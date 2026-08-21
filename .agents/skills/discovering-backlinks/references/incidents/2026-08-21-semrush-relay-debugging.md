# 2026-08-21 Semrush 中转调试复盘

本文件不是教程，而是**防止再次犯同类错误的事故记录**。任何后续修改 `semrush-relay-batch.js`、`semrush-relay.md` 或相关抓取逻辑时都必须先读。

## 已发生的错误

1. 根据前端 bundle 里的 endpoint 名称直接猜请求参数，导致 Organic 批量 27 个域名全部 HTTP 400。
2. 在 Referring Domains page0 已验证后，过早把分页也称为“已解决”；实际 `display_page=1+` 当时尚未独立验证。
3. 把 HTTP 200 但缺少 `organic_traffic` 的合法 no-data 响应记成 error。
4. 只从 `performance.getEntriesByType('resource')` 取 session key；页面后来出现 `performance=[]`，runner 失效。
5. 曾把任意 localStorage/sessionStorage/cookie 值当成 key 候选逐个请求，产生大量无意义 403。
6. 在 Console 注入拦截器后又让用户导航页面；导航会重建 JS context，注入代码因此消失。
7. 已有成功抓包/成功 JSON 可以复用时，没有先检索历史证据，反而再次要求用户手工抓取。
8. 临时代码未先做最小语法/执行预检，就直接让用户粘贴长 runner。
9. 对已经验证的事实和仅来自 bundle/推断的事实没有始终保持同一严格等级。

## 永久规则

### A. 证据等级

只有满足以下条件才能写成“已验证”：

- 精确 method/path/params 实际请求；
- HTTP 200；
- 响应结构符合预期；
- 如果涉及分页，至少实际成功取得 page1 且确认 offset/新增数据推进；
- 如果涉及完整抓取，必须以 provider 的 `total` 与本地 unique rows 对账。

前端 bundle、字符串、UI 文案、历史相似接口都只能作为**定位线索**，不能升级为请求契约。

### B. 先复用历史成功证据

任何接口异常前，先检查：

1. 仓库 `references/semrush-relay.md`；
2. runner 当前版本；
3. 已保存的成功 sanitized capture / result JSON；
4. 回归测试样例。

只有历史证据确实不足或已失效，才进入新的最小探测。不得让用户重复已经完成过的抓包。

### C. Session key

- Cookie 单独不足；当前真实请求需要有效 `key`。
- `performance` 不是唯一来源。
- 当前观察到的 key 形态为 32 位 hex；只能把符合该形态的值当候选，并且候选必须通过真实 Organic 请求验证。
- 禁止把任意 storage 值逐个当 key 试。
- 禁止打印、持久化或要求用户粘贴真实 key。
- 自动恢复失败时只生成脱敏 diagnostic 并停止，不重新猜接口。

### D. Console 上下文

浏览器页面导航会销毁当前 Console 注入的 JS context。

因此：

- 在目标页面运行 runner 后，不得通过“先注入、再导航”完成捕获；
- 必须在最终目标页面安装/运行；
- 如果确实需要跨导航持久化，必须使用正式持久方案，而不是临时 Console hook。

### E. Organic 状态

必须严格区分：

- `value`：200 + 数值 `organic_traffic`；
- `no_data`：200，但没有 `organic_traffic`；
- `session_error`：401/403 或 session key 无效；
- `http_error`：其他非成功 HTTP；
- `schema_error`：HTTP 成功但响应结构异常。

`no_data` 不能记 0，也不能计入 errors。

### F. Referring Domains 分页

- `display_page` 为 0-based；
- 使用 `total / limit / offset` 做完整性校验；
- page1+ 必须产生新 referring domains；
- offset 不推进、页面重复或新增数为 0 时必须报 pagination error；
- 不允许把固定 300 条写成完整抓取。

已验证完整样例：2026-08-21 `vectosolve.com` 完成 5 页，`reported_total=484`、`fetched_unique=484`。

### G. 正式执行方式

正式批量只使用：

`../scripts/semrush-relay-batch.js`

聊天中不再临时重写 runner。任何契约变更必须：最小验证 -> 更新 runner -> 更新 `semrush-relay.md` -> 更新 `test-cases.md`。

## 安全

任何真实 `key`、cookie、`__gmitm`、session/token：

- 不写 Git；
- 不写 Google Sheet；
- 不写下载结果；
- 不写日志；
- 不在聊天中复述。
