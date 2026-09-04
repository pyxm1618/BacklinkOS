#!/usr/bin/env python3
import argparse, concurrent.futures, csv, json, os, re, socket, ssl, time
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

UA = 'Mozilla/5.0 (compatible; BacklinkOS-Screener/1.0; +https://github.com/pyxm1618/BacklinkOS)'
MAX_BYTES = 1_500_000

MECHANISM_PATTERNS = [
    r'\bsubmit (?:your )?(?:website|site|tool|product|startup|app|business|link|url|article|post)\b',
    r'\badd (?:your )?(?:website|site|tool|product|startup|app|business|link|url|listing)\b',
    r'\blist (?:your )?(?:website|site|tool|product|startup|app|business)\b',
    r'\bclaim (?:this |your )?(?:profile|listing|business|company|page)\b',
    r'\bwrite for us\b', r'\bguest post\b', r'\bguest article\b',
    r'\bcontribute (?:an )?(?:article|post|story)\b', r'\bbecome an author\b',
    r'\bpublish (?:a |your )?(?:post|article|story|page)\b',
    r'\bcreate (?:a |your )?(?:profile|listing|page|publication|blog)\b',
    r'\bpost your (?:link|website|site|business|product|startup|app)\b',
]
FREE_PATTERNS = [r'\bfree\b', r'\$\s*0(?:\D|$)', r'\bno cost\b', r'\bfree listing\b', r'\bsubmit for free\b']
PAID_PATTERNS = [r'\bpaid (?:listing|submission|placement|post)\b', r'\bsponsored (?:post|article|listing)\b',
                 r'\bsubmission fee\b', r'\blisting fee\b', r'\bpricing\b', r'\bcheckout\b', r'\bbuy now\b',
                 r'\$\s*\d+', r'€\s*\d+', r'£\s*\d+']
SPAM_PATTERNS = [r'\bbuy backlinks?\b', r'\bpremium pbn\b', r'\bpbn network\b', r'\baged domains? and backlinks?\b',
                 r'\bbacklink packages?\b', r'\bbulk guest posts?\b', r'\bsitewide links?\b',
                 r'\bhigh quality dofollow backlinks?\b', r'\bseo backlink packages?\b', r'\bblack hat seo\b']
DISCOVERY_HINTS = re.compile(r'(directory|catalog|listing|submit|startup|product|tool|launch|profile|community|forum|blog|news|media|press|wiki|link|bookmark|social|author|guest)', re.I)
# 比 DISCOVERY_HINTS 严格得多：这些词几乎只出现在真正的投稿/收录入口上。
# DISCOVERY_HINTS 太宽（blog/product/tool 都算），命中的链接会把 candidate_urls
# 占满，真正的 /submit 反而挤不进前几名。分成强弱两档就是为了排序。
ENTRY_HINTS = re.compile(
    r'\b(submit|add[-_\s]?(?:your|a|new|site|website|tool|listing|url|link|product)'
    r'|write[-_\s]for[-_\s]us|guest[-_\s]?post|contribute|become[-_\s]an?[-_\s]author'
    r'|get[-_\s]listed|list[-_\s]your|claim|suggest)', re.I)
