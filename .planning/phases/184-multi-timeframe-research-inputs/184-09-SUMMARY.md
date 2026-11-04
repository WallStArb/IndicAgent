---
phase: 184-multi-timeframe-research-inputs
plan: 09
subsystem: research runner
tags: [runner, member-memory, certificate, warmup-prefix, snapshot-match]
requires: [184-02, 184-03, 184-05, 184-06, 184-07, 184-08]
provides: [runner._member_memory, runner._member_memories, runner._check_member_memory, runner._source_requests, runner._build_fields, runner._trade, runner._check_spec(mode, book)]
affects: [184-10]
key-files:
  modified: [src/intelligence/research/runner.py]
  created: [tests/unit/research/test_runner_feature_spec.py]
requirements-completed: [MTF-B1c, MTF-B1f, MTF-B1j, MTF-B5, MTF-B6, MTF-B7]
completed: 2026-11-04
---

# Phase 184 Plan 09: runner spec checks and S0 requests for input members

The runner now refuses bad input members at spec load, derives the S0 request (sources, warmup prefix, closes_at, high/low) from the spec, checks that a loaded snapshot matches it, and never trades a prefix row.

## What changed

- `_check_spec(spec, mode="real", book=None)`: unknown, path-dependent and not-applicable columns (feature via `check_columns` per source tf, kernel via `kernel_source.kernel_registry`) are RunRefused in every mode; two pins on one source tf are refused; outside synthetic, the supported subset (184-REVIEWS row 4) is refused before `null_battery_persistent.admit` runs on a `CertificateRequest` with source memory 0.
- `_member_memory(spec, m, configs)` is the one memory function (feature_member_memory over the registry or kernel memory under the verified provenance config of the source tf). `_check_member_memory` compares declared rows and repeats `admit` with the real source memory; it runs in `_default_build` right after `source_configs` and in `_load_panel` with configs rebuilt from the manifest's provenance blocks.
- `_member_memories(spec, manifest)` feeds timing's `e17_memory` (run_family) and `book_memory` (run_book); resid_bar members return their declared values, so existing runs are unchanged.
- `_default_build`: `source_configs`, then `build_panel(fields, warmup_sessions, sources)`; without input members the call is today's. `_build_fields` adds high and low for an equal-tf kernel source that reads them.
- `_load_panel`: `verify_sources`, and a match dict extension (closes_at, source tfs, per-tf config hash against the pin, warmup prefix recomputed from the NYSE calendar between fetch_start and scored_start, fetch_start equal to the book clock's own start). A spec without input members expects no sources and no prefix.
- `_trade(panel, cfg)` replaces both `trade_mask` call sites and zeroes rows before `scored_start`.

## Call sites

The mode reaches the check through `_gate(..., mode=mode)` (run_family; `_check_spec_tree(loaded, mode)`) and through the literal `"synthetic"` in the synthetic branches of `run_family` and `run_book` (`_check_spec(fam, "synthetic", book)`). 187-08's `certificate.admission_refusal(kind, kappa, mode, ...)` in `run_book` is unchanged. Pods skip the tree check as before.

## Deviations

- Amendment (b) (one admission mechanism in certificate.py) not built; admission is `null_battery_persistent.admit` as the lead's brief directs.
- Every regime-origin column in today's registry (hmm_*) is path dependent, so spec load refuses it on B1g before S0's B1j can; the `-k hmm` test lifts the path-dependence rule to show origin alone is not refused at spec load.
- A book with input members in any family but the first is refused: S0 is built from the first family's spec (run_book passes fam0). A union request is a later change.
- `_BARS_PER_SESSION` lives in runner.py (equal to the battery's table, asserted by a test) rather than a new constant in clock.py.
- Tests were written first and run red.
- Compare-all not run (lead). `slot_history_sessions` is at least 1 in the spec while the battery certified 0; the runner uses the spec's value.

## Gates

New tests and `tests/unit/research -k runner` green; full unit suite and repro_frozen: see the commit gate results in the report.
