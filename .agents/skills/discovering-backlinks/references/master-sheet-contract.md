# Master Sheet and Project Management Contract

本文档定义 BacklinkOS 新控制面（`@外链管理总控表`）与 Discovery 之间的契约规范。

## 1. 唯一控制面与分工原则

```text
Discovery:
- 发现候选 referring domains
- canonicalize / 去重
- 外链总表 Upsert（平台 Source of Truth）
- 最低限度 Submission Entry Enrichment
- 为明确项目创建外链管理待提交行（Materialization）

Autofill:
- 真实浏览器执行
- 登录、注册、邮箱核验、填写表单、Final Submit
- 回写实际状态、结果链接、实测免费、实测需登录、实测登录方式、实测限制、实测链接属性
```

**核心纪律：**
Discovery 负责发现和最低限度执行入口准备；`backlink-autofill` 负责真正判断与执行。不要在中间重新创造一个新的 Screening 层。

---

## 2. 表结构契约

### Tab 1: `外链总表`（平台级唯一事实库）

固定 14 列：

| 列名 | 字段类型 | 填写角色 | 说明与取值约束 |
|---|---|---|---|
| 外链ID | 文本 | Discovery / 系统 | canonical domain，稳定 join key（如 `example.com`） |
| 平台域名 | 文本 | Discovery / 系统 | canonical domain，便于人类阅读 |
| 提交入口 | URL | Discovery | 真实验证的提交入口 URL，未验证时保持为空 |
| 发现来源 | 文本 | Discovery | 本次真实发现来源（如 `semrush_competitor:xxx`, `toolify` 等） |
| 发现时间 | 日期/时间 | Discovery | 本次首次发现时间（ISO 8601 或 YYYY-MM-DD） |
| 基础状态 | 单选枚举 | Discovery / 审计 | 仅限：`候选`、`已排除`、`失效` |
| 基础排除原因 | 文本/枚举 | 审计 / 历史迁移 | 如 `明确付费-only`、`无可执行入口`、`垃圾/PBN/负面SEO`、`自动报告页/非人工可获取`、`恶意/风险`、`已失效`；候选时为空 |
| **实测免费** | 文本 | **Autofill** | **Discovery 严禁填写！必须保持为空！** |
| **实测需登录** | 文本 | **Autofill** | **Discovery 严禁填写！必须保持为空！** |
| **实测登录方式** | 文本 | **Autofill** | **Discovery 严禁填写！必须保持为空！** |
| **实测限制** | 文本 | **Autofill** | **Discovery 严禁填写！必须保持为空！** |
| **实测链接属性** | 文本 | **Autofill** | **Discovery 严禁填写！必须保持为空！** |
| **最后验证时间** | 日期/时间 | **Autofill** | **Discovery 严禁填写！必须保持为空！** |
| 平台备注 | 文本 | 通用 | 备注说明 |

### Tab 2: `外链管理`（项目级执行队列/历史）

固定 10 列：

| 列名 | 字段类型 | UI 属性 | 填写角色 | 说明 |
|---|---|---|---|---|
| 项目ID | 文本 | 显示 | Discovery / 项目上下文 | 如 `quick-iching` |
| 外链ID | 文本 | 可隐藏 | Discovery | canonical domain，精确 join `外链总表.外链ID` |
| 外链域名 | 文本 | 显示 | Discovery | canonical domain |
| 状态 | 单选枚举 | 显示 | Discovery / Autofill | `待提交`、`处理中`、`已提交`、`审核中`、`已排期`、`已上线`、`需人工`、`失败`、`不适用` |
| 尝试次数 | 数字 | 可隐藏 | 系统 / Autofill | 初始为 0 |
| 最近操作时间 | 时间 | 显示 | Autofill | 初始为空 |
| 目标URL | URL | 可隐藏 | 项目配置 / 指定 | 初始为空（由项目 profile 使用默认 canonical URL），或显式指定深链 |
| 结果链接 | URL | 显示 | Autofill | 最终建链成功的公开链接，初始为空 |
| 原因/备注 | 文本 | 显示 | Autofill / 人工 | 初始为空 |
| 证据摘要 | 文本 | 显示 | Autofill | 真实执行产生的证据摘要，初始为空 |

---

## 3. 总表 Upsert 与数据保护契约

每发现一个 referring domain，必须先进行规范化：
- 剥离 http/https、www、小写、剥离 trailing slash 及 path/query；
- 外链ID = canonical domain，平台域名 = canonical domain。

