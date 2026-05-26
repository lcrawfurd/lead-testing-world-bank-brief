#!/usr/bin/env python3
"""
Convert every PDF in docs-expanded/ to a UTF-8 text file in
docs-extracted/, using pdftotext -layout. Form-feed page separators
are preserved so per-page processing in extract_parameter_tables.py
keeps working.

Why
---
Storing the extracted text in git lets:
  - the search and tables scripts skip the pdftotext step entirely
    (much faster on second runs);
  - CI verify the downstream pipeline against committed text
    (PDFs themselves are too large to commit);
  - replicators inspect the exact text the audit "saw" without
    needing the 1 GB PDF corpus or a working `pdftotext` binary.

Per-file size is typically 20-150 KB. Across ~900 PDFs the
extracted text totals ~30-50 MB — comfortable for git.

Usage
-----
    python3 scripts/extract_text.py                   # extract any missing
    python3 scripts/extract_text.py --force           # re-extract all
    python3 scripts/extract_text.py --docs docs-expanded --out docs-extracted

Idempotent: skips PDFs whose extracted text already exists unless
--force is passed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOCS = ROOT / "docs-expanded"
DEFAULT_OUT  = ROOT / "docs-extracted"


def extract_one(pdf: Path, out: Path) -> tuple[bool, str]:
    """Run pdftotext on a single PDF. Returns (ok, message)."""
    try:
        # -layout preserves table structure; default keeps page breaks
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf), str(out)],
            check=True, capture_output=True, timeout=300,
        )
        return True, ""
    except subprocess.CalledProcessError as e:
        return False, e.stderr.decode("utf-8", errors="replace")[:200]
    except subprocess.TimeoutExpired:
        return False, "timed out after 5 minutes"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--docs", default=str(DEFAULT_DOCS),
                    help="Folder containing source PDFs (default: docs-expanded)")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="Folder to write extracted .txt files (default: docs-extracted)")
    ap.add_argument("--force", action="store_true",
                    help="Re-extract even if the .txt file already exists")
    args = ap.parse_args()

    docs = Path(args.docs)
    out = Path(args.out)
    if not docs.is_dir():
        print(f"No such folder: {docs}", file=sys.stderr)
        return 2

    out.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(docs.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {docs}", file=sys.stderr)
        return 2

    n_extracted = 0
    n_skipped = 0
    n_failed = 0

    for pdf in pdfs:
        txt = out / (pdf.stem + ".txt")
        if txt.exists() and not args.force:
            n_skipped += 1
            continue
        ok, err = extract_one(pdf, txt)
        if ok:
            n_extracted += 1
            if n_extracted % 50 == 0:
                print(f"  extracted {n_extracted}...", file=sys.stderr)
        else:
            n_failed += 1
            print(f"  ! failed: {pdf.name}  ({err})", file=sys.stderr)

    print(f"\nExtracted: {n_extracted}  skipped (already present): {n_skipped}"
          f"  failed: {n_failed}")
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
