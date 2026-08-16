# Placement Inspector and Rating Recovery Design

Date: 2026-08-16

## Problem

The first live screening run proved that the current screening workflow can collect DR, traffic, domain age and persistence evidence, but cannot reliably answer the product's most important question: whether a backlink placement is worth doing.

The root causes are:

1. the current ChatGPT runtime cannot inspect raw final `<a rel>` attributes, so Dofollow/Nofollow often remains unknown;
2. A/B/C/D currently relies on qualitative language such as "spam footprint", "ordinary" and "poor placement quality", allowing inconsistent LLM judgments;
3. highly similar sites are evaluated independently without a platform/network-family layer, which can produce unjustified C/D divergence;
4. domain-wide DR/traffic can describe the root platform while the actual backlink is published on a user subdomain or specific page;
5. publishability, technical SEO properties, and action priority are compressed into one rating.

The fix is to make placement facts deterministic first, then derive action priority from those facts.

## Scope

This design applies only to the `screening-backlinks` workflow. Discovery remains out of scope.

The first validation target is `blogstival.com`. Because several candidates appear to use the same platform/template family, the initial Gold Set will not manually validate all eleven sites. Instead:

- fully validate one representative site (`blogstival`);
- spot-check 2–3 sibling sites for technical consistency;
- expand the sample only if material differences are observed.

## Considered approaches

### A. Continue using ChatGPT/web retrieval to infer link attributes

Rejected. The runtime does not expose raw final link attributes reliably. This preserves the current failure mode.

### B. Add a deterministic server-side Placement Inspector

Recommended. Fetch the public published page, parse the final HTML, locate the expected external link, and return exact technical facts including raw `rel`, meta robots, X-Robots-Tag, canonical URL and final hostname.

Advantages:

- deterministic and testable;
- inexpensive for server-rendered Web 2.0/blog pages;
- immediately usable after publication;
- removes Dofollow/Nofollow judgment from the LLM.

Limitation: purely client-rendered pages may require a browser fallback.

### C. Use a full headless browser for every candidate

Not recommended as the default. It is heavier, slower and operationally more complex. Keep it as a fallback only when static HTML inspection cannot find the rendered link or SEO metadata.

## Architecture

### 1. Placement Inspector API

Add a protected BacklinkOS API endpoint conceptually equivalent to:

`GET /api/placement/inspect?url=<published_url>&target=<expected_target_url>`

Inputs:

- `url`: exact public published placement URL;
- `target`: expected outbound URL or target hostname to identify the backlink precisely.

The inspector follows normal public HTTP redirects and returns normalized evidence.

### 2. Security boundary

Because the endpoint fetches user-supplied URLs, it must be SSRF-safe:

- allow only `http:` and `https:`;
- reject localhost, loopback, link-local and private-network destinations;
- reject literal private IPs;
- resolve DNS and reject private/reserved results before fetching;
- apply strict redirect limits and re-validate every redirect destination;
- cap response size;
- use bounded timeouts;
- do not forward caller cookies, authorization headers or arbitrary request headers.

### 3. Inspector output

The canonical result should include at least:

```json
{
  "status": "CONFIRMED | TARGET_NOT_FOUND | UNKNOWN | LOOKUP_FAILED | PROVIDER_ERROR",
  "requested_url": "...",
  "final_url": "...",
  "final_hostname": "...",
  "http_status": 200,
  "target_url": "...",
  "target_found": true,
  "links": [
    {
      "href": "https://target.example/",
      "raw_rel": "ugc nofollow",
      "rel_tokens": ["ugc", "nofollow"],
      "link_attribute": "Nofollow",
      "anchor_text": "..."
    }
  ],
  "meta_robots": "index,follow",
  "x_robots_tag": null,
  "canonical_url": "...",
  "indexability": "INDEXABLE | NOINDEX | UNKNOWN",
  "checked_at": "..."
}
```

Link classification is deterministic:

- absent/empty `rel` => Dofollow;
- only `external`, `noopener`, `noreferrer` => Dofollow;
- any `nofollow`, `ugc`, or `sponsored` token => Nofollow;
- target link not inspectable => Unknown, never guessed.

### 4. Immediate verification semantics

As soon as the post is publicly reachable, the Placement Inspector can immediately answer:

- whether the outbound link exists in final HTML;
- the raw `rel` value;
- Dofollow/Nofollow classification;
- final placement hostname/subdomain;
- canonical URL;
- noindex/indexability directives visible in HTTP/HTML.

This does **not** prove Google has indexed the page. Google indexation is a separate later observation and must not block immediate backlink technical verification.

### 5. Browser fallback

Do not make browser automation the default production dependency.

