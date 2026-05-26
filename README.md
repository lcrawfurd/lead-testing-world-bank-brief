# Lead testing in World Bank water supply projects

Code, data, and analysis behind a [Center for Global Development blog
post](https://www.cgdev.org/) auditing how the World Bank's active
water supply portfolio handles lead in drinking water.

**Headline finding:** across the Bank's active drinking-water-supply
portfolio (81 projects tagged with the WWC sector code, ~\$3 billion
in water-attributable commitments), not one commits to ongoing lead
testing in the drinking water it delivers. A single \$30 million
sanitation project in Ghana ran a baseline groundwater test against
WHO guidelines, found lead above threshold, and committed to no
follow-up monitoring.

**A note on portfolio figures.** The pipeline defaults to the
strictest defensible filter — WWC (Water Supply) only — to capture
the drinking-water-relevant universe.

Most Bank projects are multi-sector. A typical "water supply" project
might also be tagged with sanitation, public administration, or urban
development codes; only a small fraction of the project's commitment
is actually allocated to water. The pipeline therefore writes two
dollar totals per project:

- `Total_Commitment_USD` — full project commitment (a ceiling)
- `Weighted_Commitment_USD` — sector-percent-weighted share allocated
  to water sectors

The WB Projects API populates `sector_percent` for about half of
active water projects (39 of 81 in our universe). For the other half
the API returns 0 across all sectors. The pipeline imputes a
**proportional share by sector-code count**: if a project carries
five sector tags and one is WWC, we attribute 20% of the commitment
to water. This is a structural lower bound — better than dropping the
project (which undercounts) or assuming 100% (only 2 of 81 projects
are genuinely single-sector water).

Resulting totals for the WWC-only universe of 81 projects:

| Method | Total |
|---|---|
| Unweighted (full commitment per project) | \$17.0B |
| Hybrid-weighted (audit headline) | **\$3.4B** |

## Quick start

```bash
# 1. Install Python dependencies
python3 -m pip install -r requirements.txt

# 2. Install pdftotext (poppler)
brew install poppler                # macOS
# apt-get install poppler-utils     # Debian/Ubuntu

# 3. Run the full pipeline (≈90 min, downloads ≈1 GB of PDFs)
make all

# Or just rebuild the audit + chart from cached intermediates:
make chart && make verify
```

`make verify` runs a small set of sanity checks against the audit
outputs (headline project count, total commitment, "zero confirmed
drinking-water lead testing" claim, etc.). It's also run on every
push and pull request via GitHub Actions (see `.github/workflows/verify.yml`).

`make help` lists every target. The pipeline is dependency-tracked, so
re-runs only redo what's stale.

## Folder layout

```
├── README.md                   This file
├── LICENSE                     MIT
├── CITATION.cff
├── Makefile                    Build pipeline (run `make help`)
├── requirements.txt            Python dependencies
├── .gitignore
│
├── docs-expanded/              PDFs for the broader project set (auto-downloaded; gitignored)
│   └── _manifest.csv           One row per downloaded doc with metadata
├── docs-extracted/             Plain-text extracted from every PDF
│                               (committed — lets CI and replicators run
│                               the search/tables pipeline without needing
│                               the 1 GB of PDFs or a `pdftotext` install)
│
├── scripts/                    Analysis pipeline
│   ├── fetch_wb_projects.py        Build the project universe via WB API
│   ├── download_wb_documents.py    Download project safeguards PDFs
│   ├── search_pdfs_for_lead.py     Keyword search across PDFs
│   ├── extract_parameter_tables.py Parse water-quality parameter tables
│   ├── summarize_portfolio.py      Per-project audit verdict
│   ├── enrich_audit.py             Add WB region + IBRD/IDA/grant amounts
│   ├── plot_by_region.py           Render the by-region chart
│   └── cea_botec.py                Cost-effectiveness BOTEC
│
├── outputs/
│   ├── universe/               Project list from the WB Projects API
│   ├── search/                 Keyword-search results (lead / Pb / heavy metals)
│   ├── tables/                 Parsed water-quality parameter tables
│   ├── audit/                  Per-project verdicts + region/financing chart
│   └── cea/                    Back-of-envelope cost-effectiveness analysis
```

## How the pipeline works

The pipeline is **uniform across all projects in the universe** — there is no
separate manual review of "the top 12" and automated review of "the
rest". Every project is fetched from the WB API, every safeguards
document is downloaded from the WB Documents API, every PDF is run
through the same regex-based search and parameter-table extraction.

Steps (Makefile dependencies in parentheses):

| Step | Script | Purpose |
|---|---|---|
| 1. universe | `fetch_wb_projects.py` | Query the WB Projects API for active water-sector projects (codes WWC/WWA/WWW) plus 12 legacy-coded projects added by ID. Outputs one CSV with project metadata. |
| 2. download | `download_wb_documents.py` | For each project, query the WB Documents API and download Project Appraisal Documents, ESIAs, ESMFs, ESCPs, ESSAs, Resettlement Plans, and Stakeholder Engagement Plans. Skips already-present files. |
| 3. search | `search_pdfs_for_lead.py` | Run context-aware regexes for "lead" as metal vs verb, plus 17 water-quality parameters. Records per-project keyword counts. |
| 4. tables | `extract_parameter_tables.py` | Score each PDF page for "is this a parameter table"; for high-scoring pages, parse rows into `(parameter, value, unit)` and classify as drinking / effluent / baseline / groundwater / surface. |
| 5. audit | `summarize_portfolio.py` | Join the above into a per-project verdict. |
| 6. enrich | `enrich_audit.py` | Pull WB region and IBRD/IDA/grant breakdown for each project from the API; cache responses. |
| 7. chart | `plot_by_region.py` | Stacked horizontal bar chart of $ commitments by region and financing type, in CGD brand colours. |
| 8. cea | `cea_botec.py` | Back-of-envelope cost-per-DALY analysis. |

## Audit verdict taxonomy

Each project gets one of:

| Verdict | Meaning |
|---|---|
| `confirmed` | Real numeric Lead row in a drinking-water parameter table |
| `baseline-drinking` | Lead measured against WHO drinking-water guideline in a one-shot baseline |
| `baseline-only` | Lead in a groundwater / ambient baseline table, no drinking-water context |
| `effluent-only` | Lead only in wastewater discharge standards |
| `table-unclassified` | Lead row in a table the classifier couldn't disambiguate |
| `mentioned` | Lead mentioned only in narrative / keyword match |
| `absent` | No lead mention anywhere in the safeguards docs |
| `no-docs` | No safeguards documents downloaded (typically pipeline projects) |

## Outputs

The most-cited outputs:

- `outputs/audit/portfolio_audit_with_region.csv` — one row per project
  with country, region, $ commitment, IBRD/IDA/grant split, audit
  verdict, and supporting evidence counts. The data behind the chart.
- `outputs/audit/projects_by_region.png` — chart for the blog
- `outputs/audit/portfolio_audit.md` — readable summary table
- `outputs/cea/cea_results.md` — narrative CEA summary

## Requirements

- Python 3.10+ (uses union-type syntax `dict | dict`)
- `pdftotext` system binary (poppler):
  - macOS: `brew install poppler`
  - Debian/Ubuntu: `apt-get install poppler-utils`
- Python deps in `requirements.txt`: `requests`, `matplotlib`, `python-docx`

## Known limitations

1. **Sector code coverage.** The WB has two parallel sector code
   schemes — newer (WWC/WWA/WWW) and legacy (WC/WA/WF/WZ). The
   universe query targets the modern codes plus 12 specific
   legacy-coded projects added by ID (the largest active water-supply
   projects from the original blog review). The included-IDs list is
   in the Makefile (`LEGACY_IDS`). Other legacy-coded water projects
   are not captured.
2. **Language coverage.** 67 of 556 safeguards documents in the
   WWC universe (12%) are in French, Portuguese, Spanish, or Arabic
   — mostly annexes for francophone Africa, Morocco, Peru, Argentina,
   Angola, and Brazil. The keyword search is English-only, so lead
   mentions inside those annexes are missed. Every project with any
   documents has at least one English-language document (typically
   the PAD), so no project is entirely blind to the search.
3. **Classifier ambiguity.** The parameter-table classifier's
   *drinking / effluent / baseline* tags are inferred from page
   context. Ambiguous pages get multiple tags. Any `confirmed`-verdict
   project should be manually spot-checked before citation.

## Data provenance

All project data is pulled live from the WB APIs. URLs and access
date are recorded in the script headers; the WB APIs are public and
require no authentication.

- **Project metadata:** <https://search.worldbank.org/api/v3/projects>
- **Project documents:** <https://search.worldbank.org/api/v3/wds>
- **WHO Drinking Water Quality Guideline for lead:** 10 µg/L (0.01 mg/L)
- **Larsen & Sánchez-Triana 2023, Lancet Planetary Health:**
  <https://doi.org/10.1016/S2542-5196(23)00166-3>
- **Fisher et al. 2021, Environmental Health Perspectives:**
  <https://doi.org/10.1289/EHP7804>
- **GBD 2019:** Global Burden of Disease 2019, IHME
- **Aquaya / Peletz et al. 2017** for water-quality testing costs

## Citation

If you use this code or data, please cite the [accompanying CGD blog
post](https://www.cgdev.org/) (URL once published) and this repository
(see `CITATION.cff`).

## License

MIT (see `LICENSE`).
