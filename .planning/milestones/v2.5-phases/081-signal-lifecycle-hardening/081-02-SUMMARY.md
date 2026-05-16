---
phase: 081-signal-lifecycle-hardening
plan: "02"
subsystem: intelligence-pipeline-publisher
tags:
  - signal-lifecycle
  - publisher-normalization
  - is-backfill
  - metrics
dependency_graph:
  requires:
    - src/core/stream_keys.py (TF_SECONDS canonical location)
    - src/observability/metrics.py (counter registration pattern)
    - services/intelligence_pipeline_agent.py (_publish_signals_or_dlq site)
  provides:
    - TF_SECONDS dict in src/core/stream_keys.py
    - INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL counter in metrics.py
    - Publisher-side signal normalization: timestamp/is_backfill/ttl_bars/signal_schema_version
  affects:
    - All consumers of intelligence.i7.signals (signal_tracker_compute_agent, signal_writer_agent)
    - Plan 081-03 (signal_tracker_compute_agent refactor) consumes is_backfill
    - Plan 081-06 (signal_replay_auditor_agent) imports TF_SECONDS from stream_keys
tech_stack:
  added: []
  patterns:
    - Publisher-side normalization (D-01 design decision)
    - _safe_counter helper for duplicate-safe metric registration
key_files:
  created: []
  modified:
    - src/core/stream_keys.py
    - src/observability/metrics.py
    - services/intelligence_pipeline_agent.py
decisions:
  - TF_SECONDS added to stream_keys.py as canonical location; import in intelligence_pipeline_agent.py migrated from service_utils to stream_keys
  - _safe_counter used for INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL to match Phase 80 swarm metrics pattern
  - Normalization block placed in _publish_signals_or_dlq() immediately before _enqueue() call — all ranked signals get stamped before payload leaves the agent
  - bar_ts extracted as named variable (bar.ts) for clarity; computed_at is datetime.now(UTC) at publish moment
metrics:
  duration: "~10 minutes"
  completed_date: "2026-05-08"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 3
---

# Phase 81 Plan 02: Publisher Normalization — Signal Timestamp and Backfill Stamping Summary

**One-liner:** Publisher-side normalization injects `timestamp=bar_ts`, `is_backfill` flag, `ttl_bars` default, and `signal_schema_version` default into every outbound signal on `intelligence.i7.signals`, with a Prometheus counter tracking backfill volume.

## What Was Built

Eliminated the root cause of missing/empty timestamps in outbound I7 signal payloads. Every signal published to `intelligence.i7.signals` now carries a complete, self-describing payload — no consumer-side inference required.

### Task 1: TF_SECONDS in src/core/stream_keys.py (commit 1ea6c4a9)

Added `TF_SECONDS: dict[str, int]` at module scope in `src/core/stream_keys.py` as the canonical location for the timeframe→seconds mapping. This dict is the shared contract between:
- Publishers (intelligence_pipeline_agent) — compute `is_backfill`
- Consumers (signal_tracker_compute_agent) — compute `bars_elapsed`
- Replay auditor (signal_replay_auditor_agent, Plan 06) — size OHLCV windows

The existing `TF_SECONDS` in `service_utils.py` remains for other callers but is no longer the primary import for signal lifecycle code.

### Task 2: INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL counter in metrics.py (commit 09ffeca7)

Registered a new Counter with labels `(symbol, timeframe)` in the Phase 81 intelligence pipeline publisher section of `src/observability/metrics.py`. Used `_safe_counter` helper (established pattern from Phase 80 swarm metrics) to prevent duplicate registration on module reload in tests.

### Task 3: Normalization block in intelligence_pipeline_agent.py (commit 887f4846)

**Location:** `_publish_signals_or_dlq()`, lines 1533–1565, immediately before the `self._enqueue(topic_intelligence_i7_signals...)` call.

**Changes:**
- Removed `TF_SECONDS` import from `service_utils`; now imported from `stream_keys` (canonical location)
- Added `INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL` import
- Normalization block (Phase 81 D-01):

```python
bar_ts = bar.ts          # tz-aware UTC datetime; never ""
computed_at = datetime.now(UTC)
tf_secs = TF_SECONDS.get(tf, 60)
try:
    is_backfill = (computed_at - bar_ts).total_seconds() > tf_secs
except Exception:
    is_backfill = False
for sig in ranked:
    sig["timestamp"] = bar_ts
    sig["is_backfill"] = is_backfill
    sig.setdefault("ttl_bars", 10)
    sig.setdefault("signal_schema_version", "v1")
if is_backfill and ranked:
    INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL.labels(
        symbol=symbol, timeframe=tf
    ).inc(len(ranked))
```

**Key line for downstream plans:** `sig["timestamp"] = bar_ts` at line 1548.

## Verification Results

All plan verification checks passed:

```
python -m py_compile services/intelligence_pipeline_agent.py src/core/stream_keys.py src/observability/metrics.py  -> OK
grep '"timestamp": ""' services/intelligence_pipeline_agent.py                                                     -> 0 matches
from src.core.stream_keys import TF_SECONDS                                                                        -> OK
from src.observability.metrics import INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL                                 -> OK
tests/unit/test_stream_keys.py                                                                                     -> 36/36 passed
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Duplicate TF_SECONDS import**
- **Found during:** Task 3
- **Issue:** `TF_SECONDS` was already imported from `service_utils` in the agent (used for gap detection at line 790). Adding the new import from `stream_keys` created a duplicate name in the same file, which would cause a ruff `F811` redefinition error.
- **Fix:** Removed `TF_SECONDS` from the `service_utils` import block; it is now sourced exclusively from `stream_keys`. The `service_utils.TF_SECONDS` value is identical so behavior is unchanged. All existing uses of `TF_SECONDS` in the agent (gap detection + new normalization block) resolve to the `stream_keys` version.
- **Files modified:** `services/intelligence_pipeline_agent.py`
- **Commit:** 887f4846

## Self-Check: PASSED

- `src/core/stream_keys.py` — TF_SECONDS at line 40
- `src/observability/metrics.py` — INTELLIGENCE_PIPELINE_BACKFILL_SIGNALS_TOTAL registered
- `services/intelligence_pipeline_agent.py` — normalization block at lines 1533-1565
- Commits verified: 1ea6c4a9, 09ffeca7, 887f4846
