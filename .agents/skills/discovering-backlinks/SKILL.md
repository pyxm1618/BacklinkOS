---
name: discovering-backlinks
description: Use when the user asks to 抓外链, 找外链, 批量抄竞品外链, 发现外链机会, 扩大外链库, or systematically discover backlink candidates from recent successful projects.
---

# 抓外链 / Discovering Backlinks

## 核心原则

从**近期已经跑出 SEO 结果的项目**反推它们真实获得过的 Referring Domains，再把跨项目重复出现、早期出现、当前可复制的来源优先交给审核流程。

不要为了数量降低质量标准。不要做主题相关性评分。

## 主流程

1. **扩项目池**：从 Toolify、There's An AI For That、TrustMRR 等发现近期项目。优先 90 天内；样本不足时放宽到 180 天。
2. **筛成功项目**：批量查 Semrush Organic Traffic。默认 `>= 500` 进入外链抓取；用户指定门槛时服从用户。
3. **抓 Referring Domains**：只抓通过项目；保留 `source_domain`、`backlinks_num`、`domain_ascore`、`first_seen`、`last_seen`、`lost/new/follow`。
4. **聚合**：按来源域名统计成功项目覆盖数、Follow 比例、AS、最早发现时间；去掉明确垃圾网络。
5. **加入时间信号**：有可靠项目起始/参考日期时计算 90 天早期外链；没有就只保留 `first_seen`，不得伪造早期率。
6. **继续扩容**：优先扩大成功项目样本，再增加单项目抓取深度；不要先引入复杂评分、递归图谱或失败对照组。
7. **交给审核**：Discovery 只证明“值得查”。需要确认免费/付费、可发布、Dofollow/Nofollow、最终评级时，**REQUIRED SUB-SKILL:** use `screening-backlinks`。
8. **持久化**：把项目池、发现证据、聚合结果和审核结果写入现有 BacklinkOS 在线主库；写入未获确认时不得声称已保存。

## Semrush 中转

优先复用已经验证成功的 Semrush 中转，而不是因为官方 API units 不足而停止。中转恢复、分页、会话安全和失败处理见 [references/semrush-relay.md](references/semrush-relay.md)。

**禁止把 key、cookie、`__gmitm` 或其他会话凭证提交到 Git、在线表格、日志或聊天回复。**

## 何时读取详细参考

| 需要 | 读取 |
|---|---|
| 项目来源、筛选门槛、扩容顺序、垃圾过滤 | [references/discovery-methodology.md](references/discovery-methodology.md) |
| Semrush 中转、Organic Traffic、Referring Domains、分页与凭证安全 | [references/semrush-relay.md](references/semrush-relay.md) |
| `first_seen`、90 天早期外链、日期可信度 | [references/early-link-analysis.md](references/early-link-analysis.md) |
| 在线主库字段、Discovery → Screening 交接 | [references/persistence-and-handoff.md](references/persistence-and-handoff.md) |
| 触发/不触发与回归测试 | [references/test-cases.md](references/test-cases.md) |

## 输出契约

至少保留：

`candidate_domain | source_project | source_project_organic_traffic | source_domain | backlinks_num | domain_ascore | first_seen | last_seen | is_follow | discovery_source | discovered_at`

聚合后至少输出：

`referring_domain | successful_project_count | occurrence_count | follow_count | follow_rate | max_as | early_90d_count | early_90d_rate | example_projects | status`

`early_90d_count/rate` 无法可靠计算时写 `未确认`，不是 `0`。

## 常见错误

- 官方 Semrush API units 不足 → **不是停止理由**；先检查已验证中转。
- 看到历史外链 → **不是当前可复制证据**；交给 `screening-backlinks`。
- `first_seen` → 是 Semrush 首次发现时间，**不是精确建链时间**。
- 一个域名只出现一次 → 可以保留，但优先级低于多成功项目重复来源。
- 低 AS / 低流量 → 不是自动垃圾；只有明确垃圾/链接网络证据才在 Discovery 阶段剔除。
- 为了做大数量加入复杂模型 → 先扩成功项目样本和抓取深度。
