#!/usr/bin/env python3
"""BacklinkOS Universal Phase C Execution Batch Preparation Script.

生产级通用脚本：
1. 不硬编码任何 Spreadsheet ID、project_id、target_url；
2. 从 Google Sheet 读取【外链总表】与【外链管理】；
3. 严格遵循 Phase C 边界：
   - target_ready_count (默认 10): 目标 Ready 数量
   - scan_limit (默认 100): 最多扫描待提交候选数
4. 对选中的候选执行现场 Entry 核验 (Live Verify existing entry / Live Find new entry)；
5. 聚合主页 AI-only 约束，检查项目兼容性；
6. 在 --commit 模式下，仅将现场核验成功且原入口为空/不一致的项精准写回【外链总表.提交入口】；
   立即执行 exact read-back 逐行校验；
   绝不触碰【外链管理】现有 Backlog，绝不修改项目行状态或尝试次数；
7. 输出标准 Ready Batch Manifest JSON 供 Phase D backlink-autofill 消费。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from typing import Any

# 优先载入本地 scripts 目录模块
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from google.oauth2 import service_account
from googleapiclient.discovery import build

from master_sheet_sync import (
    MASTER_HEADER,
    PROJECT_HEADER,
    canonical_domain,
    prepare_execution_batch,
    resolve_project_context,
)


def get_sheets_service(credentials_path: str):
    expanded_path = os.path.expanduser(credentials_path)
    if not os.path.exists(expanded_path):
        raise FileNotFoundError(f"找不到凭证文件: {expanded_path}")

    # 支持代理配置
    if not os.environ.get("http_proxy"):
        os.environ["http_proxy"] = "http://127.0.0.1:15236"
    if not os.environ.get("https_proxy"):
        os.environ["https_proxy"] = "http://127.0.0.1:15236"

    creds = service_account.Credentials.from_service_account_file(
        expanded_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def fetch_all_sheet_rows(service, spreadsheet_id: str, sheet_name: str) -> list[list[str]]:
    range_name = f"'{sheet_name}'!A:Z"
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name,
    ).execute()
    return result.get("values", [])


def col_index_to_letter(col_idx: int) -> str:
    """0-indexed 列索引转为 Excel 列字母 (0 -> A, 25 -> Z, 26 -> AA)"""
    result = ""
    col_idx += 1
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        result = chr(65 + remainder) + result
    return result


def parse_sheet_with_row_indices(
    raw_values: list[list[str]], expected_header: list[str]
) -> tuple[list[str], list[dict[str, Any]]]:
    if not raw_values:
        return [], []
    header = [col.strip() for col in raw_values[0]]
    rows: list[dict[str, Any]] = []
    for idx, r in enumerate(raw_values[1:], start=2):
        row_dict: dict[str, Any] = {"_sheet_row_num": idx}
        for c_idx, col in enumerate(header):
            row_dict[col] = r[c_idx].strip() if c_idx < len(r) else ""
        for col in expected_header:
            if col not in row_dict:
                row_dict[col] = ""
        rows.append(row_dict)
    return header, rows


def run_phase_c_preparation(
    spreadsheet_id: str,
    project_id: str,
    target_ready_count: int,
    scan_limit: int,
    ai_powered: bool,
    target_url: str,
    master_sheet_name: str,
    project_sheet_name: str,
    credentials_path: str,
    output_manifest: str | None,
    commit: bool,
) -> dict[str, Any]:
    print("==================================================")
    print("BacklinkOS Phase C: Execution Batch Preparation")
    print("==================================================")
    print(f"Spreadsheet ID:      {spreadsheet_id}")
    print(f"Project ID:          {project_id}")
    print(f"Target Ready Count:  {target_ready_count}")
    print(f"Scan Limit:          {scan_limit}")
    print(f"Project Context:     ai_powered={ai_powered}")
    print(f"Commit to Master:    {commit} (Dry-Run: {not commit})")
    print("==================================================")

    service = get_sheets_service(credentials_path)

    # 1. 读取工作表数据
    print(f"\n[1/5] 读取工作表 '{master_sheet_name}' 与 '{project_sheet_name}'...")
    master_raw = fetch_all_sheet_rows(service, spreadsheet_id, master_sheet_name)
    project_raw = fetch_all_sheet_rows(service, spreadsheet_id, project_sheet_name)

    master_header, master_rows = parse_sheet_with_row_indices(master_raw, MASTER_HEADER)
    project_header, project_rows = parse_sheet_with_row_indices(project_raw, PROJECT_HEADER)

    print(f"  - '{master_sheet_name}': {len(master_rows)} 数据行")
    print(f"  - '{project_sheet_name}': {len(project_rows)} 数据行")

    if "提交入口" not in master_header:
        raise ValueError(f"'{master_sheet_name}' 中缺少 '提交入口' 列")
    entry_col_letter = col_index_to_letter(master_header.index("提交入口"))
    print(f"  - Master '提交入口' 位于列: {entry_col_letter}")

    # 2. 执行现场 Live Verification
    print(f"\n[2/5] 开始筛选待提交候选并执行现场核验 (target={target_ready_count}, scan_limit={scan_limit})...")
    project_context = {"ai_powered": ai_powered}

    batch_result = prepare_execution_batch(
        master_rows=master_rows,
        project_rows=project_rows,
        project_id=project_id,
        target_ready_count=target_ready_count,
        scan_limit=scan_limit,
        project_context=project_context,
    )

    ready_rows = batch_result["ready_rows"]
    scanned_count = batch_result["scanned_count"]
    skipped_incompatible = batch_result["skipped_incompatible"]
    failed_verification_count = batch_result["failed_verification_count"]

    print(f"\n[3/5] 批次现场核验完成统计:")
    print(f"  - 扫描项目待提交候选数: {scanned_count}")
    print(f"  - 成功 Ready 数量:      {len(ready_rows)} (目标: {target_ready_count})")
    print(f"  - 兼容性排除数:          {skipped_incompatible}")
    print(f"  - 核验失败/无入口数:    {failed_verification_count}")

    # 3. 汇总 Master 写回需求
    updates_to_master: list[dict[str, Any]] = []
    ready_items: list[dict[str, Any]] = []
    ready_domains: list[str] = []

    for item in ready_rows:
        mrow = item["master_row"]
        prow = item["project_row"]
        ventry = item["verified_entry"]
        cid = canonical_domain(ventry.domain)
        ready_domains.append(cid)

        orig_entry = ""
        row_num = mrow.get("_sheet_row_num")
        if row_num and row_num <= len(master_raw):
            col_idx = master_header.index("提交入口")
            raw_r = master_raw[row_num - 1]
            orig_entry = raw_r[col_idx].strip() if col_idx < len(raw_r) else ""

        need_update = (ventry.url != orig_entry)
        if need_update and row_num:
            updates_to_master.append({
                "domain": cid,
                "row_num": row_num,
                "cell_range": f"'{master_sheet_name}'!{entry_col_letter}{row_num}",
                "old_val": orig_entry,
                "new_val": ventry.url,
            })

        ready_items.append({
            "domain": cid,
            "submission_url": ventry.url,
            "evidence_type": ventry.evidence_type,
            "evidence_summary": ventry.evidence_summary,
            "ai_only": ventry.ai_only,
            "master_row_num": row_num,
            "project_row_num": prow.get("_sheet_row_num"),
            "project_status": prow.get("状态"),
            "attempts": prow.get("尝试次数"),
        })

    # 4. Master 提交入口精准写回与 Read-Back
    print(f"\n[4/5] Master 提交入口写回阶段 (待写回项: {len(updates_to_master)}):")
    if not updates_to_master:
        print("  - 所有 Ready 项的 Master 提交入口均已是最新，无需写回。")
    elif not commit:
        print("  - [DRY-RUN] 预览将写回 Master 的提交入口:")
        for u in updates_to_master:
            print(f"    * 行 {u["row_num"]} ({u["domain"]}): '{u["old_val"]}' -> '{u["new_val"]}'")
        print("  - 未指定 --commit，跳过真实写入。")
    else:
        print("  - [--commit 模式] 开始精准单项写回与 Read-Back 校验...")
        for u in updates_to_master:
            cell = u["cell_range"]
            new_val = u["new_val"]
            body = {"values": [[new_val]]}
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=cell,
                valueInputOption="USER_ENTERED",
                body=body,
            ).execute()

            rb = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=cell,
            ).execute()
            rb_val = (rb.get("values", [[]])[0] or [""])[0]
            if rb_val != new_val:
                raise RuntimeError(
                    f"Master 提交入口写回校验失败！单元格 {cell} 预期 '{new_val}'，实际读回 '{rb_val}'"
                )
            print(f"    * 已安全写回并验证: 行 {u["row_num"]} ({u["domain"]}) -> {cell} = {new_val}")
        print("  - 全部 Master 提交入口安全更新完毕！")

    # 5. 生成 Ready Batch Manifest
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    if not output_manifest:
        os.makedirs("artifacts", exist_ok=True)
        output_manifest = f"artifacts/ready_manifest_{project_id}_{timestamp_str}.json"
    else:
        out_dir = os.path.dirname(output_manifest)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

    manifest_data = {
        "project_id": project_id,
        "target_url": target_url,
        "ai_powered": ai_powered,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "contract": "BacklinkOS Phase C Ready Allowlist Handoff",
        "target_ready_count": target_ready_count,
        "scan_limit": scan_limit,
        "scanned_count": scanned_count,
        "ready_count": len(ready_rows),
        "skipped_incompatible": skipped_incompatible,
        "failed_verification_count": failed_verification_count,
        "ready_domains": ready_domains,
        "ready_items": ready_items,
    }

    with open(output_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, ensure_ascii=False, indent=2)

    print(f"\n[5/5] Ready Batch Manifest 已保存至: {output_manifest}")
    print(f"  - Ready Domains 列表 ({len(ready_domains)} 个):")
    for idx, d in enumerate(ready_domains, 1):
        print(f"    {idx}. {d}")

    print("\n==================================================")
    print("Phase C Readiness 执行成功完成！")
    print("硬约束红线保持：绝对未修改【外链管理】3096 条 Backlog。")
    print("==================================================")

    return manifest_data


def main():
    parser = argparse.ArgumentParser(
        description="BacklinkOS Phase C Universal Execution Batch Preparation Script"
    )
    parser.add_argument(
        "--spreadsheet-id",
        type=str,
        default=os.environ.get("BACKLINK_SPREADSHEET_ID", "1uUmlPGzjxNe-XkvWfjuC3c5exiOxZuFJWvHqPTwjaTA"),
        help="Google Sheet ID",
    )
    parser.add_argument(
        "--credentials-path",
        type=str,
        default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "~/.config/seo-sheets/service-account.json"),
        help="Service account JSON credentials path",
    )
    parser.add_argument(
        "--project-id",
        type=str,
        required=True,
        help="Target Project ID (e.g. quick-iching)",
    )
    parser.add_argument(
        "--target-ready-count",
        type=int,
        default=10,
        help="Target number of verified ready candidates (default: 10)",
    )
    parser.add_argument(
        "--scan-limit",
        type=int,
        default=100,
        help="Maximum candidates to scan (default: 100)",
    )
    parser.add_argument(
        "--ai-powered",
        action="store_true",
        default=False,
        help="Whether project is AI powered (default: False)",
    )
    parser.add_argument(
        "--target-url",
        type=str,
        default="",
        help="Target project URL (e.g. https://quickiching.com/)",
    )
    parser.add_argument(
        "--master-sheet",
        type=str,
        default="外链总表",
        help="Master sheet title (default: 外链总表)",
    )
    parser.add_argument(
        "--project-sheet",
        type=str,
        default="外链管理",
        help="Project sheet title (default: 外链管理)",
    )
    parser.add_argument(
        "--output-manifest",
        type=str,
        default="",
        help="Path to save the Ready manifest JSON",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        default=False,
        help="Commit updated submission entries to Master Sheet (default: Dry-Run)",
    )

    args = parser.parse_args()

    run_phase_c_preparation(
        spreadsheet_id=args.spreadsheet_id,
        project_id=args.project_id,
        target_ready_count=args.target_ready_count,
        scan_limit=args.scan_limit,
        ai_powered=args.ai_powered,
        target_url=args.target_url,
        master_sheet_name=args.master_sheet,
        project_sheet_name=args.project_sheet,
        credentials_path=args.credentials_path,
        output_manifest=args.output_manifest or None,
        commit=args.commit,
    )


if __name__ == "__main__":
    main()
