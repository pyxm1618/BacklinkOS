#!/usr/bin/env python3
"""用真实浏览器重抓被 Cloudflare 挡住的候选。

screening_crawler 用 urllib，过不了 `cf-mitigated: challenge` 这类需要执行 JS
的挑战（toolify.ai/new、medium.com、guru99.com 都是）。这里只把抓取层换成
Chromium，分析和判定仍复用 screening_crawler 的 analyze_html / classify_probe，
保证两条路径语义一致。

只提取 rel / noindex / 链接字段，不截图、不落 HTML。
"""
import argparse, json, multiprocessing, os, re, shutil, sys, threading, time
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
                # 与 screening_crawler 保持一致：盲探来的页面不能代表站点
                if u in common:
                    pg['blind_probe'] = True
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


def _new_browser(p):
    b = p.chromium.launch(headless=True, args=['--disable-dev-shm-usage'])
    ctx = b.new_context(user_agent=UA, viewport={'width': 1280, 'height': 800})
    ctx.route('**/*', block_heavy)
    ctx.set_default_timeout(20000)
    return b, ctx


def _stub(domain, reason_code, reason, err=''):
    """抓取失败一律落 pending，不落 dead。

    抓不到是证据缺失，不是淘汰结论（screening-backlinks 硬规则 11）。
    """
    return {'domain': domain, 'input': {'domain': domain}, 'home': {'status': 0},
            'pages': [], 'errors': [err[:160]] if err else [], 'via': 'browser',
            'decision': {'bucket': 'pending', 'reason_code': reason_code, 'reason': reason}}


def worker(domains, max_paths, shard_path, cur_path):
    """一个独立进程跑一批域名，边跑边把结果 append 进自己的 shard。

    必须用进程而不是线程：Playwright 的 sync API 基于 greenlet，在非主线程里
    调用 sync_playwright() 会直接挂住（3 个域名跑 7 分钟不返回）。

    进程还有第二个作用：超时只能靠父进程 kill。page.goto 的 timeout 管不住
    route 拦截和 page.content()，实测有域名挂 6 分钟以上；SIGALRM 也没用——
    sync API 阻塞在 greenlet 的 C 调用里，信号处理函数根本轮不到执行。
    所以这里每跑一个域名先把域名写进 cur_path，父进程发现卡住就 kill 并据此
    记录是哪个域名超时。shard 逐条 flush，被 kill 也不会丢已完成的。
    """
    with sync_playwright() as p:
        b, ctx = _new_browser(p)
        with open(shard_path, 'a', encoding='utf-8') as fh:
            for d in domains:
                with open(cur_path, 'w', encoding='utf-8') as cf:
                    cf.write(d)  # 在飞的域名，供父进程超时归因
                try:
                    r = probe(ctx, d, max_paths)
                except Exception as e:
                    r = _stub(d, 'browser_exception', '浏览器抓取异常，关键事实未闭环',
                              type(e).__name__ + ': ' + str(e))
                fh.write(json.dumps(r, ensure_ascii=False) + '\n')
                fh.flush()
        try:
            b.close()
        except Exception:
            pass


