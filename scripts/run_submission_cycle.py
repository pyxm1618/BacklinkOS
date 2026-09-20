#!/usr/bin/env python3
"""BacklinkOS Formal Submission Cycle Orchestrator & State Machine.

实现正式提交流程全自动闭环支撑：
1. 锁定启动时项目待提交候选快照作为有限上限范围，最多覆盖一轮，绝不无限扩扫；
2. 自动衔接 Phase C 有界现场核验 (prepare_execution_batch)；
3. 输出当前批次 Ready 清单供当前 AI 驱动真实浏览器执行提交 (backlink-autofill)；
4. 严格统计“新增成功提交”（排除历史已有提交与断点恢复尝试）；
5. 遭遇平台全局不可用时，触发跨项目全局排除同步落表并回读验证；
6. 遭遇真阻碍挂起为 HUMAN_PENDING，保留标签页，不阻塞后续候选；
7. 全流程持久化至 ~/.backlinkos/runtime/cycles/<project_id>/state.json，新会话无缝恢复；
8. 循环推进直至达到目标成功数或快照耗尽，退出时输出严格对账清单。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from master_sheet_sync import (
    DEFAULT_BACKLINKOS_RUNTIME_DIR,
    MASTER_HEADER,
    PROJECT_HEADER,
    PROJECT_STATUS_TO_SUBMIT,
    clear_phase_c_checkpoint,
    canonical_domain,
    classify_exclusion,
    ExclusionScope,
    execute_cross_project_sync_mutations,
    normalize_canonical_url,
    load_scan_ledger_facts,
    prepare_execution_batch,
    recover_pending_cross_project_sync,
    resolve_project_context,
    sync_global_exclusions_across_projects,
    validate_project_id,
    _get_production_gate,
)
from prepare_execution_batch import (
    col_index_to_letter,
    fetch_all_sheet_rows,
    get_sheets_service,
)
from screening_crawler import fetch_page


SUCCESS_STATUSES = {"已提交", "审核中", "已排期", "已上线"}


def read_all_master_rows(service, spreadsheet_id: str, sheet_name: str) -> list[dict[str, Any]]:
    m_raw = fetch_all_sheet_rows(service, spreadsheet_id, sheet_name)
    if not m_raw or len(m_raw) < 2:
        return []
    header = [col.strip() for col in m_raw[0]]
    m_rows = []
    for idx, r in enumerate(m_raw[1:], 2):
        row_dict: dict[str, Any] = {"_sheet_row_num": idx}
        for c_idx, col in enumerate(header):
            row_dict[col] = r[c_idx].strip() if c_idx < len(r) else ""
        for col in MASTER_HEADER:
            if col not in row_dict:
                row_dict[col] = ""
        m_rows.append(row_dict)
    return m_rows


def read_all_project_rows(service, spreadsheet_id: str, sheet_name: str) -> list[dict[str, Any]]:
    p_raw = fetch_all_sheet_rows(service, spreadsheet_id, sheet_name)
    if not p_raw or len(p_raw) < 2:
        return []
    header = [col.strip() for col in p_raw[0]]
    p_rows = []
    for idx, r in enumerate(p_raw[1:], 2):
        row_dict: dict[str, Any] = {"_sheet_row_num": idx}
        for c_idx, col in enumerate(header):
            row_dict[col] = r[c_idx].strip() if c_idx < len(r) else ""
        for col in PROJECT_HEADER:
            if col not in row_dict:
                row_dict[col] = ""
        p_rows.append(row_dict)
    return p_rows


def get_cycle_dir(project_id: str, runtime_dir: str | None = None) -> Path:
    validated_pid = validate_project_id(project_id)
    base_dir = Path(runtime_dir or os.environ.get("BACKLINKOS_RUNTIME_DIR", DEFAULT_BACKLINKOS_RUNTIME_DIR))
    p = base_dir / "cycles" / validated_pid
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_cycle_state_path(project_id: str, runtime_dir: str | None = None) -> Path:
    return get_cycle_dir(project_id, runtime_dir) / "state.json"


def load_cycle_state(project_id: str, runtime_dir: str | None = None) -> dict[str, Any] | None:
    path = get_cycle_state_path(project_id, runtime_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_cycle_state(project_id: str, state: dict[str, Any], runtime_dir: str | None = None) -> None:
    path = get_cycle_state_path(project_id, runtime_dir)
    state["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _mutation_unique_key(m: dict[str, Any]) -> str:
    dom = canonical_domain(m.get("domain") or "")
    m_type = str(m.get("mutation_type") or "")
    fields = m.get("fields") or {}
    return f"{dom}_{m_type}_{json.dumps(fields, sort_keys=True)}"


def save_pending_master_mutations(
    project_id: str | None,
    mutations: list[dict[str, Any]],
    runtime_dir: str | None = None,
) -> Path | None:
    """持久化保存未成功落表或回读校验失败的 Master 表变更至全局共享文件，供跨项目恢复补偿 (落实 F4 与 S4 修复)。"""
    base_dir = Path(runtime_dir or os.environ.get("BACKLINKOS_RUNTIME_DIR", DEFAULT_BACKLINKOS_RUNTIME_DIR))
    base_dir.mkdir(parents=True, exist_ok=True)
    global_file = base_dir / "pending_master_mutations.json"

    # 若为空，清理全局及所有 cycle 下的 pending 文件
    if not mutations:
        if global_file.exists():
            try:
                global_file.unlink()
            except Exception:
                pass
        cycles_dir = base_dir / "cycles"
        if cycles_dir.exists():
            for sub in cycles_dir.iterdir():
                if sub.is_dir():
                    cf = sub / "pending_master_mutations.json"
                    if cf.exists():
                        try:
                            cf.unlink()
                        except Exception:
                            pass
        return None

    valid_keys = {_mutation_unique_key(m) for m in mutations}

    tmp_file = global_file.with_suffix(f".tmp.{os.getpid()}")
    payload = {
        "mutations": mutations,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    tmp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_file, global_file)

    # 同步清理/更新所有 cycles 目录下的副本，彻底防止已恢复项复活 (落实 S4 修复)
    cycles_dir = base_dir / "cycles"
    if cycles_dir.exists():
        for sub in cycles_dir.iterdir():
            if sub.is_dir():
                cf = sub / "pending_master_mutations.json"
                if cf.exists():
                    try:
                        c_data = json.loads(cf.read_text(encoding="utf-8"))
                        c_muts = c_data.get("mutations", []) if isinstance(c_data, dict) else []
                        kept_muts = [it for it in c_muts if _mutation_unique_key(it) in valid_keys]
                        if not kept_muts:
                            cf.unlink(missing_ok=True)
                        else:
                            c_payload = {
                                "mutations": kept_muts,
                                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            }
                            cf.write_text(json.dumps(c_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception:
                        pass

    # 兼容写入当前 project cycle_dir
    if project_id:
        cycle_dir = get_cycle_dir(project_id, runtime_dir)
        cycle_file = cycle_dir / "pending_master_mutations.json"
        try:
            cycle_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    print(f"[提示] 已持久化 {len(mutations)} 条全局待恢复 Master 变更至: {global_file}", file=sys.stderr)
    return global_file


def load_pending_master_mutations(
    project_id: str | None = None,
    runtime_dir: str | None = None,
) -> list[dict[str, Any]]:
    """读取待恢复的 Master 表变更记录。

    跨项目共享恢复契约：
    1. 优先读取全局 runtime 目录下的 pending_master_mutations.json；
    2. 自动扫描 cycles/*/pending_master_mutations.json 收集各项目可能遗留的变更；
    3. 按 (domain, 字段哈希) 合并去重，确保项目 B 启动时能完整感知并恢复项目 A 的遗留变更。
    """
    base_dir = Path(runtime_dir or os.environ.get("BACKLINKOS_RUNTIME_DIR", DEFAULT_BACKLINKOS_RUNTIME_DIR))
    mutations_by_key: dict[str, dict[str, Any]] = {}

    # 1. 扫描全局待恢复文件
    global_file = base_dir / "pending_master_mutations.json"
    files_to_read = [global_file] if global_file.exists() else []

    # 2. 扫描所有 cycles 目录
    cycles_dir = base_dir / "cycles"
    if cycles_dir.exists():
        for sub in cycles_dir.iterdir():
            if sub.is_dir():
                f = sub / "pending_master_mutations.json"
                if f.exists() and f not in files_to_read:
                    files_to_read.append(f)

    for f in files_to_read:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            items = data.get("mutations", []) if isinstance(data, dict) else []
            for it in items:
                dom = canonical_domain(it.get("domain") or "")
                if not dom:
                    continue
                key = f"{dom}_{it.get('mutation_type')}_{json.dumps(it.get('fields') or {}, sort_keys=True)}"
                if key not in mutations_by_key:
                    mutations_by_key[key] = it
        except Exception:
            pass

    return list(mutations_by_key.values())


def are_equivalent_timestamps(t1: str | None, t2: str | None) -> bool:
    """比对两个时间戳是否严格等价 (支持 ISO 字符串与 2 秒内的等价时间对比)。"""
    s1 = str(t1 or "").strip()
    s2 = str(t2 or "").strip()
    if not s1 and not s2:
        return True
    if not s1 or not s2:
        return False
    if s1 == s2:
        return True
    try:
        dt1 = datetime.datetime.fromisoformat(s1.replace("Z", "+00:00"))
        dt2 = datetime.datetime.fromisoformat(s2.replace("Z", "+00:00"))
        return abs((dt1 - dt2).total_seconds()) < 2.0
    except Exception:
        return s1 == s2


def validate_platform_facts(
    facts: dict[str, Any] | None,
    evidence: Any = None,
    outcome_status: str = "",
    backlink_id: str = "",
) -> dict[str, Any]:
    """严格校验平台事实与证据支撑，绝不凭空臆造事实 (落实 S2 规范)。

    规则约束：
    1. 只能记录有真实证据支撑的字段；证据不足时严格抛出 ValueError 拒绝；
    2. 不能由“提交成功”推断永久免费、无需登录、已经上线或其他未知属性；
    3. 否定入口必须有证据指向具体错误 URL，单个入口错误不能升级为整站失效；
    4. AI-only、付费-only 等限制仅记录平台事实，基础状态保持候选；
    5. 未知属性严格保持为空或未知，不编造补齐。
    """
    if not facts or not isinstance(facts, dict):
        return {}

    valid_facts: dict[str, Any] = {}

    # 提取 evidence 上下文字符串与字典，用于真实证据比对
    ev_dict: dict[str, Any] = {}
    if isinstance(evidence, dict):
        ev_dict = dict(evidence)
        ev_text = json.dumps(evidence, ensure_ascii=False).lower()
    elif isinstance(evidence, str):
        ev_text = evidence.lower()
        if evidence.strip().startswith("{") and evidence.strip().endswith("}"):
            try:
                ev_dict = json.loads(evidence.strip())
            except Exception:
                pass
    else:
        ev_text = str(evidence or "").lower()

    # 1. 提交入口 entry_url
    if "entry_url" in facts and facts["entry_url"]:
        raw_url = str(facts["entry_url"]).strip()
        if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
            raise ValueError(f"平台事实 entry_url 必须为以 http/https 开头的有效 URL: {raw_url!r}")
        # 结果展示页/带有具体单品或项目专属 slug 的 URL 不能作为通用提交入口 (落实 S1 修复，不依赖特定项目黑名单)
        from urllib.parse import urlparse
        parsed = urlparse(raw_url)
        path_lower = parsed.path.rstrip("/").lower()
        if any(p in path_lower for p in ["/product/", "/products/", "/listings/", "/item/", "/goods/"]):
            raise ValueError(f"平台事实 entry_url 不能包含具体产品或单品路径: {raw_url!r}")
        sub_match = re.match(r"^/(submit|add|post|new)/([^/]+)$", path_lower)
        if sub_match:
            tail = sub_match.group(2)
            common_generic_slugs = {
                "site", "tool", "tools", "startup", "startups", "app", "apps",
                "deal", "deals", "listing", "listings", "link", "software", "url", "website"
            }
            if tail not in common_generic_slugs:
                raise ValueError(f"平台事实 entry_url 必须为通用提交表单观察，不能包含具体项目专属路径或 slug: {raw_url!r}")
        valid_facts["entry_url"] = raw_url

    # 2. 否定入口 negated_entries / negated_entry
    raw_negs = facts.get("negated_entries") or facts.get("negated_entry")
    if raw_negs:
        neg_list = [raw_negs] if isinstance(raw_negs, str) else list(raw_negs)
        clean_negs = []
        for n in neg_list:
            n_str = str(n).strip()
            if not n_str:
                continue
            if not (n_str.startswith("http://") or n_str.startswith("https://")):
                raise ValueError(f"否定入口 URL 必须为合法 http/https 链接: {n_str!r}")
            clean_negs.append(n_str)
        if clean_negs:
            valid_facts["negated_entries"] = clean_negs

    # 3. 实测免费 free
    if "free" in facts and facts["free"]:
        free_val = str(facts["free"]).strip()
        # 2026-09-20 Master 规范统一使用“混合”；兼容旧调用的“部分免费”输入。
        if free_val == "部分免费":
            free_val = "混合"
        if free_val not in ("免费", "非免费", "混合"):
            raise ValueError(f"实测免费字段仅允许'免费'、'非免费'、'混合'，当前为: {free_val!r}")

        # 结构化字段检查与明确矛盾拦截 (落实 S2 修复)
        ev_free = str(ev_dict.get("free") or ev_dict.get("pricing") or ev_dict.get("实测免费") or "").strip()
        paid_keywords = ["非免费", "付费", "纯付费", "必须付费", "强制付费", "无免费通道", "无免费提交", "收费", "paid", "payment", "pricing"]
        free_keywords = ["免费", "free", "0元", "0$", "免收录费", "免费审核", "免费排队", "无需付费"]

        if free_val == "免费":
            # 矛盾拦截：若证据中观察到付费/非免费
            if ev_free in ("非免费", "付费", "paid", "paid_only") or any(kw in ev_free for kw in ["非免费", "付费", "纯付费"]):
                raise ValueError(f"声明平台事实 free='免费' 与证据中观察到的非免费/付费相矛盾 (证据: {ev_free!r})")
            if any(kw in ev_text for kw in ["非免费", "纯付费", "必须付费", "强制付费", "无免费通道", "无免费提交"]):
                raise ValueError(f"声明平台事实 free='免费' 与证据文本中的非免费/纯付费描述相矛盾")
            # 存在性检查：必须有免费证据
            has_free = (ev_free in ("免费", "free", "0") or any(kw in ev_text for kw in free_keywords))
            if not has_free:
                raise ValueError(f"声明平台事实 free='免费' 缺乏具体免费相关证据支持")

        elif free_val in ("非免费", "混合"):
            # 矛盾拦截：若证据明确为完全免费且无收费
            if ev_free in ("免费", "free") and not any(kw in ev_text for kw in paid_keywords):
                raise ValueError(f"声明平台事实 free={free_val!r} 与证据中观察到的免费相矛盾 (证据: {ev_free!r})")
            # 存在性检查：必须有付费证据
            has_paid = (ev_free in ("非免费", "付费", "paid", "pricing") or any(kw in ev_text for kw in paid_keywords))
            if not has_paid:
                raise ValueError(f"声明平台事实 free={free_val!r} 缺乏具体收费/价格相关证据支持")

        valid_facts["free"] = free_val

    # 4. 实测需登录 requires_login
    if "requires_login" in facts and facts["requires_login"]:
        login_val = str(facts["requires_login"]).strip()
        # Master 展示统一为“需要/不需要”；兼容旧调用的“是/否”输入。
        if login_val == "是":
            login_val = "需要"
        elif login_val == "否":
            login_val = "不需要"
        if login_val not in ("需要", "不需要"):
            raise ValueError(f"实测需登录字段仅允许'需要'、'不需要'，当前为: {login_val!r}")

        ev_login = ev_dict.get("requires_login") or ev_dict.get("auth_required") or ev_dict.get("实测需登录")
        login_keywords = ["登录", "sign-in", "signin", "sign in", "oauth", "需登录", "要求登录", "认证", "拦截", "注册账号"]
        no_login_keywords = ["免登录", "无需登录", "直接提交", "不需注册", "未要求登录", "not required", "guest"]

        if login_val == "不需要":
            # 矛盾拦截：证据中要求登录
            if ev_login in ("是", True, "yes", "true") or any(kw in str(ev_login).lower() for kw in ["需登录", "是"]):
                raise ValueError(f"声明平台事实 requires_login='不需要' 与证据中观察到的需登录相矛盾 (证据: {ev_login!r})")
            if any(kw in ev_text for kw in ["强制跳转登录", "强制登录", "需登录账号", "需认证", "oauth拦截"]):
                raise ValueError(f"声明平台事实 requires_login='否' 与证据文本中的需登录描述相矛盾")
            has_no_login = (ev_login in ("否", False, "no", "false") or any(kw in ev_text for kw in no_login_keywords))
            if not has_no_login:
                raise ValueError(f"声明平台事实 requires_login='否' 缺乏免登录相关证据支持")

        elif login_val == "需要":
            # 矛盾拦截：证据明确为免登录
            if ev_login in ("否", False, "no", "false") and not any(kw in ev_text for kw in login_keywords):
                raise ValueError(f"声明平台事实 requires_login='需要' 与证据中观察到的免登录相矛盾 (证据: {ev_login!r})")
            has_login = (ev_login in ("是", True, "yes", "true") or any(kw in ev_text for kw in login_keywords))
            if not has_login:
                raise ValueError(f"声明平台事实 requires_login='是' 缺乏具体登录/认证拦截相关证据支持")

        valid_facts["requires_login"] = login_val

    # 5. 实测登录方式 login_method
    if "login_method" in facts and facts["login_method"]:
        valid_facts["login_method"] = str(facts["login_method"]).strip()

    # 6. 实测限制 limits
    if "limits" in facts and facts["limits"]:
        limits_val = str(facts["limits"]).strip()
        # 对应观察证据检查 (落实 S2 修复)
        limits_parts = [p.strip().lower() for p in limits_val.replace("；", ";").split(";") if p.strip()]
        # 结构化观察存在时只比较观察值；不能用任意限制关键词支持另一条限制。
        observed_limits = [str(ev_dict[key]).strip().lower()
                           for key in ("limits", "restriction", "eligibility", "实测限制")
                           if key in ev_dict]
        if observed_limits:
            observed_parts = {part.strip() for value in observed_limits
                              for part in value.replace("；", ";").split(";") if part.strip()}
            has_limits_ev = bool(limits_parts) and all(part in observed_parts for part in limits_parts)
        else:
            has_limits_ev = bool(limits_parts) and all(part in ev_text for part in limits_parts)
        if not has_limits_ev:
            raise ValueError(f"声明平台实测限制 limits={limits_val!r} 缺乏对应收录限制观察证据（必须逐项匹配）")
        valid_facts["limits"] = limits_val

    # 7. 实测链接属性 link_rel
    if "link_rel" in facts and facts["link_rel"]:
        link_rel_val = str(facts["link_rel"]).strip()
        listing_live = ev_dict.get("listing_live") is True or status == "已上线"
        dom_rel = ev_dict.get("live_dom_rel") or ev_dict.get("dom_rel") or ev_dict.get("实测链接属性")
        if not listing_live or dom_rel is None:
            raise ValueError(f"声明平台实测链接属性 link_rel={link_rel_val!r} 缺少已上线且实际检查 DOM rel 属性的证据支持")
        if str(dom_rel).strip().lower() != link_rel_val.lower():
            raise ValueError(f"声明平台实测链接属性 link_rel={link_rel_val!r} 与 DOM 实测观察值 {dom_rel!r} 不一致")
        valid_facts["link_rel"] = link_rel_val

    # 8. 观察时间 observed_at
    if "observed_at" in facts and facts["observed_at"]:
        valid_facts["observed_at"] = str(facts["observed_at"]).strip()

    # 9. 平台备注 notes
    if "notes" in facts and facts["notes"] is not None:
        valid_facts["notes"] = str(facts["notes"]).strip()

    # 10. 基础状态 master_status 与 排除原因
    if "master_status" in facts and facts["master_status"]:
        m_st = str(facts["master_status"]).strip()
        if m_st not in ("候选", "已排除", "失效"):
            raise ValueError(f"总表基础状态仅允许'候选'、'已排除'、'失效'，当前为: {m_st!r}")
        if m_st in ("失效", "已排除"):
            # 拦截：若证据表明主页正常或尚未确认关闭收录，拒绝设为失效/已排除
            if ev_dict.get("home_status") == 200 or any(kw in ev_text for kw in ["主页正常", "首页正常", "homepage 200"]):
                raise ValueError(f"主页正常 (HTTP 200)，尚未确认整站失效，严禁将总表基础状态设为 {m_st!r}，必须保持候选")
            if any(kw in ev_text for kw in ["尚未确认", "未确认", "暂未确认"]):
                raise ValueError(f"平台状态尚未确认关闭收录，严禁将总表基础状态设为 {m_st!r}，必须保持候选")
            has_global_ev = (
                ev_dict.get("site_dead") is True
                or ev_dict.get("submission_closed") is True
                or any(kw in ev_text for kw in [
                    "nxdomain", "域名过期", "域名出售", "域名停放", "永久死站", "站点已下线",
                    "关闭收录", "不再收录", "停止运营", "关闭注册", "平台关停"
                ])
            )
            if not has_global_ev:
                raise ValueError(f"声明总表基础状态为 {m_st!r} 缺乏死站或停止运营的全局证据")
        valid_facts["master_status"] = m_st
    if "master_exclusion_reason" in facts and facts["master_exclusion_reason"]:
        valid_facts["master_exclusion_reason"] = str(facts["master_exclusion_reason"]).strip()

    return valid_facts


def recover_pending_master_mutations(
    sheets_service: Any,
    spreadsheet_id: str,
    master_sheet_name: str,
    project_id: str,
    runtime_dir: str | None = None,
) -> list[dict[str, Any]]:
    """尝试自动恢复并写回先前落表失败的 Master 表变更 (落实 F4 规范与跨项目自动恢复)。

    包含写前身份核验、行号重定位与写后全字段严格回读比对。
    支持通用字典字段 fields 批量写入与回读，以及历史 legacy mutation 类型。
    """
    muts = load_pending_master_mutations(project_id, runtime_dir)
    if not muts or not sheets_service:
        return []
    remaining: list[dict[str, Any]] = []
    for m in muts:
        domain = canonical_domain(m.get("domain") or "")
        row_num = m.get("row_num")
        mutation_type = m.get("mutation_type")
        fields = m.get("fields")
        exp_val = m.get("expected_val") or m.get("expected_limits")
        exp_vtime = m.get("expected_vtime")

        if not domain:
            continue
        if not fields and not exp_val:
            continue

        # 1. 写前行身份核验与行号重新定位
        target_row = None
        try:
            if row_num:
                pre_rb = sheets_service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id,
                    range=f"'{master_sheet_name}'!A{row_num}:B{row_num}",
                ).execute()
                cur_row = pre_rb.get("values", [[]])[0]
                cur_bid = canonical_domain(cur_row[0]) if len(cur_row) > 0 and cur_row[0] else ""
                if cur_bid == domain:
                    target_row = row_num

            # 若当前行号已不匹配（行移位），整列查找该 domain
            if not target_row:
                col_rb = sheets_service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id,
                    range=f"'{master_sheet_name}'!A1:A20000",
                ).execute()
                col_vals = col_rb.get("values", [])
                for idx, r_val in enumerate(col_vals, 1):
                    if r_val and len(r_val) > 0 and canonical_domain(r_val[0]) == domain:
                        target_row = idx
                        m["row_num"] = idx
                        break
        except Exception as pre_exc:
            m["last_retry_error"] = f"写前身份核验失败: {pre_exc}"
            remaining.append(m)
            continue

        if not target_row:
            m["last_retry_error"] = f"Master 表未找到域名 [{domain}] 的匹配行，拒绝盲写，保持待恢复"
            remaining.append(m)
            continue

        # 2. 执行安全写入
        write_success = False
        try:
            if fields and isinstance(fields, dict):
                batch_data = []
                for f_name, f_val in fields.items():
                    if f_name in MASTER_HEADER:
                        col_letter = col_index_to_letter(MASTER_HEADER.index(f_name))
                        batch_data.append({
                            "range": f"'{master_sheet_name}'!{col_letter}{target_row}",
                            "values": [[str(f_val if f_val is not None else "")]]
                        })
                if batch_data:
                    sheets_service.spreadsheets().values().batchUpdate(
                        spreadsheetId=spreadsheet_id,
                        body={"valueInputOption": "USER_ENTERED", "data": batch_data},
                    ).execute()
                    write_success = True
            elif mutation_type == "submission_entry":
                entry_letter = col_index_to_letter(MASTER_HEADER.index("提交入口"))
                sheets_service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=f"'{master_sheet_name}'!{entry_letter}{target_row}",
                    valueInputOption="USER_ENTERED",
                    body={"values": [[exp_val]]},
                ).execute()
                write_success = True
            elif mutation_type == "limits_and_vtime":
                limits_letter = col_index_to_letter(MASTER_HEADER.index("实测限制"))
                vtime_letter = col_index_to_letter(MASTER_HEADER.index("最后验证时间")) if "最后验证时间" in MASTER_HEADER else ""
                batch_data = [{"range": f"'{master_sheet_name}'!{limits_letter}{target_row}", "values": [[exp_val]]}]
                if vtime_letter and exp_vtime:
                    batch_data.append({"range": f"'{master_sheet_name}'!{vtime_letter}{target_row}", "values": [[exp_vtime]]})
                sheets_service.spreadsheets().values().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={"valueInputOption": "USER_ENTERED", "data": batch_data},
                ).execute()
                write_success = True
        except Exception as w_exc:
            m["last_retry_error"] = f"写回失败: {w_exc}"
            remaining.append(m)
            continue

        # 3. 写后全字段严格回读核验
        if write_success:
            try:
                max_col_letter = "M"
                if fields and isinstance(fields, dict):
                    for f in fields:
                        if f in MASTER_HEADER:
                            letter = col_index_to_letter(MASTER_HEADER.index(f))
                            if letter > max_col_letter:
                                max_col_letter = letter
                rb_post = sheets_service.spreadsheets().values().get(
                    spreadsheetId=spreadsheet_id,
                    range=f"'{master_sheet_name}'!A{target_row}:{max_col_letter}{target_row}",
                ).execute()
                vals = rb_post.get("values", [[]])[0]
                act_bid = canonical_domain(vals[MASTER_HEADER.index("外链ID")]) if len(vals) > MASTER_HEADER.index("外链ID") else ""

                if act_bid != domain:
                    m["last_retry_error"] = f"写后回读身份不匹配: 期望 {domain}, 实读 {act_bid}"
                    remaining.append(m)
                    continue

                if fields and isinstance(fields, dict):
                    mismatch = False
                    for f_name, f_val in fields.items():
                        if f_name not in MASTER_HEADER:
                            continue
                        f_idx = MASTER_HEADER.index(f_name)
                        act_f = vals[f_idx].strip() if len(vals) > f_idx else ""
                        exp_f = str(f_val if f_val is not None else "").strip()
                        if f_name == "最后验证时间" and exp_f:
                            if not are_equivalent_timestamps(act_f, exp_f):
                                mismatch = True
                                m["last_retry_error"] = f"回读时间不一致: 期望 {exp_f}, 实读 {act_f}"
                                break
                        elif act_f != exp_f:
                            mismatch = True
                            m["last_retry_error"] = f"回读字段 {f_name} 不一致: 期望 {exp_f!r}, 实读 {act_f!r}"
                            break
                    if mismatch:
                        remaining.append(m)
                    else:
                        # 成功恢复，不加入 remaining
                        continue
                elif mutation_type == "submission_entry":
                    act_entry = vals[MASTER_HEADER.index("提交入口")].strip() if len(vals) > MASTER_HEADER.index("提交入口") else ""
                    if act_entry == exp_val:
                        continue
                    else:
                        m["last_retry_error"] = f"写后回读不一致: 期望 ({domain}, {exp_val}), 实读 ({act_bid}, {act_entry})"
                        remaining.append(m)
                elif mutation_type == "limits_and_vtime":
                    limits_idx = MASTER_HEADER.index("实测限制")
                    vtime_idx = MASTER_HEADER.index("最后验证时间") if "最后验证时间" in MASTER_HEADER else -1
                    act_limits = vals[limits_idx].strip() if len(vals) > limits_idx else ""
                    act_vtime = vals[vtime_idx].strip() if vtime_idx >= 0 and len(vals) > vtime_idx else ""
                    time_match = are_equivalent_timestamps(act_vtime, exp_vtime) if exp_vtime else True
                    if act_limits == exp_val and time_match:
                        continue
                    else:
                        m["last_retry_error"] = f"写后回读不一致: 期望 ({domain}, {exp_val}, {exp_vtime}), 实读 ({act_bid}, {act_limits}, {act_vtime})"
                        remaining.append(m)
            except Exception as post_exc:
                m["last_retry_error"] = f"写后核验异常: {post_exc}"
                remaining.append(m)

    save_pending_master_mutations(project_id, remaining, runtime_dir)
    return remaining



def archive_finished_cycle(project_id: str, runtime_dir: str | None = None) -> Path | None:
    """将已结束的 cycle 归档，保留历史记录并允许新目标启动 (落实 R8 修复)。"""
    state = load_cycle_state(project_id, runtime_dir)
    if not state or not state.get("is_finished"):
        return None
    cycle_dir = get_cycle_dir(project_id, runtime_dir)
    archive_dir = cycle_dir / "archived"
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = archive_dir / f"cycle_{ts}.json"
    state_path = get_cycle_state_path(project_id, runtime_dir)
    shutil.copy2(state_path, archive_path)
    try:
        state_path.unlink()
    except Exception:
        pass
    return archive_path


def _get_human_pending_tools():
    """获取 backlink-autofill 的 human pending 持久化与清除工具。"""
    try:
        from execution_state import save_human_pending, resolve_human_pending, load_human_pending
        return save_human_pending, resolve_human_pending, load_human_pending
    except ImportError:
        pass
    import sys
    cand_paths = [
        Path.home() / "plugins" / "backlink-autofill" / "scripts",
        Path.home() / "Projects" / "backlink-autofill" / "plugins" / "backlink-autofill" / "scripts",
        Path.home() / ".codex" / "plugins" / "cache" / "personal" / "backlink-autofill" / "0.2.1" / "scripts",
    ]
    for p in cand_paths:
        if p.exists() and str(p) not in sys.path:
            sys.path.insert(0, str(p))
    try:
        from execution_state import save_human_pending, resolve_human_pending, load_human_pending
        return save_human_pending, resolve_human_pending, load_human_pending
    except Exception:
        return None, None, None


def is_matching_tab_scene(actual_url: str, expected_url: str) -> bool:
    """核对标签页现场 URL 是否与预期阻碍现场匹配 (支持同主域子路径与合法第三方 OAuth/质询跳转)。"""
    if not expected_url or not expected_url.strip():
        return True
    if not actual_url or not actual_url.strip():
        return False
    from urllib.parse import urlparse
    try:
        act_p = urlparse(actual_url.strip())
        exp_p = urlparse(expected_url.strip())
    except Exception:
        return actual_url.strip() == expected_url.strip()

    act_host = act_p.netloc.split(":")[0].lower()
    exp_host = exp_p.netloc.split(":")[0].lower()

    if not act_host or not exp_host:
        return actual_url.strip().startswith(expected_url.strip())

    # 1. 主机名匹配或属于同一二级主域
    if (
        act_host == exp_host
        or canonical_domain(act_host) == canonical_domain(exp_host)
        or act_host.endswith("." + exp_host)
        or exp_host.endswith("." + act_host)
    ):
        return True

    # 2. 合法第三方 OAuth 登录墙或挑战盾跳转 (如 x.ai, Google, GitHub, Cloudflare 等)
    auth_keywords = ("x.ai", "twitter.com", "google.com", "github.com", "apple.com", "auth0.com", "cloudflare")
    if any(kw in act_host for kw in auth_keywords):
        act_lower = actual_url.lower()
        if (
            exp_host in act_lower
            or canonical_domain(exp_host) in act_lower
            or any(kw in exp_host for kw in auth_keywords)
            or any(p in act_p.path.lower() for p in ("login", "auth", "challenge", "signin", "oauth"))
        ):
            return True

    return False


def verify_cdp_live_target(
    target_id: str | None,
    expected_url: str | None = None,
    cdp_port: int = 9222,
    timeout_sec: float = 1.5,
) -> tuple[bool, str | None]:
    """Query the configured local CDP host for a retained target (F2 contract)."""
    if not target_id or str(target_id).strip().lower() in ("", "none", "null"):
        return False, "no_target_id_provided"
    import urllib.request
    t_clean = str(target_id).strip()
    configured_cdp = str(os.environ.get("BACKLINK_BROWSER_CDP_URL") or "").strip()
    if configured_cdp:
        parsed = urlparse(configured_cdp)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or not parsed.port
        ):
            return False, "invalid_local_cdp_url"
        endpoint = f"{parsed.scheme}://{parsed.netloc}/json/list"
    else:
        endpoint = f"http://127.0.0.1:{cdp_port}/json/list"
    try:
        req = urllib.request.Request(endpoint, headers={"User-Agent": "BacklinkOS-CDP-Probe/1.0"})
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status != 200:
                return False, f"cdp_http_{resp.status}"
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return False, f"cdp_unreachable: {exc}"

    if not isinstance(data, list):
        return False, "invalid_cdp_response"

    for target in data:
        t_id = str(target.get("id") or "").strip()
        t_type = str(target.get("type") or "").strip().lower()
        if t_id == t_clean:
            if t_type and t_type != "page":
                return False, f"target_type_is_{t_type}"
            act_url = str(target.get("url") or "").strip()
            if expected_url and not is_matching_tab_scene(act_url, expected_url):
                return False, f"url_mismatch: actual={act_url!r} expected={expected_url!r}"
            return True, None

    return False, "target_not_found_in_live_tabs"


def record_cycle_interruption(
    project_id: str,
    reason: str,
    runtime_dir: str | None = None,
) -> dict[str, Any]:
    """持久化记录当前循环的中断/暂停原因 (落实 F6 规范)。"""
    state = load_cycle_state(project_id, runtime_dir)
    if not state:
        raise ValueError(f"未找到项目 {project_id!r} 的活跃 cycle 状态")
    clean_reason = str(reason or "").strip() or "未知中断"
    state["interruption_reason"] = clean_reason
    save_cycle_state(project_id, state, runtime_dir)
    return {"ok": True, "project_id": project_id, "interruption_reason": clean_reason}


def init_cycle_state(
    project_id: str,
    target_success: int,
    initial_candidates: list[str],
    spreadsheet_id: str,
    master_sheet: str,
    project_sheet: str,
    inherited_human_pending: dict[str, Any] | None = None,
    runtime_dir: str | None = None,
) -> dict[str, Any]:
    hp_items = dict(inherited_human_pending or {})

    # 统一责任快照：合并本轮继承的未决人工项与待提交候选，实现严格闭环对账 (落实 R9 修复)
    combined_snapshot: list[str] = []
    seen = set()
    for b in hp_items.keys():
        cb = canonical_domain(b)
        if cb and cb not in seen:
            seen.add(cb)
            combined_snapshot.append(cb)
    for b in initial_candidates:
        cb = canonical_domain(b)
        if cb and cb not in seen:
            seen.add(cb)
            combined_snapshot.append(cb)

    # 初始仍待提交数 = 在初始候选中且尚未挂起为人工的项数
    initial_clean_cands = [canonical_domain(b) for b in initial_candidates if canonical_domain(b) not in hp_items]
    still_to_submit = len(initial_clean_cands)

    state = {
        "schema_version": 2,
        "project_id": project_id,
        "target_success": target_success,
        "spreadsheet_id": spreadsheet_id,
        "master_sheet": master_sheet,
        "project_sheet": project_sheet,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        # 统一责任快照作为本轮最大范围，最多覆盖一轮
        "snapshot_candidate_bids": combined_snapshot,
        "snapshot_total_count": len(combined_snapshot),
        # 持久化扫描与交付分层状态：扫描过不等于 Ready 已发布。
        # processed_candidate_bids 保留为旧状态兼容别名，新的调度逻辑优先使用
        # scanned_candidate_bids，并用 pending_ready_delivery_bids 重新交付未闭环项。
        "processed_candidate_bids": [],
        "scanned_candidate_bids": [],
        "delivered_ready_candidate_bids": [],
        "pending_ready_delivery_bids": [],
        # 运行统计（严格对账，修复 R9）
        "newly_succeeded_count": 0,
        "prior_existing_count": 0,
        "failed_count": 0,
        "not_applicable_count": 0,
        "human_pending_count": len(hp_items),
        "still_to_submit_count": still_to_submit,
        # 明细字典
        "completed_items": {},  # bid -> {status, reason, evidence, result_url, timestamp, is_new_success, is_existing_prior}
        "human_pending_items": hp_items,  # bid -> {domain, status, reason, evidence, target_id, timestamp}
        "unresolved_review_rounds": [],  # 固定 ID 清单、派发与观察结果；不清空历史账本重试
        "active_unresolved_review_round_id": None,
        "cross_project_sync_history": [],
        # 当前活动批次
        "active_batch": None,  # {batch_id, ready_domains, ready_items, in_flight}
        "is_finished": False,
        "finish_reason": None,
        "interruption_reason": None,
    }
    save_cycle_state(project_id, state, runtime_dir)
    return state


def _review_round_for_state(state: dict[str, Any]) -> dict[str, Any] | None:
    round_id = state.get("active_unresolved_review_round_id")
    if not round_id:
        return None
    for review_round in state.get("unresolved_review_rounds", []):
        if review_round.get("round_id") == round_id:
            return review_round
    return None


def _select_unresolved_review_candidates(
    state: dict[str, Any],
    master_rows: list[dict[str, Any]],
    project_rows: list[dict[str, Any]],
    runtime_dir: str | None,
    limit: int,
) -> list[str]:
    """从当前 Sheet 与历史扫描状态交集建立一次固定、有限的复核清单。"""
    project_id = state["project_id"]
    snapshot_order = {
        canonical_domain(backlink_id): index
        for index, backlink_id in enumerate(state.get("snapshot_candidate_bids", []))
        if canonical_domain(backlink_id)
    }
    snapshot_ids = set(snapshot_order)
    historical_ids = {
        canonical_domain(backlink_id)
        for backlink_id in [
            *state.get("scanned_candidate_bids", []),
            *state.get("processed_candidate_bids", []),
        ]
        if canonical_domain(backlink_id)
    }
    completed_ids = {canonical_domain(item) for item in state.get("completed_items", {}) if canonical_domain(item)}
    human_ids = {canonical_domain(item) for item in state.get("human_pending_items", {}) if canonical_domain(item)}
    delivered_ids = {
        canonical_domain(item)
        for item in state.get("delivered_ready_candidate_bids", [])
        if canonical_domain(item)
    }
    pending_ready_ids = {
        canonical_domain(item)
        for item in state.get("pending_ready_delivery_bids", [])
        if canonical_domain(item)
    }
    active_attempt_id = canonical_domain((state.get("active_attempt") or {}).get("backlink_id") or "")
    active_batch_ids = {
        canonical_domain(item.get("domain") or "")
        for item in (state.get("active_batch") or {}).get("ready_items", [])
        if isinstance(item, dict) and canonical_domain(item.get("domain") or "")
    }

    project_by_id: dict[str, dict[str, Any]] = {}
    for row in project_rows:
        if str(row.get("项目ID") or "").strip() != project_id:
            continue
        if str(row.get("状态") or "").strip() != PROJECT_STATUS_TO_SUBMIT:
            continue
        backlink_id = canonical_domain(row.get("外链ID") or row.get("外链域名") or "")
        if backlink_id and backlink_id not in project_by_id:
            project_by_id[backlink_id] = row

    master_by_id: dict[str, dict[str, Any]] = {}
    for row in master_rows:
        backlink_id = canonical_domain(row.get("外链ID") or row.get("平台域名") or "")
        if backlink_id:
            master_by_id[backlink_id] = row

    ledger_facts = load_scan_ledger_facts(project_id, runtime_dir=runtime_dir, cooldown_seconds=7 * 86400)
    candidates: list[str] = []
    for backlink_id in historical_ids & snapshot_ids:
        if backlink_id not in project_by_id or backlink_id in completed_ids or backlink_id in human_ids:
            continue
        if backlink_id in delivered_ids or backlink_id in pending_ready_ids:
            continue
        if backlink_id == active_attempt_id or backlink_id in active_batch_ids:
            continue
        master_row = master_by_id.get(backlink_id)
        if not master_row or str(master_row.get("基础状态") or "").strip() != "候选":
            continue
        candidates.append(backlink_id)

    def review_priority(backlink_id: str) -> tuple[int, int]:
        master_row = master_by_id.get(backlink_id) or {}
        fact = ledger_facts.get(backlink_id) or {}
        current_entry = str(master_row.get("提交入口") or "").strip()
        observed_entry = str(fact.get("verified_entry_url") or "").strip()
        if current_entry and observed_entry and normalize_canonical_url(current_entry) != normalize_canonical_url(observed_entry):
            rank = 0  # 入口事实变化，优先受控复核
        elif str(fact.get("disposition") or "").lower() in {
            "probe_timeout", "local_resource_blocked", "probe_rate_limited", "probe_worker_error", "probe_unknown",
        }:
            rank = 1  # 未知/资源性结果不进入七天否定缓存
        else:
            rank = 2
        return rank, snapshot_order.get(backlink_id, len(snapshot_order))

    candidates.sort(key=review_priority)
    return candidates[: max(0, int(limit))]


def _get_or_create_unresolved_review_round(
    state: dict[str, Any],
    master_rows: list[dict[str, Any]],
    project_rows: list[dict[str, Any]],
    runtime_dir: str | None,
    limit: int,
    time_budget: float | None,
) -> dict[str, Any] | None:
    """恢复唯一的有界复核轮；一个 cycle 不会因重复调用生成无限新轮次。"""
    review_round = _review_round_for_state(state)
    if review_round:
        dispatches = review_round.setdefault("dispatches", {})
        observations = review_round.setdefault("observations", {})
        for backlink_id, dispatch in dispatches.items():
            if dispatch.get("status") == "dispatched" and backlink_id not in observations:
                dispatch["status"] = "unknown_recovery"
                review_round.setdefault("unknown_recovery_ids", []).append(backlink_id)
        if review_round.get("status") == "ACTIVE":
            deadline_at = float(review_round.get("deadline_epoch") or 0)
            if deadline_at and time.time() >= deadline_at:
                pending = [
                    backlink_id
                    for backlink_id in review_round.get("candidate_ids", [])
                    if backlink_id not in dispatches
                ]
                review_round["status"] = "TIME_BUDGET_EXHAUSTED"
                review_round["unreviewed_ids"] = pending
                review_round["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return review_round

    if state.get("unresolved_review_rounds"):
        return None

    candidate_ids = _select_unresolved_review_candidates(
        state=state,
        master_rows=master_rows,
        project_rows=project_rows,
        runtime_dir=runtime_dir,
        limit=limit,
    )
    if not candidate_ids:
        return None

    budget = max(0.0, float(time_budget if time_budget is not None else 300.0))
    now = datetime.datetime.now(datetime.timezone.utc)
    round_id = f"review_{now.strftime('%Y%m%d_%H%M%S')}_{len(state.get('unresolved_review_rounds', [])) + 1}"
    review_round = {
        "round_id": round_id,
        "status": "ACTIVE",
        "candidate_ids": candidate_ids,
        "limit": len(candidate_ids),
        "time_budget_seconds": budget,
        "deadline_epoch": time.time() + budget,
        "created_at": now.isoformat(),
        "dispatches": {},
        "observations": {},
        "unknown_recovery_ids": [],
        "unreviewed_ids": [],
    }
    state.setdefault("unresolved_review_rounds", []).append(review_round)
    state["active_unresolved_review_round_id"] = round_id
    save_cycle_state(state["project_id"], state, runtime_dir)
    return review_round


def _review_dispatch_ids(review_round: dict[str, Any], limit: int) -> list[str]:
    if review_round.get("status") != "ACTIVE":
        return []
    dispatches = review_round.setdefault("dispatches", {})
    observations = review_round.setdefault("observations", {})
    pending = [
        backlink_id
        for backlink_id in review_round.get("candidate_ids", [])
        if backlink_id not in dispatches and backlink_id not in observations
    ]
    if not pending:
        statuses = {str(item.get("status") or "") for item in dispatches.values()}
        if statuses and statuses <= {"observed", "unknown_recovery"}:
            review_round["status"] = "COMPLETED_WITH_UNKNOWN_RECOVERY" if "unknown_recovery" in statuses else "COMPLETED"
            review_round["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return []
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    selected = pending[: max(1, int(limit))]
    for backlink_id in selected:
        dispatches[backlink_id] = {"status": "dispatched", "dispatched_at": now}
    return selected


def _record_review_observations(
    review_round: dict[str, Any],
    dispatched_ids: list[str],
    preparation_result: dict[str, Any],
) -> None:
    ledger_by_id = {
        canonical_domain(entry.get("backlink_id") or entry.get("domain") or ""): entry
        for entry in preparation_result.get("scan_ledger_entries", [])
        if canonical_domain(entry.get("backlink_id") or entry.get("domain") or "")
    }
    observations = preparation_result.get("observations") or {}
    scanned_ids = {
        canonical_domain(backlink_id)
        for backlink_id in preparation_result.get("scanned_backlink_ids", [])
        if canonical_domain(backlink_id)
    }
    ready_ids = {
        canonical_domain(item.get("verified_entry").domain)
        for item in preparation_result.get("ready_rows", [])
        if item.get("verified_entry")
    }
    for backlink_id in dispatched_ids:
        dispatch = review_round.setdefault("dispatches", {}).setdefault(backlink_id, {})
        ledger_entry = ledger_by_id.get(backlink_id)
        checkpoint_observation = observations.get(backlink_id) or {}
        if backlink_id not in scanned_ids and backlink_id not in ready_ids:
            dispatch["status"] = "unknown_recovery"
            if backlink_id not in review_round.setdefault("unknown_recovery_ids", []):
                review_round["unknown_recovery_ids"].append(backlink_id)
            continue
        dispatch["status"] = "observed"
        review_round.setdefault("observations", {})[backlink_id] = {
            "status": "ready" if backlink_id in ready_ids else "unresolved",
            "disposition": (ledger_entry or {}).get("disposition") or checkpoint_observation.get("disposition"),
            "reason": (ledger_entry or {}).get("reason") or checkpoint_observation.get("reason"),
            "observed_at": (ledger_entry or {}).get("scanned_at") or checkpoint_observation.get("observed_at"),
            "probe_evidence": (ledger_entry or {}).get("probe_evidence") or checkpoint_observation.get("probe_evidence") or [],
        }

    statuses = {
        str(item.get("status") or "")
        for item in review_round.setdefault("dispatches", {}).values()
    }
    if statuses and statuses <= {"observed", "unknown_recovery"}:
        review_round["status"] = "COMPLETED_WITH_UNKNOWN_RECOVERY" if "unknown_recovery" in statuses else "COMPLETED"
        review_round["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()


def plan_next_batch(
    state: dict[str, Any],
    master_rows: list[dict[str, Any]],
    project_rows: list[dict[str, Any]],
    batch_ready_target: int = 10,
    batch_scan_limit: int = 50,
    commit_prep: bool = True,
    sheets_service: Any = None,
    runtime_dir: str | None = None,
    entry_verifier: Any = None,
    entry_finder: Any = None,
    project_context: dict[str, Any] | None = None,
    min_ready_delivery: int | None = None,
    concurrency: int = 2,
    time_budget: float | None = None,
    deadline: float | None = None,
    fetcher: Any = None,
) -> dict[str, Any]:
    """规划并准备下一批次。

    1. 自动消费与恢复上次未完成的跨项目同步 (R6)；
    2. 若已有 active_batch 且未全部完成，优先返回当前批次剩余项；
    3. 若已达到 target_success 或快照已按顺序扫描耗尽 (R7)，标记 finished 并返回对账总结；
    4. 否则按快照顺序筛选未处理候选，调用 Phase C 有界现场核验；
    5. 真实写回 Master 提交入口并回读校验 (R2)，确保 Sheet 真实更新后才交付 Ready。
    """
    proj = state["project_id"]
    target_success = state["target_success"]
    cur_success = state["newly_succeeded_count"]

    # 1. 自动消费与恢复上次可能遗留的跨项目同步 (落实 R6 修复)
    if sheets_service and commit_prep:
        try:
            recover_pending_cross_project_sync(
                sheets_service=sheets_service,
                spreadsheet_id=state["spreadsheet_id"],
                project_sheet_name=state["project_sheet"],
                project_header=PROJECT_HEADER,
                commit=True,
                runtime_dir=runtime_dir,
            )
        except Exception as e:
            print(f"[提示] 自动恢复跨项目同步跳过: {e}", file=sys.stderr)

        # 自动恢复遗留 Master 变更 (落实 F4 修复与 S4 刷新)
        try:
            recover_pending_master_mutations(
                sheets_service=sheets_service,
                spreadsheet_id=state["spreadsheet_id"],
                master_sheet_name=state["master_sheet"],
                project_id=proj,
                runtime_dir=runtime_dir,
            )
            # 若恢复了变更且提供了 sheets_service，实时刷新 master_rows 内存数据 (落实 S4 修复)
            if sheets_service and master_rows is not None:
                fresh_m = fetch_all_sheet_rows(sheets_service, state["spreadsheet_id"], state["master_sheet"])
                if fresh_m and len(fresh_m) > 1:
                    master_rows.clear()
                    for idx, r in enumerate(fresh_m[1:], 2):
                        d = dict(zip(MASTER_HEADER, r))
                        d["_sheet_row_num"] = idx
                        master_rows.append(d)
        except Exception as me:
            print(f"[提示] 自动恢复 Master 变更跳过: {me}", file=sys.stderr)

    # 2. 检查停止条件 (落实 R9 修复：失衡时绝不标记完成)
    if not state.get("is_balanced", True):
        state["is_finished"] = False
    elif cur_success >= target_success:
        state["is_finished"] = True
        state["finish_reason"] = f"达到目标新增成功数: {cur_success} >= {target_success}"
        save_cycle_state(proj, state, runtime_dir)
        return {"action": "STOP", "reason": state["finish_reason"], "state": state}

    # 3. 检查是否有尚未完成的活动批次
    active = state.get("active_batch")
    if active and active.get("in_flight"):
        remaining_in_flight = [
            item for item in active.get("ready_items", [])
            if item["domain"] not in state["completed_items"]
            and item["domain"] not in state["human_pending_items"]
        ]
        if remaining_in_flight:
            return {
                "action": "RESUME_ACTIVE_BATCH",
                "batch_id": active["batch_id"],
                "ready_items": remaining_in_flight,
                "state": state,
            }

    # 4. 检查候选快照是否耗尽 (按快照顺序筛选未处理集合，修复 R7)
    snapshot_bids = state["snapshot_candidate_bids"]
    scanned_set = set(state.get("scanned_candidate_bids", []))
    scanned_set.update(state.get("processed_candidate_bids", []))
    pending_ready_set = {
        canonical_domain(bid)
        for bid in state.get("pending_ready_delivery_bids", [])
        if canonical_domain(bid)
    }
    completed_set = set(state.get("completed_items", {}).keys())
    human_pending_set = set(state.get("human_pending_items", {}).keys())

    # 普通轮次仍严格锁定在启动快照内；只有未闭环 Ready 允许回到调度队列，
    # 不清空扫描集合，也不重新扩大快照。
    ordinary_remaining_bids = [
        bid for bid in snapshot_bids
        if bid not in completed_set
        and bid not in human_pending_set
        and (bid not in scanned_set or bid in pending_ready_set)
    ]

    # 已扫描但未处置不等于永久跳过。仅建立一次固定、有限的复核轮，且
    # 轮内一个 ID 最多派发一次；重启遇到未落观察的派发记录一律转为
    # unknown_recovery，不能伪装已完成或反复发起 HTTP/浏览器动作。
    review_round = _get_or_create_unresolved_review_round(
        state=state,
        master_rows=master_rows,
        project_rows=project_rows,
        runtime_dir=runtime_dir,
        limit=batch_scan_limit,
        time_budget=time_budget,
    )
    review_dispatch_bids = _review_dispatch_ids(review_round, batch_scan_limit) if review_round else []
    review_mode = bool(review_dispatch_bids)
    remaining_bids = review_dispatch_bids if review_mode else ordinary_remaining_bids
    if not remaining_bids:
        if not state.get("is_balanced", True):
            state["is_finished"] = False
            state["finish_reason"] = "候选快照已扫描一轮，但当前处于账目失衡状态，禁止标记完成"
        else:
            state["is_finished"] = True
            state["finish_reason"] = f"本轮候选快照已扫描一轮耗尽 (覆盖全部 {len(snapshot_bids)} 个候选)"
        save_cycle_state(proj, state, runtime_dir)
        return {"action": "STOP", "reason": state["finish_reason"], "state": state}

    # 5. 自动启动 Phase C 有界现场准备
    # 建立 master 映射以便识别已有提交入口并进行原快照内优先级挑选 (保持原快照集合完全一致，不漏项、不扩扫)
    mrow_by_bid = {}
    if master_rows:
        for mr in master_rows:
            mbid = canonical_domain(mr.get("外链ID") or mr.get("平台域名") or "")
            if mbid:
                mrow_by_bid[mbid] = mr

    # 普通轮次的优先级分组 (严格在快照范围内)。复核轮必须使用已持久化
    # 的固定 ID 顺序，不能借机扩扫或改变轮次范围。
    # Tier 1: 总表已有非空提交入口的候选 (优先快速复核)
    # Tier 2: 总表尚无提交入口的候选 (需要整站预算深测)
    if review_mode:
        ordered_remaining = review_dispatch_bids
    else:
        tier1_bids = []
        tier2_bids = []
        for bid in remaining_bids:
            mr = mrow_by_bid.get(bid)
            has_entry = bool(mr and str(mr.get("提交入口") or "").strip())
            if has_entry:
                tier1_bids.append(bid)
            else:
                tier2_bids.append(bid)
        ordered_remaining = tier1_bids + tier2_bids
    slice_bids = ordered_remaining[:batch_scan_limit]
    scan_limit = len(slice_bids)

    # 尾批边界防护：needed 绝不能大于 scan_limit，杜绝 scan_limit < target_ready_count 报错 (修复 R7)
    needed = min(batch_ready_target, target_success - cur_success, scan_limit)
    needed = max(1, needed)

    # 按照 slice_bids 顺序组装待准备的项目行
    prow_by_bid = {}
    for r in project_rows:
        if str(r.get("项目ID") or "").strip() == proj and str(r.get("状态") or "").strip() == PROJECT_STATUS_TO_SUBMIT:
            bid = canonical_domain(r.get("外链ID") or r.get("外链域名") or "")
            if bid and bid not in prow_by_bid:
                prow_by_bid[bid] = r

    filtered_project_rows = [prow_by_bid[b] for b in slice_bids if b in prow_by_bid]

    # 若切片在 Sheet 中已无待提交行，普通轮次保留旧兼容标记；复核轮则
    # 将已派发项显式记为未知恢复，绝不能将其伪装成完成观察。
    if not filtered_project_rows:
        if review_mode and review_round:
            _record_review_observations(review_round, review_dispatch_bids, {})
        else:
            for b in slice_bids:
                if b not in state.setdefault("processed_candidate_bids", []):
                    state["processed_candidate_bids"].append(b)
                if b not in state.setdefault("scanned_candidate_bids", []):
                    state["scanned_candidate_bids"].append(b)
        save_cycle_state(proj, state, runtime_dir)
        return plan_next_batch(
            state=state,
            master_rows=master_rows,
            project_rows=project_rows,
            batch_ready_target=batch_ready_target,
            batch_scan_limit=batch_scan_limit,
            commit_prep=commit_prep,
            sheets_service=sheets_service,
            runtime_dir=runtime_dir,
            entry_verifier=entry_verifier,
            entry_finder=entry_finder,
            project_context=project_context,
            min_ready_delivery=min_ready_delivery,
            concurrency=concurrency,
            time_budget=time_budget,
            deadline=deadline,
        )

    def fast_fetch(url: str, timeout: float = 5.0) -> dict:
        return fetch_page(url, timeout=timeout)

    def _phase_c_progress_hook(p_info: dict[str, Any]):
        dom = p_info.get("domain", "")
        sc = p_info.get("scanned_count", 0)
        rc = p_info.get("ready_count", 0)
        out = p_info.get("outcome", "")
        tc = p_info.get("target_ready_count", 0)
        sl = p_info.get("scan_limit", 0)
        is_blk = p_info.get("is_blocked", False)
        blk_msg = " [本机执行资源阻塞]" if is_blk else ""
        print(f"  [探测进度 {sc}/{sl}] {dom:<28} -> {out:<14} (就绪: {rc}/{tc}){blk_msg}", flush=True)

    p_ctx = resolve_project_context(proj, project_context)
    batch_prep_res = prepare_execution_batch(
        master_rows=master_rows,
        project_rows=filtered_project_rows,
        project_id=proj,
        target_ready_count=needed,
        scan_limit=scan_limit,
        project_context=p_ctx,
        entry_verifier=entry_verifier,
        entry_finder=entry_finder,
        fetcher=fetcher or fast_fetch,
        use_cursor=False,
        runtime_dir=runtime_dir,
        concurrency=concurrency,
        time_budget=time_budget,
        deadline=deadline,
        min_ready_delivery=min_ready_delivery,
        force_recheck_ids=review_dispatch_bids if review_mode else None,
        progress_callback=_phase_c_progress_hook,
    )

    if review_mode and review_round:
        _record_review_observations(review_round, review_dispatch_bids, batch_prep_res)
        # dispatch 状态必须在本次扫描的所有后续写回之前先落盘，避免进程
        # 意外退出后把已派发项再次当成未派发。
        save_cycle_state(proj, state, runtime_dir)

    if batch_prep_res.get("local_resource_blocked"):
        print("[警告] Phase C 检测到本机执行资源持续阻塞 (LOCAL_RESOURCE_BLOCKED)，停止派发新任务并保存进度", file=sys.stderr)
        record_cycle_interruption(proj, "本机执行资源阻塞 (LOCAL_RESOURCE_BLOCKED)", runtime_dir=runtime_dir)

    ready_rows = batch_prep_res["ready_rows"]
    phase_ready_bids = {
        canonical_domain(item["verified_entry"].domain)
        for item in ready_rows
        if item.get("verified_entry")
    }
    scanned_count = batch_prep_res["scanned_count"]

    # 依据准备阶段实际扫描到的 candidate ID 精确推进，彻底杜绝切片猜测导致的漏项 (落实 R7 修复)
    scanned_bids = batch_prep_res.get("scanned_backlink_ids")
    if scanned_bids is None:
        scanned_bids = [canonical_domain(r.get("外链ID") or r.get("外链域名") or "") for r in filtered_project_rows[:scanned_count]]

    for b in scanned_bids:
        if b and b not in state.setdefault("processed_candidate_bids", []):
            state["processed_candidate_bids"].append(b)
        if b and b not in state.setdefault("scanned_candidate_bids", []):
            state["scanned_candidate_bids"].append(b)

    # 保持单写入者原则：真实 scan_ledger.jsonl 已在 prepare_execution_batch 内部物理落盘 (F4)
    # 此处无需重复写入，避免上下两层各写一遍

    # 6. 真实写回 Master 提交入口及实测限制并回读校验 (落实动态列定位)
    if commit_prep and sheets_service:
        updates = []
        master_sheet_name = state["master_sheet"]
        entry_col_letter = col_index_to_letter(MASTER_HEADER.index("提交入口"))
        limits_col_letter = col_index_to_letter(MASTER_HEADER.index("实测限制"))
        verify_time_col_letter = col_index_to_letter(MASTER_HEADER.index("最后验证时间"))
        items_needing_writeback = []

        # 6.1 提交入口写回
        for item in ready_rows:
            mrow = item["master_row"]
            ventry = item["verified_entry"]
            row_num = mrow.get("_sheet_row_num")
            orig_entry = str(item.get("orig_submission_url") or "").strip()
            if ventry and ventry.url != orig_entry and row_num:
                updates.append({
                    "range": f"'{master_sheet_name}'!{entry_col_letter}{row_num}",
                    "values": [[ventry.url]],
                })
                items_needing_writeback.append((item, row_num, ventry.url))

        # 6.2 现场证实 AI-only 限制写回 (若原限制为空且现场核验确立)
        items_needing_limits_writeback = []
        for mr in batch_prep_res.get("updated_master_rows", []):
            m_rnum = mr.get("_sheet_row_num")
            m_limits = mr.get("实测限制")
            m_vtime = mr.get("最后验证时间")
            if m_rnum and m_limits == "仅限AI工具":
                orig_limits = str(mr.get("_orig_实测限制") or "").strip()
                if not orig_limits:
                    updates.append({
                        "range": f"'{master_sheet_name}'!{limits_col_letter}{m_rnum}",
                        "values": [[m_limits]],
                    })
                    if m_vtime:
                        updates.append({
                            "range": f"'{master_sheet_name}'!{verify_time_col_letter}{m_rnum}",
                            "values": [[m_vtime]],
                        })
                    items_needing_limits_writeback.append((mr, m_rnum, m_limits, m_vtime))

        if updates:
            write_ok = False
            try:
                sheets_service.spreadsheets().values().batchUpdate(
                    spreadsheetId=state["spreadsheet_id"],
                    body={"valueInputOption": "USER_ENTERED", "data": updates},
                ).execute()
                write_ok = True
            except Exception as e:
                print(f"[警告] 写回 Master 表出现异常: {e}", file=sys.stderr)

            unresolved_mutations: list[dict[str, Any]] = []
            if write_ok:
                verified_items = []
                for item, row_num, expected_url in items_needing_writeback:
                    exp_domain = canonical_domain(item["verified_entry"].domain)
                    try:
                        rb_res = sheets_service.spreadsheets().values().get(
                            spreadsheetId=state["spreadsheet_id"],
                            range=f"'{master_sheet_name}'!A{row_num}:D{row_num}",
                        ).execute()
                        rb_vals = rb_res.get("values", [[]])[0]
                        if len(rb_vals) == 1 and rb_vals[0].strip() == expected_url:
                            actual_bid = exp_domain
                            actual_url = rb_vals[0].strip()
                        else:
                            actual_bid = canonical_domain(rb_vals[MASTER_HEADER.index("外链ID")]) if len(rb_vals) > MASTER_HEADER.index("外链ID") else ""
                            actual_url = rb_vals[MASTER_HEADER.index("提交入口")].strip() if len(rb_vals) > MASTER_HEADER.index("提交入口") else ""
                        if actual_bid == exp_domain and actual_url == expected_url:
                            verified_items.append(item)
                        else:
                            err_msg = f"Master 提交入口回读不一致 (行 {row_num}): 期望 ({exp_domain}, {expected_url!r}), 实读 ({actual_bid}, {actual_url!r})"
                            print(f"[警告] {err_msg}", file=sys.stderr)
                            unresolved_mutations.append({
                                "domain": exp_domain,
                                "row_num": row_num,
                                "mutation_type": "submission_entry",
                                "cell_range": f"'{master_sheet_name}'!{entry_col_letter}{row_num}",
                                "expected_val": expected_url,
                                "actual_val": actual_url,
                                "error": err_msg,
                            })
                    except Exception as rb_exc:
                        err_msg = f"Master 提交入口回读失败 (行 {row_num}): {rb_exc}"
                        print(f"[警告] {err_msg}", file=sys.stderr)
                        unresolved_mutations.append({
                            "domain": exp_domain,
                            "row_num": row_num,
                            "mutation_type": "submission_entry",
                            "cell_range": f"'{master_sheet_name}'!{entry_col_letter}{row_num}",
                            "expected_val": expected_url,
                            "error": str(rb_exc),
                        })

                # 回读核验 AI-only 实测限制与验证时间 (落实 F4 全字段回读: A列ID, K列限制, M列时间)
                limits_col_idx = MASTER_HEADER.index("实测限制")
                vtime_col_idx = MASTER_HEADER.index("最后验证时间") if "最后验证时间" in MASTER_HEADER else -1
                for mr, row_num, exp_limits, exp_vtime in items_needing_limits_writeback:
                    exp_domain = canonical_domain(mr.get("外链ID") or mr.get("平台域名") or "")
                    try:
                        rb_all = sheets_service.spreadsheets().values().get(
                            spreadsheetId=state["spreadsheet_id"],
                            range=f"'{master_sheet_name}'!A{row_num}:M{row_num}",
                        ).execute()
                        row_vals = rb_all.get("values", [[]])[0]
                        act_bid = canonical_domain(row_vals[MASTER_HEADER.index("外链ID")]) if len(row_vals) > MASTER_HEADER.index("外链ID") else ""
                        act_limits = row_vals[limits_col_idx].strip() if len(row_vals) > limits_col_idx else ""
                        act_vtime = row_vals[vtime_col_idx].strip() if vtime_col_idx >= 0 and len(row_vals) > vtime_col_idx else ""

                        time_match = are_equivalent_timestamps(act_vtime, exp_vtime) if exp_vtime else True
                        is_valid = (act_bid == exp_domain and act_limits == exp_limits and time_match)

                        if not is_valid:
                            err_msg = (
                                f"Master 实测限制全字段回读不一致 (行 {row_num}): "
                                f"期望 (ID={exp_domain}, 限制={exp_limits!r}, 时间={exp_vtime!r}), "
                                f"实读 (ID={act_bid}, 限制={act_limits!r}, 时间={act_vtime!r})"
                            )
                            print(f"[警告] {err_msg}", file=sys.stderr)
                            unresolved_mutations.append({
                                "domain": exp_domain,
                                "row_num": row_num,
                                "mutation_type": "limits_and_vtime",
                                "cell_range": f"'{master_sheet_name}'!A{row_num}:M{row_num}",
                                "expected_limits": exp_limits,
                                "expected_vtime": exp_vtime,
                                "actual_bid": act_bid,
                                "actual_limits": act_limits,
                                "actual_vtime": act_vtime,
                                "error": err_msg,
                            })
                    except Exception as rb_lim_exc:
                        err_msg = f"Master 实测限制回读异常 (行 {row_num}): {rb_lim_exc}"
                        print(f"[警告] {err_msg}", file=sys.stderr)
                        unresolved_mutations.append({
                            "domain": exp_domain,
                            "row_num": row_num,
                            "mutation_type": "limits_and_vtime",
                            "cell_range": f"'{master_sheet_name}'!A{row_num}:M{row_num}",
                            "expected_limits": exp_limits,
                            "expected_vtime": exp_vtime,
                            "error": str(rb_lim_exc),
                        })

                # 仅交付原本无需写回的项与成功写回且回读一致的项
                items_without_writeback = [it for it in ready_rows if it not in [x[0] for x in items_needing_writeback]]
                ready_rows = items_without_writeback + verified_items
            else:
                # 写入整体失败时，记录所有待写回变更为待恢复队列
                for item, row_num, expected_url in items_needing_writeback:
                    unresolved_mutations.append({
                        "domain": canonical_domain(item["verified_entry"].domain),
                        "row_num": row_num,
                        "mutation_type": "submission_entry",
                        "cell_range": f"'{master_sheet_name}'!{entry_col_letter}{row_num}",
                        "expected_val": expected_url,
                        "error": "batchUpdate 整体写入失败",
                    })
                for mr, row_num, exp_limits, exp_vtime in items_needing_limits_writeback:
                    unresolved_mutations.append({
                        "domain": canonical_domain(mr.get("外链ID") or mr.get("平台域名") or ""),
                        "row_num": row_num,
                        "mutation_type": "limits_and_vtime",
                        "cell_range": f"'{master_sheet_name}'!A{row_num}:M{row_num}",
                        "expected_limits": exp_limits,
                        "expected_vtime": exp_vtime,
                        "error": "batchUpdate 整体写入失败",
                    })
                ready_rows = [it for it in ready_rows if it not in [x[0] for x in items_needing_writeback]]

            # 任何未闭环变更都阻断对应候选的 Ready 发布；同批其他已满足门禁的
            # 候选仍可交付，失败项通过 pending_ready_delivery_bids 恢复。
            unresolved_domains = {
                canonical_domain(mutation.get("domain") or "")
                for mutation in unresolved_mutations
                if canonical_domain(mutation.get("domain") or "")
            }
            if unresolved_domains:
                ready_rows = [
                    item
                    for item in ready_rows
                    if canonical_domain(item["verified_entry"].domain) not in unresolved_domains
                ]

            # 持久化未闭环的 Master 变更至 pending_master_mutations.json (落实 F4 规范)
            # 本轮只新增/更新自己的变更，但其他候选仍可能处于恢复中；
            # 合并保留现有队列，避免一次成功写回误清理别的候选。
            current_pending = load_pending_master_mutations(proj, runtime_dir)
            pending_by_key = {
                _mutation_unique_key(mutation): mutation
                for mutation in [*current_pending, *unresolved_mutations]
            }
            save_pending_master_mutations(
                proj,
                list(pending_by_key.values()),
                runtime_dir,
            )

    delivered_ready_bids = {
        canonical_domain(item["verified_entry"].domain)
        for item in ready_rows
        if item.get("verified_entry")
    }
    pending_ready_bids = {
        canonical_domain(bid)
        for bid in state.get("pending_ready_delivery_bids", [])
        if canonical_domain(bid)
    }
    # 新扫描出的 Ready 若未通过 Master 写回/回读，进入恢复队列；本次成功
    # 发布的项从恢复队列移除。两者均只来自当前启动快照。
    pending_ready_bids.update(phase_ready_bids - delivered_ready_bids)
    pending_ready_bids.difference_update(delivered_ready_bids)
    snapshot_order = {bid: idx for idx, bid in enumerate(state["snapshot_candidate_bids"])}
    state["pending_ready_delivery_bids"] = sorted(
        pending_ready_bids,
        key=lambda bid: snapshot_order.get(bid, len(snapshot_order)),
    )
    delivered_history = set(state.get("delivered_ready_candidate_bids", []))
    delivered_history.update(delivered_ready_bids)
    state["delivered_ready_candidate_bids"] = [
        bid for bid in state["snapshot_candidate_bids"] if bid in delivered_history
    ]

    ready_items = []
    ready_domains = []
    for item in ready_rows:
        prow = item["project_row"]
        ventry = item["verified_entry"]
        cid = canonical_domain(ventry.domain)
        ready_domains.append(cid)
        ready_items.append({
            "domain": cid,
            "submission_url": ventry.url,
            "evidence_type": ventry.evidence_type,
            "evidence_summary": ventry.evidence_summary,
            "project_row_num": prow.get("_sheet_row_num"),
            "target_url": prow.get("目标URL") or "",
        })

    batch_id = f"batch_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    is_blocked = bool(batch_prep_res.get("local_resource_blocked"))

    if is_blocked:
        interruption_msg = "LOCAL_RESOURCE_BLOCKED: worker concurrency saturated"
        state["interruption_reason"] = interruption_msg
        if ready_items:
            # 停止派发前已收集到部分 Ready：保存状态并标记为 HALT_WITH_PARTIAL_READY
            state["active_batch"] = {
                "batch_id": batch_id,
                "ready_domains": ready_domains,
                "ready_items": ready_items,
                "in_flight": True,
                "planned_count": len(ready_items),
                "scanned_in_prep": scanned_count,
            }
            save_cycle_state(proj, state, runtime_dir)
            return {
                "action": "HALT_WITH_PARTIAL_READY",
                "batch_id": batch_id,
                "ready_domains": ready_domains,
                "ready_items": ready_items,
                "scanned_in_prep": scanned_count,
                "state": state,
                "interruption_reason": interruption_msg,
                "has_local_blocked": True,
            }
        else:
            save_cycle_state(proj, state, runtime_dir)
            return {
                "action": "HALT",
                "batch_id": batch_id,
                "ready_domains": [],
                "ready_items": [],
                "scanned_in_prep": scanned_count,
                "state": state,
                "interruption_reason": interruption_msg,
                "has_local_blocked": True,
            }

    state["active_batch"] = {
        "batch_id": batch_id,
        "ready_domains": ready_domains,
        "ready_items": ready_items,
        "in_flight": True,
        "planned_count": len(ready_items),
        "scanned_in_prep": scanned_count,
        "review_round_id": review_round.get("round_id") if review_mode and review_round else None,
    } if ready_items else None
    save_cycle_state(proj, state, runtime_dir)
    # 检查点只在至少有一项 Ready 已通过所有写回/回读门禁且没有未交付
    # Ready 时清理。写回失败、回读失败或纯 unresolved 扫描都必须保留观察现场。
    if ready_items and not state["pending_ready_delivery_bids"]:
        clear_phase_c_checkpoint(proj, runtime_dir=runtime_dir)

    return {
        "action": "EXECUTE_BATCH",
        "batch_id": batch_id,
        "ready_domains": ready_domains,
        "ready_items": ready_items,
        "scanned_in_prep": scanned_count,
        "pending_ready_delivery_bids": list(state["pending_ready_delivery_bids"]),
        "state": state,
    }


def start_task_attempt(
    state: dict[str, Any],
    backlink_id: str,
    is_resume_attempt: bool = False,
    master_rows: list[dict[str, Any]] | None = None,
    project_rows: list[dict[str, Any]] | None = None,
    sheets_service: Any = None,
    commit: bool = True,
    runtime_dir: str | None = None,
) -> dict[str, Any]:
    """开始一次候选执行尝试：强制调用门禁，更新项目行状态为'处理中'并严格计算尝试次数 (落实执行动作规范)。

    硬约束：
    1. 快照与Ready守卫：候选必须在初始快照内，且新尝试必须属于当前批次 Ready 清单；
    2. 门禁强制执行：必须读取并调用 ProductionSheetGate.validate_execution_start，拒绝不合格启动；
    3. commit=True 必须提供 sheets_service 并进行写前旧值与写后整行回读核验；
    4. 记录 active_attempt 防止重复累加。
    """
    proj = state["project_id"]
    cid = canonical_domain(backlink_id)
    iso_now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # 1. 初始快照范围守卫
    snapshot_bids = {canonical_domain(x) for x in state.get("snapshot_candidate_bids", [])}
    if snapshot_bids and cid not in snapshot_bids:
        raise ValueError(f"候选 [{cid}] 不在当前 cycle 初始候选快照内，禁止跨快照启动尝试")

    # 2. 当前批次 Ready 清单守卫 (新尝试必须属于当前 Ready 清单且批次必须非空)
    if not is_resume_attempt:
        active_batch = state.get("active_batch") or {}
        ready_bids = {canonical_domain(x) for x in active_batch.get("ready_domains", [])}
        if not ready_bids or cid not in ready_bids:
            raise ValueError(
                f"候选 [{cid}] 不在当前批次 Ready 清单中（当前就绪数: {len(ready_bids)}），禁止启动未就绪条目的提交"
            )

    target_prow = None
    if project_rows:
        for pr in project_rows:
            if str(pr.get("项目ID") or "").strip() == proj and canonical_domain(pr.get("外链ID") or pr.get("外链域名") or "") == cid:
                target_prow = pr
                break

    if not target_prow or not target_prow.get("_sheet_row_num"):
        raise RuntimeError(f"未能在项目表中唯一定位目标行 [{cid}] (project_id={proj!r})")

    current_status = str(target_prow.get("状态") or "").strip()
    raw_attempt = target_prow.get("尝试次数")
    try:
        current_attempt = int(raw_attempt) if raw_attempt is not None and str(raw_attempt).strip() != "" else 0
    except Exception:
        current_attempt = 0

    if not is_resume_attempt:
        if current_status != PROJECT_STATUS_TO_SUBMIT:
            raise ValueError(f"正常启动尝试要求状态必须为 '待提交'，当前为 {current_status!r} [{cid}]")
        next_attempt = current_attempt + 1
    else:
        if current_status not in ("需人工", "处理中"):
            raise ValueError(f"断点恢复要求状态必须为 '需人工' 或 '处理中'，当前为 {current_status!r} [{cid}]")
        next_attempt = current_attempt

    # 3. 门禁强制执行 (落实实施约束 1)
    if commit and not sheets_service:
        raise RuntimeError(f"commit=True 但未提供有效的 sheets_service，拒绝在未真实落表时启动尝试 [{cid}]")

    if commit and sheets_service and not master_rows:
        try:
            master_rows = read_all_master_rows(sheets_service, state["spreadsheet_id"], state["master_sheet"])
        except Exception as mr_exc:
            raise RuntimeError(f"启动门禁需要读取总表事实，但获取总表失败 [{cid}]: {mr_exc}") from mr_exc

    GateClass, _ = _get_production_gate()
    if GateClass and hasattr(GateClass, "validate_execution_start"):
        matching_mrows = [
            mr for mr in (master_rows or [])
            if canonical_domain(mr.get("外链ID") or mr.get("平台域名") or "") == cid
        ]
        start_val = GateClass.validate_execution_start(
            project_row=target_prow,
            master_rows=matching_mrows,
            now_iso=iso_now,
            resume_same_attempt=is_resume_attempt,
        )
        if not start_val.get("eligible", False):
            raise ValueError(f"启动执行被门禁拒绝 [{cid}]: {start_val.get('reason', '不满足启动资格')}")
        next_attempt = int(start_val.get("next_attempt_count", next_attempt))

    row_num = target_prow["_sheet_row_num"]
    p_sheet = state["project_sheet"]

    if commit and sheets_service:
        # 写前整行核验身份与最新状态一致性
        rb_pre = sheets_service.spreadsheets().values().get(
            spreadsheetId=state["spreadsheet_id"],
            range=f"'{p_sheet}'!A{row_num}:J{row_num}",
        ).execute()
        cur_vals = rb_pre.get("values", [[]])[0]
        cur_proj = cur_vals[PROJECT_HEADER.index("项目ID")].strip() if len(cur_vals) > PROJECT_HEADER.index("项目ID") else ""
        cur_dom = cur_vals[PROJECT_HEADER.index("外链域名")].strip() if len(cur_vals) > PROJECT_HEADER.index("外链域名") else ""
        cur_bid = cur_vals[PROJECT_HEADER.index("外链ID")].strip() if len(cur_vals) > PROJECT_HEADER.index("外链ID") else ""
        cur_status = cur_vals[PROJECT_HEADER.index("状态")].strip() if len(cur_vals) > PROJECT_HEADER.index("状态") else ""

        if cur_proj != proj or (canonical_domain(cur_bid) != cid and canonical_domain(cur_dom) != cid):
            raise RuntimeError(
                f"启动尝试写前身份校验失败: 目标行 A{row_num} (ID={cur_bid!r}, 域={cur_dom!r}) 与内存目标 [{cid}] 不匹配"
            )
        if not is_resume_attempt and cur_status != PROJECT_STATUS_TO_SUBMIT:
            raise RuntimeError(
                f"启动尝试写前状态校验失败: 目标行 A{row_num} 最新状态为 {cur_status!r}，非 '待提交'"
            )

        # 真实写回：更新状态为“处理中”，尝试次数写入 next_attempt
        status_col_idx = PROJECT_HEADER.index("状态")
        attempt_col_idx = PROJECT_HEADER.index("尝试次数")
        stat_letter = col_index_to_letter(status_col_idx)
        att_letter = col_index_to_letter(attempt_col_idx)

        sheets_service.spreadsheets().values().batchUpdate(
            spreadsheetId=state["spreadsheet_id"],
            body={
                "valueInputOption": "USER_ENTERED",
                "data": [
                    {
                        "range": f"'{p_sheet}'!{stat_letter}{row_num}",
                        "values": [["处理中"]],
                    },
                    {
                        "range": f"'{p_sheet}'!{att_letter}{row_num}",
                        "values": [[next_attempt]],
                    },
                ],
            },
        ).execute()

        # 写后回读整行核验
        rb_post = sheets_service.spreadsheets().values().get(
            spreadsheetId=state["spreadsheet_id"],
            range=f"'{p_sheet}'!A{row_num}:J{row_num}",
        ).execute()
        post_vals = rb_post.get("values", [[]])[0]
        post_status = post_vals[status_col_idx].strip() if len(post_vals) > status_col_idx else ""
        post_att_str = post_vals[attempt_col_idx].strip() if len(post_vals) > attempt_col_idx else ""
        try:
            post_attempt = int(post_att_str) if post_att_str != "" else 0
        except Exception:
            post_attempt = 0

        if post_status != "处理中" or post_attempt != next_attempt:
            raise RuntimeError(
                f"启动尝试写后回读校验失败 (行 {row_num}): 状态期望 '处理中' 实读 {post_status!r}, 尝试次数期望 {next_attempt} 实读 {post_attempt}"
            )

    if target_prow is not None:
        target_prow["状态"] = "处理中"
        target_prow["尝试次数"] = str(next_attempt)
        target_prow["最近操作时间"] = iso_now

    # 4. 落地 active_attempt 运行态 (落实实施约束 1)
    state["active_attempt"] = {
        "backlink_id": cid,
        "attempt_count": next_attempt,
        "started_at": iso_now,
        "is_resume": is_resume_attempt,
    }
    save_cycle_state(proj, state, runtime_dir)

    print(f"🚀 [启动尝试] 条目 [{cid}] 进入 '处理中'，确立尝试次数为 {next_attempt} (断点恢复: {is_resume_attempt})")
    return {
        "ok": True,
        "backlink_id": cid,
        "status": "处理中",
        "attempt_count": next_attempt,
        "is_resume": is_resume_attempt,
        "started_at": iso_now,
    }


def record_task_outcome(
    state: dict[str, Any],
    backlink_id: str,
    status: str = "",
    reason: str | None = None,
    evidence: str | None = None,
    result_url: str | None = None,
    outcome_status: str = "",
    target_id: str | None = None,
    is_existing_prior_submit: bool = False,
    is_resume_attempt: bool = False,
    platform_facts: dict[str, Any] | str | None = None,
    project_rows: list[dict[str, Any]] | None = None,
    master_rows: list[dict[str, Any]] | None = None,
    sheets_service: Any = None,
    commit: bool = True,
    runtime_dir: str | None = None,
) -> dict[str, Any]:
    """记录条目提交结果，完成终态写回、尝试次数核验与持久化。

    1. 门禁校验拟变更内容；
    2. 核验并写回尝试次数（绝不无条件加 1，复用已确立尝试次数）；
    3. commit=True 必须提供 sheets_service 并做写前写后回读核验；
    4. 产生 human-pending 文件联动。
    """
    proj = state["project_id"]
    cid = canonical_domain(backlink_id)
    iso_now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    raw_status = status or outcome_status
    if not raw_status:
        raise ValueError("必须指定 outcome 状态 (status 或 outcome_status)")
    status = str(raw_status).strip()

    # 1. 凭据硬性约束与证据核验
    if commit and not sheets_service:
        raise RuntimeError(f"commit=True 但未提供有效的 sheets_service，拒绝在未真实落表时记录结果 [{cid}]")

    if status in SUCCESS_STATUSES:
        if not evidence and not result_url:
            raise ValueError(f"记录提交成功必须提供有效证据 (evidence 或 result_url)，拒绝空证据记录 [{cid}]")

    # 门禁校验 (调用 ProductionSheetGate.validate_project_mutation 与 validate_master_mutation)
    GateClass, _ = _get_production_gate()
    ev_dict: dict[str, Any] = {}
    if isinstance(evidence, dict):
        ev_dict = dict(evidence)
    elif isinstance(evidence, str) and evidence.strip().startswith("{") and evidence.strip().endswith("}"):
        try:
            ev_dict = json.loads(evidence.strip())
        except Exception:
            ev_dict = {"raw_evidence": evidence}
    else:
        ev_dict = {"raw_evidence": str(evidence or "")}

    sheet_result_url = result_url if status == "已上线" else ""
    ev_dict.setdefault("result_url", sheet_result_url)
    ev_dict.setdefault("status", status)
    ev_dict["public_access_verified"] = bool(ev_dict.get("public_access_verified", False))
    ev_dict["listing_identity_verified"] = bool(ev_dict.get("listing_identity_verified", False))
    ev_dict["public_listing_verified"] = bool(ev_dict.get("public_listing_verified", False))
    if sheet_result_url:
        ev_dict.setdefault("public_listing_url", sheet_result_url)

    if GateClass and hasattr(GateClass, "validate_project_mutation"):
        proposed = {
            "状态": status,
            "结果链接": sheet_result_url,
            "原因/备注": reason,
            "证据摘要": str(evidence or ""),
        }
        try:
            GateClass.validate_project_mutation(evidence=ev_dict, proposed=proposed)
        except Exception as ge:
            raise ValueError(f"门禁校验拦截失败 [{cid}]: {ge}") from ge

    # ------------------------------------------------------------------
    # 平台事实提取、严格证据校验与 Master 门禁校验 (在写项目表之前写前拒绝，落实 S2 与 S5 修复)
    # ------------------------------------------------------------------
    target_mrow = None
    if master_rows:
        for mr in master_rows:
            if canonical_domain(mr.get("外链ID") or mr.get("平台域名") or "") == cid:
                target_mrow = mr
                break

    facts_raw = {}
    if isinstance(platform_facts, dict):
        facts_raw = dict(platform_facts)
    elif isinstance(platform_facts, str) and platform_facts.strip():
        try:
            facts_raw = json.loads(platform_facts.strip())
        except Exception as je:
            raise ValueError(f"platform_facts 不是合法 JSON 格式: {je}")
    elif isinstance(evidence, dict) and "platform_facts" in evidence:
        facts_raw = dict(evidence["platform_facts"])

    valid_facts = validate_platform_facts(
        facts=facts_raw,
        evidence=ev_dict if isinstance(ev_dict, dict) else evidence,
        outcome_status=status,
        backlink_id=cid,
    )

    # 预计算 Master 表变更
    proposed_master_updates: dict[str, Any] = {}
    m_status = target_mrow.get("基础状态", "") if target_mrow else ""
    m_reason = target_mrow.get("基础排除原因", "") if target_mrow else (reason or "")
    m_limits = target_mrow.get("实测限制", "") if target_mrow else ""
    m_free = target_mrow.get("实测免费", "") if target_mrow else ""
    m_notes = target_mrow.get("平台备注", "") if target_mrow else ""

    # (A) 提交入口
    if "entry_url" in valid_facts:
        proposed_master_updates["提交入口"] = valid_facts["entry_url"]

    # (B) 否定入口：仅当总表现有入口等于该错误路径时清除该入口；平台备注追加记录，保留已有事实
    if "negated_entries" in valid_facts:
        cur_entry = str(target_mrow.get("提交入口") or "").strip() if target_mrow else ""
        cur_norm = normalize_canonical_url(cur_entry) if cur_entry else ""
        neg_norms = {normalize_canonical_url(u) for u in valid_facts["negated_entries"]}
        if cur_entry and (cur_norm in neg_norms or cur_entry.rstrip("/") in [u.rstrip("/") for u in valid_facts["negated_entries"]]):
            proposed_master_updates["提交入口"] = ""

        # 平台备注追加否定入口，防重复追加
        for u in valid_facts["negated_entries"]:
            neg_record = f"否定入口: {u} ({reason or '错误入口'})"
            if neg_record not in m_notes and u not in m_notes:
                m_notes = f"{m_notes}; {neg_record}".strip("; ")
        proposed_master_updates["平台备注"] = m_notes

    # (C) 实测限制：集合式合并保留已有事实，绝不覆盖已有已知限制 (落实 S5 修复)
    if "limits" in valid_facts:
        new_lim = str(valid_facts["limits"] or "").strip()
        if not m_limits:
            merged_limits = new_lim
        else:
            existing_parts = [p.strip() for p in m_limits.split(";") if p.strip()]
            new_parts = [p.strip() for p in new_lim.split(";") if p.strip()]
            for np in new_parts:
                if np not in existing_parts:
                    existing_parts.append(np)
            merged_limits = "; ".join(existing_parts)
        proposed_master_updates["实测限制"] = merged_limits
        m_limits = merged_limits

    # (D) 实测免费
    if "free" in valid_facts:
        proposed_master_updates["实测免费"] = valid_facts["free"]
        m_free = valid_facts["free"]

    # (E) 实测需登录与登录方式
    if "requires_login" in valid_facts:
        proposed_master_updates["实测需登录"] = valid_facts["requires_login"]
    if "login_method" in valid_facts:
        proposed_master_updates["实测登录方式"] = valid_facts["login_method"]

    # (F) 实测链接属性
    if "link_rel" in valid_facts:
        proposed_master_updates["实测链接属性"] = valid_facts["link_rel"]

    # (G) 平台备注补充
    if "notes" in valid_facts:
        note_add = valid_facts["notes"]
        if note_add not in m_notes:
            m_notes = f"{m_notes}; {note_add}".strip("; ")
            proposed_master_updates["平台备注"] = m_notes

    # (H) 平台级全局事实严密研判
    combined_info = f"{reason} {evidence}".lower()
    is_global_unavail = False
    has_unconfirmed_marker = any(
        kw in combined_info
        for kw in [
            "未确认", "尚未确认", "主页正常", "仅入口", "单个入口",
            "暂时", "临时", "疑似", "重试", "timeout", "超时"
        ]
    )

    if not has_unconfirmed_marker:
        is_dead_site = (
            status == "失败"
            and (
                "nxdomain" in combined_info
                or "域名过期" in combined_info
                or "域名出售" in combined_info
                or "域名停放" in combined_info
                or "永久死站" in combined_info
                or "站点已下线" in combined_info
                or ("死站" in combined_info and "404" not in combined_info)
            )
        )
        is_closed_platform = (
            status == "不适用"
            and any(
                kw in combined_info
                for kw in [
                    "明确关闭收录", "关闭收录", "不再收录", "停止运营", "关闭注册", "平台关停"
                ]
            )
        )
        if is_dead_site:
            m_status = "失效"
            m_reason = reason or "永久死站"
            is_global_unavail = True
        elif is_closed_platform:
            m_status = "已排除"
            m_reason = reason or "平台关闭收录"
            is_global_unavail = True

    if is_global_unavail:
        proposed_master_updates["基础状态"] = m_status
        proposed_master_updates["基础排除原因"] = m_reason
    elif "master_status" in valid_facts:
        proposed_master_updates["基础状态"] = valid_facts["master_status"]
        if "master_exclusion_reason" in valid_facts:
            proposed_master_updates["基础排除原因"] = valid_facts["master_exclusion_reason"]

    if proposed_master_updates:
        proposed_master_updates["最后验证时间"] = valid_facts.get("observed_at") or iso_now

    # 门禁校验 Master 变更 (调用 ProductionSheetGate.validate_master_mutation, 落实 S2 门禁接入，证据与拟写事实保持绝对独立)
    if GateClass and hasattr(GateClass, "validate_master_mutation") and proposed_master_updates:
        gate_m_ev = dict(ev_dict)
        # 将通过严格校验且在原始证据中确有观察的事实同步至 gate_m_ev 供门禁识别
        # 注意：绝不注入未实际观察的属性 (如未测 live_dom_rel 绝对不注入，保持证据独立性)
        if "limits" in valid_facts and "limits" not in gate_m_ev and "实测限制" not in gate_m_ev:
            # 传递原始观察，不能把拟写值复制为证据。
            gate_m_ev["limits"] = next(
                (ev_dict[key] for key in ("restriction", "eligibility") if key in ev_dict),
                evidence,
            )
        if "free" in valid_facts and "free" not in gate_m_ev and "实测免费" not in gate_m_ev:
            gate_m_ev["free"] = valid_facts["free"]
        if "requires_login" in valid_facts and "requires_login" not in gate_m_ev and "实测需登录" not in gate_m_ev:
            gate_m_ev["requires_login"] = valid_facts["requires_login"]
        if "login_method" in valid_facts and "login_method" not in gate_m_ev and "实测登录方式" not in gate_m_ev:
            gate_m_ev["login_method"] = valid_facts["login_method"]
        try:
            GateClass.validate_master_mutation(
                evidence=gate_m_ev,
                prior_facts=target_mrow,
                proposed=proposed_master_updates,
            )
        except Exception as gme:
            raise ValueError(f"Master 表门禁校验拦截失败 [{cid}]: {gme}") from gme

    # 2. 确定最终尝试次数并落表：写前身份核实与写后整行回读校验
    target_prow = None
    if project_rows:
        for pr in project_rows:
            if str(pr.get("项目ID") or "").strip() == proj and canonical_domain(pr.get("外链ID") or pr.get("外链域名") or "") == cid:
                target_prow = pr
                break

    if commit and sheets_service:
        # 若在项目表中未找到目标行或缺少行号，严禁跳过写入并记为成功
        if not target_prow or not target_prow.get("_sheet_row_num"):
            raise RuntimeError(
                f"正式落表模式下未能在项目表中唯一定位目标行 [{cid}] (project_id={proj!r})，拒绝虚假记账"
            )

    active_att = state.get("active_attempt")
    if active_att and active_att.get("backlink_id") == cid:
        final_attempt = int(active_att.get("attempt_count", 1))
    else:
        # 重报相同结果或直接检查现有行 (落实约束 1：无论走哪个分支都只能核验保留已确立次数，不能自行加一)
        prev_completed = state.get("completed_items", {}).get(cid)
        raw_att = target_prow.get("尝试次数") if target_prow else 0
        try:
            curr_att = int(raw_att) if raw_att is not None and str(raw_att).strip() != "" else 0
        except Exception:
            curr_att = 0

        if prev_completed and prev_completed.get("attempts"):
            final_attempt = int(prev_completed.get("attempts"))
        elif curr_att > 0:
            final_attempt = curr_att
        else:
            final_attempt = 0

    if commit and sheets_service:
        row_num = target_prow["_sheet_row_num"]
        p_sheet = state["project_sheet"]

        # 写前整行核验身份，防止行移位误改他人数据 (落实 R3 修复)
        rb_pre = sheets_service.spreadsheets().values().get(
            spreadsheetId=state["spreadsheet_id"],
            range=f"'{p_sheet}'!A{row_num}:J{row_num}",
        ).execute()
        cur_vals = rb_pre.get("values", [[]])[0]
        cur_proj = cur_vals[PROJECT_HEADER.index("项目ID")].strip() if len(cur_vals) > PROJECT_HEADER.index("项目ID") else ""
        cur_bid = canonical_domain(cur_vals[PROJECT_HEADER.index("外链ID")]) if len(cur_vals) > PROJECT_HEADER.index("外链ID") else ""
        if cur_proj != proj or cur_bid != cid:
            raise RuntimeError(
                f"写前行身份核验失败 (行号 {row_num}): 期望 ({proj}, {cid})，实际读到 ({cur_proj}, {cur_bid})，可能发生行移位，拒绝写入"
            )

        # 身份核验通过后，核验尝试次数硬性凭据 (落实 F1 规范：成功状态必须有真实执行凭据)
        if final_attempt == 0 and status in SUCCESS_STATUSES:
            raise RuntimeError(
                f"候选条目 [{cid}] 未经 start-attempt 启动真实执行尝试且历史尝试次数为 0，严禁无凭据记录为成功/审核中"
            )

        st_col = col_index_to_letter(PROJECT_HEADER.index("状态"))
        att_col = col_index_to_letter(PROJECT_HEADER.index("尝试次数"))
        time_col = col_index_to_letter(PROJECT_HEADER.index("最近操作时间"))
        res_col = col_index_to_letter(PROJECT_HEADER.index("结果链接"))
        reason_col = col_index_to_letter(PROJECT_HEADER.index("原因/备注"))
        ev_col = col_index_to_letter(PROJECT_HEADER.index("证据摘要"))

        batch_vals = [
            {"range": f"'{p_sheet}'!{st_col}{row_num}", "values": [[status]]},
            {"range": f"'{p_sheet}'!{att_col}{row_num}", "values": [[str(final_attempt)]]},
            {"range": f"'{p_sheet}'!{time_col}{row_num}", "values": [[iso_now]]},
            {"range": f"'{p_sheet}'!{res_col}{row_num}", "values": [[sheet_result_url]]},
            {"range": f"'{p_sheet}'!{reason_col}{row_num}", "values": [[reason]]},
            {"range": f"'{p_sheet}'!{ev_col}{row_num}", "values": [[evidence]]},
        ]
        sheets_service.spreadsheets().values().batchUpdate(
            spreadsheetId=state["spreadsheet_id"],
            body={"valueInputOption": "USER_ENTERED", "data": batch_vals},
        ).execute()

        # 写后整行回读校验 (包含尝试次数严格校验)
        rb = sheets_service.spreadsheets().values().get(
            spreadsheetId=state["spreadsheet_id"],
            range=f"'{p_sheet}'!A{row_num}:J{row_num}",
        ).execute()
        rb_vals = rb.get("values", [[]])[0]
        rb_proj = rb_vals[PROJECT_HEADER.index("项目ID")].strip() if len(rb_vals) > PROJECT_HEADER.index("项目ID") else ""
        rb_bid = canonical_domain(rb_vals[PROJECT_HEADER.index("外链ID")]) if len(rb_vals) > PROJECT_HEADER.index("外链ID") else ""
        rb_status = rb_vals[PROJECT_HEADER.index("状态")].strip() if len(rb_vals) > PROJECT_HEADER.index("状态") else ""
        rb_attempt = rb_vals[PROJECT_HEADER.index("尝试次数")].strip() if len(rb_vals) > PROJECT_HEADER.index("尝试次数") else ""
        if rb_proj != proj or rb_bid != cid or rb_status != status or rb_attempt != str(final_attempt):
            raise RuntimeError(
                f"落表回读校验失败: 期望 ({proj}, {cid}, {status!r}, 尝试次数={final_attempt}), 实际读到 ({rb_proj}, {rb_bid}, {rb_status!r}, 尝试次数={rb_attempt})"
            )
    else:
        # 非正式落表模式下：若提供了 project_rows 且明确无执行尝试记为成功，拦截凭空提交 (落实 F1 规范)
        if project_rows is not None and final_attempt == 0 and status in SUCCESS_STATUSES:
            raise RuntimeError(
                f"候选条目 [{cid}] 未经 start-attempt 启动真实执行尝试且历史尝试次数为 0，严禁无凭据记录为成功/审核中"
            )

    if target_prow:
        target_prow["状态"] = status
        target_prow["尝试次数"] = str(final_attempt)
        target_prow["最近操作时间"] = iso_now
        target_prow["结果链接"] = sheet_result_url
        target_prow["原因/备注"] = reason
        target_prow["证据摘要"] = str(evidence or "")

    # 清理活跃尝试记录
    if (state.get("active_attempt") or {}).get("backlink_id") == cid:
        state.pop("active_attempt", None)

    # 3. 判定是否为“新增成功提交” (落实 R9 修复：人工恢复首次成功正常计入)
    is_new_success = False
    if status in SUCCESS_STATUSES:
        if is_existing_prior_submit:
            is_new_success = False
        else:
            prev_completed = state.get("completed_items", {}).get(cid)
            if prev_completed and prev_completed.get("is_new_success"):
                is_new_success = False
            else:
                is_new_success = True

    # 4. 更新明细记录与人工交接文件联动 (复用 save_human_pending / resolve_human_pending，落实 F2 规范)
    save_hp_func, resolve_hp_func, _ = _get_human_pending_tools()
    autofill_runtime = Path(os.environ.get("BACKLINK_AUTOFILL_RUNTIME") or (Path(runtime_dir) / "autofill" if runtime_dir else os.path.expanduser("~/.backlink-autofill/runtime")))

    if status == "需人工":
        curr_url = str(result_url or "").strip()
        clean_tid = str(target_id).strip() if target_id and str(target_id).strip().lower() not in ("", "none", "null") else None
        live_ok, live_err = verify_cdp_live_target(clean_tid, expected_url=curr_url)
        has_live_target = live_ok
        checkpoint_ref = None if has_live_target else "needs_rebuild"

        instruction_text = (
            f"遇到真阻碍（验证码/2FA/Cloudflare盾）。可见浏览器标签页已保留挂起 (Target ID: {clean_tid or '未知'})，请人工介入处理后使用 --resume-same-attempt 恢复提交。"
            if has_live_target else
            f"遇到真阻碍（验证码/2FA/Cloudflare盾）。现场标签页未连接或已断开 (Target ID: {clean_tid or '未知'}，标记 needs_rebuild，现场待重建)。请在可见浏览器中重新打开该页面并人工解决阻碍后，使用 --resume-same-attempt 恢复提交。"
        )

        state["human_pending_items"][cid] = {
            "domain": cid,
            "status": "需人工",
            "reason": reason,
            "evidence": evidence,
            "target_id": clean_tid,
            "timestamp": iso_now,
            "live_tab_available": has_live_target,
            "checkpoint_ref": checkpoint_ref,
        }
        if cid in state.get("completed_items", {}):
            del state["completed_items"][cid]

        # 联动 backlink-autofill 持久化 human-pending JSON 文件
        try:
            extra_info = {
                "evidence": str(evidence or ""),
                "live_tab_available": has_live_target,
                "handover_instruction": instruction_text,
            }
            if save_hp_func:
                save_hp_func(
                    runtime_root=autofill_runtime,
                    project_id=proj,
                    backlink_id=cid,
                    domain=cid,
                    blocker_type=reason or "需人工介入",
                    current_url=curr_url,
                    target_id=clean_tid,
                    checkpoint_ref=checkpoint_ref,
                    extra=extra_info,
                )
            else:
                hp_dir = autofill_runtime / "human-pending" / proj
                hp_dir.mkdir(parents=True, exist_ok=True)
                hp_file = hp_dir / f"{cid}.json"
                hp_payload = {
                    "schema_version": 1,
                    "project_id": proj,
                    "backlink_id": cid,
                    "domain": cid,
                    "blocker_type": reason or "需人工介入",
                    "current_url": curr_url,
                    "target_id": clean_tid,
                    "checkpoint_ref": checkpoint_ref,
                    "status": "NEEDS_HUMAN",
                    "created_at": datetime.datetime.now(datetime.timezone.utc).timestamp(),
                    "extra": extra_info,
                }
                tmp_hp = hp_file.with_suffix(f".tmp.{os.getpid()}")
                tmp_hp.write_text(json.dumps(hp_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(tmp_hp, hp_file)
        except Exception as hp_exc:
            print(f"⚠️ [human-pending] 写入交接文件失败 [{cid}]: {hp_exc}")

        # 输出明确的操作指引并继续处理
        print(f"\n🛑 [人工介入挂起] 平台: {cid} | 阻碍: {reason}")
        if has_live_target:
            print(f"👉 现场状态: 真实标签页保持开启 (CDP Target ID: {clean_tid})")
            print(f"👉 指引: 标签页已保留可见，请在浏览器中直接完成人工处理，解决后执行:\n   python3 scripts/run_submission_cycle.py start-attempt --project-id {proj} --backlink-id {cid} --resume-same-attempt 继续提交")
        else:
            print(f"👉 现场状态: 标签页未连接或已关闭 (Target ID: {clean_tid or '未知'}，标记 needs_rebuild，现场待重建)")
            print(f"👉 指引: 现场因故丢失，恢复前请在浏览器中重新打开 {curr_url or '提交入口'} 并解决阻碍，然后执行:\n   python3 scripts/run_submission_cycle.py start-attempt --project-id {proj} --backlink-id {cid} --resume-same-attempt 继续提交")
        print("⏩ 调度器将自动继续推进本批次剩余候选项...\n")
    else:
        if cid in state.get("human_pending_items", {}):
            del state["human_pending_items"][cid]

        # 终态：已提交、审核中、失败、不适用，解决对应待办
        try:
            if resolve_hp_func:
                resolve_hp_func(
                    runtime_root=autofill_runtime,
                    project_id=proj,
                    backlink_id=cid,
                    terminal_status=status,
                )
            else:
                hp_file = autofill_runtime / "human-pending" / proj / f"{cid}.json"
                if hp_file.exists():
                    hp_file.unlink()
        except Exception:
            pass

        prev_completed = state.get("completed_items", {}).get(cid)
        item_is_new_succ = is_new_success or (prev_completed and prev_completed.get("is_new_success", False))

        state["completed_items"][cid] = {
            "domain": cid,
            "status": status,
            "reason": reason,
            "evidence": evidence,
            "result_url": result_url,
            "is_new_success": bool(item_is_new_succ),
            "is_existing_prior": bool(is_existing_prior_submit),
            "timestamp": iso_now,
        }

    # 确保加入已处理集合 (R7)
    if cid not in state.setdefault("processed_candidate_bids", []):
        state["processed_candidate_bids"].append(cid)
    if cid not in state.setdefault("scanned_candidate_bids", []):
        state["scanned_candidate_bids"].append(cid)
    if status in SUCCESS_STATUSES or status in {"失败", "不适用"}:
        pending_ready = state.setdefault("pending_ready_delivery_bids", [])
        if cid in pending_ready:
            pending_ready.remove(cid)

    # 5. 重新计算各独立互斥分类计数 (落实 R9 修复：引入 prior_existing_count 与严密互斥对账)
    new_succeeded = sum(1 for item in state["completed_items"].values() if item.get("is_new_success"))
    prior_existing = sum(1 for item in state["completed_items"].values() if item.get("is_existing_prior"))
    not_app = sum(1 for item in state["completed_items"].values() if item.get("status") == "不适用")
    failed = sum(1 for item in state["completed_items"].values() if item.get("status") == "失败")
    hp = len(state["human_pending_items"])

    # still_to_submit 为快照中既不在 completed_items 也不在 human_pending_items 的项数
    still_bids = [
        b for b in state["snapshot_candidate_bids"]
        if b not in state["completed_items"] and b not in state["human_pending_items"]
    ]
    still_to_submit = len(still_bids)

    state["newly_succeeded_count"] = new_succeeded
    state["prior_existing_count"] = prior_existing
    state["not_applicable_count"] = not_app
    state["failed_count"] = failed
    state["human_pending_count"] = hp
    state["still_to_submit_count"] = still_to_submit

    audit_sum = new_succeeded + prior_existing + not_app + failed + hp + still_to_submit
    is_balanced = (audit_sum == state["snapshot_total_count"])
    state["is_balanced"] = is_balanced

    # 6. 写入 Master Sheet 并回读核验 (落实 S3 写前身份核验与安全重定位)
    sync_result = None
    master_sync_status = "ok"

    if proposed_master_updates:
        if target_mrow:
            for k, v in proposed_master_updates.items():
                target_mrow[k] = v

        if commit and sheets_service:
            try:
                m_row_num = target_mrow.get("_sheet_row_num") if target_mrow else None
                m_sheet = state["master_sheet"]

                # 写前单行身份核验，防止行移位误改他人数据 (落实 S3 修复)
                target_valid_row = None
                if m_row_num:
                    try:
                        pre_rb = sheets_service.spreadsheets().values().get(
                            spreadsheetId=state["spreadsheet_id"],
                            range=f"'{m_sheet}'!A{m_row_num}:B{m_row_num}",
                        ).execute()
                        cur_vals = pre_rb.get("values", [[]])[0]
                        cur_bid = canonical_domain(cur_vals[0]) if len(cur_vals) > 0 and cur_vals[0] else ""
                        if cur_bid == cid:
                            target_valid_row = m_row_num
                    except Exception:
                        target_valid_row = None

                # 若行号未匹配或已移位，整列扫描重新定位
                if not target_valid_row:
                    col_rb = sheets_service.spreadsheets().values().get(
                        spreadsheetId=state["spreadsheet_id"],
                        range=f"'{m_sheet}'!A1:A20000",
                    ).execute()
                    for idx, rv in enumerate(col_rb.get("values", []), 1):
                        if rv and canonical_domain(rv[0]) == cid:
                            target_valid_row = idx
                            if target_mrow:
                                target_mrow["_sheet_row_num"] = idx
                            break

                if not target_valid_row:
                    raise RuntimeError(f"Master 表未找到域名 [{cid}] 的目标行，拒绝盲写")

                m_row_num = target_valid_row

                # 构造更新 payload
                m_updates = []
                for f_name, f_val in proposed_master_updates.items():
                    if f_name in MASTER_HEADER:
                        c_letter = col_index_to_letter(MASTER_HEADER.index(f_name))
                        m_updates.append({
                            "range": f"'{m_sheet}'!{c_letter}{m_row_num}",
                            "values": [[str(f_val if f_val is not None else "")]]
                        })

                sheets_service.spreadsheets().values().batchUpdate(
                    spreadsheetId=state["spreadsheet_id"],
                    body={"valueInputOption": "USER_ENTERED", "data": m_updates},
                ).execute()

                # 写后全字段严格回读核验
                post_rb = sheets_service.spreadsheets().values().get(
                    spreadsheetId=state["spreadsheet_id"],
                    range=f"'{m_sheet}'!A{m_row_num}:N{m_row_num}",
                ).execute()
                post_vals = post_rb.get("values", [[]])[0]
                act_bid = canonical_domain(post_vals[MASTER_HEADER.index("外链ID")]) if len(post_vals) > MASTER_HEADER.index("外链ID") else ""
                if act_bid != cid:
                    raise RuntimeError(f"Master 表回读身份不一致: 期望 {cid}, 实际读到 {act_bid}")

                for f_name, f_val in proposed_master_updates.items():
                    if f_name not in MASTER_HEADER:
                        continue
                    f_idx = MASTER_HEADER.index(f_name)
                    act_val = post_vals[f_idx].strip() if len(post_vals) > f_idx else ""
                    exp_val = str(f_val if f_val is not None else "").strip()
                    if f_name == "最后验证时间" and exp_val:
                        if not are_equivalent_timestamps(act_val, exp_val):
                            raise RuntimeError(f"Master 表回读时间不一致: 期望 {exp_val}, 实际 {act_val}")
                    elif act_val != exp_val:
                        raise RuntimeError(f"Master 表回读字段 {f_name} 不一致: 期望 {exp_val!r}, 实际 {act_val!r}")

            except Exception as m_write_err:
                print(f"⚠️ [同步待恢复] Master 表写入失败或回读不一致 [{cid}]: {m_write_err}", file=sys.stderr)
                master_sync_status = "pending_recovery"
                # 保存至全局 pending_master_mutations
                pending_mutation = {
                    "domain": cid,
                    "row_num": target_mrow.get("_sheet_row_num") if target_mrow else None,
                    "project_id": proj,
                    "fields": proposed_master_updates,
                    "expected_val": proposed_master_updates.get("提交入口") or proposed_master_updates.get("实测限制"),
                    "created_at": iso_now,
                    "error": str(m_write_err),
                }
                cur_pending = load_pending_master_mutations(proj, runtime_dir)
                cur_pending.append(pending_mutation)
                save_pending_master_mutations(proj, cur_pending, runtime_dir)

    exclusion_scope = classify_exclusion(m_status, m_reason, m_limits, m_free)
    if exclusion_scope == ExclusionScope.GLOBAL_UNAVAILABLE and master_rows and project_rows:
        sync_plan = sync_global_exclusions_across_projects(
            master_rows=master_rows,
            project_rows=project_rows,
            target_backlink_ids=[cid],
            now_iso=iso_now,
            exclude_project_id=proj,
        )
        if sync_plan["mutated_count"] > 0:
            if commit and sheets_service:
                sync_exec = execute_cross_project_sync_mutations(
                    sheets_service=sheets_service,
                    spreadsheet_id=state["spreadsheet_id"],
                    project_sheet_name=state["project_sheet"],
                    project_header=PROJECT_HEADER,
                    planned_mutations=sync_plan["planned_mutations"],
                    commit=True,
                    runtime_dir=runtime_dir,
                )
                sync_result = {
                    "planned": sync_plan["mutated_count"],
                    "committed": sync_exec["committed_count"],
                    "failed": sync_exec["failed_count"],
                    "affected_projects": sync_plan["affected_projects"],
                }
            else:
                sync_result = {
                    "planned": sync_plan["mutated_count"],
                    "status": "dry_run",
                    "affected_projects": sync_plan["affected_projects"],
                }
            state.setdefault("cross_project_sync_history", []).append({
                "backlink_id": cid,
                "timestamp": iso_now,
                "sync_result": sync_result,
            })

    # 7. 检查活动批次推进
    active = state.get("active_batch")
    if active and active.get("ready_domains"):
        all_done = all(
            d in state["completed_items"] or d in state["human_pending_items"]
            for d in active["ready_domains"]
        )
        if all_done:
            state["active_batch"] = None

    # 8. 检查总停止条件 (落实 R9 修复：失衡时绝对禁止标记完成，返回 ok=False)
    if not is_balanced:
        state["is_finished"] = False
        state["finish_reason"] = f"账目失衡 (UNBALANCED: 快照总数 {state['snapshot_total_count']} != 各分类之和 {audit_sum})，禁止标记完成"
    elif state["newly_succeeded_count"] >= state["target_success"]:
        state["is_finished"] = True
        state["finish_reason"] = f"达到目标新增成功数: {state['newly_succeeded_count']} >= {state['target_success']}"
    elif (
        len(
            set(state.get("scanned_candidate_bids", []))
            | set(state.get("processed_candidate_bids", []))
        ) >= state["snapshot_total_count"]
        and state["active_batch"] is None
        and not state.get("pending_ready_delivery_bids")
        and not (
            (review_round := _review_round_for_state(state))
            and review_round.get("status") == "ACTIVE"
        )
    ):
        state["is_finished"] = True
        state["finish_reason"] = f"本轮候选快照已扫描一轮耗尽 (覆盖全部 {state['snapshot_total_count']} 个候选)"

    save_cycle_state(proj, state, runtime_dir)

    return {
        "ok": is_balanced,
        "is_balanced": is_balanced,
        "backlink_id": cid,
        "attempts": final_attempt,
        "is_new_success": is_new_success,
        "newly_succeeded_count": state["newly_succeeded_count"],
        "prior_existing_count": state["prior_existing_count"],
        "target_success": state["target_success"],
        "human_pending_count": state["human_pending_count"],
        "master_sync_status": master_sync_status,
        "master_updates": proposed_master_updates,
        "cross_project_sync": sync_result,
        "is_finished": state["is_finished"],
        "finish_reason": state.get("finish_reason"),
        "state": state,
    }


def print_cycle_summary(state: dict[str, Any]) -> bool:
    snap_total = state["snapshot_total_count"]
    succ = state["newly_succeeded_count"]
    prior = state.get("prior_existing_count", 0)
    not_app = state["not_applicable_count"]
    failed = state["failed_count"]
    hp = state["human_pending_count"]
    still = state["still_to_submit_count"]

    # 1. 业务处置终态大账守恒
    audit_sum = succ + prior + not_app + failed + hp + still
    is_balanced = (audit_sum == snap_total)

    # 2. 待提交（未处置总量 still）完整四原子子项划分 (落实用户修正 6 / F7)
    # 集合：未扫描 + 已扫描未解决 + Ready 等待执行 + 处理中 (In-Flight)
    completed_bids = set(state.get("completed_items", {}).keys())
    hp_bids = set(state.get("human_pending_items", {}).keys())
    snapshot_bids = set(state.get("snapshot_candidate_bids") or state.get("initial_candidate_snapshot") or [])
    processed_bids = set(state.get("processed_candidate_bids", []))
    processed_bids.update(state.get("scanned_candidate_bids", []))
    pending_ready_bids = {
        canonical_domain(bid)
        for bid in state.get("pending_ready_delivery_bids", [])
        if canonical_domain(bid)
    }

    active_batch = state.get("active_batch") or {}
    active_ready_domains = set(
        active_batch.get("ready_domains")
        or [r.get("domain") for r in active_batch.get("ready_items", []) if isinstance(r, dict)]
        or []
    )
    in_flight_bids = set(active_batch.get("in_flight_bids", [])) if active_batch.get("in_flight") else set()
    if active_batch.get("in_flight_bid"):
        in_flight_bids.add(canonical_domain(active_batch.get("in_flight_bid")))
    active_attempt = state.get("active_attempt")
    if active_attempt and active_attempt.get("backlink_id"):
        in_flight_bids.add(canonical_domain(active_attempt["backlink_id"]))

    # 属于当前快照且尚未处置的真实待提交集合
    snapshot_to_submit = {b for b in snapshot_bids if b not in completed_bids and b not in hp_bids}

    # 四子项互斥分解：
    ready_waiting = {
        b for b in snapshot_to_submit
        if (b in active_ready_domains or b in pending_ready_bids)
        and b not in in_flight_bids
    }
    in_flight = {b for b in snapshot_to_submit if b in in_flight_bids}
    scanned_unresolved = {
        b for b in snapshot_to_submit
        if b in processed_bids and b not in ready_waiting and b not in in_flight
    }
    unscanned_to_submit = {
        b for b in snapshot_to_submit
        if b not in processed_bids and b not in ready_waiting and b not in in_flight
    }

    ready_waiting_cnt = len(ready_waiting)
    in_flight_cnt = len(in_flight)
    unresolved_scanned_cnt = len(scanned_unresolved)
    unscanned_cnt = len(unscanned_to_submit)

    # 子项求和校验
    sub_sum = ready_waiting_cnt + in_flight_cnt + unresolved_scanned_cnt + unscanned_cnt
    is_sub_balanced = (sub_sum == still)

    # 3. 扫描覆盖作为独立只读度量维度
    scanned_cnt = len(processed_bids)
    snap_unscanned_cnt = max(0, snap_total - scanned_cnt)
    coverage_pct = (scanned_cnt / snap_total * 100) if snap_total > 0 else 0.0

    print("\n==================================================")
    print(f"BacklinkOS 提交循环对账总结 [{state['project_id']}]")
    print("==================================================")
    print(f"目标新增成功提交数:  {state['target_success']}")
    print(f"责任候选快照总数:    {snap_total}")
    print("--------------------------------------------------")
    print("【业务处置终态对账 (互斥独立)】")
    print(f"  ✅ 本轮新增成功提交: {succ}")
    print(f"  ℹ️  查重既往已有提交: {prior}")
    print(f"  ⚠️  确认不适用 (限制): {not_app}")
    print(f"  ❌ 确认失败 (死站):   {failed}")
    print(f"  ⏸️  待人工处理 (挂起): {hp}")
    print(f"  ⏳ 保持待提交 (未处置): {still}")
    print(f"     ├─ Ready 等待执行: {ready_waiting_cnt}")
    print(f"     ├─ 处理中 (In-Flight): {in_flight_cnt}")
    print(f"     ├─ 已扫描但未解决 (超时/无入口，保留待调度): {unresolved_scanned_cnt}")
    print(f"     └─ 尚未扫描候选: {unscanned_cnt}")
    print("--------------------------------------------------")
    balance_flag = "对账一致 (BALANCED)" if (is_balanced and is_sub_balanced) else "⚠️ 账目差异 (UNBALANCED)"
    print(f"业务对账校验: {snap_total} == ({succ} + {prior} + {not_app} + {failed} + {hp} + {still}) -> {balance_flag}")
    print(f"待提交子项校验: {still} == ({ready_waiting_cnt} + {in_flight_cnt} + {unresolved_scanned_cnt} + {unscanned_cnt}) -> {'子项平衡' if is_sub_balanced else '子项失衡'}")
    print("--------------------------------------------------")
    print("【探测扫描覆盖度量 (只读统计)】")
    print(f"  本轮扫描覆盖: {scanned_cnt}/{snap_total} ({coverage_pct:.1f}%) | 全局剩余未扫: {snap_unscanned_cnt}")
    review_round = _review_round_for_state(state)
    if review_round:
        dispatched = review_round.get("dispatches", {})
        print(
            "  未解决复核轮: "
            f"{review_round.get('round_id')} | {review_round.get('status')} | "
            f"固定清单 {len(review_round.get('candidate_ids', []))} | "
            f"已派发 {len(dispatched)} | "
            f"已观察 {len(review_round.get('observations', {}))} | "
            f"未知恢复 {len(review_round.get('unknown_recovery_ids', []))}"
        )
    print("--------------------------------------------------")
    if not is_balanced:
        print(f"[严重错误] 账目失衡: 快照总数 {snap_total} != 各分类之和 {audit_sum}", file=sys.stderr)
    if not is_sub_balanced:
        print(f"[严重错误] 待提交子项失衡: 待提交总数 {still} != 四子项之和 {sub_sum}", file=sys.stderr)
    if state.get("is_finished"):
        print(f"🏁 循环结束原因: {state.get('finish_reason')}")
    if state.get("interruption_reason"):
        print(f"⏸️  上一次中断/暂停原因: {state.get('interruption_reason')}")
    if hp > 0:
        print(f"\n[待人工处理项列表 (共 {hp} 项，标签页已保留)]:")
        for idx, (bid, item) in enumerate(state["human_pending_items"].items(), 1):
            print(f"  {idx}. {bid} | 阻碍类型: {item.get('reason')} | 标签页ID: {item.get('target_id')}")
    print("==================================================\n")
    return is_balanced and is_sub_balanced


def build_parser() -> argparse.ArgumentParser:
    """构建支持统一顶层调用与子命令兼容的 CLI 解析器 (落实 R1 修复)。"""
    parser = argparse.ArgumentParser(
        description="BacklinkOS Formal Submission Cycle Orchestrator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--project-id", help="Target project ID (e.g. quick-iching)")
    parser.add_argument("--target-success", type=int, default=200, help="Target new successful submissions count")
    parser.add_argument("--batch-ready-target", type=int, default=10, help="Target ready items per batch")
    parser.add_argument("--batch-scan-limit", type=int, default=50, help="Max candidates scanned per batch")
    parser.add_argument("--concurrency", type=int, default=2, choices=[1, 2, 4], help="Concurrency for Phase C read-only HTTP probing (default: 2, max: 4, fallback: 1)")
    parser.add_argument("--time-budget", type=float, default=300.0, help="Wall-clock time budget in seconds for this run (default: 300s)")
    parser.add_argument("--spreadsheet-id", default=os.environ.get("BACKLINK_SPREADSHEET_ID", "1uUmlPGzjxNe-XkvWfjuC3c5exiOxZuFJWvHqPTwjaTA"))
    parser.add_argument("--credentials-path", default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "~/.config/seo-sheets/service-account.json"))
    parser.add_argument("--master-sheet", default="外链总表")
    parser.add_argument("--project-sheet", default="外链管理")
    parser.add_argument("--dry-run", action="store_true", default=False)

    subparsers = parser.add_subparsers(dest="command")

    # start 子命令
    p_start = subparsers.add_parser("start", help="Start or resume a submission cycle")
    p_start.add_argument("--project-id", required=True)
    p_start.add_argument("--target-success", type=int, default=200)
    p_start.add_argument("--batch-ready-target", type=int, default=10)
    p_start.add_argument("--batch-scan-limit", type=int, default=50)
    p_start.add_argument("--concurrency", type=int, default=2, choices=[1, 2, 4], help="Concurrency for Phase C read-only HTTP probing (default: 2, max: 4, fallback: 1)")
    p_start.add_argument("--time-budget", type=float, default=300.0, help="Wall-clock time budget in seconds for this run (default: 300s)")
    p_start.add_argument("--spreadsheet-id", default=os.environ.get("BACKLINK_SPREADSHEET_ID", "1uUmlPGzjxNe-XkvWfjuC3c5exiOxZuFJWvHqPTwjaTA"))
    p_start.add_argument("--credentials-path", default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "~/.config/seo-sheets/service-account.json"))
    p_start.add_argument("--master-sheet", default="外链总表")
    p_start.add_argument("--project-sheet", default="外链管理")
    p_start.add_argument("--dry-run", action="store_true", default=False)

    # status 子命令
    p_status = subparsers.add_parser("status", help="Show current cycle status")
    p_status.add_argument("--project-id", required=True)

    # record-outcome 子命令
    p_rec = subparsers.add_parser("record-outcome", help="Record task outcome for a backlink candidate")
    p_rec.add_argument("--project-id", required=True)
    p_rec.add_argument("--backlink-id", required=True)
    p_rec.add_argument("--status", required=True, choices=["已提交", "审核中", "已排期", "已上线", "需人工", "失败", "不适用"])
    p_rec.add_argument("--reason", default="")
    p_rec.add_argument("--evidence", default="")
    p_rec.add_argument("--result-url", default="")
    p_rec.add_argument("--is-existing-prior-submit", action="store_true", default=False)
    p_rec.add_argument("--is-resume-attempt", action="store_true", default=False)
    p_rec.add_argument("--target-id")
    p_rec.add_argument("--platform-facts", default="", help="JSON string or dict of verified platform facts (entry_url, negated_entries, free, requires_login, login_method, limits, link_rel, observed_at, notes, master_status)")
    p_rec.add_argument("--credentials-path", default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "~/.config/seo-sheets/service-account.json"))
    p_rec.add_argument("--dry-run", action="store_true", default=False)

    # start-attempt 子命令 (落实执行动作规范：开始一次有效尝试时原子进入处理中并增加尝试次数)
    p_att = subparsers.add_parser("start-attempt", help="Start an execution attempt for a candidate, entering IN_PROGRESS and advancing attempt count")
    p_att.add_argument("--project-id", required=True)
    p_att.add_argument("--backlink-id", required=True)
    p_att.add_argument("--resume-same-attempt", action="store_true", default=False, help="Resume execution for proven unsubmitted attempt without advancing attempt count")
    p_att.add_argument("--credentials-path", default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "~/.config/seo-sheets/service-account.json"))
    p_att.add_argument("--dry-run", action="store_true", default=False)

    # record-interruption 子命令 (落实 F6 规范：记录中断/暂停原因)
    p_int = subparsers.add_parser("record-interruption", help="Record interruption or pause reason for a cycle")
    p_int.add_argument("--project-id", required=True)
    p_int.add_argument("--reason", required=True, help="Interruption reason description")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cmd = args.command
    if not cmd:
        if args.project_id:
            cmd = "start"
        else:
            parser.print_help()
            return 1

    if cmd == "status":
        state = load_cycle_state(args.project_id)
        if not state:
            print(f"未找到项目 {args.project_id!r} 的活跃提交循环记录。")
            return 0
        balanced = print_cycle_summary(state)
        return 0 if balanced else 3

    if cmd == "record-interruption":
        try:
            res = record_cycle_interruption(args.project_id, args.reason)
            print(json.dumps(res, ensure_ascii=False, indent=2))
            return 0
        except Exception as e:
            print(f"错误: 记录中断原因失败: {e}", file=sys.stderr)
            return 2

    if cmd == "start-attempt":
        state = load_cycle_state(args.project_id)
        if not state:
            print(f"错误: 未找到项目 {args.project_id!r} 的提交循环记录，请先运行 start 初始化。", file=sys.stderr)
            return 2

        service = None
        m_rows = None
        p_rows = None
        if not args.dry_run:
            cred_file = os.path.expanduser(args.credentials_path)
            if not os.path.exists(cred_file):
                print(f"错误: 正式写回需要有效的 Google Sheets API 凭据，文件不存在: {cred_file}", file=sys.stderr)
                return 2
            try:
                service = get_sheets_service(args.credentials_path)
                m_rows = read_all_master_rows(service, state["spreadsheet_id"], state["master_sheet"])
                p_rows = read_all_project_rows(service, state["spreadsheet_id"], state["project_sheet"])
            except Exception as exc:
                print(f"错误: 连接 Google Sheets API 失败: {exc}", file=sys.stderr)
                return 2
        else:
            try:
                service = get_sheets_service(args.credentials_path)
                m_rows = read_all_master_rows(service, state["spreadsheet_id"], state["master_sheet"])
                p_rows = read_all_project_rows(service, state["spreadsheet_id"], state["project_sheet"])
            except Exception:
                pass

        try:
            att_res = start_task_attempt(
                state=state,
                backlink_id=args.backlink_id,
                is_resume_attempt=args.resume_same_attempt,
                project_rows=p_rows,
                master_rows=m_rows,
                sheets_service=service,
                commit=not args.dry_run,
            )
            print(json.dumps(att_res, ensure_ascii=False, indent=2))
            return 0
        except Exception as err:
            print(f"错误: 启动执行尝试失败: {err}", file=sys.stderr)
            return 2

    if cmd == "record-outcome":
        state = load_cycle_state(args.project_id)
        if not state:
            print(f"错误: 未找到项目 {args.project_id!r} 的提交循环记录，请先运行 start 初始化。", file=sys.stderr)
            return 2

        service = None
        m_rows = None
        p_rows = None

        if not args.dry_run:
            cred_file = os.path.expanduser(args.credentials_path)
            if not os.path.exists(cred_file):
                print(f"错误: 正式写回需要有效的 Google Sheets API 凭据，文件不存在: {cred_file}", file=sys.stderr)
                return 2
            try:
                service = get_sheets_service(args.credentials_path)
                m_raw = fetch_all_sheet_rows(service, state["spreadsheet_id"], state["master_sheet"])
                p_raw = fetch_all_sheet_rows(service, state["spreadsheet_id"], state["project_sheet"])
                if m_raw and len(m_raw) > 1:
                    m_rows = [dict(zip(MASTER_HEADER, r)) for r in m_raw[1:] if r]
                    for idx, r in enumerate(m_rows, 2):
                        r["_sheet_row_num"] = idx
                if p_raw and len(p_raw) > 1:
                    p_rows = [dict(zip(PROJECT_HEADER, r)) for r in p_raw[1:] if r]
                    for idx, r in enumerate(p_rows, 2):
                        r["_sheet_row_num"] = idx
            except Exception as exc:
                print(f"错误: 连接 Google Sheets API 失败: {exc}", file=sys.stderr)
                return 2
        else:
            try:
                service = get_sheets_service(args.credentials_path)
                m_raw = fetch_all_sheet_rows(service, state["spreadsheet_id"], state["master_sheet"])
                p_raw = fetch_all_sheet_rows(service, state["spreadsheet_id"], state["project_sheet"])
                if m_raw and len(m_raw) > 1:
                    m_rows = [dict(zip(MASTER_HEADER, r)) for r in m_raw[1:] if r]
                    for idx, r in enumerate(m_rows, 2):
                        r["_sheet_row_num"] = idx
                if p_raw and len(p_raw) > 1:
                    p_rows = [dict(zip(PROJECT_HEADER, r)) for r in p_raw[1:] if r]
                    for idx, r in enumerate(p_rows, 2):
                        r["_sheet_row_num"] = idx
            except Exception:
                pass

        try:
            rec_res = record_task_outcome(
                state=state,
                backlink_id=args.backlink_id,
                status=args.status,
                reason=args.reason,
                evidence=args.evidence,
                result_url=args.result_url,
                is_existing_prior_submit=args.is_existing_prior_submit,
                is_resume_attempt=args.is_resume_attempt,
                target_id=args.target_id,
                platform_facts=getattr(args, "platform_facts", None),
                master_rows=m_rows,
                project_rows=p_rows,
                sheets_service=service,
                commit=not args.dry_run,
            )
            print(json.dumps(rec_res, ensure_ascii=False, indent=2))
            # 严格守卫：若账目失衡，绝不以 0 退出，向 stderr 报错并返回退出码 3 (落实 R9 修复)
            if not rec_res.get("ok") or not rec_res.get("is_balanced", True):
                print(f"[严重错误] 账目失衡: 禁止以成功状态退出，请排查账目 (UNBALANCED)", file=sys.stderr)
                return 3
            return 0
        except Exception as err:
            print(f"错误: 记录执行结果失败: {err}", file=sys.stderr)
            return 2

    if cmd == "start":
        state = load_cycle_state(args.project_id)

        # 检查是否已完成。若已完成且对账平衡，归档并重开新轮次 (落实 R8 与 R9 修复)
        inherited_hp = {}
        if state and state.get("is_finished"):
            # 严格守卫：失衡轮次绝不能作为已完成归档！(落实 R9 修复)
            if not state.get("is_balanced", True):
                print(f"[严重错误] 项目 {args.project_id!r} 当前处于账目失衡状态，禁止作为已完成轮次归档！请排查 state.json。", file=sys.stderr)
                return 3
            print(f"[*] 检测到项目 {args.project_id!r} 上一轮循环已完成 ({state.get('finish_reason')})，正在归档历史...")
            archived = archive_finished_cycle(args.project_id)
            if archived:
                print(f"[*] 历史循环已安全归档至: {archived}")
            inherited_hp = state.get("human_pending_items", {})
            state = None

        service = None
        try:
            service = get_sheets_service(args.credentials_path)
        except Exception as e:
            print(f"[提示] Google Sheets API 凭据不可用或未配置代理 ({e})，将在本地/无凭据模式下工作", file=sys.stderr)

        if not state:
            # 初始化全新 cycle：读取当前项目待提交快照
            print(f"[*] 初始化项目 {args.project_id!r} 的全新提交循环 (目标新增成功: {args.target_success})...")
            if not service:
                print("错误: 初始化新循环需要读取 Google Sheet 候选快照，但凭据不可用。", file=sys.stderr)
                return 2

            p_raw = fetch_all_sheet_rows(service, args.spreadsheet_id, args.project_sheet)
            if not p_raw or len(p_raw) < 2:
                print("错误: 未能在【外链管理】读取到有效行", file=sys.stderr)
                return 2

            p_head = p_raw[0]
            status_idx = p_head.index("状态")
            proj_idx = p_head.index("项目ID")
            bid_idx = p_head.index("外链ID")

            initial_candidates = []
            for r in p_raw[1:]:
                if len(r) > max(status_idx, proj_idx, bid_idx):
                    if r[proj_idx].strip() == args.project_id and r[status_idx].strip() == PROJECT_STATUS_TO_SUBMIT:
                        cid = canonical_domain(r[bid_idx])
                        if cid and cid not in initial_candidates:
                            initial_candidates.append(cid)

            print(f"[*] 锁定当前项目待提交候选快照: {len(initial_candidates)} 个 (以此为本轮最大范围)")
            state = init_cycle_state(
                project_id=args.project_id,
                target_success=args.target_success,
                initial_candidates=initial_candidates,
                spreadsheet_id=args.spreadsheet_id,
                master_sheet=args.master_sheet,
                project_sheet=args.project_sheet,
                inherited_human_pending=inherited_hp,
            )
        else:
            print(f"[*] 恢复项目 {args.project_id!r} 的已有提交循环 (当前累计成功: {state['newly_succeeded_count']}/{state['target_success']})...")
            if args.target_success and args.target_success > state.get("target_success", 0):
                print(f"[*] 更新目标新增成功数: {state['target_success']} -> {args.target_success}")
                state["target_success"] = args.target_success
                save_cycle_state(args.project_id, state)

        # 1. 启动提交流程前优先恢复遗留 Master 变更，确保拉取到的是最新落表数据 (落实 S4 修复)
        if service and not args.dry_run:
            try:
                recover_pending_master_mutations(
                    sheets_service=service,
                    spreadsheet_id=state["spreadsheet_id"],
                    master_sheet_name=state["master_sheet"],
                    project_id=args.project_id,
                )
            except Exception as me:
                print(f"[提示] 启动前自动恢复 Master 变更跳过: {me}", file=sys.stderr)

        # 2. 读取最新的 master 与 project 表
        m_raw = fetch_all_sheet_rows(service, state["spreadsheet_id"], state["master_sheet"]) if service else []
        p_raw = fetch_all_sheet_rows(service, state["spreadsheet_id"], state["project_sheet"]) if service else []

        m_rows = []
        p_rows = []
        if m_raw and len(m_raw) > 1:
            for idx, r in enumerate(m_raw[1:], 2):
                d = dict(zip(MASTER_HEADER, r))
                d["_sheet_row_num"] = idx
                m_rows.append(d)
        if p_raw and len(p_raw) > 1:
            for idx, r in enumerate(p_raw[1:], 2):
                d = dict(zip(PROJECT_HEADER, r))
                d["_sheet_row_num"] = idx
                p_rows.append(d)

        proj_ctx = resolve_project_context(args.project_id)
        run_start_time = time.time()
        time_budget = getattr(args, "time_budget", 300.0)
        concurrency = getattr(args, "concurrency", 2)

        while True:
            # 检查全局运行时间预算 (落实用户约束 3)
            elapsed_run = time.time() - run_start_time
            remaining_budget = time_budget - elapsed_run
            if remaining_budget <= 0:
                print(f"\n[*] 达到本次运行时间预算 ({time_budget}s)，停止继续准备下一批，保存当前进度...")
                record_cycle_interruption(args.project_id, f"达到本次运行时间预算 ({time_budget}s)")
                balanced = print_cycle_summary(state)
                return 0 if balanced else 3

            plan = plan_next_batch(
                state=state,
                master_rows=m_rows,
                project_rows=p_rows,
                batch_ready_target=args.batch_ready_target,
                batch_scan_limit=args.batch_scan_limit,
                project_context=proj_ctx,
                commit_prep=not args.dry_run,
                sheets_service=service,
                concurrency=concurrency,
                time_budget=remaining_budget,
                # 正式入口采用现有 Phase C 的 min_ready_delivery 能力：
                # 达到 1 个 Ready 即交付当前小批，并停止派发新探测。
                min_ready_delivery=1,
            )

            action = plan["action"]
            if action == "STOP":
                balanced = print_cycle_summary(state)
                return 0 if balanced else 3

            if action in ("HALT", "HALT_WITH_PARTIAL_READY"):
                reason = plan.get("interruption_reason") or "本机执行资源阻塞 (LOCAL_RESOURCE_BLOCKED)"
                print(f"\n[!] 调度已中断停止: {reason}", file=sys.stderr)
                ready_items = plan.get("ready_items", [])
                if ready_items:
                    print(f"[*] 停止派发前已收集到部分 Ready 候选 ({len(ready_items)} 个)，已妥善保存可供执行提交：")
                    for idx, item in enumerate(ready_items, 1):
                        print(f"  {idx}. 域名: {item['domain']} | 提交入口: {item['submission_url']}")
                print_cycle_summary(state)
                # 返回状态码 1，明确标示因阻塞中断暂停，绝不当成正常完成
                return 1

            ready_items = plan.get("ready_items", [])
            batch_id = plan.get("batch_id")
            if ready_items:
                print(f"\n[+] 批次规划完成 [{batch_id}]: 共就绪 {len(ready_items)} 个可提交候选")
                print("请当前 AI 驱动 Playwright 浏览器逐项执行提交：")
                for idx, item in enumerate(ready_items, 1):
                    print(f"  {idx}. 域名: {item['domain']} | 提交入口: {item['submission_url']} | 目标URL: {item.get('target_url') or '默认'}")
                print("\n每完成一项，请调用 record-outcome 记录真实结果，完成后继续调用 start 获取下一批。")
                return 0
            else:
                # 普通启动轮的快照刚刚耗尽时，不能在同一进程中立即把同一
                # 清单再派发给未解决复核。这会让一个明确的 scan_limit 实际
                # 发生两轮探测。保留已落盘的扫描账本，并要求下一次显式
                # start 才创建有限复核轮；届时仍由复核轮自己的固定 ID、时间
                # 与数量边界控制。
                snapshot_ids = set(state.get("snapshot_candidate_bids", []))
                scanned_ids = set(state.get("scanned_candidate_bids", []))
                if (
                    snapshot_ids
                    and snapshot_ids.issubset(scanned_ids)
                    and not state.get("unresolved_review_rounds")
                ):
                    print(
                        "[*] 普通轮候选快照已扫描完且没有 Ready；"
                        "已保存未解决观察，有限复核将仅在下一次显式 start 时派发。"
                    )
                    balanced = print_cycle_summary(state)
                    return 0 if balanced else 3
                print(f"[*] 批次 [{batch_id}] 扫描未产出 Ready 候选，自动继续扫描下一批候选 (剩余预算: {max(0, int(remaining_budget))}s)...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
