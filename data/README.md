# Operational Data

This directory contains workflow inputs and machine-generated snapshots. It is not the canonical backlink opportunity database and it does not define product rules.

## `screening-candidates/`

Contains candidate-domain batches consumed by `.github/workflows/screening-crawler.yml`.

`RUN` is an operational workflow trigger. The numbered candidate files are inputs to the bulk triage crawler.

## `screening-results/`

`latest.jsonl` and `latest.summary.json` are the latest committed **triage snapshots** produced by the crawler workflow.

They may be large and may contain preliminary `dead`, `paid`, `pending`, or `unverified` classifications. Those machine classifications do not override the final evidence standard in `.agents/skills/screening-backlinks/`.

`unverified` means "no entry point found", which is missing evidence rather than a rejection. Those candidates must re-enter screening on the next run; only `dead` and `paid` are settled.

The latest snapshots remain tracked for compatibility with the current workflow. Changing that persistence behavior (for example, moving results entirely to GitHub Actions artifacts or another store) is an operational behavior change and must be handled separately.

## `opportunities/`

Produced by `scripts/verify_opportunity.py`.

- `opportunities.csv` — 机器已闭环 免费 + Follow + 可索引 的候选
- `internal-status.csv` — 全部候选的当前状态，含 `下一步` 列

这是**待复核的机器初判**，不是正式外链总表。按 Skill，写入正式总表前仍需人工确认免费档。`internal-status.csv` 里 `下一步` 以 `★` 开头的行是"链接已确认 Follow、只差确认免费档"的高优先候选。

## Source-of-truth rule

For final backlink decisions, use the canonical Skills. Data files record observations/results from a run; they are not instructions.