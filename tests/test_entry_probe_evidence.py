import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from master_sheet_sync import discover_and_verify_entry


class EntryProbeEvidenceTests(unittest.TestCase):
    def test_timeout_on_first_candidate_does_not_hide_second_valid_candidate(self):
        calls = []
        evidence = []

        def fake_fetch(url):
            calls.append(url)
            if url == "https://example.com/":
                return {
                    "url": url,
                    "final_url": url,
                    "status": 200,
                    "candidate_urls": [
                        "https://example.com/first",
                        "https://example.com/second",
                    ],
                    "submission_cta_links": [],
                    "actionable_forms": [],
                    "ai_only_signals": [],
                }
            if url == "https://example.com/first":
                return {
                    "url": url,
                    "final_url": url,
                    "status": 0,
                    "error": "TimeoutError: timed out",
                }
            if url == "https://example.com/second":
                return {
                    "url": url,
                    "final_url": url,
                    "status": 200,
                    "actionable_forms": [{
                        "form_type": "directory_listing",
                        "action": url,
                        "resource_fields": ["website"],
                        "submit_controls": ["Submit listing"],
                    }],
                    "submission_cta_links": [],
                    "ai_only_signals": [],
                }
            return {"url": url, "final_url": url, "status": 404, "error": "HTTP 404"}

        entry, _ = discover_and_verify_entry(
            "example.com",
            fetcher=fake_fetch,
            max_probes=2,
            evidence_sink=evidence,
        )

        self.assertIsNotNone(entry)
        self.assertEqual(entry.url, "https://example.com/second")
        self.assertIn("https://example.com/first", calls)
        self.assertIn("https://example.com/second", calls)
        first = next(item for item in evidence if item["url"] == "https://example.com/first")
        self.assertEqual(first["status"], 0)
        self.assertEqual(first["error"], "TimeoutError: timed out")
        self.assertEqual(first["timeout_stage"], "unknown")

    def test_home_http_statuses_are_preserved_instead_of_collapsing_to_http_zero(self):
        for status in (403, 404, 429, 503):
            with self.subTest(status=status):
                evidence = []

                def fake_fetch(url, _status=status):
                    return {
                        "url": url,
                        "final_url": url,
                        "status": _status,
                        "error": f"HTTP {_status}",
                    }

                entry, reason = discover_and_verify_entry(
                    "status.example",
                    fetcher=fake_fetch,
                    evidence_sink=evidence,
                )
                self.assertIsNone(entry)
                self.assertTrue(evidence)
                self.assertTrue(all(item["status"] == status for item in evidence))
                self.assertTrue(all(item["error"] == f"HTTP {status}" for item in evidence))
                self.assertNotIn("HTTP 0", reason)
                self.assertIn(str(status), reason)

    def test_unknown_timeout_stage_is_not_invented(self):
        evidence = []

        def fake_fetch(url):
            return {
                "url": url,
                "final_url": url,
                "status": 0,
                "error": "socket.timeout: timed out",
            }

        entry, reason = discover_and_verify_entry(
            "timeout.example",
            fetcher=fake_fetch,
            evidence_sink=evidence,
        )
        self.assertIsNone(entry)
        self.assertTrue(evidence)
        self.assertTrue(all(item["error"] == "socket.timeout: timed out" for item in evidence))
        self.assertTrue(all(item["timeout_stage"] == "unknown" for item in evidence))
        self.assertIn("socket.timeout", reason)


if __name__ == "__main__":
    unittest.main()
