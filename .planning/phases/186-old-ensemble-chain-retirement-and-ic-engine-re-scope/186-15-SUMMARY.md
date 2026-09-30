---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 15
subsystem: features
tags: [kernel-registry, feature-factory-split, smc, vp-sr, cross-tf, causality-probe, golden-parity]
requires:
  - phase: 186-12
    provides: price, volume, calendar, control and macro kernels; ExternalInput, path_dependent, compute_kernels
  - phase: 186-13
    provides: the tf external input, regime kernels, golden discipline
provides:
  - SMC (6 stateless kernels plus the AMD cycle) and VP/SR (rolling POC, S/R, swing structure, swing momentum, session VP, session levels) as registry kernels found by discover_kernels()
  - cross-asset and factor-beta builders in kernels/macro.py with daily-grid kernels; cross_asset_series.py deleted
  - CTF and ret_div kernels in kernels/cross_tf.py, a typed close-keyed CtfSeries that compute_batch requires
  - the dormant feature_vector_pipeline reading the registry (startup refusal on an unowned column) and a live cross-asset lookup that shares the batch path's as-of rule
affects: [186-16, 186-24, 186-25, 186-26, 186-27]
tech-stack:
  added: []
  patterns:
    - "None from a helper is NaN plus an _<key>_is_none mask output, so None and a non-finite float stay apart (row_dict_columns in _primitives)"
    - "a kernel that cannot run on the intraday row grid (a daily builder) is probed on its own grid (tests/unit/intelligence/daily_grid_fixtures.py)"
key-files:
  created:
    - src/intelligence/features/kernels/vp_sr.py
    - src/intelligence/features/kernels/smc.py
    - src/intelligence/features/kernels/cross_tf.py
    - tests/unit/intelligence/test_cross_tf_alignment.py
    - tests/unit/intelligence/daily_grid_fixtures.py
    - tests/unit/services/test_feature_vector_pipeline_registry.py
    - .planning/todos/pending/472-ctf-source-builder-hard-coded-constants-not-apr.md
  modified:
    - src/intelligence/feature_factory.py
    - src/intelligence/features/kernels/macro.py
    - src/intelligence/features/kernels/_primitives.py
    - src/intelligence/features/contract/registry.py
    - src/intelligence/features/feature_vector_persistence.py
    - services/backfill_feature_factory.py
    - services/feature_vector_pipeline.py
    - scripts/ops/corpus/ops_ctf_columns_recompute_15m.py
    - tools/check_plugin_invariants.sh
    - tools/vulture_whitelist.py
  deleted:
    - src/intelligence/features/cross_asset_series.py
key-decisions:
  - "The golden fixture was never regenerated: every move is byte-identical and the one CTF fix and the one live-lookup fix change no stored value"
  - "The CTF check found the writer's path causal (todo 243's re-key); the defect was that compute_batch accepted any dict, fixed by a CtfSeries type, not by new values"
  - "None-handling uses a mask for every nullable column instead of classifying each helper by hand; a None in a column not declared nullable raises"
patterns-established:
  - "write the availability test on the unchanged code first, commit it with strict xfail for the failing input, remove the xfail in the fix commit"
requirements-completed: [D-25, D-28, D-01]
duration: about 4h
completed: 2026-09-30
---

# Phase 186 Plan 15: SMC, VP/SR and injected kernels; pipeline on the registry

The D-25 split of `feature_factory.py` is finished. `feature_factory.py` is 3,916 lines (6,113 when this plan started, 8,733 before 186-12); 139 kernels across nine origins (calendar, control, cross_tf, macro, price, regime, smc, volume, vp_sr) produce 310 feature columns, and 3 numeric columns (the cross-sectional rank trio, todo 421) are listed as unowned with a reason. Every code move was byte-identical against the golden fixture, which this plan never touched.

## Commits (branch phase-186-15, merged into main locally; not pushed)

