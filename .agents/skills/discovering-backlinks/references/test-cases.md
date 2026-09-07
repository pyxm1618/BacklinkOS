# `discovering-backlinks` 回归契约

本文档记录当前 Skill 行为必须满足的文档级回归要求。

## A. Discovery / Semrush 事实纪律

1. 用户要求“抓外链 / 找外链 / 扩大外链库”时触发 `discovering-backlinks`。
2. 100 个新项目只是一个 Discovery 批次，不是长期扩池停止条件。
3. 需要 Semrush 时固定优先使用已验证的 `sem.3ue.com` relay；不要因为官方 API units 不足切换到未批准的官方 API 路径。
4. 正式批量使用已验证 runner，不在每次会话中重新猜 endpoint、参数、分页或 session key。
5. session 恢复必须自动、有界、脱敏；不得要求用户把真实 key 粘贴到聊天，也不得把 key/cookie/session material 写入 Git、Sheet 或日志。
6. 未验证 endpoint/request 不能升级为正式 relay contract；必须先有真实 HTTP 200 + 预期响应结构。
7. Organic HTTP 200 但没有 `organic_traffic` 时记为 `no_data`，不是 0。
8. `organic_traffic` 顶层值按已验证语义解释；不得因 query 参数自行改写为国家流量。
9. Referring Domains 必须依据返回 total 判断 complete/partial；分页不推进或没有新增 domain 时报告 `pagination_error`。
10. 历史 Semrush `is_follow=true` 只是历史观察，不能写成当前免费路径已确认 Follow。
11. `first_seen` 不是精确建链日期。
12. 已见 referring domain 再次出现时合并 provenance/成功项目证据，不伪装成首次发现。
13. Discovery 没有直接获得的事实留空，不猜 `free`、当前 Follow、登录要求、结果状态。
14. Semrush 暂时不可用时可内部记录 `pending_semrush`；若使用历史项目池 schema，必须映射为既有 `待Semrush / 待Semrush筛选` 等现有值，不发明新 Sheet 枚举。

## B. PHASE A — Master Upsert

15. `外链总表` 是平台级唯一事实库；`外链ID = canonical domain`。
16. 新域名 `基础状态=候选`，Submission Entry 默认空，真实执行事实空。
17. 已存在域名不重复创建。
18. Master Upsert 不覆盖已有 `实测免费 / 实测需登录 / 实测登录方式 / 实测限制 / 实测链接属性 / 最后验证时间`。
19. `已排除 / 失效` 绝不能被新 Discovery 恢复为 `候选`。
20. 硬黑名单来自 Master `已排除 / 失效`，不维护第二套并行业务黑名单。
21. 普通 Discovery Upsert 不根据项目类型提前过滤 Master 候选；项目限制在 Project Compatibility 阶段处理。

## C. PHASE B — Project Backlog Projection

22. **UNKNOWN != REJECT。**
23. Master `候选` 即使 `提交入口=""` 也可以创建项目 Backlog 行。
24. Master 候选存在历史未验证 Submission URL 字符串时，也可以创建 Backlog 行；该 URL 不自动成为 Ready evidence。
25. Master `已排除` 不创建 Backlog 行。
26. Master `失效` 不创建 Backlog 行。
27. 兼容性未知 → INCLUDE，创建 Backlog 行。
28. 已证实 AI-only + `project_context.ai_powered=False` → 对该项目 incompatible，不创建项目行；Master 本身仍可保持候选供其他项目复用。
29. AI-only + `project_context.ai_powered=True` → 不因 AI-only 本身阻断。
30. 新 Backlog 行默认：`状态=待提交`、`尝试次数=0`，结果/备注/证据为空。
31. `project_id + backlink_id` 唯一；已有任何状态都不 duplicate、不 reset status、不 reset attempt。
32. 历史 `已提交 / 审核中 / 已排期 / 已上线 / 需人工 / 失败 / 不适用` 等行完全保护。
33. **Project Backlog Population 不要求 `VerifiedEntry`。**
34. Projection 是纯数据库/内存逻辑，禁止为了决定是否创建 Backlog 而进行网络抓取。
35. `target_ready_count` / `scan_limit` 与 Project Backlog 总规模无关，不能把 Project Sheet 截断成几十条。
36. reconciliation 必须满足：`candidate_count = duplicate_preserved_count + proven_project_incompatible_count + would_create_count`。
37. `would_create_count=0` 是合法的幂等投影结果，不得要求任意最小新增数。

