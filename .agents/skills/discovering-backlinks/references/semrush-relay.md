# Semrush 中转运行参考

## 原则

BacklinkOS 已经实际用 Semrush 中转完成过批量查询。**官方 Semrush API units 不足时，不要把它误判为整个 Semrush 数据链路不可用。**

当前已验证中转 origin 为 `sem.3ue.com`。会话参数属于敏感运行态数据，不写入 Skill。

## 已确认页面/接口线索

历史发现文件确认过这些 Semrush 页面路由：

- Organic Overview：`/analytics/organic/overview`
- Organic Positions：`/analytics/organic/positions`
- Referring Domains：`/analytics/backlinks/refdomains`
- Backlinks：`/analytics/backlinks/backlinks`
- Keyword Overview JSON-RPC：`/kwogw/v2/webapi`

域名 Organic Traffic / Referring Domains 的实际请求结构可能随前端更新改变。优先从当前中转页面的网络请求恢复，而不是猜接口。

## 运行前恢复中转

1. 在用户文件库查找 `semrush-keyword-overview-rpc-discovery.json`、历史 batch result 或最新中转运行文件。
2. 读取 origin、页面路由、已验证请求形态；**不要把敏感参数显示给用户或写入日志**。
3. 如果当前会话仍有效，复用当前会话。
4. 如果返回登录页、401/403、空壳 HTML 或明显认证失败，判定“中转会话失效”。
5. 会话失效时请求用户提供刷新后的中转页面/会话，而不是购买官方 API units。

## 两阶段批处理

### A. Organic Traffic 预筛

对候选域名批量查询 Organic Traffic，只保存：

- domain
- organic_traffic
- query_status
- checked_at

默认 `>= 500` 进入下一阶段。

### B. Referring Domains

对通过项目分页获取。历史结果已经验证每页 `limit=100` 的结构，并返回：

- `domain` / source domain
- `backlinks_num`
- `first_seen`
- `last_seen`
- `domain_ascore`
- `country`
- `category`
- `lost`
- `new`
- `is_follow`

保留原始 Unix timestamp；展示时再转换日期。

## 批量安全

- 使用有界批量/并发，不做无限并发。
- 复用已验证的 pacing；没有证据时不要激进提速。
- 对临时网络失败做小次数重试；认证失败不重试轰炸。
- 每个域名单独记录错误，不能因为一个域名失败丢掉整批结果。
- 支持断点续跑：已成功项目不要重复抓。

## 凭证安全

任何时候都不要输出、持久化或提交：

- 中转 key
- cookie
- `__gmitm`
- session token
- 完整含凭证 URL
- 浏览器认证头

Skill / Git / Google Sheet / Feishu 只能保存**非敏感的运行方法和结果**。

## 已验证历史基线

此前一轮实际运行：

- 98 个候选项目
- 25 个达到 Organic Traffic 门槛
- 6,424 条 Referring Domain 记录
- 3,984 个唯一来源域名
- 明显垃圾过滤后 3,628 个
- 运行错误 0

这证明“中转 + 批量预筛 + 合格项目抓 RD”是已验证路径，不是理论方案。
