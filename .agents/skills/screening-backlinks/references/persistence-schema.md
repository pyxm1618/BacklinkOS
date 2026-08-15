# Persistence Schema and Feishu Contract

## Visible backlink table

Keep the operational table compact. Visible columns:

| Field | Allowed / expected values |
|---|---|
| URL | Candidate/publishing URL |
| 注册登录 | 无需注册 / 需要注册登录 / 需要审核 / 未确认 |
| 行业 | Broad platform/site category |
| 外链形式 | Profile / Blog/Post / Comment / Classified / Directory / Community/Forum / other concise type |
| 链接属性 | Dofollow / Nofollow / 未确认 |
| 免费情况 | 免费 / 部分免费 / 付费 / 未确认 |
| DR | Numeric Ahrefs DR or 未确认 |
| 月访问量 | Numeric `total_monthly_visits_estimate` for an identified provider month, otherwise 未确认 |
| 域龄 | Derived from authoritative registration date or 未确认 |
| 评级 | A / B / C / D / F |
| 状态 | 未做 / 已验证 / 已注册 / 已发布 / 淘汰 |
| 已发布外链URL | Final live backlink URL; blank before publication |

Do not add `相关度`.

### Meaning of `月访问量`

`月访问量` means exactly:

> a numeric estimate of **total monthly visits across channels** for a clearly identified month/provider.

The name is intentionally explicit so it is not confused with SEO/organic traffic.

Do not put these into `月访问量`:

- Google CrUX popularity rank/bucket
- Ahrefs/DataForSEO organic-search traffic estimates
- global/category rank
- inferred traffic converted from a rank
- placeholders for no coverage/provider errors
- Crawlora raw zero
- stale Crawlora `EstimatedMonthlyVisits` zero entries

If no valid total-monthly-visits estimate exists, use `未确认`.

If multiple current total-visits providers materially conflict, keep the visible value `未确认` until reviewed unless a documented provider-precedence rule exists.

Organic-search traffic remains evidence and may be important for SEO-quality review, but it is not represented by the `月访问量` column.

## Evidence storage

Keep supporting evidence outside the compact visible table. A second Feishu table, evidence sheet, or structured evidence object should contain as many of these as applicable:

- `canonical_domain`
- `original_candidate_url`
- `discovered_from`
- `placement_type`
- `publish_entry_url`
- `sample_published_url`
- `raw_rel`
- `registration_requirement_evidence`
- `pricing_evidence`
- `dr`
- `dr_source` = Ahrefs
- `dr_checked_at`
- `registered_at`
- `domain_age_source`
- `industry_evidence`
- `hard_rejection_scope` = domain / placement / blank
- `hard_rejection_reason`
- `verified_at`
- `notes`

### Traffic observations

Traffic must support **multiple observations per placement** so metrics/providers never overwrite each other.

Recommended fields for each traffic observation:

- `traffic_metric_type`
  - `popularity_rank`
  - `total_monthly_visits_estimate`
  - `organic_search_traffic_estimate`
  - `unknown`
- `traffic_value` = normalized numeric value or null
- `traffic_raw_value` = optional raw provider numeric value when normalization deliberately withholds it, for example Crawlora's ambiguous raw zero
- `traffic_source`
- `traffic_status` — status of **this observation/provider call only**:
  - `CONFIRMED`
  - `CONFIRMED_ZERO`
  - `NOT_COVERED`
  - `LOOKUP_FAILED`
  - `PROVIDER_ERROR`
  - `UNKNOWN`
- `traffic_period` = provider month/release, preferably `YYYY-MM`
- `provider_snapshot_date` = provider snapshot timestamp when supplied
- `traffic_checked_at`
- `traffic_confidence` = `high` / `medium` / `low` / `none`
- `traffic_origin` = exact origin when the metric is origin-scoped
- `popularity_rank` = numeric CrUX bucket boundary or null
- `popularity_bucket` = `Top 1K`, `Top 5K`, `Top 10K`, etc. or null
- `coverage_status` = `FOUND` / `NOT_COVERED` / `UNKNOWN` when applicable
- `raw_field_used` when an adapter selected a concrete upstream field
- `traffic_notes`

### Aggregate traffic review state

Cross-observation disagreement is **not** a provider status. Keep an aggregate object/state separately, for example:

- `traffic_review_status`
  - `OK`
  - `NEEDS_REVIEW`
  - `CONFLICT`
- `traffic_conflict` = boolean
- `traffic_review_notes`

Example: Crawlora may be `CONFIRMED=52300` and a second provider may be `CONFIRMED=8000`; neither observation becomes `CONFLICT`. The aggregate review state becomes `CONFLICT`.

Do not force all fields into one Feishu cell. The persistence adapter may store traffic observations as separate evidence rows linked by placement key, with aggregate review state on the main/evidence summary record.

### Traffic examples

