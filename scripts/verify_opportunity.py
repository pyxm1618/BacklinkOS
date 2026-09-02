#!/usr/bin/env python3
"""把 screening_crawler 留下的 pending 候选推过最后一公里。

爬虫只回答"这个站有没有可执行入口"。这个脚本回答剩下的问题：
入口产出的公开页面，对外链接是不是 Follow、页面能不能被索引、要不要付费。

它仍然不是最终决策引擎——canonical 语义属于 .agents/skills/screening-backlinks/。
这里只把机器能闭环的事实闭环掉，把真正需要人看的挑出来。
"""
import argparse, csv, json, os, re, sys, time
import concurrent.futures
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from screening_crawler import fetch_page

ENTRY_HINT = re.compile(r'(submit|write-for-us|guest-post|contribute|add-|/add$|claim|publish|become-an-author)', re.I)

# 获取方式 / 处理结果的值域见 screening-backlinks/references/output-schema.md
FREE, RECIPROCAL, PAID, UNKNOWN = '免费', '免费换链', '付费', '不确定'
OPPORTUNITY, PAID_OUT, DEAD, UNVERIFIED, PENDING = '正式机会', '付费排除', '已确认淘汰', '未验证', '待确认'


def _root(host):
    h = (host or '').lower()
    return h[4:] if h.startswith('www.') else h


def same_site(url, domain):
    """页面必须属于候选域名本身。

    跟随重定向后 final_url 可能跳到完全无关的站（tlinks.run 的入口一度被记成
    telegram.org/submit），那样的证据对这个候选毫无意义。
    """
    return bool(url) and _root(urlparse(url).hostname) == _root(domain)


def pick_entry(rec):
    """候选的操作入口页。

    返回 (url, is_real_entry)。is_real_entry 表示这个 URL 真的是一个用户可提交
    的入口（路径本身像投稿入口），而不是退而求其次拿到的首页或列表页。

    这个区分很重要：退化来的首页不能当入口用。首页上写着 "free" 不代表存在
    免费的投稿机制——`edmontonhomesales.ca/blog/`（房产中介博客）、
    `ubi-interactive.com/category/latest-news/`（公司新闻分类页）都曾因此
    被判成正式机会，实际上这些站根本没有对外投稿入口。
    """
    domain = rec['domain']
    pages = [p for p in (rec.get('pages') or [])
             if p.get('status') == 200 and same_site(p.get('final_url'), domain)]
    for p in pages:
        if ENTRY_HINT.search(p.get('final_url', '')):
            return p.get('final_url'), True
    if pages:
        return pages[0].get('final_url'), False
    home = (rec.get('home') or {}).get('final_url')
    return (home, False) if same_site(home, domain) else (None, False)


AGGREGATE_HINT = re.compile(r'/(category|categories|sub-category|tag|tags|topic|topics|t|c|author|page|search|archive|feed)(/|$)', re.I)


def pick_sample(rec, entry):
    """一个"已经发布出来"的用户内容页——用它来看真实外链属性。

    必须是详情页。首页、分类页、标签页上的外链是站点自己的导航，
    不能证明"用户提交之后产出的那条链接"是什么 rel。
    """
    home = rec.get('home') or {}
    seen = []
    for p in rec.get('pages') or []:
        u = p.get('final_url', '')
        if u:
            seen.append(u)
    seen.extend(home.get('candidate_urls') or [])

    def depth(u):
        return len([s for s in urlparse(u).path.split('/') if s])

    detail = [u for u in seen
              if u != entry and not ENTRY_HINT.search(u)
              and same_site(u, rec['domain'])
              and not AGGREGATE_HINT.search(urlparse(u).path)
              and depth(u) >= 2]
    if detail:
        return max(detail, key=depth)
    return None  # 没有详情页就不猜，交人工


