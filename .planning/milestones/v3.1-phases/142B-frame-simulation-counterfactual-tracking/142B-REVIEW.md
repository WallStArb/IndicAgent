---
phase: 142B-frame-simulation-counterfactual-tracking
reviewed: 2026-07-10T00:00:00Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - docs/plans/SHADOW-REVIEW.md
  - production/migrations/214_alpha_frames_schema.sql
  - scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh
  - services/alpha_frame_writer.py
  - services/counterfactual_tracker.py
  - services/service_auditor.py
  - src/observability/metrics.py
  - tests/unit/test_alpha_frames_schema.py
  - tests/unit/test_alpha_frame_writer_geometry.py
  - tests/unit/test_alpha_frame_writer.py
  - tests/unit/test_counterfactual_tracker_exit_priority.py
  - tests/unit/test_counterfactual_tracker.py
  - tests/unit/test_frame_gate.py
findings:
  critical: 2
  warning: 3
  info: 2
  total: 7
status: fixed
fixed_at: 2026-07-10T07:52:01-04:00
fix_commit: fa4208ef
---

# Phase 142B: Code Review Report

**Reviewed:** 2026-07-10T00:00:00Z
**Depth:** standard
**Files Reviewed:** 13
**Status:** fixed — all 7 findings resolved in commit `fa4208ef` (2026-07-10), independently
confirmed present in code by `142B-VERIFICATION.md`'s phase verification pass, not just
claimed. Findings below are preserved as the original review record.

## Summary

`AlphaFrameWriter` and `CounterfactualTracker` are well-instrumented, direction-aware, and
mostly consistent with the invariants their own docstrings claim (composite hypertable PK, no
FK to `alpha_events`, worker-side write-freedom, day-clustered bootstrap gate, causal ATR).
`service_auditor.py` and `metrics.py` changes are minimal and correct (two `_DAG_ORDER`/
`_ONESHOT_UNITS` entries, one new gauge). Test coverage for `determine_exit`'s direction-aware
priority ordering and the day-clustered bootstrap is genuinely thorough.

However, two BLOCKER-class defects survived: (1) `compute_frame_geometry` divides by zero
whenever the causal ATR (or `stop_atr_mult`) is exactly `0.0` — a real, not merely theoretical,
condition for stale/forward-filled bars or genuinely flat illiquid instruments — and the
resulting `ZeroDivisionError` propagates out of the *entire* streaming scan for that
`(symbol, tf)` cell, silently discarding every already-finalized frame's result from that pass
and permanently poisoning the cell for every future run touching the same historical bars. (2)
`target_r_multiple` is read live from current APR by `CounterfactualTracker` at scan time
instead of being snapshotted onto the `alpha_frames` row the way `stop_atr_mult` and `cost_r`
explicitly are — this is precisely the "silent historical drift on recalibration" failure mode
the migration's own comments describe and guard against for `cost_r`, just not applied
consistently to `target_r_multiple`. Both defects directly touch the frame corpus that Phase
142B's own gate (and eventually the frozen Phase 147 SHADOW-REVIEW criteria) depend on for a
correct pass/fail verdict.

## Critical Issues

### CR-01: `compute_frame_geometry` raises `ZeroDivisionError` on zero ATR (or zero `stop_atr_mult`), permanently poisoning the whole `(symbol, tf)` scan

**File:** `services/alpha_frame_writer.py:78-90`, consumed by `services/counterfactual_tracker.py:408-413`

**Issue:** `compute_frame_geometry` computes `r_multiple` as
`(target_price - entry_price) / (entry_price - stop_price)` (long) or
`(entry_price - target_price) / (stop_price - entry_price)` (short). Both denominators equal
`stop_atr_mult * atr`. When the causal ATR computed in `_scan_symbol_tf` (line 408,
`atr = sum(tr_window) / len(tr_window)`) is exactly `0.0` — which happens whenever every bar in
the trailing `atr_period` window has identical open/high/low/close and no gap from the prior
close (a real occurrence for stale/forward-filled bars during an IBKR outage, or genuinely flat
illiquid ETFs/futures) — `stop_distance` is `0.0`, so `r_multiple` becomes Python float
`0.0 / 0.0`, which **raises `ZeroDivisionError`**, not `NaN`. The same happens if an operator
ever sets `alpha.frame.stop_atr_mult` to `0` in APR (no floor/validation exists on that key).

