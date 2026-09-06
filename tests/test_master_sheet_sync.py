import os
import sys
import unittest
from pathlib import Path

# 保证 scripts 路径在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from master_sheet_sync import (
    MASTER_HEADER,
    MASTER_STATUS_CANDIDATE,
    MASTER_STATUS_DEAD,
    MASTER_STATUS_EXCLUDED,
    PROJECT_HEADER,
    PROJECT_STATUS_TO_SUBMIT,
    PROTECTED_FACT_COLUMNS,
    VerifiedEntry,
    batch_hydrate_candidates,
    canonical_domain,
    discover_and_verify_entry,
    materialize_project_row,
    submission_entry_policy_guard,
    upsert_master_rows,
    verify_homepage_as_entry,
    verify_submission_entry,
)


class CanonicalDomainTests(unittest.TestCase):
    def test_canonicalizes_protocols_and_www(self):
        self.assertEqual(canonical_domain("https://www.example.com/"), "example.com")
        self.assertEqual(canonical_domain("http://example.com/some/path?q=1#frag"), "example.com")
        self.assertEqual(canonical_domain("WWW.SUB.EXAMPLE.COM/"), "sub.example.com")

    def test_canonicalizes_raw_domains_and_ports(self):
        self.assertEqual(canonical_domain("example.com:8080"), "example.com")
        self.assertEqual(canonical_domain("   my-site.org/index.html   "), "my-site.org")
        self.assertEqual(canonical_domain(""), "")


