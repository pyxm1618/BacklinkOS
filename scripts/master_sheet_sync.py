#!/usr/bin/env python3
"""BacklinkOS Master Sheet and Project Management Core Sync Module.

实现新的唯一控制面（@外链管理总控表）的核心业务契约：
1. canonical_domain: 域名规范化
2. Master Sheet Upsert: 平台级唯一事实库合并，绝对保护真实实测字段与已排除/失效状态，隔离写入权限
3. Submission Entry Policy Guard & Live Verification:
   复用 screening_crawler 已有能力，区分页面真实证据（Live Evidence）与规则守卫（Policy Guard），
   严禁仅凭 URL path 宣称入口，严禁 pricing/terms/category 等冒充入口，首页严格守卫。
4. Project Materialization: 仅在候选+有效入口+项目行不存在时生成“待提交”行，保证 project_id + backlink_id 唯一。
5. Bounded Batch Hydration: 严格有界（显式 limit），逐个核验，不为了凑数造假入口，未找到入口继续保留候选。
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

# 复用已有且经过全面测试的 screening_crawler 能力
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from screening_crawler import (
    AUTH_PATH_RE,
    COMMON_PATHS,
    ENTRY_HINTS,
    MECHANISM_PATTERNS,
    analyze_html,
    fetch_page,
)

# ==========================================
# 1. 契约常量与 Header 定义
# ==========================================

MASTER_HEADER = [
    "外链ID",
    "平台域名",
    "提交入口",
    "发现来源",
    "发现时间",
    "基础状态",
    "基础排除原因",
    "实测免费",
    "实测需登录",
    "实测登录方式",
    "实测限制",
    "实测链接属性",
    "最后验证时间",
    "平台备注",
]

# 基础状态枚举（仅允许这三种）
MASTER_STATUS_CANDIDATE = "候选"
MASTER_STATUS_EXCLUDED = "已排除"
MASTER_STATUS_DEAD = "失效"
VALID_MASTER_STATUSES = {
    MASTER_STATUS_CANDIDATE,
    MASTER_STATUS_EXCLUDED,
    MASTER_STATUS_DEAD,
}

# Discovery 严禁填写的实测事实字段（由 backlink-autofill 实际执行后填写）
PROTECTED_FACT_COLUMNS = [
    "实测免费",
    "实测需登录",
    "实测登录方式",
    "实测限制",
    "实测链接属性",
    "最后验证时间",
]

PROJECT_HEADER = [
    "项目ID",
    "外链ID",
    "外链域名",
    "状态",
    "尝试次数",
    "最近操作时间",
    "目标URL",
    "结果链接",
    "原因/备注",
    "证据摘要",
]

PROJECT_STATUS_TO_SUBMIT = "待提交"
VALID_PROJECT_STATUSES = {
    "待提交",
    "处理中",
    "已提交",
    "审核中",
    "已排期",
    "已上线",
    "需人工",
    "失败",
    "不适用",
}

# 提交入口 Policy Guard 排除规则：这些页面即便存在链接或返回 200，也绝不能冒充提交入口
INVALID_ENTRY_PATH_PATTERNS = [
    re.compile(r"/(pricing|plans|billing|checkout|cart|subscribe|buy|pricing-plans)(/|$)", re.I),
    re.compile(r"/(terms|privacy|tos|policy|disclaimer|legal|terms-of-service|privacy-policy)(/|$)", re.I),
    re.compile(r"/(category|categories|sub-category|tag|tags|topic|topics|archive|feed)(/|$)", re.I),
    re.compile(r"/(report|seo-report|audit|analyze|stats|analytics|uptime|whois)(/|$)", re.I),
    re.compile(r"/(sitemap|xmlrpc|feed|atom|rss)(/|$)", re.I),
]

# 首页作为入口的显式 CTA 正则守卫（首页必须在页面中有强烈的机制 CTA 才可作为起点）
HOMEPAGE_EXPLICIT_CTA_PATTERNS = [
    re.compile(r"\b(?:submit|add|list|register)\s+(?:your\s+)?(?:product|tool|startup|site|website|project|app)\b", re.I),
    re.compile(r"\b(?:create|sign\s*up\s+to\s+create)\s+(?:a\s+)?(?:profile|listing|account\s+to\s+list)\b", re.I),
    re.compile(r"\bjoin\s+and\s+submit\b", re.I),
]


# ==========================================
# 2. 核心域名规范化
# ==========================================

def canonical_domain(raw: str) -> str:
    """规范化平台域名与外链ID。
    
    规则：
    1. 剥离前后空格，统一小写；
    2. 若包含协议则解析 netloc/hostname；
    3. 剥离 www. 前缀；
    4. 剥离 trailing slash；
    5. path、query、fragment 绝不作为平台身份。
    """
    d = str(raw or "").strip().lower()
    if not d:
        return ""
    if "://" in d or d.startswith("//"):
        try:
            parsed = urlparse(d if "://" in d else "//" + d)
            d = (parsed.hostname or parsed.netloc or "").strip()
        except Exception:
            pass
    else:
        # 如果带 path，如 example.com/path
        if "/" in d:
            d = d.split("/")[0].strip()
    if ":" in d:
        d = d.split(":")[0].strip()
    if d.startswith("www."):
        d = d[4:]
    return d.rstrip(".")


# ==========================================
# 3. Submission Entry Policy Guard
# ==========================================

def submission_entry_policy_guard(url: str, domain: str = "") -> tuple[bool, str]:
    """对候选提交入口 URL 进行政策和语法层面的守卫检查（Guard）。
    
    注意：Guard 仅负责拦截明显错误的 URL，不能单独凭 Guard 宣称 URL 是真实验证的入口。
    
    返回: (is_allowed, reason)
    """
    u = str(url or "").strip()
    if not u:
        return False, "URL 为空"
    
    try:
        parsed = urlparse(u)
    except Exception as e:
        return False, f"URL 解析失败: {e}"
        
    if parsed.scheme not in ("http", "https"):
        return False, f"不受支持的协议: {parsed.scheme}"
        
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
        
    if domain:
        cd = canonical_domain(domain)
        if cd and host != cd and not host.endswith("." + cd):
            return False, f"跨域入口（平台 {cd} vs 链接 {host}），非同源不可代表平台"

    path = parsed.path or "/"
    # 检查是否命中明确的非提交页面（pricing、terms、category、seo report 等）
    for pattern in INVALID_ENTRY_PATH_PATTERNS:
        if pattern.search(path):
            return False, f"命中排除路径规则: {pattern.pattern}"

    return True, "通过 Policy Guard"


# ==========================================
# 4. Entry Discovery & Live Verification
# ==========================================

def verify_homepage_as_entry(home_result: dict) -> tuple[bool, str]:
    """检查首页是否有充分的页面证据作为提交入口起点。
    
    首页绝不能仅凭 URL 就当成入口；必须确认页面文案或 CTA 明确提示提交/创建 Profile。
    """
    text = (home_result.get("title", "") + " " + home_result.get("text_excerpt", "")).lower()
    for pat in HOMEPAGE_EXPLICIT_CTA_PATTERNS:
        if pat.search(text):
            return True, f"首页包含明确提交 CTA: {pat.pattern}"
    return False, "首页未包含明确的提交/收录/建链 CTA，不能拿首页填空"


def discover_and_verify_entry(
    domain: str,
    fetcher: Callable[[str], dict] | None = None,
    max_probes: int = 15,
) -> tuple[str | None, str]:
    """使用已有经过测试的爬虫机制，对指定域名进行真实页面探测，寻找最低限度提交入口。
    
    流程：
    1. 访问首页（裸域/www 双试，由 fetch_page/probe 处理）；
    2. 获取首页 candidate_urls（按 strong/weak 排序）与 COMMON_PATHS；
    3. 访问子页面，寻找包含真实 mechanism 信号、且非 noindex 的 200 页面；
    4. 对候选 URL 跑 submission_entry_policy_guard；
    5. 若找到真实子页面入口，返回 (entry_url, 成功理由)；
    6. 若只有首页且首页具备明确 CTA，返回 (home_url, 首页理由)；
    7. 否则返回 (None, 失败理由)，保持为空，绝不胡乱捏造。
    """
    cd = canonical_domain(domain)
    if not cd:
        return None, "域名无效"
        
    _fetch = fetcher or fetch_page
    
    # 尝试 https 和 http 首页
    home = None
    for scheme in ("https", "http"):
        res = _fetch(f"{scheme}://{cd}/")
        if res.get("status") == 200:
            home = res
            break
            
    if not home or home.get("status") != 200:
        # 尝试 www
        for scheme in ("https", "http"):
            res = _fetch(f"{scheme}://www.{cd}/")
            if res.get("status") == 200:
                home = res
                break
                
    if not home or home.get("status") != 200:
        return None, f"站点首页不可达 (HTTP {home.get('status') if home else 0})"
        
    if home.get("noindex"):
        return None, "首页标记 noindex"

    base_url = home.get("final_url") or f"https://{cd}/"
    candidate_urls = list(home.get("candidate_urls") or [])
    
    # 将 COMMON_PATHS 与 candidate_urls 合并，优先试探 candidate_urls，再试探常见路径
    probe_targets: list[str] = []
    for u in candidate_urls:
        if u not in probe_targets:
            probe_targets.append(u)
    for cp in COMMON_PATHS:
        u = urljoin(base_url, cp)
        if u not in probe_targets:
            probe_targets.append(u)

    # 限制探测数量
    probe_targets = probe_targets[:max_probes]
    
    # 逐个探测子页面
    for target_url in probe_targets:
        allowed, guard_reason = submission_entry_policy_guard(target_url, domain=cd)
        if not allowed:
            continue
            
        page_res = _fetch(target_url)
        if page_res.get("status") != 200:
            continue
        if page_res.get("noindex"):
            continue
            
        final_url = page_res.get("final_url") or target_url
        allowed_final, _ = submission_entry_policy_guard(final_url, domain=cd)
        if not allowed_final:
            continue
            
        # 机制判断：页面具有机制信号，或者路径本身属于 ENTRY_HINTS 且页面不是 404
        has_mech = bool(page_res.get("mechanism_signals"))
        is_entry_path = bool(ENTRY_HINTS.search(urlparse(final_url).path or ""))
        
        if has_mech or is_entry_path:
            return final_url, "通过真实页面探测闭环真实入口"
            
    # 如果所有子页面都没有发现，检查首页本身是否具备明确 CTA
    is_home_cta, home_reason = verify_homepage_as_entry(home)
    if is_home_cta:
        return base_url, home_reason
        
    return None, "未定位到用户可提交的入口页（证据缺失，保持候选状态）"


# ==========================================
# 5. Master Sheet Upsert 算法
# ==========================================

def build_empty_master_row(domain: str) -> dict[str, str]:
    cd = canonical_domain(domain)
    return {col: "" for col in MASTER_HEADER} | {
        "外链ID": cd,
        "平台域名": cd,
        "基础状态": MASTER_STATUS_CANDIDATE,
    }


def upsert_master_rows(
    existing_rows: list[dict[str, Any]],
    new_discoveries: list[dict[str, Any]],
    now_iso: str = "",
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """对外链总表实行 Upsert 合并。
    
    契约规则：
    1. 外链ID = canonical domain, 平台域名 = canonical domain；
    2. 若域名不存在：
       新增行：外链ID, 平台域名, 发现来源(本次真实来源), 发现时间(本次时间), 基础状态='候选'。
       实测 5 个字段（实测免费/实测需登录/实测登录方式/实测限制/实测链接属性）严格留空！
    3. 若域名已存在：
       不得重复添加；
       不得覆盖已有真实执行字段；
       不得将'已排除'或'失效'改回'候选'；
       仅补充安全的 provenance 信息（如原有发现来源为空时补充）。
    
    返回: (合并后的全部总表记录, 变更统计 dict)
    """
    stats = {
        "initial_count": len(existing_rows),
        "new_inserted": 0,
        "existing_updated": 0,
        "existing_preserved": 0,
        "skipped_excluded_or_dead": 0,
    }
    
    # 构建索引
    master_map: dict[str, dict[str, Any]] = {}
    master_order: list[str] = []
    
    for row in existing_rows:
        raw_id = row.get("外链ID") or row.get("平台域名") or ""
        cid = canonical_domain(raw_id)
        if not cid:
            continue
        # 确保包含所有列
        normalized_row = {col: str(row.get(col) or "").strip() for col in MASTER_HEADER}
        normalized_row["外链ID"] = cid
        normalized_row["平台域名"] = cid
        master_map[cid] = normalized_row
        master_order.append(cid)

    for item in new_discoveries:
        raw_d = item.get("referring_domain") or item.get("domain") or item.get("外链ID") or ""
        cid = canonical_domain(raw_d)
        if not cid:
            continue
            
        discovery_source = str(item.get("discovery_source") or item.get("发现来源") or "").strip()
        discovery_time = str(item.get("discovery_time") or item.get("发现时间") or now_iso).strip()
        
        # 提交入口：必须经过验证才能传入，否则为空
        submit_entry = str(item.get("submission_entry") or item.get("提交入口") or "").strip()
        if submit_entry:
            valid_entry, _ = submission_entry_policy_guard(submit_entry, domain=cid)
            if not valid_entry:
                submit_entry = ""
        
        if cid not in master_map:
            # 新增
            new_row = {col: "" for col in MASTER_HEADER}
            new_row["外链ID"] = cid
            new_row["平台域名"] = cid
            new_row["提交入口"] = submit_entry
            new_row["发现来源"] = discovery_source
            new_row["发现时间"] = discovery_time
            new_row["基础状态"] = MASTER_STATUS_CANDIDATE
            # 严格确保 Discovery 不写实测事实
            for fact_col in PROTECTED_FACT_COLUMNS:
                new_row[fact_col] = ""
            master_map[cid] = new_row
            master_order.append(cid)
            stats["new_inserted"] += 1
        else:
            # 已存在
            existing = master_map[cid]
            current_status = existing.get("基础状态") or MASTER_STATUS_CANDIDATE
            
            # 若已有基础状态为已排除或失效，绝对不得改回候选
            if current_status in (MASTER_STATUS_EXCLUDED, MASTER_STATUS_DEAD):
                stats["skipped_excluded_or_dead"] += 1
                # 仅保留原有状态，不覆盖
                continue
                
            updated = False
            # 补充安全的 provenance 信息
            if not existing.get("发现来源") and discovery_source:
                existing["发现来源"] = discovery_source
                updated = True
            if not existing.get("发现时间") and discovery_time:
                existing["发现时间"] = discovery_time
                updated = True
            if not existing.get("提交入口") and submit_entry:
                existing["提交入口"] = submit_entry
                updated = True
                
            # 保护实测事实不被覆盖（如果 item 里携带了实测字段，一律忽略）
            # 不修改 existing 中的 PROTECTED_FACT_COLUMNS
            
            if updated:
                stats["existing_updated"] += 1
            else:
                stats["existing_preserved"] += 1

    merged_rows = [master_map[cid] for cid in master_order]
    return merged_rows, stats


# ==========================================
# 6. Project Management Materialization 算法
# ==========================================

def materialize_project_row(
    master_row: dict[str, Any],
    existing_project_rows: list[dict[str, Any]],
    project_id: str,
    target_url: str = "",
) -> dict[str, str] | None:
    """为明确项目（例如 quick-iching）创建【外链管理】待提交行。
    
    契约条件（必须全部满足）：
    1. master_row.基础状态 == '候选'
    2. 存在非空且通过 policy guard 的提交入口
    3. 当前 project_id + backlink_id 尚不存在于 existing_project_rows 中
    
    保护规则：
    若该项目的该外链已存在任何状态（待提交/已提交/已上线/需人工/不适用等），
    绝对不能重复创建，也绝对不能重置为待提交。
    
    返回: 新行 dict，若不满足条件则返回 None
    """
    proj = str(project_id or "").strip()
    if not proj:
        return None
        
    backlink_id = canonical_domain(master_row.get("外链ID") or master_row.get("平台域名") or "")
    if not backlink_id:
        return None
        
    # 状态必须为候选
    status = str(master_row.get("基础状态") or "").strip()
    if status != MASTER_STATUS_CANDIDATE:
        return None
        
    # 提交入口必须有效非空
    entry = str(master_row.get("提交入口") or "").strip()
    if not entry:
        return None
    allowed, _ = submission_entry_policy_guard(entry, domain=backlink_id)
    if not allowed:
        return None
        
    # 检查 project_id + backlink_id 唯一性
    for prow in existing_project_rows:
        p_proj = str(prow.get("项目ID") or "").strip()
        p_bid = canonical_domain(prow.get("外链ID") or prow.get("外链域名") or "")
        if p_proj == proj and p_bid == backlink_id:
            # 已经存在（不论是待提交、已提交、已上线等任何状态），绝不重复创建
            return None

    return {
        "项目ID": proj,
        "外链ID": backlink_id,
        "外链域名": backlink_id,
        "状态": PROJECT_STATUS_TO_SUBMIT,
        "尝试次数": "0",
        "最近操作时间": "",
        "目标URL": str(target_url or "").strip(),
        "结果链接": "",
        "原因/备注": "",
        "证据摘要": "",
    }


# ==========================================
# 7. Bounded Batch Hydration 算法
# ==========================================

def batch_hydrate_candidates(
    master_rows: list[dict[str, Any]],
    existing_project_rows: list[dict[str, Any]],
    project_id: str,
    limit: int,
    entry_finder: Callable[[str], tuple[str | None, str]] | None = None,
) -> dict[str, Any]:
    """对总表现有候选进行有界批次 Hydration（补全有效提交入口并生成项目待提交行）。
    
    严格约束：
    1. 必须显式传入 project_id 与 limit；
    2. limit > 0，默认有界，绝不自动全量扫描 3000+；
    3. 仅挑选：基础状态=='候选' 且该 project 尚未有记录的平台；
    4. 逐个核验真实入口，只有找到真实入口才更新 master_row['提交入口'] 并建立项目待提交行；
    5. 找不到真实入口的 domain 保持候选，不排除，提交入口保持为空；
    6. 达到 limit 目标数量后立即停止。
    
    返回: {
        'hydrated_master_rows': 更新后的 master_rows,
        'new_project_rows': 新生成的待提交项目行列表,
        'succeeded_count': 成功生成的行数,
        'processed_candidates': 遍历尝试的域名数,
    }
    """
    proj = str(project_id or "").strip()
    if not proj:
        raise ValueError("必须显式指定 project_id")
    if limit <= 0:
        raise ValueError("limit 必须为大于 0 的整数")
        
    _finder = entry_finder or (lambda d: discover_and_verify_entry(d))
    
    # 记录该项目已有的 backlink_id
    existing_project_bids = set()
    for prow in existing_project_rows:
        p_proj = str(prow.get("项目ID") or "").strip()
        p_bid = canonical_domain(prow.get("外链ID") or prow.get("外链域名") or "")
        if p_proj == proj and p_bid:
            existing_project_bids.add(p_bid)

    new_project_rows: list[dict[str, str]] = []
    succeeded = 0
    processed = 0
    
    for mrow in master_rows:
        if succeeded >= limit:
            break
            
        cid = canonical_domain(mrow.get("外链ID") or mrow.get("平台域名") or "")
        status = str(mrow.get("基础状态") or "").strip()
        
        # 必须是候选
        if status != MASTER_STATUS_CANDIDATE:
            continue
        # 项目尚无记录
        if cid in existing_project_bids:
            continue
            
        processed += 1
        current_entry = str(mrow.get("提交入口") or "").strip()
        
        if not current_entry:
            # 尝试现场寻找入口
            entry_url, reason = _finder(cid)
            if entry_url:
                mrow["提交入口"] = entry_url
                current_entry = entry_url
                
        if current_entry:
            prow = materialize_project_row(mrow, existing_project_rows + new_project_rows, proj)
            if prow:
                new_project_rows.append(prow)
                existing_project_bids.add(cid)
                succeeded += 1

    return {
        "hydrated_master_rows": master_rows,
        "new_project_rows": new_project_rows,
        "succeeded_count": succeeded,
        "processed_candidates": processed,
    }
