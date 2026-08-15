# BacklinkOS Repository Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the canonical `screening-backlinks` Skill into `pyxm1618/BacklinkOS`, leave `pyxm1618/backlink-metrics-api` as a deterministic metrics service, and verify that no runtime behavior is changed.

**Architecture:** `BacklinkOS` becomes the product/orchestration source of truth; `backlink-metrics-api` remains the provider/runtime source of truth. The cleanup is a migration only: no CrUX runtime, Discovery Skill, Feishu adapter, rating redesign, provider redesign, or new screening behavior is added.

**Tech Stack:** Git/GitHub, Markdown-based agent Skills, Git symlink for Claude compatibility, Next.js/Vercel for `backlink-metrics-api`, Node test runner.

## Global Constraints

- Two repositories only: `pyxm1618/BacklinkOS` and `pyxm1618/backlink-metrics-api`.
- `BacklinkOS` owns product logic and Skills.
- `backlink-metrics-api` owns deterministic metric integrations and runtime.
- Do not create a third repository.
- Do not implement CrUX runtime during cleanup.
- Do not implement `discovering-backlinks` during cleanup.
- Do not implement Feishu/Lark persistence during cleanup.
- Do not change A/B/C/D/F semantics during cleanup.
- Do not introduce topical relevance.
- Do not copy API keys or secrets between repositories.
- Preserve production `/api/dr` and `/api/traffic` behavior.
- Preserve the existing `screening-backlinks` Skill semantics exactly except for repository/source-of-truth documentation where needed.
- Migration is complete only when one canonical editable copy of `screening-backlinks` remains.

---

## File Structure After Cleanup

### `pyxm1618/BacklinkOS`

Create or retain:

```text
BacklinkOS/
├── README.md
├── .agents/
│   └── skills/
│       └── screening-backlinks/
│           ├── SKILL.md
│           └── references/
│               ├── persistence-schema.md
│               ├── test-cases.md
│               ├── traffic-evidence.md
│               └── verification-and-rating.md
├── .claude/
│   └── skills/
│       └── screening-backlinks -> ../../.agents/skills/screening-backlinks
└── docs/
    ├── V1_PRODUCT_PLAN.md
    ├── V2_PRODUCT_PLAN.md
    ├── V3_PRODUCT_STRATEGY.md
    ├── REPOSITORY_ARCHITECTURE.md
    └── superpowers/
        └── plans/
            └── 2026-08-15-repository-cleanup.md
```

Do not create empty future directories such as `integrations/`, `workflows/`, or `discovering-backlinks/` merely to match the architecture diagram.

### `pyxm1618/backlink-metrics-api`

Retain the existing runtime layout for this cleanup:

```text
backlink-metrics-api/
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── app/api/dr/route.ts
├── app/api/traffic/route.ts
├── lib/crawlora-traffic.ts
├── tests/crawlora-traffic.test.ts
├── docs/crawlora-live-validation-2026-08-15.md
└── package.json
```

Remove only the product Skill copy:

```text
.agents/skills/screening-backlinks/
.claude/skills/screening-backlinks
```

`AGENTS.md` and `CLAUDE.md` remain because they are Next.js/agent runtime guidance, not the backlink Skill itself.

---

### Task 1: Snapshot the canonical Skill before moving it

**Files:**
- Read: `backlink-metrics-api/.agents/skills/screening-backlinks/SKILL.md`
- Read: `backlink-metrics-api/.agents/skills/screening-backlinks/references/persistence-schema.md`
- Read: `backlink-metrics-api/.agents/skills/screening-backlinks/references/test-cases.md`
- Read: `backlink-metrics-api/.agents/skills/screening-backlinks/references/traffic-evidence.md`
- Read: `backlink-metrics-api/.agents/skills/screening-backlinks/references/verification-and-rating.md`
- Read: `backlink-metrics-api/.claude/skills/screening-backlinks`

**Interfaces:**
- Consumes: current `backlink-metrics-api/main` at or after `bf0035414926b5dae749d030920d195b91f9b7d2`.
- Produces: an exact source manifest containing path, blob SHA, and symlink target for every migrated Skill file.

- [ ] **Step 1: Record the five canonical Skill blob SHAs**

Expected source paths:

```text
.agents/skills/screening-backlinks/SKILL.md
.agents/skills/screening-backlinks/references/persistence-schema.md
.agents/skills/screening-backlinks/references/test-cases.md
.agents/skills/screening-backlinks/references/traffic-evidence.md
.agents/skills/screening-backlinks/references/verification-and-rating.md
```

- [ ] **Step 2: Verify the Claude compatibility entry is a symlink**

Expected Git mode and target:

```text
mode: 120000
target: ../../.agents/skills/screening-backlinks
```

- [ ] **Step 3: Verify no secret-like value exists in the Skill tree**

