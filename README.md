# BacklinkOS

> **一句话：** 批量发现真实外链候选并准备最低限度提交入口，通过真实浏览器执行（`backlink-autofill`）闭环外链获取。

BacklinkOS 拥有两个 Agent Skills：

1. `discovering-backlinks` — **找外链候选与执行入口准备（主链路）**
2. `screening-backlinks` — **历史筛外链 Skill（已退出主工作流，作为 legacy / optional 工具保留）**

它维护的是**通用外链机会库**，不负责判断某条外链是否与某个具体网站主题相关，也不做 Project × Opportunity 匹配。

## 怎么调用

前提：你的 Agent / IDE 已经安装或加载了本仓库的 Skills。

**最稳妥的方式是直接在提示词中写出 Skill 名称。**

找外链与扩库：

```text
使用 discovering-backlinks，继续帮我批量找新的外链候选。
```

为特定项目准备可执行候选：

```text
使用 discovering-backlinks，为 quick-iching 准备接下来 10 个可执行候选。
```

## 主生产工作流

```text
真实项目 / 外链来源
        ↓
discovering-backlinks
        ↓
规范化 & 去重 (canonical domain)
        ↓
【外链总表】(Master Sheet Upsert，平台级唯一事实库)
        ↓
最低限度 Submission Entry Enrichment (真实入口核验 + Policy Guard)
        ↓
为明确项目创建【外链管理】待提交行 (Materialization)
        ↓
backlink-autofill (独立执行仓库，真实浏览器自动化)
        ↓
回写真实平台事实与项目执行结果
```

## 两个 Skill 分别做什么

| Skill | 负责 | 不负责 |
| --- | --- | --- |
| [`discovering-backlinks`](.agents/skills/discovering-backlinks/SKILL.md) | 从近期 SEO 成功项目、Semrush Referring Domains 等来源发现候选域名；规范化 Upsert 到【外链总表】；进行最低限度 Submission Entry Enrichment；在明确项目上下文中为【外链管理】materialize 待提交行 | 不判断当前是否免费、是否需登录、实测限制、是否 Follow；不写实测事实字段 |
| [`screening-backlinks`](.agents/skills/screening-backlinks/SKILL.md) *(Legacy / Optional)* | 历史离线规则筛选能力，已退出主工作流；仅在需要离线快速评估或历史排查时作为可选旁路使用 | 不再是发现流程必经节点；不决定域名是否进入新外链总表；不淘汰普通候选 |

## 核心原则

- **分工明确：** Discovery 负责发现候选和最低限度执行入口准备；`backlink-autofill` 负责通过真实浏览器判断免费、登录、限制、提交、上线和链接属性。不在中间重新创造 Screening 层。
- **唯一控制面：** 以 Google Sheets `@外链管理总控表` 为准。平台事实在 `外链总表`，项目执行在 `外链管理`。
- **保护真实事实：** 总表 Upsert 不覆盖已有真实实测字段，绝不把 `已排除`、`失效` 改回候选。
- **入口不乱填：** Submission Entry 严格区分真实页面证据（Live Evidence）与 Policy Guard（排除 pricing/terms/category 等）；首页只有在包含明确机制 CTA 时才允许作为入口；找不到入口保持为空且候选继续保留，绝不因找不到入口而淘汰候选。
- **项目行不重复：** `project_id + backlink_id` 唯一。已有任何状态绝不重复创建，保护 Quick I Ching 已有历史记录。
- **存量批次有界：** 存量候选 Hydration 必须显式指定 project_id 与 limit，严格有界逐个推进，不全量灌入 3000+。

## Canonical Skills

正式 Skill 只有两份：

```text
.agents/skills/
  discovering-backlinks/
  screening-backlinks/
```

`.claude/skills/` 是兼容入口，指向 `.agents/skills/`，不是另一套独立 Skill。

当其他文档与当前 Skill 冲突时，以 `.agents/skills/*/SKILL.md` 及其 `references/` 为准。

## 仓库结构

```text
.agents/skills/              canonical Agent Skills
.claude/skills/              compatibility symlinks
scripts/                     operational helpers & master sheet sync module
.github/workflows/           automation
api/feishu/                  compatibility persistence API
lib/feishu/                  compatibility persistence implementation
data/                        operational candidates / snapshots
docs/                        architecture, strategy and historical records
tests/                       runtime/helper regression tests
```

Provider-specific 指标运行时位于独立仓库 `pyxm1618/backlink-metrics-api`，本仓库不重复实现这些 provider integrations。执行自动化由独立仓库 `pyxm1618/backlink-autofill` 负责。

## 当前权威文档

1. `.agents/skills/discovering-backlinks/SKILL.md` + `references/`
2. `.agents/skills/screening-backlinks/SKILL.md` + `references/`
3. `docs/REPOSITORY_ARCHITECTURE.md`
4. `docs/V4_PRODUCT_STRATEGY.md`
