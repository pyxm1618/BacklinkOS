#!/usr/bin/env python3
"""BacklinkOS Master Sheet and Project Management Core Sync Module.

实现新的唯一控制面（@外链管理总控表）的核心业务契约：
1. canonical_domain: 域名规范化
2. Master Sheet Upsert: 平台级唯一事实库合并，绝对保护真实实测字段与已排除/失效状态，隔离写入权限
3. Submission Entry Policy Guard & Live Verification:
   - 区分 Policy Guard 与 Live Evidence（必须有真实页面机制文案/控件或首页明确 CTA；严禁 URL path 单独冒充证据）；
   - 兼容支持登录/注册墙（AUTH_PATH_RE）正常包含 noindex 的情况，防止误杀有效入口；
   - 引入显式 VerifiedEntry 数据结构，封死未经验证 URL 绕过。
4. Project Materialization: 仅在候选 + 已有 VerifiedEntry + 项目行不存在时生成“待提交”行，保证 project_id + backlink_id 唯一。
5. Bounded Batch Hydration: 严格双边界（target_count + scan_limit），对总表现有入口同样强制 live verification，未验证通过不 materialize。
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urljoin, urlparse

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

# 常见登录/认证跳转返回参数名，用于识别 /submit -> /login?redirect=/submit 模式
AUTH_REDIRECT_PARAMS = {
    "redirect",
    "redirect_url",
    "redirect_to",
    "next",
    "return",
    "return_to",
    "continue",
    "callback",
    "target",
    "goto",
    "dest",
    "destination",
    "url",
}



# ==========================================
# 2. 核心数据结构与域名规范化
# ==========================================

@dataclass(frozen=True)
class VerifiedEntry:
    """经现场真实页面证据（Live Evidence）核验通过的提交入口凭证对象。
    
    只有该对象的实例才能在 project synchronization 中生成待提交行。
    不能仅凭未经验证的普通字符串 URL 绕过。
    """
    url: str
    domain: str
    evidence_type: str  # 'subpage_mechanism' | 'auth_wall_submission' | 'homepage_cta'
    evidence_summary: str

    def __post_init__(self):
        if not self.url or not self.domain:
            raise ValueError("VerifiedEntry 必须包含非空的 url 与 domain")


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


def check_auth_wall_callback_evidence(
    req_url: str,
    final_url: str,
    domain: str,
    is_discovered_candidate: bool = False,
) -> tuple[bool, str]:
    """检查是否属于真实合法的 /submit -> /login 重定向证据链。
    
    必须满足以下完整事实链条：
    1. 原始请求 req_url 必须通过 Policy Guard，且必须具备真实页面发现的 candidate/CTA 来源证据
       （严格执行：ENTRY_HINTS 仅能作为 probe hint，绝不得单独充当来源证据！必须 is_discovered_candidate=True）；
    2. 跳转后的 final_url 必须通过 Policy Guard，且属于同平台（canonical_domain 一致）；
    3. final_url 的 path 命中 AUTH_PATH_RE（登录/注册/认证墙）；
    4. final_url 的 query 参数中明确包含指向提交流程的回调/跳转参数（如 redirect=/submit, next=/add 等）；
    5. 重定向目标参数：
       - 若为绝对 URL，必须严格校验 callback hostname 与平台同源；外部跨域 callback 坚决拒绝；
       - 若为相对 URL，按平台路径处理；
       - 该 callback 路径必须通过 Policy Guard 且包含提交机制意图（非 pricing 等排除路径）；
    6. 证据摘要仅记录目标回调路径，严禁记录敏感 query/token。
    """
    cd = canonical_domain(domain)
    if not cd:
        return False, "域名无效"
        
    req_ok, req_reason = submission_entry_policy_guard(req_url, domain=cd)
    if not req_ok:
        return False, f"原始请求未通过 Policy Guard: {req_reason}"
        
    # 严格规则：页面无 mechanism 时，必须有真实页面发现的 candidate/CTA 来源证据！
    # ENTRY_HINTS 只能用于探测，绝不得充当来源证据！
    if not is_discovered_candidate:
        return False, "缺乏真实页面发现的 candidate/CTA 来源证据（禁止仅凭 URL 路径猜测）"
        
    final_ok, final_reason = submission_entry_policy_guard(final_url, domain=cd)
    if not final_ok:
        return False, f"最终跳转未通过 Policy Guard: {final_reason}"
        
    parsed_final = urlparse(final_url)
    final_path = (parsed_final.path or "/").strip()
    if not AUTH_PATH_RE.search(final_path):
        return False, f"最终跳转路径非认证墙: {final_path}"
        
    req_path = (urlparse(req_url).path or "/").strip()
    qs = parse_qs(parsed_final.query)
    found_valid_callback = False
    callback_path = ""
    
    for k, vals in qs.items():
        k_lower = k.lower()
        if k_lower in AUTH_REDIRECT_PARAMS or "redirect" in k_lower or "return" in k_lower or "next" in k_lower:
            for v in vals:
                decoded = unquote(v).strip()
                parsed_cb = urlparse(decoded)
                
                # 校验绝对 URL vs 相对 URL
                if parsed_cb.scheme or parsed_cb.netloc:
                    cb_host = (parsed_cb.hostname or "").lower()
                    if cb_host.startswith("www."):
                        cb_host = cb_host[4:]
                    # 必须同源，拒绝外部第三方 URL
                    if cb_host != cd and not cb_host.endswith("." + cd):
                        return False, f"认证跳转回调跨域外部域名: {cb_host} != {cd}"
                    cb_path = (parsed_cb.path or "/").strip()
                else:
                    cb_path = decoded.split("?")[0].strip()
                    if not cb_path.startswith("/"):
                        cb_path = "/" + cb_path
                
                if cb_path:
                    # 检查是否命中排除路径（比如 redirect=/pricing 绝对不行）
                    for p in INVALID_ENTRY_PATH_PATTERNS:
                        if p.search(cb_path):
                            return False, f"认证跳转回调指向排除路径: {cb_path}"
                    if ENTRY_HINTS.search(cb_path) or (req_path != "/" and req_path in cb_path):
                        found_valid_callback = True
                        callback_path = cb_path
                        break
        if found_valid_callback:
            break
            
    if not found_valid_callback:
        return False, "认证跳转页面未包含明确返回提交流程的回调参数"
        
    # 证据摘要仅记录目标回调路径与认证墙路径，绝不记录完整 query/token
    return True, f"访问提交入口触发平台认证墙，登录后重定向回提交流程 ({callback_path}): {final_path}"


def verify_submission_entry(
    domain: str,
    entry_url: str,
    fetcher: Callable[[str], dict] | None = None,
    is_discovered_candidate: bool = False,
) -> tuple[VerifiedEntry | None, str]:
    """对已有（例如历史存量或指定）的 entry_url 进行现场真实页面证据核验（Live Verification）。
    
    契约规则：
    1. 必须先通过 Policy Guard；
    2. 现场打开页面：
       - 检查 final_url 是否依然通过 Policy Guard（P0-3 必须验证 redirect 后 final_url，防止逃逸到 pricing 或跨域）；
       - 若是首页，必须通过 verify_homepage_as_entry（页面内有明确 CTA 机制证据）；
       - 若触发认证墙跳转（如 /submit -> /login?redirect=/submit），严格要求已证实来源证据（默认 is_discovered_candidate=False，历史存量未经证明不得盲目升级）；
         核验成功时 VerifiedEntry.url 保留原始稳定 entry_url，不写入带会话参数的 /login URL；
       - 若是子页面，必须具备明确机制信号（mechanism_signals）；单纯 HTTP 200 + URL 路径含 submit 绝不足以成为证据；
       - noindex 处理：提交入口页面本身不因 noindex 筛掉，只要机制真实且符合 Guard；
    3. 验证成功返回 (VerifiedEntry, 成功说明)；
    4. 验证失败返回 (None, 失败理由)。
    """
    cd = canonical_domain(domain)
    if not cd:
        return None, "域名无效"
        
    allowed, guard_reason = submission_entry_policy_guard(entry_url, domain=cd)
    if not allowed:
        return None, f"未通过 Policy Guard: {guard_reason}"
        
    _fetch = fetcher or fetch_page
    res = _fetch(entry_url)
    if res.get("status") != 200:
        return None, f"页面不可达 (HTTP {res.get('status', 0)})"
        
    final_url = res.get("final_url") or entry_url
    
    # P0-3 修复：必须对 redirect 后的 final_url 重新执行 Policy Guard
    allowed_final, final_guard_reason = submission_entry_policy_guard(final_url, domain=cd)
    if not allowed_final:
        return None, f"最终跳转 URL 未通过 Policy Guard: {final_guard_reason}"

    path = (urlparse(final_url).path or "/").strip()
    
    # 区分是否为首页
    if path in ("", "/"):
        is_cta, cta_reason = verify_homepage_as_entry(res)
        if is_cta:
            return VerifiedEntry(
                url=final_url,
                domain=cd,
                evidence_type="homepage_cta",
                evidence_summary=cta_reason,
            ), cta_reason
        return None, f"首页未包含有效机制 CTA: {cta_reason}"

    is_auth_wall = bool(AUTH_PATH_RE.search(path))
    has_mech = bool(res.get("mechanism_signals"))

    if is_auth_wall:
        is_auth_callback, auth_reason = check_auth_wall_callback_evidence(
            req_url=entry_url,
            final_url=final_url,
            domain=cd,
            is_discovered_candidate=is_discovered_candidate,
        )
        if is_auth_callback:
            # 保留原始稳定 submission URL，而不是带 token 或 query 的 /login URL
            return VerifiedEntry(
                url=entry_url,
                domain=cd,
                evidence_type="auth_wall_submission",
                evidence_summary=auth_reason,
            ), "现场核验通过 (认证墙回调证据)"
        elif has_mech:
            return VerifiedEntry(
                url=final_url,
                domain=cd,
                evidence_type="auth_wall_submission",
                evidence_summary=f"现场核验通过: 机制信号 {res.get('mechanism_signals')}",
            ), "现场核验通过"
        else:
            return None, auth_reason

    # P0-1 核心守卫：非认证墙普通子页面必须有真实机制文案/控件（mechanism_signals）
    if not has_mech:
        return None, "页面虽返回 200 但未检测到实际提交/收录/建链机制文案（拒绝仅凭 URL 路径臆想）"
        
    # P1-4 修复：页面本身无论是否标记 noindex，只要机制真实且符合 Guard，均不被误杀
    return VerifiedEntry(
        url=final_url,
        domain=cd,
        evidence_type="subpage_mechanism",
        evidence_summary=f"现场核验通过: 机制信号 {res.get('mechanism_signals')}",
    ), "现场核验通过"


def discover_and_verify_entry(
    domain: str,
    fetcher: Callable[[str], dict] | None = None,
    max_probes: int = 15,
) -> tuple[VerifiedEntry | None, str]:
    """使用已有经过测试的爬虫机制，对指定域名进行真实页面探测，寻找最低限度提交入口。
    
    流程：
    1. 访问首页（裸域/www 双试，由 fetch_page/probe 处理）；
       - 删除 homepage noindex 阻断逻辑：entry discovery 不以 indexability 淘汰；
    2. 获取首页 candidate_urls（按 strong/weak 排序）与 COMMON_PATHS；
    3. 访问子页面，寻找包含真实 mechanism 信号或合法 auth wall 回调的页面：
       - 严格执行 P0-1：只有返回 200 且真正包含 mechanism_signals 或合法 auth wall 回调才算真入口；单纯路径像 submit 坚决不通过；
       - 严格执行 P1-4：Entry 页面本身不因 noindex 筛掉；
       - 严格执行 P1-5：支持真实 /submit -> /login?redirect=/submit 回调证据链，auth wall 成功时保留原始稳定 target_url；
       - 严格执行 P0-3：任何最终跳转 URL 必须重新通过 Policy Guard；
    4. 对候选 URL 跑 submission_entry_policy_guard；
    5. 若找到真实子页面入口，返回 (VerifiedEntry, 成功理由)；
    6. 若只有首页且首页具备明确 CTA，返回 (VerifiedEntry, 首页理由)；
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
        
    # 删除原先的 if home.get("noindex"): return None 逻辑，entry discovery 不受 homepage noindex 阻断

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
            
        final_url = page_res.get("final_url") or target_url
        # P0-3 修复：对最终 URL 重新执行 Policy Guard
        allowed_final, _ = submission_entry_policy_guard(final_url, domain=cd)
        if not allowed_final:
            continue
            
        # P1-4 修复：Entry 页面本身不因 noindex 筛掉（已移除 noindex 过滤）

        # P1-5 修复：支持真实 /submit -> /login?redirect=/submit 认证墙回调证据
        is_from_candidate_list = target_url in candidate_urls
        is_auth_callback, auth_reason = check_auth_wall_callback_evidence(
            req_url=target_url,
            final_url=final_url,
            domain=cd,
            is_discovered_candidate=is_from_candidate_list,
        )
        if is_auth_callback:
            # 保留原始稳定 target_url，而不是带 token 或 query 的 final_url
            return VerifiedEntry(
                url=target_url,
                domain=cd,
                evidence_type="auth_wall_submission",
                evidence_summary=auth_reason,
            ), "通过真实页面探测闭环真实入口 (认证墙回调)"
            
        # P0-1 核心修复：坚决杜绝 URL path 单独升级！必须有实际机制信号 mechanism_signals
        has_mech = bool(page_res.get("mechanism_signals"))
        if not has_mech:
            # 即使 path 是 /submit，但页面没有机制信号，绝不通过！
            continue
            
        final_path = urlparse(final_url).path or "/"
        is_auth_wall = bool(AUTH_PATH_RE.search(final_path))
        evidence_type = "auth_wall_submission" if is_auth_wall else "subpage_mechanism"
        entry_obj = VerifiedEntry(
            url=final_url,
            domain=cd,
            evidence_type=evidence_type,
            evidence_summary=f"真实页面探测到机制信号: {page_res.get('mechanism_signals')}",
        )
        return entry_obj, "通过真实页面探测闭环真实入口"
            
    # 如果所有子页面都没有发现，检查首页本身是否具备明确 CTA
    is_home_cta, home_reason = verify_homepage_as_entry(home)
    if is_home_cta:
        entry_obj = VerifiedEntry(
            url=base_url,
            domain=cd,
            evidence_type="homepage_cta",
            evidence_summary=home_reason,
        )
        return entry_obj, home_reason
        
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
        
        # 彻底禁止从 new_discoveries 的普通字符串或 VerifiedEntry 写提交入口！
        # upsert_master_rows 只负责平台域名与来源 provenance 合并。
        # 提交入口只能由真实 Entry Enrichment orchestration 核验成功后写入。
        if cid not in master_map:
            new_row = {col: "" for col in MASTER_HEADER}
            new_row["外链ID"] = cid
            new_row["平台域名"] = cid
            new_row["提交入口"] = ""
            new_row["发现来源"] = discovery_source
            new_row["发现时间"] = discovery_time
            new_row["基础状态"] = MASTER_STATUS_CANDIDATE
            for fact_col in PROTECTED_FACT_COLUMNS:
                new_row[fact_col] = ""
            master_map[cid] = new_row
            master_order.append(cid)
            stats["new_inserted"] += 1
        else:
            existing = master_map[cid]
            current_status = existing.get("基础状态") or MASTER_STATUS_CANDIDATE
            
            if current_status in (MASTER_STATUS_EXCLUDED, MASTER_STATUS_DEAD):
                stats["skipped_excluded_or_dead"] += 1
                continue
                
            updated = False
            if not existing.get("发现来源") and discovery_source:
                existing["发现来源"] = discovery_source
                updated = True
            if not existing.get("发现时间") and discovery_time:
                existing["发现时间"] = discovery_time
                updated = True
                
            if updated:
                stats["existing_updated"] += 1
            else:
                stats["existing_preserved"] += 1

    merged_rows = [master_map[cid] for cid in master_order]
    return merged_rows, stats