# 登录/注册墙。这些页面 noindex 是理所当然的，不能当成"入口页不可索引"。
AUTH_PATH_RE = re.compile(r'/(log[-_]?in|sign[-_]?in|sign[-_]?up|register|auth|account|my-account)(/|$)', re.I)
# 按命中概率排序：probe 有请求预算，靠前的先试。
COMMON_PATHS = ['/submit','/add','/submit-site','/submit-website','/submit-tool','/submit-ai-tool',
                '/submit-product','/add-site','/add-website','/add-listing','/claim','/write-for-us',
                '/guest-post','/contribute',
                # 以下是重筛 unverified 时补的：上一轮 2426 条「没找到入口」里，
                # 很多站的入口就在这些路径上，只是不在原来的 14 条里。
                '/submit-startup','/submit-your-tool','/submit-a-tool','/submit-link','/submit-url',
                '/submit-article','/submit-blog','/submit-news','/add-url','/add-your-business',
                '/list-your-business','/get-listed','/suggest','/new','/publish','/write-for-us/',
                '/advertise','/partners','/tools/submit','/directory/submit','/submit.html',
                '/become-a-contributor','/guest-posting','/free-listing']

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title=[]; self.in_title=False; self.text=[]; self.links=[]; self.metas=[]
        self._a=None; self._atext=[]
    def handle_starttag(self, tag, attrs):
        d={k.lower():(v or '') for k,v in attrs}
        t=tag.lower()
        if t=='title': self.in_title=True
        elif t=='a':
            self._flush_a()  # 上一个 <a> 没闭合就先收掉，别把锚文本串到下一条
            self._a=(d.get('href',''), d.get('rel',''), d.get('title',''))
            self._atext=[]
        elif t=='meta': self.metas.append(d)
    def handle_endtag(self, tag):
        t=tag.lower()
        if t=='title': self.in_title=False
        elif t=='a': self._flush_a()
    def handle_data(self, data):
        if self.in_title: self.title.append(data)
        if self._a is not None: self._atext.append(data)
        self.text.append(data)
    def _flush_a(self):
        if self._a is None: return
        href, rel, atitle = self._a
        self.links.append((href, rel, atitle, ' '.join(self._atext).strip()[:200]))
        self._a=None; self._atext=[]
    def close(self):
        super().close(); self._flush_a()

def _hits(text, patterns):
    out=[]
    low=text.lower()
    for p in patterns:
        if re.search(p, low, re.I): out.append(p)
    return out

def analyze_html(raw_html, base_url):
    p=Parser()
    try: p.feed(raw_html)
    except Exception: pass
    title=' '.join(p.title).strip()[:300]
    body=' '.join(p.text)
    norm=' '.join(body.split())[:500000]
    robots=' '.join(m.get('content','') for m in p.metas if m.get('name','').lower() in ('robots','googlebot')).lower()
    noindex='noindex' in robots
    host=(urlparse(base_url).hostname or '').lower()
    ext_follow=ext_nofollow=0
    strong=[]; weak=[]
    for href, rel, atitle, atext in p.links:
        if not href or href.startswith(('#','mailto:','tel:','javascript:')): continue
        u=urljoin(base_url, href)
        pu=urlparse(u)
        if pu.scheme not in ('http','https'): continue
        # 锚文本必须参与匹配。"Submit a tool" 这种入口常常只在可见文字里，
        # href 是 /s/new 之类看不出意图的路径——只看 href+title 会整条漏掉。
        ltxt=(href+' '+atitle+' '+atext).lower()
        if (pu.hostname or '').lower()==host:
            if any(re.search(x, ltxt, re.I) for x in MECHANISM_PATTERNS) or ENTRY_HINTS.search(ltxt):
                if u not in strong: strong.append(u)
            elif DISCOVERY_HINTS.search(ltxt):
                if u not in weak: weak.append(u)
        if pu.hostname and pu.hostname.lower()!=host:
            tokens=set((rel or '').lower().split())
            if tokens & {'nofollow','ugc','sponsored'}: ext_nofollow+=1
            else: ext_follow+=1
    candidate=strong+[w for w in weak if w not in strong]
    full=(title+' '+norm)
    return {
        'title': title, 'noindex': noindex, 'mechanism_signals': _hits(full, MECHANISM_PATTERNS),
        'free_signals': _hits(full, FREE_PATTERNS), 'paid_signals': _hits(full, PAID_PATTERNS),
        'spam_signals': _hits(full, SPAM_PATTERNS),
        'external_follow_count': ext_follow, 'external_nofollow_count': ext_nofollow,
        'candidate_urls': candidate[:12], 'text_excerpt': norm[:500]
    }

class Redirects(HTTPRedirectHandler): pass
OPENER=build_opener(Redirects())

