#!/usr/bin/env python3
"""
Extract water-quality parameter tables from World Bank project PDFs so the
blog's "Water quality parameters named" column is fully auditable.

Strategy
--------
1. Run pdftotext -layout page-by-page on each PDF.
2. Score each page by how likely it is to be a water-quality parameter
   table: count of parameter-name hits + count of unit tokens (mg/l,
   μg/L, NTU, CFU, …) + presence of the words limit/standard/permissible/
   parameter/guideline.
3. Pages above a threshold are saved as candidate tables.
4. Classify each candidate by scanning nearby headings / page text for
   keywords that distinguish:
     - drinking  (drinking water / potable / tap / WHO guideline / WHO GDWQ)
     - effluent  (effluent / discharge / wastewater / sewage)
     - baseline  (baseline / groundwater / ambient / existing contamination)
     - ambient   (surface water / river / receiving water)
     - standard  (national standard / national regulation without context)
   If more than one applies, record all.
5. Parse each line for "<Parameter> <unit> <numeric>" rows.

Outputs
-------
parameter_tables.csv
    project_id, pdf, page, classification, parameter, value, unit, raw_line
parameter_tables_report.txt
    Readable per-project summary: list of (pdf, page, classification,
    parameter hits including whether Lead appears), plus the raw page text
    of each candidate for spot-checking.

Usage
-----
    python3 extract_parameter_tables.py
    python3 extract_parameter_tables.py --min-score 4   # stricter
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs-expanded"
OUT_DIR = ROOT / "outputs" / "tables"

# ---------- vocabulary ------------------------------------------------------

# Canonical parameter names → match patterns. Order matters for display.
PARAMETERS = [
    # Heavy metals
    ("Aluminum",    r"\balumin[ui]?um\b"),
    ("Antimony",    r"\bantimony\b"),
    ("Arsenic",     r"\barsenic\b"),
    ("Barium",      r"\bbarium\b"),
    ("Boron",       r"\bboron\b"),
    ("Cadmium",     r"\bcadmium\b"),
    ("Chromium",    r"\bchromium\b"),
    ("Cobalt",      r"\bcobalt\b"),
    ("Copper",      r"\bcopper\b"),
    ("Iron",        r"\biron\b"),
    ("Lead",        r"\blead\b(?!\s+(?:agenc|implementation|role|author|actor|role))"),
    ("Manganese",   r"\bmanganese\b"),
    ("Mercury",     r"\bmercury\b"),
    ("Nickel",      r"\bnickel\b"),
    ("Selenium",    r"\bselenium\b"),
    ("Silver",      r"\bsilver\b"),
    ("Zinc",        r"\bzinc\b"),
    ("Uranium",     r"\buranium\b"),
    # Nonmetals & ions
    ("Ammonia",     r"\bammonia\b"),
    ("Chloride",    r"\bchloride\b"),
    ("Chlorine",    r"\bchlorine\b|\bresidual\s+chlorine\b"),
    ("Cyanide",     r"\bcyanide\b"),
    ("Fluoride",    r"\bfluoride\b"),
    ("Nitrate",     r"\bnitrate\b"),
    ("Nitrite",     r"\bnitrite\b"),
    ("Phosphate",   r"\bphosphate\b"),
    ("Sulfate",     r"\bsulfate\b|\bsulphate\b"),
    ("Sulfide",     r"\bsulfide\b|\bsulphide\b"),
    # Organics / aggregates
    ("BOD",         r"\bBOD(?:[_\s]?5)?\b"),
    ("COD",         r"\bCOD\b"),
    ("TDS",         r"\bTDS\b|\btotal\s+dissolved\s+solids\b"),
    ("TSS",         r"\bTSS\b|\btotal\s+suspended\s+solids\b"),
    ("Phenol",      r"\bphenol(?:s)?\b"),
    ("Oil_grease",  r"\boil\s+and\s+grease\b"),
    # Physicochemical
    ("pH",          r"(?<![A-Za-z])pH(?![A-Za-z])"),
    ("Turbidity",   r"\bturbidity\b"),
    ("Conductivity", r"\bconductivity\b|\belectrical\s+conductivity\b"),
    ("Color",       r"\bcolou?r\b"),
    ("Temperature", r"\btemperature\b"),
    ("Salinity",    r"\bsalinity\b"),
    # Microbiological
    ("Coliform",    r"\bcoliform(?:s)?\b|\bfa?ecal\s+coliform"),
    ("E.coli",      r"\bE\.?\s*coli\b|\bEscherichia\s+coli\b"),
]
PARAM_RX = {name: re.compile(pat, re.IGNORECASE) for name, pat in PARAMETERS}

UNIT_RX = re.compile(
    r"\b(?:mg\s*/\s*[lL]|µg\s*/\s*[lL]|ug\s*/\s*[lL]|NTU|CFU|MPN|TCU|°C)\b",
    re.IGNORECASE,
)

TABLE_CUE_RX = re.compile(
    r"\b(?:parameter|limit|standard|permissible|guideline|maxim[au]m|threshold)\b",
    re.IGNORECASE,
)

# Classification cues
CLASSIFIERS = [
    ("drinking", re.compile(r"\b(?:drinking\s+water|potable|tap\s+water|consumption|"
                            r"WHO\s+(?:drinking[-\s]?water|guidelin|GDWQ))\b", re.I)),
    ("effluent", re.compile(r"\b(?:effluent|discharge|waste[-\s]?water|sewage|sewer|"
                            r"treated\s+(?:waste)?water)\b", re.I)),
    ("baseline", re.compile(r"\b(?:baseline|existing\s+(?:ground|water).*quality|"
                            r"water\s+quality\s+(?:contamination|issues)|"
                            r"ambient\s+water\s+quality)\b", re.I)),
    ("groundwater", re.compile(r"\b(?:ground[-\s]?water|aquifer|bore[-\s]?hole|well\s+water)\b", re.I)),
    ("surface",  re.compile(r"\b(?:surface\s+water|river|stream|receiving\s+(?:water|body)|lake)\b", re.I)),
]

# ---------- text-extraction helpers ----------------------------------------
#
# Prefer pre-extracted .txt files in docs-extracted/ (produced by
# scripts/extract_text.py) to skip the per-page pdftotext call.
# extract_text.py writes one .txt per PDF with form-feed (\f) characters
# between pages, so we can split on \f to get per-page text.
# Fall back to running pdftotext if no extracted file exists.

EXTRACTED_DIR = ROOT / "docs-extracted"
_page_cache: dict[str, list[str]] = {}


def _get_pages_from_extracted(pdf: Path) -> list[str] | None:
    """Return list of page-strings if a .txt file exists, else None."""
    txt = EXTRACTED_DIR / (pdf.stem + ".txt")
    if not txt.exists():
        return None
    key = str(txt)
    if key in _page_cache:
        return _page_cache[key]
    try:
        text = txt.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # pdftotext default uses form feed (\f) as page separator.
    # A trailing form feed produces an empty final page, drop it.
    pages = text.split("\f")
    if pages and pages[-1] == "":
        pages.pop()
    _page_cache[key] = pages
    return pages


def pdf_num_pages(pdf: Path) -> int:
    """Return number of pages in the PDF."""
    pages = _get_pages_from_extracted(pdf)
    if pages is not None:
        return len(pages)
    try:
        out = subprocess.run(["pdfinfo", str(pdf)], check=True,
                             capture_output=True, timeout=60).stdout.decode()
        for line in out.splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":", 1)[1].strip())
    except Exception as e:
        print(f"  !! pdfinfo failed for {pdf.name}: {e}", file=sys.stderr)
    return 0


def extract_page(pdf: Path, page: int) -> str:
    """Extract one page of text (1-indexed)."""
    pages = _get_pages_from_extracted(pdf)
    if pages is not None:
        if 1 <= page <= len(pages):
            return pages[page - 1]
        return ""
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", "-nopgbrk",
             "-f", str(page), "-l", str(page), str(pdf), "-"],
            check=True, capture_output=True, timeout=60,
        ).stdout.decode("utf-8", errors="replace")
        return out
    except Exception as e:
        print(f"  !! pdftotext failed on {pdf.name} p{page}: {e}", file=sys.stderr)
        return ""

# ---------- scoring --------------------------------------------------------

def score_page(text: str) -> tuple[int, dict[str, int]]:
    """
    Assign a "water-quality table" score based on:
      +1 per distinct parameter hit (capped at 10)
      +1 per 3 unit tokens
      +2 if the page contains any TABLE_CUE word
      +3 if both 'mg/l' and >=3 parameters appear
    Returns (score, per_parameter_count_dict)
    """
    param_counts = {}
    distinct = 0
    for name, rx in PARAM_RX.items():
        n = len(rx.findall(text))
        if n:
            param_counts[name] = n
            distinct += 1
    units = len(UNIT_RX.findall(text))
    cues = 1 if TABLE_CUE_RX.search(text) else 0

    score = min(distinct, 10)
    score += units // 3
    score += 2 * cues
    if units > 0 and distinct >= 3:
        score += 3
    return score, param_counts


def classify(text: str) -> list[str]:
    tags = [tag for tag, rx in CLASSIFIERS if rx.search(text)]
    return tags

# ---------- row parsing ----------------------------------------------------

# A line like:
#    "  29   Lead                   mg/l          0.1"
#    "Lead (as Pb), mg/l, max                  0.05"
#    "Arsenic (as As), mg/l, max               0.05  0.54"
ROW_RX = re.compile(
    r"(?P<param>"
    + "|".join(sorted((pat for _, pat in PARAMETERS), key=len, reverse=True))
    + r")"
    + r"[\s,]*(?:\([^)]{0,30}\))?"                                 # optional "(as Pb)"
    + r"[\s,]*(?P<unit>mg\s*/\s*[lL]|µg\s*/\s*[lL]|ug\s*/\s*[lL]|NTU|CFU|MPN|TCU|°C)?"
    + r"[\s,]*(?:max(?:imum)?|min(?:imum)?|avg|average)?"          # skip qualifier keyword
    + r"[\s,:]+(?P<value>[-<>=]?\s*\d+(?:\.\d+)?(?:\s*[-–to]{1,3}\s*\d+(?:\.\d+)?)?|Nill|N/A)",
    re.IGNORECASE,
)

def parse_rows(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) > 300:
            continue
        # Only try to parse lines that look table-ish: a number + a unit or
        # a known parameter name
        if not UNIT_RX.search(stripped) and not any(rx.search(stripped) for rx in PARAM_RX.values()):
            continue
        m = ROW_RX.search(stripped)
        if not m:
            continue
        # Resolve which canonical parameter name matched
        matched_name = None
        for name, rx in PARAM_RX.items():
            if rx.search(m.group("param")):
                matched_name = name
                break
        if not matched_name:
            continue
        rows.append({
            "parameter": matched_name,
            "value": m.group("value").strip(),
            "unit": (m.group("unit") or "").strip(),
            "raw_line": stripped,
        })
    return rows

# ---------- main driver -----------------------------------------------------

def project_id_from_filename(name: str) -> str | None:
    m = re.match(r"(P\d{6})", name)
    return m.group(1) if m else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs", default=str(DOCS_DIR))
    ap.add_argument("--out-csv",
                    default=str(OUT_DIR / "parameter_tables.csv"))
    ap.add_argument("--out-report",
                    default=str(OUT_DIR / "parameter_tables.txt"))
    ap.add_argument("--min-score", type=int, default=6,
                    help="Minimum page score to flag as a parameter table (default: 6)")
    ap.add_argument("--include-raw", action="store_true",
                    help="Also embed raw page text in the report (big files)")
    args = ap.parse_args()

    docs_dir = Path(args.docs)
    # Prefer PDFs; fall back to synthesising paths from docs-extracted/
    # when PDFs aren't present (CI path — docs-expanded/ is gitignored).
    pdfs = sorted(docs_dir.glob("*.pdf")) if docs_dir.is_dir() else []
    if not pdfs and EXTRACTED_DIR.is_dir():
        pdfs = sorted(docs_dir / (t.stem + ".pdf")
                      for t in EXTRACTED_DIR.glob("*.txt"))
        print(f"No PDFs found in {docs_dir}; using {len(pdfs)} extracted "
              f"text files from {EXTRACTED_DIR}", file=sys.stderr)
    if not pdfs:
        print(f"No PDFs or extracted text found "
              f"(checked {docs_dir} and {EXTRACTED_DIR})", file=sys.stderr)
        return 2

    # Structure:  per_project[pid] = list of candidate dicts
    per_project: dict[str, list[dict]] = {}

    total_candidates = 0

    for pdf in pdfs:
        pid = project_id_from_filename(pdf.name) or "UNKNOWN"
        n_pages = pdf_num_pages(pdf)
        if not n_pages:
            continue
        print(f"[{pid}] {pdf.name} ({n_pages} pages)", file=sys.stderr)
        for page in range(1, n_pages + 1):
            text = extract_page(pdf, page)
            if not text.strip():
                continue
            score, params = score_page(text)
            if score < args.min_score:
                continue
            tags = classify(text)
            rows = parse_rows(text)
            candidate = {
                "pdf": pdf.name,
                "page": page,
                "score": score,
                "classification": tags or ["unclassified"],
                "parameters": params,
                "has_lead": "Lead" in params,
                "rows": rows,
                "text": text if args.include_raw else None,
            }
            per_project.setdefault(pid, []).append(candidate)
            total_candidates += 1

    print(f"\n{total_candidates} candidate parameter-table pages identified",
          file=sys.stderr)

    # ---- CSV ---------------------------------------------------------------
    csv_path = Path(args.out_csv)
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["project_id", "pdf", "page", "classification", "score",
                    "parameter", "value", "unit", "raw_line"])
        for pid, candidates in sorted(per_project.items()):
            for c in candidates:
                cls = ";".join(c["classification"])
                if c["rows"]:
                    for r in c["rows"]:
                        w.writerow([pid, c["pdf"], c["page"], cls, c["score"],
                                    r["parameter"], r["value"], r["unit"], r["raw_line"]])
                else:
                    # Row-less candidate — still record which parameters appeared
                    for param in sorted(c["parameters"]):
                        w.writerow([pid, c["pdf"], c["page"], cls, c["score"],
                                    param, "", "", f"[mentioned, no parsable row]"])

    # ---- human report ------------------------------------------------------
    rep_path = Path(args.out_report)
    with rep_path.open("w") as rep:
        rep.write("PARAMETER-TABLE EXTRACTION — per-project audit\n")
        rep.write("=" * 70 + "\n\n")
        for pid, candidates in sorted(per_project.items()):
            rep.write(f"{pid}  ({len(candidates)} candidate page(s))\n")
            for c in candidates:
                cls = ", ".join(c["classification"])
                lead_flag = "  ← LEAD IN TABLE" if c["has_lead"] else ""
                rep.write(f"  {c['pdf']}  p.{c['page']}  [{cls}]  "
                          f"score={c['score']}  params={len(c['parameters'])}"
                          f"{lead_flag}\n")
                if c["rows"]:
                    for r in c["rows"]:
                        rep.write(f"      {r['parameter']:12s} {r['value']:>10s} "
                                  f"{r['unit']:<8s}  |  {r['raw_line']}\n")
                else:
                    rep.write(f"      (parameters mentioned but no parsable rows) "
                              f"{sorted(c['parameters'])}\n")
            rep.write("\n")

    print(f"Wrote {csv_path}")
    print(f"Wrote {rep_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
