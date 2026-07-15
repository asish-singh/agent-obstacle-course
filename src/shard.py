"""Scan one shard of the site list. Entry point for the census jobs.

Usage:
  python3 -m src.shard --shard 0 --shard-size 250
  python3 -m src.shard --shard 0 --pilot          (first 50 sites only)

Reads config/sites.csv, runs fetch plus render per site with an 8 worker pool
for fetches and at most 3 concurrent renders, and writes one gzipped JSON
evidence file per site to out/shard_N/ plus shard_summary.json. Ordering of
outputs is deterministic (by rank). Any per site exception is caught and the
site is recorded as unreachable with the error.
"""

import argparse
import csv
import gzip
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import classify
from src.fetcher import SiteFetcher

FETCH_WORKERS = 8
RENDER_CONCURRENCY = 3
TEXT_LIMIT = 20 * 1024
PILOT_SIZE = 50

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_sites(shard, shard_size, pilot):
    sites = []
    with open(os.path.join(ROOT, "config", "sites.csv"), encoding="utf-8") as f:
        for row in csv.DictReader(r for r in f if not r.startswith("#")):
            sites.append((int(row["rank"]), row["domain"]))
    sites.sort()
    if pilot:
        return sites[:PILOT_SIZE]
    return sites[shard * shard_size:(shard + 1) * shard_size]


def scan_site(rank, domain, signatures, penalties, render_semaphore, render_enabled):
    """Fetch, render, classify one site. Never raises."""
    try:
        evidence = SiteFetcher(domain).fetch_all()
        evidence["rank"] = rank
        evidence["domain_input"] = domain

        if evidence.get("state") == "scanned" and render_enabled:
            from src.renderer import render_homepage
            # Playwright's sync API is not thread safe, so each render runs
            # its own Chromium; the semaphore caps concurrency at 3.
            with render_semaphore:
                evidence["render"] = render_homepage(evidence["homepage_url"], signatures)
        else:
            evidence["render"] = None

        for key in ("fetch_agent", "fetch_browser"):
            fetch = evidence.get(key)
            if fetch is not None:
                fetch["text"] = classify.extract_text(fetch.get("body"))[:TEXT_LIMIT]
                fetch["body"] = (fetch.get("body") or "")[:TEXT_LIMIT]

        evidence["classification"] = classify.classify_site(evidence, signatures, penalties)
        return evidence
    except Exception as exc:
        return {
            "rank": rank, "domain": domain, "domain_input": domain,
            "state": "unreachable", "error": f"{type(exc).__name__}: {str(exc)[:400]}",
            "render": None,
            "classification": {"state": "unreachable",
                               "o1": classify.NOT_ASSESSED, "o2": classify.NOT_ASSESSED,
                               "o3": classify.NOT_ASSESSED, "o4": classify.NOT_ASSESSED,
                               "o1_vendor": None, "o5": {}, "consent": {},
                               "o4_caveat": None, "score": None},
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Scan one census shard.")
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--shard-size", type=int, default=250)
    parser.add_argument("--pilot", action="store_true",
                        help="scan only the first 50 sites")
    args = parser.parse_args(argv)

    signatures, penalties = classify.load_config()
    sites = load_sites(args.shard, args.shard_size, args.pilot)
    out_dir = os.path.join(ROOT, "out", f"shard_{args.shard}")
    os.makedirs(out_dir, exist_ok=True)

    render_semaphore = threading.Semaphore(RENDER_CONCURRENCY)

    try:
        import playwright.sync_api  # noqa: F401
        render_enabled = True
    except ImportError as exc:
        render_enabled = False
        print(f"warning: Playwright unavailable, renders skipped ({exc})", file=sys.stderr)

    results = []
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        futures = [pool.submit(scan_site, rank, domain, signatures, penalties,
                               render_semaphore, render_enabled)
                   for rank, domain in sites]
        for future in futures:
            results.append(future.result())

    results.sort(key=lambda e: e["rank"])
    summary = {"shard": args.shard, "sites": len(results), "states": {}}
    for evidence in results:
        path = os.path.join(out_dir, f"{evidence['rank']:05d}_{evidence['domain_input']}.json.gz")
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(evidence, f, ensure_ascii=False)
        state = evidence.get("state", "unknown")
        summary["states"][state] = summary["states"].get(state, 0) + 1

    with open(os.path.join(out_dir, "shard_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
