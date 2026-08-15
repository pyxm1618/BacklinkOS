# Traffic Evidence Architecture

## Purpose

Traffic is supporting evidence for backlink screening. It is not one interchangeable number and it never independently causes `F`.

Keep these semantics separate:

- `popularity_rank`: relative real-user popularity evidence, not visits
- `total_monthly_visits_estimate`: modelled estimate of total visits across channels
- `organic_search_traffic_estimate`: modelled estimate of organic-search clicks/visits

Never copy one metric into another field.

## Current implementation state

As of the current repository state:

- Traffic evidence semantics/provider contracts are documented.
- CrUX runtime adapter is **not implemented**.
- Crawlora runtime adapter **is implemented** at `GET /api/traffic?domain=<domain>`.
- Crawlora is `PRODUCTION_APPROVED` as a **selective, medium-confidence single-domain fallback** for positive `total_monthly_visits_estimate` values.
- Crawlora is **not** the bulk-first layer and is not treated as authoritative analytics.
- Crawlora raw zero is not a confirmed zero; live validation proved an obviously nonexistent domain can return HTTP 200/OK with `Visits=0`.
- Executable Crawlora adapter tests exist at `tests/crawlora-traffic.test.ts`; production builds run them before `next build` and they consume no Crawlora credits.
- The traffic regression cases in `test-cases.md` remain **non-executable behavioral scenarios**, separate from adapter tests.
- Full validation evidence is recorded in `docs/crawlora-live-validation-2026-08-15.md`.

Do not describe the full Traffic system as production-complete while CrUX bulk runtime remains unimplemented.

## Layer 1 — Google CrUX popularity evidence

### Production lookup surface

Google Chrome UX Report (CrUX) is real-user Chrome field data. In BigQuery, the production lookup for this workflow should use the materialized table:

`chrome-ux-report.materialized.metrics_summary`

Relevant fields:

- `yyyymm`
- `origin`
- `rank`

`rank` is a coarse relative-popularity ranking for the **origin**, based on observed navigations. It is not a monthly-visit count.

The workflow does not depend on a raw/experimental nested popularity field; use the documented materialized `metrics_summary.rank` surface unless a future implementation has a specific reason to use another table.

### Coverage semantics

CrUX includes origins that satisfy Google's eligibility/privacy/popularity requirements. Therefore:

- row found -> observation `traffic_status=CONFIRMED`, `coverage_status=FOUND`
- no row in the selected release -> `traffic_status=NOT_COVERED`, `coverage_status=NOT_COVERED`
- query/network/auth failure -> `LOOKUP_FAILED` or `PROVIDER_ERROR`
- `NOT_COVERED` does **not** mean zero visits

### Origin normalization

CrUX keys by origin, so scheme and host matter.

Preferred input is the final origin of the verified publishing entry/sample URL, for example:

`https://www.example.com`

Do not remove `www.` or the scheme before a CrUX lookup.

If screening starts with only a bare domain and no final URL is known, either postpone CrUX until the publishing origin is known, or query a bounded set of plausible origins separately:

- `https://example.com`
- `https://www.example.com`
- `http://example.com`
- `http://www.example.com`

Keep returned rows per origin. Do not invent one authoritative domain-wide CrUX rank from several origins.

### Bulk query strategy

Use BigQuery for bulk work, not one point query per candidate.

For normal targeted batches, query the latest month in `chrome-ux-report.materialized.metrics_summary` and join/filter on candidate origins.

Conceptual query:

```sql
WITH latest AS (
  SELECT MAX(yyyymm) AS yyyymm
  FROM `chrome-ux-report.materialized.metrics_summary`
)
SELECT
  m.yyyymm,
  m.origin,
  m.rank
FROM `chrome-ux-report.materialized.metrics_summary` AS m
JOIN latest USING (yyyymm)
WHERE m.origin IN UNNEST(@origins)
```

For very large sets such as 100K+ domains, load candidate origins into a temporary/staging table and join once against the latest summary table. Do not issue 100K independent queries.

Cache key:

`Google CrUX + origin + yyyymm`

CrUX BigQuery releases monthly; re-querying the same origin for the same `yyyymm` is wasted work.

### Cost and onboarding caveat

A Google Cloud account/project is required to query CrUX through BigQuery.

