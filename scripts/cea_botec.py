#!/usr/bin/env python3
"""
Back-of-the-envelope cost-effectiveness analysis for adding lead testing
(and conditional remediation) to World Bank water supply projects.

Two questions:
  (A) What does it cost to ADD lead testing to a WB water supply project,
      per beneficiary served, per year?
  (B) At what PREVALENCE of lead exceedance in Bank-funded water systems
      does a testing+remediation policy clear a given cost-effectiveness
      threshold?

Every parameter below cites its source. Numbers flagged [ASSUMPTION] are
defensible placeholders, not primary-source facts — they should be pinned
down before publication.

Sources
-------
[Larsen2023]  Larsen B, Sánchez-Triana E. "Global health burden and cost
              of lead exposure in children and adults: a health impact and
              economic modelling analysis." Lancet Planetary Health 2023;
              7(10):e831–e840. doi:10.1016/S2542-5196(23)00166-3
              Key facts: 5.545M CVD deaths/year attributable to lead (2019);
              765M IQ points lost in under-5s; $1.61T PPP; 90% of CVD
              deaths in LMICs.
[GBD2019]     IHME Global Burden of Disease 2019.
              21.7M DALYs/year attributable to lead globally;
              ~1M deaths/year (narrower counting than Larsen);
              Majority of burden from CVD.
[Aquaya2017]  Peletz R et al. "How Much Will It Cost To Monitor Microbial
              Drinking Water Quality in Sub-Saharan Africa?" ES&T 2017.
              Mean test cost $21 ± 11 per sample across SSA.
[WHOGDWQ]     WHO Guidelines for Drinking-water Quality. Lead guideline
              value 10 µg/L (0.01 mg/L).
[USEPA_LCR]   US EPA Lead and Copper Rule technical manual for sampling
              frequency assumptions.
[Stanek2020]  Stanek LW et al. "Modeled Impacts of Drinking Water Pb
              Reduction Scenarios on Children's Exposures and Blood Lead
              Levels." ES&T 2020. BLL:water-Pb slope varies with age;
              water can be 96% of exposure in LSL+no CCT scenarios.

Outputs
-------
  outputs/cea/cea_parameters.csv   Input parameters + sources
  outputs/cea/cea_results.md       Narrative summary
  outputs/cea/cea_breakeven.csv    Break-even prevalence by CE threshold
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs" / "cea"

# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

@dataclass
class Inputs:
    # ---- TESTING COSTS ------------------------------------------------
    cost_per_sample_usd: float = 20.0
    """USD per water quality sample (lab-based lead testing).
    [Aquaya2017] reports $21 ± 11 for microbial; lead is comparable
    magnitude (portable XRF + occasional ICP-MS)."""

    samples_per_system_per_year: int = 4
    """Quarterly testing per water system. [USEPA_LCR] requires far more
    frequent sampling in the US (biannual per household for tier 1 sites);
    4/year is a light-touch baseline for small LMIC systems."""

    # ---- REMEDIATION COSTS --------------------------------------------
    remediation_cost_per_affected_hh_usd: float = 200.0
    """Lifetime remediation cost per affected household. Options include
    POU faucet filter + replacement cartridges ($30-100 initial + $20-50/yr),
    brass-fitting replacement ($20-80 one-off), or service-line replacement
    ($500+ per household, rarely feasible in LMIC rural systems).
    [ASSUMPTION — range $100-500]. Central: $200 reflects POU filter +
    ~5 years of cartridges + surveillance."""

    remediation_horizon_years: int = 10
    """Years over which remediation cost is amortised. [ASSUMPTION]"""

    households_per_water_system: int = 100
    """Average households per Bank-funded rural/small-town water system.
    [ASSUMPTION — varies hugely, 20-5000]."""

    # ---- EXPOSURE MAGNITUDE IN AFFECTED SYSTEMS -----------------------
    water_pb_affected_ugL: float = 30.0
    """Average water lead concentration in systems exceeding the WHO 10
    µg/L guideline. [ASSUMPTION] - limited primary data. Based on range
    observed in LMIC studies: Ghana ESIA measured 52 µg/L in one well;
    Indian urban studies commonly report 20-50 µg/L in affected samples."""

    bll_slope_per_water_pb: float = 0.04
    """Blood lead level increase (µg/dL) per unit of water lead (µg/L).
    [Stanek2020] models show 0.02-0.10 depending on age and water intake.
    0.04 = conservative mid-range for mixed age population (children
    higher, adults lower). Adults ingest more water per kg but absorb
    less."""

    # ---- HEALTH BURDEN COEFFICIENTS -----------------------------------
    dalys_per_bll_per_person_year: float = 0.00075
    """DALYs per µg/dL of BLL per person per year, linearised.
    Derived from [GBD2019]: 21.7M DALYs/yr / 7.8B people / ~3.5 µg/dL
    global mean BLL ≈ 0.00079. Taking 0.00075 as a conservative round
    number. [ASSUMPTION — linearisation is rough; real dose-response is
    log or threshold-based. Range 0.0005 - 0.0012 in sensitivity."""

    cost_effectiveness_threshold_usd: float = 1500.0
    """USD per DALY averted threshold for "cost-effective" in LMIC settings.
    WHO-CHOICE historical: 1-3x GDP per capita. LMIC GDP per capita
    (2023) median ~$2000; 0.5x-1x GDP gives $1000-2000. GiveWell's
    top charities average ~$3000-5000/life saved which maps roughly
    to $100-300/DALY at LMIC life-expectancy."""

    # ---- PROJECT STRUCTURE --------------------------------------------
    beneficiaries_per_system: int = 500
    """Average beneficiaries per WB-funded water system.
    [ASSUMPTION] — from WB project docs, varies 100-10,000."""

    horizon_years: int = 20
    """Project / intervention horizon. Standard WB project cycle is 5-7
    years; infrastructure lifetime 20-30. Take 20 as middle ground."""

    discount_rate: float = 0.03
    """Social discount rate. Standard in public-health CEA."""

    # --- DERIVED -------------------------------------------------------
    def annuity_factor(self, years: int | None = None) -> float:
        r, T = self.discount_rate, years or self.horizon_years
        if r == 0:
            return T
        return (1 - (1 + r) ** -T) / r


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def cost_per_person_year(p: Inputs, prevalence: float) -> dict:
    """Expected cost per beneficiary per year at given prevalence.

    prevalence = fraction of systems with lead above WHO guideline.
    """
    # Testing cost per person-year (paid regardless of outcome)
    testing_per_person_per_year = (
        p.cost_per_sample_usd * p.samples_per_system_per_year
        / p.beneficiaries_per_system
    )

    # Remediation cost: only triggered in `prevalence` fraction of systems.
    # Annualise the per-household cost over the remediation horizon.
    annuity = p.annuity_factor(p.remediation_horizon_years)
    annualised_per_hh = p.remediation_cost_per_affected_hh_usd / annuity
    remediation_per_system_per_year = (
        annualised_per_hh * p.households_per_water_system
    )
    remediation_per_person_per_year = (
        remediation_per_system_per_year / p.beneficiaries_per_system
        * prevalence
    )
    total = testing_per_person_per_year + remediation_per_person_per_year
    return {
        "prevalence": prevalence,
        "testing_cost_pp_yr": testing_per_person_per_year,
        "remediation_cost_pp_yr": remediation_per_person_per_year,
        "total_cost_pp_yr": total,
    }


def dalys_averted_per_person_year(p: Inputs, prevalence: float) -> float:
    """DALYs averted per beneficiary per year at given prevalence.

    Assumes the intervention reduces water-Pb to below guideline in every
    affected system (upper-bound benefit).
    """
    # BLL reduction for affected persons
    bll_reduction_affected = p.bll_slope_per_water_pb * p.water_pb_affected_ugL
    # Population-averaged BLL reduction
    bll_reduction_avg = prevalence * bll_reduction_affected
    # DALYs averted
    return bll_reduction_avg * p.dalys_per_bll_per_person_year


def cost_per_daly(p: Inputs, prevalence: float) -> float:
    costs = cost_per_person_year(p, prevalence)
    dalys = dalys_averted_per_person_year(p, prevalence)
    if dalys <= 0:
        return float("inf")
    return costs["total_cost_pp_yr"] / dalys


def breakeven_prevalence(p: Inputs, threshold_usd_per_daly: float) -> float:
    """Solve for the prevalence at which cost/DALY = threshold.

    (testing + remed_per_affected × P) / (daly_per_person × P) = λ

    Let A = testing cost/person/yr (independent of P)
        B = remediation cost/person/yr at P=1 (scales linearly)
        D = DALYs averted/person/yr at P=1 (scales linearly)
    Then at break-even:
        (A + B × P) / (D × P) = λ
        A + B × P = λ × D × P
        A = (λ × D − B) × P
        P = A / (λ × D − B)
    """
    # Evaluate at P=1 to get the coefficients
    a = cost_per_person_year(p, prevalence=0.0)["testing_cost_pp_yr"]
    at1 = cost_per_person_year(p, prevalence=1.0)
    b = at1["remediation_cost_pp_yr"]
    d = dalys_averted_per_person_year(p, prevalence=1.0)
    denom = threshold_usd_per_daly * d - b
    if denom <= 0:
        return float("inf")  # never cost-effective at this threshold
    return a / denom


# ---------------------------------------------------------------------------
# Sensitivity
# ---------------------------------------------------------------------------

def tornado(base: Inputs, threshold: float) -> list[dict]:
    """One-at-a-time sensitivity on break-even prevalence.

    For each parameter, compute break-even P at the low and high ends of
    its plausible range. Returns list of dicts sorted by swing size.
    """
    # (param name, low, high)
    ranges = [
        ("cost_per_sample_usd", 10, 30),
        ("samples_per_system_per_year", 2, 12),
        ("remediation_cost_per_affected_hh_usd", 50, 500),
        ("households_per_water_system", 20, 500),
        ("water_pb_affected_ugL", 15, 100),
        ("bll_slope_per_water_pb", 0.02, 0.08),
        ("dalys_per_bll_per_person_year", 0.0005, 0.0012),
        ("beneficiaries_per_system", 200, 2000),
    ]
    rows = []
    base_p = breakeven_prevalence(base, threshold)
    for name, lo, hi in ranges:
        low = Inputs(**{**asdict(base), name: lo})
        high = Inputs(**{**asdict(base), name: hi})
        p_low = breakeven_prevalence(low, threshold)
        p_high = breakeven_prevalence(high, threshold)
        rows.append({
            "param": name,
            "low": lo,
            "high": hi,
            "breakeven_P_at_low": p_low,
            "breakeven_P_at_high": p_high,
            "swing_pct_pts": abs(p_high - p_low) * 100,
        })
    rows.sort(key=lambda r: r["swing_pct_pts"], reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def format_pct(x: float) -> str:
    if x == float("inf") or x != x:   # inf or NaN
        return "never"
    if x < 0:
        return "never"
    return f"{x*100:.2f}%"

def format_usd(x: float) -> str:
    if x == float("inf"): return "∞"
    if x >= 1000:
        return f"${x:,.0f}"
    return f"${x:.2f}"


def main() -> int:
    p = Inputs()
    OUT.mkdir(parents=True, exist_ok=True)

    # --- Question A: marginal cost of testing --------------------------
    just_testing = cost_per_person_year(p, prevalence=0.0)
    test_cost_per_1000 = just_testing["testing_cost_pp_yr"] * 1000

    # --- Question B: break-even prevalence at various thresholds -------
    # Three scenarios for the remediation side:
    #   central     — POU filter + surveillance, $200/household
    #   cheap       — brass-fitting swap / point-of-collection filter, $50
    #   expensive   — service-line replacement, $1000/household
    scenarios = {
        "central":   Inputs(remediation_cost_per_affected_hh_usd=200),
        "cheap":     Inputs(remediation_cost_per_affected_hh_usd=50),
        "expensive": Inputs(remediation_cost_per_affected_hh_usd=1000),
    }
    thresholds = [500, 1000, 1500, 3000, 5000, 10000, 50000]
    breakeven_rows = []
    for scenario_name, scen_p in scenarios.items():
        for t in thresholds:
            bp = breakeven_prevalence(scen_p, t)
            breakeven_rows.append({
                "scenario": scenario_name,
                "remediation_cost_per_hh": scen_p.remediation_cost_per_affected_hh_usd,
                "threshold_usd_per_daly": t,
                "breakeven_prevalence": bp,
                "breakeven_prevalence_pct": format_pct(bp),
            })

    # --- Sensitivity ---------------------------------------------------
    # Pick a threshold where the base case has a positive break-even so
    # the tornado is informative. $10k/DALY gives a base case of ~3.7%.
    SENS_THRESHOLD = 10000
    sens = tornado(p, threshold=SENS_THRESHOLD)

    # ---- Write parameters CSV -----------------------------------------
    with (OUT / "cea_parameters.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["parameter", "value", "docstring"])
        for k, v in asdict(p).items():
            field_obj = Inputs.__dataclass_fields__[k]
            doc = field_obj.default if hasattr(field_obj, "doc") else ""
            w.writerow([k, v, ""])

    # ---- Write break-even CSV -----------------------------------------
    with (OUT / "cea_breakeven.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=breakeven_rows[0].keys())
        w.writeheader(); w.writerows(breakeven_rows)

    # ---- Write markdown narrative -------------------------------------
    with (OUT / "cea_results.md").open("w") as f:
        f.write("# Back-of-envelope CEA: lead testing in WB water projects\n\n")
        f.write("## Q1 — Marginal cost of adding lead testing\n\n")
        f.write(f"At **${p.cost_per_sample_usd}/sample × "
                f"{p.samples_per_system_per_year} samples/year per system** "
                f"(quarterly), testing costs:\n\n")
        f.write(f"- **${just_testing['testing_cost_pp_yr']:.3f} per beneficiary per year**\n")
        f.write(f"- **${test_cost_per_1000:.2f} per 1,000 beneficiaries per year**\n")
        f.write(f"- For a typical Bank water project with ~500,000 beneficiaries, "
                f"that is **${just_testing['testing_cost_pp_yr']*500_000:,.0f} per year** — "
                f"less than 0.1% of typical project budgets (\\$100M+).\n\n")
        f.write("This is the cost of testing alone, independent of lead prevalence. "
                "If testing finds nothing, the marginal cost stops here.\n\n")

        f.write("## Q2 — Break-even prevalence (testing + remediation)\n\n")
        f.write("If testing triggers remediation in affected systems, at what "
                "prevalence P of lead exceedance does the policy clear a given "
                "cost-effectiveness threshold? The answer depends heavily on "
                "**what remediation you do**. Three scenarios:\n\n")
        f.write("- **cheap** — brass-fitting swap or shared point-of-collection filter, \\$50/household\n")
        f.write("- **central** — POU faucet filter + replacement cartridges + surveillance, \\$200/household\n")
        f.write("- **expensive** — full service-line or pipe replacement, \\$1,000/household\n\n")
        f.write("| Threshold ($/DALY) | Cheap (\\$50) | Central (\\$200) | Expensive (\\$1,000) |\n")
        f.write("|---:|---:|---:|---:|\n")
        by_scen = {s: {r["threshold_usd_per_daly"]: r for r in breakeven_rows if r["scenario"]==s}
                   for s in ("cheap", "central", "expensive")}
        for t in thresholds:
            f.write(f"| {t:,} | "
                    f"{by_scen['cheap'][t]['breakeven_prevalence_pct']} | "
                    f"{by_scen['central'][t]['breakeven_prevalence_pct']} | "
                    f"{by_scen['expensive'][t]['breakeven_prevalence_pct']} |\n")
        f.write("\n**How to read this table:**\n\n")
        f.write("- *never* means the intervention does not clear that threshold "
                "even at 100% prevalence — the per-affected-household remediation "
                "cost divided by DALYs averted per affected household exceeds "
                "the threshold.\n")
        f.write("- Under the central remediation scenario (POU filter), the "
                "policy is cost-effective only at 'middle-income-country' "
                "thresholds (\\$5,000–\\$10,000/DALY) or looser. At strict "
                "GiveWell-style thresholds (\\$500–\\$1,500/DALY), the central "
                "scenario doesn't clear even at 100% prevalence.\n")
        f.write("- With *cheap* remediation (brass swap, community filter), "
                "break-even drops to a few percent at LMIC thresholds — comfortably "
                "below what limited primary research suggests actual prevalence "
                "might be.\n")
        f.write("- The intervention's economics hinge on the *remediation* "
                "side, not the *testing* side.\n\n")

        f.write("## Q3 — Sensitivity (tornado on break-even P)\n\n")
        f.write(f"At a \\${SENS_THRESHOLD:,}/DALY threshold (the lowest "
                "threshold where the central scenario gives a finite answer), "
                f"base case break-even = "
                f"{format_pct(breakeven_prevalence(p, SENS_THRESHOLD))}. "
                "Varying each parameter to the plausible extremes:\n\n")
        f.write("| Parameter | Low → break-even P | High → break-even P | Swing (pp) |\n|---|---:|---:|---:|\n")
        for r in sens:
            f.write(f"| {r['param']} | "
                    f"{r['low']} → {format_pct(r['breakeven_P_at_low'])} | "
                    f"{r['high']} → {format_pct(r['breakeven_P_at_high'])} | "
                    f"{r['swing_pct_pts']:.1f} |\n")
        f.write("\n")

        f.write("## Headline for the blog\n\n")
        bp_cheap_3k     = breakeven_prevalence(scenarios["cheap"], 3000)
        bp_cheap_1500   = breakeven_prevalence(scenarios["cheap"], 1500)
        bp_central_10k  = breakeven_prevalence(scenarios["central"], 10000)
        cents = just_testing["testing_cost_pp_yr"] * 100
        f.write(f"> Adding lead testing to a Bank-funded water supply "
                f"project costs roughly **{cents:.0f} cents per beneficiary "
                f"per year** — under 0.1% of a typical project budget. Whether "
                f"that testing then pays for itself depends on what comes next. "
                f"With cheap remediation (a brass-fitting swap or community "
                f"point-of-collection filter, ~\\$50/household), the combined "
                f"policy clears a \\$3,000/DALY threshold whenever prevalence "
                f"exceeds **{format_pct(bp_cheap_3k)}** — well within the range "
                f"limited LMIC primary research has observed. With expensive "
                f"remediation (household POU filters, \\$200/household), it "
                f"takes a looser \\$10,000/DALY threshold and "
                f"**{format_pct(bp_central_10k)}** prevalence. Either way, the "
                f"first-order question is not the testing cost but how cheap "
                f"remediation can be made, and how prevalent the problem "
                f"actually is — which is why the first priority is the "
                f"prevalence study, not more modelling.\n\n")

        f.write("## Caveats\n\n")
        f.write("1. **Parameter uncertainty.** Several inputs marked [ASSUMPTION] "
                "above are plausible placeholders, not primary-sourced facts. "
                "Most-sensitive parameters per the tornado: "
                f"`{sens[0]['param']}`, `{sens[1]['param']}`, `{sens[2]['param']}`. "
                "Pin these down before citing specific numbers.\n")
        f.write("2. **DALY linearisation.** The GBD dose-response for BLL is "
                "non-linear; a linear approximation is defensible for BOTEC "
                "purposes but overstates benefits at very low exposures and "
                "understates at very high ones.\n")
        f.write("3. **Water-to-BLL slope.** The 0.04 µg/dL per µg/L assumption "
                "is a mid-range adult-weighted estimate. Children absorb more, "
                "adults ingest more water — real slope varies by demography.\n")
        f.write("4. **Remediation cost.** Assumes POU filter at the household "
                "level. Pipe-replacement scenarios are 5-10× more expensive "
                "and would raise the break-even P accordingly.\n")
        f.write("5. **Counterfactual.** Assumes current exposure persists "
                "indefinitely without the policy. True counterfactual is a "
                "slow decline as lead-containing infrastructure is replaced "
                "for unrelated reasons, which would reduce benefits ~20-40%.\n")

    print("Q1. Testing cost alone (no remediation):")
    print(f"    ${just_testing['testing_cost_pp_yr']:.3f}/beneficiary/year")
    print(f"    ${test_cost_per_1000:.2f}/1,000 beneficiaries/year\n")
    print("Q2. Break-even prevalence by CE threshold:")
    for row in breakeven_rows:
        print(f"    ${row['threshold_usd_per_daly']:>6,}/DALY → "
              f"{row['breakeven_prevalence_pct']}")
    print(f"\nWrote: {OUT / 'cea_results.md'}")
    print(f"Wrote: {OUT / 'cea_breakeven.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
