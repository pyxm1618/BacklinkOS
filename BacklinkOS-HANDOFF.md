# BacklinkOS 工作交接（2026-09-01）

给下一个 Claude 会话：先读这份，再读 CLAUDE.md。

## 背景

用户目标只有两个：**找外链**、**筛外链**。他自己用，强调「不要过度设计、不要误杀、重效果」。

诊断结论：项目 90% 的工程精力花在证据纪律上（防误判、防把未知当 0），
这些约束是对的，但**没人写那段把候选推过终点线的代码**，所以 4180 条候选跑完
正式机会是 0。这一轮就是补上那一段。

## 已完成（全部未 commit，务必先提交）

### 成果
```
data/opportunities/opportunities.csv     14 条已闭环 免费+Follow+可索引
data/opportunities/internal-status.csv   876 条全状态，153 条★只差确认免费档
```
其中 7 条已独立核验（证据页是真实用户产出页）：
fazier.com / usecasesforagents.com / mrrwars.com / thehackstack.com /
aiproductshunt.com / realaiexamples.com / peerlist.io

### 漏斗改善（同一批 4180 候选）
```
                                     改动前    改动后
mechanism_needs_link_verification      301  →   876    2.9 倍
no_generic_mechanism                  2852  →  2426
noindex                                157  →    57    救回 100 条误杀
inactive_dns                           121  →     0    www 双试全救回
paid_mechanism                          43  →   110
正式机会                                  0  →    14
```

### 代码改动
- `scripts/screening_crawler.py` — noindex 只认代表页、去掉首页守卫、
  裸域/www 双试、`path:` 伪信号、端口耗尽退避重试
- `scripts/verify_opportunity.py`（新）— 最后一公里：抓用户产出详情页判
  rel/noindex/免费信号，输出两个 CSV
- `scripts/browser_probe.py`（新）— Playwright 兜底被 Cloudflare 挡的候选，
  已优化（拦 image/media/font/stylesheet、按需等挑战、超时 20s）**尚未跑过全量**
- `scripts/browser_fallback.py`（新）— 上面那个的旧慢版，**应删除**
- `tests/test_screening_crawler.py` — 8 → 12 项，每项锁一个防误杀逻辑
- `.agents/skills/discovering-backlinks/SKILL.md` — 新增硬规则 16(备选来源)、
  17(www 双试)、20(count 只排序不删除)
- `CLAUDE.md`（新）、`scripts/README.md`、`data/README.md`、workflow timeout 45→90

## 绝对不要改回去的四处（每处对应一个真实误杀）

1. **noindex 只认能代表站点的页面** — 盲探 COMMON_PATHS 命中的多是 SPA 软 404，
   它们的 noindex 不代表站点（hashnode.com、dev.to 都因此被误杀过）
2. **`path:` 前缀的机制信号是伪信号** — 探测到真实入口路径时注入的，
   不是文案证据，不能作为 noindex 淘汰依据
3. **裸域和 www 都要试** — toolify.ai 裸域 403/www 200，medium.com 相反
4. **样例页必须是详情页** — 首页/分类页的外链是站点导航，不能证明
   「用户提交后产出的那条链接」的 rel（dev.to/t/productivity 曾被当成证据）

细节见 scripts/README.md 的「误杀防护」段。

## bucket 语义（不能混）

| bucket | 含义 | 会不会再被捞回 |
|---|---|---|
| dead | 已确认淘汰，有闭环负面证据 | 不会 |
| paid | 付费排除 | 不会 |
| pending | 有机制/被阻止，差最后一步 | 会 |
| unverified | **没找到入口 = 证据缺失，不是淘汰** | 会，下轮必须重筛 |

`unverified` 和 `dead` 混成一个 `recycle` 桶会让几千条没被真正筛过的候选
看起来像已淘汰，违反 SKILL 硬规则 11。

## 数据文件

```
/tmp/merged.jsonl    4180 条爬虫结果（8.9MB），/tmp 不受 TCC 管
```
如果 /tmp 被清了，重跑：
```bash
echo 'domain' > /tmp/cand.csv
cat data/screening-candidates/[0-9][0-9][0-9].txt | sed '/^$/d' | sort -u >> /tmp/cand.csv
python3 scripts/screening_crawler.py --input /tmp/cand.csv --output /tmp/full.jsonl --workers 25 --timeout 8
```
注意 **workers 别超过 25** —— 40 会打满本机端口，1456 条被误记成不可达。

## 待办

1. **先 git commit**（全部未提交）
2. 删掉 `scripts/browser_fallback.py`（保留 browser_probe.py）
3. 跑浏览器兜底 455 条 blocked：
   ```bash
   python3 scripts/browser_probe.py --input /tmp/merged.jsonl --output /tmp/bp.jsonl --workers 5
   python3 scripts/verify_opportunity.py --input /tmp/bp.jsonl --out-dir data/opportunities
   ```
   先 `--limit 15` 测速，之前未优化版 12 条跑了 10 分钟没完
4. **写 Google Sheet** —— 用户已确认用这张表：
   `1gAia71b4ts_vghzLZaFvXkEkFbgS3NJv9uVEPmeyY68`
   （另一张 `1DcA54Ra...` 是 401，读不了，不用）
   已确认映射，**不用新建表结构**：
   ```
   正式机会   → 已确认免费Follow (32 行)
   待确认     → 证据不足 (2997 行)
   已确认淘汰 → 筛选回收站 (1778 行)
   付费排除   → 已排除付费 (36 行)
   ```
   不要动 `免费外链机会`(120 行) —— 那是用 A/B/C 优先级的历史表。
   需要用户提供服务账号 JSON。写入按 SKILL 硬规则 13：
   target-first（先写目标→回读确认→再动源数据），不碰公式列。
5. Semrush 中转自动化（改进 6，未做）— Playwright 持久化 profile 驱动
   `.agents/skills/discovering-backlinks/scripts/semrush-relay-batch.js`。
   该脚本有 `return output`、无手工点击依赖，可 `page.evaluate()` 直接取返回值。
   **仍走 sem.3ue.com 中转，不碰硬规则 6**。需要用户登录一次。
6. 2426 条 `unverified` 值得用更多路径模式或浏览器再筛一轮（不是淘汰）

## 环境坑

- 项目**必须放在 ~/Projects 之类非 TCC 目录**。放 ~/Downloads 会被 macOS TCC
  反复拒绝，且 `tccutil reset` 会清掉自己刚勾的授权，形成恶性循环。
- Playwright chromium 已装好，验证有效：Toolify /new、TAAFT /new/、
  medium.com、guru99.com 四个之前全 403 的现在全 200。
- 别同时开十几个 claude 实例。

## 验收

```bash
npm test                                        # 应 39 项通过
python3 -m unittest tests/test_screening_crawler.py   # 应 12 项通过
npm run typecheck
```
