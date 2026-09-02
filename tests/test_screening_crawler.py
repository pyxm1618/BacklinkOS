import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import unittest
from screening_crawler import analyze_html, classify_probe

class AnalyzeHtmlTests(unittest.TestCase):
    def test_detects_submit_and_free_without_noindex(self):
        html='''<html><head><title>Directory</title></head><body><a href="/submit">Submit your website for free</a></body></html>'''
        r=analyze_html(html,'https://example.com/')
        self.assertTrue(r['mechanism_signals'])
        self.assertTrue(r['free_signals'])
        self.assertFalse(r['noindex'])
        self.assertIn('https://example.com/submit', r['candidate_urls'])

    def test_detects_nofollow_external_links(self):
        html='''<html><body><a href="https://outside.example/x" rel="nofollow ugc">Site</a><a href="https://follow.example/">Follow</a></body></html>'''
        r=analyze_html(html,'https://example.com/')
        self.assertEqual(r['external_follow_count'],1)
        self.assertEqual(r['external_nofollow_count'],1)

    def test_detects_spam_network_language(self):
        html='<html><body>Buy backlinks from our premium PBN network. High quality dofollow backlinks.</body></html>'
        r=analyze_html(html,'https://example.com/')
        self.assertTrue(r['spam_signals'])

    def test_entry_link_found_by_anchor_text_alone(self):
        # 入口链接常常只在可见锚文本里表明意图，href 看不出来（/s/new）。
        # 只匹配 href+title 会整条漏掉这类入口。
        html='<html><body><a href="/s/new">Submit a tool</a></body></html>'
        r=analyze_html(html,'https://example.com/')
        self.assertIn('https://example.com/s/new', r['candidate_urls'])

    def test_entry_links_rank_before_generic_discovery_links(self):
        # DISCOVERY_HINTS 太宽（blog/product/tool 都算）。真正的投稿入口必须排在
        # 泛导航链接前面，否则会被挤出 probe 的请求预算。
        html=('<html><body>'
              '<a href="/blog">Blog</a><a href="/products">Products</a>'
              '<a href="/tools">Tools</a><a href="/news">News</a>'
              '<a href="/community">Community</a><a href="/forum">Forum</a>'
              '<a href="/x7">Write for us</a>'
              '</body></html>')
        r=analyze_html(html,'https://example.com/')
        self.assertEqual(r['candidate_urls'][0], 'https://example.com/x7')

    def test_disclaimer_is_not_treated_as_a_claim_entry(self):
        # "disclaimer" 里含 "claim"。没有词边界的话，实测 10 个新命中里有 4 个
        # 是 /disclaimer，纯属浪费探测预算。
        html='<html><body><a href="/en/disclaimer">Disclaimer</a></body></html>'
        r=analyze_html(html,'https://example.com/')
        self.assertNotIn('https://example.com/en/disclaimer', r['candidate_urls'])

    def test_real_claim_entry_still_detected(self):
        html='<html><body><a href="/claim">Claim your listing</a></body></html>'
        r=analyze_html(html,'https://example.com/')
        self.assertIn('https://example.com/claim', r['candidate_urls'])

    def test_anchor_text_does_not_leak_across_unclosed_links(self):
        # 未闭合的 <a> 不能把后一条的锚文本串到前一条上，否则会凭空造出入口。
        html='<html><body><a href="/plain"><a href="/real">Submit your site</a></body></html>'
        r=analyze_html(html,'https://example.com/')
        self.assertIn('https://example.com/real', r['candidate_urls'])
        self.assertNotIn('https://example.com/plain', r['candidate_urls'])

