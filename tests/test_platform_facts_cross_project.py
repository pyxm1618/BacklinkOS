#!/usr/bin/env python3
"""BacklinkOS 平台事实跨项目沉淀与复用自动化测试 (E2E Contract Verification)。

覆盖场景：
1. 项目 A 成功提交并沉淀有效入口与平台事实 -> 总表更新 -> 项目 B 直接复用该有效入口与事实，免重复探测，直接进入 start-attempt；
2. 项目 A 发现并沉淀否定入口（如商品加购页）-> 总表清除该错误入口并记录否定事实，保持候选 -> 项目 B 避开该错误入口；
3. 平台全局死站/关闭收录 -> 跨项目同步将其他项目“待提交”标记为失效/不适用，严格保护历史非待提交记录；
4. 项目属性未知不默认假设为否定：AI-only / 付费-only 限制根据项目属性独立研判，不误伤其他兼容或属性未知的项目；
5. 跨项目自动恢复：项目 A 写总表失败存入全局 pending，项目 B 在全新会话启动时自动发现并恢复写入总表，且 A 的提交尝试次数不增加。
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from scripts.master_sheet_sync import (
    ExclusionScope,
    MASTER_HEADER,
    MASTER_STATUS_CANDIDATE,
    MASTER_STATUS_DEAD,
    MASTER_STATUS_EXCLUDED,
    PROJECT_HEADER,
    PROJECT_STATUS_TO_SUBMIT,
    VerifiedEntry,
    canonical_domain,
    classify_exclusion,
    get_persisted_paid_incompatibility,
    get_persisted_project_incompatibility,
    normalize_canonical_url,
    prepare_execution_batch,
    resolve_project_context,
    sync_global_exclusions_across_projects,
)
from scripts.run_submission_cycle import (
    init_cycle_state,
    load_pending_master_mutations,
    plan_next_batch,
    record_task_outcome,
    recover_pending_master_mutations,
    save_pending_master_mutations,
    start_task_attempt,
    validate_platform_facts,
)
from scripts.prepare_execution_batch import col_index_to_letter


class TestPlatformFactsCrossProject(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runtime_dir = self.temp_dir.name
        os.environ["BACKLINKOS_RUNTIME_DIR"] = self.runtime_dir

    def tearDown(self):
        self.temp_dir.cleanup()
        os.environ.pop("BACKLINKOS_RUNTIME_DIR", None)

    def test_s1_missing_observed_url_preserves_current_entry(self):
        from scripts.reconcile_and_sync_112_records import reconcile_item
        row = {"提交入口": "https://example.test/submit", "平台备注": "已有事实"}
        facts, deferred = reconcile_item(
            {"domain": "example.test", "status": "失败", "reason": "此前查看的是电商加购页面", "evidence": "Add to cart"}, row
        )
        self.assertEqual(facts, {})
        self.assertTrue(deferred)
        self.assertEqual(row["提交入口"], "https://example.test/submit")

    def test_s2_each_claimed_limit_requires_matching_observation(self):
        for evidence in ({"limits": "仅限个人网站"}, "平台明确只收录个人网站",
                         {"limits": "需要收录审核"}):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                validate_platform_facts({"limits": "仅限AI工具; 需要收录审核"}, evidence)
        self.assertEqual(validate_platform_facts(
            {"limits": "仅限AI工具；需要收录审核"},
            {"limits": "仅限AI工具; 需要收录审核"}
        )["limits"], "仅限AI工具；需要收录审核")

    def test_1_project_a_success_persists_facts_and_project_b_reuses_entry(self):
        """场景 1：项目 A 成功提交并沉淀事实 -> 总表落表 -> 项目 B 无缝复用有效入口与事实。"""
        domain = "directory-hub.com"
        verified_url = "https://directory-hub.com/submit-site"

        # 1. 模拟项目 A 初始状态
        state_a = init_cycle_state(
            project_id="project-a",
            target_success=1,
            initial_candidates=[domain],
            spreadsheet_id="test_sheet_id",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        state_a["active_batch"] = {"ready_domains": [domain]}

        # 2. 模拟表数据：项目 A 拥有该入口，但平台事实未实测
        master_rows = [
            {
                "_sheet_row_num": 10,
                "外链ID": domain,
                "平台域名": domain,
                "提交入口": verified_url,
                "发现来源": "manual",
                "发现时间": "2026-09-01T00:00:00Z",
                "基础状态": MASTER_STATUS_CANDIDATE,
                "基础排除原因": "",
                "实测免费": "",
                "实测需登录": "",
                "实测登录方式": "",
                "实测限制": "",
                "实测链接属性": "",
                "最后验证时间": "",
                "平台备注": "",
            }
        ]
        project_rows_a = [
            {
                "_sheet_row_num": 5,
                "项目ID": "project-a",
                "外链ID": domain,
                "外链域名": domain,
                "状态": PROJECT_STATUS_TO_SUBMIT,
                "尝试次数": "0",
                "最近操作时间": "",
                "目标URL": "https://product-a.com",
                "结果链接": "",
                "原因/备注": "",
                "证据摘要": "",
            }
        ]
        start_task_attempt(
            state=state_a,
            backlink_id=domain,
            is_resume_attempt=False,
            master_rows=master_rows,
            project_rows=project_rows_a,
            commit=False,
            runtime_dir=self.runtime_dir,
        )

        # 3. 项目 A 调用正式 record_task_outcome 提交成功并传递平台事实
        platform_facts_payload = {
            "entry_url": verified_url,
            "free": "免费",
            "requires_login": "否",
            "notes": "支持免登录极速提交",
        }
        res_a = record_task_outcome(
            state=state_a,
            backlink_id=domain,
            status="已提交",
            reason="提交表单成功并收到确认信息，实测免费且无需登录",
            evidence={
                "public_access_verified": True,
                "listing_identity_verified": True,
                "free": "免费",
                "requires_login": "否",
            },
            result_url="",
            platform_facts=platform_facts_payload,
            master_rows=master_rows,
            project_rows=project_rows_a,
            commit=False,
            runtime_dir=self.runtime_dir,
        )

        self.assertTrue(res_a["ok"])
        self.assertEqual(res_a["master_sync_status"], "ok")
        m_updates = res_a.get("master_updates", {})
        self.assertEqual(m_updates.get("提交入口"), verified_url)
        self.assertEqual(m_updates.get("实测免费"), "免费")
        self.assertEqual(m_updates.get("实测需登录"), "否")

        # 将总表行实际更新（模拟持久化完成）
        master_rows[0]["提交入口"] = verified_url
        master_rows[0]["实测免费"] = "免费"
        master_rows[0]["实测需登录"] = "否"
        master_rows[0]["平台备注"] = "支持免登录极速提交"

        # 4. 项目 B 启动并规划批次
        state_b = init_cycle_state(
            project_id="project-b",
            target_success=1,
            initial_candidates=[domain],
            spreadsheet_id="test_sheet_id",
            master_sheet="外链总表",
            project_sheet="外链管理",
            runtime_dir=self.runtime_dir,
        )
        project_rows_b = [
            {
                "_sheet_row_num": 6,
                "项目ID": "project-b",
                "外链ID": domain,
                "外链域名": domain,
                "状态": PROJECT_STATUS_TO_SUBMIT,
                "尝试次数": "0",
                "最近操作时间": "",
                "目标URL": "https://product-b.com",
                "结果链接": "",
                "原因/备注": "",
                "证据摘要": "",
            }
        ]

        def mock_verifier(d, u):
            if u == verified_url:
                return VerifiedEntry(
                    url=u,
                    domain=d,
                    evidence_type="actionable_form",
                    evidence_summary="表单存在输入项与提交按钮",
                ), ""
            return None, "入口无法访问"

        plan_b = plan_next_batch(
            state=state_b,
            master_rows=master_rows,
            project_rows=project_rows_b,
            batch_ready_target=1,
            batch_scan_limit=5,
            entry_verifier=mock_verifier,
            commit_prep=False,
            runtime_dir=self.runtime_dir,
        )

        self.assertEqual(plan_b["action"], "EXECUTE_BATCH")
        ready_items = plan_b.get("ready_items", [])
        self.assertEqual(len(ready_items), 1)
        self.assertEqual(ready_items[0]["domain"], domain)
        # 项目 B 获得的入口正是项目 A 沉淀的入口！
        self.assertEqual(ready_items[0]["submission_url"], verified_url)

        # 5. 项目 B 调用 start-attempt 启动真实执行
        att_b = start_task_attempt(
            state=state_b,
            backlink_id=domain,
            is_resume_attempt=False,
            master_rows=master_rows,
            project_rows=project_rows_b,
            commit=False,
            runtime_dir=self.runtime_dir,
        )
        self.assertEqual(att_b["status"], "处理中")
        self.assertEqual(att_b["attempt_count"], 1)

    def test_2_project_a_negates_entry_clears_master_and_project_b_avoids_it(self):
        """场景 2：项目 A 遇到错误入口沉淀否定入口 -> 总表清除并追加否定备注 -> 项目 B 避开。"""
        domain = "bad-ecommerce-hub.com"
        bad_url = "https://bad-ecommerce-hub.com/products/tool-item?add-to-cart=123"

        master_rows = [
            {
                "_sheet_row_num": 20,
                "外链ID": domain,
                "平台域名": domain,
                "提交入口": bad_url,  # 历史误抓取的错误入口
                "基础状态": MASTER_STATUS_CANDIDATE,
                "基础排除原因": "",
                "平台备注": "高权重电商",
            }
        ]
        project_rows_a = [
            {
                "_sheet_row_num": 15,
                "项目ID": "project-a",
                "外链ID": domain,
                "状态": PROJECT_STATUS_TO_SUBMIT,
                "尝试次数": "0",
            }
        ]

        state_a = init_cycle_state("project-a", 1, [domain], "test_sheet_id", "外链总表", "外链管理", runtime_dir=self.runtime_dir)
        state_a["active_batch"] = {"ready_domains": [domain]}
        start_task_attempt(
            state=state_a,
            backlink_id=domain,
            is_resume_attempt=False,
            master_rows=master_rows,
            project_rows=project_rows_a,
            commit=False,
            runtime_dir=self.runtime_dir,
        )

        facts_payload = {
            "negated_entries": [bad_url],
            "notes": "实测为电商加购页，非外链收录入口",
        }
        res_a = record_task_outcome(
            state=state_a,
            backlink_id=domain,
            status="失败",
            reason="非外链收录入口，实测为 Shopify 加购页面",
            evidence="页面仅包含 Add to Cart 按钮与价格标签",
            platform_facts=facts_payload,
            master_rows=master_rows,
            project_rows=project_rows_a,
            commit=False,
            runtime_dir=self.runtime_dir,
        )

        self.assertTrue(res_a["ok"])
        m_updates = res_a.get("master_updates", {})
        self.assertEqual(m_updates.get("提交入口"), "")
        self.assertNotIn("基础状态", m_updates)
        self.assertIn("高权重电商", m_updates.get("平台备注", ""))
        self.assertIn(f"否定入口: {bad_url}", m_updates.get("平台备注", ""))

        master_rows[0]["提交入口"] = ""
        master_rows[0]["平台备注"] = m_updates.get("平台备注", "")

        project_rows_b = [
            {
                "_sheet_row_num": 25,
                "项目ID": "project-b",
                "外链ID": domain,
                "状态": PROJECT_STATUS_TO_SUBMIT,
                "尝试次数": "0",
            }
        ]

        def mock_verifier_guard(d, u):
            if u == bad_url:
                raise AssertionError(f"错误入口 {bad_url} 不应再作为候选入口被探测！")
            return None, "未找到其他入口"

        prep_res = prepare_execution_batch(
            master_rows=master_rows,
            project_rows=project_rows_b,
            project_id="project-b",
            target_ready_count=1,
            scan_limit=5,
            entry_verifier=mock_verifier_guard,
            runtime_dir=self.runtime_dir,
        )
        self.assertEqual(prep_res["ready_count"], 0)

    def test_3_dead_site_global_exclusion_and_cross_project_history_protection(self):
        """场景 3：死站/关闭收录全局排除 -> 跨项目有限同步待提交 -> 绝对保护非待提交历史状态。"""
        dead_domain = "dead-service-xyz.com"
        master_rows = [
            {
                "外链ID": dead_domain,
                "平台域名": dead_domain,
                "基础状态": MASTER_STATUS_DEAD,
                "基础排除原因": "域名过期 NXDOMAIN",
            }
        ]
        project_rows = [
            {"_sheet_row_num": 101, "项目ID": "project-b", "外链ID": dead_domain, "状态": "待提交"},
            {"_sheet_row_num": 102, "项目ID": "project-c", "外链ID": dead_domain, "状态": "已提交"},
            {"_sheet_row_num": 103, "项目ID": "project-d", "外链ID": dead_domain, "状态": "审核中"},
            {"_sheet_row_num": 104, "项目ID": "project-e", "外链ID": dead_domain, "状态": "需人工"},
            {"_sheet_row_num": 105, "项目ID": "project-f", "外链ID": dead_domain, "状态": "已排期"},
            {"_sheet_row_num": 106, "项目ID": "project-g", "外链ID": dead_domain, "状态": "已上线"},
            {"_sheet_row_num": 107, "项目ID": "project-h", "外链ID": dead_domain, "状态": "失败"},
        ]

        sync_res = sync_global_exclusions_across_projects(master_rows=master_rows, project_rows=project_rows)
        self.assertEqual(sync_res["mutated_count"], 1)
        mut = sync_res["planned_mutations"][0]
        self.assertEqual(mut["project_id"], "project-b")
        self.assertEqual(mut["sheet_row_num"], 101)
        self.assertEqual(mut["proposed_fields"]["状态"], "失败")

    def test_4_project_attribute_unknown_not_assumed_negative_and_independent_decisions(self):
        """场景 4：项目属性未知不默认假设为否定；AI 与付费限制独立研判。"""
        ai_platform_row = {
            "外链ID": "ai-directory.org",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "实测限制": "仅限AI产品收录",
        }

        ctx_non_ai = {"ai_powered": False}
        incompat_a, _, _ = get_persisted_project_incompatibility(ai_platform_row, ctx_non_ai)
        self.assertTrue(incompat_a, "非 AI 项目必须命中排除")

        ctx_unknown_ai = {"ai_powered": None}
        incompat_b, _, _ = get_persisted_project_incompatibility(ai_platform_row, ctx_unknown_ai)
        self.assertFalse(incompat_b, "属性未知时绝不能默认排除")

        ctx_is_ai = {"ai_powered": True}
        incompat_c, _, _ = get_persisted_project_incompatibility(ai_platform_row, ctx_is_ai)
        self.assertFalse(incompat_c, "AI 项目不应被排除")

        paid_platform_row = {
            "外链ID": "paid-tools.io",
            "基础状态": MASTER_STATUS_CANDIDATE,
            "实测免费": "非免费",
            "实测限制": "纯付费收录",
        }

        ctx_no_paid = {"accepts_paid": False}
        paid_incompat_a, _, _ = get_persisted_paid_incompatibility(paid_platform_row, ctx_no_paid)
        self.assertTrue(paid_incompat_a, "明确不接受付费的项目必须排除")

        ctx_unknown_paid = {"accepts_paid": None}
        paid_incompat_b, _, _ = get_persisted_paid_incompatibility(paid_platform_row, ctx_unknown_paid)
        self.assertFalse(paid_incompat_b, "付费政策未知时绝不能默认排除")

        ctx_accepts_paid = {"accepts_paid": True}
        paid_incompat_c, _, _ = get_persisted_paid_incompatibility(paid_platform_row, ctx_accepts_paid)
        self.assertFalse(paid_incompat_c, "接受付费的项目不应被排除")

    def test_5_master_mutation_failure_cross_project_recovery_in_new_session(self):
        """场景 5：项目 A 写总表失败存入全局 pending -> 新会话启动项目 B 时自动发现并成功恢复。"""
        domain = "shared-directory.com"
        state_a = init_cycle_state("project-a", 1, [domain], "test_sheet_id", "外链总表", "外链管理", runtime_dir=self.runtime_dir)
        state_a["active_batch"] = {"ready_domains": [domain]}

        master_rows = [
            {
                "_sheet_row_num": 88,
                "外链ID": domain,
                "平台域名": domain,
                "提交入口": "https://shared-directory.com/submit",
                "基础状态": MASTER_STATUS_CANDIDATE,
                "实测免费": "",
                "实测需登录": "",
                "最后验证时间": "",
                "平台备注": "",
            }
        ]
        project_rows_a = [
            {
                "_sheet_row_num": 42,
                "项目ID": "project-a",
                "外链ID": domain,
                "外链域名": domain,
                "状态": PROJECT_STATUS_TO_SUBMIT,
                "尝试次数": "0",
            }
        ]
        start_task_attempt(
            state=state_a,
            backlink_id=domain,
            is_resume_attempt=False,
            master_rows=master_rows,
            project_rows=project_rows_a,
            commit=False,
            runtime_dir=self.runtime_dir,
        )

        mock_sheets = MagicMock()
        def mock_get_a(spreadsheetId, range):
            mock_req = MagicMock()
            if "A42:J42" in range:
                row = ["project-a", domain, domain, "已提交", "1", "", "", "", "", ""]
                mock_req.execute.return_value = {"values": [row]}
            else:
                mock_req.execute.return_value = {"values": []}
            return mock_req

        def mock_batch_update(spreadsheetId, body):
            data = body.get("data", [])
            for item in data:
                if "外链总表" in item.get("range", ""):
                    raise ConnectionError("Google Sheets API 503 Backend Error")
            return MagicMock()

        mock_sheets.spreadsheets().values().get.side_effect = mock_get_a
        mock_sheets.spreadsheets().values().batchUpdate.side_effect = mock_batch_update

        rec_res_a = record_task_outcome(
            state=state_a,
            backlink_id=domain,
            status="已提交",
            reason="提交表单成功，实测免费且无需登录",
            evidence={
                "public_access_verified": True,
                "listing_identity_verified": True,
                "free": "免费",
                "requires_login": "否",
            },
            platform_facts={
                "entry_url": "https://shared-directory.com/submit",
                "free": "免费",
                "requires_login": "否",
            },
            master_rows=master_rows,
            project_rows=project_rows_a,
            sheets_service=mock_sheets,
            commit=True,
            runtime_dir=self.runtime_dir,
        )

        self.assertTrue(rec_res_a["ok"])
        self.assertEqual(rec_res_a["master_sync_status"], "pending_recovery")
        self.assertEqual(state_a["completed_items"][domain]["status"], "已提交")

        pending_list = load_pending_master_mutations("project-a", self.runtime_dir)
        self.assertEqual(len(pending_list), 1)
        self.assertEqual(pending_list[0]["domain"], domain)
        self.assertEqual(pending_list[0]["fields"]["提交入口"], "https://shared-directory.com/submit")

        mock_sheets_recovered = MagicMock()
        mock_cells = {
            "外链ID": domain,
            "平台域名": domain,
        }
        def mock_batch_update(spreadsheetId, body):
            for item in body.get("data", []):
                r = item.get("range", "")
                v = item.get("values", [[]])[0][0]
                for col_name in MASTER_HEADER:
                    col_letter = col_index_to_letter(MASTER_HEADER.index(col_name))
                    if f"{col_letter}88" in r:
                        mock_cells[col_name] = v
            return MagicMock()

        def mock_get(spreadsheetId, range):
            mock_req = MagicMock()
            row = [""] * len(MASTER_HEADER)
            for col_name, val in mock_cells.items():
                row[MASTER_HEADER.index(col_name)] = val
            mock_req.execute.return_value = {"values": [row]}
            return mock_req

        mock_sheets_recovered.spreadsheets().values().get.side_effect = mock_get
        mock_sheets_recovered.spreadsheets().values().batchUpdate.side_effect = mock_batch_update

        rem = recover_pending_master_mutations(
            sheets_service=mock_sheets_recovered,
            spreadsheet_id="test_sheet_id",
            master_sheet_name="外链总表",
            project_id="project-b",
            runtime_dir=self.runtime_dir,
        )

        self.assertEqual(len(rem), 0)
        remaining_pending = load_pending_master_mutations("project-b", self.runtime_dir)
        self.assertEqual(len(remaining_pending), 0, "跨项目待恢复变更已全部成功落表并清除")

    def test_s1_project_slug_in_result_url_rejected_for_generic_entry(self):
        """S1 契约：带有任意项目专属 slug 的结果链接绝不能作为通用提交入口，历史有效否定事实不被误删。"""
        # 1. 任意项目的专属 slug (包括 product-b, quick-iching 等) 必须在 validate_platform_facts 中被拒绝
        for bad_url in [
            "https://flowtools.co/submit/quick-i-ching",
            "https://example.test/submit/product-b",
            "https://example.test/products/waterproof-gloves",
            "https://example.test/listings/property-123",
        ]:
            with self.assertRaises(ValueError) as ctx:
                validate_platform_facts(
                    facts={"entry_url": bad_url},
                    evidence="表单提交成功",
                )
            self.assertTrue(
                "专属路径或 slug" in str(ctx.exception) or "具体产品或单品路径" in str(ctx.exception),
                f"URL {bad_url} 应该被拒绝，实际: {ctx.exception}"
            )

        # 2. 通用入口正常允许
        ok_facts = validate_platform_facts(
            facts={"entry_url": "https://flowtools.co/submit"},
            evidence="表单提交成功",
        )
        self.assertEqual(ok_facts["entry_url"], "https://flowtools.co/submit")

        # 3. 历史有效否定事实 (如 xrp.army) 不因文本缺少 URL 被误删，且观察时间完整保留
        from scripts.reconcile_and_sync_112_records import reconcile_item
        xrp_item = {
            "domain": "xrp.army",
            "status": "失败",
            "reason": "页面为行情资讯展示页，无面向外部访客开放的有效提交入口",
            "evidence": "页面表单为WordPress后台残存的只读wp-link浮层，无公开投稿通道",
            "timestamp": "2026-09-09T10:55:37.361890+00:00",
        }
        xrp_mrow = {
            "_sheet_row_num": 529,
            "外链ID": "xrp.army",
            "提交入口": "https://xrp.army/news/",
            "平台备注": "",
            "最后验证时间": "2026-09-12T00:00:00Z",
        }
        rec_facts, _ = reconcile_item(xrp_item, xrp_mrow)
        self.assertEqual(rec_facts["entry_url"], "")
        self.assertIn("否定入口: https://xrp.army/news/", rec_facts["notes"])
        self.assertEqual(rec_facts["observed_at"], "2026-09-09T10:55:37.361890+00:00")

    def test_s2_invalid_json_and_unsupported_facts_rejected_before_project_sheet_write(self):
        """S2 契约：非法 JSON、矛盾事实、缺少对应观察、未测 DOM rel 在写项目表之前写前拒绝。"""
        domain = "test-gate-reject.com"
        state = init_cycle_state("project-a", 1, [domain], "test_sheet_id", "外链总表", "外链管理", runtime_dir=self.runtime_dir)
        state["active_attempt"] = {"backlink_id": domain, "attempt_count": 1}
        project_rows = [
            {"_sheet_row_num": 12, "项目ID": "project-a", "外链ID": domain, "状态": "待提交", "尝试次数": "0"}
        ]
        master_rows = [
            {"_sheet_row_num": 30, "外链ID": domain, "平台域名": domain, "提交入口": "https://test-gate-reject.com/submit"}
        ]

        mock_sheets = MagicMock()

        # 1. 非法 JSON 字符串直接抛出 ValueError
        with self.assertRaises(ValueError) as ctx1:
            record_task_outcome(
                state=state,
                backlink_id=domain,
                status="已提交",
                reason="提交完成",
                evidence={"public_access_verified": True, "listing_identity_verified": True},
                platform_facts="{not-valid-json",
                master_rows=master_rows,
                project_rows=project_rows,
                sheets_service=mock_sheets,
                commit=True,
                runtime_dir=self.runtime_dir,
            )
        self.assertIn("不是合法 JSON", str(ctx1.exception))
        mock_sheets.spreadsheets().values().batchUpdate.assert_not_called()

        # 2. 明确矛盾拦截：输入证据为 free=非免费, requires_login=是，拟写却声明 free=免费, requires_login=否 -> 必须拒绝
        with self.assertRaises(ValueError) as ctx2:
            record_task_outcome(
                state=state,
                backlink_id=domain,
                status="失败",
                reason="收费且需登录",
                evidence={"free": "非免费", "requires_login": "是"},
                platform_facts={"free": "免费", "requires_login": "否"},
                master_rows=master_rows,
                project_rows=project_rows,
                sheets_service=mock_sheets,
                commit=True,
                runtime_dir=self.runtime_dir,
            )
        self.assertIn("相矛盾", str(ctx2.exception))
        mock_sheets.spreadsheets().values().batchUpdate.assert_not_called()

        # 3. 缺少对应观察拦截：只观察到搜索框，拟写 limits=仅限AI工具 -> 必须拒绝
        with self.assertRaises(ValueError) as ctx3:
            record_task_outcome(
                state=state,
                backlink_id=domain,
                status="待提交",
                reason="只观察到搜索框",
                evidence={"search_box_observed": True},
                platform_facts={"limits": "仅限AI工具"},
                master_rows=master_rows,
                project_rows=project_rows,
                sheets_service=mock_sheets,
                commit=True,
                runtime_dir=self.runtime_dir,
            )
        self.assertIn("缺乏对应收录限制观察证据", str(ctx3.exception))
        mock_sheets.spreadsheets().values().batchUpdate.assert_not_called()

        # 4. 未确认的全局结论拦截：主页正常 (home_status=200) 尚未确认关闭收录，拟写 master_status=失效 -> 必须拒绝
        with self.assertRaises(ValueError) as ctx4:
            record_task_outcome(
                state=state,
                backlink_id=domain,
                status="失败",
                reason="主页正常，尚未确认关闭收录",
                evidence={"home_status": 200},
                platform_facts={"master_status": "失效"},
                master_rows=master_rows,
                project_rows=project_rows,
                sheets_service=mock_sheets,
                commit=True,
                runtime_dir=self.runtime_dir,
            )
        self.assertIn("主页正常", str(ctx4.exception))
        mock_sheets.spreadsheets().values().batchUpdate.assert_not_called()

        # 5. 未检查 DOM rel 拦截：未检查 live_dom_rel 拟写 link_rel=Dofollow -> 必须拒绝
        with self.assertRaises(ValueError) as ctx5:
            record_task_outcome(
                state=state,
                backlink_id=domain,
                status="已提交",
                reason="已提交",
                evidence={"listing_live": True},  # 缺少 live_dom_rel
                platform_facts={"link_rel": "Dofollow"},
                master_rows=master_rows,
                project_rows=project_rows,
                sheets_service=mock_sheets,
                commit=True,
                runtime_dir=self.runtime_dir,
            )
        self.assertIn("DOM rel", str(ctx5.exception))
        mock_sheets.spreadsheets().values().batchUpdate.assert_not_called()

    def test_s3_master_row_identity_check_handles_shift_and_rejects_unmatched(self):
        """S3 契约：Master 表写前单行身份核验，行移位时自动重定位，找不到时拒绝盲写并存入 pending。"""
        domain = "shifted-site.com"
        state = init_cycle_state("project-a", 1, [domain], "test_sheet_id", "外链总表", "外链管理", runtime_dir=self.runtime_dir)
        state["active_attempt"] = {"backlink_id": domain, "attempt_count": 1}
        project_rows = [
            {"_sheet_row_num": 10, "项目ID": "project-a", "外链ID": domain, "状态": "待提交", "尝试次数": "0"}
        ]
        # 初始传入的 master_row 行号为 50，但假设实际已移位到 55
        master_rows = [
            {"_sheet_row_num": 50, "外链ID": domain, "平台域名": domain, "提交入口": "https://shifted-site.com/submit"}
        ]

        mock_sheets = MagicMock()
        written_ranges = []
        mock_cells = {
            "外链ID": domain,
            "平台域名": domain,
            "实测免费": "免费",
        }

        def mock_batch_update(spreadsheetId, body):
            for d in body.get("data", []):
                r = d.get("range", "")
                written_ranges.append(r)
                v = d.get("values", [[]])[0][0]
                for col_name in MASTER_HEADER:
                    col_letter = col_index_to_letter(MASTER_HEADER.index(col_name))
                    if f"{col_letter}55" in r:
                        mock_cells[col_name] = v
            return MagicMock()

        def mock_get(spreadsheetId, range):
            mock_req = MagicMock()
            if "A10:J10" in range:
                # 项目表核验正常通过
                mock_req.execute.return_value = {"values": [["project-a", domain, domain, "已提交", "1"]]}
            elif "A50:B50" in range:
                # 模拟行号 50 已移位（当前读到的是他人数据 other-site.com）
                mock_req.execute.return_value = {"values": [["other-site.com", "other-site.com"]]}
            elif "A1:A20000" in range:
                # 全列扫描：在第 55 行找到目标 domain
                col_vals = [[""]] * 54 + [[domain]]
                mock_req.execute.return_value = {"values": col_vals}
            elif "A55:N55" in range or "A55:" in range:
                row = [""] * len(MASTER_HEADER)
                for col_name, val in mock_cells.items():
                    row[MASTER_HEADER.index(col_name)] = val
                mock_req.execute.return_value = {"values": [row]}
            else:
                mock_req.execute.return_value = {"values": []}
            return mock_req

        mock_sheets.spreadsheets().values().get.side_effect = mock_get
        mock_sheets.spreadsheets().values().batchUpdate.side_effect = mock_batch_update

        res = record_task_outcome(
            state=state,
            backlink_id=domain,
            status="已提交",
            reason="提交完成，价格实测免费",
            evidence={"public_access_verified": True, "listing_identity_verified": True, "free": "免费"},
            platform_facts={"free": "免费"},
            master_rows=master_rows,
            project_rows=project_rows,
            sheets_service=mock_sheets,
            commit=True,
            runtime_dir=self.runtime_dir,
        )

        self.assertTrue(res["ok"])
        self.assertEqual(res["master_sync_status"], "ok")
        # 验证写入的单元格为重定位后的第 55 行，绝不是原移位前的第 50 行！
        self.assertTrue(any("55" in r for r in written_ranges))
        self.assertFalse(any("50" in r for r in written_ranges))

    def test_s4_partial_recovery_cleans_all_cycle_copies_and_refreshes_downstream(self):
        """S4 契约：部分恢复成功时，已成功项从所有 cycle 副本中精确清除；启动流程消费最新落表入口。"""
        dom_success = "succ-dir.com"
        dom_fail = "fail-dir.com"

        # 模拟在 cycle_1 与 cycle_2 目录下均存在包含这两条 pending 的副本
        mut_succ = {
            "domain": dom_success,
            "row_num": 10,
            "mutation_type": "submission_entry",
            "fields": {"提交入口": "https://succ-dir.com/submit"},
            "expected_val": "https://succ-dir.com/submit",
        }
        mut_fail = {
            "domain": dom_fail,
            "row_num": 20,
            "mutation_type": "submission_entry",
            "fields": {"提交入口": "https://fail-dir.com/submit"},
            "expected_val": "https://fail-dir.com/submit",
        }

        save_pending_master_mutations("cycle_1", [mut_succ, mut_fail], self.runtime_dir)
        save_pending_master_mutations("cycle_2", [mut_succ, mut_fail], self.runtime_dir)

        # 验证初始已合并去重读取到 2 条
        all_pending = load_pending_master_mutations(runtime_dir=self.runtime_dir)
        self.assertEqual(len(all_pending), 2)

        # 模拟执行恢复：dom_success 成功写入，dom_fail 写入失败（保持在 remaining）
        mock_sheets = MagicMock()
        def mock_get(spreadsheetId, range):
            mock_req = MagicMock()
            if "A10:B10" in range:
                mock_req.execute.return_value = {"values": [[dom_success, dom_success]]}
            elif "A10:N10" in range or "A10:" in range:
                row = [""] * len(MASTER_HEADER)
                row[MASTER_HEADER.index("外链ID")] = dom_success
                row[MASTER_HEADER.index("平台域名")] = dom_success
                row[MASTER_HEADER.index("提交入口")] = "https://succ-dir.com/submit"
                mock_req.execute.return_value = {"values": [row]}
            else:
                mock_req.execute.return_value = {"values": [["unmatched", ""]]}
            return mock_req

        def mock_batch_update(spreadsheetId, body):
            for item in body.get("data", []):
                if "10" in item.get("range", ""):
                    pass  # success
                else:
                    raise ConnectionError("503 Backend Error")
            return MagicMock()

        mock_sheets.spreadsheets().values().get.side_effect = mock_get
        mock_sheets.spreadsheets().values().batchUpdate.side_effect = mock_batch_update

        rem = recover_pending_master_mutations(
            sheets_service=mock_sheets,
            spreadsheet_id="test_sheet_id",
            master_sheet_name="外链总表",
            project_id="cycle_3",
            runtime_dir=self.runtime_dir,
        )

        # 只有 dom_fail 失败并保留
        self.assertEqual(len(rem), 1)
        self.assertEqual(rem[0]["domain"], dom_fail)

        # 验证再次 load 时，dom_success 绝未复活！
        fresh_pending = load_pending_master_mutations(runtime_dir=self.runtime_dir)
        self.assertEqual(len(fresh_pending), 1)
        self.assertEqual(fresh_pending[0]["domain"], dom_fail)

    def test_s5_repeating_existing_limit_preserves_other_known_limits(self):
        """S5 契约：重复上报已有限制时，集合式合并保留，绝不抹除已有其他已知限制。"""
        domain = "multi-limits.com"
        state = init_cycle_state("project-a", 1, [domain], "test_sheet_id", "外链总表", "外链管理", runtime_dir=self.runtime_dir)
        state["active_attempt"] = {"backlink_id": domain, "attempt_count": 1}
        project_rows = [
            {"_sheet_row_num": 8, "项目ID": "project-a", "外链ID": domain, "状态": "待提交", "尝试次数": "0"}
        ]
        # 总表原本已具有两种限制
        master_rows = [
            {
                "_sheet_row_num": 18,
                "外链ID": domain,
                "平台域名": domain,
                "提交入口": "https://multi-limits.com/submit",
                "实测限制": "仅限个人网站; 需要收录审核",
            }
        ]

        # 再次上报已知限制之一: limits="需要收录审核"
        res = record_task_outcome(
            state=state,
            backlink_id=domain,
            status="不适用",
            reason="不符合当前收录条件，需要人工审核收录",
            evidence="现场提示需要收录审核",
            platform_facts={"limits": "需要收录审核"},
            master_rows=master_rows,
            project_rows=project_rows,
            commit=False,
            runtime_dir=self.runtime_dir,
        )

        self.assertTrue(res["ok"])
        m_updates = res.get("master_updates", {})
        # 验证已有限制 100% 完整保留，没有走 else 分支抹除其他限制！
        self.assertEqual(m_updates.get("实测限制"), "仅限个人网站; 需要收录审核")

        # 接着上报新限制 limits="支持中英文"，验证集合式按序追加
        res2 = record_task_outcome(
            state=state,
            backlink_id=domain,
            status="不适用",
            reason="需要支持中英文双语",
            evidence="现场要求双语支持中英文",
            platform_facts={"limits": "支持中英文"},
            master_rows=master_rows,
            project_rows=project_rows,
            commit=False,
            runtime_dir=self.runtime_dir,
        )
        self.assertEqual(res2["master_updates"].get("实测限制"), "仅限个人网站; 需要收录审核; 支持中英文")


if __name__ == "__main__":
    unittest.main()
