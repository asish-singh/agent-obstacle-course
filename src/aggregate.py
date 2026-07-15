"""Merge shard outputs into the census dataset and report.

Usage: python3 -m src.aggregate [--in out] [--data data]

Reads every out/shard_*/ evidence file, dedupes cross domain landings (the
highest ranked site keeps the result, lower ranked duplicates are flagged
duplicate_of), writes data/census.csv, copies evidence into data/raw/, and
writes REPORT.md with every number derived from census.csv.
"""

import argparse
import csv
import glob
import gzip
import json
import os
import shutil
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CSV_COLUMNS = [
    "rank", "domain", "final_url", "state", "o1", "o1_vendor", "o2", "o3", "o4",
    "o5_robots_disallows_home", "o5_robots_ai_directives", "o5_noai_meta",
    "o5_llms_txt", "consent_cmp", "consent_overlay", "score", "category",
    "duplicate_of", "error",
]

RANK_BANDS = [("top 100", 1, 100), ("101 to 1000", 101, 1000), ("1001 to 5000", 1001, 5000)]


def load_evidence(in_dir):
    records = []
    for path in sorted(glob.glob(os.path.join(in_dir, "shard_*", "*.json.gz"))):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            evidence = json.load(f)
        evidence["_path"] = path
        records.append(evidence)
    records.sort(key=lambda e: e["rank"])
    return records


def dedupe(records):
    """Flag sites whose fetches landed on another sampled registrable domain."""
    landing_owner = {}
    for e in records:  # ascending rank, so first owner is highest ranked
        landed = e.get("cross_domain_landing") or e.get("domain_input")
        landing_owner.setdefault(landed, e["domain_input"])
    for e in records:
        landed = e.get("cross_domain_landing")
        e["duplicate_of"] = None
        if landed:
            owner = landing_owner.get(landed)
            if owner and owner != e["domain_input"]:
                e["duplicate_of"] = owner
    return records


def to_row(e):
    c = e.get("classification", {})
    o5 = c.get("o5", {})
    consent = c.get("consent", {})

    def flag(value):
        if value == "not_assessed":
            return "not_assessed"
        return "1" if value else "0"

    final_url = None
    for key in ("fetch_browser", "fetch_agent"):
        fetch = e.get(key) or {}
        final_url = final_url or fetch.get("final_url")
    return {
        "rank": e["rank"],
        "domain": e.get("domain_input") or e.get("domain"),
        "final_url": final_url or "",
        "state": e.get("state", "unknown"),
        "o1": flag(c.get("o1")),
        "o1_vendor": c.get("o1_vendor") or "",
        "o2": flag(c.get("o2")),
        "o3": flag(c.get("o3")),
        "o4": flag(c.get("o4")),
        "o5_robots_disallows_home": flag(o5.get("robots_disallows_home")),
        "o5_robots_ai_directives": ";".join(o5.get("robots_ai_directives", [])),
        "o5_noai_meta": flag(o5.get("noai_meta")),
        "o5_llms_txt": flag(o5.get("llms_txt")),
        "consent_cmp": ";".join(consent.get("cmp_scripts", [])),
        "consent_overlay": flag(consent.get("overlay")),
        "score": "" if c.get("score") is None else c.get("score"),
        "category": e.get("category", ""),
        "duplicate_of": e.get("duplicate_of") or "",
        "error": e.get("error") or "",
    }


def write_census(records, data_dir):
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "census.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for e in records:
            writer.writerow(to_row(e))
    return path


