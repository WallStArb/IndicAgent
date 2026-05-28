---
reviewers: [codex]
reviewed_at: 2026-05-28T20:00:00Z
design: config-foundation-and-alerting-system
---

# Design Document Review — Config Foundation and Alerting System

## Codex Review

## Summary

The design has a strong conceptual foundation: separating infrastructure, structural, and operational config is the right architectural move, and treating alerting as a signal-processing pipeline fits IndicAgent's existing Kafka, TimescaleDB, OTel, and agent-based architecture. The main risk is that the design currently mixes a clean high-level model with several underspecified operational details: consistency semantics, config rollout safety, schema evolution, alert rule ownership, authz/audit controls, and failure behavior. It is directionally sound, but it needs tighter boundaries and rollout mechanics before implementation.

## Strengths

- Clear semantic separation between **infrastructure**, **structure**, and **operational** config. This prevents `.env`, deploy-time topology, and hot-reload behavior from becoming tangled.

- Good use of existing architecture: Kafka propagation, TimescaleDB history, BaseAgent hot reloads, OTel metrics/traces/logs, and existing `AlertingAgent`.

- `config_state` plus `config_history` is a sensible split between fast runtime reads and audit/time-travel requirements.

- "Everything OFF by default" is a good safety default for alerting, especially during migration.

- The moderate alerting approach is pragmatic. Dedupe, aggregation, correlation, and priority are useful without prematurely building a full statistical anomaly platform.

- The migration table is helpful because it distinguishes runtime tunables from deploy-time structure and secrets.

- Observability requirements are concrete and mostly actionable.

## Concerns

- **HIGH: Config consistency and ordering are underspecified.**
  The design says `set()` validates, writes DB, and emits Kafka, but does not define transactional guarantees. If DB write succeeds and Kafka publish fails, services may never receive the update. If Kafka publishes before commit visibility, consumers may reload stale state.

- **HIGH: No explicit versioning/compare-and-swap semantics.**
  `config_state.version` exists, but the API does not specify optimistic locking, expected version checks, idempotency keys, or behavior under concurrent writes. Two operators or services could overwrite each other silently.

- **HIGH: Security model is missing.**
  Config changes can alter thresholds, feature flags, and alert routing. The design needs authentication, authorization, audit identity, secret redaction, and potentially approval rules for high-risk keys. `changed_by="system"` is not enough.

- **HIGH: Alert rule ownership and configuration are unclear.**
  Alert enable flags are configurable, but the rules themselves appear to live in code. The design should specify where rule definitions, thresholds, aggregation windows, severities, notification targets, and suppression policies are owned.

- **HIGH: `revert_to_timestamp()` is dangerous without dependency and blast-radius controls.**
  Rolling back the "entire system" can violate dependencies, resurrect invalid old combinations, or disable safety-related config. This needs dry-run, validation, scoped revert, approval, and atomicity semantics.

- **MEDIUM: Hot reload pattern may conflict with existing `BaseAgent._setup()` implementations.**
  The proposed `BaseAgent._setup()` code may not compose cleanly if agents already override `_setup()`. This should probably be a reusable mixin/helper or a base lifecycle hook that subclasses explicitly call.

- **MEDIUM: Config schema is too weak for real validation.**
  `min_value`, `max_value`, `allowed_values`, and `depends_on` are a start, but the design lacks structured types, JSON schema, units, nullability, regex validation, per-environment defaults, and cross-field constraints.

- **MEDIUM: Cache behavior is underspecified.**
  Services initialize from `config_service.list()` and then consume Kafka. There is no mention of missed messages, consumer lag, rebalance handling, replay from offset, cache TTL, startup ordering, or fallback on config DB unavailability.

- **MEDIUM: Kafka topic design is too abstract.**
  The design references `topic_config_updates` and `topic_alert_requests()` but does not define message schema, partition key, ordering guarantees, retention, compaction, schema registry compatibility, or dead-letter behavior.

- **MEDIUM: AlertSignalProcessor may become a bottleneck.**
  A single processor consuming "all events" and applying rules could be expensive. The design should address filtering, topic partitioning, backpressure, state storage for windows/dedupe, and horizontal scaling.

- **MEDIUM: Alerting and Prometheus responsibility boundary is unclear.**
  Removing `alertmanager-rules.yml` may be premature. Prometheus/Alertmanager is still useful for infra-level health alerts. Application intelligence alerts and infrastructure availability alerts should likely coexist.

