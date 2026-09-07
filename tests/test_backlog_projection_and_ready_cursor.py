import unittest
from unittest.mock import patch
from scripts.master_sheet_sync import (
    materialize_project_backlog_rows,
    MASTER_STATUS_CANDIDATE,
    MASTER_STATUS_EXCLUDED,
)
from scripts.project_backlog_projection import run_projection


class TestProjectBacklogProjectionReconciliation(unittest.TestCase):
    """测试小增量 Projection 完整性 invariant / reconciliation 对账机制。"""

    def setUp(self):
        self.project_id = "test-proj"
        self.target_url = "https://testproj.com/"

    @patch("scripts.project_backlog_projection.get_sheets_service")
    @patch("scripts.project_backlog_projection.get_sheet_properties")
    @patch("scripts.project_backlog_projection.fetch_all_sheet_rows")
    def test_a_empty_project_three_candidates_creates_three(self, mock_fetch, mock_props, mock_svc):
        """场景 A: 空项目 + 3 个候选 -> 3 条新增，正常结束 (不再报 < 100 错)"""
        master_rows = [
            ["外链ID", "平台域名", "提交入口", "发现来源", "发现时间", "基础状态", "基础排除原因", "实测免费", "实测需登录", "实测登录方式", "实测限制", "实测链接属性", "最后验证时间", "平台备注"],
            ["site1.com", "site1.com", "", "source", "2026-09-01", MASTER_STATUS_CANDIDATE, "", "", "", "", "", "", "", ""],
            ["site2.com", "site2.com", "", "source", "2026-09-01", MASTER_STATUS_CANDIDATE, "", "", "", "", "", "", "", ""],
            ["site3.com", "site3.com", "", "source", "2026-09-01", MASTER_STATUS_CANDIDATE, "", "", "", "", "", "", "", ""],
        ]
        project_rows = [
            ["项目ID", "外链ID", "外链域名", "状态", "尝试次数", "最近操作时间", "目标URL", "结果链接", "原因/备注", "证据摘要"],
        ]
        mock_fetch.side_effect = lambda svc, sid, sname: master_rows if sname == "外链总表" else project_rows
        mock_props.return_value = {"sheetId": 1, "title": "test", "gridProperties": {"rowCount": 1000}}

        res = run_projection(
            spreadsheet_id="test-sheet-id",
            project_id=self.project_id,
            target_url=self.target_url,
            ai_powered=False,
            master_sheet_name="外链总表",
            project_sheet_name="外链管理",
            credentials_path="dummy.json",
            batch_size=500,
            commit=False,
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["stats"]["would_create_count"], 3)
        self.assertEqual(res["stats"]["duplicate_preserved_count"], 0)
        self.assertEqual(res["stats"]["candidate_count"], 3)

    @patch("scripts.project_backlog_projection.get_sheets_service")
    @patch("scripts.project_backlog_projection.get_sheet_properties")
    @patch("scripts.project_backlog_projection.fetch_all_sheet_rows")
    def test_b_all_already_exist_zero_creates_passes(self, mock_fetch, mock_props, mock_svc):
        """场景 B: 已经全部存在 -> 0 条新增，正常结束 (不再报 < 100 错)"""
        master_rows = [
            ["外链ID", "平台域名", "提交入口", "发现来源", "发现时间", "基础状态", "基础排除原因", "实测免费", "实测需登录", "实测登录方式", "实测限制", "实测链接属性", "最后验证时间", "平台备注"],
            ["site1.com", "site1.com", "", "source", "2026-09-01", MASTER_STATUS_CANDIDATE, "", "", "", "", "", "", "", ""],
            ["site2.com", "site2.com", "", "source", "2026-09-01", MASTER_STATUS_CANDIDATE, "", "", "", "", "", "", "", ""],
        ]
        project_rows = [
            ["项目ID", "外链ID", "外链域名", "状态", "尝试次数", "最近操作时间", "目标URL", "结果链接", "原因/备注", "证据摘要"],
            [self.project_id, "site1.com", "site1.com", "待提交", "0", "", self.target_url, "", "", ""],
            [self.project_id, "site2.com", "site2.com", "已提交", "1", "", self.target_url, "", "", ""],
        ]
        mock_fetch.side_effect = lambda svc, sid, sname: master_rows if sname == "外链总表" else project_rows
        mock_props.return_value = {"sheetId": 1, "title": "test", "gridProperties": {"rowCount": 1000}}

        res = run_projection(
            spreadsheet_id="test-sheet-id",
            project_id=self.project_id,
            target_url=self.target_url,
            ai_powered=False,
            master_sheet_name="外链总表",
            project_sheet_name="外链管理",
            credentials_path="dummy.json",
            batch_size=500,
            commit=False,
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["stats"]["would_create_count"], 0)
        self.assertEqual(res["stats"]["duplicate_preserved_count"], 2)
        self.assertEqual(res["stats"]["candidate_count"], 2)

    @patch("scripts.project_backlog_projection.get_sheets_service")
    @patch("scripts.project_backlog_projection.get_sheet_properties")
    @patch("scripts.project_backlog_projection.fetch_all_sheet_rows")
    def test_c_mixed_duplicate_new_incompatible_reconciled(self, mock_fetch, mock_props, mock_svc):
        """场景 C: 混合 duplicate + new + incompatible -> 数量完整对账"""
        master_rows = [
            ["外链ID", "平台域名", "提交入口", "发现来源", "发现时间", "基础状态", "基础排除原因", "实测免费", "实测需登录", "实测登录方式", "实测限制", "实测链接属性", "最后验证时间", "平台备注"],
            ["site-new.com", "site-new.com", "", "src", "2026-09-01", MASTER_STATUS_CANDIDATE, "", "", "", "", "", "", "", ""],
            ["site-dup.com", "site-dup.com", "", "src", "2026-09-01", MASTER_STATUS_CANDIDATE, "", "", "", "", "", "", "", ""],
            ["site-ai.com", "site-ai.com", "", "src", "2026-09-01", MASTER_STATUS_CANDIDATE, "", "", "", "", "AI-only", "", "", ""],
        ]
        project_rows = [
            ["项目ID", "外链ID", "外链域名", "状态", "尝试次数", "最近操作时间", "目标URL", "结果链接", "原因/备注", "证据摘要"],
            [self.project_id, "site-dup.com", "site-dup.com", "待提交", "0", "", self.target_url, "", "", ""],
        ]
        mock_fetch.side_effect = lambda svc, sid, sname: master_rows if sname == "外链总表" else project_rows
        mock_props.return_value = {"sheetId": 1, "title": "test", "gridProperties": {"rowCount": 1000}}

        res = run_projection(
            spreadsheet_id="test-sheet-id",
            project_id=self.project_id,
            target_url=self.target_url,
            ai_powered=False,  # 非 AI 项目，site-ai.com 应被判硬不兼容
            master_sheet_name="外链总表",
            project_sheet_name="外链管理",
            credentials_path="dummy.json",
            batch_size=500,
            commit=False,
        )
        stats = res["stats"]
        self.assertEqual(stats["candidate_count"], 3)
        self.assertEqual(stats["would_create_count"], 1)
        self.assertEqual(stats["duplicate_preserved_count"], 1)
        self.assertEqual(stats["proven_project_incompatible_count"], 1)
        # 对账等式 100% 成立
        self.assertEqual(
            stats["candidate_count"],
            stats["would_create_count"] + stats["duplicate_preserved_count"] + stats["proven_project_incompatible_count"]
        )

    @patch("scripts.project_backlog_projection.get_sheets_service")
    @patch("scripts.project_backlog_projection.get_sheet_properties")
    @patch("scripts.project_backlog_projection.fetch_all_sheet_rows")
    @patch("scripts.project_backlog_projection.materialize_project_backlog_rows")
    def test_d_unaccounted_gap_fails_closed(self, mock_mat, mock_fetch, mock_props, mock_svc):
        """场景 D: 真正出现无法解释的数据缺口时才 fail closed"""
        mock_fetch.return_value = [
            ["外链ID", "平台域名", "提交入口", "发现来源", "发现时间", "基础状态", "基础排除原因", "实测免费", "实测需登录", "实测登录方式", "实测限制", "实测链接属性", "最后验证时间", "平台备注"]
        ]
        mock_props.return_value = {"sheetId": 1, "title": "test", "gridProperties": {"rowCount": 1000}}
        # 模拟出现未对账差额 (candidate=10, sum=8, 漏了 2 条)
        mock_mat.return_value = (
            [],
            {
                "candidate_count": 10,
                "existing_project_count": 0,
                "would_create_count": 3,
                "duplicate_preserved_count": 3,
                "master_hard_negative_count": 0,
                "proven_project_incompatible_count": 2,
                "incompatible_details": [],
            }
        )

        with self.assertRaises(RuntimeError) as ctx:
            run_projection(
                spreadsheet_id="test-sheet-id",
                project_id=self.project_id,
                target_url=self.target_url,
                ai_powered=False,
                master_sheet_name="外链总表",
                project_sheet_name="外链管理",
                credentials_path="dummy.json",
                batch_size=500,
                commit=False,
            )
        self.assertIn("对账失败", str(ctx.exception))


