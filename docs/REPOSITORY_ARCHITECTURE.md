# BacklinkOS Repository Architecture

## Status

**Current architecture as of 2026-09-06.**

This document describes repository boundaries and component roles. Detailed operating rules live in the canonical Skills and take precedence over this document when wording conflicts.

## 1. Source-of-truth hierarchy

BacklinkOS deliberately separates current contracts from historical implementation records.

Current authority, highest first:

1. `.agents/skills/discovering-backlinks/SKILL.md` plus its `references/`
2. `.agents/skills/screening-backlinks/SKILL.md` plus its `references/` *(Legacy / Optional)*
3. this architecture document
4. `docs/V4_PRODUCT_STRATEGY.md`

Historical documents under `docs/V1_PRODUCT_PLAN.md`, `docs/V2_PRODUCT_PLAN.md`, `docs/superpowers/`, and `docs/live-runs/` remain useful evidence of earlier decisions but do not define current behavior.

## 2. Repository responsibilities

The system uses dedicated repositories with explicit boundaries.

### `pyxm1618/BacklinkOS`

Owns:

- backlink candidate discovery and provenance tracking
- the canonical `discovering-backlinks` Skill
- the legacy/optional `screening-backlinks` Skill
- canonical domain normalization and Master Sheet (`外链总表`) Upsert contracts
- minimal Submission Entry Enrichment (Live Evidence + Policy Guard)
- project-level execution materialization (`外链管理`)
- operational helper automation and regression tests
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

### `pyxm1618/backlink-autofill`

Owns real browser execution, authentication, account/profile creation, form interaction, email verification, final submission, and factual write-back to Google Sheets (`实测免费`, `实测需登录`, `实测登录方式`, `实测限制`, `实测链接属性`, `最后验证时间`, `结果链接`).

BacklinkOS does not execute form submission and does not decide verified runtime attributes.

### `pyxm1618/backlink-metrics-api`

Owns deterministic provider integrations and provider-specific runtime behavior, including metric normalization, error semantics, tests, and Vercel deployment.

## 3. Current product flow

```text
Recent SEO projects / discovery sources
                ↓
       discovering-backlinks
                ↓
       canonicalize & deduplicate
                ↓
       【外链总表】(Master Sheet Upsert, Source of Truth)
                ↓
       最低限度 Submission Entry Enrichment (Live Evidence + Policy Guard)
                ↓
       为明确项目生成【外链管理】待提交行 (Materialization)
                ↓
       backlink-autofill (独立执行仓库，真实浏览器执行)
                ↓
       回写真实平台事实与项目执行结果
```

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
- verified submission entry URL

Discovery strictly does NOT write verified execution facts:
- `实测免费`
- `实测需登录`
- `实测登录方式`
- `实测限制`
- `实测链接属性`
- `最后验证时间`

Discovery does not convert historical Semrush observations into claims about the current free route. Unknown fields remain unknown.

### Screening boundary (Legacy / Optional)

The old `screening-backlinks` capability has stepped down from the primary production workflow. It remains available as an optional offline inspection utility or historical reference, but does not dictate whether domains enter `外链总表` and does not reject candidates from the master candidate pool.

## 4. Active helper systems are not canonical decision engines

### Master Sheet sync helper

`scripts/master_sheet_sync.py` implements pure business transformation rules:
- domain canonicalization
- master sheet upsert with fact protection
- submission entry policy guard and live verification helper
- project management row materialization
- bounded batch hydration

### Bulk triage crawler

The repository contains:

```text
scripts/screening_crawler.py
.github/workflows/screening-crawler.yml
```

This is an active bulk triage system. Discovery reuses its battle-tested mechanism detection and anchor-text link discovery without inheriting old screening rejection thresholds.

### Operational data

`data/screening-candidates/` and `data/screening-results/` are operational inputs/snapshots used by the triage workflow. They are not the formal backlink library and do not override Skill decisions.

## 5. Feishu persistence compatibility boundary

The TypeScript APIs under:

```text
POST /api/feishu/setup
POST /api/feishu/persist
```

and implementation under `lib/feishu/` were production-validated under an earlier screening record contract. They are retained unchanged so existing integrations are not broken.

## 6. Missing-data discipline

Across current Skills and provider evidence:

- lookup failure is not zero;
- provider no-coverage is not zero;
- parser failure is not zero;
- historical `is_follow` is not proof of a current free Follow route;
- `first_seen` is not an exact acquisition date;
- missing entry point is missing evidence, not candidate rejection;
- evidence not directly obtained should remain unknown rather than being guessed.

## 7. Expected operating scale

BacklinkOS is a personal-use system. Typical screening/discovery batches are expected to be in the hundreds to low thousands. The system prefers bounded batches, deduplication, reusable evidence, and human-verifiable closure over unnecessary distributed infrastructure.

## 8. Repository hygiene rule

Current code and Skills stay in their functional locations. Historical plans are preserved but clearly labeled as history. Do not delete or move an operational file merely because its terminology is old. First establish whether automation, tests, deployment, or persistence still depends on it.