# Discovery → Screening Handoff Contract (Legacy / Optional)

> **Status: LEGACY / OPTIONAL.**
>
> This contract is preserved only for explicit historical/offline screening work. It is **not** the default BacklinkOS production handoff.

## Current default production path

```text
discovering-backlinks
        ↓
【外链总表】Master Upsert
        ↓
Project Backlog Projection to 【外链管理】
(UNKNOWN != REJECT; no VerifiedEntry required)
        ↓
Bounded Execution Preparation
(live Entry verification; VerifiedEntry required for Ready)
        ↓
Ready allowlist
        ↓
backlink-autofill real browser execution
```

`screening-backlinks` is not an implicit gate between Master and Project Backlog.

## When this legacy contract is used

Use this document only when the user explicitly asks for legacy Screening, historical mechanism reconstruction, or source-page enrichment needed by that workflow.

## Boundary

Discovery owns factual acquisition from project/SEO/backlink data. Legacy Screening owns the historical current-opportunity judgment used by that optional path.

Screening may request more Discovery facts, but Screening does not invent historical source pages and Discovery does not invent acquisition/disposition conclusions.

## Optional domain-level handoff

Historical default fields may include:

`referring_domain | source_projects | successful_project_count | occurrence_count | source_project_organic_traffic | backlinks_num | domain_ascore | first_seen | last_seen | semrush_is_follow | discovery_source | batch_id | first_discovered_at | seen_before`

All values are factual observations. Missing fields stay empty.

## Source-URL enrichment request

When legacy Screening cannot reconstruct a historical mechanism from domain-level evidence, it may request:

`source_url_enrichment_required`

with the minimum scope:

`referring_domain | source_projects | reason`

Discovery may then return directly observed historical facts such as:

`source_url | source_title | target_url | anchor | source_page_ascore | source_rel_observation | source_first_seen | source_last_seen`

These remain historical facts. `source_rel_observation=Follow` does not prove a current free route is Follow.

## Allowed evidence sources

Preferred order:

1. current same-source technical collection exposing the required source-page fields;
2. already saved same-source sanitized captures/results;
3. native Backlinks export from the allowed logged-in Semrush website flow;
4. a relay request contract only after the exact request shape has independently produced real HTTP 200 + expected response structure.

## Unverified request discipline

An unverified endpoint/request must never be promoted to a validated relay contract. Frontend bundle strings, historical notes, or partial captures are only clues until method, parameters, authentication, response shape, and pagination are verified.

Do not ask the user to repeat a Network capture if saved evidence already contains the needed facts.

## Legacy states

- `source_url_enrichment_required` — legacy Screening asks for exact source-page facts;
- `source_url_enriched` — Discovery returned at least one exact source-page fact;
- `source_url_unavailable` — permitted sources were exhausted or blocked; facts remain unknown.

None of these states is a current Project Backlog status or Ready status, and none may be used to prevent ordinary Master candidates from entering the default Project Backlog.
