import unittest
from unittest.mock import patch
from scripts.screening_crawler import analyze_html
from scripts.master_sheet_sync import (
    verify_submission_entry,
    prepare_execution_batch,
    VerifiedEntry,
)


class TestAuthRevalidation(unittest.TestCase):
    """测试问题 4: 登录型 Entry 第一次合法，保存以后二次核验通过来源重建仍合法。"""

    def setUp(self):
        self.domain = "authtest.com"
        self.entry_url = "https://authtest.com/submit"
        self.login_url = "https://authtest.com/login?redirect=/submit"

    def test_a_persisted_auth_entry_revalidates_via_homepage_cta(self):
        """测试 A: Homepage CTA -> /submit -> /login?redirect=/submit
        首次发现 Ready=1，保存到 Master 以后，第二次直接 revalidate /submit 仍为 Ready=1。
        """
        def fake_fetcher(url: str) -> dict:
            norm_url = url.split("?")[0].rstrip("/")
            if norm_url in ("https://authtest.com", "http://authtest.com", "https://authtest.com/"):
                return {
                    "status": 200,
                    "final_url": "https://authtest.com/",
                    "actionable_forms": [],
                    "submission_cta_links": [{"url": "https://authtest.com/submit", "text": "Submit Your Tool"}],
                    "ai_only_signals": [],
                }
            elif norm_url == "https://authtest.com/submit":
                return {
                    "status": 200,
                    "final_url": self.login_url,
                    "actionable_forms": [],
                    "submission_cta_links": [],
                    "ai_only_signals": [],
                }
            return {"status": 404, "final_url": url}

        # 首次现场探测 (从首页发现)
        master_rows_initial = [
            {"外链ID": self.domain, "平台域名": self.domain, "基础状态": "候选", "提交入口": ""},
        ]
        project_rows = [
            {"项目ID": "proj-auth", "外链ID": self.domain, "外链域名": self.domain, "状态": "待提交", "尝试次数": "0"},
        ]

        batch1 = prepare_execution_batch(
            master_rows=master_rows_initial,
            project_rows=project_rows,
            project_id="proj-auth",
            target_ready_count=1,
            scan_limit=2,
            fetcher=fake_fetcher,
            use_cursor=False,
        )
        self.assertEqual(batch1["ready_count"], 1)
        saved_entry = batch1["ready_rows"][0]["verified_entry"].url
        self.assertEqual(saved_entry, self.entry_url)

        # 第二次: Master 中已保存该 entry_url，直接 Live Revalidate 该 entry
        master_rows_persisted = [
            {"外链ID": self.domain, "平台域名": self.domain, "基础状态": "候选", "提交入口": saved_entry},
        ]
        batch2 = prepare_execution_batch(
            master_rows=master_rows_persisted,
            project_rows=project_rows,
            project_id="proj-auth",
            target_ready_count=1,
            scan_limit=2,
            fetcher=fake_fetcher,
            use_cursor=False,
        )
        self.assertEqual(batch2["ready_count"], 1)
        self.assertEqual(batch2["ready_rows"][0]["verified_entry"].url, self.entry_url)

    def test_b_direct_guess_submit_without_homepage_cta_fails_closed(self):
        """测试 B: 直接猜 /submit，首页无此 CTA，必须 fail closed (拒绝通过)"""
        def fake_fetcher(url: str) -> dict:
            norm_url = url.split("?")[0].rstrip("/")
            if norm_url in ("https://authtest.com", "http://authtest.com", "https://authtest.com/"):
                return {
                    "status": 200,
                    "final_url": "https://authtest.com/",
                    "actionable_forms": [],
                    # 首页没有任何提交 CTA
                    "submission_cta_links": [],
                    "ai_only_signals": [],
                }
            elif norm_url == "https://authtest.com/submit":
                return {
                    "status": 200,
                    "final_url": "https://authtest.com/login?redirect=/submit",
                    "actionable_forms": [],
                    "submission_cta_links": [],
                    "ai_only_signals": [],
                }
            return {"status": 404, "final_url": url}

        verified, reason = verify_submission_entry(
            domain=self.domain,
            entry_url="https://authtest.com/submit",
            fetcher=fake_fetcher,
            is_discovered_candidate=False,
        )
        self.assertIsNone(verified)
        self.assertIn("来源", reason)

    def test_c_auth_callback_cross_domain_rejected(self):
        """测试 C: auth callback 跨域到外部网站，必须坚决拒绝"""
        def fake_fetcher(url: str) -> dict:
            return {
                "status": 200,
                "final_url": "https://authtest.com/login?redirect=https://evil.com/submit",
                "actionable_forms": [],
                "submission_cta_links": [],
                "ai_only_signals": [],
            }

        verified, reason = verify_submission_entry(
            domain=self.domain,
            entry_url="https://authtest.com/submit",
            fetcher=fake_fetcher,
            is_discovered_candidate=True,
        )
        self.assertIsNone(verified)
        self.assertIn("跨域", reason)

    def test_d_callback_to_pricing_or_non_submission_rejected(self):
        """测试 D: callback 指向 pricing/非提交页，必须坚决拒绝"""
        def fake_fetcher(url: str) -> dict:
            return {
                "status": 200,
                "final_url": "https://authtest.com/login?redirect=/pricing",
                "actionable_forms": [],
                "submission_cta_links": [],
                "ai_only_signals": [],
            }

        verified, reason = verify_submission_entry(
            domain=self.domain,
            entry_url="https://authtest.com/submit",
            fetcher=fake_fetcher,
            is_discovered_candidate=True,
        )
        self.assertIsNone(verified)
        self.assertIn("排除路径", reason)


