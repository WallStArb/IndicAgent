---
created: 2026-03-27T11:22:20.832Z
title: Wire PERSISTENCE_CONSUMER_LAG and PERSISTENCE_BATCH_LATENCY in writer services
area: observability
files:
  - services/feature_writer_service.py
  - services/llm_writer_service.py
  - src/observability/metrics.py
---

## Problem

`PERSISTENCE_CONSUMER_LAG` and `PERSISTENCE_BATCH_LATENCY` are defined in
`src/observability/metrics.py` and imported by both writer services, but
neither service ever calls `.set()` or `.observe()` on them. The Grafana
dashboard and alerting rules that depend on these metrics receive no data.

This was flagged in the 2026-03-26 naming violations audit as "NOT YET FIXED".

## Solution

In `feature_writer_service.py`:
- `PERSISTENCE_CONSUMER_LAG.labels(agent_id="feature_writer").set(lag)` — call
  in `_report_consumer_lag()` using the Kafka consumer's committed vs latest
  offset delta (same pattern as `indicator_compute_agent.py` line 677).
- `PERSISTENCE_BATCH_LATENCY.labels(agent_id="feature_writer").observe(elapsed)`
  — call in the batch flush path, wrapping the `executemany()` call.

Same pattern for `llm_writer_service.py` with `agent_id="llm_writer"`.

These files will also be touched during the BaseAgent migration phase — wire
the metrics first so the migration diff doesn't mix correctness fixes with
refactoring.