Current Google Cloud public-dataset documentation says the first 1 TiB of query data processed per month is free and public datasets can be queried without enabling billing within that free tier. BigQuery also offers a sandbox without a credit card/billing account. The CrUX-specific setup page may still prompt for billing/card information depending on account/onboarding flow.

Therefore do **not** encode `billing/card required` as a universal invariant. Treat it as an environment/onboarding condition and verify the actual Google Cloud account setup used by the runtime.

Use the materialized summary and select only required columns to minimize bytes scanned.

### Confidence

CrUX popularity evidence has `traffic_confidence=high` for the narrow claim it supports:

> Google observed enough eligible Chrome navigations to place this exact origin in a coarse popularity bucket.

It has no authority for a monthly-visits number because it does not provide one.

Official references:

- https://developer.chrome.com/docs/crux/bigquery/
- https://developer.chrome.com/docs/crux/methodology/metrics
- https://developer.chrome.com/docs/crux/methodology/tools
- https://cloud.google.com/bigquery/public-data
- https://cloud.google.com/bigquery/docs/sandbox

## Layer 2 — Numeric total-monthly-visits estimate

### Provider: Crawlora SimilarWeb public-surface endpoint

Status:

`PRODUCTION_APPROVED`

Approval scope:

> selective, medium-confidence, single-domain fallback for positive current `data.Engagments.Visits` values.

It is **not** the 100K-domain bulk layer and must not be treated as first-party analytics.

Current documented endpoint:

`GET https://api.crawlora.net/api/v1/similarweb/web/{domain}`

Authentication:

`x-api-key: <CRAWLORA_API_KEY>`

Current documented cost/limits:

- 5 credits per successful request
- Free plan: 2,000 credits/month
- Free daily cap: 500 credits
- Free rate limit: 5 requests/minute
- no card required for the Free plan
- Crawlora states that successful 2xx responses consume credits

At 5 credits/request, the Free plan supports roughly 400 successful monthly lookups, subject to daily/rate limits. Reserve it for important, ambiguous, high-value, or boundary candidates rather than every domain in a large queue.

Crawlora states that this is not the official Similarweb API; values are modelled third-party estimates from a SimilarWeb public surface.

Official references:

- https://crawlora.net/platforms/similarweb
- https://crawlora.net/playground/similarweb-web
- https://crawlora.net/pricing
- https://crawlora.net/docs/authentication

### Live-validated raw schema

Own-key live validation on 2026-08-15 confirmed this relevant shape:

```json
{
  "code": 200,
  "msg": "OK",
  "data": {
    "Engagments": {
      "Month": "7",
      "Year": "2026",
      "Visits": "637885711"
    },
    "EstimatedMonthlyVisits": {
      "2024-09-01": 0,
      "2024-10-01": 0,
      "2024-11-01": 0
    },
    "SnapshotDate": "2026-07-01T00:00:00Z"
  }
}
```

Implementation consequences:

- `data.Engagments.Visits` is the canonical first-version current visits field.
- `Visits` is a numeric string and must be parsed safely.
- `Engagments.Month` + `Engagments.Year` define the provider period.
- preserve `SnapshotDate` as `provider_snapshot_date` when present.
- `EstimatedMonthlyVisits` is **not** a canonical current-value source. Live GitHub data showed stale 2024 month keys with zero values while current `Engagments.Visits` was 637,885,711.
- do not derive current traffic or zero semantics from those stale historical zero entries.

### Project runtime adapter

Canonical project endpoint:

`GET https://backlink-metrics-api.vercel.app/api/traffic?domain=<domain>`

Responsibilities are deliberately narrow:

`domain input -> normalize/validate -> Crawlora request -> parse -> normalized traffic observation`

It does not perform rating, DR, CrUX, RDAP, Discovery, relevance, or Feishu persistence.

Current bounded upstream timeout:

20 seconds.

The initial 12-second bound produced a real `LOOKUP_FAILED` for `google.com`; the same domain succeeded under the bounded 20-second timeout. Do not remove the timeout entirely.

Normalized response fields include:

- `domain`
- `metric_type=total_monthly_visits_estimate`
- `value`
- `raw_value`
- `status`
- `source=Crawlora / Similarweb public surface`
- `period`
- `provider_snapshot_date`
- `checked_at`
- `confidence`
- `provider_status`
- `provider_code`
- `provider_message`
- `raw_field_used`
- limited `provider_schema` evidence

