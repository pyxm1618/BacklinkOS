# BacklinkOS V3 Product Strategy

## 1. Product Vision

BacklinkOS is a personal SEO backlink opportunity system for building and maintaining a reusable database of **general-purpose backlink opportunities**.

The system has two core intelligence capabilities:

1. **Discover** — find potential backlink opportunities.
2. **Screen** — verify whether those candidates are currently executable and worth keeping, then assign A/B/C/D/F.

Verified opportunities are persisted to Feishu/Lark Base for later use.

BacklinkOS does **not** evaluate topical relevance to a promoted website. It does not perform project-to-opportunity matching. The opportunity database is intentionally reusable across different websites and industries.

## 2. Core Problem

Commercial SEO tools expose large amounts of backlink data, but a personal backlink workflow still has two difficult problems:

1. finding enough potentially reproducible backlink opportunities
2. verifying whether each discovered opportunity still works today and is worth keeping

The second problem is already handled by `screening-backlinks`.

The remaining core product gap is the first problem: systematically discovering new backlink candidates and feeding them into the existing screening pipeline.

## 3. Product Boundary

BacklinkOS is not:

- an Ahrefs replacement
- a massive backlink index
- a spam automation system
- a generic CRM
- a SaaS product
- a topical-relevance engine
- a Project × Opportunity matching system

The V3 core workflow is:

```text
Discover
  ↓
Screen
  ↓
Persist
```

Where:

- `discovering-backlinks` finds candidate opportunities.
- `screening-backlinks` verifies, evaluates, and grades those candidates.
- Feishu/Lark Base stores the verified opportunity records and supporting evidence.

Discovery and screening must remain separate responsibilities. A historical backlink, search result, directory listing, community page, resource page, or other discovery source may reveal a candidate, but it does not prove that the candidate is currently usable.

## 4. Opportunity Model

BacklinkOS stores **general-purpose backlink opportunities**.

An opportunity is evaluated on properties of the opportunity itself, such as:

- whether the site/page still exists
- whether an ordinary user can reach a real publishing path
- whether that placement can create an external link
- registration/login requirements
- free/paid status
- placement type
- actual final-link `rel` attribute
- Ahrefs DR
- authoritative domain age when available
- optional traffic evidence when it materially helps the decision
- broader site/platform quality and spam/manipulation signals

The database may store a broad `行业` classification describing the source site/platform, but this is descriptive metadata only.

There is no `相关度` field, no topical-relevance score, and no future Project × Opportunity matching layer in the V3 scope.

## 5. `screening-backlinks`: Implemented Evaluation Layer

`screening-backlinks` receives already-discovered candidate URLs/domains and determines whether each candidate is a valid reusable backlink opportunity.

It is responsible for:

1. normalizing candidates and deduplicating domain-wide metric work
2. verifying current publishability
3. verifying registration/login and free/paid status
4. identifying the actual placement type and publishing entry
5. verifying Dofollow/Nofollow from same-type final HTML when possible
6. retrieving Ahrefs DR through the project metrics API
7. retrieving authoritative domain-age evidence through the project API
8. using traffic evidence selectively when it materially helps the decision
9. assigning A/B/C/D/F from verified evidence
10. building auditable main/evidence records
11. persisting records to Feishu/Lark Base

The operational rating is A/B/C/D/F:

- A/B/C/D are priority grades for publishable opportunities.
- F is a verified hard rejection for a non-executable or unsafe opportunity, not a synonym for low quality.
- Missing evidence remains unknown rather than being converted to zero, false, Nofollow, or F.
- No topical relevance is used in the rating.

This evaluation layer is already implemented. It should not be duplicated inside discovery.

## 6. `discovering-backlinks`: Remaining Core Module

`discovering-backlinks` is the remaining core V3 capability.

Its job is only to answer:

> Where are the potential general-purpose backlink opportunities?

Potential discovery sources include:

- competitor backlinks
- search results
- directories
- communities and forums
- resource pages
- profile pages
- blog/comment footprints
- Web 2.0 platforms
- classifieds
- previously successful opportunity patterns
- other sources that can yield candidate URLs or domains

Discovery should produce candidate records with enough provenance to understand where each candidate came from, then hand those candidates to `screening-backlinks`.

