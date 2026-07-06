# Persistence Layer Fragility Assessment

**Version:** 1.0
**Status:** draft
**Priority:** high
**Milestone:** v2.8
**Last Updated:** 2026-05-16
**Tags:** persistence, fragility, asyncpg, signal-ledger, schema, validation, architecture
The persistence layer has accumulated fragility across multiple dimensions. Because signals,
features, lifecycle events, and lineage all flow through it, instability here propagates to
the whole system.

## Core Problems

### 1. Positional tuple in LedgerEntry (signal_ledger_repository.py, 977 lines)

`to_insert_params()` returns a raw 64-element positional tuple. Column reordering silently
corrupts data — no error, no warning, wrong values in wrong columns. Adding a field requires
manual counting and reordering.

**Fix:** Named parameter binding via asyncpg. One dict key per column — order-independent and
self-documenting.

### 2. No schema validation at the write boundary

Data is written to the DB without being validated against the schema. A malformed or partial
`LedgerEntry` gets committed as-is. Type coercion happens implicitly in the DB, masking bugs.

**Fix:** Pydantic model at the persistence boundary. Validate before insert, not after.

### 3. Per-signal DB calls (no batching)

Individual writes per signal instead of batched inserts. Under load (burst of bars, many
symbols) this creates DB round-trip pressure. Lifecycle updates (activate, exit, outcome)
are also per-signal.

**Fix:** Batch lifecycle updates. Use `executemany` or UNNEST bulk inserts for high-volume paths.

### 4. Inconsistent patterns across writers

The same fragility exists across all writer services — each evolved independently without a
shared persistence pattern.

**Fix:** Establish a single canonical write pattern (named params + Pydantic validation + batch
where applicable) and apply it uniformly. Use `contract_metadata_writer_agent.py` as the template.

---

## Writer Audit Results (2026-05-16)

Full audit of all 13 writer services against 4 fragility dimensions.

**Legend:** BAD / OK / N/A (Positional Tuple) | YES / NO / PARTIAL (Schema Validation) | BATCHED / PER-RECORD / MIXED (Batching) | RAISED / LOGGED / SWALLOWED (Error Handling)

| Writer | Positional Tuple | Schema Validation | Batching | Error Handling | Notes |
|--------|:-:|:-:|:-:|:-:|---|
| `signal_ledger_repository.py` | BAD | NO | BATCHED | RAISED | Baseline — all 4 issues. `to_insert_params()` = raw 64-element tuple |
| `feature_writer_agent.py` | BAD | PARTIAL | BATCHED | LOGGED | `_record_to_insert_params()` positional; parse errors logged + DLQ but no re-raise |
| `lifecycle_writer_agent.py` | BAD | YES | PER-RECORD | RAISED | Exit transitions per-record via WHERE guard; delegates to repo positional tuples |
| `lineage_writer_agent.py` | **BAD** | **NO** | BATCHED | **SWALLOWED** | Raw dict → tuple in `_flush_batch()`; returns None on parse failure with zero logging or DLQ |
| `contract_metadata_writer_agent.py` | OK | YES | BATCHED | RAISED | **Template** — named params, Pydantic, hard-fail on init, DLQ routing |
| `ctx_writer_agent.py` | OK | YES | BATCHED | LOGGED | Named params; Pydantic validation; errors logged + DLQ but `_do_flush()` exceptions not re-raised |
| `bar_writer_agent.py` | OK | PARTIAL | BATCHED | RAISED | Named positional ($1-$10); BarMessage Pydantic; parse failures to DLQ |
| `feature_snapshot_writer_agent.py` | **BAD** | PARTIAL | BATCHED | **SWALLOWED** | Clears buffer on error instead of retrying — data loss on transient write failure |
| `graduation_writer_agent.py` | OK | PARTIAL | BATCHED | RAISED | Named params ($1-$17); required-key validation (not Pydantic) |
| `signal_metrics_writer_agent.py` | OK | NO | **PER-RECORD** | SWALLOWED | Individual `execute()` per event; no Pydantic; catch-all suppresses errors |
| `signal_writer_agent.py` | BAD | YES | BATCHED | RAISED | `LedgerEntry.to_insert_params()` positional; full Pydantic before insert |
| `swarm_ledger_writer_agent.py` | OK | PARTIAL | PER-RECORD | RAISED | Named params with retry loop; UUID caught and logged |
| `llm_writer_service.py` | BAD | PARTIAL | BATCHED | **SWALLOWED** | `_parsed_to_insert_tuple()` positional; outcome `_process_outcome_message()` errors suppressed |

### Critical offenders

**lineage_writer_agent.py** — worst overall (3/4 issues). Messages silently discarded on
parse failure with no DLQ routing, no counter, no log. Complete observability blackhole.

**feature_snapshot_writer_agent.py** — clears buffer on transient write error instead of
retrying. Any brief DB unavailability silently drops all buffered snapshots.

**llm_writer_service.py** — outcome update errors (`_process_outcome_message()`) caught and
suppressed. Outcome back-fill silently fails, leaving `llm_calls` rows with no outcome.

### Error handling distribution

- **Raised** (correct): lifecycle_writer, contract_metadata, bar_writer, signal_writer, swarm_ledger
- **Logged but suppressed**: feature_writer, ctx_writer, llm_writer (outcomes), feature_snapshot
- **Silently swallowed**: lineage_writer, signal_metrics

### Partial batch flush gap (all writers)

No writer implements single-row fallback on batch failure. A constraint violation on 1 of 100
rows retries all 100 with no diagnosis. Fix: on batch exception, retry one-at-a-time and route
failing rows to DLQ.

---

## Phase 084 Fix Priority

1. **lineage_writer_agent.py** — add Pydantic model, DLQ routing, error counter (CRITICAL)
2. **feature_snapshot_writer_agent.py** — replace clear-on-error with bounded retry (HIGH)
3. **llm_writer_service.py** — re-raise outcome errors or add distinct counter (HIGH)
4. **signal_metrics_writer_agent.py** — implement buffering + batch writes (MEDIUM)
5. **All positional tuple writers** — migrate to named params following contract_metadata template (MEDIUM)
6. **Standardize error handling rule**: all `_flush_batch()` failures must either raise (for caller retry), route to DLQ with counter, or emit explicit "silent drop" counter (LOW)

---

## North Star

The persistence layer should be a multiplier, not a constraint. Adding a new signal type, a
new analysis dimension, or new quant depth should require zero persistence-layer archaeology.
The goal is a foundation wide enough to expand horizontally (fundamental, qualitative analysis)
and deep enough to support vertical sophistication without the DB layer creating friction.

## Related

- Architectural weakness assessment: `docs/ideas/architectural-weakness-assessment.md` (#3, #6)
- Todo: `.planning/todos/pending/audit-all-persistence-writers.md`
- Template writer: `services/contract_metadata_writer_agent.py`
