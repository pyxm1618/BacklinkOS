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

    def test_noindex_on_real_entry_page_is_dead(self):
        probe={'home': {'status':200,'noindex':False,'spam_signals':[],'mechanism_signals':[]},
               'pages':[{'status':200,'noindex':True,'mechanism_signals':['submit'],'spam_signals':[]}],
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
