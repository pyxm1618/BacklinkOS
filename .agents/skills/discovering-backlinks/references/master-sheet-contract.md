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
- **提交入口默认保持为空**：禁止任何未经 Live Verification 的普通字符串 URL 直接写入总表 `提交入口`。只有在通过现场真实核验（Live Verification）产出凭据时才允许记录。
- 其余未知字段及 5 个实测事实字段严格留空。

### 如果域名已存在
- **绝不重复创建新行**；
- **绝不覆盖已有真实执行字段**（`实测免费`、`实测需登录`、`实测登录方式`、`实测限制`、`实测链接属性`、`最后验证时间`）；
- **绝不得把`已排除`或`失效`重新改成`候选`**；
- 仅允许补充安全的 provenance 信息（如原有发现来源为空时补充），禁止普通字符串覆盖或写入 `提交入口`。

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
   - **禁止 URL path 单独升级为入口：** 仅凭路径含 submit 且 HTTP 200 绝不足以成为有效入口，页面内必须实际包含机制文案/交互控件（`mechanism_signals` 如 "submit your tool", "add website", "write for us"）。普通页面或空白页断然拒绝；
   - **Entry 页面本身不因 noindex 筛掉：** 提交入口表单是否 indexable 不属于价值判断条件（Indexability 属于最终建链上线结果页的验证职责）。只要机制文案真实且符合 Policy Guard，即使标记了 `noindex`，也认定为有效 Verified Entry；
   - **支持真实 Auth Wall 回调证据：** 访问真实 candidate `/submit` 时同域跳转到登录页（命中 `AUTH_PATH_RE`），且 redirect/callback 参数明确返回该提交流程时（如 `redirect=/submit`, `next=%2Fsubmit` 等），认定为合法 `auth_wall_submission`；但无回调参数的盲猜跳转坚决拒绝；
   - 首页必须确认页面本身具有明确的机制 CTA 文案（如 "Submit your tool", "Create profile to list"），不能无证据拿首页填空。
2. **Policy Guard（政策守卫拦截与 Redirect 验证）**：
   - 必须是 http/https 且同源；
   - 严格拦截非入口路径：`pricing`、`plans`、`terms`、`privacy`、`category`、`tags`、`seo-report`、`stats` 等；
   - **Redirect 后的 Final URL 重新校验：** 现场核验发生重定向时，跳转后的 `final_url` 必须重新通过 Policy Guard（拦截跳转到 pricing 或跨域逃逸），未通过则核验失败。
3. **写入决策**：
   - 只有同时具备现场真实证据且通过 Policy Guard 的 URL，才允许记录 `提交入口` 并产生内部 `VerifiedEntry`；
   - **普通新 discovery 阶段：** 提交入口默认保持为空；
   - **找不到入口时：提交入口保持为空，基础状态保持为候选。绝对不因找不到入口而淘汰候选！**
   - 严禁在这个阶段提前做免费/Follow/DR/资格等实测事实判定。

---

## 5. 项目执行行 Materialization 契约

Discovery 必须运行在**明确项目上下文**（例如 `project_id = quick-iching`）中：

### 内部 Live Verification 流程驱动
- **生产队列 Materialization 必须由内部 live verification 流程驱动：** 
  禁止外部调用者自行实例化 `VerifiedEntry(...)` 绕过现场核验；公开的编排函数 `materialize_project_row()` 必须在内部现场核验通过后，才由内部 helper 组装项目行；核验失败一律返回 `None`，杜绝任何未经验证行进入生产队列。

### 创建条件
同时满足以下四项：
1. `外链总表.基础状态 == '候选'`；
2. **经由内部 Live Verification 现场核验通过产生真实证据**；
3. 核验域名与 `外链ID` 完全一致；
4. 当前 `project_id + backlink_id` 尚不存在于 `外链管理` 中。

### 创建内容
- `项目ID = project_id`
- `外链ID = canonical domain`
- `外链域名 = canonical domain`
- `状态 = 待提交`
- `尝试次数 = 0`
- `证据摘要 = verified_entry.evidence_type: verified_entry.evidence_summary`
- 其他执行与结果列留空。

### 保护历史唯一性
- `project_id + backlink_id` 唯一。
- 若已存在任何状态（待提交、处理中、已提交、审核中、已排期、已上线、需人工、失败、不适用）：
  **绝不重新创建，绝不把状态重置为待提交。**
- Quick I Ching 已有的历史记录永远优先保护。

---

## 6. 存量池严格双边界 Bounded Batch Hydration

支持对总表存量候选池进行按批次入口注入：
- 必须显式传入 `project_id`、`target_count`（期望成功的项目行数量，默认 10）与 `scan_limit`（本次最多检查候选数，默认 30，且 `scan_limit >= target_count`）；
- **已有入口现场核验：** 对总表已存在非空 `提交入口` 的候选，现场核验其有效性；通过则生成 VerifiedEntry 并 materialize；未通过则保持候选，不生成项目行，不随意替换原 URL；
- **空入口现场探测：** 现场探测真实入口，成功则更新总表入口并生成 VerifiedEntry；
- **双边界严格停止：** 满足 `succeeded >= target_count` 或 `processed >= scan_limit` 任意一个立即停止退出；
- **严禁仅靠 target_count 在大量失败时无限扫描 3000+ 候选。**

---

## 7. Sheet 读写纪律

所有真实 Google Sheet 读写：
- 通过官方已授权 capability 执行；
- 精确定位 target row；
- 写入后立即进行 exact-row read-back 验证；
- 确保幂等，杜绝 race condition 与重复行。
