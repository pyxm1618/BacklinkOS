# Realistic Batch Screening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the current screening runtime for typical 100–1000-candidate personal-use batches, while leaving only Feishu/Lark persistence unfinished.

**Architecture:** Keep `BacklinkOS` as the product/Skill repository and `backlink-metrics-api` as deterministic runtime. The screening workflow normalizes and deduplicates domains, sends them to a rate-safe DR batch API in chunks of at most 20 unique domains, and uses Crawlora only selectively. No CrUX, large-scale queue, Discovery, or Feishu implementation is added.

**Tech Stack:** Next.js 16 App Router, TypeScript, Node built-in test runner, Vercel Functions, Ahrefs public Domain Rating API, existing Crawlora adapter.

## Global Constraints

- Typical operating batch: roughly 100–1000 candidate URLs.
- Do not design for 100K-scale ingestion, distributed workers, or large-scale queues.
- Ahrefs public Domain Rating endpoint is the only DR source.
- Ahrefs public API is rate-limited to 60 requests/minute by default; use conservative pacing below that ceiling.
- One HTTP `POST /api/dr/batch` call accepts at most 20 unique normalized domains so execution stays comfortably bounded on Vercel; a 100–1000-candidate screening run is chunked across repeated calls.
- Preserve numeric DR `0` when Ahrefs explicitly returns it.
- Missing, invalid, failed, or throttled DR must never become `0`.
- Crawlora remains a selective medium-confidence total-monthly-visits follow-up; do not query it for every domain.
- Do not implement CrUX runtime.
- Do not implement `discovering-backlinks`.
- Do not implement Feishu/Lark persistence in this plan.
- Do not change A/B/C/D/F rating semantics.
- Do not add topical relevance.
- Existing `/api/dr` and `/api/traffic` contracts must remain working.

---

## File Structure

### `backlink-metrics-api`

Create:

```text
lib/domain.ts
lib/ahrefs-dr.ts
app/api/dr/batch/route.ts
tests/domain.test.ts
tests/ahrefs-dr.test.ts
```

Modify:

```text
app/api/dr/route.ts
lib/crawlora-traffic.ts
README.md
```

Responsibilities:

- `lib/domain.ts` — one domain-scoped normalizer shared by Ahrefs DR and Crawlora.
- `lib/ahrefs-dr.ts` — Ahrefs request parsing, error classification, bounded retry, pacing, deduplication, and batch execution.
- `app/api/dr/route.ts` — thin single-domain HTTP adapter over `lib/ahrefs-dr.ts`.
- `app/api/dr/batch/route.ts` — thin batch HTTP adapter capped at 20 unique domains per call.
- `tests/domain.test.ts` — shared normalization invariants.
- `tests/ahrefs-dr.test.ts` — single/batch Ahrefs behavior and retry invariants.

### `BacklinkOS`

Modify:

```text
README.md
docs/REPOSITORY_ARCHITECTURE.md
.agents/skills/screening-backlinks/SKILL.md
.agents/skills/screening-backlinks/references/traffic-evidence.md
```

No new runtime is added to `BacklinkOS`.

---

### Task 1: Shared Domain Normalization

**Files:**
- Create: `backlink-metrics-api/lib/domain.ts`
- Create: `backlink-metrics-api/tests/domain.test.ts`
- Modify: `backlink-metrics-api/lib/crawlora-traffic.ts`

**Interfaces:**
- Produces: `normalizeDomain(rawInput: string): string`
- Consumers: Crawlora runtime, single DR runtime, batch DR runtime.

- [ ] **Step 1: Write failing normalization tests**

Tests must assert:

```ts
normalizeDomain('github.com') === 'github.com'
normalizeDomain('www.github.com') === 'github.com'
normalizeDomain('https://WWW.GITHUB.COM/openai?x=1#y') === 'github.com'
```

and must throw for:

```text
empty string
localhost
127.0.0.1
[::1]
https://
not a domain
```

- [ ] **Step 2: Run `npm test` and confirm the new tests fail because `lib/domain.ts` does not exist.**

- [ ] **Step 3: Implement `lib/domain.ts` using URL parsing plus a strict hostname regex.**

Required code contract:

```ts
export function normalizeDomain(rawInput: string): string
```

It lowercases the host, strips one leading `www.`, removes a trailing dot, ignores path/query/fragment, rejects localhost/IPs/malformed hosts, and throws `Error('Invalid domain parameter')` for invalid input.

- [ ] **Step 4: Change `lib/crawlora-traffic.ts` to import `normalizeDomain` from `./domain.ts` and remove its private duplicate normalizer.**

- [ ] **Step 5: Run the full test suite and require all existing 14 Crawlora tests plus the new normalization tests to pass.**

- [ ] **Step 6: Commit the focused change.**

Suggested message:

```text
refactor: share domain normalization across metric adapters
```

---

### Task 2: Deterministic Ahrefs DR Client

