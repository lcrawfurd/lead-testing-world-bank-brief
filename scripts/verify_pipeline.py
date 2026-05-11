#!/usr/bin/env python3
"""
Sanity-check the pipeline's headline numbers.

Reads the audit outputs and asserts they match what the blog cites.
Run after `make audit && make enrich` (or as part of `make verify`).

Exit code 0 if all checks pass, non-zero otherwise. Useful as a CI
smoke test and as a guard against silent regressions when a future
WB API change reshapes the data.

Expected values are intentionally loose ranges (not exact equality)
because the WB portfolio shifts week to week — projects close,
new ones get approved, commitments revise. The pipeline should be
robust to small drift; this test catches *large* drift.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Loose ranges around the headline numbers as of May 2026.
# Update these when the underlying portfolio shifts materially.
EXPECTED = {
    "min_projects":             130,
    "max_projects":             170,
    "min_commitment_usd":     28_000_000_000,
    "max_commitment_usd":     35_000_000_000,
    "max_confirmed_drinking_lead": 0,    # the headline claim — zero confirmed
    "min_baseline_drinking":    1,       # Ghana GAMA at minimum
    "min_countries":           60,
    "max_countries":           90,
    "expected_verdicts": {
        "confirmed",
        "baseline-drinking",
        "baseline-only",
        "effluent-only",
        "table-unclassified",
        "mentioned",
        "absent",
        "no-docs",
    },
}


def fail(msg: str):
    print(f"  ✗ FAIL: {msg}", file=sys.stderr)
    return False


def ok(msg: str):
    print(f"  ✓ {msg}")
    return True


def main() -> int:
    audit_path = ROOT / "outputs" / "audit" / "portfolio_audit.csv"
    region_path = ROOT / "outputs" / "audit" / "portfolio_audit_with_region.csv"

    if not audit_path.exists():
        return fail(f"{audit_path} not found — run `make audit` first")
    if not region_path.exists():
        return fail(f"{region_path} not found — run `make enrich` first")

    rows = list(csv.DictReader(audit_path.open()))
    region_rows = list(csv.DictReader(region_path.open()))

    passed = True

    print("Pipeline verification")
    print("=" * 50)

    # Count
    n = len(rows)
    if EXPECTED["min_projects"] <= n <= EXPECTED["max_projects"]:
        passed &= ok(f"Project count: {n} (expected {EXPECTED['min_projects']}-{EXPECTED['max_projects']})")
    else:
        passed &= fail(f"Project count: {n} (expected {EXPECTED['min_projects']}-{EXPECTED['max_projects']})")

    # Commitment
    total = sum(float(r["commitment_usd"]) for r in rows)
    if EXPECTED["min_commitment_usd"] <= total <= EXPECTED["max_commitment_usd"]:
        passed &= ok(f"Total commitment: ${total/1e9:.1f}B")
    else:
        passed &= fail(f"Total commitment: ${total/1e9:.1f}B (out of expected range)")

    # Headline claim — zero confirmed drinking-water lead testing
    confirmed = sum(1 for r in rows if r["verdict"] == "confirmed")
    if confirmed <= EXPECTED["max_confirmed_drinking_lead"]:
        passed &= ok(f"Confirmed drinking-water lead testing: {confirmed} (headline claim holds)")
    else:
        passed &= fail(
            f"Confirmed drinking-water lead testing: {confirmed} — "
            f"HEADLINE CLAIM BROKEN. Spot-check the projects."
        )
        for r in rows:
            if r["verdict"] == "confirmed":
                print(f"      → {r['project_id']} {r['country']}: {r['project_name']}",
                      file=sys.stderr)

    # Baseline-drinking finding (Ghana)
    bd = [r for r in rows if r["verdict"] == "baseline-drinking"]
    if len(bd) >= EXPECTED["min_baseline_drinking"]:
        passed &= ok(f"Baseline-drinking findings: {len(bd)} (incl. {bd[0]['project_id']} {bd[0]['country']})")
    else:
        passed &= fail(f"Baseline-drinking findings: {len(bd)} (Ghana GAMA expected)")

    # Verdict vocabulary
    found_verdicts = {r["verdict"] for r in rows}
    extras = found_verdicts - EXPECTED["expected_verdicts"]
    if extras:
        passed &= fail(f"Unknown verdict(s) emitted: {sorted(extras)}")
    else:
        passed &= ok(f"Verdict vocabulary OK ({len(found_verdicts)} of "
                    f"{len(EXPECTED['expected_verdicts'])} used)")

    # Countries
    countries = {r["country"] for r in rows if r["country"]}
    if EXPECTED["min_countries"] <= len(countries) <= EXPECTED["max_countries"]:
        passed &= ok(f"Countries: {len(countries)}")
    else:
        passed &= fail(f"Countries: {len(countries)} (out of expected range)")

    # Region coverage
    regions = {r["region"] for r in region_rows if r.get("region")}
    if "Unknown" in regions:
        passed &= fail(f"Region 'Unknown' present in enriched audit — region patches need updating")
    else:
        passed &= ok(f"All projects have a known region ({len(regions)} regions)")

    print("=" * 50)
    if passed:
        print("All checks passed.")
        return 0
    else:
        print("Some checks failed. See above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