The adapter does not return the full upstream payload or the API key.

### Domain normalization

Crawlora is domain-scoped, not CrUX-origin-scoped.

Accepted examples normalize to `github.com`:

- `github.com`
- `www.github.com`
- `https://github.com/`
- `https://www.github.com/openai`

Paths/query strings are removed, host is lowercased, and leading `www.` is removed. Malformed values, `localhost`, and IP literals are rejected locally before provider credits can be consumed.

A production request with `https://www.github.com/openai` was live-validated to normalize to `github.com` and return the same current observation.

### Live validation matrix summary

The representative matrix covered 16 unique domains across very large, medium, small, and nonexistent cases.

Examples:

- `google.com` -> 86,958,861,491
- `youtube.com` -> 30,198,422,372
- `reddit.com` -> 4,321,544,257
- `wikipedia.org` -> 3,497,809,347
- `github.com` -> 637,885,711
- `cloudflare.com` -> 57,747,445
- `vercel.com` -> 30,777,447
- `ahrefs.com` -> 7,973,809
- `mpeblog.com` -> 13,012
- `craftberrybush.com` -> 11,929
- `designertoblog.com` -> 3,487
- `collectblogs.com` -> 1,861
- `look4blog.com` -> 824
- `getblogs.net` -> 485
- `mybloglicious.com` -> raw 0 -> `UNKNOWN`
- deliberately nonexistent `.com` -> raw 0 -> `UNKNOWN`

All successful current observations above used period `2026-07` during validation.

See the full matrix and secondary comparisons in:

`docs/crawlora-live-validation-2026-08-15.md`

### Zero / no-coverage semantics

This is a provider-specific production rule.

A deliberately nonexistent `.com` domain returned:

- HTTP 200
- `code=200`
- `msg=OK`
- current period
- raw `data.Engagments.Visits="0"`

A real small domain (`mybloglicious.com`) also returned raw zero.

Therefore:

> Crawlora raw `Visits=0` is semantically ambiguous and cannot be trusted as a genuine estimated zero.

Production mapping:

- raw positive numeric `data.Engagments.Visits` -> normalized positive value + `CONFIRMED`
- raw `Visits=0` -> normalized `value=null`, retain `raw_value=0`, `traffic_status=UNKNOWN`
- missing/unusable `Visits` -> `UNKNOWN`
- explicit provider no-data signal, if one appears -> `NOT_COVERED`

The current Crawlora adapter does **not** emit `CONFIRMED_ZERO` from a raw zero.

General `CONFIRMED_ZERO` remains available in the cross-provider traffic schema for a future provider whose zero semantics are actually verified.

### Provider observation status mapping

`traffic_status` describes one observation/provider call only:

- successful response + positive numeric current Visits -> `CONFIRMED`
- explicit provider no-data signal -> `NOT_COVERED`
- timeout, DNS, transport failure -> `LOOKUP_FAILED`
- 401/403/429/5xx, malformed JSON, upstream/challenge/provider-envelope failure -> `PROVIDER_ERROR`
- successful response but no usable current numeric Visits -> `UNKNOWN`

A 2xx response with a missing field is not confirmed zero.

### HTTP mapping

Project route behavior:

- invalid/missing domain -> HTTP 400
- missing `CRAWLORA_API_KEY` -> HTTP 500
- successful observation, including `UNKNOWN` or `NOT_COVERED` -> HTTP 200
- timeout/transport lookup failure -> HTTP 504
- provider 429 -> HTTP 429 with normalized `PROVIDER_ERROR`
- other provider failures -> HTTP 502 with normalized `PROVIDER_ERROR`

Credentials are never echoed.

### Secondary plausibility validation

At least five live results were compared against independent modeled traffic sources. The purpose was order-of-magnitude plausibility, not exact equality.

Examples:

