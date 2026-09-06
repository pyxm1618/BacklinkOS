---
name: discovering-backlinks
description: Use when the user asks to 抓外链, 找外链, 批量抄竞品外链, 扩大外链库, discover backlink candidates, or continue an existing backlink-discovery batch.
---

# 抓外链

## 目标

从近期已经跑出 SEO 结果的项目反查真实 Referring Domains，规范化后对平台级唯一事实库【外链总表】实行 Upsert，全量投影项目待提交 Backlog（UNKNOWN != REJECT），执行小批量 Bounded Execution Preparation 进行现场 Submission Entry 核验，并在明确项目上下文中为 `backlink-autofill` 准备 Ready 队列。

**核心原则：**
- **PHASE A (Master Upsert)**：负责**发现候选**并合并入库，新行提交入口保持为空，不预设实测字段；
- **PHASE B (Project Backlog Projection)**：纯数据库投影，Master 候选默认全量生成项目【外链管理】`待提交` 行，UNKNOWN != REJECT；
- **PHASE C (Bounded Execution Preparation)**：每次小批量（如 10/20/50）进行 Submission Entry 现场核验；Only VerifiedEntry may become READY FOR AUTOFILL，但 VerifiedEntry is NOT required for existence in Project Backlog；
- **PHASE D (`backlink-autofill`)**：通过真实浏览器执行，真正判断免费、登录、限制、提交、上线和链接属性；
- 不在中间重新创造一个新的 Screening 层；旧的 `screening-backlinks` 已退出主工作流（仅作为 legacy / optional 历史排查工具保留）。

## 架构与数据流 (Phase A ~ Phase D)

```text
【PHASE A — Discover / Upsert Master】
发现真实 referring domains
        ↓
canonicalize / 去重
        ↓
写入或合并【外链总表】（Master Sheet Upsert，提交入口严格留空）
        ↓
【PHASE B — Project Backlog Projection】
纯数据库/内存投影（无网络IO）
Master 候选（剔除已排除/失效/已证实硬不兼容）默认生成【外链管理】待提交行
Backlog Size 达到数千规模（UNKNOWN 默认包含，保护历史行）
        ↓
【PHASE C — Bounded Execution Preparation】
小批量（10 / 20 / 50）Bounded Batch Hydration 与现场核验
已有入口 Live Revalidate / 空入口现场探测 (Live Evidence + Policy Guard)
核验通过产出 VerifiedEntry 并写回 Master.提交入口，生成 Ready for Autofill 队列
        ↓
【PHASE D — backlink-autofill】
真实浏览器自动化执行（登录、填表、提交、上线校验）
        ↓
回写真实平台事实和项目执行结果
```

## 硬规则

1. **只传事实，不传推测。** 当前工具/数据源没有直接给出的字段就留空；Discovery 绝对不填写：`实测免费`、`实测需登录`、`实测登录方式`、`实测限制`、`实测链接属性`、`最后验证时间`。这些属于 `backlink-autofill` 真实浏览器执行之后的事实。UNKNOWN 必须为空。
2. **唯一控制面与总表 Upsert 契约。** 控制面以 `@外链管理总控表` 为唯一准绳。平台级唯一事实库为 `外链总表`（基础状态仅有：`候选`、`已排除`、`失效`）。
   - 每发现一个 referring domain，先 canonicalize（剥离 http/https、www、小写、剥离 trailing slash 及 path/query）。
   - **外链ID = canonical domain，平台域名 = canonical domain**（外链ID 是稳定 join key）。
   - **`upsert_master_rows` 彻底禁止写入提交入口**：只负责平台域名与来源 provenance 合并；新行 `提交入口` 默认必为空，已有行绝不更新 `提交入口`。提交入口严格只能由真实 Entry Enrichment orchestration 核验成功后写入。
   - 若域名不存在：新增记录，`基础状态=候选`，记录真实发现来源与时间，实测字段留空。
   - 若域名已存在：**不得重复创建**，不得覆盖已有真实执行字段，**绝不得将`已排除`或`失效`重新改成`候选`**，新发现只能补充安全的 provenance 信息。
