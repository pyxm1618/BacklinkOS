---
name: discovering-backlinks
description: Use when the user asks to 抓外链, 找外链, 批量抄竞品外链, 扩大外链库, discover backlink candidates, or continue an existing backlink-discovery batch.
---

# 抓外链

## 目标

从近期已经跑出 SEO 结果的项目反查真实 Referring Domains，并把**发现阶段亲自取得的事实**交给 `screening-backlinks`。Discovery 负责找事实，不负责判断当前机会是否免费、Follow、可索引或值得入正式机会库。

## 硬规则

1. **只传事实，不传推测。** 当前工具/数据源没有直接给出的字段就留空；不要猜免费、付费、提交入口或当前是否 Follow。
2. **下游不复查这些事实。** 交给 Screening 的字段必须来自本次技术采集或已经保存的同源技术采集结果。
3. **不做项目适配。** 不判断 Quick I Ching 或任何具体项目是否“有资格”做某条外链，也不做主题相关性评分。
4. Semrush 的 `is_follow` 只表示 Semrush 观察到的历史 backlink 属性，不能写成“当前免费渠道是 Follow”。
5. `first_seen` 只表示 Semrush 首次观察时间，不是精确建链日期。
6. **Semrush 查询固定优先走已经跑通的 `sem.3ue.com` 中转。禁止因为官方 Semrush API units 不足而停止，也禁止改走需要 API units 的官方 Semrush API/connector。** 中转会话失效时，只处理登录/会话问题后继续中转。
7. **Semrush 正式批量必须使用 `scripts/semrush-relay-batch.js`。** 不得每次重新猜 endpoint、参数、分页、字段语义或 session key 获取逻辑。
8. runner 必须自动恢复并验证 session key；不能只依赖 `performance`。当 `performance=[]` 时继续走已验证的 32-hex 候选扫描和有界运行时扫描。不得让用户手抄 key，也不得用任意 storage 值乱试。
9. Organic HTTP 200 但没有 `organic_traffic` 时必须记为 `no_data`，不是 0，也不是 API error。
10. Referring Domains 是否完整必须由 `refdomains.total` 判断；若人为设置上限，只能输出 partial，不能伪装成完整抓取。
11. 分页中 offset 不推进或下一页没有新增 domain 时，必须报分页错误，不能静默完成。
12. **任何 Semrush runner/契约调试前必须先读 `references/incidents/2026-08-21-semrush-relay-debugging.md`。** 已保存成功证据能回答的问题，不得再次让用户抓 Network、截图、手抄 key 或重复试错。
13. **Console 注入不跨页面导航。** 不能先装 hook 再让用户跳页；导航会销毁当前 JS context。需要跨导航时只能使用正式持久方案。
14. 只有精确请求实际 HTTP 200 + 响应结构通过，才能称“已验证”。page0 成功不能自动扩展成“分页已验证”。
15. **100 是批次单位，不是停止条件。** 用户要求继续扩大外链库时，可以连续建立多个去重批次；不能因为单批达到 100 个项目就宣告 Discovery 完成。
16. **控制来源集中度。** 记录项目种子的来源占比；当一个来源明显集中时，优先继续使用已经批准的其他来源（如 Toolify / There’s An AI For That / TrustMRR）补充，再考虑继续向单一来源深挖。
17. **Semrush 暂时不可用时只积累项目事实。** 内部状态可记为 `pending_semrush`；当前 Google Sheet `项目池` 落表必须沿用既有 schema：`SEO筛选状态=待Semrush`、`RD状态=待Semrush筛选`。不得把字面值 `pending_semrush` 写进现有状态列，也不得填造 Organic、qualified、RD 或 backlink 字段。
18. **允许按需做 source URL enrichment。** Screening 若无法从 domain-level 事实闭环机制，可返回 `source_url_enrichment_required`；Discovery 只补精确历史来源页事实，不替 Screening 作最终判断。详细合同见 `references/screening-handoff.md`。

## 每批怎么跑