CrUX evidence:

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
  "traffic_notes": "Popularity evidence only; not monthly visits."
}
```

CrUX no coverage:

```json
{
  "traffic_metric_type": "popularity_rank",
  "traffic_value": null,
  "traffic_source": "Google CrUX BigQuery",
  "traffic_status": "NOT_COVERED",
  "traffic_period": "2026-06",
  "traffic_checked_at": "2026-08-15T00:00:00Z",
  "traffic_confidence": "none",
  "traffic_origin": "https://example.com",
  "popularity_rank": null,
  "popularity_bucket": null,
  "coverage_status": "NOT_COVERED"
}
```

Crawlora positive total visits:

```json
{
  "traffic_metric_type": "total_monthly_visits_estimate",
  "traffic_value": 52300,
  "traffic_raw_value": 52300,
  "traffic_source": "Crawlora / SimilarWeb public surface",
  "traffic_status": "CONFIRMED",
  "traffic_period": "2026-07",
  "provider_snapshot_date": "2026-07-01T00:00:00.000Z",
  "traffic_checked_at": "2026-08-15T00:00:00Z",
  "traffic_confidence": "medium",
  "raw_field_used": "data.Engagments.Visits"
}
```

Crawlora raw-zero evidence:

```json
{
  "traffic_metric_type": "total_monthly_visits_estimate",
  "traffic_value": null,
  "traffic_raw_value": 0,
  "traffic_source": "Crawlora / SimilarWeb public surface",
  "traffic_status": "UNKNOWN",
  "traffic_period": "2026-07",
  "traffic_notes": "Raw zero is ambiguous; live validation proved a nonexistent domain can return HTTP 200/OK with Visits=0."
}
```

Do not write `月访问量=0` from this observation.

Organic traffic is separate:

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

Conflict summary:

```json
{
  "traffic_review_status": "CONFLICT",
  "traffic_conflict": true,
  "traffic_review_notes": "Two confirmed total-monthly-visits estimates differ materially; preserve both and review source period/coverage."
}
```

## Placement key and deduplication

Preferred logical key:

`canonical_domain + placement_type + publish_entry_url`

Do not deduplicate by domain alone because one domain may expose multiple placements with different link attributes and rules.

A domain-wide F record can be checked before placement research only when `hard_rejection_scope=domain`.

Traffic caching is separate from placement identity:

- CrUX cache key: exact origin + CrUX release month
- numeric domain-traffic cache key: provider + metric type + canonical domain + provider month

One cached traffic observation may be reused across multiple placements on the same domain when the provider metric itself is domain-wide.

## F rows

The visible operational row can remain minimal:

- `URL`
- `评级 = F`
- `状态 = 淘汰`

Other visible fields may remain blank/`未确认` once the hard rejection is proven.

The evidence store must still preserve the rejection scope, reason, evidence, and verification date so future runs know why the candidate was skipped.

## Feishu/Lark write contract

Target system: Feishu/Lark Base.

The integration is **not yet implemented in this repository**. Until it exists:

1. produce a main-record object matching the visible schema
2. produce separate evidence record(s), including separate traffic observations where applicable
3. mark persistence as `pending`
4. never claim the record was written to Feishu

When a Feishu adapter is added, it should expose deterministic operations equivalent to:

- `lookupPlacement(key)`
- `upsertMainRecord(key, record)`
- `appendOrUpdateEvidence(key, evidence)`

The adapter must return explicit success/failure and record identifiers. The screening skill should rely on those results rather than inferring success from request completion.

## Validation invariants for future persistence code

The persistence layer should reject or preserve uncertainty rather than coercing it.

Examples:

- `traffic_status=UNKNOWN` with normalized `traffic_value=0` -> reject; raw zero may be preserved separately as `traffic_raw_value=0`
- Crawlora raw zero written as visible `月访问量=0` -> reject
- Crawlora `EstimatedMonthlyVisits` stale zero written as current `月访问量` -> reject
- `traffic_metric_type=popularity_rank` written into visible `月访问量` -> reject
- `traffic_metric_type=organic_search_traffic_estimate` written into visible `月访问量` -> reject
- `CONFIRMED_ZERO` without provider-specific documented/live-validated zero semantics -> reject
- provider disagreement must set aggregate review state; do not rewrite either observation's `traffic_status` to `CONFLICT`
- `评级=F` without a verified hard-rejection reason -> reject
- `Dofollow/Nofollow` without same-type final-link evidence -> preserve as `未确认` rather than inventing evidence

## Example non-F record

```json
{
  "URL": "https://example.com/profile/edit",
  "注册登录": "需要注册登录",
  "行业": "社区",
  "外链形式": "Profile",
  "链接属性": "Dofollow",
  "免费情况": "免费",
  "DR": 63,
  "月访问量": 52300,
  "域龄": "11.2年",
  "评级": "A",
  "状态": "已验证",
  "已发布外链URL": ""
}
```

Supporting traffic evidence:

```json
{
  "traffic_metric_type": "total_monthly_visits_estimate",
  "traffic_value": 52300,
  "traffic_source": "Crawlora / SimilarWeb public surface",
  "traffic_status": "CONFIRMED",
  "traffic_period": "2026-07",
  "provider_snapshot_date": "2026-07-01T00:00:00.000Z",
  "traffic_confidence": "medium"
}
```

## Example F record

Main record:

```json
{
  "URL": "https://dead-example.com/",
  "评级": "F",
  "状态": "淘汰"
}
```

Evidence:

```json
{
  "canonical_domain": "dead-example.com",
  "hard_rejection_scope": "domain",
  "hard_rejection_reason": "Domain/site no longer resolves and no current publishing surface exists",
  "verified_at": "<ISO timestamp>"
}
```