def copy_raw(records, data_dir):
    raw_dir = os.path.join(data_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    for e in records:
        shutil.copy2(e["_path"], os.path.join(raw_dir, os.path.basename(e["_path"])))


def read_census(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pct(n, d):
    return f"{100.0 * n / d:.1f}%" if d else "n/a"


def obstacle_stats(rows):
    stats = {}
    for key in ("o1", "o2", "o3", "o4"):
        assessed = [r for r in rows if r[key] in ("0", "1")]
        hit = sum(1 for r in assessed if r[key] == "1")
        stats[key] = (hit, len(assessed))
    return stats


def write_report(census_path, report_path):
    rows = read_census(census_path)
    unique = [r for r in rows if not r["duplicate_of"]]
    scanned = [r for r in unique if r["state"] == "scanned"]
    declared = [r for r in unique if r["state"] == "declared_exclusion"]
    unreachable = [r for r in unique if r["state"] == "unreachable"]
    scores = sorted(int(r["score"]) for r in scanned if r["score"] != "")

    lines = []
    lines.append("# The Agent Obstacle Course, Census Report")
    lines.append("")
    lines.append("Every number below is derived from `data/census.csv`. "
                 "Methodology in `METHODOLOGY.md`.")
    lines.append("")
    lines.append("## Sample")
    lines.append("")
    lines.append(f"- Sites in sample: {len(rows)}")
    lines.append(f"- Unique sites after cross domain deduplication: {len(unique)}")
    lines.append(f"- Scanned: {len(scanned)}, declared exclusion: {len(declared)}, "
                 f"unreachable: {len(unreachable)}")
    lines.append("")

    lines.append("## Obstacle prevalence")
    lines.append("")
    names = {"o1": "O1 bot wall", "o2": "O2 JavaScript dependency",
             "o3": "O3 identity discrimination", "o4": "O4 login wall"}
    lines.append("| Obstacle | Overall | " + " | ".join(b[0] for b in RANK_BANDS) + " |")
    lines.append("|---|---|" + "---|" * len(RANK_BANDS))
    overall = obstacle_stats(scanned)
    band_stats = []
    for _, lo, hi in RANK_BANDS:
        band_rows = [r for r in scanned if lo <= int(r["rank"]) <= hi]
        band_stats.append(obstacle_stats(band_rows))
    for key in ("o1", "o2", "o3", "o4"):
        hit, total = overall[key]
        cells = [f"{pct(hit, total)} ({hit}/{total})"]
        for stats in band_stats:
            h, t = stats[key]
            cells.append(f"{pct(h, t)} ({h}/{t})")
        lines.append(f"| {names[key]} | " + " | ".join(cells) + " |")
    lines.append("")
    clean = sum(1 for r in scanned
                if all(r[k] in ("0", "not_assessed") for k in ("o1", "o2", "o3", "o4"))
                and r["o1"] == "0")
    lines.append(f"Sites a non browser agent can read with no scored obstacle: "
                 f"{pct(clean, len(scanned))} ({clean}/{len(scanned)}).")
    lines.append("")

    lines.append("## Score distribution")
    lines.append("")
    if scores:
        buckets = Counter(min(s // 20 * 20, 80) for s in scores)
        lines.append("| Score band | Sites |")
        lines.append("|---|---|")
        for lo in (0, 20, 40, 60, 80):
            label = f"{lo} to {lo + 19}" if lo < 80 else "80 to 100"
            lines.append(f"| {label} | {buckets.get(lo, 0)} |")
        mid = scores[len(scores) // 2]
        lines.append("")
        lines.append(f"Median score {mid}, mean {sum(scores) / len(scores):.1f}, "
                     f"minimum {scores[0]}, maximum {scores[-1]}.")
    else:
        lines.append("No scored sites.")
    lines.append("")

    lines.append("## Declared exclusion versus broken")
    lines.append("")
    broken = sum(1 for r in scanned if r["o1"] == "1")
    lines.append(f"- Declared exclusion via robots.txt: {len(declared)} sites "
                 f"({pct(len(declared), len(unique))} of the unique sample). "
                 "These chose to exclude agents and are not scored as broken.")
    lines.append(f"- Bot walled (broken for agents without a declared policy path): "
                 f"{broken} scanned sites ({pct(broken, len(scanned))}).")
    ai_directives = sum(1 for r in unique if r["o5_robots_ai_directives"])
    llms = sum(1 for r in unique if r["o5_llms_txt"] == "1")
    lines.append(f"- Sites with named AI agent robots.txt directives: {ai_directives}.")
    lines.append(f"- Sites publishing llms.txt: {llms}.")
    lines.append("")

    lines.append("## O3, identity discrimination findings")
    lines.append("")
    o3_hit, o3_total = overall["o3"]
    lines.append(f"Of {o3_total} sites where both raw fetches completed, {o3_hit} "
                 f"({pct(o3_hit, o3_total)}) served substantially different responses "
                 "to the declared agent identity than to a stock browser identity "
                 "(different status class, or raw text ratio under 0.5). This is the "
                 "gap between a site being technically readable and being readable "
                 "for an honestly identified agent.")
    o3_domains = [r["domain"] for r in scanned if r["o3"] == "1"][:50]
    if o3_domains:
        lines.append("")
        lines.append("First affected domains (full list in census.csv): "
                     + ", ".join(o3_domains) + ".")
    lines.append("")

    lines.append("## Vantage point and limitations")
    lines.append("")
    lines.append("The scan ran once from US cloud datacenter IPs, which bot protection "
                 "treats far more harshly than residential traffic, so O1 rates are an "
                 "upper bound for datacenter agents. Homepages only, single snapshot, "
                 "signature lists make obstacle counts lower bounds, consent gates are "
                 "recorded but unscored because US egress undercounts them.")
    lines.append("")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return report_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Aggregate census shards.")
    parser.add_argument("--in", dest="in_dir", default=os.path.join(ROOT, "out"))
    parser.add_argument("--data", dest="data_dir", default=os.path.join(ROOT, "data"))
    parser.add_argument("--report", default=os.path.join(ROOT, "REPORT.md"))
    args = parser.parse_args(argv)

    records = dedupe(load_evidence(args.in_dir))
    census_path = write_census(records, args.data_dir)
    copy_raw(records, args.data_dir)
    write_report(census_path, args.report)
    print(f"wrote {census_path} and {args.report} for {len(records)} sites")


if __name__ == "__main__":
    main()
