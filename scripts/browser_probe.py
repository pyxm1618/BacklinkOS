#!/usr/bin/env python3
"""用真实浏览器重抓被 Cloudflare 挡住的候选。

screening_crawler 用 urllib，过不了 `cf-mitigated: challenge` 这类需要执行 JS
的挑战（toolify.ai/new、medium.com、guru99.com 都是）。这里只把抓取层换成
Chromium，分析和判定仍复用 screening_crawler 的 analyze_html / classify_probe，
保证两条路径语义一致。

只提取 rel / noindex / 链接字段，不截图、不落 HTML。
"""
import argparse, json, os, re, sys, threading
import concurrent.futures
from urllib.parse import urljoin, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from screening_crawler import analyze_html, classify_probe, COMMON_PATHS

from playwright.sync_api import sync_playwright

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
SETTLE = 900           # 常规页面等 JS 落地
CHALLENGE_WAIT = 4000  # 只有确实撞上挑战页才等这么久
BLOCK = {'image', 'media', 'font', 'stylesheet'}
CHALLENGE_RE = re.compile(r'(just a moment|checking your browser|attention required)', re.I)


def block_heavy(route):
    """图片/字体/CSS 对我们要的 rel 和 noindex 没用，全部拦掉。

    这是这个脚本能跑得动的关键——不拦的话单页要等十几秒。
    """
    try:
        if route.request.resource_type in BLOCK:
            route.abort()
        else:
            route.continue_()
    except Exception:
        pass


def grab(page, url, timeout=20000):
    try:
        r = page.goto(url, wait_until='domcontentloaded', timeout=timeout)
        page.wait_for_timeout(SETTLE)
        status = r.status if r else 0
        # 撞上 Cloudflare 挑战才多等一轮，不要每页都等
        if status in (403, 503) or CHALLENGE_RE.search(page.title() or ''):
            page.wait_for_timeout(CHALLENGE_WAIT)
            if not CHALLENGE_RE.search(page.title() or ''):
                status = 200
        final = page.url
        html = page.content()
        if status != 200:
            return {'url': url, 'final_url': final, 'status': status, 'error': f'HTTP {status}'}
        a = analyze_html(html, final)
        a.update({'url': url, 'final_url': final, 'status': status, 'content_type': 'text/html'})
        return a
    except Exception as e:
        return {'url': url, 'final_url': url, 'status': 0, 'error': type(e).__name__ + ': ' + str(e)[:160]}


def probe(ctx, domain, max_paths):
    page = ctx.new_page()
    out = {'domain': domain, 'input': {'domain': domain}, 'home': None, 'pages': [], 'errors': [],
           'via': 'browser'}
    try:
        hosts = [domain] if domain.startswith('www.') else [domain, 'www.' + domain]
        home = None
        for h in hosts:
            home = grab(page, f'https://{h}/')
            if home.get('status') == 200:
                break
        out['home'] = home
        if home.get('error'):
            out['errors'].append(home['error'])

        if home.get('status') == 200 and not home.get('spam_signals') and not home.get('noindex'):
            base = home.get('final_url') or f'https://{domain}/'
            host = (urlparse(base).hostname or domain).lower()
            urls = []
            for u in (home.get('candidate_urls') or [])[:3]:
                if (urlparse(u).hostname or '').lower() == host:
                    urls.append(u)
            common = set()
            for p in COMMON_PATHS[:max_paths]:
                u = urljoin(base, p)
                common.add(u)
                if u not in urls:
                    urls.append(u)
            for u in urls[:max_paths + 3]:
                pg = grab(page, u, timeout=15000)
                if (pg.get('status') == 200 and u in common and not pg.get('mechanism_signals')
                        and not pg.get('noindex')
                        and pg.get('final_url', '').rstrip('/') == u.rstrip('/')):
                    pg['mechanism_signals'] = ['path:' + urlparse(u).path]
                if pg.get('status') == 200 and (pg.get('mechanism_signals') or pg.get('spam_signals') or pg.get('noindex')):
                    out['pages'].append(pg)
                if len(out['pages']) >= 3:
                    break
        out['decision'] = classify_probe(out)
    finally:
        page.close()
    return out


def worker(domains, max_paths, progress):
    results = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=['--disable-dev-shm-usage'])
        ctx = b.new_context(user_agent=UA, viewport={'width': 1280, 'height': 800})
        ctx.route('**/*', block_heavy)
        ctx.set_default_timeout(20000)
        for d in domains:
            try:
                results.append(probe(ctx, d, max_paths))
            except Exception as e:
                results.append({'domain': d, 'input': {'domain': d}, 'home': {'status': 0},
                                'pages': [], 'errors': [str(e)[:160]], 'via': 'browser',
                                'decision': {'bucket': 'pending', 'reason_code': 'browser_exception',
                                             'reason': '浏览器抓取异常，关键事实未闭环'}})
            progress()
        b.close()
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True, help='crawler 输出的 jsonl')
    ap.add_argument('--output', required=True, help='合并后的 jsonl')
    ap.add_argument('--workers', type=int, default=5, help='并行浏览器数，别开太高')
    ap.add_argument('--max-paths', type=int, default=5)
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    records = [json.loads(l) for l in open(a.input, encoding='utf-8') if l.strip()]
    stuck = [r['domain'] for r in records
             if r.get('decision', {}).get('reason_code') in ('blocked_or_uncertain', 'browser_exception')]
    if a.limit:
        stuck = stuck[:a.limit]
    print(f'需要浏览器兜底：{len(stuck)}', flush=True)
    if not stuck:
        return

    state = {'n': 0}
    lock = threading.Lock()

    def progress():
        with lock:
            state['n'] += 1
            if state['n'] % 25 == 0:
                print(f"{state['n']}/{len(stuck)}", flush=True)

    chunks = [stuck[i::a.workers] for i in range(a.workers)]
    fixed = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(worker, c, a.max_paths, progress) for c in chunks if c]
        for f in concurrent.futures.as_completed(futs):
            for r in f.result():
                fixed[r['domain']] = r

    counts = {}
    with open(a.output, 'w', encoding='utf-8') as out:
        for r in records:
            r = fixed.get(r['domain'], r)
            out.write(json.dumps(r, ensure_ascii=False) + '\n')
            b = r['decision']['bucket']
            counts[b] = counts.get(b, 0) + 1
    recovered = sum(1 for d, r in fixed.items()
                    if r['decision']['reason_code'] not in ('blocked_or_uncertain', 'browser_exception'))
    print(json.dumps(counts, ensure_ascii=False))
    print(f'浏览器兜底救回 {recovered}/{len(stuck)} 条 -> {a.output}')


if __name__ == '__main__':
    main()
