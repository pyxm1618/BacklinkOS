# Backlink Skill Evidence Contract Design

## Goal

Upgrade the two canonical BacklinkOS Skills without merging their responsibilities. `discovering-backlinks` remains the fact-finding capability; `screening-backlinks` remains the current-opportunity decision capability. The upgrade closes the operational gap between domain-level discovery and current-path screening.

## Problem

The current architecture is sound, but real batches exposed four gaps:

1. Discovery can stop at referring-domain facts even when Screening needs an exact historical source page to identify the backlink mechanism.
2. Seed discovery does not explicitly control source concentration or define what to do when Semrush is temporarily unavailable.
3. Screening has no canonical evidence-precedence ladder, so conflicts such as current HTML vs historical Semrush Follow are only implied rather than mechanically clear.
4. `获取方式` and final disposition are conflated in wording: paid opportunities are a distinct business outcome, while spam/Nofollow/dead mechanisms are recycle outcomes.

## Architecture

Keep two Skills and add a formal handoff contract.

```text
project seeds
  -> Organic qualification
  -> referring domains
  -> optional source-URL enrichment when Screening requests it
  -> screening evidence closure
  -> disposition
```

No third decision Skill is added.

## Discovery changes

### Seed batching

- Default batch target remains 100 new project seeds, but 100 is a batch size, not a global stopping condition.
- Prefer Toolify, There’s An AI For That, TrustMRR, and similar recent-project sources.
- Track per-source counts. If one source dominates a growing project pool, prefer another already-approved source before going deeper into the dominant source.
- If Semrush is temporarily unavailable, Discovery may continue collecting verified project seeds and mark them `pending_semrush`. It must not fabricate Organic values, qualification, RD rows, or backlink facts.

### Source-URL enrichment

Domain-level RD discovery remains the default because it is cheaper. When Screening cannot determine the mechanism from domain-level evidence, it may request enrichment for a specific `referring_domain` and source project set.

Enrichment may add:

`source_url | source_title | target_url | anchor | source_page_ascore | source_rel_observation | source_first_seen | source_last_seen`

Unknown fields stay empty. Historical source-page observations remain Discovery facts and do not prove current free availability.

The validated relay contracts for Organic and Referring Domains remain unchanged. Exact Backlinks/source-URL requests are not declared relay-validated until a real request contract is independently verified. Until then, enrichment may use saved same-source exports/captures or native Backlinks export from the allowed logged-in Semrush website flow.

## Screening changes

### Evidence precedence

Use this canonical order when evidence conflicts:

1. current final listing/result HTML or DOM;
2. current official Submit/Pricing/FAQ/Terms describing the same mechanism;
3. current public example produced by the same path/template;
4. reliable current third-party test with concrete result-page evidence;
5. Discovery historical Semrush observations;
6. inference.

Higher-precedence evidence wins when it directly addresses the same fact.

### Acquisition mode vs disposition

Keep acquisition mode as:

- `免费`
- `免费换链`
- `付费`
- `不确定`

Keep final disposition as a separate field:

- `正式机会`
- `付费排除`
- `回收`
- `待确认`

Examples:

- paid Follow route -> `获取方式=付费`, `处理结果=付费排除`;
- free Nofollow route -> `获取方式=免费`, `处理结果=回收`;
- free route with unresolved final rel -> `获取方式=免费`, `处理结果=待确认`;
- free current Follow + indexable -> `获取方式=免费`, `处理结果=正式机会`.

### Missing-data discipline

Explicitly preserve:

- not found != recycle;
- AS=0 != recycle;
- historical 0 Follow != recycle;
- historical 100% Follow != current Follow;
- CAPTCHA/login/manual review != recycle;
- visually suspicious domains != network-level rejection.

Network/PBN/link-selling rejection still requires closed evidence of operator, mechanism, template, commercial link-selling behavior, or documented network relationship.

### Operational routes

A/B/C/D-style labels may exist as internal resolution routes, but never as business ratings or admission criteria.

## Persistence safety

When moving records between operational tables:

1. write target row first;
2. read back the target row;
3. only then clear source-owned data cells;
4. do not clear whole rows when array formulas or computed routing columns may be present;
5. recompute total-state invariants after each migration batch.

This is an operational safety contract, not a user-facing classification rule.

## Output/handoff contract

Discovery passes factual fields only. Screening may return `source_url_enrichment_required` with a reason when domain-level facts are insufficient. Discovery then enriches only the requested candidate(s) and returns the added facts without changing the screening disposition itself.

## Acceptance criteria

- The two canonical Skills remain separate and retain current Semrush relay safety rules.
- Discovery documents balanced seed expansion, `pending_semrush`, and source-URL enrichment without inventing an unverified relay endpoint.
- Screening documents the evidence ladder and separates acquisition mode from disposition.
- Paid exclusions are no longer described as recycle outcomes.
- Missing-data and persistence-safety rules are explicit.
- Regression tests fail on the old Skill text and pass after the upgrade.
- Existing TypeScript, typecheck, and Python crawler regression tests continue to pass.
