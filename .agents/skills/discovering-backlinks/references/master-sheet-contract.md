# Master Sheet and Project Management Contract

本文档定义当前 BacklinkOS 控制面 `@外链管理总控表`、Project Backlog、Ready Preparation 与 `backlink-autofill` 的正式契约。

> [!IMPORTANT]
> ## 2026-09-20 业务展示层规则（当前权威）
>
> `外链总表` 继续保留 A:N 技术字段供现有自动化兼容使用；其中 `基础状态`、`基础排除原因` 在 UI 中隐藏，不作为用户日常判断字段。用户日常以新增的 O:R 四列为准：
>
> - `状态`：只允许空白或 `可用`。空白天然表示“尚未完成验证/仍是候选”；不再显示“候选”状态。只有已经明确可作为外链渠道使用，或某项目已经真实提交成功/进入审核/排期/上线，才填 `可用`。
> - `淘汰原因`：只写已经明确不能采用的原因，例如无可执行外链入口、平台当前不可用、垃圾/PBN、纯付费等。非空即进入 `黑名单` 视图。疑似、未知、未核验不得填写。
> - `平台类型`：只有明确识别后才填写，例如 AI工具目录、Startup目录、MCP目录、优惠券目录、本地商家目录、内容投稿等；不确定留空。
> - `获取方式`：只有明确后才填写，例如 `免费`、`换链`、`免费（付费可选）`、`付费-only`；不确定留空。
>
> A:N 已有实测字段仍继续承载精确平台事实：`提交入口 / 实测免费 / 实测需登录 / 实测登录方式 / 实测限制 / 实测链接属性 / 最后验证时间 / 平台备注`。任何字段都遵循 **known-only** 原则：有直接、明确证据才写；未知、推测、历史疑似信息一律留空。
>
> `实测链接属性` 仍是强证据字段：只有公开结果页已上线，并直接检查目标 `<a>` 的 DOM `rel` 后，才允许写 `Follow / Nofollow / UGC / Sponsored`。平台宣传、第三方数据库、提交页说明不能代替 DOM 实测。
>
> 数据流保持不变：新发现域名可以先进入 `外链总表` 并投影到 `外链管理`；`外链管理` 的真实执行结果必须反向沉淀已经确认的平台事实。项目级 `不适用` 不等于平台淘汰；例如仅限 MCP、仅限本地商家、需互链等，如果渠道本身真实可用，应在 Master 记录类型/限制，而不是因为 Quick I Ching 不适配就全局淘汰。纯付费-only 按当前业务策略进入淘汰/黑名单。
>
> 为兼容现有生产脚本，隐藏技术列仍使用旧内部状态：`基础状态=候选/已排除/失效`。它们只是执行门禁实现细节：业务层 `状态=可用` 的平台在技术列仍可保持 `候选`；业务层 `淘汰原因` 非空时，技术列同步为 `已排除/失效`。不得把隐藏技术状态直接展示为业务结论。


## 1. 核心原则

```text
PHASE A — Master Upsert
Discovery 发现候选 + provenance
        ↓
【外链总表】
        ↓
PHASE B — Project Backlog Projection
纯数据库投影，UNKNOWN != REJECT
不要求 Submission Entry / VerifiedEntry
        ↓
【外链管理】待提交 Backlog
        ↓
PHASE C — Bounded Execution Preparation
Live Verification
只有 VerifiedEntry 才进入 Ready Allowlist
        ↓
PHASE D — backlink-autofill
真实浏览器执行与事实回写
```

最重要的契约：

> **Project Backlog Population != Execution Readiness。**
>
> `VerifiedEntry` 不是项目行存在的前提，只是 Ready for Autofill 的前提。

不要在 Phase A/B 与 Phase C 之间重新创造默认 `screening-backlinks` gate。

---

## 2. Tab 1 — `外链总表`

固定平台级事实字段：

| 列名 | 角色 | 当前契约 |
|---|---|---|
| 外链ID | Discovery/系统 | canonical domain，稳定 join key |
| 平台域名 | Discovery/系统 | canonical domain |
| 提交入口 | Execution Preparation | 只有真实 Live Verification 后才允许写；未知为空 |
| 发现来源 | Discovery | 真实 provenance |
| 发现时间 | Discovery | 真实发现时间 |
| 基础状态 | Discovery/审计 | 仅 `候选 / 已排除 / 失效` |
| 基础排除原因 | 审计/历史迁移 | 仅硬负例有值 |
| 实测免费 | Autofill | Discovery 严禁填写 |
| 实测需登录 | Autofill | Discovery 严禁填写 |
| 实测登录方式 | Autofill | Discovery 严禁填写 |
| 实测限制 | Autofill | Discovery 严禁填写 |
| 实测链接属性 | Autofill | Discovery 严禁填写 |
| 最后验证时间 | Autofill/Recheck | Discovery 严禁填写 |
| 平台备注 | 通用 | 真实备注，不得伪造事实 |

