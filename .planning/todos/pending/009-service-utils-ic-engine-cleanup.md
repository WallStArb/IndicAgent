---
**Created:** 2026-06-28
**Area:** infra
**Type:** refactor
**Priority:** P3
**Effort:** 2-3 hours
**Benefit:** Reduces code duplication; establishes shared utility location
**Risk:** low (pure refactor, no behavior change)
**Gate:** After Phase A corpus re-run — do in Phase B cleanup sprint alongside 012 and 032
---

# 009 — service_utils + ic_engine shared-utility cleanup

**Numbering note (2026-07-01):** this file previously carried three different numbers — filename
009, an inner YAML frontmatter `id: "006"`, and a heading "# 015" — from being renumbered across
sessions without the inline copies being updated. Normalized to 009 (the filename / pending-folder
key) throughout. Source: Phase 140 `/simplify` review — 4 architectural items deferred as
out-of-diff scope.

Four architectural simplifications deferred from Phase 140. None are correctness issues — all are DRY / altitude improvements. Group into one small refactor phase when convenient.

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
mirrors `_expand()` (float/NaN version). Add a sibling `_expand_int(nd_arr, mask, n) -> list[int | None]` using `np.full(n, None, dtype=object)` + index assignment, or generalise `_expand` with an optional fill/dtype parameter.

**Why:** Removes duplication of the scatter pattern; any future int-typed per-feature column benefits.

---

## Item 4: Relocate `_meta_eligible` out of ensemble_trainer

**Where:** `services/ensemble_trainer.py` line 92.

**What:** `_meta_eligible` is a pure function with no service dependencies. Move to a shared IC utilities module (e.g. `src/intelligence/ic_utils.py` or alongside IC scoring helpers).

**Why:** As a service-file private it can't be imported by a second consumer without pulling in the full service. Natural home is alongside IC scoring logic.

---

## Suggested grouping

Do all four in one commit — they all touch `src/core/service_utils.py` or shared IC helpers, require no migration, and are pure refactors with no behavior change. Verify with `pytest tests/unit/ -q` after.
