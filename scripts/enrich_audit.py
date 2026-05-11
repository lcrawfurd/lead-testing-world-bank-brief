#!/usr/bin/env python3
"""
Enrich portfolio_audit.csv with WB region + financing-type metadata
(IBRD loan / IDA credit / Grant amounts). Caches API responses so
re-runs are instant and offline-friendly.

Why this script exists
----------------------
The chart in `outputs/audit/projects_by_region.png` reads
`portfolio_audit_with_region.csv`, which extends the basic audit with
two pieces of metadata pulled from the WB Projects API:

  - `region`              — WB region for grouping projects on the map
  - `lending_instrument`  — free-text instrument label (often blank)
  - `ibrd_amount`         — current IBRD commitment (USD)
  - `ida_amount`          — current IDA commitment (USD)
  - `grant_amount`        — grant component (USD)

Six projects come back from the API with `regionname` blank or wrong;
we patch those manually using their country.

The full WB Projects API listing for a single project is expensive
(~1s + retries), so we cache results to a JSON file. Re-running the
script with the cache present is essentially free.

Inputs
------
    outputs/audit/portfolio_audit.csv

Outputs
-------
    outputs/audit/portfolio_audit_with_region.csv
    outputs/audit/_api_cache.json   (transparent cache; safe to delete)
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
AUDIT_DIR = ROOT / "outputs" / "audit"
CACHE = AUDIT_DIR / "_api_cache.json"

API_URL = "https://search.worldbank.org/api/v3/projects"
FIELDS = ["id", "regionname", "countryshortname", "lendinginstr",
          "lndinstr", "curr_ibrd_commitment", "curr_ida_commitment",
          "grantamt", "totalcommamt", "totalamt"]

# Manual region patches for projects the API returns blank/Unknown.
# Country → WB region (matches the long-form region names the API uses
# for every other project, so the chart bins them correctly).
COUNTRY_REGION = {
    "Tanzania":     "Eastern and Southern Africa",
    "Angola":       "Eastern and Southern Africa",
    "Burkina Faso": "Western and Central Africa",
    "Uganda":       "Eastern and Southern Africa",
    "China":        "East Asia and Pacific",
    "Benin":        "Western and Central Africa",
}


def load_cache(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            print(f"  ! cache file unreadable, ignoring: {path}",
                  file=sys.stderr)
    return {}


def save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True))


def api_lookup(pid: str, retries: int = 5) -> dict:
    """Return API record for a single project. Empty dict on failure."""
    delay = 1.0
    params = {"format": "json", "rows": 1, "qterm": pid,
              "fl": ",".join(FIELDS)}
    for attempt in range(retries):
        try:
            r = requests.get(API_URL, params=params, timeout=30)
            if r.status_code != 200 or not r.text.strip():
                raise ValueError(f"HTTP {r.status_code}")
            data = r.json()
            for got_pid, rec in data.get("projects", {}).items():
                if got_pid == pid:
                    return rec
            return {}  # API returned but pid didn't match
        except (requests.RequestException, ValueError) as e:
            if attempt == retries - 1:
                print(f"  ! lookup failed for {pid}: {e}", file=sys.stderr)
                return {}
            time.sleep(delay)
            delay = min(delay * 2, 30)
    return {}


def safe_float_str(x) -> str:
    """Treat empty string / None as '0' for downstream summing."""
    if x in (None, "", "null"):
        return "0"
    return str(x)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in",  dest="audit_in",
                    default=str(AUDIT_DIR / "portfolio_audit.csv"))
    ap.add_argument("--out", dest="audit_out",
                    default=str(AUDIT_DIR / "portfolio_audit_with_region.csv"))
    ap.add_argument("--cache", default=str(CACHE),
                    help="JSON cache of API responses; delete to force refresh")
    ap.add_argument("--no-cache", action="store_true",
                    help="Bypass the cache (always hit the API)")
    ap.add_argument("--sleep", type=float, default=0.2,
                    help="Seconds to sleep between API calls")
    args = ap.parse_args()

    cache = {} if args.no_cache else load_cache(Path(args.cache))
    rows = list(csv.DictReader(open(args.audit_in)))
    if not rows:
        print(f"No rows in {args.audit_in}", file=sys.stderr)
        return 1

    print(f"Enriching {len(rows)} projects "
          f"({sum(1 for r in rows if r['project_id'] in cache)} already in cache)",
          file=sys.stderr)

    n_api = 0
    for r in rows:
        pid = r["project_id"]
        rec = cache.get(pid)
        if rec is None:
            rec = api_lookup(pid)
            cache[pid] = rec
            n_api += 1
            time.sleep(args.sleep)
        # Region: API value, then manual override, then "Unknown"
        region = (rec.get("regionname") or "").strip() or "Unknown"
        if region == "Unknown" and r.get("country") in COUNTRY_REGION:
            region = COUNTRY_REGION[r["country"]]
        r["region"]             = region
        r["lending_instrument"] = (rec.get("lendinginstr") or "").strip()
        r["ibrd_amount"]        = safe_float_str(rec.get("curr_ibrd_commitment"))
        r["ida_amount"]         = safe_float_str(rec.get("curr_ida_commitment"))
        r["grant_amount"]       = safe_float_str(rec.get("grantamt"))

    print(f"  hit API for {n_api} projects, "
          f"{len(rows) - n_api} served from cache", file=sys.stderr)

    if not args.no_cache:
        save_cache(Path(args.cache), cache)

    fieldnames = list(rows[0].keys())
    with open(args.audit_out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader(); w.writerows(rows)

    # Quick stats
    from collections import Counter
    by_region = Counter(r["region"] for r in rows)
    print(f"\nWrote {args.audit_out}")
    print(f"Region distribution:")
    for region, n in by_region.most_common():
        print(f"  {n:3d}  {region}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