If static HTML returns a successful page but the expected target is absent while the page is known to be client-rendered, mark the result `NEEDS_BROWSER_REVIEW`/`UNKNOWN` initially. A future browser-rendered inspector may be added as a fallback after the static implementation is validated on real targets.

## Platform-family layer

Add descriptive evidence for `platform_family` / `network_cluster`.

The purpose is not to infer placement facts across domains. Registration, publishability and `rel` still require per-site verification where material.

The family layer is used to:

- avoid pretending near-identical platforms are unrelated quality experiences;
- detect unjustified rating divergence;
- reuse platform-level qualitative observations cautiously;
- trigger sibling spot-checks instead of manually validating every clone.

Family detection may initially be evidence-assisted/manual using shared homepage copy, signup structure, template fingerprints and user-subdomain patterns. It must not claim common ownership without evidence.

## Rating redesign

Do not let A/B/C/D/F carry three different meanings.

Expose three decision layers:

### Layer 1 — Publishability

- `YES`
- `NO`
- `UNKNOWN`

### Layer 2 — SEO placement facts

At minimum:

- `link_attribute`: Dofollow / Nofollow / Unknown;
- `indexability`: Indexable / Noindex / Unknown;
- exact published hostname/subdomain;
- link location when deterministically obtainable;
- canonical behavior.

### Layer 3 — Action recommendation

Primary user-facing decision:

- `DO` — worth doing now;
- `LOW_PRIORITY` — executable, but weak enough to defer;
- `REVIEW` — decisive facts unresolved/conflicting;
- `SKIP` — objectively non-executable or not worth the execution cost under explicit rules.

A/B/C/D may remain only as optional secondary labels after deterministic recommendation rules exist. F remains a hard-rejection cache, not a synonym for low quality.

## Recommendation rules v1

Do not introduce a black-box weighted SEO score. Use transparent gates.

1. If current external-link publishability is not confirmed => `REVIEW`.
2. If placement cannot create an external link, is dead, or is unsafe => `SKIP` / F with evidence.
3. If the page is `NOINDEX` => generally `LOW_PRIORITY` unless there is strong non-SEO referral/brand value.
4. If Dofollow + Indexable + executable => normally `DO` unless explicit severe platform/placement negatives are documented.
5. If Nofollow + Indexable + executable => `DO` or `LOW_PRIORITY` depending on execution cost and credible referral/platform value; Nofollow alone is never an automatic rejection.
6. DR, age and traffic are supporting context, not substitutes for placement facts.
7. Root-domain DR/traffic must be labelled `platform_domain_metric` when the backlink publishes on a user subdomain/page; the UI must not imply the user page itself has the same authority.
8. Similar sibling sites must not receive different recommendations unless the evidence identifies a material difference.

## Gold Set and regression strategy

### Phase 1

Use `blogstival` as the complete representative sample:

1. register/login;
2. create a minimal test post;
3. insert one known external target URL;
4. publish;
5. run Placement Inspector against the public post;
6. capture exact `rel`, indexability, final host/subdomain and canonical behavior;
7. assign the recommendation from deterministic rules.

### Phase 2

Spot-check 2–3 sibling domains that appear to share the same platform family. Verify only the material technical fields needed to determine whether family reuse is justified.

### Regression fixtures

Add executable tests using stored HTML fixtures for:

- absent `rel` => Dofollow;
- `noopener noreferrer` => Dofollow;
- `ugc`, `nofollow`, `sponsored` => Nofollow;
- multiple matching target links;
- no target link;
- relative/absolute canonical;
- meta robots noindex;
- X-Robots-Tag noindex;
- redirect handling;
- SSRF/private-host rejection;
- oversized/timeout failure semantics.

The real `blogstival` published page becomes a manually revalidatable live fixture, not a unit test dependency.

## Persistence changes

Add evidence fields for:

- `published_url`;
- `final_hostname`;
- `raw_rel`;
- `link_attribute`;
- `meta_robots`;
- `x_robots_tag`;
- `canonical_url`;
- `indexability`;
- `platform_family`;
- `recommendation`;
- `recommendation_reason`.

Existing DR, traffic, age and Feishu infrastructure remains. Do not spend more engineering effort on WHOIS/traffic before this placement-verification loop is working.

## Success criteria

The recovery is successful when a newly published `blogstival` test post can be given to BacklinkOS and the system can, without LLM guessing:

1. find the exact outbound test link;
2. return raw `rel` and Dofollow/Nofollow immediately;
3. report indexability directives;
4. identify the actual published hostname/subdomain;
5. produce a transparent `DO / LOW_PRIORITY / REVIEW / SKIP` recommendation whose reason is traceable to evidence;
6. avoid inconsistent recommendations across near-identical sibling sites unless a specific difference is documented.
