---
name: discovering-backlinks
description: Use when the user asks to 抓外链, 找外链, 批量抄竞品外链, 扩大外链库, discover backlink candidates, or continue an existing backlink-discovery batch.
---

# 抓外链

## 目标

从近期已经跑出 SEO 结果的项目反查真实 Referring Domains，并把**发现阶段亲自取得的事实**交给 `screening-backlinks`。

## 硬规则

1. **只传事实，不传推测。** 当前工具/数据源没有直接给出的字段就留空；不要猜免费、付费、提交入口或当前是否 Follow。
2. **下游不复查这些事实。** 交给 Screening 的字段必须来自本次技术采集或已经保存的同源技术采集结果。
3. **不做项目适配。** 不判断 Quick I Ching 或任何具体项目是否“有资格”做某条外链，也不做主题相关性评分。
4. Semrush 的 `is_follow` 只表示 Semrush 观察到的历史 backlink 属性，不能写成“当前免费渠道是 Follow”。
5. `first_seen` 只表示 Semrush 首次观察时间，不是精确建链日期。
6. **Semrush 查询固定优先走已经跑通的 `sem.3ue.com` 中转。禁止因为官方 Semrush API units 不足而停止，也禁止改走需要 API units 的官方 Semrush API/connector。** 中转会话失效时，只处理登录/会话问题后继续中转。

## 每批怎么跑

1. 默认每批找 **100 个新的候选项目**；先与历史项目池去重，并给本批一个批次 ID。
2. 优先从 Toolify、There’s An AI For That、TrustMRR 找近期项目；需要扩量时可以增加同类来源。
3. 批量查 Semrush Organic Traffic；默认 `>= 500` 才进入 Referring Domains 抓取。
4. 对通过项目抓 Referring Domains。先抓前 300；大项目继续分页，直到抓完或新增有效来源明显变少。
5. 保存原始事实：来源项目、Organic Traffic、referring domain、backlinks_num、AS、first_seen、last_seen、lost/new、is_follow。
6. 按 referring domain 聚合成功项目覆盖数和出现次数；记录它在 BacklinkOS 中是首次出现还是历史已见。
7. 把候选交给 `screening-backlinks`。Discovery 到此结束。

## 输出

至少传递：

`referring_domain | source_projects | successful_project_count | occurrence_count | source_project_organic_traffic | backlinks_num | domain_ascore | first_seen | last_seen | semrush_is_follow | discovery_source | batch_id | first_discovered_at | seen_before`

不知道的字段留空，不生成“可能”“大概”“推测”值。

Semrush 中转细节见 [references/semrush-relay.md](references/semrush-relay.md)。回归要求见 [references/test-cases.md](references/test-cases.md)。