class MasterSheetUpsertTests(unittest.TestCase):
    def test_new_domain_creates_candidate(self):
        existing = []
        new_items = [{
            "referring_domain": "https://newsite.com/path",
            "discovery_source": "semrush_competitor:toolify",
            "discovery_time": "2026-09-06T12:00:00Z",
        }]
        merged, stats = upsert_master_rows(existing, new_items)
        self.assertEqual(len(merged), 1)
        self.assertEqual(stats["new_inserted"], 1)
        row = merged[0]
        self.assertEqual(row["外链ID"], "newsite.com")
        self.assertEqual(row["平台域名"], "newsite.com")
        self.assertEqual(row["基础状态"], MASTER_STATUS_CANDIDATE)
        self.assertEqual(row["发现来源"], "semrush_competitor:toolify")
        self.assertEqual(row["发现时间"], "2026-09-06T12:00:00Z")
        self.assertEqual(row["提交入口"], "")

    def test_new_discovery_string_submission_entry_remains_empty_in_master_row(self):
        # P0-1 严格守卫：new_discoveries 携带普通字符串 submission_entry，但无 live verification evidence
        # 预期：新 master row.提交入口 == ""
        existing = []
        new_items = [{
            "referring_domain": "example.com",
            "submission_entry": "https://example.com/submit",
            "discovery_source": "semrush_competitor",
        }]
        merged, stats = upsert_master_rows(existing, new_items)
        self.assertEqual(len(merged), 1)
        self.assertEqual(stats["new_inserted"], 1)
        self.assertEqual(
            merged[0]["提交入口"], "",
            "禁止任何未经 live verification 的字符串 URL 进入提交入口！"
        )

    def test_forged_verified_entry_cannot_write_submission_entry_via_upsert(self):
        # 回归测试：即便外部手工伪造 VerifiedEntry 传入 new_items，upsert 也绝对不写入提交入口！
        forged_entry = VerifiedEntry(
            url="https://forged.com/submit",
            domain="forged.com",
            evidence_type="subpage_mechanism",
            evidence_summary="forged",
        )
        existing = []
        new_items = [{
            "referring_domain": "forged.com",
            "verified_entry": forged_entry,
            "submission_entry": "https://forged.com/submit",
            "discovery_source": "toolify",
        }]
        merged, stats = upsert_master_rows(existing, new_items)
        self.assertEqual(len(merged), 1)
        self.assertEqual(
            merged[0]["提交入口"], "",
            "upsert_master_rows 彻底禁止写入提交入口，即便是 VerifiedEntry 也必须保持为空！"
        )

    def test_existing_domain_not_duplicated(self):
        existing = [{
            "外链ID": "existing.com",
            "平台域名": "existing.com",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "发现来源": "old_run",
            "发现时间": "2026-08-01",
        }]
        new_items = [{
            "domain": "https://www.existing.com/page",
            "discovery_source": "new_run",
        }]
        merged, stats = upsert_master_rows(existing, new_items)
        self.assertEqual(len(merged), 1)
        self.assertEqual(stats["new_inserted"], 0)
        self.assertEqual(stats["existing_preserved"], 1)
        self.assertEqual(merged[0]["外链ID"], "existing.com")

    def test_existing_verified_facts_not_overwritten(self):
        existing = [{
            "外链ID": "verified.com",
            "平台域名": "verified.com",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "实测免费": "是",
            "实测需登录": "是",
            "实测登录方式": "Google",
            "实测限制": "每日1次",
            "实测链接属性": "Follow",
            "最后验证时间": "2026-08-20",
        }]
        new_items = [{
            "domain": "verified.com",
            "实测免费": "否",
            "实测链接属性": "Nofollow",
        }]
        merged, _ = upsert_master_rows(existing, new_items)
        row = merged[0]
        self.assertEqual(row["实测免费"], "是")
        self.assertEqual(row["实测需登录"], "是")
        self.assertEqual(row["实测登录方式"], "Google")
        self.assertEqual(row["实测限制"], "每日1次")
        self.assertEqual(row["实测链接属性"], "Follow")
        self.assertEqual(row["最后验证时间"], "2026-08-20")

    def test_excluded_status_not_reactivated_to_candidate(self):
        existing = [{
            "外链ID": "spam-site.com",
            "平台域名": "spam-site.com",
            "基础状态": MASTER_STATUS_EXCLUDED,
            "基础排除原因": "垃圾/PBN/负面SEO",
        }]
        new_items = [{"domain": "spam-site.com", "discovery_source": "new_competitor"}]
        merged, stats = upsert_master_rows(existing, new_items)
        self.assertEqual(len(merged), 1)
        self.assertEqual(stats["skipped_excluded_or_dead"], 1)
        self.assertEqual(merged[0]["基础状态"], MASTER_STATUS_EXCLUDED)
        self.assertEqual(merged[0]["基础排除原因"], "垃圾/PBN/负面SEO")

    def test_dead_status_not_reactivated_to_candidate(self):
        existing = [{
            "外链ID": "dead-domain.com",
            "平台域名": "dead-domain.com",
            "基础状态": MASTER_STATUS_DEAD,
            "基础排除原因": "已失效",
        }]
        new_items = [{"domain": "dead-domain.com"}]
        merged, stats = upsert_master_rows(existing, new_items)
        self.assertEqual(stats["skipped_excluded_or_dead"], 1)
        self.assertEqual(merged[0]["基础状态"], MASTER_STATUS_DEAD)
        self.assertEqual(merged[0]["基础排除原因"], "已失效")

    def test_safe_provenance_information_complemented(self):
        existing = [{
            "外链ID": "prov.com",
            "平台域名": "prov.com",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "发现来源": "",
            "发现时间": "",
        }]
        new_items = [{
            "domain": "prov.com",
            "discovery_source": "toolify_batch_2",
            "discovery_time": "2026-09-06",
        }]
        merged, stats = upsert_master_rows(existing, new_items)
        self.assertEqual(stats["existing_updated"], 1)
        self.assertEqual(merged[0]["发现来源"], "toolify_batch_2")
        self.assertEqual(merged[0]["发现时间"], "2026-09-06")


