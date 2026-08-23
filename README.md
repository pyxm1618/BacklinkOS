# BacklinkOS

> **一句话：** 一个可复用的外链机会系统：先批量发现真实外链候选，再筛出普通用户现在可以免费获得的有效 Follow 外链。

BacklinkOS 有两个职责分开的 Agent Skills：

1. `discovering-backlinks` — **找外链候选**
2. `screening-backlinks` — **筛外链候选**

它维护的是**通用外链机会库**，不负责判断某条外链是否与某个具体网站主题相关，也不做 Project × Opportunity 匹配。

## 怎么调用

前提：你的 Agent / IDE 已经安装或加载了本仓库的 Skills。

**最稳妥的方式是直接在提示词中写出 Skill 名称。**

找外链：

```text
使用 discovering-backlinks，继续帮我批量找新的外链候选。
```

筛外链：

```text
使用 screening-backlinks，把这批候选外链筛完，找出真正能做的免费 Follow 外链。
```

如果宿主环境支持 Agent Skills 自动匹配，也可以根据各 `SKILL.md` 的 `description` 自动触发；是否支持自动触发取决于宿主环境。需要确定调用哪个 Skill 时，直接点名最可靠。

## 两个 Skill 分别做什么

| Skill | 负责 | 不负责 |
| --- | --- | --- |
| [`discovering-backlinks`](.agents/skills/discovering-backlinks/SKILL.md) | 从近期已有 SEO 结果的项目、Semrush Referring Domains 等真实来源批量发现候选外链域名，并保留来源和指标事实 | 不判断当前是否免费、是否 Follow、是否可索引、是否适合某个具体项目 |
| [`screening-backlinks`](.agents/skills/screening-backlinks/SKILL.md) | 核验候选现在是否存在普通用户可执行的获取路径，并确认免费性、最终外链属性和页面可索引性 | 不重新发明 Discovery 已取得的事实，不做主题相关性或项目适配评分 |

## 工作流

```text
真实项目 / 外链来源
        ↓
discovering-backlinks
        ↓
   候选外链池
        ↓
screening-backlinks
        ↓
正式机会 / 付费排除 / 回收 / 待确认
```

### Discovery 的目标

Discovery 负责**扩大候选池**。

它可以利用近期项目、Semrush Organic Traffic、Referring Domains、历史 `is_follow` 等事实发现值得继续核验的域名。

这些只是发现证据。例如 Semrush 历史 `is_follow` 不能直接证明这个网站**现在**存在免费的 Follow 获取路径。

### Screening 的目标

Screening 只回答一个核心问题：

> **普通用户现在能不能免费获得一个有效的 Follow 外链？**

当前获取方式只有四种：

- `免费`
- `免费换链`
- `付费`
- `不确定`

进入正式机会库必须确认：

- 当前有普通用户可以实际执行的入口；
- 不需要付费（需要 reciprocal backlink 时记为 `免费换链`）；
- 最终公开页面存在直接外部链接；
- 最终链接不含 `nofollow`、`ugc`、`sponsored`；
- 最终页面可被搜索引擎索引。

不满足条件的候选进入 `付费排除`、`回收` 或 `待确认`，而不是混入正式机会库。

## 关键原则

- **Discovery 找事实，Screening 做当前机会判断。** 两者不能混在一起。
- **不知道就是不知道。** 缺失数据、查询失败、无覆盖都不能当成 `0` 或负面结论。
- **不做相关性评分。** BacklinkOS 存通用机会，不判断 Quick I Ching 或其他具体项目是否适合。
- **不使用 A/B/C/D/F 作为当前准入标准。** DR、流量、覆盖项目数等可以用于排序，但不决定是否进入正式机会库。
- Bulk crawler 只是批量预筛助手，不是最终 Screening 决策引擎。

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
scripts/                     operational helpers
.github/workflows/           automation
api/feishu/                  compatibility persistence API
lib/feishu/                  compatibility persistence implementation
data/                        operational candidates / snapshots
docs/                        architecture, strategy and historical records
tests/                       runtime/helper regression tests
```

Provider-specific 指标运行时位于独立仓库 `pyxm1618/backlink-metrics-api`，BacklinkOS 不重复实现这些 provider integrations。

## 当前权威文档

1. `.agents/skills/discovering-backlinks/SKILL.md` + `references/`
2. `.agents/skills/screening-backlinks/SKILL.md` + `references/`
3. `docs/REPOSITORY_ARCHITECTURE.md`
4. `docs/V4_PRODUCT_STRATEGY.md`

更早的 V1/V2、历史计划和 live-run 文档只用于保留设计与执行历史，不定义当前行为。
