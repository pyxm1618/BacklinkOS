# BacklinkOS V3 Product Strategy

## 1. Product Vision

BacklinkOS is a personal SEO Link Opportunity Intelligence System.

It helps a solo operator who manages multiple websites discover, evaluate, execute, record, and learn from backlink opportunities.

The goal is not to collect the largest backlink dataset. The goal is to make better acquisition decisions with less repeated work.

## 2. Core Problem

Commercial SEO tools already expose large amounts of backlink data. The difficult parts for personal use are:

1. finding opportunities that may actually be reproducible
2. verifying whether an opportunity still works today
3. collecting trustworthy evidence without turning missing data into fake facts
4. prioritizing limited execution time
5. recording outcomes so the same research does not need to be repeated

BacklinkOS should optimize judgment quality and execution efficiency rather than data volume.

## 3. Product Positioning

BacklinkOS is not:

- an Ahrefs replacement
- a massive backlink index
- a spam automation system
- a generic CRM
- a SaaS product

The long-term loop is:

```text
Discover
  ↓
Screen
  ↓
Decide
  ↓
Act
  ↓
Record
  ↓
Learn
```

Discovery and screening are separate capabilities. A discovery source may produce a candidate; it does not prove that the candidate is currently usable.

## 4. Current User Scenario

The system is for one person operating multiple websites.

Typical screening input is roughly **100–1000 candidate URLs per run**. The system does not need 100K-scale ingestion, distributed workers, or a large crawler infrastructure.

A run may take several minutes or longer when external providers are rate-limited. That is acceptable for the current personal-use workflow.

## 5. Current Screening Evidence

`screening-backlinks` evaluates already-discovered opportunities using current evidence such as:

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

### No topical relevance in the shared opportunity database

BacklinkOS is shared across multiple outbound websites and industries. Therefore topical relevance is **not an intrinsic property of an opportunity** and is not part of A/B/C/D/F screening.

The database may store the source site's broad `行业` classification, but there is no `相关度` field in the current screening schema.

If project-specific relevance is ever needed, it belongs to a later **Project × Opportunity matching** step, not the reusable opportunity record itself.

## 6. Current Screening Decision Model

The current operational rating is A/B/C/D/F.

- A/B/C/D are publishable opportunity priority grades based on evidence.
- F is a verified hard rejection for a non-executable/unsafe opportunity, not a synonym for low quality.
- Missing evidence is preserved as unknown rather than invented as zero/false/nofollow/F.
- No weighted black-box score is used.

## 7. Current Technical Architecture

BacklinkOS currently uses two GitHub repositories with explicit responsibilities.

### `pyxm1618/BacklinkOS`

Owns:

- product strategy
- `screening-backlinks` Skill
- evidence/rating rules
- persistence contract
- future `discovering-backlinks` Skill
- future acquisition/learning workflows

### `pyxm1618/backlink-metrics-api`

Owns deterministic provider integrations and Vercel runtime:

- Ahrefs DR single lookup
- bounded Ahrefs DR batch lookup
- selective Crawlora total-monthly-visits lookup
- provider normalization/failure semantics
- executable provider tests

Do not duplicate provider implementation code inside the Skill repository.

There is no current requirement to build a separate Web UI, Python backend, distributed worker system, or database server merely to satisfy the MVP. Those should be introduced only if real usage proves they are necessary.

## 8. Realistic Batch Strategy

For a normal 100–1000-candidate screening run:

1. normalize inputs
2. deduplicate domain-wide metric work
3. query Ahrefs DR in bounded sequential chunks
4. verify placement-specific facts independently
5. use Crawlora only for the smaller subset where a concrete monthly-visits estimate helps the decision
6. build auditable A/B/C/D/F records
7. persist to Feishu/Lark once the integration is configured

This is deliberately simpler than a large-scale queue system.

## 9. Traffic Strategy

Traffic is optional supporting evidence, not a mandatory lookup for every candidate.

Current automated numeric source:

- Crawlora / SimilarWeb public surface, used selectively as a medium-confidence total-monthly-visits estimate

Important semantics:

- Crawlora positive current Visits may be confirmed evidence
- Crawlora raw zero is unknown, not a real confirmed zero
- organic-search traffic and total monthly visits remain separate metrics
- traffic alone never causes F

CrUX is an optional future enhancement if real usage shows that popularity evidence adds enough value. It is not a current MVP dependency or blocker.

## 10. Persistence

Feishu/Lark Base is the current persistence target.

The visible operational table stays compact, while supporting evidence may live in linked/separate evidence records.

The remaining implementation gap for the current `screening-backlinks` workflow is automatic Feishu/Lark persistence.

Until that integration is actually working, the Skill may prepare import-ready records but must never claim that data was written successfully.

## 11. Future Modules

Future work is intentionally separate from the current screening implementation:

### `discovering-backlinks`

Find candidate opportunities from competitor backlinks, search results, directories, communities, resource pages, and other sources.

Output candidates into `screening-backlinks`; do not merge discovery and screening into one monolithic Skill.

### Acquisition / Learning

Later stages may track execution, successful placements, failures, reusable patterns, and site-level history.

These should be driven by actual usage rather than built speculatively.

## 12. What We Explicitly Do Not Build Now

- Ahrefs replacement
- massive backlink crawler/index
- 100K-scale processing infrastructure
- distributed job system
- automatic backlink spam system
- black-box weighted SEO score
- topical relevance inside the shared screening grade
- unnecessary UI/backend layers before the workflow proves they are needed

## 13. Current Roadmap

1. Finish and verify realistic batch screening infrastructure.
2. Configure and implement Feishu/Lark automatic persistence.
3. Run a controlled small dry-run and audit the output.
4. Use `screening-backlinks` on normal real batches.
5. Build `discovering-backlinks` separately when needed.
6. Add optional evidence/infrastructure only when real usage demonstrates a gap.

The V3 principle is simple:

> Better evidence, better decisions, less repeated work — without building infrastructure the personal workflow does not need.
