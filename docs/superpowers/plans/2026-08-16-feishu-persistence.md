# Feishu Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe, authenticated Feishu Base schema initialization and deterministic upsert persistence to `BacklinkOS`, using the two existing empty tables and the production environment variables already configured in Vercel.

**Architecture:** Keep `BacklinkOS` framework-free. Add TypeScript Vercel Functions under `api/feishu/` and focused reusable modules under `lib/feishu/`. All Feishu HTTP calls go through one client; schema planning and record validation remain pure/testable; write endpoints require `X-BacklinkOS-Key` and never expose credentials.

**Tech Stack:** TypeScript, Node.js 24, Vercel Functions (`api/*.ts`), Node built-in test runner, Feishu OpenAPI REST, native `fetch`.

## Global Constraints

- Production Vercel project: `backlink-os`.
- Existing secrets/config: `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_BITABLE_APP_TOKEN`, `FEISHU_OPPORTUNITY_TABLE_ID`, `FEISHU_EVIDENCE_TABLE_ID`.
- One new secret before live writes: `BACKLINKOS_API_KEY`.
- Never commit or log any secret/token/Authorization value.
- Never delete Feishu fields or records.
- Setup defaults to dry-run; mutation requires `apply=true`.
- Existing correctly typed fields are preserved; missing fields are created; incompatible same-name fields produce a conflict.
- Single-select fields only gain missing required options; existing options are preserved.
- `外链库` primary field becomes `URL`; `证据` primary field becomes `placement_key`, but only when the table is empty and the current primary field is the default `文本`.
- `DR=0` is valid only when explicitly numeric; missing/invalid DR is never coerced to zero.
- Visible `月访问量=0` is rejected; Crawlora ambiguous raw zero belongs only in evidence payload.
- `评级=F` requires hard-rejection evidence.
- No `相关度`, CrUX runtime, discovery logic, or change to `backlink-metrics-api`.

---

## File map

- `package.json` — Node/TypeScript scripts and module mode.
- `tsconfig.json` — strict TypeScript config for API/lib/tests.
- `vercel.json` — framework `null` and function timeout for `api/**/*.ts`.
- `lib/feishu/config.ts` — environment parsing and API-key guard.
- `lib/feishu/types.ts` — shared Feishu/app domain types.
- `lib/feishu/client.ts` — token exchange and typed Feishu HTTP requests.
- `lib/feishu/schema.ts` — desired table schemas plus idempotent setup planner/applicator.
- `lib/feishu/validation.ts` — main/evidence request validation and screening invariants.
- `lib/feishu/persistence.ts` — exact-key search and create/update/conflict behavior.
- `api/feishu/setup.ts` — authenticated dry-run/apply schema endpoint.
- `api/feishu/persist.ts` — authenticated main/evidence persistence endpoint.
- `tests/feishu-config.test.ts` — configuration/auth tests.
- `tests/feishu-client.test.ts` — token/client normalization tests.
- `tests/feishu-schema.test.ts` — schema planner/apply idempotency tests.
- `tests/feishu-validation.test.ts` — screening invariant tests.
- `tests/feishu-persistence.test.ts` — create/update/conflict tests.
- `README.md` and `.agents/skills/screening-backlinks/references/persistence-schema.md` — runtime usage and implemented-state docs after live verification.

---

### Task 1: Runtime scaffolding, configuration, and endpoint authentication

**Files:**
- Create: `package.json`
- Create: `tsconfig.json`
- Create: `vercel.json`
- Create: `lib/feishu/config.ts`
- Create: `tests/feishu-config.test.ts`

**Interfaces:**
- Produces `loadFeishuConfig(env): FeishuConfig`.
- Produces `authorizeBacklinkOS(request, expectedKey): boolean`.

- [ ] **Step 1: Write failing config/auth tests**

```ts
import test from 'node:test';
import assert from 'node:assert/strict';
import { authorizeBacklinkOS, loadFeishuConfig } from '../lib/feishu/config.ts';

test('loadFeishuConfig requires all five Feishu variables', () => {
  assert.throws(() => loadFeishuConfig({ FEISHU_APP_ID: 'cli_x' } as NodeJS.ProcessEnv));
});

test('authorizeBacklinkOS accepts only exact X-BacklinkOS-Key', () => {
  const ok = new Request('https://example.test', { headers: { 'X-BacklinkOS-Key': 'secret' } });
  const bad = new Request('https://example.test', { headers: { 'X-BacklinkOS-Key': 'wrong' } });
  assert.equal(authorizeBacklinkOS(ok, 'secret'), true);
  assert.equal(authorizeBacklinkOS(bad, 'secret'), false);
});
```

- [ ] **Step 2: Run the test and verify RED**

