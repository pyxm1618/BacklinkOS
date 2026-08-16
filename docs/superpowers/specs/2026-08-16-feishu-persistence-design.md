# Feishu Persistence Design

## Goal

Complete the current `screening-backlinks` workflow by adding deterministic Feishu/Lark Base persistence to `BacklinkOS`.

The user's Base already exists and contains two empty tables:

- `外链库` — main operational opportunity table
- `证据` — supporting evidence table

The corresponding production environment variables already exist in the Vercel project `backlink-os`:

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_BITABLE_APP_TOKEN`
- `FEISHU_OPPORTUNITY_TABLE_ID`
- `FEISHU_EVIDENCE_TABLE_ID`

One additional secret will be required before production writes are enabled:

- `BACKLINKOS_API_KEY`

This implementation does not change screening/rating semantics, discover backlinks, add CrUX, or modify `backlink-metrics-api`.

---

## 1. Runtime architecture

Keep `BacklinkOS` lightweight. Do not turn it into a full web application merely to support persistence.

Add small TypeScript Vercel Functions under the repository root `api/` directory plus reusable code under `lib/`.

Vercel supports TypeScript/JavaScript functions placed in `/api` without requiring a frontend framework. This matches the existing `backlink-os` project, whose framework is currently unset.

Target structure:

```text
BacklinkOS/
├── api/
│   └── feishu/
│       ├── setup.ts
│       └── persist.ts
├── lib/
│   └── feishu/
│       ├── client.ts
│       ├── config.ts
│       ├── schema.ts
│       ├── validation.ts
│       └── persistence.ts
├── tests/
│   └── feishu-*.test.ts
├── package.json
├── tsconfig.json
└── ... existing Skills/docs
```

No UI is required for this phase.

---

## 2. Authentication and secret handling

### Feishu authentication

The server exchanges `FEISHU_APP_ID + FEISHU_APP_SECRET` for a self-built-app `tenant_access_token` through Feishu's official token endpoint.

The temporary token is used only server-side and is never returned to the caller.

### BacklinkOS endpoint authentication

Both write-capable endpoints require:

```http
X-BacklinkOS-Key: <BACKLINKOS_API_KEY>
```

Rules:

- missing/wrong key -> HTTP 401
- compare the supplied key without logging its value
- never return App Secret, tenant token, or environment variable values
- do not put any secret in GitHub

The user will add `BACKLINKOS_API_KEY` to the `backlink-os` Vercel Production environment before live schema creation or record writes.

---

## 3. Feishu schema setup

Endpoint:

```http
POST /api/feishu/setup
```

Request:

```json
{
  "apply": false
}
```

Default behavior is inspection/dry-run. `apply=true` is required to modify the Base.

### Safety sequence

For each configured table:

1. authenticate with Feishu
2. list current fields
3. query whether real records already exist
4. compute required changes
5. return conflicts instead of guessing
6. only when `apply=true`, apply safe changes
7. list fields again and verify final schema

The setup endpoint must never delete a field or record.

### Existing primary field

Both current tables contain the default primary text field named `文本`.

For an empty table only:

- `外链库`: rename the existing primary text field from `文本` to `URL`
- `证据`: rename the existing primary text field from `文本` to `placement_key`

When renaming, preserve the field's current type/UI/property values because Feishu's update-field API performs a full update rather than a partial patch.

If the table contains real records and the primary field is still the default `文本`, stop with a schema conflict rather than silently changing it.

### Idempotency

Setup is repeatable:

- required field already exists with the expected type -> skip
- required field missing -> create it
- required field exists with a materially incompatible type -> stop and report the conflict
- for required single-select fields, preserve every existing option and add only required option names that are missing; never delete or rename user-added options
- extra user-created fields -> preserve them
- never create duplicate fields

---

## 4. `外链库` table schema

The main table remains compact and human-readable.

Required fields:

| Field | Feishu type | Notes |
|---|---|---|
| `URL` | Text, primary | candidate/publishing URL |
| `placement_key` | Text | internal deterministic upsert key |
| `注册登录` | Single select | 无需注册 / 需要注册登录 / 需要审核 / 未确认 |
| `行业` | Text | objective platform/site category |
| `外链形式` | Single select | Profile / Blog/Post / Comment / Classified / Directory / Community/Forum / Other |
| `链接属性` | Single select | Dofollow / Nofollow / 未确认 |
| `免费情况` | Single select | 免费 / 部分免费 / 付费 / 未确认 |
| `DR` | Number | blank when unknown; real numeric zero is allowed |
| `月访问量` | Number | only confirmed total-monthly-visits estimate; blank when unknown |
| `域龄` | Text | display value such as `11.2年` or `未确认` |
| `评级` | Single select | A / B / C / D / F |
| `状态` | Single select | 未做 / 已验证 / 已注册 / 已发布 / 淘汰 |
| `已发布外链URL` | Text | blank until publication |

`placement_key` is intentionally an internal helper field. It is required so repeated writes update the same logical placement instead of producing duplicates.

Logical key remains:

```text
canonical_domain + placement_type + publish_entry_url
```

The persistence layer receives or derives this key; it does not use topical relevance.

---

## 5. `证据` table schema

The evidence table stores multiple rows per placement. The primary column remains `placement_key`, as approved, and an additional `evidence_key` provides deterministic per-evidence upsert identity.

Required fields:

| Field | Feishu type | Purpose |
|---|---|---|
| `placement_key` | Text, primary | links evidence to one placement |
| `evidence_key` | Text | unique deterministic evidence identity |
| `evidence_type` | Text | e.g. DR / Traffic / DomainAge / Publishability / Registration / Pricing / LinkAttribute / HardRejection |
| `canonical_domain` | Text | normalized domain |
| `source` | Text | provider or evidence source |
| `status` | Text | provider/evidence status |
| `value_number` | Number | numeric evidence when applicable |
| `value_text` | Text | text evidence when applicable |
| `period` | Text | provider period such as YYYY-MM |
| `checked_at` | Date | verification/provider check time |
| `evidence_url` | Text | source/sample URL when applicable |
| `hard_rejection_scope` | Single select | domain / placement; blank otherwise |
| `hard_rejection_reason` | Text | required evidence for F when applicable |
| `notes` | Text | concise human-readable notes |
| `payload_json` | Text | structured provider-specific details not promoted to common columns |

The design deliberately does **not** create dozens of provider-specific columns. Instead, each independent observation gets its own evidence row. Important common fields remain filterable, while details such as `traffic_raw_value`, `provider_snapshot_date`, `raw_rel`, `raw_field_used`, or aggregate review metadata can be preserved in `payload_json` for that evidence row.

This is not one giant evidence cell: multiple provider/verification observations remain separate rows.

### Evidence key examples

```text
<placement_key>|dr|ahrefs
<placement_key>|traffic|crawlora|2026-07
<placement_key>|link_attribute|<sample-url-hash>
<placement_key>|hard_rejection|domain
```

The exact deterministic key builder is implementation-owned and tested.

---

## 6. Persistence API

Endpoint:

```http
POST /api/feishu/persist
```

Protected by `X-BacklinkOS-Key`.

Input concept:

```json
{
  "main_record": {
    "placement_key": "...",
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
  },
  "evidence_records": [
    {
      "evidence_key": "...|dr|ahrefs",
      "placement_key": "...",
      "evidence_type": "DR",
      "canonical_domain": "example.com",
      "source": "Ahrefs",
      "status": "CONFIRMED",
      "value_number": 63,
      "checked_at": "2026-08-16T01:00:00Z"
    }
  ]
}
```

### Upsert behavior

Main table:

1. search by exact `placement_key`
2. no match -> create
3. one match -> update
4. multiple matches -> fail with explicit duplicate-conflict response; never choose one arbitrarily

Evidence table:

1. search each `evidence_key`
2. no match -> create
3. one match -> update
4. multiple matches -> report conflict for that evidence item

A partial failure must be explicit. The API must not return `success=true` if the main record or requested evidence records were not actually persisted.

The response includes action (`created` / `updated` / `conflict` / `failed`) and Feishu record IDs, but never credentials.

---

## 7. Validation before writes

Persistence validates the existing `screening-backlinks` invariants rather than blindly accepting any JSON.

Required guards include:

- missing required placement identity -> reject
- `DR` nonnumeric -> keep blank/unknown or reject malformed input; never coerce to 0
- genuine numeric DR `0` is allowed
- `月访问量=0` must not be accepted as a substitute for Crawlora `UNKNOWN` raw zero
- traffic evidence with `status=UNKNOWN` may preserve raw `0` only inside its evidence payload/raw evidence, not as visible `月访问量=0`
- organic-search traffic must not be written into `月访问量`
- popularity rank must not be written into `月访问量`
- `评级=F` requires a matching verified hard-rejection evidence record/reason in the same request or an already-persisted hard-rejection evidence record
- no `相关度` field is created or accepted as a rating input

The adapter persists judgments already made by the Skill; it does not independently rate opportunities.

---

## 8. Feishu client behavior

Use official Feishu OpenAPI surfaces:

- self-built-app tenant token exchange
- list/create/update fields
- search records
- create/update records
- batch create/update may be used later when it materially simplifies 100–1000-item persistence, but the first implementation should prioritize deterministic per-record upsert correctness over throughput

Provider/API errors are normalized into safe application errors containing HTTP status / Feishu code / message where useful, with credentials removed.

No request or error log may print App Secret, tenant token, `BACKLINKOS_API_KEY`, or full Authorization headers.

---

## 9. Tests

All Feishu tests mock upstream HTTP; automated builds must not mutate the real Base.

Executable tests must cover at least:

1. environment/config validation
2. BacklinkOS API-key protection
3. tenant token success/failure and no secret leakage
4. field listing/normalization
5. empty default table -> planned primary-field rename
6. setup dry-run performs no mutations
7. setup apply creates only missing fields
8. repeated setup makes no duplicate changes
9. wrong-type same-name field -> explicit conflict
10. single-select setup preserves existing options and adds only required missing options
11. nonempty unsafe default-primary rename -> blocked
12. main-record create
13. main-record update
14. duplicate main-key conflict
15. evidence create/update by `evidence_key`
16. partial evidence failure is reported
17. numeric DR zero remains valid
18. missing/invalid DR never becomes zero
19. Crawlora raw zero cannot become visible `月访问量=0`
20. organic traffic/popularity cannot populate `月访问量`
21. F without hard-rejection evidence is rejected
22. secrets/tokens are absent from API responses

Build/TypeScript checks run before deployment.

---

## 10. Production rollout

The rollout is deliberately staged.

### Stage A — code deploy

Deploy the implementation to `backlink-os` with the five existing Feishu environment variables. Until `BACKLINKOS_API_KEY` exists, protected write endpoints must refuse access.

### Stage B — user adds one final secret

The user adds `BACKLINKOS_API_KEY` to the `backlink-os` Vercel **Production** environment only.

### Stage C — schema dry-run

Call:

```json
POST /api/feishu/setup
{"apply": false}
```

Verify the planned changes match the two intended empty tables.

### Stage D — schema apply

Call with `apply=true`, then re-read the fields and verify both final schemas.

### Stage E — live persistence test

Use one clearly marked temporary test placement:

1. create one main row and supporting evidence row
2. verify Feishu returned record IDs
3. read/search back the persisted records
4. write the same logical placement again with one changed non-destructive field
5. verify the existing row was updated rather than duplicated
6. remove the temporary test records only if a safe cleanup endpoint/tool is deliberately implemented; otherwise leave them clearly marked and let the user delete them manually

Do not test by overwriting arbitrary user data.

---

## 11. Completion definition

Feishu persistence is complete only when all of the following are true:

- `BacklinkOS` deploys successfully as the `backlink-os` Vercel project
- the setup endpoint is authenticated and idempotent
- both empty Feishu tables are initialized to the expected schema without deleting data/fields
- main records can be created and updated by logical placement identity
- multiple evidence rows can be created/updated deterministically
- unknown/missing values never become false zeros
- F cannot be persisted without hard-rejection evidence
- production live create + read-back + update verification succeeds
- no secret appears in GitHub, build logs, runtime responses, or test fixtures
- `screening-backlinks` documentation is updated to say Feishu persistence is implemented only after the live verification above succeeds

At that point the current `screening-backlinks` workflow is closed at the persistence layer. `discovering-backlinks` remains a separate future Skill and is not part of this implementation.
