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

import datetime
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urljoin, urlparse

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

MASTER_HEADER = [
    "外链ID", "平台域名", "提交入口", "发现来源", "发现时间", "基础状态", "基础排除原因",
    "实测免费", "实测需登录", "实测登录方式", "实测限制", "实测链接属性", "最后验证时间", "平台备注",
]
MASTER_STATUS_CANDIDATE = "候选"
MASTER_STATUS_EXCLUDED = "已排除"
MASTER_STATUS_DEAD = "失效"
VALID_MASTER_STATUSES = {MASTER_STATUS_CANDIDATE, MASTER_STATUS_EXCLUDED, MASTER_STATUS_DEAD}
PROTECTED_FACT_COLUMNS = ["实测免费", "实测需登录", "实测登录方式", "实测限制", "实测链接属性", "最后验证时间"]
PROJECT_HEADER = ["项目ID", "外链ID", "外链域名", "状态", "尝试次数", "最近操作时间", "目标URL", "结果链接", "原因/备注", "证据摘要"]
PROJECT_STATUS_TO_SUBMIT = "待提交"
VALID_PROJECT_STATUSES = {"待提交", "处理中", "已提交", "审核中", "已排期", "已上线", "需人工", "失败", "不适用"}

INVALID_ENTRY_PATH_PATTERNS = [
    re.compile(r"/(pricing|plans|billing|checkout|cart|subscribe|buy|pricing-plans)(/|$)", re.I),
    re.compile(r"/(terms|privacy|tos|policy|disclaimer|legal|terms-of-service|privacy-policy)(/|$)", re.I),
    re.compile(r"/(category|categories|sub-category|tag|tags|topic|topics|archive|feed)(/|$)", re.I),
    re.compile(r"/(report|seo-report|audit|analyze|stats|analytics|uptime|whois)(/|$)", re.I),
    re.compile(r"/(sitemap|xmlrpc|feed|atom|rss)(/|$)", re.I),
]
DASHBOARD_PATH_RE = re.compile(r"/(?:app/)?(?:dashboard|overview|console|admin|portal)(?:/|$)", re.I)
HOMEPAGE_EXPLICIT_CTA_PATTERNS = [
    re.compile(r"\b(?:submit|add|list|register)\s+(?:your\s+)?(?:product|tool|startup|site|website|project|app)\b", re.I),
    re.compile(r"\b(?:create|sign\s*up\s+to\s+create)\s+(?:a\s+)?(?:profile|listing|account\s+to\s+list)\b", re.I),
    re.compile(r"\bjoin\s+and\s+submit\b", re.I),
]
AUTH_REDIRECT_PARAMS = {
    "redirect", "redirect_url", "redirect_to", "next", "return", "return_to", "continue", "callback",
    "target", "goto", "dest", "destination", "url",
}


@dataclass(frozen=True)
class VerifiedEntry:
    url: str
    domain: str
    evidence_type: str
    evidence_summary: str
    form_details: dict[str, Any] | None = None
    ai_only: bool = False

    def __post_init__(self):
        if not self.url or not self.domain:
            raise ValueError("VerifiedEntry 必须包含非空的 url 与 domain")


def canonical_domain(raw: str) -> str:
    d = str(raw or "").strip().lower()
    if not d:
        return ""
    if "://" in d or d.startswith("//"):
        try:
            parsed = urlparse(d if "://" in d else "//" + d)
            d = (parsed.hostname or parsed.netloc or "").strip()
        except Exception:
            pass
    elif "/" in d:
        d = d.split("/")[0].strip()
    if ":" in d:
        d = d.split(":")[0].strip()
    if d.startswith("www."):
        d = d[4:]
    return d.rstrip(".")


def submission_entry_policy_guard(url: str, domain: str = "") -> tuple[bool, str]:
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
    for pattern in INVALID_ENTRY_PATH_PATTERNS:
        if pattern.search(path):
            return False, f"命中排除路径规则: {pattern.pattern}"
    if DASHBOARD_PATH_RE.search(path):
        q = (parsed.query or "").lower()
        if not re.search(r'\b(submit|add|listing|new|action=)\b', q):
            return False, f"命中私有控制台排除规则（无提交意图参数）: {path}"
    return True, "通过 Policy Guard"


def verify_homepage_as_entry(home_result: dict) -> tuple[bool, str]:
    text = (home_result.get("title", "") + " " + home_result.get("text_excerpt", "")).lower()
    for pat in HOMEPAGE_EXPLICIT_CTA_PATTERNS:
        if pat.search(text):
            return True, f"首页包含明确提交 CTA: {pat.pattern}"
    return False, "首页未包含明确的提交/收录/建链 CTA，不能拿首页填空"


