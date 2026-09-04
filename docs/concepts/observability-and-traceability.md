# Observability and Traceability

**Version:** 1.1
**Status:** current
**Last Updated:** 2026-09-04
**Tags:** observability, metrics, audit-trail, otel

> Every decision the system makes is measurable, attributable, and auditable — from a raw bar to a fired signal to an LLM call to a position outcome.

## The Problem It Solves

A quantitative system that cannot explain its own decisions is not a quantitative system — it is a black box that happens to trade. Without observability: bugs are found by traders, not engineers; latency regressions are invisible until they matter; signal quality degrades silently; and post-mortems are guesswork. Traceability adds the dimension of time: not just "what is happening now" but "what happened at 14:32:07 on Tuesday and why."

## The Principle

Observability is infrastructure, not afterthought. Three pillars:

1. **Metrics** — quantitative measurements over time (counters, histograms, gauges). Answer: "is the system healthy?"
2. **Traces** — causal chains linking events across services. Answer: "why did this signal fire?"
3. **Audit logs** — immutable records of every decision with full context. Answer: "what exactly happened?"

These three are complementary. Metrics tell you something is wrong. Traces tell you where. Audit logs tell you what the system was thinking.

## How IndicAgent Applies It

**Metrics** are emitted via OTel SDK (`src/observability/metrics.py`). Every `BaseDaemon` subclass (`src/core/agent/base.py`) automatically emits five mandatory signals:

| Signal | Type | Purpose |
|--------|------|---------|
| `agent_last_message_timestamp_seconds` | gauge | Liveness — updated every processed message |
| `agent_crash_total` | counter | Uncaught exceptions in `_run()` |
| `agent_dlq_total` | counter | Dead-letter queue routing events |
| `watchdog_notify_total` | counter | Successful systemd `WATCHDOG=1` pings |
| `watchdog_notify_suppressed_total` | counter | Agent alive but idle/stalled |

Scrape endpoint: `:8000/metrics`. Grafana at `:3001`.

**Traces** use OTel spans via `observed_span()` from `src/observability/spans.py`. Auto-records ERROR status and exception on raise. `ATTR_*` constants from the same module — no raw strings.

**Audit logs** — every LLM call is persisted to `llm_calls` table with full context: `call_id`, `agent_id`, `prompt_version`, `symbol`, `signal_id`, `regime`. Outcome is back-filled by `LLMWriter` (`services/llm_writer.py`) when the signal resolves. This enables prompt A/B testing, per-agent performance scoring, and full decision archaeology.

**D-27 SLO alerts** (Grafana):
- `agent_last_message_timestamp_seconds` stale > 120s → page
- `watchdog_notify_suppressed_total` rate > 0 → warning
- Any oneshot `job_completed_total{status="failure"}` → warning

**Oneshot contract (D-06):** Timer-triggered scripts emit `job_completed_total{job, status}` at exit. `job` label must match systemd unit `%n` suffix exactly (kebab-case).

## Invariants

- Every new `BaseDaemon` subclass inherits the 5 mandatory OTel signals — no per-service instrumentation code needed. Four use label key `agent_id`; `agent_crash_total` uses `agent` instead (`_crash_attrs` in `src/core/agent/base.py`).
- `prometheus_client` must never be imported — it was fully removed; OTel SDK only.
- Counters: `.add(1, {"label": val})`. Histograms: `.record(val, {"label": val})`. Up-down gauges: `.add(delta, {"label": val})`. Point gauges: `.set(value, {"label": val})`. Wrong call pattern silently fails.
- The `llm_calls` composite PK is `(call_id, called_at)` — ON CONFLICT must include both columns.
- `prompt_version` class attribute is mandatory on every `BaseAIWorker` subclass — enables prompt A/B testing in `llm_calls`.

## Recipe

When designing observability for a new system:

1. **Define the five baseline signals for every agent** — liveness, crashes, DLQ, watchdog. These are non-negotiable.
2. **Audit logs are not logs** — structured records in a queryable store, not text files. Design the schema before the agent.
3. **Trace the decision chain** — from input event to output decision, every intermediate step should be attributable.
4. **Version everything that affects decisions** — model versions, prompt versions, weight versions. Store them with the decision.
5. **SLO alerts before features** — define what "healthy" looks like before building. Alerts at deployment, not after incidents.
6. **Separate operational metrics from business metrics** — `agent_crash_total` is operational; `signal_win_rate` is business. Both matter; they live in different dashboards.

## See Also

- Implementation: `docs/platform/platform-observability.md` — OTel instruments, Grafana setup, D-27 SLO alerts
- Agent contract: `docs/agents/agents-foundation.md` — BaseAgent mandatory OTel signals
- Audit trail: `docs/intelligence/intelligence-ai.md` — `llm_calls` schema and back-fill pattern
