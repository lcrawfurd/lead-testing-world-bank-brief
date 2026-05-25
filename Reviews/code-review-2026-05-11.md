# Code review — `lead-testing-world-bank-brief` (round 2)

**Date:** 11 May 2026
**Reviewer:** Claude (via `/code-review`)
**Scope:** All files in the public repository as of commit `9408db6`
**Prior review:** `Reviews/code-review-2026-05-07.md` (round 1)

## Summary

The five major issues from the round-1 review are all closed. The
pipeline has been harmonised to a single corpus (no more split between
`source-documents/` and `docs-expanded/`, no more union step), every
intermediate that the audit reads is produced by a script in `scripts/`,
dependencies are pinned, the Makefile orchestrates the whole flow from
one command, and `verify_pipeline.py` asserts the headline claim
("zero confirmed drinking-water lead testing") on every run. A
clean-run test (delete all audit outputs, run `make chart`) reproduces
the numbers in ~1 second from cached intermediates. This is now well
above the bar for a CGD blog companion repo — and within reach of a
formal AEA-style replication package with a few small additions
documented below.

The repo is live at
`https://github.com/lcrawfurd/lead-testing-world-bank-brief` and
ready to transfer to `Center-for-Global-Development`.

---

## Major Issues

**None.** Everything that would cause a clean checkout to fail or that
would block external replication has been fixed since round 1.

---

## Minor Issues

1. **No `make install` target.** Replicators must remember
   `python3 -m pip install -r requirements.txt` as a separate step
   before `make all`. README mentions it but a target would be
   foolproof. **Fix:** add a `make install` target to the Makefile
   that runs `pip install -r requirements.txt` and prints a reminder
   to install `poppler` separately.

2. **Output-to-script mapping is not formalised in the README.** The
   README's "Pipeline" table maps scripts → outputs, but there's no
   reverse table mapping every output back to the script that
   produced it. For an AEA-template README that mapping is canonical.
   **Fix:** add a small table to the README listing each top-level
   output file (`portfolio_audit_with_region.csv`,
   `projects_by_region.png`, `cea_results.md`, etc.) with its
   producing script, ideally with line numbers of the in-text claims
   each one supports.

3. **No formal Data Availability Statement.** The README's "Data
   provenance" section has the URLs and access dates needed but
   doesn't follow the AEA template's headings (rights confirmation,
   access conditions, licensing, in-package vs external for each
   dataset). For the WB Projects API and WDS API, all the underlying
   data is public and licence-friendly — but stating that explicitly
   in the AEA-template headings makes the repo a one-click submission
   to journals that ask for it. **Fix:** add a "Data Availability
   Statement" section to the README with one paragraph per data
   source.

4. **Scripts are not numbered with execution-order prefixes**
   (`01_fetch_wb_projects.py`, `02_download_wb_documents.py`, …).
   The Makefile resolves execution order via dependency targets, so
   this is arguably a non-issue for this repo — but the convention
   the rubric calls for is helpful for readers skimming `scripts/`
   for the first time. **Fix:** optional. Renaming would help; the
   alternative is a `scripts/README.md` that lists scripts in
   execution order with one line each.

5. **Script docstrings vary in formality.** Every script has a header
   docstring with purpose and source citations, but the AEA-template
   convention is `Author / Date / Inputs / Outputs / Dependencies`
   as a structured block. Currently captured informally inside the
   prose. **Fix:** optional. Adding 4-line structured headers to each
   script would take 20 minutes and read more like a replication
   package; not blocking.

6. **`outputs/audit/_api_cache.json` is committed but undocumented.**
   The `.gitignore` has a comment explaining why it's committed, but
   a first-time reader cloning the repo won't know what it is or
   when to refresh it. **Fix:** add a one-paragraph
   `outputs/audit/README.md` mentioning the cache file and the
   `enrich_audit.py --no-cache` flag for refresh.

7. **CI workflow committed locally but not yet pushed to GitHub.**
   `.github/workflows/verify.yml` exists in the working tree but
   wasn't pushed because the gh token didn't have `workflow` scope.
   The README and PR template both reference CI as if it's live.
   **Fix:** `gh auth refresh -s workflow`, then push. (Already
   documented in the chat log.)

8. **No `tests/` folder.** `scripts/verify_pipeline.py` is a smoke
   test in the right spirit but lives in `scripts/`, not `tests/`.
   For a pure-research blog repo this is fine. For a future-proofed
   repo that may grow, conventional `tests/` placement helps
   contributors find the test suite. **Fix:** optional. Could move
   to `tests/test_pipeline_headlines.py` if you ever add a real test
   harness.