| Step | Commit | Message |
|---|---|---|
| T1 | `bc3c8f1b7` | refactor: VP/SR kernels |
| T1 | `6b1aaaa63` | refactor: SMC kernels |
| T2 | `2699d043c` | refactor: cross-asset and factor-beta builders as macro kernels |
| T2 | `feeecaa60` | test: CTF and ret_div availability tests, written before the move |
| T2 | `49756d47e` | refactor: cross-timeframe kernels (CTF, ret_div) |
| T2 | `85dbb2894` | fix: CTF join accepts only a close-keyed CtfSeries |
| T2 | `1e5435ee0` | docs: record the CTF availability check on todo 450 |
| T3 | `a65bc6f97` | refactor: feature_vector_pipeline imports the kernel registry (D-28) |
| T3 | `e93ee7adc` | test: live cross-asset lookup as-of tests, RED on the date-keyed lookup |
| T3 | `f790fe3dc` | fix: live cross-asset lookup uses the as-of daily close rule |
| Close | `d327c7516` | chore: vulture whitelist for the rebuild-facing helpers, todo 472 |

The commit after `bc3c8f1b7` fixed a binary-pattern-scanner failure that first commit introduced (a `== 1.0` on a mask); `6b1aaaa63` carries the fix.

## D-01 gate

2026-09-30, before any edit: `ps -eo pid,args | grep -E "ic_engine|backfill_feature_factory|regime_writer|rebuild|ic_measure"` (own shell and pytest lines excluded) printed nothing. STATE.md's lane table lists no live or resumable ic_engine corpus run and no feature rebuild. The only processes up were the todo 449 lane (`intraday_chain.sh`, `infrastructure_run_historical_pipeline.py`), which this plan never touched. All edits were made in `/home/bg/dev/indicagent-186-15`. Baseline `test_kernel_registry_parity.py` on the unchanged worktree: 18 tests, 32.4 s.

## Golden status

Byte-identical, not regenerated. `git diff --stat main -- tests/fixtures/kernel_parity/ src/intelligence/research/` is empty; no move commit lists a fixture file. `repro_frozen` was not run: nothing under `src/intelligence/research/` or `statistics/` changed.

## None handling

The plan asked for a per-column class (None only, non-finite only, both). Tracing every helper for every column by hand was not done; instead every nullable column gets both encodings, which is correct in all three classes. A column is nullable when its helper's fallback dict holds None for it, and `row_dict_columns` raises if a helper returns None for any other key. Nullable columns emit NaN plus an `_<key>_is_none` mask (1.0 for None, 0.0 for a number); `compute_batch` rebuilds None from the mask, so a non-finite float still reaches `_guard` as before.

- Nullable, mask emitted (45 columns): session VP 10 (`nearest_hvn/lvn_above/below_dist_atr`, `nearest_hvn_dist_atr`, `va_width_atr`, `distance_to_vah/val_atr`, `poc_rolling_dist_atr`, `poc_session_rolling_divergence_atr`); swing 7; trend 6; fib 4; swing momentum 8; session levels 16 (the VP, swing/trend/fib and swing-momentum groups are the four kernels; session VP and session levels are the two cache-backed ones).
- Never None (plain float columns): S/R 7, order blocks 7, FVG 3, sweeps 4, pools 5, zones 7, BOS/CHoCH 6, AMD 4, and the four VP columns outside the list above.
- Intermediates: `_fvg_midpoint` and `_price_in_premium` (consumed by the zones kernel), `_poc_price_rolling` (NaN for None and for tf 1d).

## Memory and tolerance

No kernel needed a `memory_atol`; every windowed recompute matched the full-series float32 value exactly at both configs (small / production) on 3,000 bars at rows 700, 1200, 1800, 2400, 2999 (500 bars at 4 rows in `test_causality_probe.py`). Effective memory in bars (own plus the ATR chain where the kernel reads it):

| Kernel | own | effective (small / production) |
|---|---|---|
| rolling_poc | `session_vp_rolling_window - 1` = 479 | 479 / 479 |
| support_resistance | `max(max(sr_lookback_by_tf), 120) - 1` = 119 | 399 / 679 |
| swing_structure (swing, trend, fib) | `swing_lookback_bars - 1` = 119 | 399 / 679 |
| swing_momentum | `swing_momentum_lookback_bars - 1` = 59 | 59 / 59 |
| order_blocks, fair_value_gaps | 99 | 379 / 659 |
| liquidity_sweeps, bos_choch | 119 | 399 / 679 |
| liquidity_pools | 149 | 429 / 709 |
| supply_demand_zones | 149 (chains through FVG and pools) | 578 / 858 |
| factor_beta_daily | `factor_beta_window + factor_beta_zscore_window + 2` = 42 / 314 | 42 / 314 |
| ctf_passthrough | 0 | 0 |
| cross_tf_divergence | 0 | 3 |

