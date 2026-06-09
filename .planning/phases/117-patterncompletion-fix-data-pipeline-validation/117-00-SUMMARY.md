---
phase: 117-patterncompletion-fix-data-pipeline-validation
plan: "00"
subsystem: intelligence-pipeline
tags:
  - signal-quality
  - cvd-divergence
  - confidence-wiring
  - i6-confluence
  - hmm-regime
  - signal-probe-auditor
  - oneshot
  - migration
dependency_graph:
  requires:
    - signal_ledger_full view (migration 095)
    - hmm_regime_weight (src/intelligence/utils/gradient_utils.py)
    - compose_confidence (src/intelligence/trading/confidence_utils.py)
  provides:
    - CVD threshold floor enforced (0.002) in cvd_divergence.py
    - ctf_score + hmm_regime_weight wired into 6 high-volume NEEDS_REFACTOR plugins
    - signal_probe_results table (migration 120)
    - SignalProbeAuditor daily oneshot for ground-truth outcome simulation
  affects:
    - signal confidence values for 6 plugins (additive wiring only)
    - signal_probe_results (new table, daily writes)
tech_stack:
  added:
    - signal_probe_results table (TimescaleDB plain table)
    - indicagent-signal-probe-auditor systemd service + timer pair
  patterns:
    - Additive confidence wiring (ctf_score + hmm_regime_weight before compose_confidence)
    - Daily oneshot mirroring shadow_auditor D-06 pattern
key_files:
  created:
    - production/migrations/120_signal_probe_results.sql
    - services/signal_probe_auditor.py
    - production/systemd/indicagent-signal-probe-auditor.service
    - production/systemd/indicagent-signal-probe-auditor.timer
    - tests/unit/services/test_signal_probe_auditor.py
    - tests/unit/intelligence/test_i6_hmm_confidence_wiring.py
  modified:
    - src/intelligence/trading/cvd_divergence.py
    - src/intelligence/trading/ofi_continuation.py
    - src/intelligence/trading/gap_analysis_setup.py
    - src/intelligence/trading/divergence_stack.py
    - src/intelligence/trading/microstructure_utils.py
    - services/service_auditor.py
decisions:
  - "CVD threshold set to 0.002 (conservative floor); empirical value deferred to Phase 117.5 after probe data accumulates"
  - "ctf + hmm contributions are additive-only to raw confidence; gate thresholds and signal logic untouched"
  - "simulate_outcome extracted as pure function testable without DB; coarse sim_outcome strings (never_activated/window_end) defer taxonomy to Phase 117.5"
  - "signal_probe_results uses plain table (not hypertable) for simplicity; probe volume is low (1% sample, daily)"
metrics:
  duration: ~90 minutes
  completed: 2026-06-08
  tasks: 3
  files: 12
---

# Phase 117 Plan 00: Fix Data Pipeline Validation Summary

**One-liner:** CVD floor 0.0->0.002 enforced; ctf_score + hmm_regime_weight wired additively into 6 high-volume NEEDS_REFACTOR plugins; SignalProbeAuditor daily oneshot generates ground-truth sim outcomes from OHLCV for Phase 117.5 threshold derivation.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Fix CVD threshold floor + wire ctf_score/hmm_regime_weight into 4 stateful plugins | `0cd4f15e` | cvd_divergence.py, ofi_continuation.py, gap_analysis_setup.py, divergence_stack.py |
| 2 | Wire ctf_score + hmm_regime_weight into shared spike util + add wiring test | `8c0fd6b3` | microstructure_utils.py, test_i6_hmm_confidence_wiring.py |
| 3 | SignalProbeAuditor migration + daily oneshot + systemd pair + DAG registration + test | `ddcc21d8` | 120_signal_probe_results.sql, signal_probe_auditor.py, systemd pair, service_auditor.py, test_signal_probe_auditor.py |

## What Was Built

### Task 1: CVD Floor + 4 Stateful Plugin Confidence Wiring

Changed `_CVD_DIV_THRESHOLD: float = 0.0` to `0.002` in `cvd_divergence.py` and replaced the `if cvd_div == 0.0:` guard with `if abs(cvd_div) < _CVD_DIV_THRESHOLD:` so the floor is actually enforced at the gate (previously the constant was declared but never compared).

Wired ctf_score and hmm_regime_weight into all 4 stateful plugins (cvd_divergence, ofi_continuation, gap_analysis_setup, divergence_stack) using identical additive expressions just before `compose_confidence()`:

