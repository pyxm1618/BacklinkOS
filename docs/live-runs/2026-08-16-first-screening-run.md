# First live `screening-backlinks` run — 2026-08-16

## Purpose

Run the current production screening workflow against a small real batch before scaling to hundreds of candidates. The batch comes from the previously supplied `Quick_I_Ching_外链管理_飞书版.xlsx`, specifically the surviving candidates whose provenance was the earlier `14站点CSV`.

Old spreadsheet judgments were treated only as historical context. They were not reused as current facts.

## Batch

1. `https://ukadslist.com/`
2. `https://blogstival.com/`
3. `https://blogzag.com/`
4. `https://collectblogs.com/`
5. `https://designertoblog.com/`
6. `https://getblogs.net/`
7. `https://look4blog.com/`
8. `https://mpeblog.com/`
9. `https://mybloglicious.com/`
10. `https://post-blogs.com/`
11. `https://widblog.com/`

## Fresh Ahrefs DR

All values were read from the production BacklinkOS Ahrefs adapter on 2026-08-16.

| Domain | DR |
|---|---:|
| ukadslist.com | 66 |
| blogstival.com | 46 |
| blogzag.com | 51 |
| collectblogs.com | 48 |
| designertoblog.com | 50 |
| getblogs.net | 48 |
| look4blog.com | 47 |
| mpeblog.com | 53 |
| mybloglicious.com | 45 |
| post-blogs.com | 50 |
| widblog.com | 52 |

No non-Ahrefs authority metric was substituted into DR.

## Selective current total-monthly-visits evidence

Crawlora was deliberately not called for every domain. It was used where numeric traffic helped investigate high-DR / weak-quality contradictions.

| Domain | 2026-07 total monthly visits estimate | Normalized status |
|---|---:|---|
| ukadslist.com | 2,742 | CONFIRMED |
| blogzag.com | 374 | CONFIRMED |
| designertoblog.com | 3,487 | CONFIRMED |
| mpeblog.com | 13,012 | CONFIRMED |
| post-blogs.com | 576 | CONFIRMED |
| widblog.com | 3,397 | CONFIRMED |
| mybloglicious.com | blank | UNKNOWN (`raw_value=0`) |

The MyBloglicious raw zero was correctly preserved as UNKNOWN and was not written as visible traffic zero.

## Current placement verification

### Verified current Blog/Post external-link capability

The following platforms had a currently accessible published user post where the rendered page exposed at least one clickable external link, plus a current start/signup path where checked:

- `blogzag.com`
- `collectblogs.com`
- `look4blog.com`
- `mpeblog.com`
- `mybloglicious.com`
- `post-blogs.com`
- `widblog.com`

For these placements, Blog/Post external-link publishability is established. The current runtime still cannot inspect the raw final `<a rel>` attribute, so `链接属性=未确认`; no Dofollow/Nofollow value is inferred from the shared template or from the old spreadsheet.

### Not yet established strongly enough for a grade

- `ukadslist.com` — current root page claims free posting, no signup, and an external URL field, but the page also states that the site was recovered with Wayback Downloader; the actual post-ad route could not be fetched in this runtime. Do not treat the restored landing-page claim as proof that the current publishing route works.
- `blogstival.com` — current signup and recent user content exist, but this run did not obtain a currently inspectable published external link.
- `designertoblog.com` — current user content and external-looking URL text exist, but this run did not obtain a currently inspectable rendered external link.
- `getblogs.net` — current login/signup and recent user content exist, but this run did not obtain a currently inspectable published external link.

These four candidates remain partially verified and must not be forced into C/D/F just to fill the rating column.

## First-batch ratings

These are placement-quality grades, not project-relevance grades.

| Domain | Result | Reason |
|---|---|---|
| ukadslist.com | pending / no grade | current posting route not established |
| blogstival.com | pending / no grade | external-link publishability not established in this run |
| blogzag.com | D | external links are executable, but current pages show a clear low-quality/spam footprint and DR 51 conflicts with only ~374 estimated monthly visits |
| collectblogs.com | D | executable external-link posts plus obvious SEO/link-placement footprint and low-quality related content |
| designertoblog.com | pending / no grade | external-link publishability not established strongly enough |
| getblogs.net | pending / no grade | external-link publishability not established strongly enough |
| look4blog.com | D | executable external-link post, obvious low-quality/spam footprint and poor placement quality |
| mpeblog.com | D | executable external-link posts, current casino/SEO/link-farm style content and weak placement quality despite DR 53 |
| mybloglicious.com | C | executable external-link post and DR 45, but link attribute is unknown and platform quality is ordinary/SEO-heavy; Crawlora raw zero remains UNKNOWN rather than a negative traffic fact |
| post-blogs.com | D | executable external-link post, obvious spam footprint and DR 50 versus only ~576 estimated monthly visits |
| widblog.com | D | executable external-link post, spam/adult/suspended-blog footprint and DR 52 versus only ~3,397 estimated monthly visits |