def fetch_page(url, timeout=8, _retry=True):
    req=Request(url, headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml;q=0.9,*/*;q=0.1'})
    try:
        with OPENER.open(req, timeout=timeout) as resp:
            status=getattr(resp,'status',200); final=resp.geturl(); ctype=resp.headers.get('content-type','')
            data=resp.read(MAX_BYTES)
            if 'html' not in ctype.lower() and b'<html' not in data[:1000].lower():
                return {'url':url,'final_url':final,'status':status,'content_type':ctype,'title':'','noindex':False,'mechanism_signals':[],'free_signals':[],'paid_signals':[],'spam_signals':[],'external_follow_count':0,'external_nofollow_count':0,'candidate_urls':[]}
            enc=resp.headers.get_content_charset() or 'utf-8'
            try: txt=data.decode(enc,errors='replace')
            except Exception: txt=data.decode('utf-8',errors='replace')
            a=analyze_html(txt,final); a.update({'url':url,'final_url':final,'status':status,'content_type':ctype}); return a
    except HTTPError as e:
        return {'url':url,'final_url':getattr(e,'url',url),'status':e.code,'error':f'HTTP {e.code}'}
    except (URLError, socket.timeout, TimeoutError, ssl.SSLError) as e:
        # "Can't assign requested address" 是本机临时端口被我们自己打满，
        # 不是站点的问题。退避后重试一次，否则会把上千个正常站点误记成不可达。
        if _retry and "assign requested address" in str(e):
            time.sleep(1.5)
            return fetch_page(url, timeout, _retry=False)
        return {'url':url,'final_url':url,'status':0,'error':type(e).__name__+': '+str(e)[:180]}
    except Exception as e:
        return {'url':url,'final_url':url,'status':0,'error':type(e).__name__+': '+str(e)[:180]}

def classify_probe(probe):
    # bucket 语义（对应 screening-backlinks 的处理结果）：
    #   dead       已确认淘汰——有闭环负面证据，不会再被捞回
    #   paid       付费排除
    #   pending    待确认——发现机制但差最后一步证据
    #   unverified 未验证——没找到入口。按 SKILL 硬规则 11「缺失事实不是负面事实」，
    #              这不是淘汰，下一轮必须重新参与筛选。
    h=probe.get('home') or {}
    status=int(h.get('status') or 0)
    allpages=[h]+list(probe.get('pages') or [])
    if status in (404,410): return {'bucket':'dead','reason_code':'inactive_404','reason':'主页返回 404/410，当前入口失效'}
    err=' '.join(probe.get('errors') or [])+' '+str(h.get('error') or '')
    if status==0 and re.search(r'(Name or service not known|Temporary failure in name resolution|nodename nor servname|No address associated|NXDOMAIN)', err, re.I):
        return {'bucket':'dead','reason_code':'inactive_dns','reason':'DNS 当前无法解析，候选站点不可达'}
    if status==0 or status in (401,403,407,408,409,425,429) or status>=500:
        return {'bucket':'pending','reason_code':'blocked_or_uncertain','reason':'当前抓取被阻止/超时/服务器异常，无法闭环关键事实'}
    # noindex 只在能代表站点的页面上成立。盲探 COMMON_PATHS 命中的多是 SPA 软 404 /
    # 登录墙，它们的 noindex 不能证明站点不可索引（hashnode.com 曾因此被误杀）。
    if h.get('status')==200 and h.get('noindex'):
        return {'bucket':'dead','reason_code':'noindex','reason':'当前站点首页明确 noindex'}
    def _textual(p):  # 'path:' 是探测到入口路径时注入的伪信号，不算文案证据
        return [s for s in (p.get('mechanism_signals') or []) if not str(s).startswith('path:')]
    def _bare(u):
        # 注意别用 lstrip('www.')——那是按字符集剥，'wow.com' 会变成 'o.com'
        hn=(urlparse(u or '').hostname or '').lower()
        return hn[4:] if hn.startswith('www.') else hn
    site_host=_bare(h.get('final_url'))
    def _same_host(p):
        # 跨站页面不能代表本站。实测有域名是被 tally.so 的表单页、甚至另一个
        # 域名的页面 noindex 判死的（aitools.fyi、aicloudbase.com）。
        ph=_bare(p.get('final_url'))
        return bool(ph) and bool(site_host) and ph==site_host
    def _usable_noindex(p):
        """这一页的 noindex 能不能拿来淘汰整个域名。"""
        req=p.get('url') or ''; fu=p.get('final_url') or ''
        # 登录/注册墙的 noindex 是理所当然的，它不是入口页本身。而且被跳到
        # 登录页恰恰说明投稿机制存在（callbackUrl 里就写着 /submit），
        # 这种情况应该留在 pending 让人去确认，绝不能判死。
        if AUTH_PATH_RE.search(urlparse(fu).path or ''): return False
        # 跟着跳转跑到别的页面去了，那个 noindex 属于跳转目标，不属于这个入口
        if req and fu and (urlparse(req).path or '/').rstrip('/')!=(urlparse(fu).path or '/').rstrip('/'):
            return False
        # 目录站的每个页面都在导航/页脚里写着 "Submit your tool"，所以页面文案
        # 命中机制正则根本不能说明这一页就是入口。只有路径本身像投稿入口才算。
        # 否则 /category/news/、/products、/forum 这类正常 noindex 的归档页
        # 会把整个域名判死（kulfiy.com、topreviewed.ai、promoteproject.com）。
        if not ENTRY_HINTS.search(urlparse(fu).path or ''): return False
        return True
    # 盲探 COMMON_PATHS 命中的页面一律不作淘汰依据，哪怕它有文案信号。
    # SPA 对任意不存在的路径返回软 200 + noindex，壳里的文案还可能撞上机制正则
    # （polymarket.com 的 /submit /add /submit-site 全是这样，差点被判死）。
    # 只有站点自己在页面上链出来的入口才算能代表站点。
    if any(p.get('noindex') and _textual(p) and not p.get('blind_probe')
           and _same_host(p) and _usable_noindex(p)
           for p in (probe.get('pages') or []) if p.get('status')==200):
        return {'bucket':'dead','reason_code':'noindex','reason':'当前可执行入口页明确 noindex'}
    spam=[x for p in allpages if p.get('status')==200 for x in (p.get('spam_signals') or [])]
    if spam:
        return {'bucket':'dead','reason_code':'spam_or_link_network','reason':'当前页面出现明确卖链/PBN/批量SEO链接网络信号'}
    mech=[p for p in allpages if p.get('status')==200 and p.get('mechanism_signals')]
    if mech:
        paid=[x for p in mech for x in (p.get('paid_signals') or [])]
        free=[x for p in mech for x in (p.get('free_signals') or [])]
        if paid and not free:
            return {'bucket':'paid','reason_code':'paid_mechanism','reason':'当前提交/发布入口出现明确付费信号，未发现免费层证据'}
        return {'bucket':'pending','reason_code':'mechanism_needs_link_verification','reason':'发现当前可执行提交/发布/claim机制，但免费性或最终 Follow/可索引属性尚需同路径闭环'}
    return {'bucket':'unverified','reason_code':'no_generic_mechanism','reason':'当前站点可访问；标准化探测未发现通用提交/发布/claim入口。这是证据缺失，不是淘汰结论'}

def probe_domain(item, timeout=8, max_probes=20):
    domain=item['domain'].strip().lower()
    out={'domain':domain,'input':item,'home':None,'pages':[],'errors':[]}
    # 裸域和 www 都试：不少站只在其中一个上放行（toolify.ai 裸域 403 / www 200，
    # medium.com 正好相反）。取最好的一次结果。
    hosts=[domain] if domain.startswith('www.') else [domain,'www.'+domain]
    attempts=[]
    for host in hosts:
        for scheme in ('https','http'):
            h=fetch_page(f'{scheme}://{host}/',timeout)
            attempts.append(h)
            if h.get('status')==200: break
        if attempts[-1].get('status')==200: break
    home=next((a for a in attempts if a.get('status')==200), None) \
         or next((a for a in attempts if a.get('status') not in (0,495,496)), None) \
         or attempts[0]
    out['home']=home
    if home.get('error'): out['errors'].append(home['error'])
    # 不再用首页文案做守卫。旧的 should_probe_common() 让 99% 的"无机制"判定
    # 只看过首页，softwaretestinghelp.com/add 这类真实入口因此被漏掉。
    if home.get('status')==200 and not home.get('spam_signals') and not home.get('noindex'):
        urls=[]
        host=(urlparse(home.get('final_url') or f'https://{domain}/').hostname or domain).lower()
        # 首页链接只取前 6 条，给 COMMON_PATHS 留出名额：旧的 urls[:10] 会被
        # 首页链接占满，导致 /submit 之类的常见入口根本没被试过。
        for u in home.get('candidate_urls',[])[:6]:
            if (urlparse(u).hostname or '').lower()==host and u not in urls: urls.append(u)
        base=home.get('final_url') or f'https://{domain}/'
        common=set()
        for path in COMMON_PATHS:
            u=urljoin(base,path)
            common.add(u)
            if u not in urls: urls.append(u)
        for u in urls[:max_probes]:
            p=fetch_page(u,timeout)
            # 标记这一页是盲探来的：它不是站点自己链出来的入口，不能代表站点，
            # classify_probe 据此拒绝拿它的 noindex 淘汰整个域名。
            if u in common: p['blind_probe']=True
            # COMMON_PATHS 上真实存在的 200 页面本身就是入口证据，不要求页面文案
            # 再次命中机制正则（heykuki.com/submit 只有免费措辞，旧逻辑会漏掉）。
            # 但 noindex 的页面不注入：SPA 对不存在的路径常返回软 200 + noindex
            # （dev.to/submit），注入后会被误判成"入口页 noindex"而淘汰整个域名。
            if (p.get('status')==200 and u in common and not p.get('mechanism_signals')
                    and not p.get('noindex')
                    and p.get('final_url','').rstrip('/')==u.rstrip('/')
                    and not re.search(r'\b(404|not found|page not found)\b', p.get('title',''), re.I)):
                p['mechanism_signals']=['path:'+urlparse(u).path]
            if p.get('status')==200 and (p.get('mechanism_signals') or p.get('spam_signals') or p.get('noindex')):
                out['pages'].append(p)
            elif p.get('status') in (401,403,429) and len(out['pages'])<3:
                out['pages'].append(p)
            if p.get('error') and p.get('status') not in (404,410): out['errors'].append(p['error'])
            if len(out['pages'])>=4: break
    out['decision']=classify_probe(out)
    return out

def load_input(path):
    items=[]
    if path.endswith('.json') or path.endswith('.jsonl'):
        with open(path,encoding='utf-8') as f:
            for line in f:
                line=line.strip()
                if not line: continue
                obj=json.loads(line); items.append(obj if isinstance(obj,dict) else {'domain':str(obj)})
    else:
        with open(path,newline='',encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                if row.get('domain'): items.append(row)
    return items

def normalize_domain(value):
    raw=str(value or '').strip().lower()
    if not raw: return ''
    if '://' not in raw: raw='//'+raw
    host=(urlparse(raw).hostname or '').rstrip('.')
    return host[4:] if host.startswith('www.') else host

def unique_input(items):
    """按规范化域名去重，同时保留本轮最新的输入事实。"""
    merged={}
    order=[]
    for item in items:
        domain=normalize_domain(item.get('domain'))
        if not domain: continue
        normalized=dict(item); normalized['domain']=domain
        if domain not in merged: order.append(domain)
        merged[domain]=normalized
    return [merged[domain] for domain in order]

def load_existing_results(path):
    results={}
    if not path or not os.path.exists(path): return results
    with open(path,encoding='utf-8') as f:
        for line_number,line in enumerate(f,start=1):
            line=line.strip()
            if not line: continue
            try: row=json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f'已有结果第 {line_number} 行不是有效 JSON：{path}') from exc
            domain=normalize_domain(row.get('domain'))
            if domain and isinstance(row.get('decision'),dict): results[domain]=row
    return results

def existing_status_placeholder(item):
    return {
        'domain':item['domain'],
        'input':item,
        'home':{'status':0},
        'pages':[],
        'errors':[],
        'decision':{
            'bucket':'status_reused',
            'reason_code':'existing_status_reused',
            'reason':'总账已有深入筛选状态，本轮不重复抓取',
        },
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input',required=True)
    ap.add_argument('--output',default='screening-results.jsonl')
    ap.add_argument('--workers',type=int,default=40)
    ap.add_argument('--timeout',type=int,default=8)
    ap.add_argument('--max-probes',type=int,default=20,help='每个域名最多探测多少个子页面')
    ap.add_argument('--existing-results',default='',help='已有 crawler JSONL；默认复用，不重复抓取')
    ap.add_argument('--fresh',action='store_true',help='明确要求全部重新抓取')
    a=ap.parse_args(); items=unique_input(load_input(a.input))

    existing={}
    if not a.fresh:
        existing.update(load_existing_results(a.existing_results))
        if os.path.exists(a.output) and os.path.abspath(a.output)!=os.path.abspath(a.existing_results or ''):
            existing.update(load_existing_results(a.output))

    results={}
    todo=[]
    reused_existing_results=0
    skipped_existing_status=0
    allowed_queue_states={'approved','deferred','confirmed_reject','triaged_only','unreviewed'}
    for item in items:
        domain=item['domain']
        queue_state=(item.get('queue_state') or '').strip()
        if queue_state and queue_state not in allowed_queue_states:
            raise ValueError(f'未知 queue_state：{queue_state}（{domain}）')
        if domain in existing:
            reused=dict(existing[domain])
            reused['domain']=domain
            reused['input']=item
            results[domain]=reused
            reused_existing_results+=1
        elif queue_state and queue_state!='unreviewed':
            results[domain]=existing_status_placeholder(item)
            skipped_existing_status+=1
        else:
            todo.append(item)

    print(f'BacklinkOS crawler: 总数 {len(items)}，复用 {len(results)}，本次抓取 {len(todo)}，workers={a.workers}', flush=True)
    done=0
    with open(a.output,'w',encoding='utf-8') as out:
        for item in items:
            if item['domain'] in results:
                out.write(json.dumps(results[item['domain']],ensure_ascii=False)+'\n')
        out.flush()
        if todo:
            with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as ex:
                futs={ex.submit(probe_domain,item,a.timeout,a.max_probes):item for item in todo}
                for fut in concurrent.futures.as_completed(futs):
                    item=futs[fut]
                    try: r=fut.result()
                    except Exception as e: r={'domain':item.get('domain',''),'input':item,'home':{'status':0},'pages':[],'errors':[str(e)],'decision':{'bucket':'pending','reason_code':'crawler_exception','reason':'抓取器异常，关键事实未闭环'}}
                    results[item['domain']]=r
                    out.write(json.dumps(r,ensure_ascii=False)+'\n'); out.flush(); done+=1
                    if done%100==0: print(f'{done}/{len(todo)} 本轮新增', flush=True)

    if len(results)!=len(items):
        raise RuntimeError(f'结果数量无法对齐：候选 {len(items)}，结果 {len(results)}')
    counts={}
    for r in results.values():
        b=r['decision']['bucket']; counts[b]=counts.get(b,0)+1
    summary={'total':len(items),'reused':len(items)-len(todo),'processed_this_run':len(todo),
             'reused_existing_results':reused_existing_results,
             'skipped_existing_status':skipped_existing_status,
             'counts':counts,'generated_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    with open(a.output+'.summary.json','w',encoding='utf-8') as f: json.dump(summary,f,ensure_ascii=False,indent=2)
    print(json.dumps(counts), flush=True)

if __name__=='__main__': main()
