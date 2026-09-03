---
phase: 166-frame-execution-recalibration
reviewed: 2026-07-23T14:52:55Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - production/migrations/253_alpha_frame_stop_target_calibration.sql
  - scripts/analysis/diagnose166_frame_calibration.py
  - scripts/analysis/gate166_frame_recalibration_eval.py
  - services/alpha_frame_writer.py
  - services/ensemble_ic_engine.py
  - src/intelligence/trading/structural_confluence.py
  - tests/unit/test_alpha_frame_writer_candidate_geometry.py
  - tests/unit/test_diagnose166_frame_calibration.py
  - tests/unit/test_ensemble_ic_stop_target_calibration.py
  - tests/unit/test_gate166_frame_recalibration_eval.py
  - tests/unit/test_structural_confluence.py
findings:
  critical: 0
  warning: 3
  info: 1
  total: 4
status: clean
resolution: all 4 findings fixed same session (see Resolution section below)
---

# Phase 166: Code Review Report

**Reviewed:** 2026-07-23T14:52:55Z
**Depth:** standard
**Files Reviewed:** 11 (+ 2 diff-only files existing before this phase: `services/alpha_frame_writer.py`, `services/ensemble_ic_engine.py`)
**Status:** issues_found

## Summary

Reviewed the full Phase 166 diff: migration 253's APR seed, the two calibration mechanisms
(`_calibrate_stop_target` in `ensemble_ic_engine.py`, the `geometry_source` dispatch in
`alpha_frame_writer.py`), the new `structural_confluence.py` confluence port, the diagnosis and
gate166 scripts, and their unit tests. This is a well-constructed, empirically disciplined
piece of work — the CR-02 champion-gate pattern is correctly mirrored, the uncensored-
subpopulation selection criterion (Finding 1/Pitfall 1) is correctly implemented (not a copy of
the IC-decay walk), the extracted `_write_median_calibration` helper is a faithful, correct
refactor of the pre-existing `_calibrate_hold_max_bars` write loop, and the ATR-normalized-
distance-to-price reconstruction formulas in `structural_confluence.py` were independently
verified against Phase 163's actual planned formulas (163-02-PLAN.md/163-03-PLAN.md, not yet
executed) and are sign-correct for `poc_dist_atr`, `poc_rolling_dist_atr`,
`distance_to_vah_atr`, `distance_to_val_atr`, `sr_support_dist`, and `sr_resist_dist`. All
tests in the reviewed set pass (`tests/unit/test_structural_confluence.py`,
`test_alpha_frame_writer_candidate_geometry.py`, `test_ensemble_ic_stop_target_calibration.py`,
`test_diagnose166_frame_calibration.py`, `test_gate166_frame_recalibration_eval.py`,
`test_alpha_frame_writer.py`).

No BLOCKER-level defects were found — nothing here causes incorrect trading-relevant output
that contradicts the phase's own disclosed empirical verdict (both candidates FAIL; this review
does not re-litigate that). Three WARNING-level findings surfaced: a migrated-but-never-read
APR key (a real, if narrow, APR-mandate gap), a scoping mismatch between the stop/target
calibration's actual eligibility filter and what its own code comment/docstring claims it
mirrors, and a minor diagnostic-counter inaccuracy. One INFO-level finding: a test that doesn't
actually exercise the code path it claims to guard.

## Warnings

### WR-01: `alpha.frame.structure_snap_proximity_atr` is migrated but never read by any Phase 166 code

**File:** `production/migrations/253_alpha_frame_stop_target_calibration.sql:257-268`, cross-checked against `src/intelligence/trading/structural_confluence.py` and `services/alpha_frame_writer.py`

**Issue:** Migration 253 Section 3 seeds `alpha.frame.structure_snap_proximity_atr` (default
`1.5`) with a description stating it is "the maximum ATR distance between the ATR-fallback
stop/target price and a resolved structural confluence level for the candidate to 'snap' to
that structural level instead of the pure-ATR price." 166-01-PLAN.md's Task 1 action text
explicitly lists this key alongside the other 6 structural-confluence thresholds as something
to migrate for the structural candidate.

