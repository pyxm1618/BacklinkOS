# Historical Live-Run Records

Files in this directory capture what happened in a specific BacklinkOS run on a specific date.

They are preserved as evidence/debugging history. They **do not define current product rules, current completion state, or current Skill behavior**.

Older runs may refer to Screening as the main production path or describe candidate states that no longer control Project Backlog admission. Those statements remain valid only for the recorded date.

For current default behavior use:

1. `../../.agents/skills/discovering-backlinks/SKILL.md` + current references
2. `../REPOSITORY_ARCHITECTURE.md`
3. `../V4_PRODUCT_STRATEGY.md`
4. `../../BacklinkOS-HANDOFF.md`

Current default flow:

```text
Master Upsert
→ Project Backlog Projection (UNKNOWN != REJECT)
→ Bounded Ready Preparation (VerifiedEntry required for Ready)
→ backlink-autofill
```

`screening-backlinks` is Legacy / Optional and only governs that explicitly requested historical screening path.

Do not rewrite old run bodies to make them look current. When an old run says something was unimplemented or used a different pipeline, compare against current main before taking action.
