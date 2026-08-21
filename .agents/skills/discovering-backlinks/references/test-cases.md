# 回归测试

以下行为必须成立：

1. 用户说“帮我抓外链”或“继续扩大外链库”时触发 `discovering-backlinks`。
2. 官方 Semrush API units 不足时，优先使用已验证中转，不因此停止任务。
3. Discovery 没有亲自验证 `free`、`submit_url`、当前免费渠道 `Follow` 时，不输出这些字段的猜测值。
4. Semrush `is_follow=true` 只能输出为历史 Follow 事实，不能改写成“当前免费提交一定 Follow”。
5. 不因为目标项目是 Quick I Ching、AI、非 AI 或其他行业而过滤候选。
6. 已经在 BacklinkOS 见过的 referring domain 再次出现时标记为历史已见，并增加新的成功项目证据；不能伪装成本轮首次发现。
7. `first_seen` 不得表述为精确建链日期。
8. Discovery 不判断免费/付费、当前提交入口或最终是否入库；这些必须交给 `screening-backlinks`。
