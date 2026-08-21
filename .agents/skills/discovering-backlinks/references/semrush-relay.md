# Semrush 中转

只在需要批量查询 Organic Traffic 或 Referring Domains 时读取本文件。

## 固定路线

Semrush 查询固定优先走已经跑通的 `sem.3ue.com` 中转。**禁止**因为官方 Semrush API units 不足而停止，也**禁止**改走需要 API units 的官方 Semrush API/connector。

中转依赖用户浏览器里已登录的 `sem.3ue.com` 同源会话。正式执行器固定使用：

`../scripts/semrush-relay-batch.js`

不要在聊天里重新发明另一套请求参数；除非回归测试证明当前契约失效。

## 已验证请求契约（2026-08-21）

以下请求均已在真实 `sem.3ue.com` 登录会话中实际返回 HTTP 200，并核对了响应结构。

### 1. Organic Traffic

```text
GET /analytics/backlinks/webapi2/organic-traffic
  ?domain=<root-domain>
  &key=<current-session-key>
  &_=<timestamp>
```

必要参数是 `domain`。已验证：

- `domain=obby.fun` 返回 `organic_traffic=187`；
- `databases.us=139`；
- `target + target_type` 形式会返回 400；
- `action=report + target + target_type` 会返回 400；
- `type=organic-traffic + target + target_type` 会返回 400；
- 加 `db=us` 不会把顶层 `organic_traffic` 改成 US 流量。

字段语义固定为：

- `organic_traffic`：Global Organic Traffic；
- `databases.<country>`：对应国家/地区的 Organic Traffic；
- HTTP 200 但缺少 `organic_traffic`：状态必须记为 `no_data`，**不是 0，也不是 API error**。

### 2. Referring Domains

```text
GET /analytics/backlinks/webapi2/
  ?action=report
  &type=backlinks_refdomains
  &target=<root-domain>
  &target_type=root_domain
  &display_page=<0-based-page>
  &sort_field=domain_ascore
  &sort_type=desc
  &key=<current-session-key>
  &_=<timestamp>
```

已验证响应：

```text
status = SUCCESS
refdomains.total
refdomains.limit
refdomains.offset
refdomains.data[]
```

`refdomains.data[]` 已确认包含：

`domain | backlinks_num | first_seen | last_seen | ip | country | domain_ascore | category | lost | new | is_follow`

分页是 `display_page=0,1,2...`，当前每页 `limit=100`。执行器必须依据 `refdomains.total` 判断完整性，不能把固定 300 条伪装成“抓完”。如果人为设置抓取上限，输出必须明确标记 `partial`。

## 强制 Preflight

每次正式批量前，执行器必须先对一个已知可返回数据的域名做双接口预检：

1. Organic：HTTP 200，并得到 `value` 或合法 `no_data` 状态；
2. Referring Domains：HTTP 200、`status=SUCCESS`、`refdomains.data` 为数组。

任一失败，**整批立即停止**，并自动下载脱敏 diagnostic JSON。禁止在契约错误时继续把整批域名打成 400。

## 状态模型

Organic 至少区分：

- `value`：HTTP 200 且返回数值 `organic_traffic`；
- `no_data`：HTTP 200，但 Semrush 没有返回 `organic_traffic`；
- `http_error`：4xx/5xx；
- `schema_error`：HTTP 成功但结构异常；
- `session_error`：无法取得当前 Backlink Analytics session key / 登录态失效。

`no_data` 不计入 errors。

## 批量顺序

1. 一次准备整批候选域名并去重。
2. Preflight。
3. 批量查 Global Organic Traffic。
4. 默认只对 `organic_traffic >= 500` 的项目抓 Referring Domains。
5. Referring Domains 默认按 `total` 自动分页抓完整；若配置了上限，必须标记 partial。
6. 原始结果先保存，再做去重与聚合。
7. 原始事实交给 `screening-backlinks`，中转层不判断免费/付费或项目适配。

## 会话与安全

执行器从当前页面已经发生过的 `/analytics/backlinks/webapi2` resource 中读取 `key`，只在内存中使用。

若当前页面 URL 含 `__gmitm`，也只能在内存中使用。

任何 `key`、cookie、session 参数、`__gmitm` 或类似凭证都不得写进：

- Git；
- 表格；
- 下载结果；
- 日志；
- 聊天回复。

所有 diagnostic / result JSON 必须脱敏。

## 字段语义

- `first_seen`：Semrush 首次观察到该 backlink 的时间，不是精确建链日期；
- `last_seen`：Semrush 最近观察时间；
- `is_follow`：Semrush 对历史 backlink 的 Follow 观察，不能写成“当前免费提交一定 Follow”；
- `domain_ascore`：Semrush Authority Score，不等同 Ahrefs DR。

这些字段都是 Discovery 事实；Screening 不重新查询它们。
