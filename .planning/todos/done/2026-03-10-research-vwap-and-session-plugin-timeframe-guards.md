---
created: 2026-03-10T00:00:00Z
title: Research VWAP and session plugin timeframe guards
area: general
files:
  - src/intelligence/trading/vwap_deviation.py:33
  - src/intelligence/trading/session_extremes_setup.py:42
---

## Problem

Phase 23 changed all I7 plugin `InputSpec(timeframe="1m")` to `timeframe=".*"` since the field is not enforced at runtime (signal_generator_service passes current-TF OHLCV regardless). This is currently safe because the service config hard-limits to `["1m", "5m", "15m", "1h"]`.

However, two plugins are semantically session/intraday-only:
- **VWAPDeviationPlugin** (`vwap_deviation.py`) — uses session VWAP; daily or weekly data produces meaningless signals. Lookbacks (100 bars) and ATR periods are calibrated for intraday granularity.
- **SessionExtremesSetupPlugin** (`session_extremes_setup.py`) — depends on `session_london`/`session_ny` features which are only meaningful intraday. ATR lookbacks (-14:, -21:-1 bars) have vastly different semantics across TFs.

If `"4h"` or `"1d"` is ever added to service config timeframes, these plugins would silently produce semantically incorrect signals with no guard.

## Solution

Investigate three options:
1. **Do nothing** — service config restriction is sufficient; add a comment in both plugins cross-referencing the service config to document the dependency.
2. **Runtime assertion in `compute_full`** — check timeframe arg and raise or return empty result if not in `{"1m", "5m", "15m", "1h"}`. Clean but adds per-bar overhead.
3. **`InputSpec.timeframe` restriction** — change to `"1m|5m|15m|1h"` with a comment that this is documentation only (not enforced). Explicit intent without runtime cost.

Option 1 is likely sufficient given the service config is the authoritative control point. Confirm by checking whether either plugin has existing internal timeframe checks in `compute_full`.
