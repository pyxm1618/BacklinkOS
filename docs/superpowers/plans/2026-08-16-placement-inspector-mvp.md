# Placement Inspector MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the minimum deterministic HTML inspector needed to verify the real Blogstival Quick I Ching article without asking the user to inspect source manually.

**Architecture:** Add a small parsing library plus a Vercel GET function. The function fetches a public page with strict URL safety and bounded limits, then parses anchors, robots directives, canonical URL, headings, and basic formatting evidence. The first live target is the user's published `outline.blogstival.com` article.

**Tech Stack:** TypeScript 5.9, Node.js 24 built-ins, Vercel Functions, Node test runner.

## Global Constraints

- No LLM inference for `rel` or link existence.
- Missing evidence stays unknown; it never becomes Dofollow/Nofollow by guess.
- Fetch only `http:`/`https:` public URLs and reject local/private network targets.
- Re-validate redirects, cap redirects at 5, timeout at 10 seconds, and cap HTML at 2 MB.
- Do not add a headless browser in this MVP.
- Do not modify traffic, DR, domain-age, or Feishu behavior in this plan.

---

### Task 1: Deterministic HTML parsing

**Files:**
- Create: `lib/placement/html-inspector.ts`
- Create: `tests/placement-html-inspector.test.ts`

**Interfaces:**
- Produces: `inspectHtml(html: string, baseUrl: string, target?: string): HtmlInspection`
- `HtmlInspection` includes target matches, raw `rel`, link classification, meta robots, canonical URL, heading counts, and whether meaningful HTML formatting tags survived.

- [ ] **Step 1: Write failing parser tests**

Cover: target anchor with no `rel`; `noopener noreferrer`; `nofollow`; `ugc`; missing target; `meta robots=noindex`; canonical resolution; H2/H3 preservation; fully flattened paragraph HTML.

- [ ] **Step 2: Run tests and confirm failure**

Run: `npm test`
Expected: FAIL because `lib/placement/html-inspector.ts` does not exist.

- [ ] **Step 3: Implement parser with no new dependency**

Use bounded regular-expression extraction for `<a>`, `<meta>`, `<link rel="canonical">`, and heading tags. Normalize attribute names case-insensitively and decode only the minimal HTML entities required for URLs and attribute tokens.

- [ ] **Step 4: Run tests**

Run: `npm test`
Expected: PASS.

### Task 2: Safe public fetcher and Vercel endpoint

**Files:**
- Create: `lib/placement/public-fetch.ts`
- Create: `api/placement/inspect.ts`
- Create: `tests/placement-api.test.ts`

**Interfaces:**
- Produces: `fetchPublicHtml(url: URL): Promise<FetchResult>`
- Produces: `GET /api/placement/inspect?url=<public_url>&target=<optional_target>`

- [ ] **Step 1: Write failing request validation tests**

Cover: missing URL, invalid scheme, localhost, loopback/private literal IP, valid public HTTPS URL, parser result mapping, fetch failure semantics.

- [ ] **Step 2: Run tests and confirm failure**

Run: `npm test`
Expected: FAIL because fetcher/handler do not exist.

- [ ] **Step 3: Implement safe fetcher**

Use Node DNS resolution before each request/redirect, reject private/reserved IP ranges, use manual redirects, 5 redirect maximum, `AbortSignal.timeout(10000)`, 2 MB response cap, and a neutral browser-like user agent. Do not forward cookies or authorization.

- [ ] **Step 4: Implement endpoint**

Return JSON with request URL, final URL/hostname, HTTP status, target matches and `rel`, robots/canonical, heading counts, formatting-preservation evidence, checked time, and explicit status.

- [ ] **Step 5: Run tests and typecheck**

Run: `npm test && npm run typecheck`
Expected: PASS.

### Task 3: Live Blogstival verification

**Files:**
- Modify only if live evidence exposes a parser bug: files from Tasks 1–2.

**Interfaces:**
- Consumes deployed `/api/placement/inspect` endpoint.

- [ ] **Step 1: Wait for Git-connected Vercel deployment of main**

Confirm deployment succeeds.

- [ ] **Step 2: Query the real article**

URL: `https://outline.blogstival.com/64300257/three-ways-to-consult-the-i-ching-coins-yarrow-stalks-and-mei-hua-yi-shu`
Target: `https://www.quickiching.com/`

- [ ] **Step 3: Record the factual conclusion**

Distinguish these cases:
- target `<a>` exists in final HTML -> external link is published; classify exact `rel`;
- Quick I Ching text exists but no target `<a>` -> Blogstival/theme strips or fails to render the link;
- HTML keeps headings/paragraphs but target anchor disappears -> link-specific filtering;
- headings and anchors are both stripped/flattened -> content-rendering/theme/template problem rather than a link-only policy.

- [ ] **Step 4: Decide next product action**

If the current theme strips markup, test a platform-supported alternative theme or a different placement mechanism before classifying the entire Blogstival platform as unable to produce links. Do not infer sibling domains until spot-checked.
