# AGENTS.md

This repository hosts BacklinkOS and coordinates with `backlink-autofill` for backlink submissions.

## 正式使用入口 (Formal Submission Workflow)

当用户在新会话中输入类似指令：
> “按本项目正式流程，为 quick-iching 提交外链，本轮目标新增成功提交 200 个。”

**所有 AI 宿主（Codex, Gemini, Claude 等）必须遵循唯一权威正式流程：**
👉 **[docs/FORMAL_SUBMISSION_WORKFLOW.md](docs/FORMAL_SUBMISSION_WORKFLOW.md)**

### 执行要点摘要
1. **自动衔接**：严禁要求用户手动提供 Ready 清单或先跑准备脚本。无 Ready 清单时，由正式入口自动进行有界的 Phase C 现场核验，将 VerifiedEntry 写回【外链总表.提交入口】并生成 Ready Allowlist。
2. **当前 AI 驱动真实提交**：提交执行阶段由当前 AI 会话驱动 `backlink-autofill` 插件与 `browser_cli` 运行浏览器操作。模拟结果仅用于测试，严禁作为正式提交路径。
3. **有限范围与双边界**：以启动时候选快照为界，最多覆盖一轮；达到成功目标（如 200 个）或本轮候选耗尽时停止，绝不无限扩扫。
4. **运行状态全持久化**：进度、检查记录与待人工挂起保存至磁盘（`~/.backlinkos/runtime/cycles/<project_id>/`），新会话可直接恢复。
5. **排除分类与跨项目同步**：
   - 平台全局不可用（死站、关闭收录）：总表记已排除/失效，有限同步其他项目尚未开始的 `待提交` 记录为不适用/失败；
   - 项目不兼容（如 AI-only）：仅写当前项目不适用，总表记录事实，其他项目根据自身条件判断，绝不连带排除；
   - 付费-only：记录实测非免费事实，由各项目政策决定；
   - 超时/未找到入口等未知：保持为候选，不永久排除。
6. **尝试计数与人工交接闭环**：
   - 驱动浏览器操作前必须执行 `start-attempt` 进入 `处理中` 并递增 `尝试次数`（断点恢复不递增）；
   - 遇到验证码/2FA等真阻碍，必须保留可见 headed 标签页，获取 CDP `target_id`，联动落地 `~/.backlink-autofill/runtime/human-pending/{project_id}/{backlink_id}.json`，向用户输出指引后立即继续处理当前批次其他项；若现场因故丢失则标记 `needs_rebuild`，给出重新打开指引；
   - 执行完成调用 `record-outcome` 写回终态并回读核验尝试次数；提前中止必须调用 `record-interruption` 记录明确原因（查不明记为未知中断），绝不把对账平衡当作任务完成。
7. **探测账本冷却期复用**：
   - 探测账本记录跨轮次事实，支持 7 天冷却期复用无入口和否定结果，到期重验，超时项始终保留为候选。
8. **平台事实自动沉淀与跨项目复用**：
   - 调用 `record-outcome` 传入 `--platform-facts`，自动安全回写【外链总表】（更新有效入口、清除错误入口并记否定备注、合并实测限制、沉淀免费与登录要求），写后整行回读核验；
   - 后续项目准备时直接复用沉淀入口，避开已否定入口；未知属性严格保持未知，独立研判不误伤；
   - 回写异常持久化至全局共享 `pending_master_mutations.json`，新会话启动任一项目均自动发现并恢复。

### 常用命令
```bash
# 启动/恢复指定项目的自动化提交流程
python3 scripts/run_submission_cycle.py --project-id quick-iching --target-success 200

# 记录结果并沉淀平台事实
python3 scripts/run_submission_cycle.py record-outcome --project-id quick-iching --backlink-id <bid> --status <status> --reason "<原因>" --evidence "<证据>" --platform-facts '{"entry_url": "...", "free": "免费", "requires_login": "否"}'

# 记录提前中断原因
python3 scripts/run_submission_cycle.py record-interruption --project-id quick-iching --reason "<明确原因>"

# Python 回归测试
PYTHONPATH=. pytest -v

# TS 契约测试
npm test
```