class ClassifyTests(unittest.TestCase):
    def test_no_mechanism_is_unverified_not_dead(self):
        # 没找到入口是证据缺失，不是淘汰结论（SKILL 硬规则 11）。
        probe={'home': {'status':200,'noindex':False,'spam_signals':[],'mechanism_signals':[]}, 'pages':[], 'errors':[]}
        r=classify_probe(probe)
        self.assertEqual(r['bucket'],'unverified')
        self.assertEqual(r['reason_code'],'no_generic_mechanism')

    def test_blind_probed_noindex_page_does_not_kill_domain(self):
        # /submit 等盲探路径常返回软 200 + noindex（hashnode.com）。
        # 该页没有机制信号时不能代表站点不可索引。
        probe={'home': {'status':200,'noindex':False,'spam_signals':[],'mechanism_signals':[]},
               'pages':[{'status':200,'noindex':True,'mechanism_signals':[],'spam_signals':[]}],
               'errors':[]}
        r=classify_probe(probe)
        self.assertNotEqual(r['reason_code'],'noindex')
        self.assertEqual(r['bucket'],'unverified')

    def test_blind_probed_page_with_text_signals_still_does_not_kill_domain(self):
        # polymarket.com 的 /submit /add /submit-site 全是软 200 + noindex，
        # SPA 壳里的文案还撞上了机制正则。盲探来的页面不能代表站点，
        # 哪怕它有文案信号也不能拿来淘汰整个域名。
        probe={'home': {'status':200,'noindex':False,'spam_signals':[],'mechanism_signals':[]},
               'pages':[{'status':200,'noindex':True,'blind_probe':True,
                         'mechanism_signals':[r'\bsubmit (?:your )?(?:website|site)\b'],
                         'spam_signals':[]}],
               'errors':[]}
        r=classify_probe(probe)
        self.assertNotEqual(r['bucket'],'dead')

    def test_cross_host_noindex_page_does_not_kill_domain(self):
        # aitools.fyi 曾被 tally.so 的表单页 noindex 判死，aicloudbase.com 被
        # 另一个域名的页面判死。别的站的页面不能代表本站。
        probe={'home': {'status':200,'noindex':False,'spam_signals':[],'mechanism_signals':[],
                        'final_url':'https://aitools.fyi/'},
               'pages':[{'status':200,'noindex':True,'final_url':'https://tally.so/r/2EkV4g',
                         'mechanism_signals':[r'\bsubmit (?:your )?(?:website|site)\b'],
                         'spam_signals':[]}],
               'errors':[]}
        r=classify_probe(probe)
        self.assertNotEqual(r['bucket'],'dead')

    def test_www_variant_still_counts_as_same_host(self):
        # www 与裸域是同一个站，不能因为前缀不同就放过真实的入口页 noindex。
        probe={'home': {'status':200,'noindex':False,'spam_signals':[],'mechanism_signals':[],
                        'final_url':'https://allaboutai.com/'},
               'pages':[{'status':200,'noindex':True,'final_url':'https://www.allaboutai.com/submit/',
                         'mechanism_signals':[r'\bsubmit (?:your )?(?:website|site)\b'],
                         'spam_signals':[]}],
               'errors':[]}
        r=classify_probe(probe)
        self.assertEqual(r['bucket'],'dead')
        self.assertEqual(r['reason_code'],'noindex')

    def test_login_wall_noindex_does_not_kill_domain(self):
        # 提交入口跳到登录页，登录页 noindex 是理所当然的。而且 callbackUrl 里
        # 写着 /submit，恰恰说明投稿机制存在——这种必须留在 pending。
        probe={'home': {'status':200,'noindex':False,'spam_signals':[],'mechanism_signals':[],
                        'final_url':'https://peerpush.com/'},
               'pages':[{'status':200,'noindex':True,'url':'https://peerpush.com/submit',
                         'final_url':'https://peerpush.com/auth/login?redirectTo=%2Fsubmit',
                         'mechanism_signals':[r'\bsubmit (?:your )?(?:website|site)\b'],
                         'spam_signals':[]}],
               'errors':[]}
        r=classify_probe(probe)
        self.assertNotEqual(r['bucket'],'dead')

    def test_redirected_page_noindex_does_not_kill_domain(self):
        # 跟着跳转跑到别的路径，那个 noindex 属于跳转目标，不属于这个入口。
        probe={'home': {'status':200,'noindex':False,'spam_signals':[],'mechanism_signals':[],
                        'final_url':'https://example.com/'},
               'pages':[{'status':200,'noindex':True,'url':'https://example.com/submit',
                         'final_url':'https://example.com/category/news/',
                         'mechanism_signals':[r'\bsubmit (?:your )?(?:website|site)\b'],
                         'spam_signals':[]}],
               'errors':[]}
        r=classify_probe(probe)
        self.assertNotEqual(r['bucket'],'dead')

    def test_category_page_noindex_does_not_kill_domain(self):
        # 目录站每页导航里都有 "Submit your tool"，所以文案命中说明不了这一页
        # 是入口。/category/news/ 这类归档页 noindex 是常规做法，不能判死。
        probe={'home': {'status':200,'noindex':False,'spam_signals':[],'mechanism_signals':[],
                        'final_url':'https://kulfiy.com/'},
               'pages':[{'status':200,'noindex':True,'final_url':'https://kulfiy.com/category/news/',
                         'mechanism_signals':[r'\bsubmit (?:your )?(?:website|site)\b'],
                         'spam_signals':[]}],
               'errors':[]}
        r=classify_probe(probe)
        self.assertNotEqual(r['bucket'],'dead')

    def test_noindex_on_real_entry_page_is_dead(self):
        probe={'home': {'status':200,'noindex':False,'spam_signals':[],'mechanism_signals':[],
                        'final_url':'https://example.com/'},
               'pages':[{'status':200,'noindex':True,'final_url':'https://example.com/submit',
                         'mechanism_signals':['submit'],'spam_signals':[]}],
               'errors':[]}
        r=classify_probe(probe)
        self.assertEqual(r['bucket'],'dead')
        self.assertEqual(r['reason_code'],'noindex')

    def test_homepage_noindex_is_dead(self):
        probe={'home': {'status':200,'noindex':True,'spam_signals':[],'mechanism_signals':[]}, 'pages':[], 'errors':[]}
        r=classify_probe(probe)
        self.assertEqual(r['bucket'],'dead')
        self.assertEqual(r['reason_code'],'noindex')

    def test_path_only_evidence_does_not_trigger_noindex_kill(self):
        # 'path:' 是探测到真实入口路径时注入的伪信号，不是文案证据。
        # 它不能把一个 noindex 页面升级成"入口页 noindex"淘汰依据。
        probe={'home': {'status':200,'noindex':False,'spam_signals':[],'mechanism_signals':[]},
               'pages':[{'status':200,'noindex':True,'mechanism_signals':['path:/submit'],'spam_signals':[]}],
               'errors':[]}
        r=classify_probe(probe)
        self.assertNotEqual(r['bucket'],'dead')

    def test_nxdomain_is_dead(self):
        probe={'home': {'status':0,'error':'URLError: <urlopen error [Errno -2] Name or service not known>'}, 'pages':[], 'errors':['URLError: <urlopen error [Errno -2] Name or service not known>']}
        r=classify_probe(probe)
        self.assertEqual(r['bucket'],'dead')
        self.assertEqual(r['reason_code'],'inactive_dns')

    def test_pending_when_blocked(self):
        probe={'home': {'status':403}, 'pages':[], 'errors':['HTTP 403']}
        r=classify_probe(probe)
        self.assertEqual(r['bucket'],'pending')
        self.assertEqual(r['reason_code'],'blocked_or_uncertain')

    def test_paid_when_submission_page_is_paid_and_not_free(self):
        probe={'home': {'status':200,'noindex':False,'spam_signals':[],'mechanism_signals':['submit']},
               'pages':[{'status':200,'noindex':False,'mechanism_signals':['submit'],'paid_signals':['pricing','$'],'free_signals':[]}],
               'errors':[]}
        r=classify_probe(probe)
        self.assertEqual(r['bucket'],'paid')

    def test_pending_when_free_submission_exists_but_link_attributes_not_proven(self):
        probe={'home': {'status':200,'noindex':False,'spam_signals':[],'mechanism_signals':['submit']},
               'pages':[{'status':200,'noindex':False,'mechanism_signals':['submit'],'paid_signals':[],'free_signals':['free']}],
               'errors':[]}
        r=classify_probe(probe)
        self.assertEqual(r['bucket'],'pending')
        self.assertEqual(r['reason_code'],'mechanism_needs_link_verification')

if __name__=='__main__': unittest.main()
