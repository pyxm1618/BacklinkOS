# BacklinkOS Documentation Map

BacklinkOS keeps historical plans for decision traceability, but historical documents do not define current runtime behavior.

## Current documents

Use these for the current product model:

1. repository root `README.md`
2. `REPOSITORY_ARCHITECTURE.md`
3. `V4_PRODUCT_STRATEGY.md`

For detailed operating rules, the canonical Skills have higher authority than all documents in this directory:

```text
../.agents/skills/discovering-backlinks/
../.agents/skills/screening-backlinks/
```

When wording conflicts, the current Skill and its references win.

## Historical product documents

- `V1_PRODUCT_PLAN.md` — historical V1 direction
- `V2_PRODUCT_PLAN.md` — historical V2 direction

They intentionally preserve superseded concepts and should not be edited to pretend those earlier decisions never existed.

## Historical implementation records

- `superpowers/` — implementation plans and design specs captured at the time work was performed
- `live-runs/` — point-in-time run records

These records can contain statements that were true on their date but are no longer current, including statements about unimplemented features, A/B/C/D/F ratings, or persistence gaps.

## Rule for future documentation

A new current behavior change must update the canonical Skill first (or in the same change), then update current architecture/strategy documentation. Do not change historical documents merely to make old records look current.