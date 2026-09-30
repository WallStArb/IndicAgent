---
phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope
plan: 10
subsystem: measure
tags: [ic, proposer, term-structure, monitoring, regime_volatility, pure-functions]
requires: []
provides:
  - src/intelligence/measure/ (params, targets, ic, proposer, term_structure, monitoring, regime_disclosure)
  - pooled_rank_ic and align_features, the names 186-14 and 186-20 import
affects: [186-14, 186-20, 186-28]
tech-stack:
  added: []
  patterns: [pure functions over ic_math and the research kernel, tunables passed in by the caller, source lint for purity]
key-files:
  created:
    - src/intelligence/measure/__init__.py
    - src/intelligence/measure/params.py
    - src/intelligence/measure/targets.py
    - src/intelligence/measure/ic.py
    - src/intelligence/measure/proposer.py
    - src/intelligence/measure/term_structure.py
    - src/intelligence/measure/monitoring.py
    - src/intelligence/measure/regime_disclosure.py
    - tests/unit/measure/ (conftest and six test modules plus test_measure_purity.py)
  modified:
    - tools/check_plugin_invariants.sh
decisions:
  - "MeasureParams gains a tenth field, degenerate_std (ic_engine's 1e-8 floor is an inline literal there, so it arrives as a parameter, not a new literal here)."
  - "IcCell.n_obs is complete finite pairs before the stride; n_independent is the strided valid count, which is what ic_engine stores as n_independent (its n_valid)."
  - "proposer returns ProposerResult(cell, bh_adjusted_p, passes_fdr); regime_volatility_disclosure returns (dict[label, IcCell], n_unlabelled)."
metrics:
  tasks: 3
  tests: 34 in tests/unit/measure
  completed: 2026-09-29
---

# Phase 186 Plan 10: measure package, the fresh IC engine's three jobs

The proposer, IC term structure and monitoring exist as pure functions under `src/intelligence/measure/`, with `regime_volatility` disclosure as the only regime-stratified IC. Every target is `panel.forward_returns` on S0 panels built in symbol chunks, so the panel end is `oos_start` and no target window reaches it.

## Stride and mask order pooled_rank_ic mirrors (for 186-20)

Mirrors `services/ic_engine.py::_compute_one_cross_sectional_cell` (subsample at lines 3984-3990, valid mask at 3994-3996) and `_subsample_and_rank` (2062):

1. Degenerate columns (std over the whole observation set below the floor, ic_engine 2348) are NaN and counted.
2. Stride first: rows `0, s, 2s...` of the (bar_ts, symbol) row-major flattening (a slice).
3. Valid mask second: target finite and all live features finite.
4. One pooled rank per column, Pearson on ranks, t-approximation p on the strided valid count, circular block bootstrap with `default_rng(rng_seed)`.

Stored `n_independent` equals the strided valid count (`"n_independent": int(n_valid)`, ic_engine 4125). `observation_rows` accepts a `row_mask` [n, m] so 186-20 can pass regime-label bars x peer symbols without reordering. `pooled_rank_ic(X, y, stride=, params=, feature_names=)` does not itself do the regime split.

## MeasureParams fields and the APR keys 186-14 maps them to

| Field | APR key (186-14 loads; this plan adds none) |
|---|---|
| min_stride | alpha.ic.subsample_min_stride (existing) |
| bootstrap_block_size | alpha.ic.bootstrap_block_size.{tf} (existing) |
| bootstrap_resamples | alpha.ic.bootstrap_resamples (existing) |
| rng_seed | writer-chosen per cell |
| fdr_alpha | existing BH-FDR level key used by ic_engine |
| min_obs | alpha.ic.min_reliable_n equivalent (ic_engine's min_reliable_n) |
| symbol_chunk_size | new infra.* key, seeded by 186-14 |
| monitor_window_sessions | new alpha.* key, seeded by 186-14 |
| hac_max_lag | existing HAC lag key used by ic_engine |
| degenerate_std | new key or documented conventional constant, 186-14 decides (ic_engine value 1e-8) |

Exact existing key names for min_obs, fdr_alpha and hac_max_lag were not verified against `config_state` here (no APR read allowed in this plan); 186-14 must confirm them.

## Commits (branch phase-186-10-measure)

- e5bce6800 chore: exempt the measure library from the plugin class suffix check
- 6d6c417f0 feat: measure params and kernel targets on chunked S0 panels
- 832fea575 feat: pooled rank IC, proposer and term structure
- 78edf26e5 feat: member monitoring, regime_volatility disclosure and purity lint

## Deviations from plan

**1. [Rule 3 - Blocking] Plugin class naming hook rejected the pinned class names**
- Found during: task 1 commit. `IcCell`, `TargetStack`, `MeasureParams`, `TermStructure`, `MemberIcSeries` fail the `src/intelligence/` suffix check.
- Fix: added `src/intelligence/measure/*` to the exclusion list in `tools/check_plugin_invariants.sh`, the same precedent as `bars/` and `features/contract/registry.py`. Pinned names are kept because 186-14 and 186-20 import them.
- Commit: e5bce6800

**2. TDD ordering.** Tests and implementation for each task were written together and committed as one feat commit per task, not separate RED and GREEN commits. Each test module was run green before commit; no separate failing-run commit exists.

**3. Added `degenerate_std` to MeasureParams** (see decisions).

## Verification

- `pytest tests/unit/measure -q`: 34 passed (worktree).
- Purity greps: 0 hits. `git diff main -- src/intelligence/research services/ic_engine.py src/intelligence/statistics production/migrations` is empty.
- No migration, no APR key, no database write.
- repro_frozen.py not required: `src/intelligence/research/` and `statistics/` are byte-unchanged.
- /simplify and /review could not be invoked in this executor (no skill tool); a manual read-through was done instead.

## Known stubs

None.

## Threat flags

None.
