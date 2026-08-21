# 回归测试

以下行为必须成立：

1. 用户说“帮我抓外链”或“继续扩大外链库”时触发 `discovering-backlinks`。
2. 需要 Semrush 时固定优先使用已经跑通的 `sem.3ue.com` 中转；即使官方 Semrush API units 不足，也不得停止任务或改走需要 API units 的官方 API/connector。
3. 中转会话失效时，只处理登录/会话问题后继续中转，不把 API units 当成解决路径。
4. 禁止把从前端 bundle 里发现的 endpoint 名称直接当成已验证请求。只有真实 HTTP 200 且响应结构符合预期，才能进入 `semrush-relay.md` 的“已验证请求契约”。
5. 正式 Semrush 批量必须使用 `scripts/semrush-relay-batch.js`，不得每次在聊天中重新猜请求参数。
6. 批量启动前必须做双接口 Preflight；Organic 或 Referring Domains 任一失败时整批停止，并自动产生脱敏 diagnostic JSON。
7. Organic Traffic 固定使用 `domain=<root-domain>` 请求；不得改成 `target + target_type`、`action + target` 或其他未重新验证的形式。
8. Organic 返回 HTTP 200 但缺少 `organic_traffic` 时，必须记为 `no_data`；不得记成 0，也不得计入 `errors`。
9. `organic_traffic` 固定表示 Global；`databases.us` 等国家字段才表示国家流量。不得因为 query 中出现 `db=us` 就把顶层值解释成 US 流量。
10. Referring Domains 固定使用 `type=backlinks_refdomains`、`target_type=root_domain` 和 0-based `display_page`。
11. Referring Domains 必须根据 `refdomains.total` 判断是否抓完整。若人为设置抓取上限，必须明确输出 partial；不得把“前 300 条”写成完整结果。
12. runner 输出中不得包含真实 `key`、cookie、`__gmitm` 或其他会话凭证。
13. Discovery 没有亲自验证 `free`、`submit_url`、当前免费渠道 `Follow` 时，不输出这些字段的猜测值。
14. Semrush `is_follow=true` 只能输出为历史 Follow 事实，不能改写成“当前免费提交一定 Follow”。
15. 不因为目标项目是 Quick I Ching、AI、非 AI 或其他行业而过滤候选。
16. 已经在 BacklinkOS 见过的 referring domain 再次出现时标记为历史已见，并增加新的成功项目证据；不能伪装成本轮首次发现。
17. `first_seen` 不得表述为精确建链日期。
18. Discovery 不判断免费/付费、当前提交入口或最终是否入库；这些必须交给 `screening-backlinks`。
19. runner 最终 summary 至少分别报告：`organic_value`、`organic_no_data`、真实错误数、合格项目数、RD complete/partial 项目数、raw RD rows、unique referring domains。
20. 已验证基准样例：`obby.fun` 的 Organic 请求曾返回 Global 187 / US 139；其 Referring Domains 请求曾返回 total 115、page0 100 rows。此样例只用于回归结构验证，不作为永久业务数据。
