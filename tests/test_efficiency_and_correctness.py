"""BacklinkOS 小范围效率改进与正确性验证测试集 (针对 NO-GO 独立复核项 F1–F7 的全量回归与返修验证)。

覆盖：
1. F1 [P1]: 正式 start 入口与断点恢复调用链无 NameError (time)，平滑执行；
2. F2 [P1]: 跨批次与配置变更时的信号量防御：底层在途慢请求未退出时拒绝改变并发度，活跃请求数严格受限；
3. F3 [P1]: 检查点恢复观察结果严格执行正式 Ready 门禁（项目行终态拦截、否定入口拦截、项目不兼容拦截、断网下无损重建 Ready、过期检查点失效）；
4. F4 [P1]: 探测账本单一写入者真实落盘与双重中断窗口测试（未落盘不假标、落盘未标不重复追加，原时间戳复用）；
5. F5 [P1]: CTA 子页面阻塞透传与 HALT 终止前完整保留同批已产生 Ready (非零退出码 1，保留中断原因)；
6. F6 [P2]: 默认探测路径预算透传与小批 Ready 提前交付无损 (不截断丢弃超出 min_ready_delivery 的已就绪项)；
7. F7 [P2]: 业务处置账目与四原子互斥子项严格守恒对账测试；
8. 资源与性能基准测量：8 候选样本下并发 1 vs 2 vs 4 的加速比 (>=2.0x)、高频线程采样峰值受限与 RSS 测量。
"""

from __future__ import annotations

import copy
import datetime
import json
import os
import resource
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from scripts.master_sheet_sync import (
    MASTER_HEADER,
    MASTER_STATUS_CANDIDATE,
    PROJECT_HEADER,
    PROJECT_STATUS_TO_SUBMIT,
    DaemonProbeExecutor,
    VerifiedEntry,
    append_scan_ledger_entry_safely,
    canonical_domain,
    discover_and_verify_entry,
    load_phase_c_checkpoint,
    make_scan_ledger_entry,
    prepare_execution_batch,
    save_phase_c_checkpoint,
    verify_submission_entry,
)
from scripts.run_submission_cycle import (
    init_cycle_state,
    load_cycle_state,
    main as cycle_main,
    plan_next_batch,
    print_cycle_summary,
    record_cycle_interruption,
    save_cycle_state,
)

PROJECT_STATUS_IN_PROGRESS = "处理中"
PROJECT_STATUS_HUMAN = "需人工"
PROJECT_STATUS_SUBMITTED = "已提交"


