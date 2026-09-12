# BacklinkOS Repository Architecture

## Status

**Current architecture as of 2026-09-07.**

This document describes repository boundaries and the production data flow after the 2026-09-07 repair/acceptance closeout.

## 1. Source-of-truth hierarchy

Default production behavior, highest authority first:

1. `.agents/skills/discovering-backlinks/SKILL.md` plus its current `references/`
2. this architecture document
3. `docs/V4_PRODUCT_STRATEGY.md`
4. `BacklinkOS-HANDOFF.md`
5. root `README.md`

`.agents/skills/screening-backlinks/` is **Legacy / Optional**. It is authoritative only when that legacy screening path is explicitly requested; it is not a required stage of the default production pipeline.

Historical documents under `docs/V1_PRODUCT_PLAN.md`, `docs/V2_PRODUCT_PLAN.md`, `docs/superpowers/`, and `docs/live-runs/` preserve earlier decisions and must not override current behavior.

## 2. Repository boundaries

### `pyxm1618/BacklinkOS`

Owns:

- candidate discovery and provenance;
- canonical domain normalization;
- `外链总表` Master Upsert and fact-protection contracts;
- Project Backlog Projection into `外链管理`;
- persisted Project Compatibility Hard Gate;
- Submission Entry Live Verification and Policy Guard;
- bounded execution preparation;
- Ready cursor / orphan accounting;
- Ready manifest / allowlist handoff;
- production projection helpers and regression tests;
- documentation for the above contracts.

BacklinkOS does **not** perform Final Submit.

### `pyxm1618/backlink-autofill`

Owns real browser execution:

- authentication / account flows;
- form interaction;
- Existing Submission Preflight;
- anonymous fail-closed behavior;
- CAPTCHA / Turnstile / 2FA / SMS human blockers;
- Final Submit;
- factual project-state classification;
- result URL and live DOM link-attribute verification;
- Manual Post-submit Recheck;
- production fact write-back.

### `pyxm1618/backlink-metrics-api`

Owns provider-specific deterministic metric integrations. Metric-runtime implementation is not duplicated in BacklinkOS.

## 3. Current production flow

```text
PHASE A — Discover / Master Upsert
recent SEO projects / discovery sources
                ↓
       discovering-backlinks
                ↓
       canonicalize & deduplicate
                ↓
       【外链总表】 Master Sheet
                ↓
PHASE B — Project Backlog Projection
       0 network / pure data projection
       candidate → project `待提交`
       UNKNOWN != REJECT
                ↓
PHASE C — Bounded Execution Preparation
       bounded scan of existing `待提交` rows
       live Entry verification
       VerifiedEntry → Ready manifest
       unresolved → stays `待提交`
                ↓
PHASE D — backlink-autofill
       real browser execution + recheck
                ↓
       platform facts + project result write-back
```

### Phase A — Master boundary

`外链总表` is a reusable platform-level fact store.

Discovery may write:

- canonical domain / backlink ID;
- discovery source/provenance;
- discovery timestamps;
- base status (`候选 / 已排除 / 失效`);
- verified Submission Entry only after actual Entry Live Verification.

Discovery must not invent runtime facts such as free status, login requirement, restrictions, live link rel, or verification time. Unknown facts remain empty.

### Phase B — Project Backlog Projection

This is the critical separation from older architecture.

- Project Backlog population is a **pure database/in-memory projection**;
- no network request is required;
- a Master candidate does not need a Submission Entry or `VerifiedEntry` to exist in `外链管理`;
- `UNKNOWN != REJECT`;
- only Master hard negatives (`已排除 / 失效`) or persisted, proven project incompatibility may prevent projection;
- `project_id + backlink_id` is unique;
- any existing project state is preserved and never reset by projection.

`外链管理` therefore represents the project's opportunity backlog and full execution lifecycle, not merely the subset ready to execute now.

### Phase C — Execution Readiness

Execution readiness is bounded and separate from backlog size.

