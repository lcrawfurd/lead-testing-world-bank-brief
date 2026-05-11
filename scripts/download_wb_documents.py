#!/usr/bin/env python3
"""
Download World Bank safeguards / appraisal documents for a list of projects.

Uses the WB Documents & Reports (WDS) API:
    https://search.worldbank.org/api/v3/wds

The portfolio-wide expansion of the lead-testing audit needs one directory
of PDFs per project. The WDS API returns *everything* for each project
(165+ docs, mostly procurement plans and audit memos) so we filter to the
document types that matter for the audit — Project Appraisal Documents,
Environmental Assessments, ESSAs, ESCPs, ESMFs, resettlement plans, SEPs
and related safeguards docs.

Usage
-----
# Download docs for the 12 projects already in the blog
python3 download_wb_documents.py --projects P170734,P178389,P169342,P179039,P179192,P163732,P151224,P176619,P164345,P163782,P164186,P178954 --out ./docs-expanded

# Download from a CSV (expects a Project_ID column)
python3 download_wb_documents.py --from-csv world_bank_water_projects_rebuilt.csv --out ./docs-expanded

# Limit to first 5 projects (useful for smoke-testing)
python3 download_wb_documents.py --from-csv world_bank_water_projects_rebuilt.csv --out ./docs-expanded --limit 5

# Dry run — print the plan, download nothing
python3 download_wb_documents.py --from-csv world_bank_water_projects_rebuilt.csv --out ./docs-expanded --dry-run
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent.parent

WDS_API = "https://search.worldbank.org/api/v3/wds"
TIMEOUT = 120

# ---------------------------------------------------------------------------
# Document-type filter.
# WDS's `docty` is a fairly noisy free-text field. These are the values we
# want to keep (exact match, case-insensitive). See
# https://documents.worldbank.org for the canonical list.
# ---------------------------------------------------------------------------
KEEP_DOCTY_EXACT = {
    # Appraisal-stage documents
    "project appraisal document",
    "project paper",
    "program appraisal document",
    "program document",
    "program-for-results appraisal document",
    "project information document",
    "program information document",
    # Environmental and social safeguards
    "environmental assessment",
    "environmental impact assessment",
    "environmental and social impact assessment",
    "environmental and social management framework",
    "environmental and social management plan",
    "environmental and social commitment plan",
    "environmental and social review summary",
    "program-for-results environmental and social systems assessment",
    "environmental and social systems assessment",
    "environmental action plan",
    "environmental mitigation plan",
    "environmental monitoring report",
    # Resettlement / social
    "resettlement plan",
    "resettlement action plan",
    "resettlement policy framework",
    "resettlement framework",
    "indigenous peoples plan",
    "indigenous peoples planning framework",
    "stakeholder engagement plan",
    "labor management procedures",
    "social assessment",
    "social impact assessment",
}

# Fallback substring filter for edge cases where docty is formatted oddly
KEEP_DOCTY_SUBSTRING = [
    "environmental and social",
    "environmental assessment",
    "environmental impact",
    "project appraisal",
    "resettlement",
    "indigenous people",
    "stakeholder engagement",
]


def is_safeguards_doc(docty: str) -> bool:
    if not docty:
        return False
    lower = docty.strip().lower()
    if lower in KEEP_DOCTY_EXACT:
        return True
    return any(sub in lower for sub in KEEP_DOCTY_SUBSTRING)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def http_get(url: str, *, params=None, retries: int = 5, stream: bool = False):
    """GET with exponential backoff. Raises on final failure."""
    delay = 1.0
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT, stream=stream)
            if r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code}")
            if r.status_code == 429:
                # Rate limited — wait longer
                ra = int(r.headers.get("Retry-After", "5"))
                time.sleep(ra)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last_exc = e
            if attempt == retries - 1:
                break
            print(f"    retry {attempt+1}/{retries} after {delay:.1f}s: {e}",
                  file=sys.stderr)
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
    raise last_exc  # type: ignore[misc]


def list_project_documents(project_id: str) -> list[dict]:
    r = http_get(WDS_API, params={
        "format": "json",
        "rows": 1000,
        "projectid": project_id,
    })
    data = r.json()
    docs = data.get("documents") or {}
    return list(docs.values())


# ---------------------------------------------------------------------------
# Selection / dedup
# ---------------------------------------------------------------------------

def dedup_docs(docs: list[dict]) -> list[dict]:
    """
    WDS returns the same file multiple times under different docty
    classifications. Collapse to one entry per pdfurl (the canonical
    download). Keep the entry with the most informative docty string
    (longest, in practice).
    """
    by_url: dict[str, dict] = {}
    for d in docs:
        url = d.get("pdfurl")
        if not url:
            continue
        current = by_url.get(url)
        if current is None:
            by_url[url] = d
            continue
        # Prefer English language over others, then longer docty string
        def score(x):
            lang_ok = (x.get("lang") or "").lower().startswith("english")
            return (lang_ok, len(x.get("docty") or ""))
        if score(d) > score(current):
            by_url[url] = d
    return list(by_url.values())


def prefer_english(docs: list[dict]) -> list[dict]:
    """
    Within a set of documents grouped by `chronical_docm_id`, prefer the
    English version. If no English is present, keep whatever is there.
    """
    by_chron: dict[str, list[dict]] = {}
    standalone: list[dict] = []
    for d in docs:
        ch = d.get("chronical_docm_id")
        if ch:
            by_chron.setdefault(ch, []).append(d)
        else:
            standalone.append(d)
    out = list(standalone)
    for ch, group in by_chron.items():
        english = [d for d in group if (d.get("lang") or "").lower().startswith("english")]
        if english:
            english.sort(key=lambda d: d.get("docdt", ""), reverse=True)
            out.append(english[0])
        else:
            group.sort(key=lambda d: d.get("docdt", ""), reverse=True)
            out.append(group[0])
    return out


def classify_doctype_short(docty: str) -> str:
    """Collapse the verbose docty into a short slug for filenames."""
    if not docty:
        return "misc"
    lower = docty.lower()
    mapping = [
        ("project appraisal document",       "PAD"),
        ("program appraisal document",       "PAD"),
        ("program-for-results appraisal",    "PAD"),
        ("project paper",                    "ProjectPaper"),
        ("program document",                 "PAD"),
        ("project information document",     "PID"),
        ("program information document",     "PID"),
        ("environmental and social systems assessment", "ESSA"),
        ("program-for-results environmental and social systems assessment", "ESSA"),
        ("environmental and social impact assessment",  "ESIA"),
        ("environmental and social management framework", "ESMF"),
        ("environmental and social management plan",    "ESMP"),
        ("environmental and social commitment plan",    "ESCP"),
        ("environmental and social review summary",     "ESRS"),
        ("environmental assessment",         "EA"),
        ("environmental impact assessment",  "EIA"),
        ("environmental action plan",        "EAP"),
        ("environmental monitoring report",  "EMR"),
        ("resettlement policy framework",    "RPF"),
        ("resettlement framework",           "RF"),
        ("resettlement action plan",         "RAP"),
        ("resettlement plan",                "RP"),
        ("indigenous peoples planning framework", "IPPF"),
        ("indigenous peoples plan",          "IPP"),
        ("stakeholder engagement plan",      "SEP"),
        ("labor management procedures",      "LMP"),
        ("social impact assessment",         "SIA"),
        ("social assessment",                "SA"),
    ]
    for needle, slug in mapping:
        if needle in lower:
            return slug
    # Fallback: strip non-alnum
    return re.sub(r"[^A-Za-z0-9]+", "", docty)[:20] or "misc"


def safe_filename(project_id: str, country: str, doctype_short: str,
                  report_nb: str, doc_date: str, guid: str) -> str:
    country = re.sub(r"[^A-Za-z0-9]+", "", country or "")[:30] or "Unknown"
    report_nb = re.sub(r"[^A-Za-z0-9._-]+", "_", report_nb or "")[:40]
    date = (doc_date or "")[:10]
    # Keep a short guid tail to guarantee uniqueness across repeated doctypes
    tail = re.sub(r"[^A-Za-z0-9]+", "", guid or "")[:6]
    parts = [project_id, country, doctype_short]
    if date:
        parts.append(date)
    if report_nb:
        parts.append(report_nb)
    if tail:
        parts.append(tail)
    return "_".join(parts) + ".pdf"


def download_pdf(url: str, dest: Path) -> tuple[bool, int]:
    try:
        r = http_get(url, stream=True)
    except Exception as e:
        print(f"    ! download failed: {e}", file=sys.stderr)
        return False, 0
    size = 0
    tmp = dest.with_suffix(".pdf.part")
    with tmp.open("wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 15):
            if chunk:
                f.write(chunk)
                size += len(chunk)
    tmp.rename(dest)
    return True, size


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_project_ids(args) -> list[tuple[str, str]]:
    """Return a list of (project_id, country_hint)."""
    if args.projects:
        ids = [p.strip() for p in args.projects.split(",") if p.strip()]
        return [(pid, "") for pid in ids]
    if args.from_csv:
        rows = []
        with open(args.from_csv) as f:
            reader = csv.DictReader(f)
            for row in reader:
                pid = row.get("Project_ID") or row.get("project_id") or row.get("id")
                country = row.get("Country") or row.get("country") or ""
                if pid:
                    rows.append((pid.strip(), country.strip()))
        if args.limit:
            rows = rows[: args.limit]
        return rows
    print("ERROR: pass --projects or --from-csv", file=sys.stderr)
    sys.exit(2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--projects", help="Comma-separated project IDs")
    src.add_argument("--from-csv",
                     help="CSV with a Project_ID (or project_id / id) column")
    ap.add_argument("--out", default=str(ROOT / "docs-expanded"),
                    help="Destination folder for downloaded PDFs")
    ap.add_argument("--manifest", default=None,
                    help="Manifest CSV path (default: <out>/_manifest.csv)")
    ap.add_argument("--limit", type=int, default=0,
                    help="Only process the first N projects from --from-csv")
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="Seconds to sleep between document downloads")
    ap.add_argument("--non-english-ok", action="store_true",
                    help="Also keep non-English document versions when no "
                         "English is available")
    ap.add_argument("--dry-run", action="store_true",
                    help="List what would be downloaded, do not fetch PDFs")
    args = ap.parse_args()

    projects = load_project_ids(args)
    if not projects:
        print("No projects to process.", file=sys.stderr)
        return 0

    out_dir = Path(args.out)
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = Path(args.manifest or (out_dir / "_manifest.csv"))

    # Open manifest in append-ish mode: if file exists, keep existing rows and
    # record already-seen (project_id, guid) to skip.
    seen: set[tuple[str, str]] = set()
    manifest_rows: list[dict] = []
    if manifest_path.exists() and not args.dry_run:
        with manifest_path.open() as f:
            for row in csv.DictReader(f):
                manifest_rows.append(row)
                seen.add((row.get("project_id",""), row.get("guid","")))
        print(f"Loaded {len(manifest_rows)} existing manifest rows "
              f"(will skip already-downloaded docs)", file=sys.stderr)

    total_downloaded = 0
    total_skipped = 0
    total_failed = 0

    for pid, country_hint in projects:
        print(f"\n=== {pid} ({country_hint or '?'}) ===", file=sys.stderr)
        try:
            docs = list_project_documents(pid)
        except Exception as e:
            print(f"  ! list failed: {e}", file=sys.stderr)
            continue

        kept = [d for d in docs if is_safeguards_doc(d.get("docty", ""))]
        kept = dedup_docs(kept)
        if not args.non_english_ok:
            kept = prefer_english(kept)

        print(f"  {len(docs)} total docs → {len(kept)} safeguards docs",
              file=sys.stderr)

        for d in kept:
            guid = d.get("guid") or d.get("id") or ""
            if (pid, guid) in seen:
                total_skipped += 1
                continue

            docty = d.get("docty", "")
            doctype_short = classify_doctype_short(docty)
            pdf_url = d.get("pdfurl")
            if not pdf_url:
                print(f"    . no pdfurl for {guid} ({docty})", file=sys.stderr)
                continue

            country = country_hint or d.get("count", "")
            fname = safe_filename(
                pid, country, doctype_short,
                d.get("repnb", ""), d.get("docdt", ""), guid,
            )
            dest = out_dir / fname

            print(f"  → {fname}  [{docty}, {d.get('lang','?')}]", file=sys.stderr)

            if args.dry_run or dest.exists():
                if dest.exists():
                    total_skipped += 1
                    print("     (already present, skipping)", file=sys.stderr)
                row_status = "present" if dest.exists() else "planned"
                size = dest.stat().st_size if dest.exists() else 0
            else:
                ok, size = download_pdf(pdf_url, dest)
                if ok:
                    total_downloaded += 1
                    row_status = "downloaded"
                else:
                    total_failed += 1
                    row_status = "failed"
                time.sleep(args.sleep)

            manifest_rows.append({
                "project_id": pid,
                "country": country,
                "docty": docty,
                "doctype_short": doctype_short,
                "lang": d.get("lang", ""),
                "docdt": (d.get("docdt") or "")[:10],
                "report_nb": d.get("repnb", ""),
                "guid": guid,
                "pdfurl": pdf_url,
                "filename": fname,
                "size_bytes": size,
                "status": row_status,
            })
            seen.add((pid, guid))

    if not args.dry_run:
        fieldnames = ["project_id", "country", "docty", "doctype_short",
                      "lang", "docdt", "report_nb", "guid",
                      "pdfurl", "filename", "size_bytes", "status"]
        with manifest_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(manifest_rows)
        print(f"\nWrote manifest: {manifest_path}", file=sys.stderr)

    print(f"\nSummary: downloaded={total_downloaded}  "
          f"skipped/already-present={total_skipped}  failed={total_failed}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
