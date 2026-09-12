#!/usr/bin/env python3
"""生产数据对账与修复脚本 (Reconcile and Fix Historical Observations).

严格按真实操作证据逐条修复此前 5 个历史站点的状态与事实落表：
1. listedai.co: Phase D 真实填写提交并成功回执 -> 项目表尝试次数修正为 1；
2. xrp.army: Phase D 真实访问页面确认无公开通道 -> 项目表尝试次数修正为 1；总表清空入口，在平台备注追加否定入口，基础状态保持候选；
3. lbbai.com: 原报告 Phase D 真实访问耗时 163 秒确认全为 AI 分类 -> 项目表尝试次数修正为 1；总表实测限制写入'仅限AI工具'，最后验证时间写入原观察时间 2026-09-09T09:54:36Z；
4. grokipedia.com: Phase D 真实访问遇到 OAuth 拦截 -> 项目表尝试次数修正为 1；
5. extensionauditor.com: Phase D 真实访问遇到 Cloudflare 质询 -> 项目表尝试次数修正为 1。

支持 --dry-run 预览与 --commit 真实写回核验。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from master_sheet_sync import (
    MASTER_HEADER,
    PROJECT_HEADER,
    canonical_domain,
)
from prepare_execution_batch import col_index_to_letter, fetch_all_sheet_rows, get_sheets_service
from run_submission_cycle import load_cycle_state, save_cycle_state


HISTORICAL_OBSERVATIONS = {
    "listedai.co": {
        "domain": "listedai.co",
        "project_status": "审核中",
        "project_attempts": "1",
        "evidence_summary": "POST https://www.listedai.co/submit 返回 200, 响应: Tool submitted! Your tool will be reviewed and published soon",
        "master_updates": {},
    },
    "xrp.army": {
        "domain": "xrp.army",
        "project_status": "失败",
        "project_attempts": "1",
        "evidence_summary": "页面表单为WordPress后台残存的只读wp-link浮层，无公开投稿通道",
        "master_updates": {
            "提交入口": "",
            "平台备注_append": "否定入口: https://xrp.army/news/ (非公开投稿通道)",
        },
    },
    "lbbai.com": {
        "domain": "lbbai.com",
        "project_status": "不适用",
        "project_attempts": "1",
        "evidence_summary": "页面分类均为AI工具(如AI写作、AI图像、AI效率等)，无非AI通用分类",
        "master_updates": {
            "实测限制": "仅限AI工具",
            "最后验证时间": "2026-09-09T09:54:36Z",  # 严格使用原观察时间
        },
    },
    "grokipedia.com": {
        "domain": "grokipedia.com",
        "project_status": "需人工",
        "project_attempts": "1",
        "evidence_summary": "点击Suggest Article与Sign in均强制跳转至 https://accounts.x.ai/check-login 进行认证",
        "master_updates": {},
    },
    "extensionauditor.com": {
        "domain": "extensionauditor.com",
        "project_status": "需人工",
        "project_attempts": "1",
        "evidence_summary": "页面跳转至 Cloudflare challenge: __cf_chl_rt_tk, Title: Just a moment...",
        "master_updates": {},
    },
}


def build_plan(
    master_rows: list[dict[str, Any]],
    project_rows: list[dict[str, Any]],
    project_id: str,
    master_sheet_name: str,
    project_sheet_name: str,
) -> dict[str, Any]:
    project_mutations = []
    master_mutations = []

    prow_by_bid = {}
    for r in project_rows:
        if str(r.get("项目ID") or "").strip() == project_id:
            bid = canonical_domain(r.get("外链ID") or r.get("外链域名") or "")
            if bid:
                prow_by_bid[bid] = r

    mrow_by_bid = {}
    for r in master_rows:
        bid = canonical_domain(r.get("外链ID") or r.get("平台域名") or "")
        if bid:
            mrow_by_bid[bid] = r

    for bid, spec in HISTORICAL_OBSERVATIONS.items():
        pr = prow_by_bid.get(bid)
        if not pr or not pr.get("_sheet_row_num"):
            print(f"[警告] 项目表中未找到目标行: {bid}", file=sys.stderr)
            continue
        p_rnum = pr["_sheet_row_num"]
        cur_status = str(pr.get("状态") or "").strip()
        cur_attempts = str(pr.get("尝试次数") or "").strip()

        # 检查尝试次数与状态修复
        target_status = spec["project_status"]
        target_attempts = spec["project_attempts"]

        # 严格安全防御 (落实复核限制：遇到新历史或不一致直接拒绝，禁止覆盖后来真实成果)
        if cur_attempts not in ("", "0", target_attempts):
            raise ValueError(f"安全拒绝：[{bid}] 存在更新的尝试次数 ({cur_attempts} != 预期历史)，禁止覆盖新成果")
        if cur_status not in ("", target_status):
            raise ValueError(f"安全拒绝：[{bid}] 存在更新的状态 ({cur_status} != 预期历史)，禁止覆盖新成果")

        p_updates = []
        if cur_attempts != target_attempts:
            att_col = col_index_to_letter(PROJECT_HEADER.index("尝试次数"))
            p_updates.append({
                "cell": f"'{project_sheet_name}'!{att_col}{p_rnum}",
                "column": "尝试次数",
                "old_val": cur_attempts,
                "new_val": target_attempts,
            })
        if cur_status != target_status:
            st_col = col_index_to_letter(PROJECT_HEADER.index("状态"))
            p_updates.append({
                "cell": f"'{project_sheet_name}'!{st_col}{p_rnum}",
                "column": "状态",
                "old_val": cur_status,
                "new_val": target_status,
            })

        if p_updates:
            project_mutations.append({
                "domain": bid,
                "row_num": p_rnum,
                "updates": p_updates,
            })

        # 检查 Master 表更新
        m_updates = spec.get("master_updates", {})
        if m_updates:
            mr = mrow_by_bid.get(bid)
            if not mr or not mr.get("_sheet_row_num"):
                print(f"[警告] 总表中未找到对应平台行: {bid}", file=sys.stderr)
                continue
            m_rnum = mr["_sheet_row_num"]
            m_muts = []

            for col_name, new_val in m_updates.items():
                if col_name.endswith("_append"):
                    real_col = col_name.replace("_append", "")
                    cur_val = str(mr.get(real_col) or "").strip()
                    if new_val not in cur_val:
                        combined = f"{cur_val} | {new_val}".strip(" |") if cur_val else new_val
                        c_idx = MASTER_HEADER.index(real_col)
                        c_letter = col_index_to_letter(c_idx)
                        m_muts.append({
                            "cell": f"'{master_sheet_name}'!{c_letter}{m_rnum}",
                            "column": real_col,
                            "old_val": cur_val,
                            "new_val": combined,
                        })
                else:
                    cur_val = str(mr.get(col_name) or "").strip()
                    if cur_val != new_val:
                        c_idx = MASTER_HEADER.index(col_name)
                        c_letter = col_index_to_letter(c_idx)
                        m_muts.append({
                            "cell": f"'{master_sheet_name}'!{c_letter}{m_rnum}",
                            "column": col_name,
                            "old_val": cur_val,
                            "new_val": new_val,
                        })

            if m_muts:
                master_mutations.append({
                    "domain": bid,
                    "row_num": m_rnum,
                    "updates": m_muts,
                })

    return {
        "project_mutations": project_mutations,
        "master_mutations": master_mutations,
    }


def execute_plan(
    service: Any,
    spreadsheet_id: str,
    plan: dict[str, Any],
) -> None:
    batch_vals = []
    for pm in plan["project_mutations"]:
        for u in pm["updates"]:
            batch_vals.append({
                "range": u["cell"],
                "values": [[u["new_val"]]],
            })
    for mm in plan["master_mutations"]:
        for u in mm["updates"]:
            batch_vals.append({
                "range": u["cell"],
                "values": [[u["new_val"]]],
            })

    if not batch_vals:
        print("[*] 所有目标行与单元格均已是最新，无待执行变更。")
        return

    print(f"[*] 正在执行真实写回 (共 {len(batch_vals)} 处单元格更新)...")
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "USER_ENTERED", "data": batch_vals},
    ).execute()

    print("[*] 写后回读校验中...")
    for pm in plan["project_mutations"]:
        for u in pm["updates"]:
            rb = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=u["cell"],
            ).execute()
            rb_val = (rb.get("values", [[]])[0] or [""])[0]
            if rb_val != u["new_val"]:
                raise RuntimeError(f"回读校验失败: {u['cell']} 期望 {u['new_val']!r}, 实读 {rb_val!r}")
            print(f"  ✅ [项目表] {pm['domain']} ({u['column']}): {rb_val}")

    for mm in plan["master_mutations"]:
        for u in mm["updates"]:
            rb = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=u["cell"],
            ).execute()
            rb_val = (rb.get("values", [[]])[0] or [""])[0]
            if rb_val != u["new_val"]:
                raise RuntimeError(f"回读校验失败: {u['cell']} 期望 {u['new_val']!r}, 实读 {rb_val!r}")
            print(f"  ✅ [总表] {mm['domain']} ({u['column']}): {rb_val}")

    print("🎉 全部修改已通过 exact read-back 核验完成！")


def update_local_cycle(project_id: str) -> None:
    state = load_cycle_state(project_id)
    if not state:
        return
    # 更新 state 中的 5 个站点明细
    for bid, spec in HISTORICAL_OBSERVATIONS.items():
        if bid in state.get("completed_items", {}):
            item = state["completed_items"][bid]
            item["status"] = spec["project_status"]
            item["attempts"] = int(spec["project_attempts"])
        elif bid in state.get("human_pending_items", {}):
            item = state["human_pending_items"][bid]
            item["status"] = spec["project_status"]
            item["attempts"] = int(spec["project_attempts"])
    save_cycle_state(project_id, state)
    print("[*] 本地 cycle state.json 已同步更新完成。")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile and Fix Historical Observations")
    parser.add_argument("--project-id", default="quick-iching")
    parser.add_argument("--spreadsheet-id", default=os.environ.get("BACKLINK_SPREADSHEET_ID", "1uUmlPGzjxNe-XkvWfjuC3c5exiOxZuFJWvHqPTwjaTA"))
    parser.add_argument("--credentials-path", default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "~/.config/seo-sheets/service-account.json"))
    parser.add_argument("--master-sheet", default="外链总表")
    parser.add_argument("--project-sheet", default="外链管理")
    parser.add_argument("--commit", action="store_true", default=False, help="Commit changes to Google Sheet")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Preview changes without committing")
    args = parser.parse_args()

    cred_file = os.path.expanduser(args.credentials_path)
    if not os.path.exists(cred_file):
        print(f"错误: 找不到凭据文件: {cred_file}", file=sys.stderr)
        return 2

    service = get_sheets_service(args.credentials_path)
    print(f"[*] 读取生产工作表: {args.spreadsheet_id}...")
    m_raw = fetch_all_sheet_rows(service, args.spreadsheet_id, args.master_sheet)
    p_raw = fetch_all_sheet_rows(service, args.spreadsheet_id, args.project_sheet)

    m_rows = []
    if m_raw and len(m_raw) > 1:
        for idx, r in enumerate(m_raw[1:], 2):
            d = dict(zip(MASTER_HEADER, r))
            d["_sheet_row_num"] = idx
            m_rows.append(d)

    p_rows = []
    if p_raw and len(p_raw) > 1:
        for idx, r in enumerate(p_raw[1:], 2):
            d = dict(zip(PROJECT_HEADER, r))
            d["_sheet_row_num"] = idx
            p_rows.append(d)

    plan = build_plan(
        master_rows=m_rows,
        project_rows=p_rows,
        project_id=args.project_id,
        master_sheet_name=args.master_sheet,
        project_sheet_name=args.project_sheet,
    )

    print("\n==================================================")
    print(f"生产数据修复差异预览 [{args.project_id}]")
    print("==================================================")
    print(f"待修复项目表行数: {len(plan['project_mutations'])}")
    for pm in plan["project_mutations"]:
        print(f"  • [项目表行 {pm['row_num']}] {pm['domain']}:")
        for u in pm["updates"]:
            print(f"      - {u['column']} ({u['cell']}): '{u['old_val']}' -> '{u['new_val']}'")

    print(f"\n待修复总表行数: {len(plan['master_mutations'])}")
    for mm in plan["master_mutations"]:
        print(f"  • [总表行 {mm['row_num']}] {mm['domain']}:")
        for u in mm["updates"]:
            print(f"      - {u['column']} ({u['cell']}): '{u['old_val']}' -> '{u['new_val']}'")
    print("==================================================\n")

    if args.commit:
        execute_plan(service, args.spreadsheet_id, plan)
        update_local_cycle(args.project_id)
    else:
        print("[提示] 当前为 --dry-run 预览模式。确认无误后添加 --commit 执行真实写回。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
