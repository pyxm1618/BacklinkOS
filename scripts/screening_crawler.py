#!/usr/bin/env python3
import argparse, concurrent.futures, csv, json, re, socket, ssl, time
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
COMMON_PATHS = ['/submit','/add','/submit-site','/submit-website','/submit-tool','/submit-ai-tool','/submit-product','/add-site','/add-website','/add-listing','/claim','/write-for-us','/guest-post','/contribute']

class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title=[]; self.in_title=False; self.text=[]; self.links=[]; self.metas=[]
    def handle_starttag(self, tag, attrs):
        d={k.lower():(v or '') for k,v in attrs}
        if tag.lower()=='title': self.in_title=True
        elif tag.lower()=='a': self.links.append((d.get('href',''), d.get('rel',''), d.get('title','')))
        elif tag.lower()=='meta': self.metas.append(d)
    def handle_endtag(self, tag):
        if tag.lower()=='title': self.in_title=False
    def handle_data(self, data):
        if self.in_title: self.title.append(data)
        self.text.append(data)

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
    candidate=[]
    for href, rel, atitle in p.links:
        if not href or href.startswith(('#','mailto:','tel:','javascript:')): continue
        u=urljoin(base_url, href)
        pu=urlparse(u)
        if pu.scheme not in ('http','https'): continue
        ltxt=(href+' '+atitle).lower()
        if any(re.search(x, ltxt, re.I) for x in MECHANISM_PATTERNS) or DISCOVERY_HINTS.search(ltxt):
            if (pu.hostname or '').lower()==host and u not in candidate:
                candidate.append(u)
        if pu.hostname and pu.hostname.lower()!=host:
            tokens=set((rel or '').lower().split())
            if tokens & {'nofollow','ugc','sponsored'}: ext_nofollow+=1
            else: ext_follow+=1
    full=(title+' '+norm)
    return {
        'title': title, 'noindex': noindex, 'mechanism_signals': _hits(full, MECHANISM_PATTERNS),
        'free_signals': _hits(full, FREE_PATTERNS), 'paid_signals': _hits(full, PAID_PATTERNS),
        'spam_signals': _hits(full, SPAM_PATTERNS),
        'external_follow_count': ext_follow, 'external_nofollow_count': ext_nofollow,
        'candidate_urls': candidate[:8], 'text_excerpt': norm[:500]
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
    if any(p.get('noindex') and _textual(p) for p in (probe.get('pages') or []) if p.get('status')==200):
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

def probe_domain(item, timeout=8):
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
        for u in urls[:20]:
            p=fetch_page(u,timeout)
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

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input',required=True); ap.add_argument('--output',default='screening-results.jsonl'); ap.add_argument('--workers',type=int,default=40); ap.add_argument('--timeout',type=int,default=8)
    a=ap.parse_args(); items=load_input(a.input)
    print(f'BacklinkOS crawler: {len(items)} domains, workers={a.workers}', flush=True)
    done=0; counts={}
    with open(a.output,'w',encoding='utf-8') as out, concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs={ex.submit(probe_domain,item,a.timeout):item for item in items}
        for fut in concurrent.futures.as_completed(futs):
            item=futs[fut]
            try: r=fut.result()
            except Exception as e: r={'domain':item.get('domain',''),'input':item,'home':{'status':0},'pages':[],'errors':[str(e)],'decision':{'bucket':'pending','reason_code':'crawler_exception','reason':'抓取器异常，关键事实未闭环'}}
            out.write(json.dumps(r,ensure_ascii=False)+'\n'); out.flush(); done+=1
            b=r['decision']['bucket']; counts[b]=counts.get(b,0)+1
            if done%100==0: print(f'{done}/{len(items)} {counts}', flush=True)
    with open(a.output+'.summary.json','w',encoding='utf-8') as f: json.dump({'total':len(items),'counts':counts,'generated_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())},f,ensure_ascii=False,indent=2)
    print(json.dumps(counts), flush=True)

if __name__=='__main__': main()
