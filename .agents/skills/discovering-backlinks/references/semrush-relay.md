# Semrush 中转

只在需要批量查询 Organic Traffic 或 Referring Domains 时读取本文件。

## 固定路线

Semrush 查询固定优先走已经跑通的 `sem.3ue.com` 中转。**禁止**因为官方 Semrush API units 不足而停止，也**禁止**改走需要 API units 的官方 Semrush API/connector。

中转依赖用户浏览器里已登录的 `sem.3ue.com` 同源会话。正式执行器固定使用：

`../scripts/semrush-relay-batch.js`

不要在聊天里重新发明另一套请求参数、分页或 session key 获取办法；除非回归测试证明当前契约失效。

完整事故复盘见：

`incidents/2026-08-21-semrush-relay-debugging.md`

后续改 runner / 契约前必须先读该文件。

## 已验证请求契约（2026-08-21）

以下请求均已在真实 `sem.3ue.com` 登录会话中实际返回 HTTP 200，并核对响应结构。

### 1. Organic Traffic

```text
GET /analytics/backlinks/webapi2/organic-traffic
  ?domain=<root-domain>
  &key=<current-session-key>
  &_=<timestamp>
```

已验证：

- `domain=obby.fun` 曾返回 `organic_traffic=187`；
- `databases.us=139`；
- `target + target_type` 形式返回 400；
- `action=report + target + target_type` 返回 400；
- `type=organic-traffic + target + target_type` 返回 400；
- 加 `db=us` 不会把顶层 `organic_traffic` 改成 US 流量；
- 不带有效 `key` 时实际返回过 400/403，因此不能只依赖 Cookie。

字段语义固定为：

- `organic_traffic`：Global / 返回数据库合计层面的 Organic Traffic；
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

响应结构：

```text
status = SUCCESS
refdomains.total
refdomains.limit
refdomains.offset
refdomains.data[]
```

`refdomains.data[]` 已确认包含：

`domain | backlinks_num | first_seen | last_seen | ip | country | domain_ascore | category | lost | new | is_follow`

分页使用 `display_page=0,1,2...`。2026-08-21 已对 `vectosolve.com` 实际完成 5 页抓取：`reported_total=484`、`fetched_unique=484`、`complete=true`。因此执行器必须依据 `refdomains.total` 自动分页到完整；如果人为设置上限，输出必须明确标记 partial。

## 强制 Preflight

每次正式批量前必须先对一个已知域名做双接口预检：

1. Organic：HTTP 200，并得到 `value` 或合法 `no_data`；
2. Referring Domains：HTTP 200、`status=SUCCESS`、`refdomains.data` 为数组。

任一失败，**整批立即停止**，并自动下载脱敏 diagnostic JSON。禁止在契约错误时继续把整批域名打成 400/403。

## Session key 恢复规则

真实请求中的 session key 当前观察为 **32 位十六进制值**。正式 runner 只允许按下列顺序恢复并验证：

1. 当前页面内存中已验证的 `window.__BACKLINKOS_SEM_KEY`；
2. `performance` 中仍保留的 Backlink Analytics 请求；
3. localStorage / sessionStorage / cookie / inline script 中符合 32-hex 形态的候选；
4. 当 `performance=[]` 时，对当前运行时做**有界扫描**，只收集符合 32-hex 形态的候选；
5. 每个候选必须用已验证 Organic 接口实际返回 HTTP 200 后才可使用。

禁止：

- 把任意 storage 值都当成 key 逐个请求；
- 把 key 打印到 Console、聊天、下载文件、Git 或 Sheet；
- 因为 `performance=[]` 就重新让用户抓 Network、手抄 key 或猜参数。

若所有自动恢复路径都失败，runner 只输出脱敏 diagnostic JSON 并停止。此时处理登录/会话问题，而不是重新猜接口。

## Console 上下文规则

Console 注入代码属于当前页面 JS context。**页面导航会销毁这个 context。**

因此：

- 不能“先安装 fetch/XHR hook，再导航到另一个 Backlink Analytics 页面”；
- runner 必须直接在最终目标页面运行；
- 如果需要跨导航捕获，必须使用正式持久化方案，不能靠临时 Console hook；
- 不得再次把“导航后 hook 消失”误判成接口异常。

## 历史证据复用规则

任何异常出现时，先依次检查：

1. 本文件的已验证契约；
2. 当前正式 runner；
3. 已保存的 sanitized capture / result JSON；
4. 回归测试样例。

只有这些证据确实不足或已经失效时，才允许做新的最小探测。**不得让用户重复已经做过的抓包/截图。**

## 已验证与推断的边界

只有精确请求实际 HTTP 200 + 响应结构符合预期，才能称“已验证”。

- bundle 里的 endpoint 名称只是线索；
- page0 成功不能自动推出 page1 已验证；
- 分页只有在 page1+ 实际返回新数据且 offset/unique rows 推进后才算验证；
- 完整抓取必须用 `reported total` 与本地 unique rows 对账。

禁止把尚未实际验证的部分描述为“接口已经全部破解/解决”。

## 状态模型

Organic 至少区分：

- `value`：HTTP 200 且返回数值 `organic_traffic`；
- `no_data`：HTTP 200，但 Semrush 没有返回 `organic_traffic`；
- `http_error`：非会话型 4xx/5xx；
- `session_error`：401/403 或无法恢复有效 session key；
- `schema_error`：HTTP 成功但结构异常。

`no_data` 不计入 errors。

## 批量顺序

1. 准备整批候选域名并去重。
2. 自动恢复并验证 session key。
3. 双接口 Preflight。
4. 批量查 Global Organic Traffic。
5. 默认只对 `organic_traffic >= 500` 的项目抓 Referring Domains。
6. Referring Domains 默认按 `total` 自动分页抓完整；若配置上限，必须标记 partial。
7. 原始结果先保存，再做 referring domain 去重与聚合。
8. 原始事实交给 `screening-backlinks`；中转层不判断免费/付费或项目适配。

## 会话与安全

`key`、cookie、session 参数、`__gmitm` 或类似凭证都不得写进：

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
