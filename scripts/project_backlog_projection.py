#!/usr/bin/env python3
"""BacklinkOS Universal Project Backlog Projection and Audit Production Script.

通用生产级脚本：
1. 不硬编码任何 Spreadsheet ID、project_id、target_url；
2. 支持 --dry-run 与 --commit 模式；
3. 纯内存/数据库逻辑投影，绝不发起网络爬虫请求；
4. 提交前自动创建独立时间戳备份工作表（如 外链管理_backup_YYYYMMDD_HHMMSS），绝不覆盖旧备份；
5. 自动检查工作表 rowCount 容量，仅在必要时安全扩大 rowCount，绝不修改 Header、列结构或枚举契约；
6. 分批写入（默认 200 行/批）并立即执行 exact read-back 逐行校验；
7. 执行最终 LEFT JOIN 完整性审计，报告所有候选的覆盖与跳过原因。
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from collections import Counter
from typing import Any

# 优先载入本地 scripts 目录模块
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from google.oauth2 import service_account
from googleapiclient.discovery import build

from master_sheet_sync import (
    MASTER_HEADER,
    MASTER_STATUS_CANDIDATE,
    MASTER_STATUS_DEAD,
    MASTER_STATUS_EXCLUDED,
    PROJECT_HEADER,
    canonical_domain,
    get_persisted_project_incompatibility,
    materialize_project_backlog_rows,
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


def get_sheet_properties(service, spreadsheet_id: str, sheet_name: str) -> dict[str, Any]:
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for s in meta.get("sheets", []):
        props = s.get("properties", {})
        if props.get("title") == sheet_name:
            return props
    raise ValueError(f"工作表 '{sheet_name}' 在表格 {spreadsheet_id} 中不存在")


def create_timestamped_backup(service, spreadsheet_id: str, source_sheet_props: dict[str, Any]) -> str:
    now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_title = f"{source_sheet_props['title']}_backup_{now_str}"
    source_sheet_id = source_sheet_props["sheetId"]

    req = {
        "duplicateSheet": {
            "sourceSheetId": source_sheet_id,
            "newSheetName": backup_title,
        }
    }
    body = {"requests": [req]}
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body=body,
    ).execute()
    return backup_title


def ensure_sheet_capacity(
    service,
    spreadsheet_id: str,
    sheet_props: dict[str, Any],
    needed_total_rows: int,
    buffer_rows: int = 500,
) -> int:
    sheet_id = sheet_props["sheetId"]
    current_capacity = sheet_props.get("gridProperties", {}).get("rowCount", 1000)
    target_capacity = needed_total_rows + buffer_rows

    if current_capacity < target_capacity:
        print(f">>> 当前工作表 '{sheet_props['title']}' rowCount={current_capacity}，不足以容纳 {needed_total_rows} 行数据。")
        print(f">>> 正在安全扩容 rowCount 至 {target_capacity}（保留 buffer={buffer_rows}，不修改列结构与格式）...")
        req = {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {
                        "rowCount": target_capacity,
                    },
                },
                "fields": "gridProperties.rowCount",
            }
        }
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [req]},
        ).execute()
        print(f">>> 扩容完成！新 rowCount={target_capacity}")
        return target_capacity
    else:
        print(f">>> 当前工作表容量充足 (rowCount={current_capacity} >= 目标需求 {target_capacity})，无需扩容。")
        return current_capacity


def parse_rows_to_dicts(raw_values: list[list[str]], expected_header: list[str]) -> list[dict[str, str]]:
    if not raw_values:
        return []
    header = [col.strip() for col in raw_values[0]]
    rows = []
    for r in raw_values[1:]:
        row_dict = {}
        for idx, col in enumerate(header):
            row_dict[col] = r[idx].strip() if idx < len(r) else ""
        # 补全缺失列
        for col in expected_header:
            if col not in row_dict:
                row_dict[col] = ""
        rows.append(row_dict)
    return rows


def run_projection(
    spreadsheet_id: str,
    project_id: str,
    target_url: str,
    ai_powered: bool,
    master_sheet_name: str,
    project_sheet_name: str,
    credentials_path: str,
    batch_size: int,
    commit: bool,
) -> dict[str, Any]:
    print(f"==================================================")
    print(f"BacklinkOS Universal Project Backlog Projection")
    print(f"==================================================")
    print(f"Spreadsheet ID: {spreadsheet_id}")
    print(f"项目ID: {project_id}")
    print(f"目标URL: {target_url}")
    print(f"ai_powered: {ai_powered}")
    print(f"模式: {'【COMMIT 真实写库】' if commit else '【DRY RUN 预检模拟】'}")
    print(f"--------------------------------------------------")

    service = get_sheets_service(credentials_path)

    # 1. 实时读取数据
    print(f">>> 正在读取实时 Google Sheet 数据...")
    master_props = get_sheet_properties(service, spreadsheet_id, master_sheet_name)
    project_props = get_sheet_properties(service, spreadsheet_id, project_sheet_name)

    master_raw = fetch_all_sheet_rows(service, spreadsheet_id, master_sheet_name)
    project_raw = fetch_all_sheet_rows(service, spreadsheet_id, project_sheet_name)

    print(f"  读取到【{master_sheet_name}】原始行数: {len(master_raw)}")
    print(f"  读取到【{project_sheet_name}】原始行数: {len(project_raw)}")

    master_dicts = parse_rows_to_dicts(master_raw, MASTER_HEADER)
    project_dicts = parse_rows_to_dicts(project_raw, PROJECT_HEADER)

    # 统计 Master 状态
    master_status_counter = Counter(r.get("基础状态") for r in master_dicts)
    total_master = len(master_dicts)
    candidate_master = master_status_counter.get(MASTER_STATUS_CANDIDATE, 0)
    excluded_master = master_status_counter.get(MASTER_STATUS_EXCLUDED, 0)
    dead_master = master_status_counter.get(MASTER_STATUS_DEAD, 0)

    print(f"\n【外链总表实时统计】")
    print(f"  总平台数: {total_master}")
    print(f"  候选: {candidate_master}")
    print(f"  已排除: {excluded_master}")
    print(f"  失效: {dead_master}")
    for st, cnt in master_status_counter.items():
        if st not in (MASTER_STATUS_CANDIDATE, MASTER_STATUS_EXCLUDED, MASTER_STATUS_DEAD):
            print(f"  其他状态 ({st}): {cnt}")

    # 统计当前项目历史状态
    existing_cur_project = [r for r in project_dicts if r.get("项目ID") == project_id]
    cur_project_status_counter = Counter(r.get("状态") for r in existing_cur_project)

    print(f"\n【外链管理现有项目统计 (project_id={project_id})】")
    print(f"  现有总行数: {len(existing_cur_project)}")
    for st, cnt in cur_project_status_counter.items():
        print(f"  状态 {st}: {cnt}")

    # 2. 运行纯数据库级 Backlog Projection
    print(f"\n>>> 正在运行 Project Backlog Projection（纯内存/数据库级，0 网络请求）...")
    project_context = {"ai_powered": ai_powered}
    new_project_rows, stats = materialize_project_backlog_rows(
        master_rows=master_dicts,
        existing_project_rows=project_dicts,
        project_id=project_id,
        target_url=target_url,
        project_context=project_context,
    )

    print(f"\n【Projection 计算统计】")
    print(f"  Master 候选数: {stats['candidate_count']}")
    print(f"  当前项目现有记录数: {stats['existing_project_count']}")
    print(f"  本轮将新建 Backlog 行数 (would_create_count): {stats['would_create_count']}")
    print(f"  已有记录完全保护数 (duplicate_preserved_count): {stats['duplicate_preserved_count']}")
    print(f"  Master 硬负例排除数 (master_hard_negative_count): {stats['master_hard_negative_count']}")
    print(f"  已证实项目硬不兼容数 (proven_project_incompatible_count): {stats['proven_project_incompatible_count']}")

    if stats["incompatible_details"]:
        print(f"\n【已证实硬不兼容详情 (共 {len(stats['incompatible_details'])} 个)】")
        for item in stats["incompatible_details"]:
            print(f"  - 域名: {item['domain']}, 证据: '{item['evidence']}', 原因: {item['reason']}")

    # Sanity check
    if stats["would_create_count"] < 100:
        raise RuntimeError(
            f"Projection 异常拦截：would_create_count={stats['would_create_count']} 远低于合理预期（千级）！"
            f"请检查是否错误复用了 Entry Verification 过滤。"
        )

    if not commit:
        print(f"\n==================================================")
        print(f"【DRY RUN 预检通过】未对 Google Sheet 作任何修改。")
        print(f"若要执行真实写入，请传入 --commit 参数。")
        print(f"==================================================")
        return {
            "stats": stats,
            "master_stats": master_status_counter,
            "new_rows_count": len(new_project_rows),
            "commit": False,
        }

    # ==========================================
    # 真实写入执行阶段
    # ==========================================
    print(f"\n==================================================")
    print(f"开始执行真实 Sheet 写入")
    print(f"==================================================")

    # 3. 创建时间戳备份
    print(f">>> 正在为 '{project_sheet_name}' 创建独立时间戳备份...")
    backup_title = create_timestamped_backup(service, spreadsheet_id, project_props)
    print(f">>> 备份成功创建: '{backup_title}'（旧备份不受任何影响）")

    # 4. 容量检查与扩容
    current_total_rows = len(project_raw)
    needed_total_rows = current_total_rows + len(new_project_rows)
    ensure_sheet_capacity(service, spreadsheet_id, project_props, needed_total_rows, buffer_rows=500)

    # 5. 分批写入并逐批立即 exact read-back
    print(f"\n>>> 准备分批写入 {len(new_project_rows)} 行，每批 {batch_size} 行...")
    current_row_idx = current_total_rows  # 1-indexed next available row is current_row_idx + 1

    total_batches = (len(new_project_rows) + batch_size - 1) // batch_size

    for b_idx in range(total_batches):
        batch_slice = new_project_rows[b_idx * batch_size : (b_idx + 1) * batch_size]
        start_row = current_row_idx + 1
        end_row = current_row_idx + len(batch_slice)

        # 转换为 values 矩阵（严格按照 PROJECT_HEADER 顺序）
        batch_values = []
        for r in batch_slice:
            row_vals = [r.get(col, "") for col in PROJECT_HEADER]
            batch_values.append(row_vals)

        write_range = f"'{project_sheet_name}'!A{start_row}:J{end_row}"
        print(f"  [批次 {b_idx + 1}/{total_batches}] 正在写入 {write_range} (共 {len(batch_slice)} 行)...")

        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=write_range,
            valueInputOption="USER_ENTERED",
            body={"values": batch_values},
        ).execute()

        # 立即 exact read-back 验证
        read_res = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=write_range,
        ).execute()
        read_values = read_res.get("values", [])

        if len(read_values) != len(batch_slice):
            raise RuntimeError(
                f"批次 {b_idx + 1} 校验失败！写入 {len(batch_slice)} 行，回读仅有 {len(read_values)} 行！"
            )

        for i, (expected_row, actual_vals) in enumerate(zip(batch_slice, read_values)):
            # 校验关键列
            actual_dict = {
                PROJECT_HEADER[idx]: actual_vals[idx].strip() if idx < len(actual_vals) else ""
                for idx in range(len(PROJECT_HEADER))
            }
            for check_col in ["项目ID", "外链ID", "状态", "尝试次数", "目标URL"]:
                if expected_row.get(check_col, "") != actual_dict.get(check_col, ""):
                    raise RuntimeError(
                        f"批次 {b_idx + 1} 第 {i} 行字段 '{check_col}' 回读不一致！"
                        f"期望 '{expected_row.get(check_col)}' vs 实际 '{actual_dict.get(check_col)}'"
                    )

        print(f"  [批次 {b_idx + 1}/{total_batches}] 写入并 exact read-back 校验通过！")
        current_row_idx = end_row

    print(f"\n>>> 全部 {len(new_project_rows)} 行写入完成并全部通过回读校验！")

    # ==========================================
    # 6. 写后 Full Audit 与完整性审计
    # ==========================================
    print(f"\n==================================================")
    print(f"执行写后 Full Audit 与完整性审计")
    print(f"==================================================")
    full_project_raw = fetch_all_sheet_rows(service, spreadsheet_id, project_sheet_name)
    full_project_dicts = parse_rows_to_dicts(full_project_raw, PROJECT_HEADER)

    cur_project_all = [r for r in full_project_dicts if r.get("项目ID") == project_id]
    final_status_counter = Counter(r.get("状态") for r in cur_project_all)

    print(f"\n【写后项目状态审计】")
    print(f"  当前项目 ({project_id}) 最终总行数: {len(cur_project_all)}")
    for st, cnt in final_status_counter.items():
        print(f"  状态 {st}: {cnt}")

    # 查重审计
    bid_counts = Counter(canonical_domain(r.get("外链ID") or r.get("外链域名") or "") for r in cur_project_all)
    duplicates = [b for b, c in bid_counts.items() if c > 1 and b]
    print(f"  重复记录数 (duplicate project_id + 外链ID): {len(duplicates)}")
    if duplicates:
        raise RuntimeError(f"写后审计失败：发现 {len(duplicates)} 个重复外链ID: {duplicates[:5]}")

    # 历史记录保护校验
    for hist_row in existing_cur_project:
        h_bid = canonical_domain(hist_row.get("外链ID") or hist_row.get("外链域名") or "")
        # 在全量表中找到该记录
        matched = [r for r in cur_project_all if canonical_domain(r.get("外链ID") or r.get("外链域名") or "") == h_bid]
        if not matched:
            raise RuntimeError(f"历史记录丢失：{h_bid}")
        cur = matched[0]
        if cur.get("状态") != hist_row.get("状态") or cur.get("尝试次数") != hist_row.get("尝试次数"):
            raise RuntimeError(f"历史记录被篡改：{h_bid} (原状态 {hist_row.get('状态')} vs 现状态 {cur.get('状态')})")
    print(f"  历史 {len(existing_cur_project)} 条记录完整性与状态保护: 100% PASS！")

    # LEFT JOIN 完整性审计
    # 将 Master 所有 候选平台 与 当前项目记录做 LEFT JOIN
    project_bids_set = set(canonical_domain(r.get("外链ID") or r.get("外链域名") or "") for r in cur_project_all)
    unprojected_candidates = []

    p_ctx = resolve_project_context(project_id, {"ai_powered": ai_powered})

    for mrow in master_dicts:
        m_bid = canonical_domain(mrow.get("外链ID") or mrow.get("平台域名") or "")
        if not m_bid:
            continue
        if mrow.get("基础状态") != MASTER_STATUS_CANDIDATE:
            continue
        if m_bid not in project_bids_set:
            is_incomp, ev, reas = get_persisted_project_incompatibility(mrow, p_ctx)
            unprojected_candidates.append({
                "domain": m_bid,
                "is_incompatible": is_incomp,
                "evidence": ev,
                "reason": reas,
            })

    print(f"\n【LEFT JOIN 完整性审计】")
    print(f"  Master 候选但未进入项目的平台数: {len(unprojected_candidates)}")
    for item in unprojected_candidates:
        if item["is_incompatible"]:
            print(f"  - 合法跳过: {item['domain']} (原因: {item['reason']})")
        else:
            raise RuntimeError(
                f"完整性审计失败！候选 {item['domain']} 未进入项目 backlog，且没有已证实 hard incompatibility！"
            )

    print(f"\n==================================================")
    print(f"【投影与审计全部成功完成】")
    print(f"  BACKLOG SIZE = {len(cur_project_all)}")
    print(f"  EXECUTION BATCH SIZE = 10/20/50 (解耦准备)")
    print(f"==================================================")

    return {
        "stats": stats,
        "master_stats": master_status_counter,
        "final_status_counter": final_status_counter,
        "total_project_rows": len(cur_project_all),
        "backup_title": backup_title,
        "unprojected_candidates": unprojected_candidates,
        "commit": True,
    }


def main():
    parser = argparse.ArgumentParser(description="BacklinkOS Project Backlog Projection")
    parser.add_argument(
        "--spreadsheet-id",
        type=str,
        default="1uUmlPGzjxNe-XkvWfjuC3c5exiOxZuFJWvHqPTwjaTA",
        help="Google Spreadsheet ID",
    )
    parser.add_argument(
        "--project-id",
        type=str,
        default="quick-iching",
        help="Project identifier (e.g. quick-iching)",
    )
    parser.add_argument(
        "--target-url",
        type=str,
        default="https://quickiching.com/",
        help="Target project promotion URL",
    )
    parser.add_argument(
        "--ai-powered",
        action="store_true",
        default=False,
        help="Set flag if project is AI powered",
    )
    parser.add_argument(
        "--master-sheet",
        type=str,
        default="外链总表",
        help="Name of Master sheet",
    )
    parser.add_argument(
        "--project-sheet",
        type=str,
        default="外链管理",
        help="Name of Project sheet",
    )
    parser.add_argument(
        "--credentials-file",
        type=str,
        default="~/.config/seo-sheets/service-account.json",
        help="Path to Google Service Account JSON",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Batch size for writing to Sheet",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        default=False,
        help="Commit writes to Google Sheet (default is Dry Run)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Run projection in dry-run mode without mutating Sheet",
    )

    args = parser.parse_args()
    is_commit = args.commit and not args.dry_run

    run_projection(
        spreadsheet_id=args.spreadsheet_id,
        project_id=args.project_id,
        target_url=args.target_url,
        ai_powered=args.ai_powered,
        master_sheet_name=args.master_sheet,
        project_sheet_name=args.project_sheet,
        credentials_path=args.credentials_file,
        batch_size=args.batch_size,
        commit=is_commit,
    )


if __name__ == "__main__":
    main()