# ==========================================
# 6. Project Management Materialization 算法
# ==========================================

def _materialize_verified_project_row(
    master_row: dict[str, Any],
    existing_project_rows: list[dict[str, Any]],
    project_id: str,
    verified_entry: VerifiedEntry,
    target_url: str = "",
) -> dict[str, str] | None:
    """内部底层 helper：仅供内部 live verification 流程在产生现场证据后组装项目行。
    
    严禁作为生产外部公开入口，外部必须调用 materialize_project_row 进行现场核验。
    """
    proj = str(project_id or "").strip()
    if not proj:
        return None
        
    backlink_id = canonical_domain(master_row.get("外链ID") or master_row.get("平台域名") or "")
    if not backlink_id:
        return None
        
    if not isinstance(verified_entry, VerifiedEntry):
        return None
    if canonical_domain(verified_entry.domain) != backlink_id:
        return None
    if not verified_entry.url:
        return None
        
    # 状态必须为候选
    status = str(master_row.get("基础状态") or "").strip()
    if status != MASTER_STATUS_CANDIDATE:
        return None
        
    # 检查 project_id + backlink_id 唯一性
    for prow in existing_project_rows:
        p_proj = str(prow.get("项目ID") or "").strip()
        p_bid = canonical_domain(prow.get("外链ID") or prow.get("外链域名") or "")
        if p_proj == proj and p_bid == backlink_id:
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
        "证据摘要": f"{verified_entry.evidence_type}: {verified_entry.evidence_summary}",
    }


