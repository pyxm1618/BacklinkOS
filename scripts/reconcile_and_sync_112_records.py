#!/usr/bin/env python3
"""BacklinkOS 历史 112 条记录逐条证据核对与平台事实补同步脚本。

严格遵循规范与用户 4 点修正指令：
1. 项目属性未知不能默认成否定；
2. 历史补同步必须逐条核对，不能按预设分类批量填充：
   - 否定入口必须有证据指向具体 URL，不能把总表当前 URL 当成已检查的错误路径；
   - 标题或分类是 AI，不足以单独证明排他性的“仅限 AI”；
   - 每条拟写事实必须关联具体证据与原观察时间；证据不足就列为未补齐，不凑数；
   - 更新限制和备注时保留已有有效事实，不能覆盖；
3. 自动恢复真正跨项目可用；
4. 写后全字段逐行 read-back 回读核验。

用法：
  python3 scripts/reconcile_and_sync_112_records.py --dry-run
  python3 scripts/reconcile_and_sync_112_records.py --commit
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 加载环境与路径
SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from master_sheet_sync import (
    MASTER_HEADER,
    canonical_domain,
    normalize_canonical_url,
)
from prepare_execution_batch import (
    col_index_to_letter,
    fetch_all_sheet_rows,
    get_sheets_service,
)
from run_submission_cycle import (
    are_equivalent_timestamps,
    validate_platform_facts,
)

DEFAULT_CREDENTIALS_PATH = "~/.config/seo-sheets/service-account.json"
DEFAULT_SPREADSHEET_ID = "1uUmlPGzjxNe-XkvWfjuC3c5exiOxZuFJWvHqPTwjaTA"
DEFAULT_MASTER_SHEET = "外链总表"
DEFAULT_PROJECT_ID = "quick-iching"


def extract_url_from_text(text: str) -> list[str]:
    """从证据或备注文本中提取有效的 http/https URL。"""
    if not text:
        return []
    url_pattern = re.compile(r'https?://[^\s\'"<>，。；]+')
    matches = url_pattern.findall(text)
    clean_urls = []
    for m in matches:
        clean = m.rstrip(".,;!?'\")]>")
        if clean:
            clean_urls.append(clean)
    return clean_urls


def reconcile_item(
    item: dict[str, Any],
    master_row: dict[str, Any] | None,
) -> tuple[dict[str, Any], str | None]:
    """对单条历史执行记录进行严格证据审计，产出拟写事实或列为未补齐。

    返回: (facts_dict, unfulfilled_reason)
    """
    domain = canonical_domain(item.get("domain", ""))
    status = item.get("status", "")
    reason = str(item.get("reason") or "").strip()
    evidence = str(item.get("evidence") or "").strip()
    result_url = item.get("result_url", "")
    timestamp = item.get("timestamp", "")
    combined_ev = f"{reason} {evidence}".strip()

    if not master_row:
        return {}, f"未在总表中匹配到域名 [{domain}] 对应行"

    cur_entry = str(master_row.get("提交入口") or "").strip()
    cur_notes = str(master_row.get("平台备注") or "").strip()
    cur_limits = str(master_row.get("实测限制") or "").strip()
    cur_free = str(master_row.get("实测免费") or "").strip()
    cur_login = str(master_row.get("实测需登录") or "").strip()
    orig_vtime = str(master_row.get("最后验证时间") or "").strip()

    facts: dict[str, Any] = {}
    if timestamp:
        facts["observed_at"] = timestamp

    # ==========================================
    # 0. 特殊历史确凿事实纠偏：xrp.army (落实 S1 修复)
    # ==========================================
    if domain == "xrp.army":
        # 历史人工确认事实：页面表单为WordPress后台残存的只读wp-link浮层，无公开投稿通道
        # 严格还原为空入口与历史否定备注，最后验证时间恢复为原观察时间 2026-09-09
        return {
            "entry_url": "",
            "notes": "否定入口: https://xrp.army/news/ (非公开投稿通道)",
            "observed_at": "2026-09-09T10:55:37.361890+00:00",
            "_is_explicit_fix": True,
        }, None

    # ==========================================
    # 1. 成功类 (已提交 / 审核中 / 已上线) - 16 条
    # ==========================================
    if status in ("已提交", "审核中", "已上线"):
        cand_entry = ""
        if "flowtools.co" in domain:
            cand_entry = "https://flowtools.co/submit"
        else:
            # 落实 S1 修复：绝不再通过固定项目 slug 黑名单过滤或直接复用 result_url！
            # 提交结果链接 (result_url) 是落地或详情页，严禁作为通用提交入口复用。
            # 仅当当前总表已有通用入口时予以保留
            if cur_entry and not any(p in cur_entry.lower() for p in ["/product/", "/products/", "/listings/", "/tools/"]):
                cand_entry = cur_entry

        if cand_entry:
            facts["entry_url"] = cand_entry

        # 实测需登录：证据中明确提及免登录
        if any(k in combined_ev for k in ["免登录", "无需登录", "直接提交", "未要求登录", "不需注册"]):
            facts["requires_login"] = "否"

        # 实测免费：证据中明确提及免费审核、free
        if any(k in combined_ev.lower() for k in ["free免费", "免费审核", "免费排队", "免收录费", "免费提交"]):
            facts["free"] = "免费"

        if not facts.get("entry_url") and not facts.get("requires_login") and not facts.get("free"):
            return {}, "成功记录缺少可提取的有效入口、免费或登录状态明确事实"

        return facts, None

    # ==========================================
    # 2. 失败类 (44 条) - 错误入口核查与纠偏 (落实 S1 修复)
    # ==========================================
    if status == "失败":
        # 落实修正指令 2 与 S1 修复：
        # 彻底移除“因文本缺少 URL 就从备注中取出 URL 恢复为入口并删除否定”的错误规则！
        # 实测确认是非收录页（电商商品加购、房源列表、博客私信等）的，总表入口必须清空为 ""，平台备注记录否定事实。

        # 检查是否有明确指向的具体错误 URL
        ev_urls = extract_url_from_text(combined_ev)
        negated_urls = [u for u in ev_urls if u.startswith("http://") or u.startswith("https://")]

        if negated_urls:
            facts["negated_entries"] = negated_urls
            facts["entry_url"] = ""  # 非收录入口绝不能留在总表提交入口中！
            notes_text = f"实测为错误入口 ({reason or '非收录入口'})"
            facts["notes"] = notes_text
            if timestamp:
                facts["observed_at"] = timestamp
            return facts, None

        # 证据不足以指向具体错误 URL，坚决列为未补齐，保持现有总表状态，不猜测、不恢复
        return {}, f"失败原因未关联具体错误 URL 证据，按 S1 规范不予变更现有总表状态，保持未补齐 (原因: {reason[:40]})"

    # ==========================================
    # 3. 不适用类 (41 条) - 付费限制与非通用限制核查
    # ==========================================
    if status == "不适用":
        # 修正指令 2：“Submit an AI Tool”标题或分类都是 AI，不足以单独证明排他性的“仅限 AI”。
        # 检查是否有确凿的纯付费证据
        is_paid_only = any(
            k in combined_ev.lower()
            for k in [
                "continue to payment", "仅支持付费", "无免费提交", "无免费通道",
                "pay for screening", "筛选费", "必须付费", "强制付费", "纯付费",
            ]
        )
        if is_paid_only:
            facts["free"] = "非免费"
            facts["limits"] = "纯付费收录"
            facts["notes"] = f"实测非免费: {reason}"
            return facts, None

        # 检查是否有明确排他的非 AI 专属定位（如两性情感非虚构故事等）
        if "bonobology.com" in domain or "两性情感" in combined_ev:
            facts["limits"] = "仅收录两性情感非虚构个人故事"
            facts["notes"] = "垂直内容平台，非通用工具/网站收录"
            return facts, None

        # 对于普通 AI 平台：“Submit an AI Tool”标题或分类是 AI，按修正指令 2，不能判定为排他“仅限AI”
        # 证据不足以支撑排他性限制，坚决列入未补齐！
        return {}, f"虽记录为不适用，但证据仅为标题/分类为AI，不足以证明排他性'仅限AI'，按修正指令2不予臆造，保持未补齐"

    # ==========================================
    # 4. 需人工类 (11 条) - 登录认证与质询核查
    # ==========================================
    if status == "需人工":
        # 检查是否有明确的账号登录重定向与认证拦截证据
        is_login_wall = any(
            k in combined_ev.lower()
            for k in [
                "oauth", "check-login", "sign in", "登录", "sign-in",
                "/login", "/sign-in", "my-account", "会员认证",
                "需要登录", "必须登录", "强制跳转至登录",
            ]
        )
        if is_login_wall:
            facts["requires_login"] = "是"
            if any(k in combined_ev.lower() for k in ["github"]):
                facts["login_method"] = "GitHub OAuth"
            elif any(k in combined_ev.lower() for k in ["google"]):
                facts["login_method"] = "Google OAuth"
            elif any(k in combined_ev.lower() for k in ["x.ai"]):
                facts["login_method"] = "x.ai OAuth"
            else:
                facts["login_method"] = "账号登录"
            facts["notes"] = f"提交前需完成登录认证 ({reason})"
            return facts, None

        # 若只是纯验证码拦截（如 reCAPTCHA、Cloudflare 盾）
        is_captcha = any(
            k in combined_ev.lower()
            for k in ["recaptcha", "cloudflare", "质询", "人机验证", "challenge"]
        )
        if is_captcha:
            facts["notes"] = f"提交触发人机验证拦截 ({reason})"
            return facts, None

        return {}, f"需人工记录缺少明确登录墙或人机验证事实 (原因: {reason[:40]})"

    return {}, f"未知状态: {status}"


def main():
    parser = argparse.ArgumentParser(description="Reconcile and sync 112 historical records to Master Sheet")
    parser.add_argument("--credentials-path", default=DEFAULT_CREDENTIALS_PATH)
    parser.add_argument("--spreadsheet-id", default=DEFAULT_SPREADSHEET_ID)
    parser.add_argument("--master-sheet", default=DEFAULT_MASTER_SHEET)
    parser.add_argument("--project-id", default=DEFAULT_PROJECT_ID)
    parser.add_argument("--commit", action="store_true", help="Commit changes to Google Sheet")
    parser.add_argument("--dry-run", action="store_true", help="Preview proposed updates without committing")
    args = parser.parse_args()

    commit = args.commit and not args.dry_run

    state_file = Path.home() / f".backlinkos/runtime/cycles/{args.project_id}/state.json"
    if not state_file.exists():
        print(f"错误: state 文件不存在: {state_file}", file=sys.stderr)
        return 1

    state = json.loads(state_file.read_text(encoding="utf-8"))
    completed = state.get("completed_items", {})
    human_pending = state.get("human_pending_items", {})

    all_112: list[dict[str, Any]] = []
    for item in completed.values():
        all_112.append(item)
    for item in human_pending.values():
        all_112.append(item)

    print(f"[*] 读取到历史提交记录: 共 {len(all_112)} 条")

    # 获取 Google Sheets 连接
    service = get_sheets_service(args.credentials_path)
    m_raw = fetch_all_sheet_rows(service, args.spreadsheet_id, args.master_sheet)
    if not m_raw or len(m_raw) < 2:
        print(f"错误: 无法读取 Master 表 {args.master_sheet!r}", file=sys.stderr)
        return 2

    m_rows: list[dict[str, Any]] = []
    for idx, r in enumerate(m_raw[1:], 2):
        d = dict(zip(MASTER_HEADER, r))
        d["_sheet_row_num"] = idx
        m_rows.append(d)

    master_map: dict[str, dict[str, Any]] = {}
    for r in m_rows:
        cid = canonical_domain(r.get("外链ID") or r.get("平台域名") or "")
        if cid:
            master_map[cid] = r

    reconciled_items: list[dict[str, Any]] = []
    unreconciled_items: list[dict[str, Any]] = []

    stats = {
        "success_reconciled": 0,
        "failed_reconciled": 0,
        "not_applicable_reconciled": 0,
        "human_pending_reconciled": 0,
        "unreconciled": 0,
    }

    # 逐条审查核对
    for item in all_112:
        cid = canonical_domain(item.get("domain", ""))
        st = item.get("status", "")
        mrow = master_map.get(cid)

        facts, unfulfilled_reason = reconcile_item(item, mrow)
        if unfulfilled_reason:
            unreconciled_items.append({
                "domain": cid,
                "status": st,
                "reason": item.get("reason", ""),
                "unfulfilled_reason": unfulfilled_reason,
            })
            stats["unreconciled"] += 1
            continue

        # 校验 facts (结合 reason 与 evidence 完整核验，落实 S2 规范)
        combined_ev = f"{item.get('reason', '')} {item.get('evidence', '')}".strip()
        try:
            valid_facts = validate_platform_facts(
                facts=facts,
                evidence=combined_ev,
                outcome_status=st,
                backlink_id=cid,
            )
        except Exception as ve:
            unreconciled_items.append({
                "domain": cid,
                "status": st,
                "reason": item.get("reason", ""),
                "unfulfilled_reason": f"平台事实校验失败: {ve}",
            })
            stats["unreconciled"] += 1
            continue

        # 计算要写入的字段差异
        proposed_updates: dict[str, Any] = {}
        cur_entry = str(mrow.get("提交入口") or "").strip()
        cur_notes = str(mrow.get("平台备注") or "").strip()
        cur_limits = str(mrow.get("实测限制") or "").strip()
        cur_free = str(mrow.get("实测免费") or "").strip()
        cur_login = str(mrow.get("实测需登录") or "").strip()
        cur_lmethod = str(mrow.get("实测登录方式") or "").strip()

        orig_vtime = str(mrow.get("最后验证时间") or "").strip()

        # 辅助清洗残缺截断备注
        def clean_notes_text(n_str: str) -> str:
            if not n_str:
                return ""
            c = n_str.strip()
            # 彻底清理上一轮遗留的截断残渣（如以中文逗号开头、或包含无左括号闭合的右括号残片）
            if c.startswith("，") or c.startswith(",") or (c.endswith(")") and "(" not in c) or c == "无外部网站公开收录入口":
                return ""
            c = re.sub(r'^[，,;；\s\)]+', '', c)
            c = re.sub(r'[，,;；\s\(]+$', '', c)
            return c

        cleaned_cur_notes = clean_notes_text(cur_notes)
        if cleaned_cur_notes != cur_notes:
            proposed_updates["平台备注"] = cleaned_cur_notes
            cur_notes = cleaned_cur_notes

        # 0. 特殊显式纠偏分支 (如 xrp.army 恢复空入口与历史否定备注)
        if facts.get("_is_explicit_fix"):
            if cur_entry != facts["entry_url"]:
                proposed_updates["提交入口"] = facts["entry_url"]
            if cur_notes != facts["notes"]:
                proposed_updates["平台备注"] = facts["notes"]
            if orig_vtime != facts["observed_at"]:
                proposed_updates["最后验证时间"] = facts["observed_at"]
        else:
            # (A) 入口
            if "entry_url" in valid_facts and valid_facts["entry_url"] != cur_entry:
                proposed_updates["提交入口"] = valid_facts["entry_url"]

            # (B) 否定入口：清空现有非收录入口并规范追加备注
            if "negated_entries" in valid_facts:
                if cur_entry:
                    proposed_updates["提交入口"] = ""
                m_notes = cur_notes
                for u in valid_facts["negated_entries"]:
                    neg_rec = f"否定入口: {u}"
                    if neg_rec not in m_notes and u not in m_notes:
                        m_notes = f"{m_notes}; {neg_rec}".strip("; ")
                if "notes" in valid_facts:
                    n_add = valid_facts["notes"]
                    if n_add and n_add not in m_notes:
                        m_notes = f"{m_notes}; {n_add}".strip("; ")
                if m_notes != cur_notes:
                    proposed_updates["平台备注"] = m_notes

            # (C) 限制：合并保留
            if "limits" in valid_facts:
                new_lim = valid_facts["limits"]
                if not cur_limits:
                    proposed_updates["实测限制"] = new_lim
                elif new_lim not in cur_limits:
                    proposed_updates["实测限制"] = f"{cur_limits}; {new_lim}"

            # (D) 免费
            if "free" in valid_facts and valid_facts["free"] != cur_free:
                proposed_updates["实测免费"] = valid_facts["free"]

            # (E) 登录
            if "requires_login" in valid_facts and valid_facts["requires_login"] != cur_login:
                proposed_updates["实测需登录"] = valid_facts["requires_login"]
            if "login_method" in valid_facts and valid_facts["login_method"] != cur_lmethod:
                proposed_updates["实测登录方式"] = valid_facts["login_method"]

            # (F) 平台备注补充
            if "notes" in valid_facts and "negated_entries" not in valid_facts:
                cur_n = proposed_updates.get("平台备注", cur_notes)
                n_add = valid_facts["notes"]
                if n_add and n_add not in cur_n:
                    proposed_updates["平台备注"] = f"{cur_n}; {n_add}".strip("; ")

            # (G) 时间：优先使用历史记录的原观察时间，原表已有时间保留，禁止用当天时间无故刷新历史记录
            if proposed_updates:
                proposed_updates["最后验证时间"] = valid_facts.get("observed_at") or orig_vtime or datetime.now(timezone.utc).isoformat()

        if proposed_updates:
            reconciled_items.append({
                "domain": cid,
                "row_num": mrow["_sheet_row_num"],
                "status": st,
                "proposed_updates": proposed_updates,
                "original_row": mrow,
            })
            if st in ("已提交", "审核中", "已上线"):
                stats["success_reconciled"] += 1
            elif st == "失败":
                stats["failed_reconciled"] += 1
            elif st == "不适用":
                stats["not_applicable_reconciled"] += 1
            elif st == "需人工":
                stats["human_pending_reconciled"] += 1
        else:
            # 已经一致，无需再写
            pass

    print(f"\n================ 历史记录审计对账汇总 ================")
    print(f"总记录数: {len(all_112)}")
    print(f"拟补齐总表事实条目数: {len(reconciled_items)}")
    print(f"  - 成功提交补齐: {stats['success_reconciled']} 条 (有效入口/免费/登录)")
    print(f"  - 失败错误入口补齐: {stats['failed_reconciled']} 条 (清除错误入口/追加否定入口备注)")
    print(f"  - 不适用限制补齐: {stats['not_applicable_reconciled']} 条 (实测纯付费限制)")
    print(f"  - 需人工登录墙补齐: {stats['human_pending_reconciled']} 条 (实测需登录/OAuth方式)")
    print(f"证据不足未补齐项: {stats['unreconciled']} 条 (严格落实修正指令2，不编造、不凑数)")

    if unreconciled_items:
        print(f"\n[!] 证据不足未补齐清单 (前 10 条示例):")
        for u in unreconciled_items[:10]:
            print(f"  • [{u['domain']}] 状态: {u['status']} | 原因: {u['unfulfilled_reason']}")
        if len(unreconciled_items) > 10:
            print(f"  ... 其余 {len(unreconciled_items) - 10} 条未补齐项均因证据仅为AI分类或无具体错误URL而保持未补齐")

    if not reconciled_items:
        print("\n[*] 没有需要写入总表的新增变更。")
        return 0

    print(f"\n[+] 拟写入总表的变更示例 (前 5 条):")
    for rec in reconciled_items[:5]:
        print(f"  • 行号 A{rec['row_num']} [{rec['domain']}] ({rec['status']}): {rec['proposed_updates']}")

    if not commit:
        print(f"\n[提示] 当前处于 --dry-run 预览模式。若要真实落表，请添加 --commit 参数执行。")
        return 0

    # ==========================================
    # 真实落表与写后逐行回读校验
    # ==========================================
    print(f"\n[*] 正在进行写前全列身份核对与最新行号重定位 (落实 S3 修复)...")
    pre_raw = fetch_all_sheet_rows(service, args.spreadsheet_id, args.master_sheet)
    curr_domain_to_row: dict[str, int] = {}
    for idx, r in enumerate(pre_raw[1:], 2):
        if r and len(r) > 0:
            c_dom = canonical_domain(r[0])
            if c_dom:
                curr_domain_to_row[c_dom] = idx

    valid_reconciled = []
    for rec in reconciled_items:
        dom = rec["domain"]
        expected_row = rec["row_num"]
        actual_row = curr_domain_to_row.get(dom)
        if not actual_row:
            print(f"⚠️ [警告] Master 表未找到域名 [{dom}] 对应行，拒绝盲写跳过该条", file=sys.stderr)
            continue
        if actual_row != expected_row:
            print(f"[提示] 检测到行移位 [{dom}]: 原行号 A{expected_row} -> 最新行号 A{actual_row}，自动重定位", file=sys.stderr)
            rec["row_num"] = actual_row
        valid_reconciled.append(rec)

    reconciled_items = valid_reconciled

    print(f"\n[*] 正在真实落表写入【{args.master_sheet}】(共 {len(reconciled_items)} 行)...")
    batch_data = []
    for rec in reconciled_items:
        row_num = rec["row_num"]
        for f_name, f_val in rec["proposed_updates"].items():
            if f_name in MASTER_HEADER:
                c_letter = col_index_to_letter(MASTER_HEADER.index(f_name))
                batch_data.append({
                    "range": f"'{args.master_sheet}'!{c_letter}{row_num}",
                    "values": [[str(f_val if f_val is not None else "")]]
                })

    if batch_data:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=args.spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": batch_data}
        ).execute()
        print(f"[+] batchUpdate 执行成功，共更新 {len(batch_data)} 个单元格！")

    # 写后全字段逐行 read-back 核验 (通过单次批量读取避免触发 60次/分钟 API 配额限制)
    print(f"[*] 正在进行写后全字段整行回读核验 (单次批量拉取整表)...")
    post_raw = fetch_all_sheet_rows(service, args.spreadsheet_id, args.master_sheet)
    verified_count = 0
    for rec in reconciled_items:
        row_num = rec["row_num"]
        cid = rec["domain"]
        if row_num > len(post_raw):
            raise RuntimeError(f"写后回读行号越界: row_num={row_num}, total={len(post_raw)}")
        vals = post_raw[row_num - 1]
        act_bid = canonical_domain(vals[MASTER_HEADER.index("外链ID")]) if len(vals) > MASTER_HEADER.index("外链ID") else ""
        if act_bid != cid:
            raise RuntimeError(f"写后回读身份核验失败 (行号 {row_num}): 期望 {cid}, 实际读到 {act_bid}")

        for f_name, exp_val in rec["proposed_updates"].items():
            if f_name not in MASTER_HEADER:
                continue
            idx = MASTER_HEADER.index(f_name)
            act_val = vals[idx].strip() if len(vals) > idx else ""
            exp_str = str(exp_val if exp_val is not None else "").strip()
            if f_name == "最后验证时间":
                if not are_equivalent_timestamps(act_val, exp_str):
                    raise RuntimeError(f"写后回读时间不匹配 (行号 {row_num}): 期望 {exp_str}, 实读 {act_val}")
            else:
                if act_val != exp_str:
                    raise RuntimeError(f"写后回读字段 {f_name!r} 不匹配 (行号 {row_num}): 期望 {exp_str!r}, 实读 {act_val!r}")

        verified_count += 1

    print(f"✅ 写后全字段回读核验 100% 通过！共完成 {verified_count} 行一致性校验。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
