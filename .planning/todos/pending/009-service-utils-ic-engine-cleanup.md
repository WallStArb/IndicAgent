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

**Part A closed 2026-07-31** (migration 275): all 4 constants migrated to APR --
`infra.backfill.insert_batch_size`, `alpha.ic.insert_batch_size` (code already read this
key, migration was the missing piece -- see below), `alpha.hmm.min_obs_factor`,
`infra.signal_auditor.audit_interval_seconds`. All 3 code-side migrations (backfill,
regime_writer, signal_auditor) thread the live value through their existing
ProcessPoolExecutor worker-args tuple / `BaseDaemon.get_config()` pattern, matching each
file's established style. `forward_return_writer.py`'s code was already wired
(`cfg.get_sync("alpha.ic.insert_batch_size", ...)`) but the key was never seeded --
the read was silently always falling back to the hardcoded default until this migration.
Seeded at exact pre-migration values, byte-identical behavior. Tests green
(`tests/unit/services/test_backfill_feature_factory.py` updated for the new worker-args
tuple shape), ruff/black clean.

**Part D closed 2026-07-31** -- 4 items, 2 done as originally scoped, 2 found stale:
- **Item 1 DONE**: `parse_training_window_end(raw: str) -> datetime` added to
  `src/core/service_utils.py`, replacing the identical 8-line block in
  `services/ic_engine.py` and `services/forward_return_writer.py`. New direct test
  `tests/unit/test_service_utils_parse_training_window_end.py`.
- **Item 2 STALE, nothing to do**: the inline `is_intraday = tf in ("5m", "15m", "1h")`
  check this item targeted no longer exists in `forward_return_writer.py` -- removed as
  part of todo 208's same-ET-session gate removal (2026-07-30), before this item was
  picked up.
- **Item 3 DONE**: `expand_int(nd_arr, mask, n) -> list[int | None]` added to
  `src/intelligence/statistics/ic_math.py` as the int-typed sibling of `_expand`
  (which fills NaN, invalid for an int column). Replaces the identical 4-line manual
  scatter loop at both of `ic_engine.py`'s occurrences (per-symbol pass, cross-sectional
  pass). Direct tests `tests/unit/test_ic_math_expand_int.py`, incl. a byte-identical
  comparison against the original inline loop on a random mask.
- **Item 4 DONE, but not exactly as scoped**: `_meta_eligible`'s "pure function with no
  service dependencies" premise was stale -- it calls `_resolve_per_tf`, which is a real
  (if thin) dependency. Moved both `_resolve_per_tf` (-> `resolve_per_tf`) and
  `_meta_eligible` (-> `meta_eligible`) together to `services/_batch_utils.py`, the
  already-established shared home for `cfg()` (which `resolve_per_tf` itself calls) and
  imported by 16 other services -- not the originally-suggested new
  `src/intelligence/ic_utils.py` module. `ensemble_trainer.py` now imports both under
  their original private names (`_resolve_per_tf`, `_meta_eligible`) so all existing call
  sites and tests (`test_ensemble_trainer.py`, `test_ensemble_meta_fdr.py`) are unchanged.

Part E closed 2026-07-23: Phase 162-01 extracted `build_walk_forward_folds(n_obs, n_folds,
embargo_bars)` into `src/intelligence/statistics/ic_math.py`, replacing all 4 inline copies
(3 in `ic_engine.py`, 1 in `ensemble_ic_engine.py`), with direct unit tests
(`tests/unit/test_ic_math_walk_forward_folds.py`). This resolves Part E's entire remaining
scope (item 3 — items 1-2 were already done via todo 048). Parts A, B, C, D remain open below.
The 2026-07-19 hold-back's blocker (todo 094's 143.1-08 concurrent-session sequencing chain)
finished 2026-07-21 — no longer a live concern for re-picking up A/D.

