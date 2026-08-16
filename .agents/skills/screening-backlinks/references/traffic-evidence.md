# Traffic Evidence Architecture

## Purpose

Traffic is optional supporting evidence for backlink screening. It is not one interchangeable number and it never independently causes `F`.

Keep these semantics separate:

- `total_monthly_visits_estimate`: modelled estimate of total visits across channels
- `organic_search_traffic_estimate`: modelled estimate of organic-search clicks/visits
- `popularity_rank`: optional relative popularity evidence, not visits

Never copy one metric into another field.

## Current operating model

The current personal-use workflow typically screens roughly **100–1000 candidate URLs per run**.

Traffic is **not** queried for every candidate. The normal order is:

1. collect the facts already required for screening, including publishability, link attribute, Ahrefs DR, age, and platform quality
2. use Crawlora selectively when a concrete total-monthly-visits estimate materially helps an important, ambiguous, or higher-priority decision
3. use manual secondary traffic sources only when a conflict/decision justifies the extra effort
4. treat CrUX as an optional future enhancement, not a current dependency or blocker

This avoids spending Crawlora credits on low-value candidates and avoids unnecessary large-scale infrastructure.

## Current implementation state

- Crawlora runtime is implemented at `GET https://backlink-metrics-api.vercel.app/api/traffic?domain=<domain>`.
- Crawlora is `PRODUCTION_APPROVED` only as a **selective, medium-confidence single-domain source** for positive current `total_monthly_visits_estimate` values.
- Crawlora is not first-party analytics and is not authoritative truth.
- Crawlora raw zero is not a confirmed zero; live validation proved an obviously nonexistent domain can return HTTP 200/OK with `Visits=0`.
- Executable Crawlora tests live in `pyxm1618/backlink-metrics-api/tests/crawlora-traffic.test.ts` and mock the provider so CI consumes no credits.
- Full Crawlora validation evidence lives in `backlink-metrics-api/docs/crawlora-live-validation-2026-08-15.md`.
- CrUX runtime is not implemented because it is not required for the current workflow.

The absence of CrUX does **not** make the current screening Traffic evidence system incomplete. It is simply an optional future evidence source.

## Current numeric provider — Crawlora / SimilarWeb public surface

### Role

Use Crawlora when a concrete monthly-visits estimate is worth the lookup cost.

Good reasons include:

- a candidate is otherwise high priority and traffic could strengthen/conflict with that view
- DR/site-quality signals disagree materially
- a Nofollow placement may still have meaningful referral/brand value
- two candidates are otherwise similar and traffic helps prioritize effort

Do not call Crawlora merely because a domain exists in the batch.

### Provider endpoint

Upstream provider endpoint:

`GET https://api.crawlora.net/api/v1/similarweb/web/{domain}`

Authentication:

`x-api-key: <CRAWLORA_API_KEY>`

Project endpoint:

`GET https://backlink-metrics-api.vercel.app/api/traffic?domain=<domain>`

The project endpoint is the canonical runtime surface for the Skill.

### Live-validated raw schema

Own-key live validation confirmed this relevant shape:

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

- canonical current numeric field = `data.Engagments.Visits`
- `Visits` can be a numeric string and must be parsed strictly
- `Engagments.Month` + `Engagments.Year` define the provider period
- preserve `SnapshotDate` as `provider_snapshot_date` when present
- `EstimatedMonthlyVisits` is **not** the canonical current value; live GitHub data contained stale historical zero entries while current `Engagments.Visits` was strongly positive

### Zero / missing-data semantics

A deliberately nonexistent `.com` domain returned:

- HTTP 200
- provider `code=200`
- provider `msg=OK`
- current period
- raw `data.Engagments.Visits="0"`

A real small domain also returned raw zero.

Therefore current production mapping is:

- positive numeric current `Engagments.Visits` -> `CONFIRMED`, normalized numeric value
- raw `Visits=0` -> `UNKNOWN`, normalized `value=null`, preserve `raw_value=0`
- missing/malformed Visits -> `UNKNOWN`
- explicit provider no-data signal -> `NOT_COVERED`
- timeout/network failure -> `LOOKUP_FAILED`
- auth/rate-limit/5xx/malformed-provider failure -> `PROVIDER_ERROR`

The adapter does **not** emit `CONFIRMED_ZERO` from Crawlora raw zero.

A general future provider may use `CONFIRMED_ZERO` only after that provider's own zero semantics are documented/live-validated as a genuine zero estimate.