def check_auth_wall_callback_evidence(req_url: str, final_url: str, domain: str, is_discovered_candidate: bool = False) -> tuple[bool, str]:
    cd = canonical_domain(domain)
    if not cd:
        return False, "域名无效"
    req_ok, req_reason = submission_entry_policy_guard(req_url, domain=cd)
    if not req_ok:
        return False, f"原始请求未通过 Policy Guard: {req_reason}"
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
                if parsed_cb.scheme or parsed_cb.netloc:
                    cb_host = (parsed_cb.hostname or "").lower()
                    if cb_host.startswith("www."):
                        cb_host = cb_host[4:]
                    if cb_host != cd and not cb_host.endswith("." + cd):
                        return False, f"认证跳转回调跨域外部域名: {cb_host} != {cd}"
                    cb_path = (parsed_cb.path or "/").strip()
                else:
                    cb_path = decoded.split("?")[0].strip()
                    if not cb_path.startswith("/"):
                        cb_path = "/" + cb_path
                if cb_path:
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
    return True, f"访问提交入口触发平台认证墙，登录后重定向回提交流程 ({callback_path}): {final_path}"


def evaluate_page_for_actionable_entry(
    page_res: dict[str, Any],
    req_url: str,
    domain: str,
    fetcher: Callable[[str], dict],
    is_discovered_candidate: bool = False,
    allow_cta_follow: bool = True,
) -> tuple[VerifiedEntry | None, str]:
    cd = canonical_domain(domain)
    final_url = page_res.get("final_url") or req_url
    if page_res.get("is_search_page") or ("?q=" in final_url or "?s=" in final_url):
        return None, "页面为搜索结果页，非有效提交入口"
    path = (urlparse(final_url).path or "/").strip()
    is_auth_wall = bool(AUTH_PATH_RE.search(path))
    actionable_forms = page_res.get("actionable_forms") or []
    if actionable_forms:
        top_form = actionable_forms[0]
        summary = f"现场核验通过: 真实可操作提交表单 ({top_form['form_type']}, 字段: {top_form['resource_fields']}, 按钮: {top_form['submit_controls']})"
        return VerifiedEntry(
            url=final_url, domain=cd, evidence_type="actionable_form", evidence_summary=summary,
            form_details=top_form, ai_only=bool(page_res.get("ai_only_signals")),
        ), "现场核验通过 (Actionable Form)"
    if is_auth_wall:
        is_auth_callback, auth_reason = check_auth_wall_callback_evidence(
            req_url=req_url, final_url=final_url, domain=cd, is_discovered_candidate=is_discovered_candidate,
        )
        if is_auth_callback:
            return VerifiedEntry(
                url=req_url, domain=cd, evidence_type="auth_wall_submission", evidence_summary=auth_reason,
                ai_only=bool(page_res.get("ai_only_signals")),
            ), "现场核验通过 (认证墙回调证据)"
        if not is_discovered_candidate and fetcher:
            req_parsed = urlparse(req_url)
            req_path = (req_parsed.path or "/").rstrip("/") or "/"
            reverified_entry: VerifiedEntry | None = None
            reverified_reason = ""
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
                            cb_ok, cb_reason = check_auth_wall_callback_evidence(
                                req_url=req_url, final_url=final_url, domain=cd, is_discovered_candidate=True,
                            )
                            if cb_ok:
                                summary = f"通过首页明确 CTA ('{cta.get('text', 'CTA')}') 重新建立来源证据 -> {cb_reason}"
                                reverified_entry = VerifiedEntry(
                                    url=req_url, domain=cd, evidence_type="auth_wall_submission", evidence_summary=summary,
                                    ai_only=bool(page_res.get("ai_only_signals") or home_res.get("ai_only_signals")),
                                )
                                reverified_reason = "现场核验通过 (通过首页CTA重新建立认证墙来源证据)"
                                break
                            auth_reason = cb_reason
                            break
                    if reverified_entry:
                        break
            if reverified_entry:
                return reverified_entry, reverified_reason
            return None, auth_reason
        return None, auth_reason
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
            sub_verified, sub_reason = evaluate_page_for_actionable_entry(
                page_res=tgt_res, req_url=tgt_url, domain=cd, fetcher=fetcher,
                is_discovered_candidate=True, allow_cta_follow=False,
            )
            if sub_verified:
                combined_summary = f"跟随来源页 CTA ('{tgt_text}') -> {sub_verified.evidence_summary}"
                return VerifiedEntry(
                    url=sub_verified.url, domain=cd, evidence_type=sub_verified.evidence_type,
                    evidence_summary=combined_summary, form_details=sub_verified.form_details,
                    ai_only=bool(sub_verified.ai_only or page_res.get("ai_only_signals")),
                ), f"通过跟随 CTA 闭环入口 ({sub_reason})"
    return None, "页面虽返回 200 但未检测到真实可操作提交表单（Actionable Form）或有效认证墙（拒绝正文文字臆想）"


