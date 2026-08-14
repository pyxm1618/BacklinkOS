# BacklinkOS V1 Product Plan

## Product Positioning

BacklinkOS is a Backlink Opportunity Pipeline, not a simple backlink publishing bot.

The goal is to continuously discover, verify, evaluate, acquire, and maintain valuable backlink opportunities with minimal manual effort.

## Core Principle

Do not optimize for backlink quantity. Optimize for discovering and acquiring backlinks that are worth acquiring.

Avoid artificial scoring systems that create false precision. V1 focuses on transparent evidence and decision rules.

## System Shape

BacklinkOS consists of three parts:

1. Feishu Bitable as the main operation interface and data repository.
2. Backend workers for crawling, verification, enrichment, and data processing.
3. Browser assistance for tasks that require human browser context, such as semi-automatic submission workflows.

The browser component is an auxiliary tool, not the whole product.

## Core Workflow

```
Discovery
    ↓
Verification
    ↓
Evidence Enrichment
    ↓
Decision
    ↓
Acquisition
    ↓
Post-acquisition Verification
    ↓
Continuous Discovery
```

## V1 Modules

### 1. Backlink Verification

Verify whether an existing backlink is real:

- Page accessibility
- Link existence
- Target URL
- Anchor text
- rel attributes
- Indexability signals
- Link placement

### 2. Evidence Enrichment

Collect supporting information:

- Domain and page metrics
- Traffic signals
- Topic relevance
- Outbound link patterns
- Competitor backlink overlap
- Spam indicators

### 3. Decision System

Use transparent rules instead of a black-box score.

Output categories:

- Recommended
- Needs manual review
- Rejected

Every decision should explain why.

### 4. Acquisition Workflow

Support multiple backlink acquisition methods:

- Blog comments
- Directories
- Resource pages
- Profiles
- Outreach opportunities
- Guest posts

Blog comments are only one acquisition channel.

### 5. Verification After Acquisition

Track:

- Published status
- Link persistence
- rel changes
- Page changes

## V1 Non-Goals

- No uncontrolled automatic backlink spam.
- No fake precision scoring model.
- No CAPTCHA bypass.
- No fully autonomous mass submission system.

## Future Direction

BacklinkOS should become a reusable SEO asset acquisition system for multiple projects, where data quality and learning loops improve over time.
