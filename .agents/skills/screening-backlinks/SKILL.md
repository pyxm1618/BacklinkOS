---
name: screening-backlinks
description: Use when screening backlink/外链 candidate URLs or domains for a reusable SEO opportunity database, including competitor backlinks, profile links, blog comments, Web 2.0 posts, classifieds, directories, communities, and similar user-publishable link opportunities.
---

# Screening Backlinks

## Goal

Create an auditable backlink-opportunity record from current evidence. Treat every candidate placement as an independent verification task. Facts come before rating.

This skill screens already-discovered candidates. It does **not** discover backlinks. Discovery belongs in a separate skill/workflow that outputs candidates into this screening pipeline.

This skill orchestrates research and verification. Deterministic metrics belong in APIs/scripts; do not reimplement them by guessing or by substituting unrelated third-party metrics.

## Operating scale

This is a personal-use workflow. A typical run contains roughly **100–1000 candidate URLs**, not 100K-scale input.

For domain-wide metrics:

1. normalize candidate URLs/domains
2. deduplicate normalized domains
3. reuse one current domain-wide metric observation across placements on that same domain when appropriate
4. keep placement-specific facts such as publishability and link attribute independent

Do not build or assume distributed workers, large ingestion queues, or other large-scale infrastructure for the current workflow.

## Non-negotiable rules

1. **Verify each candidate independently.** Never infer one site's registration, pricing, link attribute, publishability, or traffic from another site, even when they share a CMS, template, owner, or network.
2. **Historical backlinks are discovery evidence only.** A competitor's old backlink does not prove the placement is currently reproducible.
3. **Missing is not zero.** A failed lookup, blocked page, absent field, parser failure, 403, CAPTCHA, unsupported source, or provider no-coverage result must not become `0`, `无`, `Nofollow`, or `F`.
4. **Preserve metric semantics.** Organic-search traffic, total monthly visits, and popularity evidence are different metrics and must never overwrite or impersonate one another.
5. **Use current, direct evidence whenever possible.** Prefer first-party pages, actual forms, actual published examples, raw final HTML, official metric APIs, authoritative RDAP, and clearly documented provider APIs.
6. **Do not use topical relevance.** This database is shared across outbound sites in different industries. There is no `相关度` field and relevance must not affect A/B/C/D/F.
7. **Do not assign A/B/C/D before collecting available facts.** `F` may be assigned early only for a verified hard rejection defined below.
8. **Traffic never independently causes F.** Low traffic, confirmed zero from a future provider with valid zero semantics, unknown traffic, no coverage, or provider failure are not hard rejection reasons.
9. **Do not claim persistence succeeded unless the target system confirms the write.**

## Inputs

Accept one or more of:

- candidate URL(s) or domain(s)
- competitor/source URL that revealed the opportunity
- an existing backlink database/export to deduplicate against
- a requested placement type such as profile, comment, article, classified, directory, or community post

The destination website being promoted is optional and must not be used to calculate relevance.

## Record identity

Do not collapse distinct placements on the same domain.

Use a placement identity based on:

`canonical_domain + placement_type + publish_entry_url`

A profile link and a blog-comment link on the same domain may have different rules and different `rel` values; keep them separate.

A domain-wide hard rejection can block every placement only when the evidence is truly domain-wide, such as an expired/dead domain.

## Workflow

### 1. Normalize, deduplicate, and check existing records

- Normalize the hostname to lowercase and remove a leading `www.` for the canonical database domain.
- Preserve the original candidate URL as evidence.
- Deduplicate domain-wide metric work before making provider calls.
- Do **not** deduplicate placement records by domain alone; the placement identity remains `canonical_domain + placement_type + publish_entry_url`.
- If an existing database is available, search it before doing expensive research.
- If the exact placement already has a verified `F` hard-rejection record, reuse it unless the user explicitly requests revalidation.
- If no database/persistence backend is accessible, continue with evidence collection but never pretend a lookup occurred.

### 2. Verify current publishability

Open the candidate and independently confirm:

- the site/page currently exists
- an ordinary user can currently reach a reproducible publishing path
- the path can produce an external link
- the applicable placement type
- the actual publishing entry URL