### 如果域名不存在
- 新增行：`外链ID=canonical domain`、`平台域名=canonical domain`、`基础状态=候选`、`发现来源=本次真实来源`、`发现时间=本次时间`。
- **提交入口严格保持为空**：`upsert_master_rows` 彻底禁止写入提交入口（无论普通字符串还是 VerifiedEntry），纯粹负责 domain 和 provenance upsert。提交入口只能由真实 Entry Enrichment orchestration 核验成功后写入。
- 其余未知字段及 5 个实测事实字段严格留空。

### 如果域名已存在
- **绝不重复创建新行**；
- **绝不覆盖已有真实执行字段**（`实测免费`、`实测需登录`、`实测登录方式`、`实测限制`、`实测链接属性`、`最后验证时间`）；
- **绝不得把`已排除`或`失效`重新改成`候选`**；
- 仅允许补充安全的 provenance 信息（如原有发现来源为空时补充），绝不更新 `提交入口`。

### 硬黑名单机制
如果查询发现总表中域名的 `基础状态 == 已排除` 或 `基础状态 == 失效`：
- 视为“历史已知硬负例”；
- 不重复研究，不重新进入项目执行队列，不覆盖排除原因；
- 不再维护第二套独立黑名单数据库。

---

## 4. 最低限度 Submission Entry Enrichment

针对 `基础状态 == '候选'` 且准备进入项目执行队列的平台，进行真实入口查找与现场核验（Live Verification）：

### 核心架构原则
1. **Live Evidence（真实页面证据）**：
   - 实际请求目标页面（HTTP 200，同源）；
   - **正文机制文案仅作为 Hint，绝不得单独升级为 Entry：** 普通 SEO 文章、搜索结果页（`?q=`）、软文即便出现 "submit product"、"guest post" 等文字，若无真实提交表单或合规认证墙，坚决不判 Verified Entry；
   - **Actionable Form 最低证据要求：**
     - Directory / Tool Listing：必须包含至少一个资源身份字段（如 `url / website / site / tool / product / app / startup / business / listing`），再加 submit 按钮；**普通 Contact 表单（如姓名 + 邮箱 + Message + Submit）严格排除**；
     - Guest Post：必须在“投稿/写文章”上下文（URL 路径或标题/正文含有 `write for us / guest post / submit article / contribute`）下，且表单包含投稿相关字段（如 `article / pitch / content / draft` 或 `url / website`）；
   - **CTA Link 追踪（来源页绝不能当 Entry）：** 页面出现 `Submit a Tool` 等 CTA 按钮时只能作为 Candidate 链接，来源页本身不是 Entry；必须跟随打开目标页，只有目标页本身具备 Actionable Form 时，才以目标页为 Entry；
   - **跨域 Form Action 拦截：** 表单 action 若指向外部第三方域名，直接判定为跨域非法表单并排除，防止把中间跳转 landing page 当 Entry；
   - **Entry 表单与首页不因 noindex 筛掉：** Entry discovery 不以 indexability 淘汰。表单页或首页带 noindex 绝不阻断后续真实机制入口的发现；
   - **支持真实 Auth Wall 回调证据：** 访问真实 candidate `/submit` 时同域跳转到登录页（`AUTH_PATH_RE`），且 redirect/callback 参数明确返回该提交流程时，认定为有效入口。
     - **来源证明严格要求：** 页面缺少机制文案时，必须要求具备真实页面 CTA/link 发现依据（`ENTRY_HINTS` 只能用于探测，绝不得作为来源证据）；
     - **历史 Master Entry 不默认放行：** 默认未经来源证明，不能因为跳转 `/login?redirect=/submit` 自动升级；
     - **保留原始稳定 Submission URL：** `VerifiedEntry.url` 记录原始稳定的 entry URL，而不是带有会话参数的 `/login?...` 临时 URL，证据摘要不记录完整 query/token；
     - **Callback 同源校验：** callback 若为绝对 URL，必须验证 hostname 与平台同源；外部跨域 callback 坚决拒绝；
   - 首页必须确认页面本身具有明确的机制 CTA 文案（如 "Submit your tool", "Create profile to list"），不能无证据拿首页填空。