def acquisition_mode(rec, entry_page):
    """获取方式。只看入口页自己的措辞，不拿首页的价格表当证据。"""
    free = bool(entry_page.get('free_signals'))
    paid = bool(entry_page.get('paid_signals'))
    if free and not paid:
        return FREE, '入口页有免费措辞且无付费信号'
    if paid and not free:
        return PAID, '入口页出现付费信号且无免费层证据'
    if free and paid:
        return UNKNOWN, '入口页同时出现免费与付费信号，需人工确认免费档范围'
    return UNKNOWN, '入口页未出现明确免费/付费措辞'


def verify(rec, timeout=10):
    domain = rec['domain']
    entry, real_entry = pick_entry(rec)
    sample_url = pick_sample(rec, entry)
    if not entry:
        return {'Domain': domain, '操作入口': '', '获取方式': UNKNOWN, '处理结果': PENDING,
                '已确认事实': '', '缺失事实': '当前页面全部重定向到站外，未取得属于该域名的入口页',
                '证据URL': '', '证据日期': time.strftime('%Y-%m-%d'), '外链形式': '', 'DR': '',
                '成功项目数': rec.get('input', {}).get('successful_project_count', '')}
    row = {
        'Domain': domain, '操作入口': entry or '', '获取方式': UNKNOWN, '处理结果': PENDING,
        '已确认事实': '', '缺失事实': '', '证据URL': sample_url or '', '证据日期': time.strftime('%Y-%m-%d'),
        '外链形式': '', 'DR': '', '成功项目数': rec.get('input', {}).get('successful_project_count', ''),
    }

    entry_page = next((p for p in (rec.get('pages') or []) if p.get('final_url') == entry), None) or rec.get('home') or {}
    mode, mode_why = acquisition_mode(rec, entry_page)
    row['获取方式'] = mode

    if mode == PAID:
        row.update({'处理结果': PAID_OUT, '已确认事实': mode_why})
        return row

    # 没定位到真正的投稿入口就不能给正式机会。首页/列表页上的 "free" 措辞
    # 说明不了存在免费的投稿机制，拿它当证据会产出一批"点进去不知道在哪提交"
    # 的假机会。这里落待确认——是证据缺失，不是淘汰。
    if not real_entry:
        row.update({'获取方式': UNKNOWN, '处理结果': PENDING,
                    '缺失事实': '未定位到用户可提交的入口页（当前只拿到首页或列表页），无法确认存在对外投稿机制'})
        return row

    if not sample_url:
        row.update({'处理结果': PENDING, '缺失事实': '没有找到用户产出的详情页，无法验证最终外链属性'})
        return row

    p = fetch_page(sample_url, timeout)
    if p.get('status') != 200:
        row.update({'处理结果': PENDING,
                    '缺失事实': f"样例页抓取失败（{p.get('status')} {str(p.get('error') or '')[:40]}），当前无法验证 rel"})
        return row

    f, n = p.get('external_follow_count', 0), p.get('external_nofollow_count', 0)
    facts = [mode_why]

    if p.get('noindex'):
        row.update({'处理结果': DEAD, '已确认事实': '；'.join(facts + ['样例公开页 noindex，外链不会被索引'])})
        return row
    facts.append('样例公开页可索引')

    if f and not n:
        facts.append(f'样例页 {f} 条外部链接全部为 Follow')
        row['外链形式'] = 'Follow 外链'
        # 免费 + Follow + 可索引 才进正式机会；免费性只有文案证据时保持待确认。
        row['处理结果'] = OPPORTUNITY if mode == FREE else PENDING
        if mode != FREE:
            row['缺失事实'] = '链接属性已确认，但免费性未闭环'
    elif n and not f:
        facts.append(f'样例页 {n} 条外部链接全部为 Nofollow/UGC/Sponsored')
        row['处理结果'] = DEAD
    elif f and n:
        facts.append(f'样例页 Follow {f} 条 / Nofollow {n} 条')
        row['缺失事实'] = '同页混合 rel，需确认用户产出的那条链接属于哪种'
        row['处理结果'] = PENDING
    else:
        row['缺失事实'] = '样例页没有外部链接，未证明该机制会产出直接外链'
        row['处理结果'] = PENDING

    row['已确认事实'] = '；'.join(facts)
    return row