def materialize_project_row(
    master_row: dict[str, Any],
    existing_project_rows: list[dict[str, Any]],
    project_id: str,
    target_url: str = "",
    entry_url: str = "",
    fetcher: Callable[[str], dict] | None = None,
    entry_verifier: Callable[[str, str], tuple[VerifiedEntry | None, str]] | None = None,
    entry_finder: Callable[[str], tuple[VerifiedEntry | None, str]] | None = None,
) -> dict[str, str] | None:
    """为明确项目（例如 quick-iching）创建【外链管理】待提交行的正式公开生产编排函数。
    
    契约规则（P0-2）：
    1. 生产队列 materialization 必须由内部 live verification 流程驱动；
    2. 禁止调用方通过自行实例化 VerifiedEntry 绕过现场核验；
    3. 内部核验链路：
       - 若指定了 entry_url 或 master_row 已有'提交入口'：调用 entry_verifier 进行现场核验；
       - 若无已知入口：调用 entry_finder 现场探测；
       - 验证失败或未获得真实证据：返回 None，绝不入库；
       - 验证成功：由内部 helper 组装待提交行；
    4. 保证 project_id + backlink_id 唯一，保留已有项目行状态，不重复创建。
    
    返回: 新行 dict，若核验不通过或不满足唯一性条件则返回 None
    """
    proj = str(project_id or "").strip()
    if not proj:
        return None
        
    backlink_id = canonical_domain(master_row.get("外链ID") or master_row.get("平台域名") or "")
    if not backlink_id:
        return None
        
    status = str(master_row.get("基础状态") or "").strip()
    if status != MASTER_STATUS_CANDIDATE:
        return None

    # 查重检查：已存在则绝不重复创建
    for prow in existing_project_rows:
        p_proj = str(prow.get("项目ID") or "").strip()
        p_bid = canonical_domain(prow.get("外链ID") or prow.get("外链域名") or "")
        if p_proj == proj and p_bid == backlink_id:
            return None

    _verifier = entry_verifier or (lambda d, u: verify_submission_entry(d, u, fetcher=fetcher))
    _finder = entry_finder or (lambda d: discover_and_verify_entry(d, fetcher=fetcher))

    cand_entry = str(entry_url or master_row.get("提交入口") or "").strip()
    verified_obj: VerifiedEntry | None = None

    if cand_entry:
        verified_obj, _ = _verifier(backlink_id, cand_entry)
    else:
        verified_obj, _ = _finder(backlink_id)

    if not verified_obj:
        return None

    return _materialize_verified_project_row(
        master_row=master_row,
        existing_project_rows=existing_project_rows,
        project_id=proj,
        verified_entry=verified_obj,
        target_url=target_url,
    )


