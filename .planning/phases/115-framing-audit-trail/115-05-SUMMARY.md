---
phase: 115
plan: "05"
subsystem: trade_framer_observability
tags: [tdd, otel, histogram, structlog, framing, audit-trail]
dependency_graph:
  requires: [TradeFrame.adaptive_buffer_mult, frame_trade.regime_type kwarg]
  provides: [STOP_BUFFER_MULT_DISTRIBUTION histogram, adaptive_buffer_applied structlog debug]
  affects: [metrics.py, trade_framer.py, Grafana dashboards]
tech_stack:
  added: []
  patterns: [TDD red-green, OTel histogram, structlog.testing.capture_logs]
key_files:
  created: []
  modified:
    - src/observability/metrics.py
    - src/intelligence/trading/trade_framer.py
    - tests/unit/intelligence/test_trade_framer.py
decisions:
  - "Used structlog.testing.capture_logs() instead of pytest caplog — caplog does not capture structlog output without a stdlib bridge"
  - "Histogram record placed between adaptive_buffer_mult computation and _classify_stop_basis — stop_type already resolved from _resolve_stop_* calls above"
metrics:
  duration_seconds: 108
  completed_date: "2026-06-05"
  tasks_completed: 1
  tasks_total: 1
  files_changed: 3
---

# Phase 115 Plan 05: OTel Histogram and Structlog Debug for frame_trade() Summary

STOP_BUFFER_MULT_DISTRIBUTION histogram added to metrics.py and wired into frame_trade() with a conditional structlog DEBUG event, making vol regime drift operationally detectable via Grafana.

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 5 | Add OTel histogram and structlog debug to frame_trade() | 02c896e6 | metrics.py, trade_framer.py, test_trade_framer.py |

## What Was Built

**`STOP_BUFFER_MULT_DISTRIBUTION` histogram** added to `src/observability/metrics.py` at line 833:
- `_meter.create_histogram("stop_buffer_mult_distribution", ..., unit="1")`
- Labels: `regime_type` (trend | mean_reversion | any) and `stop_type` (demand_zone | ob_bottom | etc.)
- Enables Grafana alerting on regime-based buffer shifts over time

**Observability block in `frame_trade()`** added immediately after `adaptive_buffer_mult = _adaptive_buffer(...)`:
- Histogram records on every `frame_trade()` call (unconditional)
- Structlog DEBUG event `"adaptive_buffer_applied"` fires only when `adaptive_buffer_mult != 1.0` AND `regime_type in ("trend", "mean_reversion")`
- Logs: `regime_type`, `vol_ratio`, `hurst`, `buffer_mult` (rounded to 4dp), `stop_type`
- No debug log when buffer is neutral (`mult == 1.0`) or regime is `"any"`

**Imports added to `trade_framer.py`:**
- `import structlog as _structlog`
- `from src.observability.metrics import STOP_BUFFER_MULT_DISTRIBUTION`
- `_logger = _structlog.get_logger(__name__)` module-level logger

**`TestFrameTradeObservability` class** added to `test_trade_framer.py` with 2 tests:
1. `test_structlog_debug_emitted_when_hurst_fires` - H=0.75 trend regime → DEBUG event captured via `capture_logs()`
2. `test_no_debug_when_buffer_neutral` - vol_ratio=1.0, no Hurst → no DEBUG event

Total test count: 105 (was 103, added 2).

## Deviations from Plan

### Test approach: capture_logs() instead of caplog

**Found during:** RED phase

**Issue:** The PLAN.md action section already specified the correct approach (`structlog.testing.capture_logs()`) - no deviation. The source plan Step 5.1 reference to `caplog` was correctly overridden by the PLAN.md action block which specified `capture_logs()`.

**Impact:** None - used correct approach from the start.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| src/observability/metrics.py - STOP_BUFFER_MULT_DISTRIBUTION at line 833 | FOUND |
| src/intelligence/trading/trade_framer.py - STOP_BUFFER_MULT_DISTRIBUTION.record | FOUND (line 1064) |
| src/intelligence/trading/trade_framer.py - adaptive_buffer_applied event | FOUND (line 1070) |
| tests/unit/intelligence/test_trade_framer.py - TestFrameTradeObservability | FOUND |
| commit 02c896e6 | FOUND |
| TestFrameTradeObservability (2 tests) | PASSED |
| Full unit suite (4362 tests) | PASSED |