9. **`.DS_Store` is on disk** (gitignored, doesn't get committed),
   but it's a small reminder that the repo was developed on macOS.
   Not actionable; just noted.

10. **The Makefile's `clean` and `distclean` targets** use shell
    globbing that quietly succeeds if no matching files exist (good)
    but won't warn about unexpected files in the same directories.
    A new contributor adding `outputs/audit/notes.md` and running
    `make clean` won't lose it (the rm patterns are specific), which
    is correct. Just noting that the cleaning is conservative; if
    you ever add new output filenames that don't match the existing
    patterns, update the Makefile in lockstep.

---

## Strengths (preserve these)

- **`verify_pipeline.py` asserts the headline claim.** The script
  fails loudly if the "zero confirmed drinking-water lead testing"
  finding ever flips. This is a category of self-test that almost no
  development-economics repo has, and it directly protects the blog
  from silent regression in the underlying data.

- **Single-source-of-truth pipeline.** No hidden shell heredocs, no
  manual interventions, no separate paths for "the 12" vs "the rest".
  Everything that produces a number in the audit lives in `scripts/`
  and is wired together in the Makefile.

- **Path discipline.** Every script uses
  `ROOT = Path(__file__).resolve().parent.parent` and zero hardcoded
  `/Users/...` paths. The repo moves cleanly between machines.

- **Idempotent + cached.** `download_wb_documents.py` skips
  already-present PDFs; `enrich_audit.py` has a JSON cache for the
  WB Projects API. Both make iterative development pleasant.

- **API retry logic.** All three scripts that hit the WB APIs
  (`fetch_wb_projects`, `download_wb_documents`, `enrich_audit`)
  use exponential backoff with explicit retry counts. Right pattern
  for unreliable third-party services.

- **Clear taxonomy on the audit verdict.** Eight categories
  (`confirmed`, `baseline-drinking`, `baseline-only`, `effluent-only`,
  `table-unclassified`, `mentioned`, `absent`, `no-docs`) with
  precise definitions in the README. Makes the headline claim
  defensible and the false-positive analysis auditable.

- **CI workflow defined.** GitHub Actions runs `make audit && make
  enrich && make chart && make verify` on every push. The cache being
  committed means CI doesn't need WB API access; it just exercises
  the downstream pipeline. Right design.

- **CGD data viz style guide adherence.** `plot_by_region.py` reads
  the official CGD categorical palette + typography rules. Charts in
  the repo look like CGD's other publications.

- **Honest "Known limitations" section in README.** Three caveats
  (sector code coverage, language coverage, classifier ambiguity)
  spelled out plainly. Replicators know what to expect.

- **License + CITATION.cff + PR template.** All three signals that
  the repo is meant for external use, not just author-internal.

---

## Recommended Priority Order

If you want to add formality before publishing the blog or submitting
to a venue that asks for AEA-template replication packages:

1. **Push the CI workflow** (Minor #7). Single command after a `gh
   auth refresh`. Largest visibility-to-effort ratio.

2. **Add `make install`** (Minor #1). Three lines of Makefile;
   removes one foot-gun for first-time users.

3. **Add a Data Availability Statement section to the README**
   (Minor #3). 20 minutes of prose. Bumps the repo into "ready for
   formal submission" category.

4. **Add an output-to-script mapping table to the README** (Minor #2).
   15-row table; turns the README into something a journal data
   editor would tick off as compliant.

If you don't want to do any of the above, the repo is already in good
shape for a CGD-blog-companion release. None of the remaining items
would block reproduction or generate complaints from a reasonable
reader.

---

## What's different from the round-1 review

| Round 1 item | Status |
|---|---|
| Major #1 — CSV-union step missing from codebase | Resolved (deleted entirely — pipeline harmonised) |
| Major #2 — Region-enrichment step missing | Resolved (`scripts/enrich_audit.py` added) |
| Major #3 — No `requirements.txt` | Resolved |
| Major #4 — No Makefile / master script | Resolved (`Makefile`) |
| Major #5 — Stale `summarize_for_blog.py` | Resolved (deleted) |
| Minor #1 — `~$index.docx` Word lock file | Resolved (deleted) |
| Minor #2 — README references files in `archive/` | Resolved (README rewritten) |
| Minor #3 — No manifest for `source-documents/` | Moot (`source-documents/` no longer used) |
| Minor #4 — Region lookup not cached | Resolved (`_api_cache.json` in `enrich_audit.py`) |
| Minor #5 — Script headers lack Inputs/Outputs blocks | Partially addressed (some scripts have, others informal) |
| Minor #6 — No random seed concerns | N/A — pipeline is deterministic |
| Minor #7 — No formal data citations | Open (see Minor #3 above) |
| Minor #8 — `cea_botec.py` parameters CSV stub | Open (low priority) |
| Minor #9 — Slow extraction has no checkpointing | Open (low priority — `make tables` is rerun rarely) |
| Minor #10 — Download manifest only written at end | Open (low priority — script rarely crashes mid-run) |