def _shard_done(shard_path):
    """读回一个 shard 已完成的域名（顺序保留）。"""
    done = []
    if not os.path.exists(shard_path):
        return done
    with open(shard_path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                done.append(json.loads(line)['domain'])
            except (json.JSONDecodeError, KeyError):
                continue  # 被 kill 时可能留下半行
    return done


def supervise(slots, max_paths, budget, poll=5):
    """跑所有分片，卡住就杀掉重启。

    一个 slot = (域名列表, shard 路径, cur 路径)。父进程只看 shard 行数：
    超过 budget 秒没有新行，就认为在飞的那个域名挂死了，kill 掉进程，把它记成
    browser_timeout，然后用剩下的域名重启这个 slot。
    """
    procs = {}

    def spawn(i):
        domains, shard, cur = slots[i]
        remaining = [d for d in domains if d not in set(_shard_done(shard))]
        if not remaining:
            return None
        p = multiprocessing.Process(target=worker, args=(remaining, max_paths, shard, cur))
        p.daemon = True
        p.start()
        return {'p': p, 'n': len(_shard_done(shard)), 'ts': time.time()}

    for i in range(len(slots)):
        st = spawn(i)
        if st:
            procs[i] = st

    while procs:
        time.sleep(poll)
        for i in list(procs):
            st = procs[i]
            domains, shard, cur = slots[i]
            n = len(_shard_done(shard))
            if n > st['n']:
                st['n'], st['ts'] = n, time.time()
            if not st['p'].is_alive():
                # 正常跑完，或者浏览器自己崩了——还有剩就重启
                nxt = spawn(i)
                if nxt:
                    procs[i] = nxt
                else:
                    del procs[i]
                continue
            if time.time() - st['ts'] > budget:
                stuck = ''
                try:
                    with open(cur, encoding='utf-8') as cf:
                        stuck = cf.read().strip()
                except OSError:
                    pass
                st['p'].kill()
                st['p'].join(10)
                if stuck and stuck not in set(_shard_done(shard)):
                    with open(shard, 'a', encoding='utf-8') as fh:
                        fh.write(json.dumps(
                            _stub(stuck, 'browser_timeout',
                                  f'浏览器抓取超过 {budget}s 预算，关键事实未闭环'),
                            ensure_ascii=False) + '\n')
                    print(f'  超时跳过 {stuck}', flush=True)
                nxt = spawn(i)
                if nxt:
                    procs[i] = nxt
                else:
                    del procs[i]


def load_shards(shard_dir):
    """读回已完成的 shard，用于进度显示和断点续跑。"""
    done = {}
    if not os.path.isdir(shard_dir):
        return done
    for name in os.listdir(shard_dir):
        if not name.endswith('.jsonl'):
            continue
        with open(os.path.join(shard_dir, name), encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue  # 中断时可能留下半行
                done[r['domain']] = r
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True, help='crawler 输出的 jsonl')
    ap.add_argument('--output', required=True, help='合并后的 jsonl')
    ap.add_argument('--workers', type=int, default=5, help='并行浏览器进程数，别开太高')
    ap.add_argument('--max-paths', type=int, default=5)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--shard-dir', default='', help='断点目录，默认 <output>.shards')
    ap.add_argument('--fresh', action='store_true', help='忽略已有断点，从头跑')
    ap.add_argument('--budget', type=int, default=75, help='单域名墙钟预算（秒）')
    a = ap.parse_args()

    records = [json.loads(l) for l in open(a.input, encoding='utf-8') if l.strip()]
    stuck = [r['domain'] for r in records
             if r.get('decision', {}).get('reason_code') in ('blocked_or_uncertain', 'browser_exception', 'browser_timeout')]
    if a.limit:
        stuck = stuck[:a.limit]

    shard_dir = a.shard_dir or (a.output + '.shards')
    if a.fresh and os.path.isdir(shard_dir):
        shutil.rmtree(shard_dir)
    os.makedirs(shard_dir, exist_ok=True)

    fixed = load_shards(shard_dir)
    todo = [d for d in stuck if d not in fixed]
    print(f'需要浏览器兜底：{len(stuck)}（已完成 {len(stuck) - len(todo)}，本次跑 {len(todo)}）', flush=True)

    if todo:
        chunks = [todo[i::a.workers] for i in range(a.workers)]
        slots = [(c, os.path.join(shard_dir, f'w{i}.jsonl'), os.path.join(shard_dir, f'w{i}.cur'))
                 for i, c in enumerate(chunks) if c]

        stop = threading.Event()

        def tick():
            # 只数 shard 行数报进度，不碰浏览器
            t0 = time.time()
            base = len(stuck) - len(todo)
            while not stop.wait(30):
                n = len(load_shards(shard_dir))
                el = time.time() - t0
                rate = (n - base) / el if el else 0
                eta = (len(todo) - (n - base)) / rate / 60 if rate > 0 else 0
                print(f'  {n}/{len(stuck)}  已跑 {el/60:.1f} 分钟，预计还要 {eta:.0f} 分钟', flush=True)

        mon = threading.Thread(target=tick, daemon=True)
        mon.start()
        try:
            supervise(slots, a.max_paths, a.budget)
        finally:
            stop.set()
        fixed = load_shards(shard_dir)

    counts = {}
    with open(a.output, 'w', encoding='utf-8') as out:
        for r in records:
            r = fixed.get(r['domain'], r)
            out.write(json.dumps(r, ensure_ascii=False) + '\n')
            b = r['decision']['bucket']
            counts[b] = counts.get(b, 0) + 1
    recovered = sum(1 for d, r in fixed.items()
                    if r['decision']['reason_code'] not in ('blocked_or_uncertain', 'browser_exception', 'browser_timeout'))
    print(json.dumps(counts, ensure_ascii=False))
    print(f'浏览器兜底救回 {recovered}/{len(stuck)} 条 -> {a.output}')


if __name__ == '__main__':
    main()
