# BacklinkOS V2 Product Plan

> **Status: HISTORICAL.** This document preserves an earlier product direction and must not be used as the current operating contract. Current behavior is defined by the canonical Skills under `.agents/skills/`, then `REPOSITORY_ARCHITECTURE.md` and `V4_PRODUCT_STRATEGY.md`. Concepts below such as topical relevance, acquisition workflow, or older decision categories may intentionally differ from the current system.

## Product Positioning

BacklinkOS is a personal SEO asset acquisition operating system.

It is not:

- A backlink database.
- A mini Ahrefs.
- A backlink spam automation tool.
- A backlink publishing bot.

The objective is not to maximize backlink quantity. The objective is to continuously discover, evaluate, acquire, verify, and learn from backlinks that are genuinely valuable for owned websites.

---

## Core Insight

For a solo SEO operator, the biggest bottleneck is not discovering enough backlink candidates.

The real bottleneck is:

1. Identifying which opportunities are worth pursuing.
2. Reducing manual verification cost.
3. Prioritizing limited outreach time.
4. Learning which acquisition methods actually work.

Therefore BacklinkOS should optimize decision quality, not data volume.

---

## V2 Design Principles

### 1. Quality over quantity

Avoid optimizing for the number of discovered links, domains, or opportunities.

A small number of relevant, authoritative, sustainable backlinks is more valuable than thousands of low-quality opportunities.

### 2. Evidence over artificial scoring

Avoid black-box scores that create false precision.

The system should explain decisions through evidence:

- Why recommended.
- Why rejected.
- What requires manual review.

### 3. Human-in-the-loop automation

Backlink acquisition contains many tasks requiring judgment and browser context.

Automation should reduce repetitive work, not replace strategic decisions.

### 4. Build a learning loop

Every opportunity should create reusable knowledge:

- Which sources work.
- Which acquisition methods work.
- Which niches respond.
- Which signals predict success.

---

# System Model

```
Opportunity Discovery
        ↓
Verification
        ↓
Evidence Collection
        ↓
Decision Support
        ↓
Acquisition Workflow
        ↓
Post-acquisition Monitoring
        ↓
Learning Loop
```

---

# V2 Core Modules

## 1. Opportunity Intelligence Engine (Highest Priority)

Purpose:

Turn raw opportunities into actionable decisions.

Input:

- Competitor backlinks.
- Resource pages.
- Industry directories.
- Relevant websites.
- Manual discoveries.

Output:

### Recommended

High probability and high value.

### Manual Review

Potential value but requires human judgment.

### Rejected

Low relevance, spam risk, or poor acquisition value.

Every decision must include evidence.

---

## 2. Backlink Verification Engine

Purpose:

Verify whether backlinks actually exist and remain valuable.

Checks:

- Page accessibility.
- Link existence.
- Target URL.
- Anchor text.
- rel attributes.
- Link placement.
- Page changes.
- Indexability signals.

This is the foundation for both existing links and acquired links.

---

## 3. Evidence Enrichment Layer

Collect supporting information without creating fake precision.

Signals:

- Domain authority indicators.
- Traffic signals.
- Topic relevance.
- Outbound link behavior.
- Competitor overlap.
- Spam indicators.

The system provides evidence, not a magic score.

---

## 4. Acquisition Pipeline

Manage the process from opportunity to completion.

Supported acquisition methods:

- Resource page inclusion.
- Directories.
- Profiles.
- Outreach.
- Guest posts.
- Community contributions.
- Blog comments when appropriate.

Blog comments are only one channel and should never become the main strategy.

---

## 5. Post-acquisition Monitoring

After obtaining a backlink:

Track:

- Published status.
- Link persistence.
- Anchor changes.
- rel changes.
- Page changes.

A backlink is an asset that requires maintenance.

---

# Technical Direction

Because BacklinkOS is for personal use, avoid unnecessary SaaS complexity.

Recommended architecture:

```
Feishu Bitable
        |
Python Workers
        |
Crawler / Verification / Enrichment / AI Analysis
        |
Result Sync
```

Optional components:

- Playwright for browser-assisted workflows.
- Scheduled jobs for monitoring.
- LLM analysis for decision explanations.

Avoid:

- Complex frontend systems.
- Multi-user architecture.
- Distributed crawler infrastructure.
- Large-scale backlink index.

Those solve commercial SaaS problems, not personal SEO problems.

---

# V1 vs V2 Changes

## Keep

- Backlink Opportunity Pipeline positioning.
- Verification workflow.
- Evidence-based decisions.
- Human-assisted acquisition.
- Post-acquisition verification.

## Improve

- Move decision quality above discovery volume.
- Make opportunity evaluation the central product capability.
- Add learning loop and historical intelligence.
- Simplify technical architecture for personal use.

## Avoid

- Building an Ahrefs clone.
- Collecting massive backlink datasets.
- Automated spam operations.
- Unexplainable scoring systems.

---

# Final Vision

BacklinkOS should become a personal SEO operating system that helps one person make better backlink decisions repeatedly.

The competitive advantage is not more data.

The advantage is better judgment, faster execution, and accumulated SEO learning.