**Held back 2026-07-19 (historical, blocker resolved):** picked this up for execution (Parts A/D/E looked like safe, mechanical,
gate-cleared wins) but stopped before editing any code. Live check showed the 143.1 shadow-mode
sequencing chain (todo 094's 143.1-08 validation) is actively in progress in a concurrent session
right now — `.planning/corpus_manifests/*.json` are mid-edit and PRIORITIES.md's P0 section is
being updated live. Parts A, D, and E all touch the exact files that chain reads/writes
(`ic_engine.py`, `forward_return_writer.py`, `ensemble_trainer.py`, `ic_math.py`,
`ensemble_ic_engine.py`) — and Part E's own text already says not to do this refactor
"simultaneously with active correctness fixes... that doubles the diff and makes regression
analysis impossible." That constraint applies literally right now. Re-pick this up once the
094→096→088 chain (see PRIORITIES.md P0) clears, not before — should still take the mechanical
parts (A/D/E) in one sitting once it's safe, they remain fully scoped below.

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

## Part A — APR Services Sweep (~4 constants in `services/`, verified 2026-07-29)

| File | Constant | Value | APR key | Status (2026-07-29) |
|---|---|---|---|---|
| `services/backfill_feature_factory.py` | `_INSERT_BATCH_SIZE = 500` | 500 | `infra.backfill.insert_batch_size` | still hardcoded, confirmed live |
| `services/forward_return_writer.py` | `_INSERT_BATCH_SIZE_DEFAULT = 500` | 500 | `infra.forward_return_writer.insert_batch_size` | partially migrated — an `alpha.ic.insert_batch_size` cfg read exists near line 475, but the module constant is still the hardcoded fallback/default param elsewhere; verify scope before assuming this is fully done |
| `services/regime_writer.py` | `_MIN_OBS_FACTOR = 50` | 50 | `alpha.hmm.min_obs_factor` | still hardcoded, confirmed live |
| `services/signal_auditor.py` | `_AUDIT_INTERVAL = 300` | 300 | `infra.signal_auditor.audit_interval_seconds` | still hardcoded, confirmed live |

**Dropped 2026-07-12:** the original 6th item, `services/intelligence_pipeline.py`'s
`_OUTPUT_QUEUE_MAXSIZE`, no longer applies — that file doesn't exist anymore (v2.x pipeline,
archived; CLAUDE.md confirms `indicagent-intelligence-pipeline.service` is `failed` with
`ExecStart` pointing at a deleted file).

**Dropped 2026-07-29:** `services/regime_writer.py`'s `_UPDATE_BATCH_SIZE = 500` row no longer
applies — `grep` confirms this constant no longer exists in `regime_writer.py`; the update path
was rewritten to use `bulk_update_by_key` (COPY + JOIN-UPDATE, `services/_batch_utils.py`),
which has no batch-size concept to migrate to APR.

Each migration: INSERT into `config_schema` + `config_state`, remove module constant,
load via `ConfigService.get()` at init. Description must include `[initial_estimate]`.
`_MIN_OBS_FACTOR` is a threshold, not a batch size — use `alpha.hmm.*` not `infra.*`.

---

## Part B — Promote 4 Batch Scripts to BaseBatch + Systemd (verified 2026-07-12: none done)

The v3.0 AlphaEngine DAG has 6 nodes. Two are proper `BaseBatch` services (already correctly
named `EnsembleTrainer` / `AlphaPublisher` — see dropped rename rows below). Four are procedural
scripts with no class, no systemd unit, and no OTel coverage — confirmed still true 2026-07-12
(`grep "class.*BaseBatch"` across all four target files returns nothing). Promote all four:

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

**Dropped 2026-07-29 — both already done, and one target name was wrong:**
`AlphaEmitter` → `AlphaPublisher`: already shipped (`services/alpha_publisher.py` has
`class AlphaPublisher(BaseBatch)`, registered in `service_auditor.py`'s `_DAG_ORDER`).
`EnsembleBuilder` → `EnsembleOptimizer`: moot as originally written — `EnsembleBuilder` no
longer exists anywhere in the codebase; the live class took a different final name,
`EnsembleTrainer` (`services/ensemble_trainer.py`, `indicagent-ensemble-trainer` unit), not
`EnsembleOptimizer`. Nothing left to rename.

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

## Part E — ic_engine pure-function extraction (original 032 scope) — ✅ CLOSED 2026-07-23

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
3. **`build_walk_forward_folds(n_obs, n_folds, embargo_bars)` — DONE 2026-07-23 (Phase 162-01).**
   Extracted into `src/intelligence/statistics/ic_math.py`, replacing all 4 inline copies
   (`ic_engine.py`'s `_compute_symbol_tf`, its context-features loop, its cross-sectional loop,
   and `ensemble_ic_engine.py`'s analogous path). Direct unit tests on synthetic fold boundaries:
   `tests/unit/test_ic_math_walk_forward_folds.py`.

**Part E fully closed** — all 3 items done, no remaining scope.
