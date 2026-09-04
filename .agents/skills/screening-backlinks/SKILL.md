---
name: screening-backlinks
description: Use when the user asks to 筛外链, 审核外链, 核验外链候选, 判断哪些外链能做, or process candidates produced by discovering-backlinks.
---

# 筛外链

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
2. 进入正式外链库必须同时满足：
   - 当前有普通用户可执行的入口；
   - 不需要付费；需要 reciprocal backlink 时归为 `免费换链`；
   - 最终公开页面有直接指向外站的链接；
   - 链接是 Follow：最终 `<a>` 不含 `nofollow`、`ugc`、`sponsored`；
   - 最终页面可被搜索引擎索引。
3. 必须付款才能得到合格 Follow → `获取方式=付费`、`处理结果=付费排除`，不是回收。
4. 免费路径最终 Nofollow/UGC/Sponsored、没有外部 URL、入口失效、页面 noindex、网站死亡或有闭环证据证明属于垃圾/恶意/卖链网络 → `处理结果=回收`。
5. 关键事实确实查不到 → 保留已确认的获取方式（无法确认时为 `不确定`），`处理结果=待确认`；不要编答案。
6. 不使用 A/B/C/D 作为业务评级。DR、流量、成功项目数、`first_seen` 只用于排序，不决定保留或淘汰。A/B/C/D 如存在，只能作为内部**解决路线**。
7. **用户说“继续”“全部执行”“筛完”“做完”时，默认进入全量完成模式。** 不得处理十几条样本后自行停下并称阶段完成；必须持续处理当前候选池，直到 `待筛选=0`，或出现明确外部阻塞（权限、登录、工具故障、必须人工验证）。
8. 若被外部阻塞而无法归零，必须明确报告剩余 `待筛选` 数；不得说“全部完成”。
9. **允许网络级批量判定，但证据必须闭环。** 只有当同一批域名有可验证的共同运营方、品牌、模板、机制、明确卖链行为或公开调查证据时，才允许用正则/家族规则批量归类；不能只凭域名长得像垃圾站。
10. 网络级批量判定必须保留：匹配规则、结论、原因、证据 URL、核验日期、适用范围。新匹配到该规则的域名可自动继承状态；规则证据失效时必须重新核验。
11. **缺失事实不是负面事实。** “没找到入口/页面”本身不等于回收；AS=0、历史 0 Follow、历史 100% Follow 都不能单独决定当前处理结果。详见 `references/screening-rules.md`。
12. 如果 domain-level 事实不足、但精确历史来源页可能帮助识别机制，返回 `source_url_enrichment_required` 给 `discovering-backlinks`，写明 `referring_domain | source_projects | reason`。Screening 不自己猜历史 source URL。
13. 迁移运行表数据时遵守 target-first 安全写入：目标写入 → 回读确认 → 再清源数据；不得破坏 ARRAYFORMULA/公式列。详见 `references/screening-rules.md`。
14. **正式批量只能从增量总账开始。** 先用仓库根目录的 `scripts/prepare_screening_input.py` 合并旧候选、本次发现、已有粗筛结果和已有深筛状态。固定的旧候选文件不是当前待处理清单，不能直接拿来重跑。
15. **默认复用已有结果。** 已有粗筛结果必须复用，已有深筛状态必须复用；旧结论保留原证据和日期。新请求只处理当前总账中 `queue_state=unreviewed` 的候选，其他候选不得再次消耗网络请求和工具额度。
16. **重新检查必须由用户明确要求。** `--fresh`、全量重跑、对已有状态重新检查，都不能作为默认动作；用户没有明确要求时，不得为了“保险”重复处理。
17. **运行前后都要对账。** 核对 `approved + deferred + confirmed_reject + triaged_only + unreviewed = 合并后总数`；任何条目都不能因缺证据、没进保留名单或本轮未复查而被当成回收。数量不平就停止并修正总账。

## 流程

1. 用 `scripts/prepare_screening_input.py` 生成增量总账和对账清单；只在数量完全对平后继续。
2. 向粗筛程序传入已有粗筛结果，向浏览器复核和最终判定程序传入已有深筛状态；默认复用，不重查。
3. 只取 `queue_state=unreviewed` 的候选作为本轮新任务，再按“网站 + 外链形式 + 操作入口”去重；同一网站不同入口可以是不同机会。
4. 优先识别可被同一证据覆盖的网络/域名家族，批量处理有闭环证据的 PBN、卖链、自动垃圾页、Nofollow 网络，减少逐站重复劳动。
5. 对剩余独立候选找到当前真实操作入口。
6. 判断获取方式：免费 / 免费换链 / 付费 / 不确定。
7. 用**当前同一路径产生的公开页面**验证最终链接；先确定正在判断的是价格/资格还是 `rel`/indexability 等技术输出，再按对应证据优先级解决冲突。
8. 如果 exact historical source page 是关键缺口，返回 `source_url_enrichment_required`；收到 Discovery 补证后继续本候选，不因等待补证而强判。
9. 按 [references/screening-rules.md](references/screening-rules.md) 得出处理结果：正式机会 / 付费排除 / 回收 / 待确认。
10. `正式机会` 写入“外链总表”；只有总表以前没有的机会才追加到“新增记录”。
11. `付费排除`、`回收`、`待确认` 分开保留，不互相冒充，也不混进正式外链总表。
12. 每轮写入后重新生成状态统计并对账；全量模式下若 `unreviewed` 仍大于 0，继续下一批，不把“本轮写入成功”当成任务完成。

## 正式结果

正式总表只收 `处理结果=正式机会`，且获取方式只能是：

- `免费`
- `免费换链`

二者都必须已经确认：**当前可获得 + Follow + 可索引**。

完成标准：当前候选池中每个候选都必须落入 `正式机会 / 付费排除 / 回收 / 待确认` 之一，`待筛选=0`；`待确认` 可以存在，但必须是已经完成本轮 Screening 且明确记录缺口的状态，而不是未处理。

表字段见 [references/output-schema.md](references/output-schema.md)。回归要求见 [references/test-cases.md](references/test-cases.md)。Discovery 精确来源页补证合同由 `discovering-backlinks/references/screening-handoff.md` 定义。
