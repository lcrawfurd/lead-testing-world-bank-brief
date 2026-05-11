#!/usr/bin/env python3
"""
Portfolio-wide summariser.

Takes the outputs of:
  - fetch_wb_projects.py       → world_bank_water_projects_rebuilt.csv
  - search_pdfs_for_lead.py    → lead_search_results.csv
  - extract_parameter_tables.py → parameter_tables.csv
  - download_wb_documents.py    → docs-expanded/_manifest.csv

and emits:
  - portfolio_audit.csv        — one row per project with the audit verdict
  - portfolio_audit.md         — readable summary with top-line stats

Verdict per project (drinking-water lead testing):
  "confirmed"     — Lead appears in a parameter table classified as drinking-water
  "effluent-only" — Lead appears only in effluent / discharge tables
  "baseline-only" — Lead appears only in groundwater / ambient baseline tables
  "mentioned"     — Lead mentioned in narrative but not in any structured table
  "absent"        — No Lead mentioned in any safeguards doc
  "no-docs"       — No safeguards documents downloaded for the project

Usage:
    python3 summarize_portfolio.py \
        --projects world_bank_water_projects_rebuilt.csv \
        --tables parameter_tables.csv \
        --keywords lead_search_results.csv \
        --manifest docs-expanded/_manifest.csv \
        --out-csv portfolio_audit.csv \
        --out-md  portfolio_audit.md
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return list(csv.DictReader(f))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--projects",
        default=str(root / "outputs/universe/world_bank_water_projects.csv"))
    ap.add_argument("--tables",
        default=str(root / "outputs/tables/parameter_tables.csv"))
    ap.add_argument("--keywords",
        default=str(root / "outputs/search/lead_search.csv"))
    ap.add_argument("--manifest",
        default=str(root / "docs-expanded/_manifest.csv"))
    ap.add_argument("--out-csv",
        default=str(root / "outputs/audit/portfolio_audit.csv"))
    ap.add_argument("--out-md",
        default=str(root / "outputs/audit/portfolio_audit.md"))
    args = ap.parse_args()

    projects = load_csv(Path(args.projects))
    tables   = load_csv(Path(args.tables))
    keywords = load_csv(Path(args.keywords))
    manifest = load_csv(Path(args.manifest))

    # --- index manifest: project -> list of filenames
    manifest_by_pid = defaultdict(list)
    for row in manifest:
        pid = row.get("project_id")
        if pid and row.get("status") in ("downloaded", "present"):
            manifest_by_pid[pid].append(row)

    # --- index parameter_tables.csv: project -> list of {pdf, page, class, params}
    tables_by_pid = defaultdict(list)
    for row in tables:
        pid = row.get("project_id")
        if pid:
            tables_by_pid[pid].append(row)

    # --- index keyword-search: project -> {lead_metal_hits, ...}
    keywords_by_pid = {row.get("Project_ID"): row for row in keywords}

    # --- verdict per project
    audit_rows = []
    totals = defaultdict(int)

    for p in projects:
        pid = p.get("Project_ID") or p.get("id")
        country = p.get("Country") or ""
        name = p.get("Project_Name") or ""
        commitment = int(float(p.get("Total_Commitment_USD") or 0))

        docs = manifest_by_pid.get(pid, [])
        table_pages = tables_by_pid.get(pid, [])
        kw = keywords_by_pid.get(pid) or {}

        lead_in_tables = [t for t in table_pages
                          if (t.get("parameter") or "").lower() == "lead"]
        kw_lead_hits = int(kw.get("Lead_Metal_Hits") or 0)

        # A "real" lead row has a numeric mg/L value — not a narrative mention,
        # not a regulation code like "03:2023/BTNMT" parsed as a value, not a
        # soil mg/kg measurement.
        def is_real_water_row(t: dict) -> bool:
            unit = (t.get("unit") or "").lower()
            value = (t.get("value") or "").strip()
            raw = (t.get("raw_line") or "").lower()
            # Exclude regulation-code values (colons) and soil (mg/kg)
            if ":" in value or "mg/kg" in raw:
                return False
            if "[mentioned" in raw:   # placeholder row, not a real parse
                return False
            return unit in {"mg/l", "mg / l", "µg/l", "ug/l"}

        real_lead_rows = [t for t in lead_in_tables if is_real_water_row(t)]

        # Classify lead-in-table contexts using REAL rows only
        table_classes: set[str] = set()
        for t in real_lead_rows:
            cls = (t.get("classification") or "unclassified").lower()
            for c in cls.split(";"):
                c = c.strip()
                if c:
                    table_classes.add(c)

        drinking_only = table_classes & {"drinking"}
        effluent_only = table_classes <= {"effluent", "surface", "discharge", "wastewater"}
        baseline_any  = table_classes & {"baseline", "groundwater", "ambient"}

        # "no-docs" only if we literally have nothing (no manifest, no keyword
        # scan, no table extraction) for this project. The keyword/table CSVs
        # carry their own evidence even if manifest is empty.
        has_any_data = bool(docs) or kw or table_pages
        if not has_any_data:
            verdict = "no-docs"
        elif real_lead_rows and drinking_only and not baseline_any and not effluent_only:
            verdict = "confirmed"          # genuine drinking-water Lead row
        elif real_lead_rows and drinking_only and baseline_any:
            verdict = "baseline-drinking"  # baseline test compared to drinking guidelines
        elif real_lead_rows and effluent_only:
            verdict = "effluent-only"
        elif real_lead_rows and baseline_any:
            verdict = "baseline-only"
        elif real_lead_rows:
            verdict = "table-unclassified"
        elif lead_in_tables or kw_lead_hits > 0:
            verdict = "mentioned"
        else:
            verdict = "absent"

        totals[verdict] += 1
        totals["_usd"] += commitment

        audit_rows.append({
            "project_id": pid,
            "country": country,
            "project_name": name,
            "commitment_usd": commitment,
            "n_docs_scanned": len(docs),
            "lead_metal_keyword_hits": kw_lead_hits,
            "lead_rows_in_tables": len(lead_in_tables),
            "real_lead_water_rows": len(real_lead_rows),
            "lead_table_classes": ";".join(sorted(table_classes)),
            "verdict": verdict,
        })

    # Sort by commitment desc
    audit_rows.sort(key=lambda r: r["commitment_usd"], reverse=True)

    # ---------- CSV
    out_csv = Path(args.out_csv)
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(audit_rows[0].keys()) if audit_rows else [])
        w.writeheader()
        w.writerows(audit_rows)

    # ---------- Markdown
    out_md = Path(args.out_md)
    with out_md.open("w") as f:
        f.write("# Portfolio Audit — Lead Testing in WB Water Projects\n\n")
        f.write(f"Total projects: **{len(audit_rows)}**   |   ")
        f.write(f"Total commitment: **${totals['_usd']/1e9:,.1f} B**\n\n")
        f.write("## Verdict distribution\n\n")
        f.write("| Verdict | N projects | $ B |\n|---|---:|---:|\n")
        usd_by_verdict = defaultdict(int)
        n_by_verdict = defaultdict(int)
        for r in audit_rows:
            usd_by_verdict[r["verdict"]] += r["commitment_usd"]
            n_by_verdict[r["verdict"]] += 1
        for v in ["confirmed", "baseline-drinking", "baseline-only",
                  "effluent-only", "table-unclassified",
                  "mentioned", "absent", "no-docs"]:
            n = n_by_verdict.get(v, 0)
            usd = usd_by_verdict.get(v, 0)
            if n:
                f.write(f"| {v} | {n} | {usd/1e9:,.2f} |\n")

        f.write("\n## Per-project details (sorted by commitment)\n\n")
        f.write("| Project | Country | $M | Docs | KW hits | Lead rows | Classes | Verdict |\n")
        f.write("|---|---|---:|---:|---:|---:|---|---|\n")
        for r in audit_rows:
            f.write(f"| {r['project_id']} | {r['country']} | "
                    f"{r['commitment_usd']/1e6:,.0f} | "
                    f"{r['n_docs_scanned']} | "
                    f"{r['lead_metal_keyword_hits']} | "
                    f"{r['lead_rows_in_tables']} | "
                    f"{r['lead_table_classes'] or '—'} | "
                    f"**{r['verdict']}** |\n")

    print(f"Wrote {out_csv}")
    print(f"Wrote {out_md}")
    print(f"\nTotals: {dict((k,v) for k,v in totals.items() if not k.startswith('_'))}")
    print(f"Total commitment: ${totals['_usd']/1e9:,.2f} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
