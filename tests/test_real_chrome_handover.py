import http.server
import json
import os
import shutil
import socket
import socketserver
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

from scripts.run_submission_cycle import (
    init_cycle_state,
    record_task_outcome,
    start_task_attempt,
    verify_cdp_live_target,
)


class SimpleHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = "<html><body><h1>Captcha / Cloudflare Test Page</h1><form><input name='test'/></form></body></html>"
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        pass  # 静默测试服务器日志


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class RealChromeHandoverTests(unittest.TestCase):
    """端到端连接真实可见 Chrome 实例进行交接与现场校验测试 (落实实施约束 1)。"""

    @classmethod
    def setUpClass(cls):
        cls.chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        if not os.path.exists(cls.chrome_bin):
            raise unittest.SkipTest("真实 Google Chrome 未安装，跳过真实浏览器验收")

        # 启动本地 HTTP 测试服务器
        cls.server = socketserver.TCPServer(("127.0.0.1", 0), SimpleHandler)
        cls.http_port = int(cls.server.server_address[1])
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

        # 启动真实 Chrome 实例（随机隔离 CDP 端口，绝不抢占用户的 9222 会话）
        cls.profile_dir = tempfile.mkdtemp(prefix="chrome_cdp_test_")
        cls.cdp_port = find_free_port()
        cls.previous_cdp_url = os.environ.get("BACKLINK_BROWSER_CDP_URL")
        os.environ["BACKLINK_BROWSER_CDP_URL"] = f"http://127.0.0.1:{cls.cdp_port}"
        cls.target_url = f"http://127.0.0.1:{cls.http_port}/handover-test.html"

        cmd = [
            cls.chrome_bin,
            f"--remote-debugging-port={cls.cdp_port}",
            f"--user-data-dir={cls.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            cls.target_url,
        ]
        cls.chrome_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 等待 CDP 端口可达
        t0 = time.time()
        cls.live_target_id = None
        while time.time() - t0 < 8.0:
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{cls.cdp_port}/json/list")
                with urllib.request.urlopen(req, timeout=1.0) as resp:
                    if resp.status == 200:
                        tabs = json.loads(resp.read().decode("utf-8"))
                        for t in tabs:
                            if t.get("type") == "page" and t.get("url") == cls.target_url:
                                cls.live_target_id = t.get("id")
                                break
                        if cls.live_target_id:
                            break
            except Exception:
                time.sleep(0.3)

        if not cls.live_target_id:
            cls.chrome_proc.terminate()
            raise RuntimeError(f"未能启动并连接真实 Chrome CDP {cls.cdp_port} 目标页面")

    @classmethod
    def tearDownClass(cls):
        # 关闭真实 Chrome
        if hasattr(cls, "chrome_proc") and cls.chrome_proc:
            cls.chrome_proc.terminate()
            try:
                cls.chrome_proc.wait(timeout=3.0)
            except Exception:
                cls.chrome_proc.kill()
        # 关闭测试 HTTP 服务器
        if hasattr(cls, "server") and cls.server:
            cls.server.shutdown()
            cls.server.server_close()
        # 清理临时 profile
        if hasattr(cls, "profile_dir") and os.path.exists(cls.profile_dir):
            shutil.rmtree(cls.profile_dir, ignore_errors=True)
        if getattr(cls, "previous_cdp_url", None) is None:
            os.environ.pop("BACKLINK_BROWSER_CDP_URL", None)
        else:
            os.environ["BACKLINK_BROWSER_CDP_URL"] = cls.previous_cdp_url

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.runtime_dir = Path(self.temp_dir) / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.autofill_runtime = Path(self.temp_dir) / "autofill"
        self.autofill_runtime.mkdir(parents=True, exist_ok=True)
        os.environ["BACKLINK_AUTOFILL_RUNTIME"] = str(self.autofill_runtime)
        self.project_id = "quick-iching"

    def tearDown(self):
        os.environ.pop("BACKLINK_AUTOFILL_RUNTIME", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_real_chrome_handover_and_continue_flow(self):
        """测试连接真实 Chrome：定位真实标签页 -> 保存交接 -> 输出指引 -> 继续下一项。"""
        # 1. 验证 verify_cdp_live_target 真实命中
        is_live, err = verify_cdp_live_target(
            target_id=self.live_target_id,
            expected_url=self.target_url,
            cdp_port=self.cdp_port,
        )
        self.assertTrue(is_live, f"真实 Chrome 标签页定位失败: {err}")
        self.assertIsNone(err)

        # 2. 初始化 cycle 并启动 127.0.0.1
        state = init_cycle_state(
            project_id=self.project_id,
            target_success=5,
            initial_candidates=["127.0.0.1", "site-next.com"],
            spreadsheet_id="test_sheet",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=str(self.runtime_dir),
        )
        state["active_batch"] = {
            "ready_domains": ["127.0.0.1", "site-next.com"],
            "ready_items": [
                {"domain": "127.0.0.1", "submission_url": self.target_url},
                {"domain": "site-next.com", "submission_url": "https://site-next.com/submit"},
            ],
        }
        p_rows = [
            {"项目ID": self.project_id, "外链ID": "127.0.0.1", "外链域名": "127.0.0.1", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 2},
            {"项目ID": self.project_id, "外链ID": "site-next.com", "外链域名": "site-next.com", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 3},
        ]
        m_rows = [
            {"外链ID": "127.0.0.1", "平台域名": "127.0.0.1", "提交入口": self.target_url, "基础状态": "候选", "基础排除原因": "", "_sheet_row_num": 2},
            {"外链ID": "site-next.com", "平台域名": "site-next.com", "提交入口": "https://site-next.com/submit", "基础状态": "候选", "基础排除原因": "", "_sheet_row_num": 3},
        ]

        # 启动尝试
        start_task_attempt(
            state=state,
            backlink_id="127.0.0.1",
            is_resume_attempt=False,
            project_rows=p_rows,
            master_rows=m_rows,
            sheets_service=None,
            commit=False,
            runtime_dir=str(self.runtime_dir),
        )

        # 3. 记录人工交接 (需人工，带真实 target_id)
        res1 = record_task_outcome(
            state=state,
            backlink_id="127.0.0.1",
            status="需人工",
            reason="遇到真实 Cloudflare 验证盾",
            evidence="现场截获 Cloudflare Turnstile 挑战控件",
            result_url=self.target_url,
            target_id=self.live_target_id,
            project_rows=p_rows,
            sheets_service=None,
            commit=False,
            runtime_dir=str(self.runtime_dir),
        )
        self.assertTrue(res1["ok"])
        self.assertEqual(state["human_pending_count"], 1)

        # 核验内存与持久化记录
        hp_item = state["human_pending_items"]["127.0.0.1"]
        self.assertTrue(hp_item["live_tab_available"])
        self.assertIsNone(hp_item["checkpoint_ref"])
        self.assertEqual(hp_item["target_id"], self.live_target_id)

        # 核验落盘的 human-pending JSON
        hp_file = self.autofill_runtime / "human-pending" / self.project_id / "127.0.0.1.json"
        self.assertTrue(hp_file.exists())
        hp_data = json.loads(hp_file.read_text(encoding="utf-8"))
        self.assertEqual(hp_data["status"], "NEEDS_HUMAN")
        self.assertEqual(hp_data["target_id"], self.live_target_id)
        self.assertIsNone(hp_data["checkpoint_ref"])
        self.assertTrue(hp_data["extra"]["live_tab_available"])

        # 4. 调度器继续处理本批次下一个候选 site-next.com
        start_task_attempt(
            state=state,
            backlink_id="site-next.com",
            is_resume_attempt=False,
            project_rows=p_rows,
            master_rows=m_rows,
            sheets_service=None,
            commit=False,
            runtime_dir=str(self.runtime_dir),
        )
        res2 = record_task_outcome(
            state=state,
            backlink_id="site-next.com",
            status="审核中",
            reason="提交成功回执",
            evidence="已收到确认信",
            result_url="https://site-next.com/confirm",
            project_rows=p_rows,
            sheets_service=None,
            commit=False,
            runtime_dir=str(self.runtime_dir),
        )
        self.assertTrue(res2["ok"])
        self.assertEqual(state["newly_succeeded_count"], 1)
        self.assertEqual(state["human_pending_count"], 1)
        # 对账严格平衡
        self.assertTrue(state["is_balanced"])


if __name__ == "__main__":
    unittest.main()
