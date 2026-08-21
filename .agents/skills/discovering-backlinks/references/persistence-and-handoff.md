# 持久化与 Screening 交接

## 职责边界

`discovering-backlinks` 负责：

- 找项目
- 判断是否达到当前成功项目门槛
- 抓历史 Referring Domains
- 聚合重复/时间信号
- 生成候选和证据

`screening-backlinks` 负责：

- 当前是否还能发布
- 注册/登录/审核要求
- 免费 / 部分免费 / 付费
- 实际发布入口
- 同类型最终 HTML 的 Dofollow/Nofollow
- DR / 域龄 /必要的流量证据
- A/B/C/D/F
- 最终可执行记录

Historical backlink ≠ current reproducibility。

## “帮我抓外链”的默认解释

用户说“帮我抓外链”“继续抓”“扩大外链库”时，默认完成：

`Discover → 对高价值候选调用 screening-backlinks → Persist`

如果用户明确只要候选发现，停在 Discovery。

如果用户明确说“审核/筛选这批外链”，不要重新跑 Discovery，直接使用 `screening-backlinks`。

## 在线主库

优先复用现有 BacklinkOS 在线主库，不为每轮创建新 Excel。

当前发现库使用 Google Sheets 时，按标题 `BacklinkOS_外链发现数据库_主库` 搜索并复用；如果项目配置提供稳定 ID，以配置为准。

建议工作表：

- `发现源`
- `项目池`
- `免费外链机会`
- `已排除付费`
- `运行记录`
- `验证说明`

不要把会话凭证写入任何表。

## 项目池最小字段

- domain
- discovery_source
- source_url
- source_listing_date
- project_reference_date
- reference_date_type
- organic_traffic
- qualified
- referring_domains_total
- referring_domains_fetched
- checked_at
- status/error

## 发现机会最小字段

- referring_domain
- successful_project_count
- occurrence_count
- max_as
- follow_count
- follow_rate
- early_90d_count
- eligible_early_projects
- early_90d_rate
- example_projects
- discovery_status
- screening_status
- last_checked_at

## 写入纪律

- 先按 canonical domain / placement key 去重，再 upsert。
- 写入动作必须得到目标系统成功响应后才能说“已保存/已写入”。
- 连接不可用时保留结构化待写入记录并标记 `persistence_pending`。
- 不用 Excel 作为长期主库；Excel 只作为导出/备份。