Run: `npm test -- tests/feishu-config.test.ts`

Expected: fail because `lib/feishu/config.ts` does not exist.

- [ ] **Step 3: Implement minimal config/auth module**

```ts
export type FeishuConfig = {
  appId: string;
  appSecret: string;
  appToken: string;
  opportunityTableId: string;
  evidenceTableId: string;
};

function required(env: NodeJS.ProcessEnv, key: string): string {
  const value = env[key]?.trim();
  if (!value) throw new Error(`Missing required environment variable: ${key}`);
  return value;
}

export function loadFeishuConfig(env = process.env): FeishuConfig {
  return {
    appId: required(env, 'FEISHU_APP_ID'),
    appSecret: required(env, 'FEISHU_APP_SECRET'),
    appToken: required(env, 'FEISHU_BITABLE_APP_TOKEN'),
    opportunityTableId: required(env, 'FEISHU_OPPORTUNITY_TABLE_ID'),
    evidenceTableId: required(env, 'FEISHU_EVIDENCE_TABLE_ID'),
  };
}

export function authorizeBacklinkOS(request: Request, expectedKey: string): boolean {
  if (!expectedKey) return false;
  return request.headers.get('X-BacklinkOS-Key') === expectedKey;
}
```

- [ ] **Step 4: Add runtime files**

`package.json`:

```json
{
  "name": "backlink-os",
  "private": true,
  "type": "module",
  "scripts": {
    "test": "node --test --experimental-strip-types tests/*.test.ts",
    "typecheck": "tsc --noEmit",
    "build": "npm test && npm run typecheck"
  },
  "devDependencies": {
    "@types/node": "^24.0.0",
    "typescript": "^5.9.0"
  }
}
```

`vercel.json`:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "framework": null,
  "functions": {
    "api/**/*.ts": { "maxDuration": 30 }
  }
}
```

- [ ] **Step 5: Run focused and full build checks**

Run: `npm test -- tests/feishu-config.test.ts && npm run build`

Expected: config tests pass and TypeScript/build pass.

- [ ] **Step 6: Commit**

```bash
git add package.json tsconfig.json vercel.json lib/feishu/config.ts tests/feishu-config.test.ts
git commit -m "feat: scaffold Feishu persistence runtime"
```

---

### Task 2: Feishu client and safe error normalization

**Files:**
- Create: `lib/feishu/types.ts`
- Create: `lib/feishu/client.ts`
- Create: `tests/feishu-client.test.ts`

**Interfaces:**
- `createFeishuClient(config, fetchImpl?)` returns methods `listFields`, `createField`, `updateField`, `searchRecords`, `createRecord`, `updateRecord`.
- Feishu API failures throw `FeishuApiError` with safe `httpStatus`, `code`, `message` and no credentials.

- [ ] **Step 1: Write failing token/client tests**

```ts
test('client exchanges app credentials for tenant token and never exposes credentials', async () => {
  const calls: string[] = [];
  const fetchImpl = async (input: string | URL | Request) => {
    calls.push(String(input));
    return new Response(JSON.stringify({ code: 0, tenant_access_token: 'tenant-token', expire: 7200 }), { status: 200 });
  };
  const client = createFeishuClient(config, fetchImpl);
  const token = await client.getTenantAccessToken();
  assert.equal(token, 'tenant-token');
  assert.match(calls[0], /tenant_access_token\/internal/);
});

test('client normalizes Feishu envelope error without secret leakage', async () => {
  const fetchImpl = async () => new Response(JSON.stringify({ code: 1254001, msg: 'bad request' }), { status: 200 });
  const client = createFeishuClient(config, fetchImpl);
  await assert.rejects(client.listFields('tbl_x'), (error: unknown) => {
    return error instanceof FeishuApiError && error.code === 1254001 && !error.message.includes(config.appSecret);
  });
});
```

- [ ] **Step 2: Run and verify RED**

Run: `npm test -- tests/feishu-client.test.ts`

Expected: missing module/exports.

- [ ] **Step 3: Implement token exchange and generic request helper**

Use official endpoints:

```ts
const FEISHU_BASE = 'https://open.feishu.cn/open-apis';

