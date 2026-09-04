# Operational Helper Scripts

Scripts in this directory are executable helpers. They do not automatically define BacklinkOS business semantics.

## `prepare_screening_input.py`

所有正式批量必须先走这个入口。它逐个读取候选文件，合并 Discovery 的
`refdomain_aggregates`，按规范化域名去重，并根据历史初筛结果与
`internal-status.csv` 生成完整状态账本。不要再用 `cat 001.txt 002.txt ...` 拼文件；
任一文件缺少末尾换行都会把两个域名粘成一个。

```bash
python scripts/prepare_screening_input.py \
  --candidate-dir data/screening-candidates \
  --discovery-json outputs/backlinkos-run/02-semrush-01.json \
  --existing-results data/screening-results/latest.jsonl \
  --existing-status data/opportunities/internal-status.csv \
  --output outputs/backlinkos-run/screening-input.csv \
  --manifest outputs/backlinkos-run/screening-input.manifest.json
```

账本中的 `approved / deferred / confirmed_reject / triaged_only / unreviewed`
必须合计为 `combined_unique`。只有 `unreviewed` 进入新的 crawler 请求。

## `screening_crawler.py`

This crawler is currently used by `.github/workflows/screening-crawler.yml` for large-batch **triage**.

It intentionally performs cheap machine checks and emits preliminary buckets. Those buckets are useful for reducing follow-up work, but they are not equivalent to the final decisions required by the canonical `screening-backlinks` Skill.

正式运行必须传入已有结果；同一域名默认复用，只有明确要求重新抓取时才使用
`--fresh`：

```bash
python scripts/screening_crawler.py \
  --input outputs/backlinkos-run/screening-input.csv \
  --output outputs/backlinkos-run/screening-results.jsonl \
  --existing-results data/screening-results/latest.jsonl
```

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

一个子页的 noindex 想淘汰整个域名，必须同时满足下面四条。每条都对应实测到的误杀，
实跑 4180 条时这组守卫把 66 条 noindex 判死收敛到 23 条，救回 43 条：

1. **不是盲探来的。** SPA 对任意不存在路径返回软 200 + noindex，壳里的文案还可能撞上机制正则——`polymarket.com` 的 `/submit`、`/add`、`/submit-site` 全是这样。
2. **和站点同源。** `aitools.fyi` 曾被第三方表单站 `tally.so` 的页面判死，`aicloudbase.com` 被另一个域名的页面判死。判同源要按前缀剥 `www.`，**不能用 `lstrip('www.')`**——那是按字符集剥，`wow.com` 会变成 `o.com`。
3. **不是登录墙、也不是跳转后的落地页。** 登录页 noindex 天经地义；而且跳转参数里写着 `redirectTo=/submit` 恰恰证明投稿机制存在，这种必须留 `pending`（`peerpush.com`、`whatlaunched.today`）。
4. **路径本身像投稿入口。** 目录站每个页面的导航/页脚都写着 "Submit your tool"，所以页面文案命中机制正则根本说明不了这一页是入口。只看路径才能把 `/submit/`、`/claim-your-tool/` 和 `/category/news/`、`/products`、`/forum` 分开（`kulfiy.com`、`topreviewed.ai`、`promoteproject.com` 都是这样被误杀的，其中 `promoteproject.com` 救回后成了已确认的正式机会）。

已知仍会误判的一例：`timothe.ai/tools/pdf-add-link` 是个 PDF 工具页，路径里的 `add-link` 命中了入口词。子页 noindex 判死目前保留在契约里（`test_noindex_on_real_entry_page_is_dead`）；要不要收紧成"只有首页 noindex 才判死"是一次显式的契约变更，不要顺手改。

入口链接的识别与排序：

- **锚文本必须参与匹配。** 入口常常只在可见文字里表明意图（`<a href="/s/new">Submit a tool</a>`），href 和 title 都看不出来。只匹配 href+title 会整条漏掉这类入口。
- **强弱两档排序。** `DISCOVERY_HINTS` 太宽（`blog`/`product`/`tool`/`news` 都算），命中的泛导航链接会把候选列表占满，真正的 `/submit` 挤不进 probe 的请求预算。`ENTRY_HINTS` 只收几乎必然是投稿入口的词，排在前面。
- **`ENTRY_HINTS` 必须带词边界。** `disclaimer` 里含 `claim`——实测没有 `\b` 时，新增命中里有 4/10 是 `/disclaimer`，纯属浪费预算。
- 每个域名的探测预算由 `--max-probes` 控制（默认 20）。`COMMON_PATHS` 按命中概率排序，靠前的先试。

## `verify_opportunity.py`

把爬虫留下的 `mechanism_needs_link_verification` 候选推过最后一公里：抓一个**用户产出的详情页**，确认最终外链的 `rel`、页面可索引性和免费/付费信号，产出 `data/opportunities/`。

样例页必须是详情页。首页、分类页、标签页上的外链是站点自己的导航，不能证明"用户提交之后产出的那条链接"是什么 rel——用它们判定会把 `dev.to/t/productivity` 这种聚合页当成证据，得出偏乐观的结论。

它同样不是最终决策引擎：`处理结果=正式机会` 表示机器已闭环 Follow + 可索引 + 免费措辞，仍应按 Skill 复核后才写入正式外链总表。

浏览器兜底与最终核验也必须复用已有深入状态。默认不重查
`internal-status.csv` 里已经有记录的域名；只有显式传
`--recheck-existing-status` 才重新处理：

```bash
python scripts/browser_probe.py \
  --input outputs/backlinkos-run/screening-results.jsonl \
  --output outputs/backlinkos-run/browser-results.jsonl \
  --existing-status data/opportunities/internal-status.csv

python scripts/verify_opportunity.py \
  --input outputs/backlinkos-run/browser-results.jsonl \
  --out-dir data/opportunities \
  --existing-status data/opportunities/internal-status.csv
```

The crawler remains an operational helper used by GitHub Actions; its incremental reuse behavior is covered by regression tests.

Any future change that makes crawler output authoritative must be treated as a separate behavior change with explicit regression tests and a corresponding Screening Skill update.