- **MEDIUM: "All state is time-series data" is philosophically consistent but may lead to overreach.**
  Current config belongs in a normal current-state table; history is time-series. Treating all state as time-series should not force unnecessary query complexity into the runtime path.

- **LOW: Implementation phase ordering is questionable.**
  The Config API is phase 4, but migration and alerting need a safe way to inspect and mutate config. A minimal internal API/admin CLI may be needed earlier.

- **LOW: Observability may leak sensitive data.**
  Tracing/logging `old_value` and `new_value` can expose secrets, routing tokens, URLs, or trading-sensitive thresholds. Redaction policy should be explicit.

- **LOW: "Layer 8" and "Layer 9" naming needs reconciliation.**
  The project context says 7-tier plugin pipeline I1-I8, while this design introduces Layer 8 and Layer 9. If these are service layers rather than plugin tiers, clarify the taxonomy.

## Suggestions

- Add a **config update transaction model**:
  - Write `config_history`
  - Upsert `config_state`
  - Insert an outbox row
  - Publish Kafka from an outbox dispatcher
  - Mark published after successful Kafka ack

- Use a **transactional outbox pattern** for config propagation instead of direct DB-write-then-Kafka-publish.

- Add optimistic concurrency to `set()`:

  ```python
  async def set(key, value, changed_by, expected_version=None, reason=None) -> ConfigChange:
      ...
  ```

- Define canonical Kafka message schemas for config updates and alert requests, including:
  - `config_key`
  - `value`
  - `version`
  - `changed_by`
  - `changed_at`
  - `schema_version`
  - `correlation_id`
  - `redacted`
  - `reason`

- Make config consumers resilient:
  - Load DB snapshot on startup
  - Subscribe to compacted Kafka topic
  - Ignore stale versions
  - Reconcile periodically against DB
  - Emit lag/staleness metrics

- Strengthen `config_schema` with:
  - `json_schema`
  - `unit`
  - `description`
  - `owner`
  - `risk_level`
  - `requires_restart`
  - `is_secret`
  - `is_runtime_mutable`
  - `deprecated_at`
  - `environment`

- Add RBAC and audit controls before exposing the FastAPI endpoints:
  - Read-only vs write permission
  - Per-category write permission
  - High-risk approval flow
  - Required change reason
  - Redacted logging for sensitive values

- Split alerting into two categories:
  - **Infrastructure alerts**: keep Prometheus/Alertmanager for service down, disk, memory, scrape failure, Kafka unavailable.
  - **Intelligence/application alerts**: use `AlertSignalProcessor` for domain-aware events and correlated incidents.

- Define rule configuration explicitly. For example:
  - Rule code in versioned Python modules
  - Rule parameters in config DB
  - Rule metadata in registry
  - Rule state in Redis/TimescaleDB/Kafka Streams state store, depending on latency needs

- Add failure-mode behavior:
  - What happens when ConfigService is unavailable?
  - What happens when Kafka is unavailable?
  - Do agents use last-known-good config?
  - How long can config be stale?
  - Which config keys require fail-closed vs fail-open behavior?

- Replace broad `revert_to_timestamp()` with safer operations:
  - `preview_revert_to_timestamp(t)`
  - `revert_category(category, t)`
  - `revert_keys(keys, t)`
  - dependency validation before applying
  - explicit approval for high-risk keys

- Add rollout strategy:
  - Seed DB from current settings
  - Run in read-only/shadow mode
  - Compare DB config to current settings
  - Enable one service category at a time
  - Keep rollback path to static settings during migration

- Move a minimal config management interface earlier in the implementation plan. Even a CLI is enough:

  ```bash
  indic config get regime.prob_min
  indic config set regime.prob_min 0.72 --reason "reduce false positives"
  indic config history regime.prob_min
  ```

## Risk Assessment

**Overall risk: MEDIUM-HIGH.**

The architectural direction is good and aligns with IndicAgent's event-driven design, but the current draft leaves several production-critical behaviors undefined: transactional propagation, concurrent writes, authz, rollback safety, stale config handling, and alert state management. These are not cosmetic gaps; they determine whether hot-reload tuning is safe under real operating conditions.

The risk can be reduced to **MEDIUM** by narrowing phase 1 to a robust config foundation with outbox-based Kafka propagation, versioned updates, RBAC/audit, last-known-good behavior, and a small migration surface before introducing the full alert processor.