Spot check: factor_beta_daily at memory 188 and 60 raises `MemoryViolation`; at 314 it holds.

## Path-dependent kernels added (reasons)

- `session_vp`, `session_levels`: session accumulator state, its session-boundary resets and the exclusion of row 0 depend on where the series starts.
- `amd_cycle`: the overnight-range accumulator and its cycle resets depend on the series start.
- `cross_asset_daily`: `flight_quality` anchors to the first available close, and the running z-score histories start at the first record date.
- `ctf_source`: cumulative VWAP and the HMM forward pass run from the series start.

`PATH_DEPENDENT` in `test_feature_kernels.py` is now twelve (the 186-12 seven plus these five), counted by a test that a person changes on review.

## Cache-backed handoff to 186-25

`compute_batch` still runs these on its own `FeatureCache` (the kernels replay a fresh cache, are registered, and are checked equal in `test_feature_kernels.py`; switching the read changes results for a caller passing a pre-warmed cache, so it belongs with the retirement of the cache-driven loop): session VP (`_derive_session_vp`), session levels (`_derive_session_levels`) and the AMD cycle (`_derive_amd_cycle`), joining 186-12's list (hurst, shannon, garch_ratio, hma_slope_z, adx, above_wk_vwap and their products). The callers of `build_cross_asset_series`, `build_symbol_beta_series` and `ctf_series_by_close` keep calling the builders directly; the daily-grid kernels and `cross_asset_records`, `beta_records` and `daily_reference_grid` exist for 186-25's warmup and probe and are whitelisted for vulture until it lands.

## compute_batch timing

Real parity sample, SPY, four timeframes, best of 3 (sum): main at start 6.67 s, after the SMC commit 6.75 s (+1%). No slowdown over 10%. Probe runtime for the heaviest new kernels at 3,000 bars: order_blocks 1.4 s, liquidity_sweeps 1.3 s, session_vp 1.25 s; all five probe rows run, no subset needed.

## Mutation checks (not committed)

- Order-block mutation: adding 1e-3 to the first output of `_compute_order_blocks` in `kernels/smc.py` fails the parity test (`ob_bull_dist_atr: row 0 got 0.001 golden 0.0`). It does not fail test (b) (registered outputs equal compute_batch), because compute_batch now reads the same kernel; 186-12 found the same. The added `test_stateless_structure_kernels_equal_direct_helper_calls` (helpers called directly on the loop's windows, every 7th row) does fail (`('ob_bull_dist_atr', 1)`), so two tests bite, not (b).
- Un-re-keyed CTF dict in Test A: Tests A and B and the real-data variant fail.

## CTF and ret_div availability (task 2)

Written and run on the unchanged code first (`feeecaa60`). Result: all pass except the four strict xfails.

- Test A (5m to 1h), Test B (1h to 1d), Test C (1m to 5m), the four scenarios (opening 30-minute partial hour, a missing 1h bar, a weekend gap, a half-day) through the writer's own path (`_build_ctf_series`, the re-key, `compute_batch`), and the real-data variant (50 evenly spaced rows of SPY 5m, QQQ 15m and SPY 1h; every HTF bar not closed by the row's bar end replaced by seeded random OHLCV): unchanged values on every row. Todo 243's re-keying does make the batch join causal; no stored CTF or ret_div value carries a lookahead from it.
- `test_start_keyed_dict_lets_an_intraday_row_read_an_unfinished_htf_bar` passed on the unchanged code: handed the dict `_build_ctf_series` returns, `compute_batch` gave the 5m row at 15:05 the 15:00 to 16:00 hour bar that closes at 16:00 and its `ctf_momentum`.
- RED: `test_row_reads_only_htf_bars_closed_by_its_bar_end` on that start-keyed input fails in all four scenarios, recorded as strict xfail:
  `assert 2022-06-01 14:00 UTC <= 2022-06-01 13:35 UTC + 0:05:00` (the row at 13:35 read the bar that closes at 14:00).
