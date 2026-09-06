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
- 其余未知字段及 5 个实测事实字段严格留空。

### 如果域名已存在
- **绝不重复创建新行**；
- **绝不覆盖已有真实执行字段**（`实测免费`、`实测需登录`、`实测登录方式`、`实测限制`、`实测链接属性`、`最后验证时间`）；
- **绝不得把`已排除`或`失效`重新改成`候选`**；
- 仅允许补充安全的 provenance 信息（如原有发现来源为空时补充）。

### 硬黑名单机制
如果查询发现总表中域名的 `基础状态 == 已排除` 或 `基础状态 == 失效`：
- 视为“历史已知硬负例”；
- 不重复研究，不重新进入项目执行队列，不覆盖排除原因；
- 不再维护第二套独立黑名单数据库。

---

## 4. 最低限度 Submission Entry Enrichment

针对 `基础状态 == '候选' AND 提交入口为空` 且准备进入项目执行队列的平台，进行真实入口查找：

### 两层架构原则
1. **Live Evidence（真实页面证据）**：
   - 实际请求目标页面（HTTP 200，非 noindex，同源）；
   - 从实际 HTML 中通过锚文本、链接（ENTRY_HINTS / MECHANISM_PATTERNS）定位到可执行提交子页面（如 `/submit`, `/add-tool`, `/s/new`）；
   - 或者确认首页本身具有明确的机制 CTA 文案（如 "Submit your tool", "Create profile to list"）。
2. **Policy Guard（政策守卫拦截）**：
   - 必须是 http/https 且同源；
   - 严格拦截非入口路径：`pricing`、`plans`、`terms`、`privacy`、`category`、`tags`、`seo-report`、`stats` 等；
   - 首页绝不能仅凭 URL 冒充入口；无页面 CTA 证据的首页一律拦截。
3. **写入决策**：
   - 只有同时具备真实页面证据且通过 Policy Guard 的 URL，才写入 `提交入口`；
   - **找不到入口时：提交入口保持为空，基础状态保持为候选。绝对不因找不到入口而淘汰候选！**
   - 严禁在这个阶段提前做免费/Follow/DR/资格等实测事实判定。

---

## 5. 项目执行行 Materialization 契约

Discovery 必须运行在**明确项目上下文**（例如 `project_id = quick-iching`）中：

### 创建条件
同时满足以下三项：
1. `外链总表.基础状态 == '候选'`
2. `存在真实验证的提交入口`（非空且通过 Policy Guard）
3. 当前 `project_id + backlink_id` 尚不存在于 `外链管理` 中

### 创建内容
- `项目ID = project_id`
- `外链ID = canonical domain`
- `外链域名 = canonical domain`
- `状态 = 待提交`
- `尝试次数 = 0`
- 其他执行与结果列留空。

### 保护历史唯一性
- `project_id + backlink_id` 唯一。
- 若已存在任何状态（待提交、处理中、已提交、审核中、已排期、已上线、需人工、失败、不适用）：
  **绝不重新创建，绝不把状态重置为待提交。**
- Quick I Ching 已有的历史记录永远优先保护。

---

## 6. 存量池 Bounded Batch Hydration

支持对总表存量候选池进行按批次入口注入：
- 必须显式传入 `project_id` 和 `limit`（目标批次大小，如 10）；
- 严格有界，逐个核验候选域名；
- 成功找到真实入口一个，才生成一条项目待提交行，达到 limit 即停止；
- 找不到真实入口的 domain 保持候选，提交入口留空，不生成项目行；
- **严禁一次性将 3000+ 候选全量复制或扫入项目队列。**

---

## 7. Sheet 读写纪律

所有真实 Google Sheet 读写：
- 通过官方已授权 capability 执行；
- 精确定位 target row；
- 写入后立即进行 exact-row read-back 验证；
- 确保幂等，杜绝 race condition 与重复行。
