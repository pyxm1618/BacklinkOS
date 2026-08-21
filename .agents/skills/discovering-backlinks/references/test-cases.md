# 回归测试

以下行为必须成立：

1. 用户说“帮我抓外链”或“继续扩大外链库”时触发 `discovering-backlinks`。
2. 需要 Semrush 时固定优先使用已经跑通的 `sem.3ue.com` 中转；即使官方 Semrush API units 不足，也不得停止任务或改走需要 API units 的官方 API/connector。
3. 中转会话失效时，只处理登录/会话问题后继续中转，不把 API units 当成解决路径。
4. 禁止把从前端 bundle 里发现的 endpoint 名称直接当成已验证请求。只有真实 HTTP 200 且响应结构符合预期，才能进入 `semrush-relay.md` 的“已验证请求契约”。
5. 正式 Semrush 批量必须使用 `scripts/semrush-relay-batch.js`，不得每次在聊天中重新猜请求参数、分页或 key 获取逻辑。
6. 批量启动前必须自动恢复并验证 session key，然后做双接口 Preflight；任一步失败时整批停止，并自动产生脱敏 diagnostic JSON。
7. Session key 恢复不能只依赖 `performance`。当 `performance=[]` 时，runner 必须继续走已验证 32-hex 候选扫描 + 有界运行时扫描。
8. 禁止把任意 localStorage/sessionStorage/cookie 值都当成 key 逐个试请求；只允许验证符合已观察 key 形态的候选。
9. runner 不得要求用户把真实 key 粘贴到聊天，也不得把 key 打印、落盘或写入 Git/Sheet。
10. Organic Traffic 固定使用 `domain=<root-domain>` 请求；不得改成 `target + target_type`、`action + target` 或其他未重新验证的形式。
11. Organic 返回 HTTP 200 但缺少 `organic_traffic` 时，必须记为 `no_data`；不得记成 0，也不得计入 `errors`。
12. `organic_traffic` 表示 Global / 返回数据库合计层面的流量；`databases.us` 等国家字段才表示国家流量。不得因为 query 中出现 `db=us` 就把顶层值解释成 US 流量。
13. Referring Domains 固定使用 `type=backlinks_refdomains`、`target_type=root_domain` 和 0-based `display_page`。
14. Referring Domains 必须根据 `refdomains.total` 判断是否抓完整。若人为设置抓取上限，必须明确输出 partial；不得把“前 300 条”写成完整结果。
15. 分页时如果 offset 不推进或新页没有新增 referring domain，必须报 `pagination_error`，不能静默当成完成。
16. runner 输出中不得包含真实 `key`、cookie、`__gmitm` 或其他会话凭证。
17. Discovery 没有亲自验证 `free`、`submit_url`、当前免费渠道 `Follow` 时，不输出这些字段的猜测值。
18. Semrush `is_follow=true` 只能输出为历史 Follow 事实，不能改写成“当前免费提交一定 Follow”。
19. 不因为目标项目是 Quick I Ching、AI、非 AI 或其他行业而过滤候选。
20. 已经在 BacklinkOS 见过的 referring domain 再次出现时标记为历史已见，并增加新的成功项目证据；不能伪装成本轮首次发现。
21. `first_seen` 不得表述为精确建链日期。
22. Discovery 不判断免费/付费、当前提交入口或最终是否入库；这些必须交给 `screening-backlinks`。
23. runner 最终 summary 至少分别报告：`organic_value`、`organic_no_data`、真实错误数、合格项目数、RD complete/partial 项目数、raw RD rows、unique referring domains。
24. 已验证结构样例：`obby.fun` 的 Organic 请求曾返回 Global 187 / US 139；其 Referring Domains 请求曾返回 total 115、page0 100 rows。该样例只用于结构回归，不作为永久业务数据。
25. 已验证分页样例：`vectosolve.com` 在 2026-08-21 实际完成 5 页，`reported_total=484`、`fetched_unique=484`、`complete=true`。此结果用于证明自动分页链路，而不是固定业务常量。
26. 如果当前页面 `performance=[]`，不得直接判定登录态/接口失效；必须继续走正式 session 恢复逻辑。
27. 如果需要 Console hook，必须在最终目标页面安装并使用；测试不得设计成“安装 hook -> 导航 -> 期待 hook 仍存在”，因为导航会重建 JS context。
28. 调试时必须先搜索仓库契约、runner、历史 sanitized capture/result；只要历史证据足够，就不得让用户重复抓 Network、截图或重新提供已经给过的数据。
29. page0 真实 HTTP 200 只能证明 page0；在 page1+ 未实际返回新 rows/offset 推进前，不得宣称分页已验证。
30. 临时探测代码不得直接扩展到整批。任何新请求形态必须先用 1 个域名做最小验证，确认 HTTP 200 + 结构后才能批量。
31. 长 Console runner 在交给用户前必须至少通过 JS 语法检查与最小启动检查；不得把语法错误留给用户发现。
32. 不得使用“接口已经全部破解/全部解决”这类表述，除非 method、参数、认证、响应结构、分页和完整性都已经分别实际验证。
33. 2026-08-21 的调试事故规则以 `references/incidents/2026-08-21-semrush-relay-debugging.md` 为强制回归基线；后续修改不得删除这些约束，除非有新的真实证据替代。
