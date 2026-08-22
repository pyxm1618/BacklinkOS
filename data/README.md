# Operational Data

This directory contains workflow inputs and machine-generated snapshots. It is not the canonical backlink opportunity database and it does not define product rules.

## `screening-candidates/`

Contains candidate-domain batches consumed by `.github/workflows/screening-crawler.yml`.

`RUN` is an operational workflow trigger. The numbered candidate files are inputs to the bulk triage crawler.

## `screening-results/`

`latest.jsonl` and `latest.summary.json` are the latest committed **triage snapshots** produced by the crawler workflow.

They may be large and may contain preliminary `recycle`, `paid`, or `pending` classifications. Those machine classifications do not override the final evidence standard in `.agents/skills/screening-backlinks/`.

The latest snapshots remain tracked for compatibility with the current workflow. Changing that persistence behavior (for example, moving results entirely to GitHub Actions artifacts or another store) is an operational behavior change and must be handled separately.

## Source-of-truth rule

For final backlink decisions, use the canonical Skills. Data files record observations/results from a run; they are not instructions.