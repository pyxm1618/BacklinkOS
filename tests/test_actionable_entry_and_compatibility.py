import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import unittest
from screening_crawler import analyze_html
from master_sheet_sync import (
    evaluate_page_for_actionable_entry,
    verify_submission_entry,
    discover_and_verify_entry,
    materialize_project_row,
    MASTER_STATUS_CANDIDATE,
    PROJECT_STATUS_TO_SUBMIT,
)


class ActionableEntryAndCompatibilityTests(unittest.TestCase):
    """
    针对真实 Bounded Hydration 暴露的假阳性与通用兼容性门禁的回归测试
    覆盖 6 点要求：
    1. Actionable Form 最低证据（区分 Listing 资源字段 vs 普通 Contact 表单）
    2. 正文文案仅做 Hint，绝不单凭文本信号通过
    3. CTA Link 追踪，来源页绝不能当 Entry
    4. 跨域 Form Action 拦截
    5. Dashboard 私有控制台保护
    6. 通用 Project Compatibility Hard Gate（如 AI-only 限制 vs 非 AI 项目）
    """

    def test_contact_form_rejected_as_submission_entry(self):
        # 普通联系我们表单：姓名 + 邮箱 + Message + Submit
        # 绝不能被判定为 Directory Listing 或 Actionable Entry
        html = """
        <html>
        <head><title>Contact Us - Example</title></head>
        <body>
            <h1>Contact Support</h1>
            <form action="/contact" method="POST">
                <input type="text" name="name" placeholder="Your Name" />
                <input type="email" name="email" placeholder="Your Email" />
                <textarea name="message" placeholder="Your message here"></textarea>
                <button type="submit">Send Message</button>
            </form>
        </body>
        </html>
        """
        analysis = analyze_html(html, "https://example.com/contact")
        self.assertEqual(len(analysis["actionable_forms"]), 0, "普通 Contact 表单绝不能识别为 actionable_forms！")

        def fake_fetch(url):
            return analysis | {"status": 200, "final_url": "https://example.com/contact"}

        entry_obj, reason = verify_submission_entry("example.com", "https://example.com/contact", fetcher=fake_fetch)
        self.assertIsNone(entry_obj)
        self.assertIn("未检测到真实可操作提交表单", reason)

    def test_directory_listing_form_accepted_with_resource_fields(self):
        # 合法 Directory / Tool Listing 表单：包含 URL/Website 资源字段 + Submit 按钮
        html = """
        <html>
        <head><title>Submit Your Startup - Directory</title></head>
        <body>
            <h1>Submit Tool</h1>
            <form action="/submit" method="POST">
                <input type="text" name="tool_name" placeholder="Tool Name" />
                <input type="url" name="website_url" placeholder="https://..." />
                <input type="email" name="email" placeholder="Contact Email" />
                <button type="submit">Submit Website</button>
            </form>
        </body>
        </html>
        """
        analysis = analyze_html(html, "https://example.com/submit")
        self.assertEqual(len(analysis["actionable_forms"]), 1)
        form = analysis["actionable_forms"][0]
        self.assertEqual(form["form_type"], "directory_listing")
        self.assertIn("website_url", str(form["resource_fields"]))

        def fake_fetch(url):
            return analysis | {"status": 200, "final_url": "https://example.com/submit"}

        entry_obj, reason = verify_submission_entry("example.com", "https://example.com/submit", fetcher=fake_fetch)
        self.assertIsNotNone(entry_obj)
        self.assertEqual(entry_obj.evidence_type, "actionable_form")
        self.assertEqual(entry_obj.form_details["form_type"], "directory_listing")

    def test_guest_post_form_requires_context_and_gp_fields(self):
        # 投稿表单：必须具备 Write For Us 上下文 + 投稿相关字段（pitch/article/draft）
        html_valid = """
        <html>
        <head><title>Write For Us - Guest Post Guidelines</title></head>
        <body>
            <h1>Submit Guest Post Pitch</h1>
            <form action="/guest-post-submit" method="POST">
                <input type="text" name="author_name" />
                <input type="email" name="author_email" />
                <input type="text" name="article_title" placeholder="Proposed Title" />
                <textarea name="pitch_summary" placeholder="Your pitch"></textarea>
                <input type="submit" value="Submit Pitch" />
            </form>
        </body>
        </html>
        """
        analysis_valid = analyze_html(html_valid, "https://example.com/write-for-us")
        self.assertEqual(len(analysis_valid["actionable_forms"]), 1)
        self.assertEqual(analysis_valid["actionable_forms"][0]["form_type"], "guest_post")

        # 缺少投稿上下文但有文章字段，或无文章字段的普通表单，不能误判
        html_invalid = """
        <html>
        <head><title>General Feedback</title></head>
        <body>
            <form action="/feedback" method="POST">
                <input type="text" name="author_name" />
                <textarea name="feedback"></textarea>
                <input type="submit" value="Send" />
            </form>
        </body>
        </html>
        """
        analysis_invalid = analyze_html(html_invalid, "https://example.com/feedback")
        self.assertEqual(len(analysis_invalid["actionable_forms"]), 0)

    def test_cross_domain_form_action_rejected(self):
        # 表单 action 指向外部第三方域名（例如 robuta.com 指向 websitescrawl.com）
        html = """
        <html>
        <body>
            <form action="https://websitescrawl.com/submit-api" method="POST">
                <input type="url" name="site_url" />
                <button type="submit">Submit</button>
            </form>
        </body>
        </html>
        """
        analysis = analyze_html(html, "https://robuta.com/submit")
        self.assertEqual(len(analysis["actionable_forms"]), 0, "跨域 action 必须被过滤排除！")

    def test_search_page_with_query_rejected(self):
        # 搜索结果页面（URL 带有 ?q= 或标题为 Search Results）即使包含机制词也坚决拒绝
        html = """
        <html>
        <head><title>Search results for submit tool</title></head>
        <body>
            <p>Results showing tools that allow you to submit website.</p>
        </body>
        </html>
        """
        analysis = analyze_html(html, "https://breachviews.com/search?q=submit+directory")
        self.assertTrue(analysis["is_search_page"])

        def fake_fetch(url):
            return analysis | {"status": 200, "final_url": "https://breachviews.com/search?q=submit+directory"}

        entry_obj, reason = verify_submission_entry("breachviews.com", "https://breachviews.com/search?q=submit+directory", fetcher=fake_fetch)
        self.assertIsNone(entry_obj)
        self.assertIn("搜索结果页", reason)

    def test_text_only_signals_in_article_rejected(self):
        # 普通文章/SEO 软文提及 "guest post"、"submit your product"，但无表单
        html = """
        <html>
        <head><title>10 Ways to submit product to directories in 2026</title></head>
        <body>
            <p>You can write for us or submit website to high DA platforms to gain backlinks.</p>
        </body>
        </html>
        """
        analysis = analyze_html(html, "https://parse.gl/blog/seo-tips")
        self.assertTrue(len(analysis["mechanism_signals"]) > 0)
        self.assertEqual(len(analysis["actionable_forms"]), 0)

        def fake_fetch(url):
            return analysis | {"status": 200, "final_url": "https://parse.gl/blog/seo-tips"}

        entry_obj, reason = verify_submission_entry("parse.gl", "https://parse.gl/blog/seo-tips", fetcher=fake_fetch)
        self.assertIsNone(entry_obj)
        self.assertIn("未检测到真实可操作提交表单", reason)

    def test_cta_link_tracking_uses_target_page_never_source_page(self):
        # 来源页面包含 "Submit Tool" CTA 按钮，来源页本身绝不能当 Entry！
        # 必须跟随打开目标页，只有目标页有表单时才作为 Entry
        homepage_html = """
        <html>
        <head><title>AI Tools Hub</title></head>
        <body>
            <header>
                <a href="/submit-tool" class="btn">Submit Tool</a>
            </header>
            <main>Welcome to AI Tools Hub</main>
        </body>
        </html>
        """
        target_html = """
        <html>
        <head><title>Submit Your Tool</title></head>
        <body>
            <form action="/submit-tool" method="POST">
                <input type="url" name="tool_url" />
                <button type="submit">Submit</button>
            </form>
        </body>
        </html>
        """
        def fake_fetch(url):
            if url == "https://hub.example.com/":
                return analyze_html(homepage_html, "https://hub.example.com/") | {"status": 200, "final_url": "https://hub.example.com/"}
            if url == "https://hub.example.com/submit-tool":
                return analyze_html(target_html, "https://hub.example.com/submit-tool") | {"status": 200, "final_url": "https://hub.example.com/submit-tool"}
            return {"status": 404}

        entry_obj, reason = discover_and_verify_entry("hub.example.com", fetcher=fake_fetch)
        self.assertIsNotNone(entry_obj)
        self.assertEqual(entry_obj.url, "https://hub.example.com/submit-tool", "VerifiedEntry 必须是目标表单页面，绝不能是来源页！")
        self.assertNotEqual(entry_obj.url, "https://hub.example.com/")

    def test_dashboard_redirect_without_submission_context_rejected(self):
        # 请求提交路径却重定向到纯控制台 /dashboard，被拒绝
        def fake_fetch(url):
            return {
                "status": 200,
                "final_url": "https://platform.com/app/dashboard",
                "actionable_forms": [],
            }
        entry_obj, reason = verify_submission_entry("platform.com", "https://platform.com/submit", fetcher=fake_fetch)
        self.assertIsNone(entry_obj)
        self.assertIn("私有控制台", reason)

    def test_project_compatibility_hard_gate_blocks_ai_only_for_non_ai_project(self):
        # 平台具有强 AI-only 约束，项目为 non-ai (ai_powered=False)
        ai_platform_html = """
        <html>
        <head><title>AI Tools Directory - Submit AI Tool</title></head>
        <body>
            <p>Notice: Only AI products, AI tools and artificial intelligence startups are accepted.</p>
            <form action="/submit" method="POST">
                <input type="url" name="product_url" />
                <button type="submit">Submit AI Tool</button>
            </form>
        </body>
        </html>
        """
        def fake_fetch(url):
            if url == "https://only-ai.com/submit":
                return analyze_html(ai_platform_html, "https://only-ai.com/submit") | {"status": 200, "final_url": "https://only-ai.com/submit"}
            return {"status": 404}

        master_row = {
            "外链ID": "only-ai.com",
            "平台域名": "only-ai.com",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "提交入口": "https://only-ai.com/submit",
        }

        # 1. 针对 non-ai 项目（如 quick-iching），物化必须被拦截！
        prow_non_ai = materialize_project_row(
            master_row=master_row,
            existing_project_rows=[],
            project_id="quick-iching",
            project_context={"ai_powered": False},
            fetcher=fake_fetch,
        )
        self.assertIsNone(prow_non_ai, "强 AI-only 平台必须被 Project Compatibility Gate 拒绝物化进 non-ai 项目待提交队列！")

        # 2. 针对 ai-powered 项目（如 ai-agent-builder），物化应当允许通过
        prow_ai = materialize_project_row(
            master_row=master_row,
            existing_project_rows=[],
            project_id="ai-agent-project",
            project_context={"ai_powered": True},
            fetcher=fake_fetch,
        )
        self.assertIsNotNone(prow_ai, "AI-powered 项目应正常物化 AI 平台！")
        self.assertEqual(prow_ai["状态"], PROJECT_STATUS_TO_SUBMIT)

    def test_general_platform_allowed_for_non_ai_project(self):
        # 通用无 AI 强约束平台，non-ai 项目正常通行
        general_html = """
        <html>
        <head><title>Web Directory - Submit Website</title></head>
        <body>
            <p>Submit your website, blog or business listing.</p>
            <form action="/submit" method="POST">
                <input type="url" name="website_url" />
                <button type="submit">Submit</button>
            </form>
        </body>
        </html>
        """
        def fake_fetch(url):
            if url == "https://general-dir.com/submit":
                return analyze_html(general_html, "https://general-dir.com/submit") | {"status": 200, "final_url": "https://general-dir.com/submit"}
            return {"status": 404}

        master_row = {
            "外链ID": "general-dir.com",
            "平台域名": "general-dir.com",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "提交入口": "https://general-dir.com/submit",
        }

        prow = materialize_project_row(
            master_row=master_row,
            existing_project_rows=[],
            project_id="quick-iching",
            project_context={"ai_powered": False},
            fetcher=fake_fetch,
        )
        self.assertIsNotNone(prow)
        self.assertEqual(prow["状态"], PROJECT_STATUS_TO_SUBMIT)

    def test_homepage_text_submit_your_tool_without_href_or_form_is_rejected(self):
        # 1. 删除 homepage text-only fallback:
        # 首页只有 "Submit your tool" 等正文文案，但没有可操作 form，也没有结构化可跟随的 CTA 链接
        # 坚决拒绝 (REJECT)，禁止生成 homepage_cta VerifiedEntry 作为生产准入！
        html = """
        <html>
        <head><title>Awesome Directory</title></head>
        <body>
            <h1>Welcome to Awesome Directory</h1>
            <p>You can submit your tool to reach 100k users! Check back soon for submissions.</p>
        </body>
        </html>
        """
        def fake_fetch(url):
            return analyze_html(html, "https://textonly.com/") | {"status": 200, "final_url": "https://textonly.com/"}

        # 直接验证首页
        entry_v, reason_v = verify_submission_entry("textonly.com", "https://textonly.com/", fetcher=fake_fetch)
        self.assertIsNone(entry_v, "首页仅有文本文案无表单/CTA链接，必须坚决拒绝！")
        self.assertIn("无 Actionable Form", reason_v)

        # 发现流程验证首页
        entry_d, reason_d = discover_and_verify_entry("textonly.com", fetcher=fake_fetch)
        self.assertIsNone(entry_d, "探测流程遇到纯正文首页，必须返回 None 保持候选，绝不能升级为 homepage_cta！")
        self.assertIn("无 Actionable Form", reason_d)

    def test_actionable_form_submit_intent_tightening(self):
        # 2. 收紧 Actionable Form submit intent：
        # Directory/listing form 必须同时具备 resource identity field + 真实 submission intent
        # 明确拒绝 checker intent (check, analyze, scan, search 等)

        # A. URL input + <button>Analyze</button> -> REJECT
        html_analyze = """
        <html>
        <body>
            <form action="/analyze" method="POST">
                <input type="url" name="website_url" />
                <button type="submit">Analyze</button>
            </form>
        </body>
        </html>
        """
        analysis_analyze = analyze_html(html_analyze, "https://checker.com/analyze")
        self.assertEqual(len(analysis_analyze["actionable_forms"]), 0, "Analyze 按钮属于 checker intent，必须被排除！")

        def fake_fetch_analyze(url):
            return analysis_analyze | {"status": 200, "final_url": "https://checker.com/analyze"}
        entry_analyze, _ = verify_submission_entry("checker.com", "https://checker.com/analyze", fetcher=fake_fetch_analyze)
        self.assertIsNone(entry_analyze, "带 Analyze 按钮的分析表单绝不能作为提交入口！")

        # B. website input + <input type=submit value="Check"> -> REJECT
        html_check = """
        <html>
        <body>
            <form action="/check" method="POST">
                <input type="text" name="site_url" />
                <input type="submit" value="Check" />
            </form>
        </body>
        </html>
        """
        analysis_check = analyze_html(html_check, "https://checker.com/check")
        self.assertEqual(len(analysis_check["actionable_forms"]), 0, "Check 按钮属于 checker intent，必须被排除！")

        def fake_fetch_check(url):
            return analysis_check | {"status": 200, "final_url": "https://checker.com/check"}
        entry_check, _ = verify_submission_entry("checker.com", "https://checker.com/check", fetcher=fake_fetch_check)
        self.assertIsNone(entry_check, "带 Check 按钮的检查表单绝不能作为提交入口！")

        # C. website_url + <button>Submit Website</button> -> PASS
        html_submit = """
        <html>
        <body>
            <form action="/submit" method="POST">
                <input type="url" name="website_url" />
                <button type="submit">Submit Website</button>
            </form>
        </body>
        </html>
        """
        analysis_submit = analyze_html(html_submit, "https://good-dir.com/submit")
        self.assertEqual(len(analysis_submit["actionable_forms"]), 1, "合法 submission intent 按钮必须正常识别！")

        def fake_fetch_submit(url):
            return analysis_submit | {"status": 200, "final_url": "https://good-dir.com/submit"}
        entry_submit, _ = verify_submission_entry("good-dir.com", "https://good-dir.com/submit", fetcher=fake_fetch_submit)
        self.assertIsNotNone(entry_submit)
        self.assertEqual(entry_submit.evidence_type, "actionable_form")

    def test_project_compatibility_aggregates_homepage_ai_only_signals_for_existing_master_entry(self):
        # 3. Project Compatibility 聚合平台约束：
        # 场景：
        # homepage = "Only AI tools accepted"
        # existing Master entry = /submit
        # /submit 有正常 actionable form 但不含 AI-only 文案
        homepage_html = """
        <html>
        <head><title>AI Platform Home</title></head>
        <body>
            <h1>AI Hub</h1>
            <p>Notice: Only AI tools accepted. Non-AI tools are rejected.</p>
        </body>
        </html>
        """
        submit_page_html = """
        <html>
        <head><title>Submit Page</title></head>
        <body>
            <h1>Submit Tool</h1>
            <form action="/submit" method="POST">
                <input type="url" name="tool_url" />
                <button type="submit">Submit Tool</button>
            </form>
        </body>
        </html>
        """
        def fake_fetch(url):
            if url == "https://ai-directory.com/":
                return analyze_html(homepage_html, "https://ai-directory.com/") | {"status": 200, "final_url": "https://ai-directory.com/"}
            if url == "https://ai-directory.com/submit":
                return analyze_html(submit_page_html, "https://ai-directory.com/submit") | {"status": 200, "final_url": "https://ai-directory.com/submit"}
            return {"status": 404}

        master_row = {
            "外链ID": "ai-directory.com",
            "平台域名": "ai-directory.com",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "提交入口": "https://ai-directory.com/submit",  # existing Master entry
        }

        # Case 1: project ai_powered=False -> NO MATERIALIZATION
        prow_non_ai = materialize_project_row(
            master_row=master_row,
            existing_project_rows=[],
            project_id="test-non-ai-project",
            project_context={"ai_powered": False},
            fetcher=fake_fetch,
        )
        self.assertIsNone(prow_non_ai, "首页声明了 AI-only，非 AI 项目绝不能物化！")

        # Case 2: 同样场景 ai_powered=True -> PASS
        prow_ai = materialize_project_row(
            master_row=master_row,
            existing_project_rows=[],
            project_id="test-ai-project",
            project_context={"ai_powered": True},
            fetcher=fake_fetch,
        )
        self.assertIsNotNone(prow_ai, "显式声明 ai_powered=True 应正常物化！")
        self.assertEqual(prow_ai["状态"], PROJECT_STATUS_TO_SUBMIT)

        # Case 3: 同样场景 ai_powered missing/unknown -> NO MATERIALIZATION (fail closed)
        prow_missing_ai = materialize_project_row(
            master_row=master_row,
            existing_project_rows=[],
            project_id="test-unknown-project",
            project_context={},  # ai_powered missing!
            fetcher=fake_fetch,
        )
        self.assertIsNone(prow_missing_ai, "ai_powered 缺失时必须 fail closed 拒绝物化！")


if __name__ == "__main__":
    unittest.main()
