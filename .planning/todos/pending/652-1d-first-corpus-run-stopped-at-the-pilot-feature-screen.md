---
status: pending
priority: P3
filed: 2026-11-22
source: indicagent-1a, corpus run a4f6ad40-e156-4d89-ba83-83b78333a9ad parked by the lead 2026-11-22
owner: lead
---

# The 1d-first corpus run stopped at the pilot feature column screen

## What

Run a4f6ad40-e156-4d89-ba83-83b78333a9ad (scope 1d, commit b373cb0fc) passed `data_gate` and `pin_gate` (pin 23 of 23 checks true, timers quiesced and since released), then the `pilot` step failed on G1-G3: gate failures G1 23, G2 84, G3 221, G6 10. G4-G5 passed (0 failures, 0 errors on 25 names). The run is parked by materiality: the daily residual family reads canonical 1d and `universe_membership` through the panel, not `feature_vectors`, so this run is not on the path to the first counted test.

Pilot sample: the 25 first-alphabetical names (A, AA, AAAP, AAAU, AAAU~0LPXX872, AABA, AACG, AACQ, AACT, AAC~0K1Y3PT9, AAC~1829432, AADR, AADX, AAI, AAIC, AAL, AAMC, AAMI, AAN, AAN~0WCNDCZ6, AAOG, AAOI, AAON, AAOX, AAOZ), 305 columns, 32,194 rows, 17 of 19 judged names. Six names were not screened for short history (min_name_rows 252, min_rows 1000): AACQ, AACT, AADX, AAOG, AAOX, AAOZ.

G6 null share against the 5% limit (worst first): choch_strength 0.884, supply_dist_atr and supply_freshness 0.752, demand_dist_atr and demand_freshness 0.697, zone_friction_score 0.516, bars_since_last_shift and bos_strength 0.509, bars_since_vol_spike_fast 0.444, dividend_yield 0.389, roll_spread 0.383, resistance_age_bars, resistance_strength and sr_resist_dist 0.290, sr_support_dist, support_age_bars and support_strength 0.245, bars_since_vol_spike_slow 0.135, hmm_churn and hmm_duration 0.086 (hmm_entropy and the hmm probabilities 0.086), hyg_lqd_ret_z 0.085; hma_slope_z cannot be measured (no judged name has a row past its warmup). Full report was `logs/feature_column_screen_20261121T231639Z.json` in the run worktree (removed); the numbers above are the record.

## Question

Do the pilot sample rule (first alphabetical names, several under 600 rows) and the 5% null gate fit a 1d scope, and are the structure and zone NaNs warm-up (a swing or zone does not exist yet, so the value is NaN by `no_fill`) rather than compute faults? Nothing was diagnosed; no gate was weakened.

## Done when

A short note settles the question: either the sample rule and null gate are corrected for 1d (longer-history sample, null share judged after warm-up) under a ledger entry, or the NaNs are traced to a compute fault and fixed. Rerun the 1d-first run under a new run id only if the feature layer becomes a counted input.
