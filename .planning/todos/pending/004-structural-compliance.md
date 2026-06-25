# 004 — Structural Compliance (APR sweep, BaseBatch promotion, naming vocabulary)

**Priority: Medium — ship as one batch after corpus/IC validated. All three are clean-up,
not correctness. Gate: Phase 139 P3 complete and IC discovery report validated.**

---

## Part A — APR Services Sweep (~6 constants in `services/`)

The APR mandate covers `services/`. These constants need migration to APR.

| File | Constant | Value | APR key |
|---|---|---|---|
| `services/backfill_feature_factory.py` | `_INSERT_BATCH_SIZE = 500` | 500 | `infra.backfill.insert_batch_size` |
| `services/forward_return_writer.py` | `_INSERT_BATCH_SIZE_DEFAULT = 500` | 500 | `infra.forward_return_writer.insert_batch_size` |
| `services/regime_writer.py` | `_UPDATE_BATCH_SIZE = 500` | 500 | `infra.regime_writer.update_batch_size` |
| `services/regime_writer.py` | `_MIN_OBS_FACTOR = 50` | 50 | `alpha.hmm.min_obs_factor` |
| `services/signal_auditor.py` | `_AUDIT_INTERVAL = 300` | 300 | `infra.signal_auditor.audit_interval_seconds` |
| `services/intelligence_pipeline.py` | `_OUTPUT_QUEUE_MAXSIZE = 500` | 500 | `infra.pipeline.output_queue_maxsize` |

Each migration: INSERT into `config_schema` + `config_state`, remove module constant,
load via `ConfigService.get()` at init. Description must include `[initial_estimate]`.
`_MIN_OBS_FACTOR` is a threshold, not a batch size — use `alpha.hmm.*` not `infra.*`.

---

## Part B — Promote 4 Batch Scripts to BaseBatch + Systemd

The v3.0 AlphaEngine DAG has 6 nodes. Two (`EnsembleBuilder`, `AlphaEmitter`) are
proper `BaseBatch` services. Four are procedural scripts with no class, no systemd unit,
and no OTel coverage. Promote all four:

| Current file | Correct class name | Rationale |
|---|---|---|
| `services/backfill_feature_factory.py` | `FeatureVectorBatchWriter` | Batch analog of live `FeatureVectorWriter` |
| `services/regime_writer.py` | `RegimeTrainer` | Model training: data → artifact |
| `services/forward_return_writer.py` | `ForwardReturnAnalyzer` | Pure analytical DB→DB, no model |
| `services/ic_engine.py` | `ICEngine` | Plain role noun per glossary |

Each gets: `BaseBatch` class wrapping current procedural logic, systemd `Type=oneshot`
unit under `production/systemd/`, D-06 `job_completed_total{job, status}` at exit,
registration in `_DAG_ORDER` and `_AGENT_ID_TO_UNIT` in `service_auditor.py`,
`setup_service_logging()` call.

**Also fix non-canonical suffixes on existing BaseBatch services:**

| Current | Correct | File rename |
|---|---|---|
| `EnsembleBuilder` | `EnsembleOptimizer` | `services/ensemble_builder.py` → `services/ensemble_optimizer.py` |
| `AlphaEmitter` | `AlphaPublisher` | `services/alpha_emitter.py` → `services/alpha_publisher.py` |

File renames require: systemd unit rename, `_DAG_ORDER` / `_AGENT_ID_TO_UNIT` update,
test sweep (`grep -r "EnsembleBuilder\|AlphaEmitter" tests/`).

**Gate:** 003 (feature-factory-tech-debt) Issues 1-5 resolved + `compute()` unification
(Issue 6) complete — confirms batch and live paths unified before renaming the classes.

---

## Part C — Add Batch Compute Category to Naming System Vocabulary B

**File:** `docs/foundation/naming-system.md` — Vocabulary B table

Add after the `Trainer` row:
```markdown
| `Optimizer` | Constructs a model artifact via mathematical optimization | DB → DB (weight artifact) | `EnsembleOptimizer` |
| `BatchWriter` | Reads from DB, computes, writes results to DB in batch (no Kafka, no daemon) | DB → DB | `FeatureVectorBatchWriter`, `ForwardReturnAnalyzer` |
```

Add disambiguating note:
> **`Writer` is Kafka → DB only.** For batch DB → DB persistence, use `BatchWriter` or
> the appropriate analytical suffix (`Analyzer`, `Trainer`).

Also add `Optimizer` and `BatchWriter` to the disambiguating notes section as batch-only,
always extending `BaseBatch`, not `BaseDaemon`.

**Gate:** Part B complete — so the taxonomy row has live examples in the `Example` column.
