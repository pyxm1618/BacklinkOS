import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_script(script, *args):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


class PrepareScreeningInputTests(unittest.TestCase):
    def test_preserves_file_boundaries_and_builds_a_reconciled_incremental_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            candidate_dir = work / "candidates"
            candidate_dir.mkdir()
            (candidate_dir / "001.txt").write_text("alpha.com", encoding="utf-8")
            (candidate_dir / "002.txt").write_text("beta.com\nalpha.com\n", encoding="utf-8")

            discovery = work / "discovery.json"
            discovery.write_text(
                json.dumps(
                    {
                        "refdomain_aggregates": [
                            {
                                "referring_domain": "alpha.com",
                                "source_projects": ["one.example"],
                                "successful_project_count": 1,
                                "batch_id": "batch-1",
                            },
                            {
                                "referring_domain": "gamma.com",
                                "source_projects": ["two.example"],
                                "successful_project_count": 1,
                                "batch_id": "batch-1",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            existing_results = work / "latest.jsonl"
            existing_results.write_text(
                json.dumps(
                    {
                        "domain": "alpha.com",
                        "input": {"domain": "alpha.com"},
                        "decision": {"bucket": "unverified", "reason_code": "no_generic_mechanism"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            existing_status = work / "internal-status.csv"
            with existing_status.open("w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.DictWriter(fh, fieldnames=["Domain", "处理结果"])
                writer.writeheader()
                writer.writerow({"Domain": "beta.com", "处理结果": "正式机会"})

            output = work / "screening-input.csv"
            manifest = work / "screening-input.manifest.json"
            result = run_script(
                "prepare_screening_input.py",
                "--candidate-dir",
                candidate_dir,
                "--discovery-json",
                discovery,
                "--existing-results",
                existing_results,
                "--existing-status",
                existing_status,
                "--output",
                output,
                "--manifest",
                manifest,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            with output.open(newline="", encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual([row["domain"] for row in rows], ["alpha.com", "beta.com", "gamma.com"])
            self.assertNotIn("alpha.combeta.com", {row["domain"] for row in rows})

            ledger = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(
                ledger["candidate_counts"],
                {
                    "existing_pool_unique": 2,
                    "discovery_unique": 2,
                    "overlap": 1,
                    "discovery_new": 1,
                    "combined_unique": 3,
                },
            )
            self.assertEqual(
                ledger["status_ledger"],
                {
                    "approved": 1,
                    "deferred": 0,
                    "confirmed_reject": 0,
                    "triaged_only": 1,
                    "unreviewed": 1,
                },
            )
            self.assertEqual(sum(ledger["status_ledger"].values()), 3)
            self.assertEqual(ledger["crawler_queue_count"], 1)


class IncrementalCrawlerTests(unittest.TestCase):
    def test_reuses_existing_result_without_crawling_it_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            input_csv = work / "input.csv"
            with input_csv.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=["domain", "batch_id"])
                writer.writeheader()
                writer.writerow({"domain": "alpha.com", "batch_id": "new-batch"})

            existing = work / "latest.jsonl"
            existing.write_text(
                json.dumps(
                    {
                        "domain": "alpha.com",
                        "input": {"domain": "alpha.com", "batch_id": "old-batch"},
                        "home": {"status": 200},
                        "pages": [],
                        "errors": [],
                        "decision": {"bucket": "unverified", "reason_code": "no_generic_mechanism"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            output = work / "merged.jsonl"

            result = run_script(
                "screening_crawler.py",
                "--input",
                input_csv,
                "--output",
                output,
                "--existing-results",
                existing,
                "--workers",
                "1",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["input"]["batch_id"], "new-batch")
            summary = json.loads((Path(str(output) + ".summary.json")).read_text(encoding="utf-8"))
            self.assertEqual(summary["reused"], 1)
            self.assertEqual(summary["processed_this_run"], 0)

    def test_does_not_crawl_a_status_managed_domain_when_triage_history_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            input_csv = work / "input.csv"
            with input_csv.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=["domain", "queue_state"])
                writer.writeheader()
                writer.writerow({"domain": "status-only.invalid", "queue_state": "approved"})

            output = work / "merged.jsonl"
            result = run_script(
                "screening_crawler.py",
                "--input",
                input_csv,
                "--output",
                output,
                "--workers",
                "1",
                "--timeout",
                "1",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads((Path(str(output) + ".summary.json")).read_text(encoding="utf-8"))
            self.assertEqual(summary["processed_this_run"], 0)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["decision"]["reason_code"], "existing_status_reused")


class IncrementalDeepScreeningTests(unittest.TestCase):
    def _write_status(self, path):
        fields = [
            "Domain",
            "下一步",
            "操作入口",
            "获取方式",
            "处理结果",
            "已确认事实",
            "缺失事实",
            "证据URL",
            "证据日期",
            "外链形式",
            "DR",
            "成功项目数",
        ]
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerow(
                {
                    "Domain": "alpha.com",
                    "下一步": "可以做——去操作入口发布",
                    "操作入口": "https://alpha.com/submit",
                    "获取方式": "免费",
                    "处理结果": "正式机会",
                    "已确认事实": "已验证",
                    "缺失事实": "",
                    "证据URL": "https://alpha.com/example",
                    "证据日期": "2026-09-01",
                    "外链形式": "Follow 外链",
                    "DR": "",
                    "成功项目数": "1",
                }
            )

    def test_browser_probe_skips_domains_already_in_internal_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            input_jsonl = work / "crawler.jsonl"
            record = {
                "domain": "alpha.com",
                "input": {"domain": "alpha.com"},
                "home": {"status": 403},
                "pages": [],
                "errors": ["HTTP 403"],
                "decision": {"bucket": "pending", "reason_code": "blocked_or_uncertain"},
            }
            input_jsonl.write_text(json.dumps(record) + "\n", encoding="utf-8")
            status = work / "internal-status.csv"
            self._write_status(status)
            output = work / "browser.jsonl"

            result = run_script(
                "browser_probe.py",
                "--input",
                input_jsonl,
                "--output",
                output,
                "--existing-status",
                status,
                "--workers",
                "1",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("已有深入状态跳过 1", result.stdout)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows, [record])

    def test_verify_preserves_existing_status_instead_of_rechecking_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            input_jsonl = work / "browser.jsonl"
            input_jsonl.write_text(
                json.dumps(
                    {
                        "domain": "alpha.com",
                        "input": {"domain": "alpha.com"},
                        "home": {"status": 200, "final_url": "https://alpha.com/"},
                        "pages": [],
                        "errors": [],
                        "decision": {
                            "bucket": "pending",
                            "reason_code": "mechanism_needs_link_verification",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            output_dir = work / "opportunities"
            output_dir.mkdir()
            status = output_dir / "internal-status.csv"
            self._write_status(status)

            result = run_script(
                "verify_opportunity.py",
                "--input",
                input_jsonl,
                "--out-dir",
                output_dir,
                "--existing-status",
                status,
                "--workers",
                "1",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("已有深入状态复用 1", result.stdout)
            with status.open(newline="", encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["处理结果"], "正式机会")
            with (output_dir / "opportunities.csv").open(newline="", encoding="utf-8-sig") as fh:
                opportunities = list(csv.DictReader(fh))
            self.assertEqual([row["Domain"] for row in opportunities], ["alpha.com"])


if __name__ == "__main__":
    unittest.main()
