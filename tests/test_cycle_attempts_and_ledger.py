import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from scripts.master_sheet_sync import (
    MASTER_HEADER,
    PROJECT_HEADER,
    canonical_domain,
    discover_and_verify_entry,
    extract_negated_entries_from_row,
    get_persisted_project_incompatibility,
    prepare_execution_batch,
    submission_entry_policy_guard,
    verify_submission_entry,
)
from scripts.run_submission_cycle import (
    init_cycle_state,
    plan_next_batch,
    record_task_outcome,
    start_task_attempt,
)


class CycleAttemptsAndLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.runtime_dir = Path(self.temp_dir) / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.project_id = "test-proj"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_start_attempt_increments_attempts_and_sets_in_progress(self):
        """测试正常启动时尝试次数严格 +1，状态变为处理中。"""
        project_rows = [
            {"项目ID": self.project_id, "外链ID": "site-a.com", "外链域名": "site-a.com", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 2},
        ]
        master_rows = [
            {"外链ID": "site-a.com", "平台域名": "site-a.com", "提交入口": "https://site-a.com/submit", "基础状态": "候选", "基础排除原因": "", "_sheet_row_num": 2}
        ]
        state = init_cycle_state(
            project_id=self.project_id,
            target_success=10,
            initial_candidates=["site-a.com"],
            spreadsheet_id="test_sheet",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=str(self.runtime_dir),
        )
        state["active_batch"] = {
            "ready_domains": ["site-a.com"],
            "ready_items": [{"domain": "site-a.com", "submission_url": "https://site-a.com/submit"}],
        }

        res = start_task_attempt(
            state=state,
            backlink_id="site-a.com",
            is_resume_attempt=False,
            master_rows=master_rows,
            project_rows=project_rows,
            sheets_service=None,
            commit=False,
            runtime_dir=str(self.runtime_dir),
        )

        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "处理中")
        self.assertEqual(res["attempt_count"], 1)
        self.assertEqual(project_rows[0]["尝试次数"], "1")
        self.assertEqual(project_rows[0]["状态"], "处理中")
        self.assertEqual(state["active_attempt"]["attempt_count"], 1)

    def test_start_attempt_resume_does_not_increment_attempts(self):
        """测试断点恢复时尝试次数保持不变。"""
        project_rows = [
            {"项目ID": self.project_id, "外链ID": "site-b.com", "外链域名": "site-b.com", "状态": "需人工", "尝试次数": "1", "_sheet_row_num": 2},
        ]
        master_rows = [
            {"外链ID": "site-b.com", "平台域名": "site-b.com", "提交入口": "https://site-b.com/submit", "基础状态": "候选", "基础排除原因": "", "_sheet_row_num": 2}
        ]
        state = init_cycle_state(
            project_id=self.project_id,
            target_success=10,
            initial_candidates=["site-b.com"],
            spreadsheet_id="test_sheet",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=str(self.runtime_dir),
        )

        res = start_task_attempt(
            state=state,
            backlink_id="site-b.com",
            is_resume_attempt=True,
            master_rows=master_rows,
            project_rows=project_rows,
            sheets_service=None,
            commit=False,
            runtime_dir=str(self.runtime_dir),
        )

        self.assertTrue(res["ok"])
        self.assertEqual(res["attempt_count"], 1)
        self.assertEqual(project_rows[0]["尝试次数"], "1")
        self.assertEqual(project_rows[0]["状态"], "处理中")

    def test_record_outcome_writes_and_verifies_attempts(self):
        """测试 record_task_outcome 写回并核验尝试次数。"""
        project_rows = [
            {"项目ID": self.project_id, "外链ID": "site-c.com", "外链域名": "site-c.com", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 2},
        ]
        master_rows = [
            {"外链ID": "site-c.com", "平台域名": "site-c.com", "提交入口": "https://site-c.com/submit", "基础状态": "候选", "基础排除原因": "", "_sheet_row_num": 2}
        ]
        state = init_cycle_state(
            project_id=self.project_id,
            target_success=10,
            initial_candidates=["site-c.com"],
            spreadsheet_id="test_sheet",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=str(self.runtime_dir),
        )
        state["active_batch"] = {
            "ready_domains": ["site-c.com"],
            "ready_items": [{"domain": "site-c.com", "submission_url": "https://site-c.com/submit"}],
        }

        # Mock Sheets Service
        mock_service = MagicMock()
        # 1) start_task_attempt: 写前读取 (状态待提交, 次数0), 写后回读 (状态处理中, 次数1)
        # 2) record_task_outcome: 写前读取 (状态处理中, 次数1), 写后回读 (状态审核中, 次数1)
        mock_service.spreadsheets().values().get().execute.side_effect = [
            {"values": [[self.project_id, "site-c.com", "site-c.com", "待提交", "0", "", "", "", "", ""]]},
            {"values": [[self.project_id, "site-c.com", "site-c.com", "处理中", "1", "2026-09-10T00:00:00Z", "", "", "", ""]]},
            {"values": [[self.project_id, "site-c.com", "site-c.com", "处理中", "1", "2026-09-10T00:00:00Z", "", "", "", ""]]},
            {"values": [[self.project_id, "site-c.com", "site-c.com", "审核中", "1", "2026-09-10T00:00:00Z", "", "", "提交成功等待审核", "提交成功回执"]]},
        ]

        # 严格执行约束 1：必须先启动尝试确立凭据
        start_res = start_task_attempt(
            state=state,
            backlink_id="site-c.com",
            is_resume_attempt=False,
            master_rows=master_rows,
            project_rows=project_rows,
            sheets_service=mock_service,
            commit=True,
            runtime_dir=str(self.runtime_dir),
        )
        self.assertTrue(start_res["ok"])
        self.assertEqual(start_res["attempt_count"], 1)

        res = record_task_outcome(
            state=state,
            backlink_id="site-c.com",
            status="审核中",
            reason="提交成功等待审核",
            evidence="提交成功回执",
            result_url="",
            project_rows=project_rows,
            sheets_service=mock_service,
            commit=True,
            runtime_dir=str(self.runtime_dir),
        )

        self.assertTrue(res["ok"])
        self.assertEqual(res["newly_succeeded_count"], 1)
        self.assertEqual(project_rows[0]["尝试次数"], "1")
        # 验证 batchUpdate 传参中包含了尝试次数
        calls = mock_service.spreadsheets().values().batchUpdate.call_args_list
        self.assertTrue(len(calls) >= 2)
        outcome_call = calls[-1]
        body = outcome_call[1]["body"]
        data = body["data"]
        attempt_entry = next((d for d in data if d["range"] == "'外链管理'!E2"), None)
        self.assertIsNotNone(attempt_entry)
        self.assertEqual(attempt_entry["values"], [["1"]])

    def test_negated_entry_guard_blocks_negated_urls(self):
        """测试否定入口被 Policy Guard 拦截。"""
        negated = {"https://xrp.army/news"}
        allowed, reason = submission_entry_policy_guard("https://xrp.army/news/", domain="xrp.army", negated_entries=negated)
        self.assertFalse(allowed)
        self.assertIn("命中已否定入口", reason)

        # 正常 URL 不受影响
        allowed_ok, _ = submission_entry_policy_guard("https://xrp.army/submit", domain="xrp.army", negated_entries=negated)
        self.assertTrue(allowed_ok)

    def test_extract_negated_entries_from_row(self):
        mrow = {
            "平台备注": "否定入口: https://xrp.army/news/ (非公开通道)",
            "基础排除原因": "",
        }
        negs = extract_negated_entries_from_row(mrow)
        self.assertIn("https://xrp.army/news", negs)

    def test_site_timeout_budget_strictly_terminates(self):
        """测试整站探测总耗时预算生效，超时后立即退出并留存原因。"""
        import time

        def slow_fetch(url, timeout=5.0):
            time.sleep(0.1)
            return {"status": 0, "error": "slow"}

        t0 = time.monotonic()
        entry, reason = discover_and_verify_entry(
            domain="slow-site.com",
            fetcher=slow_fetch,
            max_probes=10,
            site_timeout_budget=0.15,  # 极短总预算
        )
        elapsed = time.monotonic() - t0
        self.assertIsNone(entry)
        self.assertIn("超时", reason)
        self.assertLess(elapsed, 0.25, f"整站探测超时预算耗时超标: 实际 {elapsed:.3f}s，预期 < 0.25s")

    def test_discover_entry_terminates_blocking_fetcher_within_wall_clock(self):
        """测试即使底层网络库或fetcher挂起阻塞2秒，整站预算也能在0.25秒内绝对强杀截断。"""
        import time

        def blocking_fetch(url, **kwargs):
            # 模拟底层网络卡死的慢请求或分块挂起
            time.sleep(2.0)
            return {"status": 200, "html": "ok"}

        t0 = time.monotonic()
        entry, reason = discover_and_verify_entry(
            domain="blocking-site.com",
            fetcher=blocking_fetch,
            max_probes=5,
            site_timeout_budget=0.15,
        )
        elapsed = time.monotonic() - t0
        self.assertIsNone(entry)
        self.assertIn("超时", reason)
        self.assertLess(elapsed, 0.25, f"阻塞抓取强杀超时超标: 实际 {elapsed:.3f}s，预期 < 0.25s")

    def test_persisted_ai_only_incompatibility_preserves_unknown_attributes(self):
        """测试兼容性判断严格遵守：仅当 ai_powered is False 明确为非 AI 项目时才排除，未知时一律保留。"""
        mrow = {
            "实测限制": "仅限AI工具",
            "平台备注": "",
            "基础排除原因": "",
        }
        # 1. 明确为非 AI 项目 -> 排除
        incomp, _, _ = get_persisted_project_incompatibility(mrow, {"ai_powered": False})
        self.assertTrue(incomp)

        # 2. 属性未知 (None) -> 绝不主观排除，保留待核实
        incomp_unknown, _, _ = get_persisted_project_incompatibility(mrow, {"ai_powered": None})
        self.assertFalse(incomp_unknown)

        # 3. AI 项目 -> 不排除
        incomp_ai, _, _ = get_persisted_project_incompatibility(mrow, {"ai_powered": True})
        self.assertFalse(incomp_ai)

    def test_start_attempt_empty_ready_rejected(self):
        """测试当前批次无 Ready 或不在 Ready 清单中时被严格拒绝 (F1 守卫)。"""
        project_rows = [
            {"项目ID": self.project_id, "外链ID": "site-x.com", "外链域名": "site-x.com", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 2},
        ]
        state = init_cycle_state(
            project_id=self.project_id,
            target_success=10,
            initial_candidates=["site-x.com"],
            spreadsheet_id="test_sheet",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=str(self.runtime_dir),
        )
        # 情况 1: active_batch 为 None / 空 ready_domains
        state["active_batch"] = {"ready_domains": []}
        with self.assertRaises(ValueError) as ctx:
            start_task_attempt(
                state=state,
                backlink_id="site-x.com",
                is_resume_attempt=False,
                project_rows=project_rows,
                sheets_service=None,
                commit=False,
                runtime_dir=str(self.runtime_dir),
            )
        self.assertIn("不在当前批次 Ready 清单中", str(ctx.exception))

        # 情况 2: active_batch 有其他域名，但没有 site-x.com
        state["active_batch"] = {"ready_domains": ["other.com"]}
        with self.assertRaises(ValueError) as ctx2:
            start_task_attempt(
                state=state,
                backlink_id="site-x.com",
                is_resume_attempt=False,
                project_rows=project_rows,
                sheets_service=None,
                commit=False,
                runtime_dir=str(self.runtime_dir),
            )
        self.assertIn("不在当前批次 Ready 清单中", str(ctx2.exception))

    def test_record_outcome_without_attempt_fails_for_success(self):
        """测试未经 start-attempt 确立凭据且原尝试次数为 0 时，记录审核中直接抛错 (杜绝保底赋 1)。"""
        project_rows = [
            {"项目ID": self.project_id, "外链ID": "site-unstarted.com", "外链域名": "site-unstarted.com", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 2},
        ]
        state = init_cycle_state(
            project_id=self.project_id,
            target_success=10,
            initial_candidates=["site-unstarted.com"],
            spreadsheet_id="test_sheet",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=str(self.runtime_dir),
        )
        # 未启动 start_task_attempt，直接记录审核中
        with self.assertRaises(RuntimeError) as ctx:
            record_task_outcome(
                state=state,
                backlink_id="site-unstarted.com",
                status="审核中",
                reason="凭空提交",
                evidence="无凭据",
                project_rows=project_rows,
                sheets_service=None,
                commit=False,
                runtime_dir=str(self.runtime_dir),
            )
        self.assertIn("严禁无凭据记录为成功/审核中", str(ctx.exception))

    def test_record_outcome_without_attempt_preserves_zero_for_excluded(self):
        """测试未经启动尝试的排除/不适用条目保持尝试次数为 0，不被保底赋 1。"""
        project_rows = [
            {"项目ID": self.project_id, "外链ID": "site-excluded.com", "外链域名": "site-excluded.com", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 2},
        ]
        state = init_cycle_state(
            project_id=self.project_id,
            target_success=10,
            initial_candidates=["site-excluded.com"],
            spreadsheet_id="test_sheet",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=str(self.runtime_dir),
        )
        res = record_task_outcome(
            state=state,
            backlink_id="site-excluded.com",
            status="不适用",
            reason="非AI项目排除",
            evidence="",
            project_rows=project_rows,
            sheets_service=None,
            commit=False,
            runtime_dir=str(self.runtime_dir),
        )
        self.assertEqual(res["attempts"], 0)
        self.assertEqual(project_rows[0]["尝试次数"], "0")

    def test_load_scan_ledger_facts_handles_all_timestamp_formats_and_cooldown(self):
        """测试 load_scan_ledger_facts 兼容所有时间戳格式并在冷却期内提取，超期丢弃 (F4)。"""
        import time
        from scripts.master_sheet_sync import load_scan_ledger_facts

        now = time.time()
        recent_ts_float = now - 3600  # 1小时前
        recent_iso = "2026-09-10T10:00:00+00:00"
        expired_ts_float = now - 8 * 86400  # 8天前 (超期)

        ledger_file = self.runtime_dir / "cycles" / self.project_id / "scan_ledger.jsonl"
        ledger_file.parent.mkdir(parents=True, exist_ok=True)

        records = [
            {"domain": "site-float.com", "scanned_timestamp": recent_ts_float, "disposition": "no_entry_found", "reason": "无表单"},
            {"domain": "site-iso.com", "timestamp": recent_iso, "disposition": "negated_entry", "reason": "已否定入口"},
            {"domain": "site-scanned-at.com", "scanned_at": recent_iso, "disposition": "unverified_no_form", "reason": "无提交按钮"},
            {"domain": "site-expired.com", "scanned_timestamp": expired_ts_float, "disposition": "no_entry_found", "reason": "过期事实"},
        ]
        with ledger_file.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        facts = load_scan_ledger_facts(
            project_id=self.project_id,
            runtime_dir=str(self.runtime_dir),
            cooldown_seconds=7 * 86400,
        )
        self.assertIn("site-float.com", facts)
        self.assertIn("site-iso.com", facts)
        self.assertIn("site-scanned-at.com", facts)
        self.assertNotIn("site-expired.com", facts)  # 超期被正确过滤

    def test_prepare_batch_reuses_ledger_facts_and_never_skips_timeout(self):
        """测试 prepare_execution_batch 冷却期复用无入口/否定事实，且超时项绝不被跳过 (F4)。"""
        import time
        now = time.time()
        ledger_file = self.runtime_dir / "cycles" / self.project_id / "scan_ledger.jsonl"
        ledger_file.parent.mkdir(parents=True, exist_ok=True)

        # 写入两条记录：一条已否定（应复用跳过），一条超时（绝不能复用跳过，必须保留重新探测）
        records = [
            {"domain": "reused-negated.com", "scanned_timestamp": now - 3600, "disposition": "negated_entry", "reason": "已否定入口"},
            {"domain": "timeout-retry.com", "scanned_timestamp": now - 3600, "disposition": "probe_timeout", "reason": "超时"},
        ]
        with ledger_file.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

        p_rows = [
            {"项目ID": self.project_id, "外链ID": "reused-negated.com", "外链域名": "reused-negated.com", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 2},
            {"项目ID": self.project_id, "外链ID": "timeout-retry.com", "外链域名": "timeout-retry.com", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 3},
        ]
        m_rows = [
            {"外链ID": "reused-negated.com", "平台域名": "reused-negated.com", "提交入口": "", "基础状态": "候选", "基础排除原因": "", "实测限制": "", "_sheet_row_num": 2},
            {"外链ID": "timeout-retry.com", "平台域名": "timeout-retry.com", "提交入口": "", "基础状态": "候选", "基础排除原因": "", "实测限制": "", "_sheet_row_num": 3},
        ]

        probed_domains = []
        def mock_verifier(dom, url):
            probed_domains.append(dom)
            return None, "现场核验无入口"

        def mock_finder(dom, **kwargs):
            probed_domains.append(dom)
            return None, "现场探测无入口"

        res = prepare_execution_batch(
            project_id=self.project_id,
            target_ready_count=5,
            scan_limit=10,
            project_rows=p_rows,
            master_rows=m_rows,
            project_context={"ai_powered": True},
            entry_verifier=mock_verifier,
            entry_finder=mock_finder,
            runtime_dir=str(self.runtime_dir),
            use_scan_ledger=True,
        )

        # reused-negated.com 被账本事实复用，没有触发 entry_verifier / entry_finder 探测
        # timeout-retry.com 超时项绝不复用跳过，必须实际执行探测！
        self.assertNotIn("reused-negated.com", probed_domains)
        self.assertIn("timeout-retry.com", probed_domains)

    def test_pending_master_mutations_persistence_and_recovery(self):
        """测试 Master 表写回失败时落地 pending_master_mutations.json，并能自动恢复 (F4)。"""
        from scripts.run_submission_cycle import (
            load_pending_master_mutations,
            recover_pending_master_mutations,
            save_pending_master_mutations,
        )

        test_mutations = [
            {
                "domain": "ai-tool.com",
                "row_num": 10,
                "mutation_type": "limits_and_vtime",
                "cell_range": "'外链总表'!A10:M10",
                "expected_limits": "仅限AI工具",
                "expected_vtime": "2026-09-10T12:00:00Z",
            }
        ]

        # 1. 保存
        p_file = save_pending_master_mutations(self.project_id, test_mutations, str(self.runtime_dir))
        self.assertTrue(p_file.exists())

        # 2. 读取
        loaded = load_pending_master_mutations(self.project_id, str(self.runtime_dir))
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["domain"], "ai-tool.com")

        # 3. 恢复 (Mock Sheets 成功执行 batchUpdate，并满足写前身份核验与写后全字段严格回读)
        def mock_get(spreadsheetId, range):
            mock_req = MagicMock()
            if "A10:B10" in range:
                mock_req.execute.return_value = {"values": [["ai-tool.com", "ai-tool.com"]]}
            elif "A10:M10" in range:
                row = [""] * 13
                row[0] = "ai-tool.com"
                row[10] = "仅限AI工具"
                row[12] = "2026-09-10T12:00:00Z"
                mock_req.execute.return_value = {"values": [row]}
            else:
                mock_req.execute.return_value = {"values": []}
            return mock_req

        mock_sheets = MagicMock()
        mock_sheets.spreadsheets().values().get.side_effect = mock_get
        rem = recover_pending_master_mutations(
            sheets_service=mock_sheets,
            spreadsheet_id="test_sheet",
            master_sheet_name="外链总表",
            project_id=self.project_id,
            runtime_dir=str(self.runtime_dir),
        )
        self.assertEqual(len(rem), 0)
        # 成功恢复后，文件被清空/删除
        self.assertFalse(p_file.exists())

    def test_continuous_timeouts_prevent_thread_accumulation(self):
        """测试连续多次超时任务后，线程数受到严格上界约束，不会随任务数无限堆积 (F5)。"""
        import time
        import threading
        from scripts.master_sheet_sync import DaemonProbeExecutor

        def slow_blocking_call():
            time.sleep(0.5)
            return "delayed"

        # 连续触发 8 次超时任务 (每个任务限时 0.02s)
        results = []
        for _ in range(8):
            succ, res, is_to = DaemonProbeExecutor.execute(
                func=slow_blocking_call,
                timeout=0.02,
            )
            results.append(is_to)

        # 验证所有调用均被识别为超时，且后台活跃线程数有界
        self.assertTrue(all(results))
        active_cnt = threading.active_count()
        self.assertLessEqual(active_cnt, 10, f"活跃线程数异常堆积: {active_cnt}")

    def test_late_arriving_response_never_pollutes_state(self):
        """测试后台迟到响应被任务令牌取消机制安全丢弃，绝不触发污染 (F5)。"""
        import time
        from scripts.master_sheet_sync import DaemonProbeExecutor

        def delayed_writer():
            time.sleep(0.08)
            return {"status": 200, "leaked": True}

        succ, res, is_to = DaemonProbeExecutor.execute(
            func=delayed_writer,
            timeout=0.02,
        )
        self.assertTrue(is_to)
        self.assertFalse(succ)
        self.assertIn("TIMEOUT", str(res))

    def test_subprocess_clean_exit_with_hanging_fetcher(self):
        """测试真实子进程在底层网络挂起时能够瞬间干净退出，不被线程 join 拖住 (F5)。"""
        import subprocess
        import sys
        import time

        code = """
import time
from scripts.master_sheet_sync import discover_and_verify_entry

def hanging_fetch(url, **kwargs):
    time.sleep(5.0)  # 模拟网络卡死 5 秒
    return {"status": 200}

entry, reason = discover_and_verify_entry(
    domain="hanging-test.com",
    fetcher=hanging_fetch,
    max_probes=1,
    site_timeout_budget=0.15,
)
assert entry is None
assert "超时" in reason
"""
        t0 = time.monotonic()
        p = subprocess.run(
            [sys.executable, "-c", code],
            cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
            capture_output=True,
            text=True,
            timeout=2.0,  # 2秒硬性保护
        )
        elapsed = time.monotonic() - t0
        self.assertEqual(p.returncode, 0, f"子进程执行失败: {p.stderr}")
        self.assertLess(elapsed, 0.8, f"子进程未能干净退出，被后台线程拖住: 耗时 {elapsed:.2f}s (预期 < 0.8s)")


if __name__ == "__main__":
    unittest.main()
