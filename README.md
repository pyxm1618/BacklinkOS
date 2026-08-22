# BacklinkOS

BacklinkOS is a personal backlink discovery and screening system for building a reusable database of **general-purpose backlink opportunities**.

The repository contains the product rules, the two canonical Agent Skills, operational helpers, and compatibility persistence code. Provider-specific metric integrations remain in `pyxm1618/backlink-metrics-api`.

## Source of truth

Current operating behavior is defined in this order:

1. `.agents/skills/discovering-backlinks/SKILL.md` and its `references/`
2. `.agents/skills/screening-backlinks/SKILL.md` and its `references/`
3. `docs/REPOSITORY_ARCHITECTURE.md`
4. `docs/V4_PRODUCT_STRATEGY.md`
5. historical plans/specs only for design history

If an older document conflicts with a current Skill, **the current Skill wins**.

The `.claude/skills/*` entries are compatibility symlinks to the canonical `.agents/skills/*` trees; they are not second editable copies.

## Current workflow

```text
Discover
   ↓
Screen
   ↓
Keep / reciprocal-link keep / paid exclusion / recycle / pending confirmation
   ↓
Operational persistence
```

### `discovering-backlinks`

Discovery finds candidate referring domains and passes factual observations downstream. It does not decide whether a current public route is free, whether the resulting link is currently Follow, or whether a candidate is suitable for a particular promoted project.

The current Semrush workflow uses the validated `sem.3ue.com` relay and the Skill-owned batch runner in `.agents/skills/discovering-backlinks/scripts/`.

### `screening-backlinks`

Screening answers one question: **can an ordinary user currently obtain an effective Follow backlink without paying?**

The current business outcomes are:

- `免费`
- `免费换链`
- `付费`
- `不确定`

Only confirmed `免费` and `免费换链` opportunities with a current executable route, a direct Follow external link, and an indexable final page belong in the formal backlink opportunity table. The current Screening Skill does **not** use A/B/C/D/F as an admission or priority system.

## Runtime and compatibility components

### Deterministic metric runtime

Provider-specific metric code lives in `pyxm1618/backlink-metrics-api` rather than being duplicated here.

Production endpoint:

```text
https://backlink-metrics-api.vercel.app
```

### Bulk screening crawler

`scripts/screening_crawler.py` and `.github/workflows/screening-crawler.yml` are active **bulk triage helpers**. They can cheaply classify large candidate sets into preliminary buckets and write snapshots under `data/screening-results/`.

Those crawler buckets are **not final Screening decisions**. Absence of an automatically detected mechanism is not, by itself, the evidence standard required by the canonical Screening Skill. Final opportunity decisions must follow `.agents/skills/screening-backlinks/`.

### Feishu persistence compatibility layer

`api/feishu/` and `lib/feishu/` contain a production-validated persistence implementation created under an earlier screening record contract. It intentionally remains unchanged for compatibility and may still contain historical fields such as `评级`.

That compatibility schema must not be used to infer current Screening business semantics. The current user-facing table contract is defined by `.agents/skills/screening-backlinks/references/output-schema.md`.

## Repository layout

```text
.agents/skills/
  discovering-backlinks/       canonical Discovery Skill
  screening-backlinks/         canonical Screening Skill
.claude/skills/                compatibility symlinks
.github/workflows/             operational automation
api/feishu/                    compatibility persistence API
lib/feishu/                    compatibility persistence implementation
data/                          operational candidate/result snapshots
docs/                          current architecture + historical records
scripts/                       operational helper scripts
tests/                         runtime/helper regression tests
```

## Documentation status

- `docs/REPOSITORY_ARCHITECTURE.md` — current architecture
- `docs/V4_PRODUCT_STRATEGY.md` — current product strategy
- `docs/V1_PRODUCT_PLAN.md` — historical
- `docs/V2_PRODUCT_PLAN.md` — historical
- `docs/superpowers/` — historical implementation plans/specs
- `docs/live-runs/` — historical run records

See `docs/README.md` for the documentation precedence rules.