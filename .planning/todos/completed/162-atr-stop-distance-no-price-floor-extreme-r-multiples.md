---
status: pending
priority: P1
filed: 2026-07-21
reclassified: 2026-07-21 -- P2->P1 same day, after checking the IN-SAMPLE population
  (not just 143.1-08's OOS window) and finding the same contamination, worse in
  magnitude and cross-cutting in scope. See "2026-07-21 escalation" below.
source: found while writing up 143.1-08's shadow-validation criteria (D-19-style
  data-quality check before trusting the champion/challenger numbers)
---

# ATR-based stop distance has no minimum-price-fraction floor — produces extreme R-multiple outliers on thin-ATR instruments

## 2026-07-21 escalation — this is not scoped to 143.1-08, and the tail is worse than first measured

Checked the in-sample population (`bar_ts < alpha.validation.oos_start`, the population
`counterfactual_tracker.py --evaluate-gate`'s FRAME-04 exit gate reads directly) after filing
this at P2 against only 143.1-08's OOS window. Same bug, same mechanism, **worse magnitude**:
`min(counterfactual_pnl_r) = -926.87` (EZU 5m, stop 0.056 price-units from a $51.55 entry —
0.11% of price), 25,094 of 22,387,404 in-sample closed frames (0.11%) exceed `abs(pnl_r) > 10`.
Every top-10 symbol/tf combination by extreme-frame count is a 5m FX or commodity ETF (FXE,
FXY, GLD, EWY, EWG, FXA, EZU, FXI, SLV, EWT) — the identical instrument class as the OOS
finding, confirming this is systemic to the instrument/timeframe combination, not an artifact
of this session's specific sign-symmetric run.

**Honest caveat, not confirmed either way:** `alpha_frames` currently contains only the two
`143.1-08-*` weight_epochs (checked live) — whatever population Component A's original
staged-validation gate (E6, referenced in 143.1-07's blocked-status writeup) or any prior
FRAME-04 evaluation ran against has since been superseded/replaced. **I cannot verify
retroactively whether those past gate verdicts were actually contaminated** — the underlying
row-level evidence no longer exists to check. Given the bug lives in `alpha_frame_writer.py`'s
`compute_frame_geometry()` (unrelated to 143.1-08's own changes, and present for as long as
ATR-based frame construction has run against this instrument set), it is *plausible* that any
past FRAME-04-style gate evaluation was affected — but this is a flagged risk to investigate
before trusting a past verdict at face value, not a confirmed retroactive finding. Reclassified
P2->P1 on cross-cutting blast radius and magnitude, not on a proven-wrong-decision claim.

## What's wrong

`compute_frame_geometry()` (`services/alpha_frame_writer.py:64`) derives `stop_price` as
`entry_price ± stop_atr_mult * atr`, guarding only against `atr <= 0` (a genuinely degenerate/
stale-bar case, raises `ValueError`, caller skips and counts it via `degenerate_atr_skip_count`).
It does NOT guard against `atr` being a small but perfectly legitimate positive value on a
low-absolute-volatility instrument at a short timeframe — e.g. an FX or commodity ETF (FXY, FXE,
DBB, DBC, GLD, SLV, EWT, MCHI, INDA) on 5m bars, where a real ATR can be ~0.02-0.3% of price.
The resulting stop is razor-thin in absolute terms; ordinary 5m price noise (not a real adverse
move) blows through it by many multiples, producing `counterfactual_pnl_r` values far beyond a
normal stop-out's ~-1.0R — observed down to **-57.27R** in the 143.1-08 shadow-validation corpus.

This is not the `degenerate_atr_skip` bug (that guard is working correctly, catching truly
zero/stale ATR — 754 frames skipped in the 2026-07-21 full backfill). This is a distinct,
previously-undetected gap: a *small-but-valid* ATR that still produces an economically
meaningless stop distance.

## Evidence (2026-07-21, 143.1-08 OOS window specifically, `bar_ts >= 2025-12-24` — see escalation above for the broader in-sample check)

- 766 champion + 3,439 challenger closed frames have `abs(counterfactual_pnl_r) > 5` (out of
  33,892 / 740,204 total — 2.3% / 0.46% of each population respectively).
- Sample extreme rows: FXY 5m stop 0.0236 price-units away from entry (0.04% of price) ->
  `counterfactual_pnl_r = -57.27`; similar pattern across FXE/DBB/BIL/SLV/EWT/DBC/GLD/MCHI/INDA,
  concentrated in 5m (and some 15m) bars.
- Confirmed NOT solely responsible for the qualitative shadow-validation result: trimming
  `abs(pnl_r) > 10` still leaves both champion (mean -0.136) and challenger (mean -0.040)
  net-negative over the OOS window — but these outliers materially inflate the *magnitude* of
  Sharpe and max-drawdown statistics computed from the full (untrimmed) population, which is
  what 143.1-08's pre-committed criteria actually gate on (GROSS `counterfactual_pnl_r`, no
  filtering).

## Why this matters beyond 143.1-08

Any current or future corpus-wide statistic computed from `alpha_frames.counterfactual_pnl_r`
(Sharpe, drawdown, mean-CI) inherits this same tail contamination whenever ATR-based framing runs
against thin-absolute-volatility instrument/timeframe combinations — not specific to the
champion/challenger comparison that surfaced it.

## RESOLVED 2026-07-21

Went with the skip-and-count direction, not the floor-widening one: a widened stop would
also widen `target_price` (derived from `stop_distance`) by the same factor, fabricating a
trading rule real ATR-based sizing never specified. `compute_frame_geometry()` now raises the
same `ValueError` it already raises for `atr <= 0` when `stop_distance <
alpha.frame.min_stop_price_fraction * entry_price` — same skip-and-count mechanism
(`degenerate_atr_skip_count`), no new stop-sizing logic, exactly the "alternative" direction
sketched below.

`alpha.frame.min_stop_price_fraction` seeded at 0.001 (0.10% of price), migration 243,
`[initial_estimate]`. Checked the live corpus before picking a number (not fit to the
observed outliers): extreme-frame rate vs. stop-distance% is a smooth, continuous gradient
with no natural cutoff (0.27% extreme rate at <0.05% stop-distance, declining to 0.07% at
0.28-0.30%, still above the ~0.03% baseline at wider buckets) — 0.10% is a conservative,
deliberately non-overfit starting point past the steepest part of that curve, flagged for
future recalibration once more corpus runs exist to properly characterize the
rejected-frame-count vs. residual-extreme-tail-rate tradeoff.

Threaded through `FrameConfig.from_apr` (eager validation, mirroring `stop_atr_mult`'s
precedent) and the full call chain `_execute_inner -> worker_args ->
_run_counterfactual_worker -> _scan_symbol_tf -> compute_frame_geometry`.
`compute_frame_geometry` has exactly one call site in the whole codebase, so no other
consumer needed updating. Full diff: `services/alpha_frame_writer.py`,
`services/counterfactual_tracker.py`, `tests/unit/test_alpha_frame_writer_geometry.py`,
`production/migrations/243_frame_min_stop_price_fraction.sql`.

**Not done here, deliberately separate:** whether frame geometry should become SR-aware once
Phase 163 ships real `sr_support_dist`/`sr_resist_dist` data (currently 100% NULL) is a
distinct, bigger design question — see the new Phase 163 cross-reference todo. This fix is
data-integrity hygiene on the existing ATR-only path, not a redesign of it.

## Candidate fix directions (historical — see RESOLVED above for what shipped)

- A minimum stop-distance floor as a fraction of price (e.g. `max(stop_atr_mult * atr,
  min_stop_price_fraction * entry_price)`), APR-backed (`alpha.frame.min_stop_price_fraction`
  or similar namespace).
- Alternative: widen the existing `degenerate_atr_skip` guard from `atr <= 0` to `atr <=
  some_price_relative_floor`, same skip-and-count mechanism, no new stop-sizing logic.
- Needs a real decision on which instruments/timeframes are most affected (looks concentrated
  in FX/commodity ETFs at 5m/15m) and whether this is a stop-sizing issue specifically or also
  affects `target_price`/`r_multiple` (same `stop_atr_mult`-derived `stop_distance` feeds both).

## References

- `services/alpha_frame_writer.py:64` (`compute_frame_geometry` — the `atr <= 0` guard that
  doesn't catch this case)
- `services/counterfactual_tracker.py:441-455` (the try/except around `compute_frame_geometry`,
  `degenerate_atr_skip_count`)
- `.planning/milestones/v3.1-phases/143.1-measurement-and-eligibility-integrity-fisher-z-ci-bootstrap-/143.1-08-SHADOW-VALIDATION.md`
  Section 6 — where this was found