class TestEfficiencyAndCorrectness(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="backlinkos_eff_f1_f7_")
        self.runtime_dir = os.path.join(self.tmp_dir, "runtime")
        os.makedirs(self.runtime_dir, exist_ok=True)
        self.orig_runtime_env = os.environ.get("BACKLINKOS_RUNTIME_DIR")
        os.environ["BACKLINKOS_RUNTIME_DIR"] = self.runtime_dir
        DaemonProbeExecutor._semaphore = None
        DaemonProbeExecutor._concurrency = 0
        DaemonProbeExecutor._active_probes_count = 0

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        if self.orig_runtime_env is not None:
            os.environ["BACKLINKOS_RUNTIME_DIR"] = self.orig_runtime_env
        else:
            os.environ.pop("BACKLINKOS_RUNTIME_DIR", None)
        DaemonProbeExecutor._semaphore = None
        DaemonProbeExecutor._concurrency = 0
        DaemonProbeExecutor._active_probes_count = 0

    def test_f1_start_and_resume_cli_no_name_error(self):
        """F1: 正式 start 入口及恢复循环调用链无 NameError (time)，平滑执行。"""
        p_raw = [
            PROJECT_HEADER,
            ["quick-iching", "site1.com", "site1.com", "待提交", "0", "", "", "", "", ""],
            ["quick-iching", "site2.com", "site2.com", "待提交", "0", "", "", "", "", ""],
        ]
        m_raw = [
            MASTER_HEADER,
            ["site1.com", "site1.com", MASTER_STATUS_CANDIDATE, "https://site1.com/submit", "免费", "否", "", "", "", "", ""],
            ["site2.com", "site2.com", MASTER_STATUS_CANDIDATE, "https://site2.com/submit", "免费", "否", "", "", "", "", ""],
        ]

        def mock_fetch_rows(service, sheet_id, sheet_name):
            if "管理" in sheet_name or "Project" in sheet_name:
                return copy.deepcopy(p_raw)
            return copy.deepcopy(m_raw)

        with patch("scripts.run_submission_cycle.get_sheets_service", return_value=MagicMock()),              patch("scripts.run_submission_cycle.fetch_all_sheet_rows", side_effect=mock_fetch_rows):

            exit_code = cycle_main([
                "--project-id", "quick-iching",
                "--target-success", "2",
                "--batch-ready-target", "1",
                "--batch-scan-limit", "2",
                "--time-budget", "10",
                "--dry-run",
            ])
            self.assertEqual(exit_code, 0, "CLI 启动并规划批次应当正常返回 0")

            state = load_cycle_state("quick-iching", runtime_dir=self.runtime_dir)
            self.assertIsNotNone(state)
            self.assertIn("site1.com", state["snapshot_candidate_bids"])

            exit_code_resume = cycle_main([
                "--project-id", "quick-iching",
                "--target-success", "2",
                "--time-budget", "10",
                "--dry-run",
            ])
            self.assertEqual(exit_code_resume, 0, "断点恢复调用链应当平滑返回 0")

    def test_f2_concurrency_config_change_and_active_quota_safety(self):
        """F2: 底层在途慢请求未退出时，拒绝改变并发度重建信号量；多批连续调用活跃请求数绝对不超过上限。"""
        ok_init = DaemonProbeExecutor.set_concurrency(2)
        self.assertTrue(ok_init)
        self.assertEqual(DaemonProbeExecutor.get_concurrency(), 2)

        started_event = threading.Event()
        finish_event = threading.Event()

        def slow_func():
            started_event.set()
            finish_event.wait(timeout=2.0)
            return "ok"

        th = threading.Thread(
            target=lambda: DaemonProbeExecutor.execute_bounded(slow_func, timeout=2.0),
            daemon=True
        )
        th.start()
        started_event.wait(timeout=1.0)

        self.assertEqual(DaemonProbeExecutor.get_active_probes_count(), 1)

        rejected_expand = DaemonProbeExecutor.set_concurrency(4)
        self.assertFalse(rejected_expand, "有在途慢请求时，严禁通过改变并发度重建信号量获得额外额度")
        self.assertEqual(DaemonProbeExecutor.get_concurrency(), 2)

        rejected_shrink = DaemonProbeExecutor.set_concurrency(1)
        self.assertFalse(rejected_shrink, "有在途慢请求时，严禁改变并发度")
        self.assertEqual(DaemonProbeExecutor.get_concurrency(), 2)

        finish_event.set()
        th.join(timeout=1.0)
        self.assertEqual(DaemonProbeExecutor.get_active_probes_count(), 0)

        high_watermark_active = 0
        lock = threading.Lock()

        def slow_probing_verifier(domain, entry_url, **kwargs):
            nonlocal high_watermark_active
            with lock:
                cur = DaemonProbeExecutor.get_active_probes_count()
                if cur > high_watermark_active:
                    high_watermark_active = cur
            time.sleep(0.15)
            return None, "超时"

        p_rows = [{
            "项目ID": "test_f2",
            "外链ID": f"slow{i}.com",
            "外链域名": f"slow{i}.com",
            "状态": PROJECT_STATUS_TO_SUBMIT,
            "尝试次数": "0",
        } for i in range(1, 7)]
        m_rows = [{
            "外链ID": f"slow{i}.com",
            "平台域名": f"slow{i}.com",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "提交入口": f"https://slow{i}.com/submit",
        } for i in range(1, 7)]

        for batch_idx in range(3):
            sub_p = p_rows[batch_idx * 2 : (batch_idx + 1) * 2]
            sub_m = m_rows[batch_idx * 2 : (batch_idx + 1) * 2]
            prepare_execution_batch(
                project_id="test_f2",
                target_ready_count=1,
                scan_limit=2,
                project_rows=sub_p,
                master_rows=sub_m,
                entry_verifier=slow_probing_verifier,
                concurrency=2,
                runtime_dir=self.runtime_dir,
                time_budget=0.1,
            )

        self.assertLessEqual(high_watermark_active, 2, f"活跃并发数绝对不能超过 2，实际最高为 {high_watermark_active}")

    def test_f3_checkpoint_recovery_strict_gates_and_no_rescan(self):
        """F3: 检查点驱动恢复观察时，严格执行项目行终态、否定入口、兼容性门禁；有效项断网下无损重建 Ready。"""
        checkpoint_data = {
            "project_id": "test_f3",
            "batch_id": "batch_f3_01",
            "project_context": {"ai_powered": False},
            "created_at": time.time(),
            "observations": {
                "submitted-site.com": {
                    "stage": "probed_pending_verify",
                    "domain": "submitted-site.com",
                    "verified_entry": {"url": "https://submitted-site.com/submit", "domain": "submitted-site.com"},
                    "verify_reason": "现场核验通过",
                },
                "denied-site.com": {
                    "stage": "probed_pending_verify",
                    "domain": "denied-site.com",
                    "verified_entry": {"url": "https://denied-site.com/submit", "domain": "denied-site.com"},
                    "verify_reason": "现场核验通过",
                },
                "incomp-site.com": {
                    "stage": "probed_pending_verify",
                    "domain": "incomp-site.com",
                    "verified_entry": {"url": "https://incomp-site.com/submit", "domain": "incomp-site.com"},
                    "verify_reason": "现场核验通过",
                },
                "valid-site.com": {
                    "stage": "probed_pending_verify",
                    "domain": "valid-site.com",
                    "verified_entry": {"url": "https://valid-site.com/submit", "domain": "valid-site.com"},
                    "verify_reason": "现场核验通过",
                },
            },
            "written_ledger_bids": [],
        }
        save_phase_c_checkpoint("test_f3", checkpoint_data, runtime_dir=self.runtime_dir)

        p_rows = [
            {"项目ID": "test_f3", "外链ID": "submitted-site.com", "外链域名": "submitted-site.com", "状态": PROJECT_STATUS_SUBMITTED, "尝试次数": "1"},
            {"项目ID": "test_f3", "外链ID": "denied-site.com", "外链域名": "denied-site.com", "状态": PROJECT_STATUS_TO_SUBMIT, "尝试次数": "0"},
            {"项目ID": "test_f3", "外链ID": "incomp-site.com", "外链域名": "incomp-site.com", "状态": PROJECT_STATUS_TO_SUBMIT, "尝试次数": "0"},
            {"项目ID": "test_f3", "外链ID": "valid-site.com", "外链域名": "valid-site.com", "状态": PROJECT_STATUS_TO_SUBMIT, "尝试次数": "0"},
        ]

        m_rows = [
            {"外链ID": "submitted-site.com", "平台域名": "submitted-site.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://submitted-site.com/submit"},
            {"外链ID": "denied-site.com", "平台域名": "denied-site.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://denied-site.com/submit", "否定入口": "https://denied-site.com/submit"},
            {"外链ID": "incomp-site.com", "平台域名": "incomp-site.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://incomp-site.com/submit", "实测限制": "AI工具专收"},
            {"外链ID": "valid-site.com", "平台域名": "valid-site.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://valid-site.com/submit"},
        ]

        def broken_network_fetcher(url, **kwargs):
            raise ConnectionError("断网中，严禁发起盲探！")

        res = prepare_execution_batch(
            project_id="test_f3",
            target_ready_count=5,
            scan_limit=5,
            project_rows=p_rows,
            master_rows=m_rows,
            fetcher=broken_network_fetcher,
            project_context={"ai_powered": False},
            runtime_dir=self.runtime_dir,
        )

        ready_domains = [r["verified_entry"].domain for r in res["ready_rows"]]
        self.assertNotIn("submitted-site.com", ready_domains, "已提交终态项不得因检查点回放进入队列")
        self.assertNotIn("denied-site.com", ready_domains, "否定入口项必须被门禁拦截拒绝")
        self.assertNotIn("incomp-site.com", ready_domains, "不兼容项必须被门禁拦截拒绝")
        self.assertIn("valid-site.com", ready_domains, "合法检查点观察项在断网下必须直接无损重建 Ready")

        expired_checkpoint = copy.deepcopy(checkpoint_data)
        expired_checkpoint["created_at"] = time.time() - 4000
        save_phase_c_checkpoint("test_f3", expired_checkpoint, runtime_dir=self.runtime_dir)
        loaded = load_phase_c_checkpoint("test_f3", runtime_dir=self.runtime_dir)
        self.assertIsNone(loaded, "超过 3600 秒的旧检查点必须判定为过期失效")

    def test_f4_ledger_dual_interruption_windows_no_duplication(self):
        """F4: 账本单一写入者安全落盘，覆盖双重中断窗口：未落盘不假标，落盘未标记不重复追加且复用原时间戳。"""
        entry_1 = make_scan_ledger_entry(
            domain="window-test.com",
            disposition="ready",
            reason="探测成功",
            probe_duration_sec=0.2,
            verified_entry_url="https://window-test.com/submit",
        )
        orig_scanned_at = entry_1["scanned_at"]
        orig_scanned_ts = entry_1["scanned_timestamp"]

        checkpoint_A = {"written_ledger_keys": []}
        with patch.object(Path, "open", side_effect=OSError("磁盘满中断")):
            res_A = append_scan_ledger_entry_safely(
                project_id="test_f4",
                ledger_entry=entry_1,
                written_ledger_keys_set=set(checkpoint_A["written_ledger_keys"]),
                checkpoint_data=checkpoint_A,
                runtime_dir=self.runtime_dir,
            )
            self.assertFalse(res_A, "写入失败时应当返回 False")
            self.assertEqual(len(checkpoint_A["written_ledger_keys"]), 0, "写入失败时检查点绝不能假标已写入")

        res_A_succ = append_scan_ledger_entry_safely(
            project_id="test_f4",
            ledger_entry=entry_1,
            written_ledger_keys_set=set(checkpoint_A["written_ledger_keys"]),
            checkpoint_data=checkpoint_A,
            runtime_dir=self.runtime_dir,
        )
        self.assertTrue(res_A_succ)
        self.assertEqual(len(checkpoint_A["written_ledger_keys"]), 1)

        checkpoint_B = {"written_ledger_keys": []}
        time.sleep(0.01)

        entry_1_retry = make_scan_ledger_entry(
            domain="window-test.com",
            disposition="ready",
            reason="探测成功",
            probe_duration_sec=0.2,
            verified_entry_url="https://window-test.com/submit",
            scanned_timestamp=orig_scanned_ts,
            scanned_at=orig_scanned_at,
        )
        res_B = append_scan_ledger_entry_safely(
            project_id="test_f4",
            ledger_entry=entry_1_retry,
            written_ledger_keys_set=set(checkpoint_B["written_ledger_keys"]),
            checkpoint_data=checkpoint_B,
            runtime_dir=self.runtime_dir,
        )

        self.assertFalse(res_B, "命中磁盘已有去重键时无需重复追加，返回 False")
        self.assertEqual(len(checkpoint_B["written_ledger_keys"]), 1)
        ledger_path = os.path.join(self.runtime_dir, "cycles", "test_f4", "scan_ledger.jsonl")
        with open(ledger_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        self.assertEqual(len(lines), 1, f"磁盘账本应当只有 1 行，实际有 {len(lines)} 行")
        saved_rec = json.loads(lines[0])
        self.assertEqual(saved_rec["scanned_at"], orig_scanned_at)

    def test_f5_cta_blocked_bubbling_and_halt_preserves_ready(self):
        """F5: CTA 子页面阻塞正确向上传递 LOCAL_RESOURCE_BLOCKED；调度终止前完整保留同批已产生 Ready。"""
        def cta_blocking_fetcher(url, **kwargs):
            if "submit" in url:
                return {
                    "status": 0,
                    "error": "LOCAL_RESOURCE_BLOCKED (concurrency full)",
                    "local_blocked": True,
                    "timeout": False,
                }
            return {
                "status": 200,
                "url": url,
                "final_url": url,
                "candidate_urls": [f"{url}/submit"],
                "submission_cta_links": [{"url": f"{url}/submit", "text": "Submit Tool"}],
                "actionable_forms": [],
                "ai_only_signals": [],
            }

        ventry, reason = discover_and_verify_entry(
            domain="cta-block.com",
            fetcher=cta_blocking_fetcher,
        )
        self.assertIsNone(ventry)
        self.assertIn("LOCAL_RESOURCE_BLOCKED", reason, "子页面阻塞必须向上传递为 LOCAL_RESOURCE_BLOCKED")

        p_rows = [
            {"项目ID": "test_f5", "外链ID": "good1.com", "外链域名": "good1.com", "状态": PROJECT_STATUS_TO_SUBMIT, "尝试次数": "0"},
            {"项目ID": "test_f5", "外链ID": "good2.com", "外链域名": "good2.com", "状态": PROJECT_STATUS_TO_SUBMIT, "尝试次数": "0"},
            {"项目ID": "test_f5", "外链ID": "blocked.com", "外链域名": "blocked.com", "状态": PROJECT_STATUS_TO_SUBMIT, "尝试次数": "0"},
        ]
        m_rows = [
            {"外链ID": "good1.com", "平台域名": "good1.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://good1.com/submit"},
            {"外链ID": "good2.com", "平台域名": "good2.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://good2.com/submit"},
            {"外链ID": "blocked.com", "平台域名": "blocked.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://blocked.com/submit"},
        ]

        def mixed_verifier(domain, entry_url, **kwargs):
            if domain == "blocked.com":
                return None, "LOCAL_RESOURCE_BLOCKED (worker thread pool saturated)"
            return VerifiedEntry(
                url=entry_url,
                domain=domain,
                evidence_type="direct",
                evidence_summary="ok",
                form_details={},
                ai_only=True,
            ), "核验成功"

        state = init_cycle_state(
            project_id="test_f5",
            target_success=5,
            initial_candidates=["good1.com", "good2.com", "blocked.com"],
            spreadsheet_id="dummy",
            master_sheet="总表",
            project_sheet="管理",
            runtime_dir=self.runtime_dir,
        )

        dummy_fetch = lambda u, **kw: {"status": 200, "ai_only_signals": []}
        plan = plan_next_batch(
            state=state,
            master_rows=m_rows,
            project_rows=p_rows,
            batch_ready_target=3,
            batch_scan_limit=3,
            concurrency=2,
            runtime_dir=self.runtime_dir,
            entry_verifier=mixed_verifier,
            fetcher=dummy_fetch,
        )

        self.assertEqual(plan["action"], "HALT_WITH_PARTIAL_READY")
        ready_items = plan.get("ready_items", [])
        self.assertEqual(len(ready_items), 2, "遇到阻塞时，绝不能丢弃同批已就绪的 Ready 候选")
        self.assertEqual({r["domain"] for r in ready_items}, {"good1.com", "good2.com"})
        self.assertIn("LOCAL_RESOURCE_BLOCKED", state.get("interruption_reason", ""))

    def test_f6_deadline_propagation_and_partial_ready_delivery_no_loss(self):
        """F6: 截止时间预算透传至底层；提前交付交付当前已就绪的全部项，绝不截取丢弃。"""
        received_budgets = []

        def budget_tracking_verifier(domain, entry_url, site_timeout_budget=None, **kwargs):
            received_budgets.append(site_timeout_budget)
            return None, "未找到"

        p_rows = [{"项目ID": "test_f6", "外链ID": "bud1.com", "外链域名": "bud1.com", "状态": PROJECT_STATUS_TO_SUBMIT, "尝试次数": "0"}]
        m_rows = [{"外链ID": "bud1.com", "平台域名": "bud1.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://bud1.com/submit"}]

        prepare_execution_batch(
            project_id="test_f6",
            target_ready_count=1,
            scan_limit=1,
            project_rows=p_rows,
            master_rows=m_rows,
            entry_verifier=budget_tracking_verifier,
            time_budget=3.5,
            runtime_dir=self.runtime_dir,
        )
        self.assertEqual(len(received_budgets), 1)
        self.assertIsNotNone(received_budgets[0])
        self.assertAlmostEqual(received_budgets[0], 3.5, delta=0.5, msg="site_timeout_budget 必须有效透传到底层 verifier")

        domains = [f"multi-ready-{i}.com" for i in range(1, 4)]
        p_rows_multi = [{
            "项目ID": "test_f6",
            "外链ID": d,
            "外链域名": d,
            "状态": PROJECT_STATUS_TO_SUBMIT,
            "尝试次数": "0",
        } for d in domains]
        m_rows_multi = [{
            "外链ID": d,
            "平台域名": d,
            "基础状态": MASTER_STATUS_CANDIDATE,
            "提交入口": f"https://{d}/submit",
        } for d in domains]

        def multi_ready_verifier(domain, entry_url, **kwargs):
            return VerifiedEntry(
                url=entry_url,
                domain=domain,
                evidence_type="direct",
                evidence_summary="multi ok",
                form_details={},
            ), "ok"

        res_delivery = prepare_execution_batch(
            project_id="test_f6",
            target_ready_count=10,
            scan_limit=10,
            project_rows=p_rows_multi,
            master_rows=m_rows_multi,
            entry_verifier=multi_ready_verifier,
            min_ready_delivery=1,
            concurrency=2,
            runtime_dir=self.runtime_dir,
        )

        delivered_count = res_delivery["ready_count"]
        # 满足 min_ready_delivery=1 提前停止派发，且交付已完成的全部项，绝不超量派发第 3 项
        self.assertGreaterEqual(delivered_count, 1, "必须至少交付达到 min_ready_delivery 的项")
        self.assertLessEqual(delivered_count, 2, "必须提前停止派发，绝不派发第 3 项")
        self.assertEqual(len(res_delivery["ready_rows"]), delivered_count)

        # 当 min_ready_delivery=3 时，继续派发直到 3 个全部就绪
        p_rows_multi_3 = [{
            "项目ID": "test_f6_3",
            "外链ID": d,
            "外链域名": d,
            "状态": PROJECT_STATUS_TO_SUBMIT,
            "尝试次数": "0",
        } for d in domains]
        res_delivery_3 = prepare_execution_batch(
            project_id="test_f6_3",
            target_ready_count=10,
            scan_limit=10,
            project_rows=p_rows_multi_3,
            master_rows=m_rows_multi,
            entry_verifier=multi_ready_verifier,
            min_ready_delivery=3,
            concurrency=2,
            runtime_dir=self.runtime_dir,
        )
        self.assertEqual(res_delivery_3["ready_count"], 3)

    def test_f7_four_atomic_subitems_mutual_exclusivity_and_accounting(self):
        """F7: 业务处置大账与待提交四原子互斥子项对账严格守恒，继承人工项完全隔离不污染待提交子项。"""
        snapshot_bids = ["s1.com", "na1.com", "f1.com", "hp1.com", "r1.com", "r2.com", "inf1.com", "unres1.com", "unscanned1.com", "unscanned2.com"]

        state = {
            "schema_version": 2,
            "project_id": "test_f7_proj",
            "target_success": 5,
            "spreadsheet_id": "dummy_sheet",
            "master_sheet": "外链总表",
            "project_sheet": "外链管理",
            "snapshot_candidate_bids": snapshot_bids,
            "snapshot_total_count": 10,
            "processed_candidate_bids": ["s1.com", "na1.com", "f1.com", "hp1.com", "r1.com", "r2.com", "inf1.com", "unres1.com"],
            "newly_succeeded_count": 1,
            "prior_existing_count": 0,
            "not_applicable_count": 1,
            "failed_count": 1,
            "human_pending_count": 1,
            "still_to_submit_count": 6,
            "completed_items": {
                "s1.com": {"status": "已提交"},
                "na1.com": {"status": "不适用"},
                "f1.com": {"status": "失败"},
            },
            "human_pending_items": {
                "hp1.com": {"status": "需人工"},
            },
            "inherited_human_pending_items": {
                "ihp1.com": {"status": "需人工"},
                "ihp2.com": {"status": "需人工"},
            },
            "active_batch": {
                "batch_id": "b1",
                "ready_items": [{"domain": "r1.com"}, {"domain": "r2.com"}],
                "in_flight_bid": "inf1.com",
            },
            "is_finished": False,
            "finish_reason": None,
        }

        balanced = print_cycle_summary(state)
        self.assertTrue(balanced, "四原子互斥子项之和严格等于待提交总数，对账必须平衡 (balanced=True)")

        total_disposed = (
            state["newly_succeeded_count"]
            + state["prior_existing_count"]
            + state["not_applicable_count"]
            + state["failed_count"]
            + state["human_pending_count"]
            + state["still_to_submit_count"]
        )
        self.assertEqual(total_disposed, 10, "大账总和必须严格等于责任快照 10")

    def test_resource_benchmark_8_candidates_and_rss_measurement(self):
        """基准测量: 8 候选样本下测试并发 1, 2, 4 的加速比 (>=2.0x)、高频采样线程峰值与 RSS 增量。"""
        domains = [f"bench{i}.com" for i in range(1, 9)]
        p_rows = [{
            "项目ID": "bench_proj",
            "外链ID": d,
            "外链域名": d,
            "状态": PROJECT_STATUS_TO_SUBMIT,
            "尝试次数": "0",
        } for d in domains]
        m_rows = [{
            "外链ID": d,
            "平台域名": d,
            "基础状态": MASTER_STATUS_CANDIDATE,
            "提交入口": f"https://{d}/submit",
        } for d in domains]

        def sim_verifier(domain, entry_url, **kwargs):
            time.sleep(0.05)
            return VerifiedEntry(
                url=entry_url,
                domain=domain,
                evidence_type="direct",
                evidence_summary="bench ok",
                form_details={},
                ai_only=True,
            ), "ok"

        dummy_fetcher = lambda u, **kw: {"status": 200, "ai_only_signals": []}

        timings = {}
        peak_sampled_threads = {}
        peak_rss_mb = {}
        results_by_concurrency = {}

        for c in (1, 2, 4):
            sample_peak = 0
            stop_sampling = threading.Event()

            def thread_sampler():
                nonlocal sample_peak
                while not stop_sampling.is_set():
                    cnt = threading.active_count()
                    if cnt > sample_peak:
                        sample_peak = cnt
                    time.sleep(0.005)

            sampler_th = threading.Thread(target=thread_sampler, daemon=True)
            sampler_th.start()

            t0 = time.time()
            res = prepare_execution_batch(
                project_id="bench_proj",
                target_ready_count=8,
                scan_limit=8,
                project_rows=p_rows,
                master_rows=m_rows,
                entry_verifier=sim_verifier,
                fetcher=dummy_fetcher,
                concurrency=c,
                runtime_dir=self.runtime_dir,
            )
            elapsed = time.time() - t0
            stop_sampling.set()
            sampler_th.join(timeout=0.2)

            usage = resource.getrusage(resource.RUSAGE_SELF)
            rss_mb = usage.ru_maxrss / (1024 * 1024)

            timings[c] = elapsed
            peak_sampled_threads[c] = sample_peak
            peak_rss_mb[c] = rss_mb
            results_by_concurrency[c] = res

            self.assertEqual(res["ready_count"], 8)

        doms_1 = [r["verified_entry"].domain for r in results_by_concurrency[1]["ready_rows"]]
        doms_2 = [r["verified_entry"].domain for r in results_by_concurrency[2]["ready_rows"]]
        doms_4 = [r["verified_entry"].domain for r in results_by_concurrency[4]["ready_rows"]]
        self.assertEqual(set(doms_1), set(doms_2))
        self.assertEqual(set(doms_1), set(doms_4))

        speedup_4 = timings[1] / timings[4]
        self.assertGreaterEqual(
            speedup_4,
            2.0,
            f"并发 4 加速比应 >= 2.0x, 实际: {speedup_4:.2f}x (1路: {timings[1]:.2f}s, 4路: {timings[4]:.2f}s)"
        )

        for c in (1, 2, 4):
            self.assertLessEqual(peak_sampled_threads[c], 20, f"并发 {c} 采样线程峰值异常: {peak_sampled_threads[c]}")

    def test_audit_counterexamples_suite(self):
        """独立复核反例全集 (F2–F7) 在本沙箱内全量回归，确保 bug_reproduced 全部为 False。"""
        import copy
        import io
        import contextlib
        import scripts.run_submission_cycle as c
        import scripts.prepare_execution_batch as cli

        # F3-A: prepare 返回后检查点存在，恢复时无需网络重试
        proj = "f3-write-window"
        ps = [{"项目ID": proj, "外链ID": "ready.example", "外链域名": "ready.example", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 2}]
        ms = [{"外链ID": "ready.example", "平台域名": "ready.example", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://ready.example/", "是否免费": "免费", "需要登录": "否", "_sheet_row_num": 2}]
        def ready_v(d, u, **kw):
            return VerifiedEntry(url=u, domain=d, evidence_type="actionable_form", evidence_summary="fixture ready", ai_only=True), "fixture ready"

        r1 = prepare_execution_batch(
            project_id=proj, target_ready_count=1, scan_limit=1,
            project_rows=copy.deepcopy(ps), master_rows=copy.deepcopy(ms),
            project_context={"ai_powered": True}, runtime_dir=self.runtime_dir,
            entry_verifier=ready_v, use_scan_ledger=False, concurrency=1,
        )
        cp_after_return = load_phase_c_checkpoint(proj, runtime_dir=self.runtime_dir)
        self.assertIsNotNone(cp_after_return, "prepare_execution_batch 返回后细粒度检查点必须保留")

        offline_calls = []
        def offline_v(d, u, **kw):
            offline_calls.append(d)
            return None, "offline"
        r2 = prepare_execution_batch(
            project_id=proj, target_ready_count=1, scan_limit=1,
            project_rows=copy.deepcopy(ps), master_rows=copy.deepcopy(ms),
            project_context={"ai_powered": True}, runtime_dir=self.runtime_dir,
            entry_verifier=offline_v, use_scan_ledger=False, concurrency=1,
        )
        self.assertEqual(len(offline_calls), 0, "断网恢复时应从检查点恢复，不应发起网络探测")
        self.assertEqual(r2["ready_count"], 1, "从检查点恢复出的 Ready 数量应为 1")

        # F3-B: Master 基础状态已排除时，门禁拦截，不能从 checkpoint 恢复 Ready
        proj_b = "f3-latest-master"
        ps_b = [{"项目ID": proj_b, "外链ID": "excluded.example", "外链域名": "excluded.example", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 2}]
        ms_b = [{"外链ID": "excluded.example", "平台域名": "excluded.example", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://excluded.example/", "是否免费": "免费", "需要登录": "否", "_sheet_row_num": 2}]
        class Interrupted(Exception): pass
        def interrupt_hook(_): raise Interrupted()
        try:
            prepare_execution_batch(
                project_id=proj_b, target_ready_count=1, scan_limit=1,
                project_rows=copy.deepcopy(ps_b), master_rows=copy.deepcopy(ms_b),
                project_context={"ai_powered": True}, runtime_dir=self.runtime_dir,
                entry_verifier=ready_v, progress_callback=interrupt_hook,
            )
        except Interrupted:
            pass
        ms_b[0]["基础状态"] = "已排除"
        r_b = prepare_execution_batch(
            project_id=proj_b, target_ready_count=1, scan_limit=1,
            project_rows=copy.deepcopy(ps_b), master_rows=copy.deepcopy(ms_b),
            project_context={"ai_powered": True}, runtime_dir=self.runtime_dir,
            entry_verifier=offline_v,
        )
        self.assertEqual(r_b["ready_count"], 0, "Master 状态为已排除时绝不能复活为 Ready")

        # F5: 非首页入口跟随 CTA 遇到 local_blocked 正确冒泡
        proj_cta = "f5-nested-cta"
        ps_cta = [{"项目ID": proj_cta, "外链ID": "cta.example", "外链域名": "cta.example", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 2}]
        ms_cta = [{"外链ID": "cta.example", "平台域名": "cta.example", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://cta.example/submit", "是否免费": "免费", "需要登录": "否", "_sheet_row_num": 2}]
        def cta_fetch(u):
            if u.endswith("/submit/form"):
                return {"status": 0, "final_url": u, "local_blocked": True, "error": "LOCAL_RESOURCE_BLOCKED"}
            return {"status": 200, "final_url": u, "actionable_forms": [], "submission_cta_links": [{"url": "https://cta.example/submit/form", "text": "Submit Tool"}]}
        r_cta = prepare_execution_batch(
            project_id=proj_cta, target_ready_count=1, scan_limit=1,
            project_rows=ps_cta, master_rows=ms_cta,
            project_context={"ai_powered": True}, runtime_dir=self.runtime_dir,
            entry_verifier=None, fetcher=cta_fetch,
        )
        self.assertTrue(r_cta["local_resource_blocked"], "跟随 CTA 遇到本机阻塞必须置位 local_resource_blocked")

        # F7: start_task_attempt 在对账总结中精确计入处理中
        proj_start = "f7-start"
        ps_start = [{"项目ID": proj_start, "外链ID": "started.example", "外链域名": "started.example", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 2}]
        ms_start = [{"外链ID": "started.example", "平台域名": "started.example", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://started.example/", "是否免费": "免费", "需要登录": "否", "_sheet_row_num": 2}]
        st = c.init_cycle_state(proj_start, 1, ["started.example"], "synthetic", "Master", "Project", runtime_dir=self.runtime_dir)
        st["active_batch"] = {"batch_id": "b_fix", "ready_domains": ["started.example"], "ready_items": [{"domain": "started.example", "submission_url": "https://started.example/"}], "in_flight": True}
        st["processed_candidate_bids"] = ["started.example"]
        c.start_task_attempt(st, "started.example", master_rows=ms_start, project_rows=ps_start, commit=False, runtime_dir=self.runtime_dir)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            balanced = c.print_cycle_summary(st)
        summary = buf.getvalue()
        self.assertTrue(balanced)
        self.assertIn("处理中 (In-Flight): 1", summary)


if __name__ == "__main__":
    unittest.main()