class SubmissionEntryPolicyGuardAndDiscoveryTests(unittest.TestCase):
    def test_valid_submit_url_passes_guard(self):
        allowed, reason = submission_entry_policy_guard("https://example.com/submit-site", domain="example.com")
        self.assertTrue(allowed)
        self.assertIn("通过", reason)

        allowed, reason = submission_entry_policy_guard("https://example.com/s/new", domain="example.com")
        self.assertTrue(allowed)

    def test_disallowed_paths_blocked_by_guard(self):
        # pricing
        allowed, _ = submission_entry_policy_guard("https://example.com/pricing", domain="example.com")
        self.assertFalse(allowed)
        # terms / privacy
        allowed, _ = submission_entry_policy_guard("https://example.com/terms-of-service", domain="example.com")
        self.assertFalse(allowed)
        allowed, _ = submission_entry_policy_guard("https://example.com/privacy-policy", domain="example.com")
        self.assertFalse(allowed)
        # category / tags
        allowed, _ = submission_entry_policy_guard("https://example.com/category/latest-news", domain="example.com")
        self.assertFalse(allowed)
        # seo report
        allowed, _ = submission_entry_policy_guard("https://example.com/seo-report/run", domain="example.com")
        self.assertFalse(allowed)

    def test_cross_domain_entry_blocked_by_guard(self):
        allowed, reason = submission_entry_policy_guard("https://othersite.com/submit", domain="mysite.com")
        self.assertFalse(allowed)
        self.assertIn("跨域", reason)

    def test_homepage_cannot_blindly_serve_as_entry_without_explicit_cta(self):
        home_without_cta = {
            "title": "Welcome to our tool directory",
            "text_excerpt": "Here are 100 interesting tools you can use.",
        }
        allowed, reason = verify_homepage_as_entry(home_without_cta)
        self.assertFalse(allowed)
        self.assertIn("未包含明确", reason)

        home_with_cta = {
            "title": "Directory Home",
            "text_excerpt": "Submit your tool today to reach 50,000 users. Or explore listings.",
        }
        allowed, reason = verify_homepage_as_entry(home_with_cta)
        self.assertTrue(allowed)
        self.assertIn("包含明确提交 CTA", reason)

    def test_p0_1_submit_url_with_200_but_no_mechanism_is_rejected(self):
        # P0-1 核心：/submit 返回 HTTP 200，但 mechanism_signals 为空且为普通文章内容，必须坚决拒绝！
        def fake_fetch(url):
            if url == "https://plain-site.com/":
                return {
                    "status": 200,
                    "final_url": "https://plain-site.com/",
                    "candidate_urls": ["https://plain-site.com/submit"],
                    "mechanism_signals": [],
                    "noindex": False,
                }
            if url == "https://plain-site.com/submit":
                return {
                    "status": 200,
                    "final_url": "https://plain-site.com/submit",
                    "mechanism_signals": [],  # 没有真实机制信号！
                    "noindex": False,
                    "title": "Submit Page",
                    "text_excerpt": "This is a generic page with some text.",
                }
            return {"status": 404}

        entry_obj, reason = discover_and_verify_entry("plain-site.com", fetcher=fake_fetch)
        self.assertIsNone(entry_obj, "没有机制信号的 /submit 页面绝不得被升级为 verified entry！")
        self.assertIn("证据缺失", reason)

    def test_p1_auth_wall_with_noindex_is_accepted_when_mechanism_present(self):
        # P1 核心：登录/注册墙（/login）带 noindex 是正常的，若存在机制信号，绝不能被当作不可索引误杀
        def fake_fetch_auth(url):
            if url == "https://auth-site.com/":
                return {
                    "status": 200,
                    "final_url": "https://auth-site.com/",
                    "candidate_urls": ["https://auth-site.com/login?redirect=/submit"],
                    "mechanism_signals": [],
                    "noindex": False,
                }
            if url == "https://auth-site.com/login?redirect=/submit":
                return {
                    "status": 200,
                    "final_url": "https://auth-site.com/login?redirect=/submit",
                    "mechanism_signals": ["submit your project"],  # 机制明确
                    "noindex": True,  # 登录墙正常 noindex
                }
            return {"status": 404}

        entry_obj, reason = discover_and_verify_entry("auth-site.com", fetcher=fake_fetch_auth)
        self.assertIsNotNone(entry_obj, "认证墙有效机制入口不应因 noindex 被误杀")
        self.assertEqual(entry_obj.evidence_type, "auth_wall_submission")
        self.assertEqual(entry_obj.url, "https://auth-site.com/login?redirect=/submit")

    def test_p0_3_verify_submission_entry_rejects_redirect_to_pricing(self):
        # P0-3: example.com/submit -> redirect example.com/pricing -> reject
        def fake_fetch(url):
            return {
                "status": 200,
                "final_url": "https://example.com/pricing",
                "mechanism_signals": ["submit a tool"],
            }
        entry_obj, reason = verify_submission_entry("example.com", "https://example.com/submit", fetcher=fake_fetch)
        self.assertIsNone(entry_obj, "重定向到 /pricing 的入口必须被 Policy Guard 坚决拒绝！")
        self.assertIn("未通过 Policy Guard", reason)

    def test_p0_3_verify_submission_entry_rejects_redirect_to_thirdparty(self):
        # P0-3: example.com/submit -> redirect thirdparty.com/form -> reject
        def fake_fetch(url):
            return {
                "status": 200,
                "final_url": "https://thirdparty.com/form",
                "mechanism_signals": ["submit a tool"],
            }
        entry_obj, reason = verify_submission_entry("example.com", "https://example.com/submit", fetcher=fake_fetch)
        self.assertIsNone(entry_obj, "重定向到跨域域名的入口必须被 Policy Guard 坚决拒绝！")
        self.assertIn("跨域", reason)

    def test_p1_4_submission_entry_with_noindex_is_accepted_when_mechanism_present(self):
        # P1-4: https://example.com/submit, HTTP 200, mechanism_signals = ["submit your product"], noindex = true
        # 预期: Verified Entry (提交表单页面的 indexability 不作为淘汰条件)
        def fake_fetch(url):
            return {
                "status": 200,
                "final_url": "https://example.com/submit",
                "mechanism_signals": ["submit your product"],
                "noindex": True,
            }
        entry_obj, reason = verify_submission_entry("example.com", "https://example.com/submit", fetcher=fake_fetch)
        self.assertIsNotNone(entry_obj, "Entry 页面本身不应因标记 noindex 被筛掉！")
        self.assertEqual(entry_obj.url, "https://example.com/submit")
        self.assertEqual(entry_obj.evidence_type, "subpage_mechanism")
        self.assertIn("现场核验通过", reason)

    def test_p1_5_auth_wall_submission_with_redirect_callback_is_verified(self):
        # P1-5: 请求 example.com/submit，跳到 example.com/login?redirect=/submit
        # 登录页本身未再写机制文案，但保留了原始 candidate 请求 + auth wall + 回调参数的完整事实链
        # 验证保留原始稳定 submission URL（不是带 query 的 login URL）
        def fake_fetch(url):
            return {
                "status": 200,
                "final_url": "https://example.com/login?redirect=%2Fsubmit",
                "mechanism_signals": [],  # 登录页通常仅有 Sign In 文案
                "noindex": True,
            }
        entry_obj, reason = verify_submission_entry(
            "example.com",
            "https://example.com/submit",
            fetcher=fake_fetch,
            is_discovered_candidate=True,
        )
        self.assertIsNotNone(entry_obj, "包含明确回跳提交参数的认证墙应当作为有效入口核验通过！")
        self.assertEqual(entry_obj.url, "https://example.com/submit", "必须保留原始稳定 submission URL！")
        self.assertEqual(entry_obj.evidence_type, "auth_wall_submission")
        self.assertIn("认证墙", reason)

    def test_guessed_submit_with_auth_callback_is_rejected_without_candidate_evidence(self):
        # 盲猜 /submit（无页面 CTA/link 发现证据），即使触发 auth callback 也坚决拒绝！
        def fake_fetch(url):
            return {
                "status": 200,
                "final_url": "https://guessed.com/login?redirect=%2Fsubmit",
                "mechanism_signals": [],
            }
        entry_obj, reason = verify_submission_entry(
            "guessed.com",
            "https://guessed.com/submit",
            fetcher=fake_fetch,
            is_discovered_candidate=False,
        )
        self.assertIsNone(entry_obj, "盲猜 /submit 触发 auth callback 仍然不够，必须拒绝！")
        self.assertIn("缺乏真实页面发现", reason)

    def test_discovered_candidate_submit_with_auth_callback_is_verified(self):
        # 真实 homepage 发现的 candidate /submit + auth callback 可以通过
        def fake_fetch(url):
            if url == "https://discovered-site.com/":
                return {
                    "status": 200,
                    "final_url": "https://discovered-site.com/",
                    "candidate_urls": ["https://discovered-site.com/submit"],
                    "mechanism_signals": [],
                }
            if url == "https://discovered-site.com/submit":
                return {
                    "status": 200,
                    "final_url": "https://discovered-site.com/login?redirect=%2Fsubmit",
                    "mechanism_signals": [],
                }
            return {"status": 404}

        entry_obj, reason = discover_and_verify_entry("discovered-site.com", fetcher=fake_fetch)
        self.assertIsNotNone(entry_obj, "首页真实链接发现的 /submit 遭遇 auth wall callback 应该通过！")
        self.assertEqual(entry_obj.evidence_type, "auth_wall_submission")
        self.assertEqual(entry_obj.url, "https://discovered-site.com/submit")

    def test_auth_callback_with_external_url_is_rejected(self):
        # external callback URL 拒绝：跳转到 /login?redirect=https://external-phishing.com/submit
        def fake_fetch(url):
            return {
                "status": 200,
                "final_url": "https://safe-domain.com/login?redirect=https%3A%2F%2Fexternal-phishing.com%2Fsubmit",
                "mechanism_signals": [],
            }
        entry_obj, reason = verify_submission_entry(
            "safe-domain.com",
            "https://safe-domain.com/submit",
            fetcher=fake_fetch,
            is_discovered_candidate=True,
        )
        self.assertIsNone(entry_obj, "指向外部域名的 callback 必须坚决拒绝！")
        self.assertIn("跨域外部域名", reason)

    def test_auth_wall_verified_entry_retains_original_submission_url_not_login_query(self):
        # auth wall 不把 login query URL 写入入口，而是保留原始 entry URL；且 evidence 不记录完整 query/token
        def fake_fetch(url):
            return {
                "status": 200,
                "final_url": "https://myplatform.com/login?redirect=%2Fsubmit&session_token=secret123&nonce=456",
                "mechanism_signals": [],
            }
        entry_obj, reason = verify_submission_entry(
            "myplatform.com",
            "https://myplatform.com/submit",
            fetcher=fake_fetch,
            is_discovered_candidate=True,
        )
        self.assertIsNotNone(entry_obj)
        self.assertEqual(
            entry_obj.url, "https://myplatform.com/submit",
            "VerifiedEntry.url 必须保留原始稳定 submission URL，而不是带 session/query 的 /login URL！"
        )
        self.assertNotIn("secret123", entry_obj.evidence_summary, "evidence 严禁泄露完整 query 或 token！")
        self.assertNotIn("nonce", entry_obj.evidence_summary)
        self.assertIn("/submit", entry_obj.evidence_summary)

    def test_homepage_noindex_does_not_block_entry_discovery(self):
        # homepage noindex 不阻断后续 entry discovery
        def fake_fetch(url):
            if url == "https://noindex-home.com/":
                return {
                    "status": 200,
                    "final_url": "https://noindex-home.com/",
                    "candidate_urls": ["https://noindex-home.com/add-tool"],
                    "mechanism_signals": [],
                    "noindex": True,  # 首页标记为 noindex！
                }
            if url == "https://noindex-home.com/add-tool":
                return {
                    "status": 200,
                    "final_url": "https://noindex-home.com/add-tool",
                    "mechanism_signals": ["submit your product"],
                    "noindex": False,
                }
            return {"status": 404}

        entry_obj, reason = discover_and_verify_entry("noindex-home.com", fetcher=fake_fetch)
        self.assertIsNotNone(entry_obj, "首页 noindex 绝不应阻断后续子页面真实入口的发现！")
        self.assertEqual(entry_obj.url, "https://noindex-home.com/add-tool")
        self.assertEqual(entry_obj.evidence_type, "subpage_mechanism")

    def test_p1_5_auth_wall_submission_without_callback_is_rejected(self):
        # 任意未知路径跳到纯 /login（无 callback 参数）-> 拒绝，防止盲猜
        def fake_fetch(url):
            return {
                "status": 200,
                "final_url": "https://example.com/login",
                "mechanism_signals": [],
            }
        entry_obj, reason = verify_submission_entry("example.com", "https://example.com/random", fetcher=fake_fetch)
        self.assertIsNone(entry_obj, "无明确 callback 参数的未知登录跳转绝不能当做有效入口！")

    def test_discover_and_verify_entry_locates_subpage(self):
        def fake_fetch(url):
            if url == "https://testdir.com/":
                return {
                    "status": 200,
                    "final_url": "https://testdir.com/",
                    "candidate_urls": ["https://testdir.com/add-project"],
                    "mechanism_signals": [],
                    "noindex": False,
                }
            if url == "https://testdir.com/add-project":
                return {
                    "status": 200,
                    "final_url": "https://testdir.com/add-project",
                    "mechanism_signals": ["submit your product"],
                    "noindex": False,
                }
            return {"status": 404}

        entry_obj, reason = discover_and_verify_entry("testdir.com", fetcher=fake_fetch)
        self.assertIsNotNone(entry_obj)
        self.assertEqual(entry_obj.url, "https://testdir.com/add-project")
        self.assertEqual(entry_obj.evidence_type, "subpage_mechanism")

    def test_entry_unknown_remains_empty_and_candidate_retained(self):
        def fake_fetch_no_entry(url):
            if url == "https://noentry.com/":
                return {
                    "status": 200,
                    "final_url": "https://noentry.com/",
                    "candidate_urls": ["https://noentry.com/about", "https://noentry.com/contact"],
                    "mechanism_signals": [],
                    "noindex": False,
                    "title": "A standard blog",
                    "text_excerpt": "Just a personal blog with thoughts.",
                }
            return {"status": 404}

        entry_obj, reason = discover_and_verify_entry("noentry.com", fetcher=fake_fetch_no_entry)
        self.assertIsNone(entry_obj)
        self.assertIn("证据缺失", reason)


