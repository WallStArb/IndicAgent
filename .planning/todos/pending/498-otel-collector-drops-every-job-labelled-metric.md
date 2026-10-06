---
status: pending
priority: P2
filed: 2026-10-06
source: interactive session (189 session), found during the 189-06 cutover smoke run
---

# The OTel collector drops every metric that carries a `job` label, so the D-06 oneshot contract has no Prometheus surface

## What

The collector's Prometheus exporter (`otel/opentelemetry-collector-contrib:0.153.0`,
`production/otel-collector-config.yaml`) rejects every metric with a `job` label:
`failed to convert metric job_completed_total: duplicate label names in constant and variable labels`.
The same error hits `job_duration_seconds` and the fetcher's `ohlcv_coverage_sla_breached_series`.
It has logged since the container started (2026-06-22). The services emit these metrics; the collector
receives and then drops them. So no `job_completed_total` is visible in Prometheus or Grafana for any
oneshot (`BaseBatch`) job, which is the D-06 contract in CLAUDE.md ("every oneshot emits
`job_completed_total{job, status}` at exit; `job` matches the systemd unit suffix").

## Fix

Either rename the label in `src/observability/metrics.py` (for example `job_name`, with the Grafana
panels and alert rules updated to match), or stop the exporter's resource-to-label promotion from adding
a constant `job` label. Pick whichever keeps the CLAUDE.md contract text true; update that text if the
label name changes. Verify with a real run of any oneshot (the 189 fetcher timer fires every 15 minutes)
and a PromQL query for the new series.

## Why it matters

The fetcher's staleness gauge and run status are the only live signal that daily freshness is slipping
(todo 387's staleness observability). With the metrics dropped, the alert path for a silently failing
oneshot is dark. Silent wrong answers are worse than loud crashes.

## Constraints

- `production/otel-collector-config.yaml` change needs `cd production && docker compose up -d` and keeps
  the docker log caps.
- Do not rename metrics without sweeping `production/grafana/` dashboards and alert rules (the operations
  dashboard has uncommitted edits from another session at filing time).
