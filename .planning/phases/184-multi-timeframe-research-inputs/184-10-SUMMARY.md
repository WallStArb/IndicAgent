---
phase: 184-multi-timeframe-research-inputs
plan: 10
subsystem: research runner
tags: [runner, s2b, align, s3-guards, kernel-probe, feature-members]
requires: [184-01, 184-02, 184-03, 184-08, 184-09]
provides: [runner.InputSources, runner.member_index, runner.member_input, runner._guard_input_member, Panel.sources]
affects: [184-11]
key-files:
  modified: [src/intelligence/research/runner.py, src/intelligence/research/panel.py, src/intelligence/research/snapshot.py, tests/unit/research/test_runner_feature_spec.py]
  created: [tests/unit/research/test_runner_feature_members.py]
requirements-completed: [MTF-B1i, MTF-B2b, MTF-B3a, MTF-B5, MTF-B7]
completed: 2026-11-04
---

# Phase 184 Plan 10: feature and kernel members on the book clock

Input members now compute in S2b and are guarded in S3. A spec with a stored feature or kernel member runs S0 to S8 on a synthetic panel.

## What changed

- `InputSources` (carried on the new `Panel.sources` field, never saved or hashed) reads the book snapshot dir, child dirs of coarser sources and the finer-source evidence arrays. `member_index` is the only alignment: coarser or equal sources go through `align.align_index` over `clock.closes_at` recomputed on the source grid; finer sources replay S0's persisted `idx__` remapped into `ref_values__`. `member_input` returns the same `resid_bar` object for existing members, else the gathered (and optionally smoothed) float32 input. `compute_members(..., panel=)` routes through it.
- `real_guards` calls `_guard_input_member` per input member: `check_alignment` over every scored row (rows before `scored_start` masked via the shared `_scored_mask`, which `_trade` now uses too), causality probe and memory check on member-over-smoother with `declared = MemberMemory.transform_rows`, provenance `code_key` cited for stored values. Kernel members add: recompute from raw bars on the probe symbols must equal the persisted input; phase 186 truncation probe and memory check on the kernel chain; end-to-end perturbation of raw bars after a decision row (NaN, then seeded rescale) through kernel, alignment, smoother and member. The report appears as `summary["input_members"]` only when input members exist.
- `Panel.load(path, verify=False)`, `snapshot.PROBE_SYMBOLS` (renamed from private).

## Deviations

- Tests were written after the implementation, then checked red by mutating `_perturb` (planted-kernel test fails) rather than red first.
- Equal or coarser kernel members read S0's stored `kernel__<tf>__<member>` array in S2b instead of recomputing the kernel over every symbol; the guard recomputes it from raw bars on the probe symbols and requires equality.
- `Panel.sources` field added (panel.py) and `Panel.load(verify=)`; total_return segments and transforms that change the row grid are refused for input members (RunRefused).
- Kernel tests use `rk_price_percentile`; `rk_vwap_dev` needs `volume_basis`, which S0 never supplies, so it cannot run through `snapshot._run_kernel` today.
- 187-18 (`execution.py`) has not landed.

## Remaining gap

A book with input members in a family other than the first is still refused (S0 is built from the first family). Compare-all not run (lead).
