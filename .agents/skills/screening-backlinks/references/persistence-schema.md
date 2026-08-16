# Persistence Schema and Feishu Contract

## Status

Feishu/Lark Base persistence is implemented in `BacklinkOS` and was production-validated on 2026-08-16.

Production endpoints:

```text
POST /api/feishu/setup
POST /api/feishu/persist
```

Both require:

```text
X-BacklinkOS-Key: <BACKLINKOS_API_KEY>
```

Credentials and table IDs live only in the Vercel project `backlink-os` environment variables. They must never be committed to GitHub or returned in API responses.

---

## Main table: 外链库

Required fields:

| Field | Type / meaning |
|---|---|
| `URL` | Primary text; candidate/publishing URL |
| `placement_key` | Internal deterministic identity |
| `注册登录` | 无需注册 / 需要注册登录 / 需要审核 / 未确认 |
| `行业` | Broad objective platform/site category |
| `外链形式` | Profile / Blog/Post / Comment / Classified / Directory / Community/Forum / Other |
| `链接属性` | Dofollow / Nofollow / 未确认 |
| `免费情况` | 免费 / 部分免费 / 付费 / 未确认 |
| `DR` | Numeric Ahrefs DR; blank when unknown |
| `月访问量` | Positive confirmed total-monthly-visits estimate; blank when unknown |
| `域龄` | Display value derived from authoritative registration date or 未确认 |
| `评级` | A / B / C / D / F |
| `状态` | 未做 / 已验证 / 已注册 / 已发布 / 淘汰 |
| `已发布外链URL` | Final published backlink URL; blank before publication |

Do not add `相关度`.

### Placement identity

Use:

```text
canonical_domain + placement_type + publish_entry_url
```

Store the deterministic result in `placement_key`.

Do not deduplicate by domain alone. One domain may expose multiple independently verifiable placements.

---

## Evidence table: 证据

Each independent observation is a separate row. Required fields:

| Field | Purpose |
|---|---|
| `placement_key` | Primary text linking the evidence to one placement |
| `evidence_key` | Deterministic identity for this evidence observation |
| `evidence_type` | DR / Traffic / DomainAge / Publishability / Registration / Pricing / LinkAttribute / HardRejection / other concise type |
| `canonical_domain` | Normalized domain |
| `source` | Provider or evidence source |
| `status` | Provider/evidence status |
| `value_number` | Numeric value when applicable |
| `value_text` | Text value when applicable |
| `period` | Provider period such as YYYY-MM |
| `checked_at` | Verification/provider timestamp |
| `evidence_url` | Source/sample URL when applicable |
| `hard_rejection_scope` | domain / placement; blank otherwise |
| `hard_rejection_reason` | Verified reason when rating F |
| `notes` | Concise human-readable notes |
| `payload_json` | Structured details that do not need dedicated common columns |

Do not create dozens of provider-specific columns. Preserve provider-specific details such as raw traffic value, snapshot date, raw `rel`, confidence, review state, or selected upstream field in `payload_json` when they are not common columns.

### Evidence identity

Examples:

```text
<placement_key>|dr|ahrefs
<placement_key>|traffic|crawlora|2026-07
<placement_key>|link_attribute|<sample-url-hash>
<placement_key>|hard_rejection|domain
```

Repeated persistence of the same `evidence_key` updates the existing evidence row rather than creating a duplicate.

---

## Meaning of 月访问量

`月访问量` means exactly:

> a positive numeric estimate of total monthly visits across channels for a clearly identified provider month.

Do **not** put these into `月访问量`:

- CrUX popularity rank/bucket
- Ahrefs/DataForSEO organic-search traffic estimates
- global/category rank
- inferred traffic converted from rank
- placeholders for no coverage/provider errors
- Crawlora raw zero
- stale Crawlora `EstimatedMonthlyVisits` zero entries

If no valid total-monthly-visits estimate exists, leave the numeric Feishu field blank and represent the uncertainty in evidence.

