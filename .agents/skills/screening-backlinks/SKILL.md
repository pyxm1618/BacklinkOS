---
name: screening-backlinks
description: Use when the user asks to 筛外链, 审核外链, 核验外链候选, 判断哪些外链能做, or process candidates produced by discovering-backlinks.
---

# 筛外链

## 目标

只判断一件事：**这个候选现在能不能免费获得一个有效的 Follow 外链。**

Discovery 已经传来的技术事实直接使用，不重新查、不重新怀疑。

## 硬规则

1. **不做项目适配。** 不判断 Quick I Ching 或任何具体项目是否适合；只记录机会本身的限制。
2. 获取方式只允许四个值：`免费`、`免费换链`、`付费`、`不确定`。
3. 进入正式外链库必须同时满足：
   - 当前有普通用户可执行的入口；
   - 不需要付费；需要 reciprocal backlink 时归为 `免费换链`；
   - 最终公开页面有直接指向外站的链接；
   - 链接是 Follow：最终 `<a>` 不含 `nofollow`、`ugc`、`sponsored`；
   - 最终页面可被搜索引擎索引。
4. `付费`、Nofollow/UGC/Sponsored、没有外部 URL、入口失效、页面 noindex、明显垃圾站 → 回收站。
5. 关键事实确实查不到 → `不确定`，放待确认；不要编答案。
6. 不使用 A/B/C/D 评级。DR、流量、成功项目数、`first_seen` 只用于排序，不决定保留或淘汰。

## 流程

1. 按“网站 + 外链形式 + 操作入口”去重；同一网站不同入口可以是不同机会。
2. 找到当前真实操作入口。
3. 判断获取方式：免费 / 免费换链 / 付费 / 不确定。
4. 用**当前同一路径产生的公开页面**验证最终链接；没有可验证样例且不能实际完成提交时，记 `不确定`。
5. 按 [references/screening-rules.md](references/screening-rules.md) 得出结果。
6. 通过的机会写入“外链总表”；只有总表以前没有的机会才追加到“新增记录”。
7. 回收站和待确认可以内部保留，但不要混进正式外链总表。

## 正式结果

正式总表只收两类：

- `免费`
- `免费换链`

且二者都必须已经确认：**当前可获得 + Follow + 可索引**。

表字段见 [references/output-schema.md](references/output-schema.md)。回归要求见 [references/test-cases.md](references/test-cases.md)。
