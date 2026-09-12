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

import concurrent.futures
import datetime
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urljoin, urlparse


class DaemonProbeExecutor:
    """具备守护线程属性、任务取消令牌与并发上限的探测执行器 (F5)。"""
    _semaphore = threading.BoundedSemaphore(4)  # 限制最多 4 个活跃探测线程，杜绝连续超时堆积

    @classmethod
    def execute(
        cls,
        func: Callable[[], Any],
        timeout: float,
        deadline: float | None = None,
    ) -> tuple[bool, Any, bool]:
        """在守护线程中执行 func。
        返回: (is_success, result_or_exc, is_timeout)
        """
        now = time.time()
        wall_remaining = (deadline - now) if deadline is not None else timeout
        effective_timeout = max(0.001, min(timeout, wall_remaining))
        if effective_timeout <= 0.001 and wall_remaining <= 0:
            return False, "SITE_PROBE_TIMEOUT (deadline exceeded)", True

        token = {"canceled": False}
        result_box: list[tuple[str, Any]] = []
        done_event = threading.Event()

        acquired = cls._semaphore.acquire(blocking=False)
        if not acquired:
            acquired = cls._semaphore.acquire(blocking=True, timeout=min(0.2, effective_timeout))
            if not acquired:
                return False, "SITE_PROBE_TIMEOUT (worker concurrency saturated)", True

        def _worker():
            try:
                res = func()
                if not token["canceled"]:
                    result_box.append(("ok", res))
            except Exception as exc:
                if not token["canceled"]:
                    result_box.append(("err", exc))
            finally:
                cls._semaphore.release()
                done_event.set()

        # 启动守护线程 (daemon=True)，进程退出时绝不被 join 拖住卡死
        t = threading.Thread(target=_worker, daemon=True)
        t.start()

        completed = done_event.wait(timeout=effective_timeout)
        if not completed:
            token["canceled"] = True  # 标记取消，迟到响应绝不更新状态或返回
            return False, "SITE_PROBE_TIMEOUT (wall-clock deadline exceeded)", True

        if not result_box:
            token["canceled"] = True
            return False, "UNKNOWN_WORKER_ERROR", False

        status, val = result_box[0]
        if status == "ok":
            return True, val, False
        else:
            return False, val, False

DEFAULT_BACKLINKOS_RUNTIME_DIR = os.path.expanduser("~/.backlinkos/runtime")
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_project_id(project_id: str) -> str:
    if not isinstance(project_id, str):
        raise ValueError("project_id must be a string")
    pid = project_id.strip()
    if pid in {"", ".", ".."} or not _PROJECT_ID_RE.fullmatch(pid):
        raise ValueError(f"invalid project_id: {project_id!r}")
    return pid


def get_ready_cursor_path(project_id: str, runtime_dir: str | None = None) -> Path:
    validated_pid = validate_project_id(project_id)
    base_dir = Path(runtime_dir or os.environ.get("BACKLINKOS_RUNTIME_DIR", DEFAULT_BACKLINKOS_RUNTIME_DIR))
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"ready_cursor_{validated_pid}.json"