Examples of valid mechanisms:

- profile Website/Bio field
- blog/article publishing
- blog comment Website field or permitted comment-body link
- classified ad URL field
- directory submission
- community/forum profile or post

Do not mark `可发布` merely because a page contains an old external link.

If your runtime is blocked by 403, CAPTCHA, geofencing, login state, or tooling limitations, classify the fact as `未确认`; this alone is not an `F`.

### 3. Verify registration and pricing

Inspect the current signup/login/publishing flow for this site itself.

`注册登录` should use a concise value such as:

- `无需注册`
- `需要注册登录`
- `需要审核`
- `未确认`

`免费情况` should use:

- `免费`
- `部分免费`
- `付费`
- `未确认`

Do not infer either field from the platform category.

### 4. Classify industry and placement

`行业` describes the platform/site itself using a broad stable category, for example `综合博客平台`, `科技`, `教育`, `生活方式`, `体育`, `商业服务`.

`外链形式` should identify the actual placement, for example `Profile`, `Blog/Post`, `Comment`, `Classified`, `Directory`, `Community/Forum`.

Industry is descriptive metadata only. It is not project relevance and must not alter A/B/C/D/F.

### 5. Verify Dofollow/Nofollow from final HTML

Use an **actual published external link of the same placement type**. Inspect the final `<a>` element, not the form, CMS defaults, or a third-party claim.

Classification rules:

- `rel` absent or empty -> `Dofollow`
- `rel` contains only non-ranking/safety tokens such as `external`, `noopener`, `noreferrer` -> `Dofollow`
- `rel` contains any of `ugc`, `nofollow`, `sponsored` -> `Nofollow`
- raw final HTML cannot be directly verified -> `未确认`

Record the raw `rel` string and sample/evidence URL in evidence storage.

Never infer WordPress comments are Nofollow, or a Web 2.0 network is Dofollow, without inspecting the actual link.

### 6. Fetch Ahrefs DR from the project API

Ahrefs is the only DR source.

For one-off checks use:

`GET https://backlink-metrics-api.vercel.app/api/dr?domain=<canonical_domain>`

For normal batches, deduplicate domains first and call:

`POST https://backlink-metrics-api.vercel.app/api/dr/batch`

with:

```json
{
  "domains": ["example.com", "https://www.github.com/openai"]
}
```

Batch rules:

- one batch HTTP request accepts at most **20 unique normalized domains**
- split a larger 100–1000-candidate run into sequential chunks of at most 20 unique domains
- do not send one long request containing the entire run
- the runtime paces Ahrefs requests conservatively and performs only bounded retries for temporary failures
- one failed domain must not invalidate the other results in that batch
- reuse one current DR observation for multiple placements on the same canonical domain

DR evidence rules:

- successful numeric `dr` -> record that value
- request/provider failure -> `DR = 未确认`
- result status `UNKNOWN` -> `DR = 未确认`
- never substitute Semrush Authority Score or third-party cached DR
- record `source=Ahrefs` and `checked_at` from the response in evidence

A legitimate numeric DR of `0` is allowed only when the API successfully returns a numeric zero. Missing, invalid, failed, or throttled DR must never be converted to zero.

### 7. Collect traffic evidence only when it helps the decision

Traffic is optional supporting evidence, not a mandatory lookup for every candidate. Follow [references/traffic-evidence.md](references/traffic-evidence.md).

Current strategy:

1. **Do not query a traffic provider by default for every domain.** First collect the cheaper/current facts already needed for screening.
2. **Crawlora numeric total-monthly-visits estimate** — use the project adapter selectively when a concrete traffic estimate materially helps an important, ambiguous, or higher-priority decision: `GET https://backlink-metrics-api.vercel.app/api/traffic?domain=<canonical_domain>`.
3. **Manual secondary checks** — traffic.cv and Ahrefs Traffic Checker may be used for important/conflicting cases when the additional evidence justifies manual effort.
4. **CrUX is optional future evidence.** It is not a current MVP dependency or blocker. If implemented later, its rank must remain `popularity_rank` evidence and must never be stored as monthly visits.

Crawlora runtime rules:

