"""Bounded recovery coverage for previously scanned unresolved candidates."""

from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

import scripts.run_submission_cycle as cycle
from scripts.master_sheet_sync import MASTER_STATUS_CANDIDATE, PROJECT_STATUS_TO_SUBMIT
from scripts.run_submission_cycle import (
    _get_or_create_unresolved_review_round,
    _record_review_observations,
    _review_dispatch_ids,
    _select_unresolved_review_candidates,
    init_cycle_state,
)


class UnresolvedReviewSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="backlinkos_unresolved_review_")
        self.runtime_dir = self.temp_dir.name
        self.project_id = "quick-iching"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _state(self, domains=("retry.example", "other.example")):
        state = init_cycle_state(
            self.project_id,
            target_success=5,
            initial_candidates=list(domains),
            spreadsheet_id="synthetic-sheet",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        state["processed_candidate_bids"] = list(domains)
        state["scanned_candidate_bids"] = list(domains)
        return state

    def _rows(self, domains=("retry.example", "other.example"), *, status=PROJECT_STATUS_TO_SUBMIT):
        project_rows = [
            {
                "项目ID": self.project_id,
                "外链ID": domain,
                "外链域名": domain,
                "状态": status,
                "尝试次数": "0",
                "_sheet_row_num": index + 2,
            }
            for index, domain in enumerate(domains)
        ]
        master_rows = [
            {
                "外链ID": domain,
                "平台域名": domain,
                "基础状态": MASTER_STATUS_CANDIDATE,
                "提交入口": f"https://{domain}/submit",
                "_sheet_row_num": index + 2,
            }
            for index, domain in enumerate(domains)
        ]
        return master_rows, project_rows

    def test_scanned_unresolved_candidate_gets_one_fixed_review_dispatch(self):
        state = self._state()
        master_rows, project_rows = self._rows()

        review_round = _get_or_create_unresolved_review_round(
            state, master_rows, project_rows, self.runtime_dir, limit=1, time_budget=30
        )
        self.assertEqual(review_round["candidate_ids"], ["retry.example"])
        self.assertEqual(_review_dispatch_ids(review_round, limit=1), ["retry.example"])
        self.assertEqual(_review_dispatch_ids(review_round, limit=1), [])

    def test_restart_without_saved_observation_becomes_unknown_not_repeat_dispatch(self):
        state = self._state()
        master_rows, project_rows = self._rows()
        review_round = _get_or_create_unresolved_review_round(
            state, master_rows, project_rows, self.runtime_dir, limit=2, time_budget=30
        )
        self.assertEqual(_review_dispatch_ids(review_round, limit=1), ["retry.example"])

        resumed = _get_or_create_unresolved_review_round(
            state, master_rows, project_rows, self.runtime_dir, limit=2, time_budget=30
        )
        self.assertEqual(resumed["dispatches"]["retry.example"]["status"], "unknown_recovery")
        self.assertEqual(_review_dispatch_ids(resumed, limit=2), ["other.example"])
        self.assertEqual(resumed["unknown_recovery_ids"], ["retry.example"])

    def test_terminal_and_human_project_states_are_not_review_candidates(self):
        state = self._state(("terminal.example",))
        master_rows, project_rows = self._rows(("terminal.example",), status="处理中")
        self.assertEqual(
            _select_unresolved_review_candidates(state, master_rows, project_rows, self.runtime_dir, limit=5),
            [],
        )
        project_rows[0]["状态"] = "需人工"
        self.assertEqual(
            _select_unresolved_review_candidates(state, master_rows, project_rows, self.runtime_dir, limit=5),
            [],
        )

    def test_observation_is_persisted_once_and_never_requires_a_second_dispatch(self):
        state = self._state(("observed.example",))
        master_rows, project_rows = self._rows(("observed.example",))
        review_round = _get_or_create_unresolved_review_round(
            state, master_rows, project_rows, self.runtime_dir, limit=1, time_budget=30
        )
        dispatched = _review_dispatch_ids(review_round, limit=1)
        _record_review_observations(
            review_round,
            dispatched,
            {
                "scanned_backlink_ids": ["observed.example"],
                "observations": {
                    "observed.example": {
                        "disposition": "probe_timeout",
                        "reason": "site budget exhausted",
                        "observed_at": "2026-09-15T00:00:00+00:00",
                    }
                },
            },
        )
        self.assertEqual(review_round["dispatches"]["observed.example"]["status"], "observed")
        self.assertEqual(review_round["observations"]["observed.example"]["status"], "unresolved")
        self.assertEqual(_review_dispatch_ids(review_round, limit=1), [])

    def test_formal_start_defers_new_review_until_next_explicit_run(self):
        state = init_cycle_state(
            self.project_id,
            target_success=1,
            initial_candidates=["first.example", "second.example"],
            spreadsheet_id="synthetic-sheet",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        calls = []

        def complete_normal_scan(**kwargs):
            calls.append(kwargs)
            kwargs["state"]["scanned_candidate_bids"] = list(kwargs["state"]["snapshot_candidate_bids"])
            kwargs["state"]["processed_candidate_bids"] = list(kwargs["state"]["snapshot_candidate_bids"])
            return {"action": "NEXT", "ready_items": [], "batch_id": "normal-batch"}

        with (
            patch.object(cycle, "load_cycle_state", return_value=state),
            patch.object(cycle, "get_sheets_service", return_value=object()),
            patch.object(cycle, "recover_pending_master_mutations"),
            patch.object(cycle, "fetch_all_sheet_rows", side_effect=[[], []]),
            patch.object(cycle, "resolve_project_context", return_value={}),
            patch.object(cycle, "plan_next_batch", side_effect=complete_normal_scan),
            patch.object(cycle, "print_cycle_summary", return_value=True),
        ):
            exit_code = cycle.main(["start", "--project-id", self.project_id])

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(state.get("unresolved_review_rounds"), [])


if __name__ == "__main__":
    unittest.main()
