---
phase: 54
plan: "54-04"
subsystem: provider-merger
tags: [provider-abstraction, merger, failover, quality-events, systemd, cutover]
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
    - CLAUDE.md
    - services/indicagent-ibkr-provider.service
decisions:
  - "provider_merger_consumer group name — idempotent on restart, matches project convention"
  - "_extract_provider_from_topic() uses rsplit('.', 1)[-1] — handles any env prefix depth"
  - "Test helper _make_agent() sets module-level Prometheus label children — avoids duplicate registration"
  - "Recovery publishes event first, then falls through to route bar normally — primary is authoritative immediately on resume"
  - "latency_ms clamped to 0 with max(0.0, latency_s * 1000) — prevents negative values from clock skew"
  - "Removed After=indicagent-data-provider.service from ibkr-provider unit — old dependency no longer exists post-cutover"
metrics:
  duration: "~20 min total"
  completed: "2026-03-28"
  tasks_completed: 3
  tasks_total: 3
  files_created: 3
  files_modified: 3
---

# Phase 54 Plan 04: ProviderMergerAgent + Zero-Downtime Cutover Summary

ProviderMergerAgent canonical gateway implemented with TDD: routes authoritative provider bars to market.bars, auto-failovers on primary silence, publishes ProviderQualityEvent side-channel for every bar lifecycle event. Zero-downtime cutover executed; CLAUDE.md updated to reflect new two-service provider stack.

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

**CLAUDE.md updates**:
- Active Services table: replaced `Data Provider | indicagent-data-provider` row with two rows for `IBKR Provider | indicagent-ibkr-provider` and `Provider Merger | indicagent-provider-merger`
- New contracts procedure: updated restart list to include `indicagent-ibkr-provider` instead of `indicagent-data-provider`
- Infrastructure section: updated DataProviderAgent rollover note to IBKRProviderAgent

**indicagent-ibkr-provider.service** post-cutover cleanup:
- Removed `After=indicagent-data-provider.service` dependency (service no longer exists)
- Removed `Wants=indicagent-data-provider.service` dependency
- Re-installed to `/etc/systemd/system/` + `systemctl daemon-reload`

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

### Task 3: Zero-downtime cutover and CLAUDE.md update — COMPLETE
- Both `indicagent-ibkr-provider` and `indicagent-provider-merger` running active at cutover time
- `indicagent-data-provider` was absent (no unit file) — clean cutover state
- `indicagent-ibkr-provider.service`: removed stale `After=indicagent-data-provider.service` + `Wants=` line; unit re-installed
- CLAUDE.md Active Services table updated with two new rows replacing old Data Provider row
- CLAUDE.md New contracts restart procedure updated to `indicagent-ibkr-provider`
- CLAUDE.md infrastructure rollover note updated from DataProviderAgent to IBKRProviderAgent
- Full unit test suite: 321 failed / 2696 passed (identical to HEAD before changes — no regressions introduced)
- Commit: `0f2b67c`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Test helper missing metric label children**
- **Found during:** Task 2 (first test run)
- **Issue:** `_make_agent()` in test helper bypasses `__init__` via `__new__` and didn't set `_routed_lbl`, `_dropped_lbl`, `_latency_lbl` dicts that the implementation requires
- **Fix:** Added module-level test Prometheus counters and histogram, added label child caches to `_make_agent()` — matches the CLAUDE.md "Service test `__new__` pattern" requirement
- **Files modified:** `tests/unit/service_tests/test_provider_merger_agent.py`
- **Commit:** `803ddd9`

**2. [Rule 3 - Blocking issue] Stale systemd dependency on removed service**
- **Found during:** Task 3 (post-cutover cleanup)
- **Issue:** `indicagent-ibkr-provider.service` had `After=indicagent-data-provider.service` and `Wants=indicagent-data-provider.service` — the old DataProviderAgent no longer exists, creating a stale dependency that could delay or prevent service startup
- **Fix:** Removed both lines from the unit file; re-installed to `/etc/systemd/system/`; ran `daemon-reload`
- **Files modified:** `services/indicagent-ibkr-provider.service`
- **Commit:** `0f2b67c`

## Known Stubs

None — ProviderMergerAgent is fully implemented and live. CLAUDE.md reflects the new two-service architecture. All three tasks complete.

## Self-Check: PASSED
