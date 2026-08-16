# Verification and Rating Rules

## Evidence hierarchy

Prefer evidence in this order:

1. first-party current page/form/policy
2. raw final HTML of an actual published same-type external link
3. official metric API operated by the metric provider
4. authoritative RDAP/registrar data
5. documented third-party metric APIs with explicit provenance/failure semantics
6. reputable third-party/manual sources as supporting context

A lower-tier source must not override a contradictory higher-tier source without explicitly recording the conflict.

## Publishability

A placement is currently publishable only when an ordinary user has a reproducible path that can create an external link.

Historical competitor backlinks, search snippets, archive pages, or third-party platform lists are discovery signals only.

Access failure in the current runtime is not proof that a site is unavailable. If 403/CAPTCHA/login/tooling prevents verification, use `未确认` unless separate evidence proves a hard rejection.

## Link attribute

Inspect a final same-type published `<a>` tag.

| Raw `rel` | Classification |
|---|---|
| absent / empty | Dofollow |
| only `external`, `noopener`, `noreferrer` | Dofollow |
| contains `ugc` | Nofollow |
| contains `nofollow` | Nofollow |
| contains `sponsored` | Nofollow |
| cannot inspect raw final HTML | 未确认 |

Store the raw `rel` exactly as observed.

## Ahrefs DR

Canonical source:

`https://backlink-metrics-api.vercel.app/api/dr?domain=<domain>`

Rules:

- accept only a successful response containing numeric `dr`
- keep `checked_at` as evidence
- if the call fails or the payload lacks numeric `dr`, use `未确认`
- never substitute Semrush Authority Score or a third-party cached DR into the DR field

## Traffic evidence

Follow [traffic-evidence.md](traffic-evidence.md).

The system distinguishes:

- `popularity_rank` — CrUX origin-level popularity evidence
- `total_monthly_visits_estimate` — modelled all-channel monthly visits
- `organic_search_traffic_estimate` — modelled organic-search traffic

They are not interchangeable.

Core rules:

- visible `月访问量` contains only `total_monthly_visits_estimate`
- CrUX no coverage -> `NOT_COVERED`, never zero
- provider timeout/transport failure -> `LOOKUP_FAILED`
- provider/rate-limit/upstream failure -> `PROVIDER_ERROR`
- `CONFIRMED_ZERO` is valid only when that provider's zero semantics are documented or live-validated as a genuine zero estimate
- Crawlora raw `Visits=0` -> `UNKNOWN`, because own-key live validation proved a nonexistent domain can return HTTP 200/OK with raw zero
- each traffic observation keeps its own provider status
- multiple providers can coexist as separate observations
- material disagreement is an aggregate review state (`traffic_review_status=CONFLICT` or `NEEDS_REVIEW`), not an observation/provider status
- traffic alone never causes `F`

CrUX popularity is strong evidence only for the claim that Google observed enough eligible Chrome navigations for the exact origin to include it in a coarse popularity bucket. It is not a visit count.

Crawlora's SimilarWeb public-surface endpoint is `PRODUCTION_APPROVED` only as a **selective, medium-confidence single-domain fallback** for positive current `data.Engagments.Visits` values. The live validation matrix covered very large, medium, small, nonexistent, normalization, timeout, and secondary-comparison cases. It is not an authoritative traffic source and not the 100K-domain bulk-first layer.

Crawlora-specific rules:

- positive current `Engagments.Visits` -> `CONFIRMED`
- preserve `Engagments.Month` + `Engagments.Year` as the provider period
- preserve `SnapshotDate` when available
- do not use stale `EstimatedMonthlyVisits` zero entries as the current value
- raw `Visits=0` -> `UNKNOWN`, not `CONFIRMED_ZERO`
- missing/malformed Visits -> `UNKNOWN`

traffic.cv and Ahrefs Traffic Checker remain manual secondary evidence unless a stable official production API contract is later confirmed.

## Domain age

Prefer authoritative RDAP or registrar creation/registration events.

Store:

- exact registration date
- source
- verification date
- derived age

If no reliable registration event exists, use `未确认`.

