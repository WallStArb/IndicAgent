# Phase 085: Persistence Writer Migration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-17
**Phase:** 085-persistence-writer-migration
**Areas discussed:** signal_metrics batching design, lineage_writer payload model, feature_snapshot retry vs DLQ, PERSIST-05 named params scope

---

## signal_metrics batching design

| Option | Description | Selected |
|--------|-------------|----------|
| Migrate to BaseWriterAgent, single buffer, type-dispatch in _flush_batch() | One buffer holds all event dicts. _flush_batch() splits by event_type and runs the right SQL for each group. Gets DLQ, buffer-depth metric, flush contract for free. | ✓ |
| Three separate BaseWriterAgent instances | One agent per event type, each with its own buffer and flush. 3x systemd units and 3 consumer groups on the same topic. | |
| Keep BaseAgent, add internal batch accumulator | Add a dict buffer keyed by event_type. Reinvents what BaseWriterAgent already provides. | |

**User's choice:** Option 1 — migrate to BaseWriterAgent with single buffer and type-dispatch.
**Notes:** User explicitly invoked "Renaissance / Jim Simons" principle throughout — correctness by construction, reuse of base contracts, one pattern fleet-wide. Also chose to add a `SignalMetricsEvent` Pydantic discriminated union in `schemas.py` as `payload_model` for base-layer validation. Setup_performance shim stays inside `_handle_metrics_computed()` — no separate method for temporary code.

---

## lineage_writer payload model

| Option | Description | Selected |
|--------|-------------|----------|
| Define LineageEvent in src/core/ai/lineage.py alongside LineageRecorder | Co-locate schema with the sole producer. lineage_writer imports as payload_model. Malformed events DLQ automatically. | ✓ |
| Define LineageEvent in src/intelligence/schemas.py | Consistent with bus schemas, but creates awkward cross-layer import from core/ into intelligence/. | |
| No payload_model — keep manual validation in _parse_payload() | LineageRecorder is trusted internal code. Leaves a gap: ValidationError silently drops instead of DLQ-ing. | |

**User's choice:** Option 1 — `LineageEvent` in `src/core/ai/lineage.py`.
**Notes:** Renaissance framing: schema contract lives with the producer. Delete manual `signal_id`/`event_type` check from `_parse_payload()` — Pydantic model enforces required fields, manual check becomes dead code.

---

## feature_snapshot retry vs DLQ

| Option | Description | Selected |
|--------|-------------|----------|
| Delete the _do_flush() override — inherit base re-raise behavior | Base re-raises on failure, buffer stays intact, systemd restarts. Kafka offset not committed → reprocess on restart. Bounded retry by construction. | ✓ |
| Override _do_flush() with N retries then DLQ | More explicit retry logic. Reinvents what systemd provides. | |
| Override _do_flush() with N retries then drop (metric increment) | Shadow table = best-effort, never block. But a deliberate observable drop — still not a silent drop. Jim Simons: observable drops are fine, silent drops are not. | |

**User's choice:** Option 1 — delete the `_do_flush()` override.
**Notes:** No DLQ for shadow table. Reasoning: shadow data is sourced from `intelligence.journal` (replayable via Kafka offset); no replay consumer exists for a shadow DLQ; DLQ without a reader is operational noise. Failure stays visible via `_flush_errors_total` counter + structured log.

---

## PERSIST-05 named params scope

| Option | Description | Selected |
|--------|-------------|----------|
| Named dicts passed to a helper that builds positional args in declared order | Dict-based row construction. Helper extracts values in declared field order for the positional tuple for executemany. SQL stays $1/$2. | ✓ |
| SQL comments naming each positional param | Minimal change. Doesn't fix Python-side tuple construction. | |
| Switch to a different DB library that supports named params | asyncpg is a core infrastructure choice. Out of scope. | |

**User's choice:** Option 1 — named-field row construction fleet-wide.
**Notes:** User explicitly said "let's get this right now and be consistent." All writers with positional tuples migrate: lineage_writer, lifecycle_writer, ctx_writer, bar_writer, swarm_ledger_writer. Pattern: Pydantic model attributes where a payload_model exists; named `_to_row()` helper otherwise. One pattern, zero exceptions.

---

## Claude's Discretion

- Exact field list for `LineageEvent` Pydantic model (derived from `LineageRecorder.record()` call sites)
- Exact field list for `SignalMetricsEvent` discriminated union variants (derived from existing handler functions)
- Batch size and flush interval defaults for migrated `SignalMetricsWriterAgent`
- Exact `_to_row()` helper signatures for non-Pydantic writers

## Deferred Ideas

- DLQ consumer for shadow table replay — no consumer exists today; revisit if parity auditor requirements evolve
- Per-writer Grafana DLQ depth panels — Phase 084 wired `agent_dlq_total`; dashboarding is Phase 086/089 scope
