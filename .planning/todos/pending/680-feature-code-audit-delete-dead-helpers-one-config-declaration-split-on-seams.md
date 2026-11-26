---
status: pending
priority: P3
filed: 2026-11-26
source: read-only audit of src/intelligence/features and research/feature_inputs.py (lead brief 2026-11-26); grep, AST scan, contract tests and two light SELECTs, no edit to code
---

# Feature code audit: delete the dead helpers, one declaration per config field, split only on seams

## What

An audit of the feature code at 33e2c8f94 (fast-forwarded to c6a145f49). Every item below edits a module inside the rebuild's import closure (`kernels/`, `contract/`, `feature_factory_config.py`, `feature_vector*.py`) or the research lane (`feature_inputs.py`), so nothing lands while the corpus pilot, `stage_1d` or the todo 471 measure is live or resumable (`code_content_key`). Items already owned elsewhere are pointed to, not repeated: 472 (vp_sr S/R lookback and cap), 474 (neutral fills), 475 (symbol branches), 550 (percentile kernel), 558 (redundancy groups), 601 (consumer graph, vulture whitelist), 606 (registration CI check), 665 (ic_measure column list), 674 (pass-through reach), 477's idea (shared pivot pass, decision log 2026-11-26).

## Findings

Size and dead code:

1. `kernels/price.py:250-273`: `_rsi` and `_rsi_wilder` have no production caller; only `tests/unit/intelligence/test_feature_factory_p7.py:26,173-193` pins them, and they return 50.0 on a cold start where the stored RSI (`kernels/_primitives.py:59-66`) returns NaN. Two RSIs with opposite no_fill contracts.
2. `kernels/_hmm.py:327-368` (`_build_obs_matrix`) and `398-438` (`_build_obs_matrix_volatility`): callers are tests and `scripts/debug/analysis/debug_bic_k_selection.py` (last touched 2026-08-03). The comment at `_hmm.py:38-45` says 186-16 deletes them with the pilots; it never did. With them go the defaults `_DEFAULT_COVARIANCE_RIDGE` and `_DEFAULT_MOMENTUM_VOL_FLOOR` (`_hmm.py:46-47`); the walk-forward fit already passes the APR ridge (`_hmm.py:988-1002`).
3. `days_to_month_end` is still computed per row (`kernels/calendar.py:300,345`), carried in `feature_vector.py:208` and `feature_vector_persistence.py:83`, but its concept is deprecated and `feature_vectors` does not store it (the registry has 308 feature columns, the table 305 numeric; the gap is this column plus the two text regime labels).
4. `kernels/price.py:1703-1705`: the `else np.ones(len(c))` branch of `vol_ratio` is unreachable, since `bounded_window_bars` is a max that includes `vol_long_bars` (`kernels/_primitives.py:76-84`).
5. `FeatureVector` (`feature_vector.py`, 749 lines, 284 fields) states 285 fields at line 1 and 300 at lines 13 and 102. Once 665 moves ic_measure to `feature_vectors_numeric_columns()`, its remaining readers are the persistence name tuple and tests; `KERNEL_ONLY_COLUMNS` (`contract/registry.py:616-630`) exists only to reconcile it.

Duplication (config, registry, naming):

6. Each config key is written four times: the class docstring list (`feature_factory_config.py:21-192`, 165 of 183 keys), a comment per field (for example `:225-233`), a dataclass default on 73 fields, and `FEATURE_APR_FIELDS` (`:536-792`), held equal by a test. Of 183 keys, 32 do not derive from their field name (`feature.period.rsi.fast` for `rsi_fast_period`, `feature.breakout.*`, `feature.session.*`, `alpha.ic.canary_rng_seed`).
7. `feature_factory_config.py:16` imports `HmmConfig` from `kernels/_hmm.py`, so the config module depends on a kernel module and loads hmmlearn and sklearn.
8. `contract/registry.py:80` `_TF_MINUTES` is one of six timeframe-minute maps (`src/core/bar_normalizer.py:41`, `src/core/bar_accumulator.py:35`, `src/intelligence/bars/sources.py:27`, `bars/gap_plan.py:91`, `research/clock.py:28`).
9. `1e-10` appears 69 times as a literal across the kernels (24 in `price.py`) beside `EPS = 1e-10` (`kernels/_primitives.py:19`); the log-return expression `np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))` is repeated 13 times in `price.py`. These are mathematical guards, which CLAUDE.md exempts from APR, so 472's request to seed the `cross_tf.py` `1e-10` guards as APR keys should be dropped in favour of the one `EPS`.
10. `research/feature_inputs.py:320-381` (`_coerce`, `_build`, `feature_config`) is a second constructor of `FeatureFactoryConfig`, from a provenance projection, beside `FeatureFactoryConfig.from_values`.

