# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目性质

BacklinkOS 是**Agent Skill 的宿主仓库**加上支撑基础设施。仓库里的 TypeScript / Python 代码是辅助设施，产品业务规范写在 `.agents/skills/*/SKILL.md` 里，靠散文契约 + 回归测试保证。

## 常用命令

```bash
npm test           # 编译到 .test-dist 后用 node --test 跑全部 TS 测试，跑完删除产物
npm run typecheck  # tsc --noEmit（api/ lib/ tests/）
npm run build      # test + typecheck

# 跑单个 TS 测试
npx tsc -p tsconfig.test.json && node --test .test-dist/tests/skill-contracts.test.js

# Python 回归测试（包含新控制面契约、守卫、爬虫回归测试）
pytest -v

# 仅跑新控制面与入口同步测试
pytest -v tests/test_master_sheet_sync.py
```

ESM + `module: NodeNext`，`api/` 和 `lib/` 里的相对 import **必须写 `.js` 后缀**（指向编译产物），`tests/runtime-imports.test.ts` 会在写成 `.ts` 时失败。

## 权威层级（改动前先确认自己在哪一层）

1. `.agents/skills/discovering-backlinks/SKILL.md` + `references/`
2. `.agents/skills/screening-backlinks/SKILL.md` + `references/` *(Legacy / Optional)*
3. `docs/REPOSITORY_ARCHITECTURE.md`
4. `docs/V4_PRODUCT_STRATEGY.md`

`docs/V1_PRODUCT_PLAN.md`、`docs/V2_PRODUCT_PLAN.md`、`docs/superpowers/`、`docs/live-runs/` 只是历史记录，**不定义当前行为**。

Skill 的唯一可编辑源在 `.agents/skills/`；`.claude/skills/` 下两项是指向它的 symlink，不是第二套 Skill，不要在那边编辑或复制。

## 核心架构与职责分工

当前生产架构中：

```text
discovering-backlinks
        ↓
发现真实 referring domains
        ↓
canonicalize / 去重
        ↓
写入或合并【外链总表】（Master Sheet Upsert）
        ↓
最低限度 Submission Entry Enrichment (Live Evidence + Policy Guard)
        ↓
为明确项目创建【外链管理】待提交行 (Materialization)
        ↓
backlink-autofill (独立仓库，真实浏览器执行)
        ↓
回写真实平台事实和项目执行结果
```

### 1. 唯一控制面：`@外链管理总控表`
- **Tab: `外链总表`**（平台级唯一事实库）：
  - 基础状态仅有：`候选`、`已排除`、`失效`。
  - **字段隔离：** Discovery 严格只写发现事实，绝对禁止填写 `实测免费`、`实测需登录`、`实测登录方式`、`实测限制`、`实测链接属性`、`最后验证时间`。这些属于 `backlink-autofill` 真实执行之后的事实。UNKNOWN 必须为空。
  - **Upsert 保护：** 新域名新增为候选；已有域名不重复创建，不得覆盖已有真实实测字段，**绝不得将`已排除`或`失效`改回`候选`**。
  - **硬黑名单：** 直接来自总表 `已排除` 或 `失效` 状态，不重复研究，不重新进入项目执行队列。不维护第二套独立黑名单。

### 2. 最低限度 Submission Entry Enrichment
- 对准备进入项目队列的平台确认真实可执行入口（Submit, Add Product, Write for Us, Create Profile 等）。
- 严格区分两层：
  - **Live Evidence（真实页面证据）：** 必须实际打开页面确认机制文案/控件（`mechanism_signals`）或首页明确 CTA。**禁止仅凭 URL 路径类似 `/submit` 升级为真入口**。
  - **登录/注册墙 noindex 防误杀：** 复用 `AUTH_PATH_RE`；登录/注册墙页面带 noindex 是正常现象，只要有机制文案或登录跳转特征，绝不误杀。
  - **Policy Guard（政策守卫）：** 排除 pricing, terms, privacy, category, seo-report 等页面。
- 首页绝不能仅凭 URL 冒充入口；无页面 CTA 证据的首页一律拦截。
- **找不到入口时：提交入口保持为空，基础状态保持为候选。绝对不因找不到入口而淘汰候选！**

### 3. 项目执行行 Materialization
- 必须运行在明确项目上下文（如 `quick-iching`）下。
- **历史提交入口强制重新核验：** 总表现存历史 `提交入口` 必须通过现场 Live Verification 生成 `VerifiedEntry`，才能 materialize 为待提交行；未通过现场核验不生成项目行。
- 仅当满足：`总表基础状态==候选` AND `具备现场核验通过的 VerifiedEntry` AND `当前 project_id + backlink_id 尚不存在` 时，才生成 `待提交` 行。
- **项目行不重复：** `project_id + backlink_id` 唯一。已存在任何状态均不重复创建或重置。Quick I Ching 已有历史记录必须保护。
- **存量批次双边界有界：** 存量候选 Hydration 必须显式指定 `project_id`、`target_count` 与 `scan_limit`，满足 `succeeded >= target_count` 或 `processed >= scan_limit` 任一条件即刻停止，绝不因大量失败而无限扫完 3000+。


### 4. `screening-backlinks` 定位
- 旧的筛选 Skill 已退出主工作流。不要删除其历史文件。
- 不再作为发现流程的必经节点，不决定域名是否进入新外链总表，不因为离线判断淘汰普通候选。
- 仅作为 legacy / optional 旁路保留。

## 支撑模块与助手系统

- `scripts/master_sheet_sync.py`：实现域名规范化、总表 Upsert 合并、Submission Entry 守卫与真实核验、项目待提交行 Materialization 及有界批次 Hydration 核心纯业务契约。
- `scripts/screening_crawler.py`：包含经过全面测试的锚文本入口匹配、ENTRY_HINTS、COMMON_PATHS、机制检测等基础设施。新 Discovery 复用其入口发现能力。
- 本仓库不维护生产 Google 凭据；真实 Google Sheet 读写由运行环境的官方 capability 负责，且遵循：精确定位 row → mutation → exact-row read-back 验证。
- Provider-specific 指标运行时在独立仓库 `pyxm1618/backlink-metrics-api`；自动化执行与表单填写在独立仓库 `pyxm1618/backlink-autofill`。

## 修改 Skill 时的特殊约束

`tests/skill-contracts.test.ts` 用正则直接断言 `SKILL.md` 和 `references/*.md` 的行文内容。改写 Skill 文案时：**先确认是有意的契约变更，再同步更新断言**，不要随手删改断言。
