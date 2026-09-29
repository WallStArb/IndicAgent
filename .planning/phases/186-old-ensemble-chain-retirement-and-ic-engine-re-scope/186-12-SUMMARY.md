---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 12
subsystem: features
tags: [kernel-registry, feature-factory-split, causality-probe, golden-parity, lookahead-fix]
requires:
  - phase: 186-08
    provides: kernel registry, causality probe, golden parity fixture
provides:
  - price, volume, calendar, control and macro kernels under src/intelligence/features/kernels/ (117 kernels, 190 feature columns, 7 intermediates), found by discover_kernels() with no registry edit
  - registry extensions for real kernels (ExternalInput, path_dependent, memory_atol, acausal_control, compute_kernels, feature_columns)
  - feature_factory.compute_batch and _precompute_series read every delegated column from the registry
  - as-of alignment of the daily cross-asset and beta records (align_daily_asof), gap_z alignment fix
affects: [186-13, 186-14, 186-15, 186-25, 186-26, 186-27]
tech-stack:
  added: []
  patterns:
    - "kernel modules import FeatureFactoryConfig under TYPE_CHECKING only; feature_factory calls default_registry() inside functions, never at import"
    - "code-move commits leave the golden fixture untouched; a behavior change is a fix commit plus a golden regeneration commit that names the reason"
key-files:
  created:
    - src/intelligence/features/kernels/_primitives.py
    - src/intelligence/features/kernels/calendar.py
    - src/intelligence/features/kernels/control.py
    - src/intelligence/features/kernels/price.py
    - src/intelligence/features/kernels/volume.py
    - src/intelligence/features/kernels/macro.py
    - tests/unit/intelligence/test_feature_kernels.py
    - tests/unit/intelligence/test_macro_alignment.py
    - .planning/todos/pending/461-gap-z-read-the-next-bars-open.md
  modified:
    - src/intelligence/feature_factory.py
    - src/intelligence/features/registry.py
    - src/intelligence/features/causality_probe.py
    - tests/unit/intelligence/test_kernel_registry.py
    - tests/unit/intelligence/test_causality_probe.py
    - tests/unit/test_feature_factory.py
    - tests/unit/services/test_backfill_feature_factory.py
    - tests/fixtures/kernel_parity/ (manifest, real_golden, real_golden_sample, synthetic_golden)
    - tools/check_plugin_invariants.sh
    - docs/research/summary-cards/cache-feature-vectors-v1.md
    - .planning/todos/PRIORITIES.md
key-decisions:
  - "Moved code is byte-identical against the 186-08 golden on every code-only commit; the two behavior fixes each have their own fix and golden commits"
  - "gap_z was fixed in this plan, not deferred: the probe the plan mandates failed it, and the plan requires the probe to pass every kernel except the canary"
  - "compute_batch keeps reading the cache-backed columns (hurst, shannon, garch_ratio, hma_slope_z, adx, above_wk_vwap and their two products) from the cache; their kernels are registered and parity-tested, and switching the read is left to 186-25"
patterns-established:
  - "KernelRegistry.compute_kernels is the one runner used by compute_batch, _precompute_series, the probe and (later) the rebuild"
requirements-completed: [D-25, D-26, D-01, R-11]
duration: 55min
completed: 2026-09-29
---

# Phase 186 Plan 12: Split price, volume, calendar, control and macro out of feature_factory into registry kernels

feature_factory.py drops from 8,733 to 6,187 lines: 117 registry kernels now compute the price, volume, calendar, canary and macro columns, `compute_batch` and `_precompute_series` read them through `compute_kernels`, and the split is byte-identical against the golden. The probe the plan mandates also found two real lookaheads (the macro records and `gap_z`); both are fixed in their own commits.

## Commits (branch phase-186-12)

| Step | Commit | Message |
|---|---|---|
| Task 1 | `a96b4fba4` | refactor: shared kernel primitives module; registry external inputs and memory classes |
| Task 1 | `d03d7fc01` | refactor: calendar and control kernels; compute_batch delegates them |
| Task 2 | `842561991` | refactor: price dynamics kernels |
| Task 2 | `c6544e9d3` | refactor: volume and flow kernels |
| Task 3 | `66baa3b18` | refactor: macro kernels (byte-identical move) |
| Task 3 | `973ed70e3` | fix: align daily cross-asset and beta records as-of the daily close (same-day lookahead) |
| Task 3 | `cedec8f3e` | test: regenerate kernel parity golden after the macro alignment fix |
| Extra | `9840009aa` | fix: gap_z row i no longer reads bar i+1's open (one-bar lookahead) |
| Extra | `06ea62f59` | test: regenerate kernel parity golden after the gap_z alignment fix |
| Extra | `db4ef4e80` | docs: close todo 450, file todo 461 (gap_z lookahead), record both on the feature_vectors card |
| Cleanup | `22a9e8ee9` | refactor: drop section banners for moved code; use bounded_window_bars directly |