3. **硬黑名单直接来自外链总表。** 若发现 domain 查询显示 `基础状态=已排除` 或 `基础状态=失效`，则视为历史已知硬负例：不重复研究，不重新进入项目执行队列，不覆盖排除原因，记录历史事实即可。不再维护第二套独立黑名单数据库。
4. **最低限度 Submission Entry Enrichment（执行就绪核验）。** 针对准备进入执行队列的平台，在 Execution Preparation 阶段确认真实可执行入口：
   - 严格区分两层：**Live Evidence（真实打开页面检测到可操作提交表单 Actionable Form，或同域合法认证墙，或首页明确 CTA） → Candidate URL → Policy Guard 校验 → 写入 Sheet**。
   - **正文机制文案仅作为 Hint，绝不得单独升级为 Entry：** 普通 SEO 文章、搜索结果页（`?q=`）、软文即便出现 "submit product"、"guest post" 等文字，若无真实提交表单或合规认证墙，坚决不判 Verified Entry。
   - **禁止 URL path 单独升级为有效入口：** 仅凭路径类似 `/submit` 且 HTTP 200 绝不足以成为真入口，页面内必须实际包含真实可操作表单（Actionable Form）或合规认证墙。普通文章或空白页坚决拒绝。
   - **Actionable Form 最低证据要求：**
     - Directory / Tool Listing：必须包含至少一个资源身份字段（如 `url / website / site / tool / product / app / startup / business / listing`），再加 submit 按钮；**普通 Contact 表单（如姓名 + 邮箱 + Message + Submit）严格排除**；
     - Guest Post：必须在“投稿/写文章”上下文（URL 路径或标题/正文含有 `write for us / guest post / submit article / contribute`）下，且表单包含投稿相关字段（如 `article / pitch / content / draft` 或 `url / website`）。
   - **CTA Link 追踪（来源页绝不能当 Entry）：** 页面出现 `Submit a Tool` 等 CTA 按钮时只能作为 Candidate 链接，来源页本身不是 Entry；必须跟随打开目标页，只有目标页本身具备 Actionable Form 时，才以目标页为 Entry。
   - **跨域 Form Action 拦截：** 表单 action 若指向外部第三方域名，直接判定为跨域非法表单并排除，防止把中间跳转 landing page 当 Entry。
   - **私有控制台保护：** 重定向终态若为用户私有控制台（如 `/dashboard`、`/app/overview`、`/console`），除非 query 明确携带未完成的提交上下文，否则坚决拒绝。
   - **Entry 表单与首页不因 noindex 筛掉：** Entry discovery 不以 indexability 淘汰。表单页或首页带 noindex 绝不阻断后续真实机制入口的发现。
   - **支持真实 Auth Wall 回调证据：** 访问真实 candidate `/submit` 时同域跳转到登录页（`AUTH_PATH_RE`），且 redirect/callback 参数明确返回该提交流程时，认定为有效入口。
     - **来源证明严格要求：** 页面缺少机制文案时，必须要求具备真实页面 CTA/link 发现依据（`ENTRY_HINTS` 只能用于探测，绝不得作为来源证据）；
     - **历史 Master Entry 不默认放行：** 默认未经来源证明，不能因为跳转 `/login?redirect=/submit` 自动升级；
     - **保留原始稳定 Submission URL：** `VerifiedEntry.url` 记录原始稳定的 entry URL，而不是带有会话参数的 `/login?...` 临时 URL，证据摘要不记录完整 query/token；
     - **Callback 同源校验：** callback 若为绝对 URL，必须验证 hostname 与平台同源；外部跨域 callback 坚决拒绝。
   - 严禁乱填：pricing、terms、privacy、category、SEO report、普通 article、自动统计页、unrelated landing page 绝不能冒充提交入口。
   - 平台首页：只有真实确认首页存在明确的提交/收录/建链 CTA 时（如 Submit your product, Create profile, Sign up to list, Add your site）才允许作为提交入口；否则绝不能拿首页填空。
   - **找不到入口时：提交入口保持为空，候选继续保留。绝对不因为找不到入口而把候选标记为已排除！**
   - 严禁在这个阶段提前根据 Follow/Nofollow/DR/免费性等淘汰候选。
