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
    def test_recycles_reachable_site_with_no_generic_mechanism(self):
        probe={'home': {'status':200,'noindex':False,'spam_signals':[],'mechanism_signals':[]}, 'pages':[], 'errors':[]}
        r=classify_probe(probe)
        self.assertEqual(r['bucket'],'recycle')
        self.assertEqual(r['reason_code'],'no_generic_mechanism')

    def test_recycles_nxdomain_as_inactive(self):
        probe={'home': {'status':0,'error':'URLError: <urlopen error [Errno -2] Name or service not known>'}, 'pages':[], 'errors':['URLError: <urlopen error [Errno -2] Name or service not known>']}
        r=classify_probe(probe)
        self.assertEqual(r['bucket'],'recycle')
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
