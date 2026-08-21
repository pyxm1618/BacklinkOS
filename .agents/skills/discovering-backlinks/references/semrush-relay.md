# Semrush 中转

只在需要批量查询 Organic Traffic 或 Referring Domains 时读取本文件。

## 已验证路线

优先复用已经跑通的 `sem.3ue.com` 中转，不因为官方 Semrush API units 不足而停止。

已验证过的中转页面/接口路线包括：

- `/kwogw/v2/webapi`
- `/analytics/organic/overview`
- `/analytics/backlinks/refdomains`

历史批量运行已经成功完成约 100 个候选项目的 Organic Traffic 筛选，并对通过项目批量抓取 Referring Domains。

## 批量顺序

1. 一次准备整批候选域名。
2. 先批量查 Organic Traffic。
3. 只对达到门槛的项目抓 Referring Domains。
4. Referring Domains 分页抓取；保留原始字段，不在中转层做 Screening 判断。
5. 原始结果先保存，再做去重与聚合。

## 会话

中转依赖已登录会话。会话失效时，只刷新登录/会话后继续，不改走需要额外 API units 的官方 API。

任何 key、cookie、session 参数、`__gmitm` 或类似凭证都不得写进 Git、表格、日志或聊天回复。

## 字段语义

- `first_seen`：Semrush 首次观察到该 backlink 的时间。
- `last_seen`：Semrush 最近观察时间。
- `is_follow`：Semrush 对历史 backlink 的 Follow 观察。
- `domain_ascore`：Semrush Authority Score，不等同 Ahrefs DR。

这些字段都是 Discovery 事实；Screening 不重新查询它们。
