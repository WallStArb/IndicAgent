---
phase: 184-multi-timeframe-research-inputs
plan: 02
subsystem: research (S2 sources), features (research kernels)
tags: [kernels, kernel_source, causality, memory, D5, D7-guard-5]
requires: [phase 186 registry contract (registry.py, causality_probe.py)]
provides:
  - src/intelligence/features/research_kernels (KERNELS, factories, CONFIG_FREE_KERNELS, STORED_EQUIVALENTS, STORED_WINDOW_FIELD)
  - src/intelligence/research/kernel_source.py (kernel_registry, kernel_member_memory_bars, kernel_source, KernelSourceResult, KernelSourceRefused)
affects: [184-04 feature_inputs.feature_config (supplies the config), 184-06 spec wiring (windows, max_gap_rows), 186 registry (promotion todos 550-552)]
tech-stack:
  added: []
  patterns: [sliding_window_view chunked reductions, per-symbol present-row compute and scatter, combined default + research registry]
key-files:
  created:
    - src/intelligence/features/research_kernels/__init__.py
    - src/intelligence/features/research_kernels/rolling.py
    - src/intelligence/research/kernel_source.py
    - tests/unit/intelligence/test_research_kernels.py
    - tests/unit/research/test_kernel_source.py
    - .planning/todos/pending/550-promote-research-kernel-rolling-percentile.md
    - .planning/todos/pending/551-promote-research-kernel-rolling-max-distance.md
    - .planning/todos/pending/552-promote-research-kernel-rolling-vwap-deviation.md
  modified:
    - docs/foundation/glossary.md
    - .planning/todos/PRIORITIES.md
decisions:
  - "kernel_source refuses config=None for a research family with a stored equivalent (percentile, max distance): the stored window that the D5 / row 10 rule compares against is a provenance-config value, so without the config the check cannot be made, and skipping it would be a silent hole"
  - "windows maps research family -> one window per call; the output name carries the window (rk_<family>_w<window>) and must match the pinned window"
  - "Research kernels give NaN (not 0.0 or a fill) on degenerate denominators and on windows holding a NaN; parity with the stored originals holds bit for bit on finite inputs from the first full window"
  - "Battery windows kept as planned (126, 126, 20): none equals a stored window (APR percentile 50/200, high_52w 252; stored VWAP deviation has no window)"
metrics:
  completed: 2026-10-28
  tasks: 2
  files: 10
---

# Phase 184 Plan 02: research kernels and kernel_source summary

Vectorized trailing-window research kernels (rolling percentile, rolling max distance, rolling
VWAP deviation) under the 186 Kernel contract in a package `default_registry()` never discovers,
plus `kernel_source`, which runs registry and research kernels per symbol over present rows of an
S0 panel at pinned windows: float32 on the grid, NaN until declared memory, a gap rule with counts,
and refusals for expanding outputs, stored windows and config-reading closures without the
provenance config.

## Tasks

| Task | Name | Commit | Files |
|---|---|---|---|
| 1 | research_kernels package, parity, causality and memory tests (B2a, B2c) | 4e83cf73d | research_kernels/__init__.py, rolling.py, test_research_kernels.py |
| 2 | kernel_source, glossary, promotion todos, PRIORITIES rows (B2b, B2c) | 30924930b | research/kernel_source.py, test_kernel_source.py, glossary.md, todos 550-552, PRIORITIES.md |

Todo numbers used: 550 (rolling percentile), 551 (rolling max distance), 552 (rolling VWAP
deviation), all P3 under "Kernel and feature code (phase 186 follow-ups)", gated on 186-27.

## What was built

- `rolling.py`: factories `rolling_percentile_kernel`, `rolling_max_distance_kernel`,
  `rolling_vwap_deviation_kernel` (window an int >= 2, else ValueError); outputs
  `rk_price_percentile_w{w}`, `rk_high_dist_w{w}`, `rk_vwap_dev_w{w}`; memory `w - 1`,
  `memory_atol` 0. Each window is reduced from its own rows (no prefix sums), in row chunks that
  bound the temporary array. `KERNELS` exposes windows 126, 126, 20.
