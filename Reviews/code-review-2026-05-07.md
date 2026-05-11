# Code review — `lead-testing-world-bank-brief`

**Date:** 7 May 2026
**Reviewer:** Claude (via `/code-review`)
**Scope:** All Python scripts, README, folder structure, output organisation

## Summary

This is a blog-supporting analysis project, not a journal replication
package, so the standards apply asymmetrically — the headline finding
is in the rendered blog text, not in a regression table. That said, the
code that *produces* the headline numbers is genuinely meant to be
replicable (and even cite-able if the work expands into a brief). On
that bar, the project is in good shape but has three structural gaps
that would make external replication costly: there's no master script,
no pinned dependencies, and several pipeline steps that ran as inline
Python heredocs during the working session never made it into
`scripts/`. The scripts that *are* there are cleanly written, use a
sensible `ROOT = parent.parent` pattern, and have descriptive
docstrings — but the union-of-corpora step that produces the
`*_union.csv` files (which the summariser actually reads) is missing
entirely. A second researcher checking out this folder cold could not
reproduce the headline "145 projects, $30.6B" number from raw API
calls.

---

## Major Issues

(Would prevent clean external replication or break if the underlying
data shifts.)

1. **The CSV-union step is missing from the codebase.** The summariser
   reads `outputs/{search,tables,universe}/*_union.csv` files. Those
   files were produced by a Python heredoc during the session and are
   not in any script. After deletion, re-running `scripts/*.py` would
   produce `lead_search_portfolio.csv`, `parameter_tables_portfolio.csv`,
   and `world_bank_water_projects_rebuilt.csv` — but no `*_union.csv`,
   so `summarize_portfolio.py` would fail.
   **Fix:** add `scripts/union_corpora.py` that does what the heredoc did
   (union the source-documents results with the docs-expanded results,
   union the original 12 with the rebuilt universe, dedupe by primary
   key). Document it as step 4.5 in README.