- Crawlora `google.com` 86.96B vs traffic.cv 84.9B (adjacent months)
- Crawlora `youtube.com` 30.20B vs traffic.cv 28.8B
- Crawlora `reddit.com` 4.32B vs traffic.cv 4.2B
- Crawlora `wikipedia.org` 3.50B vs traffic.cv 3.3B
- Crawlora `github.com` 637.9M vs HypeStat 627.6M / cited SimilarWeb 615.2M; traffic.cv also showed 504.0M in an indexed report
- Crawlora `cloudflare.com` 57.75M vs HypeStat cited SimilarWeb 50.86M and Semrush 89.74M
- Crawlora `ahrefs.com` 7.97M vs Semrush 24.61M, a material roughly 3x difference

The matrix did not show a systematic absurdity such as very large sites becoming tiny or small sites becoming billions. Provider variance can still be material, so confidence remains `medium`.

### Confidence

Crawlora numeric traffic uses:

`traffic_confidence=medium`

Reason:

- current field/period/schema are live validated;
- values were directionally plausible across a representative matrix;
- the underlying number is still a modeled third-party estimate rather than first-party analytics;
- provider-to-provider disagreement can be material.

## Layer 3 — Manual secondary evidence

### traffic.cv

Use as manual/browser secondary evidence for important or conflicting cases unless a stable public production API contract is later confirmed.

Do not scrape the browser product as a default automation path.

Metric type must reflect what the page actually shows. A total-visits estimate is stored as `total_monthly_visits_estimate`.

References:

- https://traffic.cv/
- https://traffic.cv/bulk

### Ahrefs Traffic Checker

Ahrefs Organic Traffic is an estimated monthly figure of Google organic-search clicks/traffic, not total all-channel monthly visits.

If manually used, store:

`traffic_metric_type=organic_search_traffic_estimate`

Do not put this value into visible `月访问量`.

No free public production traffic API suitable for this pipeline has been validated. Do not automate by scraping the free checker.

References:

- https://ahrefs.com/traffic-checker
- https://help.ahrefs.com/en/articles/1863206-what-is-organic-traffic-in-ahrefs-and-how-do-we-calculate-it
- https://help.ahrefs.com/en/articles/1115995-is-organic-traffic-a-monthly-figure-based-on-past-30-days

## Future paid provider — not a current dependency

DataForSEO can remain a future organic-search traffic provider if its economics/onboarding later fit the project. It is not a current mandatory dependency.

Do not silently enable a paid provider without explicit selection and validation.

## Excluded from the current production path

Do not use as default production adapters unless revalidated later:

- WebsiteTrafficChecker.net
- Apify/community gateways for DataForSEO
- arbitrary RapidAPI traffic endpoints
- scraping traffic.cv or Ahrefs free checker pages

## Observation model vs aggregate review model

One placement/domain can have multiple traffic observations. Preserve them separately.

Each observation has its own `traffic_status`:

- `CONFIRMED`
- `CONFIRMED_ZERO`
- `NOT_COVERED`
- `LOOKUP_FAILED`
- `PROVIDER_ERROR`
- `UNKNOWN`

`CONFLICT` is **not** a provider observation status.

Cross-observation review belongs to an aggregate layer:

- `traffic_review_status=OK`
- `traffic_review_status=NEEDS_REVIEW`
- `traffic_review_status=CONFLICT`
- optional `traffic_conflict=true/false`
- `traffic_review_notes`

Example: two providers may both be `CONFIRMED` while their values conflict materially; the aggregate review state is `CONFLICT`.

Recommended Crawlora positive observation:

```json
{
  "traffic_metric_type": "total_monthly_visits_estimate",
  "traffic_value": 52300,
  "traffic_source": "Crawlora / SimilarWeb public surface",
  "traffic_status": "CONFIRMED",
  "traffic_period": "2026-07",
  "provider_snapshot_date": "2026-07-01T00:00:00.000Z",
  "traffic_checked_at": "2026-08-15T00:00:00Z",
  "traffic_confidence": "medium",
  "raw_field_used": "data.Engagments.Visits",
  "notes": ""
}
```

Crawlora raw-zero example:

```json
{
  "traffic_metric_type": "total_monthly_visits_estimate",
  "traffic_value": null,
  "traffic_raw_value": 0,
  "traffic_source": "Crawlora / SimilarWeb public surface",
  "traffic_status": "UNKNOWN",
  "traffic_period": "2026-07",
  "traffic_confidence": "none",
  "notes": "Raw zero is ambiguous; live validation proved a nonexistent domain can return Visits=0 with HTTP 200/OK."
}
```

