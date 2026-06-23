---
type: todo
priority: medium
created: 2026-06-23
phase: post-138
---

# APR Services Sweep — Remaining `services/` Violations

The APR mandate was expanded in Phase 138 (migration 163 / firefly plan) to cover `services/`
in addition to `src/`. These ~25 constants in `services/` now violate the mandate and need
migration to APR. None are blocking for Phase 138 execution — capture here for a future sweep.

## Namespace `infra.*` (new — batch sizes, queue depths, timeouts, intervals)

| File | Constant | Current value | APR key |
|------|----------|---------------|---------|
| `services/backfill_feature_factory.py` | `_INSERT_BATCH_SIZE = 500` | 500 | `infra.backfill.insert_batch_size` |
| `services/forward_return_writer.py` | `_INSERT_BATCH_SIZE_DEFAULT = 500` | 500 | `infra.forward_return_writer.insert_batch_size` |
| `services/regime_writer.py` | `_UPDATE_BATCH_SIZE = 500` | 500 | `infra.regime_writer.update_batch_size` |
| `services/regime_writer.py` | `_MIN_OBS_FACTOR = 50` | 50 | `infra.regime_writer.min_obs_factor` |
| `services/signal_auditor.py` | `_AUDIT_INTERVAL = 300` | 300 | `infra.signal_auditor.audit_interval_seconds` |
| `services/intelligence_pipeline.py` | `_OUTPUT_QUEUE_MAXSIZE = 500` | 500 | `infra.pipeline.output_queue_maxsize` |

## Already-APR-backed in this sweep (do not re-migrate)

- `alpha.hmm.random_state` — done in migration 163
- `alpha.ic.lookahead.*` — done in migration 163
- `feature.hmm.n_components`, `feature.hmm.vol_window`, `feature.hmm.n_iter` — already in APR
- `alpha.ic.insert_batch_size`, `alpha.ic.min_observations`, etc. — already in APR (migration 161)

## Notes

- Use `infra.*` namespace for all infrastructure performance constants
- Each migration should: INSERT into config_schema + config_state, then remove the module constant
- Description must include `[initial_estimate]` and note whether this is an ML learning target (most infra constants are not)
- The `_MIN_OBS_FACTOR = 50` in regime_writer is a threshold (min meaningful HMM observations), not a batch size — could go under `alpha.hmm.min_obs_factor` instead of `infra.*`