def verify_submission_entry(
    domain: str,
    entry_url: str,
    fetcher: Callable[[str], dict] | None = None,
    is_discovered_candidate: bool = False,
) -> tuple[VerifiedEntry | None, str]:
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
    allowed_final, final_guard_reason = submission_entry_policy_guard(final_url, domain=cd)
    if not allowed_final:
        return None, f"最终跳转 URL 未通过 Policy Guard: {final_guard_reason}"
    path = (urlparse(final_url).path or "/").strip()
    if path in ("", "/"):
        if res.get("actionable_forms"):
            top_form = res["actionable_forms"][0]
            summary = f"首页内嵌真实可操作提交表单: {top_form['form_type']} (字段: {top_form['resource_fields']}, 控件: {top_form['submit_controls']})"
            return VerifiedEntry(
                url=final_url, domain=cd, evidence_type="homepage_actionable", evidence_summary=summary,
                form_details=top_form, ai_only=bool(res.get("ai_only_signals")),
            ), "首页核验通过 (内嵌表单)"
        cta_links = res.get("submission_cta_links") or []
        for cta in cta_links[:3]:
            tgt_url = cta.get("url")
            tgt_text = cta.get("text") or "CTA"
            if not tgt_url:
                continue
            allowed_tgt, _ = submission_entry_policy_guard(tgt_url, domain=cd)
            if not allowed_tgt:
                continue
            tgt_res = _fetch(tgt_url)
            if tgt_res.get("status") != 200:
                continue
            tgt_final = tgt_res.get("final_url") or tgt_url
            allowed_tgt_final, _ = submission_entry_policy_guard(tgt_final, domain=cd)
            if not allowed_tgt_final:
                continue
            sub_verified, sub_reason = evaluate_page_for_actionable_entry(
                page_res=tgt_res, req_url=tgt_url, domain=cd, fetcher=_fetch,
                is_discovered_candidate=True, allow_cta_follow=False,
            )
            if sub_verified:
                summary = f"跟随首页 CTA ('{tgt_text}') -> {sub_verified.evidence_summary}"
                return VerifiedEntry(
                    url=sub_verified.url, domain=cd, evidence_type=sub_verified.evidence_type,
                    evidence_summary=summary, form_details=sub_verified.form_details,
                    ai_only=bool(sub_verified.ai_only or res.get("ai_only_signals")),
                ), f"通过跟随首页 CTA 闭环子页面入口 ({sub_reason})"
        return None, "首页无 Actionable Form 且未发现可跟随的有效提交 CTA 链接（严禁正文文字臆想为入口）"
    sub_verified, sub_reason = evaluate_page_for_actionable_entry(
        page_res=res, req_url=entry_url, domain=cd, fetcher=_fetch,
        is_discovered_candidate=is_discovered_candidate, allow_cta_follow=True,
    )
    if sub_verified and not sub_verified.ai_only and _fetch:
        for scheme in ("https", "http"):
            home_res = _fetch(f"{scheme}://{cd}/")
            if home_res and home_res.get("status") == 200:
                if home_res.get("ai_only_signals"):
                    sub_verified = VerifiedEntry(
                        url=sub_verified.url, domain=sub_verified.domain, evidence_type=sub_verified.evidence_type,
                        evidence_summary=sub_verified.evidence_summary, form_details=sub_verified.form_details, ai_only=True,
                    )
                break
    return sub_verified, sub_reason


def _probe_evidence_record(url: str, phase: str, result: dict[str, Any], elapsed_ms: int) -> dict[str, Any]:
    status_raw = result.get("status")
    try:
        status = int(status_raw or 0)
    except (TypeError, ValueError):
        status = 0
    error = str(result.get("error") or "").strip()
    timeout_stage = None
    if status == 0 and re.search(r"timeout|timed\s*out", error, re.I):
        # screening_crawler currently preserves the exception text but cannot
        # reliably prove connect-vs-read stage. Do not invent one.
        timeout_stage = "unknown"
    return {
        "url": url,
        "phase": phase,
        "final_url": str(result.get("final_url") or url),
        "status": status,
        "error": error or None,
        "timeout_stage": timeout_stage,
        "elapsed_ms": max(0, int(elapsed_ms)),
    }


