import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.run_submission_cycle import (
    init_cycle_state,
    record_task_outcome,
    start_task_attempt,
)


class HumanHandoffLiveContractTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.runtime_dir = Path(self.temp_dir) / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.autofill_runtime = Path(self.temp_dir) / "autofill_runtime"
        self.autofill_runtime.mkdir(parents=True, exist_ok=True)
        self.project_id = "test-proj"

        # 严格隔离测试环境下的 AUTOFILL 目录，防止污染用户正式环境
        self._orig_autofill_runtime = os.environ.get("BACKLINK_AUTOFILL_RUNTIME")
        os.environ["BACKLINK_AUTOFILL_RUNTIME"] = str(self.autofill_runtime)

    def tearDown(self):
        if self._orig_autofill_runtime is not None:
            os.environ["BACKLINK_AUTOFILL_RUNTIME"] = self._orig_autofill_runtime
        else:
            os.environ.pop("BACKLINK_AUTOFILL_RUNTIME", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("scripts.run_submission_cycle.verify_cdp_live_target", return_value=(True, None))
    def test_live_tab_handoff_with_real_target_and_resume_flow(self, mock_verify):
        """测试遇到真阻碍时：保留真实可见CDP target、记录实际阻碍URL、输出指引并支持断点恢复。"""
        project_rows = [
            {"项目ID": self.project_id, "外链ID": "captcha-site.com", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 2},
        ]
        master_rows = [
            {
                "外链ID": "captcha-site.com",
                "平台域名": "captcha-site.com",
                "提交入口": "https://captcha-site.com/submit",
                "基础状态": "候选",
                "基础排除原因": "",
                "_sheet_row_num": 5,
            }
        ]
        state = init_cycle_state(
            project_id=self.project_id,
            target_success=10,
            initial_candidates=["captcha-site.com"],
            spreadsheet_id="test_sheet",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=str(self.runtime_dir),
        )
        state["active_batch"] = {
            "ready_domains": ["captcha-site.com"],
            "ready_items": [{"domain": "captcha-site.com", "submission_url": "https://captcha-site.com/submit"}],
        }

        # 1. 启动尝试 (调用门禁，进入处理中，尝试次数+1)
        start_res = start_task_attempt(
            state=state,
            backlink_id="captcha-site.com",
            master_rows=master_rows,
            project_rows=project_rows,
            commit=False,
            runtime_dir=str(self.runtime_dir),
        )
        self.assertTrue(start_res["ok"])
        self.assertEqual(start_res["attempt_count"], 1)

        # 2. 发生验证码阻碍：保留真实 CDP 目标与阻碍当前 URL
        real_target_id = "CDP_TAB_ABCD_1234"
        obstacle_url = "https://captcha-site.com/challenge?id=9988"

        rec_res = record_task_outcome(
            state=state,
            backlink_id="captcha-site.com",
            status="需人工",
            reason="页面触发 Cloudflare 验证码质询",
            evidence="hCaptcha 控件可见，需要人工勾选",
            result_url=obstacle_url,
            target_id=real_target_id,
            project_rows=project_rows,
            commit=False,
            runtime_dir=str(self.runtime_dir),
        )

        self.assertTrue(rec_res["ok"])
        self.assertEqual(rec_res["human_pending_count"], 1)

        # 验证交接文件真实落盘到测试隔离目录
        hp_file = self.autofill_runtime / "human-pending" / self.project_id / "captcha-site.com.json"
        self.assertTrue(hp_file.exists(), f"交接文件应落地于隔离目录: {hp_file}")

        hp_data = json.loads(hp_file.read_text(encoding="utf-8"))
        self.assertEqual(hp_data["target_id"], real_target_id)
        self.assertEqual(hp_data["current_url"], obstacle_url)
        self.assertEqual(hp_data["status"], "NEEDS_HUMAN")
        self.assertTrue(hp_data["extra"]["live_tab_available"])
        self.assertIn("人工介入处理", hp_data["extra"]["handover_instruction"])

        # 3. 人工解决后：断点恢复 (--resume-same-attempt) 尝试次数不累加
        resume_res = start_task_attempt(
            state=state,
            backlink_id="captcha-site.com",
            is_resume_attempt=True,
            master_rows=master_rows,
            project_rows=project_rows,
            commit=False,
            runtime_dir=str(self.runtime_dir),
        )
        self.assertTrue(resume_res["ok"])
        self.assertEqual(resume_res["attempt_count"], 1)  # 严格保持为 1

        # 4. 提交成功后记录终态：验证交接文件被 resolve 清除
        done_res = record_task_outcome(
            state=state,
            backlink_id="captcha-site.com",
            status="审核中",
            reason="人工过盾后表单提交成功",
            evidence="返回 200 审核中",
            is_resume_attempt=True,
            project_rows=project_rows,
            commit=False,
            runtime_dir=str(self.runtime_dir),
        )
        self.assertTrue(done_res["ok"])
        self.assertEqual(done_res["human_pending_count"], 0)
        self.assertEqual(done_res["newly_succeeded_count"], 1)
        # 验证交接文件已被解决移除
        self.assertFalse(hp_file.exists(), "终态达成后，待办交接文件应被清理移除")

    def test_missing_live_target_marks_needs_rebuild_and_no_fake_available(self):
        """测试缺少有效CDP target或阻碍URL时：显式标记待重建，不虚报可用。"""
        project_rows = [
            {"项目ID": self.project_id, "外链ID": "lost-tab.com", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 3},
        ]
        master_rows = [
            {
                "外链ID": "lost-tab.com",
                "平台域名": "lost-tab.com",
                "提交入口": "https://lost-tab.com/submit",
                "基础状态": "候选",
                "基础排除原因": "",
                "_sheet_row_num": 6,
            }
        ]
        state = init_cycle_state(
            project_id=self.project_id,
            target_success=10,
            initial_candidates=["lost-tab.com"],
            spreadsheet_id="test_sheet",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=str(self.runtime_dir),
        )
        state["active_batch"] = {
            "ready_domains": ["lost-tab.com"],
            "ready_items": [{"domain": "lost-tab.com", "submission_url": "https://lost-tab.com/submit"}],
        }

        start_task_attempt(
            state=state,
            backlink_id="lost-tab.com",
            master_rows=master_rows,
            project_rows=project_rows,
            commit=False,
            runtime_dir=str(self.runtime_dir),
        )

        # target_id 为 None，result_url 为空
        rec_res = record_task_outcome(
            state=state,
            backlink_id="lost-tab.com",
            status="需人工",
            reason="浏览器崩溃或断开",
            evidence="CDP target disconnected",
            target_id=None,
            result_url="",
            project_rows=project_rows,
            commit=False,
            runtime_dir=str(self.runtime_dir),
        )
        self.assertTrue(rec_res["ok"])

        hp_file = self.autofill_runtime / "human-pending" / self.project_id / "lost-tab.com.json"
        self.assertTrue(hp_file.exists())
        hp_data = json.loads(hp_file.read_text(encoding="utf-8"))

        self.assertIsNone(hp_data["target_id"])
        self.assertEqual(hp_data["checkpoint_ref"], "needs_rebuild")
        self.assertFalse(hp_data["extra"]["live_tab_available"])

    @patch("scripts.run_submission_cycle.verify_cdp_live_target", return_value=(True, None))
    def test_visible_browser_tab_matching_user_guidance_and_proceeds_to_next_candidate(self, mock_verify):
        """测试实际可见标签页匹配、用户操作指引输出、以及挂起后批次立即推进下一候选项。"""
        import io
        from contextlib import redirect_stdout

        project_rows = [
            {"项目ID": self.project_id, "外链ID": "captcha-site.com", "外链域名": "captcha-site.com", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 2},
            {"项目ID": self.project_id, "外链ID": "next-site.com", "外链域名": "next-site.com", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 3},
        ]
        master_rows = [
            {"外链ID": "captcha-site.com", "平台域名": "captcha-site.com", "提交入口": "https://captcha-site.com/submit", "基础状态": "候选", "_sheet_row_num": 10},
            {"外链ID": "next-site.com", "平台域名": "next-site.com", "提交入口": "https://next-site.com/submit", "基础状态": "候选", "_sheet_row_num": 11},
        ]
        state = init_cycle_state(
            project_id=self.project_id,
            target_success=10,
            initial_candidates=["captcha-site.com", "next-site.com"],
            spreadsheet_id="test_sheet",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=str(self.runtime_dir),
        )
        state["active_batch"] = {
            "ready_domains": ["captcha-site.com", "next-site.com"],
            "ready_items": [
                {"domain": "captcha-site.com", "submission_url": "https://captcha-site.com/submit"},
                {"domain": "next-site.com", "submission_url": "https://next-site.com/submit"},
            ],
        }

        # 模拟可见浏览器打开的标签页列表 (CDP /json/list 格式)
        mock_cdp_tabs = [
            {
                "id": "CDP_TAB_REAL_9876",
                "type": "page",
                "title": "Just a moment... (Cloudflare Turnstile)",
                "url": "https://captcha-site.com/challenge?token=xyz",
                "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/CDP_TAB_REAL_9876",
            },
            {
                "id": "CDP_TAB_OTHER_0001",
                "type": "page",
                "title": "About Blank",
                "url": "about:blank",
            }
        ]

        # 1. 启动第一个候选尝试
        start_res1 = start_task_attempt(
            state=state,
            backlink_id="captcha-site.com",
            master_rows=master_rows,
            project_rows=project_rows,
            commit=False,
            runtime_dir=str(self.runtime_dir),
        )
        self.assertTrue(start_res1["ok"])

        # 2. 真实匹配到可见标签页
        matched_tab = next((t for t in mock_cdp_tabs if "captcha-site.com" in t["url"]), None)
        self.assertIsNotNone(matched_tab, "应能从可见浏览器会话中唯一定位阻碍页面的CDP标签页")
        target_id = matched_tab["id"]
        challenge_url = matched_tab["url"]

        # 3. 记录需人工并捕获用户指引输出
        f = io.StringIO()
        with redirect_stdout(f):
            rec_res1 = record_task_outcome(
                state=state,
                backlink_id="captcha-site.com",
                status="需人工",
                reason="遭遇 Cloudflare Turnstile 质询",
                evidence="页面可见 Turnstile 勾选框",
                target_id=target_id,
                result_url=challenge_url,
                project_rows=project_rows,
                commit=False,
                runtime_dir=str(self.runtime_dir),
            )
        output_str = f.getvalue()

        # 验证指引明确输出
        self.assertIn("人工介入挂起", output_str)
        self.assertIn("captcha-site.com", output_str)
        self.assertIn(target_id, output_str)
        self.assertIn("resume-same-attempt", output_str)
        self.assertIn("自动继续推进本批次剩余候选项", output_str)

        # 4. 关键验证：调度器没有被阻塞，立即继续推进下一个候选 next-site.com
        start_res2 = start_task_attempt(
            state=state,
            backlink_id="next-site.com",
            master_rows=master_rows,
            project_rows=project_rows,
            commit=False,
            runtime_dir=str(self.runtime_dir),
        )
        self.assertTrue(start_res2["ok"])
        self.assertEqual(start_res2["attempt_count"], 1)

        rec_res2 = record_task_outcome(
            state=state,
            backlink_id="next-site.com",
            status="审核中",
            reason="提交成功等待审核",
            evidence="表单提交回执 200",
            project_rows=project_rows,
            commit=False,
            runtime_dir=str(self.runtime_dir),
        )
        self.assertTrue(rec_res2["ok"])
        self.assertEqual(rec_res2["newly_succeeded_count"], 1)
        self.assertEqual(rec_res2["human_pending_count"], 1)
        self.assertTrue(state["is_balanced"])


if __name__ == "__main__":
    unittest.main()