**Files:**
- Create: `backlink-metrics-api/lib/ahrefs-dr.ts`
- Create/extend: `backlink-metrics-api/tests/ahrefs-dr.test.ts`
- Modify: `backlink-metrics-api/app/api/dr/route.ts`

**Interfaces:**

Produce:

```ts
export type DrStatus = 'CONFIRMED' | 'UNKNOWN' | 'LOOKUP_FAILED' | 'PROVIDER_ERROR';

export type AhrefsDrObservation = {
  domain: string;
  dr: number | null;
  status: DrStatus;
  source: 'Ahrefs';
  checked_at: string;
  provider_status: number | null;
  license: string | null;
  notes?: string;
};

export class AhrefsDrError extends Error {
  status: 'LOOKUP_FAILED' | 'PROVIDER_ERROR';
  providerStatus: number | null;
}

export async function fetchAhrefsDr(args: {
  domain: string;
  apiKey: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}): Promise<AhrefsDrObservation>;
```

- [ ] **Step 1: Write failing tests for positive DR, real numeric zero, missing DR, 401/403, 429, 5xx, malformed JSON, and transport timeout.**

Expected semantics:

```text
numeric positive -> CONFIRMED + numeric dr
numeric zero -> CONFIRMED + dr=0
HTTP 200 but missing/non-finite domain_rating -> UNKNOWN + dr=null
401/403/429/5xx -> throw AhrefsDrError(PROVIDER_ERROR)
timeout/network -> throw AhrefsDrError(LOOKUP_FAILED)
malformed JSON -> throw AhrefsDrError(PROVIDER_ERROR)
```

- [ ] **Step 2: Run only the Ahrefs test file and confirm failure because the module is not implemented.**

- [ ] **Step 3: Implement `lib/ahrefs-dr.ts` with a bounded 10-second upstream timeout and no secret leakage.**

Provider request:

```text
GET https://api.ahrefs.com/v3/public/domain-rating-free?target=<normalized-domain>
Authorization: Bearer <AHREFS_API_KEY>
Accept: application/json
```

- [ ] **Step 4: Refactor `app/api/dr/route.ts` to call `normalizeDomain` + `fetchAhrefsDr`.**

Preserve the current public behavior:

```text
missing/invalid domain -> HTTP 400
missing AHREFS_API_KEY -> HTTP 500
confirmed numeric DR -> HTTP 200
provider HTTP failure -> corresponding provider-style error response
successful payload without valid numeric DR -> HTTP 502, never zero
```

- [ ] **Step 5: Run the full test suite and require zero failures.**

- [ ] **Step 6: Commit.**

Suggested message:

```text
refactor: isolate Ahrefs DR provider semantics
```

---

### Task 3: Rate-Safe Batch DR

**Files:**
- Modify: `backlink-metrics-api/lib/ahrefs-dr.ts`
- Modify: `backlink-metrics-api/tests/ahrefs-dr.test.ts`
- Create: `backlink-metrics-api/app/api/dr/batch/route.ts`

**Interfaces:**

Produce:

```ts
export const MAX_DR_BATCH_DOMAINS = 20;

export type InvalidDomainResult = {
  input: string;
  status: 'INVALID_INPUT';
};

export type AhrefsDrBatchResult = {
  requested: number;
  unique_domains: number;
  invalid_inputs: InvalidDomainResult[];
  results: AhrefsDrObservation[];
};

export async function fetchAhrefsDrBatch(args: {
  domains: unknown[];
  apiKey: string;
  fetchImpl?: typeof fetch;
  sleepImpl?: (ms: number) => Promise<void>;
  minIntervalMs?: number;
  maxRetries?: number;
}): Promise<AhrefsDrBatchResult>;
```

- [ ] **Step 1: Write failing tests for deduplication and invalid input preservation.**

Example input:

```json
[
  "github.com",
  "https://www.github.com/openai",
  "example.com",
  "localhost"
]
```

Expected:

```text
requested=4
unique_domains=2
one INVALID_INPUT entry for localhost
provider called once for github.com and once for example.com
```

- [ ] **Step 2: Write failing tests for partial success.**

One domain may return a confirmed DR while another returns a permanent provider error; the whole batch still resolves with both per-domain results represented.

- [ ] **Step 3: Write failing retry tests.**

Required retry policy:

```text
429 -> retry up to 2 times
5xx -> retry up to 2 times
LOOKUP_FAILED/network -> retry up to 2 times
401/403 -> do not retry
UNKNOWN from a successful 200 payload -> do not retry
```

Tests inject `sleepImpl = async () => {}` so CI does not actually wait.

- [ ] **Step 4: Implement conservative pacing.**

Default:

```ts
minIntervalMs = 1100
maxRetries = 2
```

Process provider attempts sequentially. Sleep between provider attempts so steady-state throughput stays below the default Ahrefs 60-requests/minute ceiling.

Retry backoff adds:

