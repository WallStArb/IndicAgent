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

## Findings (f6, read-only trace, 2026-11-22)

Source: the 32,194 stored 1d `feature_vectors` rows of the pilot (19 names with rows) and `logs/feature_column_screen_20261121T231639Z.json`. No compute fault found. Distinct failing columns: G1 5, G2 20, G3 24, G6 10 (the 23, 84, 221 counts are column-name pairs). The structure and zone columns named above as G6 failures are registry-declared object-dependent; they appear only under `worst` and do not fail G6 (judged by unit_stats at `feature_complete`).

- G3 (24 columns): measured 0/1 flags, ternary states and sparse magnitudes, not fills: `earnings_season_flag` 0.675 zero with values {0,1}, `opex_flag` 0.954, `quad_witching_flag` 0.984, `above_wk_vwap` 0.489, `in_fib_discount_zone` 0.806, `swing_pattern` and `struct_accel_bias` {-1,0,1}, `reclaim_velocity` {0, 0.6667}, `swing_amplitude_expanding` {0,1}. All lack a `zero_is_state` declaration. Fix is a registry declaration, no threshold change.
- G2 beta trio (`equity_beta_z`, `market_residual_z`, `rate_beta_z`): first finite row is 59 or 60 for all 19 names, declared memory 0. A 60-row window warmup is undeclared. Fix is the declaration.
- G2 and G6 context columns (`vix_z` first finite 19, `sb_corr_z` 29, `tip_tlt_ret_z` 61, `hyg_lqd_ret_z` 901, only for names whose stored start is the first date, 2004-09-10): the context input does not exist yet; every pooled NaN share equals first_finite / n (A 901/5570 = 0.162, AAI 901/1673 = 0.539). Expected, never filled. The gate should start the clock at the input's first availability.
- `hma_slope_z`: declared memory 7,560 rows (252 slopes, one per 30-bar refresh), above every name's history (max 5,571), so it is all NULL for every name at 1d. A calibration fact of `feature.regime.cache_refresh_bars` and `feature.momentum.zscore_window`, not a bug; at 1d the column never exists.
- HMM family (`hmm_*`, 12 columns): first finite 291 for most names (negative gap, passes). AADR (73% post-warmup NaN), AACG (52%) and AAN (15%) are labelled late or not; consistent with the degenerate-occupation gate (`_check_occupation_gate`, segment status 2 to 4), but the segment status is not stored, so not verified. One-name recompute of AADR would confirm.
- `dividend_yield`: all NULL for 13 of 19 names (outside `dividend_event_coverage`: unknown, never zero); pooled 38.9% null.
- Sample: chunk 0 is the 25 first-alphabetical names; 6 had under 252 rows and were not judged, 19 of 25 stored. History across 34,063 symbols (1d tradeable bars before 2026-11-01): p10 87, p25 271, median 777, p75 1,868, p90 3,839 rows; 24% under 252, 56% under 1,000.

## Follow-ups (f6, 2026-11-22)

- Landed 5c8461d81 (declarations, degenerate_input_state, screen clock) and the seven per-column checked states (swing_pattern, in_fib_discount_zone, fib_cluster_strength, swing_amplitude_expanding and _intensity, bars_since_last_sweep, bars_since_last_shift: genuine measured 0.0, declared zero_is_state while staying object dependent). Faults filed: 659 reclaim_velocity, 660 struct_accel_bias; 661 stores the HMM segment status.
- hma_slope_z: the static not_applicable at 1d was replaced by the screen listing a column whose declared warmup exceeds every judged history as not judged (G6 output key not_judged_warmup_exceeds_history).
- Open (small): the context clock should come from the reference input series, not the screened rows (a defect on every name on the same dates is absorbed; the payload now lists the dates).
- P3 notes: the beta and residual first rows are 1d only (intraday rows repeat the daily record, so an intraday screen still fails them); a covered name that never paid a dividend reads constant 0.0 and fails G1.
- Still owed: the pilot-sample numbers (1,000-row rule). History across 34,063 symbols: p10 87, p25 271, median 777, p75 1,868, p90 3,839 rows; 24% under 252, 56% under 1,000.

## Lead ruling (2026-11-22)

The declarations landed (5c8461d81, c409bc86c, 2aa04d1d4); the pilot sample rule (1,000 bars, 65 judged names, hash-ordered selection) is declared in ledger 2026-11-22d. Left before a new run: todos 659 and 660, then the sample reader in the pilot step with the refuse check on `n_names_judged`, then the run (not on the path of the price-derived families).
