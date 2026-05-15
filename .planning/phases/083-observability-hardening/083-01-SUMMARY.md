---
phase: 083-observability-hardening
plan: "01"
subsystem: observability
tags: [otel, spans, tracing, resource]
dependency_graph:
  requires: []
  provides:
    - src/observability/spans.py (ATTR_* constants + observed_span async ctx manager)
    - service.instance.id in OTel Resource
  affects:
    - Plans 02-06 (span enrichment consumers)
tech_stack:
  added: []
  patterns:
    - asynccontextmanager for span lifecycle
    - OTel StatusCode.ERROR + record_exception for span error semantics
key_files:
  created:
    - src/observability/spans.py
  modified:
    - src/observability/otel.py
decisions:
  - "spans.py is purely additive — no call sites changed in Plan 01"
  - "observed_span docstring clarifies it is for intelligence_pipeline_agent pipeline sites only; base classes own other spans"
  - "socket and os imports both added to otel.py for service.instance.id = hostname:pid"
metrics:
  duration_seconds: 169
  completed_date: "2026-05-15"
  tasks_completed: 2
  files_changed: 2
---

# Phase 083 Plan 01: OTel Span Foundation Summary

## One-liner

New `spans.py` with 9 ATTR_* span attribute constants and `observed_span()` async context manager with ERROR status recording; `otel.py` Resource enriched with `service.instance.id = hostname:pid`.

## What Was Built

### Task 1 - Create src/observability/spans.py (commit 30977a24)

New file providing the standard span attribute schema and an async context manager for the two pipeline span sites in `intelligence_pipeline_agent.py`.

Exports:
- `ATTR_SYMBOL`, `ATTR_TF`, `ATTR_PLUGIN`, `ATTR_TIER`, `ATTR_AGENT_ID`, `ATTR_SIGNAL_ID`, `ATTR_GROUP_ID`, `ATTR_BATCH_SZ`, `ATTR_FLUSH_MS` — 9 string constants for consistent span attribute naming
- `observed_span(name, tracer=None, **attrs)` — async context manager that sets `StatusCode.ERROR` and calls `span.record_exception(exc)` before re-raising

### Task 2 - Add service.instance.id to OTel Resource (commit ca9c5261)

Added `import socket` and `"service.instance.id": f"{socket.gethostname()}:{os.getpid()}"` to the `Resource.create()` call in `init_otel_providers()`. Enables multi-instance differentiation in Tempo.

## Verification

- Import test: `python -c "from src.observability.spans import observed_span, ATTR_SYMBOL, ..."` - OK
- ruff check src/observability/ - all checks passed
- pytest tests/unit/ - 3247 passed, 1 skipped (1 pre-existing unrelated failure: `test_swarm_settings_defaults` asserts SWARM_MAX_CONCURRENT_CALLS==2 but settings has 8 - out of scope)

## Deviations from Plan

None - plan executed exactly as written.

## Pre-existing Issues (not introduced by this plan)

- `test_swarm_settings_defaults` fails: `SWARM_MAX_CONCURRENT_CALLS` default changed from 2 to 8 in settings. Pre-existing, unrelated to observability changes. Deferred.

## Self-Check

Files:
- [x] src/observability/spans.py - FOUND
- [x] src/observability/otel.py - contains service.instance.id - FOUND

Commits:
- [x] 30977a24 - spans.py creation
- [x] ca9c5261 - otel.py service.instance.id

## Self-Check: PASSED