This exception is raised from *inside* the single streaming per-(symbol, tf) bar scan in
`_scan_symbol_tf` (not per-frame-guarded). The only exception handler is the per-`tf` `try`
in `_run_counterfactual_worker` (`services/counterfactual_tracker.py:496-506`), which catches
it, logs `"{symbol}/{tf}: {error}"`, and moves to the next `tf` — but by then `_scan_symbol_tf`
has already aborted mid-function and its local `results` list (which may contain thousands of
already-correctly-finalized frames scanned *before* the degenerate bar was reached) is
discarded entirely; nothing from that pass is ever flushed. Because the root cause is a fixed
historical fact in `market_data_ohlcv`, **every subsequent run will hit the identical bar and
fail identically** — this is a permanent poison-pill for that `(symbol, tf)` cell, not a
transient failure, silently starving that cell of any counterfactual outcomes forever (directly
violating this project's "never drop data that could contain signal" principle).

No unit test exercises `atr == 0`.

**Fix:**
```python
# services/alpha_frame_writer.py
def compute_frame_geometry(
    direction: str,
    entry_price: float,
    atr: float,
    stop_atr_mult: float,
    target_r_multiple: float,
) -> tuple[float, float, float]:
    if atr <= 0 or stop_atr_mult <= 0:
        raise ValueError(
            f"compute_frame_geometry: non-positive stop distance "
            f"(atr={atr}, stop_atr_mult={stop_atr_mult}) -- cannot derive a stop/target"
        )
    ...
```
And in `services/counterfactual_tracker.py`, guard the per-frame activation so one degenerate
bar cannot abort the whole cell's scan:
```python
try:
    stop_price, target_price, r_multiple = compute_frame_geometry(
        direction, entry_price, atr, float(frame["stop_atr_mult"]), target_r_multiple
    )
except ValueError as error:
    _logger.warning(
        "counterfactual_tracker.degenerate_atr_skip",
        symbol=symbol, tf=tf, frame_id=frame["frame_id"], error=str(error),
    )
    continue  # leave this frame open, do not abort the rest of the cell's scan
```

### CR-02: `target_r_multiple` is not snapshotted on `alpha_frames` — `CounterfactualTracker` scores geometry with the *current* APR value, not the value `AlphaFrameWriter` used for `gross_expected_r`/`net_expected_r`

**File:** `production/migrations/214_alpha_frames_schema.sql:70-76`, `services/alpha_frame_writer.py:93-132`, `services/counterfactual_tracker.py:408-413,624-627,656`

**Issue:** `AlphaFrameWriter` snapshots `stop_atr_mult` onto every row (migration 214 line 75,
`stop_atr_mult double precision`) explicitly so it can be read back unchanged later
(`float(frame["stop_atr_mult"])` in `counterfactual_tracker.py:412`). `cost_r` is likewise
copy-through snapshotted from `alpha_events.cost_hurdle`, and the migration's own column
comment states the reason explicitly: *"NOT re-derived live from the `alpha.quant.cost_hurdle.<tf>`
APR key, so `net_expected_r` never silently drifts from historical truth on the next
cost-hurdle recalibration + backfill re-run"* (migration 214, lines 144-149).

`target_r_multiple` receives no such treatment. `alpha_frames` has **no `target_r_multiple`
column at all**. `AlphaFrameWriter` uses its own load-time APR value
(`frame_config.target_r_multiple`, from `FrameConfig.from_apr`) to compute
`gross_expected_r = abs(alpha_score) * target_r_multiple` and persist it into the row
(`compute_expected_r_snapshot`, `alpha_frame_writer.py:93-114`). `CounterfactualTracker`, run at
an arbitrary later time (nightly incremental or `--backfill`), instead reads
`alpha.frame.target_r_multiple` fresh from **current** `config_state`
(`counterfactual_tracker.py:625`, `target_r_multiple = _cfg(cfg, "alpha.frame.target_r_multiple", 2.0)`)
and uses that single, uniform, "now" value for *every* open frame it scans in that run
(`counterfactual_tracker.py:411-413`, passed straight into `compute_frame_geometry`), regardless
of what `target_r_multiple` was in effect when each individual frame was written.

If `alpha.frame.target_r_multiple` is ever recalibrated between an `AlphaFrameWriter` run and a
later `CounterfactualTracker` run (or across two `CounterfactualTracker` runs straddling a
recalibration, since not all frames close in a single pass), the corpus ends up with rows whose
`gross_expected_r`/`net_expected_r` diagnostics (computed under the OLD value) are silently
inconsistent with `target_price`/`r_multiple`/`counterfactual_pnl_r` (computed under the value
live at scan time) for the same row — exactly the "silent historical drift" failure mode the
migration explicitly designed `cost_r` to avoid, applied inconsistently here. This corrupts the
audit trail the `gross_expected_r`/`net_expected_r`/`counterfactual_pnl_r` triad is meant to
support, and — because `target_r_multiple` directly shapes `target_price` — it changes which
bars trigger `closed_target` vs `closed_max_hold`, silently biasing the FRAME-04 gate and the
eventual SHADOW-REVIEW criteria the corpus feeds.

**Fix:** Add a `target_r_multiple double precision` column to `alpha_frames` (mirroring
`stop_atr_mult`), have `AlphaFrameWriter` write it into every row, and have
`CounterfactualTracker` read `float(frame["target_r_multiple"])` from the fetched row (as it
already does for `frame["stop_atr_mult"]`) instead of `_cfg(cfg, "alpha.frame.target_r_multiple", ...)`
at scan time.

## Warnings

### WR-01: FRAME-04 bootstrap CI has no fixed seed — the "frozen," non-negotiable gate verdict is not reproducible across runs

**File:** `services/counterfactual_tracker.py:201-209`

**Issue:** `frame_gate_passes` calls `scipy.stats.bootstrap((cluster_means,), np.mean, ...,
method="BCa", batch=bootstrap_batch)` with no `random_state=` argument. `scipy.stats.bootstrap`
without an explicit `rng`/`random_state` uses non-deterministic entropy per call, so re-running
`counterfactual_tracker.py --evaluate-gate` twice against the *identical* frame data can produce
a different `ci_lower` each time. `SHADOW-REVIEW.md` (this same phase's own frozen spec)
explicitly states *"Post-hoc gate negotiation... is not permitted. If the gate fails, diagnose —
don't renegotiate"* — but a borderline cell whose `ci_lower` straddles `0` could flip pass/fail
on nothing but re-run luck, which is worse than negotiation: it's silent non-determinism in the
thing the "no renegotiation" rule is meant to protect. CLAUDE.md's APR mandate explicitly names
this failure class: *"Seeds that affect algorithm output → APR (e.g., `HMM_RANDOM_STATE = 42` →
`alpha.hmm.random_state`...)."* No such seed exists for this bootstrap.

**Fix:**
```python
result = bootstrap(
    (cluster_means,),
    np.mean,
    confidence_level=0.95,
    alternative="greater",
    method="BCa",
    batch=bootstrap_batch,
    random_state=np.random.default_rng(_cfg(cfg, "alpha.scoring.bootstrap_random_state", 42)),
)
```
Seed via a new `alpha.scoring.bootstrap_random_state` APR key, per the project's seed-APR
convention, and document that changing it invalidates prior gate verdicts.

### WR-02: `hold_max_bars` fallback to the hardcoded default is silent and uninstrumented when `regime` is `None`

**File:** `services/alpha_frame_writer.py:295-296`

**Issue:** `alpha_events.regime` is nullable (`production/migrations/168_ensemble_tables.sql:102`,
`regime text,` with no `NOT NULL`). When `regime` is `None`,
`hold_key = f"alpha.frame.hold_max_bars.{regime}.{tf}"` formats to the literal string
`"alpha.frame.hold_max_bars.None.5m"`, which will never exist among the 36 seeded
`alpha.frame.hold_max_bars.<regime>.<tf>` keys (migration 195). `_cfg()` (`services/_batch_utils.py:129-132`)
silently returns the hardcoded `_DEFAULT_HOLD_MAX_BARS = 60` fallback with no logging or metric
whatsoever — indistinguishable from a legitimately-seeded 60-bar hold. This is the same class of
condition the codebase already instruments elsewhere (e.g. `PLUGIN_FALLBACK_TOTAL`,
"Plugin fallbacks to direct calculation") and CLAUDE.md's stated design mindset ("Silent wrong
answers are worse than loud crashes"; "Instrument everything") explicitly calls out.

**Fix:** Emit a counter (or at minimum a `logger.warning`) whenever the `hold_key` lookup misses
the loaded APR dict, so a `None`/unexpected `regime` or an un-seeded new regime label is visible
instead of silently defaulting:
```python
if hold_key not in cfg:
    self.logger.warning("alpha_frame_writer.hold_max_bars_key_missing", hold_key=hold_key, regime=regime, tf=tf)
max_hold_bars = int(_cfg(cfg, hold_key, _DEFAULT_HOLD_MAX_BARS))
```

### WR-03: SHADOW-REVIEW.md's ratio-based criteria 4 and 5 are undefined for non-positive denominators

**File:** `docs/plans/SHADOW-REVIEW.md:49-56`, `:61-68`

**Issue:** Criterion 4 (max drawdown) is specified as
`max_peak_to_trough_decline_R / peak_cumulative_R_at_trough < 0.25`, and criterion 5 (no
IC-Sharpe cliff) as `last_20d_IC_Sharpe / full_period_IC_Sharpe >= 0.5`. Neither the doc nor any
reviewed code addresses the case where the denominator is zero or negative:
`peak_cumulative_R_at_trough` can be `<= 0` early in a shadow period before cumulative R turns
positive, and `full_period_IC_Sharpe` can legitimately be negative. In either case the ratio
comparison is either undefined (division by zero) or sign-inverted (a ratio of two negatives can
exceed `0.5` while the underlying trend is actually deteriorating, silently producing a
"passing" verdict on data that should fail). Since this document is explicitly FROZEN as the
authoritative, non-negotiable spec for Phase 147, this ambiguity should be resolved now — before
any implementer has to guess under gate-evaluation pressure, at which point fixing it would
itself look like post-hoc negotiation.

**Fix:** Add an explicit clause to each criterion, e.g.: "If `peak_cumulative_R_at_trough <= 0`
at the point of maximum decline, criterion 4 fails outright (undefined base, cannot certify a
bounded drawdown)." and "If `full_period_IC_Sharpe <= 0`, criterion 5 fails outright regardless
of the ratio (a negative full-period Sharpe is disqualifying on its own, independent of any
cliff)."

## Info

### IN-01: `cost_r` silently defaults to `0.0` with no observability when `alpha_events.cost_hurdle` is NULL

**File:** `services/alpha_frame_writer.py:289`

**Issue:** `cost_r = float(row["cost_hurdle"]) if row["cost_hurdle"] is not None else 0.0` treats
a missing cost snapshot as zero cost, which makes `net_expected_r` look identical to
`gross_expected_r` for that row with no way to distinguish "genuinely zero cost" from "cost
data was never populated." Low impact since both are reporting-only diagnostics (not gate
inputs per D-01/D-02), but worth a counter for corpus-quality auditing.

**Fix:** Increment a small counter (or log) when `row["cost_hurdle"] is None` so a downstream
audit of the diagnostic columns can distinguish "cost known to be zero" from "cost unknown."

### IN-02: Unclosed cursor in worker connection-liveness check

**File:** `services/counterfactual_tracker.py:489`

**Issue:** `conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor).execute("SELECT 1")`
creates a cursor object and never closes it (no `with` block, no `.close()`). Relies on garbage
collection. Minor resource hygiene issue in a subprocess worker that otherwise carefully manages
connection lifecycle (`conn.close()` in the `finally` block).

**Fix:**
```python
with conn.cursor() as probe_cur:
    probe_cur.execute("SELECT 1")
```

---

_Reviewed: 2026-07-10T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
