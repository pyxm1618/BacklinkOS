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


if __name__ == "__main__":
    unittest.main()
