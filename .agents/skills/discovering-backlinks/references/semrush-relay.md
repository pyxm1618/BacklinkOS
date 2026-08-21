# Semrush 中转

只在需要批量查询 Organic Traffic 或 Referring Domains 时读取本文件。

## 固定路线

Semrush 查询固定优先走已经跑通的 `sem.3ue.com` 中转。**禁止**因为官方 Semrush API units 不足而停止，也**禁止**改走需要 API units 的官方 Semrush API/connector。

历史批量运行已经真实成功完成过批量 Organic Traffic 查询，并对通过项目批量抓取 Referring Domains；结果文件中包含 `traffic`、`refdomains.total`、`refdomains.data`、`first_seen`、`last_seen`、`domain_ascore`、`is_follow` 等字段。

## 重要：不要伪造“已验证请求”

当前仓库和已保存结果里**没有保存当时成功批处理的完整 Console 执行脚本/精确请求契约**。因此：

- 不得根据前端 JS 中出现的 endpoint 名称自行猜 GET/POST、参数名、query/body 或分页格式；
- 不得把“从 bundle 中发现的 endpoint”写成“已验证可直接调用的请求”；
- 只有实际返回 200 且返回结构与历史成功结果一致的请求，才能升级为已验证请求；
- 一旦重新恢复成功批处理脚本，必须把完整可执行脚本及其最小测试样例保存进本仓库，避免再次丢失。

已确认可访问的页面/中转路线包括：

- `/analytics/organic/overview`
- `/analytics/backlinks/refdomains`
- `/kwogw/v2/webapi`（Keyword Overview 的 JSON-RPC；不要与 Organic Traffic / Referring Domains 的请求契约混为一谈）

## 批量顺序

1. 一次准备整批候选域名。
2. 先批量查 Organic Traffic。
3. 只对达到门槛的项目抓 Referring Domains。
4. Referring Domains 分页抓取；保留原始字段，不在中转层做 Screening 判断。
5. 原始结果先保存，再做去重与聚合。

## 会话

中转依赖用户浏览器里已登录的 `sem.3ue.com` 同源会话。

若当前页面 URL 含 `__gmitm`，执行器只在内存里复用该值，不把它写入下载结果、Git、表格、日志或聊天回复。

会话失效时，只刷新登录/会话后继续，不改走需要额外 API units 的官方 API。

任何 key、cookie、session 参数、`__gmitm` 或类似凭证都不得写进 Git、表格、日志或聊天回复。

## 字段语义

- `first_seen`：Semrush 首次观察到该 backlink 的时间。
- `last_seen`：Semrush 最近观察时间。
- `is_follow`：Semrush 对历史 backlink 的 Follow 观察。
- `domain_ascore`：Semrush Authority Score，不等同 Ahrefs DR。

这些字段都是 Discovery 事实；Screening 不重新查询它们。
