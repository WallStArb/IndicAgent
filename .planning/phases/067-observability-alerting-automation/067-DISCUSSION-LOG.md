# Phase 67: Observability, Alerting & Automation — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-23
**Phase:** 067-observability-alerting-automation
**Areas discussed:** AlertingAgent scope, Renaissance refactor, Plan restructure

---

## AlertingAgent Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal dispatcher | Kafka consumer → route by severity → HTTP POST. No rate limiting, dedup, or retry. | ✓ |
| Dedup + rate limit | Add in-memory dedup (5min window) + rate limiting (10 alerts/min). Prevents spam. | |
| Full feature set | Dedup + rate limit + retry with backoff + alert grouping. Maximum reliability. | |

**User's choice:** Minimal dispatcher (Renaissance principle: start minimal, add complexity when evidence proves it's needed)
**Notes:** Jim Simons approach: don't build dedup until you've measured duplicate alert volume. Don't build rate limiting until cascading failures actually happen. Internal metrics (dispatch_total, latency_seconds) provide the measurement foundation.

---

## Renaissance Refactor

| Option | Description | Selected |
|--------|-------------|----------|
| Full migration | Remove ALL inline webhook methods from service_auditor. Replace with _send_alert(). Clean DAG. | ✓ |
| Hybrid — keep both | Add _send_alert() alongside existing webhooks. Dual dispatch during transition. | |

**User's choice:** Full migration (Renaissance principle: single source of truth, separation of concerns)
**Notes:** Two dispatch paths = two failure modes, two places to update, zero benefit. service_auditor AUDITS, AlertingAgent DISPATCHES. Hybrid leaves SRP violation in place. 11 inline webhook references to remove and replace.

---

## Plan Restructure

| Option | Description | Selected |
|--------|-------------|----------|
| /gsd-fast (inline) | Execute directly in session, no planning overhead. ~150 lines new code + refactor. | ✓ |
| Single plan, quick execute | One condensed plan, then /gsd-execute-phase. Keeps GSD tracking. | |
| Keep 4 plans | Update existing plan structure for remaining work. | |
| Defer to later phase | Roll into Phase 71 or similar. | |

**User's choice:** /gsd-fast inline execution
**Notes:** Process should match the work. 150 lines doesn't need a planning phase. Most Phase 67 work was already implemented during Phase 68 or earlier.

---

## Key Finding: Phase 67 Mostly Complete

Phase 68 implemented most of Phase 67's planned work:
- BaseAgent crash/setup metrics (4 Prometheus counters)
- BaseAgent._send_alert() (Kafka-based alert publishing)
- BaseAgent._setup_with_retry() (exponential backoff)
- bar_auditor gap tracking + DLQ path
- SwarmOrchestrator cache seeding
- Grafana alert-rules.yml (13KB, 10+ rules)
- All 3 dashboards (operations, pipeline-health, signals-i8)
- service_auditor roll consumer with auto-restart

Only 3 items remain: AlertingAgent service, service_auditor webhook removal, contact-points credentials.

---

## Claude's Discretion

- Exact aiohttp session management in AlertingAgent
- Test mocking strategy for webhook dispatch
- Whether to also migrate signal_tracker from own bootstrap retry to BaseAgent._setup_with_retry()

## Deferred Ideas

- **Website→Grafana proxy** — Access Grafana dashboards from Next.js dashboard. Separate frontend concern.
- Rate limiting / dedup for alerts — build when evidence proves needed
- market_data_gaps historical backfill — separate script
- signal_tracker bootstrap retry migration to BaseAgent pattern — minor, optional