### Master Upsert

每个 referring domain 必须 canonicalize：

- 去 http/https；
- 去 `www.`；
- 小写；
- 去 path/query/fragment；
- `外链ID = 平台域名 = canonical domain`。

新域名：

- 新增 `基础状态=候选`；
- 提交入口为空；
- 实测事实为空；
- 写真实 provenance。

已有域名：

- 不重复创建；
- 不覆盖已有真实实测字段；
- **绝不得把 `已排除` / `失效` 改回 `候选`；**
- 普通 Discovery Upsert 不更新 `提交入口`。

### 硬黑名单

不维护第二套业务黑名单。Master `基础状态=已排除/失效` 即当前硬负例来源。

---

## 3. Tab 2 — `外链管理`

`外链管理` 是**项目机会全集 + 执行生命周期**，不是 Ready-only 表。

固定 10 列：

| 列名 | 初始/业务规则 |
|---|---|
| 项目ID | 当前明确 project_id |
| 外链ID | canonical domain |
| 外链域名 | canonical domain |
| 状态 | 新 Backlog 为 `待提交` |
| 尝试次数 | 新 Backlog 为 `0` |
| 最近操作时间 | 初始为空 |
| 目标URL | 项目 canonical URL 或显式深链 |
| 结果链接 | 初始为空；只有真实结果才写 |
| 原因/备注 | 初始为空；真实执行/人工事实 |
| 证据摘要 | 初始为空；真实执行证据 |

有效生命周期包括：

- `待提交`
- `处理中`
- `已提交`
- `审核中`
- `已排期`
- `已上线`
- `需人工`
- `失败`
- `不适用`

### 唯一性与历史保护

`project_id + backlink_id` 唯一。

如果当前项目已经有任何状态的该外链行：

- 不 duplicate；
- 不重置为待提交；
- 不重置 attempt；
- 不覆盖历史结果/备注/证据。

---

## 4. PHASE B — Project Backlog Projection

正式函数语义：`materialize_project_backlog_rows(...)`。

### 输入

- `master_rows`
- `existing_project_rows`
- `project_id`
- `target_url`
- `project_context`

### 核心行为

1. **禁止网络请求。**
2. 只对 Master `基础状态=候选` 做项目投影。
3. **禁止要求 `提交入口` 非空。**
4. **禁止要求 `VerifiedEntry`。**
5. UNKNOWN 默认 INCLUDE：
   - Entry 未知；
   - 免费未知；
   - 登录未知；
   - Follow 未知；
   - 当前可执行性未知。
6. 只有明确 hard incompatibility 才跳过该项目。
7. 已存在项目行完整保护。
8. 新项目行为 `待提交 / 尝试次数=0`，结果与证据字段为空。

### Project Compatibility Hard Gate

Hard Gate 必须基于已持久化、明确、与项目相关的强事实。

例如：平台被明确证实为 AI-only，且 `project_context.ai_powered == False`，则不为该项目投影。

规则：

- strong fact → 可判 incompatible；
- weak/ambiguous/missing fact → UNKNOWN → INCLUDE；
- 项目不兼容不会自动把 Master 平台标为全局已排除。

### Projection reconciliation

候选总数必须被完整解释：

```text
candidate_count
=
duplicate_preserved_count
+ proven_project_incompatible_count
+ would_create_count
```

`would_create_count=0` 是合法幂等结果，不能因为“新增少于某个数量”失败。

---

## 5. PHASE C — Submission Entry Live Verification

Submission Entry Enrichment 属于 **Execution Preparation**，不是 Backlog Population 的前置 gate。

### VerifiedEntry 最低原则

只有真实页面证据足够时才创建内部 `VerifiedEntry`。

可接受证据包括：

- Actionable Form；
- 有真实 provenance/callback 的同域认证墙；
- 可跟随并最终落到真实 Actionable Form 的明确 CTA。

不可接受：