## D. PHASE C — Submission Entry / Ready Preparation

38. Submission Entry Enrichment 属于 Execution Readiness，不是 Project Backlog 的前置条件。
39. `Policy Guard` 必须拒绝 pricing / terms / privacy / category / report 等非提交页面。
40. URL path 叫 `/submit` + HTTP 200 不足以生成 `VerifiedEntry`。
41. 普通正文提到 “submit product / guest post” 只能作为 hint，不是 Entry evidence。
42. Directory/Tool Listing Actionable Form 必须有资源身份字段 + submit；普通 name/email/message Contact form 不够。
43. Guest Post 必须同时有投稿上下文与投稿相关表单字段。
44. CTA 来源页本身不能冒充 Entry；必须跟随到目标页并验证目标页。
45. 跨域 form action 不能被当成本平台 Entry。
46. Auth Wall 只有在同域、合法 callback/redirect、真实 Submission provenance 成立时可通过；历史 Master entry 不自动放行。
47. 找不到入口 → Master 提交入口保持空，项目行仍 `待提交`，绝不因为缺入口淘汰候选。
48. `prepare_execution_batch` 只从当前 project 的现有 `待提交` 行准备 Ready。
49. blank entry → live find 成功 → 生成真实 `VerifiedEntry` → Ready。
50. blank/stored entry → live verification unresolved → 项目仍 `待提交`、attempt 不增加，并继续扫描后续行。
51. Ready scan 必须受 `target_ready_count` 与 `scan_limit` 双边界约束。
52. Ready cursor 必须从上次扫描位置推进，避免 unresolved 头部候选长期饿死后续行。
53. Project orphan（找不到 Master）必须明确报告并跳过，不阻断 cursor。
54. **只有 Ready row 才具备 `VerifiedEntry` 可进入 Autofill Gate。**
55. `待提交 != Ready`。
56. Phase C 必须产出真实 Ready manifest / allowlist；不能用合成 allowlist 冒充真实生产 handoff evidence。

## E. AI-only Project Compatibility

57. AI-only 不能仅因为页面出现 “AI” 就成立。
58. 可以使用组合强证据：明确 AI submission object + 明确 AI eligibility/acceptance。
59. `AI or SaaS`、`AI and non-AI`、明确 general/inclusive acceptance 等必须作为 inclusive guard，防止误杀。
60. 真实 `navtools.ai` 类结构必须识别为 AI-only；Quick I Ching (`ai_powered=False`) 必须 `NOT READY` / incompatible。
61. 相同 AI-only Entry 对 `ai_powered=True` 项目可以继续通过其他正常 Ready gates。
62. 不得硬编码 `navtools.ai` 域名作为规则。

## F. PHASE C → PHASE D Handoff

63. `backlink-autofill` 只能消费：`Ready allowlist ∩ 当前 project_id ∩ Sheet 状态=待提交`。
64. standalone 无 Ready allowlist 必须 fail closed。
65. 未 Ready 的数千条 Backlog 不能被 Autofill 盲目拉取。
66. `validate-execution-start` 不能被 unresolved/non-Ready 行调用。

## G. Legacy / Optional Screening

67. `screening-backlinks` 已退出默认主链路。
68. [可选历史契约] 用户明确调用 legacy Screening 时，可以使用 `source_url_enrichment_required` 请求精确历史来源页事实。
69. `source_url`、`target_url`、`anchor`、`source_rel_observation` 等 enrichment 仍是历史发现事实，不能冒充当前执行事实。
70. legacy Screening 没完成不能阻止普通 Master 候选进入当前 Project Backlog。
