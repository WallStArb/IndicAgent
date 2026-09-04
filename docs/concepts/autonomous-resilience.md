# Autonomous Resilience

**Version:** 1.1
**Status:** current
**Last Updated:** 2026-09-04
**Tags:** fault-tolerance, self-healing, circuit-breaker, reliability

> The system detects failures, routes around them, and recovers without human intervention.

## The Problem It Solves

A system that requires manual intervention to recover from failures is not a 24/7 trading system — it is a system that trades during business hours. Overnight crashes, stalled consumers, DB timeouts, and LLM provider failures all require the same human response: someone wakes up, diagnoses, and restarts. At scale, this is operationally untenable. The system must be its own first responder.

## The Principle

Resilience is layered: detect failure early (watchdogs), isolate it (circuit breakers), route around it (DLQ), and recover automatically (service auditor). Each layer handles a different failure mode:

1. **Watchdogs** — detect agent death or stall (no heartbeat within N seconds)
2. **Circuit breakers** — detect cascading failures and open the circuit before they compound
3. **Dead-letter queues (DLQ)** — route unparseable or consistently-failing messages out of the hot path
4. **Service auditor** — monitors all services, restarts failed ones, enforces the DAG restart order

## How IndicAgent Applies It

**Watchdogs (systemd + OTel):** Every `BaseDaemon` emits `WATCHDOG=1` to systemd via sd_notify on each processed message. If the watchdog interval elapses without a ping, systemd restarts the service. `watchdog_notify_suppressed_total` distinguishes a stalled (alive but idle) agent from a crashed one.

**Circuit breakers** (`src/observability/circuit_breaker.py`): States are `CLOSED` (normal) → `OPEN` (failing) → `HALF_OPEN` (testing recovery). For manual tracking outside `call()`: use `allow_request()` (time-based OPEN→HALF_OPEN check) and `record_success()` (closes from HALF_OPEN). Do not call `record_failure()` and expect automatic recovery without one of these.

**DLQ:** `BaseWriter._parse_payload` returns `None` (route whole payload to DLQ) or `[]` (valid parse, no signals — do not DLQ). Every DLQ event increments `agent_dlq_total`. DLQ messages are quarantined for investigation, not silently dropped.

**Service Auditor (`ServiceAuditor`):** Monitors all services via systemd unit state. `_DAG_ORDER` in `services/service_auditor.py` defines restart sequence — services earlier in the DAG restart before services that depend on them. Consumer lag thresholds are no longer a hardcoded dict — they're loaded per service from `alert.lag.*` APR keys via `_load_lag_thresholds()` at startup, and hot-reloaded on Kafka config updates.

**Parity Auditor (not currently deployed):** `services/feature_parity_auditor.py` implements a timer-triggered NULL-field regression guard for `intelligence_features` (Phase 117 Wave 1 write-path fix) — but `intelligence_features` is the v2.x typed-bus table with no live consumer since 2026-07-02, and `indicagent-feature-parity-auditor.timer` is not installed on the current host. The consecutive-clean-cycle certification pattern (`parity_repository.fetch_clean_cycles`, `CERTIFICATION_THRESHOLD`) exists in code but is vulture-whitelisted as unused — there is no live caller. This is a resilience pattern the codebase has built but not wired up for the v3.0 pipeline; it is not a current self-healing layer.

## Invariants

- Every daemon service must emit `WATCHDOG=1` on each processed message — inherited from `BaseDaemon`.
- `_parse_payload` returning `None` routes the whole payload to DLQ. Return `[]` for valid-but-empty to prevent double-DLQ.
- The `_DAG_ORDER` in `service_auditor.py` is the single source of truth for restart order — never maintain a parallel list.
- Circuit breaker `OPEN→HALF_OPEN` recovery only fires inside `call()` — manual tracking requires explicit `allow_request()` calls.

## Recipe

When designing autonomous resilience for a new system:

1. **Define failure modes first** — agent crash, agent stall, message parse failure, DB timeout, external API failure. Each needs a different mechanism.
2. **Watchdogs on every daemon** — systemd `WatchdogSec=` + sd_notify is the simplest reliable approach.
3. **DLQ before alerting** — bad messages should be quarantined, not cause service crashes. Alerts fire on DLQ growth, not on parse errors.
4. **Circuit breakers on external dependencies** — DB, LLM APIs, external data providers. Internal agent failures use watchdogs instead.
5. **Service auditor is a meta-service** — one agent that knows the full DAG restart order and acts on it. Simpler and more reliable than distributed health checks.
6. **Distinguish dead from stalled** — a crashed agent and a stalled-but-alive agent need different responses. Separate metrics for each.

## See Also

- Implementation: `docs/agents/agents-operations.md` — service auditor DAG, watchdog config
- Implementation: `docs/platform/platform-self-healing.md` — detailed self-healing patterns
- Code: `src/observability/circuit_breaker.py` — CircuitBreaker with manual tracking API
- OTel Health Contract in `CLAUDE.md` — mandatory OTel signals (D-26), `BaseDaemon`-inherited