1. 默认每批找 **100 个新的候选项目**；先与历史项目池去重，并给本批一个批次 ID。100 是工作批次大小，不限制后续继续扩批。
2. 优先从 Toolify、There’s An AI For That、TrustMRR 找近期项目；需要扩量时可以增加同类来源。记录每个来源的新增量，避免长期由单一来源主导项目池。
3. 如果 Semrush 当前不可用，可以继续核真实 Website 并进入内部 `pending_semrush`；写入当前 `项目池` 时使用 `待Semrush` / `待Semrush筛选`，到这里停止该项目的 SEO/RD 推进，不生成未知字段。
4. 在已登录 `sem.3ue.com` 的 Backlink Analytics 页面加载固定 runner；runner 自动恢复/验证 session key，再做双接口 Preflight。
5. 批量查 Semrush Global Organic Traffic；默认 `>= 500` 才进入 Referring Domains 抓取。国家流量读取 `databases.<country>`。
6. 对通过项目抓 Referring Domains；默认根据 `refdomains.total` 自动分页抓完整。如果明确配置了抓取上限，必须保留 complete/partial 状态。
7. 保存原始事实：来源项目、Organic 状态/流量、referring domain、backlinks_num、AS、first_seen、last_seen、lost/new、is_follow。
8. 按 referring domain 聚合成功项目覆盖数和出现次数；记录它在 BacklinkOS 中是首次出现还是历史已见。
9. 把 domain-level 候选交给 `screening-backlinks`。Discovery 的默认阶段到此结束。
10. 如果 Screening 返回 `source_url_enrichment_required`，按 `references/screening-handoff.md` 仅对请求的 referring domain / source projects 补充精确来源页事实，再把事实返回 Screening。

## Source URL enrichment

按需 enrichment 可传递：

`source_url | source_title | target_url | anchor | source_page_ascore | source_rel_observation | source_first_seen | source_last_seen`

优先复用当前同源技术采集、已保存 sanitized capture/result 或允许的已登录 Semrush 网站原生 Backlinks 导出。**不得因为知道某个 Backlinks endpoint 名称，就把它写成已验证 relay 请求。** 只有 exact request 实际 HTTP 200、认证/参数/响应结构（以及需要时的分页）都验证后，才可升级 `references/semrush-relay.md` 的正式契约。

## Semrush runner 的失败处理

- Session key 自动恢复失败或 Preflight 失败：整批停止；使用 runner 自动下载的脱敏 diagnostic JSON 排查。不要再让用户手工截图、复制 Network 请求、粘贴 key 或逐个试参数。
- `no_data`：保留为 Semrush 无 Organic 估值，不进入 errors，不进入 `>=500` 项目。
- `http_error` / `schema_error` / `session_error` / `pagination_error`：作为真实错误记录并处理；不得与 `no_data` 混淆。
- runner/契约如需更新，必须先复用历史成功证据；确有缺口时才用最小样例重新实际验证 HTTP 200 + 预期结构，再修改 `references/semrush-relay.md` 和回归测试。

## 输出

Domain-level handoff 至少传递：

`referring_domain | source_projects | successful_project_count | occurrence_count | source_project_organic_traffic | backlinks_num | domain_ascore | first_seen | last_seen | semrush_is_follow | discovery_source | batch_id | first_discovered_at | seen_before`

按需 source-page enrichment 追加：

`source_url | source_title | target_url | anchor | source_page_ascore | source_rel_observation | source_first_seen | source_last_seen`

项目层至少保留：

`domain | organic_status | organic_traffic | organic_traffic_by_db | qualified | referring_domains_total | referring_domains_fetched | rd_complete`

Semrush 尚未执行的已核实项目内部使用 `pending_semrush`；当前 `项目池` 落表映射为 `SEO筛选状态=待Semrush`、`RD状态=待Semrush筛选`，Organic / qualification / RD 未知字段保持空白。

不知道的字段留空，不生成“可能”“大概”“推测”值。

Semrush 中转细节见 [references/semrush-relay.md](references/semrush-relay.md)。Discovery→Screening 精确补证合同见 [references/screening-handoff.md](references/screening-handoff.md)。事故复盘见 [references/incidents/2026-08-21-semrush-relay-debugging.md](references/incidents/2026-08-21-semrush-relay-debugging.md)。正式执行器见 [scripts/semrush-relay-batch.js](scripts/semrush-relay-batch.js)。回归要求见 [references/test-cases.md](references/test-cases.md)。