# ==========================================
# 7. Bounded Batch Hydration 算法 (双边界)
# ==========================================

def batch_hydrate_candidates(
    master_rows: list[dict[str, Any]],
    existing_project_rows: list[dict[str, Any]],
    project_id: str,
    target_count: int = 10,
    scan_limit: int = 30,
    entry_finder: Callable[[str], tuple[VerifiedEntry | None, str]] | None = None,
    entry_verifier: Callable[[str, str], tuple[VerifiedEntry | None, str]] | None = None,
) -> dict[str, Any]:
    """对总表现有候选进行严格双边界批次 Hydration。
    
    严格约束：
    1. 必须显式传入 project_id；
    2. target_count > 0（目标待提交行数），scan_limit > 0（最多扫描候选数），scan_limit >= target_count；
    3. 满足 `succeeded >= target_count or processed >= scan_limit` 任意一个立即停止；
    4. P0-2：已有非空 `提交入口` 必须经 entry_verifier 现场重新核验，核验通过才能 materialize；
       未通过则保持候选，不生成项目行，不随意替换原 URL；
    5. 空入口通过 entry_finder 现场探测，探测成功写入总表提交入口并 materialize；
    6. 找不到真实入口的 domain 保持候选，不排除，提交入口保持为空。
    
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
    if target_count <= 0:
        raise ValueError("target_count 必须为大于 0 的整数")
    if scan_limit <= 0:
        raise ValueError("scan_limit 必须为大于 0 的整数")
    if scan_limit < target_count:
        raise ValueError("scan_limit 不能小于 target_count")
        
    _finder = entry_finder or discover_and_verify_entry
    _verifier = entry_verifier or verify_submission_entry
    
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
        # P0-3 双边界检查：达成目标或达到扫描上限即刻停止
        if succeeded >= target_count or processed >= scan_limit:
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
        verified_obj: VerifiedEntry | None = None
        
        if current_entry:
            # P0-2 核心守卫：已有非空 entry 必须现场核验！
            verified_obj, _ = _verifier(cid, current_entry)
        else:
            # 入口为空，执行现场探测
            verified_obj, _ = _finder(cid)
            if verified_obj:
                mrow["提交入口"] = verified_obj.url
                
        if verified_obj:
            prow = _materialize_verified_project_row(
                master_row=mrow,
                existing_project_rows=existing_project_rows + new_project_rows,
                project_id=proj,
                verified_entry=verified_obj,
            )
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
