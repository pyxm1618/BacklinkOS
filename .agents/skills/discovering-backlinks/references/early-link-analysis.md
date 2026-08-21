# first_seen 与早期外链

## 语义边界

Semrush `first_seen` 表示 **Semrush 第一次观察到这条/这个来源外链的时间**。

它不是：

- 精确建链时间
- 发布页面真实创建时间
- 项目上线时间
- 外链产生因果的证明

因此只把它用于**相对时间信号和排序**。

## 项目参考日期

计算早期外链前必须有项目参考日期，并保留日期类型：

优先级：

1. `launch_date`：官方/产品明确上线日期
2. `founded_date`：成立日期；仅在产品上线时间接近时可辅助
3. `source_listing_date`：Toolify/TAAFT 等最近收录日期，只是代理日期
4. `discovered_at`：仅是我们发现日期，不能用于计算早期外链

如果只有 `discovered_at`，不要计算 early rate。

## 默认 90 天规则

当参考日期足够可信时：

`days_from_reference = first_seen_date - project_reference_date`

- `0 <= days <= 90` → `early_90d=true`
- `days > 90` → `early_90d=false`
- `days < 0` → 不要直接算 early；标记 `pre_reference`，说明项目可能早于目录收录/参考日期
- 任一日期缺失或不可靠 → `early_90d=未确认`

不要把未确认写成 false 或 0。

## 聚合

对每个 referring domain 统计：

- `eligible_early_projects`：有可用参考日期的成功项目数
- `early_90d_count`
- `early_90d_rate = early_90d_count / eligible_early_projects`

只有 `eligible_early_projects > 0` 才计算比例。

## 使用方式

时间信号用于回答：

> 这个来源是否经常在成功新站的早期阶段出现？

优先级通常高于“成功后很久才出现”的媒体报道或自然提及，但仍需 `screening-backlinks` 验证当前是否可复制。
