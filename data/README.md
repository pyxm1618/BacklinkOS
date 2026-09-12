# Operational Data

This directory contains repository-local workflow inputs and machine-generated snapshots. It is **not** the current business control plane and it does not define product rules.

## Current source-of-truth rule

Current production state lives in Google Sheets `@外链管理总控表`:

- `外链总表` — platform-level fact store;
- `外链管理` — project opportunity backlog and execution lifecycle.

Repository-local CSV/JSONL snapshots must never override newer Sheet facts or current Skill contracts.

## `screening-candidates/`

Historical/operational candidate-domain batches consumed by the bulk triage crawler workflow.

`RUN` is an operational trigger for that legacy/auxiliary workflow. These files are not the current Project Backlog.

## `screening-results/`

`latest.jsonl` and `latest.summary.json` are crawler **triage snapshots**.

Historical buckets such as `dead`, `paid`, `pending`, or `unverified` were created for the older screening workflow. They are useful as observations/debugging evidence, but they are not the default admission logic for the current production pipeline.

Current rules:

- `unverified` means missing Entry evidence, not rejection;
- a crawler's inability to close free/Follow facts does not stop a Master `候选` from entering Project Backlog;
- current execution readiness is established separately by Phase C Live Verification / `VerifiedEntry`;
- actual free/login/restriction/link-attribute facts come from `backlink-autofill` real execution.

## `opportunities/`

Produced by the historical/auxiliary `scripts/verify_opportunity.py` flow.

Files such as `opportunities.csv` and `internal-status.csv` are legacy machine-evaluation outputs. They are not `外链总表` and are not `外链管理`.

Do not use an old `正式机会 / 回收 / 付费排除` snapshot as a substitute for the current Master/Project control plane unless the user explicitly asks to investigate the legacy screening dataset.

## Historical-data discipline

Repository data may contain classifications that were correct for an older workflow or date but no longer represent current product semantics.

When repository snapshots conflict with current sources, use this order:

1. current Google Sheets facts;
2. current `discovering-backlinks` Skill/current references;
3. current architecture/handoff documentation;
4. repository-local historical snapshots.

Do not re-run old migrations or rebuild Project Backlog from these snapshots merely because they are committed in Git.