def load_ready_cursor(project_id: str, runtime_dir: str | None = None) -> str | None:
    path = get_ready_cursor_path(project_id, runtime_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("last_scanned_backlink_id")
    except Exception:
        return None

def save_ready_cursor(project_id: str, last_scanned_backlink_id: str, runtime_dir: str | None = None) -> None:
    path = get_ready_cursor_path(project_id, runtime_dir)
    data = {
        "project_id": project_id,
        "last_scanned_backlink_id": last_scanned_backlink_id,
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    tmp_path = path.with_suffix(f".tmp.{os.getpid()}")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)

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

# 私有控制台保护规则：除非携带提交上下文，否则不能作为通用 Entry
DASHBOARD_PATH_RE = re.compile(r"/(?:app/)?(?:dashboard|overview|console|admin|portal)(?:/|$)", re.I)

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
    evidence_type: str  # 'actionable_form' | 'auth_wall_submission' | 'homepage_actionable' | 'homepage_cta'
    evidence_summary: str
    form_details: dict[str, Any] | None = None
    ai_only: bool = False

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


def normalize_canonical_url(url: str) -> str:
    """规范化 URL 便于比对：去除前后空格、协议差异、末尾斜杠及 www 前缀。"""
    if not url or not isinstance(url, str):
        return ""
    u = url.strip()
    if not u:
        return ""
    try:
        parsed = urlparse(u if "://" in u else f"https://{u}")
        netloc = (parsed.hostname or parsed.netloc or "").strip().lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        port_str = f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""
        path = parsed.path.rstrip("/")
        query = f"?{parsed.query}" if parsed.query else ""
        return f"{netloc}{port_str}{path}{query}"
    except Exception:
        return u.lower().rstrip("/")


# ==========================================
# 3. Submission Entry Policy Guard
# ==========================================

def submission_entry_policy_guard(
    url: str,
    domain: str = "",
    negated_entries: set[str] | list[str] | None = None,
) -> tuple[bool, str]:
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

    # 检查是否命中私有控制台保护规则（dashboard/console/admin 等），除非带明确提交 intent
    if DASHBOARD_PATH_RE.search(path):
        q = (parsed.query or "").lower()
        if not re.search(r'\b(submit|add|listing|new|action=)\b', q):
            return False, f"命中私有控制台排除规则（无提交意图参数）: {path}"

    # 检查是否命中已否定入口 (negated entries guard)
    if negated_entries:
        norm_u = u.rstrip("/")
        for neg in negated_entries:
            norm_neg = str(neg).strip().rstrip("/")
            if norm_neg and (norm_u == norm_neg or norm_u.startswith(norm_neg + "/") or norm_u.startswith(norm_neg + "?")):
                return False, f"命中已否定入口（历史已核实非公开提交流程）: {norm_neg}"

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


def evaluate_page_for_actionable_entry(
    page_res: dict[str, Any],
    req_url: str,
    domain: str,
    fetcher: Callable[[str], dict],
    is_discovered_candidate: bool = False,
    allow_cta_follow: bool = True,
) -> tuple[VerifiedEntry | None, str]:
    """统一评估一个抓取到的页面是否构成真实可操作的提交入口。
    
    规则：
    1. 搜索结果页 (is_search_page=True) 直接拒绝；
    2. 检查 Actionable Form：包含 directory_listing 或 guest_post 表单；
    3. 检查 Auth Wall：访问后重定向至登录页且 callback 明确指向提交流程；
    4. 检查 CTA 跟随 (Follow CTA)：来源页本身绝不升级为 Entry，跟随打开 CTA 目标页并验证；
    5. 绝不允许仅凭正文 mechanism_signals 单独升级！
    """
    cd = canonical_domain(domain)
    final_url = page_res.get("final_url") or req_url

    # 1. 搜索结果页拦截
    if page_res.get("is_search_page") or ("?q=" in final_url or "?s=" in final_url):
        return None, "页面为搜索结果页，非有效提交入口"

    path = (urlparse(final_url).path or "/").strip()
    is_auth_wall = bool(AUTH_PATH_RE.search(path))

    # 2. 检查 Actionable Forms (A 规则)
    actionable_forms = page_res.get("actionable_forms") or []
    if actionable_forms:
        top_form = actionable_forms[0]
        summary = f"现场核验通过: 真实可操作提交表单 ({top_form['form_type']}, 字段: {top_form['resource_fields']}, 按钮: {top_form['submit_controls']})"
        return VerifiedEntry(
            url=final_url,
            domain=cd,
            evidence_type="actionable_form",
            evidence_summary=summary,
            form_details=top_form,
            ai_only=bool(page_res.get("ai_only_signals")),
        ), "现场核验通过 (Actionable Form)"

    # 3. 检查 Auth Wall (C 规则)
    if is_auth_wall:
        is_auth_callback, auth_reason = check_auth_wall_callback_evidence(
            req_url=req_url,
            final_url=final_url,
            domain=cd,
            is_discovered_candidate=is_discovered_candidate,
        )
        if is_auth_callback:
            return VerifiedEntry(
                url=req_url,
                domain=cd,
                evidence_type="auth_wall_submission",
                evidence_summary=auth_reason,
                ai_only=bool(page_res.get("ai_only_signals")),
            ), "现场核验通过 (认证墙回调证据)"
        elif not is_discovered_candidate and fetcher:
            # 最小正确方案：当 persisted entry 跳到 auth wall 且 verifier 缺少来源证据
            # 则重新验证来源关系：检查 Homepage 是否存在明确指向当前 entry 的 Submit/Add/List CTA
            # 且 auth callback 仍指向合法提交路径
            req_parsed = urlparse(req_url)
            req_path = (req_parsed.path or "/").rstrip("/") or "/"
            reverified_entry: VerifiedEntry | None = None
            reverified_reason: str = ""

            for scheme in ("https", "http"):
                home_res = fetcher(f"{scheme}://{cd}/")
                if home_res and home_res.get("status") == 200:
                    cta_links = home_res.get("submission_cta_links") or []
                    for cta in cta_links:
                        cta_u = cta.get("url") or ""
                        cta_parsed = urlparse(cta_u)
                        cta_host = (cta_parsed.hostname or "").lower()
                        if cta_host.startswith("www."):
                            cta_host = cta_host[4:]
                        cta_path = (cta_parsed.path or "/").rstrip("/") or "/"

                        if (not cta_host or cta_host == cd) and cta_path == req_path:
                            # 首页证实存在明确指向当前 entry 的提交 CTA
                            cb_ok, cb_reason = check_auth_wall_callback_evidence(
                                req_url=req_url,
                                final_url=final_url,
                                domain=cd,
                                is_discovered_candidate=True,
                            )
                            if cb_ok:
                                summary = f"通过首页明确 CTA ('{cta.get('text', 'CTA')}') 重新建立来源证据 -> {cb_reason}"
                                reverified_entry = VerifiedEntry(
                                    url=req_url,
                                    domain=cd,
                                    evidence_type="auth_wall_submission",
                                    evidence_summary=summary,
                                    ai_only=bool(page_res.get("ai_only_signals") or home_res.get("ai_only_signals")),
                                )
                                reverified_reason = "现场核验通过 (通过首页CTA重新建立认证墙来源证据)"
                                break
                            else:
                                auth_reason = cb_reason
                                break
                    if reverified_entry:
                        break

            if reverified_entry:
                return reverified_entry, reverified_reason
            return None, auth_reason
        else:
            return None, auth_reason

    # 4. 检查 CTA 跟随 (B 规则)
    if allow_cta_follow:
        cta_links = page_res.get("submission_cta_links") or []
        for cta in cta_links[:3]:
            tgt_url = cta.get("url")
            tgt_text = cta.get("text") or "CTA"
            if not tgt_url:
                continue
            allowed_tgt, _ = submission_entry_policy_guard(tgt_url, domain=cd)
            if not allowed_tgt:
                continue
            tgt_res = fetcher(tgt_url)
            if tgt_res.get("status") != 200:
                continue
            tgt_final = tgt_res.get("final_url") or tgt_url
            allowed_tgt_final, _ = submission_entry_policy_guard(tgt_final, domain=cd)
            if not allowed_tgt_final:
                continue
            # 递归检查目标页面 (禁止二次嵌套 follow 防止死循环)
            sub_verified, sub_reason = evaluate_page_for_actionable_entry(
                page_res=tgt_res,
                req_url=tgt_url,
                domain=cd,
                fetcher=fetcher,
                is_discovered_candidate=True,
                allow_cta_follow=False,
            )
            if sub_verified:
                combined_summary = f"跟随来源页 CTA ('{tgt_text}') -> {sub_verified.evidence_summary}"
                return VerifiedEntry(
                    url=sub_verified.url,
                    domain=cd,
                    evidence_type=sub_verified.evidence_type,
                    evidence_summary=combined_summary,
                    form_details=sub_verified.form_details,
                    ai_only=bool(sub_verified.ai_only or page_res.get("ai_only_signals")),
                ), f"通过跟随 CTA 闭环入口 ({sub_reason})"

    # 5. 纯正文或普通文章，坚决不通过
    return None, "页面虽返回 200 但未检测到真实可操作提交表单（Actionable Form）或有效认证墙（拒绝正文文字臆想）"


def extract_negated_entries_from_row(master_row: dict[str, Any]) -> set[str]:
    """从总表行的平台备注与基础排除原因中提取已否定的入口 URL 集合。"""
    res = set()
    text = f"{master_row.get('平台备注', '')} {master_row.get('基础排除原因', '')}"
    for match in re.finditer(r'(?:否定入口|已否定入口|negated_entry|错误入口)\s*[:：]\s*(https?://[^\s,;，；\)]+)', text, re.I):
        u = match.group(1).strip().rstrip("/")
        if u:
            res.add(u)
    return res



def verify_submission_entry(
    domain: str,
    entry_url: str,
    fetcher: Callable[[str], dict] | None = None,
    is_discovered_candidate: bool = False,
    negated_entries: set[str] | list[str] | None = None,
    site_timeout_budget: float = 15.0,
) -> tuple[VerifiedEntry | None, str]:
    """对已有（例如历史存量或指定）的 entry_url 进行现场真实页面证据核验（Live Verification）。"""
    cd = canonical_domain(domain)
    if not cd:
        return None, "域名无效"

    t0 = time.time()
    deadline = t0 + site_timeout_budget
    _raw_fetch = fetcher or fetch_page
    neg_set = {str(x).strip().rstrip("/") for x in (negated_entries or []) if str(x).strip()}

    clean_entry = str(entry_url).strip().rstrip("/")
    if clean_entry in neg_set or any(clean_entry == n or clean_entry.startswith(n + "/") for n in neg_set):
        return None, f"未通过 Policy Guard: 命中已否定入口 ({clean_entry})"

    allowed, guard_reason = submission_entry_policy_guard(entry_url, domain=cd, negated_entries=neg_set)
    if not allowed:
        return None, f"未通过 Policy Guard: {guard_reason}"

    def _budgeted_fetch(url: str, timeout: float | None = None) -> dict:
        now = time.time()
        remaining = deadline - now
        if remaining <= 0:
            return {"status": 0, "error": "SITE_PROBE_TIMEOUT", "timeout": True}
        call_timeout = min(timeout if timeout is not None else 5.0, remaining)

        def _do_call():
            try:
                return _raw_fetch(url, timeout=call_timeout, deadline=deadline)
            except TypeError:
                try:
                    return _raw_fetch(url, timeout=call_timeout)
                except TypeError:
                    return _raw_fetch(url)

        is_succ, res_or_err, is_to = DaemonProbeExecutor.execute(
            func=_do_call,
            timeout=call_timeout,
            deadline=deadline,
        )
        if is_to:
            return {"status": 0, "error": str(res_or_err), "timeout": True}
        if not is_succ:
            err_str = str(res_or_err).lower()
            to_kw = "timed out" in err_str or "timeout" in err_str or (time.time() - t0) >= site_timeout_budget
            return {"status": 0, "error": str(res_or_err), "timeout": to_kw}
        return res_or_err

    _fetch = _budgeted_fetch
    res = _budgeted_fetch(entry_url)
    if res.get("timeout") or (time.time() - t0) >= site_timeout_budget:
        return None, "已有入口核验超时，保留为未知/候选"
    if res.get("status") != 200:
        return None, f"页面不可达 (HTTP {res.get('status', 0)})"

    final_url = res.get("final_url") or entry_url
    clean_final = str(final_url).strip().rstrip("/")
    if clean_final in neg_set or any(clean_final == n or clean_final.startswith(n + "/") for n in neg_set):
        return None, f"最终跳转 URL 命中已否定入口: {clean_final}"
    allowed_final, final_guard_reason = submission_entry_policy_guard(final_url, domain=cd, negated_entries=neg_set)
    if not allowed_final:
        return None, f"最终跳转 URL 未通过 Policy Guard: {final_guard_reason}"

    path = (urlparse(final_url).path or "/").strip()
    
    # 首页检查
    if path in ("", "/"):
        # 若首页自身包含 Actionable Form
        if res.get("actionable_forms"):
            top_form = res["actionable_forms"][0]
            summary = f"首页内嵌真实可操作提交表单: {top_form['form_type']} (字段: {top_form['resource_fields']}, 控件: {top_form['submit_controls']})"
            return VerifiedEntry(
                url=final_url,
                domain=cd,
                evidence_type="homepage_actionable",
                evidence_summary=summary,
                form_details=top_form,
                ai_only=bool(res.get("ai_only_signals")),
            ), "首页核验通过 (内嵌表单)"

        # 首页尝试跟随 CTA
        cta_links = res.get("submission_cta_links") or []
        for cta in cta_links[:3]:
            tgt_url = cta.get("url")
            tgt_text = cta.get("text") or "CTA"
            if not tgt_url:
                continue
            allowed_tgt, _ = submission_entry_policy_guard(tgt_url, domain=cd, negated_entries=negated_entries)
            if not allowed_tgt:
                continue
            tgt_res = _fetch(tgt_url)
            if tgt_res.get("status") != 200:
                continue
            tgt_final = tgt_res.get("final_url") or tgt_url
            allowed_tgt_final, _ = submission_entry_policy_guard(tgt_final, domain=cd, negated_entries=negated_entries)
            if not allowed_tgt_final:
                continue
            sub_verified, sub_reason = evaluate_page_for_actionable_entry(
                page_res=tgt_res,
                req_url=tgt_url,
                domain=cd,
                fetcher=_fetch,
                is_discovered_candidate=True,
                allow_cta_follow=False,
            )
            if sub_verified:
                summary = f"跟随首页 CTA ('{tgt_text}') -> {sub_verified.evidence_summary}"
                return VerifiedEntry(
                    url=sub_verified.url,
                    domain=cd,
                    evidence_type=sub_verified.evidence_type,
                    evidence_summary=summary,
                    form_details=sub_verified.form_details,
                    ai_only=bool(sub_verified.ai_only or res.get("ai_only_signals")),
                ), f"通过跟随首页 CTA 闭环子页面入口 ({sub_reason})"

        return None, "首页无 Actionable Form 且未发现可跟随的有效提交 CTA 链接（严禁正文文字臆想为入口）"

    # 子页面使用核心评估函数
    sub_verified, sub_reason = evaluate_page_for_actionable_entry(
        page_res=res,
        req_url=entry_url,
        domain=cd,
        fetcher=_fetch,
        is_discovered_candidate=is_discovered_candidate,
        allow_cta_follow=True,
    )
    if sub_verified and not sub_verified.ai_only and _fetch:
        for scheme in ("https", "http"):
            home_res = _fetch(f"{scheme}://{cd}/")
            if home_res and home_res.get("status") == 200:
                if home_res.get("ai_only_signals"):
                    sub_verified = VerifiedEntry(
                        url=sub_verified.url,
                        domain=sub_verified.domain,
                        evidence_type=sub_verified.evidence_type,
                        evidence_summary=sub_verified.evidence_summary,
                        form_details=sub_verified.form_details,
                        ai_only=True,
                    )
                break
    return sub_verified, sub_reason


def discover_and_verify_entry(
    domain: str,
    fetcher: Callable[[str], dict] | None = None,
    max_probes: int = 15,
    site_timeout_budget: float = 15.0,
    negated_entries: set[str] | list[str] | None = None,
) -> tuple[VerifiedEntry | None, str]:
    """使用已有经过测试的爬虫机制，对指定域名进行真实页面探测，寻找最低限度提交入口。
    
    硬约束：
    1. site_timeout_budget 真正约束整站整条链路的所有网络请求（主页、www、子路径、跳转等）；
    2. 剩余预算耗尽时立即终止探测，返回超时（未知/候选），绝不无限阻塞；
    3. 支持 negated_entries 守卫，防止重复将已否定入口选为 Ready。
    """
    cd = canonical_domain(domain)
    if not cd:
        return None, "域名无效"
        
    t0 = time.time()
    deadline = t0 + site_timeout_budget
    _raw_fetch = fetcher or fetch_page
    neg_set = {str(x).strip().rstrip("/") for x in (negated_entries or []) if str(x).strip()}

    def _budgeted_fetch(url: str, timeout: float | None = None) -> dict:
        now = time.time()
        remaining = deadline - now
        if remaining <= 0:
            return {"status": 0, "error": "SITE_PROBE_TIMEOUT", "timeout": True}
        call_timeout = min(timeout if timeout is not None else 5.0, remaining)

        def _do_call():
            try:
                return _raw_fetch(url, timeout=call_timeout, deadline=deadline)
            except TypeError:
                try:
                    return _raw_fetch(url, timeout=call_timeout)
                except TypeError:
                    return _raw_fetch(url)

        is_succ, res_or_err, is_to = DaemonProbeExecutor.execute(
            func=_do_call,
            timeout=call_timeout,
            deadline=deadline,
        )
        if is_to:
            return {"status": 0, "error": str(res_or_err), "timeout": True}
        if not is_succ:
            err_str = str(res_or_err).lower()
            to_kw = "timed out" in err_str or "timeout" in err_str or (time.time() - t0) >= site_timeout_budget
            return {"status": 0, "error": str(res_or_err), "timeout": to_kw}
        return res_or_err

    # 尝试 https 和 http 首页
    home = None
    had_timeout = False
    for scheme in ("https", "http"):
        if (time.time() - t0) >= site_timeout_budget:
            return None, "站点整条探测超时 (主页探测前预算耗尽)，保留为未知/候选"
        res = _budgeted_fetch(f"{scheme}://{cd}/")
        if res.get("timeout"):
            had_timeout = True
            break
        if res.get("status") == 200:
            home = res
            break
            
    if not home and not had_timeout:
        # 尝试 www
        for scheme in ("https", "http"):
            if (time.time() - t0) >= site_timeout_budget:
                return None, "站点整条探测超时 (www 主页探测前预算耗尽)，保留为未知/候选"
            res = _budgeted_fetch(f"{scheme}://www.{cd}/")
            if res.get("timeout"):
                had_timeout = True
                break
            if res.get("status") == 200:
                home = res
                break
                
    if not home or home.get("status") != 200:
        if had_timeout or (time.time() - t0) >= site_timeout_budget:
            return None, "站点整条探测超时 (主页连接超时)，保留为未知/候选"
        return None, f"站点首页不可达 (HTTP {home.get('status') if home else 0})"

    base_url = home.get("final_url") or f"https://{cd}/"
    candidate_urls = list(home.get("candidate_urls") or [])
    for cta in home.get("submission_cta_links") or []:
        u = cta.get("url")
        if u and u not in candidate_urls:
            candidate_urls.append(u)
    
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
        if (time.time() - t0) >= site_timeout_budget:
            return None, "站点整条探测超时 (子页面探测预算耗尽)，保留为未知/候选"
            
        clean_target = str(target_url).strip().rstrip("/")
        if clean_target in neg_set or any(clean_target == n or clean_target.startswith(n + "/") for n in neg_set):
            continue
            
        allowed_target, _ = submission_entry_policy_guard(target_url, domain=cd, negated_entries=neg_set)
        if not allowed_target:
            continue

        page_res = _budgeted_fetch(target_url)
        if page_res.get("timeout") or (time.time() - t0) >= site_timeout_budget:
            return None, "站点整条探测超时 (子页面请求超时)，保留为未知/候选"
        if page_res.get("status") != 200:
            continue
            
        final_url = page_res.get("final_url") or target_url
        allowed_final, _ = submission_entry_policy_guard(final_url, domain=cd, negated_entries=neg_set)
        if not allowed_final:
            continue

        is_from_candidate_list = target_url in candidate_urls
        sub_verified, sub_reason = evaluate_page_for_actionable_entry(
            page_res=page_res,
            req_url=target_url,
            domain=cd,
            fetcher=_budgeted_fetch,
            is_discovered_candidate=is_from_candidate_list,
            allow_cta_follow=True,
        )
        if sub_verified:
            # 守卫：若命中了已否定入口，拒绝该入口继续探测后续
            u_clean = str(sub_verified.url).strip().rstrip("/")
            if u_clean in neg_set or any(u_clean == n or u_clean.startswith(n + "/") for n in neg_set):
                continue

            # 继承主页的 ai_only_signals
            if home and home.get("ai_only_signals") and not sub_verified.ai_only:
                sub_verified = VerifiedEntry(
                    url=sub_verified.url,
                    domain=sub_verified.domain,
                    evidence_type=sub_verified.evidence_type,
                    evidence_summary=sub_verified.evidence_summary,
                    form_details=sub_verified.form_details,
                    ai_only=True,
                )
            return sub_verified, f"通过真实页面探测闭环真实入口 ({sub_reason})"

    # 首页检查
    if home.get("actionable_forms"):
        u_clean = str(base_url).strip().rstrip("/")
        if u_clean not in neg_set and not any(u_clean == n or u_clean.startswith(n + "/") for n in neg_set):
            top_form = home["actionable_forms"][0]
            return VerifiedEntry(
                url=base_url,
                domain=cd,
                evidence_type="homepage_actionable",
                evidence_summary=f"首页内嵌真实表单: {top_form['form_type']} (字段: {top_form['resource_fields']})",
                form_details=top_form,
                ai_only=bool(home.get("ai_only_signals")),
            ), "通过首页真实表单闭环入口"

    if (time.time() - t0) >= site_timeout_budget:
        return None, "站点整条探测超时 (探测耗尽预算)，保留为未知/候选"

    return None, "未定位到用户可提交的入口页（证据缺失，无 Actionable Form 或可跟随的有效提交 CTA，保持候选状态）"



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


def load_project_profile_facts(project_id: str) -> dict[str, Any]:
    """读取项目 profile 权威事实配置，缺失或证据不足时保持未知 (None)，绝不盲目猜测。

    规则约束：
    1. 项目属性未知不能默认成否定。
    2. “没有付费预算配置”不能自动推断 accepts_paid=False。
    3. “禁止声称 AI-powered”也不能单独证明 ai_powered=False。
    4. 优先读取现有权威配置；缺失或证据不足时保持未知。只根据明确项目属性和政策进行排除。
    """
    proj = str(project_id or "").strip()
    if not proj:
        return {}

    candidate_paths: list[Path] = []
    custom_dir = os.environ.get("BACKLINK_PROJECTS_DIR")
    if custom_dir:
        candidate_paths.append(Path(custom_dir) / f"{proj}.json")
        candidate_paths.append(Path(custom_dir) / f"{proj}.md")

    base_proj_dir = Path(__file__).resolve().parent.parent
    candidate_paths.append(base_proj_dir / "projects" / f"{proj}.json")
    candidate_paths.append(base_proj_dir / "projects" / f"{proj}.md")
    candidate_paths.append(base_proj_dir.parent / "backlink-autofill" / "plugins" / "backlink-autofill" / "references" / "projects" / f"{proj}.md")
    candidate_paths.append(Path.home() / ".backlink-autofill" / "projects" / proj / "profile.json")
    candidate_paths.append(Path.home() / ".backlink-autofill" / "projects" / proj / "assets.json")
    candidate_paths.append(Path.home() / ".backlinkos" / "projects" / f"{proj}.json")

    facts: dict[str, Any] = {}
    for p in candidate_paths:
        if not p.exists():
            continue
        if p.suffix == ".json":
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    if "ai_powered" in data and data["ai_powered"] is not None:
                        facts["ai_powered"] = bool(data["ai_powered"])
                    if "accepts_paid" in data and data["accepts_paid"] is not None:
                        facts["accepts_paid"] = bool(data["accepts_paid"])
            except Exception:
                pass
        elif p.suffix == ".md":
            try:
                text = p.read_text(encoding="utf-8")
                # 1. 严格解析 ai_powered:
                # 只有结合权威审查事实声明（如 reviewed facts 明确不兼容 AI 工具且禁止声称 AI）才确立为 False
                # 单独的禁止声称不能证明 ai_powered=False
                reviewed_incompat_ai = bool(
                    re.search(r"incompatible\s+with\s+this\s+project\s+under\s+the\s+current\s+reviewed\s+facts", text, re.I)
                    and re.search(r"restricted\s+to\s+AI\s+products", text, re.I)
                )
                forbidden_ai = bool(re.search(r"(?:Do\s+not\s+state\s+or\s+imply|Forbidden).*?AI[- ]powered", text, re.I | re.S))
                explicit_non_ai = bool(re.search(r"\bAI[- ]powered\s*:\s*(?:false|no)\b", text, re.I))
                explicit_ai = bool(re.search(r"\bAI[- ]powered\s*:\s*(?:true|yes)\b", text, re.I))

                if explicit_non_ai or (reviewed_incompat_ai and forbidden_ai):
                    facts["ai_powered"] = False
                elif explicit_ai:
                    facts["ai_powered"] = True
                # 否则保持未知 None，不盲目猜测

                # 2. 严格解析 accepts_paid:
                # 只有显式声明政策才确立布尔值，“没有付费预算配置”绝对不能推断为 accepts_paid=False
                explicit_no_paid = bool(
                    re.search(r"\baccepts?[-_ ]paid\s*:\s*(?:false|no)\b", text, re.I)
                    or re.search(r"(?:policy|政策).*?(?:仅限免费|不接受付费|只提交免费|free\s+submissions?\s+only|no\s+paid\s+listings?)", text, re.I)
                )
                explicit_paid = bool(
                    re.search(r"\baccepts?[-_ ]paid\s*:\s*(?:true|yes)\b", text, re.I)
                    or re.search(r"(?:policy|政策).*?(?:接受付费|有付费预算|paid\s+listings?\s+accepted)", text, re.I)
                )
                if explicit_no_paid:
                    facts["accepts_paid"] = False
                elif explicit_paid:
                    facts["accepts_paid"] = True
                # 否则保持未知 None，不盲目猜测
            except Exception:
                pass

        if "ai_powered" in facts and "accepts_paid" in facts:
            break

    return facts


def resolve_project_context(project_id: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """通用项目上下文解析器。返回项目上下文 dict，严禁硬编码任何具体项目名称。
    
    规则约束：
    1. 显式传入的 context 优先；
    2. 未指定属性通过 load_project_profile_facts 自动加载权威事实；
    3. 缺失或证据不足时保持未知 (None)，严禁猜测否定。
    """
    resolved = dict(context or {})
    proj = str(project_id or "").strip()
    if not proj:
        return resolved

    if "ai_powered" not in resolved or "accepts_paid" not in resolved:
        profile_facts = load_project_profile_facts(proj)
        for k, v in profile_facts.items():
            if k not in resolved and v is not None:
                resolved[k] = v

    return resolved


def get_persisted_paid_incompatibility(
    master_row: dict[str, Any],
    project_context: dict[str, Any] | None = None,
) -> tuple[bool, str, str]:
    """纯数据库/内存逻辑：判断已有 Master 记录与当前项目是否存在已持久化的付费限制不兼容事实。
    
    硬约束：
    1. 绝对不发起任何网络请求；
    2. 只有当当前项目明确声明 accepts_paid is False 时才进行排除；
    3. 若 accepts_paid 未知 (None) 或为 True，绝对不排除 (UNKNOWN -> INCLUDE，返回 False)；
    4. 只有总表明确证实为非免费 (实测免费 == '非免费' 或明确纯付费/paid-only 且无免费收录通道) 才生效。
    
    返回: (is_incompatible, evidence_text, reason)
    """
    p_ctx = resolve_project_context("", project_context)
    if p_ctx.get("accepts_paid") is False:
        m_free = str(master_row.get("实测免费") or "").strip()
        if m_free == "非免费":
            return True, "非免费", "总表已持久化实测非免费，与当前项目明确不接受付费政策不兼容"

        restriction = str(master_row.get("实测限制") or master_row.get("限制/要求") or "").strip()
        notes = str(master_row.get("平台备注") or "").strip()
        reason_text = str(master_row.get("基础排除原因") or "").strip()
        persisted_candidates = [restriction, notes, reason_text]

        for text in persisted_candidates:
            if not text:
                continue
            # 若有包容性免费通道声明 (如 "free or paid", "免费或付费", "含免费收录")，跳过
            if re.search(r"\b(?:free\s+or\s+paid|paid\s+or\s+free|含免费|支持免费|有免费)\b", text, re.I):
                continue
            if re.search(r"\b(?:paid[- ]only|纯付费|仅限付费|只接受付费|必须付费|强制付费)\b", text, re.I):
                return True, text, f"总表已持久化付费限制 '{text}'，与当前项目明确不接受付费政策不兼容"

    return False, "", ""



# 持久化强限制排他正则：仅用于已持久化且明确的强事实，不能因模糊文案误判
PERSISTED_AI_ONLY_STRONG_PATTERNS = [
    re.compile(r"\b(?:ai[- ]only|only[- ]ai|ai[- ]tools?[- ]only|strictly\s+ai)\b", re.I),
    re.compile(r"\bsolely\s+dedicated\s+to\s+(?:ai|artificial intelligence)\b", re.I),
    re.compile(r"\bexclusively\s+(?:features?|focuses?\s+on|dedicated\s+to|lists?|showcases?|curates?|for)\s+(?:ai|artificial intelligence)\b", re.I),
    re.compile(r"\b(?:we\s+)?(?:only|strictly)\s+accepts?\s+(?:ai|ai[- ]powered|artificial intelligence)\b", re.I),
    re.compile(r"\b(?:products?|tools?|sites?|apps?|startups?|submissions?)\s+must\s+(?:be|use|feature|leverage|incorporate|utilize)\s+(?:an?\s+)?ai\b", re.I),
    re.compile(r"\b(?:non[- ]ai|not\s+(?:utilizing|using|leveraging)\s+ai|without\s+ai)\b.*?\b(?:causes?\s+(?:rejection|denial)|(?:are|will\s+be)\s+rejected|not\s+accepted)\b", re.I),
    re.compile(r"(?:仅接受|仅限|只接受|只收录|仅支持)\s*(?:ai|人工智能)|(?:非\s*ai|非人工智能).*(?:不收|拒绝|不接受)", re.I),
]

# 允许非 AI / SaaS / 通用工具的包容性模式（防误杀 Visalytica 等声明 "AI or SaaS tool" 的平台）
PERSISTED_AI_INCLUSIVE_PATTERNS = [
    re.compile(r'\b(?:ai\s+or\s+(?:saas|software|web|tech|digital|developer|other|tools?|products?|apps?))\b', re.I),
    re.compile(r'\b(?:saas|software|web|tech|digital|developer|other)\s+or\s+ai\b', re.I),
    re.compile(r'\b(?:ai\s*(?:,|/|and)\s*(?:saas|software|digital|tech))\b', re.I),
    re.compile(r'\b(?:ai\s+and\s+non[- ]ai)\b', re.I),
]


def get_persisted_project_incompatibility(
    master_row: dict[str, Any],
    project_context: dict[str, Any] | None = None,
) -> tuple[bool, str, str]:
    """纯数据库/内存逻辑：判断已有 Master 记录与当前项目是否存在已持久化的强不兼容事实。
    
    硬约束：
    1. 绝对不发起任何网络请求；
    2. 绝不依赖运行时 VerifiedEntry.ai_only；
    3. 仅使用已持久化且明确的强事实（实测限制、平台备注、基础排除原因等）；
    4. 证据不足时一律 UNKNOWN -> INCLUDE（返回 False）；
    5. 不能因为“AI directory”、“看起来像 AI 平台”就排除；只有明确排他限制（如“仅接受 AI 工具”、“AI tools only”）才对 ai_powered=False 生效。
    
    返回: (is_incompatible, evidence_text, reason)
    """
    p_ctx = resolve_project_context("", project_context)
    if p_ctx.get("ai_powered") is False:
        # 检查持久化文本：实测限制、限制/要求、平台备注、基础排除原因
        restriction = str(master_row.get("实测限制") or master_row.get("限制/要求") or "").strip()
        notes = str(master_row.get("平台备注") or "").strip()
        reason_text = str(master_row.get("基础排除原因") or "").strip()
        persisted_candidates = [restriction, notes, reason_text]
        
        for candidate_text in persisted_candidates:
            if not candidate_text:
                continue
            # 若包含包容性模式（如 "AI or SaaS"），直接跳过防误杀
            if any(p.search(candidate_text) for p in PERSISTED_AI_INCLUSIVE_PATTERNS):
                continue
            for pat in PERSISTED_AI_ONLY_STRONG_PATTERNS:
                m = pat.search(candidate_text)
                if m:
                    match_str = m.group(0)
                    return True, match_str, f"已持久化强事实明确限制 '{match_str}'，与非 AI 项目不兼容"
                    
    return False, "", ""


def materialize_project_backlog_rows(
    master_rows: list[dict[str, Any]],
    existing_project_rows: list[dict[str, Any]],
    project_id: str,
    target_url: str = "",
    project_context: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """纯内存/数据库级 Project Backlog Projection（项目机会全量投影）。
    
    核心业务契约：
    1. 纯数据库级投影，绝对禁止发起任何网络请求；
    2. 禁止调用 verify_submission_entry / discover_and_verify_entry；
    3. 禁止要求 Master 提交入口非空；
    4. Master 基础状态 == 候选，默认生成 Project Backlog Row（UNKNOWN != REJECT）；
    5. Master 基础状态 == 已排除 或 失效，不创建 Project Row；
    6. 仅依据已持久化强事实拦截项目硬不兼容（get_persisted_project_incompatibility），证据不足（UNKNOWN）一律包含；
    7. project_id + 外链ID 唯一，绝不重复创建，绝不重置状态、尝试次数或覆盖历史执行事实；
    8. 新项目行默认：状态='待提交'，尝试次数='0'，最近操作时间=''，目标URL=target_url，结果链接=''，原因/备注=''，证据摘要=''。
    
    返回: (new_project_rows, stats)
    """
    proj = str(project_id or "").strip()
    if not proj:
        raise ValueError("必须显式指定 project_id")

    p_ctx = resolve_project_context(proj, project_context)
    
    existing_bids: set[str] = set()
    existing_project_count = 0
    for prow in existing_project_rows:
        p_proj = str(prow.get("项目ID") or "").strip()
        if p_proj == proj:
            existing_project_count += 1
            bid = canonical_domain(prow.get("外链ID") or prow.get("外链域名") or "")
            if bid:
                existing_bids.add(bid)
                
    stats: dict[str, Any] = {
        "candidate_count": 0,
        "existing_project_count": existing_project_count,
        "would_create_count": 0,
        "duplicate_preserved_count": 0,
        "master_hard_negative_count": 0,
        "proven_project_incompatible_count": 0,
        "incompatible_details": [],
    }
    
    new_rows: list[dict[str, str]] = []
    seen_in_new: set[str] = set()
    
    for mrow in master_rows:
        raw_id = mrow.get("外链ID") or mrow.get("平台域名") or ""
        cid = canonical_domain(raw_id)
        if not cid:
            continue
            
        status = str(mrow.get("基础状态") or "").strip()
        if status in (MASTER_STATUS_EXCLUDED, MASTER_STATUS_DEAD):
            stats["master_hard_negative_count"] += 1
            continue
        if status != MASTER_STATUS_CANDIDATE:
            continue
            
        stats["candidate_count"] += 1
        
        # 查重：已存在于历史项目行或本批新生成中，绝不重复创建
        if cid in existing_bids or cid in seen_in_new:
            stats["duplicate_preserved_count"] += 1
            continue
            
        # 检查已持久化硬不兼容强事实
        is_incompatible, evidence, reason = get_persisted_project_incompatibility(mrow, p_ctx)
        if is_incompatible:
            stats["proven_project_incompatible_count"] += 1
            stats["incompatible_details"].append({
                "domain": cid,
                "evidence": evidence,
                "reason": reason,
            })
            continue
            
        # 默认生成待提交 Backlog Row
        row = {
            "项目ID": proj,
            "外链ID": cid,
            "外链域名": cid,
            "状态": PROJECT_STATUS_TO_SUBMIT,
            "尝试次数": "0",
            "最近操作时间": "",
            "目标URL": str(target_url or "").strip(),
            "结果链接": "",
            "原因/备注": "",
            "证据摘要": "",
        }
        new_rows.append(row)
        seen_in_new.add(cid)
        stats["would_create_count"] += 1
        
    return new_rows, stats


def load_scan_ledger_facts(
    project_id: str,
    runtime_dir: str | None = None,
    cooldown_seconds: float = 7 * 86400,
) -> dict[str, dict[str, Any]]:
    """读取已沉淀的 scan_ledger.jsonl，在冷却期内提取可复用的事实。"""
    base_dir = Path(runtime_dir or os.environ.get("BACKLINKOS_RUNTIME_DIR", DEFAULT_BACKLINKOS_RUNTIME_DIR))
    ledger_file = base_dir / "cycles" / project_id / "scan_ledger.jsonl"
    if not ledger_file.exists():
        return {}
    
    facts: dict[str, dict[str, Any]] = {}
    now = time.time()
    try:
        with ledger_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    bid = canonical_domain(entry.get("backlink_id") or entry.get("domain") or "")
                    if not bid:
                        continue

                    # 兼容读取 timestamp / scanned_timestamp / scanned_at (支持 ISO 字符串与 float 戳)
                    ts = None
                    for key in ("scanned_timestamp", "timestamp", "scanned_at"):
                        val = entry.get(key)
                        if val is None:
                            continue
                        if isinstance(val, (int, float)):
                            ts = float(val)
                            break
                        val_str = str(val).strip()
                        if not val_str:
                            continue
                        try:
                            ts = float(val_str)
                            break
                        except ValueError:
                            pass
                        try:
                            dt = datetime.datetime.fromisoformat(val_str.replace("Z", "+00:00"))
                            ts = dt.timestamp()
                            break
                        except Exception:
                            pass

                    if ts is not None and (now - float(ts)) <= cooldown_seconds:
                        facts[bid] = entry
                except Exception:
                    pass
    except Exception as e:
        print(f"[警告] 读取 scan_ledger.jsonl 失败: {e}", file=sys.stderr)
    return facts


def make_scan_ledger_entry(
    domain: str,
    disposition: str,
    reason: str,
    probe_duration_sec: float = 0.0,
    verified_entry_url: str | None = None,
    scanned_timestamp: float | None = None,
    scanned_at: str | None = None,
) -> dict[str, Any]:
    """生成具备完整字段与时间戳的 scan_ledger 条目。
    
    支持显式传入原观察时间 (scanned_timestamp / scanned_at)，复用旧事实时严禁续期。
    """
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    now_ts = time.time()
    cid = canonical_domain(domain)
    eff_ts = float(scanned_timestamp) if scanned_timestamp is not None else now_ts
    eff_at = str(scanned_at) if scanned_at is not None else (
        datetime.datetime.fromtimestamp(eff_ts, datetime.timezone.utc).isoformat() if scanned_timestamp is not None else now_iso
    )
    return {
        "backlink_id": cid or domain,
        "domain": cid or domain,
        "timestamp": now_iso,
        "scanned_timestamp": eff_ts,
        "scanned_at": eff_at,
        "disposition": disposition,
        "reason": reason,
        "probe_duration_sec": round(probe_duration_sec, 3),
        "verified_entry_url": verified_entry_url,
    }


def prepare_execution_batch(
    project_id: str,
    target_ready_count: int,
    scan_limit: int,
    project_rows: list[dict[str, Any]],
    master_rows: list[dict[str, Any]],
    project_context: dict[str, Any] | None = None,
    entry_verifier: Callable[[str, str], tuple[VerifiedEntry | None, str]] | None = None,
    entry_finder: Callable[[str], tuple[VerifiedEntry | None, str]] | None = None,
    fetcher: Callable[[str], dict] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    use_cursor: bool = False,
    runtime_dir: str | None = None,
    use_scan_ledger: bool = True,
    ledger_cooldown_seconds: float = 7 * 86400,
) -> dict[str, Any]:
    """从已有项目 Backlog 中筛选待提交记录，执行有界的现场 Entry 核验，产出 Ready for Autofill 队列。"""
    proj = str(project_id or "").strip()
    if not proj:
        raise ValueError("必须显式指定 project_id")
    if target_ready_count <= 0:
        raise ValueError("target_ready_count 必须为大于 0 的整数")
    if scan_limit <= 0:
        raise ValueError("scan_limit 必须为大于 0 的整数")
    if scan_limit < target_ready_count:
        raise ValueError("scan_limit 不能小于 target_ready_count")

    def _default_verifier(d: str, u: str, negated_entries: set[str] | list[str] | None = None, **kw) -> tuple[VerifiedEntry | None, str]:
        return verify_submission_entry(d, u, fetcher=fetcher, negated_entries=negated_entries)

    def _default_finder(d: str, negated_entries: set[str] | list[str] | None = None, **kw) -> tuple[VerifiedEntry | None, str]:
        return discover_and_verify_entry(d, fetcher=fetcher, negated_entries=negated_entries)

    _verifier = entry_verifier or _default_verifier
    _finder = entry_finder or _default_finder
    p_ctx = resolve_project_context(proj, project_context)
    ledger_facts = load_scan_ledger_facts(proj, runtime_dir=runtime_dir, cooldown_seconds=ledger_cooldown_seconds) if use_scan_ledger else {}

    # 建立 master 映射并记录 _orig_实测限制，确保仅写回新增事实
    master_map: dict[str, dict[str, Any]] = {}
    for mrow in master_rows:
        cid = canonical_domain(mrow.get("外链ID") or mrow.get("平台域名") or "")
        if cid:
            master_map[cid] = mrow
            if "_orig_实测限制" not in mrow:
                mrow["_orig_实测限制"] = mrow.get("实测限制")

    # 筛选当前项目且状态为待提交的候选行
    eligible_project_rows: list[dict[str, Any]] = []
    for prow in project_rows:
        p_proj = str(prow.get("项目ID") or "").strip()
        p_status = str(prow.get("状态") or "").strip()
        if p_proj == proj and p_status == PROJECT_STATUS_TO_SUBMIT:
            eligible_project_rows.append(prow)

    # 游标处理 (从上次 last_scanned_backlink_id 后面继续，到末尾 wrap)
    scan_sequence = eligible_project_rows
    if use_cursor and eligible_project_rows:
        last_id = load_ready_cursor(proj, runtime_dir=runtime_dir)
        if last_id:
            cursor_idx = -1
            for idx, prow in enumerate(eligible_project_rows):
                bid = canonical_domain(prow.get("外链ID") or prow.get("外链域名") or "")
                if bid == last_id:
                    cursor_idx = idx
                    break
            if cursor_idx != -1:
                scan_sequence = eligible_project_rows[cursor_idx + 1:] + eligible_project_rows[:cursor_idx + 1]

    ready_rows: list[dict[str, Any]] = []
    scanned_count = 0
    skipped_incompatible = 0
    failed_verification_count = 0
    orphan_count = 0
    orphan_backlink_ids: list[str] = []
    scanned_backlink_ids: list[str] = []
    scan_ledger_entries: list[dict[str, Any]] = []
    last_scanned_id: str | None = None

    for prow in scan_sequence:
        if len(ready_rows) >= target_ready_count or scanned_count >= scan_limit:
            break

        cid = canonical_domain(prow.get("外链ID") or prow.get("外链域名") or "")
        raw_bid = str(prow.get("外链ID") or prow.get("外链域名") or "").strip()
        bid_key = cid or raw_bid
        if bid_key:
            scanned_backlink_ids.append(bid_key)

        # 每访问一个待提交行，先计入本轮扫描边界并推进游标
        scanned_count += 1
        last_scanned_id = bid_key
        cand_t0 = time.time()

        # 检查是否为 Orphan Row (在 Master Sheet 中不存在对应 row)
        if not cid or cid not in master_map:
            orphan_count += 1
            orphan_id = raw_bid or cid or "unknown"
            orphan_backlink_ids.append(orphan_id)
            scan_ledger_entries.append(make_scan_ledger_entry(
                domain=cid or raw_bid,
                disposition="orphan",
                reason="在 Master Sheet 中缺少对应平台行 (Orphan Row)",
                probe_duration_sec=0.0,
                verified_entry_url=None,
            ))
            if progress_callback:
                progress_callback({
                    "scanned_count": scanned_count,
                    "domain": cid or raw_bid,
                    "outcome": "orphan",
                    "entry_url": None,
                    "ready_count": len(ready_rows),
                    "target_ready_count": target_ready_count,
                    "scan_limit": scan_limit,
                    "orphan_count": orphan_count,
                })
            continue

        mrow = master_map[cid]
        m_status = str(mrow.get("基础状态") or "").strip()
        if m_status != MASTER_STATUS_CANDIDATE:
            scan_ledger_entries.append(make_scan_ledger_entry(
                domain=cid,
                disposition="master_non_candidate",
                reason=f"Master 基础状态为非候选: {m_status}",
                probe_duration_sec=0.0,
                verified_entry_url=None,
            ))
            if progress_callback:
                progress_callback({
                    "scanned_count": scanned_count,
                    "domain": cid,
                    "outcome": "master_non_candidate",
                    "entry_url": None,
                    "ready_count": len(ready_rows),
                    "target_ready_count": target_ready_count,
                    "scan_limit": scan_limit,
                    "orphan_count": orphan_count,
                })
            continue

        # 1. 检查 Master 表已持久化排他限制 (严格复用 get_persisted_project_incompatibility，仅当明确为非 AI 项目时排除)
        is_incompat, ev_text, incomp_reason = get_persisted_project_incompatibility(mrow, p_ctx)
        if is_incompat:
            skipped_incompatible += 1
            scan_ledger_entries.append(make_scan_ledger_entry(
                domain=cid,
                disposition="incompatible_ai_only",
                reason=f"命中总表已持久化排他限制: {incomp_reason}",
                probe_duration_sec=0.0,
                verified_entry_url=None,
            ))
            if progress_callback:
                progress_callback({
                    "scanned_count": scanned_count,
                    "domain": cid,
                    "outcome": "incompatible",
                    "entry_url": None,
                    "ready_count": len(ready_rows),
                    "target_ready_count": target_ready_count,
                    "scan_limit": scan_limit,
                    "orphan_count": orphan_count,
                })
            continue

        # 1.2 检查 Master 表已持久化付费限制 (严格复用 get_persisted_paid_incompatibility，仅当项目明确声明 accepts_paid is False 时排除)
        is_paid_incompat, paid_ev_text, paid_incomp_reason = get_persisted_paid_incompatibility(mrow, p_ctx)
        if is_paid_incompat:
            skipped_incompatible += 1
            scan_ledger_entries.append(make_scan_ledger_entry(
                domain=cid,
                disposition="incompatible_paid_only",
                reason=f"命中总表已持久化付费限制: {paid_incomp_reason}",
                probe_duration_sec=0.0,
                verified_entry_url=None,
            ))
            if progress_callback:
                progress_callback({
                    "scanned_count": scanned_count,
                    "domain": cid,
                    "outcome": "incompatible_paid",
                    "entry_url": None,
                    "ready_count": len(ready_rows),
                    "target_ready_count": target_ready_count,
                    "scan_limit": scan_limit,
                    "orphan_count": orphan_count,
                })
            continue

        # 1.5 查阅 scan_ledger 冷却期复用事实 (落实实施约束 3)
        cached_fact = ledger_facts.get(cid)
        current_entry = str(mrow.get("提交入口") or "").strip()
        if cached_fact and not current_entry:
            c_disp = str(cached_fact.get("disposition") or cached_fact.get("result") or "").strip().lower()
            # 统一枚举映射：支持 no_entry / no_entry_found / unverified_no_form 与 negated / negated_entry
            # 超时项 (probe_timeout) 始终保留为候选，绝不复用跳过
            if c_disp in ("no_entry", "no_entry_found", "negated", "negated_entry", "unverified_no_form"):
                orig_ts = cached_fact.get("scanned_timestamp") or cached_fact.get("timestamp")
                orig_at = cached_fact.get("scanned_at") or cached_fact.get("timestamp")
                scan_ledger_entries.append(make_scan_ledger_entry(
                    domain=cid,
                    disposition=c_disp,
                    reason=f"复用近期账本事实 (冷却期内已记录为 {c_disp}): {cached_fact.get('reason', '')}",
                    probe_duration_sec=0.0,
                    verified_entry_url=None,
                    scanned_timestamp=orig_ts,
                    scanned_at=orig_at,
                ))
                if progress_callback:
                    progress_callback({
                        "scanned_count": scanned_count,
                        "domain": cid,
                        "outcome": "reused_ledger",
                        "entry_url": None,
                        "ready_count": len(ready_rows),
                        "target_ready_count": target_ready_count,
                        "scan_limit": scan_limit,
                        "orphan_count": orphan_count,
                    })
                continue

        # 2. 提取已否定入口
        negated_entries = extract_negated_entries_from_row(mrow)

        current_entry = str(mrow.get("提交入口") or "").strip()
        orig_submission_url = current_entry
        verified_obj: VerifiedEntry | None = None
        verify_reason: str = ""

        # 检查现有入口是否被否定
        neg_norm_set = {normalize_canonical_url(x) for x in negated_entries if normalize_canonical_url(x)}
        cur_norm = normalize_canonical_url(current_entry) if current_entry else ""
        if current_entry and (cur_norm in neg_norm_set or current_entry.rstrip("/") in {x.rstrip("/") for x in negated_entries}):
            verified_obj = None
            verify_reason = f"当前入口已被确认为否定入口: {current_entry}"
            # 否定入口与现有入口完全一致时，清除该提交入口
            mrow["提交入口"] = ""
        elif current_entry:
            # Live Revalidate existing entry
            try:
                verified_obj, verify_reason = _verifier(cid, current_entry, negated_entries=negated_entries)
            except TypeError:
                try:
                    verified_obj, verify_reason = _verifier(cid, current_entry)
                except TypeError:
                    verified_obj, verify_reason = verify_submission_entry(cid, current_entry, fetcher=fetcher, negated_entries=negated_entries)
        else:
            # 现场探测 entry
            try:
                verified_obj, verify_reason = _finder(cid, negated_entries=negated_entries)
            except TypeError:
                try:
                    verified_obj, verify_reason = _finder(cid)
                except TypeError:
                    verified_obj, verify_reason = discover_and_verify_entry(cid, fetcher=fetcher, negated_entries=negated_entries)
            if verified_obj:
                mrow["提交入口"] = verified_obj.url

        if verified_obj:
            # 最终守卫：若交付的入口命中否定入口，强制拒绝
            v_clean = str(verified_obj.url).strip().rstrip("/")
            if v_clean in {x.rstrip("/") for x in negated_entries} or any(v_clean == n.rstrip("/") or v_clean.startswith(n.rstrip("/") + "/") for n in negated_entries):
                verified_obj = None
                verify_reason = f"最终入口命中已否定入口: {v_clean}"

        if verified_obj:
            # 聚合主页 ai_only 约束 (落实 F5: 统一接入 DaemonProbeExecutor 硬预算强杀执行器，严禁慢滴流绕过预算)
            if not verified_obj.ai_only:
                _fetch = fetcher or fetch_page
                cand_budget = 10.0
                for scheme in ("https", "http"):
                    cur_rem = max(0.0, (cand_t0 + cand_budget) - time.time())
                    if cur_rem <= 0.1:
                        break
                    home_url = f"{scheme}://{cid}/"
                    home_timeout = min(3.0, cur_rem)
                    
                    def _do_home_fetch(u=home_url, t=home_timeout):
                        try:
                            return _fetch(u, timeout=t)
                        except TypeError:
                            return _fetch(u)
                    
                    ok, home_res, is_to = DaemonProbeExecutor.execute(_do_home_fetch, timeout=home_timeout)
                    if not ok or is_to or not home_res:
                        continue
                    if isinstance(home_res, dict) and home_res.get("status") == 200:
                        if home_res.get("ai_only_signals"):
                            verified_obj = VerifiedEntry(
                                url=verified_obj.url,
                                domain=verified_obj.domain,
                                evidence_type=verified_obj.evidence_type,
                                evidence_summary=verified_obj.evidence_summary + " [主页核实为仅限AI工具]",
                                form_details=verified_obj.form_details,
                                ai_only=True,
                            )
                            break

            cand_duration = round(time.time() - cand_t0, 2)
            if verified_obj.ai_only:
                # 现场证实 AI-only，记录到 mrow（供后续写入总表）
                mrow["实测限制"] = "仅限AI工具"
                if not mrow.get("最后验证时间"):
                    mrow["最后验证时间"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

                # 严格判断项目兼容性：仅当当前项目明确为非 AI 项目 (ai_powered is False) 时才排除！
                # 若 ai_powered 为 None (属性未知)，绝不主观排除，保留待核实
                if p_ctx.get("ai_powered") is False:
                    skipped_incompatible += 1
                    scan_ledger_entries.append(make_scan_ledger_entry(
                        domain=cid,
                        disposition="incompatible_ai_only",
                        reason="平台仅限AI工具，当前项目明确为非AI项目",
                        probe_duration_sec=cand_duration,
                        verified_entry_url=verified_obj.url,
                    ))
                    if progress_callback:
                        progress_callback({
                            "scanned_count": scanned_count,
                            "domain": cid,
                            "outcome": "incompatible",
                            "entry_url": verified_obj.url,
                            "ready_count": len(ready_rows),
                            "target_ready_count": target_ready_count,
                            "scan_limit": scan_limit,
                            "orphan_count": orphan_count,
                        })
                    continue

            scan_ledger_entries.append(make_scan_ledger_entry(
                domain=cid,
                disposition="ready",
                reason=verify_reason or "现场核验通过",
                probe_duration_sec=cand_duration,
                verified_entry_url=verified_obj.url,
            ))
            ready_rows.append({
                "project_row": dict(prow),
                "master_row": dict(mrow),
                "orig_submission_url": orig_submission_url,
                "verified_entry": verified_obj,
                "verify_reason": verify_reason,
            })
        else:
            # 核验失败 / unresolved:
            # 项目行仍然存在，状态仍然待提交，尝试次数仍然 0，不得标记为失败或不适用
            failed_verification_count += 1
            cand_duration = round(time.time() - cand_t0, 2)
            vr_lower = verify_reason.lower()
            if "超时" in verify_reason or "timeout" in vr_lower:
                disp = "probe_timeout"
            elif "不可达" in verify_reason or "unreachable" in vr_lower:
                disp = "site_unreachable"
            elif "已否定" in verify_reason or "negated" in vr_lower:
                disp = "negated_entry"
            else:
                disp = "no_entry_found"
            scan_ledger_entries.append(make_scan_ledger_entry(
                domain=cid,
                disposition=disp,
                reason=verify_reason or "未能定位可操作提交入口，保持候选",
                probe_duration_sec=cand_duration,
                verified_entry_url=None,
            ))

        if progress_callback:
            outcome = "ready" if (verified_obj and not (verified_obj.ai_only and p_ctx.get("ai_powered") is False)) else ("incompatible" if (verified_obj and verified_obj.ai_only) else "unresolved")
            progress_callback({
                "scanned_count": scanned_count,
                "domain": cid,
                "outcome": outcome,
                "entry_url": verified_obj.url if verified_obj else None,
                "ready_count": len(ready_rows),
                "target_ready_count": target_ready_count,
                "scan_limit": scan_limit,
                "orphan_count": orphan_count,
            })

    # 扫描结束保存本地原子游标
    if use_cursor and last_scanned_id:
        save_ready_cursor(proj, last_scanned_id, runtime_dir=runtime_dir)

    return {
        "ready_rows": ready_rows,
        "updated_master_rows": master_rows,
        "ready_count": len(ready_rows),
        "scanned_count": scanned_count,
        "scanned_backlink_ids": scanned_backlink_ids,
        "skipped_incompatible": skipped_incompatible,
        "failed_verification_count": failed_verification_count,
        "orphan_count": orphan_count,
        "orphan_backlink_ids": orphan_backlink_ids,
        "scan_ledger_entries": scan_ledger_entries,
    }



def _materialize_verified_project_row(
    master_row: dict[str, Any],
    existing_project_rows: list[dict[str, Any]],
    project_id: str,
    verified_entry: VerifiedEntry,
    target_url: str = "",
    project_context: dict[str, Any] | None = None,
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

    # P0-3 通用项目兼容性硬门禁 (Project Compatibility Hard Gate)
    # 对 ai_only 平台：只有 ai_powered == True 才允许；False 或 missing/unknown 均 fail closed
    p_ctx = resolve_project_context(proj, project_context)
    if verified_entry.ai_only:
        if p_ctx.get("ai_powered") is not True:
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
    project_context: dict[str, Any] | None = None,
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
    4. 保证 project_id + backlink_id 唯一，保留已有项目行状态，不重复创建；
    5. P0-3: 检查项目通用兼容性上下文 (Project Compatibility Hard Gate)。
    
    返回: 新行 dict，若核验不通过或不满足唯一性/兼容性条件则返回 None
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

    # 聚合平台约束：homepage ai_only_signals + verified entry page ai_only_signals
    # 无论 entry_finder 路径还是 existing Master entry + entry_verifier 路径，语义必须一致
    if not verified_obj.ai_only:
        _fetch = fetcher or fetch_page
        for scheme in ("https", "http"):
            home_res = _fetch(f"{scheme}://{backlink_id}/")
            if home_res and home_res.get("status") == 200:
                if home_res.get("ai_only_signals"):
                    verified_obj = VerifiedEntry(
                        url=verified_obj.url,
                        domain=verified_obj.domain,
                        evidence_type=verified_obj.evidence_type,
                        evidence_summary=verified_obj.evidence_summary,
                        form_details=verified_obj.form_details,
                        ai_only=True,
                    )
                break

    return _materialize_verified_project_row(
        master_row=master_row,
        existing_project_rows=existing_project_rows,
        project_id=proj,
        verified_entry=verified_obj,
        target_url=target_url,
        project_context=project_context,
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
    project_context: dict[str, Any] | None = None,
    fetcher: Callable[[str], dict] | None = None,
) -> dict[str, Any]:
    """对候选进行批次 Readiness 准备（向后兼容薄包装器，现已全面委托 prepare_execution_batch）。
    
    架构演进契约（P0-3）：
    1. Project Backlog 行已在 Phase B (project_backlog_projection) 中全量投影，
       因此本函数严禁新建任何项目持久化行，new_project_rows 必须永远返回空列表 []；
    2. 若 existing_project_rows 未包含当前项目的待提交行（例如老单元测试传入空列表），
       为保持向后兼容，基于 master_rows 中未在 existing_project_rows 出现的候选构建内存临时行委托执行；
    3. 返回结构保持向后兼容：
       {
           'hydrated_master_rows': master_rows,
           'new_project_rows': [],
           'ready_rows': ready_rows,
           'succeeded_count': ready_count,
           'processed_candidates': scanned_count,
           'skipped_incompatible': skipped_incompatible,
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

    # 检查 existing_project_rows 是否有对应项目的待提交候选
    p_rows = existing_project_rows
    has_proj_candidates = any(
        str(r.get("项目ID") or "").strip() == proj and str(r.get("状态") or "").strip() == PROJECT_STATUS_TO_SUBMIT
        for r in existing_project_rows
    )
    if not has_proj_candidates:
        existing_bids = {
            canonical_domain(r.get("外链ID") or r.get("外链域名") or "")
            for r in existing_project_rows
            if str(r.get("项目ID") or "").strip() == proj
        }
        p_rows = [
            {
                "项目ID": proj,
                "外链ID": canonical_domain(mrow.get("外链ID") or mrow.get("平台域名") or ""),
                "外链域名": canonical_domain(mrow.get("外链ID") or mrow.get("平台域名") or ""),
                "状态": PROJECT_STATUS_TO_SUBMIT,
                "尝试次数": "0",
            }
            for mrow in master_rows
            if str(mrow.get("基础状态") or "").strip() == MASTER_STATUS_CANDIDATE
            and canonical_domain(mrow.get("外链ID") or mrow.get("平台域名") or "") not in existing_bids
        ]

    ready_res = prepare_execution_batch(
        master_rows=master_rows,
        project_rows=p_rows,
        project_id=proj,
        target_ready_count=target_count,
        scan_limit=scan_limit,
        entry_verifier=entry_verifier,
        entry_finder=entry_finder,
        project_context=project_context,
        fetcher=fetcher,
    )

    return {
        "hydrated_master_rows": ready_res["updated_master_rows"],
        "new_project_rows": [],  # 严禁新建项目持久化行
        "ready_rows": ready_res["ready_rows"],
        "succeeded_count": ready_res["ready_count"],
        "processed_candidates": ready_res["scanned_count"],
        "skipped_incompatible": ready_res["skipped_incompatible"],
    }


# ==========================================
# 6. 排除分类与跨项目同步 (Cross-Project Exclusion Sync)
# ==========================================

class ExclusionScope:
    GLOBAL_UNAVAILABLE = "GLOBAL_UNAVAILABLE"      # 平台级全局不可用：死站、关闭收录、全量禁止等 -> 总表已排除/失效，传播给其他项目待提交
    PROJECT_INCOMPATIBLE = "PROJECT_INCOMPATIBLE"  # 项目特定不兼容：如仅限AI产品，而当前项目非AI -> 仅当前项目不适用，总表记事实，其他项目不排除
    PAID_ONLY = "PAID_ONLY"                        # 付费平台：总表记录实测非免费事实，各项目依自身付费政策决定是否排除
    UNKNOWN_TEMPORARY = "UNKNOWN_TEMPORARY"        # 未知/暂时性问题：超时、未找到入口、读取不完整 -> 保持候选，绝不永久排除


_GLOBAL_UNAVAILABLE_KEYWORDS = [
    "关闭收录", "停止收录", "不再接受", "停止接受", "关闭提交", "停止提交",
    "域名出售", "域名过期", "永久下线", "停止运营", "服务终止", "网站关闭",
    "dead", "closed", "shut down", "out of business", "domain for sale",
    "no longer accepting", "submissions closed", "permanently closed",
    "nxdomain", "dns failure", "dns failed", "死站"
]


def classify_exclusion(
    status: str,
    reason: str = "",
    limits: str = "",
    free_status: str = "",
) -> str:
    """根据已有明确证据和适用范围准确识别排除适用性分类。
    
    1. GLOBAL_UNAVAILABLE: 平台彻底关闭收录、域名过期、永久死站等对所有项目成立的禁止条件；
    2. PROJECT_INCOMPATIBLE: 平台仅收录特定类型（如 AI-only），仅针对不兼容项目成立；
    3. PAID_ONLY: 平台仅支持付费收录，由各项目的免费/付费政策分别决定；
    4. UNKNOWN_TEMPORARY: 未找到入口、网络超时、读取不完整、状态不明确，绝不能作为永久排除理由。
    """
    s = str(status or "").strip()
    r = str(reason or "").strip().lower()
    lim = str(limits or "").strip().lower()
    free = str(free_status or "").strip()

    # 1. 临时或未知情况：超时、未找到入口、读取不完整
    if any(k in r for k in ["未找到入口", "找不到入口", "超时", "timeout", "未解决", "unresolved", "读取不完整"]):
        return ExclusionScope.UNKNOWN_TEMPORARY

    # 2. 项目特定限制（如 AI-only）
    if "ai-only" in lim or "仅限ai" in lim or "ai only" in lim or "ai-only" in r or "仅限ai" in r:
        return ExclusionScope.PROJECT_INCOMPATIBLE

    # 3. 付费-only
    if free == "非免费" or "付费" in r or "paid only" in r or "收费" in r:
        return ExclusionScope.PAID_ONLY

    # 4. 全局不可用事实
    if s in (MASTER_STATUS_EXCLUDED, MASTER_STATUS_DEAD):
        for kw in _GLOBAL_UNAVAILABLE_KEYWORDS:
            if kw in r:
                return ExclusionScope.GLOBAL_UNAVAILABLE
        if s == MASTER_STATUS_DEAD:
            return ExclusionScope.GLOBAL_UNAVAILABLE
        if s == MASTER_STATUS_EXCLUDED and not ("ai" in r or "付费" in r):
            return ExclusionScope.GLOBAL_UNAVAILABLE

    return ExclusionScope.UNKNOWN_TEMPORARY


def sync_global_exclusions_across_projects(
    master_rows: list[dict[str, Any]],
    project_rows: list[dict[str, Any]],
    target_backlink_ids: list[str] | set[str] | None = None,
    now_iso: str | None = None,
    exclude_project_id: str | None = None,
) -> dict[str, Any]:
    """计算跨项目全局排除同步变更明细。
    
    规则：
    1. 仅针对经确认的平台级全局不可用事实（GLOBAL_UNAVAILABLE）；
    2. 根据稳定的项目 ID + 外链 ID 定位；
    3. 写前核实当前状态：严格仅允许同步尚未开始的“待提交”记录；
    4. 绝不覆盖已提交、审核中、已排期、已上线、处理中、需人工等任何历史或中间状态；
    5. 绝不复制源项目的项目专属限制、项目素材、结果链接或提交结果给其他项目；
    6. 返回精确变更列表与保护统计。
    """
    iso_time = now_iso or datetime.datetime.now(datetime.timezone.utc).isoformat()
    target_filter = {canonical_domain(b) for b in target_backlink_ids} if target_backlink_ids else None

    # 建立 master 映射
    master_map: dict[str, dict[str, Any]] = {}
    for m in master_rows:
        cid = canonical_domain(m.get("外链ID") or m.get("平台域名") or "")
        if cid:
            master_map[cid] = m

    planned_mutations: list[dict[str, Any]] = []
    skipped_historical: list[dict[str, Any]] = []
    affected_projects: set[str] = set()
    skipped_projects: set[str] = set()

    for prow in project_rows:
        bid = canonical_domain(prow.get("外链ID") or prow.get("外链域名") or "")
        if not bid:
            continue
        if target_filter is not None and bid not in target_filter:
            continue

        p_proj = str(prow.get("项目ID") or "").strip()
        if exclude_project_id and p_proj == exclude_project_id:
            continue

        mrow = master_map.get(bid)
        if not mrow:
            continue

        m_status = str(mrow.get("基础状态") or "").strip()
        m_reason = str(mrow.get("基础排除原因") or "").strip()
        m_limits = str(mrow.get("实测限制") or mrow.get("平台备注") or "").strip()
        m_free = str(mrow.get("实测免费") or "").strip()

        scope = classify_exclusion(m_status, m_reason, m_limits, m_free)
        if scope != ExclusionScope.GLOBAL_UNAVAILABLE:
            continue

        # 平台级全局不可用
        p_proj = str(prow.get("项目ID") or "").strip()
        p_status = str(prow.get("状态") or "").strip()

        # 写前核实当前状态：必须精确等于待提交
        if p_status != PROJECT_STATUS_TO_SUBMIT:
            skipped_historical.append({
                "project_id": p_proj,
                "backlink_id": bid,
                "current_status": p_status,
                "reason": f"保护历史状态 {p_status}，禁止修改",
            })
            skipped_projects.add(p_proj)
            continue

        # 构造安全同步 mutation
        if m_status == MASTER_STATUS_EXCLUDED:
            target_status = "不适用"
            target_reason = f"平台级不可用：总表已排除（{m_reason}）" if m_reason else "平台级不可用：总表已排除"
        else:
            target_status = "失败"
            target_reason = f"平台级不可用：总表已失效（{m_reason}）" if m_reason else "平台级不可用：总表已失效"

        evidence_summary = f"[跨项目全局排除同步: {target_reason}]"

        mutation = {
            "project_id": p_proj,
            "backlink_id": bid,
            "original_row": prow,
            "master_row": dict(mrow),
            "sheet_row_num": prow.get("_sheet_row_num"),
            "proposed_fields": {
                "状态": target_status,
                "最近操作时间": iso_time,
                "结果链接": "",  # 严禁复制其他项目结果链接
                "原因/备注": target_reason,
                "证据摘要": evidence_summary,
            },
        }
        planned_mutations.append(mutation)
        affected_projects.add(p_proj)

    return {
        "ok": True,
        "planned_mutations": planned_mutations,
        "mutated_count": len(planned_mutations),
        "skipped_historical_count": len(skipped_historical),
        "skipped_historical": skipped_historical,
        "affected_projects": sorted(affected_projects),
        "skipped_projects": sorted(skipped_projects),
    }


def _get_production_gate():
    """动态获取 ProductionSheetGate 门禁类，支持多种安装路径与环境。"""
    try:
        from execution_state import ProductionSheetGate, EvidenceContractError
        return ProductionSheetGate, EvidenceContractError
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
        from execution_state import ProductionSheetGate, EvidenceContractError
        return ProductionSheetGate, EvidenceContractError
    except Exception:
        return None, None


def _col_idx_to_letter(col_idx: int) -> str:
    """0-indexed column number to Excel column letters (0->A, 25->Z, 26->AA)."""
    result = ""
    col_idx += 1
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        result = chr(65 + remainder) + result
    return result


def execute_cross_project_sync_mutations(
    sheets_service,
    spreadsheet_id: str,
    project_sheet_name: str,
    project_header: list[str],
    planned_mutations: list[dict[str, Any]],
    commit: bool = False,
    runtime_dir: str | None = None,
) -> dict[str, Any]:
    """实际执行跨项目同步写回并回读验证 (落实 R5 与 R6 修复)。
    
    安全契约规则：
    1. 写前通过 API 读取当前整行，严格核实 (项目ID == p_id AND 外链ID == b_id AND 状态 == '待提交')，杜绝行移位误写；
    2. 真实调用 ProductionSheetGate.validate_cross_project_sync_mutation 门禁校验；
    3. 写入后立即整行回读，校验身份字段与写入值完全匹配；
    4. 待恢复文件 pending_cross_project_sync.json 采用稳定复合键 (project_id::backlink_id) 合并管理，成功项精确移除。
    """
    results: list[dict[str, Any]] = []
    failed_items: list[dict[str, Any]] = []
    base_dir = Path(runtime_dir or os.environ.get("BACKLINKOS_RUNTIME_DIR", DEFAULT_BACKLINKOS_RUNTIME_DIR))
    base_dir.mkdir(parents=True, exist_ok=True)
    pending_path = base_dir / "pending_cross_project_sync.json"

    # 读取并初始化以稳定键为索引的 pending_map
    pending_map: dict[str, dict[str, Any]] = {}
    if pending_path.exists():
        try:
            saved_pending = json.loads(pending_path.read_text(encoding="utf-8"))
            if isinstance(saved_pending.get("pending_map"), dict):
                pending_map = saved_pending["pending_map"]
            elif isinstance(saved_pending.get("failed_items"), list):
                for item in saved_pending["failed_items"]:
                    k = f"{item.get('project_id')}::{canonical_domain(item.get('backlink_id', ''))}"
                    pending_map[k] = item
        except Exception:
            pending_map = {}

    p_id_col = project_header.index("项目ID") if "项目ID" in project_header else 0
    b_id_col = project_header.index("外链ID") if "外链ID" in project_header else 1
    status_col = project_header.index("状态") if "状态" in project_header else 2
    time_col = project_header.index("最近操作时间") if "最近操作时间" in project_header else -1
    res_url_col = project_header.index("结果链接") if "结果链接" in project_header else -1
    reason_col = project_header.index("原因/备注") if "原因/备注" in project_header else -1
    ev_col = project_header.index("证据摘要") if "证据摘要" in project_header else -1

    gate_cls, gate_err_cls = _get_production_gate()

    for item in planned_mutations:
        p_id = item["project_id"]
        b_id = item["backlink_id"]
        item_key = f"{p_id}::{canonical_domain(b_id)}"
        row_num = item.get("sheet_row_num")
        fields = item["proposed_fields"]
        master_row = item.get("master_row") or {}

        if not row_num:
            fail_record = {
                "project_id": p_id,
                "backlink_id": b_id,
                "sheet_row_num": None,
                "proposed_fields": fields,
                "master_row": master_row,
                "error": "缺少 sheet_row_num，无法精确定位",
            }
            failed_items.append(fail_record)
            pending_map[item_key] = fail_record
            continue

        try:
            # 写前重新核实：通过 API 读取当前整行
            get_res = sheets_service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=f"'{project_sheet_name}'!A{row_num}:J{row_num}",
            ).execute()
            cur_vals = get_res.get("values", [[]])[0]

            cur_p_id = cur_vals[p_id_col].strip() if p_id_col < len(cur_vals) else ""
            cur_b_id = cur_vals[b_id_col].strip() if b_id_col < len(cur_vals) else ""
            cur_status = cur_vals[status_col].strip() if status_col < len(cur_vals) else ""

            # 1. 严格核实行身份（防行移位错杀）
            if cur_p_id != p_id or (canonical_domain(cur_b_id) != canonical_domain(b_id) and cur_b_id != b_id):
                fail_record = {
                    "project_id": p_id,
                    "backlink_id": b_id,
                    "sheet_row_num": row_num,
                    "proposed_fields": fields,
                    "master_row": master_row,
                    "error": f"写前行身份核实失败: 期望 (项目ID={p_id!r}, 外链ID={b_id!r})，实际读取 (项目ID={cur_p_id!r}, 外链ID={cur_b_id!r})，可能发生行移位，拒绝修改",
                }
                failed_items.append(fail_record)
                pending_map[item_key] = fail_record
                continue

            # 2. 严格核实待提交状态
            if cur_status != PROJECT_STATUS_TO_SUBMIT:
                fail_record = {
                    "project_id": p_id,
                    "backlink_id": b_id,
                    "sheet_row_num": row_num,
                    "proposed_fields": fields,
                    "master_row": master_row,
                    "error": f"写前状态核实失败: 当前状态为 {cur_status!r}，非待提交，拒绝覆盖",
                }
                failed_items.append(fail_record)
                pending_map[item_key] = fail_record
                continue

            # 3. 门禁校验 (调用 ProductionSheetGate.validate_cross_project_sync_mutation)
            if gate_cls:
                cur_row_dict = {
                    h: (cur_vals[i].strip() if i < len(cur_vals) else "")
                    for i, h in enumerate(project_header)
                }
                master_row_synth = dict(master_row)
                if "基础状态" not in master_row_synth:
                    master_row_synth["基础状态"] = "已排除" if fields.get("状态") == "不适用" else "失效"
                if "基础排除原因" not in master_row_synth:
                    master_row_synth["基础排除原因"] = fields.get("原因/备注", "")
                
                try:
                    gate_cls.validate_cross_project_sync_mutation(
                        cur_row_dict, master_row_synth, fields
                    )
                except Exception as gate_exc:
                    fail_record = {
                        "project_id": p_id,
                        "backlink_id": b_id,
                        "sheet_row_num": row_num,
                        "proposed_fields": fields,
                        "master_row": master_row,
                        "error": f"门禁拦截: {gate_exc}",
                    }
                    failed_items.append(fail_record)
                    pending_map[item_key] = fail_record
                    continue

            if not commit:
                results.append({
                    "project_id": p_id,
                    "backlink_id": b_id,
                    "sheet_row_num": row_num,
                    "status": "dry_run",
                    "proposed_fields": fields,
                })
                continue

            # 4. commit 模式下批量写回目标单元格
            batch_data = [
                {"range": f"'{project_sheet_name}'!{_col_idx_to_letter(status_col)}{row_num}", "values": [[fields["状态"]]]},
            ]
            if time_col >= 0 and "最近操作时间" in fields:
                batch_data.append({"range": f"'{project_sheet_name}'!{_col_idx_to_letter(time_col)}{row_num}", "values": [[fields["最近操作时间"]]]})
            if res_url_col >= 0 and "结果链接" in fields:
                batch_data.append({"range": f"'{project_sheet_name}'!{_col_idx_to_letter(res_url_col)}{row_num}", "values": [[fields["结果链接"]]]})
            if reason_col >= 0 and "原因/备注" in fields:
                batch_data.append({"range": f"'{project_sheet_name}'!{_col_idx_to_letter(reason_col)}{row_num}", "values": [[fields["原因/备注"]]]})
            if ev_col >= 0 and "证据摘要" in fields:
                batch_data.append({"range": f"'{project_sheet_name}'!{_col_idx_to_letter(ev_col)}{row_num}", "values": [[fields["证据摘要"]]]})

            sheets_service.spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": batch_data},
            ).execute()

            # 5. 写后精确整行回读校验
            read_back = sheets_service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=f"'{project_sheet_name}'!A{row_num}:J{row_num}",
            ).execute()
            rb_vals = read_back.get("values", [[]])[0]
            rb_p_id = rb_vals[p_id_col].strip() if p_id_col < len(rb_vals) else ""
            rb_b_id = rb_vals[b_id_col].strip() if b_id_col < len(rb_vals) else ""
            rb_status = rb_vals[status_col].strip() if status_col < len(rb_vals) else ""
            rb_reason = rb_vals[reason_col].strip() if (reason_col >= 0 and reason_col < len(rb_vals)) else ""

            if (
                rb_p_id != p_id
                or (canonical_domain(rb_b_id) != canonical_domain(b_id) and rb_b_id != b_id)
                or rb_status != fields["状态"]
                or (reason_col >= 0 and "原因/备注" in fields and rb_reason != fields["原因/备注"])
            ):
                fail_record = {
                    "project_id": p_id,
                    "backlink_id": b_id,
                    "sheet_row_num": row_num,
                    "proposed_fields": fields,
                    "master_row": master_row,
                    "error": f"回读校验不匹配: 期望 (状态={fields['状态']!r}, 备注={fields.get('原因/备注')!r})，实读 (状态={rb_status!r}, 备注={rb_reason!r})",
                }
                failed_items.append(fail_record)
                pending_map[item_key] = fail_record
            else:
                results.append({
                    "project_id": p_id,
                    "backlink_id": b_id,
                    "sheet_row_num": row_num,
                    "status": "committed",
                    "readback_status": rb_status,
                })
                # 写入并校验成功，从待恢复集合中精确移除
                pending_map.pop(item_key, None)

        except Exception as exc:
            fail_record = {
                "project_id": p_id,
                "backlink_id": b_id,
                "sheet_row_num": row_num,
                "proposed_fields": fields,
                "master_row": master_row,
                "error": str(exc),
            }
            failed_items.append(fail_record)
            pending_map[item_key] = fail_record

    # 仅在 commit 模式下持久化/清理 pending 文件
    if commit:
        if pending_map:
            pending_data = {
                "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "pending_map": pending_map,
                "failed_items": list(pending_map.values()),
            }
            pending_path.write_text(json.dumps(pending_data, ensure_ascii=False, indent=2), encoding="utf-8")
        elif pending_path.exists():
            try:
                pending_path.unlink()
            except Exception:
                pass

    return {
        "ok": len(failed_items) == 0,
        "committed_count": len(results),
        "failed_count": len(failed_items),
        "results": results,
        "failed_items": failed_items,
        "remaining_pending_count": len(pending_map),
    }


def recover_pending_cross_project_sync(
    sheets_service,
    spreadsheet_id: str,
    project_sheet_name: str,
    project_header: list[str],
    commit: bool = True,
    runtime_dir: str | None = None,
) -> dict[str, Any]:
    """从 pending_cross_project_sync.json 恢复并安全重试未完成的跨项目排除同步 (落实 R6 修复)。"""
    base_dir = Path(runtime_dir or os.environ.get("BACKLINKOS_RUNTIME_DIR", DEFAULT_BACKLINKOS_RUNTIME_DIR))
    pending_path = base_dir / "pending_cross_project_sync.json"
    if not pending_path.exists():
        return {"ok": True, "recovered_count": 0, "message": "No pending cross-project sync"}

    try:
        data = json.loads(pending_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"Failed to read pending file: {exc}"}

    items_to_recover: list[dict[str, Any]] = []
    if isinstance(data.get("pending_map"), dict):
        items_to_recover = list(data["pending_map"].values())
    elif isinstance(data.get("failed_items"), list):
        items_to_recover = data["failed_items"]

    if not items_to_recover:
        try:
            pending_path.unlink()
        except Exception:
            pass
        return {"ok": True, "recovered_count": 0, "message": "Pending sync items empty"}

    planned_mutations: list[dict[str, Any]] = []
    for item in items_to_recover:
        if "project_id" in item and "backlink_id" in item and "proposed_fields" in item:
            planned_mutations.append({
                "project_id": item["project_id"],
                "backlink_id": item["backlink_id"],
                "sheet_row_num": item.get("sheet_row_num"),
                "proposed_fields": item["proposed_fields"],
                "master_row": item.get("master_row") or {},
            })

    if not planned_mutations:
        return {"ok": True, "recovered_count": 0, "message": "No valid planned mutations"}

    return execute_cross_project_sync_mutations(
        sheets_service=sheets_service,
        spreadsheet_id=spreadsheet_id,
        project_sheet_name=project_sheet_name,
        project_header=project_header,
        planned_mutations=planned_mutations,
        commit=commit,
        runtime_dir=runtime_dir,
    )


