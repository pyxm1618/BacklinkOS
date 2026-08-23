# Discovery → Screening Handoff Contract

## Boundary

Discovery owns factual acquisition from project/SEO/backlink data. Screening owns current-opportunity judgment. Screening may request more Discovery facts, but Screening does not invent historical source pages，**Discovery 不决定获取方式或处理结果**。

## Default handoff

Domain-level discovery is the default handoff because it is cheaper and usually sufficient:

`referring_domain | source_projects | successful_project_count | occurrence_count | source_project_organic_traffic | backlinks_num | domain_ascore | first_seen | last_seen | semrush_is_follow | discovery_source | batch_id | first_discovered_at | seen_before`

All values are factual observations. Missing fields stay empty.

## Source-URL enrichment request

When domain-level facts are insufficient to identify the historical backlink mechanism, **Screening 请求 Discovery** 返回 `source_url_enrichment_required`，并附最小必要范围：

`referring_domain | source_projects | reason`

Discovery then enriches only the requested candidate/project set and returns any directly observed fields:

`source_url | source_title | target_url | anchor | source_page_ascore | source_rel_observation | source_first_seen | source_last_seen`

The response remains historical/factual evidence. `source_rel_observation=Follow` does not prove that a current public free route is Follow.

## Allowed evidence sources

Use, in order of preference:

1. current same-source technical collection that directly exposes the source-page fields;
2. already saved same-source sanitized captures/results;
3. native Backlinks export from the allowed logged-in Semrush website flow;
4. a relay request contract only after that exact request shape has been independently validated by real HTTP 200 + expected response structure.

## Unverified request discipline

An **unverified endpoint/request must never be promoted to a validated relay contract**. Seeing an endpoint name in a frontend bundle, historical note, or partial capture is only a clue. Until exact method, parameters, authentication, response shape, and any required pagination are verified, do not add them to `references/semrush-relay.md` as validated.

Do not ask the user to repeat a Network capture if a saved capture/export already contains the needed source-page facts.

## States

- `source_url_enrichment_required`: Screening cannot close the mechanism from domain-level evidence and asks Discovery for exact source-page facts.
- `source_url_enriched`: Discovery returned at least one exact source-page fact.
- `source_url_unavailable`: permitted sources were exhausted or blocked; facts remain unknown and Screening decides whether that leaves the candidate `待确认`.

None of these states is a quality rating.