A minimal discovery output may include:

```text
candidate_url
source_url
source_type
possible_placement_type
discovered_at
```

Discovery must **not** duplicate screening work. It should not independently decide final publishability, Dofollow/Nofollow, pricing, DR, domain age, traffic quality, or A/B/C/D/F when those facts belong to `screening-backlinks`.

Historical backlink existence is discovery evidence only. Current usability must be verified by screening.

## 7. Current Technical Architecture

BacklinkOS currently uses two GitHub repositories with explicit responsibilities.

### `pyxm1618/BacklinkOS`

Owns:

- product strategy
- `screening-backlinks` Skill
- future `discovering-backlinks` Skill
- evidence/rating rules
- Feishu/Lark persistence workflow
- backlink opportunity records and lifecycle

### `pyxm1618/backlink-metrics-api`

Owns deterministic provider integrations and Vercel runtime, including:

- Ahrefs DR single lookup
- bounded Ahrefs DR batch lookup
- selective Crawlora total-monthly-visits lookup
- domain-age lookup
- provider normalization/failure semantics
- executable provider tests

Provider implementation code should not be duplicated inside the Skills repository.

There is no current requirement for a separate Web UI, Python backend, distributed worker system, or database server merely to satisfy the personal-use workflow.

## 8. Screening Scale and Batch Strategy

Typical screening input is roughly **100–1000 candidate URLs per run**.

For a normal run:

1. normalize inputs
2. deduplicate domain-wide metric work
3. query Ahrefs DR in bounded sequential chunks
4. verify placement-specific facts independently
5. use Crawlora only for the smaller subset where a concrete monthly-visits estimate helps the decision
6. build auditable A/B/C/D/F records
7. persist verified records to Feishu/Lark Base

The system intentionally avoids 100K-scale ingestion, distributed workers, and unnecessary queue infrastructure.

## 9. Traffic Strategy

Traffic is optional supporting evidence, not a mandatory lookup for every candidate.

Current automated numeric source:

- Crawlora / SimilarWeb public surface, used selectively as a medium-confidence total-monthly-visits estimate

Important semantics:

- Crawlora positive current Visits may be confirmed evidence
- Crawlora raw zero is unknown, not a real confirmed zero
- organic-search traffic and total monthly visits remain separate metrics
- traffic alone never causes F

CrUX remains an optional future evidence source only if real screening usage proves that it adds useful information. It is not part of the core V3 gap.

## 10. Persistence

Feishu/Lark Base is the production persistence target.

The visible operational table stays compact, while supporting evidence may live in linked/separate evidence records.

Automatic Feishu/Lark persistence is **implemented and production-validated**.

The production workflow supports:

- protected schema setup
- deterministic main-record upsert
- deterministic evidence-record upsert
- exact-key lookup
- create/update without duplicate logical records

Persistence is therefore not a remaining core V3 implementation gap.

## 11. What V3 Explicitly Does Not Build

- topical relevance scoring
- Project × Opportunity matching
- destination-site relevance decisions
- Ahrefs replacement
- massive backlink crawler/index
- 100K-scale processing infrastructure
- distributed job system
- automatic backlink spam system
- black-box weighted SEO score
- unnecessary UI/backend layers before real usage proves they are needed

## 12. Current Completion State

### Implemented

- `screening-backlinks` evidence and rating workflow
- current publishability verification contract
- Ahrefs DR integration and bounded batch processing
- selective traffic evidence
- authoritative domain-age workflow
- A/B/C/D/F decision semantics
- Feishu/Lark automatic persistence and production verification

### Remaining core capability

- `discovering-backlinks`

Therefore the current BacklinkOS V3 development focus is straightforward:

> Build a dedicated `discovering-backlinks` Skill that finds general-purpose backlink candidates and feeds them into the already-implemented `screening-backlinks` pipeline.

## 13. Current Roadmap

1. Use `screening-backlinks` on real candidate batches and fix only problems revealed by real usage.
2. Design and implement `discovering-backlinks` as a separate Skill.
3. Connect discovery output directly into the existing screening pipeline.
4. Add optional evidence or infrastructure only when real usage demonstrates a concrete gap.

The V3 principle is:

> Find more real opportunities, verify them rigorously, and avoid rebuilding functionality that already exists.
