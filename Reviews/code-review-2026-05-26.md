# Code review — `lead-testing-world-bank-brief` (round 3)

**Date:** 26 May 2026
**Reviewer:** Claude (via `/code-review`)
**Scope:** All files in the public repository as of commit `45532c8`
**Prior reviews:** `code-review-2026-05-07.md`, `code-review-2026-05-11.md`

## Summary

This review follows a second methodological tightening (the universe
filter has now been narrowed twice: first from WWC+WWA+WWW to WWC+WWA
in response to a WB reviewer's feedback, then to WWC alone for the
strictest defensible drinking-water filter). All headline findings
have survived both narrowings — zero confirmed drinking-water lead
testing, Ghana baseline-drinking, Uganda effluent-only, Malawi
table-unclassified — and `make verify` continues to assert this on
every run. The pipeline runs end-to-end from a clean state in ~1
second using committed intermediates. Repo is at 4 commits, all
clean, on GitHub at `lcrawfurd/lead-testing-world-bank-brief`. The
only outstanding GitHub-side item is the CI workflow file, which
remains uncommitted to remote because of the OAuth `workflow` scope
issue carried over from round 1.

---

## Major Issues

**None.**

The two filter narrowings are documented in the README and in code
comments. The `verify_pipeline.py` ranges have been updated each
time. The headline finding is invariant across denominators. Anyone
cloning the repo can rebuild and verify.

---

## Minor Issues

1. **README mentions `Reviews/` rated reports but doesn't link to them.**
   A new reader sees `Reviews/` in the folder layout but isn't told
   why it exists. **Fix:** add a one-line description: *"Review reports
   from prior code-quality audits."*

2. **`scripts/fetch_wb_projects.py` retains `--broad` as a deprecated
   alias.** Reasonable for backward compatibility, but now slightly
   confusing — the docstring says it's an alias for
   `--include-water-resources`, but the actual code behaviour is now
   buried under several levels of conditional. **Fix:** add a single
   inline comment in the conditional block noting that `--broad` is
   kept for compatibility, or remove it outright in a future version
   bump (it has only ever been used internally by this project).

3. **Three docx drafts at repository root** (`Blog latest.docx`,
   `Lead WB Water (v1, shared).docx`, `Lead WB Water (v2, shared).docx`).
   They're correctly gitignored (via `*.docx`), so they don't
   pollute the public repo, but they clutter the local working
   tree. **Fix:** move to a `drafts/` subdirectory that's also
   gitignored, keeping the root clean.

4. **`.github/workflows/verify.yml` still uncommitted to remote.**
   Carried over from rounds 1 and 2. The workflow file exists
   locally (restored after each push attempt) but the OAuth token
   doesn't have `workflow` scope. **Fix:** run
   `gh auth refresh -s workflow`, then `git add
   .github/workflows/verify.yml && git commit -m "Add CI workflow"
   && git push`. Five-minute task.

5. **Output-to-script mapping table** still not in README. Carried
   over from round 2. Low priority.

6. **Formal Data Availability Statement** still not in README in
   AEA-template form. Carried over from round 2. Low priority.

7. **`outputs/audit/_api_cache.json` is now larger** because the
   most recent runs of `enrich_audit.py` hit the API for 94 then 81
   projects (deleted the cache between runs). The committed cache
   reflects the current 81-project universe. **Worth noting:** if
   the universe expands again later (via `--include-sanitation` or
   `--include-water-resources`) and someone runs `make enrich`, the
   newly-fetched records will be appended to the existing cache. The
   cache merges fine across universe definitions. No fix needed.

8. **`scripts/fetch_wb_projects.py` docstring describes the universe
   as "~65 projects"** for the WWC-only default, but the actual count
   with the 12 manual additions is 81. Small but worth tightening:
   *"~65 from the API query, plus the 12 legacy-coded manual
   additions in `LEGACY_IDS` from the Makefile = ~77–81 total."*

---

## Strengths

- **Methodology is now genuinely tight.** WWC-only is the strictest
  defensible filter for a piece about lead in drinking water. The
  blog can claim it audited the drinking-water-supply portfolio
  specifically, and the criticism survives whether you use WWC
  alone, WWC + WWA, or the broader WWC + WWA + WWW universe.

- **Methodological gap with the WB is now documented honestly.** The
  README explains exactly why our $17B differs from the Bank's $8.7B
  (we can't sector-percent-weight from public API data). Anyone who
  asks "why doesn't your number match the WB's" can read the
  paragraph and understand the answer.

- **Three universe levels are accessible via flags.** A future
  reader can run `--include-sanitation` or `--include-water-resources`
  and get the broader figures with one keystroke. No commenting-out
  required.

- **`verify_pipeline.py` ranges were updated each time.** The smoke
  test catches the new ranges; it would fail if a future change
  accidentally widened or narrowed the universe.

- **Git history is honest.** Three commits, each with a clear
  message explaining the methodological intent. A reviewer can
  trace exactly how the universe definition evolved.

- **Headline finding invariant.** Zero confirmed drinking-water
  lead testing at every level of the filter. This is the
  strongest possible robustness check for the blog's main claim.

---

## Recommended Priority Order

If you want to put any more polish on before the blog goes live, in order:

1. **Push the CI workflow** (Minor #4). Five minutes, biggest
   visibility-to-effort ratio.

2. **Move draft docx files to `drafts/`** (Minor #3). One command;
   keeps the root clean for external readers.

3. **Add Reviews/ description to the README folder-layout block**
   (Minor #1). One line.

4. **Tighten the fetch_wb_projects.py docstring** (Minor #8).
   30 seconds.

The remaining items (output-to-script mapping table, formal Data
Availability Statement) are for if you ever submit this to a
journal that requires AEA-template compliance. Not needed for the
CGD blog itself.

---

## What changed since round 2

| Round 2 item | Status |
|---|---|
| Major issues | All clear (none in round 2 either) |
| Minor #1 — no `make install` | Still open |
| Minor #2 — no output-to-script mapping | Still open |
| Minor #3 — no formal DAS | Still open |
| Minor #4 — scripts not numerically prefixed | Still open (Makefile orchestrates order; non-issue in practice) |
| Minor #5 — script docstrings vary | Still open |
| Minor #6 — `_api_cache.json` undocumented | Closed (README paragraph added in round-3-pre commit) |
| Minor #7 — CI workflow not pushed | Still open |
| Minor #8 — `tests/` folder | Still open (low priority) |

New since round 2:
- WB reviewer's portfolio-figure objection addressed (round 3 commit `d4c91ed`)
- Further narrowing to WWC alone (round 3 commit `45532c8`)
- README has two methodological-note paragraphs documenting the universe-definition choices and the sector_percent gap
- This review report
