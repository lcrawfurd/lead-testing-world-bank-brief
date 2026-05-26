#!/usr/bin/env python3
"""
Fetch active World Bank water-supply projects from the WB Projects API.

Reproduces (as closely as possible) the universe behind the blog claim of
"151 active water supply projects worth approximately $26 billion", and
writes a CSV comparable to world_bank_water_projects.csv.

API docs: https://search.worldbank.org/api/v3/projects

Filter field notes (discovered by probing the API):
  projectstatusdisplay_exact  -- use this for status (NOT status or status_exact)
  sectorcode                  -- accepts a single code per call (WWC, WWA, ...)

Sector codes:
  WWC = Water Supply (drinking water — the canonical code for our work)
  WWA = Sanitation (sewerage, wastewater — adjacent but distinct)
  WWW = Water Resources (dams, flood/drought, irrigation — NOT drinking water)
  WWF = Public Administration - Water / Sanitation / Solid Waste

Modes:
  default                     -> Active + WWC only (~65 projects)
                                 The drinking-water-supply universe — strictest
                                 defensible filter for a piece about lead in
                                 drinking water.
  --include-sanitation        -> WWC + WWA. Adds sanitation projects, matching
                                 the WB's own "water supply portfolio"
                                 definition (~95 projects).
  --include-water-resources   -> WWC + WWA + WWW. Adds dams, flood, irrigation
                                 (~140 projects). NOT recommended for
                                 drinking-water work.
  --widest                    -> also adds WWF (public admin).

`--broad` is retained as an alias of `--include-water-resources` for
backward compatibility with earlier blog drafts.

Usage:
  python3 fetch_wb_projects.py                          # WWC only (default)
  python3 fetch_wb_projects.py --include-sanitation     # WWC + WWA
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "outputs" / "universe"

API_URL = "https://search.worldbank.org/api/v3/projects"
ROWS_PER_PAGE = 200

FIELDS = [
    "id",
    "project_name",
    "countryshortname",
    "boardapprovaldate",
    "projectstatusdisplay",
    "status",
    "totalcommamt",
    "totalamt",
    "curr_ibrd_commitment",
    "curr_ida_commitment",
    "grantamt",
    "sectorcode",
    "major_sector_code",
]

WATER_SUPPLY = "WWC"
SANITATION   = "WWA"
WATER_RES    = "WWW"
WATER_PUBADM = "WWF"


def fetch_page(sector_code: str, offset: int, active_only: bool, retries: int = 4) -> dict:
    params = {
        "format": "json",
        "rows": ROWS_PER_PAGE,
        "os": offset,
        "fl": ",".join(FIELDS),
        "sectorcode": sector_code,
    }
    if active_only:
        params["projectstatusdisplay_exact"] = "Active"

    delay = 1.0
    for attempt in range(retries):
        try:
            r = requests.get(API_URL, params=params, timeout=60)
            if r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code} server error")
            r.raise_for_status()
            # Some server errors return non-JSON text
            return r.json()
        except (requests.RequestException, ValueError) as e:
            if attempt == retries - 1:
                raise
            print(f"  retry {attempt+1}/{retries} after {delay:.1f}s: {e}",
                  file=sys.stderr)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")


def iter_projects(sector_code: str, active_only: bool):
    offset = 0
    while True:
        payload = fetch_page(sector_code, offset, active_only)
        total = int(payload.get("total", 0))
        projects = payload.get("projects") or {}
        if not projects:
            return
        for _, rec in projects.items():
            yield rec
        offset += ROWS_PER_PAGE
        if offset >= total:
            return
        time.sleep(0.3)


def sector_codes(rec: dict) -> set[str]:
    raw = rec.get("sectorcode") or ""
    return {c.strip() for c in raw.split(",") if c.strip()}


def commitment_usd(rec: dict) -> float:
    """Pick the most meaningful single-figure total commitment."""
    for key in ("totalcommamt", "totalamt"):
        v = rec.get(key)
        if v not in (None, "", "0"):
            try:
                return float(v)
            except ValueError:
                pass
    total = 0.0
    for key in ("curr_ibrd_commitment", "curr_ida_commitment", "grantamt"):
        try:
            total += float(rec.get(key) or 0)
        except ValueError:
            pass
    return total


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--out",
                    default=str(OUT_DIR / "world_bank_water_projects.csv"))
    ap.add_argument("--include-sanitation", action="store_true",
                    help="Add WWA (Sanitation) to the universe. Matches the "
                         "WB's own 'water supply portfolio' definition.")
    ap.add_argument("--include-water-resources", action="store_true",
                    help="Add WWA and WWW (Water Resources — dams, flood, "
                         "irrigation). NOT recommended for drinking-water work.")
    ap.add_argument("--broad", action="store_true",
                    help="DEPRECATED alias for --include-water-resources, "
                         "kept for backward compatibility.")
    ap.add_argument("--widest", action="store_true",
                    help="WWC + WWA + WWW + WWF (largest universe).")
    ap.add_argument("--all-status", action="store_true",
                    help="Include projects of any status (Closed / Pipeline / Dropped)")
    ap.add_argument("--include-ids",
                    default="",
                    help="Comma-separated list of additional project IDs to "
                         "include (looked up by qterm). Use this to add "
                         "projects with legacy sector codes that the WW* "
                         "queries miss.")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()

    # Default = WWC only = strict drinking-water-supply universe.
    # This is the tightest defensible filter for a piece about lead in
    # drinking water — only projects whose primary work is delivering
    # water supply. Sanitation projects (WWA) are adjacent and can be
    # added via --include-sanitation. Water Resources (WWW) covers dams,
    # flood, irrigation and is irrelevant for drinking water — opt-in via
    # --include-water-resources.
    if args.widest:
        target_sectors = [WATER_SUPPLY, SANITATION, WATER_RES, WATER_PUBADM]
    elif args.include_water_resources or args.broad:
        target_sectors = [WATER_SUPPLY, SANITATION, WATER_RES]
    elif args.include_sanitation:
        target_sectors = [WATER_SUPPLY, SANITATION]
    else:
        target_sectors = [WATER_SUPPLY]

    active_only = not args.all_status
    print(f"Sectors: {target_sectors}   active_only={active_only}",
          file=sys.stderr)

    # Union by project id across sector queries
    seen: dict[str, dict] = {}
    for code in target_sectors:
        n_before = len(seen)
        for rec in iter_projects(code, active_only):
            pid = rec.get("id")
            if pid and pid not in seen:
                seen[pid] = rec
        print(f"  after sector {code}: {len(seen)} unique projects "
              f"(+{len(seen) - n_before})", file=sys.stderr)

    # Add manually-included project IDs (typically legacy-sector-coded
    # projects that the WW* queries don't return).
    extra_ids = [pid.strip() for pid in args.include_ids.split(",") if pid.strip()]
    n_added_manual = 0
    failed = []
    for pid in extra_ids:
        if pid in seen:
            continue
        rec = None
        delay = 1.0
        for attempt in range(5):
            try:
                r = requests.get(API_URL, params={
                    "format": "json", "rows": 1, "id": pid,
                    "fl": ",".join(FIELDS),
                }, timeout=30)
                if r.status_code == 200 and r.text.strip():
                    rec = (r.json().get("projects") or {}).get(pid)
                    if rec:
                        break
                # 5xx or empty body → retry
            except (requests.RequestException, ValueError):
                pass
            time.sleep(delay)
            delay = min(delay * 2, 30.0)

        if rec:
            seen[pid] = rec
            n_added_manual += 1
        else:
            failed.append(pid)
        time.sleep(0.2)

    if extra_ids:
        print(f"  manual additions: {n_added_manual}/{len(extra_ids)} "
              f"projects added", file=sys.stderr)
        if failed:
            print(f"  ! manual lookup ultimately failed for: {failed}",
                  file=sys.stderr)

    rows = list(seen.values())
    rows.sort(key=commitment_usd, reverse=True)

    out_path = Path(args.out)
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Project_ID", "Project_Name", "Country", "Approval_Date",
                    "Status", "Total_Commitment_USD", "Sector_Codes"])
        for rec in rows:
            w.writerow([
                rec.get("id", ""),
                rec.get("project_name", ""),
                rec.get("countryshortname", ""),
                (rec.get("boardapprovaldate") or "")[:10],
                rec.get("projectstatusdisplay") or rec.get("status", ""),
                int(commitment_usd(rec)),
                ",".join(sorted(sector_codes(rec))),
            ])
    print(f"\nWrote {out_path} ({len(rows)} projects)", file=sys.stderr)

    total_usd = sum(commitment_usd(r) for r in rows)
    print(f"Total commitment: ${total_usd/1e9:,.2f} B")

    print(f"\nTop {args.top} by commitment:")
    for rec in rows[:args.top]:
        amt = commitment_usd(rec)
        print(f"  {rec.get('id','?'):10s} {rec.get('countryshortname','?'):25s} "
              f"${amt/1e6:>7,.0f} M  {rec.get('project_name','')[:60]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