However, `structural_confluence.py` only ever reads 6 threshold keys
(`cluster_radius_atr`, `single_level_radius_atr`, `zone_buffer_atr`, `min_width_atr`,
`strength_weight`, `proximity_weight` — see `_read_config` call sites at lines 39-59) and
`_build_structural_config_service` in `alpha_frame_writer.py` populates the cache-only
`ConfigService` with exactly those same 6 keys (lines listing
`"alpha.frame.cluster_radius_atr"` through `"alpha.frame.proximity_weight"`). No file in this
phase's diff references `structure_snap_proximity_atr` anywhere (`grep -rn
"structure_snap_proximity_atr" src/ services/ tests/` returns only unrelated hits in the
archived `trade_framer.py`/`feature_vector_pipeline.py`). The 3-tier resolution architecture
(`_resolve_zone`: confluence → single-best → ATR fallback) never implements a "snap the ATR
price to a nearby-but-not-quite-in-window structural level" step — the ATR fallback
(`tier="atr"`) always returns the pure scalar seed unconditionally, with no proximity check
against any candidate that fell just outside `collect_candidates`' strict `(stop, entry)`
window.

This violates the APR mandate's own migration contract (CLAUDE.md: "Adding a parameter: ...
(2) load via `ConfigService.get()` at init ... remove the hard-coded constant") — the key was
added but never wired to any consuming code path. It is either dead configuration surface, or a
genuinely missing feature (the "snap" behavior the migration's description promises) that got
dropped silently during Plan 166-03/166-05's implementation without updating the migration
comment or filing a follow-on todo.

**Fix:** Either (a) remove the unused key from migration 253 (via a follow-up migration, since
253 is already applied live) if the snap behavior was intentionally descoped, updating the
description/comment accordingly, or (b) implement the snap step in `_resolve_zone`'s ATR
fallback tier (check the nearest out-of-window candidate against
`structure_snap_proximity_atr` before falling back to pure ATR) and wire the 7th key into
`_read_config`/`_build_structural_config_service`. Either way, the current state (seeded,
described, never consumed) should not persist silently — file a todo if deferring.

### WR-02: `_calibrate_stop_target`'s eligibility scoping is coarser than its own comment claims

**File:** `services/ensemble_ic_engine.py:1327` (eligible_symbols derivation) and `:997-1003` (`_STOP_TARGET_FETCH_SQL` comment)

**Issue:** The code comment above `_STOP_TARGET_FETCH_SQL` states: "`symbol = ANY($3)`
restricts to the symbols this run's ensemble_alpha corpus actually measured (mirrors the
scoping `results` provides to `_calibrate_hold_max_bars`...)". In practice this is a coarser
scope than what `_calibrate_hold_max_bars` provides: `_calibrate_hold_max_bars` groups
directly from `results` itself, so it can only ever produce a value for a `(symbol, tf,
regime)` triple that has an actual row in `results` (i.e., a triple this run's IC computation
successfully measured and passed whatever per-tf sufficiency/stability gates apply upstream).

`_calibrate_stop_target`, by contrast, derives `eligible_symbols` as a flat set of symbol
*names* (`{row["symbol"] for row in results if not row.get("is_pooled")}`) and then fetches
`alpha_frames` filtered only by `symbol = ANY($3::text[])` and `weight_epoch`/`bar_ts` — with
**no `tf` filter**. If a symbol qualified in `results` for `tf=5m` but not `tf=1h` (e.g. that
`(symbol, 1h)` combination failed `min_obs_per_regime` or a walk-forward-stability gate
upstream and produced no row in `results`), `_calibrate_stop_target` will still fetch and
calibrate that symbol's `1h` `alpha_frames` rows and contribute them to a `(regime, 1h)` cell's
median — a `(regime, tf)` cell that was never actually IC-validated for that symbol in this
run, unlike what `_calibrate_hold_max_bars` would do for the equivalent case.

In the current corpus this is likely benign in practice (an `AlphaFrameWriter --backfill` run
typically covers the full symbol×tf grid uniformly, and `EnsembleICEngine`'s `symbol_to_tfs`
mapping generally includes every active tf per symbol), but the code's stated invariant
("mirrors the scoping results provides") does not actually hold, and a future corpus shape
where symbols measure cleanly on some tfs but not others would silently widen the scoring
population beyond what the comment promises.

**Fix:** Either scope the SQL fetch by the actual `(symbol, tf)` pairs present in `results`
(e.g. `WHERE (symbol, tf) = ANY(...)` against a passed array of tuples, or filter frame_rows in
Python post-fetch against the exact `(symbol, tf)` pairs seen in `results`), or correct the
comment/docstring to accurately state that eligibility is symbol-level only (not
symbol+tf-level), so a future reader doesn't rely on a guarantee the code doesn't provide.

### WR-03: `missing_cost_hurdle_count` can over-count frames that are ultimately skipped for degenerate structural geometry

**File:** `services/alpha_frame_writer.py:634-660` (approx., `_process_partition` per-row loop)

**Issue:** In the per-row loop, `missing_cost_hurdle_count` is incremented immediately when
`row["cost_hurdle"] is None`, *before* the new `geometry = _resolve_row_geometry(...)` call and
its `if geometry is None: ... continue` skip. A row whose structural geometry resolves to a
degenerate (razor-thin) stop distance is counted toward `missing_cost_hurdle_count` (if its
`cost_hurdle` also happened to be null) even though that row is never inserted into
`alpha_frames` — the two diagnostic counters (`missing_cost_hurdle_count` and
`degenerate_geometry_skip_count`) are not mutually exclusive in a way the per-partition log
lines make clear, so the printed `missing_cost_hurdle_count` slightly overstates the number of
*written* rows with a missing cost hurdle. This is a descriptive-logging-only inaccuracy (no
downstream computation reads this counter), but it can mislead an operator diagnosing data
quality from the log output.

**Fix:** Move the `cost_hurdle` null-check/counter increment to after the geometry
resolution's `continue`, or explicitly note in the log line that the two counts can overlap.

## Info

### IN-01: `test_dry_run_performs_zero_writes` doesn't exercise `main()`'s actual dry-run branch

**File:** `tests/unit/test_gate166_frame_recalibration_eval.py:373-386`

**Issue:** This test builds `dry_run = True` as a local Python variable and asserts `if not
dry_run: await _write_gate166_row(...)` — i.e., it reimplements the branch condition inline in
the test itself rather than calling `main()` (or a refactored-out dispatch function) with
`args.dry_run=True`. Since `dry_run` is hardcoded to `True` in the test, the `if not dry_run`
body is unreachable by construction and `mock_pool.acquire.assert_not_called()` is trivially
true regardless of whether the real `main()` correctly gates its own write call on
`args.dry_run`. This test provides no regression protection if a future edit to `main()`
accidentally calls `_write_gate166_row` unconditionally.

**Fix:** Either invoke `main()` itself with `sys.argv`/`argparse` patched to include
`--dry-run` (mocking `asyncpg.create_pool` and the DB fetch), or at minimum restructure the
test to assert against the real conditional in `main()`'s source rather than a re-declared
local variable of the same name.

## Resolution

All 4 findings fixed same session, before phase completion:

- **WR-01**: Migration 254 corrects `alpha.frame.structure_snap_proximity_atr`'s description
  (idempotent, description-only, zero live behavior change) — traced the original "snap"
  description to a misreading of archived `trade_framer.py`'s actual semantics (a post-hoc
  stop_basis classification label, never a price transformation). Reserved for todo 175
  (Part 2), not implemented as new untested trading logic.
- **WR-02**: `_calibrate_stop_target` (`services/ensemble_ic_engine.py`) now narrows fetched
  `alpha_frames` rows to the exact `(symbol, tf)` pairs present in `results`, not symbol alone
  — the SQL-level comment was also corrected to stop claiming parity with
  `_calibrate_hold_max_bars`' scoping.
- **WR-03**: `missing_cost_hurdle_count`'s increment in `alpha_frame_writer.py` moved after the
  geometry-resolution skip-continue, so it no longer overcounts frames that are never written.
- **IN-01**: `test_dry_run_performs_zero_writes` (`tests/unit/test_gate166_frame_recalibration_eval.py`)
  rewritten to invoke `main()` itself (mocked `asyncpg.create_pool`, patched `sys.argv`) and
  assert `_write_gate166_row` is never called — now exercises the real conditional instead of
  a re-declared local variable.

Full `tests/unit/` suite green after all fixes (ruff/black clean).

---

_Reviewed: 2026-07-23T14:52:55Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Resolved: 2026-07-23 (same session)_
