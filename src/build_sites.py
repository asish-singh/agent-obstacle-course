"""Build config/sites.csv from the Tranco list. Run once before the census.

Usage: python3 -m src.build_sites [--target 5000]

Downloads the current default Tranco list (top-1m.csv.zip), records the list
ID in config/tranco-list-id.txt, deduplicates entries to registrable (pay
level) domains using the public suffix list via tldextract, applies
config/exclusions.csv, and writes rank,domain rows until the target count of
real websites remains.
"""

import argparse
import csv
import io
import os
import zipfile
from datetime import date, datetime, timezone

import requests
import tldextract

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRANCO_LATEST = "https://tranco-list.eu/top-1m.csv.zip"
TRANCO_ID_API = "https://tranco-list.eu/api/lists/date/latest"


def load_exclusions():
    path = os.path.join(ROOT, "config", "exclusions.csv")
    with open(path, encoding="utf-8") as f:
        return {row["domain"].strip().lower() for row in csv.DictReader(f)}


def fetch_list_id():
    try:
        resp = requests.get(TRANCO_ID_API, timeout=30)
        resp.raise_for_status()
        return resp.json().get("list_id", "unknown")
    except Exception:
        return "unknown"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=5000)
    args = parser.parse_args(argv)

    list_id = fetch_list_id()
    print(f"Tranco list ID: {list_id}")
    print("downloading Tranco top-1m ...")
    resp = requests.get(TRANCO_LATEST, timeout=300)
    resp.raise_for_status()

    extract = tldextract.TLDExtract()  # public suffix list, cached locally
    exclusions = load_exclusions()
    seen = set()
    rows = []
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        name = zf.namelist()[0]
        with zf.open(name) as f:
            for line in io.TextIOWrapper(f, encoding="utf-8"):
                _, _, domain = line.strip().partition(",")
                domain = domain.lower()
                ext = extract(domain)
                if not ext.domain or not ext.suffix:
                    continue
                registrable = f"{ext.domain}.{ext.suffix}"
                if registrable in seen or registrable in exclusions:
                    continue
                seen.add(registrable)
                rows.append(registrable)
                if len(rows) >= args.target:
                    break

    out = os.path.join(ROOT, "config", "sites.csv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write(f"# Tranco list ID {list_id}, downloaded {datetime.now(timezone.utc).date()}, "
                "deduplicated to registrable domains via the public suffix list "
                "(tldextract), exclusions.csv applied\n")
        f.write("rank,domain\n")
        for i, domain in enumerate(rows, 1):
            f.write(f"{i},{domain}\n")
    with open(os.path.join(ROOT, "config", "tranco-list-id.txt"), "w", encoding="utf-8") as f:
        f.write(f"list_id: {list_id}\ndownloaded: {date.today().isoformat()}\n"
                f"source: {TRANCO_LATEST}\n"
                "note: default Tranco list deduplicated to registrable (pay level) "
                "domains using the public suffix list via tldextract\n")
    print(f"wrote {out} with {len(rows)} sites")


if __name__ == "__main__":
    main()
