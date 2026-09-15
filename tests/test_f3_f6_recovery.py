"""F3-A/F6 residual acceptance tests.

These tests exercise the real preparation and cycle-planning code with only
the Google Sheets boundary replaced by an in-memory service.
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.master_sheet_sync import (
    MASTER_HEADER,
    MASTER_STATUS_CANDIDATE,
    PROJECT_STATUS_TO_SUBMIT,
    DaemonProbeExecutor,
    VerifiedEntry,
    get_phase_c_checkpoint_path,
    load_phase_c_checkpoint,
    prepare_execution_batch,
)
from scripts.run_submission_cycle import init_cycle_state, plan_next_batch


class _Request:
    def __init__(self, callback):
        self._callback = callback

    def execute(self):
        return self._callback()


class _MemoryMasterSheet:
    """Small Sheets API boundary with controllable write/read-back failures."""

    def __init__(self, rows, *, write_failure=False, readback_failure_domains=()):
        self.rows = copy.deepcopy(rows)
        self.write_failure = write_failure
        self.readback_failure_domains = set(readback_failure_domains)
        self.writes = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def raw(self, *_args, **_kwargs):
        return [MASTER_HEADER] + [
            [row.get(column, "") for column in MASTER_HEADER] for row in self.rows
        ]

    @staticmethod
    def _cell(range_name):
        match = re.search(r"!([A-Z]+)([0-9]+)(?::[A-Z]+[0-9]+)?$", range_name)
        if not match:
            raise AssertionError(f"unexpected synthetic range: {range_name}")
        letters, row_number = match.groups()
        column_number = 0
        for letter in letters:
            column_number = column_number * 26 + ord(letter) - ord("A") + 1
        return int(row_number), column_number - 1

    def _write(self, range_name, values):
        row_number, column_number = self._cell(range_name)
        self.rows[row_number - 2][MASTER_HEADER[column_number]] = values[0][0]
        self.writes.append(range_name)

    def batchUpdate(self, spreadsheetId, body):  # noqa: N802 - Sheets API shape
        def execute():
            if self.write_failure:
                raise RuntimeError("synthetic Master write failure")
            for update in body["data"]:
                self._write(update["range"], update["values"])
            return {}

        return _Request(execute)

    def update(self, spreadsheetId, range, body, **_kwargs):  # noqa: A002 - Sheets API shape
        return _Request(lambda: self._write(range, body["values"]))

    def get(self, spreadsheetId, range):  # noqa: A002 - Sheets API shape
        row_number, _ = self._cell(range)
        row = self.rows[row_number - 2]
        domain = row.get("外链ID", "")
        if domain in self.readback_failure_domains:
            self.readback_failure_domains.remove(domain)
            raise RuntimeError(f"synthetic Master read-back failure: {domain}")

        end_match = re.search(r"![A-Z]+[0-9]+:([A-Z]+)[0-9]+$", range)
        end_column = len(MASTER_HEADER) - 1
        if end_match:
            letters = end_match.group(1)
            end_column = 0
            for letter in letters:
                end_column = end_column * 26 + ord(letter) - ord("A")
            end_column -= 1
        values = [[row.get(column, "") for column in MASTER_HEADER[: end_column + 1]]]
        return _Request(lambda: {"values": values})


class F3F6RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="backlinkos_f3_f6_")
        self.runtime_dir = self.temp_dir.name
        self.previous_runtime = os.environ.get("BACKLINKOS_RUNTIME_DIR")
        os.environ["BACKLINKOS_RUNTIME_DIR"] = self.runtime_dir
        DaemonProbeExecutor._semaphore = None
        DaemonProbeExecutor._concurrency = 0
        DaemonProbeExecutor._active_probes_count = 0

    def tearDown(self):
        DaemonProbeExecutor._semaphore = None
        DaemonProbeExecutor._concurrency = 0
        DaemonProbeExecutor._active_probes_count = 0
        if self.previous_runtime is None:
            os.environ.pop("BACKLINKOS_RUNTIME_DIR", None)
        else:
            os.environ["BACKLINKOS_RUNTIME_DIR"] = self.previous_runtime
        self.temp_dir.cleanup()

    @staticmethod
    def _rows(project_id, domains):
        project_rows = [
            {
                "项目ID": project_id,
                "外链ID": domain,
                "外链域名": domain,
                "状态": PROJECT_STATUS_TO_SUBMIT,
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
                "提交入口": f"https://{domain}/old-submit",
                "实测限制": "仅限AI工具",
                "最后验证时间": "2026-09-14T00:00:00+00:00",
                "_sheet_row_num": index + 2,
            }
            for index, domain in enumerate(domains)
        ]
        return project_rows, master_rows

    @staticmethod
    def _verified(domain, url, **_kwargs):
        return (
            VerifiedEntry(
                url=f"https://{domain}/submit",
                domain=domain,
                evidence_type="actionable_form",
                evidence_summary="synthetic validated form",
                ai_only=True,
            ),
            "synthetic verified",
        )

    def _plan(self, project_id, project_rows, master_rows, sheet, verifier):
        state = init_cycle_state(
            project_id,
            target_success=3,
            initial_candidates=[row["外链ID"] for row in project_rows],
            spreadsheet_id="synthetic-sheet",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        kwargs = {
            "state": state,
            "master_rows": master_rows,
            "project_rows": project_rows,
            "batch_ready_target": len(project_rows),
            "batch_scan_limit": len(project_rows),
            "commit_prep": True,
            "sheets_service": sheet,
            "runtime_dir": self.runtime_dir,
            "entry_verifier": verifier,
            "project_context": {"ai_powered": True, "accepts_paid": True},
            "concurrency": 1,
            "time_budget": 2,
            "fetcher": lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("unexpected synthetic network request")
            ),
        }
        return state, kwargs

    def test_master_write_failure_is_recovered_as_ready_without_rescan(self):
        self._assert_master_failure_recovers_without_rescan(write_failure=True)

    def test_master_readback_failure_is_recovered_as_ready_without_rescan(self):
        self._assert_master_failure_recovers_without_rescan(
            readback_failure_domains={"recover.example"}
        )

    def _assert_master_failure_recovers_without_rescan(
        self, *, write_failure=False, readback_failure_domains=()
    ):
        project_id = "f3-recovery"
        project_rows, master_rows = self._rows(project_id, ["recover.example"])
        sheet = _MemoryMasterSheet(
            master_rows,
            write_failure=write_failure,
            readback_failure_domains=readback_failure_domains,
        )
        state, kwargs = self._plan(
            project_id, project_rows, master_rows, sheet, self._verified
        )

        with patch(
            "scripts.run_submission_cycle.fetch_all_sheet_rows",
            side_effect=sheet.raw,
        ):
            first = plan_next_batch(**kwargs)

        self.assertEqual(first["ready_domains"], [])
        self.assertEqual(state["processed_candidate_bids"], ["recover.example"])
        self.assertEqual(
            state["pending_ready_delivery_bids"], ["recover.example"]
        )
        self.assertIsNotNone(
            load_phase_c_checkpoint(project_id, runtime_dir=self.runtime_dir),
            "写回未闭环时必须保留现场观察检查点",
        )
        self.assertEqual(project_rows[0]["尝试次数"], "0")

        sheet.write_failure = False
        verifier_calls = []

        def must_restore_from_checkpoint(*args, **kwargs):
            verifier_calls.append(args[0] if args else "unknown")
            raise AssertionError("recovery must not HTTP-probe again")

        with patch(
            "scripts.run_submission_cycle.fetch_all_sheet_rows",
            side_effect=sheet.raw,
        ):
            second = plan_next_batch(
                **{**kwargs, "entry_verifier": must_restore_from_checkpoint}
            )

        self.assertEqual(second["ready_domains"], ["recover.example"])
        self.assertEqual(verifier_calls, [])
        self.assertEqual(state["pending_ready_delivery_bids"], [])
        self.assertEqual(
            state["delivered_ready_candidate_bids"], ["recover.example"]
        )
        self.assertEqual(sheet.rows[0]["提交入口"], "https://recover.example/submit")
        self.assertIsNone(
            load_phase_c_checkpoint(project_id, runtime_dir=self.runtime_dir),
            "成功发布 Ready 后才允许清理检查点",
        )

    def test_partial_master_readback_failure_delivers_only_verified_ready_and_recovers_rest(self):
        project_id = "f3-partial-recovery"
        project_rows, master_rows = self._rows(
            project_id, ["good.example", "bad.example"]
        )
        sheet = _MemoryMasterSheet(
            master_rows, readback_failure_domains={"bad.example"}
        )
        state, kwargs = self._plan(
            project_id, project_rows, master_rows, sheet, self._verified
        )

        with patch(
            "scripts.run_submission_cycle.fetch_all_sheet_rows",
            side_effect=sheet.raw,
        ):
            first = plan_next_batch(**kwargs)

        self.assertEqual(first["ready_domains"], ["good.example"])
        self.assertEqual(state["pending_ready_delivery_bids"], ["bad.example"])
        self.assertEqual(
            set(state["processed_candidate_bids"]), {"good.example", "bad.example"}
        )
        self.assertIsNotNone(
            load_phase_c_checkpoint(project_id, runtime_dir=self.runtime_dir)
        )

        # The good item has been handed off; the next planning call is now
        # allowed to focus on the still-undelivered item.
        state["active_batch"] = None
        verifier_calls = []

        def must_restore_from_checkpoint(*args, **kwargs):
            verifier_calls.append(args[0] if args else "unknown")
            raise AssertionError("partial recovery must not HTTP-probe again")

        with patch(
            "scripts.run_submission_cycle.fetch_all_sheet_rows",
            side_effect=sheet.raw,
        ):
            second = plan_next_batch(
                **{**kwargs, "entry_verifier": must_restore_from_checkpoint}
            )

        self.assertEqual(second["ready_domains"], ["bad.example"])
        self.assertEqual(verifier_calls, [])
        self.assertEqual(state["pending_ready_delivery_bids"], [])
        self.assertEqual(
            set(state["delivered_ready_candidate_bids"]),
            {"good.example", "bad.example"},
        )
        self.assertIsNone(
            load_phase_c_checkpoint(project_id, runtime_dir=self.runtime_dir)
        )

    @staticmethod
    def _form_page(url):
        return {
            "status": 200,
            "final_url": url,
            "actionable_forms": [
                {
                    "form_type": "directory_listing",
                    "resource_fields": ["url"],
                    "submit_controls": ["Submit"],
                }
            ],
            "ai_only_signals": [],
            "submission_cta_links": [],
        }

    def test_default_verifier_collects_slow_result_and_releases_resources(self):
        project_id = "f6-slow-result"
        project_rows, master_rows = self._rows(
            project_id, ["fast.example", "slow.example"]
        )
        http_calls = []
        call_lock = threading.Lock()

        def slow_fetch(url, timeout=None):
            delay = 0.03 if "fast.example" in url else 0.35
            time.sleep(delay)
            with call_lock:
                http_calls.append(url)
            return self._form_page(url)

        started = time.monotonic()
        result = prepare_execution_batch(
            project_id=project_id,
            target_ready_count=1,
            scan_limit=2,
            project_rows=project_rows,
            master_rows=master_rows,
            project_context={"ai_powered": True, "accepts_paid": True},
            fetcher=slow_fetch,
            concurrency=2,
            time_budget=5,
            runtime_dir=self.runtime_dir,
            use_scan_ledger=False,
        )
        elapsed = time.monotonic() - started

        ready_domains = [row["verified_entry"].domain for row in result["ready_rows"]]
        checkpoint = load_phase_c_checkpoint(project_id, runtime_dir=self.runtime_dir)
        self.assertEqual(set(ready_domains), {"fast.example", "slow.example"})
        self.assertEqual(set(checkpoint["observations"]), {"fast.example", "slow.example"})
        self.assertIn("slow.example", " ".join(http_calls))
        self.assertGreaterEqual(elapsed, 0.6)
        self.assertEqual(DaemonProbeExecutor.get_active_probes_count(), 0)

    def test_process_exit_waits_for_and_reports_all_completed_results(self):
        project_root = Path(__file__).resolve().parents[1]
        child_code = r'''
import json, os, sys, tempfile, time
from scripts.master_sheet_sync import MASTER_STATUS_CANDIDATE, VerifiedEntry, prepare_execution_batch

runtime = tempfile.mkdtemp(prefix="backlinkos-child-runtime-")
project_rows = [
    {"项目ID": "child", "外链ID": d, "外链域名": d, "状态": "待提交", "尝试次数": "0"}
    for d in ("fast.example", "slow.example")
]
master_rows = [
    {"外链ID": d, "平台域名": d, "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://" + d + "/submit"}
    for d in ("fast.example", "slow.example")
]

def verifier(domain, url, **kwargs):
    time.sleep(0.03 if domain == "fast.example" else 0.8)
    return VerifiedEntry(url=url, domain=domain, evidence_type="synthetic", evidence_summary="ok", ai_only=True), "ok"

started = time.monotonic()
result = prepare_execution_batch(
    project_id="child", target_ready_count=1, scan_limit=2,
    project_rows=project_rows, master_rows=master_rows,
    entry_verifier=verifier, concurrency=2, time_budget=5,
    runtime_dir=runtime, use_scan_ledger=False,
)
print(json.dumps({"function_seconds": time.monotonic() - started, "ready": result["ready_count"]}), flush=True)
'''
        started = time.monotonic()
        completed = subprocess.run(
            [sys.executable, "-c", child_code],
            cwd=project_root,
            env={**os.environ, "PYTHONPATH": str(project_root)},
            capture_output=True,
            text=True,
            timeout=6,
            check=True,
        )
        process_elapsed = time.monotonic() - started
        payload = json.loads(completed.stdout.strip().splitlines()[-1])

        self.assertGreaterEqual(payload["ready"], 2)
        self.assertGreaterEqual(payload["function_seconds"], 0.7)
        self.assertLess(process_elapsed - payload["function_seconds"], 0.5)

    def test_formal_planner_passes_existing_min_ready_delivery_to_preparation(self):
        project_id = "f6-formal-entry"
        project_rows, master_rows = self._rows(
            project_id, ["first.example", "second.example", "third.example"]
        )
        state = init_cycle_state(
            project_id,
            target_success=3,
            initial_candidates=[row["外链ID"] for row in project_rows],
            spreadsheet_id="synthetic-sheet",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        seen = []

        def verifier(domain, url, **_kwargs):
            seen.append(domain)
            return self._verified(domain, url)

        result = plan_next_batch(
            state=state,
            master_rows=master_rows,
            project_rows=project_rows,
            batch_ready_target=3,
            batch_scan_limit=3,
            commit_prep=False,
            runtime_dir=self.runtime_dir,
            entry_verifier=verifier,
            project_context={"ai_powered": True, "accepts_paid": True},
            concurrency=1,
            time_budget=2,
            min_ready_delivery=1,
        )

        self.assertEqual(seen, ["first.example"])
        self.assertEqual(result["ready_domains"], ["first.example"])


if __name__ == "__main__":
    unittest.main()
