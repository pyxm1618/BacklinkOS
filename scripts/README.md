# Operational Helper Scripts

Scripts in this directory are executable helpers. They do not automatically define BacklinkOS business semantics.

## `screening_crawler.py`

This crawler is currently used by `.github/workflows/screening-crawler.yml` for large-batch **triage**.

It intentionally performs cheap machine checks and emits preliminary buckets. Those buckets are useful for reducing follow-up work, but they are not equivalent to the final decisions required by the canonical `screening-backlinks` Skill.

Buckets, and what each one is allowed to mean:

| bucket | 含义 | 会不会再被捞回 |
|---|---|---|
| `dead` | 已确认淘汰——404/DNS 死亡/卖链信号/真实入口页 noindex | 不会 |
| `paid` | 入口出现付费信号且无免费层证据 | 不会 |
| `pending` | 发现可执行机制，或抓取被阻止——差最后一步证据 | 会 |
| `unverified` | **没找到入口。这是证据缺失，不是淘汰结论** | 会，下一轮必须重新参与 |

`unverified` 与 `dead` 必须分开。SKILL 硬规则 11 明确「没找到入口 ≠ 回收」，把两者混成一个 `recycle` 桶会让几千条从没被真正筛过的候选看起来像已经淘汰。

Important boundary:

- the crawler may fail to discover a valid current publishing mechanism;
- a crawler `unverified` result is never sufficient evidence for a final opportunity rejection;
- final free/reciprocal/paid/uncertain classification, Follow verification, indexability verification, and evidence closure belong to `.agents/skills/screening-backlinks/`.

误杀防护（改动前先读，避免改回去）：

- **noindex 只认能代表站点的页面。** 盲探 `COMMON_PATHS` 命中的多是 SPA 软 404 或登录墙，它们的 noindex 不能代表站点（`hashnode.com`、`dev.to` 都曾因此被误杀）。
- **`path:` 前缀的机制信号是探测到真实入口路径时注入的伪信号**，不是文案证据，不能作为 noindex 淘汰的依据。
- **裸域和 `www` 都要试。** `toolify.ai` 裸域 403 / `www` 200，`medium.com` 相反。
- **不要用首页文案给子页探测加守卫。** 旧的 `should_probe_common()` 让 99% 的"无机制"判定只看过首页，`softwaretestinghelp.com/add` 这类真实入口因此被漏掉。

## `verify_opportunity.py`

把爬虫留下的 `mechanism_needs_link_verification` 候选推过最后一公里：抓一个**用户产出的详情页**，确认最终外链的 `rel`、页面可索引性和免费/付费信号，产出 `data/opportunities/`。

样例页必须是详情页。首页、分类页、标签页上的外链是站点自己的导航，不能证明"用户提交之后产出的那条链接"是什么 rel——用它们判定会把 `dev.to/t/productivity` 这种聚合页当成证据，得出偏乐观的结论。

它同样不是最终决策引擎：`处理结果=正式机会` 表示机器已闭环 Follow + 可索引 + 免费措辞，仍应按 Skill 复核后才写入正式外链总表。

The crawler and its regression tests are retained unchanged during repository hygiene cleanup because the GitHub Actions workflow actively depends on them.

Any future change that makes crawler output authoritative must be treated as a separate behavior change with explicit regression tests and a corresponding Screening Skill update.