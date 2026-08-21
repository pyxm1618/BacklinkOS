# Semrush 中转

只在需要批量查询 Organic Traffic 或 Referring Domains 时读取本文件。

## 固定路线

Semrush 查询固定优先走已经跑通的 `sem.3ue.com` 中转。**禁止**因为官方 Semrush API units 不足而停止，也**禁止**改走需要 API units 的官方 Semrush API/connector。

历史批量运行已经成功完成约 100 个候选项目的 Organic Traffic 筛选，并对通过项目批量抓取 Referring Domains。

## 已验证请求

### Organic Traffic

同源浏览器会话内请求：

`/analytics/backlinks/webapi2/organic-traffic?domain=<DOMAIN>&type=organic-traffic`

### Referring Domains

同源浏览器会话内请求：

`/analytics/backlinks/webapi2/?action=report&type=backlinks_refdomains&target=<DOMAIN>&target_type=root_domain&display_page=<PAGE>&sort_field=backlinksnum&sort_type=desc`

- `display_page` 从 0 开始。
- 每页通常返回 100 条。
- 默认先抓 3 页，即最多 300 条；需要继续时再翻页。

页面路线仍可用于人工核验：

- `/analytics/organic/overview`
- `/analytics/backlinks/refdomains`
- `/kwogw/v2/webapi`

## 批量顺序

1. 一次准备整批候选域名。
2. 先批量查 Organic Traffic。
3. 只对达到门槛的项目抓 Referring Domains。
4. Referring Domains 分页抓取；保留原始字段，不在中转层做 Screening 判断。
5. 原始结果先保存，再做去重与聚合。

## 会话

中转依赖用户浏览器里已登录的 `sem.3ue.com` 同源会话。执行代码应直接在该页面 Console 中运行，通过同源 `fetch(..., {credentials: "include"})` 复用当前登录状态。

若当前页面 URL 含 `__gmitm`，执行器只在内存里复用该值，不把它写入下载结果、Git、表格、日志或聊天回复。

会话失效时，只刷新登录/会话后继续，不改走需要额外 API units 的官方 API。

任何 key、cookie、session 参数、`__gmitm` 或类似凭证都不得写进 Git、表格、日志或聊天回复。

## 字段语义

- `first_seen`：Semrush 首次观察到该 backlink 的时间。
- `last_seen`：Semrush 最近观察时间。
- `is_follow`：Semrush 对历史 backlink 的 Follow 观察。
- `domain_ascore`：Semrush Authority Score，不等同 Ahrefs DR。

这些字段都是 Discovery 事实；Screening 不重新查询它们。
