# BacklinkOS Repository Architecture

## Status

**Current architecture as of 2026-08-22.**

This document describes repository boundaries and component roles. Detailed operating rules live in the canonical Skills and take precedence over this document when wording conflicts.

## 1. Source-of-truth hierarchy

BacklinkOS deliberately separates current contracts from historical implementation records.

Current authority, highest first:

1. `.agents/skills/discovering-backlinks/SKILL.md` plus its `references/`
2. `.agents/skills/screening-backlinks/SKILL.md` plus its `references/`
3. this architecture document
4. `docs/V4_PRODUCT_STRATEGY.md`

Historical documents under `docs/V1_PRODUCT_PLAN.md`, `docs/V2_PRODUCT_PLAN.md`, `docs/superpowers/`, and `docs/live-runs/` remain useful evidence of earlier decisions but do not define current behavior.

## 2. Repository responsibilities

The system uses two repositories with explicit boundaries.

### `pyxm1618/BacklinkOS`

Owns:

- backlink product logic and lifecycle
- the canonical `discovering-backlinks` Skill
- the canonical `screening-backlinks` Skill
- discovery provenance and handoff contracts
- current screening rules and output schema
- operational helper automation
- Feishu compatibility persistence code
- product and architecture documentation

Canonical Skill paths:

```text
.agents/skills/discovering-backlinks/
.agents/skills/screening-backlinks/
```

Claude compatibility entries:

```text
.claude/skills/discovering-backlinks
→ ../../.agents/skills/discovering-backlinks

.claude/skills/screening-backlinks
→ ../../.agents/skills/screening-backlinks
```

The symlinks are compatibility entries only. There is one editable Skill source for each capability.

### `pyxm1618/backlink-metrics-api`

Owns deterministic provider integrations and provider-specific runtime behavior, including metric normalization, error semantics, tests, and Vercel deployment.

BacklinkOS must not duplicate provider-specific metric clients merely to make a Skill self-contained.

## 3. Current product flow

```text
Recent SEO projects / discovery sources
                ↓
       discovering-backlinks
                ↓
  factual referring-domain candidates
                ↓
        screening-backlinks
                ↓
┌──────────┬────────────┬──────────┬───────────┐
│ 免费     │ 免费换链    │ 付费     │ 不确定     │
└──────────┴────────────┴──────────┴───────────┘
       ↓ confirmed opportunity only
       formal backlink opportunity table
```

Discovery and Screening remain separate responsibilities.

### Discovery boundary

Discovery may collect and pass facts such as:

- source projects
- project Organic Traffic status/value
- referring domain
- backlinks count
- Semrush Authority Score
- first/last seen
- historical `is_follow`
- batch/provenance fields

Discovery does not convert historical Semrush observations into claims about the current free route. Unknown fields remain unknown.

### Screening boundary

Screening verifies the current opportunity itself:

- current ordinary-user execution route
- free / reciprocal-link / paid / uncertain acquisition mode
- final direct external link
- final link `rel`
- final-page indexability
- network-level evidence where a family rule is justified

The current Screening contract does not use A/B/C/D/F ratings. DR, traffic, project coverage, and first-seen dates may help ordering or context but do not determine admission to the formal opportunity table.

## 4. Active helper systems are not canonical decision engines

### Bulk triage crawler

The repository contains:

```text
scripts/screening_crawler.py
.github/workflows/screening-crawler.yml
```

This is an active bulk triage system. The workflow builds a candidate CSV, runs regression tests, crawls candidates, and writes the latest machine snapshot to `data/screening-results/`.

Its output is preliminary. In particular, an automatically undetected generic mechanism is insufficient evidence for a final current-Screening rejection. The crawler may reduce manual workload or prioritize follow-up, but the canonical Skill owns final opportunity semantics.

### Operational data

`data/screening-candidates/` and `data/screening-results/` are operational inputs/snapshots used by the triage workflow. They are not the formal backlink library and do not override Skill decisions.

The current workflow intentionally commits the latest result snapshot for compatibility. Large generated snapshots should not be interpreted as product source code.

## 5. Feishu persistence compatibility boundary

The TypeScript APIs under:

```text
POST /api/feishu/setup
POST /api/feishu/persist
```

and implementation under `lib/feishu/` were production-validated under an earlier screening record contract.

They are retained unchanged so existing integrations are not broken. That earlier schema includes fields such as `评级`, while the current Screening Skill no longer uses A/B/C/D/F as its business decision model.

Therefore:

- the Feishu runtime remains executable compatibility infrastructure;
- its historical fields do not define current screening semantics;
- new user-facing table behavior must follow `.agents/skills/screening-backlinks/references/output-schema.md`;
- a future persistence-schema migration should be a separate, explicitly tested behavior change rather than part of repository cleanup.

## 6. Missing-data discipline

Across current Skills and provider evidence:

- lookup failure is not zero;
- provider no-coverage is not zero;
- parser failure is not zero;
- historical `is_follow` is not proof of a current free Follow route;
- `first_seen` is not an exact acquisition date;
- evidence not directly obtained should remain unknown rather than being guessed.

## 7. Expected operating scale

BacklinkOS is a personal-use system. Typical screening/discovery batches are expected to be in the hundreds to low thousands, not a 100K-scale distributed ingestion platform.

The system should prefer bounded batches, deduplication, reusable evidence, and human-verifiable closure over unnecessary distributed infrastructure.

## 8. Repository hygiene rule

Current code and Skills stay in their functional locations. Historical plans are preserved but clearly labeled as history.

Do not delete or move an operational file merely because its terminology is old. First establish whether automation, tests, deployment, or persistence still depends on it. Cleanup must not silently change runtime behavior.