- select current-project `待提交` rows;
- use a cursor so unresolved head rows do not starve later candidates;
- report and skip orphan rows rather than blocking the scan;
- live revalidate stored entries and discover blank entries as needed;
- apply current project compatibility using verified/persisted facts;
- only a real `VerifiedEntry` can enter the Ready manifest;
- unresolved verification leaves the project row untouched (`待提交`, attempt unchanged);
- `target_ready_count` / `scan_limit` limit the current preparation batch only, never the size of the Project Backlog.

### Phase D — Autofill handoff

The execution contract is:

> **Ready allowlist ∩ Sheet `待提交` rows**

`待提交 != Ready`.

Standalone Autofill execution without a Ready allowlist must fail closed. Autofill does not pull blindly from the thousands of backlog rows.

## 4. Google Sheets control plane

Google Sheets `@外链管理总控表` is the current business control plane.

### `外链总表`

Platform-level unique facts. Base status is exactly:

- `候选`
- `已排除`
- `失效`

Upsert protects real execution facts and cannot revive hard-negative status.

### `外链管理`

Project opportunity backlog + execution lifecycle.

Valid lifecycle states include:

- `待提交`
- `处理中`
- `已提交`
- `审核中`
- `已排期`
- `已上线`
- `需人工`
- `失败`
- `不适用`

The early small project sheet has already been migrated to the full backlog model. Old plans describing a future migration from a few dozen rows to thousands are completed/superseded and must not be re-executed.

## 5. Active helper systems

### `scripts/master_sheet_sync.py`

Implements core data contracts and readiness logic, including canonicalization, Master protection, materialization, compatibility, entry verification, cursor, and bounded preparation.

### `scripts/project_backlog_projection.py`

Production Project Backlog projection runner:

- dry-run / commit;
- 0-network projection;
- reconciliation invariant;
- timestamped backup;
- dynamic row-capacity expansion;
- batch writes;
- exact read-back;
- final completeness audit.

### `scripts/prepare_execution_batch.py`

Operational wrapper for bounded Phase C preparation.

### `scripts/screening_crawler.py`

An active historical/auxiliary triage and page-analysis helper. Current Discovery may reuse its mechanism/entry-analysis infrastructure, but crawler buckets are not the default production admission or final execution decision engine.

## 6. Legacy Screening boundary

`screening-backlinks` remains available for explicit historical/offline screening questions such as free-vs-paid and current Follow-opportunity analysis.

It is not allowed to become an implicit gate between Master discovery and Project Backlog population. Ordinary candidates are not excluded from the current control plane merely because legacy Screening has not closed all facts.

## 7. Missing-data discipline

Across the default production flow:

- lookup failure is not zero;
- provider no-coverage is not zero;
- missing Entry is not candidate rejection;
- unknown free/login/Follow facts are not rejection;
- historical `is_follow` is not proof of current free-route Follow;
- a candidate is project-incompatible only when a relevant hard constraint is supported by strong evidence;
- ambiguous evidence fails closed for execution readiness but remains in the backlog unless a formal terminal decision exists.

## 8. Acceptance baseline

The 2026-09-07 closeout validated the repaired architecture with production Sheet reads and bounded live checks.

Key outcomes:

- Projection reconciliation and idempotent `would_create=0` behavior passed;
- Ready cursor advancement passed;
- orphan reporting/skip behavior passed;
- Ready allowlist and standalone fail-closed passed;
- Manual Post-submit Recheck preserved attempts/scheduled state/master facts;
- AI-only live verification was corrected after the real `navtools.ai` case and now blocks non-AI projects from Ready;
- final BacklinkOS regression: Python 115 passed, Node 41 passed, TypeScript 0 errors.

This closeout did not require or perform ten arbitrary real Final Submits. Production use should naturally exercise Ready candidates over time instead of manufacturing a submission quota for acceptance.

## 9. Repository hygiene

Current documents must describe the above architecture. Historical plans/specs/live-runs remain preserved as point-in-time evidence and should be labeled/indexed as historical rather than rewritten to look current.