Search at minimum for:

```text
AHREFS_API_KEY
CRAWLORA_API_KEY
crl_
Bearer 
```

Expected: variable names/documentation may exist; no actual credential value is committed.

- [ ] **Step 4: Do not modify the source repository yet**

The destination must be created and verified before the source copy is deleted.

---

### Task 2: Create the canonical Skill in `BacklinkOS`

**Files:**
- Create: `.agents/skills/screening-backlinks/SKILL.md`
- Create: `.agents/skills/screening-backlinks/references/persistence-schema.md`
- Create: `.agents/skills/screening-backlinks/references/test-cases.md`
- Create: `.agents/skills/screening-backlinks/references/traffic-evidence.md`
- Create: `.agents/skills/screening-backlinks/references/verification-and-rating.md`
- Create: `.claude/skills/screening-backlinks` as a Git symlink

**Interfaces:**
- Consumes: exact file contents and symlink target captured in Task 1.
- Produces: the canonical product Skill tree in `BacklinkOS` with unchanged semantics.

- [ ] **Step 1: Copy the five Skill files byte-for-byte**

Do not rewrite wording during migration. The destination file contents must match the Task 1 source contents exactly.

- [ ] **Step 2: Create the Claude compatibility symlink**

Create a Git tree entry with:

```text
path: .claude/skills/screening-backlinks
mode: 120000
type: blob
blob content: ../../.agents/skills/screening-backlinks
```

Do not create a second directory copy under `.claude/skills/`.

- [ ] **Step 3: Verify destination file identity**

For each of the five migrated files, compare destination content to the Task 1 source. Expected: exact content match.

- [ ] **Step 4: Verify the symlink target**

Expected:

```text
.claude/skills/screening-backlinks
→ ../../.agents/skills/screening-backlinks
```

- [ ] **Step 5: Commit the migration into `BacklinkOS`**

Use one focused commit, for example:

```text
feat: make BacklinkOS the canonical screening skill home
```

Do not touch `backlink-metrics-api` in this commit.

---

### Task 3: Add a concise `BacklinkOS` root README

**Files:**
- Create: `BacklinkOS/README.md`

**Interfaces:**
- Consumes: `docs/REPOSITORY_ARCHITECTURE.md` and the migrated Skill path.
- Produces: a human-readable repository entry point that prevents future product/runtime mixing.

- [ ] **Step 1: Create a minimal README with the repository boundary**

The README must state:

```text
BacklinkOS = backlink product/orchestration repository.
Canonical Skill: .agents/skills/screening-backlinks/
Deterministic metrics runtime: pyxm1618/backlink-metrics-api
Production metrics endpoint: https://backlink-metrics-api.vercel.app
```

- [ ] **Step 2: Document current status without overclaiming**

Include:

```text
Implemented:
- screening-backlinks Skill contract
- DR runtime dependency
- selective Crawlora total-monthly-visits runtime dependency

Not yet implemented:
- CrUX bulk runtime
- Feishu persistence adapter
- large-scale batch orchestration
- discovering-backlinks Skill
```

- [ ] **Step 3: Link to architecture and strategy docs using repository-relative paths**

Use:

```text
docs/REPOSITORY_ARCHITECTURE.md
docs/V3_PRODUCT_STRATEGY.md
```

- [ ] **Step 4: Commit the README**

This may be included in the same BacklinkOS migration commit if implementation tooling supports one atomic tree commit; otherwise use a second focused documentation commit.

---

### Task 4: Remove product-Skill ownership from `backlink-metrics-api`

**Files:**
- Delete: `.agents/skills/screening-backlinks/SKILL.md`
- Delete: `.agents/skills/screening-backlinks/references/persistence-schema.md`
- Delete: `.agents/skills/screening-backlinks/references/test-cases.md`
- Delete: `.agents/skills/screening-backlinks/references/traffic-evidence.md`
- Delete: `.agents/skills/screening-backlinks/references/verification-and-rating.md`
- Delete: `.claude/skills/screening-backlinks`
- Modify: `README.md`

**Interfaces:**
- Consumes: verified canonical destination from Tasks 2–3.
- Produces: a metrics-only repository with no editable backlink Skill copy.

- [ ] **Step 1: Confirm the destination exists before deletion**

Required checks:

```text
BacklinkOS/.agents/skills/screening-backlinks/SKILL.md exists
all four reference files exist
BacklinkOS/.claude/skills/screening-backlinks is a symlink
```

If any check fails, stop and do not delete the source Skill.

- [ ] **Step 2: Delete the five source Skill files and Claude symlink**

After file deletion, empty `.agents/skills/screening-backlinks/` and `.claude/skills/` directories disappear naturally from Git.

- [ ] **Step 3: Update `backlink-metrics-api/README.md`**

The README must say this repository owns deterministic metrics only and that the canonical screening Skill lives in:

