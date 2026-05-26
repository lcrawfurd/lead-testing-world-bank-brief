#!/usr/bin/env python3
"""
Search World Bank project PDFs for mentions of lead (the metal) and other
water-quality parameters. Produces the evidence table that sits behind the
blog post: for each project, does any of its documents reference lead /
Pb / heavy metals, and which water-quality parameters are named?

Expects source-documents/ to contain PDFs named like:
    P170734_Nigeria_PAD.pdf
    P170734_Nigeria_ESSA.pdf
    ...
i.e. each filename starts with the WB project ID (P######).

Requires the `pdftotext` binary (poppler). Install with:
    brew install poppler

Usage:
    python3 search_pdfs_for_lead.py                 # write CSV + TXT report
    python3 search_pdfs_for_lead.py --show-snippets # also print snippets
"""

from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs-expanded"
OUT_DIR = ROOT / "outputs" / "search"

# Terms we count. Each entry: (label, regex). Regex is applied to
# extracted text with re.IGNORECASE and \b word boundaries where useful.
# For "lead" we deliberately DO NOT use a plain \blead\b — too many false
# positives ("will lead to", "leads implementation"). Instead we require
# chemical/material context nearby.
CONTEXT_WINDOW = 120  # chars either side for snippets

# Positive lead-as-metal patterns. Each matches a phrase that almost
# unambiguously refers to lead the element.
LEAD_METAL_PATTERNS = [
    r"\blead\s*\(\s*Pb\s*\)",                         # "lead (Pb)"
    r"\bPb\b(?!\w)",                                  # standalone Pb
    r"\blead\s+(?:contamination|poisoning|exposure|toxicity|level|concentration|content)s?\b",
    r"\blead[- ]free\b",
    r"\blead[- ]based\b",
    r"\blead\s+pipes?\b",
    r"\blead\s+solder\b",
    r"\blead\s+stabili[sz]ers?\b",
    r"\blead\s+in\s+(?:water|paint|drinking)\b",
    r"\blead\s+acid\b",                               # often wastewater / batteries
    r"\blead\s+and\s+(?:copper|arsenic|mercury|cadmium|zinc)\b",
    r"\b(?:copper|arsenic|mercury|cadmium|zinc)\s+and\s+lead\b",
    r"\bheavy\s+metals?\b",                           # generic heavy metals
    r"\bmg/L\b.*\blead\b",                            # numeric limit
    r"\blead\b.*\bmg/L\b",
]

LEAD_RE = re.compile("|".join(f"(?:{p})" for p in LEAD_METAL_PATTERNS), re.IGNORECASE)

# Per-parameter counts (water-quality parameters named in the document).
PARAM_PATTERNS = {
    "arsenic":   r"\barsenic\b",
    "fluoride":  r"\bfluorid(?:e|es)\b",
    "nitrate":   r"\bnitrat(?:e|es)\b",
    "manganese": r"\bmangan(?:ese|eses)\b",
    "iron":      r"\biron\b",
    "chlorine":  r"\bchlorin(?:e|ation)\b",
    "coliform":  r"\bcoliforms?\b",
    "E. coli":   r"\bE\.?\s*coli\b",
    "BOD":       r"\bBOD\b",
    "COD":       r"\bCOD\b",
    "turbidity": r"\bturbidity\b",
    "salinity":  r"\bsalinity\b",
    "mercury":   r"\bmercury\b",
    "cadmium":   r"\bcadmium\b",
    "zinc":      r"\bzinc\b",
    "copper":    r"\bcopper\b",
    "microbial": r"\bmicrobial\b",
}
PARAM_RE = {k: re.compile(v, re.IGNORECASE) for k, v in PARAM_PATTERNS.items()}

# Also count the non-metal uses of "lead" so we can report the ratio.
LEAD_ANY_RE = re.compile(r"\blead(?:s|ing|er|ers)?\b", re.IGNORECASE)


PROJECT_NAMES = {
    "P170734": ("Nigeria",      "SURWASH"),
    "P178389": ("DRC",          "PASEA"),
    "P169342": ("Bangladesh",   "RWSSHC"),
    "P179039": ("India",        "Karnataka Rural Water"),
    "P179192": ("Morocco",      "Water Security"),
    "P163732": ("Tanzania",     "SRWSSP"),
    "P151224": ("Angola",       "WSIDP2"),
    "P176619": ("Jordan",       "Water Efficiency"),
    "P164345": ("Burkina Faso", "WSS Program"),
    "P163782": ("Uganda",       "IWMDP"),
    "P164186": ("Benin",        "Rural Water"),
    "P178954": ("Malawi",       "WSP-I"),
}


EXTRACTED_DIR = ROOT / "docs-extracted"


