# BacklinkOS

BacklinkOS is the backlink product and orchestration repository.

## Repository boundary

- Canonical screening Skill: `.agents/skills/screening-backlinks/`
- Deterministic metrics runtime: `pyxm1618/backlink-metrics-api`
- Production metrics endpoint: `https://backlink-metrics-api.vercel.app`

BacklinkOS owns product logic, screening workflow, evidence/rating contracts, and future discovery/persistence orchestration. Provider-specific metric code belongs in `backlink-metrics-api` rather than being duplicated here.

## Current status

Implemented:

- `screening-backlinks` Skill contract
- Ahrefs DR runtime dependency via `backlink-metrics-api`
- selective Crawlora total-monthly-visits runtime dependency via `backlink-metrics-api`

Not yet implemented:

- CrUX bulk runtime
- Feishu/Lark persistence adapter
- large-scale batch orchestration
- `discovering-backlinks` Skill

## Docs

- [Repository architecture](docs/REPOSITORY_ARCHITECTURE.md)
- [V3 product strategy](docs/V3_PRODUCT_STRATEGY.md)
