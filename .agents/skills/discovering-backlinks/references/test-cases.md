# 回归测试

以下行为必须成立：

1. 用户说“帮我抓外链”或“继续扩大外链库”时触发 `discovering-backlinks`。
2. 需要 Semrush 时固定优先使用已经跑通的 `sem.3ue.com` 中转；即使官方 Semrush API units 不足，也不得停止任务或改走需要 API units 的官方 API/connector。
3. 中转会话失效时，只处理登录/会话问题后继续中转，不把 API units 当成解决路径。
4. **禁止把从前端 bundle 里发现的 endpoint 名称直接当成已验证请求。** 未实际返回 200 且未得到预期结构前，不得猜 HTTP 方法、参数名、query/body 或分页规则并写进 Skill。
5. 一旦某个批量 Semrush 请求重新跑通，必须把完整可执行脚本和最小测试样例保存进仓库，不能只保存结果 JSON。
6. Discovery 没有亲自验证 `free`、`submit_url`、当前免费渠道 `Follow` 时，不输出这些字段的猜测值。
7. Semrush `is_follow=true` 只能输出为历史 Follow 事实，不能改写成“当前免费提交一定 Follow”。
8. 不因为目标项目是 Quick I Ching、AI、非 AI 或其他行业而过滤候选。
9. 已经在 BacklinkOS 见过的 referring domain 再次出现时标记为历史已见，并增加新的成功项目证据；不能伪装成本轮首次发现。
10. `first_seen` 不得表述为精确建链日期。
11. Discovery 不判断免费/付费、当前提交入口或最终是否入库；这些必须交给 `screening-backlinks`。