2. **Region-enrichment step is also missing.** The chart in
   `outputs/audit/projects_by_region.png` reads from
   `portfolio_audit_with_region.csv`, which was produced by an inline
   heredoc that called the WB Projects API for every project to pull
   `regionname` and the IBRD/IDA/grant amounts. That step also
   manually fixed 6 projects whose region the API returned as
   `Unknown`.
   **Fix:** add `scripts/enrich_audit.py` containing both the API call
   and the manual region overrides (with the country→region lookup
   table inline so it's auditable).

3. **No requirements file.** The project depends on `requests`,
   `matplotlib`, `python-docx` (used in shell-side edits to the .docx),
   plus stdlib. None of these are pinned. A replicator gets whatever
   pip currently installs — potentially incompatible.
   **Fix:** add `requirements.txt` with the three packages and the
   currently-installed versions, plus a Python-version note (>=3.9 for
   `dataclass(asdict)` patterns, >=3.10 ideally for the `|` union
   types used in type hints).

4. **No master script / Makefile.** README documents the seven-step
   pipeline as separate commands. Re-running from scratch requires
   manually executing each. No way to atomically "rebuild everything
   from raw API calls".
   **Fix:** add a `Makefile` with targets `universe`, `download`,
   `search`, `tables`, `union`, `enrich`, `audit`, `chart`,
   `cea`, and `all`. Each depends on the prior step's output, so
   `make audit` regenerates only what's needed.

5. **Hardcoded project list in `summarize_for_blog.py`.** Lines 25–37
   list the 12 original projects with their commitments. If the blog
   ever expands beyond those 12, the script becomes wrong silently.
   The portfolio summariser does this correctly (reads from CSV), so
   `summarize_for_blog.py` is now a stale relic.
   **Fix:** delete `summarize_for_blog.py`. Its outputs were superseded
   by `summarize_portfolio.py`. If the 12-project subset is needed
   again, parametrise the portfolio summariser with a `--filter-ids`
   flag.

---

## Minor Issues

1. **`~$index.docx` Word lock file in repo root.** Apple/Office cruft.
   Add to a `.gitignore` if you ever git-init this folder.

2. **README references `index.qmd` and `index.docx` in the root** but
   both files have been moved to `archive/`. Update the README's folder
   layout block.

3. **`source-documents/` PDFs are not enumerated in any manifest.**
   `docs-expanded/_manifest.csv` covers the 798 auto-downloaded PDFs.
   The 53 hand-collected ones in `source-documents/` have no provenance
   metadata. A second researcher can't tell which WB document each PDF
   corresponds to without opening it.
   **Fix:** add `source-documents/_manifest.csv` with at minimum
   `filename, project_id, country, doc_type` per file. Could be
   bootstrapped from filenames since they follow a `P######_Country_Type.pdf`
   convention.

4. **Region API lookup is rate-limited and slow.** Each project takes
   ~1s + retries. For 145 projects that's >2 minutes per run. Could
   cache the result locally so re-runs are instant.

5. **No script-level "Inputs/Outputs" comment header.** Each script
   has a purpose docstring but doesn't list its expected input files
   and what it writes. AEA template-README convention. For example,
   `summarize_portfolio.py` reads four CSVs and writes two — that
   should be in its docstring header.

6. **Random seed concerns are minor here.** No bootstrapping or
   sampling is done. The only nondeterminism is API ordering, which
   doesn't affect downstream tallies.

7. **No formal data citations.** WB API URLs are listed under "Data
   provenance" in the README but not in a structured way. If this
   becomes a brief, would want full bibliographic citations with
   accessed-on dates.

8. **`cea_botec.py` parameters are inline in a dataclass.** That's
   fine for a BOTEC, but if anyone tweaks parameters they don't show
   up in `cea_parameters.csv` (which is currently written but appears
   to be a stub — it has empty `docstring` columns). The dataclass
   defaults are the de-facto source of truth; the CSV is decorative.
   **Fix:** populate the CSV by writing the field's `__doc__` from the
   dataclass, or remove the empty CSV and rely on the script docstring.

9. **`extract_parameter_tables.py` page-by-page extraction is slow**
   (~25 minutes on 851 PDFs). No checkpointing — if it crashes
   half-way you lose everything. Could persist progress per-PDF.

10. **`download_wb_documents.py` writes the manifest only at the end**
    of the run. If the script crashes mid-run, the manifest is lost
    even though the PDFs are on disk. Could append to manifest after
    each successful download.

---

## Strengths (preserve these)

- **Consistent path discipline.** Every script uses
  `ROOT = Path(__file__).resolve().parent.parent` and builds paths
  from there. Zero hardcoded `/Users/...` paths in any script. Means
  the project moves cleanly between machines.

- **Clear folder taxonomy.** `outputs/{universe,search,tables,audit,cea}`
  is logical and the file names within each subfolder are
  self-explanatory. A second reader can navigate.

- **Idempotent download script.** `download_wb_documents.py` skips
  already-present files, so a partial run can be resumed without
  re-downloading.

- **API retry logic with exponential backoff.** Both `fetch_wb_projects.py`
  and `download_wb_documents.py` retry on 5xx errors with growing
  delays — the right pattern for unreliable third-party APIs.

- **README has a "Known gaps" section.** Explicitly documents the
  legacy-vs-new sector code issue and the language-coverage gap. Good
  practice; replicators know what to expect.

- **Each script has a docstring** explaining purpose, sources, and
  command-line examples. Above average for a research codebase.

- **Outputs are CSV/Markdown** — never binary or proprietary. Audit
  trail is grep-able.

- **The two-stage analysis (search + parameter tables)** is well-
  factored. Each script does one thing. The summariser joins them.

---

## Recommended Priority Order

1. **Add `union_corpora.py`** (Major #1) — without this the pipeline doesn't
   re-run end-to-end after a clean checkout. Highest replication risk.

2. **Add `enrich_audit.py`** (Major #2) — same reason; the chart fails
   without it.

3. **Add `requirements.txt` and Python version note** (Major #3) — quick win.

4. **Add `Makefile`** (Major #4) — turns the pipeline into a single
   command and makes #1 and #2 properly wired together.

5. **Delete `summarize_for_blog.py`** (Major #5) — stale code is worse
   than no code.

6. **Fix README's folder layout block** (Minor #2) — cheap, prevents
   confusion.

7. **Add `source-documents/_manifest.csv`** (Minor #3) — small effort,
   meaningful provenance improvement.

The remaining minors are polish — none would block use of this folder
as the data appendix to a CGD note or working paper.