5. **项目 Backlog Projection 与 Execution Readiness 契约。** Discovery 必须运行在**明确项目上下文**中（例如 `当前项目 = quick-iching`）：
   - **PHASE B — Project Backlog Projection（全量机会池生成）：**
     - 纯数据库级投影，零网络 IO，**禁止要求 Master 提交入口非空**；
     - **UNKNOWN != REJECT：** 入口未知、免费未知、需登录未知、Follow 未知等绝不阻断进入项目 Backlog；
     - **通用 Project Compatibility Hard Gate：** 针对平台的强类型约束（如已持久化强事实标明 `AI-only` 平台强约束要求仅接受 AI 工具），在 `project_context.ai_powered == False`（非 AI 项目如 Quick I Ching）时，拦截不为其生成项目待提交行，同时总表基础状态保持为 `候选`（不影响其他 AI 项目复用）；若缺乏明确证据，UNKNOWN 默认包含；
     - **绝对不能创建重复项目行：** `project_id + backlink_id` 唯一。若已存在（待提交、处理中、已提交、审核中、已排期、已上线、需人工、失败、不适用 任何一种），绝不重新创建或重置为待提交。Quick I Ching 已有历史记录必须优先保护；
     - 待提交行默认值：`项目ID=当前项目ID`、`外链ID=canonical domain`、`外链域名=canonical domain`、`状态=待提交`、`尝试次数=0`、`目标URL=默认 canonical URL 或指定深链`、其他结果字段留空。
   - **PHASE C — Bounded Execution Preparation（小批量执行就绪准备）：**
     - 从已有 `待提交` 记录中按批次处理（如 `target_ready_count=10`，`scan_limit=50`）；
     - 关联 Master 进行现场核验（已有入口 Live Revalidate，空入口现场探测）；
     - **核验通过才成为 Ready for Autofill**（写入 Master 提交入口，组装 VerifiedEntry 批次）；
     - **核验失败或 unresolved：项目行仍保留，状态仍为待提交，尝试次数仍为 0，不标失败，继续下一候选**。
6. **存量池严格双边界 Bounded Batch Hydration。** 支持对总表存量候选池按批次进行 Execution Preparation：
   - 必须显式传入 `project_id`、`target_count`（期望成功的项目行数量）与 `scan_limit`（最多检查候选数，`scan_limit >= target_count`）；
   - **双边界停止条件：** `succeeded >= target_count` 或 `processed >= scan_limit` 任意一个达到立即停止退出；
   - 严禁仅靠目标数量在大量失败时无限扫描 3000+ 候选。
   - 明确说明：此机制只控制本次 Ready Preparation 数量，绝不能限制 Project Sheet 总人口。

7. **Semrush 查询固定优先走已经跑通的 `sem.3ue.com` 中转。禁止因为官方 Semrush API units 不足而停止，也禁止改走需要 API units 的官方 Semrush API/connector。** 中转会话失效时，只处理登录/会话问题后继续中转。
8. **Semrush 正式批量必须使用 `scripts/semrush-relay-batch.js`。** 不得每次重新猜 endpoint、参数、分页、字段语义或 session key 获取逻辑。
9. runner 必须自动恢复并验证 session key；不能只依赖 `performance`。当 `performance=[]` 时继续走已验证的 32-hex 候选扫描和有界运行时扫描。不得让用户手抄 key，也不得用任意 storage 值乱试。
10. Organic HTTP 200 但没有 `organic_traffic` 时必须记为 `no_data`，不是 0，也不是 API error。
11. Referring Domains 是否完整必须由 `refdomains.total` 判断；若人为设置上限，只能输出 partial，不能伪装成完整抓取。
12. 分页中 offset 不推进或下一页没有新增 domain 时，必须报分页错误，不能静默完成。
13. **任何 Semrush runner/契约调试前必须先读 `references/incidents/2026-08-21-semrush-relay-debugging.md`。** 已保存成功证据能回答的问题，不得再次让用户抓 Network、截图、手抄 key 或重复试错。
14. **Console 注入不跨页面导航。** 不能先装 hook 再让用户跳页；导航会销毁当前 JS context。需要跨导航时只能使用正式持久方案。
15. 只有精确请求实际 HTTP 200 + 响应结构通过，才能称“已验证”。page0 成功不能自动扩展成“分页已验证”。
16. **100 是批次单位，不是停止条件。** 用户要求继续扩大外链库时，可以连续建立多个去重批次；不能因为单批达到 100 个项目就宣告 Discovery 完成。
17. **控制来源集中度。** 记录项目种子的来源占比；当一个来源明显集中时，优先继续使用已经批准的其他来源（如 Toolify / There’s An AI For That / TrustMRR）补充，再考虑继续向单一来源深挖。Toolify 与 TAAFT 的列表页受 Cloudflare 保护时改用浏览器自动化，或补充 Product Hunt、Indie Hackers、Futurepedia、MicroLaunch、Uneed、BetaList 等来源。
18. **域名请求同时试裸域和 `www`。** 两者的 Cloudflare/DNS 策略常不一致。只试一个会把可用来源误判成不可达。
19. **Semrush 暂时不可用时只积累项目事实。** 内部状态可记为 `pending_semrush`；当前 Google Sheet `项目池` 落表必须沿用既有 schema：`SEO筛选状态=待Semrush`、`RD状态=待Semrush筛选`。不得把字面值 `pending_semrush` 写进现有状态列，也不得填造未知字段。
20. **`successful_project_count` 只用于排序，不用于淘汰。** 覆盖项目多的候选先进入执行准备，但只被 1 个项目引用的域名同样保留在候选池里，任何阶段都不因为这个数字丢弃候选。
21. **[可选历史旁路] 按需支持 source URL enrichment。** 若在特定排查中需要复用 legacy `screening-backlinks`，当其返回 `source_url_enrichment_required` 时，Discovery 仅按 `references/screening-handoff.md` 补全 `source_url` 等来源页历史事实。但这不再是默认主链路的必经环节。

