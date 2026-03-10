---
phase: 05-live-pipeline
plan: 01
subsystem: pipeline-correctness
tags: [bug-fix, tws-daemon, feature-writer, systemd, reconnect]
dependency_graph:
  requires: []
  provides: [false-connected-detection, active-contract-symbols, timeframes-unit]
  affects: [production/daemons/high_frequency_tws_daemon.py, services/feature_writer_service.py]
tech_stack:
  added: []
  patterns: [provider.is_connected() guard, get_active_contracts() symbol config]
key_files:
  created:
    - tests/unit/daemon_tests/__init__.py
    - tests/unit/daemon_tests/test_tws_daemon_reconnect.py
    - tests/unit/service_tests/test_feature_writer_config.py
    - services/indicagent-timeframes.service
  modified:
    - production/daemons/high_frequency_tws_daemon.py
    - services/feature_writer_service.py
decisions:
  - "05-01: TWS false-connected check uses self.connected and self.provider guard before calling provider.is_connected() — safe even when provider is None"
  - "05-01: feature_writer follows market_analysis_service pattern exactly: try/except Settings() inside _load_config, pass _settings to get_active_contracts()"
  - "05-01: test_tws_daemon_reconnect.py tests the conditional logic directly (not via main loop execution) — avoids needing to run the full loop"
  - "05-01: indicagent-timeframes.service created in repo; requires manual sudo install (interactive auth gate, not auto-installable)"
metrics:
  duration: ~4 minutes
  completed: 2026-02-24
  tasks_completed: 2
  files_modified: 6
requirements_satisfied: [LIVE-01, LIVE-06]
---

# Phase 5 Plan 01: Live Pipeline Bug Fixes Summary

**One-liner:** TWS daemon false-connected state detection + feature_writer active contract symbols + timeframes systemd unit file.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix TWS daemon false-connected state bug | d67d49c | high_frequency_tws_daemon.py, test_tws_daemon_reconnect.py |
| 2 | Fix feature_writer symbol config + add timeframes systemd unit | 2925e63 | feature_writer_service.py, indicagent-timeframes.service, test_feature_writer_config.py |

## What Was Built

### Task 1: TWS Daemon False-Connected Fix

Added a secondary disconnect detection check in the main loop of `production/daemons/high_frequency_tws_daemon.py` (lines 392-407):

```python
# Secondary disconnect detection: catches false-connected state
# (self.connected=True but provider actually disconnected)
if self.connected and self.provider and not self.provider.is_connected():
    logger.warning(
        "Provider reports disconnected — correcting false-connected state",
        connected_flag=self.connected,
    )
    self.connected = False
    self._on_disconnected()
```

This block is inserted BEFORE the existing `if not self.connected:` reconnect block. When TWS resets overnight (e.g., daily restart at ~23:45 EST), the `self.connected` flag stays True but `IBKRProvider.is_connected()` (which calls `ib.isConnected()`) returns False. Without this fix, the daemon polls `poll_1m_bars()` indefinitely against a dead connection — resulting in zero market data until manual restart.

Three unit tests verify the logic:
- `test_false_connected_triggers_reconnect`: false-connected state sets connected=False and calls _on_disconnected()
- `test_true_connected_no_trigger`: healthy connection — _on_disconnected() not called
- `test_disconnected_flag_no_secondary_check`: connected=False short-circuits; provider.is_connected() never called

### Task 2: Feature Writer Symbol Config

In `services/feature_writer_service.py`:
- Added `from src.config.settings import Settings, get_active_contracts` import
- Updated `_load_config()` to instantiate `Settings()` with try/except (same pattern as market_analysis_service)
- Replaced hardcoded `["ESH6", "NQH6", "RTYH6", "CLK6", "GCM6", "NGK6"]` with `get_active_contracts(_settings)`

The stale symbols CLK6 (CL April) and GCM6 (GC June) are no longer in the default list. All 23 active H6/J6 contracts are now covered.

Two unit tests verify the fix:
- `test_default_config_uses_active_contracts`: ESH6/NQH6 present, CLK6/GCM6 absent, list matches get_active_contracts()
- `test_active_contracts_count`: at least 20 symbols (all 23 active expected)

### Task 2 (Part B): Timeframes Systemd Unit

Created `services/indicagent-timeframes.service` — the systemd unit file for `timeframes_builder_service.py`. Structure mirrors `indicagent-feature-writer.service`:
- `After=indicagent-tws.service` (needs 1m bars from TWS daemon)
- `Restart=always`, `RestartSec=10`
- `SyslogIdentifier=indicagent-timeframes`

**Note:** The unit file was committed to the repo. Systemd installation requires `sudo` which requires interactive authentication. The user must run:

```bash
sudo cp services/indicagent-timeframes.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable indicagent-timeframes
```

## Test Results

- New tests added: 5 (3 reconnect + 2 config)
- Total passing: 607 (up from 584 baseline)
- Pre-existing failures: 5 (test_settings, test_ibkr_provider, test_historical_backfill — out of scope, documented in STATE.md)
- No regressions introduced

## Deviations from Plan

### Auth Gate: Systemd Installation

**Found during:** Task 2 Part B
**Issue:** `sudo cp` and `sudo systemctl` require interactive password authentication; non-interactive sudo is not configured for this user.
**Action:** Unit file committed to repo. Manual sudo commands documented above.
**Impact:** Unit not yet installed in /etc/systemd/system/. User must run 3 sudo commands before Plan 05-02 smoke test.

### Directory Name: daemon_tests vs daemons

**Type:** Minor deviation — plan specified `tests/unit/daemon_tests/` but existing tests use `tests/unit/daemons/`
**Decision:** Created `tests/unit/daemon_tests/` as specified by the plan's `must_haves.artifacts` path constraint. Both directories coexist.

## Self-Check: PASSED

Files exist:
- production/daemons/high_frequency_tws_daemon.py — FOUND, contains `provider.is_connected()` at line 396
- services/feature_writer_service.py — FOUND, contains `get_active_contracts` at line 185
- services/indicagent-timeframes.service — FOUND
- tests/unit/daemon_tests/test_tws_daemon_reconnect.py — FOUND (31 lines)
- tests/unit/service_tests/test_feature_writer_config.py — FOUND (51 lines)

Commits exist:
- d67d49c — fix(05-01): add false-connected state detection in TWS daemon main loop
- 2925e63 — fix(05-01): replace stale symbols in feature_writer and add timeframes systemd unit
