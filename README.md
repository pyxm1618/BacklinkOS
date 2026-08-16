# BacklinkOS

BacklinkOS is the backlink product and orchestration repository.

## Repository boundary

- Canonical screening Skill: `.agents/skills/screening-backlinks/`
- Deterministic metrics runtime: `pyxm1618/backlink-metrics-api`
- Production metrics endpoint: `https://backlink-metrics-api.vercel.app`

BacklinkOS owns product logic, screening workflow, evidence/rating contracts, and Feishu persistence. Provider-specific metric code belongs in `backlink-metrics-api` rather than being duplicated here.

## Current operating model

The personal-use screening workflow is designed for typical runs of roughly **100–1000 candidate URLs**, not 100K-scale processing.

For each run:

1. normalize candidate URLs/domains
2. deduplicate domain-level work
3. query Ahrefs DR through `backlink-metrics-api` in sequential chunks of at most 20 unique domains per batch request
4. verify publishability, registration/pricing, link attribute, domain age, and other placement facts independently
5. use Crawlora selectively when a concrete total-monthly-visits estimate materially helps the decision
6. assign A/B/C/D/F from verified evidence
7. persist verified main/evidence records to Feishu Base

A run with hundreds of unique domains may take several minutes or longer because provider rate limits are intentionally respected. This is acceptable for a personal-use tool and avoids unnecessary queue/distributed-worker infrastructure.

## Feishu persistence

The repository contains protected TypeScript APIs for schema setup and record persistence:

```text
POST /api/feishu/setup
POST /api/feishu/persist
```

Both require the request header:

```text
X-BacklinkOS-Key: <BACKLINKOS_API_KEY>
```

Production variables belong in the Vercel project `backlink-os` only:

```text
FEISHU_APP_ID
FEISHU_APP_SECRET
FEISHU_BITABLE_APP_TOKEN
FEISHU_OPPORTUNITY_TABLE_ID
FEISHU_EVIDENCE_TABLE_ID
BACKLINKOS_API_KEY
```

`/api/feishu/setup` is dry-run by default. Use `{ "apply": false }` to inspect planned changes and `{ "apply": true }` only after the dry-run is reviewed. Setup never deletes fields or records.

The persistence adapter validates the screening invariants before writing, including `Unknown != 0`, visible `月访问量` semantics, and the requirement for hard-rejection evidence when `评级=F`.

**Rollout status:** code and automated tests are implemented on the Feishu feature branch. Production schema creation and live create/update verification must succeed before the Skill documentation is changed to call Feishu persistence production-verified.

## Current status

Implemented for `screening-backlinks`:

- screening/evidence/rating contract
- Ahrefs DR single-domain runtime dependency
- bounded batch DR runtime for realistic 100–1000-candidate workflows
- selective Crawlora total-monthly-visits runtime dependency
- explicit missing/unknown/error semantics; missing data is never silently converted to zero
- Feishu persistence code with protected setup/upsert APIs and mocked automated tests

Production verification still required before closing the current screening workflow:

- add `BACKLINKOS_API_KEY` to `backlink-os` Production
- run Feishu schema dry-run and apply
- verify one live create + read-back + update without duplication

Separate future work, not blockers for the current screening implementation:

- optional CrUX popularity evidence if it later proves useful
- `discovering-backlinks` as a separate Skill

## Docs

- [Repository architecture](docs/REPOSITORY_ARCHITECTURE.md)
- [V3 product strategy](docs/V3_PRODUCT_STRATEGY.md)
- [Feishu persistence design](docs/superpowers/specs/2026-08-16-feishu-persistence-design.md)