class TestReadyScanCursor(unittest.TestCase):
    """测试问题 3: Ready 扫描游标本地 Checkpoint / Cursor 机制。"""

    def setUp(self):
        import tempfile
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.runtime_dir = self.tmp_dir.name
        self.project_id = "proj-cursor"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_a_run1_scans_1_2_run2_scans_from_3_and_gets_ready(self):
        """测试 A:
        1 unresolved
        2 unresolved
        3 ready
        scan_limit=2
        Run 1: 只扫描 1、2
        Run 2: 必须从 3 开始，并得到 Ready
        """
        from scripts.master_sheet_sync import prepare_execution_batch, VerifiedEntry

        master_rows = [
            {"外链ID": "site1.com", "平台域名": "site1.com", "基础状态": "候选", "提交入口": "https://site1.com/submit"},
            {"外链ID": "site2.com", "平台域名": "site2.com", "基础状态": "候选", "提交入口": "https://site2.com/submit"},
            {"外链ID": "site3.com", "平台域名": "site3.com", "基础状态": "候选", "提交入口": "https://site3.com/submit"},
        ]
        project_rows = [
            {"项目ID": self.project_id, "外链ID": "site1.com", "外链域名": "site1.com", "状态": "待提交", "尝试次数": "0"},
            {"项目ID": self.project_id, "外链ID": "site2.com", "外链域名": "site2.com", "状态": "待提交", "尝试次数": "0"},
            {"项目ID": self.project_id, "外链ID": "site3.com", "外链域名": "site3.com", "状态": "待提交", "尝试次数": "0"},
        ]

        def fake_verifier(domain, url):
            if domain == "site3.com":
                return VerifiedEntry(url=url, domain=domain, evidence_type="actionable_form", evidence_summary="verified", form_details={}), "ok"
            return None, "unresolved"

        # Run 1: scan_limit=2, target_ready_count=1
        res1 = prepare_execution_batch(
            master_rows=master_rows,
            project_rows=project_rows,
            project_id=self.project_id,
            target_ready_count=1,
            scan_limit=2,
            entry_verifier=fake_verifier,
            runtime_dir=self.runtime_dir,
            use_cursor=True,
        )
        self.assertEqual(res1["scanned_count"], 2)
        self.assertEqual(res1["ready_count"], 0)

        # Run 2: scan_limit=2, target_ready_count=1
        # 必须从 site3.com 开始扫描并成功就绪
        res2 = prepare_execution_batch(
            master_rows=master_rows,
            project_rows=project_rows,
            project_id=self.project_id,
            target_ready_count=1,
            scan_limit=2,
            entry_verifier=fake_verifier,
            runtime_dir=self.runtime_dir,
            use_cursor=True,
        )
        self.assertEqual(res2["ready_count"], 1)
        self.assertEqual(res2["ready_rows"][0]["verified_entry"].domain, "site3.com")

    def test_b_wraps_around_at_end(self):
        """测试 B: 扫描到末尾后可以 wrap 回开头"""
        from scripts.master_sheet_sync import prepare_execution_batch, save_ready_cursor, VerifiedEntry

        master_rows = [
            {"外链ID": "site1.com", "平台域名": "site1.com", "基础状态": "候选", "提交入口": "https://site1.com/submit"},
            {"外链ID": "site2.com", "平台域名": "site2.com", "基础状态": "候选", "提交入口": "https://site2.com/submit"},
        ]
        project_rows = [
            {"项目ID": self.project_id, "外链ID": "site1.com", "外链域名": "site1.com", "状态": "待提交", "尝试次数": "0"},
            {"项目ID": self.project_id, "外链ID": "site2.com", "外链域名": "site2.com", "状态": "待提交", "尝试次数": "0"},
        ]

        def fake_verifier(domain, url):
            return VerifiedEntry(url=url, domain=domain, evidence_type="actionable_form", evidence_summary="verified", form_details={}), "ok"

        # 事先保存 cursor 在最后一条 site2.com
        save_ready_cursor(self.project_id, "site2.com", runtime_dir=self.runtime_dir)

        # 执行扫描，应该从头 wrap 到 site1.com
        res = prepare_execution_batch(
            master_rows=master_rows,
            project_rows=project_rows,
            project_id=self.project_id,
            target_ready_count=1,
            scan_limit=1,
            entry_verifier=fake_verifier,
            runtime_dir=self.runtime_dir,
            use_cursor=True,
        )
        self.assertEqual(res["ready_count"], 1)
        self.assertEqual(res["ready_rows"][0]["verified_entry"].domain, "site1.com")

    def test_c_missing_or_disappeared_id_resets_safely_without_crash(self):
        """测试 C: cursor 指向已不存在 ID 时不会 crash，安全从头开始"""
        from scripts.master_sheet_sync import prepare_execution_batch, save_ready_cursor, VerifiedEntry

        master_rows = [
            {"外链ID": "site1.com", "平台域名": "site1.com", "基础状态": "候选", "提交入口": "https://site1.com/submit"},
        ]
        project_rows = [
            {"项目ID": self.project_id, "外链ID": "site1.com", "外链域名": "site1.com", "状态": "待提交", "尝试次数": "0"},
        ]

        def fake_verifier(domain, url):
            return VerifiedEntry(url=url, domain=domain, evidence_type="actionable_form", evidence_summary="verified", form_details={}), "ok"

        # cursor 指向一个已删除的不存在 ID
        save_ready_cursor(self.project_id, "deleted-domain.com", runtime_dir=self.runtime_dir)

        res = prepare_execution_batch(
            master_rows=master_rows,
            project_rows=project_rows,
            project_id=self.project_id,
            target_ready_count=1,
            scan_limit=1,
            entry_verifier=fake_verifier,
            runtime_dir=self.runtime_dir,
            use_cursor=True,
        )
        self.assertEqual(res["ready_count"], 1)
        self.assertEqual(res["ready_rows"][0]["verified_entry"].domain, "site1.com")

    def test_d_project_isolation(self):
        """测试 D: 不同 project 的 cursor 严格隔离"""
        from scripts.master_sheet_sync import save_ready_cursor, load_ready_cursor

        save_ready_cursor("proj-alpha", "site-alpha.com", runtime_dir=self.runtime_dir)
        save_ready_cursor("proj-beta", "site-beta.com", runtime_dir=self.runtime_dir)

        self.assertEqual(load_ready_cursor("proj-alpha", runtime_dir=self.runtime_dir), "site-alpha.com")
        self.assertEqual(load_ready_cursor("proj-beta", runtime_dir=self.runtime_dir), "site-beta.com")
        self.assertIsNone(load_ready_cursor("proj-gamma", runtime_dir=self.runtime_dir))

    def test_e_orphan_consumes_scan_boundary_and_advances_cursor(self):
        """测试 E (问题 5): orphan 消耗 scan 边界并推进 cursor"""
        from scripts.master_sheet_sync import prepare_execution_batch, load_ready_cursor, VerifiedEntry

        master_rows = [
            {"外链ID": "site-valid.com", "平台域名": "site-valid.com", "基础状态": "候选", "提交入口": "https://site-valid.com/submit"},
        ]
        project_rows = [
            {"项目ID": self.project_id, "外链ID": "orphan1.com", "外链域名": "orphan1.com", "状态": "待提交", "尝试次数": "0"},
            {"项目ID": self.project_id, "外链ID": "orphan2.com", "外链域名": "orphan2.com", "状态": "待提交", "尝试次数": "0"},
            {"项目ID": self.project_id, "外链ID": "site-valid.com", "外链域名": "site-valid.com", "状态": "待提交", "尝试次数": "0"},
        ]

        def fake_verifier(domain, url):
            return VerifiedEntry(url=url, domain=domain, evidence_type="actionable_form", evidence_summary="verified", form_details={}), "ok"

        # scan_limit 设为 2，正好只能扫描 orphan1.com 和 orphan2.com
        res = prepare_execution_batch(
            master_rows=master_rows,
            project_rows=project_rows,
            project_id=self.project_id,
            target_ready_count=2,
            scan_limit=2,
            entry_verifier=fake_verifier,
            runtime_dir=self.runtime_dir,
            use_cursor=True,
        )
        # 严格消耗了 2 个 scan 额度，未超限扫描第三条
        self.assertEqual(res["scanned_count"], 2)
        self.assertEqual(res["orphan_count"], 2)
        self.assertEqual(res["ready_count"], 0)
        # cursor 推进到 orphan2.com
        saved_cursor = load_ready_cursor(self.project_id, runtime_dir=self.runtime_dir)
        self.assertEqual(saved_cursor, "orphan2.com")

        # 下一轮扫描，将从 orphan2.com 之后开始，直接命中 site-valid.com
        res2 = prepare_execution_batch(
            master_rows=master_rows,
            project_rows=project_rows,
            project_id=self.project_id,
            target_ready_count=1,
            scan_limit=2,
            entry_verifier=fake_verifier,
            runtime_dir=self.runtime_dir,
            use_cursor=True,
        )
        self.assertEqual(res2["ready_count"], 1)
        self.assertEqual(res2["ready_rows"][0]["verified_entry"].domain, "site-valid.com")

    def test_f_master_non_candidate_advances_cursor_and_consumes_boundary(self):
        """测试 F (问题 5): Master 非候选行消耗 scan 边界，cursor 不会反复停留"""
        from scripts.master_sheet_sync import prepare_execution_batch, load_ready_cursor, VerifiedEntry

        master_rows = [
            {"外链ID": "site-excluded.com", "平台域名": "site-excluded.com", "基础状态": "已排除", "提交入口": ""},
            {"外链ID": "site-valid.com", "平台域名": "site-valid.com", "基础状态": "候选", "提交入口": "https://site-valid.com/submit"},
        ]
        project_rows = [
            {"项目ID": self.project_id, "外链ID": "site-excluded.com", "外链域名": "site-excluded.com", "状态": "待提交", "尝试次数": "0"},
            {"项目ID": self.project_id, "外链ID": "site-valid.com", "外链域名": "site-valid.com", "状态": "待提交", "尝试次数": "0"},
        ]

        def fake_verifier(domain, url):
            return VerifiedEntry(url=url, domain=domain, evidence_type="actionable_form", evidence_summary="verified", form_details={}), "ok"

        # scan_limit=1，只能扫描第一条非候选行
        res = prepare_execution_batch(
            master_rows=master_rows,
            project_rows=project_rows,
            project_id=self.project_id,
            target_ready_count=1,
            scan_limit=1,
            entry_verifier=fake_verifier,
            runtime_dir=self.runtime_dir,
            use_cursor=True,
        )
        self.assertEqual(res["scanned_count"], 1)
        self.assertEqual(res["ready_count"], 0)
        # cursor 成功推进到 site-excluded.com，不会停留在它之前
        saved_cursor = load_ready_cursor(self.project_id, runtime_dir=self.runtime_dir)
        self.assertEqual(saved_cursor, "site-excluded.com")

        # 下一轮扫描，直接从 site-valid.com 开始
        res2 = prepare_execution_batch(
            master_rows=master_rows,
            project_rows=project_rows,
            project_id=self.project_id,
            target_ready_count=1,
            scan_limit=1,
            entry_verifier=fake_verifier,
            runtime_dir=self.runtime_dir,
            use_cursor=True,
        )
        self.assertEqual(res2["ready_count"], 1)
        self.assertEqual(res2["ready_rows"][0]["verified_entry"].domain, "site-valid.com")

    def test_g_invalid_project_id_rejected(self):
        """测试 G (问题 5): 非法 project_id 严格拒绝，抛出 ValueError"""
        from scripts.master_sheet_sync import get_ready_cursor_path, validate_project_id

        for invalid_id in ("", " ", "../escape", "project/slash", "project$bad", ".hidden", "a"*150):
            with self.assertRaises(ValueError):
                validate_project_id(invalid_id)
            with self.assertRaises(ValueError):
                get_ready_cursor_path(invalid_id, runtime_dir=self.runtime_dir)

    def test_h_strict_project_id_physical_isolation_dot_and_underscore(self):
        """测试 H (问题 5): a.b 与 a_b cursor 物理隔离，不发生碰撞"""
        from scripts.master_sheet_sync import save_ready_cursor, load_ready_cursor, get_ready_cursor_path

        p1 = "proj.test"
        p2 = "proj_test"

        path1 = get_ready_cursor_path(p1, runtime_dir=self.runtime_dir)
        path2 = get_ready_cursor_path(p2, runtime_dir=self.runtime_dir)
        self.assertNotEqual(path1, path2)
        self.assertTrue(path1.name.endswith("ready_cursor_proj.test.json"))
        self.assertTrue(path2.name.endswith("ready_cursor_proj_test.json"))

        save_ready_cursor(p1, "cursor-dot.com", runtime_dir=self.runtime_dir)
        save_ready_cursor(p2, "cursor-underscore.com", runtime_dir=self.runtime_dir)

        self.assertEqual(load_ready_cursor(p1, runtime_dir=self.runtime_dir), "cursor-dot.com")
        self.assertEqual(load_ready_cursor(p2, runtime_dir=self.runtime_dir), "cursor-underscore.com")


