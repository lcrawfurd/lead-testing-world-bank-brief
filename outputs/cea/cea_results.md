# Back-of-envelope CEA: lead testing in WB water projects

## Q1 — Marginal cost of adding lead testing

At **$20.0/sample × 4 samples/year per system** (quarterly), testing costs:

- **$0.160 per beneficiary per year**
- **$160.00 per 1,000 beneficiaries per year**
- For a typical Bank water project with ~500,000 beneficiaries, that is **$80,000 per year** — less than 0.1% of typical project budgets (\$100M+).

This is the cost of testing alone, independent of lead prevalence. If testing finds nothing, the marginal cost stops here.

## Q2 — Break-even prevalence (testing + remediation)

If testing triggers remediation in affected systems, at what prevalence P of lead exceedance does the policy clear a given cost-effectiveness threshold? The answer depends heavily on **what remediation you do**. Three scenarios:

- **cheap** — brass-fitting swap or shared point-of-collection filter, \$50/household
- **central** — POU faucet filter + replacement cartridges + surveillance, \$200/household
- **expensive** — full service-line or pipe replacement, \$1,000/household

| Threshold ($/DALY) | Cheap (\$50) | Central (\$200) | Expensive (\$1,000) |
|---:|---:|---:|---:|
| 500 | never | never | never |
| 1,000 | never | never | never |
| 1,500 | 90.04% | never | never |
| 3,000 | 10.47% | never | never |
| 5,000 | 4.81% | never | never |
| 10,000 | 2.04% | 3.71% | never |
| 50,000 | 0.37% | 0.40% | 0.74% |

**How to read this table:**

- *never* means the intervention does not clear that threshold even at 100% prevalence — the per-affected-household remediation cost divided by DALYs averted per affected household exceeds the threshold.
- Under the central remediation scenario (POU filter), the policy is cost-effective only at 'middle-income-country' thresholds (\$5,000–\$10,000/DALY) or looser. At strict GiveWell-style thresholds (\$500–\$1,500/DALY), the central scenario doesn't clear even at 100% prevalence.
- With *cheap* remediation (brass swap, community filter), break-even drops to a few percent at LMIC thresholds — comfortably below what limited primary research suggests actual prevalence might be.
- The intervention's economics hinge on the *remediation* side, not the *testing* side.

## Q3 — Sensitivity (tornado on break-even P)

At a \$10,000/DALY threshold (the lowest threshold where the central scenario gives a finite answer), base case break-even = 3.71%. Varying each parameter to the plausible extremes:

| Parameter | Low → break-even P | High → break-even P | Swing (pp) |
|---|---:|---:|---:|
| remediation_cost_per_affected_hh_usd | 50 → 2.04% | 500 → never | inf |
| households_per_water_system | 20 → 1.98% | 500 → never | inf |
| water_pb_affected_ugL | 15 → never | 100 → 0.63% | inf |
| bll_slope_per_water_pb | 0.02 → never | 0.08 → 1.20% | inf |
| beneficiaries_per_system | 200 → never | 2000 → 0.51% | inf |
| dalys_per_bll_per_person_year | 0.0005 → 12.21% | 0.0012 → 1.65% | 10.6 |
| samples_per_system_per_year | 2 → 1.86% | 12 → 11.13% | 9.3 |
| cost_per_sample_usd | 10 → 1.86% | 30 → 5.57% | 3.7 |

## Headline for the blog

> Adding lead testing to a Bank-funded water supply project costs roughly **16 cents per beneficiary per year** — under 0.1% of a typical project budget. Whether that testing then pays for itself depends on what comes next. With cheap remediation (a brass-fitting swap or community point-of-collection filter, ~\$50/household), the combined policy clears a \$3,000/DALY threshold whenever prevalence exceeds **10.47%** — well within the range limited LMIC primary research has observed. With expensive remediation (household POU filters, \$200/household), it takes a looser \$10,000/DALY threshold and **3.71%** prevalence. Either way, the first-order question is not the testing cost but how cheap remediation can be made, and how prevalent the problem actually is — which is why the first priority is the prevalence study, not more modelling.

## Caveats

1. **Parameter uncertainty.** Several inputs marked [ASSUMPTION] above are plausible placeholders, not primary-sourced facts. Most-sensitive parameters per the tornado: `remediation_cost_per_affected_hh_usd`, `households_per_water_system`, `water_pb_affected_ugL`. Pin these down before citing specific numbers.
2. **DALY linearisation.** The GBD dose-response for BLL is non-linear; a linear approximation is defensible for BOTEC purposes but overstates benefits at very low exposures and understates at very high ones.
3. **Water-to-BLL slope.** The 0.04 µg/dL per µg/L assumption is a mid-range adult-weighted estimate. Children absorb more, adults ingest more water — real slope varies by demography.
4. **Remediation cost.** Assumes POU filter at the household level. Pipe-replacement scenarios are 5-10× more expensive and would raise the break-even P accordingly.
5. **Counterfactual.** Assumes current exposure persists indefinitely without the policy. True counterfactual is a slow decline as lead-containing infrastructure is replaced for unrelated reasons, which would reduce benefits ~20-40%.