2. **Policy Guard（政策守卫拦截与 Redirect 验证）**：
   - 必须是 http/https 且同源；
   - 严格拦截非入口路径：`pricing`、`plans`、`terms`、`privacy`、`category`、`tags`、`seo-report`、`stats` 等；
   - **私有控制台保护：** 拦截 `/dashboard`、`/app/overview`、`/console` 等路径，除非 query 携带明确提交意图；
   - **Redirect 后的 Final URL 重新校验：** 现场核验发生重定向时，跳转后的 `final_url` 必须重新通过 Policy Guard（拦截跳转到 pricing、私有控制台或跨域逃逸），未通过则核验失败。
3. **写入决策**：
   - 只有同时具备现场真实证据且通过 Policy Guard 的 URL，才允许记录 `提交入口` 并产生内部 `VerifiedEntry`；
   - **普通新 discovery 阶段：** 提交入口默认保持为空；
   - **找不到入口时：提交入口保持为空，基础状态保持为候选。绝对不因找不到入口而淘汰候选！**
   - 严禁在这个阶段提前做免费/Follow/DR/资格等实测事实判定。

---

## 5. 项目 Backlog Projection 与 Execution Readiness 契约

Discovery 必须运行在**明确项目上下文**（例如 `project_id = quick-iching`）中：

### A. 全量 Project Backlog Projection（纯数据库投影）
- **核心原则：UNKNOWN != REJECT。**
- 凡是 `外链总表.基础状态 == '候选'` 且无已持久化项目硬不兼容事实的平台，一律默认生成项目待提交行。
- 严禁在该阶段要求 Master 提交入口非空，禁止做网络请求。
- **通用 Project Compatibility Hard Gate：**
  针对平台的已持久化强事实约束（如已确认 `AI-only` 且 `project_context.ai_powered == False`），纯数据库/内存逻辑拦截不为该项目生成行，Master 本身保持候选；若缺乏明确强事实，一律作为 UNKNOWN 默认生成待提交行。
- **创建内容：**
  `项目ID = project_id`, `外链ID = canonical domain`, `外链域名 = canonical domain`, `状态 = 待提交`, `尝试次数 = 0`, `目标URL = 指定或默认`, 结果列与证据列留空。
- **保护历史唯一性：**
  `project_id + backlink_id` 唯一。若已存在任何状态（待提交、处理中、已提交、审核中、已排期、已上线、需人工、失败、不适用），绝不重复创建，绝不重置状态和尝试次数。Quick I Ching 已有历史记录必须优先保护。

### B. Bounded Execution Preparation（小批量执行就绪准备）
- 从已有 `待提交` 记录中筛选小批量（如 `target_ready_count=10`，`scan_limit=50`）进行现场核验；
- 只有经内部现场 Live Verification 核验通过产生真实证据（VerifiedEntry），才标记为 Ready for Autofill、写回 Master 提交入口，并生成 Ready Allowlist Manifest；
- 未能验证或 unresolved 的项目行，继续保持在 Backlog 中（状态保持 `待提交`，尝试次数保持 0，不标失败）；
- **Handoff 契约**：下游 `backlink-autofill` 只能消费该 Ready Allowlist 与待提交的交集，绝不能直接盲目拉取 Sheet 待提交行，防止将未准备就绪的合法 Backlog 误报失败。

---

## 6. 存量池严格双边界 Bounded Batch Hydration

支持对总表存量候选池进行按批次执行就绪准备（Execution Preparation）：
- 必须显式传入 `project_id`、`target_count`（期望成功的项目行数量，默认 10）与 `scan_limit`（本次最多检查候选数，默认 30，且 `scan_limit >= target_count`）；
- **已有入口现场核验：** 对总表已存在非空 `提交入口` 的候选，现场核验其有效性；通过则生成 VerifiedEntry 并进入 Ready 队列；未通过则保持候选，不进入 Ready 队列，不随意替换原 URL；
- **空入口现场探测：** 现场探测真实入口，成功则更新总表入口并生成 VerifiedEntry；
- **双边界严格停止：** 满足 `succeeded >= target_count` 或 `processed >= scan_limit` 任意一个立即停止退出；
- **明确边界：** 此参数仅控制单次 Ready 批次规模，绝不限制 Project Backlog 总规模。


---

## 7. Sheet 读写纪律

所有真实 Google Sheet 读写：
- 通过官方已授权 capability 执行；
- 精确定位 target row；
- 写入后立即进行 exact-row read-back 验证；
- 确保幂等，杜绝 race condition 与重复行。