class ProjectSynchronizationTests(unittest.TestCase):
    def test_candidate_with_verified_entry_materializes_to_to_submit(self):
        master_row = {
            "外链ID": "good-opportunity.com",
            "平台域名": "good-opportunity.com",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "提交入口": "https://good-opportunity.com/submit",
        }
        # 通过 fake fetcher 驱动真实 live verification
        def fake_fetch(url):
            if url == "https://good-opportunity.com/submit":
                return {
                    "status": 200,
                    "final_url": "https://good-opportunity.com/submit",
                    "mechanism_signals": ["submit a tool"],
                }
            return {"status": 404}

        existing_project_rows = []
        prow = materialize_project_row(
            master_row=master_row,
            existing_project_rows=existing_project_rows,
            project_id="quick-iching",
            fetcher=fake_fetch,
        )
        self.assertIsNotNone(prow)
        self.assertEqual(prow["项目ID"], "quick-iching")
        self.assertEqual(prow["外链ID"], "good-opportunity.com")
        self.assertEqual(prow["状态"], PROJECT_STATUS_TO_SUBMIT)
        self.assertEqual(prow["尝试次数"], "0")
        self.assertIn("subpage_mechanism", prow["证据摘要"])

    def test_materialize_fails_when_live_verification_fails(self):
        # 生产队列 materialization 必须由内部 live verification 驱动，核验失败绝不生成行
        master_row = {
            "外链ID": "unverified.com",
            "平台域名": "unverified.com",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "提交入口": "https://unverified.com/submit",
        }
        def fake_fetch_fail(url):
            return {
                "status": 200,
                "final_url": "https://unverified.com/submit",
                "mechanism_signals": [],  # 无机制文案
            }
        self.assertIsNone(materialize_project_row(master_row, [], "quick-iching", fetcher=fake_fetch_fail))

    def test_existing_project_row_not_duplicated_or_reset(self):
        master_row = {
            "外链ID": "active-task.com",
            "平台域名": "active-task.com",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "提交入口": "https://active-task.com/submit",
        }
        def fake_fetch(url):
            return {
                "status": 200,
                "final_url": "https://active-task.com/submit",
                "mechanism_signals": ["submit"],
            }
        existing_project_rows = [{
            "项目ID": "quick-iching",
            "外链ID": "active-task.com",
            "状态": "已提交",
            "结果链接": "https://active-task.com/p/quickiching",
        }]
        prow = materialize_project_row(master_row, existing_project_rows, "quick-iching", fetcher=fake_fetch)
        self.assertIsNone(prow)

    def test_excluded_or_dead_master_row_does_not_materialize(self):
        def fake_fetch(url):
            return {
                "status": 200,
                "final_url": url,
                "mechanism_signals": ["submit"],
            }
        excluded_master = {
            "外链ID": "excluded.com",
            "基础状态": MASTER_STATUS_EXCLUDED,
            "提交入口": "https://excluded.com/submit",
        }
        dead_master = {
            "外链ID": "dead.com",
            "基础状态": MASTER_STATUS_DEAD,
            "提交入口": "https://dead.com/submit",
        }
        self.assertIsNone(materialize_project_row(excluded_master, [], "quick-iching", fetcher=fake_fetch))
        self.assertIsNone(materialize_project_row(dead_master, [], "quick-iching", fetcher=fake_fetch))

    def test_preserves_quick_iching_historical_terminal_statuses(self):
        def fake_fetch(url):
            return {
                "status": 200,
                "final_url": url,
                "mechanism_signals": ["submit"],
            }
        for terminal_status in ["已排期", "需人工", "不适用", "已上线", "失败"]:
            master_row = {
                "外链ID": "e2e-protected.com",
                "基础状态": MASTER_STATUS_CANDIDATE,
                "提交入口": "https://e2e-protected.com/submit",
            }
            existing = [{
                "项目ID": "quick-iching",
                "外链ID": "e2e-protected.com",
                "状态": terminal_status,
            }]
            self.assertIsNone(materialize_project_row(master_row, existing, "quick-iching", fetcher=fake_fetch))



