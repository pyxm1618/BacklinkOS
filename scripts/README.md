# Operational Helper Scripts

Scripts in this directory are executable helpers. Current product semantics come from the canonical `discovering-backlinks` contract and the current architecture docs, not from an old helper's historical purpose.

## Current production helpers

### `master_sheet_sync.py`

Core business transformation/helper module used by the current four-phase flow. It contains capabilities for:

- canonical domain normalization;
- Master Upsert/fact protection;
- Project Backlog materialization;
- persisted project hard-compatibility checks;
- Submission Entry Policy Guard and Live Verification;
- bounded execution preparation;
- Ready cursor and orphan accounting.

Important current semantic:

> **Project Backlog does not require `VerifiedEntry`; Ready for Autofill does.**

If an old Python module docstring or historical comment conflicts with the current Skill/functions, do not treat the comment as a product contract.

### `project_backlog_projection.py`

Production Project Backlog Projection runner.

Responsibilities:

- read current Master + Project Sheet rows;
- pure data/in-memory projection with zero crawler/network requirement for materialization;
- `UNKNOWN != REJECT`;
- preserve all existing project states/attempts;
- reconciliation invariant;
- dry-run / commit modes;
- timestamped backup before production append;
- dynamic row-capacity expansion;
- batched writes;
- exact read-back verification;
- final completeness audit.

This helper replaced the early architecture where only candidates with a live `VerifiedEntry` could appear in the project sheet.

### `prepare_execution_batch.py`

Phase C bounded execution-readiness helper.

It operates on existing project `待提交` rows and is intentionally bounded by Ready target / scan limit. It may live-verify stored entries or discover blank entries.

Rules:

- only a real `VerifiedEntry` can enter the Ready manifest;
- unresolved rows remain `待提交` and do not gain attempts;
- Ready cursor prevents unresolved head rows from starving later rows;
- orphan joins are reported/skipped rather than blocking the scan;
- `target_ready_count` / `scan_limit` limit the current preparation run, not total Backlog population.

## Auxiliary / legacy triage helpers

### `screening_crawler.py`

This crawler and `.github/workflows/screening-crawler.yml` are retained as bulk triage/page-analysis infrastructure.

Historical buckets such as `dead`, `paid`, `pending`, and `unverified` are **not the current default production admission model**.

Current boundary:

- Discovery may reuse battle-tested page parsing, anchor discovery, Entry hints, mechanism detection, and related low-level helpers;
- a crawler result must not become an implicit gate that prevents ordinary Master candidates from entering Project Backlog;
- `unverified` means missing evidence, never automatic rejection;
- current runtime free/login/restriction/link-attribute facts belong to `backlink-autofill`;
- final execution readiness belongs to Phase C `VerifiedEntry` preparation, not to crawler bucket labels.

Historical noindex/soft-404/entry-detection regression knowledge remains valuable when modifying `screening_crawler.py`, including:

- noindex on soft-404/login pages must not automatically kill a domain;
- probe hints are not equivalent to verified mechanism evidence;
- bare/www variants may behave differently;
- anchor text matters for Entry discovery;
- same-origin and auth-wall callback validation are mandatory;
- generic contact forms and unrelated pages must not be promoted to Submission Entry.

Do not reintroduce old behavior where failure to find an entry removes a candidate from the current Master/Project opportunity pool.

### `verify_opportunity.py`

Historical/auxiliary verification helper for the older screening/opportunity dataset. Its outputs are not the current Google Sheets control plane and do not override the four-stage production pipeline.

Use it only when explicitly working with the legacy screening dataset/workflow.

## Execution repository boundary

Real browser work is not performed by these BacklinkOS helpers. It belongs to `pyxm1618/backlink-autofill`, including:

- login/account flows;
- Existing Submission Preflight;
- form fill;
- CAPTCHA / Turnstile / 2FA / SMS blockers;
- Final Submit;
- project-state classification;
- result URL / live DOM rel;
- Manual Post-submit Recheck.

## Modification rule

Before changing a helper, identify which phase it belongs to:

- Phase A: Master discovery/upsert;
- Phase B: Project Backlog Projection;
- Phase C: Ready preparation;
- Phase D: Autofill (separate repo).

Do not blur these boundaries merely because an older helper once combined screening and admission decisions.