def _summarize_probe_failure(records: list[dict[str, Any]]) -> str:
    facts: list[str] = []
    for item in records[:4]:
        url = item.get("url") or "?"
        status = int(item.get("status") or 0)
        error = item.get("error")
        if status > 0:
            facts.append(f"{url} => HTTP {status}")
        elif error:
            facts.append(f"{url} => {error}")
        else:
            facts.append(f"{url} => 未取得 HTTP 响应")
    return "; ".join(facts) if facts else "无可用探测证据"


def discover_and_verify_entry(
    domain: str,
    fetcher: Callable[[str], dict] | None = None,
    max_probes: int = 15,
    evidence_sink: list[dict[str, Any]] | None = None,
) -> tuple[VerifiedEntry | None, str]:
    """真实页面探测提交入口；单请求失败只记录事实，不升级成整站终态。"""
    cd = canonical_domain(domain)
    if not cd:
        return None, "域名无效"
    _fetch = fetcher or fetch_page
    evidence = evidence_sink if evidence_sink is not None else []

    def observed_fetch(url: str, phase: str) -> dict[str, Any]:
        started = time.monotonic()
        try:
            result = _fetch(url)
            if not isinstance(result, dict):
                result = {"url": url, "final_url": url, "status": 0, "error": f"InvalidFetcherResult: {type(result).__name__}"}
        except Exception as exc:
            result = {
                "url": url,
                "final_url": url,
                "status": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
        elapsed_ms = int((time.monotonic() - started) * 1000)
        evidence.append(_probe_evidence_record(url, phase, result, elapsed_ms))
        return result

    home = None
    home_records_start = len(evidence)
    for scheme in ("https", "http"):
        url = f"{scheme}://{cd}/"
        res = observed_fetch(url, "home")
        if res.get("status") == 200:
            home = res
            break
    if not home or home.get("status") != 200:
        for scheme in ("https", "http"):
            url = f"{scheme}://www.{cd}/"
            res = observed_fetch(url, "home")
            if res.get("status") == 200:
                home = res
                break
    if not home or home.get("status") != 200:
        home_records = [x for x in evidence[home_records_start:] if x.get("phase") == "home"]
        return None, f"站点首页未取得 HTTP 200；{_summarize_probe_failure(home_records)}"

    base_url = home.get("final_url") or f"https://{cd}/"
    candidate_urls = list(home.get("candidate_urls") or [])
    for cta in home.get("submission_cta_links") or []:
        u = cta.get("url")
        if u and u not in candidate_urls:
            candidate_urls.append(u)

    probe_targets: list[str] = []
    for u in candidate_urls:
        if u not in probe_targets:
            probe_targets.append(u)
    for cp in COMMON_PATHS:
        u = urljoin(base_url, cp)
        if u not in probe_targets:
            probe_targets.append(u)
    probe_targets = probe_targets[:max_probes]

    def nested_fetch(url: str) -> dict[str, Any]:
        return observed_fetch(url, "nested")

    for target_url in probe_targets:
        allowed, _ = submission_entry_policy_guard(target_url, domain=cd)
        if not allowed:
            continue
        page_res = observed_fetch(target_url, "candidate")
        # Timeout/429/5xx/other unresolved request affects only this candidate.
        # Continue while the bounded candidate list still has items.
        if page_res.get("status") != 200:
            continue
        final_url = page_res.get("final_url") or target_url
        allowed_final, _ = submission_entry_policy_guard(final_url, domain=cd)
        if not allowed_final:
            continue
        is_from_candidate_list = target_url in candidate_urls
        sub_verified, sub_reason = evaluate_page_for_actionable_entry(
            page_res=page_res, req_url=target_url, domain=cd, fetcher=nested_fetch,
            is_discovered_candidate=is_from_candidate_list, allow_cta_follow=True,
        )
        if sub_verified:
            if home and home.get("ai_only_signals") and not sub_verified.ai_only:
                sub_verified = VerifiedEntry(
                    url=sub_verified.url, domain=sub_verified.domain, evidence_type=sub_verified.evidence_type,
                    evidence_summary=sub_verified.evidence_summary, form_details=sub_verified.form_details, ai_only=True,
                )
            return sub_verified, f"通过真实页面探测闭环真实入口 ({sub_reason})"

    if home.get("actionable_forms"):
        top_form = home["actionable_forms"][0]
        return VerifiedEntry(
            url=base_url, domain=cd, evidence_type="homepage_actionable",
            evidence_summary=f"首页内嵌真实表单: {top_form['form_type']} (字段: {top_form['resource_fields']})",
            form_details=top_form, ai_only=bool(home.get("ai_only_signals")),
        ), "通过首页真实表单闭环入口"

    return None, "未定位到用户可提交的入口页（证据缺失，无 Actionable Form 或可跟随的有效提交 CTA，保持候选状态）"


def build_empty_master_row(domain: str) -> dict[str, str]:
    cd = canonical_domain(domain)
    return {col: "" for col in MASTER_HEADER} | {"外链ID": cd, "平台域名": cd, "基础状态": MASTER_STATUS_CANDIDATE}


def upsert_master_rows(existing_rows: list[dict[str, Any]], new_discoveries: list[dict[str, Any]], now_iso: str = "") -> tuple[list[dict[str, Any]], dict[str, int]]:
    stats = {"initial_count": len(existing_rows), "new_inserted": 0, "existing_updated": 0, "existing_preserved": 0, "skipped_excluded_or_dead": 0}
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
    return [master_map[cid] for cid in master_order], stats


def resolve_project_context(project_id: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    return dict(context or {})


PERSISTED_AI_ONLY_STRONG_PATTERNS = [
    re.compile(r"\b(?:ai[- ]only|only[- ]ai|ai[- ]tools?[- ]only|strictly\s+ai)\b", re.I),
    re.compile(r"\bsolely\s+dedicated\s+to\s+(?:ai|artificial intelligence)\b", re.I),
    re.compile(r"\bexclusively\s+(?:features?|focuses?\s+on|dedicated\s+to|lists?|showcases?|curates?|for)\s+(?:ai|artificial intelligence)\b", re.I),
    re.compile(r"\b(?:we\s+)?(?:only|strictly)\s+accepts?\s+(?:ai|ai[- ]powered|artificial intelligence)\b", re.I),
    re.compile(r"\b(?:products?|tools?|sites?|apps?|startups?|submissions?)\s+must\s+(?:be|use|feature|leverage|incorporate|utilize)\s+(?:an?\s+)?ai\b", re.I),
    re.compile(r"\b(?:non[- ]ai|not\s+(?:utilizing|using|leveraging)\s+ai|without\s+ai)\b.*?\b(?:causes?\s+(?:rejection|denial)|(?:are|will\s+be)\s+rejected|not\s+accepted)\b", re.I),
    re.compile(r"(?:仅接受|仅限|只接受|只收录|仅支持)\s*(?:ai|人工智能)\s*(?:工具|产品|项目)?(?:\b|$)|(?:非\s*ai|非人工智能).*(?:不收|拒绝|不接受)", re.I),
]
PERSISTED_AI_INCLUSIVE_PATTERNS = [
    re.compile(r'\b(?:ai\s+or\s+(?:saas|software|web|tech|digital|developer|other|tools?|products?|apps?))\b', re.I),
    re.compile(r'\b(?:saas|software|web|tech|digital|developer|other)\s+or\s+ai\b', re.I),
    re.compile(r'\b(?:ai\s*(?:,|/|and)\s*(?:saas|software|digital|tech))\b', re.I),
    re.compile(r'\b(?:ai\s+and\s+non[- ]ai)\b', re.I),
]


def get_persisted_project_incompatibility(master_row: dict[str, Any], project_context: dict[str, Any] | None = None) -> tuple[bool, str, str]:
    p_ctx = resolve_project_context("", project_context)
    if p_ctx.get("ai_powered") is False:
        restriction = str(master_row.get("实测限制") or master_row.get("限制/要求") or "").strip()
        notes = str(master_row.get("平台备注") or "").strip()
        reason_text = str(master_row.get("基础排除原因") or "").strip()
        for candidate_text in [restriction, notes, reason_text]:
            if not candidate_text:
                continue
            if any(p.search(candidate_text) for p in PERSISTED_AI_INCLUSIVE_PATTERNS):
                continue
            for pat in PERSISTED_AI_ONLY_STRONG_PATTERNS:
                m = pat.search(candidate_text)
                if m:
                    match_str = m.group(0)
                    return True, match_str, f"已持久化强事实明确限制 '{match_str}'，与非 AI 项目不兼容"
    return False, "", ""


def materialize_project_backlog_rows(
    master_rows: list[dict[str, Any]], existing_project_rows: list[dict[str, Any]], project_id: str,
    target_url: str = "", project_context: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
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
        "candidate_count": 0, "existing_project_count": existing_project_count, "would_create_count": 0,
        "duplicate_preserved_count": 0, "master_hard_negative_count": 0, "proven_project_incompatible_count": 0,
        "incompatible_details": [],
    }
    new_rows: list[dict[str, str]] = []
    seen_in_new: set[str] = set()
    for mrow in master_rows:
        cid = canonical_domain(mrow.get("外链ID") or mrow.get("平台域名") or "")
        if not cid:
            continue
        status = str(mrow.get("基础状态") or "").strip()
        if status in (MASTER_STATUS_EXCLUDED, MASTER_STATUS_DEAD):
            stats["master_hard_negative_count"] += 1
            continue
        if status != MASTER_STATUS_CANDIDATE:
            continue
        stats["candidate_count"] += 1
        if cid in existing_bids or cid in seen_in_new:
            stats["duplicate_preserved_count"] += 1
            continue
        is_incompatible, evidence, reason = get_persisted_project_incompatibility(mrow, p_ctx)
        if is_incompatible:
            stats["proven_project_incompatible_count"] += 1
            stats["incompatible_details"].append({"domain": cid, "evidence": evidence, "reason": reason})
            continue
        row = {
            "项目ID": proj, "外链ID": cid, "外链域名": cid, "状态": PROJECT_STATUS_TO_SUBMIT,
            "尝试次数": "0", "最近操作时间": "", "目标URL": str(target_url or "").strip(),
            "结果链接": "", "原因/备注": "", "证据摘要": "",
        }
        new_rows.append(row)
        seen_in_new.add(cid)
        stats["would_create_count"] += 1
    return new_rows, stats


def prepare_execution_batch(
    master_rows: list[dict[str, Any]],
    project_rows: list[dict[str, Any]],
    project_id: str,
    target_ready_count: int = 10,
    scan_limit: int = 50,
    entry_verifier: Callable[[str, str], tuple[VerifiedEntry | None, str]] | None = None,
    entry_finder: Callable[[str], tuple[VerifiedEntry | None, str]] | None = None,
    project_context: dict[str, Any] | None = None,
    fetcher: Callable[[str], dict] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    use_cursor: bool = False,
    runtime_dir: str | None = None,
) -> dict[str, Any]:
    proj = str(project_id or "").strip()
    if not proj:
        raise ValueError("必须显式指定 project_id")
    if target_ready_count <= 0:
        raise ValueError("target_ready_count 必须为大于 0 的整数")
    if scan_limit <= 0:
        raise ValueError("scan_limit 必须为大于 0 的整数")
    if scan_limit < target_ready_count:
        raise ValueError("scan_limit 不能小于 target_ready_count")

    _verifier = entry_verifier or (lambda d, u: verify_submission_entry(d, u, fetcher=fetcher))
    p_ctx = resolve_project_context(proj, project_context)
    master_map: dict[str, dict[str, Any]] = {}
    for mrow in master_rows:
        cid = canonical_domain(mrow.get("外链ID") or mrow.get("平台域名") or "")
        if cid:
            master_map[cid] = mrow
    eligible_project_rows = [
        prow for prow in project_rows
        if str(prow.get("项目ID") or "").strip() == proj and str(prow.get("状态") or "").strip() == PROJECT_STATUS_TO_SUBMIT
    ]
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
    verification_details: list[dict[str, Any]] = []
    scanned_count = skipped_incompatible = failed_verification_count = orphan_count = 0
    orphan_backlink_ids: list[str] = []
    last_scanned_id: str | None = None

    for prow in scan_sequence:
        if len(ready_rows) >= target_ready_count or scanned_count >= scan_limit:
            break
        cid = canonical_domain(prow.get("外链ID") or prow.get("外链域名") or "")
        raw_bid = str(prow.get("外链ID") or prow.get("外链域名") or "").strip()
        scanned_count += 1
        last_scanned_id = cid or raw_bid
        if not cid or cid not in master_map:
            orphan_count += 1
            orphan_id = raw_bid or cid or "unknown"
            orphan_backlink_ids.append(orphan_id)
            detail = {"domain": cid or raw_bid, "outcome": "orphan", "verify_reason": "Master row missing", "probe_evidence": []}
            verification_details.append(detail)
            if progress_callback:
                progress_callback({
                    "scanned_count": scanned_count, "domain": cid or raw_bid, "outcome": "orphan", "entry_url": None,
                    "ready_count": len(ready_rows), "target_ready_count": target_ready_count, "scan_limit": scan_limit,
                    "orphan_count": orphan_count, "verify_reason": detail["verify_reason"], "probe_evidence": [],
                })
            continue
        mrow = master_map[cid]
        if str(mrow.get("基础状态") or "").strip() != MASTER_STATUS_CANDIDATE:
            detail = {"domain": cid, "outcome": "master_non_candidate", "verify_reason": "Master row is not candidate", "probe_evidence": []}
            verification_details.append(detail)
            if progress_callback:
                progress_callback({
                    "scanned_count": scanned_count, "domain": cid, "outcome": "master_non_candidate", "entry_url": None,
                    "ready_count": len(ready_rows), "target_ready_count": target_ready_count, "scan_limit": scan_limit,
                    "orphan_count": orphan_count, "verify_reason": detail["verify_reason"], "probe_evidence": [],
                })
            continue

        current_entry = str(mrow.get("提交入口") or "").strip()
        verified_obj: VerifiedEntry | None = None
        verify_reason = ""
        probe_evidence: list[dict[str, Any]] = []
        if current_entry:
            verified_obj, verify_reason = _verifier(cid, current_entry)
        else:
            if entry_finder is not None:
                verified_obj, verify_reason = entry_finder(cid)
            else:
                verified_obj, verify_reason = discover_and_verify_entry(cid, fetcher=fetcher, evidence_sink=probe_evidence)
            if verified_obj:
                mrow["提交入口"] = verified_obj.url

        if verified_obj:
            if not verified_obj.ai_only:
                _fetch = fetcher or fetch_page
                for scheme in ("https", "http"):
                    home_res = _fetch(f"{scheme}://{cid}/")
                    if home_res and home_res.get("status") == 200:
                        if home_res.get("ai_only_signals"):
                            verified_obj = VerifiedEntry(
                                url=verified_obj.url, domain=verified_obj.domain, evidence_type=verified_obj.evidence_type,
                                evidence_summary=verified_obj.evidence_summary, form_details=verified_obj.form_details, ai_only=True,
                            )
                        break
            if verified_obj.ai_only and p_ctx.get("ai_powered") is not True:
                skipped_incompatible += 1
                detail = {"domain": cid, "outcome": "incompatible", "verify_reason": verify_reason, "probe_evidence": probe_evidence}
                verification_details.append(detail)
                if progress_callback:
                    progress_callback({
                        "scanned_count": scanned_count, "domain": cid, "outcome": "incompatible", "entry_url": verified_obj.url,
                        "ready_count": len(ready_rows), "target_ready_count": target_ready_count, "scan_limit": scan_limit,
                        "orphan_count": orphan_count, "verify_reason": verify_reason, "probe_evidence": probe_evidence,
                    })
                continue
            ready_rows.append({
                "project_row": dict(prow), "master_row": dict(mrow), "verified_entry": verified_obj,
                "verify_reason": verify_reason, "probe_evidence": probe_evidence,
            })
            outcome = "ready"
        else:
            failed_verification_count += 1
            outcome = "unresolved"

        detail = {"domain": cid, "outcome": outcome, "verify_reason": verify_reason, "probe_evidence": probe_evidence}
        verification_details.append(detail)
        if progress_callback:
            progress_callback({
                "scanned_count": scanned_count, "domain": cid, "outcome": outcome,
                "entry_url": verified_obj.url if verified_obj else None, "ready_count": len(ready_rows),
                "target_ready_count": target_ready_count, "scan_limit": scan_limit, "orphan_count": orphan_count,
                "verify_reason": verify_reason, "probe_evidence": probe_evidence,
            })

    if use_cursor and last_scanned_id:
        save_ready_cursor(proj, last_scanned_id, runtime_dir=runtime_dir)
    return {
        "ready_rows": ready_rows, "updated_master_rows": master_rows, "ready_count": len(ready_rows),
        "scanned_count": scanned_count, "skipped_incompatible": skipped_incompatible,
        "failed_verification_count": failed_verification_count, "orphan_count": orphan_count,
        "orphan_backlink_ids": orphan_backlink_ids, "verification_details": verification_details,
    }


def _materialize_verified_project_row(
    master_row: dict[str, Any], existing_project_rows: list[dict[str, Any]], project_id: str,
    verified_entry: VerifiedEntry, target_url: str = "", project_context: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    proj = str(project_id or "").strip()
    if not proj:
        return None
    backlink_id = canonical_domain(master_row.get("外链ID") or master_row.get("平台域名") or "")
    if not backlink_id or not isinstance(verified_entry, VerifiedEntry):
        return None
    if canonical_domain(verified_entry.domain) != backlink_id or not verified_entry.url:
        return None
    if str(master_row.get("基础状态") or "").strip() != MASTER_STATUS_CANDIDATE:
        return None
    p_ctx = resolve_project_context(proj, project_context)
    if verified_entry.ai_only and p_ctx.get("ai_powered") is not True:
        return None
    for prow in existing_project_rows:
        if str(prow.get("项目ID") or "").strip() == proj and canonical_domain(prow.get("外链ID") or prow.get("外链域名") or "") == backlink_id:
            return None
    return {
        "项目ID": proj, "外链ID": backlink_id, "外链域名": backlink_id, "状态": PROJECT_STATUS_TO_SUBMIT,
        "尝试次数": "0", "最近操作时间": "", "目标URL": str(target_url or "").strip(), "结果链接": "",
        "原因/备注": "", "证据摘要": f"{verified_entry.evidence_type}: {verified_entry.evidence_summary}",
    }


def materialize_project_row(
    master_row: dict[str, Any], existing_project_rows: list[dict[str, Any]], project_id: str, target_url: str = "",
    entry_url: str = "", fetcher: Callable[[str], dict] | None = None,
    entry_verifier: Callable[[str, str], tuple[VerifiedEntry | None, str]] | None = None,
    entry_finder: Callable[[str], tuple[VerifiedEntry | None, str]] | None = None,
    project_context: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    proj = str(project_id or "").strip()
    if not proj:
        return None
    backlink_id = canonical_domain(master_row.get("外链ID") or master_row.get("平台域名") or "")
    if not backlink_id or str(master_row.get("基础状态") or "").strip() != MASTER_STATUS_CANDIDATE:
        return None
    for prow in existing_project_rows:
        if str(prow.get("项目ID") or "").strip() == proj and canonical_domain(prow.get("外链ID") or prow.get("外链域名") or "") == backlink_id:
            return None
    _verifier = entry_verifier or (lambda d, u: verify_submission_entry(d, u, fetcher=fetcher))
    cand_entry = str(entry_url or master_row.get("提交入口") or "").strip()
    if cand_entry:
        verified_obj, _ = _verifier(backlink_id, cand_entry)
    elif entry_finder is not None:
        verified_obj, _ = entry_finder(backlink_id)
    else:
        verified_obj, _ = discover_and_verify_entry(backlink_id, fetcher=fetcher)
    if not verified_obj:
        return None
    if not verified_obj.ai_only:
        _fetch = fetcher or fetch_page
        for scheme in ("https", "http"):
            home_res = _fetch(f"{scheme}://{backlink_id}/")
            if home_res and home_res.get("status") == 200:
                if home_res.get("ai_only_signals"):
                    verified_obj = VerifiedEntry(
                        url=verified_obj.url, domain=verified_obj.domain, evidence_type=verified_obj.evidence_type,
                        evidence_summary=verified_obj.evidence_summary, form_details=verified_obj.form_details, ai_only=True,
                    )
                break
    return _materialize_verified_project_row(
        master_row=master_row, existing_project_rows=existing_project_rows, project_id=proj,
        verified_entry=verified_obj, target_url=target_url, project_context=project_context,
    )


def batch_hydrate_candidates(
    master_rows: list[dict[str, Any]], existing_project_rows: list[dict[str, Any]], project_id: str,
    target_count: int = 10, scan_limit: int = 30,
    entry_finder: Callable[[str], tuple[VerifiedEntry | None, str]] | None = None,
    entry_verifier: Callable[[str, str], tuple[VerifiedEntry | None, str]] | None = None,
    project_context: dict[str, Any] | None = None, fetcher: Callable[[str], dict] | None = None,
) -> dict[str, Any]:
    proj = str(project_id or "").strip()
    if not proj:
        raise ValueError("必须显式指定 project_id")
    if target_count <= 0:
        raise ValueError("target_count 必须为大于 0 的整数")
    if scan_limit <= 0:
        raise ValueError("scan_limit 必须为大于 0 的整数")
    if scan_limit < target_count:
        raise ValueError("scan_limit 不能小于 target_count")
    p_rows = existing_project_rows
    has_proj_candidates = any(
        str(r.get("项目ID") or "").strip() == proj and str(r.get("状态") or "").strip() == PROJECT_STATUS_TO_SUBMIT
        for r in existing_project_rows
    )
    if not has_proj_candidates:
        existing_bids = {
            canonical_domain(r.get("外链ID") or r.get("外链域名") or "")
            for r in existing_project_rows if str(r.get("项目ID") or "").strip() == proj
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
        master_rows=master_rows, project_rows=p_rows, project_id=proj, target_ready_count=target_count,
        scan_limit=scan_limit, entry_verifier=entry_verifier, entry_finder=entry_finder,
        project_context=project_context, fetcher=fetcher,
    )
    return {
        "hydrated_master_rows": ready_res["updated_master_rows"],
        "new_project_rows": [],
        "ready_rows": ready_res["ready_rows"],
        "succeeded_count": ready_res["ready_count"],
        "processed_candidates": ready_res["scanned_count"],
        "skipped_incompatible": ready_res["skipped_incompatible"],
    }