async function getTenantAccessToken() {
  const response = await fetchImpl(`${FEISHU_BASE}/auth/v3/tenant_access_token/internal`, {
    method: 'POST',
    headers: { 'content-type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ app_id: config.appId, app_secret: config.appSecret }),
  });
  // require HTTP success, envelope code===0, non-empty tenant_access_token
}
```

Implement Base endpoints using `Authorization: Bearer <tenant_access_token>`:

```text
GET  /bitable/v1/apps/:app_token/tables/:table_id/fields
POST /bitable/v1/apps/:app_token/tables/:table_id/fields
PUT  /bitable/v1/apps/:app_token/tables/:table_id/fields/:field_id
POST /bitable/v1/apps/:app_token/tables/:table_id/records/search
POST /bitable/v1/apps/:app_token/tables/:table_id/records
PUT  /bitable/v1/apps/:app_token/tables/:table_id/records/:record_id
```

- [ ] **Step 4: Add response parsing tests for list/search/create/update**

Cover HTTP non-2xx, malformed JSON, envelope nonzero code, pagination-safe list/search result extraction, and no secret/token in thrown messages.

- [ ] **Step 5: Run client tests and full build**

Run: `npm test -- tests/feishu-client.test.ts && npm run build`

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add lib/feishu/types.ts lib/feishu/client.ts tests/feishu-client.test.ts
git commit -m "feat: add safe Feishu OpenAPI client"
```

---

### Task 3: Idempotent schema planner and setup applicator

**Files:**
- Create: `lib/feishu/schema.ts`
- Create: `tests/feishu-schema.test.ts`

**Interfaces:**
- `planTableSetup(kind, fields, recordCount)` returns `{ actions, conflicts }` without mutation.
- `applyTableSetup(client, tableId, plan)` applies safe rename/create/update-option operations only.

- [ ] **Step 1: Write failing planner tests**

Required scenarios:

```ts
test('empty opportunity table renames default primary and creates only missing fields', () => { /* ... */ });
test('dry-run plan is idempotent when desired schema already exists', () => { /* actions=[] */ });
test('same-name incompatible field becomes conflict', () => { /* ... */ });
test('nonempty default primary rename is blocked', () => { /* ... */ });
test('single-select merge preserves existing options and adds only required missing options', () => { /* ... */ });
```

- [ ] **Step 2: Run and verify RED**

Run: `npm test -- tests/feishu-schema.test.ts`

Expected: missing module.

- [ ] **Step 3: Define exact desired schemas**

Use Feishu field type codes supported by Base:

```ts
const OPPORTUNITY_SCHEMA = [
  ['URL', 1],
  ['placement_key', 1],
  ['注册登录', 3],
  ['行业', 1],
  ['外链形式', 3],
  ['链接属性', 3],
  ['免费情况', 3],
  ['DR', 2],
  ['月访问量', 2],
  ['域龄', 1],
  ['评级', 3],
  ['状态', 3],
  ['已发布外链URL', 1]
] as const;
```

Evidence fields follow the approved design: text for identifiers/source/status/payload, number for numeric value, date field for `checked_at`, single select for `hard_rejection_scope`.

- [ ] **Step 4: Implement planner/applicator**

Rules:

```text
correct name + compatible type -> skip
missing -> create
single select missing required choices -> full-field update preserving existing property/options
wrong type -> conflict
extra field -> preserve
primary 文本 + empty table -> full-field update rename preserving property/ui values
primary 文本 + nonempty table -> conflict
```

- [ ] **Step 5: Run schema tests and full build**

Run: `npm test -- tests/feishu-schema.test.ts && npm run build`

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add lib/feishu/schema.ts tests/feishu-schema.test.ts
git commit -m "feat: add idempotent Feishu schema setup"
```

---

### Task 4: Persistence validation and deterministic upsert

**Files:**
- Create: `lib/feishu/validation.ts`
- Create: `lib/feishu/persistence.ts`
- Create: `tests/feishu-validation.test.ts`
- Create: `tests/feishu-persistence.test.ts`

**Interfaces:**
- `validatePersistRequest(input): ValidatedPersistRequest` throws `PersistenceValidationError`.
- `persistPlacement(client, config, request)` returns explicit main/evidence actions and Feishu record IDs.

- [ ] **Step 1: Write failing validation tests**

```ts
test('numeric DR zero is accepted', () => { /* DR: 0 */ });
test('missing or nonnumeric DR is never coerced to zero', () => { /* ... */ });
test('visible monthly visits zero is rejected', () => { /* 月访问量: 0 */ });
test('organic/popularity evidence cannot be promoted into visible 月访问量', () => { /* ... */ });
test('F without hard rejection evidence is rejected', () => { /* ... */ });
```

- [ ] **Step 2: Implement validation**

Require `main_record.placement_key`, `main_record.URL`, valid enum values where provided, and evidence records whose `placement_key` matches the main record. If `评级==='F'`, require a `HardRejection` evidence item with non-empty `hard_rejection_reason`.

- [ ] **Step 3: Write failing upsert tests**

```ts
test('no main key match creates one record', async () => { /* ... */ });
test('one main key match updates the existing record', async () => { /* ... */ });
test('multiple main key matches returns conflict and does not choose one', async () => { /* ... */ });
test('evidence upserts independently by evidence_key', async () => { /* ... */ });
test('one evidence failure makes overall success false while preserving other result details', async () => { /* ... */ });
```

- [ ] **Step 4: Implement exact-key search and upsert**

Search record filter must use exact field equality on `placement_key` or `evidence_key`. Return `created`, `updated`, `conflict`, or `failed`, and include `record_id` only when Feishu supplied one.

- [ ] **Step 5: Run validation/persistence tests and full build**

Run: `npm test -- tests/feishu-validation.test.ts tests/feishu-persistence.test.ts && npm run build`

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add lib/feishu/validation.ts lib/feishu/persistence.ts tests/feishu-validation.test.ts tests/feishu-persistence.test.ts
git commit -m "feat: add deterministic Feishu record upserts"
```

---

### Task 5: HTTP functions for setup and persistence

**Files:**
- Create: `api/feishu/setup.ts`
- Create: `api/feishu/persist.ts`
- Extend: `tests/feishu-config.test.ts` or create `tests/feishu-api.test.ts`

**Interfaces:**
- `POST /api/feishu/setup` body `{ "apply": boolean }`.
- `POST /api/feishu/persist` body `{ main_record, evidence_records }`.
- Both require `X-BacklinkOS-Key`.

- [ ] **Step 1: Write failing HTTP handler tests**

Cover method rejection, missing/wrong API key => 401, missing `BACKLINKOS_API_KEY` => safe 503, malformed JSON => 400, setup dry-run => no mutation, setup conflict => 409, persist validation => 400, success => 200.

- [ ] **Step 2: Implement Web Handler functions**

Use framework-free Vercel Functions:

```ts
export async function POST(request: Request): Promise<Response> {
  const expectedKey = process.env.BACKLINKOS_API_KEY?.trim() ?? '';
  if (!authorizeBacklinkOS(request, expectedKey)) {
    return Response.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }
  // parse body, load Feishu config, call setup/persistence service
}
```

No endpoint response may contain App ID, App Secret, tenant token, API key, or Authorization header.

- [ ] **Step 3: Run API tests and full build**

Run: `npm test -- tests/feishu-api.test.ts && npm run build`

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add api/feishu/setup.ts api/feishu/persist.ts tests/feishu-api.test.ts
git commit -m "feat: expose protected Feishu persistence APIs"
```

---

### Task 6: Documentation, production deploy, dry-run, schema apply, and live upsert verification

**Files:**
- Modify: `README.md`
- Modify after successful live verification only: `.agents/skills/screening-backlinks/SKILL.md`
- Modify after successful live verification only: `.agents/skills/screening-backlinks/references/persistence-schema.md`

**Interfaces:**
- User adds `BACKLINKOS_API_KEY` to Vercel Production.
- Production endpoints are used only after build/tests pass.

- [ ] **Step 1: Document runtime and final environment-variable list**

README must explain the two protected endpoints, dry-run-first rule, and that Feishu variables belong only in `backlink-os`.

- [ ] **Step 2: Run fresh full verification**

Run: `npm run build`

Expected: all executable tests pass and `tsc --noEmit` exits 0.

- [ ] **Step 3: Deploy development branch and inspect Vercel build logs**

Expected: framework-free project detects `/api/feishu/setup` and `/api/feishu/persist`; deployment READY.

- [ ] **Step 4: Stop and have user add `BACKLINKOS_API_KEY` to Production**

Do not ask the user to paste the value into chat. A long random value is sufficient.

- [ ] **Step 5: Promote/merge verified tree to `main` and wait for Production READY**

- [ ] **Step 6: Call schema dry-run**

```http
POST /api/feishu/setup
X-BacklinkOS-Key: <secret>
Content-Type: application/json

{"apply":false}
```

Expected: only the approved primary-field renames + missing field creates/options merges, no conflicts.

- [ ] **Step 7: Apply schema and verify by rereading fields**

Call with `{"apply":true}`. Expected: actions succeed and a second dry-run returns zero actions/conflicts.

- [ ] **Step 8: Live create/read/update test**

Persist one clearly marked test placement such as `backlinkos-test.invalid` with non-F rating and one evidence row. Verify returned record IDs, query it back, then submit the same logical key with a changed `notes`/status and verify `updated` rather than duplicate create.

- [ ] **Step 9: Update Skill/persistence docs only after live success**

Change wording from “not implemented/pending” to “implemented and production-verified”; retain the rule that persistence success is claimed only when a write call confirms it.

- [ ] **Step 10: Final verification and commit**

Run: `npm run build`, inspect production deployment status, fresh dry-run setup, fresh read of the test placement/evidence. Commit docs with:

```bash
git commit -m "docs: mark Feishu persistence production-verified"
```
