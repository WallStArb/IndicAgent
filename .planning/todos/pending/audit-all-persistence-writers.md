---
created: 2026-05-16
title: Audit All Persistence Writers for Fragility Patterns
area: persistence
priority: high
---

## Problem

The signal ledger has known fragility: 64-field positional tuple, no schema validation,
per-signal DB calls. The same patterns likely exist in other writer services that evolved
independently.

## Task

Audit each persistence writer for:

1. **Positional tuples** — does `to_insert_params()` or equivalent return a positional tuple?
2. **Schema validation** — is data validated before insert, or committed as-is?
3. **Batching** — are writes per-record or batched?
4. **Error handling** — are write failures surfaced or swallowed?

## Writers to audit

- `services/signal_ledger_repository.py` (known bad — baseline)
- `services/feature_writer_service.py`
- `services/lifecycle_writer_service.py`
- `services/lineage_writer_service.py`
- `services/contract_metadata_writer_service.py`
- `services/ctx_writer_service.py`
- Any other `*_writer*` service

## Output

Produce a short table: writer × issue (positional tuple / no validation / no batching / poor
error handling). This becomes the scope input for Phase 084 Persistence Hardening.

## Related

- Note: `docs/ideas/persistence-layer-fragility-assessment.md`
- Phase 084 (planned): Persistence Layer Hardening
