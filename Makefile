# Makefile for the lead-testing-world-bank-brief analysis pipeline.
#
# Usage:
#     make help               # show targets
#     make audit              # build the per-project audit (fast, ~5 sec)
#     make chart              # also build the by-region chart
#     make all                # full rebuild from scratch (downloads ~1 GB)
#     make clean              # remove generated outputs (keeps PDFs + cache)
#     make distclean          # also remove docs-expanded/ and the API cache

PY        := python3
SCRIPTS   := scripts
OUT       := outputs
DOCS      := docs-expanded

# 12 projects with legacy WB sector codes (WC/WA/WF/WZ) that the WW*
# queries don't return. These are the largest active water-supply
# projects from the original blog review and are added to the universe
# manually so the pipeline runs end-to-end from a clean checkout.
LEGACY_IDS := P170734,P178389,P169342,P179039,P179192,P163732,P151224,P176619,P164345,P163782,P164186,P178954

# ----- Outputs --------------------------------------------------------
UNIVERSE     := $(OUT)/universe/world_bank_water_projects.csv
SEARCH       := $(OUT)/search/lead_search.csv
TABLES       := $(OUT)/tables/parameter_tables.csv
AUDIT        := $(OUT)/audit/portfolio_audit.csv
AUDIT_REG    := $(OUT)/audit/portfolio_audit_with_region.csv
CHART        := $(OUT)/audit/projects_by_region.png
CEA_RESULTS  := $(OUT)/cea/cea_results.md
MANIFEST     := $(DOCS)/_manifest.csv

.PHONY: help all clean distclean audit chart cea verify \
        universe download search tables enrich

help:
	@echo "Targets:"
	@echo "  universe   Build the active-water-project universe CSV (calls WB API)"
	@echo "  download   Download safeguards PDFs into docs-expanded/    (slow, ~60min)"
	@echo "  search     Run keyword search across docs-expanded/"
	@echo "  tables     Extract parameter tables from docs-expanded/    (slow, ~25min)"
	@echo "  audit      Build portfolio_audit.csv (fast)"
	@echo "  enrich     Add WB region + financing-type metadata to the audit"
	@echo "  chart      Render the by-region chart"
	@echo "  cea        Run the back-of-envelope cost-effectiveness analysis"
	@echo "  verify     Sanity-check the audit outputs against expected ranges"
	@echo "  all        Full rebuild from raw API calls (downloads + reprocesses)"
	@echo "  clean      Remove generated outputs (keeps downloaded PDFs)"
	@echo "  distclean  Also remove docs-expanded/ and the API cache"

# ----- Step targets ---------------------------------------------------

universe: $(UNIVERSE)
$(UNIVERSE):
	$(PY) $(SCRIPTS)/fetch_wb_projects.py --include-ids $(LEGACY_IDS)

download: $(MANIFEST)
$(MANIFEST): $(UNIVERSE)
	$(PY) $(SCRIPTS)/download_wb_documents.py --from-csv $(UNIVERSE)

search: $(SEARCH)
$(SEARCH): $(MANIFEST)
	$(PY) $(SCRIPTS)/search_pdfs_for_lead.py

tables: $(TABLES)
$(TABLES): $(MANIFEST)
	$(PY) $(SCRIPTS)/extract_parameter_tables.py

audit: $(AUDIT)
$(AUDIT): $(UNIVERSE) $(SEARCH) $(TABLES) $(MANIFEST)
	$(PY) $(SCRIPTS)/summarize_portfolio.py

enrich: $(AUDIT_REG)
$(AUDIT_REG): $(AUDIT)
	$(PY) $(SCRIPTS)/enrich_audit.py

chart: $(CHART)
$(CHART): $(AUDIT_REG)
	$(PY) $(SCRIPTS)/plot_by_region.py

cea: $(CEA_RESULTS)
$(CEA_RESULTS):
	$(PY) $(SCRIPTS)/cea_botec.py

verify: $(AUDIT_REG)
	$(PY) $(SCRIPTS)/verify_pipeline.py

all: chart cea verify
	@echo "Full pipeline complete."

clean:
	rm -f $(OUT)/audit/portfolio_audit*.{csv,md}
	rm -f $(OUT)/audit/projects_by_region.{png,svg}
	rm -f $(OUT)/cea/cea_*.{csv,md}
	@echo "Removed generated outputs in outputs/audit and outputs/cea."

distclean: clean
	rm -rf $(DOCS)
	rm -f $(OUT)/audit/_api_cache.json
	rm -f $(OUT)/search/lead_search*.{csv,txt,log}
	rm -f $(OUT)/tables/parameter_tables*.{csv,txt,log}
	rm -f $(OUT)/universe/world_bank_water_projects*.csv
	@echo "Removed downloaded PDFs and all intermediates."
