# Note for 186-26: the rebuild preconditions now read verdicts (plan 185-41)

Author: phase 185 session. Informed by: `docs/plans/2026-10-06-data-layer-integrity-design.md` sections 6, 8 and 9 step 10.

185-41 changed `services/rebuild_preconditions.py` (186-25's module). 186-26-PLAN.md was not edited, and its descriptions of the module are out of date. Read this note first.

## What changed

`check_d2_landed` and `check_bar_coverage` no longer test row existence or tradeable spans. They read the same computed `bar_integrity` verdict rows promotion reads (D7 writes them every run), through one pure function, `src/intelligence/bars/verdict_gate.gate_symbols`. A symbol fails when a required verdict is failed, missing, older than `threshold.bar_integrity.report_max_age_hours` (30), or older than the series' latest load that changed bars. The failure names the symbol, timeframe and check.

- `check_d2_landed(scan)`: 1d checks for every 1d rebuild symbol (session_coverage, policy_conformance, lineage_missing, canonical_recompute, digest_fresh, unexplained_seam, vendor_basis_run). Was `check_d2_landed(symbols_missing_lineage, symbols_missing_digest)`.
- `check_bar_coverage(scan, empty_history_spans)`: 5m (slot_coverage, digest_fresh, coverage_cache), 15m and 1h (digest_fresh, grid_parity) plus stray_vendor_rows (this gate only; promotion ignores it). The `ohlcv_empty_history` spans are still listed verbatim. Was `check_bar_coverage(coverage_rows, expected_spans, empty_history_spans)`.
- `check_data_layer_final_landed(markers)` is new and part of `run_all`: it fails until 185-42, 185-43, 185-45 and 189-11 SUMMARY files exist. `run_all` now runs nine checks.
- An empty scan (no symbols judged) fails; it proves nothing.

## Signature changes the 186-26 driver must follow

- `fetch_d2_inputs(conn, symbols, *, now=None)` returns a `VerdictScan` (failures, n_symbols, first and last verdict time). The `rule_version="d2-v1"` argument and the (missing_lineage, missing_digest) return are gone; lineage is a view and the rule is d2-v2 everywhere.
- `fetch_bar_verdict_inputs(conn, symbols, tfs, *, now=None)` is new: the intraday scan (tfs minus 1d) with stray_vendor_rows required. Pass it the names the rebuild covers at 5m, 15m and 1h.
- `fetch_final_landed_markers(project_root=None)` is new.
- `fetch_coverage_inputs(conn, tfs, symbols)` keeps its return shape (the writer imports `CoverageRow`); its empty-history query used columns that do not exist (`first_bar`, `last_bar`) and now reads `empty_from` and `empty_through`.
- `run_all(...)`: the `coverage_rows`, `expected_spans`, `d2_symbols_missing_lineage` and `d2_symbols_missing_digest` parameters are replaced by `bar_scan`, `d2_scan` and `final_landed_markers`. `empty_history_spans` stays; every other parameter is unchanged.

## Timing

186-26 runs once, after the data is final, in this order: cleanup (185-42, 185-45, 185-43), then the new data (189-11: 5m backfill complete, vendor 15m/1h rows out), then the rebuild.

- 185-43 (and the cleanup before it) comes first so the writer's `code_content_key` is taken on final code. 185-42 edits the rebuild writer, so an earlier launch would also block that edit.
- 189-11 comes first so the rebuild reads final 5m bars and derived grids, not bars it would have to redo.
- `check_data_layer_final_landed` enforces both: do not work around it.

## State on 2026-10-07 (read-only run of the gates)

1d: 285 of 1,502 names fail (session_coverage 240, unexplained_seam 8, vendor_basis_run 46; the 46 are 185-37's input). Intraday: all 233 `compute` names fail (slot_coverage 233, coverage_cache 228, grid_parity 59 on 15m and 72 on 1h). The 5m tail gap since 2026-09-29 closes with the 189-10 fetch. The grid_parity volume tolerance is an owner decision; the rule is unchanged.

Code commit: 9ae6d529e (rebuild preconditions); the promotion gate is dbfdcce50 and 6f007d826. `git log --grep "185-41"` lists all.