- ctf contribution: `+= 0.15 * min(1.0, abs(ctf_score)/0.7)` when `abs(ctf_score) > 0.3`
- hmm contribution: `+= 0.10 * (regime_w - 0.5)` (0.5-neutral; high-conviction = +0.05 max, contra = -0.05 max)

No gate thresholds, bar counts, direction expressions, or signal structures changed. `compose_confidence()` clamps final value.

### Task 2: Shared Spike Util + Wiring Test

Added the same ctf + hmm additive wiring to `detect_spike_signal` in `microstructure_utils.py`. Both `ofi_spike.py` and `cvd_spike.py` delegate entirely to this util and inherited the wiring without modification.

Test `test_i6_hmm_confidence_wiring.py` proves:
- favorable I6 confidence strictly exceeds bare confidence for the spike path
- `abs(cvd_div) < 0.002` returns no_signal (CVD floor enforced)

### Task 3: SignalProbeAuditor Daily Oneshot

**Migration 120** creates `signal_probe_results` with PK `(signal_id, probed_at)`, a unique index on `signal_id` for idempotency, and an index on `(setup_plugin, probed_at)` for Phase 117.5 analysis queries.

**`signal_probe_auditor.py`** mirrors `shadow_auditor.py` structure exactly:
- `NEEDS_REFACTOR_SETUPS` frozenset of all 21 setup names from RCA Appendix A
- `_select_unselected_sample()`: queries `signal_ledger_full` for `was_selected=false AND NOT is_shadow AND activated_at IS NULL AND status IN ('expired','regime_suppressed')` in the last 2 days, applies `random() < 0.01` sampling, excludes already-probed signal_ids via NOT EXISTS
- `simulate_outcome()`: pure function (no DB) that scans up to `MAX_BARS_FORWARD=20` bars for zone entry, computes pnl_r/mae/mfe in R units using stop distance, returns `sim_outcome='never_activated'` or `'window_end'`
- `_run_probe()`: orchestrates sample + simulate + batch `executemany` INSERT with `ON CONFLICT DO NOTHING`
- `main()`: D-06 compliant with `job_completed_total{job=signal-probe-auditor}` on success and failure paths, `flush_and_shutdown_metrics()` in finally

**Systemd timer** runs daily at 03:30 (`OnCalendar=*-*-* 03:30:00`, `Persistent=true`).

**`service_auditor.py`** registers `indicagent-signal-probe-auditor` in `_DAG_ORDER` at priority 8 and adds it to `_ONESHOT_UNITS`.

**Test** covers: long activation when bar dips to entry_zone_high, never_activated when bars stay above zone, short activation, positive/negative pnl_r sign correctness, empty bars, missing entry zone, bars_forward count, D-06 label constant, 21-setup frozenset membership.

## Verification

```
.venv/bin/pytest tests/unit/services/test_signal_probe_auditor.py -q   → 11 passed
.venv/bin/pytest tests/unit/intelligence/test_i6_hmm_confidence_wiring.py -q   → green
.venv/bin/ruff check services/signal_probe_auditor.py tests/unit/services/test_signal_probe_auditor.py   → all checks passed
```

Full unit suite (excluding pre-existing correctness/ collection errors): 4348 passed, 35 pre-existing failures (none in task 3 scope).

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- `/home/bg/dev/indicagent/.claude/worktrees/agent-a1595fef2e68acb11/production/migrations/120_signal_probe_results.sql` - FOUND
- `/home/bg/dev/indicagent/.claude/worktrees/agent-a1595fef2e68acb11/services/signal_probe_auditor.py` - FOUND
- `/home/bg/dev/indicagent/.claude/worktrees/agent-a1595fef2e68acb11/production/systemd/indicagent-signal-probe-auditor.service` - FOUND
- `/home/bg/dev/indicagent/.claude/worktrees/agent-a1595fef2e68acb11/production/systemd/indicagent-signal-probe-auditor.timer` - FOUND
- `/home/bg/dev/indicagent/.claude/worktrees/agent-a1595fef2e68acb11/tests/unit/services/test_signal_probe_auditor.py` - FOUND
- Commit `ddcc21d8` - FOUND (feat(117-00): add SignalProbeAuditor daily oneshot + migration 120 + systemd pair)
- Commit `0cd4f15e` - FOUND (fix(117-00): CVD threshold floor + ctf_score/hmm_regime_weight wiring in 4 stateful plugins)
- Commit `8c0fd6b3` - FOUND (feat(117-00): wire ctf_score + hmm_regime_weight into shared spike util + add wiring test)