```text
attempt 1 retry: 1500 ms
attempt 2 retry: 3000 ms
```

When provider failure remains after exhaustion, append a result with `dr=null` and explicit `PROVIDER_ERROR` or `LOOKUP_FAILED`; never reject the entire batch.

- [ ] **Step 5: Enforce HTTP-call cap.**

After normalization/deduplication, if more than `MAX_DR_BATCH_DOMAINS=20` valid unique domains remain, `POST /api/dr/batch` returns HTTP 413 with a message instructing the caller to split the run into chunks of 20.

This is intentional: a 100–1000-candidate screening run is multiple bounded HTTP calls, not one long Vercel invocation.

- [ ] **Step 6: Implement `POST app/api/dr/batch/route.ts`.**

Input:

```json
{ "domains": ["example.com", "https://www.github.com/openai"] }
```

Output:

```json
{
  "requested": 2,
  "unique_domains": 2,
  "invalid_inputs": [],
  "results": []
}
```

Validate that `domains` is a non-empty JSON array; otherwise HTTP 400.

- [ ] **Step 7: Run full tests and require zero failures.**

- [ ] **Step 8: Commit.**

Suggested message:

```text
feat: add rate-safe batch DR endpoint
```

---

### Task 4: Align Product/Skill Documentation to Real Scale

**Files:**
- Modify: `BacklinkOS/README.md`
- Modify: `BacklinkOS/docs/REPOSITORY_ARCHITECTURE.md`
- Modify: `BacklinkOS/.agents/skills/screening-backlinks/SKILL.md`
- Modify: `BacklinkOS/.agents/skills/screening-backlinks/references/traffic-evidence.md`
- Modify: `backlink-metrics-api/README.md`

**Interfaces:**
- Consumes: production batch DR contract from Task 3.
- Produces: one consistent operating model for future agents.

- [ ] **Step 1: Remove current operating guidance that frames 100K scale as the expected path.**

Current model must say:

```text
Typical run = about 100–1000 candidate URLs.
Normalize and deduplicate first.
Send unique domains to /api/dr/batch in sequential chunks of at most 20.
A 1000-unique-domain run can take roughly tens of minutes because Ahrefs itself is rate-limited; this is acceptable for personal use.
```

- [ ] **Step 2: Reclassify CrUX.**

Use wording equivalent to:

```text
CrUX is an optional future enhancement, not a current MVP dependency or blocker.
```

Remove instructions that make CrUX the mandatory first traffic layer for the current workflow.

- [ ] **Step 3: Keep Crawlora narrow.**

Current model:

```text
Do not call Crawlora for every domain.
Use it selectively when a concrete total-monthly-visits estimate materially helps the decision.
```

All raw-zero and stale-EstimatedMonthlyVisits protections remain unchanged.

- [ ] **Step 4: Update completion wording.**

After this implementation, `BacklinkOS` should state that the current `screening-backlinks` implementation has one remaining integration gap:

```text
Feishu/Lark automatic persistence
```

Do not count future Discovery as part of this screening implementation.

- [ ] **Step 5: Commit documentation changes in each repository separately.**

Suggested messages:

```text
BacklinkOS: docs: align screening workflow to realistic batch scale
backlink-metrics-api: docs: document bounded batch DR usage
```

---

### Task 5: Production Verification and Integration

**Files:**
- Verify all changed files in both repositories.

**Interfaces:**
- Consumes: completed feature branches.
- Produces: final go/no-go evidence.

- [ ] **Step 1: Run the full metrics test suite on the final `backlink-metrics-api` branch.**

Required:

```text
0 failed tests
existing Crawlora suite remains green
new normalization/Ahrefs/batch tests remain green
```

- [ ] **Step 2: Build the Next.js project and require TypeScript/build success.**

Production build command remains:

```bash
npm test && next build
```

- [ ] **Step 3: Verify a Vercel Preview deployment for the feature branch is READY.**

- [ ] **Step 4: Fresh-call Preview endpoints.**

Verify:

```text
GET /api/dr?domain=hey.com -> numeric DR
POST /api/dr/batch with duplicates/URL forms -> deduplicated confirmed results
GET /api/traffic?domain=github.com -> CONFIRMED positive value
GET /api/traffic?domain=<new nonexistent domain> -> raw_value=0, value=null, UNKNOWN
```

- [ ] **Step 5: Audit scope.**

Confirm no implementation of:

```text
CrUX
Discovery
Feishu
new rating logic
topical relevance
new traffic provider
large-scale queue infrastructure
```

- [ ] **Step 6: Fast-forward both feature branches to `main` only after verification is green.**

- [ ] **Step 7: Wait for final Production deployment of `backlink-metrics-api/main` to be READY and repeat fresh `/api/dr`, `/api/dr/batch`, and `/api/traffic` checks.**

- [ ] **Step 8: Report final SHAs and stop.**

Do not run the full screening Skill yet. Do not implement Feishu in the same plan.