Crawlora raw `Visits=0` must remain evidence with normalized traffic value null/unknown. It must never become visible `月访问量=0`.

Organic-search traffic remains a separate evidence observation and never overwrites total monthly visits.

---

## Traffic evidence semantics

Keep each provider observation separate. Useful payload fields include:

```text
traffic_metric_type
traffic_value
traffic_raw_value
traffic_source
traffic_status
traffic_period
provider_snapshot_date
traffic_checked_at
traffic_confidence
traffic_origin
popularity_rank
popularity_bucket
coverage_status
raw_field_used
traffic_notes
traffic_review_status
traffic_conflict
traffic_review_notes
```

Provider-call status values may include:

```text
CONFIRMED
CONFIRMED_ZERO
NOT_COVERED
LOOKUP_FAILED
PROVIDER_ERROR
UNKNOWN
```

`CONFIRMED_ZERO` is allowed only for a future provider whose zero semantics are independently validated. Current Crawlora raw zero does not qualify.

Cross-provider disagreement belongs in aggregate review metadata such as `traffic_review_status=CONFLICT`; it does not rewrite an individual observation's provider status.

---

## Feishu setup behavior

`POST /api/feishu/setup` is safe and repeatable:

- dry-run first with `{ "apply": false }`
- `{ "apply": true }` performs safe missing-field work
- never deletes records or fields
- an already-correct field is skipped
- a missing field is created
- a same-name incompatible field produces an explicit conflict
- existing user-created fields are preserved
- single-select setup preserves existing options and only adds required missing options
- the default primary field `文本` may be renamed only when existing rows contain no meaningful cell values
- Feishu's default blank rows do not count as real user data
- if any row contains real data, an unsafe primary-field rename is blocked

After setup, re-run dry-run. A completed schema returns no remaining actions and no conflicts.

---

## Upsert behavior

### Main table

1. search by exact `placement_key`
2. zero matches -> create
3. one match -> update that record
4. multiple matches -> return conflict and do not choose arbitrarily

### Evidence table

For each evidence item:

1. search by exact `evidence_key`
2. zero matches -> create
3. one match -> update that record
4. multiple matches -> explicit conflict

A response is successful only when the requested main/evidence writes actually return successful actions. Record IDs are part of the confirmation.

Production live validation confirmed that writing the same logical test placement twice produced `created` on the first call and `updated` on the second call with the same main and evidence record IDs.

---

## Validation invariants

The persistence layer rejects malformed certainty rather than coercing it.

Required rules:

- numeric Ahrefs `DR=0` is valid
- missing/invalid/failed DR never becomes 0
- visible `月访问量=0` is rejected
- visible `月访问量` requires matching `CONFIRMED` `total_monthly_visits_estimate` evidence with the same positive value
- organic-search traffic cannot populate `月访问量`
- popularity rank cannot populate `月访问量`
- Crawlora raw zero may be preserved in evidence but cannot populate `月访问量`
- `评级=F` requires confirmed hard-rejection evidence and a non-empty reason
- evidence `placement_key` must match the main record
- unsupported single-select values are rejected before a Feishu write
- no `相关度` field or rating input is accepted

The persistence adapter stores the Skill's judgment. It does not independently calculate A/B/C/D/F.

---

## F rows

A visible F row may remain minimal once hard rejection is proven:

```text
URL
评级 = F
状态 = 淘汰
```

The evidence table must preserve at least the rejection scope, reason, source/evidence, and verification context.

F is not appropriate merely because DR is low, traffic is low/unknown, the link is Nofollow, registration is required, the placement is paid, or a tool could not access the page.

---

## Fallback when Feishu is temporarily unavailable

If the active runtime cannot reach the production Feishu adapter:

1. continue evidence collection
2. output an import-ready main record
3. output separate evidence records
4. mark persistence as pending
5. never claim the record was written

This is an operational fallback, not an implementation gap.