```text
https://github.com/pyxm1618/BacklinkOS/tree/main/.agents/skills/screening-backlinks
```

Retain documentation for:

```text
/api/dr
/api/traffic
AHREFS_API_KEY
CRAWLORA_API_KEY
npm test
```

Do not move provider code in this cleanup.

- [ ] **Step 4: Commit the metrics-repository cleanup**

Use one focused commit, for example:

```text
refactor: keep metrics repo runtime-only
```

---

### Task 5: Verify repository boundaries and source-of-truth uniqueness

**Files:**
- Inspect: both repository trees after Tasks 2–4.

**Interfaces:**
- Consumes: both cleanup commits.
- Produces: evidence that the repository split is complete and non-duplicative.

- [ ] **Step 1: Verify `BacklinkOS` owns exactly one canonical Skill**

Expected path:

```text
.agents/skills/screening-backlinks/SKILL.md
```

- [ ] **Step 2: Verify `backlink-metrics-api` has no canonical Skill copy**

Search for:

```text
screening-backlinks
```

Allowed occurrences after cleanup:

- README link pointing to `BacklinkOS`
- provider validation text that mentions screening context descriptively

Disallowed:

- `.agents/skills/screening-backlinks/`
- `.claude/skills/screening-backlinks`

- [ ] **Step 3: Verify product/runtime ownership by tree inspection**

Expected runtime files remain in `backlink-metrics-api`:

```text
app/api/dr/route.ts
app/api/traffic/route.ts
lib/crawlora-traffic.ts
tests/crawlora-traffic.test.ts
docs/crawlora-live-validation-2026-08-15.md
```

- [ ] **Step 4: Verify no secrets were added during migration**

Search changed files for actual credential-like material. Environment variable names are allowed; secret values are not.

---

### Task 6: Re-run metrics tests and production regressions

**Files:**
- Test: `backlink-metrics-api/tests/crawlora-traffic.test.ts`
- Runtime: production `/api/dr`
- Runtime: production `/api/traffic`

**Interfaces:**
- Consumes: cleaned `backlink-metrics-api/main`.
- Produces: fresh evidence that repository organization did not change runtime behavior.

- [ ] **Step 1: Run the full metrics test suite**

Run:

```bash
npm test
```

Expected current baseline:

```text
14 tests
14 pass
0 fail
```

If the number changes because unrelated upstream work has landed, require zero failures and explain the delta instead of forcing the historical count.

- [ ] **Step 2: Verify the production deployment for the cleanup commit is READY**

Do not treat a successful Git commit alone as deployment verification.

- [ ] **Step 3: Fresh-call DR production endpoint**

Request:

```text
GET https://backlink-metrics-api.vercel.app/api/dr?domain=hey.com
```

Expected contract:

```json
{
  "domain": "hey.com",
  "dr": "<numeric>",
  "source": "Ahrefs"
}
```

Do not assert DR must remain exactly `80`; Ahrefs can change over time.

- [ ] **Step 4: Fresh-call Traffic production endpoint**

Request:

```text
GET https://backlink-metrics-api.vercel.app/api/traffic?domain=github.com
```

Expected contract:

```text
HTTP 200
metric_type = total_monthly_visits_estimate
status = CONFIRMED
value = positive numeric
source = Crawlora / Similarweb public surface
```

- [ ] **Step 5: Fresh-call an obviously nonexistent domain**

Expected contract:

```text
raw_value = 0
value = null
status = UNKNOWN
```

The cleanup must not regress the `raw zero ≠ confirmed zero` rule.

---

### Task 7: Final migration audit

**Files:**
- Read: `BacklinkOS/README.md`
- Read: `BacklinkOS/docs/REPOSITORY_ARCHITECTURE.md`
- Read: `BacklinkOS/.agents/skills/screening-backlinks/SKILL.md`
- Read: `backlink-metrics-api/README.md`

**Interfaces:**
- Consumes: completed migration and verification evidence.
- Produces: final go/no-go decision for repository cleanup only.

- [ ] **Step 1: Check architecture consistency**

Confirm all four documents agree that:

```text
BacklinkOS owns Skills/product workflow.
backlink-metrics-api owns deterministic provider runtime.
```

- [ ] **Step 2: Check scope discipline**

Confirm cleanup commits contain none of:

```text
CrUX runtime
Discovery Skill
Feishu adapter
new rating rules
topical relevance
new provider integration
```

- [ ] **Step 3: Report exact final commit SHAs for both repositories**

Report separately:

```text
BacklinkOS: <sha>
backlink-metrics-api: <sha>
```

- [ ] **Step 4: Stop after cleanup**

Do not run the full `screening-backlinks` Skill and do not start CrUX implementation in the same execution. The next development stage begins only after the user reviews the cleaned repository structure.