- Parity: rolling percentile and max distance equal `_price_percentile_series_full` and
  `_high_52w_dist_series_full` cast to float32 bit for bit on every row >= w - 1, at windows 20, 60
  and 252 (plus a ties case for the weak count).
- `kernel_source`: combined registry `KernelRegistry.from_kernels(default.kernels + research,
  default.external_inputs)`; `ts` int64 UTC ns from `panel.timestamps`; optional `high` / `low`
  arrays, refused when a kernel needs them and they are absent; unknown outputs and families,
  path-dependent outputs (D7 guard 5), stored-window duplicates (184-REVIEWS row 10) and bad
  `max_gap_rows` raise `KernelSourceRefused`. Never constructs `FeatureFactoryConfig()` or reads
  APR; imports neither `services` nor `measure`.

## Verification

- `tests/unit/intelligence/test_research_kernels.py`: 34 passed (`-k guard5`: 4).
- `tests/unit/research/test_kernel_source.py`: 17 passed (`-k guard5` 1, `-k stored_window` 4,
  `-k config` 5).
- `test_kernel_registry.py`, `test_feature_vectors_v2_schema.py` pass unchanged; no diff under
  `features/kernels` or `features/contract`; `grep research_kernels` in kernels/contract/services
  returns 0.
- `pytest tests/unit -k priorities`: 4 passed. Full `pytest tests/unit/ -n auto`: green (one
  pre-existing HMM skip).
- B7 trio (all green):
  - repro_frozen (scratch `repro_184_02`, after both commits; "not recorded in frozen artifact,
    skipped" lines omitted), exit 0:
    ```
    phase 179 S3: bit-identical [ 0.21612308 -0.14601638 -0.10558864]
    phase 181 S2 (signal from Panel): bit-identical
    phase 181 S3: bit-identical [0.19424572]
    ```
  - `tests/unit/research/test_spec_hashes_pinned.py`: 8 passed.
  - compare-all: one shared run by the 184-03 executor from a detached worktree at d47174891
    (contains 4e83cf73d and 30924930b), verbatim:
    ```
    Shared 184 compare-all (covers 184-01..04 code)
    start 2026-10-28T06:53:40Z at d4717489105df8b511f76b24710d0b8537345103
         16 "outcome": "equal"
          4 "outcome": "pre_e17"
    log: logs/research/series_backfill_2026-10-28T11:26:10.035417Z.json
    exit=0
    ```
    The 4 pre_e17 entries are the E16-era family1_intraday_periodicity runs (187-03, classified
    by 44ece68c5), not caused by this plan.

## Deviations from plan

1. [Rule 2 - correctness] `kernel_source` with `config=None` also refuses a research family that
   has a stored equivalent, because the stored-window check needs the provenance config. The
   plan's "None accepted when config free" therefore applies in `kernel_source` only to
   `rk_vwap_dev` (and to `kernel_member_memory_bars` / `kernel_registry` for all three).
2. [Rule 2] `STORED_WINDOW_FIELD` (stored column -> FeatureFactoryConfig field) added next to
   `STORED_EQUIVALENTS`, which maps each family to stored column names rather than function names,
   so the window comparison reads the provenance config directly. A test holds every listed column
   to an existing registry output.
3. Process: the plan asked for one commit after both tasks; the executor instructions asked for
   one per task, so there are two. Tests and implementation were committed together per task (no
   separate RED commit).
4. B7 trio ran after both commits, because 184-01's compare-all held the machine until then.

## Known stubs

None. `windows` and `max_gap_rows` have no module defaults by design; plan 06 wires them from the
spec, and 184-04 supplies the provenance config.

## Threat flags

None beyond the plan's register (T-184-05 to T-184-08, each mitigated and tested).

## Self-Check: PASSED

Both commits and all created files exist.