- URL path 仅仅叫 `/submit`；
- 普通正文提到 submit/add；
- 搜索结果页；
- pricing/terms/privacy/category/report；
- generic Contact form；
- 私有 dashboard 无提交上下文；
- 跨域 form action 被误当平台自身 Entry。

### Actionable Form

Directory / Tool Listing：

- 至少一个资源身份字段（URL/website/tool/product/app/startup/business/listing 等）；
- 有真实 submit action/button；
- 普通 name/email/message Contact form 不够。

Guest Post：

- 页面/路径存在 write-for-us / guest-post / submit-article / contribute 等投稿上下文；
- 表单有投稿相关字段。

### Auth Wall

历史 Master Entry 不因为 `/login?redirect=/submit` 自动放行。

必须建立真实来源关系，并验证：

- 原 Entry 合法；
- same-origin auth wall；
- callback/redirect 指向合法提交流程；
- callback 不跨域；
- 保存稳定原始 Submission URL，不保存敏感 session query。

### AI-only 等兼容性 Live Evidence

Live Verification 可以产生项目兼容性强事实。

AI-only 不能只靠页面偶尔出现 “AI”。应使用强组合证据（例如明确 AI submission object + AI eligibility/acceptance）并保留 inclusive guard（例如 `AI or SaaS` 不应误判为 AI-only）。

---

## 6. PHASE C — Bounded Execution Preparation

正式语义：`prepare_execution_batch(...)`。

### 输入池

只从**已经存在于 `外链管理`、当前项目、状态=`待提交`**的行中准备 Ready。

### 双边界

典型参数：

- `target_ready_count=10`
- `scan_limit=50`

`scan_limit >= target_ready_count`。

停止条件是 Ready 目标达到或扫描上限达到。

这两个参数只限制**当前 Ready preparation 批次**，绝不能限制 Project Backlog 总规模。

### Cursor

Ready scan 使用本地 cursor，从上一批最后扫描位置继续，防止 unresolved 头部候选长期饿死后续行。

### Orphan

Project 行找不到对应 Master 行时：

- 明确计入/report orphan；
- 不生成 Ready；
- 不让 orphan 阻断 cursor 和后续扫描。

### unresolved

Entry 核验失败或仍未知：

- 项目行保持 `待提交`；
- attempt 保持原值（正常初始为 0）；
- 不标失败；
- 不删除；
- 继续扫描后续候选。

### Ready 输出

只有 Live Verification 成功的 `VerifiedEntry` 可以进入 Ready manifest / allowlist。

---

## 7. PHASE C → PHASE D Handoff

`backlink-autofill` 只能消费：

```text
Ready Allowlist
∩
当前 project_id
∩
Sheet 状态=待提交
```

**待提交 != Ready。**

没有 Ready allowlist 的 standalone 模式必须 fail closed，不能直接从数千条 Backlog 盲取。

---

## 8. PHASE D — Autofill Fact Ownership

`backlink-autofill` 负责真实浏览器事实：

- 是否免费；
- 是否需登录；
- 登录方式；
- 平台限制；
- Existing Submission Preflight；
- Final Submit；
- CAPTCHA/Turnstile/2FA/SMS human blocker；
- 项目最终状态；
- 结果链接；
- live DOM rel；
- 最后验证时间；
- Manual Post-submit Recheck。

### Fact protection

- 没观察到的 Master fact 不得在 Recheck 中清空；
- 结果 URL 只有公开 listing + identity verified 才写；
- live DOM rel 只有实际检查目标 `<a rel>` 才写；
- Recheck 不增加 attempt、不重新 Final Submit；
- 已排期在无明确取消事实时不得被弱 `Pending/Review` 降级。

---

## 9. Production Projection Helper

`scripts/project_backlog_projection.py` 是当前正式生产投影 helper。

必须支持：

- dry-run / commit；
- 0-network projection；
- reconciliation；
- commit 前 timestamp backup；
- 按需 grid row 扩容；
- batch append；
- exact read-back；
- final duplicate/completeness audit。

旧计划里写死“扩到 5000 行”“每批 500”“新增必须超过某数”不是当前契约；正式 helper 按实际需求动态执行。

---

## 10. Historical/Legacy Screening

`screening-backlinks` 已退出默认主链路。

它可以在用户明确要求时进行历史/offline 的免费/Follow opportunity 分析，但：

- 不能作为 Master 候选进入 Project Backlog 的默认 gate；
- 不能因未完成 legacy Screening 就排除普通候选；
- legacy 输出表/CSV 不覆盖当前 Google Sheets 控制面。
