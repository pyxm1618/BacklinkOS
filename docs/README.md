# BacklinkOS Documentation Map

This directory separates **current operating documents** from **historical decision records**.

## Current production documents

Use these for the default production model, in this order:

1. `../.agents/skills/discovering-backlinks/SKILL.md` + current references
2. `REPOSITORY_ARCHITECTURE.md`
3. `V4_PRODUCT_STRATEGY.md`
4. `../BacklinkOS-HANDOFF.md`
5. `../README.md`

The default production architecture is:

```text
Discover / Master Upsert
        ↓
Project Backlog Projection (UNKNOWN != REJECT, no VerifiedEntry required)
        ↓
Bounded Execution Preparation (VerifiedEntry required for Ready)
        ↓
backlink-autofill real browser execution / recheck
```

`screening-backlinks` is **Legacy / Optional**. Its Skill/references define behavior only when that historical/offline screening path is explicitly requested. It is not a default gate between discovery and Project Backlog.

## Historical product documents

- `V1_PRODUCT_PLAN.md` — historical V1 direction
- `V2_PRODUCT_PLAN.md` — historical V2 direction

Both already carry explicit HISTORICAL status banners. Preserve their original reasoning; do not rewrite them to look current.

## Historical implementation records

- `superpowers/` — point-in-time implementation plans and design specs
- `live-runs/` — point-in-time run records

Their directory READMEs mark them as historical. Individual files may intentionally say that a feature was missing, use old Screening semantics, or describe an older persistence/control-plane design.

**Do not execute a historical plan just because the file exists.** First compare it to current main and the current Skill. If the capability is already implemented, treat the old plan as `Completed / Superseded by current main implementation`.

The old “Project Backlog Population vs Execution Readiness” correction plan is one such completed/superseded plan: current main already implements full Backlog Projection, bounded Ready preparation, and production Sheet migration.

## Supporting documentation outside `docs/`

- `../scripts/README.md` — helper-script roles; current helpers vs legacy triage
- `../data/README.md` — operational snapshot/data boundaries
- `../CLAUDE.md` — developer/agent repository guidance
- `../BacklinkOS-HANDOFF.md` — current closeout/operational baseline

## Documentation maintenance rule

When current production behavior changes:

1. update the canonical current Skill/reference contract;
2. update current architecture/strategy/handoff docs;
3. keep historical plans and live-run records intact except for clearly marking their historical status/indexing;
4. do not modify Python/TypeScript implementation merely to make old prose match current behavior unless a real code defect is separately confirmed.
