---
phase: 083-observability-hardening
plan: "07"
subsystem: observability
tags: [otel, dlq, kafka, systemd, gap-closure]

requires:
  - phase: 083-observability-hardening
    provides: OTel migration, DLQ drain agent, alert rules

provides:
  - OTel MeterProvider guard fixed (isinstance vs brittle __class__.__name__)
  - DLQ drain service enabled and running
  - 3 orphaned Redpanda topics deleted

affects: []

tech-stack:
  added: []
  patterns:
    - "Use isinstance() for OpenTelemetry SDK provider checks — __class__.__name__ is internal and mismatches across SDK versions"

key-files:
  created: []
  modified:
    - src/observability/otel.py
    - production/systemd/indicagent-dlq-drain.service

key-decisions:
  - "isinstance(metrics.get_meter_provider(), MeterProvider) over __class__.__name__ string check — SDK internal class names differ (_ProxyMeterProvider vs ProxyMeterProvider)"

patterns-established:
  - "isinstance guard for OTel provider checks — applied to both MeterProvider and TracerProvider init guards"

requirements-completed: []

duration: 10min
completed: 2026-05-15
---

# Phase 083-07: UAT Gap Closure Summary

**OTel metrics now export correctly (isinstance fix), DLQ drain active, and 3 orphaned Redpanda topics deleted**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-05-15
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Fixed OTel MeterProvider init guard — brittle `__class__.__name__ == "ProxyMeterProvider"` check never matched SDK's actual `_ProxyMeterProvider`; replaced with `isinstance(provider, MeterProvider)` so metrics now flow to OTLP collector
- DLQ drain service enabled and started — was deployed but never activated; `StartLimitIntervalSec` also moved from `[Service]` to `[Unit]` where systemd actually reads it
- Three orphaned Redpanda topics deleted: `intelligence.signal.audit`, `market.data.quality`, `system.health.events`

## Task Commits

1. **Task 1-3: OTel guard + DLQ activation + orphaned topics** - `c7f6473e` (fix)
2. **Simplify pass: StartLimitIntervalSec in 2 more service files + otel.py comment trim** - `e327ece9` (chore)

## Files Created/Modified
- `src/observability/otel.py` — isinstance guard for MeterProvider and TracerProvider init
- `production/systemd/indicagent-dlq-drain.service` — StartLimitIntervalSec moved to [Unit]
- `production/systemd/indicagent-alerting-agent.service` — same fix (simplify pass)
- `production/systemd/indicagent-service-auditor.service` — same fix (simplify pass)

## Decisions Made
- Used `isinstance(provider, MeterProvider)` not a name-string check — SDK class names are internal and differ across versions; isinstance is stable

## Deviations from Plan
- Simplify pass extended `StartLimitIntervalSec` fix to `alerting-agent` and `service-auditor` service files (two more cases of the same bug found during cleanup) — additive, no scope change

## Issues Encountered
None — all three gaps closed cleanly per plan.

## Next Phase Readiness
Phase 083 complete. All 7 plans executed, UAT gaps resolved. Milestone v2.5 ready for completion.

---
*Phase: 083-observability-hardening*
*Completed: 2026-05-15*
