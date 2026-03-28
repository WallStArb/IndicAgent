---
phase: 54
plan: "54-04"
subsystem: provider-merger
tags: [provider-abstraction, merger, failover, quality-events, systemd]
dependency_graph:
  requires: [54-01, 54-02, 54-03]
  provides: [market.bars canonical gateway, auto-failover, ProviderQualityEvent side-channel]
  affects: [feature_compute_agent, bar_aggregator_agent, bar_writer_agent, signal_generator, all market.bars consumers]
tech_stack:
  added: []
  patterns: [BaseAgent lifecycle, KafkaConsumerClient multi-topic subscribe, ProviderQualityEvent schema, provider silence detection]
key_files:
  created:
    - services/provider_merger_agent.py
    - services/indicagent-provider-merger.service
    - tests/unit/service_tests/test_provider_merger_agent.py
  modified:
    - src/config/settings.py
decisions:
  - "provider_merger_consumer group name — idempotent on restart, matches project convention"
  - "_extract_provider_from_topic() uses rsplit('.', 1)[-1] — handles any env prefix depth"
  - "Test helper _make_agent() sets module-level Prometheus label children — avoids duplicate registration"
  - "Recovery publishes event first, then falls through to route bar normally — primary is authoritative immediately on resume"
  - "latency_ms clamped to 0 with max(0.0, latency_s * 1000) — prevents negative values from clock skew"
metrics:
  duration: "369s (~6 min)"
  completed: "2026-03-28"
  tasks_completed: 2
  tasks_total: 3
  files_created: 3
  files_modified: 1
---

# Phase 54 Plan 04: ProviderMergerAgent + Zero-Downtime Cutover Summary

ProviderMergerAgent canonical gateway implemented with TDD: routes authoritative provider bars to market.bars, auto-failovers on primary silence, publishes ProviderQualityEvent side-channel for every bar lifecycle event.

## What Was Built

**ProviderMergerAgent** (`services/provider_merger_agent.py`):
- Subscribes to all configured `market.bars.raw.<provider>` topics via a single `KafkaConsumerClient`
- Routes bars from the authoritative provider (per `provider_routing_config[asset_class]`) to `market.bars`
- Non-authoritative bars update secondary tracking state only (not forwarded)
- Auto-failover: primary silent >= `provider_silence_bars_threshold * bar_interval_seconds` triggers `_promoted[symbol] = secondary`
- Recovery: when primary resumes on a promoted symbol, `_promoted` is cleared and recovery event published
- `ProviderQualityEvent` published to `market.data.quality` on every: bar routed, failover, recovery
- Metrics port `:9130` with labeled MERGER_* Prometheus counters/histogram

**Settings additions** (`src/config/settings.py`):
- `provider_raw_topics: list[str]` — default `["ibkr"]`
- `provider_routing_config: dict[str, str]` — default `{"futures": "ibkr", "equity": "ibkr", "crypto": "ibkr", "fx": "ibkr"}`
- `provider_silence_bars_threshold: int` — default `5`

**systemd unit** (`services/indicagent-provider-merger.service`):
- `PYTHONUNBUFFERED=1` — mandatory per CLAUDE.md
- `After=indicagent-ibkr-provider.service` — correct startup ordering
- `Restart=always` with `RestartSec=10`

## Tasks

### Task 1: Write ProviderMergerAgent tests — COMPLETE
- 11 failing tests covering: BaseAgent inheritance, authoritative routing, source preservation, quality event schema, latency positivity, failover promotion, recovery clearing, topic subscription, consumer group, provider extraction
- All tests fail initially (no implementation)
- Commit: `a5d0364`

### Task 2: Implement ProviderMergerAgent, settings config, systemd unit — COMPLETE
- All 11 tests pass
- ruff clean on `services/provider_merger_agent.py`
- Pre-existing E501 lines in `settings.py` defaults block deferred (out-of-scope per scope boundary rule)
- Commit: `803ddd9`

### Task 3: Zero-downtime cutover and CLAUDE.md update — CHECKPOINT REACHED
- Pre-cutover automation completed by executor:
  - Backfill script imports checked: no hard imports of `data_provider_agent` found
  - Systemd units installed to `/etc/systemd/system/`
  - `systemctl daemon-reload` executed
  - IBKRProviderAgent started successfully (Kafka connected)
  - ProviderMergerAgent fails with file-not-found (service file in worktree, not main) — **resolved after merge to main**
- **Awaiting human approval** before cutover from DataProviderAgent to new two-service stack

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Test helper missing metric label children**
- **Found during:** Task 2 (first test run)
- **Issue:** `_make_agent()` in test helper bypasses `__init__` via `__new__` and didn't set `_routed_lbl`, `_dropped_lbl`, `_latency_lbl` dicts that the implementation requires
- **Fix:** Added module-level test Prometheus counters and histogram, added label child caches to `_make_agent()` — matches the CLAUDE.md "Service test `__new__` pattern" requirement
- **Files modified:** `tests/unit/service_tests/test_provider_merger_agent.py`
- **Commit:** `803ddd9`

## Known Stubs

None — ProviderMergerAgent is fully implemented. Task 3 (cutover + CLAUDE.md) is blocked at checkpoint for human verification before executing the production cutover.

## Self-Check: PASSED