- canonical metric source = positive numeric `data.Engagments.Visits`
- period = `Engagments.Year` + `Engagments.Month`
- preserve `provider_snapshot_date` from `SnapshotDate` when available
- `EstimatedMonthlyVisits` is **not** used as the canonical current monthly-visits source; live validation found stale historical zero entries while current `Engagments.Visits` was strongly positive
- Crawlora raw `Visits=0` -> normalized `value=null`, retain `raw_value=0`, `traffic_status=UNKNOWN`; live validation proved a nonexistent domain can return HTTP 200/OK with `Visits=0`
- missing/malformed Visits -> `UNKNOWN`
- timeout/network failure -> `LOOKUP_FAILED`
- provider auth/rate-limit/5xx/malformed-provider failure -> `PROVIDER_ERROR`
- the current Crawlora adapter does not derive `CONFIRMED_ZERO` from raw zero
- default upstream timeout is bounded at 20 seconds

General traffic rules:

- Keep `organic_search_traffic_estimate`, `total_monthly_visits_estimate`, and any future `popularity_rank` observation separate.
- The compact visible field is named `月访问量`, not `月流量`. It is populated **only** by a numeric `total_monthly_visits_estimate`; otherwise use `未确认`.
- Any future CrUX rank never goes into `月访问量`.
- Ahrefs Traffic Checker organic traffic never goes into `月访问量`; it remains a separate evidence observation.
- no coverage from any provider is not zero
- each provider observation keeps its own provider status; cross-provider disagreement is recorded separately as aggregate `traffic_review_status=CONFLICT` or `NEEDS_REVIEW`
- traffic status by itself never produces `F`

Cache/reuse traffic evidence by provider + metric type + domain/origin + period when appropriate. Do not repeat an unchanged monthly lookup merely because another placement on the same domain is screened.

### 8. Fetch domain age from the project API

Use the production domain-age endpoint for the canonical domain:

`GET https://backlink-metrics-api.vercel.app/api/domain-age?domain=<canonical_domain>`

The runtime is RDAP-first and may attempt WHOIS only as a fallback. Screening should use the normalized response rather than implementing its own registration-date heuristics.

Domain-age evidence rules:

- `status=CONFIRMED` with a usable `registration_date` -> record the exact registration date, returned `domain_age_years`, `source`, and `checked_at`; retain `expiration_date` when present
- any non-confirmed result (`UNKNOWN`, `LOOKUP_FAILED`, or `PROVIDER_ERROR`) -> `域龄 = 未确认`
- never turn a missing/failed registration date into `0`
- never substitute Wayback first-seen dates, copyright years, search snippets, or SEO-tool age for authoritative registration evidence
- reuse one current domain-age observation across placements on the same canonical domain when appropriate

Do not treat the age of a root platform domain as the age of a newly created user page/subdomain.

### 9. Assign rating

Apply [references/verification-and-rating.md](references/verification-and-rating.md).

Important:

- A/B/C/D are quality/priority grades for publishable opportunities.
- F is only a verified hard rejection, not a synonym for low quality.
- Traffic is supporting evidence, not a black-box score and not an automatic threshold.
- Traffic evidence is considered **when available**; unknown traffic does not lower a rating by itself.
- Strong real-user/traffic evidence can support higher priority, including for credible Nofollow placements with referral/brand value.
- DR/traffic contradictions trigger quality review; they do not automatically produce F.
- Low DR, Nofollow, paid access, registration friction, or low/zero traffic do not independently justify F.

### 10. Build the database record

Use the visible schema in [references/persistence-schema.md](references/persistence-schema.md).

For an `F` record, keep the visible row minimal: at minimum `URL`, `评级=F`, and `状态=淘汰`; store the hard-rejection reason, evidence, and verification date in evidence storage. Do not waste time filling every metric after a hard rejection is proven.

For A/B/C/D, fill every field that has verified data and use `未确认` where a required fact remains unresolved.

### 11. Persist to Feishu or prepare a fallback record

The production persistence target is Feishu/Lark Base through the protected BacklinkOS persistence API.

