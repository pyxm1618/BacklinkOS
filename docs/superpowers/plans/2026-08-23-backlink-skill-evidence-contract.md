# Backlink Skill Evidence Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the two canonical BacklinkOS Skills with a source-URL enrichment handoff, explicit evidence precedence, separated acquisition/disposition semantics, source-balanced seed expansion, and persistence safety.

**Architecture:** Preserve `discovering-backlinks` and `screening-backlinks` as separate canonical Skills. Add a small handoff reference owned by Discovery; Screening may request enrichment but never performs Discovery itself. Enforce the contract with an executable TypeScript test that reads the canonical Markdown files.

**Tech Stack:** Agent Skills Markdown, Node.js 22, TypeScript 5.9, `node:test`, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-23-backlink-skill-evidence-contract-design.md`

## Global Constraints

- Do not merge Discovery and Screening into one Skill.
- Do not weaken existing Semrush relay/session/pagination/no-data safety rules.
- Do not declare an exact Backlinks/source-URL relay endpoint validated unless a real HTTP 200 contract has been verified.
- Historical Semrush observations remain facts, not current-route conclusions.
- Paid exclusion and recycle remain distinct final dispositions.
- Unknown facts remain unknown.

---

### Task 1: Add executable contract tests

**Files:**
- Create: `tests/skill-contracts.test.ts`

**Interfaces:**
- Consumes: canonical Markdown files under `.agents/skills/`.
- Produces: CI-enforced assertions for the upgraded Skill contract.

- [ ] **Step 1: Write failing tests**

Create tests that assert:

```ts
assert.match(discovery, /pending_semrush/);
assert.match(discovery, /source_url_enrichment_required/);
assert.match(discovery, /source_url/);
assert.match(screening, /证据优先级/);
assert.match(screening, /付费排除/);
assert.doesNotMatch(screening, /`付费`、Nofollow\/UGC\/Sponsored、没有外部 URL、入口失效、页面 noindex、明显垃圾站 → 回收站/);
assert.match(rules, /not found.*!=.*recycle|没找到.*不等于.*回收/i);
assert.match(rules, /target.*readback.*source|目标.*回读.*源/);
```

- [ ] **Step 2: Verify RED**

Run through PR CI: `npm test`.
Expected: the new `skill-contracts.test.ts` fails because the old Skill text lacks the new contract and still conflates paid with recycle.

- [ ] **Step 3: Commit test-only change**

Commit message: `test: define backlink skill evidence contract`.

---

### Task 2: Upgrade Discovery contract

**Files:**
- Modify: `.agents/skills/discovering-backlinks/SKILL.md`
- Create: `.agents/skills/discovering-backlinks/references/screening-handoff.md`
- Modify: `.agents/skills/discovering-backlinks/references/test-cases.md`

**Interfaces:**
- Consumes: project seeds, Semrush Organic/RD facts, optional saved/native Backlinks exports.
- Produces: factual RD candidates plus optional source-page enrichment; `source_url_enrichment_required` is a request state originating from Screening.

- [ ] **Step 1: Add seed-balance and paused-Semrush behavior**

Document that 100 is a batch size, not a global stop; track source counts; when Semrush is unavailable, only verified project seeds may be appended with `pending_semrush`.

- [ ] **Step 2: Add source-URL enrichment handoff**

Add `references/screening-handoff.md` with the request/response fields and the rule that unverified relay endpoints must not be invented.

- [ ] **Step 3: Extend Discovery output fields**

Add optional fields:

```text
source_url | source_title | target_url | anchor | source_page_ascore |
source_rel_observation | source_first_seen | source_last_seen
```

- [ ] **Step 4: Add regression cases**

Cover source concentration, `pending_semrush`, enrichment requests, and unverified endpoint discipline.

- [ ] **Step 5: Commit**

Commit message: `feat: add discovery evidence enrichment handoff`.

---

### Task 3: Upgrade Screening semantics

**Files:**
- Modify: `.agents/skills/screening-backlinks/SKILL.md`
- Modify: `.agents/skills/screening-backlinks/references/screening-rules.md`
- Modify: `.agents/skills/screening-backlinks/references/output-schema.md`
- Modify: `.agents/skills/screening-backlinks/references/test-cases.md`

**Interfaces:**
- Consumes: Discovery facts and current public evidence.
- Produces: acquisition mode plus independent final disposition; may request Discovery enrichment when domain-level evidence is insufficient.

- [ ] **Step 1: Add evidence precedence**

Document current DOM/HTML > official current mechanism docs > same-path current example > reliable current third-party concrete test > historical Semrush > inference.

- [ ] **Step 2: Separate acquisition mode and disposition**

Keep acquisition mode `免费 / 免费换链 / 付费 / 不确定` and add disposition `正式机会 / 付费排除 / 回收 / 待确认`.

- [ ] **Step 3: Fix paid/recycle contradiction**

Paid Follow opportunities become `付费排除`, not `回收`; free Nofollow/UGC/Sponsored remains recycle.

- [ ] **Step 4: Add missing-data and persistence safety rules**

Explicitly encode not-found discipline, historical/AS non-decision rules, network-evidence requirements, target-write/readback/source-clear migration order, and formula-row safety.

- [ ] **Step 5: Add enrichment request path**

When current domain-level evidence cannot identify the mechanism, return `source_url_enrichment_required` rather than guessing or blindly rejecting.

- [ ] **Step 6: Update output schema and test cases**

Document acquisition/disposition as separate internal fields and keep the formal opportunity table limited to confirmed free/reciprocal opportunities.

- [ ] **Step 7: Commit**

Commit message: `feat: strengthen screening evidence semantics`.

---

### Task 4: Verify and open PR

**Files:**
- No new production files.

**Interfaces:**
- Consumes: branch state after Tasks 1-3.
- Produces: verified PR ready for independent review.

- [ ] **Step 1: Run CI**

Required commands in GitHub Actions:

```text
npm test
npm run typecheck
python -m unittest tests/test_screening_crawler.py -v
```

Expected: all green.

- [ ] **Step 2: Inspect PR diff**

Verify only intended Skill/reference/spec/plan/test files changed and no credentials/session keys appear.

- [ ] **Step 3: Perform self-review**

Check the diff against the design acceptance criteria, especially paid-vs-recycle semantics and the prohibition on claiming an unverified Backlinks relay contract.

- [ ] **Step 4: Open PR**

Title: `feat: strengthen backlink discovery-screening evidence contract`

PR body must include summary, behavior changes, RED/GREEN test evidence, CI result, and explicit note that exact Backlinks relay request parameters were not newly claimed as validated.
