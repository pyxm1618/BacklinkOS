# BacklinkOS V4 Product Strategy

## Status

**Current product strategy as of 2026-08-22.**

BacklinkOS is a personal SEO backlink opportunity system for discovering and maintaining a reusable database of **general-purpose backlink opportunities**.

It has two implemented intelligence capabilities:

1. **Discover** — systematically find new backlink candidates from projects that already show SEO results.
2. **Screen** — verify whether each candidate currently exposes a reusable, executable backlink opportunity.

The system intentionally does **not** evaluate topical relevance to a promoted website and does not perform Project × Opportunity matching.

## 1. Core workflow

```text
Discover
   ↓
Screen
   ↓
Operational persistence / execution
```

Discovery and Screening must remain separate. A historical backlink observation can identify a candidate, but it cannot prove that the current public route is free, Follow, or still executable.

## 2. `discovering-backlinks`

The canonical Discovery Skill is:

```text
.agents/skills/discovering-backlinks/
```

Its job is to find candidate referring domains and preserve factual provenance.

Current operating model:

1. build batches of recently successful projects from sources such as Toolify, There’s An AI For That, TrustMRR, and similar sources;
2. deduplicate projects against prior batches;
3. use the validated `sem.3ue.com` Semrush relay rather than relying on unavailable official API units;
4. query project Organic Traffic and retain explicit `no_data` / error semantics;
5. by default, continue to Referring Domains for projects with Global Organic Traffic `>= 500`;
6. page Referring Domains according to the returned total rather than silently truncating;
7. preserve raw facts such as source projects, referring domain, backlinks count, Authority Score, first/last seen, and historical `is_follow`;
8. aggregate repeated referring domains across successful projects;
9. hand candidates to `screening-backlinks`.

Discovery does not decide current pricing, current free availability, current final-link attributes, or project fit. Unknown facts remain unknown.

## 3. `screening-backlinks`

The canonical Screening Skill is:

```text
.agents/skills/screening-backlinks/
```

Its job is to answer:

> Can an ordinary user currently obtain an effective Follow backlink without paying?

Current acquisition classifications are exactly:

- `免费`
- `免费换链`
- `付费`
- `不确定`

A formal reusable opportunity must have all of the following confirmed:

- a current ordinary-user execution route;
- no required payment (`免费换链` is tracked separately when a reciprocal backlink is required);
- a direct external link on the final public page;
- no `nofollow`, `ugc`, or `sponsored` token on the final link;
- an indexable final page.

Paid opportunities, Nofollow/UGC/Sponsored placements, missing external URLs, dead routes, noindex pages, and verified spam/link-network placements do not enter the formal opportunity table.

Critical facts that cannot be closed are `不确定`; they are not guessed.

## 4. No A/B/C/D/F decision model

V4 no longer uses A/B/C/D/F as the current screening/admission system.

DR, traffic, successful-project coverage, first-seen dates, and similar metrics may help prioritize work or provide context, but they do not determine whether a candidate belongs in the formal opportunity table.

Some compatibility persistence code still contains historical rating fields. Those fields are retained only to avoid silently breaking existing integrations; they are not current V4 business semantics.

## 5. General-purpose opportunity model

BacklinkOS stores reusable opportunities, not destination-project matches.

The system may describe source-site metadata and operational restrictions, but it does not answer questions such as:

- whether Quick I Ching is eligible for a specific opportunity;
- whether an opportunity is topically relevant to a particular site;
- whether one destination project deserves a higher relevance score than another.

Those decisions are outside the V4 opportunity database contract.

## 6. Evidence discipline

BacklinkOS distinguishes direct facts from interpretations.

Examples:

- Semrush historical `is_follow` is discovery evidence, not proof that the current free route is Follow;
- `first_seen` is Semrush’s first observation, not a precise acquisition date;
- provider missing data is not zero;
- failed lookup is not a negative business conclusion;
- network-level rejection requires evidence of a common operator, mechanism, template, or other closed family-level proof rather than visual similarity alone.

## 7. Supporting runtime

### Metrics

Provider-specific deterministic metric runtime belongs in:

```text
pyxm1618/backlink-metrics-api
```

BacklinkOS should consume metric evidence without duplicating provider implementation code inside the Skills.

### Bulk triage crawler

`scripts/screening_crawler.py` and its GitHub Actions workflow remain active helpers for large candidate pools.

They are a **pre-screening triage mechanism**, not the V4 final decision engine. Their machine buckets may prioritize follow-up, but final admission/rejection must meet the evidence contract in `screening-backlinks`.

### Persistence

The current user-facing output contract is defined by:

```text
.agents/skills/screening-backlinks/references/output-schema.md
```

Existing Feishu API/library code is retained as compatibility infrastructure from an earlier record schema. Any migration of that runtime to the new output schema is a separate behavior-changing project and is not part of repository hygiene cleanup.

## 8. Current completion state

Implemented:

- dedicated `discovering-backlinks` Skill;
- validated Semrush relay workflow and batch runner;
- dedicated `screening-backlinks` Skill;
- current free / reciprocal / paid / uncertain screening semantics;
- network-level evidence rules;
- current formal output-table schema;
- operational bulk triage crawler;
- compatibility Feishu persistence runtime;
- deterministic metric-runtime separation.

The main work now is operational: continue discovery batches, screen candidates to closure, improve the evidence library from real cases, and change runtime code only when real usage demonstrates a concrete need.

## 9. Explicit non-goals

V4 does not build:

- topical relevance scoring;
- Project × Opportunity matching;
- destination-site eligibility decisions;
- an Ahrefs/Semrush replacement;
- a massive backlink crawler/index;
- 100K-scale distributed processing infrastructure;
- uncontrolled automated backlink spam;
- a black-box weighted SEO score.

## 10. Product rule

When product documentation conflicts with a canonical Skill, the Skill is authoritative. Historical plans are retained to preserve decision history, not to override the current operating contract.