No candidate was assigned F. None had a directly verified hard rejection such as a dead domain, permanently closed publishing route, proven inability to create an external link, or confirmed malicious/unsafe site.

No candidate was assigned A or B because this run did not verify a high-quality placement with a confirmed Dofollow external link and sufficiently strong overall platform quality.

## Domain age handling

The live run found third-party WHOIS-style registration dates for many domains, but the Skill requires authoritative RDAP/registrar evidence where available. To avoid weakening the evidence standard, the first-batch final records should keep `域龄=未确认` until authoritative registration evidence is collected. This exposes a practical gap: deterministic domain-age/RDAP lookup is not yet available through the project runtime.

## What behaved correctly

1. The old 14-site spreadsheet was used as candidate input, not as truth.
2. Every site was checked independently despite the blog platforms sharing templates.
3. Topical relevance was not used.
4. DR came only from the project Ahrefs adapter.
5. Crawlora was selective rather than called for all 11 domains.
6. High DR did not automatically create A/B ratings.
7. Low traffic did not create F.
8. Missing/ambiguous traffic did not become zero.
9. The old `Dofollow（大概率）` values were not reused; raw `rel` remains unconfirmed where it could not be inspected.
10. Tool/cache failures were treated as unknown rather than hard rejection.

## Problems exposed by the live run

### 1. Rating eligibility was not explicit enough

Before this run the documents did not say clearly enough what to do when signup/content exists but external-link publishability is still unresolved. Forcing C/D would turn uncertainty into a quality judgment.

The rating rules were corrected during this run: A/B/C/D require established current external-link publishability; otherwise preserve evidence and leave `评级` blank/pending. A regression scenario was added.

### 2. Current ChatGPT runtime cannot inspect raw `rel`

The web retrieval tool can expose rendered clickable links on some pages, but does not expose the raw final `<a rel>` attribute. Therefore a large share of real candidates will correctly remain `链接属性=未确认` unless a dedicated safe HTML/link-inspection capability is added.

This is an execution-capability gap, not a reason to guess Dofollow/Nofollow.

### 3. Current ChatGPT runtime cannot invoke the POST batch/write APIs

The backend exposes:

- `POST /api/dr/batch`
- `POST /api/feishu/persist`

The Vercel tool available in this ChatGPT session fetches URLs with GET only. Consequently this live run had to use the single-domain DR GET endpoint, and it cannot honestly claim to have persisted the screening records to Feishu. A GET request to `/api/feishu/persist` correctly returns HTTP 405.

The Feishu adapter itself was previously production-validated with real create-then-update behavior, but the current Skill-hosting runtime lacks a callable POST bridge. Until that bridge exists, the correct Skill behavior is persistence pending / import-ready output.

### 4. Domain-age evidence is not deterministic in the current runtime

The Skill asks for authoritative RDAP/registrar evidence, but the current project API has no domain-age endpoint. Manual web lookup is inconsistent and often produces lower-tier WHOIS mirrors. This should remain unknown rather than silently weakening the evidence hierarchy.

### 5. Placement identity needs clearer pre-auth guidance

`placement_key = canonical_domain + placement_type + publish_entry_url` is sound once the publishing entry is known. For account-based platforms, however, an unauthenticated run may only know the public signup/start URL while the authenticated editor URL appears later. The rules should specify a stable pre-auth identity so a later login does not accidentally create a second record for the same placement.

## Overall judgment

The evidence and rating principles worked substantially as intended and prevented several false conclusions that the old spreadsheet would have encouraged. The first live run also proved that the workflow is not yet fully end-to-end from this ChatGPT runtime: raw link-attribute inspection, authoritative domain-age lookup, and a callable POST bridge for batch DR / Feishu persistence remain operational gaps.

Do not scale to hundreds of candidates until those execution gaps are deliberately accepted or fixed.
