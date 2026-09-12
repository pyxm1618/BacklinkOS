# BacklinkOS V4 Product Strategy

## Status

**Current product strategy as of 2026-09-07.**

BacklinkOS is a personal SEO backlink opportunity operating system built around a reusable platform fact store, a per-project opportunity backlog, bounded execution-readiness preparation, and safe real-browser execution through `backlink-autofill`.

The product is not a backlink spam bot and does not require all business facts to be known before preserving a candidate.

## 1. Product model

The current model has four distinct responsibilities:

1. **Discover / Master Upsert** — find real candidate domains and maintain platform-level facts.
2. **Project Backlog Projection** — project reusable candidates into a specific project's full opportunity backlog without requiring live execution readiness.
3. **Bounded Execution Preparation** — live-verify a small batch and produce a Ready allowlist.
4. **Autofill Execution** — perform real browser actions and write back actual execution facts.

The key product rule is:

> **UNKNOWN != REJECT, and Project Backlog != Ready Queue.**

## 2. Phase A — Discover / Master Upsert

The canonical current Skill is:

```text
.agents/skills/discovering-backlinks/
```

Discovery finds candidate referring domains from real sources such as SEO-success projects and Semrush Referring Domains, then canonicalizes and Upserts them into `外链总表`.

Discovery preserves provenance and directly observed facts. It does not guess current free status, login requirements, current Follow status, or execution outcomes.

A candidate may legitimately exist with:

- blank Submission Entry;
- unknown free/paid state;
- unknown authentication requirements;
- unknown final-link attributes.

Those unknowns are not rejection evidence.

## 3. Phase B — Project Backlog Projection

`外链管理` is the project-level opportunity backlog and lifecycle table.

Projection rules:

- operate without network I/O;
- include Master `候选` rows by default;
- do not require Submission Entry or `VerifiedEntry`;
- exclude only Master `已排除/失效` or proven project hard incompatibility;
- preserve `project_id + backlink_id` uniqueness;
- preserve all existing project states and attempts;
- create new backlog rows as `待提交 / 尝试次数=0`.

This is intentionally a large pool. Batch size limits belong to execution preparation, not backlog population.

## 4. Project compatibility

BacklinkOS still does not implement a general black-box topical relevance score or weighted Project × Opportunity ranking system.

However, the current product **does** enforce explicit hard compatibility when strong platform facts require it. Example: a verified AI-only submission platform must not become Ready for a project whose `project_context.ai_powered` is false.

Rules:

- strong, relevant, persisted/verified constraint → may block that project;
- ambiguous or missing constraint → include in backlog;
- a project-specific incompatibility does not globally mark the Master platform as bad for all projects.

## 5. Phase C — Bounded Execution Preparation

Execution preparation answers a narrower question:

> Is this backlog row sufficiently verified to hand to the browser executor now?

It is intentionally bounded, for example by `target_ready_count` and `scan_limit`.

Preparation performs current Entry Live Verification and produces `VerifiedEntry` objects only when evidence is sufficient.

Rules:

- stored historical entries are revalidated;
- blank entries may be discovered live;
- invalid pricing/terms/category/report pages are rejected by Policy Guard;
- ordinary body text or URL path alone cannot manufacture a submission entry;
- auth-wall acceptance requires valid same-origin submission callback/provenance evidence;
- unresolved verification leaves the backlog row as `待提交`, attempt unchanged;
- a cursor prevents unresolved front rows from starving later candidates;
- orphan project rows are reported and skipped rather than blocking progress.

Only verified rows enter the Ready manifest.

## 6. Phase D — `backlink-autofill`

Real browser execution belongs to the separate repository:

```text
pyxm1618/backlink-autofill
```

The handoff contract is:

> **Ready allowlist ∩ current project `待提交` rows**

`待提交 != Ready`.

Autofill owns:

- authentication and account flows;
- form filling;
- Existing Submission Preflight;
- anonymous fail-closed rules;
- CAPTCHA / Turnstile / 2FA / SMS human blockers;
- Final Submit;
- lifecycle classification;
- result URLs;
- actual DOM link attributes;
- Manual Post-submit Recheck.

Execution must fail closed when evidence is ambiguous rather than improvising an unsafe submit.

## 7. Google Sheets as control plane

The current control plane is Google Sheets `@外链管理总控表`.

### `外链总表`

Platform-level reusable facts.

### `外链管理`

Project-level backlog and lifecycle.

This architecture is intentionally sufficient at the current scale; moving to a separate database is not a prerequisite for normal operation.

## 8. Legacy `screening-backlinks`

The historical `screening-backlinks` Skill remains available as **Legacy / Optional** for explicit free/Follow opportunity screening, historical investigations, or special offline review.

It is no longer the default admission gate between discovery and the control plane.

Therefore older statements such as:

```text
Discover → Screen → only formal opportunities enter the database
```

are historical semantics, not the current production pipeline.

## 9. Evidence discipline

Current evidence rules include:

- missing data stays unknown;
- historical Semrush `is_follow` is discovery evidence, not current-route proof;
- `first_seen` is not an exact acquisition date;
- missing Entry is not rejection;
- generic AI mentions are not enough for AI-only classification;
- AI-only requires strong submission-object/eligibility evidence with inclusive guards;
- public result URL is only written after a public listing and identity are verified;
- live `rel` is only written after actual DOM inspection;
- Recheck must preserve unobserved historical Master facts.

## 10. Current completion state

The core production architecture is implemented and accepted.

Completed:

- Master Upsert and fact protection;
- full Project Backlog Projection;
- idempotent reconciliation;
- production backup / capacity / batch-write / exact-readback projection helper;
- bounded execution preparation;
- Ready cursor;
- orphan reporting;
- Ready allowlist handoff;
- standalone Autofill fail-closed;
- anonymous preflight fail-closed;
- Manual Post-submit Recheck;
- scheduled-state and Master-fact preservation;
- AI-only project compatibility after real live verification failure exposed the gap.

Final BacklinkOS regression at closeout: Python 115 passed, Node 41 passed, TypeScript 0 errors.

The next product phase is **normal production use**, not another architecture redesign. New fixes should be driven by concrete real-run failures.

## 11. Explicit non-goals

Current V4 does not require:

- general topical relevance scoring;
- black-box backlink quality scoring;
- an Ahrefs/Semrush replacement;
- a massive backlink crawler/index;
- distributed 100K-scale infrastructure;
- a scheduler/worker platform merely for architectural completeness;
- a forced quota of ten arbitrary real submissions as acceptance evidence;
- uncontrolled automated backlink spam.

## 12. Historical-document rule

`V1_PRODUCT_PLAN.md`, `V2_PRODUCT_PLAN.md`, `docs/superpowers/`, and `docs/live-runs/` preserve earlier product reasoning. They may describe architectures that have since been replaced.

Do not execute an old plan simply because its document still exists. Compare it to the current Skill and main implementation first; completed/superseded plans remain historical records.
