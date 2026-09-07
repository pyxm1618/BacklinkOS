# BacklinkOS

> **一句话：** BacklinkOS 负责发现外链候选、维护平台事实库、把候选全量投影为项目 Backlog，并小批量准备 Ready 队列；真实浏览器执行由独立仓库 `backlink-autofill` 完成。

## 当前状态

截至 2026-09-07，当前生产架构已经完成专项修复与验收。默认主链路不再要求候选先通过 `screening-backlinks`，也不要求先取得 `VerifiedEntry` 才能进入项目 Backlog。

BacklinkOS 当前有两个 Agent Skills：

1. `discovering-backlinks` — **当前主生产 Skill**：发现候选、Master Upsert、Project Backlog Projection、Bounded Execution Preparation。
2. `screening-backlinks` — **Legacy / Optional**：历史筛选能力，仅在用户明确要求历史筛选/专项核验时使用，不是默认生产必经节点。

## 当前四阶段生产工作流

```text
PHASE A — Discover / Master Upsert
真实项目 / 外链来源
        ↓
discovering-backlinks
        ↓
canonicalize / 去重
        ↓
【外链总表】平台级唯一事实库
新候选允许入口未知、免费未知、登录未知、Follow 未知
        ↓
PHASE B — Project Backlog Projection
纯数据库/内存投影，0 网络请求
候选默认进入【外链管理】待提交池
UNKNOWN != REJECT
仅排除：Master 已排除/失效，或已持久化的明确 hard incompatibility
        ↓
PHASE C — Bounded Execution Preparation
从已有待提交池小批量扫描（例如 target_ready_count=10 / scan_limit=50）
现场核验 Submission Entry
只有 VerifiedEntry 才进入 Ready Allowlist
unresolved 仍保留待提交，attempt 不增加
        ↓
PHASE D — backlink-autofill
真实浏览器执行：登录 / 填表 / Final Submit / 状态判断 / 上线核验
        ↓
回写【外链总表】真实平台事实 + 【外链管理】项目执行结果
```

## 两个仓库的边界

### `pyxm1618/BacklinkOS`

负责：

- 外链候选发现与 provenance；
- canonical domain 与 Master Upsert；
- `外链总表` / `外链管理` 数据契约；
- Project Backlog Projection；
- Project Compatibility Hard Gate（只使用明确已证实的硬限制；UNKNOWN 默认包含）；
- Submission Entry Live Verification；
- Ready cursor、Ready manifest 与 Ready allowlist handoff；
- 生产 Projection helper 与相关回归测试。

### `pyxm1618/backlink-autofill`

负责：

- 真实浏览器执行；
- 登录/注册/表单填写；
- Existing Submission Preflight；
- 匿名提交 fail-closed；
- CAPTCHA / Turnstile / 人工阻断处理；
- Final Submit；
- `已提交 / 审核中 / 已排期 / 已上线 / 需人工 / 失败 / 不适用` 等项目状态；
- Manual Post-submit Recheck；
- 真实结果链接和 DOM `rel` 等事实回写。

可以简单理解为：**BacklinkOS 决定“做哪个、现在是否 Ready”；backlink-autofill 负责“怎么真实执行”。**

## 唯一控制面

Google Sheets `@外链管理总控表` 是当前唯一业务控制面：

- `外链总表`：平台级唯一事实库；
- `外链管理`：项目机会全集、待提交 Backlog 与执行生命周期。

关键纪律：

- `外链总表.基础状态` 仅有 `候选 / 已排除 / 失效`；
- Discovery 不填写 `实测免费 / 实测需登录 / 实测登录方式 / 实测限制 / 实测链接属性 / 最后验证时间`；
- `project_id + backlink_id` 唯一，已有任何状态不得重复创建或重置；
- **Project Backlog 可以在 Submission Entry 未知时存在；只有进入 Ready 才要求 VerifiedEntry。**

## 怎么调用

找新外链、扩 Master：

```text
使用 discovering-backlinks，继续帮我批量找新的外链候选。
```

为项目继续准备执行批次：

```text
使用 discovering-backlinks，为 quick-iching 准备下一批 Ready 外链候选。
```

随后将真实 Ready allowlist 交给 `backlink-autofill` 执行。

## 关键生产 helper

- `scripts/master_sheet_sync.py` — 核心纯业务契约与 Ready preparation；
- `scripts/project_backlog_projection.py` — Project Backlog dry-run / commit、备份、按需扩容、分批写入、exact read-back 与 reconciliation；
- `scripts/prepare_execution_batch.py` — bounded Ready preparation；
- `scripts/screening_crawler.py` — 历史/辅助 triage 与入口发现基础设施，不是当前默认最终决策层。

## Canonical Skills

正式 Skill 源只有：

```text
.agents/skills/
  discovering-backlinks/
  screening-backlinks/
```

`.claude/skills/` 是 compatibility symlink，不是第二套 Skill。

当前生产行为优先级：

1. `.agents/skills/discovering-backlinks/SKILL.md` + current references；
2. `docs/REPOSITORY_ARCHITECTURE.md`；
3. `docs/V4_PRODUCT_STRATEGY.md`；
4. `BacklinkOS-HANDOFF.md`。

`screening-backlinks` 及其 references 只在明确调用 Legacy / Optional Screening 时定义该旁路行为，不覆盖默认四阶段主链路。

## 历史文档

`docs/V1_PRODUCT_PLAN.md`、`docs/V2_PRODUCT_PLAN.md`、`docs/superpowers/`、`docs/live-runs/` 保留决策和运行历史，不定义当前生产行为。不要因为历史文档中的旧架构或“尚未实现”描述重新开启已完成的开发任务。