## A/B/C/D/F policy

The rating is evidence-based priority classification, not a weighted score. Do not calculate formulas such as `DR * weight + traffic * weight`.

Traffic modifies confidence/priority only **when usable evidence exists**. Unknown traffic is absence of evidence, not negative evidence.

### Eligibility gate before A/B/C/D

A/B/C/D are grades for opportunities whose **current external-link publishability has been established**. Seeing an active signup page, an editor, or recent user content is not enough by itself if the current run still cannot establish that the intended placement can actually produce an external link.

If a decisive publishability fact is blocked, unavailable, or still unverified:

- preserve the verified partial evidence
- keep the unresolved fact as `未确认`
- leave `评级` blank/pending rather than forcing C or D merely to fill the table
- do not use F unless direct evidence proves a hard rejection
- resume rating once external-link publishability is established

`C` and `D` are quality grades, not uncertainty buckets.

### A — highest priority

Typical pattern:

- currently reproducible external-link placement
- Dofollow
- strong Ahrefs DR (normally 50+)
- meaningful operating history (normally 3+ years)
- site/platform appears legitimate and usable, without material spam/manipulation red flags
- traffic/popularity evidence, **when available**, is healthy or at least not materially contradictory

Strong traffic evidence is positive, but traffic being unknown does not disqualify or downgrade an otherwise A-quality opportunity by itself.

### B — recommended

Typical cases:

- Dofollow, DR roughly 20–49, established legitimate domain, with traffic evidence **when available** not materially contradicting the rest of the evidence; or
- exceptionally strong/credible high-DR platform with Nofollow plus clear brand/referral value, especially when supported by strong popularity/traffic evidence

Traffic does not need to be known for B. Do not upgrade a weak platform solely because DR or traffic is high.

### C — optional / accumulation

Publishable opportunity with ordinary or incomplete quality signals, for example:

- low DR but legitimate platform
- link attribute `未确认`
- younger domain
- some friction such as approval or account creation
- confirmed low traffic **together with** other weaker quality signals
- multiple material evidence gaps, where traffic may also be unknown but is not itself the downgrade reason

Do **not** classify C solely because traffic is unknown.

Small sites are not automatically bad. C can still be worth doing when execution cost is low.

### D — lowest priority but still publishable

Use when the opportunity remains legitimate and executable but has multiple clear negatives, such as:

- very weak site quality
- obvious spam footprint
- DR/quality/traffic-popularity mismatch
- confirmed very weak traffic combined with other poor-quality evidence
- high execution friction
- poor placement quality

Unknown traffic by itself is not a D signal.

D is not a rejection. Keep it in the asset database so it can be used intentionally or deprioritized.

### Quality review before rating

Do not force a rating when material evidence conflicts.

Examples:

- high DR + no CrUX coverage + very weak pages + abnormal outbound-link patterns
- two confirmed total-monthly-visits observations differ materially
- different traffic metric types are accidentally being compared as if they were the same

In a provider disagreement, keep both observations' own statuses unchanged (for example both may remain `CONFIRMED`) and set the aggregate `traffic_review_status=CONFLICT` or `NEEDS_REVIEW`. Reconcile metric semantics and source freshness before relying on a visible aggregate value.

`NEEDS_REVIEW`/`CONFLICT` are review states, not sixth ratings and never imply `F`.

### F — hard rejection cache

Use only for objectively verified non-executable/unsafe opportunities:

- dead/expired site or domain
- publishing route removed/permanently closed
- ordinary users cannot create the intended placement
- actual verification shows the intended placement cannot contain an external link
- confirmed malicious/phishing/unsafe site

Do not assign F because of low DR, low/zero/unknown traffic, CrUX no coverage, Nofollow, payment, login requirements, industry mismatch, or a temporary tool/provider-access failure.

## F evidence

An F record exists mainly to prevent repeated wasted research. Store at least:

- domain/URL
- whether rejection is domain-wide or placement-specific
- rejection reason
- evidence URL or observation
- verification date

If the rejection is placement-specific, do not automatically reject other placement types on the same domain.
