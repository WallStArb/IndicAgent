---
title: Promote 4 Batch Scripts to BaseBatch + Systemd — AlphaEngine DAG Consistency
created: 2026-06-24
source: Renaissance naming audit + DAG structural review
priority: medium
---

# Context

The v3.0 AlphaEngine pipeline has 6 nodes. Two (`EnsembleBuilder`, `AlphaEmitter`) are
proper `BaseBatch` services with systemd units, D-06 instrumentation, and canonical
class names. Four are procedural scripts with no class, no systemd unit, and no OTel
coverage. This is a structural inconsistency in the DAG — all six nodes are the same
kind of thing (periodic batch compute, DB→DB or DB→Kafka), but four have a weaker
contract than the other two.

Additionally, `EnsembleBuilder` and `AlphaEmitter` use non-canonical suffixes (`Builder`,
`Emitter`) that do not appear in the Vocabulary B taxonomy.

**Do not execute before the full 58-symbol corpus validates the IC methodology.**
These scripts are working. Promote them after Phase 139 P3 is confirmed correct.

---

## Work Items

### 1 — Promote 4 scripts to `BaseBatch` + systemd

| Current file | Current name | Correct class name | Rationale |
|---|---|---|---|
| `services/backfill_feature_factory.py` | (no class) | `FeatureVectorBatchWriter` | Reads OHLCV, writes `feature_vectors`; batch analog of live `FeatureVectorWriter` |
| `services/regime_writer.py` | (no class) | `RegimeTrainer` | Trains GaussianHMM per (symbol, tf), decodes causal labels — model training: Data → artifact |
| `services/forward_return_writer.py` | (no class) | `ForwardReturnAnalyzer` | Pure analytical computation, DB→DB, no model, no Kafka |
| `services/ic_engine.py` | (no class) | `ICEngine` | Canonical plain role noun per glossary (same pattern as `AlphaEngine`) |

Each gets:
- A `BaseBatch` class wrapping the current procedural logic
- A systemd `Type=oneshot` unit under `production/systemd/`
- D-06 `job_completed_total{job, status}` at exit (inherited from `BaseBatch`)
- Registration in `_DAG_ORDER` and `_AGENT_ID_TO_UNIT` in `service_auditor.py`
- `setup_service_logging()` call

### 2 — Fix non-canonical suffixes on existing BaseBatch services

| Current class | Correct class | File |
|---|---|---|
| `EnsembleBuilder` | `EnsembleOptimizer` | `services/ensemble_builder.py` → `services/ensemble_optimizer.py` |
| `AlphaEmitter` | `AlphaPublisher` | `services/alpha_emitter.py` → `services/alpha_publisher.py` |

`EnsembleBuilder` → `EnsembleOptimizer`: runs Ledoit-Wolf covariance optimization to
produce ensemble weight artifact. `Optimizer` is the correct suffix (produces optimized
artifact from data).

`AlphaEmitter` → `AlphaPublisher`: reads `ensemble_alpha` (DB), writes `alpha_events`
(DB), emits to Kafka shadow topic. Closest canonical suffix is `Publisher` (DB → Kafka),
extended to cover the DB write side.

File renames require: systemd unit rename, `_DAG_ORDER` / `_AGENT_ID_TO_UNIT` update,
test sweep (`grep -r "EnsembleBuilder\|AlphaEmitter" tests/`).

---

## Gate

- Phase 139 P3 corpus run complete and IC discovery report validated
- `feature-factory-batch-technical-debt.md` Issues 1-5 resolved
- `compute()` unification (Issue 6) complete — confirms batch and live paths are unified
  before renaming the classes that own them
