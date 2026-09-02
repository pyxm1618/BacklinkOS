# BacklinkOS 工作交接（2026-09-02 更新）

给下一个 Claude 会话：先读这份，再读 CLAUDE.md。

## 背景

用户目标只有两个：**找外链**、**筛外链**。他自己用，强调「不要过度设计、不要误杀、重效果」。

诊断结论：项目 90% 的工程精力花在证据纪律上（防误判、防把未知当 0），
这些约束是对的，但**没人写那段把候选推过终点线的代码**，所以 4180 条候选跑完
正式机会是 0。这一轮补上了那一段。

## 当前成果（全部已 commit）

```
data/opportunities/opportunities.csv     18 条已闭环 免费+Follow+可索引
data/opportunities/internal-status.csv   1002 条全状态
```
其中 7 条早前已独立核验（证据页是真实用户产出页）：
fazier.com / usecasesforagents.com / mrrwars.com / thehackstack.com /
aiproductshunt.com / realaiexamples.com / peerlist.io

### 漏斗（同一批 4180 候选，两轮累计）

```
                                     最初    现在
mechanism_needs_link_verification      301  →  1002
no_generic_mechanism（unverified）    2852  →  2314
noindex 判死                           157  →    23
inactive_dns                           121  →     0
paid_mechanism                          43  →   134
正式机会                                  0  →    18
```

## 绝对不要改回去的地方

`scripts/README.md` 的「误杀防护」段是权威版本，改动前必读。要点：

1. **noindex 只认能代表站点的页面**（SPA 软 404、登录墙都不算）
2. **`path:` 前缀是伪信号**，不能作淘汰依据
3. **裸域和 www 都要试**（toolify.ai 裸域 403/www 200，medium.com 相反）
4. **样例页必须是详情页**（首页/分类页的外链是站点导航）
5. **子页 noindex 判死要同时满足四条**：非盲探、同源、不是登录墙/跳转落地页、
   路径本身像投稿入口。这组守卫救回了 43 条，其中 promoteproject.com
   救回后成了正式机会
6. **判同源不能用 `lstrip('www.')`**——按字符集剥，`wow.com` 会变成 `o.com`
7. **`ENTRY_HINTS` 必须带词边界**——`disclaimer` 里含 `claim`

## bucket 语义（不能混）

| bucket | 含义 | 会不会再被捞回 |
|---|---|---|
| dead | 已确认淘汰，有闭环负面证据 | 不会 |
| paid | 付费排除 | 不会 |
| pending | 有机制/被阻止，差最后一步 | 会 |
| unverified | **没找到入口 = 证据缺失，不是淘汰** | 会，下轮必须重筛 |

## 数据文件

```
/tmp/final2.jsonl   4180 条最新爬虫结果（已含浏览器兜底 + 重筛 + 误杀修正）
```
/tmp 被清了就重跑（**workers 别超过 25**，40 会打满本机端口）：
```bash
echo 'domain' > /tmp/cand.csv
cat data/screening-candidates/[0-9][0-9][0-9].txt | sed '/^$/d' | sort -u >> /tmp/cand.csv
python3 scripts/screening_crawler.py --input /tmp/cand.csv --output /tmp/full.jsonl \
  --workers 25 --timeout 8 --max-probes 30
python3 scripts/browser_probe.py --input /tmp/full.jsonl --output /tmp/bp.jsonl --workers 6
python3 scripts/verify_opportunity.py --input /tmp/bp.jsonl --out-dir data/opportunities --workers 25
```

## 待办

1. **写 Google Sheet**（上轮用户选择暂缓）—— 表 `1gAia71b4ts_vghzLZaFvXkEkFbgS3NJv9uVEPmeyY68`
   已确认映射，**不用新建表结构**：
   ```
   正式机会   → 已确认免费Follow      待确认 → 证据不足
   已确认淘汰 → 筛选回收站            付费排除 → 已排除付费
   ```
   不要动 `免费外链机会`(120 行) —— 那是用 A/B/C 优先级的历史表。
   **需要用户提供服务账号 JSON**（仓库里没有任何 Google 相关代码或密钥）。
   写入按 SKILL 硬规则 13：target-first（先写目标→回读确认→再动源数据），不碰公式列。
2. **Semrush 中转自动化**（上轮用户选择暂缓）—— Playwright 持久化 profile 驱动
   `.agents/skills/discovering-backlinks/scripts/semrush-relay-batch.js`。
   该脚本有 `return output`、无手工点击依赖，可 `page.evaluate()` 直接取返回值。
   **仍走 sem.3ue.com 中转，不碰硬规则 6**。需要用户登录一次。
3. 926 条 `待确认` 里，多数是「入口页有免费措辞但样例页拿不到 rel」。
   值得用浏览器兜底跑 `verify_opportunity` 那一步（现在它只用 urllib）。
4. 2314 条 `unverified` 仍未找到入口。已经过两轮路径扩展，边际收益在递减，
   再挖建议换思路（如按站点类型分组、或人工抽样看看这些站到底长什么样），
   **但它们始终不是淘汰**。
5. 一个已知误判：`timothe.ai/tools/pdf-add-link` 是 PDF 工具页，路径里的
   `add-link` 命中入口词被判死。要不要把子页 noindex 判死收紧成
   「只有首页 noindex 才判死」是**显式契约变更**（`test_noindex_on_real_entry_page_is_dead`
   锁着），别顺手改。

## 环境坑

- 项目**必须放在 ~/Projects 之类非 TCC 目录**。放 ~/Downloads 会被 macOS TCC
  反复拒绝，且 `tccutil reset` 会清掉自己刚勾的授权，形成恶性循环。
- **Playwright sync API 不能在线程里用**。`sync_playwright()` 基于 greenlet，
  放进 ThreadPoolExecutor 会直接挂死。`browser_probe.py` 用多进程。
- **单域名超时只能靠父进程 kill**。`page.goto` 的 timeout 管不住 route 拦截和
  `page.content()`，SIGALRM 也没用（阻塞在 greenlet 的 C 调用里）。
- `outputs/` 已进 .gitignore（24MB 截图/xlsx，仓库不跟踪二进制）。
- 别同时开十几个 claude 实例。

## 验收

```bash
npm test                                              # 39 项
python3 -m unittest tests/test_screening_crawler.py   # 23 项
npm run typecheck
```
