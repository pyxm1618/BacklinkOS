# BacklinkOS Repository Architecture

## Status

Approved two-repository architecture and current operating model.

The system is optimized for personal use with typical screening runs of roughly **100–1000 candidate URLs**. It is intentionally not designed as a 100K-scale distributed data system.

## 1. Repository responsibilities

BacklinkOS uses two repositories with explicit boundaries:

1. `pyxm1618/BacklinkOS` — product, Skills, screening workflow, evidence/rating rules, and persistence contracts.
2. `pyxm1618/backlink-metrics-api` — deterministic metric-provider integrations, normalization, provider error semantics, tests, and Vercel runtime.

Do not create a third repository for the current scope.

### `pyxm1618/BacklinkOS`

This is the canonical home for backlink product logic.

It owns:

- backlink opportunity model and lifecycle
- `screening-backlinks` Skill
- A/B/C/D/F screening semantics
- publishability / registration / pricing / link-attribute verification workflow
- evidence and persistence contracts
- Feishu/Lark integration when implemented
- future `discovering-backlinks` Skill as a separate module
- product strategy, architecture and decisions

It must not duplicate Ahrefs, Crawlora, or other provider-specific runtime code.

Current canonical Skill:

```text
.agents/skills/screening-backlinks/
```

Claude compatibility entry:

```text
.claude/skills/screening-backlinks
→ ../../.agents/skills/screening-backlinks
```

### `pyxm1618/backlink-metrics-api`

This repository provides deterministic metric evidence.

It owns:

- Ahrefs DR single-domain integration
- Ahrefs DR bounded batch integration
- Crawlora total-monthly-visits integration
- shared domain normalization for domain-scoped metrics
- provider error / missing-data semantics
- provider-specific executable tests
- provider validation evidence
- Vercel deployment/runtime configuration

It does not own:

- backlink discovery
- backlink A/B/C/D/F decisions
- publishability rules
- registration/pricing classification
- placement-type business rules
- Feishu business workflow
- topical relevance

## 2. Current runtime relationship

The current screening path is:

```text
Candidate URLs
      ↓
BacklinkOS / screening-backlinks
      ↓
normalize + deduplicate domain-level work
      ↓
backlink-metrics-api
      ├── /api/dr            single-domain DR
      ├── /api/dr/batch      bounded batch DR
      └── /api/traffic       selective total-monthly-visits estimate
      ↓
BacklinkOS combines metric evidence with current page/placement verification
      ↓
A / B / C / D / F
      ↓
Feishu/Lark persistence (remaining integration)
```

The metrics API returns evidence. The Skill decides how that evidence is used in the screening workflow.

## 3. Realistic batch model

The expected operating scale is roughly **100–1000 candidate URLs per run**.

The workflow should reduce external calls before doing provider lookups:

1. normalize candidate URLs/domains
2. deduplicate by the correct identity
3. reuse one domain-wide metric observation across placements when the metric itself is domain-wide
4. query DR for the unique domains
5. keep placement verification independent even when several placements share a domain

### DR batching

`backlink-metrics-api` exposes:

```text
POST /api/dr/batch
```

One HTTP call accepts at most **20 unique normalized domains**. A larger 100–1000-candidate screening run is split into sequential chunks of at most 20 unique domains.

This limit is intentional. It keeps each Vercel request bounded while respecting the Ahrefs provider rate limit instead of building a long-running queue system.

The batch runtime:

- normalizes URL/domain inputs
- deduplicates normalized domains
- rejects malformed/local/IP inputs before provider calls
- paces provider requests conservatively
- retries only temporary failures within a small bounded limit
- preserves partial results when one domain fails
- never converts missing/failed DR into zero

No distributed workers or large-scale ingestion infrastructure is required for the current personal-use workflow.

## 4. Traffic evidence

Traffic remains optional supporting evidence, not a required lookup for every candidate.

### Crawlora

Current production use:

- selective follow-up for a concrete `total_monthly_visits_estimate`
- medium-confidence modelled estimate, not first-party analytics
- positive current `data.Engagments.Visits` may be used as confirmed evidence
- raw zero remains `UNKNOWN`, not confirmed zero
- stale `EstimatedMonthlyVisits` values are not used as the current monthly-visits value

Do not spend Crawlora credits on every domain in a batch. Use it where a concrete traffic estimate materially helps the screening decision.

### CrUX

CrUX is an **optional future enhancement**, not a current MVP dependency, blocker, or required next stage.

If it is implemented later, its popularity rank must remain a separate `popularity_rank` observation and must never be written as monthly visits.

## 5. Missing-data discipline

Across the system:

- lookup failure is not zero
- provider no-coverage is not zero
- parser failure is not zero
- tool access failure is not `F`
- Crawlora raw zero is not confirmed zero
- a real numeric Ahrefs DR zero is valid only when Ahrefs successfully returns that numeric zero

These rules are part of the product contract, not optional implementation details.

## 6. Source of truth

- Product/Skill source of truth: `pyxm1618/BacklinkOS`
- Deterministic metric source of truth: `pyxm1618/backlink-metrics-api`
- Production metric endpoint: `https://backlink-metrics-api.vercel.app`

Do not create a second editable copy of `screening-backlinks` in the metrics repository.

## 7. Current completion boundary

For the current `screening-backlinks` implementation, the intended runtime and workflow pieces are:

- screening/evidence/rating contract — implemented
- Ahrefs DR single-domain lookup — implemented
- bounded Ahrefs DR batching for realistic runs — implemented
- selective Crawlora monthly-visits evidence — implemented
- current-page/placement verification workflow — defined by the Skill
- Feishu/Lark automatic persistence — **remaining implementation gap**

Separate future work is not counted as an unfinished part of the current screening implementation:

- `discovering-backlinks`
- optional CrUX popularity evidence
- future acquisition/measurement/learning workflows

## 8. Work order from here

1. Finish and verify the bounded batch DR implementation.
2. Configure and implement Feishu/Lark automatic persistence.
3. Run a controlled small dry-run and audit the records.
4. Then use `screening-backlinks` on normal real batches.
5. Build `discovering-backlinks` separately when needed.
6. Consider CrUX only if real usage shows that the existing evidence is insufficient.

This ordering keeps the personal tool simple and lets real usage determine whether more infrastructure is justified.