def extract_text(pdf_path: Path) -> str:
    """Return extracted text for a PDF.

    Prefers a pre-extracted .txt file in docs-extracted/ (much faster,
    works without `pdftotext` installed, and lets CI run this script
    against the committed text corpus). Falls back to running
    pdftotext on the PDF if no extracted file exists.
    """
    txt_path = EXTRACTED_DIR / (pdf_path.stem + ".txt")
    if txt_path.exists():
        try:
            return txt_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"  !! reading {txt_path} failed: {e}", file=sys.stderr)
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", "-nopgbrk", str(pdf_path), "-"],
            check=True, capture_output=True, timeout=300,
        )
        return out.stdout.decode("utf-8", errors="replace")
    except subprocess.CalledProcessError as e:
        print(f"  !! pdftotext failed on {pdf_path.name}: {e}", file=sys.stderr)
        return ""
    except subprocess.TimeoutExpired:
        print(f"  !! pdftotext timed out on {pdf_path.name}", file=sys.stderr)
        return ""


def project_id_from_filename(name: str) -> str | None:
    m = re.match(r"(P\d{6})", name)
    return m.group(1) if m else None


def snippet(text: str, start: int, end: int, window: int = CONTEXT_WINDOW) -> str:
    a = max(0, start - window)
    b = min(len(text), end + window)
    s = text[a:b].replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def analyse_document(text: str):
    lead_hits = [(m.start(), m.end(), m.group(0)) for m in LEAD_RE.finditer(text)]
    lead_any = len(LEAD_ANY_RE.findall(text))
    params_found = {
        name: len(rx.findall(text))
        for name, rx in PARAM_RE.items()
    }
    return {
        "lead_metal_hits": lead_hits,
        "lead_any_count": lead_any,
        "params": params_found,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs", default=str(DOCS_DIR),
                    help="Folder containing the PDFs (default: ./source-documents)")
    ap.add_argument("--out-csv",
                    default=str(OUT_DIR / "lead_search.csv"))
    ap.add_argument("--out-report",
                    default=str(OUT_DIR / "lead_search.txt"))
    ap.add_argument("--show-snippets", action="store_true",
                    help="Print lead snippets to stdout as we go")
    args = ap.parse_args()

    docs_dir = Path(args.docs)

    # Prefer the PDF list (works whether or not extracted text exists);
    # fall back to the extracted text list when PDFs aren't present
    # (e.g. on CI, where docs-expanded/ is gitignored). In the fallback
    # path we synthesise PDF paths from the .txt filenames — extract_text
    # routes back to the .txt files anyway.
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

    # project_id -> list of (filename, analysis_result)
    per_project: dict[str, list[tuple[str, dict]]] = defaultdict(list)

    for pdf in pdfs:
        pid = project_id_from_filename(pdf.name) or "UNKNOWN"
        print(f"[{pid}] {pdf.name}", file=sys.stderr)
        text = extract_text(pdf)
        if not text:
            per_project[pid].append((pdf.name, None))
            continue
        result = analyse_document(text)
        per_project[pid].append((pdf.name, {**result, "text": text}))
        if args.show_snippets and result["lead_metal_hits"]:
            for s, e, matched in result["lead_metal_hits"]:
                print(f"    ⤷ match '{matched}': …{snippet(text, s, e)}…")

    # Aggregate per project and write CSV.
    csv_path = Path(args.out_csv)
    report_path = Path(args.out_report)

    with csv_path.open("w", newline="") as f, report_path.open("w") as rep:
        w = csv.writer(f)
        w.writerow([
            "Project_ID", "Country", "Short_Name",
            "N_Documents", "Lead_Metal_Hits", "Heavy_Metals_Mentioned",
            "Lead_Any_Count", "Water_Quality_Parameters_Named",
        ])

        rep.write("LEAD SEARCH — per-project evidence report\n")
        rep.write("=" * 70 + "\n\n")

        for pid in sorted(per_project):
            country, short = PROJECT_NAMES.get(pid, ("?", "?"))
            docs = per_project[pid]
            lead_metal_hits = 0
            lead_any = 0
            heavy_metals = False
            params_union: set[str] = set()
            for name, res in docs:
                if res is None:
                    continue
                lead_metal_hits += len(res["lead_metal_hits"])
                lead_any += res["lead_any_count"]
                for param, n in res["params"].items():
                    if n > 0:
                        params_union.add(param)
                # Any heavy-metals phrase specifically?
                if any("heavy" in m.lower() for _, _, m in res["lead_metal_hits"]):
                    heavy_metals = True

            w.writerow([
                pid, country, short, len(docs),
                lead_metal_hits, "Yes" if heavy_metals else "No",
                lead_any, ", ".join(sorted(params_union)),
            ])

            rep.write(f"{pid}  {country} — {short}\n")
            rep.write(f"  Documents scanned: {len(docs)}\n")
            rep.write(f"  Lead-as-metal matches: {lead_metal_hits}\n")
            rep.write(f"  Generic 'lead/leads/leading' tokens: {lead_any}  "
                      f"(≈ verb or 'leadership' uses)\n")
            rep.write(f"  Water-quality params named: "
                      f"{', '.join(sorted(params_union)) or '(none)'}\n")
            for name, res in docs:
                if res is None:
                    rep.write(f"    - {name}: [pdftotext failed]\n")
                    continue
                hits = res["lead_metal_hits"]
                rep.write(f"    - {name}: {len(hits)} lead-metal hit(s)\n")
                for s, e, matched in hits:
                    rep.write(f"        • '{matched}' … {snippet(res['text'], s, e)} …\n")
            rep.write("\n")

    print(f"\nWrote {csv_path}\nWrote {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
