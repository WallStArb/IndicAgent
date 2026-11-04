---
phase: 184-multi-timeframe-research-inputs
plan: 08
subsystem: research S0
tags: [snapshot, feature-read, provenance-config, finer-source-index]
requires: [184-01, 184-02, 184-04, 184-07]
provides: [MemberSourceRequest, SourceRequest, source_configs, build_panel sources=, verify_sources]
key-files:
  created: [production/migrations/564_research_snapshot_feature_chunk_apr.sql, tests/unit/research/test_snapshot_features.py]
  modified: [src/intelligence/research/snapshot.py, src/intelligence/research/feature_inputs.py, tests/unit/research/test_feature_inputs.py]
requirements-completed: [MTF-B1e, MTF-B1f, MTF-B1g, MTF-B1h, MTF-B1j, MTF-B1k, MTF-B7]
---

# Phase 184 Plan 08: S0 feature block

S0 reads stored feature columns and computes kernel members per source tf under one provenance-verified config.

## Interface for 184-09/10

- `MemberSourceRequest(member, kind "feature"|"kernel", column, windows, max_age_rows, max_gap_rows, coverage_floor)`; `SourceRequest(tf, pinned_config_projection_hash, members, need_high_low)`.
- `await source_configs(dsn, sources, start, end, *, symbols) -> {tf: {"block", "config"}}` (symbols added to the plan signature; provenance needs them).
- `build_panel(..., sources=None)`; manifest `sources[tf]` holds relation (equal/coarser/finer), config_hash, projection, provenance, per-column warmup and coverage, unmatched_rows; coarser also `dir`, `sha256`.
- Arrays: equal tf `feature__<tf>__<col>`, `kernel__<tf>__<member>`; coarser the same inside child dir `sources/<tf>`; finer `idx__<member>` int32, `ref_rows__<member>`, `ref_values__<member>` float32, `src_ts__<tf>`, `src_valid__<tf>`, `probe_bars__<tf>` [n_src, first 3 symbols, (o,h,l,c,v)].
- `verify_sources(book_path) -> {tf: Path}`; `feature_inputs.check_columns(names, registry, tf)`, `feature_select_sql(names, registry, *, tf)`, new `symbol_counts` and `coverage_from_counts` (coverage_check composes them).

## Gates
Migration 564 applied live (value 100). Unit suite exit 0; repro_frozen bit-identical; pinned spec hashes and read boundary green; no compare-all (per lead).

## Deviations
- Migration 564 instead of 526 (taken), per lead.
- Implementation was written before the amendment tests, not strictly red first.
- Child tf start uses `warmup_fetch_start(scored_lo, tf, sessions)` so a daily source is not cut by an intraday open.