- Mutation without the re-key (above) fails Test A, Test B and the real-data variant.

Fix (`85dbb2894`): `ctf_series_by_close` returns a `CtfSeries`; `ctf_row_inputs` and `compute_batch` raise `TypeError` for anything else (tested for a plain dict, the `_build_ctf_series` output and direct construction). The close-bound test passes for all four scenarios; the xfails became passing tests. No value changed, so there is no golden regeneration commit and no per-case changed-column list (every case empty); the 15m recompute script now calls `ctf_series_by_close` and `ctf_row_inputs` instead of its own copy of the join (todo 273). Todo 450 carries the dated "CTF check (186-15)" section.

The asymmetry stays: CTF reads HTF bars closed by the LTF bar start, the macro rule reads daily records available by the bar end; the CTF form is stricter by at most one LTF bar at a boundary, and changing it would change values without fixing a lookahead.

## D-08 greps

- `cross_asset_series` (src, services, scripts, tests, docs): importers were `services/backfill_feature_factory.py`, `services/feature_vector_pipeline.py`, `src/intelligence/feature_factory.py`, three test modules plus the parity reference, `test_macro_alignment.py`; all repointed. `infrastructure_context_features_writer.py` and `scripts/analysis/` never imported it (the writer has its own local builder; `scripts/analysis/` no longer holds an importer after 186-16). Two `docs/ideas/` paths updated. `grep -rn "features.cross_asset_series" --include=*.py src services scripts tests | wc -l` returns 0.
- `CtfValues` (renamed `CtfRecord` for the suffix taxonomy), `_build_ctf_series`, `_rekey_ctf_series_to_actual_close`, `_build_ltf_return_series`: users were `services/backfill_feature_factory.py`, `scripts/ops/corpus/ops_ctf_columns_recompute_15m.py`, `test_ctf_momentum_live_batch_parity.py`, `test_backfill_feature_factory.py`, `test_feature_factory_batch.py`; all repointed to `kernels/cross_tf.py`.

## Live cross-asset lookup RED (task 3)

Tests first (`e93ee7adc`) against the date-keyed lookup, recorded as strict xfail:

- 10:00 EST bar on d reads the prior day's record: `vix_z: 2.0 != 1.0` (read d's record, closed at 16:00 that day).
- bar at 01:00 UTC on d+1 reads the ET evening date: `vix_z: 3.0 != 2.0` (read d+1).
- bar before any close is available reads the default: `vix_z: 2.0 != 0.0`.
- the 5m bar ending at 16:00 ET reads d: passed before and after.

Fix (`f790fe3dc`): `daily_asof_index` in `kernels/macro.py` is the one availability rule; `align_daily_asof` and the pipeline's `_cross_asset_record_for_bar(bar_ts, tf)` both call it, with the availability instants computed once per loaded series. The method is renamed from `_cross_asset_record_for_date`, which no longer takes a date. Five existing tests keyed on dates moved to bar timestamps and cite the fix in their docstrings.

## Registry coverage