## 每批怎么跑

1. 默认每批找 **100 个新的候选项目**；先与历史项目池去重，并给本批一个批次 ID。100 是工作批次大小，不限制后续继续扩批。
2. 优先从 Toolify、There’s An AI For That、TrustMRR 找近期项目；记录每个来源的新增量，避免长期由单一来源主导项目池。
3. 如果 Semrush 当前不可用，核实真实 Website 后进入内部 `pending_semrush`；落表使用 `待Semrush` / `待Semrush筛选`，到此停止该项目的 RD 推进。
4. 在已登录 `sem.3ue.com` 的页面加载固定 runner，自动恢复 session key 并做 Preflight。
5. 批量查 Semrush Global Organic Traffic；默认 `>= 500` 才进入 Referring Domains 抓取。
6. 对通过项目抓 Referring Domains；根据 `refdomains.total` 自动分页抓完整，保留 complete/partial 状态。
7. 保存原始事实：来源项目、Organic 状态/流量、referring domain、backlinks_num、AS、first_seen、last_seen、lost/new、is_follow。
8. 规范化并聚合：通过 `canonical_domain` 统一格式，按 referring domain 聚合成功项目覆盖数和出现次数。
9. **更新【外链总表】(Phase A)：** 对 `@外链管理总控表` 的 `外链总表` 实行 Upsert（新增候选，保护已有实测事实与已排除/失效状态，不写任何实测字段，提交入口默认留空）。
10. **全量生成项目 Backlog (Phase B)：** 运行纯数据库 Projection（`materialize_project_backlog_rows`），为明确项目（如 `quick-iching`）生成全量待提交行（UNKNOWN != REJECT，保护现有 36 条历史记录）。
11. **小批量执行准备 (Phase C)：** 运行 `prepare_execution_batch`，受 `target_ready_count`（如 10/20）控制，现场探测/重验提交入口，验证通过标记为 Ready 供执行。
12. **交给 autofill 执行 (Phase D)：** 由 `backlink-autofill` 在真实浏览器中消费 Ready 队列并执行提交。
13. **[可选/历史旁路]** 如需调用 legacy `screening-backlinks`，按 `references/screening-handoff.md` 处理 `source_url_enrichment_required` 补证。

## 控制面契约参考

- 主控制面表结构与 Upsert/Materialization 契约见 [references/master-sheet-contract.md](references/master-sheet-contract.md)。
- Semrush 中转细节见 [references/semrush-relay.md](references/semrush-relay.md)。
- 事故复盘见 [references/incidents/2026-08-21-semrush-relay-debugging.md](references/incidents/2026-08-21-semrush-relay-debugging.md)。
- 正式执行器见 [scripts/semrush-relay-batch.js](scripts/semrush-relay-batch.js)。
- 控制面与同步核心模块见 [scripts/master_sheet_sync.py](../../scripts/master_sheet_sync.py)。
- 回归要求见 [references/test-cases.md](references/test-cases.md)。
- 可选历史 screening 补证合同见 [references/screening-handoff.md](references/screening-handoff.md)。

