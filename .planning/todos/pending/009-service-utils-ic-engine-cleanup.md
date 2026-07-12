---
**Created:** 2026-06-28
**Area:** infra
**Type:** refactor / tech_debt
**Priority:** P3
**Effort:** 1-2 days combined (was 2-3h + 2-3d + 2-3h split across 3 files)
**Benefit:** Reduces code duplication; completes APR compliance; establishes shared utility/pure-function locations
**Risk:** low-medium (mostly pure refactor, no behavior change; Part B below is a real class/file rename with more surface area)
**Gate:** After Phase A corpus re-run — Phase B cleanup sprint
---

# 009 — Phase B infra cleanup batch (merged 012, 032)

**Numbering note (2026-07-01):** this file previously carried three different numbers — filename
009, an inner YAML frontmatter `id: "006"`, and a heading "# 015" — from being renumbered across
sessions without the inline copies being updated. Normalized to 009 (the filename / pending-folder
key) throughout.

**Merged 2026-07-12** (housekeeping consolidation): `.planning/todos/pending/012-structural-compliance.md`
and `.planning/todos/pending/032-ic-engine-pure-function-refactor.md` folded in here — all three
were explicitly gated on the same "Phase B cleanup sprint" and cross-referenced each other by
number ("alongside 009 and 032," "Related: 009... can be done in the same sprint"). Both original
files now redirect here; see them for the merge note if referenced elsewhere. Content below
verified against live code 2026-07-12, not just carried forward verbatim — see the status notes
under each part.

Source: Phase 140 `/simplify` review (4 items, Part D below) + a separate structural-compliance
sweep (Parts A-C) + an ic_engine pure-function-extraction proposal (Part E). None are correctness
issues — all are DRY / APR-compliance / altitude improvements. Group into one refactor sprint.

---

## Part A — APR Services Sweep (~5 constants in `services/`, verified 2026-07-12)

| File | Constant | Value | APR key | Status (2026-07-12) |
|---|---|---|---|---|
| `services/backfill_feature_factory.py` | `_INSERT_BATCH_SIZE = 500` | 500 | `infra.backfill.insert_batch_size` | still hardcoded, confirmed live |
| `services/forward_return_writer.py` | `_INSERT_BATCH_SIZE_DEFAULT = 500` | 500 | `infra.forward_return_writer.insert_batch_size` | partially migrated — an `alpha.ic.insert_batch_size` cfg read exists near line 475, but the module constant is still the hardcoded fallback/default param elsewhere; verify scope before assuming this is fully done |
| `services/regime_writer.py` | `_UPDATE_BATCH_SIZE = 500` | 500 | `infra.regime_writer.update_batch_size` | still hardcoded, confirmed live |
| `services/regime_writer.py` | `_MIN_OBS_FACTOR = 50` | 50 | `alpha.hmm.min_obs_factor` | still hardcoded, confirmed live |
| `services/signal_auditor.py` | `_AUDIT_INTERVAL = 300` | 300 | `infra.signal_auditor.audit_interval_seconds` | still hardcoded, confirmed live |

**Dropped 2026-07-12:** the original 6th item, `services/intelligence_pipeline.py`'s
`_OUTPUT_QUEUE_MAXSIZE`, no longer applies — that file doesn't exist anymore (v2.x pipeline,
archived; CLAUDE.md confirms `indicagent-intelligence-pipeline.service` is `failed` with
`ExecStart` pointing at a deleted file).

Each migration: INSERT into `config_schema` + `config_state`, remove module constant,
load via `ConfigService.get()` at init. Description must include `[initial_estimate]`.
`_MIN_OBS_FACTOR` is a threshold, not a batch size — use `alpha.hmm.*` not `infra.*`.

---

## Part B — Promote 4 Batch Scripts to BaseBatch + Systemd (verified 2026-07-12: none done)

The v3.0 AlphaEngine DAG has 6 nodes. Two (`EnsembleBuilder`, `AlphaEmitter`) are
proper `BaseBatch` services. Four are procedural scripts with no class, no systemd unit,
and no OTel coverage — confirmed still true 2026-07-12 (`grep "class.*BaseBatch"` across all
four target files returns nothing). Promote all four:

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

**Gate:** 004 Issue 6 (`compute()` unification) complete — confirms batch and live paths unified before renaming the classes. Issues 1-5 already done (Phase 139).

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

---

## Part D — service_utils + ic_engine shared-utility cleanup (original 009 scope)

Four architectural simplifications deferred from Phase 140. None are correctness issues — all are DRY / altitude improvements.

---

## Item 1: `parse_training_window_end` in service_utils

**Where:** `services/ic_engine.py` and `services/forward_return_writer.py` — identical 8-line block in both `main()` functions.

