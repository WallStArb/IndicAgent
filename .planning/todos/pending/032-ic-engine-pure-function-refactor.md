---
**Created:** 2026-06-30
**Area:** infra
**Type:** refactor
**Priority:** P2
**Effort:** 2-3 hours
**Benefit:** Pure functions are testable in isolation, auditable, and make future ic_engine changes lower risk
**Risk:** low (pure refactor, no behavior change)
**Gate:** After Phase A corpus re-run validates corrected methodology — refactor known-correct code, not simultaneously-fixed code
---

# 032 — ic_engine Pure Function Extraction

**Trigger:** After Phase A (A2 + A5) ships and corpus re-run confirms corrected IC scores.
Stabilize measurement correctness first; then harden the infrastructure around it.

## Problem

`ic_engine.py` conflates four distinct concerns in one monolith:
1. **Measurement** — IC computation (pure math)
2. **Methodology** — fold and embargo construction (pure math)
3. **Multiple testing** — BH-FDR application (pure statistics)
4. **Orchestration + persistence** — ProcessPoolExecutor dispatch, DB writes

This is why the A2 P2 fix (corpus-level BH-FDR) required tracing the result collection
flow across all four layers before writing anything. A future BH-FDR change should be
a three-line fix, not an architectural trace.

Jim Simons' mandate: every measurement is a deterministic function with no side effects —
testable in isolation, auditable, parallelizable without surprise.

## Proposed extractions

### 1. `build_walk_forward_folds(n_obs, n_folds, embargo_bars) -> list[tuple[int,int,int,int]]`

Pure function returning `(train_start, train_end, test_start, test_end)` per fold.
Currently embedded in the per-cell compute loop.

**Benefit:** P0 (walk-forward correctness) would have been a 5-line rewrite of one
function with a direct unit test. Currently it requires understanding the full cell
compute context.

```python
def build_walk_forward_folds(
    n_obs: int, n_folds: int, embargo_bars: int
) -> list[tuple[int, int, int, int]]:
    """Fixed-origin expanding window with per-fold embargo."""
    ...
```

### 2. `compute_ic_for_window(ranks_x, ranks_y) -> SpearmanResult`

Pure function: takes rank arrays, returns IC + p-value. No APR, no config, no DB.
Currently embedded in the scale loop inside `_compute_symbol_tf`.

**Benefit:** Unit-testable with synthetic data. Correctness provable independently
of the surrounding orchestration.

### 3. `apply_corpus_fdr(p_values, alpha) -> np.ndarray[bool]`

Pure function: takes all p-values across all cells, returns boolean mask.
The A2 P2 fix moved this from per-cell to corpus-level in the main process.
This extraction just names and isolates what that fix already achieves logically.

```python
def apply_corpus_fdr(p_values: list[float], alpha: float) -> np.ndarray:
    from statsmodels.stats.multitest import multipletests
    _, corrected, _, _ = multipletests(p_values, alpha=alpha, method="fdr_bh")
    return corrected
```

**Benefit:** Swappable (Bonferroni, Storey's q, Benjamini-Yekutieli) without
touching the orchestration layer.

### 4. `_cluster_features` — already a private method, keep as-is

The clustering is already isolated. No change needed.

## What stays in the service

- ProcessPoolExecutor dispatch and worker coordination
- DB read/write path
- APR config loading (already moving to compile-time binding per todo 008)
- Logging and metrics

## Suggested location

New module: `src/intelligence/ic/` (or `src/intelligence/ensemble/ic_math.py`)
containing the three pure functions + their unit tests in `tests/unit/intelligence/test_ic_math.py`.

## Notes

- Do not do this simultaneously with A2 correctness fixes — that doubles the diff
  and makes regression analysis impossible.
- Do not do this before the corpus re-run — refactor on validated code, not on
  code you're simultaneously fixing.
- After extraction, the existing `test_ic_engine.py` (if any) can be supplemented
  with direct unit tests for each pure function using synthetic rank arrays.
- Related: 009 (service_utils cleanup) can be done in the same sprint.
