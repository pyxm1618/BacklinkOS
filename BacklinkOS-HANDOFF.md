# BacklinkOS 工作交接（2026-09-06 更新）

给下一个 Claude 会话：先读这份，再读 CLAUDE.md。

## 最新架构升级（2026-09-06）

主生产工作流已全面重构，解耦对旧 `screening-backlinks` 的强依赖：

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

### 核心变更点

1. **唯一控制面：`@外链管理总控表`**
   - **`外链总表`**（平台级唯一事实库）：基础状态为 `候选`、`已排除`、`失效`。
   - **字段隔离：** Discovery 严禁填写 `实测免费`、`实测需登录`、`实测登录方式`、`实测限制`、`实测链接属性`、`最后验证时间`。这些属于 `backlink-autofill` 真实执行之后的事实。UNKNOWN 必须为空。
   - **Upsert 保护：** 新域名新增为候选；已有域名不重复创建，不得覆盖已有真实实测字段，**绝不得将`已排除`或`失效`改回`候选`**。
   - **硬黑名单：** 直接来自总表 `已排除` 或 `失效` 状态，不重复研究，不重新进入项目执行队列。不维护第二套独立黑名单。
2. **最低限度 Submission Entry Enrichment**
   - 严格区分两层：**Live Evidence（真实打开页面检测到实际机制文案/控件，或首页明确 CTA） → Candidate URL → Policy Guard 校验（排除 pricing/terms/category/seo-report 等） → 写入 Sheet**。
   - **禁止 URL path 单独升级为入口：** 仅凭路径含 submit 且 HTTP 200 绝不足以成为有效入口，页面内必须实际包含机制文案/控件（`mechanism_signals`）。普通页面坚决拒绝。
   - **登录/注册墙 noindex 防误杀：** 复用 `AUTH_PATH_RE`；登录/注册墙页面带 noindex 是正常现象，只要有机制文案或登录跳转特征，绝不误杀。
   - 首页绝不能仅凭 URL 冒充入口；无页面 CTA 证据的首页一律拦截。
   - **找不到入口时：提交入口保持为空，基础状态保持为候选。绝对不因找不到入口而淘汰候选！**
3. **项目执行行 Materialization**
   - 必须运行在明确项目上下文（如 `quick-iching`）下。
   - **历史提交入口强制重新核验：** 总表现存历史 `提交入口` 必须通过现场 Live Verification 生成 `VerifiedEntry`，才能 materialize 为待提交行；未通过现场核验不生成项目行。
   - 仅当满足：`总表基础状态==候选` AND `具备现场核验通过的 VerifiedEntry` AND `当前 project_id + backlink_id 尚不存在` 时，才生成 `待提交` 行。
   - **项目行不重复：** `project_id + backlink_id` 唯一。已存在任何状态均不重复创建或重置。Quick I Ching 已有历史记录必须保护。
4. **存量池严格双边界 Bounded Batch Hydration**
   - 必须显式指定 `project_id`、`target_count` 与 `scan_limit`，满足 `succeeded >= target_count` 或 `processed >= scan_limit` 任一条件即刻停止，**绝不因大量失败而无限扫完 3000+**。
5. **`screening-backlinks` 状态**
   - 旧 Skill 退出主工作流，不要删除其历史文件，作为 legacy / optional 旁路保留。

---

## 支撑代码与回归测试

- 核心逻辑模块：`scripts/master_sheet_sync.py`
  - 纯业务契约与测试完全解耦 I/O，不引入生产凭据。
  - 复用 `scripts/screening_crawler.py` 经过全面验证的入口匹配基础设施（`ENTRY_HINTS`、`COMMON_PATHS`、Parser 锚文本等）。
- 回归测试：`tests/test_master_sheet_sync.py`（22 个用例全部 PASS），覆盖 Domain Upsert、Entry Policy Guard & Live Verification、Project Synchronization、Bounded Batch Hydration、Fact Separation 全语义。
- TS 契约测试：`tests/skill-contracts.test.ts`。

---

## 验收命令

```bash
pytest -v                                             # Python 回归测试 (45 passed)
npm test                                              # TS 契约测试 (41 passed)
npm run typecheck                                     # 类型检查
```

---

## 历史环境踩坑备忘

- 项目**必须放在 ~/Projects 之类非 TCC 目录**。放 ~/Downloads 会被 macOS TCC 反复拒绝。
- **Playwright sync API 不能在线程里用**。`sync_playwright()` 基于 greenlet，放进 ThreadPoolExecutor 会直接挂死。
- **单域名超时只能靠父进程 kill**。`page.goto` 的 timeout 管不住 route 拦截和 `page.content()`。
- **误杀防护 7 大要点**（见 `scripts/README.md`）：
  1. noindex 只认能代表站点的页面（SPA 软 404、登录墙不算）；
  2. `path:` 前缀是伪信号，不能作淘汰依据；
  3. 裸域和 www 都要试；
  4. 样例页必须是详情页；
  5. 子页 noindex 判死需同时满足四条守卫；
  6. 判同源不能用 `lstrip('www.')`；
  7. `ENTRY_HINTS` 必须带词边界。

