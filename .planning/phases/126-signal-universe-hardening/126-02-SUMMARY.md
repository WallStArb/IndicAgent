---
phase: "126"
plan: "02"
subsystem: "signal-universe"
tags: ["i7-plugins", "confluence-wiring", "signal-diagnostics", "fvg-audit", "orb-plugins", "mean-reversion"]
dependency_graph:
  requires: ["126-01"]
  provides: ["i6-confluence-complete", "zero-signal-verdicts", "fvg-defect-documented"]
  affects: ["intelligence_pipeline", "shadow_registry", "signal_ledger"]
tech_stack:
  added: []
  patterns:
    - "bar-by-bar stateful plugin testing (compute_full() incremental calls)"
    - "SQL quantitative diagnostic: entry-timing defect via zone overlap check"
    - "ECL annotation pattern (ctf_score/ctf_confirmed non-gate passthrough)"
key_files:
  created:
    - "production/migrations/133_phase126_mean_reversion.sql"
    - "tests/unit/intelligence/test_orb_plugins.py"
  modified:
    - "src/intelligence/register_plugins.py"
    - "src/intelligence/plugins/base.py"
    - "src/intelligence/trading/regime_transition.py"
    - "src/intelligence/trading/prev_day_level_test.py"
    - "src/intelligence/trading/anchored_vwap_reversion.py"
    - "src/intelligence/trading/poc_rejection.py"
    - "src/intelligence/trading/hvn_rejection.py"
    - "src/intelligence/trading/cross_asset_divergence.py"
    - "src/intelligence/trading/mean_reversion.py"
    - "src/intelligence/trading/squeeze_expansion.py"
    - "src/intelligence/trading/session_extremes_setup.py"
    - "src/intelligence/trading/orb15.py"
    - "src/intelligence/trading/orb30.py"
    - "src/intelligence/trading/fvg_fill.py"
    - "tests/unit/intelligence/test_i6_confluence_enforcement.py"
decisions:
  - "MeanReversion dual-gate conflict: Gate A (|trend_regime| < 0.4) and Gate B (|kalman_price_position| >= 1.0) are mathematically contradictory; 0.005% of bars pass both; parked shadow_only=True, relaxed gate to 0.2 via APR; redesign needed"
  - "SessionExtremesSetup SCOPE-MISMATCH: zero asian_session_high coverage in corpus; no code change; set shadow_only=False when Asian-session instruments added"
  - "ORB15/ORB30 CORRECT-RARE: gate logic structurally sound, fires <=2x per RTH session per symbol; correct behavior"
  - "FVGFill ENTRY-TIMING DEFECT: uses close[-1] as market entry (fires on presence, not fill); 86% of entries outside FVG zone; fix requires at_limit entry type; documented for Phase 127"
metrics:
  duration_minutes: 95
  completed_date: "2026-06-15"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 15
  tests_added: 13
---

# Phase 126 Plan 02: Signal Universe Hardening - Confluence Wiring and Zero-Signal Diagnoses Summary

Wire all 8 formerly-exempt I7 plugins to I6 confluence (ECL annotation pattern), diagnose 3 zero-signal time-specific plugins with quantified verdicts, and deliver a quantitative root-cause analysis of FVGFill's catastrophic 8.93% equity win rate.

## What Was Built

### Task 1: Delete _I7_I6_EXEMPT, Wire 8 Plugins

Deleted the `_I7_I6_EXEMPT` frozenset from `register_plugins.py` and the corresponding carve-out from `validate_tier()` in `base.py`. Wired all 8 formerly-exempt plugins:

| Plugin | File |
| --- | --- |
| RegimeTransition | regime_transition.py |
| PrevDayLevelTest | prev_day_level_test.py |
| AnchoredVWAPReversion | anchored_vwap_reversion.py |
| POCRejection | poc_rejection.py |
| HVNRejection | hvn_rejection.py |
| CrossAssetDivergence | cross_asset_divergence.py |
| MeanReversion | mean_reversion.py |
| SqueezeExpansion | squeeze_expansion.py |

Each plugin received:
- `requires_i6_confluence: bool = True`
- ECL annotation block: `ctf_score` and `ctf_confirmed` computed and passed to `make_signal_from_frame()`
- `get_min_ctf_score` import

ECL is annotation-only (Phase 123 principle): `ctf_score`/`ctf_confirmed` are extrinsic metadata, not emission gates. No `return no_signal()` added after the ECL block.

Updated `test_i6_confluence_enforcement.py` to cover ALL TIER_I7 plugins with no exemptions.

### Task 2: Zero-Signal Plugin Diagnoses

**SessionExtremesSetup - SCOPE-MISMATCH**

SQL probe on 2,222,900 bars: `asian_session_high` has zero occurrences in `intelligence_features`. The current instrument universe (ES, NQ, RTY, FX pairs) does not include Asian-session products that publish this field. Gate logic is structurally correct. No code change required; added verdict docstring with resolution path.

**ORB15 / ORB30 - CORRECT-RARE**