## Preconditions and D-01 gate

- 186-08 was merged (`registry.py` and `tests/fixtures/kernel_parity/manifest.json` present on main at 759abc7d5).
- D-01 gate, `ps aux | grep -E "ic_engine|backfill_feature_factory|regime_writer|rebuild|ic_measure" | grep -v grep` at 2026-09-29 14:05 EDT: no output. STATE.md's lane table lists no live or resumable ic_engine corpus run or feature rebuild. The only processes running were the todo 449 backfill lane (`intraday_chain.sh`, `intraday_htf_lane.sh`, `infrastructure_run_historical_pipeline.py`), which this plan never touched.
- Baseline before any change: `test_kernel_registry_parity.py` passes on the unchanged worktree in 33.5 s (18 tests).
- All edits were made in `/home/bg/dev/indicagent-186-12`; no file was created or edited in the main checkout (the timing runs below executed main's code read-only with `PYTHONDONTWRITEBYTECODE=1`).

## What was built

- Registry (`registry.py`, `causality_probe.py`): `ExternalInput` and module `EXTERNAL_INPUTS` (duplicates and collisions with outputs raise), `Kernel.path_dependent` with a required reason, `memory_atol`, `acausal_control`, `compute_kernels(registry, inputs, config, outputs=None)`, `feature_columns()`, `is_path_dependent()`. `feature_memory_bars` raises for a path-dependent kernel or any kernel downstream of one, naming the reason. `probe_registry` now returns a status per kernel (`ok`, `path_dependent_skipped_memory`, `acausal_control_detected`) and fails if an acausal control is not caught.
- Kernels: `_primitives.py` (shared rolling and ATR helpers, `ts_ns_to_datetimes`, `wilder_memory_bars`, `bounded_window_bars`), `calendar.py` (4 kernels, 32 outputs), `control.py` (3 kernels, `symbol` external, `canary_acausal_placebo` is the control), `price.py`, `volume.py`, `macro.py` (10 `ext_*` externals, pass-through, two products, `align_daily_asof`). All moved bodies are unchanged text; kernel loops call the same scalar helpers on the same slices as the old loop.
- `feature_factory.py`: `compute_batch` runs one `compute_kernels` call for the series and every delegated column and reads row i; `_precompute_series` (used by `compute()`) reads the same kernels. Moved helpers are re-exported so existing imports keep working.

## Verification

- Golden parity: `test_kernel_registry_parity.py` (18 tests) is byte-identical on every code-only commit (`d03d7fc01`, `842561991`, `c6544e9d3`, `66baa3b18`), about 33 s each run. It is red only between a fix commit and its regeneration commit, as the plan expects, and green on `cedec8f3e`, `06ea62f59` and HEAD.
- Mutation check (not committed): adding 1e-3 to the output of the moved `_momentum_z_series_full` made the parity test fail (`momentum_z_fast: row 0 got 0.001 golden 0.0`). Test (b) in `test_feature_kernels.py` did not fail: once `compute_batch` delegates, both sides of (b) read the same kernel, so (b) cannot detect a wrong kernel; the golden does. (b) still checks the cache-backed `above_wk_vwap` against an independent path and every delegated column against the batch assembly.
- Causality probe and memory check: every kernel passes at its declared memory on 3,000 synthetic bars under both configs (the manifest's small-window config and the production snapshot), except `canary_acausal_placebo`, which the probe detects. Spot check: shortening `vol_percentile` memory by 5 makes `MemoryViolation` fire on both configs.
- Full `pytest tests/unit/ -q` on the branch (worktree): green, 2 skips (unchanged). Full `pytest tests/unit/ -q` on merged main (10967cd67, run in the main checkout): green, exit 0, the same 2 skips.
- `git diff --stat main -- services/ src/intelligence/research/ src/intelligence/features/cross_asset_series.py`: empty. Migrations: none.
- `repro_frozen.py` was not required: nothing under `src/intelligence/research/` or `statistics/` changed.

### Memory and tolerance table

No kernel needed a non-zero `memory_atol`. At the probed rows (700, 1200, 1800, 2400, 2999) every windowed recompute matched the full-series float32 value exactly, including the cumsum-based rolling statistics and the Wilder recursions. Declared memory in bars, effective (own plus the longest upstream chain), small config / production config:

| Kernel group | small / production |
|---|---|
| calendar_*, canary_*, macro_pass_through, bar_shape, range_to_close | 0 / 0 |
| atr_wilder, atr_valid, range_vs_atr, informed_flow | 280 / 560 (`40 x adx_period`, Wilder seed weight below e^-40) |
| atr_z, ret_vol_ratio_fast, vol_velocity_z, vol_of_vol | 310, 310, 331, 350 / 812, 812, 827, 852 |
| gap_z | 312 / 814 |
| momentum_z_fast, mid, slow | 35, 50, 90 / 257, 272, 312 (+ velocity kernels 21 bars each) |
| rsi_fast, mid, slow | 287, 574, 1148 / 287, 574, 1148 (Wilder) |
| ret_skew_z, ret_acf1_z, ret_kurtosis_z | 31, 26, 61 / 313, 283, 343 |
| dist_from_high/low fast, slow | 300, 330 / 580, 610 |
| dollar_vol_z, vol_percentile, obv_z, amihud_illiq_z | 20, 20, 21, 21 / 252, 252, 253, 253 |
| price_vol_corr, vol_asymmetry_z | 31, 41 / 505, 505 |
| cmf, bounded_window_scalars (range_position, vol_ratio, cci, aroon) | 40 / 40 |
| bars_since_* | 20 to 101 / 20 to 252 |

186-25's warmup reads these from `feature_memory_bars`; the full per-kernel list is `default_registry().kernels` with `effective_memory_bars`.

### Path-dependent kernels (no finite memory; `feature_memory_bars` raises)

- `calendar_above_wk_vwap`: weekly accumulator state and row-0 exclusion depend on the series start; the weekly reset bounds it in calendar time, but the bound in bars depends on tf, which a kernel does not receive.
- `ret_autocorr` (`ret_autocorr_1`, `ret_autocorr_5`), `abs_ret_autocorr`, `variance_ratio` (fast, slow): expanding full-history estimators anchored at the series start.
- `streak_z`: the signed streak length is unbounded.
- `vwap_dev_sigma`: running VWAP and running deviation statistics accumulate from the series start.
- `bar_statistics_refresh` (`hurst`, `shannon`, `garch_ratio`, `hma_slope_z`, `adx`): refresh cadence counts from row 0 and the HMA slope history accumulates across refreshes.
- Downstream of these (raise through `is_path_dependent`): `vwap_dev_sigma_velocity`, `momentum_trend_product`, `reversion_hurst_product`, `variance_ratio_momentum_product`.

### compute_batch timing (real parity sample, SPY, 4 timeframes, best of 3)

Before (main): 1.77, 1.77, 1.86, 1.84 s (sum 7.24 s). After (branch HEAD before cleanup): 1.74, 1.70, 1.81, 1.78 s (sum 7.03 s), a 3% speedup; no slowdown, so no kernel to report.

## Deviations from Plan

### Auto-fixed and added (Rule 1, Rule 3)

**1. [Rule 1 - Bug] gap_z looked ahead by one bar, found by the mandated causality probe**
- **Found during:** Task 2, first probe run on the moved `gap_z` kernel.
- **Issue:** `_gap_z_series_full` wrote the z-score of the gap at bar k+1 into row k, so stored `gap_z` at bar T was built from `open[T+1]`, and the last row of every batch and every live `compute()` call was 0.0. All timeframes, 1d included. Proved by a failing test first (row 300 moved from -1.935 to 1.105 when bar 301's open changed; last row 0.0).
- **Fix:** own fix commit `9840009aa` (row k takes the score of the gap at bar k), golden regenerated in its own commit `06ea62f59` (only `gap_z` changed, on every case; live capture reproduced the config and inputs exactly). The code-only commits carried it as a known-acausal entry that the probe test asserted still failed, so no move commit changed a byte.
- **Follow-up:** todo 461 filed with its two dependents (see the caveat trace).

**2. [Rule 3 - Blocking] Pre-commit file naming check rejected `_primitives.py`**
- The plan pins the name (the leading underscore keeps discovery from importing it). Exempted that one path in `tools/check_plugin_invariants.sh` (`file-naming`), in commit `a96b4fba4`. Same pattern as 186-08's exemption.

**3. Tests outside the plan's list needed updating**
- `tests/unit/services/test_backfill_feature_factory.py::test_cross_asset_from_dict_not_cache` keyed its record on the bars' own date; it now keys on the previous day (fix commit).
- `tests/unit/test_feature_factory.py`: the no-look-ahead source scan now covers the kernel modules (the canary placebo moved), and `TestGapZAtrFloor` moves its row indexes one bar later (regeneration commit).

**4. `compute_reference` not repointed**
- 186-08's note said to repoint `kernel_parity_reference.compute_reference` at the registry path. It calls `FeatureFactory.compute_batch` and `_compute_symbol_tf`, which now run on the registry, so the golden already exercises the registry path; the file is unchanged, as is `tests/fixtures/kernel_parity/` in every code-only commit.

**5. Bar-end offset for 1m**
- `align_daily_asof` uses `TF_DURATIONS` (bar start plus duration) for 5m and up and offset 0 for 1m, instead of `TF_SECONDS`. `service_utils` documents that 1m `ts` is the close time; offset 0 is exact for that and conservative if 1m `ts` were a start. Unknown tf raises `ValueError`.

**6. Golden regeneration reused the stored inputs**
- The capture script re-queries the database. Both regenerations ran it into a scratch directory first and compared: manifest config snapshots and `real_inputs.npz` were identical to the fixture, so only the fix moved the bytes. `real_inputs.npz` was not rewritten. The manifest records `regenerated_from`, `regeneration_reason`, `changed_columns` and a `regeneration_history`.

**7. `probe_registry` return type**
- Returns name to status string (plan-specified) instead of name to memory; 186-08's chain test was updated.

## Macro alignment fix

- RED (against `66baa3b18`): `test_same_day_close_does_not_reach_a_10am_row` failed with `assert 0.9733664700143244 == 4.170333908256634`: vix_z at 10:00 EDT on d changed when d's SPY close changed.
- After the fix: the 10:00 ET row reads d-1; the 15:55 ET 5m row (bar end 16:00) reads d; a 21:00 UTC row reads d, never d+1; 1d rows read their own date; SPY `equity_beta_z` and TLT `rate_beta_z` stay None; a row with no available record gets the default (0.0, betas None); unknown tf and unsorted dates raise (12 tests).
- Changed columns in the golden (`cedec8f3e`), identical set on every intraday case except where a symbol's own beta is None: `vix_z`, `flight_quality`, `yield_slope_z`, `tip_tlt_ret_z`, `hyg_lqd_ret_z`, `sb_corr_fast`, `sb_corr_slow`, `sb_corr_z`, `equity_beta_z` (not SPY), `rate_beta_z` (not TLT), `yield_slope_momentum_product`, `vix_reversion_product`. Every 1d case, the synthetic case and every other column: unchanged. SPY and TLT are in the sample and their beta digests are equal before and after the macro move commit (`66baa3b18`), which confirms a NaN beta on the kernel grid only ever came from None.
- gap_z regeneration (`06ea62f59`): `gap_z` only, all 17 cases.

## Caveat trace

- Macro columns (todo 450, closed): grepped `docs/research/construction-verdict-ledger.md`, `docs/research/summary-cards/`, `scripts/research/` and `src/intelligence/research/` for the twelve names: no dependent. Recorded under known defects on the `cache-feature-vectors-v1` card (`tests/unit/test_summary_cards.py` green). Todo 450 moved to `completed/` with the closure note and its PRIORITIES row removed; `test_todo_priorities_link_integrity.py` green.
- gap_z (todo 461, new, pending, P1): dependents are `construction-verdict-ledger.md` lines 155-169 (the per-feature IC read: "95/232 broad support", "strongly negative intraday"; a gap at the close of T followed by an open-to-open label starting at open[T+1] is the mean-reversion pattern that read found, so the intraday effect is likely the leak) and the `legacy-n1-nonlinear-interaction-combiner` card (fold 1 breaches G1 on `gap_z`). Both are research-lane docs and were not edited; the coordinator should relay to the research lane. The defect is also on the `cache-feature-vectors-v1` card.

## Handoffs

- 186-25: the cache-backed columns stay on the cache path in `compute_batch` (`hurst`, `shannon`, `garch_ratio`, `hma_slope_z`, `adx`, `above_wk_vwap`, `momentum_trend_product`, `reversion_hurst_product`). Their kernels (`bar_statistics_refresh`, `calendar_above_wk_vwap`, `cache_products`) replay a fresh cache and are parity-tested against the cache path in `test_feature_kernels.py`; switching the read changes results for callers passing a pre-warmed cache and drops the cache side effects some tests rely on, so it belongs with the retirement of the cache-driven batch loop. Rebuild must compute the path-dependent kernels from the series start.
- 186-15: `ctf_by_ts` is looked up with `bisect_right(ctf_ts_list, bar_ts) - 1` on higher-timeframe bar keys. If those keys are higher-timeframe bar starts, an intraday row reads an unfinished higher-timeframe bar. Prove it with the same failing-test approach when the CTF kernels move.
- 186-14 and 186-26: per-kernel code key can hash `Kernel.module`; stored `feature_vectors` still carry the macro and `gap_z` defects until the rebuild.
- Live path: `FeatureFactory.compute()` now returns a real `gap_z` on the last bar (it was always 0.0 before); expect a one-time shift in live `gap_z`.

## Known Stubs

None.

## Threat Flags

None. No new endpoints, auth paths or schema changes; `tools/check_plugin_invariants.sh` gained one path exemption.

## Self-Check: PASSED

All files listed under key-files exist on the branch and every commit in the table exists (`git log main..phase-186-12`).
