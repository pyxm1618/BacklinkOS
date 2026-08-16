# BacklinkOS

BacklinkOS is the backlink product and orchestration repository.

## Repository boundary

- Canonical screening Skill: `.agents/skills/screening-backlinks/`
- Deterministic metrics runtime: `pyxm1618/backlink-metrics-api`
- Production metrics endpoint: `https://backlink-metrics-api.vercel.app`

BacklinkOS owns product logic, screening workflow, evidence/rating contracts, and future discovery/persistence orchestration. Provider-specific metric code belongs in `backlink-metrics-api` rather than being duplicated here.

## Current operating model

The personal-use screening workflow is designed for typical runs of roughly **100–1000 candidate URLs**, not 100K-scale processing.

For each run:

1. normalize candidate URLs/domains
2. deduplicate domain-level work
3. query Ahrefs DR through `backlink-metrics-api` in sequential chunks of at most 20 unique domains per batch request
4. verify publishability, registration/pricing, link attribute, domain age, and other placement facts independently
5. use Crawlora selectively when a concrete total-monthly-visits estimate materially helps the decision
6. assign A/B/C/D/F from verified evidence
7. persist the result when the Feishu/Lark integration is available

A run with hundreds of unique domains may take several minutes or longer because provider rate limits are intentionally respected. This is acceptable for a personal-use tool and avoids unnecessary queue/distributed-worker infrastructure.

## Current status

Implemented for `screening-backlinks`:

- screening/evidence/rating contract
- Ahrefs DR single-domain runtime dependency
- bounded batch DR runtime for realistic 100–1000-candidate workflows
- selective Crawlora total-monthly-visits runtime dependency
- explicit missing/unknown/error semantics; missing data is never silently converted to zero

Remaining implementation gap for the current screening workflow:

- **Feishu/Lark automatic persistence**

Separate future work, not blockers for the current screening implementation:

- optional CrUX popularity evidence if it later proves useful
- `discovering-backlinks` as a separate Skill

## Docs

- [Repository architecture](docs/REPOSITORY_ARCHITECTURE.md)
- [V3 product strategy](docs/V3_PRODUCT_STRATEGY.md)
