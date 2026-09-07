---
name: screening-backlinks
description: Legacy / Optional. Use only when the user explicitly asks to 筛外链, 审核外链候选, 核验免费/Follow机会, or investigate the historical screening workflow. Do not insert this Skill as a default gate between discovery, Project Backlog Projection, and backlink-autofill.
---

# 筛外链（Legacy / Optional）

> **状态：Legacy / Optional。** 当前默认生产主链路是 `discovering-backlinks` → Master Upsert → Project Backlog Projection → Bounded Ready Preparation → `backlink-autofill`。本 Skill 只在用户明确要求旧式免费/Follow Screening、历史排查或专项核验时使用；它不决定普通 Master 候选是否能进入当前 Project Backlog。

## 目标

只判断一件事：**这个候选现在能不能免费获得一个有效的 Follow 外链。**

Discovery 已经传来的技术事实直接使用，不重新查询或改写；Screening 负责验证**当前机会机制**。

## 两个独立字段

不要把“怎么获得”和“最后怎么处理”混为一谈。

**获取方式**只允许四个值：

- `免费`
- `免费换链`
- `付费`
- `不确定`

**处理结果**只允许四个值：

- `正式机会`
- `付费排除`
- `回收`
- `待确认`

典型映射：

- 免费 + 当前 Follow + 可索引 → `正式机会`
- 免费换链 + 当前 Follow + 可索引 → `正式机会`
- 必须付款才能得到合格 Follow → `付费排除`
- 免费但最终 Nofollow/UGC/Sponsored、noindex、无外链、死亡/垃圾机制 → `回收`
- 关键事实无法闭环 → `待确认`

## 证据优先级

证据优先级必须**按正在判断的事实类型**使用，不能把一个来源等级机械套到所有事实。

- **获取方式 / 价格 / 资格条件**：当前实际提交流程优先，其次是当前官方 Submit / Pricing / FAQ / Terms；第三方与历史证据只作补充。
- **技术事实（`href`、`rel`、Follow/Nofollow、`noindex`、canonical）**：当前具体 listing/result 结果页的实际 HTML / DOM 是最高证据；当前同一路径、同模板的实际结果页次之。
- 对技术事实，能指向具体当前结果页并给出可复核 HTML/DOM 观察的第三方实测，可以高于泛化的官方营销/宣传文案；官方“Dofollow”宣传不能覆盖当前 listing 实测 `rel=nofollow`。
- Discovery 传来的历史 Semrush 观察低于所有当前机制和当前结果页证据；推断最低。

因此历史 `10/10 Follow` 不能覆盖当前 DOM 的 `rel=nofollow`；历史 `0 Follow` 也不能自动证明当前没有免费 Follow 路径。若官方宣传与当前第三方技术实测冲突、而当前 listing DOM 尚未取得，则保持 `待确认`，优先补当前结果页 DOM，不让任一低充分度证据强行胜出。

## 硬规则

1. **不做项目适配。** 不判断 Quick I Ching 或任何具体项目是否适合；只记录机会本身的限制。
2. 进入本 Legacy Screening 的“正式机会”结果必须同时满足：
   - 当前有普通用户可执行的入口；
   - 不需要付费；需要 reciprocal backlink 时归为 `免费换链`；
   - 最终公开页面有直接指向外站的链接；
   - 链接是 Follow：最终 `<a>` 不含 `nofollow`、`ugc`、`sponsored`；
   - 最终页面可被搜索引擎索引。
3. 必须付款才能得到合格 Follow → `获取方式=付费`、`处理结果=付费排除`，不是回收。
4. 免费路径最终 Nofollow/UGC/Sponsored、没有外部 URL、入口失效、页面 noindex、网站死亡或有闭环证据证明属于垃圾/恶意/卖链网络 → `处理结果=回收`。
5. 关键事实确实查不到 → 保留已确认的获取方式（无法确认时为 `不确定`），`处理结果=待确认`；不要编答案。
6. 不使用 A/B/C/D 作为业务评级。DR、流量、成功项目数、`first_seen` 只用于排序，不决定保留或淘汰。A/B/C/D 如存在，只能作为内部**解决路线**。
7. **用户明确要求本 Legacy Screening “继续”“全部执行”“筛完”“做完”时，默认进入该候选池的全量完成模式。** 不得处理十几条样本后自行停下并称阶段完成；必须持续处理当前指定候选池，直到 `待筛选=0`，或出现明确外部阻塞。
8. 若被外部阻塞而无法归零，必须明确报告剩余 `待筛选` 数；不得说“全部完成”。
9. **允许网络级批量判定，但证据必须闭环。** 只有同一批域名有可验证共同运营方、品牌、模板、机制、明确卖链行为或公开调查证据时，才允许用家族规则批量归类；不能只凭域名长得像垃圾站。
10. 网络级批量判定必须保留匹配规则、结论、原因、证据 URL、核验日期、适用范围。
11. **缺失事实不是负面事实。** “没找到入口/页面”本身不等于回收；AS=0、历史 0 Follow、历史 100% Follow 都不能单独决定当前处理结果。
12. 如果 domain-level 事实不足、但精确历史来源页可能帮助识别机制，可以按 Legacy contract 返回 `source_url_enrichment_required` 给 `discovering-backlinks`。
13. 迁移旧 Screening 运行表数据时遵守 target-first 安全写入：目标写入 → 回读确认 → 再清源数据；不得破坏 ARRAYFORMULA/公式列。
14. **本 Skill 的 `正式机会 / 回收 / 付费排除 / 待确认` 不得作为当前默认 Project Backlog admission gate。** 当前 Project Backlog 遵循 `UNKNOWN != REJECT`，只有明确 Master hard negative / project hard incompatibility 才阻止投影。

## 流程

1. 按“网站 + 外链形式 + 操作入口”去重；同一网站不同入口可以是不同机会。
2. 优先识别可被同一证据覆盖的网络/域名家族，批量处理有闭环证据的 PBN、卖链、自动垃圾页、Nofollow 网络，减少逐站重复劳动。
3. 对剩余独立候选找到当前真实操作入口。
4. 判断获取方式：免费 / 免费换链 / 付费 / 不确定。
5. 用**当前同一路径产生的公开页面**验证最终链接；先确定正在判断的是价格/资格还是 `rel`/indexability 等技术输出，再按对应证据优先级解决冲突。
6. 如果 exact historical source page 是关键缺口，返回 `source_url_enrichment_required`；收到 Discovery 补证后继续本候选，不因等待补证而强判。
7. 按 [references/screening-rules.md](references/screening-rules.md) 得出处理结果：正式机会 / 付费排除 / 回收 / 待确认。
8. Legacy Screening 输出只写其明确指定的历史/旁路结果位置；不得覆盖当前默认 `外链总表` / `外链管理` 控制面语义。
9. `付费排除`、`回收`、`待确认` 分开保留，不互相冒充。
10. 每轮重新统计该 Legacy Screening 候选池的 `待筛选`；明确要求全量时继续下一批直到归零或外部阻塞。

## Legacy Screening 结果

本旁路中的正式机会只收获取方式：

- `免费`
- `免费换链`

并要求已确认：**当前可获得 + Follow + 可索引**。

表字段见 [references/output-schema.md](references/output-schema.md)。规则见 [references/screening-rules.md](references/screening-rules.md)。历史 Discovery 精确来源页补证合同见 `discovering-backlinks/references/screening-handoff.md`。

再次强调：这些 Legacy Screening 结果不替代当前四阶段生产链路，也不把普通候选从 Project Backlog 中删除。