CrUX example:

```json
{
  "traffic_metric_type": "popularity_rank",
  "traffic_value": null,
  "traffic_source": "Google CrUX BigQuery",
  "traffic_status": "CONFIRMED",
  "traffic_period": "2026-06",
  "traffic_checked_at": "2026-08-15T00:00:00Z",
  "traffic_confidence": "high",
  "traffic_origin": "https://www.example.com",
  "popularity_rank": 100000,
  "popularity_bucket": "Top 100K",
  "coverage_status": "FOUND",
  "notes": "Popularity evidence only; not monthly visits."
}
```

Organic-search evidence is a separate observation:

```json
{
  "traffic_metric_type": "organic_search_traffic_estimate",
  "traffic_value": 12000,
  "traffic_source": "Ahrefs Traffic Checker",
  "traffic_status": "CONFIRMED",
  "traffic_period": "2026-08",
  "traffic_checked_at": "2026-08-15T00:00:00Z",
  "traffic_confidence": "medium"
}
```

Conflict aggregate example:

```json
{
  "traffic_review_status": "CONFLICT",
  "traffic_conflict": true,
  "traffic_review_notes": "Two confirmed total-monthly-visits estimates differ materially. Preserve both observations and review periods/coverage."
}
```

## Visible `月访问量`

Keep the main Feishu table compact.

`月访问量` means:

> numeric `total_monthly_visits_estimate` for a clearly identified month/provider.

This field is intentionally named `月访问量` rather than the ambiguous `月流量`.

If no such value exists, store `未确认`.

Do not place any of these into `月访问量`:

- CrUX rank/bucket
- organic-search traffic estimate
- global/category rank
- inferred traffic derived from rank
- provider no-data/error placeholders
- Crawlora raw zero
- stale `EstimatedMonthlyVisits` zero entries

If multiple current total-monthly-visits providers materially disagree, keep `月访问量=未确认` until reviewed or resolved by a documented precedence rule. Preserve all observations.

## Rating use

Traffic is evidence, not a score formula.

Positive traffic/popularity evidence can support priority when it demonstrates real users, exposure, or brand/referral potential.

Confirmed low traffic can be a negative signal only in context with other weaker-quality evidence.

Traffic unknown is neutral absence of evidence; it must not lower a rating by itself.

Traffic must never independently produce `F`.

Special cases:

- high DR + weak/no popularity evidence + poor pages + abnormal outbound-link footprint -> quality review
- high traffic/popularity + credible Nofollow placement -> referral/brand value can remain positive
- traffic unknown + otherwise strong evidence -> do not downgrade solely for missing traffic
- provider disagreement -> keep observation statuses intact and set aggregate `traffic_review_status=CONFLICT`/`NEEDS_REVIEW`

## Scale, cache, and retry

For large queues:

1. deduplicate by canonical domain and exact CrUX origin
2. reuse evidence that is still within its provider period/freshness window
3. query CrUX in batches against the latest monthly summary once runtime exists
4. reserve Crawlora credits for boundary/high-value/no-coverage cases
5. use manual providers only when the decision justifies human effort

Retry only transient failures. Use backoff for rate limits and upstream errors. Do not repeatedly retry deterministic unknown/no-coverage observations.

Suggested cache keys:

- CrUX: `crux:{origin}:{yyyymm}`
- numeric provider: `{provider}:total_visits:{domain}:{provider_month}`
- manual evidence: `{provider}:{metric_type}:{domain}:{period}`

No cached value may be relabelled as fresher than its source period.

## Executable tests vs behavioral scenarios

Executable Crawlora adapter tests live in:

`tests/crawlora-traffic.test.ts`

Production build runs them before `next build`.

Latest validation covers 14 executable tests including:

- domain normalization and invalid inputs
- positive Visits parsing
- period parsing
- SnapshotDate preservation
- stale `EstimatedMonthlyVisits` zero trap
- missing field -> UNKNOWN
- explicit no-data shape -> NOT_COVERED
- raw zero -> UNKNOWN
- 401/403, 429 and 5xx mapping
- timeout/network mapping
- malformed JSON/provider envelope handling
- Unknown never becomes zero

Behavioral screening scenarios remain in `references/test-cases.md`. Keep these two forms of validation separate in reports.