class TestFormClassificationAndHostedForms(unittest.TestCase):
    """测试问题 5: signup + submission 组合表单识别与 hosted form 来源保障。"""

    def test_a_login_email_password_excluded(self):
        """测试 A: 纯登录表单 (email + password + Log in) 仍排除"""
        html = """
        <html>
        <body>
            <form action="/login" method="POST">
                <input type="email" name="email" placeholder="Your Email">
                <input type="password" name="password" placeholder="Your Password">
                <button type="submit">Log in</button>
            </form>
        </body>
        </html>
        """
        res = analyze_html(html, "https://mysite.com/login")
        self.assertEqual(len(res["actionable_forms"]), 0)

    def test_b_signup_submission_combo_identified(self):
        """测试 B: signup + submission (name, email, password, website, submit your site) 正确识别"""
        html = """
        <html>
        <body>
            <form action="/register" method="POST">
                <input type="text" name="name" placeholder="Founder Name">
                <input type="email" name="email" placeholder="Email">
                <input type="password" name="password" placeholder="Create Password">
                <input type="url" name="website" placeholder="Product Website URL">
                <textarea name="description" placeholder="Short description of your product"></textarea>
                <button type="submit">Submit your site</button>
            </form>
        </body>
        </html>
        """
        res = analyze_html(html, "https://mysite.com/submit")
        self.assertEqual(len(res["actionable_forms"]), 1)
        form = res["actionable_forms"][0]
        self.assertIn("website", form["resource_fields"])
        self.assertTrue(any("submit your site" in c.lower() for c in form["submit_controls"]))

    def test_c_password_plus_search_not_misidentified(self):
        """测试 C: password + 搜索框 不误识别"""
        html = """
        <html>
        <body>
            <form action="/search" method="GET">
                <input type="password" name="auth_token" placeholder="Secret Key">
                <input type="search" name="q" placeholder="Search tools...">
                <button type="submit">Search</button>
            </form>
        </body>
        </html>
        """
        res = analyze_html(html, "https://mysite.com/search")
        self.assertEqual(len(res["actionable_forms"]), 0)


if __name__ == "__main__":
    unittest.main()
