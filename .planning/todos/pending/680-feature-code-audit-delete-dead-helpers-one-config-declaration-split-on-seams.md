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

## Triage by class

Import set: `src/core/code_identity.py:import_closure` run (AST only) on the entries the pins hash: `rebuild_code_key()` (`services/backfill_feature_factory.py:1492-1495`) is the per-kernel closure of every non-underscore module in `kernels/` (`:500-503`, `contract/registry.py:585-603`) plus the writer closure of `services.backfill_feature_factory` less `WRITER_UNHASHED_IMPORTS` (`:515-547`, 61 modules), and the ic_measure job keys (`services/ic_measure.py:1140-1187`, 76 modules); together they hold every `kernels/` module, `contract/registry.py`, `feature_factory_config.py`, `feature_vector.py`, `feature_vector_persistence.py`, `research/feature_inputs.py`, `research/clock.py`, `src/core/bar_normalizer.py`, `src/core/bar_accumulator.py` and `bars/sources.py`, but not `bars/gap_plan.py`, `scripts/` or `tests/`.
Triaged 2026-11-26 at 268f17ee0 (lines re-verified on this checkout; the live run eca9e854 executes from its own worktree, so the hold is about its pin and resume, not its files). Classes: (a) changes feature output, next re-pin with parity goldens or a ledger entry; (b) no output change in a hashed module, hold until no fingerprinted run is live or resumable; (c) safe now.

| # | file:line | finding | class | size | reason |
|---|---|---|---|---|---|
| 1 | `.planning/todos/pending/472-*` | item 9: drop 472's request to seed the `cross_tf.py` `1e-10` guards as APR keys | c | small (planning text) | planning edit only; `1e-10` is a mathematical guard, APR exempt |
| 2 | `scripts/debug/analysis/debug_bic_k_selection.py` | item 2, first half: retire the last non-test caller of `_build_obs_matrix*` | c | small (one file) | `scripts/` is in no closure and nothing imports the script; must land before row 7 |
| 3 | `kernels/macro.py:190,426`, `_hmm.py:1` | item 11: ring, timestamp and glossary checks are clean | c | none | record only, no edit |
| 4 | `concept_registry` vs `feature_vectors` | item 14: every stored column has a concept row | c | none | record only, no edit |
| 5 | `tests/unit/intelligence/test_feature_kernels.py:54-70,184-191,227` | item 15: one probe per kernel; path-dependent kernels rest on `test_declared_warmup.py` | c | none | record only; the 21 pass-through columns are 674's |
| 6 | `kernels/price.py:250-271`; `tests/unit/intelligence/test_feature_factory_p7.py:26,173-193` | item 1: delete `_rsi` and `_rsi_wilder` (only test callers; stored RSI is `_primitives.py:58-73`) | b | small (~45) | dead code, but `price.py` is a kernel module, so the deletion moves its code key |
| 7 | `kernels/_hmm.py:38-47,327-368,398-438,472,505`; 5 test files | item 2, second half: delete `_build_obs_matrix*` and both `_DEFAULT_*` constants (ridge becomes a required argument; `:988-1002` already passes it) | b | medium (~100 src, 5 test files) | no output change; `_hmm` is in the writer and ic_measure closures |
| 8 | `kernels/price.py:1700-1705` | item 4: unreachable `else np.ones(len(c))` in `vol_ratio` (`_primitives.py:76-84` makes the branch always true) | b | small (3) | dead branch in a hashed module |
| 9 | `kernels/calendar.py:165,300,345`; `feature_vector.py:208`; `feature_vector_persistence.py:73-83`; parity manifest | item 3: delete `days_to_month_end` compute, field and dropped-set entry | b | small (~20 plus tests and manifest) | the column is never stored, so no stored value moves; all three files are hashed; `scripts/ops/alpha/ops_broadcast_feature_audit.py:131` lists the name and needs its owner's edit |
| 10 | `kernels/*.py` (69 `1e-10` literals; `price.py` 13 log-return copies) | item 9: one `EPS`, one `_log_returns` helper | b | medium (~85 sites, 9 files) | same float, bit-identical output, but the AST changes in every kernel module |
| 11 | `feature_factory_config.py:16,21-192,223-234,536-792`; `_hmm.py:118-223` | items 6 and 7: one declaration per field, `HmmConfig` to its own config module | b | large (~600) | no value moves if defaults and keys are carried verbatim; both modules are hashed |
| 12 | `kernels/price.py:1781-1783`; `_cache_state.py:816,847,869` | item 12, second half: write the bar statistic minimums once | b | small (~10) | same constants, one home; both files hashed |
| 13 | `kernels/_cache_state.py:839` | item 12, first half: APR key for `n_bins=10` | b | small (migration plus ~5) | seeded at 10, so no value moves, but the new `config_state` row moves the APR snapshot pin as well as the code key |
| 14 | `research/feature_inputs.py:320-381` | item 10: one `FeatureFactoryConfig` constructor | b | medium (~60) | in the ic_measure closure and the research lane; needs `repro_frozen` bit-identical, after 669 |
| 15 | `feature_vector.py` (749); `contract/registry.py:616-630`; `feature_vector_persistence.py` | item 5: retire `FeatureVector` and `KERNEL_ONLY_COLUMNS` | b | large (~800) | schema-order source only; blocked on 665 moving ic_measure first |
| 16 | `price.py`, `vp_sr.py`, `smc.py:115,723,769`, `_hmm.py`, `contract/registry.py:74-113,657-770` | the splits, including the smc touch count as an int | b | large (~5,000 moved) | moves each kernel's `module` (`contract/registry.py:119-121`), so every split re-keys at once; parity goldens must hold, especially for the smc label change |
| 17 | `contract/registry.py:80`; `src/core/bar_normalizer.py:38`; `src/core/bar_accumulator.py:35`; `bars/sources.py:27`; `bars/gap_plan.py:91`; `research/clock.py:28` | item 8: one timeframe-minute map in `src/core/` | b | medium (6 files) | five of the six files are hashed (only `gap_plan.py` is not) and the maps differ in coverage (`1m`, `30m`, `4h`, `1d`), so the merge must keep each reader's domain |
| 18 | `kernels/price.py:1678` | item 13: `vol_ratio` writes 1.0 on a zero-variance window where CCI (`:1650`) writes NaN | a | small (1 plus goldens) | stored values move from 1.0 to NaN; goes with 474 in the re-pin batch |
| 19 | `kernels/price.py:1580-1600` | item 16: vectorize the six `ret_lag_*` columns | a | small (~25 plus parity test) | SIMD and scalar `log` can differ in the last bit, so treat it as an output change unless parity proves bit-identity |

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