- Upsert the main record by exact `placement_key` and evidence rows by exact `evidence_key`.
- A successful write must return an explicit `created` or `updated` action plus a Feishu record ID.
- Repeating the same logical placement must update the existing record rather than create a duplicate.
- If the Feishu integration is temporarily unavailable in the current runtime, produce an import-ready structured main record plus evidence records and mark persistence as pending.
- Never say “已写入飞书” unless the write call actually succeeded.

**Feishu/Lark automatic persistence is implemented and production-validated.** Live verification on 2026-08-16 created one main record and one evidence record, then updated those same record IDs on the second write.

The persistence adapter remains intentionally replaceable; see [references/persistence-schema.md](references/persistence-schema.md).

## Hard rejection (`F`)

Use `F` only when direct evidence establishes that the opportunity is not legitimately executable, for example:

- domain/site is dead or expired
- publishing feature/entry has been removed or permanently closed
- ordinary users cannot publish the intended placement
- the intended placement cannot produce an external link after actual verification
- the site is confirmed malicious/phishing or otherwise unsuitable to interact with

Do **not** use `F` merely because:

- DR is low
- traffic is low, zero, unknown, not covered, or provider-failed
- the link is Nofollow
- registration is required
- the placement is paid
- the site is in an unrelated industry
- your current tool cannot access the page

## Evidence standard

Every decisive fact should be traceable. Keep, when applicable:

- original candidate/source URL
- normalized domain
- publishing entry URL
- actual published sample URL
- raw `<a rel>` value
- registration/pricing evidence URL
- Ahrefs DR value and `checked_at`
- domain-age API registration date, expiration date when present, source, status, `checked_at`, and derived `域龄`
- traffic observation(s): metric type, normalized value, optional raw provider value, source, provider status, period, provider snapshot date when available, checked_at, confidence, origin/domain, raw field used, and notes
- aggregate traffic review status/conflict state when multiple observations exist
- optional CrUX coverage/rank only if CrUX is actually queried in a future implementation
- hard-rejection reason
- verification date
- concise notes about uncertainty, provider conflicts, or access blocks

## Completion check

Before completing a screening task, verify:

- [ ] each placement was independently checked
- [ ] domain-wide metric calls were normalized/deduplicated before repeated provider work
- [ ] no missing data was turned into zero
- [ ] current publishability has evidence or is explicitly `未确认`
- [ ] link attribute comes from final same-type HTML or is `未确认`
- [ ] DR comes only from the project Ahrefs API
- [ ] normal multi-domain DR work uses bounded `/api/dr/batch` chunks rather than one unbounded request
- [ ] traffic metrics preserve their type/source/provider-status and are not mixed
- [ ] `月访问量` contains only a total-monthly-visits estimate or `未确认`
- [ ] Crawlora uses only positive current `Engagments.Visits` as a confirmed numeric value
- [ ] Crawlora raw zero remains `UNKNOWN` and is never written as `月访问量=0`
- [ ] provider errors/timeouts are not converted to zero or F
- [ ] observation status is separate from aggregate conflict/review status
- [ ] any future popularity rank is never converted into monthly visits
- [ ] domain age comes from the project domain-age API; only `CONFIRMED` becomes a numeric `域龄`
- [ ] non-confirmed domain-age results remain `未确认`
- [ ] no relevance field was added
- [ ] F is supported by a hard-rejection reason
- [ ] persistence success is not claimed without confirmation
- [ ] when Feishu persistence is used, the response confirms `created`/`updated` and returns record IDs

## Additional resources

- Verification and rating rules: [references/verification-and-rating.md](references/verification-and-rating.md)
- Traffic evidence architecture and provider contracts: [references/traffic-evidence.md](references/traffic-evidence.md)
- Visible/evidence schemas and Feishu adapter contract: [references/persistence-schema.md](references/persistence-schema.md)
- Behavioral regression scenarios: [references/test-cases.md](references/test-cases.md)
- Executable metric-adapter tests live in the `pyxm1618/backlink-metrics-api` repository.
- Crawlora live validation report lives in `backlink-metrics-api/docs/crawlora-live-validation-2026-08-15.md`.
- Domain-age production validation report lives in `backlink-metrics-api/docs/domain-age-live-validation-2026-08-16.md`.
