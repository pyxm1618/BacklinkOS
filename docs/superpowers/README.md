# Historical Implementation Records

Everything under `docs/superpowers/` is a **point-in-time implementation plan or design specification**.

These files are preserved to explain why earlier repository/runtime decisions were made. They are **not** the current BacklinkOS operating contract and must not be treated as an unfinished task queue.

Older plans/specs may:

- describe Feishu-first or earlier persistence architecture;
- use old Screening/admission semantics;
- require A/B/C/D/F ratings;
- say a capability was not yet implemented;
- describe gaps that later main commits already fixed;
- propose migrations that have already been executed in production.

For current default behavior use:

1. `../../.agents/skills/discovering-backlinks/SKILL.md` + current references
2. `../REPOSITORY_ARCHITECTURE.md`
3. `../V4_PRODUCT_STRATEGY.md`
4. `../../BacklinkOS-HANDOFF.md`

`../../.agents/skills/screening-backlinks/` is Legacy / Optional and only governs that explicitly requested historical screening path.

The current default production flow is:

```text
Master Upsert
→ Project Backlog Projection (UNKNOWN != REJECT)
→ Bounded Ready Preparation (VerifiedEntry required here)
→ backlink-autofill
```

When reviewing any file in `plans/` or `specs/`:

- preserve its original point-in-time content;
- compare the proposed work to current main before doing anything;
- if current main already implements it, classify it as `Completed / Superseded by current main implementation` rather than reopening development.

Do not rewrite historical plans merely to make their body text match the present.