class TestProjectOrphanRowHandling(unittest.TestCase):
    """测试问题 7: Project orphan row 显式统计与报告，消除 silent continue。"""

    def setUp(self):
        self.project_id = "proj-orphan"

    def test_orphan_explicit_reporting_and_non_blocking(self):
        """测试 A-E:
        A. project row 无 master -> orphan_count=1
        B. 输出 backlink_id
        C. 不进入 ready
        D. 不影响后续合法候选继续扫描
        E. 不 silent continue (progress_callback 也上报 orphan)
        """
        from scripts.master_sheet_sync import prepare_execution_batch, VerifiedEntry

        # Master 中只有 site-valid.com，没有 orphan-site.com
        master_rows = [
            {"外链ID": "site-valid.com", "平台域名": "site-valid.com", "基础状态": "候选", "提交入口": "https://site-valid.com/submit"},
        ]
        # Project 中有 orphan-site.com (在前) 和 site-valid.com (在后)
        project_rows = [
            {"项目ID": self.project_id, "外链ID": "orphan-site.com", "外链域名": "orphan-site.com", "状态": "待提交", "尝试次数": "0"},
            {"项目ID": self.project_id, "外链ID": "site-valid.com", "外链域名": "site-valid.com", "状态": "待提交", "尝试次数": "0"},
        ]

        def fake_verifier(domain, url):
            return VerifiedEntry(url=url, domain=domain, evidence_type="actionable_form", evidence_summary="verified", form_details={}), "ok"

        progress_events = []

        res = prepare_execution_batch(
            master_rows=master_rows,
            project_rows=project_rows,
            project_id=self.project_id,
            target_ready_count=1,
            scan_limit=5,
            entry_verifier=fake_verifier,
            use_cursor=False,
            progress_callback=lambda p: progress_events.append(p),
        )

        # A. orphan_count 明确统计为 1
        self.assertEqual(res.get("orphan_count"), 1)
        # B. 输出 orphan backlink IDs
        self.assertEqual(res.get("orphan_backlink_ids"), ["orphan-site.com"])
        # C. orphan 绝不进入 ready
        ready_domains = [r["verified_entry"].domain for r in res["ready_rows"]]
        self.assertNotIn("orphan-site.com", ready_domains)
        # D. 不影响后续合法候选 site-valid.com 成功进入 ready
        self.assertIn("site-valid.com", ready_domains)
        self.assertEqual(res["ready_count"], 1)
        # E. 不 silent continue: progress_events 中明确有 orphan 汇报
        orphan_events = [p for p in progress_events if p.get("outcome") == "orphan"]
        self.assertEqual(len(orphan_events), 1)
        self.assertEqual(orphan_events[0]["domain"], "orphan-site.com")


if __name__ == "__main__":
    unittest.main()