Origins: calendar, control, cross_tf, macro, price, regime, smc, volume, vp_sr (D-25's seven plus control and cross_tf). `feature_columns()` (310) plus `UNOWNED_COLUMNS` equals the numeric `_ALL_COLUMN_NAMES` set exactly (`test_feature_columns_plus_unowned_equal_schema`; the regime kernels' non-schema outputs are the regime writer's own columns).

| UNOWNED column | reason |
|---|---|
| `momentum_rank_z`, `volatility_rank_z`, `volume_rank_z` | todo 421: hard-coded None in feature_factory; a cross-sectional rank needs the whole universe per bar; 186-24 drops the column |

The Asian session pair is now owned by the session-levels kernel; `regime_rolling` is not a numeric FeatureVector column. The pipeline refuses to start on a gap (`_require_registry_column_ownership`, tested directly because `make_agent` bypasses `_prewarm_threshold_config`).

## Deviations from Plan

**1. [Rule 3 - Blocking] `CtfSeries` needed the class-suffix allowlist and `CtfValues` a rename.** The pre-commit class-naming check rejected both. `CtfValues` became `CtfRecord`; `Series` joined `_ALLOWED_SUFFIXES` in `tools/check_plugin_invariants.sh` (single canonical list), as 186-08 and 186-12 did for file naming. The plan names the type `CtfSeries`; kept.

**2. [Rule 3] Kernels cannot carry logging; the builders' partial-coverage log stays in a wrapper.** `build_cross_asset_series` now wraps a pure `_cross_asset_records` that the kernel calls. Same output and same log for every existing caller.

**3. [Rule 2] Daily-grid kernels are probed on their own grid.** On an intraday row grid several rows share a date, so a date-keyed builder sees later rows of the same date and the probe flags it. `cross_asset_daily` and `factor_beta_daily` run through `daily_grid_fixtures.py` in `test_feature_kernels.py` and `test_causality_probe.py` (every kernel is still probed, no exemption). A new `Alignment.DAILY_REFERENCE_GRID` with its own truncation runner in `test_macro_alignment.py` types the `ref_*_close` externals.

**4. `gradient-exempt` comment on one moved line.** `ctf_regime[i + 1] = 0.0 if label == 0 else 1.0` tripped the binary pattern scanner once it sat under `src/`; it is an HMM state label, so the line carries `# gradient-exempt: HMM state label` (comment only).

**5. Vulture whitelist.** `cross_asset_records`, `beta_records` and `daily_reference_grid` have tests and no production caller until 186-25; a local variable named `ctf` in the deleted copy of the join also used to mask `_.ctf` in `src/core/memory/writer.py`. Four whitelist entries with reasons; vulture output otherwise equals main's.

**6. Plan acceptance literal not met.** `grep -c "cross_asset_series" services/feature_vector_pipeline.py` returns 4 (not 0): the matches are `build_cross_asset_series` (the plan keeps that public function and the pipeline calls it) and the methods `_load_cross_asset_series` and `_refresh_cross_asset_series`. No import of the deleted module remains (`grep -rn "features.cross_asset_series"` returns 0 across src, services, scripts, tests). `_cross_asset_record_for_date` was renamed `_cross_asset_record_for_bar`.

**7. Test (b) cannot detect a wrong stateless kernel** (both sides read the kernel), as in 186-12; an independent test was added (see mutation checks).

**8. Step order.** The move commits were grouped as the plan lists (VP/SR, SMC, builders, tests, CTF move, fix); the first VP/SR commit carried one scanner failure fixed in the next commit, noted above.

## Manual review pass

`/simplify` and `/review` cannot be invoked from an executor; a careful manual pass was done over the diff (stale comments removed from `compute_batch`, unused imports cleaned, `_kernel_row` typed `dict[str, Any]` because `_merge_structural_fields`' parameter types differ per group). The coordinator runs both after this lands.

## Verification

- `pytest tests/unit/ -q` on the branch worktree: see the merged-main line below.
- ruff, black clean on every touched file (two pre-existing unsorted-import findings in `tests/unit/research_tools/test_repro_frozen.py` and `tests/unit/scripts/test_bar_campaign_preflight.py` are not mine and were left).
- mypy: `mypy src/ --ignore-missing-imports | mypy-baseline filter` reports `new: 0`; per-file message counts differ from main only by the three moved "Unsupported operand" errors (feature_factory.py to vp_sr.py) and one fewer "Argument 2" in feature_factory.py.
- vulture: equal to main after the four whitelist entries.
- `tests/unit/test_todo_priorities_link_integrity.py` green with todo 472 added.

## Adjacent findings not fixed

- todo 472 (P3, PRIORITIES row added): `_build_ctf_series` keeps an HMM observation window of 20, a cold-start volatility of 0.005 and numeric guards inline; they move stored `ctf_regime_align`, so the APR mandate applies; held back because the move had to be byte-identical.
- `feature_cache._HMM_K` and `_hmm_forward_step` (used by the CTF series) carry the same question; covered by 472.

## Known Stubs

None.

## Threat Flags

None. No new endpoints, auth paths or schema changes.

## Self-Check

See the merged-main record appended after the merge.
