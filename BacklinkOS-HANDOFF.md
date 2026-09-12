# BacklinkOS 工作交接（2026-09-07 Closeout Baseline）

> 这是当前交接基线。先读本文件，再读 `CLAUDE.md`、`README.md` 和 canonical `discovering-backlinks` Skill。

## 当前结论

BacklinkOS + `backlink-autofill` 本轮专项修复与验收已经完成并收口。

截至 2026-09-07：

- BacklinkOS 当前生产 `main` 基线（文档同步前）：`533272bf8561125a6823ba9570bea42ff433102a`；
- `backlink-autofill/main`：`0d82d921bbcc0e2b7b192b71b24abde1d202fa0f`；
- BacklinkOS 最终代码回归：Python `115 passed`、Node `41 passed`、TypeScript `0 errors`；
- 本轮验收没有为了凑样本而强行执行 10 个真实 Final Submit；新增真实 Final Submit = 0；
- `BacklinkOS` 历史 PR #1、#5 已关闭且未 merge；当前生产实现只认 `main`。

不要因为旧 Plan、旧 PR、旧 live-run 或旧 screening 文档中的“未实现/待开发”表述重新开启已经完成的架构改造。

## 当前四阶段架构

```text
PHASE A — Discover / Master Upsert
发现真实 referring domains
        ↓
canonicalize / 去重
        ↓
【外链总表】平台事实库
        ↓
PHASE B — Project Backlog Projection
0 网络纯投影
候选默认进入【外链管理】待提交池
UNKNOWN != REJECT
仅排除 Master 已排除/失效或已证实 hard incompatibility
        ↓
PHASE C — Bounded Execution Preparation
从待提交池小批量 live verify Entry
VerifiedEntry → Ready Allowlist
unresolved → 仍待提交，attempt 不增加
        ↓
PHASE D — backlink-autofill
真实浏览器执行 + 状态/事实回写 + Manual Recheck
```

### 最重要的语义纠偏

**Project Backlog Population 与 Execution Readiness 已彻底解耦。**

- `外链管理` 是具体项目所有值得尝试的机会全集与生命周期表；
- Project Backlog **不要求** Submission Entry 已知，也不要求 `VerifiedEntry`；
- Entry 未知、免费未知、登录未知、Follow 未知：`UNKNOWN != REJECT`；
- 只有 Phase C 进入 Ready for Autofill 时才要求现场 `VerifiedEntry`；
- Phase C unresolved 不能把合法 Backlog 行标失败、删除或增加尝试次数。

## 唯一控制面

Google Sheets `@外链管理总控表`：

### `外链总表`

平台级唯一事实库。

- `基础状态`：`候选 / 已排除 / 失效`；
- Discovery 只写发现/来源事实；
- Discovery 不写 `实测免费 / 实测需登录 / 实测登录方式 / 实测限制 / 实测链接属性 / 最后验证时间`；
- 已排除/失效不得被新 Discovery 改回候选；
- Submission Entry 可以为空；只有真实 Live Verification 后才可写 verified entry。

### `外链管理`

项目机会全集 + 生命周期。

- `project_id + backlink_id` 唯一；
- Backlog 默认 `状态=待提交 / 尝试次数=0`；
- 已有任何状态不得重复创建、覆盖或重置；
- 当前生产表已经完成从早期几十行向数千行 Backlog 的投影迁移；不要重新执行一次“36 → 3000+”旧迁移计划。

## Production Projection

正式 helper：`scripts/project_backlog_projection.py`。

当前能力：

- `--dry-run` 与 `--commit`；
- 纯内存/数据库投影，0 网络；
- reconciliation invariant；
- commit 前时间戳备份；
- 按需扩容 rowCount；
- 分批写入；
- exact read-back；
- 最终完整性审计。

Gate A 曾在生产表验证过幂等投影：候选均已被已有项目行/不兼容/新增三类完整解释，`would_create=0` 可以合法通过，不再要求任意最小新增数量。

## Ready Preparation

正式 helper：`prepare_execution_batch` / `scripts/prepare_execution_batch.py`。

- 从当前项目 `待提交` Backlog 中取 bounded batch；
- 默认思路例如 `target_ready_count=10`、`scan_limit=50`；
- Ready cursor 防止每轮从头扫描导致头部饥饿；
- orphan Master join 缺失会被明确报告并跳过，不阻断 cursor；
- 已有 entry 必须 live revalidate；空 entry 可现场发现；
- 只有 `VerifiedEntry` 进入 Ready manifest；
- AI-only 等 hard compatibility 必须按项目上下文阻断，未知限制不提前拒绝。

2026-09-07 真实验收发现 `navtools.ai` 是 AI-only 平台，曾被错误识别为 `ai_only=False`；该漏判已通过组合强证据规则修复并合入 main。Quick I Ching (`ai_powered=False`) 对该平台现在正确为 `NOT READY`。

## `backlink-autofill` Handoff

`backlink-autofill` 只能消费：

> **Ready allowlist ∩ 当前项目 Sheet `待提交` 行**

没有 Ready allowlist 时必须 standalone fail-closed；`待提交 != Ready`。

Autofill 负责：

- Existing Submission Preflight；
- 匿名路径 fail-closed；
- 登录/注册/表单执行；
- CAPTCHA / Turnstile / 2FA / SMS 等 human blocker；
- Final Submit；
- 真实状态分类；
- 结果链接；
- DOM `rel`；
- Manual Post-submit Recheck。

Manual Recheck 不得当成新提交：不调用 execution-start、不增加 attempt、不重复 Final Submit；排期状态在没有强取消事实时不得被弱 Pending/Review 证据降级。

## `screening-backlinks` 当前定位

Legacy / Optional。

它不是当前默认主链路中的必经层，不负责决定普通候选是否能进入 Master 或 Project Backlog。只有用户明确要求旧式免费/Follow 机会筛选、历史排查或专项审计时才调用。

## 已知非 blocker 数据事项

生产 `外链管理` 中曾识别出 4 个历史 orphan 项目行：

- `aiching.app`
- `buddhistwisdom.info`
- `beebom.com`
- `parade.com`

当前代码会明确报告并安全跳过，不再卡死 Ready cursor。它们是数据清理事项，不是本轮系统 blocker；不要因它们重新打开代码专项。

## 历史文档纪律

以下是历史档案，不定义当前行为：

- `docs/V1_PRODUCT_PLAN.md`
- `docs/V2_PRODUCT_PLAN.md`
- `docs/superpowers/`
- `docs/live-runs/`

旧的“核心业务语义纠偏实施计划”（Backlog 与 Ready 解耦、项目池扩容迁移）已经被后续 main 实现和生产迁移取代，状态应理解为：**Completed / Superseded by current main implementation**。

## 验收/维护原则

后续正常生产运行时，不要为了“验收数量”专门强行 Submit 10 个平台。系统应正常从 Backlog 持续准备 Ready，再由 Autofill 执行；新故障只在真实生产出现时作为独立 bug 处理。

任何未来代码变更都必须先判断：

1. 是不是当前真实生产故障；
2. 是否违反上述四阶段边界；
3. 是否会把 UNKNOWN 错当 REJECT；
4. 是否会把 `待提交` 错当 Ready；
5. 是否会破坏现有历史状态/实测事实。
