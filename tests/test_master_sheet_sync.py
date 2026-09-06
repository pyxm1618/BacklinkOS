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
    batch_hydrate_candidates,
    canonical_domain,
    discover_and_verify_entry,
    materialize_project_row,
    submission_entry_policy_guard,
    upsert_master_rows,
    verify_homepage_as_entry,
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
        # 新发现中即使伪造了实测事实，upsert 必须严格保护已有事实不被污染覆盖
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

        entry_url, reason = discover_and_verify_entry("testdir.com", fetcher=fake_fetch)
        self.assertEqual(entry_url, "https://testdir.com/add-project")
        self.assertIn("闭环", reason)

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

        entry_url, reason = discover_and_verify_entry("noentry.com", fetcher=fake_fetch_no_entry)
        self.assertIsNone(entry_url)
        self.assertIn("证据缺失", reason)


class ProjectSynchronizationTests(unittest.TestCase):
    def test_candidate_with_valid_entry_materializes_to_to_submit(self):
        master_row = {
            "外链ID": "good-opportunity.com",
            "平台域名": "good-opportunity.com",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "提交入口": "https://good-opportunity.com/submit",
        }
        existing_project_rows = []
        prow = materialize_project_row(master_row, existing_project_rows, "quick-iching")
        self.assertIsNotNone(prow)
        self.assertEqual(prow["项目ID"], "quick-iching")
        self.assertEqual(prow["外链ID"], "good-opportunity.com")
        self.assertEqual(prow["外链域名"], "good-opportunity.com")
        self.assertEqual(prow["状态"], PROJECT_STATUS_TO_SUBMIT)
        self.assertEqual(prow["尝试次数"], "0")
        self.assertEqual(prow["目标URL"], "")
        self.assertEqual(prow["结果链接"], "")

    def test_existing_project_row_not_duplicated_or_reset(self):
        master_row = {
            "外链ID": "active-task.com",
            "平台域名": "active-task.com",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "提交入口": "https://active-task.com/submit",
        }
        existing_project_rows = [{
            "项目ID": "quick-iching",
            "外链ID": "active-task.com",
            "状态": "已提交",
            "结果链接": "https://active-task.com/p/quickiching",
        }]
        prow = materialize_project_row(master_row, existing_project_rows, "quick-iching")
        self.assertIsNone(prow)

    def test_excluded_or_dead_master_row_does_not_materialize(self):
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
        self.assertIsNone(materialize_project_row(excluded_master, [], "quick-iching"))
        self.assertIsNone(materialize_project_row(dead_master, [], "quick-iching"))

    def test_empty_entry_does_not_materialize(self):
        master_row = {
            "外链ID": "no-entry.com",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "提交入口": "",
        }
        self.assertIsNone(materialize_project_row(master_row, [], "quick-iching"))

    def test_preserves_quick_iching_historical_terminal_statuses(self):
        # 保护 36 条历史人工/E2E记录：已排期、需人工、不适用等终态绝对不被改写或重建
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
            self.assertIsNone(materialize_project_row(master_row, existing, "quick-iching"))


class BoundedBatchHydrationTests(unittest.TestCase):
    def test_batch_hydration_is_strictly_bounded_by_limit(self):
        master_rows = [
            {"外链ID": f"cand-{i}.com", "平台域名": f"cand-{i}.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": ""}
            for i in range(20)
        ]
        existing_project_rows = []

        def mock_finder(d):
            return f"https://{d}/submit", "found"

        res = batch_hydrate_candidates(
            master_rows=master_rows,
            existing_project_rows=existing_project_rows,
            project_id="quick-iching",
            limit=5,
            entry_finder=mock_finder,
        )

        self.assertEqual(res["succeeded_count"], 5)
        self.assertEqual(len(res["new_project_rows"]), 5)
        # 只处理了 5 个即停止，绝不一次性扫描全部 20 个
        self.assertEqual(res["processed_candidates"], 5)

    def test_batch_hydration_skips_failed_entry_and_retains_candidate(self):
        master_rows = [
            {"外链ID": "fail-1.com", "平台域名": "fail-1.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": ""},
            {"外链ID": "success-2.com", "平台域名": "success-2.com", "基础状态": MASTER_STATUS_CANDIDATE, "提交入口": ""},
        ]
        def mock_finder(d):
            if d == "fail-1.com":
                return None, "no entry found"
            return f"https://{d}/submit", "found"

        res = batch_hydrate_candidates(
            master_rows=master_rows,
            existing_project_rows=[],
            project_id="quick-iching",
            limit=5,
            entry_finder=mock_finder,
        )

        self.assertEqual(res["succeeded_count"], 1)
        self.assertEqual(len(res["new_project_rows"]), 1)
        self.assertEqual(res["new_project_rows"][0]["外链ID"], "success-2.com")
        # fail-1.com 提交入口保持为空，基础状态保持为候选，不被排除
        self.assertEqual(master_rows[0]["提交入口"], "")
        self.assertEqual(master_rows[0]["基础状态"], MASTER_STATUS_CANDIDATE)


class FactSeparationTests(unittest.TestCase):
    def test_discovery_never_populates_verified_fact_columns(self):
        existing = []
        new_items = [{
            "referring_domain": "clean.com",
            "discovery_source": "toolify",
            # 假定上游或脚本不慎传递了猜测的实测值
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