### Confidence

Crawlora observations use `traffic_confidence=medium` for positive numeric values.

Reason:

- field/period/schema are live validated
- representative large/medium/small domains produced plausible order-of-magnitude results
- provider-to-provider disagreement can still be material
- the number is a modelled third-party estimate, not first-party analytics

### Scale and reuse

For a normal 100–1000-candidate run:

- normalize/deduplicate domain-wide traffic work
- reuse a current monthly observation across multiple placements on the same domain when the metric itself is domain-wide
- query only the subset where the estimate helps the decision
- do not automatically bulk-query Crawlora for the entire run
- cache/reuse by provider + metric type + canonical domain + provider month when appropriate

No cached value may be relabelled as fresher than its provider period.

## Manual secondary evidence

### traffic.cv

Use as manual/browser secondary evidence for important or conflicting cases unless a stable public production API contract is later confirmed.

Do not scrape the browser product as a default automation path.

If the page shows a total-visits estimate, store it as:

`traffic_metric_type=total_monthly_visits_estimate`

### Ahrefs Traffic Checker

Ahrefs Organic Traffic is an estimate of organic-search traffic, not total all-channel monthly visits.

If manually used, store:

`traffic_metric_type=organic_search_traffic_estimate`

Do **not** put this value into visible `月访问量`.

## Optional future evidence — CrUX

CrUX is not required for the current MVP and should not be implemented merely because earlier architecture assumed very large batches.

If real usage later shows it provides useful incremental evidence, it may be added as an origin-scoped `popularity_rank` observation.

If implemented later, preserve these invariants:

- CrUX rank is popularity evidence only, never monthly visits
- scheme + host matter because CrUX is origin-scoped
- no row means `NOT_COVERED`, not zero
- query failure means failure/unknown, not zero
- a CrUX rank must never be written into visible `月访问量`

## Observation model

One placement/domain can have multiple traffic observations. Preserve them separately.

Each observation has its own provider status:

- `CONFIRMED`
- `CONFIRMED_ZERO`
- `NOT_COVERED`
- `LOOKUP_FAILED`
- `PROVIDER_ERROR`
- `UNKNOWN`

`CONFLICT` is **not** a provider observation status.

Cross-observation disagreement belongs to an aggregate review layer:

- `traffic_review_status=OK`
- `traffic_review_status=NEEDS_REVIEW`
- `traffic_review_status=CONFLICT`
- optional `traffic_conflict=true/false`
- `traffic_review_notes`

Example: two providers may both remain `CONFIRMED` while their numeric values conflict materially; the aggregate state becomes `CONFLICT`.

## Visible `月访问量`

`月访问量` means exactly:

> numeric `total_monthly_visits_estimate` for a clearly identified provider/month.

If no valid numeric total-monthly-visits estimate exists, use `未确认`.

Never put these into `月访问量`:

- organic-search traffic estimate
- CrUX/popularity rank
- global/category rank
- inferred traffic converted from rank
- provider failure/no-coverage placeholders
- Crawlora raw zero
- stale Crawlora `EstimatedMonthlyVisits` zero entries

If multiple current total-monthly-visits providers materially disagree, keep `月访问量=未确认` until reviewed or resolved by a documented precedence rule. Preserve all observations.

## Rating use

Traffic is evidence, not a score formula.

- strong traffic evidence can support higher priority or referral/brand value
- confirmed low traffic can be a negative signal only together with other weaker-quality evidence
- unknown traffic is neutral absence of evidence and does not lower a rating by itself
- traffic never independently produces `F`
- provider disagreement triggers review, not automatic rejection

## Regression invariants

Any future traffic adapter or persistence implementation must preserve:

1. Organic-search traffic is never stored as total monthly visits.
2. Popularity rank is never converted into visits.
3. Missing/no coverage/provider error is never converted into zero.
4. Crawlora raw zero is `UNKNOWN`, not `CONFIRMED_ZERO`.
5. Crawlora stale `EstimatedMonthlyVisits` zeros never replace current `Engagments.Visits`.
6. Traffic never independently causes `F`.
7. Provider observations keep their own statuses even when values conflict.
8. Aggregate conflict/review state remains separate from provider status.
9. Provider month, SnapshotDate when available, and checked-at time are preserved.
10. Unknown traffic never lowers A/B/C/D by itself.
11. `月访问量` only contains total-monthly-visits estimates.
12. Traffic lookup is selective for the current 100–1000-candidate personal-use workflow, not mandatory for every domain.
