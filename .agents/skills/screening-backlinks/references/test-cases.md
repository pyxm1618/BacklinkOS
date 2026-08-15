# Skill Regression Scenarios

These are **non-executable behavioral regression scenarios** for reviewing changes to `screening-backlinks`.

They are not Jest/Vitest/integration/API tests and must not be reported as automated tests. Executable Crawlora adapter tests exist separately at `tests/crawlora-traffic.test.ts`; they mock the upstream provider, consume no credits, and are run before the production build.

The expected behavior below is the contract; exact wording may vary.

## Core screening scenarios

### Case 1 — Same network is not evidence

Prompt:

> Check these five Web 2.0 sites. They look identical, so classify registration and Dofollow in one batch.

Expected:

- verifies each site independently
- does not infer registration/pricing/rel from shared design/CMS/network
- records `未确认` when a site's own evidence is unavailable

### Case 2 — Historical competitor backlink

Prompt:

> Ahrefs shows my competitor got a backlink from this 2022 comment page. Add it as publishable.

Expected:

- treats the historical backlink only as discovery evidence
- verifies the current comment/profile/post path before marking publishable
- if comments are now closed, records placement-specific F only with direct evidence

### Case 3 — Access blocked

Prompt:

> The crawler gets 403 on this candidate. Reject it.

Expected:

- does not assign F from crawler/tool failure alone
- uses `未确认` unless separate evidence proves a hard rejection

### Case 4 — Missing traffic must not become zero

Prompt:

> Traffic lookup returned nothing. Put 0 so we can rate it.

Expected:

- preserves an explicit unknown/error/no-coverage observation status
- does not convert missing coverage to zero
- does not assign F from missing traffic

### Case 5 — DR source discipline

Prompt:

> Ahrefs API is temporarily unavailable, but Semrush Authority Score is 72. Put DR 72.

Expected:

- refuses to substitute Authority Score for DR
- records DR as `未确认`

### Case 6 — Same domain, different placements

Prompt:

> The profile link is Dofollow and the comment link is Nofollow on the same domain. Keep one domain row.

Expected:

- preserves separate placement identities
- does not flatten the domain into one link-attribute classification

### Case 7 — `rel` with safety tokens

Observed HTML:

```html
<a href="https://example.com" rel="noopener noreferrer">Example</a>
```

Expected: `Dofollow`.

Observed HTML:

```html
<a href="https://example.com" rel="ugc noopener">Example</a>
```

Expected: `Nofollow`.

### Case 8 — F is not low quality

Prompt:

> This site is DR 7 and Nofollow. Mark F.

Expected:

- does not mark F solely for low DR/Nofollow
- uses C/D as appropriate if still legitimately publishable

### Case 9 — Relevance must not return

Prompt:

> This backlink is unrelated to my I Ching site, so lower the relevance score.

Expected:

- explains that the shared backlink database has no relevance field
- does not alter rating based on topical relevance

### Case 10 — Feishu unavailable

Prompt:

> Save these records to Feishu, but no working Feishu connector/API is available.

Expected:

- produces import-ready main/evidence records
- marks persistence pending
- does not claim the records were written

### Case 11 — Hard rejection minimal work

Prompt:

> The domain is conclusively expired and has no live site. Continue finding DR, age, rel, and pricing for completeness.

Expected:

- creates a domain-wide F record with reason/evidence/date
- stops unnecessary metric research
- leaves nonessential fields blank or `未确认`

### Case 12 — Candidate from another industry

Prompt:

> This is a sports site and my current product is finance. Should it be downgraded for relevance?

Expected:

- does not use relevance
- records the site's industry only
- evaluates the opportunity using publishability, link evidence, DR, age, platform quality, and available traffic evidence

## Traffic regression scenarios

### Case 13 — CrUX has popularity data

Observation:

> `https://www.example.com` appears in the latest CrUX release with rank `100000`.

Expected:

- stores `traffic_metric_type=popularity_rank`
- stores exact origin and CrUX release month
- stores rank/bucket as CrUX popularity evidence
- does **not** write `月访问量=100000`
- does not claim a specific monthly visit count from CrUX

### Case 14 — CrUX has no coverage

Observation:

> The exact publishing origin has no row in the latest CrUX release.

Expected:

- observation stores `traffic_status=NOT_COVERED`
- stores `coverage_status=NOT_COVERED`
- keeps `traffic_value=null`
- does not set traffic to zero
- does not assign F

### Case 15 — Provider timeout / 403 / API error

Observation:

> Numeric provider request times out, returns 429, or returns an upstream/provider error.

Expected:

- timeout/network -> observation `LOOKUP_FAILED`
- rate-limit/upstream/provider failure -> observation `PROVIDER_ERROR`
- keeps numeric traffic unknown
- does not write zero
- does not assign F

### Case 16 — Crawlora raw zero

Observation:

> Crawlora returns HTTP 200 / `msg=OK` / `data.Engagments.Visits="0"`.

Expected:

- stores `traffic_metric_type=total_monthly_visits_estimate`
- normalized `traffic_value=null`
- preserves raw evidence as `traffic_raw_value=0`
- stores observation `traffic_status=UNKNOWN`
- preserves provider period/source/SnapshotDate/checked_at when present
- does **not** write `月访问量=0`
- does not assign F from zero alone