**What:** Extract `parse_training_window_end(raw: str) -> datetime` into `src/core/service_utils.py`:
- `datetime.fromisoformat(raw)`
- reject naive (`tzinfo is None` → `ValueError`)
- `.astimezone(UTC)`

**Why:** Third service that needs `--training-window-end` (e.g. regime_writer) will copy the same block again.

---

## Item 2: `is_intraday_tf(tf)` in service_utils

**Where:** `services/forward_return_writer.py` line 187 — `is_intraday = tf in ("5m", "15m", "1h")`.

**What:** Add `is_intraday_tf(tf: str) -> bool` to `src/core/service_utils.py`, backed by the existing `TF_SECONDS` dict (daily = 86400s). The inline tuple silently misses any future TF added to the registry.

**Why:** Single source of truth for "what counts as intraday" — currently duplicated knowledge across at least forward_return_writer and any future consumer.

---

## Item 3: `_expand_int` / generalise `_expand` in ic_engine

**Where:** `services/ic_engine.py` cluster expand block (~line 677).

**What:** The manual scatter loop:
```python
cluster_id_full: list[int | None] = [None] * n_features
nd_positions = np.where(non_degenerate_mask)[0]
for _i, _pos in enumerate(nd_positions):
    cluster_id_full[_pos] = int(cluster_ids_nd[_i])
```
mirrors `_expand()` (float/NaN version) — **note (2026-07-12): `_expand` has since moved to
`src/intelligence/statistics/ic_math.py`** (todo 048, 2026-07-02), not `ic_engine.py` where this
item originally pointed; the sibling function belongs there too. Add a sibling `_expand_int(nd_arr, mask, n) -> list[int | None]` using `np.full(n, None, dtype=object)` + index assignment, or generalise `_expand` with an optional fill/dtype parameter.

**Why:** Removes duplication of the scatter pattern; any future int-typed per-feature column benefits.

---

## Item 4: Relocate `_meta_eligible` out of ensemble_trainer

**Where:** `services/ensemble_trainer.py` line 92.

**What:** `_meta_eligible` is a pure function with no service dependencies. Move to a shared IC utilities module (e.g. `src/intelligence/ic_utils.py` or alongside IC scoring helpers).

**Why:** As a service-file private it can't be imported by a second consumer without pulling in the full service. Natural home is alongside IC scoring logic.

---

**Suggested grouping (Part D only):** do all four in one commit — they all touch
`src/core/service_utils.py` or shared IC helpers, require no migration, and are pure refactors
with no behavior change. Verify with `pytest tests/unit/ -q` after.

---

## Part E — ic_engine pure-function extraction (original 032 scope, status verified 2026-07-12)

Jim Simons' mandate: every measurement is a deterministic function with no side effects —
testable in isolation, auditable, parallelizable without surprise. `ic_engine.py` originally
conflated measurement/methodology/multiple-testing/orchestration in one monolith; **2 of the 3
proposed extractions already shipped** via a separate effort (todo 048, 2026-07-02,
`src/intelligence/statistics/ic_math.py`) — this section is corrected to reflect that, not a
verbatim carryover of the original proposal.

1. **`compute_ic_for_window(ranks_x, ranks_y)` — DONE.** `ic_math.py` has `_vectorized_ic` /
   `_p_values_from_ic` covering this; already pure, already shared between `ic_engine.py` and
   `ensemble_ic_engine.py`.
2. **`apply_corpus_fdr(p_values, alpha)` — DONE.** `ic_math.py`'s `apply_bh_fdr(p_values, alpha)`
   is exactly this function (confirmed via `grep`).
3. **`build_walk_forward_folds(n_obs, n_folds, embargo_bars)` — STILL OUTSTANDING.** Confirmed
   2026-07-12: no such function exists anywhere in `src/` or `services/`. The fixed-origin
   expanding-window-with-embargo fold construction (`for k in range(walk_forward_folds): train_end
   = ...`) is still embedded inline in `ic_engine.py`'s `_compute_symbol_tf` (and duplicated in the
   context-features loop in the same file, and again in `ensemble_ic_engine.py`'s analogous path) —
   this is the one remaining piece of the original proposal with real value: a P0-relevant
   walk-forward-correctness bug would still require tracing 2-3 copies of this loop instead of a
   5-line pure-function fix.

**Remaining scope for this todo:** just item 3 above — extract `build_walk_forward_folds` into
`ic_math.py` alongside its siblings, replacing the 2-3 inline copies. Much smaller than the
original 3-function proposal.

**Notes carried forward from the original todo:**
- Do not do this simultaneously with active correctness fixes (e.g. the current 143.1 sequencing
  chain) — that doubles the diff and makes regression analysis impossible.
- After extraction, add direct unit tests using synthetic rank arrays/fold boundaries.
