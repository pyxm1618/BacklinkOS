#!/usr/bin/env python3
"""合并历史候选与 Discovery 结果，生成去重后的筛选输入和状态账本。"""

import argparse
import csv
import json
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlparse


STATUS_TO_LEDGER = {
    "正式机会": "approved",
    "待确认": "deferred",
    "付费排除": "confirmed_reject",
    "已确认淘汰": "confirmed_reject",
    "回收": "confirmed_reject",
}


def normalize_domain(value):
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else "//" + raw)
    host = (parsed.hostname or "").strip().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def load_candidate_files(candidate_dir):
    records = OrderedDict()
    files = sorted(Path(candidate_dir).glob("[0-9][0-9][0-9].txt"))
    if not files:
        raise ValueError(f"没有找到候选文件：{candidate_dir}/[0-9][0-9][0-9].txt")
    for path in files:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            domain = normalize_domain(raw_line)
            if not domain:
                continue
            record = records.setdefault(
                domain,
                {"domain": domain, "candidate_sources": [], "discovery_records": []},
            )
            source = str(path)
            if source not in record["candidate_sources"]:
                record["candidate_sources"].append(source)
    return records


def load_discovery(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("refdomain_aggregates")
    if not isinstance(rows, list):
        raise ValueError(f"Discovery 文件缺少 refdomain_aggregates：{path}")
    return payload, rows


def load_existing_results(path):
    results = {}
    if not path or not Path(path).exists():
        return results
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            domain = normalize_domain(row.get("domain"))
            if domain:
                results[domain] = row
    return results


def load_existing_status(path):
    statuses = {}
    if not path or not Path(path).exists():
        return statuses
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            domain = normalize_domain(row.get("Domain"))
            if domain:
                statuses[domain] = row
    return statuses


def merge_discovery_record(target, row, fallback_batch_id):
    copied = dict(row)
    copied["referring_domain"] = target["domain"]
    if not copied.get("batch_id") and fallback_batch_id:
        copied["batch_id"] = fallback_batch_id
    target["discovery_records"].append(copied)


def summarize_discovery(record):
    rows = record["discovery_records"]
    projects = []
    batch_ids = []
    sources = []
    for row in rows:
        for project in row.get("source_projects") or []:
            if project not in projects:
                projects.append(project)
        batch_id = row.get("batch_id")
        if batch_id and batch_id not in batch_ids:
            batch_ids.append(batch_id)
        source = row.get("discovery_source")
        if source and source not in sources:
            sources.append(source)
    latest = rows[-1] if rows else {}
    return {
        "source_projects": projects,
        "successful_project_count": len(projects) if projects else latest.get("successful_project_count", ""),
        "batch_ids": batch_ids,
        "discovery_sources": sources,
        "latest": latest,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--discovery-json", action="append", default=[])
    parser.add_argument("--existing-results", default="")
    parser.add_argument("--existing-status", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    candidates = load_candidate_files(args.candidate_dir)
    existing_pool = set(candidates)
    discovery_domains = set()

    for path in args.discovery_json:
        payload, rows = load_discovery(path)
        fallback_batch_id = payload.get("batch_id", "")
        for row in rows:
            domain = normalize_domain(row.get("referring_domain"))
            if not domain:
                continue
            discovery_domains.add(domain)
            target = candidates.setdefault(
                domain,
                {"domain": domain, "candidate_sources": [], "discovery_records": []},
            )
            merge_discovery_record(target, row, fallback_batch_id)

    existing_results = load_existing_results(args.existing_results)
    existing_status = load_existing_status(args.existing_status)
    ledger = {
        "approved": 0,
        "deferred": 0,
        "confirmed_reject": 0,
        "triaged_only": 0,
        "unreviewed": 0,
    }

    fieldnames = [
        "domain",
        "queue_state",
        "existing_processing_result",
        "candidate_sources",
        "discovery_source",
        "batch_id",
        "source_projects",
        "source_project_organic_traffic",
        "successful_project_count",
        "occurrence_count",
        "domain_ascore",
        "backlinks_num",
        "first_seen",
        "last_seen",
        "semrush_is_follow",
        "first_discovered_at",
        "seen_before",
        "discovery_facts",
    ]
    output_rows = []
    for domain in sorted(candidates):
        record = candidates[domain]
        status = existing_status.get(domain, {})
        processing_result = status.get("处理结果", "")
        if processing_result:
            state = STATUS_TO_LEDGER.get(processing_result, "deferred")
        elif domain in existing_results:
            state = "triaged_only"
        else:
            state = "unreviewed"
        ledger[state] += 1

        discovery = summarize_discovery(record)
        latest = discovery["latest"]
        output_rows.append(
            {
                "domain": domain,
                "queue_state": state,
                "existing_processing_result": processing_result,
                "candidate_sources": json.dumps(record["candidate_sources"], ensure_ascii=False),
                "discovery_source": json.dumps(discovery["discovery_sources"], ensure_ascii=False),
                "batch_id": json.dumps(discovery["batch_ids"], ensure_ascii=False),
                "source_projects": json.dumps(discovery["source_projects"], ensure_ascii=False),
                "source_project_organic_traffic": json.dumps(
                    latest.get("source_project_organic_traffic", {}), ensure_ascii=False
                ),
                "successful_project_count": discovery["successful_project_count"],
                "occurrence_count": latest.get("occurrence_count", ""),
                "domain_ascore": latest.get("domain_ascore", ""),
                "backlinks_num": latest.get("backlinks_num", ""),
                "first_seen": latest.get("first_seen", ""),
                "last_seen": latest.get("last_seen", ""),
                "semrush_is_follow": latest.get("semrush_is_follow", ""),
                "first_discovered_at": latest.get("first_discovered_at", ""),
                "seen_before": latest.get("seen_before", ""),
                "discovery_facts": json.dumps(record["discovery_records"], ensure_ascii=False),
            }
        )

    combined_unique = len(candidates)
    if sum(ledger.values()) != combined_unique:
        raise RuntimeError("状态账本数量无法与候选总数对齐")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    manifest = {
        "candidate_counts": {
            "existing_pool_unique": len(existing_pool),
            "discovery_unique": len(discovery_domains),
            "overlap": len(existing_pool & discovery_domains),
            "discovery_new": len(discovery_domains - existing_pool),
            "combined_unique": combined_unique,
        },
        "status_ledger": ledger,
        "crawler_queue_count": ledger["unreviewed"],
        "excluded_existing_result_domains": sorted(set(existing_results) - set(candidates)),
        "output": str(output_path),
    }
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