class P0_2_ExistingMasterEntryVerificationTests(unittest.TestCase):
    def test_existing_homepage_entry_without_cta_cannot_materialize_in_hydration(self):
        # P0-2: master 中已有提交入口=https://example.com/，但首页现场核验无 Submit CTA -> 不得 materialize
        master_rows = [{
            "外链ID": "no-cta.com",
            "平台域名": "no-cta.com",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "提交入口": "https://no-cta.com/",
        }]

        def mock_verifier(d, url):
            # 首页无 CTA
            return None, "首页无明确 CTA"

        res = batch_hydrate_candidates(
            master_rows=master_rows,
            existing_project_rows=[],
            project_id="quick-iching",
            target_count=5,
            scan_limit=10,
            entry_verifier=mock_verifier,
        )

        self.assertEqual(res["succeeded_count"], 0)
        self.assertEqual(len(res["new_project_rows"]), 0)
        # 保持原有值，不瞎猜替换，保持候选
        self.assertEqual(master_rows[0]["提交入口"], "https://no-cta.com/")
        self.assertEqual(master_rows[0]["基础状态"], MASTER_STATUS_CANDIDATE)

    def test_existing_subpage_entry_without_mechanism_cannot_materialize_in_hydration(self):
        # P0-2: master 中已有提交入口=https://example.com/submit，但现场页面不存在提交机制 -> 不得 materialize
        master_rows = [{
            "外链ID": "fake-submit.com",
            "平台域名": "fake-submit.com",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "提交入口": "https://fake-submit.com/submit",
        }]

        def mock_verifier(d, url):
            return None, "页面无机制信号"

        res = batch_hydrate_candidates(
            master_rows=master_rows,
            existing_project_rows=[],
            project_id="quick-iching",
            target_count=5,
            scan_limit=10,
            entry_verifier=mock_verifier,
        )

        self.assertEqual(res["succeeded_count"], 0)
        self.assertEqual(len(res["new_project_rows"]), 0)
        self.assertEqual(master_rows[0]["提交入口"], "https://fake-submit.com/submit")


