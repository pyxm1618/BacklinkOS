# Operational Helper Scripts

Scripts in this directory are executable helpers. They do not automatically define BacklinkOS business semantics.

## `screening_crawler.py`

This crawler is currently used by `.github/workflows/screening-crawler.yml` for large-batch **triage**.

It intentionally performs cheap machine checks and emits preliminary buckets such as `recycle`, `paid`, and `pending`. Those buckets are useful for reducing follow-up work, but they are not equivalent to the final decisions required by the canonical `screening-backlinks` Skill.

Important boundary:

- the crawler may fail to discover a valid current publishing mechanism;
- a crawler `recycle` result based only on automated mechanism detection is not sufficient evidence for a final opportunity rejection;
- final free/reciprocal/paid/uncertain classification, Follow verification, indexability verification, and evidence closure belong to `.agents/skills/screening-backlinks/`.

The crawler and its regression tests are retained unchanged during repository hygiene cleanup because the GitHub Actions workflow actively depends on them.

Any future change that makes crawler output authoritative must be treated as a separate behavior change with explicit regression tests and a corresponding Screening Skill update.