CLAUDE.md checks:

11. No ring breach (the `services/` hits in `kernels/macro.py:190,426` and `_hmm.py:1` are docstrings), no `datetime.now()` or `utcnow`, no retired glossary term in these files.
12. APR: the Shannon entropy bin count is a tunable default (`kernels/_cache_state.py:839`, `n_bins=10`) with no key. The bar statistic minimums are written twice, `price.py:1781-1783` (17, 11, 10) against `_cache_state.py:816,847,869`; `bar_statistics_refresh` is path dependent, so the probe skips its memory check and only `tests/unit/intelligence/test_declared_warmup.py:207` (5-bar tolerance) would catch drift.
13. no_fill: `vol_ratio` writes 1.0 on a zero-variance window (`price.py:1678`) where CCI writes NaN (`price.py:1650`); not in 474's list.

Methodology:

14. Concept rows: every one of the 305 stored numeric columns has a `concept_registry` row (288 active, 17 candidate); no active concept lacks a column.
15. Causality: every kernel is probed by exactly one registry probe (`tests/unit/intelligence/test_feature_kernels.py:227`). The 15 path-dependent kernels (59 columns, `test_feature_kernels.py:54-70,184-191`) skip the memory check and rest on `test_declared_warmup.py`; the 21 pass-through columns are 674's.
16. Slow path: `price.py:1580-1620` builds the six `ret_lag_*` columns with one Python call per row; it can be vectorized, under a parity test, because scalar and SIMD `log` may differ in the last bit.

Splits (seams named by the modules' own sections; a split moves each kernel's `module`, which the per-kernel code key hashes, `contract/registry.py:121`, so all splits go in one re-pin batch):

- `price.py` (2,129): returns and autocorrelation; volatility estimators (`:711-1050`, `:1369-1450`); breakout and recency (`:337-583`, `:1270-1368`, `:1453-1521`); bar shape (`:43-250`, `:1522-1580`); bounded-window oscillators (`:1621-1750`); bar statistics (`:1750-1822`).
- `vp_sr.py` (1,490): volume profile (`:57-214`), support and resistance (`:215-381`), swing, trend and Fibonacci (`:382-1061`), session levels (`:1062-1216`).
- `smc.py` (1,275): no file split; split `_compute_order_blocks` (`:115-338`) and `_compute_supply_demand_zones` (`:769-962`) into detection and state, and carry the touch count as an int instead of parsing it back out of the label (`_pool_touches_for`, `:723-741`).
- `_hmm.py` (1,380): delete item 2 and move `HmmConfig` (`:118-223`) out; the 196-line `_walk_forward_hmm_full` waits for todo 108.
- `contract/registry.py` (858): the volume guard (`:657-770`) and the anchor helpers (`:74-113`) to their own contract modules.

## Ranked order

1. Delete items 1, 2 and 4 with their tests. Stored values and goldens are unchanged.
2. Delete item 3 (`days_to_month_end` compute, field and persistence entry).
3. Item 9: one `EPS` and one `_log_returns` helper, goldens bit-identical; drop 472's guard part.
4. Items 6 and 7: one declaration per field (default and APR key in field metadata, the table and docs derived), `HmmConfig` in its own config module. Do not rename the 32 off-pattern keys: that is an APR migration that moves every provenance pin's hash for no stored-value gain.
5. Item 5: retire `FeatureVector` and `KERNEL_ONLY_COLUMNS` after 665.
6. The splits and item 16 in one batch with 472, 474 (add item 13), 475, 550 and 108, so the kernel code keys move once.
7. Item 10 (one config constructor) and item 12's `n_bins` key: research lane and code key, after 669 and with `repro_frozen` bit-identical.
8. Item 8: one timeframe-minute map in `src/core/`, last, since it touches the bar path.

## Gates

No edit until the pilot, `stage_1d` and the 471 measure are recorded and no fingerprinted run is resumable. Each step: `/simplify`, `/review`, `pytest tests/unit/ -n auto` by exit code, kernel parity goldens unchanged (step 6: any moved digest has a reason in the commit), `repro_frozen` bit-identical for step 7.

## Done when

Items 1 to 5 deleted, each config key declared once, the splits landed in one re-pin, and the rows above closed or moved to their owning todos.
