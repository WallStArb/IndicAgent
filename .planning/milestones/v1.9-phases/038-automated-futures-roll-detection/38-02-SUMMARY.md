---
phase: 038-automated-futures-roll-detection
plan: 02
subsystem: tws_daemon
tags: [futures, roll-detection, volume-analysis, z-score, tws-daemon, kafka, paper-account, tdd]

# Dependency graph
requires:
  - phase: 038-01
    provides: "derive_roll_chain(), topic_system_events(), get_active_contracts(), Settings roll_monitor_* fields"
provides:
  - RollMonitor class in services/tws_daemon.py with full detection algorithm
  - Volume-based roll detection: 100-bar rolling window, z-score gate, segmented thresholds
  - 3-bar confirmation window, 30-minute cooldown, time-of-day gating
  - Paper account detection via ib_host check + PAPER_SKIP_CONTRACTS skip logic
  - Kafka system.events + atomic DB publishing on roll confirmation
  - Bar polling loop wiring: update_volume + check_roll per bar when enabled
  - 52 unit tests covering detection algorithm + TOD gating
affects:
  - 038-03: pipeline integration (RollMonitor wired in, ready for derive_roll_chain integration)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RollMonitor: 100-bar rolling deque per base symbol; ratio + z-score dual gate before confirmation"
    - "Segmented thresholds via VOLUME_THRESHOLDS class dict; unknown symbols fall back to roll_monitor_threshold_default"
    - "_apply_tod_adjustment: ET-aware session gating returns None for post-close skip, float multiplier otherwise"
    - "Paper account detection: ib_host membership in PAPER_ACCOUNT_HOSTS set at __init__ time"
    - "Feature flag pattern: _enabled check as first guard in check_roll() — zero behavior change when False"

key-files:
  created:
    - tests/unit/test_roll_detection_algorithm.py
    - tests/unit/test_time_of_day_gating.py
  modified:
    - services/tws_daemon.py (added RollMonitor class + wiring in _fetch_bars_for_symbol)

key-decisions:
  - "RollMonitor.check_roll() is synchronous; _on_roll_confirmed() is async — caller (bar loop) schedules the coroutine"
  - "Z-score computed over next_vol distribution in window (not ratio distribution) — measures statistical significance of next contract volume surge"
  - "std=0 guard: when all window bars have identical next_vol, z-score=0 which correctly blocks detection (no variability = no signal)"
  - "_fetch_bars_for_symbol wires both update_volume AND check_roll on every new bar — per-bar granularity for timely detection"
  - "Paper skip applied before provider.fetch_historical_bars call — avoids wasted IBKR API calls for unavailable contracts"

metrics:
  duration: "5 minutes"
  tasks_completed: 2
  files_modified: 1
  files_created: 2
  tests_added: 52
  completed_date: "2026-03-18"
---

# Phase 38 Plan 02: Roll Detection Engine Summary

RollMonitor class in tws_daemon.py implements volume-based z-score roll detection with segmented thresholds (equity=1.2, metals=1.5, rates=1.4), 3-bar confirmation, 30-minute cooldown, time-of-day gating, and paper account skip logic.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | RollMonitor class + algorithm + wiring tests | 6313155 | services/tws_daemon.py, tests/unit/test_roll_detection_algorithm.py |
| 2 | Time-of-day gating tests | 8aa6aff | tests/unit/test_time_of_day_gating.py |

## What Was Built

### RollMonitor Class (`services/tws_daemon.py`)

**Core algorithm:**
- `update_volume(base_symbol, current_vol, next_vol)` — appends to 100-bar rolling deque (configurable)
- `check_roll(base_symbol, utc_now)` — dual gate: `ratio = next_vol / current_vol >= threshold` AND `z_score > 2.0`
- Minimum 20 bars required before any detection attempt
- 3 consecutive confirming bars required before roll declared (confirmation window prevents spikes)
- 30-minute cooldown per base symbol after any confirmed roll

**Segmented thresholds (`VOLUME_THRESHOLDS`):**
- ES/NQ/RTY/YM: 1.2 (high-liquidity equity index, sharp transitions)
- CL/GC/SI/HG: 1.5 (energy/metals, gradual volume shifts)
- ZN/ZF/ZB/ZT: 1.4 (rates, moderate liquidity)
- Unknown base symbols: falls back to `roll_monitor_threshold_default` (default 1.2)

**Time-of-day gating (`_apply_tod_adjustment`):**
- Pre-open (9:00–10:59 ET): threshold × 1.3 (stricter to avoid open noise)
- Close (15:00–15:59 ET): threshold × 0.9 (more sensitive at close window)
- Post-close (16:00–17:59 ET): returns `None` (skip detection entirely)
- All other times: threshold unchanged
- Disabled via `roll_time_of_day_gated=False` — always returns threshold unchanged

**Paper account support:**
- `_is_paper_account()`: checks `ib_host in {"192.168.1.157", "127.0.0.1"}`
- `should_skip_symbol(symbol)`: returns `True` for `PAPER_SKIP_CONTRACTS` on paper accounts
- `PAPER_SKIP_CONTRACTS = {"BZJ6", "NGJ6", "SR1H6", "ZWH6"}`

**Publishing (`_on_roll_confirmed`):**
- Publishes to `topic_system_events(env_name)` with roll payload JSON
- Atomic DB updates: toggle `is_front_month`, update `roll_detected_at/gap/direction`, insert `system_events` row

**Bar loop wiring in `_fetch_bars_for_symbol`:**
- Paper skip check before API call (avoids wasted IBKR calls)
- Per-bar: `update_volume()` + `check_roll()` when `_enabled`
- Schedules `_on_roll_confirmed()` on confirmation

**Feature flag:**
- `ROLL_MONITOR_ENABLED=false` (default): `check_roll()` returns `False` immediately; zero behavior change

### Test Coverage

**`test_roll_detection_algorithm.py` — 35 tests:**
- Initialization, update_volume window management
- Insufficient data guard (< 20 bars)
- Volume ratio trigger / no-trigger
- Z-score gate (uniform next_vol blocks detection)
- 3-bar confirmation, reset on confirmation, non-consecutive reset
- Cooldown within/after window
- All segmented thresholds + unknown symbol fallback
- Feature flag disabled (no-op)
- Paper account detection (2 hosts + live host)
- PAPER_SKIP_CONTRACTS (paper vs live account behavior)
- Bar loop wiring: enabled (update + check called), disabled (not called), paper skip

**`test_time_of_day_gating.py` — 17 tests:**
- Pre-open (9 ET, 10 ET, 10:59 ET edge) → 1.3x
- Close (15:00 ET, 15:59 ET edge) → 0.9x
- Post-close (16 ET, 17 ET, 17:59 ET edge) → None
- Standard RTH (12 ET) → unchanged
- Overnight (3 ET) → unchanged
- Gating disabled: all windows return unchanged (incl. would-be None post-close)
- Weekend (Sat/Sun): no errors, valid output type
- Integration: check_roll() post-close counter stays 0; RTH can detect

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

All artifacts verified:
- FOUND: tests/unit/test_roll_detection_algorithm.py
- FOUND: tests/unit/test_time_of_day_gating.py
- FOUND: .planning/phases/038-automated-futures-roll-detection/38-02-SUMMARY.md
- FOUND: class RollMonitor in services/tws_daemon.py (count=1)
- FOUND: commit 6313155 (Task 1)
- FOUND: commit 8aa6aff (Task 2)
