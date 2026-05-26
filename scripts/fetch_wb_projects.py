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

Modes (project counts include the 12 legacy-coded manual additions
in `LEGACY_IDS`, set in the Makefile):

  default                     -> Active + WWC only (~65 from API + 12
                                 manual = ~77-81 projects)
                                 The drinking-water-supply universe — strictest
                                 defensible filter for a piece about lead in
                                 drinking water.
  --include-sanitation        -> WWC + WWA (~80 from API + 12 manual
                                 = ~92-95 projects). Adds sanitation,
                                 matching the WB's own "water supply
                                 portfolio" definition.
  --include-water-resources   -> WWC + WWA + WWW (~130 from API + 12
                                 manual = ~140-145 projects). Adds dams,
                                 flood, irrigation. NOT recommended for
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
    "major_sectors",   # nested structure with per-sector percentages
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


def sector_percent_sum(rec: dict, target_codes: list[str]) -> float:
    """Sum of sector_percent values for any matching sector code.

    Returns 0.0 if no major_sectors data or none of the target codes
    appear with non-zero percent. The API populates sector_percent for
    roughly half of active water projects; the rest report 0% across
    all sectors, which here we treat as "data missing" → weighted
    commitment of 0 for that project.
    """
    total = 0.0
    for major in rec.get("major_sectors", []) or []:
        m = major.get("major_sector", {}) if isinstance(major, dict) else {}
        for s in m.get("sectors", []) or []:
            code = (s.get("sector_code") or "").strip()
            if code in target_codes:
                try:
                    total += float(s.get("sector_percent") or 0)
                except (ValueError, TypeError):
                    pass
    return total


def weighted_commitment_usd(rec: dict, target_codes: list[str]) -> float:
    """Hybrid sector-percent-weighted commitment.

    Two sources of share information per project:
      (a) API's `sector_percent` field — populated for ~half of active
          water projects; reliable where present.
      (b) Project's full set of sector codes — always available.
          The water sectors' share of the total code list is a useful
          structural proxy.

    Strategy:
      - If `sector_percent` is populated for the target codes
        (>0% sums to a real value), use that.
      - Otherwise fall back to (water_codes / total_codes) × full_commitment.

    For a project tagged WWC + four other sector codes with no
    sector_percent populated, this attributes 20% of the commitment
    to water. That's a structural lower bound — assumes equal
    weighting across sectors — but matches reality better than
    either dropping the project (0%) or assuming 100%.

    Reconciliation to the Bank's stated $8.7B (WWC + WWA, sector-
    percent-weighted internally) is documented in README.md.
    """
    pct = sector_percent_sum(rec, target_codes)
    if pct > 0:
        return commitment_usd(rec) * pct / 100.0
    # Fall back to proportional share by sector-code count
    codes = sector_codes(rec)
    if not codes:
        return 0.0
    water_count = sum(1 for c in codes if c in target_codes)
    if water_count == 0:
        return 0.0
    return commitment_usd(rec) * water_count / len(codes)


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
                    "Status", "Total_Commitment_USD",
                    "Water_Sector_Percent",
                    "Weighted_Commitment_USD",
                    "Sector_Codes"])
        for rec in rows:
            full = commitment_usd(rec)
            pct = sector_percent_sum(rec, target_sectors)
            weighted = weighted_commitment_usd(rec, target_sectors)
            w.writerow([
                rec.get("id", ""),
                rec.get("project_name", ""),
                rec.get("countryshortname", ""),
                (rec.get("boardapprovaldate") or "")[:10],
                rec.get("projectstatusdisplay") or rec.get("status", ""),
                int(full),
                round(pct, 1),
                int(weighted),
                ",".join(sorted(sector_codes(rec))),
            ])
    print(f"\nWrote {out_path} ({len(rows)} projects)", file=sys.stderr)

    total_usd = sum(commitment_usd(r) for r in rows)
    total_weighted = sum(weighted_commitment_usd(r, target_sectors) for r in rows)
    n_with_percent = sum(1 for r in rows
                         if sector_percent_sum(r, target_sectors) > 0)
    print(f"Total commitment (unweighted): ${total_usd/1e9:,.2f} B")
    print(f"Total commitment (sector-percent-weighted): "
          f"${total_weighted/1e9:,.2f} B  "
          f"[from {n_with_percent}/{len(rows)} projects with populated "
          f"sector_percent]")

    print(f"\nTop {args.top} by commitment:")
    for rec in rows[:args.top]:
        amt = commitment_usd(rec)
        wt  = weighted_commitment_usd(rec, target_sectors)
        print(f"  {rec.get('id','?'):10s} {rec.get('countryshortname','?'):25s} "
              f"${amt/1e6:>7,.0f} M  (wt: ${wt/1e6:>5,.0f}M)  "
              f"{rec.get('project_name','')[:50]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
