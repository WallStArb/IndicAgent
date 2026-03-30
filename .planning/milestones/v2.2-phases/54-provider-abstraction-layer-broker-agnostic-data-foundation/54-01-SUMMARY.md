---
phase: 54
plan: "01"
subsystem: providers
tags: [provider-abstraction, protocol, schema, stream-keys, metrics, tdd]
dependency_graph:
  requires: []
  provides:
    - DataProviderAdapter Protocol (src/providers/base.py)
    - ProviderQualityEvent schema (src/core/schemas/provider_quality.py)
    - topic_market_bars_raw() stream key function
    - topic_market_data_quality() stream key function
    - PROVIDER_* and MERGER_* Prometheus metric objects
    - SOURCE_IBKR_GENERIC in BarMessage.source Literal
  affects:
    - src/providers/__init__.py (added DataProviderAdapter export)
    - src/core/schemas/bar_message.py (added SOURCE_IBKR_GENERIC to Literal)
    - src/observability/metrics.py (added 8 new metric objects)
tech_stack:
  added: []
  patterns:
    - "@runtime_checkable Protocol for structural subtyping with isinstance() support"
    - "Pydantic field_validator mode=before for UTC-aware datetime enforcement"
    - "Histogram with custom buckets=[0.1...60.0] for merger latency distribution"
key_files:
  created:
    - src/core/schemas/provider_quality.py
    - tests/unit/providers/test_adapter_protocol.py
  modified:
    - src/providers/base.py
    - src/providers/__init__.py
    - src/core/stream_keys.py
    - src/core/schemas/bar_message.py
    - src/observability/metrics.py
    - tests/unit/test_stream_keys.py
decisions:
  - "DataProviderAdapter placed alongside (not replacing) DataProvider Protocol — old protocol stays for existing IBKRProvider callers; new adapter is the Phase 54 contract for MergerAgent architecture"
  - "ProviderQualityEvent uses field_validator mode=before on all three datetime fields to uniformly reject naive datetimes before Pydantic coercion"
  - "SOURCE_IBKR_GENERIC added to BarMessage Literal — IBKRAdapter (Plan 54-02) will produce bars with source=SOURCE_IBKR_GENERIC; without this the Literal would reject adapter-produced bars"
  - "topic_market_data_quality distinct from topic_data_quality — former is provider telemetry (latency/failover), latter is pipeline signal quality gating"
metrics:
  duration_seconds: 256
  completed_date: "2026-03-28"
  tasks_completed: 2
  files_modified: 8
  tests_added: 19
---

# Phase 54 Plan 01: Foundation — Contracts, Schemas, Stream Keys Summary

**One-liner:** @runtime_checkable DataProviderAdapter Protocol + ProviderQualityEvent schema + 2 stream key functions + 8 Golden Signal metrics establishing typed contracts for the broker-agnostic provider abstraction layer.

## What Was Built

Pure additive contracts for Phase 54's provider abstraction layer. Zero behavioral change to existing services — all downstream plans (IBKRAdapter, MergerAgent, BarWriterAgent) build on these typed interfaces.

### DataProviderAdapter Protocol (`src/providers/base.py`)

`@runtime_checkable Protocol` with 6 required members:
- `provider_name: str` — identifier used in topic keys and metric labels
- `connect() -> bool`, `disconnect() -> None`, `is_connected() -> bool` — lifecycle
- `stream_bars(instruments) -> AsyncIterator[BarMessage]` — live bar stream
- `fetch_historical(symbol, tf, start, end) -> list[BarMessage]` — gap-fill
- `qualify_instrument(instrument) -> Instrument` — provider-specific contract lookup

### ProviderQualityEvent Schema (`src/core/schemas/provider_quality.py`)

Pydantic model with UTC-aware validation on all three datetime fields. Supports event_type Literal: `bar_received | gap_detected | failover | recovery`. Optional `promoted_provider` for failover/recovery events.

### Stream Keys (`src/core/stream_keys.py`)

- `topic_market_bars_raw(env, provider)` → `<env>.market.bars.raw.<provider>`
- `topic_market_data_quality(env)` → `<env>.market.data.quality`

### Metrics (`src/observability/metrics.py`)

4 provider metrics (bars_produced, reconnects, connected gauge, gaps_filled) and 4 merger metrics (bars_routed, bars_dropped, failovers, bar_latency_seconds histogram). All labeled for per-provider Prometheus dashboards.

### BarMessage Source Literal (`src/core/schemas/bar_message.py`)

Added `SOURCE_IBKR_GENERIC` ("ibkr") to the source Literal union. Required so IBKRAdapter-produced bars pass BarMessage validation.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Write failing tests (TDD RED) | 253e996 | tests/unit/providers/test_adapter_protocol.py, tests/unit/test_stream_keys.py |
| 2 | Implement contracts (TDD GREEN) | c03af44 | src/providers/base.py, src/providers/__init__.py, src/core/schemas/provider_quality.py, src/core/stream_keys.py, src/core/schemas/bar_message.py, src/observability/metrics.py |

## Deviations from Plan

### Auto-added: Extra UTC validation tests

**Rule 2 — Missing critical functionality**
- **Found during:** Task 1 (test writing)
- **Issue:** Plan specified only `test_provider_quality_event_ts_must_be_utc` for one field. `publish_ts` and `consume_ts` are equally safety-critical for latency calculations. Missing UTC enforcement on them would silently accept naive datetimes that produce wrong latency metrics.
- **Fix:** Added `test_provider_quality_event_publish_ts_must_be_utc` and `test_provider_quality_event_consume_ts_must_be_utc` as additional test cases. Applied `field_validator` to all three datetime fields in ProviderQualityEvent.
- **Files modified:** tests/unit/providers/test_adapter_protocol.py, src/core/schemas/provider_quality.py

**Result:** 19 tests total (plan specified 12+ protocol tests + 4 stream key tests = 16 minimum; added 3 extra for complete UTC coverage).

## Known Stubs

None — this plan is purely additive contracts with no data flow stubs. All types are fully specified.

## Self-Check: PASSED

All created files exist on disk. Both task commits (253e996, c03af44) verified in git log. All 41 tests pass.
