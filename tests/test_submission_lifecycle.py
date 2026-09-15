#!/usr/bin/env python3
"""BacklinkOS Formal Submission Lifecycle & Safety Contract Regression Tests.

验证行为：
1. 缺少 Ready 清单时能自动衔接准备阶段 (Phase C)；
2. 多批次执行严格遵守初始候选快照总范围与双边界停止条件；
3. 全局排除仅向其他项目尚未开始的“待提交”行传播，严格保护历史非待提交状态；
4. 项目专属限制 (如 AI-only) 隔离在当前项目，不误伤其他兼容项目；
5. 付费-only 仅记录共享实测事实，不作为全局排除；
6. 人工事项挂起 (HUMAN_PENDING) 不阻塞批次内与后续候选；
7. 同一次尝试断点恢复不重复计入新增成功；
8. 批量状态严密对账：快照总数 == 新增成功 + 不适用 + 失败 + 需人工 + 仍待提交。
"""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.master_sheet_sync import (
    ExclusionScope,
    MASTER_STATUS_CANDIDATE,
    MASTER_STATUS_DEAD,
    MASTER_STATUS_EXCLUDED,
    PROJECT_STATUS_TO_SUBMIT,
    VerifiedEntry,
    classify_exclusion,
    sync_global_exclusions_across_projects,
)
from scripts.run_submission_cycle import (
    init_cycle_state,
    plan_next_batch,
    record_task_outcome,
)


class SubmissionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runtime_dir = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_1_classify_exclusion_scope_boundaries(self):
        """准确分类排除适用范围：全局不可用、项目不兼容、付费-only、未知不排除"""
        # 1. 全局不可用
        self.assertEqual(
            classify_exclusion(MASTER_STATUS_EXCLUDED, reason="站点明确关闭收录"),
            ExclusionScope.GLOBAL_UNAVAILABLE,
        )
        self.assertEqual(
            classify_exclusion(MASTER_STATUS_DEAD, reason="域名过期死站 NXDOMAIN"),
            ExclusionScope.GLOBAL_UNAVAILABLE,
        )

        # 2. 项目特定不兼容 (AI-only)
        self.assertEqual(
            classify_exclusion(MASTER_STATUS_CANDIDATE, limits="仅限AI产品收录"),
            ExclusionScope.PROJECT_INCOMPATIBLE,
        )
        self.assertEqual(
            classify_exclusion(MASTER_STATUS_EXCLUDED, reason="仅限AI", limits="ai-only"),
            ExclusionScope.PROJECT_INCOMPATIBLE,
        )

        # 3. 付费-only
        self.assertEqual(
            classify_exclusion(MASTER_STATUS_CANDIDATE, free_status="非免费"),
            ExclusionScope.PAID_ONLY,
        )

        # 4. 未知/临时性异常：超时、未找到入口 -> 绝不能作为永久排除！
        self.assertEqual(
            classify_exclusion(MASTER_STATUS_CANDIDATE, reason="连接超时 timeout"),
            ExclusionScope.UNKNOWN_TEMPORARY,
        )
        self.assertEqual(
            classify_exclusion(MASTER_STATUS_CANDIDATE, reason="未找到入口"),
            ExclusionScope.UNKNOWN_TEMPORARY,
        )

    def test_2_cross_project_sync_only_mutates_to_submit_and_protects_historical(self):
        """全局排除同步仅作用于其他项目'待提交'行，绝对保护历史已提交/审核中/已排期/需人工等"""
        master_rows = [
            {
                "外链ID": "closed-platform.com",
                "平台域名": "closed-platform.com",
                "基础状态": MASTER_STATUS_EXCLUDED,
                "基础排除原因": "平台关闭收录",
            },
            {
                "外链ID": "dead-platform.com",
                "平台域名": "dead-platform.com",
                "基础状态": MASTER_STATUS_DEAD,
                "基础排除原因": "域名已过期死站",
            },
        ]
        project_rows = [
            # 应该被同步的行（其他项目待提交）
            {"_sheet_row_num": 10, "项目ID": "project-b", "外链ID": "closed-platform.com", "状态": "待提交"},
            {"_sheet_row_num": 11, "项目ID": "project-c", "外链ID": "dead-platform.com", "状态": "待提交"},
            # 绝对不能被同步修改的历史行
            {"_sheet_row_num": 12, "项目ID": "project-b", "外链ID": "dead-platform.com", "状态": "已提交"},
            {"_sheet_row_num": 13, "项目ID": "project-d", "外链ID": "closed-platform.com", "状态": "审核中"},
            {"_sheet_row_num": 14, "项目ID": "project-e", "外链ID": "closed-platform.com", "状态": "需人工"},
            {"_sheet_row_num": 15, "项目ID": "project-f", "外链ID": "closed-platform.com", "状态": "已排期"},
            {"_sheet_row_num": 16, "项目ID": "project-g", "外链ID": "closed-platform.com", "状态": "已上线"},
        ]

        sync_res = sync_global_exclusions_across_projects(
            master_rows=master_rows,
            project_rows=project_rows,
        )

        self.assertEqual(sync_res["mutated_count"], 2)
        mutated_pids = {m["project_id"] for m in sync_res["planned_mutations"]}
        self.assertEqual(mutated_pids, {"project-b", "project-c"})

        # 校验 mutation 字段
        m10 = next(m for m in sync_res["planned_mutations"] if m["sheet_row_num"] == 10)
        self.assertEqual(m10["proposed_fields"]["状态"], "不适用")
        self.assertIn("总表已排除", m10["proposed_fields"]["原因/备注"])
        self.assertEqual(m10["proposed_fields"]["结果链接"], "")

        m11 = next(m for m in sync_res["planned_mutations"] if m["sheet_row_num"] == 11)
        self.assertEqual(m11["proposed_fields"]["状态"], "失败")
        self.assertIn("总表已失效", m11["proposed_fields"]["原因/备注"])

        # 保护历史统计
        self.assertEqual(sync_res["skipped_historical_count"], 5)
        skipped_statuses = {s["current_status"] for s in sync_res["skipped_historical"]}
        self.assertEqual(skipped_statuses, {"已提交", "审核中", "需人工", "已排期", "已上线"})

    def test_3_cycle_state_bounds_and_no_infinite_expansion(self):
        """以初始快照为最大上限范围，最多覆盖一轮，达到目标或耗尽即停止"""
        initial_candidates = ["site1.com", "site2.com", "site3.com", "site4.com", "site5.com"]
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=3,
            initial_candidates=initial_candidates,
            spreadsheet_id="dummy-sheet-id",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )

        self.assertEqual(state["snapshot_total_count"], 5)
        self.assertEqual(state["newly_succeeded_count"], 0)

        # 模拟执行 site1 成功
        rec1 = record_task_outcome(
            state=state,
            backlink_id="site1.com",
            status="已提交",
            reason="提交成功",
            evidence="[Screenshot: listing live]",
            commit=False,
            runtime_dir=self.runtime_dir,
        )
        self.assertTrue(rec1["is_new_success"])
        self.assertEqual(state["newly_succeeded_count"], 1)
        self.assertFalse(state["is_finished"])

        # 模拟执行 site2 需人工 (HUMAN_PENDING) -> 不阻塞继续！
        rec2 = record_task_outcome(
            state=state,
            backlink_id="site2.com",
            status="需人工",
            reason="遭遇验证码",
            target_id="target-tab-123",
            commit=False,
            runtime_dir=self.runtime_dir,
        )
        self.assertFalse(rec2["is_new_success"])
        self.assertEqual(state["human_pending_count"], 1)
        self.assertEqual(state["newly_succeeded_count"], 1)
        self.assertFalse(state["is_finished"])

        # 模拟执行 site3 成功
        rec3 = record_task_outcome(
            state=state,
            backlink_id="site3.com",
            status="审核中",
            reason="审核排期中",
            evidence="[Pending approval message]",
            commit=False,
            runtime_dir=self.runtime_dir,
        )
        self.assertTrue(rec3["is_new_success"])
        self.assertEqual(state["newly_succeeded_count"], 2)

        # 模拟 site4 查重发现此前已有提交 (is_existing_prior_submit=True) -> 不计入新增成功！
        rec4 = record_task_outcome(
            state=state,
            backlink_id="site4.com",
            status="已提交",
            evidence="[Existing listing found]",
            is_existing_prior_submit=True,
            commit=False,
            runtime_dir=self.runtime_dir,
        )
        self.assertFalse(rec4["is_new_success"])
        self.assertEqual(state["newly_succeeded_count"], 2)

        # 模拟 site5 成功 -> 达到 target_success (3) -> 自动结束！
        rec5 = record_task_outcome(
            state=state,
            backlink_id="site5.com",
            status="已上线",
            evidence=json.dumps({
                "public_access_verified": True,
                "listing_identity_verified": True,
                "public_listing_verified": True,
                "public_listing_url": "https://site5.com/quick-iching",
                "note": "[Live URL confirmation]",
            }),
            result_url="https://site5.com/quick-iching",
            commit=False,
            runtime_dir=self.runtime_dir,
        )
        self.assertTrue(rec5["is_new_success"])
        self.assertEqual(state["newly_succeeded_count"], 3)
        self.assertTrue(state["is_finished"])
        self.assertIn("达到目标新增成功数", state["finish_reason"])

        # 账目严格对账验证
        snap_total = state["snapshot_total_count"]
        succ = state["newly_succeeded_count"]
        prior = state["prior_existing_count"]
        hp = state["human_pending_count"]
        still = state["still_to_submit_count"]
        self.assertEqual(snap_total, 5)
        self.assertEqual(succ, 3)
        self.assertEqual(prior, 1)
        self.assertEqual(hp, 1)
        self.assertEqual(still, 0)
        self.assertEqual(succ + prior + hp + still, snap_total)

    def test_4_resume_same_attempt_does_not_double_count(self):
        """同一次尝试挂起恢复且已是成功状态时，不重复二次计入新增成功"""
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=10,
            initial_candidates=["pending-site.com"],
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )

        # 1. 挂起为需人工
        record_task_outcome(
            state=state,
            backlink_id="pending-site.com",
            status="需人工",
            reason="需要邮件验证码",
            target_id="tab-1",
            commit=False,
            runtime_dir=self.runtime_dir,
        )
        self.assertEqual(state["human_pending_count"], 1)
        self.assertEqual(state["newly_succeeded_count"], 0)

        # 2. 用户人工解决后首次成功完成 -> 正常计入新增成功 (落实 R9 修复)
        rec_resume_first = record_task_outcome(
            state=state,
            backlink_id="pending-site.com",
            status="已提交",
            evidence="[OTP resolved and submitted]",
            commit=False,
            runtime_dir=self.runtime_dir,
        )
        self.assertTrue(rec_resume_first["is_new_success"])
        self.assertEqual(state["newly_succeeded_count"], 1)
        self.assertEqual(state["human_pending_count"], 0)

        # 3. 对同一个 candidate 重复上报已提交 -> 防重机制生效，不二次计入新增成功
        rec_resume_second = record_task_outcome(
            state=state,
            backlink_id="pending-site.com",
            status="已提交",
            evidence="[Duplicate report]",
            commit=False,
            runtime_dir=self.runtime_dir,
        )
        self.assertFalse(rec_resume_second["is_new_success"])
        self.assertEqual(state["newly_succeeded_count"], 1)

    def test_5_plan_next_batch_auto_prepares_ready_when_missing(self):
        """缺少 Ready 清单时自动进行现场有界准备并生成 Ready Allowlist"""
        master_rows = [
            {
                "外链ID": "mock-ready.com",
                "平台域名": "mock-ready.com",
                "基础状态": MASTER_STATUS_CANDIDATE,
                "提交入口": "https://mock-ready.com/submit",
                "_sheet_row_num": 2,
            },
        ]
        project_rows = [
            {
                "项目ID": "quick-iching",
                "外链ID": "mock-ready.com",
                "状态": PROJECT_STATUS_TO_SUBMIT,
                "_sheet_row_num": 2,
            },
        ]
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=5,
            initial_candidates=["mock-ready.com"],
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )

        def mock_verifier(domain, url):
            return (
                VerifiedEntry(
                    url=url,
                    domain=domain,
                    evidence_type="ACTIONABLE_FORM",
                    evidence_summary="[Verified mock submission form]",
                    ai_only=False,
                ),
                "ok",
            )

        plan = plan_next_batch(
            state=state,
            master_rows=master_rows,
            project_rows=project_rows,
            batch_ready_target=1,
            batch_scan_limit=5,
            commit_prep=False,
            runtime_dir=self.runtime_dir,
            entry_verifier=mock_verifier,
        )

        self.assertEqual(plan["action"], "EXECUTE_BATCH")
        self.assertEqual(plan["ready_domains"], ["mock-ready.com"])
        self.assertEqual(len(plan["ready_items"]), 1)
        self.assertEqual(plan["ready_items"][0]["domain"], "mock-ready.com")

    def test_r1_cli_argument_parsing(self):
        """[R1] CLI 参数解析支持直接调用 --project-id quick-iching --target-success 200"""
        from scripts.run_submission_cycle import build_parser
        parser = build_parser()
        # 测试直接传参（无子命令）
        args = parser.parse_args(["--project-id", "quick-iching", "--target-success", "200"])
        self.assertEqual(args.project_id, "quick-iching")
        self.assertEqual(args.target_success, 200)
        self.assertIsNone(args.command)

        # 测试子命令传参
        args_start = parser.parse_args(["start", "--project-id", "quick-iching"])
        self.assertEqual(args_start.command, "start")
        self.assertEqual(args_start.project_id, "quick-iching")

    def test_r2_master_submission_url_writeback_detected(self):
        """[R2] 现场探测得到新入口时，正确检测到 orig_submission_url 差异并构造写回"""
        from unittest.mock import MagicMock
        master_rows = [
            {
                "外链ID": "need-entry.com",
                "平台域名": "need-entry.com",
                "基础状态": MASTER_STATUS_CANDIDATE,
                "提交入口": "",  # 原本为空
                "_sheet_row_num": 5,
            }
        ]
        project_rows = [
            {
                "项目ID": "quick-iching",
                "外链ID": "need-entry.com",
                "状态": PROJECT_STATUS_TO_SUBMIT,
                "_sheet_row_num": 12,
            }
        ]
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=1,
            initial_candidates=["need-entry.com"],
            spreadsheet_id="dummy-sheet",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )

        def mock_finder(domain):
            return (
                VerifiedEntry(
                    url=f"https://{domain}/discovered-submit",
                    domain=domain,
                    evidence_type="ACTIONABLE_FORM",
                    evidence_summary="[Discovered submit entry]",
                    ai_only=False,
                ),
                "discovered",
            )

        mock_sheets = MagicMock()
        # 模拟 batchUpdate 成功，并且后续回读返回写入的新 url
        mock_sheets.spreadsheets().values().get().execute.return_value = {
            "values": [["https://need-entry.com/discovered-submit"]]
        }

        plan = plan_next_batch(
            state=state,
            master_rows=master_rows,
            project_rows=project_rows,
            batch_ready_target=1,
            batch_scan_limit=5,
            commit_prep=True,
            sheets_service=mock_sheets,
            runtime_dir=self.runtime_dir,
            entry_finder=mock_finder,
        )

        self.assertEqual(plan["action"], "EXECUTE_BATCH")
        self.assertEqual(len(plan["ready_items"]), 1)
        self.assertEqual(plan["ready_items"][0]["submission_url"], "https://need-entry.com/discovered-submit")
        # 验证真实调用了 batchUpdate 写入 Master 表
        mock_sheets.spreadsheets().values().batchUpdate.assert_called_once()

    def test_r3_record_outcome_rejects_empty_evidence(self):
        """[R3] 记录提交成功但缺少任何证据时，严格拦截并抛出异常，拒绝假成功"""
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=5,
            initial_candidates=["site-no-evidence.com"],
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        with self.assertRaises(ValueError):
            record_task_outcome(
                state=state,
                backlink_id="site-no-evidence.com",
                status="已提交",
                evidence="",
                result_url="",
                commit=False,
                runtime_dir=self.runtime_dir,
            )

    def test_r4_classify_exclusion_and_cross_project_sync_on_failure(self):
        """[R4] 提交执行报告死站等全局事实时，准确研判为 GLOBAL_UNAVAILABLE 并触发跨项目同步"""
        master_rows = [
            {"外链ID": "dead-domain.com", "基础状态": "已排除", "基础排除原因": "域名过期死站", "_sheet_row_num": 3}
        ]
        project_rows = [
            {"项目ID": "quick-iching", "外链ID": "dead-domain.com", "状态": "待提交", "_sheet_row_num": 10},
            {"项目ID": "other-proj", "外链ID": "dead-domain.com", "状态": "待提交", "_sheet_row_num": 20},
        ]
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=5,
            initial_candidates=["dead-domain.com"],
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        res = record_task_outcome(
            state=state,
            backlink_id="dead-domain.com",
            status="失败",
            reason="域名过期死站 404 NXDOMAIN",
            evidence="[DNS resolution failed]",
            master_rows=master_rows,
            project_rows=project_rows,
            commit=False,  # dry-run
            runtime_dir=self.runtime_dir,
        )
        self.assertIsNotNone(res["cross_project_sync"])
        self.assertEqual(res["cross_project_sync"]["planned"], 1)
        self.assertIn("other-proj", res["cross_project_sync"]["affected_projects"])

    def test_r5_cross_project_sync_checks_row_identity_and_rejects_mismatch(self):
        """[R5] 跨项目同步写前核实行身份，若因行移位项目ID/外链ID不匹配，严禁修改"""
        from unittest.mock import MagicMock
        from scripts.master_sheet_sync import execute_cross_project_sync_mutations, PROJECT_HEADER

        mock_sheets = MagicMock()
        # 模拟读回的行属于别人 (project-wrong, other-site.com)
        mock_sheets.spreadsheets().values().get().execute.return_value = {
            "values": [["project-wrong", "other-site.com", "待提交", "", "", "", "", "", "", ""]]
        }
        planned = [{
            "project_id": "project-target",
            "backlink_id": "target-site.com",
            "sheet_row_num": 15,
            "proposed_fields": {"状态": "不适用", "原因/备注": "死站"},
        }]
        res = execute_cross_project_sync_mutations(
            sheets_service=mock_sheets,
            spreadsheet_id="dummy",
            project_sheet_name="外链管理",
            project_header=PROJECT_HEADER,
            planned_mutations=planned,
            commit=True,
            runtime_dir=self.runtime_dir,
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["failed_count"], 1)
        self.assertIn("写前行身份核实失败", res["failed_items"][0]["error"])

    def test_r6_pending_cross_project_sync_recovery(self):
        """[R6] 跨项目同步失败项持久化到 pending 文件，并能通过 recover 正常消费"""
        import json
        from unittest.mock import MagicMock
        from scripts.master_sheet_sync import recover_pending_cross_project_sync, PROJECT_HEADER

        pending_file = Path(self.runtime_dir) / "pending_cross_project_sync.json"
        pending_data = {
            "pending_map": {
                "proj-b::dead.com": {
                    "project_id": "proj-b",
                    "backlink_id": "dead.com",
                    "sheet_row_num": 8,
                    "proposed_fields": {"状态": "不适用", "最近操作时间": "2026-09-09T00:00:00Z", "结果链接": "", "原因/备注": "已排除", "证据摘要": "[同步]"},
                    "master_row": {"基础状态": "已排除", "基础排除原因": "平台关闭"},
                }
            }
        }
        pending_file.write_text(json.dumps(pending_data), encoding="utf-8")

        mock_sheets = MagicMock()
        # 写前读取匹配正确 (0: 项目ID, 1: 外链ID, 2: 外链域名, 3: 状态, 4: 尝试次数, 5: 最近操作时间, 6: 目标URL, 7: 结果链接, 8: 原因/备注, 9: 证据摘要)
        mock_sheets.spreadsheets().values().get().execute.side_effect = [
            {"values": [["proj-b", "dead.com", "dead.com", "待提交", "0", "", "", "", "", ""]]},  # 写前
            {"values": [["proj-b", "dead.com", "dead.com", "不适用", "0", "2026-09-09T00:00:00Z", "", "", "已排除", "[同步]"]]}, # 写后回读
        ]

        rec_res = recover_pending_cross_project_sync(
            sheets_service=mock_sheets,
            spreadsheet_id="dummy",
            project_sheet_name="外链管理",
            project_header=PROJECT_HEADER,
            commit=True,
            runtime_dir=self.runtime_dir,
        )
        self.assertTrue(rec_res["ok"])
        self.assertEqual(rec_res["committed_count"], 1)
        self.assertFalse(pending_file.exists())  # 消费完成，文件自动清除

    def test_r7_snapshot_order_strictly_maintained(self):
        """[R7] Sheet 行顺序与 snapshot 顺序不同时，批次准备仍按 snapshot 原始顺序推进"""
        initial = ["site-a.com", "site-b.com", "site-c.com"]
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=3,
            initial_candidates=initial,
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        # Sheet 顺序被打乱：c 在前，b 在中，a 在后
        project_rows = [
            {"项目ID": "quick-iching", "外链ID": "site-c.com", "状态": PROJECT_STATUS_TO_SUBMIT, "_sheet_row_num": 4},
            {"项目ID": "quick-iching", "外链ID": "site-b.com", "状态": PROJECT_STATUS_TO_SUBMIT, "_sheet_row_num": 3},
            {"项目ID": "quick-iching", "外链ID": "site-a.com", "状态": PROJECT_STATUS_TO_SUBMIT, "_sheet_row_num": 2},
        ]
        master_rows = [
            {"外链ID": d, "平台域名": d, "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": f"https://{d}/submit", "_sheet_row_num": i}
            for i, d in enumerate(initial, 2)
        ]

        def mock_verifier(domain, url):
            return (
                VerifiedEntry(url=url, domain=domain, evidence_type="ACTIONABLE_FORM", evidence_summary="ok", ai_only=False),
                "ok"
            )

        # 批次限制 1 个
        plan = plan_next_batch(
            state=state,
            master_rows=master_rows,
            project_rows=project_rows,
            batch_ready_target=1,
            batch_scan_limit=1,
            commit_prep=False,
            runtime_dir=self.runtime_dir,
            entry_verifier=mock_verifier,
        )
        # 第一个准备的必须是快照排第一的 site-a.com，而不是 Sheet 排第一的 site-c.com
        self.assertEqual(plan["ready_domains"], ["site-a.com"])

    def test_r8_archive_finished_cycle_and_new_target_lifecycle(self):
        """[R8] 循环完成后可安全归档并开启新轮次，继承未解决的人工项"""
        from scripts.run_submission_cycle import archive_finished_cycle
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=1,
            initial_candidates=["site-finished.com"],
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            inherited_human_pending={"pending-old.com": {"reason": "captcha"}},
            runtime_dir=self.runtime_dir,
        )
        record_task_outcome(
            state=state,
            backlink_id="site-finished.com",
            status="已提交",
            evidence="[Finished]",
            commit=False,
            runtime_dir=self.runtime_dir,
        )
        self.assertTrue(state["is_finished"])

        archived_path = archive_finished_cycle("quick-iching", runtime_dir=self.runtime_dir)
        self.assertIsNotNone(archived_path)
        self.assertTrue(archived_path.exists())

        # 归档后原 state 文件被清除，可以开启新轮次并继承 pending
        state_new = init_cycle_state(
            project_id="quick-iching",
            target_success=5,
            initial_candidates=["new-site-1.com", "new-site-2.com"],
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            inherited_human_pending=state.get("human_pending_items"),
            runtime_dir=self.runtime_dir,
        )
        self.assertEqual(state_new["target_success"], 5)
        self.assertEqual(state_new["human_pending_count"], 1)
        self.assertIn("pending-old.com", state_new["human_pending_items"])

    def test_r9_strict_accounting_balance_with_prior_existing_and_resume_success(self):
        """[R9] 完整对账验证：快照 = 新增成功 + 历史已有 + 不适用 + 失败 + 需人工 + 仍待提交 绝对平衡"""
        candidates = ["site-succ.com", "site-prior.com", "site-notapp.com", "site-fail.com", "site-human.com", "site-wait.com"]
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=10,
            initial_candidates=candidates,
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        # 1. 成功提交
        record_task_outcome(state, "site-succ.com", "已提交", evidence="[Form ok]", commit=False, runtime_dir=self.runtime_dir)
        # 2. 既往已有
        record_task_outcome(state, "site-prior.com", "已提交", evidence="[Already listed]", is_existing_prior_submit=True, commit=False, runtime_dir=self.runtime_dir)
        # 3. 不适用
        record_task_outcome(state, "site-notapp.com", "不适用", reason="仅限AI", commit=False, runtime_dir=self.runtime_dir)
        # 4. 失败
        record_task_outcome(state, "site-fail.com", "失败", reason="永久死站", commit=False, runtime_dir=self.runtime_dir)
        # 5. 需人工
        record_task_outcome(state, "site-human.com", "需人工", reason="验证码", commit=False, runtime_dir=self.runtime_dir)
        # 6. site-wait.com 保持未处理

        total = state["snapshot_total_count"]
        succ = state["newly_succeeded_count"]
        prior = state["prior_existing_count"]
        notapp = state["not_applicable_count"]
        fail = state["failed_count"]
        hp = state["human_pending_count"]
        still = state["still_to_submit_count"]

        self.assertEqual(total, 6)
        self.assertEqual(succ, 1)
        self.assertEqual(prior, 1)
        self.assertEqual(notapp, 1)
        self.assertEqual(fail, 1)
        self.assertEqual(hp, 1)
        self.assertEqual(still, 1)
        self.assertEqual(succ + prior + notapp + fail + hp + still, total)

    def test_r3_commit_true_requires_sheets_service(self):
        """[R3] commit=True 但未提供有效 sheets_service 时必须抛出 RuntimeError，拒绝无凭据记账"""
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=5,
            initial_candidates=["no-service.com"],
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        with self.assertRaises(RuntimeError) as ctx:
            record_task_outcome(
                state=state,
                backlink_id="no-service.com",
                status="已提交",
                evidence="[Live screenshot]",
                commit=True,
                sheets_service=None,
                runtime_dir=self.runtime_dir,
            )
        self.assertIn("未提供有效的 sheets_service", str(ctx.exception))

    def test_r3_cli_fails_with_exit_code_2_on_missing_credentials(self):
        """[R3] CLI record-outcome 在缺失凭据且非 dry-run 时向 stderr 报错并退出码 2"""
        import os
        import subprocess
        import sys
        state = init_cycle_state(
            project_id="cli-r3-test",
            target_success=5,
            initial_candidates=["cli-site.com"],
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        res = subprocess.run(
            [
                sys.executable,
                "scripts/run_submission_cycle.py",
                "record-outcome",
                "--project-id", "cli-r3-test",
                "--backlink-id", "cli-site.com",
                "--status", "已提交",
                "--evidence", "[Evidence ok]",
                "--credentials-path", "/path/to/nonexistent/credentials.json",
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "BACKLINKOS_RUNTIME_DIR": self.runtime_dir},
        )
        self.assertEqual(res.returncode, 2)
        self.assertIn("凭据", res.stderr)

    def test_r3_pre_write_identity_check_rejects_row_shift(self):
        """[R3] 写前行身份核实发现行移位 (项目ID或外链ID不符) 时拒绝写入并抛出 RuntimeError"""
        from unittest.mock import MagicMock
        mock_sheets = MagicMock()
        mock_sheets.spreadsheets().values().get().execute.return_value = {
            "values": [["other-project", "other-domain.com", "待提交", "", "", "", "", "", "", ""]]
        }
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=5,
            initial_candidates=["my-domain.com"],
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        prows = [
            {"项目ID": "quick-iching", "外链ID": "my-domain.com", "状态": "待提交", "_sheet_row_num": 10}
        ]
        with self.assertRaises(RuntimeError) as ctx:
            record_task_outcome(
                state=state,
                backlink_id="my-domain.com",
                status="已提交",
                evidence="[Evidence ok]",
                project_rows=prows,
                sheets_service=mock_sheets,
                commit=True,
                runtime_dir=self.runtime_dir,
            )
        self.assertIn("写前行身份核验失败", str(ctx.exception))
        mock_sheets.spreadsheets().values().batchUpdate.assert_not_called()

    def test_r4_master_fact_writeback_and_sync_execution(self):
        """[R4] 平台死站事实写回 Master 表并更新内存，确保跨项目同步成功触发"""
        from unittest.mock import MagicMock
        mock_sheets = MagicMock()
        mock_sheets.spreadsheets().values().get().execute.side_effect = [
            # 1. Project 写前读取
            {"values": [["quick-iching", "dead-domain.com", "dead-domain.com", "待提交", "", "", "", "", "", ""]]},
            # 2. Project 写后回读
            {"values": [["quick-iching", "dead-domain.com", "dead-domain.com", "失败", "0", "", "", "", "永久死站 404 NXDOMAIN", "[DNS resolution failed]"]]},
            # 3. Master 写前核验 (S3 要求)
            {"values": [["dead-domain.com", "dead-domain.com"]]},
            # 4. Master 写后回读 (index 0: 外链ID, index 1: 平台域名, index 5: 基础状态, index 6: 基础排除原因)
            {"values": [["dead-domain.com", "dead-domain.com", "", "", "", "失效", "永久死站 404 NXDOMAIN", ""]]},
            # 5. 跨项目同步 project-other 写前读取
            {"values": [["project-other", "dead-domain.com", "dead-domain.com", "待提交", "", "", "", "", "", ""]]},
            # 6. 跨项目同步 project-other 写后回读
            {"values": [["project-other", "dead-domain.com", "dead-domain.com", "失败", "", "", "", "", "平台级不可用：总表已失效（永久死站 404 NXDOMAIN）", "[跨项目自动同步]"]]},
        ]

        master_rows = [
            {"外链ID": "dead-domain.com", "平台域名": "dead-domain.com", "基础状态": "候选", "基础排除原因": "", "_sheet_row_num": 5}
        ]
        project_rows = [
            {"项目ID": "quick-iching", "外链ID": "dead-domain.com", "状态": "待提交", "_sheet_row_num": 10},
            {"项目ID": "project-other", "外链ID": "dead-domain.com", "状态": "待提交", "_sheet_row_num": 20},
        ]
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=5,
            initial_candidates=["dead-domain.com"],
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )

        res = record_task_outcome(
            state=state,
            backlink_id="dead-domain.com",
            status="失败",
            reason="永久死站 404 NXDOMAIN",
            evidence="[DNS resolution failed]",
            master_rows=master_rows,
            project_rows=project_rows,
            sheets_service=mock_sheets,
            commit=True,
            runtime_dir=self.runtime_dir,
        )
        self.assertEqual(master_rows[0]["基础状态"], "失效")
        self.assertIn("死站", master_rows[0]["基础排除原因"])
        self.assertIsNotNone(res["cross_project_sync"])
        self.assertEqual(res["cross_project_sync"]["committed"], 1)
        self.assertIn("project-other", res["cross_project_sync"]["affected_projects"])

    def test_r7_dual_candidate_reverse_order_multi_batch_coverage(self):
        """[R7] 双候选倒序场景：第一批只准备快照第一项，第二批精准扫描第二项，不遗漏不跳步"""
        initial = ["site-1.com", "site-2.com"]
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=2,
            initial_candidates=initial,
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        project_rows = [
            {"项目ID": "quick-iching", "外链ID": "site-2.com", "状态": PROJECT_STATUS_TO_SUBMIT, "_sheet_row_num": 3},
            {"项目ID": "quick-iching", "外链ID": "site-1.com", "状态": PROJECT_STATUS_TO_SUBMIT, "_sheet_row_num": 2},
        ]
        master_rows = [
            {"外链ID": "site-1.com", "平台域名": "site-1.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://site-1.com/sub", "_sheet_row_num": 2},
            {"外链ID": "site-2.com", "平台域名": "site-2.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://site-2.com/sub", "_sheet_row_num": 3},
        ]

        def mock_verifier(domain, url):
            return (VerifiedEntry(url=url, domain=domain, evidence_type="ACTIONABLE_FORM", evidence_summary="ok", ai_only=False), "ok")

        plan1 = plan_next_batch(
            state=state,
            master_rows=master_rows,
            project_rows=project_rows,
            batch_ready_target=1,
            batch_scan_limit=1,
            commit_prep=False,
            runtime_dir=self.runtime_dir,
            entry_verifier=mock_verifier,
        )
        self.assertEqual(plan1["ready_domains"], ["site-1.com"])
        self.assertEqual(state["processed_candidate_bids"], ["site-1.com"])

        record_task_outcome(state, "site-1.com", "已提交", evidence="[Form 1 ok]", commit=False, runtime_dir=self.runtime_dir)

        plan2 = plan_next_batch(
            state=state,
            master_rows=master_rows,
            project_rows=project_rows,
            batch_ready_target=1,
            batch_scan_limit=1,
            commit_prep=False,
            runtime_dir=self.runtime_dir,
            entry_verifier=mock_verifier,
        )
        self.assertEqual(plan2["ready_domains"], ["site-2.com"])
        self.assertEqual(set(state["processed_candidate_bids"]), {"site-1.com", "site-2.com"})

        record_task_outcome(state, "site-2.com", "已提交", evidence="[Form 2 ok]", commit=False, runtime_dir=self.runtime_dir)

        plan3 = plan_next_batch(
            state=state,
            master_rows=master_rows,
            project_rows=project_rows,
            batch_ready_target=1,
            batch_scan_limit=1,
            commit_prep=False,
            runtime_dir=self.runtime_dir,
            entry_verifier=mock_verifier,
        )
        self.assertEqual(plan3["action"], "STOP")
        self.assertEqual(state["newly_succeeded_count"], 2)

    def test_r7_tail_batch_scan_limit_smaller_than_target_ready_no_crash(self):
        """[R7] 尾批剩余候选数小于 batch_ready_target 时，不触发 scan_limit < target_ready_count 报错崩溃"""
        initial = ["cand-a.com", "cand-b.com"]
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=100,
            initial_candidates=initial,
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        project_rows = [
            {"项目ID": "quick-iching", "外链ID": "cand-a.com", "状态": PROJECT_STATUS_TO_SUBMIT, "_sheet_row_num": 2},
            {"项目ID": "quick-iching", "外链ID": "cand-b.com", "状态": PROJECT_STATUS_TO_SUBMIT, "_sheet_row_num": 3},
        ]
        master_rows = [
            {"外链ID": "cand-a.com", "平台域名": "cand-a.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://cand-a.com/sub", "_sheet_row_num": 2},
            {"外链ID": "cand-b.com", "平台域名": "cand-b.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": "https://cand-b.com/sub", "_sheet_row_num": 3},
        ]

        def mock_verifier(domain, url):
            return (VerifiedEntry(url=url, domain=domain, evidence_type="ACTIONABLE_FORM", evidence_summary="ok", ai_only=False), "ok")

        plan = plan_next_batch(
            state=state,
            master_rows=master_rows,
            project_rows=project_rows,
            batch_ready_target=10,
            batch_scan_limit=2,
            commit_prep=False,
            runtime_dir=self.runtime_dir,
            entry_verifier=mock_verifier,
        )
        self.assertEqual(plan["action"], "EXECUTE_BATCH")
        self.assertEqual(len(plan["ready_items"]), 2)

    def test_r9_inherited_human_pending_unified_snapshot_accounting(self):
        """[R9] 跨轮继承人工项后，纳入统一责任快照，全流程流转账目绝对保持 BALANCED"""
        inherited_hp = {
            "hp-1.com": {"domain": "hp-1.com", "status": "需人工", "reason": "验证码"},
            "hp-2.com": {"domain": "hp-2.com", "status": "需人工", "reason": "2FA"},
        }
        new_cands = ["cand-1.com", "cand-2.com", "cand-3.com"]

        state = init_cycle_state(
            project_id="quick-iching",
            target_success=10,
            initial_candidates=new_cands,
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            inherited_human_pending=inherited_hp,
            runtime_dir=self.runtime_dir,
        )

        self.assertEqual(state["snapshot_total_count"], 5)
        self.assertEqual(state["human_pending_count"], 2)
        self.assertEqual(state["still_to_submit_count"], 3)
        self.assertEqual(state["newly_succeeded_count"], 0)
        self.assertEqual(
            state["newly_succeeded_count"] + state["prior_existing_count"] + state["not_applicable_count"]
            + state["failed_count"] + state["human_pending_count"] + state["still_to_submit_count"],
            state["snapshot_total_count"],
        )

        # 解决 hp-1.com
        rec1 = record_task_outcome(state, "hp-1.com", "已提交", evidence="[Captcha solved]", commit=False, runtime_dir=self.runtime_dir)
        self.assertTrue(rec1["is_new_success"])
        self.assertEqual(state["newly_succeeded_count"], 1)
        self.assertEqual(state["human_pending_count"], 1)
        self.assertTrue(state["is_balanced"])

        # 重复上报 hp-1.com 防重
        rec2 = record_task_outcome(state, "hp-1.com", "已提交", evidence="[Duplicate]", commit=False, runtime_dir=self.runtime_dir)
        self.assertFalse(rec2["is_new_success"])
        self.assertEqual(state["newly_succeeded_count"], 1)
        self.assertTrue(state["is_balanced"])

        # 新候选 cand-1.com 提交成功
        rec3 = record_task_outcome(state, "cand-1.com", "已提交", evidence="[Success]", commit=False, runtime_dir=self.runtime_dir)
        self.assertTrue(rec3["is_new_success"])
        self.assertEqual(state["newly_succeeded_count"], 2)
        self.assertEqual(state["still_to_submit_count"], 2)
        self.assertTrue(state["is_balanced"])

        # 新候选 cand-2.com 遇到验证码挂起需人工
        rec4 = record_task_outcome(state, "cand-2.com", "需人工", reason="验证码", commit=False, runtime_dir=self.runtime_dir)
        self.assertFalse(rec4["is_new_success"])
        self.assertEqual(state["human_pending_count"], 2)
        self.assertEqual(state["still_to_submit_count"], 1)
        self.assertTrue(state["is_balanced"])

        # 新候选 cand-3.com 判定永久死站失败
        rec5 = record_task_outcome(state, "cand-3.com", "失败", reason="域名已过期死站", commit=False, runtime_dir=self.runtime_dir)
        self.assertFalse(rec5["is_new_success"])
        self.assertEqual(state["failed_count"], 1)
        self.assertEqual(state["still_to_submit_count"], 0)
        self.assertTrue(state["is_balanced"])

        self.assertEqual(
            state["newly_succeeded_count"] + state["prior_existing_count"] + state["not_applicable_count"]
            + state["failed_count"] + state["human_pending_count"] + state["still_to_submit_count"],
            state["snapshot_total_count"],
        )

    def test_r3_missing_target_row_in_project_rows_rejected(self):
        """[R3] 正式落表模式下，若在 project_rows 中找不到目标行，必须抛出 RuntimeError 拒绝虚假记账"""
        from unittest.mock import MagicMock
        mock_sheets = MagicMock()
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=5,
            initial_candidates=["orphan-site.com"],
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        # project_rows 存在其他项目行，但没有 orphan-site.com
        prows = [
            {"项目ID": "quick-iching", "外链ID": "other-site.com", "状态": "待提交", "_sheet_row_num": 10}
        ]
        with self.assertRaises(RuntimeError) as ctx:
            record_task_outcome(
                state=state,
                backlink_id="orphan-site.com",
                status="已提交",
                evidence="[Some evidence]",
                project_rows=prows,
                sheets_service=mock_sheets,
                commit=True,
                runtime_dir=self.runtime_dir,
            )
        self.assertIn("未能在项目表中唯一定位目标行", str(ctx.exception))
        self.assertEqual(state["newly_succeeded_count"], 0)
        self.assertEqual(len(state["completed_items"]), 0)

    def test_r3_claims_live_without_positive_evidence_rejected_by_gate(self):
        """[R3] 仅传 URL 声称已上线但缺少真实核验证据时，门禁严格拦截拒绝伪造事实"""
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=5,
            initial_candidates=["unverified-site.com"],
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        # 仅传入 URL，无真实核验证据，声称已上线
        with self.assertRaises(ValueError) as ctx:
            record_task_outcome(
                state=state,
                backlink_id="unverified-site.com",
                status="已上线",
                result_url="https://success.example/listing/unverified",
                evidence="",
                commit=False,
                runtime_dir=self.runtime_dir,
            )
        self.assertIn("门禁校验拦截失败", str(ctx.exception))

    def test_r4_entry_404_with_homepage_200_unconfirmed_does_not_mutate_master_or_sync(self):
        """[R4] 单个提交入口 404 但主页正常且平台关闭未确认，严禁升级为 Master 失效或向其他项目传播"""
        from unittest.mock import MagicMock
        mock_sheets = MagicMock()
        master_rows = [
            {"外链ID": "partial-404.com", "平台域名": "partial-404.com", "基础状态": "候选", "基础排除原因": "", "_sheet_row_num": 8}
        ]
        project_rows = [
            {"项目ID": "quick-iching", "外链ID": "partial-404.com", "状态": "待提交", "_sheet_row_num": 15},
            {"项目ID": "project-b", "外链ID": "partial-404.com", "状态": "待提交", "_sheet_row_num": 25},
        ]
        state = init_cycle_state(
            project_id="quick-iching",
            target_success=5,
            initial_candidates=["partial-404.com"],
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )

        res = record_task_outcome(
            state=state,
            backlink_id="partial-404.com",
            status="失败",
            reason="提交入口返回404，主页正常，平台是否关闭尚未确认",
            evidence="提交入口 HTTP 404，主页 HTTP 200",
            master_rows=master_rows,
            project_rows=project_rows,
            commit=False,
            runtime_dir=self.runtime_dir,
        )

        # 1. 验证 Master 依然为候选，原因不被修改
        self.assertEqual(master_rows[0]["基础状态"], "候选")
        self.assertEqual(master_rows[0]["基础排除原因"], "")
        # 2. 验证绝不触发跨项目全局排除同步
        self.assertIsNone(res["cross_project_sync"])
        # 3. 验证 project-b 依然为待提交
        self.assertEqual(project_rows[1]["状态"], "待提交")

    def test_r9_injected_unbalanced_state_blocks_completion_and_cli_exit_3(self):
        """[R9] 故意注入失衡状态时，record_task_outcome 返回 ok=False，禁止 is_finished，CLI 退出码为 3"""
        import json
        import os
        import subprocess
        import sys
        from scripts.run_submission_cycle import get_cycle_state_path

        state = init_cycle_state(
            project_id="unbalanced-proj",
            target_success=1,
            initial_candidates=["site-1.com"],
            spreadsheet_id="dummy",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        # 故意篡改 state.json 注入失衡状态：快照总数为 999，导致账目严重失衡
        state["snapshot_total_count"] = 999
        p = get_cycle_state_path("unbalanced-proj", self.runtime_dir)
        p.write_text(json.dumps(state), encoding="utf-8")

        # 1. record_task_outcome 内存调用测试：ok 必须为 False，is_finished 必须为 False
        res = record_task_outcome(
            state=state,
            backlink_id="site-1.com",
            status="已提交",
            evidence="[Evidence ok]",
            commit=False,
            runtime_dir=self.runtime_dir,
        )
        self.assertFalse(res["ok"])
        self.assertFalse(res["is_balanced"])
        self.assertFalse(res["is_finished"])
        self.assertIn("账目失衡", res["finish_reason"])

        # 2. 外部子进程调用 record-outcome CLI：退出码必须为 3
        cli_res = subprocess.run(
            [
                sys.executable,
                "scripts/run_submission_cycle.py",
                "record-outcome",
                "--project-id", "unbalanced-proj",
                "--backlink-id", "site-1.com",
                "--status", "已提交",
                "--evidence", "[Evidence ok]",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "BACKLINKOS_RUNTIME_DIR": self.runtime_dir},
        )
        self.assertEqual(cli_res.returncode, 3)
        self.assertIn("账目失衡", cli_res.stderr)

        # 3. 外部子进程调用 start CLI：检测到失衡状态禁止作为已完成归档，退出码必须为 3
        # 即使设置了 is_finished = True，只要 is_balanced = False，就必须拒绝归档
        state_corrupt = json.loads(p.read_text(encoding="utf-8"))
        state_corrupt["is_finished"] = True
        state_corrupt["is_balanced"] = False
        p.write_text(json.dumps(state_corrupt), encoding="utf-8")

        start_res = subprocess.run(
            [
                sys.executable,
                "scripts/run_submission_cycle.py",
                "start",
                "--project-id", "unbalanced-proj",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "BACKLINKOS_RUNTIME_DIR": self.runtime_dir},
        )
        self.assertEqual(start_res.returncode, 3)
        self.assertIn("账目失衡", start_res.stderr)


if __name__ == "__main__":
    unittest.main()