def next_action(r):
    """这条候选接下来该做什么。人看这一列就知道下一步，不用读证据文本。"""
    if r['处理结果'] == OPPORTUNITY:
        return '可以做——去操作入口发布'
    if r['处理结果'] == PAID_OUT:
        return '不做——需要付费'
    if r['处理结果'] == DEAD:
        return '不做——已有闭环负面证据'
    if r['外链形式'] == 'Follow 外链':
        return '★ 优先人工确认：链接已是 Follow，只差确认免费档'
    if '混合 rel' in r['缺失事实']:
        return '人工确认：找一条用户产出的链接看它的 rel'
    if '没有外部链接' in r['缺失事实']:
        return '人工确认：发布后是否真的会留下外链'
    return '人工确认：' + (r['缺失事实'] or '入口与免费档')


# 排序：能直接做的在最前，其次是只差一步的，已否决的沉底
ORDER = {OPPORTUNITY: 0, PENDING: 1, UNVERIFIED: 2, PAID_OUT: 3, DEAD: 4}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default='data/screening-results/latest.jsonl')
    ap.add_argument('--out-dir', default='data/opportunities')
    ap.add_argument('--workers', type=int, default=30)
    ap.add_argument('--timeout', type=int, default=10)
    ap.add_argument('--limit', type=int, default=0, help='只处理前 N 条，用于试跑')
    a = ap.parse_args()

    records = []
    with open(a.input, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get('decision', {}).get('reason_code') == 'mechanism_needs_link_verification':
                records.append(d)
    if a.limit:
        records = records[:a.limit]
    print(f'待推进候选：{len(records)}', flush=True)

    rows, done = [], 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for row in ex.map(lambda r: verify(r, a.timeout), records):
            rows.append(row)
            done += 1
            if done % 50 == 0:
                print(f'{done}/{len(records)}', flush=True)

    os.makedirs(a.out_dir, exist_ok=True)
    internal = os.path.join(a.out_dir, 'internal-status.csv')
    formal = os.path.join(a.out_dir, 'opportunities.csv')

    for r in rows:
        r['下一步'] = next_action(r)

    cols = ['Domain', '下一步', '操作入口', '获取方式', '处理结果', '已确认事实', '缺失事实', '证据URL', '证据日期', '外链形式', 'DR', '成功项目数']
    with open(internal, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        # 能做的最前，只差免费性的紧随其后，已否决的沉底
        w.writerows(sorted(rows, key=lambda r: (ORDER.get(r['处理结果'], 9),
                                                r['外链形式'] != 'Follow 外链', r['Domain'])))

    wins = [r for r in rows if r['处理结果'] == OPPORTUNITY]
    fcols = ['新增日期', 'Domain', '操作入口URL', '外链形式', '获取方式', 'DR', '最近验证', '备注']
    with open(formal, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fcols)
        w.writeheader()
        for r in wins:
            w.writerow({'新增日期': r['证据日期'], 'Domain': r['Domain'], '操作入口URL': r['操作入口'],
                        '外链形式': r['外链形式'], '获取方式': r['获取方式'], 'DR': r['DR'],
                        '最近验证': r['证据日期'], '备注': r['已确认事实']})

    counts = {}
    for r in rows:
        counts[r['处理结果']] = counts.get(r['处理结果'], 0) + 1
    print(json.dumps(counts, ensure_ascii=False))
    print(f'正式机会 {len(wins)} 条 -> {formal}')
    print(f'全部状态 {len(rows)} 条 -> {internal}')


if __name__ == '__main__':
    main()
