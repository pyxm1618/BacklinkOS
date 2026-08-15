# BacklinkOS Repository Architecture

## Status

Approved design for repository responsibility and migration. This document defines structure only; it does not authorize feature expansion during the repository-cleanup step.

## Decision

BacklinkOS will use two repositories with explicit boundaries:

1. `pyxm1618/BacklinkOS` — product/orchestration layer.
2. `pyxm1618/backlink-metrics-api` — deterministic metrics service.

Do not create a third repository for the current scope.

---

## 1. `BacklinkOS`: product and workflow layer

`BacklinkOS` is the canonical home for backlink product logic.

It owns:

- backlink opportunity model and lifecycle
- `screening-backlinks` Skill
- future `discovering-backlinks` Skill
- A/B/C/D/F screening semantics
- publishability / registration / pricing / link-attribute verification workflow
- evidence and persistence contracts
- Feishu/Lark integration when implemented
- batch screening orchestration when implemented
- product strategy, architecture and decisions
- future acquisition / measurement / learning workflows

It must not implement or duplicate proprietary/deterministic metric-provider logic when that logic belongs in `backlink-metrics-api`.

### Target structure

```text
BacklinkOS/
├── .agents/
│   └── skills/
│       ├── screening-backlinks/
│       └── discovering-backlinks/        # future, not part of cleanup
├── .claude/
│   └── skills/                            # compatibility symlinks only
├── docs/
│   ├── V1_PRODUCT_PLAN.md
│   ├── V2_PRODUCT_PLAN.md
│   ├── V3_PRODUCT_STRATEGY.md
│   └── REPOSITORY_ARCHITECTURE.md
├── integrations/
│   └── feishu/                            # future
├── workflows/
│   └── screening/                         # future
└── tests/
    └── skill-contracts/                   # future if executable contract tests are added
```

The cleanup must not create empty speculative directories solely to match this diagram.

---

## 2. `backlink-metrics-api`: deterministic metrics service

`backlink-metrics-api` is a supporting infrastructure repository. It exposes stable metric endpoints and provider adapters.

It owns:

- Ahrefs DR provider integration
- Crawlora total-monthly-visits provider integration
- future CrUX popularity runtime
- provider normalization
- provider error / no-data semantics
- provider-specific tests
- provider validation reports
- Vercel deployment/runtime configuration

It does not own:

- backlink discovery
- backlink opportunity rating
- A/B/C/D/F logic
- backlink publishability logic
- registration/pricing classification
- placement-type business rules
- Feishu schema/business workflow
- Skill orchestration
- topical relevance

### Target structure

```text
backlink-metrics-api/
├── app/
│   └── api/
│       ├── dr/
│       ├── traffic/
│       └── crux/                          # future
├── lib/
│   └── providers/                         # preferred destination for provider code as it grows
├── tests/
│   └── providers/                         # preferred destination for provider tests as it grows
├── docs/
│   └── provider-validation/
└── README.md
```

The cleanup may move existing provider files into clearer directories only when imports/tests remain stable and the move has clear value. It must not add CrUX runtime or other new features during the cleanup.

---

## 3. System relationship

The product flow is:

```text
Discovering Backlinks (future)
        ↓
Raw Opportunity
        ↓
Screening Backlinks
        ↓
Verified Opportunity
        ↓
Persistence / Acquisition / Learning
```

`screening-backlinks` may call `backlink-metrics-api` for deterministic evidence:

```text
BacklinkOS / screening-backlinks
        │
        ├── DR request ───────→ backlink-metrics-api /api/dr
        ├── visits request ───→ backlink-metrics-api /api/traffic
        └── CrUX request ─────→ backlink-metrics-api /api/crux   # future
```

The API returns evidence. The Skill decides how evidence is interpreted in the backlink workflow.

---

## 4. Migration scope

The repository cleanup is intentionally narrow.

### Move to `BacklinkOS`

Move the canonical `screening-backlinks` Skill and its references from `backlink-metrics-api` to `BacklinkOS`:

```text
.agents/skills/screening-backlinks/
```

Recreate/maintain the Claude compatibility symlink in `BacklinkOS`:

```text
.claude/skills/screening-backlinks
→ ../../.agents/skills/screening-backlinks
```

The migrated Skill must continue to call the deployed metrics API rather than importing provider implementation code.

### Keep in `backlink-metrics-api`

Keep:

- `/api/dr`
- `/api/traffic`
- Ahrefs provider implementation
- Crawlora provider implementation
- executable provider tests
- provider validation report(s)
- deployment/runtime configuration

### Remove from `backlink-metrics-api`

After the Skill exists and is verified in `BacklinkOS`, remove the duplicated canonical Skill directory and its Claude compatibility link from `backlink-metrics-api`.

Do not leave two independently editable copies of `screening-backlinks`.

---

## 5. Source of truth

After migration:

- Product/Skill source of truth: `pyxm1618/BacklinkOS`
- Deterministic metric source of truth: `pyxm1618/backlink-metrics-api`
- Production metric endpoint: `https://backlink-metrics-api.vercel.app`

A provider implementation must not be copied into the Skill repository merely to make the Skill self-contained.

---

## 6. Cleanup safety rules

Repository cleanup must preserve behavior.

1. No new backlink feature development during the move.
2. No CrUX runtime implementation during the move.
3. No Discovery Skill implementation during the move.
4. No Feishu adapter implementation during the move.
5. No rating-rule redesign during the move.
6. No secret values may be copied between repositories.
7. Existing production `/api/dr` and `/api/traffic` must remain operational.
8. Existing provider tests must remain green.
9. The Skill content must be byte-equivalent or semantically unchanged except for repository/path references required by the move.
10. Migration is not complete until only one canonical editable `screening-backlinks` copy remains.

---

## 7. Verification after migration

The cleanup is accepted only after all of the following are verified:

- `BacklinkOS/.agents/skills/screening-backlinks/SKILL.md` exists.
- All current `screening-backlinks/references/*` files exist in `BacklinkOS`.
- `BacklinkOS/.claude/skills/screening-backlinks` resolves to the `.agents` Skill.
- No canonical `screening-backlinks` Skill remains in `backlink-metrics-api`.
- `backlink-metrics-api` provider/runtime files remain present.
- `npm test` passes in `backlink-metrics-api`.
- production `/api/dr?domain=hey.com` returns a valid Ahrefs DR response.
- production `/api/traffic?domain=github.com` returns a valid Crawlora observation.
- no API key or secret is added to GitHub.

---

## 8. Work order after cleanup

Do not run the full screening Skill immediately after repository cleanup.

Recommended sequence:

1. Complete and verify repository cleanup.
2. Implement CrUX BigQuery bulk popularity runtime in `backlink-metrics-api`.
3. Add only the minimum persistence/batch infrastructure needed by the screening workflow.
4. Perform a controlled dry-run on a small candidate set and audit outputs.
5. Only then run `screening-backlinks` on larger real candidate sets.
6. Build `discovering-backlinks` as a separate Skill later.

This ordering keeps infrastructure validation separate from business-workflow validation and prevents repository restructuring from being mixed with new feature development.