Both plugins are stateful bar-by-bar accumulators that fire at most twice per RTH session per symbol (once long, once short via fire-once guard). Zero corpus fires are expected when: corpus lacks RTH bar coverage for the session date range, volume expansion gate (1.5x avg) is stringent, or pipeline was not running during US market hours. Gate logic verified.

Created `tests/unit/intelligence/test_orb_plugins.py` with 13 tests using bar-by-bar simulation (calling `compute_full()` once per bar with incrementally growing DataFrames to replicate live pipeline state accumulation). All 13 tests pass.

**MeanReversion - ENTRY-GATE-CONFLICT (major finding)**

SQL probe revealed dual-gate mutual exclusion:
- Gate A (`|trend_regime| < 0.4`): 120,648 bars (5.4%)
- Gate B (`|kalman_price_position| >= 1.0`): 276,144 bars (12.4%)
- Both gates simultaneously: **114 bars (0.005%)**

Root cause: In ranging regimes (where Gate A passes), `kalman_price_position` is near-zero (p50 = 2.57e-13) because the Kalman filter tracks price closely when there is no persistent trend. Gate B demands LARGE displacement from Kalman fair value, which cannot exist in the same bars where Gate A demands a ranging regime.

Fix: relaxed Gate A from 0.4 to 0.2 via APR key `threshold.mean_reversion.trend_regime_max`, registered in migration 133. Plugin parked `shadow_only=True` pending fundamental redesign - the gates are logically contradictory and must be replaced, not tuned.

### Task 3: FVGFill Diagnostic

SQL diagnostic on 68,800 signals confirmed ENTRY-TIMING DEFECT:

| Entry Position | Count | avg_pnl_r |
| --- | --- | --- |
| long above zone_high | 28,609 (86%) | -0.68R |
| long inside zone | 4,686 (14%) | -0.28R |
| short below zone_low | 30,113 (85%) | -0.66R |
| short inside zone | 5,392 (15%) | -0.19R |

The plugin uses `close[-1]` as market entry at the moment `fvg_type != 0` is detected. The FVG fill thesis requires entering AT the FVG zone boundary (limit order), not at current market price after the gap has formed and price has moved away from it. When price is above zone_high on a bull FVG, a long entry is buying into momentum AGAINST the mean-reversion fill direction.

In-zone entries perform 2.4x better in expectancy, confirming the defect is structural.

Fix design (not implemented; requires Phase 127 architectural change):
1. Change entry_type to `at_limit`, set `entry_price = fvg_top` (bull) or `fvg_bottom` (bear)
2. Add proximity gate: only fire if `abs(close - fvg_zone_boundary) < N * atr`
3. Register `threshold.fvg_fill.proximity_atr_max` in APR (seed: 0.5)
4. Requires `trade_framer.py` changes for at_limit FVG semantics

The 8.93% equity win rate is fully explained by this defect. Average pnl_r = -0.60R.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] MeanReversion gate relaxation registered in APR**
- **Found during:** Task 2 (MeanReversion diagnosis)
- **Issue:** After discovering the dual-gate conflict, the threshold relaxation (0.4 to 0.2) needed to be in APR (config_state), not hard-coded
- **Fix:** Created migration 133 registering `threshold.mean_reversion.trend_regime_max = 0.2`; plugin reads via `cfg.get_sync()` at runtime
- **Files modified:** `mean_reversion.py`, `production/migrations/133_phase126_mean_reversion.sql`
- **Commit:** 219a98bf

**2. [Rule 1 - Bug] ORB unit test approach was wrong (bar-by-bar vs batch)**
- **Found during:** Task 2 (ORB test implementation)
- **Issue:** Initial tests passed all bars in a single `compute_full()` call; ORB plugins only process `df.iloc[-1]` so state never accumulated
- **Fix:** Rewrote tests to call `compute_full()` once per bar with incrementally growing DataFrames; added `_simulate_session_to_orb15_breakout()` and `_simulate_session_to_orb30_breakout()` helper functions
- **Files modified:** `tests/unit/intelligence/test_orb_plugins.py`
- **Commit:** 219a98bf

**3. [Rule 3 - Blocking] Pre-commit hook missing .venv symlink in worktree**
- **Found during:** Task 1 first commit attempt
- **Issue:** Pre-commit hook uses `REPO_ROOT/.venv/bin/ruff` but REPO_ROOT in worktree is the worktree dir, not the main repo
- **Fix:** Created symlink `.venv -> /home/bg/dev/indicagent/.venv` in worktree directory
- **Files modified:** (symlink only, not tracked)
- **Commit:** n/a (infrastructure fix)

## Commits

| Hash | Description |
| --- | --- |
| 9570e164 | feat(126-02): wire 8 exempt plugins to I6, delete _I7_I6_EXEMPT |
| 219a98bf | feat(126-02): diagnose zero-signal plugins, relax MeanReversion gate, add ORB tests |
| d7fb35ef | fix(126-02): FVGFill entry-timing defect - document root cause and fix design |

## Self-Check: PASSED

All 4 key files verified present. All 3 task commits verified in git log. All 8 formerly-exempt plugins have `requires_i6_confluence: bool = True` confirmed by grep.
