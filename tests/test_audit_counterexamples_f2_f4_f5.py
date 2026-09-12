import contextlib
import copy
import io
import json
import os
import re
import shutil
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.request import build_opener, ProxyHandler

import scripts.master_sheet_sync as master
import scripts.run_submission_cycle as cycle
import scripts.screening_crawler as crawler


class Response:
    def __init__(self, value):
        self.value = value
    def execute(self):
        return copy.deepcopy(self.value)


class SheetsMock:
    def __init__(self, grids):
        self.grids = grids
        self.reads = []
        self.writes = []
    def spreadsheets(self):
        return self
    def values(self):
        return self
    def get(self, spreadsheetId, range):
        self.reads.append(range)
        match = re.fullmatch(r"'(.+)'!([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?", range)
        if not match:
            # 兼容标准 A1:A20000
            match = re.fullmatch(r"'(.+)'!([A-Z]+)(\d+):([A-Z]+)(\d+)", range)
        if match:
            sheet, left, row, right, _ = match.groups()
            start = ord(left) - ord("A")
            end = ord(right or left) - ord("A") + 1
            values = self.grids.get((sheet, int(row)), [""] * 14)[start:end]
            return Response({"values": [values]})
        return Response({"values": []})

    def batchUpdate(self, spreadsheetId, body):
        self.writes.extend(copy.deepcopy(body["data"]))
        for item in body["data"]:
            match = re.fullmatch(r"'(.+)'!([A-Z]+)(\d+)", item["range"])
            if match:
                sheet, column, row = match.groups()
                cells = self.grids.setdefault((sheet, int(row)), [""] * 14)
                cells[ord(column) - ord("A")] = str(item["values"][0][0])
        return Response({"ok": True})


class AuditCounterexamplesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="audit-test-")
        self.runtime_dir = Path(self.temp_dir) / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.autofill_runtime = Path(self.temp_dir) / "autofill"
        self.autofill_runtime.mkdir(parents=True, exist_ok=True)
        self.orig_runtime = os.environ.get("BACKLINKOS_RUNTIME_DIR")
        self.orig_autofill = os.environ.get("BACKLINK_AUTOFILL_RUNTIME")
        os.environ["BACKLINKOS_RUNTIME_DIR"] = str(self.runtime_dir)
        os.environ["BACKLINK_AUTOFILL_RUNTIME"] = str(self.autofill_runtime)

    def tearDown(self):
        if self.orig_runtime:
            os.environ["BACKLINKOS_RUNTIME_DIR"] = self.orig_runtime
        else:
            os.environ.pop("BACKLINKOS_RUNTIME_DIR", None)
        if self.orig_autofill:
            os.environ["BACKLINK_AUTOFILL_RUNTIME"] = self.orig_autofill
        else:
            os.environ.pop("BACKLINK_AUTOFILL_RUNTIME", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_f2_wrong_page_rejected_by_verify_cdp(self):
        """[F2 反例] 标签页虽然 ID 存在，但 URL 被导航到无关网站时，verify_cdp_live_target 必须拒绝。"""
        class CDPFixture(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps([{"id": "ACTUAL_TARGET", "type": "page", "url": "https://unrelated.example/"}]).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args): pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), CDPFixture)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            ok, reason = cycle.verify_cdp_live_target(
                "ACTUAL_TARGET",
                expected_url="https://example.com/challenge",
                cdp_port=server.server_port,
            )
            self.assertFalse(ok)
            self.assertIn("url_mismatch", reason)
        finally:
            server.shutdown()
            server.server_close()

    def test_f4_reuse_preserves_original_observation_timestamp(self):
        """[F4 反例] 冷却期复用旧账本时，保留事实原观察时间，绝不续期刷新。"""
        project, start_ts = "expiry-audit", 1788048000.0
        ledger = self.runtime_dir / "cycles" / project / "scan_ledger.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        calls = []
        def no_entry(domain, **kwargs):
            calls.append(domain)
            return None, "未发现有效入口"
        def run_at(ts):
            with patch.object(master.time, "time", return_value=ts):
                batch = master.prepare_execution_batch(
                    project_id=project,
                    target_ready_count=1,
                    scan_limit=1,
                    project_rows=[{"项目ID": project, "外链ID": "example.com", "外链域名": "example.com", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 2}],
                    master_rows=[{"外链ID": "example.com", "平台域名": "example.com", "提交入口": "", "基础状态": "候选", "_sheet_row_num": 2}],
                    project_context={"ai_powered": False},
                    entry_finder=no_entry,
                    runtime_dir=str(self.runtime_dir),
                )
            with ledger.open("a", encoding="utf-8") as out:
                for entry in batch["scan_ledger_entries"]:
                    out.write(json.dumps(entry) + "\n")
            return batch

        first = run_at(start_ts)
        sixth = run_at(start_ts + 6 * 86400)
        eighth = run_at(start_ts + 8 * 86400)

        self.assertEqual(len(calls), 2, "按原观察时间 7 天冷却期，第 8 天必须执行第 2 次真实网络探测，不可被第 6 天复用续期")

    def test_f4_recovery_verifies_row_identity_and_readback(self):
        """[F4 反例] Master 待恢复项在行移位时先读表核验身份，拒绝向错误行写入。"""
        mutation = {
            "domain": "original.example",
            "row_num": 2,
            "mutation_type": "limits_and_vtime",
            "cell_range": "'外链总表'!A2:M2",
            "expected_limits": "仅限AI工具",
            "expected_vtime": "2026-09-10T10:00:00Z",
        }
        cycle.save_pending_master_mutations("recovery-audit", [mutation], str(self.runtime_dir))
        unrelated = {"外链ID": "unrelated.example", "平台域名": "unrelated.example", "提交入口": "", "基础状态": "候选", "_sheet_row_num": 2}
        service = SheetsMock({("外链总表", 2): [unrelated.get(k, "") for k in master.MASTER_HEADER]})
        remaining = cycle.recover_pending_master_mutations(service, "isolated-sheet", "外链总表", "recovery-audit", str(self.runtime_dir))
        
        self.assertEqual(len(service.writes), 0, "行移位时严禁向错误条目写入数据")
        self.assertEqual(len(remaining), 1, "未核验通过的项必须继续保留在待恢复队列中")

    def test_f4_wrong_nonempty_timestamp_rejected(self):
        """[F4 反例] 首次写回回读核验时，最后验证时间即使非空，若与预期不符必须拦截并保存待恢复项。"""
        class WrongTimeSheets(SheetsMock):
            def batchUpdate(self, spreadsheetId, body):
                reply = super().batchUpdate(spreadsheetId, body)
                self.grids[("外链总表", 2)][master.MASTER_HEADER.index("最后验证时间")] = "2020-01-01T00:00:00Z"
                return reply

        state = cycle.init_cycle_state("time-audit", 5, ["ai.example"], "isolated-sheet", "外链总表", "外链管理", runtime_dir=str(self.runtime_dir))
        mr = {"外链ID": "ai.example", "平台域名": "ai.example", "提交入口": "", "基础状态": "候选", "_sheet_row_num": 2}
        service = WrongTimeSheets({("外链总表", 2): [mr.get(k, "") for k in master.MASTER_HEADER]})
        def ai_finder(domain, **kwargs):
            return master.VerifiedEntry(url=f"https://{domain}/submit", domain=domain, evidence_type="actionable_form", evidence_summary="ISOLATED explicit AI-only fact", ai_only=True), "isolated"

        with patch.object(cycle, "resolve_project_context", return_value={"ai_powered": False}):
            cycle.plan_next_batch(state, [mr], [{"项目ID": "time-audit", "外链ID": "ai.example", "外链域名": "ai.example", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 2}], batch_ready_target=1, batch_scan_limit=1, sheets_service=service, runtime_dir=str(self.runtime_dir), entry_finder=ai_finder)

        pending = cycle.load_pending_master_mutations("time-audit", str(self.runtime_dir))
        self.assertEqual(len(pending), 1, "回读验证时间与预期不符时，必须保留在待恢复队列中")

    def test_f5_slow_drip_homepage_terminates_within_budget(self):
        """[F5 反例] 主页 AI-only 复核面对 slow-drip 慢响应时，严格在硬预算内截断退出。"""
        class SlowBody(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"<html><body>" + b"x" * 300 + b"</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                for offset in range(0, len(body), 10):
                    self.wfile.write(body[offset:offset + 10])
                    self.wfile.flush()
                    if offset + 10 < len(body):
                        time.sleep(0.4)
            def log_message(self, *args): pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), SlowBody)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            def local_fetch(url, timeout=5.0):
                return crawler.fetch_page(f"http://127.0.0.1:{server.server_port}/", timeout=timeout)
            def entry_verified(domain, url, **kwargs):
                return master.VerifiedEntry(url=url, domain=domain, evidence_type="actionable_form", evidence_summary="ISOLATED already verified entry"), "isolated"

            with patch.object(crawler, "OPENER", build_opener(ProxyHandler({}))):
                began = time.monotonic()
                batch = master.prepare_execution_batch(
                    project_id="homepage-budget",
                    target_ready_count=1,
                    scan_limit=1,
                    project_rows=[{"项目ID": "homepage-budget", "外链ID": "example.com", "外链域名": "example.com", "状态": "待提交", "尝试次数": "0", "_sheet_row_num": 2}],
                    master_rows=[{"外链ID": "example.com", "平台域名": "example.com", "提交入口": "https://example.com/submit", "基础状态": "候选", "_sheet_row_num": 2}],
                    project_context={"ai_powered": False},
                    entry_verifier=entry_verified,
                    fetcher=local_fetch,
                    runtime_dir=str(self.runtime_dir),
                )
                elapsed = time.monotonic() - began

            self.assertLess(elapsed, 9.0, f"主页复核耗时 {elapsed:.2f}s 超过了硬预算限制")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()