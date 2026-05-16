---
title: Persistence Layer — Fragility Assessment
date: 2026-05-16
context: Pre-v2.6 foundation cleanup — architectural weakness exploration
---

# Persistence Layer Fragility Assessment

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

The same fragility likely exists in feature_writer, lifecycle_writer, lineage_writer, and
contract_metadata_writer — each evolved independently without a shared persistence pattern.

**Fix:** Establish a single canonical write pattern (named params + Pydantic validation + batch
where applicable) and apply it uniformly across all writer services.

## North Star

The persistence layer should be a multiplier, not a constraint. Adding a new signal type, a
new analysis dimension, or new quant depth should require zero persistence-layer archaeology.
The goal is a foundation wide enough to expand horizontally (fundamental, qualitative analysis)
and deep enough to support vertical sophistication (more quant ideas) without the DB layer
creating friction.

## Related

- Architectural weakness assessment: `docs/ideas/architectural-weakness-assessment.md` (#3)
- Todo: `todos/pending/audit-all-persistence-writers.md`