Reason:

Own-key live validation proved a deliberately nonexistent `.com` domain can return HTTP 200/OK with raw `Visits=0`. Therefore current Crawlora raw zero is semantically ambiguous and must not become `CONFIRMED_ZERO`.

### Case 17 — Numeric monthly visits is available

Observation:

> Crawlora returns positive current `Engagments.Visits=52300`, Month/Year for the current provider period, and a SnapshotDate.

Expected:

- visible `月访问量=52300`
- evidence stores `traffic_metric_type=total_monthly_visits_estimate`
- evidence stores source, provider period, SnapshotDate, checked_at, confidence
- `raw_field_used=data.Engagments.Visits`
- does not claim first-party analytics

### Case 18 — Organic traffic and total visits both exist

Observation:

> Crawlora returns 52,300 total monthly visits; Ahrefs manual check returns 12,000 organic-search traffic.

Expected:

- stores two separate traffic observations
- visible `月访问量=52300`
- organic value stays `organic_search_traffic_estimate`
- neither metric overwrites the other

### Case 19 — Traffic providers conflict materially

Observation:

> Two current sources both return confirmed total-monthly-visits estimates but differ by an order of magnitude.

Expected:

- preserves both observations
- both observations retain their own provider statuses, e.g. `CONFIRMED`
- aggregate `traffic_review_status=CONFLICT` (or `NEEDS_REVIEW` when conflict is not yet established)
- optional `traffic_conflict=true`
- does **not** rewrite either observation's status to `CONFLICT`
- does not silently choose the larger, smaller, or preferred-looking number
- visible `月访问量` remains `未确认` unless a documented precedence rule resolves the conflict

### Case 20 — High DR with weak traffic evidence

Observation:

> DR is high, CrUX is not covered, numeric traffic is unknown, pages look weak, and outbound-link patterns appear abnormal.

Expected:

- triggers quality/spam review
- does not treat CrUX no coverage as zero
- does not automatically assign F
- assigns A/B/C/D only after reviewing broader evidence

### Case 21 — High traffic but Nofollow

Observation:

> A credible platform is Nofollow but has strong CrUX popularity and/or strong total-monthly-visits evidence.

Expected:

- keeps `Nofollow`
- allows referral/brand exposure to count as positive evidence
- does not automatically classify it as low-value junk solely because it is Nofollow
- still considers placement quality and other facts

### Case 22 — Traffic unknown, other evidence strong

Observation:

> Publishability is verified, Dofollow is verified, DR/age/platform quality are strong, but traffic providers have no usable result.

Expected:

- traffic remains unknown
- no downgrade occurs solely because traffic is missing
- candidate may still qualify for A/B if the remaining evidence supports it
- does not assign F

### Case 23 — Crawlora production approval must stay narrow

Prompt:

> Crawlora is production-approved now, so use it as the authoritative traffic source for every candidate and treat zero as real zero.

Expected:

- refuses the broader interpretation
- uses Crawlora only as a selective medium-confidence `total_monthly_visits_estimate` fallback
- does not use it as the 100K-domain bulk-first layer
- positive current `Engagments.Visits` may be `CONFIRMED`
- raw zero remains `UNKNOWN`
- provider disagreements remain reviewable evidence rather than one source becoming truth

### Case 24 — Stale EstimatedMonthlyVisits zero trap

Observation:

> Crawlora returns current `Engagments.Visits="637885711"` for 2026-07, but `EstimatedMonthlyVisits` contains only 2024 month keys whose values are all `0`.

Expected:

- current `Engagments.Visits` remains the canonical current total-visits value
- stores current period and SnapshotDate
- may preserve the `EstimatedMonthlyVisits` shape as raw/schema evidence
- does **not** overwrite current visits with zero
- does **not** create `CONFIRMED_ZERO`
- does not write the stale historical zero into visible `月访问量`

## Traffic invariants

Any future traffic adapter or persistence implementation must preserve these invariants:

1. CrUX popularity rank is never converted into visits.
2. Organic-search traffic is never stored as total monthly visits.
3. Missing/no coverage/provider error is never converted into zero.
4. Crawlora raw zero is `UNKNOWN`, not `CONFIRMED_ZERO`; live validation proved raw zero can occur for a nonexistent domain.
5. A general future provider may use `CONFIRMED_ZERO` only after provider-specific zero semantics establish it is a genuine estimate.
6. Traffic never independently causes F.
7. Conflicting provider observations are retained and keep their provider statuses.
8. Aggregate conflict/review state is separate from provider observation status.
9. Provider month, SnapshotDate when available, and checked-at time are preserved for numeric estimates.
10. CrUX origin preserves scheme/host semantics.
11. Unknown traffic never lowers A/B/C/D by itself.
12. `月访问量` means total-monthly-visits estimate, never organic traffic or CrUX popularity.
13. Crawlora `EstimatedMonthlyVisits` stale zero entries never replace current `Engagments.Visits`.
14. Behavioral regression scenarios and executable adapter tests are distinct and must be reported separately.
