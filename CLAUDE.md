# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目性质

BacklinkOS 不是一个应用，而是**两个 Agent Skill 的宿主仓库**加上少量支撑基础设施。仓库里的 TypeScript / Python 代码是辅助设施，产品逻辑本身写在 `.agents/skills/*/SKILL.md` 里，靠散文契约 + 回归测试保证。

## 常用命令

```bash
npm test           # 编译到 .test-dist 后用 node --test 跑全部 TS 测试，跑完删除产物
npm run typecheck  # tsc --noEmit（api/ lib/ tests/）
npm run build      # test + typecheck

# 跑单个 TS 测试（npm test 无法只跑一个文件）
npx tsc -p tsconfig.test.json && node --test .test-dist/tests/feishu-client.test.js

# Python 爬虫回归测试（CI 与 crawler workflow 都会跑）
python -m unittest tests/test_screening_crawler.py -v

# 本地跑批量三筛爬虫
python scripts/screening_crawler.py --input candidates.csv --output out.jsonl --workers 40 --timeout 8

# 把爬虫留下的 pending 候选推过最后一公里，产出 data/opportunities/
python scripts/verify_opportunity.py --workers 30      # 加 --limit N 试跑
```

ESM + `module: NodeNext`，`api/` 和 `lib/` 里的相对 import **必须写 `.js` 后缀**（指向编译产物），`tests/runtime-imports.test.ts` 会在写成 `.ts` 时失败。

## 权威层级（改动前先确认自己在哪一层）

1. `.agents/skills/discovering-backlinks/SKILL.md` + `references/`
2. `.agents/skills/screening-backlinks/SKILL.md` + `references/`
3. `docs/REPOSITORY_ARCHITECTURE.md`
4. `docs/V4_PRODUCT_STRATEGY.md`

`docs/V1_PRODUCT_PLAN.md`、`docs/V2_PRODUCT_PLAN.md`、`docs/superpowers/`、`docs/live-runs/` 只是历史记录，**不定义当前行为**，不要拿它们当依据修改 Skill。措辞冲突时以 Skill 为准。

Skill 的唯一可编辑源在 `.agents/skills/`；`.claude/skills/` 下两项是指向它的 symlink，不是第二套 Skill，不要在那边编辑或复制。

## 核心架构：Discovery 与 Screening 的职责边界

这是整个仓库最重要的不变式，跨多个文件才能看出来：

- **`discovering-backlinks` 只产出事实**：从近期有 SEO 结果的项目反查 Semrush Referring Domains，保留 `referring_domain / source_projects / organic_traffic / backlinks_num / domain_ascore / first_seen / semrush_is_follow / batch_id` 等采集事实。它**不**判断免费、Follow、可索引与否。
- **`screening-backlinks` 只回答一个问题**：普通用户**现在**能不能免费拿到一个有效的 Follow 外链。它使用 Discovery 传来的事实但不重查，自己负责验证当前机制。
- 两个正交字段不能混：**获取方式** ∈ {`免费`, `免费换链`, `付费`, `不确定`}；**处理结果** ∈ {`正式机会`, `付费排除`, `回收`, `待确认`}。只有 `正式机会` 进正式外链总表。
- **证据优先级按事实类型分开**：价格/资格看当前提交流程与官方页面；`rel` / `noindex` 等技术事实以当前结果页 DOM 为最高证据，官方"Dofollow"宣传不能覆盖实测 `rel=nofollow`；历史 Semrush 观察最低。
- **缺失不是负面**：查不到入口、AS=0、历史 0 Follow 都不能直接判 `回收`，应落 `待确认`。历史 `is_follow` 也不能证明当前存在免费 Follow 路径。
- 不做主题相关性 / 项目适配评分；不用 A/B/C/D/F 作为准入标准。
- 双向补证合同：Screening 缺精确来源页时返回 `source_url_enrichment_required`，由 Discovery 按 `discovering-backlinks/references/screening-handoff.md` 只补事实。

## 助手系统不是决策引擎

`scripts/screening_crawler.py` + `.github/workflows/screening-crawler.yml` 是**批量预筛**：推送 `data/screening-candidates/RUN` 触发，拼合 `data/screening-candidates/[0-9][0-9][0-9].txt` 成 CSV，爬取后把快照提交回 `data/screening-results/`。`scripts/verify_opportunity.py` 接在它后面，把 `pending` 候选推到 `data/opportunities/`。

爬虫的 bucket 有严格语义，**`unverified`（没找到入口）和 `dead`（有闭环负面证据）必须分开**——前者是证据缺失，下一轮要重新参与筛选。把两者混成一个 `recycle` 桶，会让几千条从没被真正筛过的候选看起来像已淘汰，直接违反 SKILL 硬规则 11。

这两个脚本里有多处**专门防误杀的逻辑**，改动前先读 `scripts/README.md` 的"误杀防护"段（noindex 只认能代表站点的页面、`path:` 伪信号不作淘汰依据、裸域/www 双试、样例页必须是详情页）。每一条都对应一个真实误杀案例，改回去会重新引入。

`data/` 下的文件是运行输入与快照，不是正式外链库。

## Feishu 持久化是兼容层

`api/feishu/{setup,persist}.ts` + `lib/feishu/`（Vercel Functions，`maxDuration: 30`）是在**旧版**筛选记录契约下上线验证过的代码，为了不打断既有集成而**原样保留**。它的字段里仍有 `评级` 这类 A/B/C/D 概念，而当前 Screening Skill 已经不用评级作为业务决策。

因此：新的用户可见表行为按 `.agents/skills/screening-backlinks/references/output-schema.md` 写；不要为了"清理术语一致性"去改这套 runtime。持久化 schema 迁移是单独的、需要显式测试的行为变更。

所有 handler 走 `createXxxHandler(deps)` 依赖注入模式（`env` / `clientFactory` / impl 可替换），测试据此注入假实现，不要改成直接读 `process.env` 的裸函数。鉴权用 `X-BacklinkOS-Key` 头对比 `BACKLINKOS_API_KEY`；Feishu 配置为 5 个必填环境变量，缺失时 `loadFeishuConfig` 抛错并返回 503。

Provider-specific 指标运行时在独立仓库 `pyxm1618/backlink-metrics-api`，本仓库**不要**重复实现 provider 集成。

## 修改 Skill 时的特殊约束

`tests/skill-contracts.test.ts` 用正则直接断言 `SKILL.md` 和 `references/*.md` 的**行文内容**（例如必须出现 `pending_semrush`、`source_url_enrichment_required`、`待Semrush筛选`、"100 是批次单位不是停止条件"、"AS=0 ≠ 回收" 等）。改写 Skill 文案会让这些测试失败——这是刻意的：**先确认是有意的契约变更，再同步更新断言**，不要为了让测试通过随手删断言。

## 清理纪律

不要因为某个文件术语老旧就删除或移动它。先确认是否仍有 automation、测试、部署或持久化依赖它（`screening_crawler.py`、`lib/feishu/`、`data/screening-*` 都属于这一类）。清理不得静默改变运行时行为。

BacklinkOS 是个人自用系统，批次规模在数百到数千量级；优先做有界批次、去重、证据复用和可人工复核的闭环，不要引入分布式基础设施。
