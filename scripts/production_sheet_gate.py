#!/usr/bin/env python3
"""BacklinkOS-local implementation of the formal Sheet evidence gate.

The submission orchestrator can run from a clean BacklinkOS checkout without
depending on a user's local backlink-autofill installation.  This module keeps
the shared mutation invariants at the repository boundary; the plugin may
still provide its richer gate implementation when it is installed.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


SHEET_TO_INTERNAL = {
    "待提交": "PENDING",
    "处理中": "IN_PROGRESS",
    "已提交": "SUBMITTED",
    "审核中": "UNDER_REVIEW",
    "已排期": "SCHEDULED",
    "已上线": "LIVE",
    "需人工": "NEEDS_HUMAN",
    "失败": "FAILED",
    "不适用": "NOT_APPLICABLE",
}

FORBIDDEN_RESULT_URL_SEGMENTS = (
    "dashboard",
    "admin",
    "account",
    "edit",
    "payment",
    "checkout",
    "confirm",
    "confirmation",
    "queue",
    "login",
    "signin",
    "auth",
    "setting",
    "settings",
)


class EvidenceContractError(ValueError):
    """Raised when a proposed Sheet mutation lacks direct evidence."""


def sanitize_result_url(
    url: str | None,
    evidence: dict[str, Any] | None = None,
) -> str:
    """Return a public result URL only when positive evidence is present."""
    if not isinstance(url, str) or not url.strip():
        return ""
    raw = url.strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""

    combined = f"{parsed.path.lower()}?{parsed.query.lower()}"
    for segment in FORBIDDEN_RESULT_URL_SEGMENTS:
        pattern = rf"(^|[/_?&=-]){re.escape(segment)}([/_?&=-]|$)"
        if re.search(pattern, combined):
            return ""

    facts = evidence if isinstance(evidence, dict) else {}
    public_access = bool(
        facts.get("public_access_verified", False)
        or (
            facts.get("public_listing_verified", False)
            and facts.get("public_access_verified") is not False
        )
    )
    identity = bool(
        facts.get("listing_identity_verified", False)
        or facts.get("target_identity_verified", False)
        or (
            facts.get("public_listing_verified", False)
            and facts.get("listing_identity_verified") is not False
        )
    )
    return raw if public_access and identity else ""


def _same_origin(host: str, domain: str) -> bool:
    clean_host = host.lower().strip().split(":")[0].strip(".")
    clean_domain = domain.lower().strip().split(":")[0].strip(".")
    if clean_host.startswith("www."):
        clean_host = clean_host[4:]
    if clean_domain.startswith("www."):
        clean_domain = clean_domain[4:]
    return bool(clean_host and clean_domain and (clean_host == clean_domain or clean_host.endswith("." + clean_domain)))


def _evaluate_master_row(
    project_row: dict[str, Any],
    master_rows: list[dict[str, Any]],
) -> tuple[bool, str, str, str | None]:
    project_id = str(project_row.get("外链ID") or "").strip()
    if not project_id:
        return False, "失败", "项目行缺少外链ID", None
    if len(master_rows) == 0:
        return False, "失败", "外链ID在外链总表中不存在", None
    if len(master_rows) > 1:
        return False, "失败", "外链ID在外链总表中不唯一", None

    master = master_rows[0]
    if not isinstance(master, dict):
        return False, "失败", "外链ID在外链总表中不存在", None
    master_id = str(master.get("外链ID") or "").strip()
    if master_id != project_id:
        return False, "失败", f"总表外链ID ({master_id!r}) 与项目外链ID ({project_id!r}) 不匹配", None

    base_status = str(master.get("基础状态") or "").strip()
    if base_status != "候选":
        if base_status == "已排除":
            reason = str(master.get("基础排除原因") or "").strip()
            return False, "不适用", reason or "外链总表基础状态为已排除", None
        if base_status == "失效":
            return False, "失败", "外链总表基础状态为失效", None
        return False, "失败", f"外链总表基础状态非法或未处于候选状态（当前为: {base_status!r}）", None

    platform_domain = str(master.get("平台域名") or "").strip()
    if not platform_domain:
        return False, "失败", "外链总表缺少平台域名", None
    entry_url = str(master.get("提交入口") or "").strip()
    parsed = urlparse(entry_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False, "失败", "缺少有效提交入口", None
    if not _same_origin(parsed.netloc, platform_domain):
        return False, "失败", f"提交入口域名 ({parsed.netloc}) 与外链主平台域名 ({platform_domain}) 不匹配", None
    return True, "待提交", "", entry_url


class ProductionSheetGate:
    """Minimal repository contract used when the plugin is not installed."""

    @staticmethod
    def validate_project_mutation(
        evidence: dict[str, Any],
        proposed: dict[str, Any],
        strict_schedule: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(evidence, dict):
            raise EvidenceContractError("evidence must be a dictionary")
        if not isinstance(proposed, dict):
            raise EvidenceContractError("proposed mutation must be a dictionary")
        status = proposed.get("状态")
        if status not in SHEET_TO_INTERNAL:
            raise EvidenceContractError(f"invalid or missing sheet status: {status!r}")

        raw_url = str(proposed.get("结果链接") or "").strip()
        if raw_url and not sanitize_result_url(raw_url, evidence=evidence):
            raise EvidenceContractError(
                f"REJECTED: 结果链接 {raw_url!r} lacks positive verification (public_access_verified and listing_identity_verified)"
            )

        if status == "已上线":
            public_url = sanitize_result_url(evidence.get("public_listing_url"), evidence=evidence)
            if not evidence.get("public_listing_verified") or not public_url:
                raise EvidenceContractError(
                    "REJECTED: Cannot set status to 已上线 without verified public listing URL"
                )

        scheduled = str(evidence.get("scheduled_date") or "").strip()
        if scheduled and status == "审核中":
            if strict_schedule:
                raise EvidenceContractError(
                    f"REJECTED: Platform has scheduled date {scheduled}; status must be 已排期, not 审核中"
                )
            status = "已排期"

        result = dict(proposed)
        result["状态"] = status
        result["结果链接"] = sanitize_result_url(raw_url, evidence=evidence) if raw_url else ""
        return result

    @staticmethod
    def validate_master_mutation(
        evidence: dict[str, Any],
        prior_facts: dict[str, Any] | None,
        proposed: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(evidence, dict):
            raise EvidenceContractError("evidence must be a dictionary")
        if not isinstance(proposed, dict):
            raise EvidenceContractError("proposed mutation must be a dictionary")

        observed_rel = proposed.get("实测链接属性")
        if observed_rel and not (
            evidence.get("listing_live") is True and evidence.get("live_dom_rel") is not None
        ):
            raise EvidenceContractError(
                f"REJECTED: 实测链接属性 cannot be set to {observed_rel!r} without live listing and inspected DOM rel"
            )

        observed_fields = {
            "实测免费": "free",
            "实测需登录": "requires_login",
            "实测登录方式": "login_method",
            "实测限制": "limits",
            "实测链接属性": "live_dom_rel",
        }
        for field, evidence_key in observed_fields.items():
            if proposed.get(field) and evidence_key not in evidence and field not in evidence:
                raise EvidenceContractError(
                    f"REJECTED: {field} was populated without direct observation in current execution evidence"
                )
        return dict(proposed)

    @staticmethod
    def validate_execution_start(
        project_row: dict[str, Any],
        master_rows: list[dict[str, Any]],
        now_iso: str | None = None,
        resume_same_attempt: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(project_row, dict) or not isinstance(master_rows, list):
            raise EvidenceContractError("project_row and master_rows have invalid types")
        try:
            current_attempt = int(project_row.get("尝试次数") or 0)
        except (TypeError, ValueError):
            current_attempt = 0
        eligible, status, reason, entry_url = _evaluate_master_row(project_row, master_rows)
        current_status = str(project_row.get("状态") or "").strip()
        if not eligible:
            return {
                "ok": True,
                "eligible": False,
                "reason": reason,
                "current_attempt_count": current_attempt,
                "next_attempt_count": current_attempt,
                "proposed_status": status,
                "verified_entry_url": None,
                "project_mutation": {"状态": status, "尝试次数": str(current_attempt), "结果链接": ""},
            }

        if not resume_same_attempt and current_status != "待提交":
            reason = f"项目当前状态为 {current_status!r}，非待提交状态不可启动新执行"
            return {
                "ok": True,
                "eligible": False,
                "reason": reason,
                "current_attempt_count": current_attempt,
                "next_attempt_count": current_attempt,
                "proposed_status": current_status if current_status in SHEET_TO_INTERNAL else "失败",
                "verified_entry_url": None,
                "project_mutation": {"状态": current_status, "尝试次数": str(current_attempt), "结果链接": ""},
            }
        if resume_same_attempt:
            if current_status not in {"需人工", "处理中"}:
                reason = f"显式恢复模式仅允许恢复 需人工 或 中断处理中 状态（当前状态为: {current_status!r}）"
                return {
                    "ok": True,
                    "eligible": False,
                    "reason": reason,
                    "current_attempt_count": current_attempt,
                    "next_attempt_count": current_attempt,
                    "proposed_status": current_status if current_status in SHEET_TO_INTERNAL else "失败",
                    "verified_entry_url": None,
                    "project_mutation": {"状态": current_status, "尝试次数": str(current_attempt), "结果链接": ""},
                }
            notes = f"{project_row.get('原因/备注') or ''} {project_row.get('证据摘要') or ''}".lower()
            if any(token in notes for token in ("提交结果不确定", "结果不明确", "避免重复提交", "uncertain submit", "ambiguous post-submit")):
                reason = "检测到提交结果不确定风险，禁止自动恢复以避免重复提交，须人工终审"
                return {
                    "ok": True,
                    "eligible": False,
                    "reason": reason,
                    "current_attempt_count": current_attempt,
                    "next_attempt_count": current_attempt,
                    "proposed_status": "需人工",
                    "verified_entry_url": None,
                    "project_mutation": {"状态": "需人工", "尝试次数": str(current_attempt), "结果链接": ""},
                }

        next_attempt = current_attempt if resume_same_attempt else current_attempt + 1
        return {
            "ok": True,
            "eligible": True,
            "reason": "",
            "current_attempt_count": current_attempt,
            "next_attempt_count": next_attempt,
            "proposed_status": "处理中",
            "verified_entry_url": entry_url,
            "project_mutation": {"状态": "处理中", "尝试次数": str(next_attempt), "结果链接": ""},
        }

    @staticmethod
    def validate_cross_project_sync_mutation(
        current_project_row: dict[str, Any],
        master_row: dict[str, Any],
        proposed: dict[str, Any],
    ) -> dict[str, Any]:
        if str(current_project_row.get("状态") or "").strip() != "待提交":
            raise EvidenceContractError("REJECTED: 跨项目排除同步仅允许更新'待提交'行")
        master_status = str(master_row.get("基础状态") or "").strip()
        if master_status not in {"已排除", "失效"}:
            raise EvidenceContractError("REJECTED: 跨项目排除同步要求总表状态必须为'已排除'或'失效'")
        notes = " ".join(
            str(master_row.get(key) or "").lower()
            for key in ("基础排除原因", "实测限制", "平台备注", "实测定价", "价格分类")
        )
        if any(token in notes for token in ("ai-only", "仅限ai", "ai only", "paid-only", "付费", "非免费", "paid")):
            raise EvidenceContractError("REJECTED: 平台属于项目特定限制或付费限制，禁止全局同步")
        expected = "不适用" if master_status == "已排除" else "失败"
        if proposed.get("状态") != expected:
            raise EvidenceContractError(f"REJECTED: 总表状态为{master_status!r}时项目同步状态必须为{expected!r}")
        if proposed.get("结果链接"):
            raise EvidenceContractError("REJECTED: 跨项目排除同步严禁携带结果链接")
        return dict(proposed)

    @staticmethod
    def filter_ready_execution_queue(
        project_rows: list[dict[str, Any]],
        selected_project_id: str,
        ready_allowlist: list[str] | set[str] | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], str | None]:
        if ready_allowlist is None:
            return [], "STANDALONE_FAIL_CLOSED: 未提供 BacklinkOS Ready Allowlist"
        allow = {str(item or "").strip().lower() for item in ready_allowlist if str(item or "").strip()}
        if not allow:
            return [], "EMPTY_ALLOWLIST: Ready Allowlist 为空"
        selected: list[dict[str, Any]] = []
        for row in project_rows:
            if len(selected) >= min(len(allow), max(1, limit)):
                break
            if str(row.get("项目ID") or "").strip() != str(selected_project_id or "").strip():
                continue
            if str(row.get("状态") or "").strip() != "待提交":
                continue
            bid = str(row.get("外链ID") or row.get("外链域名") or "").strip().lower()
            if bid in allow:
                selected.append(row)
        return selected, None
