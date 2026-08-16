# Realistic Batch Screening Design

## Goal

Finish the current `screening-backlinks` system for the user's real operating scale: typical batches of roughly **100–1000 candidate URLs** for a personal-use tool.

This design replaces earlier 100K-scale assumptions. The objective is a simple, reliable workflow, not large-scale data engineering.

## Scope Decision

This implementation will leave only **Feishu/Lark persistence** as the remaining unfinished part of the current screening system.

The following are in scope:

- update product/architecture/Skill documentation from 100K-scale assumptions to a typical 100–1000-item batch model
- add a simple batch DR capability suitable for hundreds to about one thousand candidates
- normalize and deduplicate candidate domains before metric lookup
- support bounded concurrency / pacing and retry for temporary rate-limit or provider failures
- keep partial progress/results so one failed domain does not invalidate the batch
- preserve `Unknown != 0` semantics
- keep Crawlora as a selective follow-up source for important/ambiguous candidates rather than querying every domain
- keep existing single-domain `/api/dr` and `/api/traffic` contracts working
- update automated tests and production verification accordingly

The following are explicitly out of scope:

- CrUX runtime
- 100K-scale ingestion or queueing
- distributed workers
- complex job infrastructure
- `discovering-backlinks`
- Feishu/Lark write integration
- new rating semantics
- topical relevance
- new traffic providers

## Scale Model

Typical input:

- about 100–1000 candidate URLs per run
- duplicate URLs/domains are expected
- runs may take several minutes; instant completion is not required
- personal use, so operational simplicity is more important than maximum throughput

The system should reduce work before external calls:

1. accept candidate URLs/domains
2. normalize hostnames
3. deduplicate domains
4. query DR for unique domains
5. preserve per-domain success/unknown/error result
6. reuse that domain result for all placements on the same domain
7. use Crawlora only when screening needs a concrete total-monthly-visits estimate for a smaller subset

## Batch DR Design

Add a deterministic batch endpoint to `backlink-metrics-api`, conceptually:

`POST /api/dr/batch`

Input:

```json
{
  "domains": ["example.com", "https://www.github.com/openai", "example.com"]
}
```

The endpoint should:

- validate the request shape
- normalize domains using one shared normalization implementation
- deduplicate normalized domains
- reject malformed/local/IP-like inputs without spending Ahrefs calls
- process valid unique domains with conservative bounded concurrency/pacing
- retry only temporary failures such as 429/5xx, with bounded backoff
- never retry deterministic invalid input
- return one result per unique normalized domain
- not fail the whole batch because one domain failed

Representative result shape:

```json
{
  "requested": 3,
  "unique_domains": 2,
  "results": [
    {
      "domain": "example.com",
      "dr": 42,
      "status": "CONFIRMED",
      "source": "Ahrefs",
      "checked_at": "<ISO>"
    },
    {
      "domain": "github.com",
      "dr": 97,
      "status": "CONFIRMED",
      "source": "Ahrefs",
      "checked_at": "<ISO>"
    }
  ]
}
```

For provider failure or unusable data, `dr` must be `null` and status must explicitly indicate the failure/unknown state. Missing DR must never become zero.

The existing single-domain `/api/dr` endpoint remains supported.

## Shared Normalization

The current DR and Crawlora paths use separate normalization logic. This implementation should introduce a small shared domain normalizer so batch DR and single-domain DR do not diverge.

Required behavior:

- lowercase hostname
- strip leading `www.` for domain-scoped metrics
- remove path/query/fragment
- reject empty input
- reject localhost
- reject IP literals
- reject malformed hostnames

CrUX-origin normalization is irrelevant because CrUX is no longer part of this implementation.

## Crawlora Role

Crawlora remains unchanged as a selective, medium-confidence total-monthly-visits estimate.

Do not batch-query Crawlora for every input domain.

Use it only when the screening decision benefits from a concrete traffic estimate, such as important candidates, ambiguous cases, or higher-priority domains after other evidence is collected.

Existing rules remain:

- positive current `data.Engagments.Visits` -> confirmed estimate
- raw zero -> unknown, not confirmed zero
- missing/malformed value -> unknown
- provider failure -> explicit failure status
- `EstimatedMonthlyVisits` is not the canonical current value

## Screening Skill Changes

The Skill should describe the real workflow rather than a large-scale architecture:

- typical batch = 100–1000 candidates
- normalize/deduplicate before repeated domain-level metric calls
- batch DR is appropriate for the full unique-domain set
- Crawlora is selective, not universal
- no CrUX dependency is required for the current screening MVP
- unknown traffic remains neutral
- Feishu persistence is the only planned unfinished integration after this implementation

This does not change A/B/C/D/F rules.

## Error Handling

Batch processing must preserve partial results.

Examples:

- malformed input -> local invalid result; no provider request
- Ahrefs rate limit -> bounded retry/backoff, then explicit provider-error result if still failing
- Ahrefs network/5xx -> bounded retry, then explicit lookup/provider failure
- missing/invalid DR payload -> `dr=null`, never `0`
- one failed domain -> other domains continue

No API key or provider response containing credentials may be returned or logged.

## Testing

Add executable tests for:

- shared domain normalization
- URL/path/www normalization
- duplicate-domain collapse
- invalid/localhost/IP rejection
- successful batch DR mapping
- real numeric DR zero remains valid
- missing DR never becomes zero
- partial batch failure does not fail other results
- 429 retry behavior
- 5xx retry behavior
- bounded retry exhaustion
- single-domain DR regression
- Crawlora regression suite remains green

Production verification after deployment:

- batch request with duplicate/URL-form inputs
- single `/api/dr` fresh call
- `/api/traffic` positive fresh call
- Crawlora nonexistent-domain raw-zero regression

## Documentation Changes

Update current repository docs so future agents do not reintroduce 100K assumptions.

Use wording such as:

> Typical operating batch: 100–1000 candidate URLs. Prefer simple deduplication and bounded batch requests over large-scale queue infrastructure.

CrUX should be described as an optional future enhancement, not a current blocker or required next stage.

## Completion Definition

This implementation is complete when:

- 100K-scale assumptions are removed from current operating guidance
- batch DR for roughly 100–1000 candidate workflows is implemented and tested
- single-domain DR and Crawlora behavior remain intact
- production deployment is verified with fresh calls
- current docs and Skill agree on the 100–1000-item operating model
- no CrUX, Discovery, or Feishu implementation was added

After that point, the only remaining implementation task for the current `screening-backlinks` workflow is **Feishu/Lark persistence**.