class P0_3_BoundedBatchHydrationTests(unittest.TestCase):
    def test_batch_hydration_stops_at_scan_limit_when_all_fail(self):
        # 100 个 candidate，全部 finder 返回 None，target_count=10, scan_limit=20
        # 预期：processed_candidates == 20, succeeded_count == 0，绝不扫描 100 个！
        master_rows = [
            {"外链ID": f"cand-{i}.com", "平台域名": f"cand-{i}.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": ""}
            for i in range(100)
        ]

        def mock_fail_finder(d):
            return None, "no entry found"

        res = batch_hydrate_candidates(
            master_rows=master_rows,
            existing_project_rows=[],
            project_id="quick-iching",
            target_count=10,
            scan_limit=20,
            entry_finder=mock_fail_finder,
        )

        self.assertEqual(res["processed_candidates"], 20)
        self.assertEqual(res["succeeded_count"], 0)
        self.assertEqual(len(res["new_project_rows"]), 0)

    def test_batch_hydration_stops_early_when_scan_limit_hit_before_target(self):
        # 成功率低：只有前 2 个成功，之后全失败，target_count=10，scan_limit=15
        master_rows = [
            {"外链ID": f"cand-{i}.com", "平台域名": f"cand-{i}.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": ""}
            for i in range(50)
        ]

        def mock_low_hit_finder(d):
            if d in ("cand-0.com", "cand-1.com"):
                return VerifiedEntry(
                    url=f"https://{d}/submit",
                    domain=d,
                    evidence_type="subpage_mechanism",
                    evidence_summary="ok",
                ), "ok"
            return None, "no entry"

        res = batch_hydrate_candidates(
            master_rows=master_rows,
            existing_project_rows=[],
            project_id="quick-iching",
            target_count=10,
            scan_limit=15,
            entry_finder=mock_low_hit_finder,
        )

        # 触达 scan_limit=15 立即退出，虽然目标 10 未达成
        self.assertEqual(res["processed_candidates"], 15)
        self.assertEqual(res["succeeded_count"], 2)
        self.assertEqual(len(res["new_project_rows"]), 2)


class FactSeparationTests(unittest.TestCase):
    def test_discovery_never_populates_verified_fact_columns(self):
        existing = []
        new_items = [{
            "referring_domain": "clean.com",
            "discovery_source": "toolify",
            "实测免费": "是",
            "实测需登录": "否",
            "实测登录方式": "OAuth",
            "实测限制": "无",
            "实测链接属性": "Follow",
            "最后验证时间": "2026-09-06",
        }]
        merged, _ = upsert_master_rows(existing, new_items)
        row = merged[0]
        for col in PROTECTED_FACT_COLUMNS:
            self.assertEqual(
                row[col], "",
                f"Discovery 严禁填写实测字段 '{col}'，必须保持为空！"
            )


if __name__ == "__main__":
    unittest.main()
