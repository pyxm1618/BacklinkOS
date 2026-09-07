# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## 项目性质

BacklinkOS 是 **Agent Skill 宿主仓库 + 外链控制面支撑基础设施**。当前默认生产行为由 `discovering-backlinks` Skill 与其 current references 定义；Python/TypeScript 是实现这些契约的支撑代码。

## 当前权威层级

默认生产主链路的权威顺序：

1. `.agents/skills/discovering-backlinks/SKILL.md` + current `references/`
2. `docs/REPOSITORY_ARCHITECTURE.md`
3. `docs/V4_PRODUCT_STRATEGY.md`
4. `BacklinkOS-HANDOFF.md`
5. root `README.md`

`.agents/skills/screening-backlinks/` 是 **Legacy / Optional**。只有用户明确要求旧式 Screening/历史排查时才以其 Skill 与 references 定义该旁路行为；它不能覆盖默认主链路。

历史文档：

- `docs/V1_PRODUCT_PLAN.md`
- `docs/V2_PRODUCT_PLAN.md`
- `docs/superpowers/`
- `docs/live-runs/`

历史文档保留 point-in-time 决策，不定义当前行为。不要从历史“未实现”“待开发”文字推断当前 main 仍缺功能。

Skill 的唯一可编辑源在 `.agents/skills/`；`.claude/skills/` 是 symlink compatibility entry，不要复制成第二套 Skill。

## 当前四阶段架构

```text
PHASE A — Discover / Master Upsert
referring domains → canonicalize → 【外链总表】
        ↓
PHASE B — Project Backlog Projection
纯数据库/内存，0 网络
Master 候选默认进入【外链管理】待提交池
UNKNOWN != REJECT
        ↓
PHASE C — Bounded Execution Preparation
从现有待提交池小批量 live verify Entry
VerifiedEntry → Ready Allowlist
unresolved → 保持待提交、attempt 不增加
        ↓
PHASE D — backlink-autofill
真实浏览器执行 / Final Submit / 状态与事实回写 / Manual Recheck
```

### 核心语义

**Project Backlog Population != Execution Readiness。**

- Project Backlog 可以在 Submission Entry 未知时存在；
- Phase B 禁止要求 `VerifiedEntry`、禁止网络请求；
- 入口未知、免费未知、登录未知、Follow 未知都属于 UNKNOWN，不阻断 Backlog；
- 只有明确 Master `已排除/失效` 或已持久化的项目 hard incompatibility 才跳过；
- 只有 Phase C 进入 Ready 时要求 `VerifiedEntry`；
- `待提交 != Ready`；Autofill 只消费 Ready allowlist 与当前待提交行的交集。

## 唯一控制面

Google Sheets `@外链管理总控表`：

### `外链总表`

- 平台级唯一事实库；
- `基础状态 = 候选 / 已排除 / 失效`；
- Discovery 不写 `实测免费 / 实测需登录 / 实测登录方式 / 实测限制 / 实测链接属性 / 最后验证时间`；
- Master Upsert 不覆盖真实实测字段，不把已排除/失效恢复为候选；
- Submission Entry 可为空；只有真实 Live Verification 后才写 verified entry。

### `外链管理`

- 项目机会全集 + 执行生命周期；
- `project_id + backlink_id` 唯一；
- 新 Backlog 行默认 `待提交 / 尝试次数=0`；
- 已有任何状态不得重复创建或重置；
- 当前生产 Backlog 已完成数千行投影，不要重新执行早期“几十行 → 数千行”迁移计划。

## 当前核心 helper

### `scripts/master_sheet_sync.py`

核心业务逻辑：

- canonical domain；
- Master Upsert 与事实保护；
- Project Backlog materialization；
- Project Compatibility Hard Gate；
- Submission Entry Policy Guard / Live Verification；
- bounded execution preparation；
- Ready cursor / orphan accounting。

注意：该 Python 文件顶部若仍有历史 docstring 描述，不得以旧注释覆盖当前函数实现与 canonical Skill 契约；本轮文档同步仅修改 Markdown 文档，不修改代码文件。

### `scripts/project_backlog_projection.py`

正式 Project Backlog Projection runner：

- dry-run / commit；
- 0 网络投影；
- reconciliation invariant；
- 时间戳备份；
- 按需 Sheet 扩容；
- 分批写入；
- exact read-back；
- 完整性审计。

### `scripts/prepare_execution_batch.py`

Phase C bounded Ready preparation helper。

### `scripts/screening_crawler.py`

历史/辅助 triage 与 Entry discovery 基础设施。可被当前流程复用底层页面分析能力，但 crawler bucket 不是默认生产最终决策层。

## `backlink-autofill` 边界

独立仓库 `pyxm1618/backlink-autofill` 负责：

- 真实浏览器；
- 登录/注册/填表；
- Existing Submission Preflight；
- anonymous fail-closed；
- CAPTCHA/Turnstile/2FA/SMS human blockers；
- Final Submit；
- 项目状态分类；
- 结果链接、DOM rel；
- Manual Post-submit Recheck。

Manual Recheck 不得调用 execution-start、不增加 attempt、不重复 Final Submit。

## 当前验收基线

2026-09-07 closeout：

- BacklinkOS 代码基线（文档同步前）`533272bf8561125a6823ba9570bea42ff433102a`；
- Python `115 passed`；
- Node `41 passed`；
- TypeScript `0 errors`；
- `backlink-autofill/main = 0d82d921bbcc0e2b7b192b71b24abde1d202fa0f`；
- 本轮没有为了验收强行跑 10 个真实提交，新增 Final Submit = 0。

真实 Gate B 曾发现 `navtools.ai` 是 AI-only，而非 AI 项目 Quick I Ching 被错误放入 Ready；该 AI-only live verification 漏判已修复并合入 main。未来不可硬编码域名，仍使用通用强证据 + inclusive guard。

## 常用验证命令

```bash
npm test
npm run typecheck
pytest -v
```

修改 Skill Markdown 时先读 `tests/skill-contracts.test.ts`，避免无意破坏文档契约；若用户明确限定“仅文档”，不要为了让文案看起来一致而修改 Python/TypeScript 实现。
