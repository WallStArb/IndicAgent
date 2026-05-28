# Agent Contract Checklist

**Version:** 2.8
**Last Updated:** 2026-05-02
**Status:** Architecture standard

Every new agent must satisfy this checklist before implementation. The goal is to preserve DAG boundaries, separation of concerns, and compute/persistence isolation as the system grows.

## Required Contract

| Field | Required answer |
|---|---|
| Agent name | Class name and file path. |
| Role | `ProviderAgent`, `MergerAgent`, `ComputeAgent`, `WriterAgent`, `TrackerAgent`, `AuditorAgent`, `ReadModelAgent`, or explicitly approved exception. |
| Hot path | `yes` or `no`; hot-path agents require stricter latency and DB rules. |
| Inputs | Kafka topics, timer trigger, or explicit read-only projection. |
| Outputs | Kafka topics, canonical tables, projection tables, metrics, or DLQ. |
| Canonical truth | Whether this agent owns a canonical fact listed in `canonical-truth-registry.md`. |
| DB access | `none`, `read-only`, or `write`; write access is allowed only for writer/read-model roles. |
| State | In-memory, compacted checkpoint topic, canonical DB table, or external provider. |
| Replay behavior | Whether output is deterministic from offset 0 and what warmup is required. |
| Failure behavior | Retry, DLQ, graceful absence, halt, or alert. |
| Promotion gate | Shadow/statistical criteria if output can affect confidence, ranking, sizing, or execution. |
| Observability | Metrics, traces, lag, DLQ counters, and alert rules. |

## Role Rules

### ProviderAgent

- Translates external protocol payloads into typed stream events.
- Publishes to provider-specific raw topics.
- Performs no mathematical/statistical compute.
- Does not write to the database.

### MergerAgent

- Consumes multiple provider/raw streams.
- Publishes one authoritative canonical stream.
- May quality-gate and route.
- Does not write to the database.

### ComputeAgent

- Performs deterministic transformation, scoring, aggregation, or signal computation.
- Consumes streams and publishes streams.
- Does not write to the database.
- Does not synchronously call another agent.
- If it needs historical seed data, use a documented warmup/seeder helper or checkpoint topic; do not add ad hoc DB queries.

### WriterAgent

- Owns persistence into canonical tables.
- Consumes streams and batch-writes to storage.
- Does not perform domain compute beyond validation, serialization, and idempotent upsert/insert logic.
- Owns retries, DLQ, and graceful shutdown drain for persistence batches.

### TrackerAgent

- Tracks lifecycle state for a business object.
- Publishes lifecycle transition events.
- Does not mutate canonical storage directly; a writer persists transitions.

### AuditorAgent

- Detects integrity, parity, lag, or quality violations.
- May read canonical storage when needed for validation.
- Publishes audit/remediation events.
- Must not silently mutate canonical data. Corrections go through the owning writer/provider path.

### ReadModelAgent

- Consumes one or more canonical streams/tables and materializes a consumer view.
- May write projection/cache tables.
- Must not publish authoritative domain facts.
- Must not be required for upstream domain ingestion or compute.
- Must be rebuildable from canonical truth.

## Statistical Promotion Rule

Any output that can affect signal confidence, ranking, sizing, execution, or risk posture must pass promotion gates before production use:

- Shadow mode enabled before production influence.
- Minimum sample size declared.
- Statistical threshold declared, usually `p < 0.05` against a baseline.
- Segment review by regime, setup, timeframe, and symbol family.
- Rollback path documented.
- Data quality gate passed before model/performance evaluation.

Explanatory outputs can be rendered immediately, but they remain non-authoritative until promoted.

## No Hidden Synchrony Rule

Agents communicate by streams, not direct service calls. The only approved synchronous exception is a pre-trade risk check with independent risk authority. All other cross-domain integration should use Kafka topics, canonical tables, or optional read models.

