# IC Null Calibration Diagnostic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a read-only diagnostic that empirically checks whether the analytic Fisher z-transform CI (`_fisher_z_ci` in `ic_math.py`) correctly describes the null distribution of Spearman IC on this corpus, using a circular-shift permutation test on cells stratified at the CI/FDR gate decision boundary.

**Architecture:** A new pure function (`_circular_shift_null`) in the shared `ic_math.py` kernel, consumed by a new one-off `scripts/ops/alpha/` diagnostic script that reuses the existing production IC-computation functions unchanged. No schema change, no APR keys, no edit to any production write path. The diagnostic's verdict determines whether the dead `alpha.ic.bootstrap_*` APR keys get deleted or bootstrap gets reopened, recorded as a new dated entry in `docs/research/measurement-ic-engine.md`.

**Tech Stack:** Python 3.14, numpy, scipy.stats (rankdata, shapiro), asyncpg, pytest.

## Global Constraints

- All timestamps UTC — `datetime.now(UTC)` only (no new timestamps are created by this work, but any logged timestamps must follow this).
- Exception variable name is `error`, not `exc`.
- No hardcoded numeric thresholds in `src/` — `_SE_RATIO_SUSPECT_THRESHOLD` and similar constants belong in the `scripts/ops/` script as CLI-arg defaults (matches existing `ops_ensemble_ic_diagnosis.py`/`ops_ensemble_weight_compare.py` precedent — one-off diagnostic scripts are not APR-backed; the APR mandate scopes to `src/` and `services/`).
- Reuse `_vectorized_ic`, `_fisher_z_ci`, `rankdata` from `ic_math.py` directly in the diagnostic script — never reimplement IC computation.
- DSN pattern: `Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")` + `asyncpg.create_pool(dsn=dsn)` (matches `ops_ensemble_weight_compare.py`/`ops_ensemble_ic_diagnosis.py`).
- Exit code always 0 for the diagnostic script — informational, never a gate.

---

### Task 1: `_circular_shift_null` pure function + unit tests

**Files:**
- Modify: `src/intelligence/statistics/ic_math.py`
- Modify: `tests/unit/test_ensemble_ic_math.py`

**Interfaces:**
- Produces: `_circular_shift_null(Y: np.ndarray, rng: np.random.Generator) -> np.ndarray` — used by Task 2's permutation loop.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_ensemble_ic_math.py`, extending the existing import block:

```python
from src.intelligence.statistics.ic_math import (
    _circular_shift_null,
    _fisher_z_ci,
    _p_values_from_ic,
    _vectorized_ic,
    apply_bh_fdr,
    fisher_z_difference_p,
)
```

Add these test functions at the end of the file:

```python
def test_circular_shift_null_preserves_value_multiset():
    """Shifting must not fabricate or drop any value -- same multiset, same length."""
    rng = np.random.default_rng(7)
    Y = np.array([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0])
    shifted = _circular_shift_null(Y, rng)
    assert len(shifted) == len(Y)
    assert sorted(shifted.tolist()) == sorted(Y.tolist())


def test_circular_shift_null_never_returns_identity_for_distinct_values():
    """Offset excludes 0 -- with all-distinct values, output must differ from input."""
    Y = np.arange(50.0)
    for seed in range(20):
        rng = np.random.default_rng(seed)
        shifted = _circular_shift_null(Y, rng)
        assert not np.array_equal(shifted, Y)


def test_circular_shift_null_is_deterministic_given_seeded_generator():
    """Two independently-seeded generators with the same seed must produce the same shift."""
    Y = np.arange(30.0)
    rng_a = np.random.default_rng(123)
    rng_b = np.random.default_rng(123)
    shifted_a = _circular_shift_null(Y, rng_a)
    shifted_b = _circular_shift_null(Y, rng_b)
    assert np.array_equal(shifted_a, shifted_b)


def test_circular_shift_null_wraps_circularly_matches_np_roll():
    """Implementation must be np.roll (circular, no truncation) -- verify against a known offset."""
    Y = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    rng = np.random.default_rng(99)
    offset = int(rng.integers(1, len(Y)))
    rng_replay = np.random.default_rng(99)
    shifted = _circular_shift_null(Y, rng_replay)
    assert np.array_equal(shifted, np.roll(Y, offset))


def test_circular_shift_null_handles_length_one():
    """n < 2: no valid nonzero offset exists -- return the array unchanged."""
    rng = np.random.default_rng(1)
    Y = np.array([42.0])
    shifted = _circular_shift_null(Y, rng)
    assert np.array_equal(shifted, Y)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ic_math.py -k circular_shift -v`
Expected: FAIL with `ImportError: cannot import name '_circular_shift_null'`

- [ ] **Step 3: Implement `_circular_shift_null` in `ic_math.py`**

Add this function after `_vectorized_ic` (before the `compute_ic_vectorized` public wrapper), in the "Vectorized IC computation" section:

```python
def _circular_shift_null(
    Y: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Circularly shift Y by a random offset in [1, len(Y)-1] (todo 071 / L4-2).

    Destroys alignment with any paired X while preserving Y's own autocorrelation/
    spectral structure exactly -- every value present, same adjacency structure up
    to the wrap point. This is what makes the result a meaningful null for an
    autocorrelated series; an i.i.d. shuffle would destroy the autocorrelation the
    stride-subsampling/HAC design exists to handle, producing an easier strawman null.

    Excludes offset=0 (the identity permutation, which would leave X-Y aligned).
    n < 2 has no valid nonzero offset; returns a copy of Y unchanged.
    """
    n = len(Y)
    if n < 2:
        return Y.copy()
    offset = int(rng.integers(1, n))
    return np.roll(Y, offset)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ic_math.py -k circular_shift -v`
Expected: 5 passed

- [ ] **Step 5: Run full ic_math test file to confirm no regression**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ic_math.py -v`
Expected: all tests pass (14 pre-existing + 5 new = 19)

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/statistics/ic_math.py tests/unit/test_ensemble_ic_math.py
git commit -m "feat(ic-math): add circular-shift null permutation for L4-2 calibration check"
```

---

### Task 2: `ops_ic_null_calibration.py` diagnostic script

**Files:**
- Create: `scripts/ops/alpha/ops_ic_null_calibration.py`

**Interfaces:**
- Consumes: `_circular_shift_null(Y, rng)` from Task 1; `_vectorized_ic(ranks_X, ranks_Y)`, `_fisher_z_ci(ic_vector, n)` from `ic_math.py` (both pre-existing, unchanged).
- Produces: a Markdown report on stdout; exit code 0 always.

**Context needed before writing this task (verified against live schema/code, not assumed):**

- `feature_ic_scores` columns used: `feature_name, symbol, tf, regime, lookahead_bars, training_window_end, is_pooled, n_independent, reliable, passes_fdr, ic_value, ic_ci_lower, ic_sharpe_hac`.
- `market_regimes` columns: `asset_class, tf, ts, regime_label, regime_prob_vector` (PK `asset_class, tf, ts`) — **note the time column is `ts`, not `bar_ts`**.
- **Regime labels for BOTH per-symbol (`is_pooled=false`) and pooled (`is_pooled=true`) cells come from `market_regimes`, not `feature_vectors.regime`.** Verified via `SELECT regime_scope, count(*) FROM feature_ic_scores GROUP BY 1` — only `cross_sectional` (783,300 rows, spanning both `is_pooled` values) and `pooled` (137,349 rows) exist; `symbol_hmm` has zero rows (todo 026 P4a unresolved). This corpus was measured with `equity_model_enabled=true`, meaning `ic_engine.py` sourced every regime label — per-symbol cells included — from `market_regimes`, never from `feature_vectors.regime`. **The two fetch shapes differ only in whether `fv.symbol` is pinned to one value or left unconstrained** — same join through `market_regimes`, not two structurally different queries.
- `forward_returns` columns: `return_fast, return_mid, return_slow, return_extended, complete_fast, complete_mid, complete_slow, complete_extended`, filtered by `return_type = 'executable_open_to_open'`.
- Scale-to-bars mapping is APR-configurable (`alpha.ic.lookahead.{fast,mid,slow,extended}`, defaults 1/5/20/60) — read from `config_state` at script start and build a `bars_to_scale` reverse map; don't hardcode the default mapping, since `feature_ic_scores.lookahead_bars` is an integer and the script needs the scale name to pick `return_<scale>`/`complete_<scale>` columns.
- `alpha.ic.subsample_min_stride` (default 5) read from `config_state` the same way — `SELECT config_value FROM config_state WHERE config_key = $1` (plain SQL, matches `ops_ensemble_weight_compare.py`'s pattern; no `ConfigService` instantiation needed for a one-off read).
- Cell sampling scopes to the single latest `training_window_end` vintage (`WHERE training_window_end = (SELECT max(training_window_end) FROM feature_ic_scores)`) — the design doc didn't spell this out explicitly, but it's required: without it, sampling could mix cells from different corpus rebuilds, comparing null calibration against stale data. This matches the existing `max(scored_at)` "latest vintage" convention used elsewhere (`ops_ensemble_ic_diagnosis.py`, D-142A-R2).
- "Top decile" for strong cells (from the design doc) is operationalized as "top 2 by `ic_sharpe_hac` rank" — selecting exactly 2 rows from within a computed decile boundary is behaviorally identical to picking the top 2 by rank for this diagnostic's purpose, and avoids an unnecessary `percentile_cont()` subquery.
- `_compute_ic_rolling_metrics`'s per-scale subsampling in production computes `n_independent = len(sub_idx)` **before** the completeness/finite-value mask is applied — the diagnostic's mismatch check (Mechanics step 3 in the design doc) must therefore compare `len(sub_idx)` (post-stride, pre-completeness-filter count) against the stored `n_independent`, not the post-filter valid count.

- [ ] **Step 1: Write the script**

Create `scripts/ops/alpha/ops_ic_null_calibration.py`:

```python
#!/usr/bin/env python3
"""
ops_ic_null_calibration.py -- L4-2 empirical null calibration for the IC inference chain.

Design: docs/plans/2026-07-09-ic-null-calibration-design.md (todo 071 / L4-2).

Checks whether `_fisher_z_ci`'s analytic standard error (SE = 1/sqrt(n-3)) correctly
describes the sampling distribution of Spearman IC on this corpus, by circularly
shifting the forward-return series (destroys X-Y alignment, preserves Y's own
autocorrelation) 200x per sampled cell and comparing the empirical null's standard
error and shape against the analytic prediction.

Cells are stratified at the CI/FDR gate decision boundary (5 boundary cells nearest
`|ic_ci_lower|`, 2 clearly-null, 2 clearly-strong per (tf, is_pooled) stratum) rather
than sampled uniformly -- the point is to protect decisions actually being made
today, not to characterize the null everywhere. See the design doc for the full
rationale, including why `is_pooled` (not `regime_scope`) is the correct
stratification axis (`regime_scope='symbol_hmm'` has zero rows today).

D-01: regime labels for every sampled cell -- per-symbol AND pooled -- come from
`market_regimes` (this corpus was measured with `equity_model_enabled=true`), never
from `feature_vectors.regime`. The per-symbol and pooled fetch queries differ only in
whether `fv.symbol` is pinned to one value.

D-02: sampling scopes to the single latest `training_window_end` vintage in
`feature_ic_scores`, matching the existing "latest vintage" convention used by
`ops_ensemble_ic_diagnosis.py` -- prevents mixing cells across corpus rebuilds.

D-03: the `n_independent` cross-check (production's `_compute_ic_rolling_metrics`
computes this as `len(sub_idx)` BEFORE the completeness/finite-value mask) compares
against the diagnostic's own post-stride, pre-completeness-filter row count -- not
the post-filter valid count -- to match production's definition exactly.

This report is diagnostic; remediation (delete the dead `alpha.ic.bootstrap_*` APR
keys, or reopen circular block bootstrap) is a follow-up decision recorded in
`docs/research/measurement-ic-engine.md`, not made by this script. Exit code is
always 0 -- informational, not a gate.

Usage:
    python scripts/ops/alpha/ops_ic_null_calibration.py
    python scripts/ops/alpha/ops_ic_null_calibration.py --n-permutations 500 --seed 7
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg
import numpy as np
from scipy.stats import rankdata, shapiro

from src.config.settings import Settings
from src.intelligence.statistics.ic_math import _circular_shift_null, _fisher_z_ci, _vectorized_ic

_TFS = ("5m", "15m", "1h", "1d")
_N_BOUNDARY_CELLS = 5
_N_NULL_CELLS = 2
_N_STRONG_CELLS = 2
_N_PERMUTATIONS_DEFAULT = 200
_SE_RATIO_SUSPECT_THRESHOLD_DEFAULT = 1.2
_SHAPIRO_ALPHA = 0.05

_LATEST_VINTAGE_SQL = "SELECT max(training_window_end) FROM feature_ic_scores"

_LOOKAHEAD_APR_KEYS = {
    "fast": "alpha.ic.lookahead.fast",
    "mid": "alpha.ic.lookahead.mid",
    "slow": "alpha.ic.lookahead.slow",
    "extended": "alpha.ic.lookahead.extended",
}
_LOOKAHEAD_DEFAULTS = {"fast": 1, "mid": 5, "slow": 20, "extended": 60}

_BOUNDARY_CELLS_SQL = """
    SELECT feature_name, symbol, tf, regime, lookahead_bars, training_window_end,
           is_pooled, n_independent, ic_ci_lower, ic_value, ic_sharpe_hac
    FROM feature_ic_scores
    WHERE tf = $1 AND is_pooled = $2 AND training_window_end = $3
      AND passes_fdr = true AND reliable = true AND ic_ci_lower IS NOT NULL
    ORDER BY abs(ic_ci_lower) ASC
    LIMIT $4
"""

_NULL_CELLS_SQL = """
    SELECT feature_name, symbol, tf, regime, lookahead_bars, training_window_end,
           is_pooled, n_independent, ic_ci_lower, ic_value, ic_sharpe_hac
    FROM feature_ic_scores
    WHERE tf = $1 AND is_pooled = $2 AND training_window_end = $3
      AND passes_fdr = false AND reliable = true AND ic_value IS NOT NULL
    ORDER BY abs(ic_value) ASC
    LIMIT $4
"""

_STRONG_CELLS_SQL = """
    SELECT feature_name, symbol, tf, regime, lookahead_bars, training_window_end,
           is_pooled, n_independent, ic_ci_lower, ic_value, ic_sharpe_hac
    FROM feature_ic_scores
    WHERE tf = $1 AND is_pooled = $2 AND training_window_end = $3
      AND reliable = true AND ic_sharpe_hac IS NOT NULL
    ORDER BY ic_sharpe_hac DESC
    LIMIT $4
"""

_FETCH_PER_SYMBOL_SQL_TMPL = """
    SELECT fv.bar_ts, fv."{feature_name}" AS x_val, fr.return_{scale} AS y_val,
           fr.complete_{scale} AS is_complete
    FROM market_regimes mr
    INNER JOIN feature_vectors fv ON fv.bar_ts = mr.ts AND fv.tf = mr.tf
    INNER JOIN forward_returns fr
        ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
        AND fr.return_type = 'executable_open_to_open'
    WHERE mr.asset_class = 'equity' AND mr.tf = $1 AND mr.regime_label = $2
      AND fv.bar_ts <= $3 AND fv.symbol = $4
    ORDER BY fv.bar_ts
"""

_FETCH_POOLED_SQL_TMPL = """
    SELECT fv.bar_ts, fv."{feature_name}" AS x_val, fr.return_{scale} AS y_val,
           fr.complete_{scale} AS is_complete
    FROM market_regimes mr
    INNER JOIN feature_vectors fv ON fv.bar_ts = mr.ts AND fv.tf = mr.tf
    INNER JOIN forward_returns fr
        ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
        AND fr.return_type = 'executable_open_to_open'
    WHERE mr.asset_class = 'equity' AND mr.tf = $1 AND mr.regime_label = $2
      AND fv.bar_ts <= $3
    ORDER BY fv.bar_ts, fv.symbol
"""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-permutations", type=int, default=_N_PERMUTATIONS_DEFAULT)
    parser.add_argument("--se-ratio-suspect-threshold", type=float, default=_SE_RATIO_SUSPECT_THRESHOLD_DEFAULT)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


async def _load_config_int(pool: asyncpg.Pool, key: str, default: int) -> int:
    row = await pool.fetchval("SELECT config_value FROM config_state WHERE config_key = $1", key)
    return int(row) if row is not None else default


async def _sample_cells(pool: asyncpg.Pool, vintage) -> list[dict]:
    cells: list[dict] = []
    for tf in _TFS:
        for is_pooled in (False, True):
            for sql, limit in (
                (_BOUNDARY_CELLS_SQL, _N_BOUNDARY_CELLS),
                (_NULL_CELLS_SQL, _N_NULL_CELLS),
                (_STRONG_CELLS_SQL, _N_STRONG_CELLS),
            ):
                rows = await pool.fetch(sql, tf, is_pooled, vintage, limit)
                if len(rows) < limit:
                    print(
                        f"WARNING: stratum tf={tf} is_pooled={is_pooled} query="
                        f"{sql.strip().splitlines()[1].strip()[:40]}... only found "
                        f"{len(rows)}/{limit} qualifying cells"
                    )
                cells.extend(dict(r) for r in rows)
    return cells


async def _fetch_cell_series(
    pool: asyncpg.Pool, cell: dict, scale: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    tmpl = _FETCH_POOLED_SQL_TMPL if cell["is_pooled"] else _FETCH_PER_SYMBOL_SQL_TMPL
    sql = tmpl.format(feature_name=cell["feature_name"], scale=scale)
    if cell["is_pooled"]:
        rows = await pool.fetch(sql, cell["tf"], cell["regime"], cell["training_window_end"])
    else:
        rows = await pool.fetch(sql, cell["tf"], cell["regime"], cell["training_window_end"], cell["symbol"])
    x = np.array([r["x_val"] for r in rows], dtype=np.float64)
    y = np.array([r["y_val"] if r["y_val"] is not None else np.nan for r in rows], dtype=np.float64)
    complete = np.array([bool(r["is_complete"]) for r in rows], dtype=bool)
    return x, y, complete


def _evaluate_cell(
    x_raw: np.ndarray,
    y_raw: np.ndarray,
    complete_raw: np.ndarray,
    stride: int,
    stored_n_independent: int,
    n_permutations: int,
    rng: np.random.Generator,
) -> dict | None:
    n_raw = len(x_raw)
    sub_idx = np.arange(0, n_raw, stride)
    n_independent = len(sub_idx)
    if n_independent != stored_n_independent:
        return None  # mismatch: cell mis-selected or corpus drifted since measurement

    x_sub = x_raw[sub_idx]
    y_sub = y_raw[sub_idx]
    complete_sub = complete_raw[sub_idx]
    valid_mask = complete_sub & np.isfinite(y_sub) & np.isfinite(x_sub)
    n_valid = int(valid_mask.sum())
    if n_valid < 4:
        return None  # _fisher_z_ci requires n >= 4

    x_valid = x_sub[valid_mask]
    y_valid = y_sub[valid_mask]
    ranks_x = rankdata(x_valid).reshape(-1, 1)

    observed_ic = float(_vectorized_ic(ranks_x, rankdata(y_valid))[0])

    ic_null = np.empty(n_permutations)
    for i in range(n_permutations):
        y_shifted = _circular_shift_null(y_valid, rng)
        ic_null[i] = _vectorized_ic(ranks_x, rankdata(y_shifted))[0]

    z_null = np.arctanh(np.clip(ic_null, -1 + 1e-10, 1 - 1e-10))
    empirical_se = float(np.std(z_null, ddof=1))
    analytic_se = 1.0 / np.sqrt(n_valid - 3)
    se_ratio = empirical_se / analytic_se
    shapiro_stat, shapiro_p = shapiro(z_null)

    return {
        "n_valid": n_valid,
        "observed_ic": observed_ic,
        "empirical_se": empirical_se,
        "analytic_se": analytic_se,
        "se_ratio": se_ratio,
        "shapiro_p": float(shapiro_p),
    }


async def main() -> int:
    args = _parse_args()
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)

    try:
        vintage = await pool.fetchval(_LATEST_VINTAGE_SQL)
        if vintage is None:
            print("ERROR: feature_ic_scores is empty -- nothing to sample.")
            return 0

        lookaheads = {
            scale: await _load_config_int(pool, key, _LOOKAHEAD_DEFAULTS[scale])
            for scale, key in _LOOKAHEAD_APR_KEYS.items()
        }
        bars_to_scale = {bars: scale for scale, bars in lookaheads.items()}
        subsample_min_stride = await _load_config_int(pool, "alpha.ic.subsample_min_stride", 5)

        print(f"# L4-2 Null Calibration Report (vintage: {vintage})\n")
        print(f"n_permutations={args.n_permutations}, seed={args.seed}, "
              f"se_ratio_suspect_threshold={args.se_ratio_suspect_threshold}\n")

        cells = await _sample_cells(pool, vintage)
        print(f"Sampled {len(cells)} cells.\n")

        rng = np.random.default_rng(args.seed)
        print("| feature | symbol | tf | regime | lookahead | n_valid | observed_ic | "
              "analytic_se | empirical_se | se_ratio | shapiro_p | flag |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|")

        n_suspect = 0
        n_evaluated = 0
        n_skipped = 0
        suspect_by_stratum: dict[tuple[str, bool], int] = {}

        for cell in cells:
            scale = bars_to_scale.get(cell["lookahead_bars"])
            if scale is None:
                n_skipped += 1
                continue
            stride = max(subsample_min_stride, cell["lookahead_bars"])
            x_raw, y_raw, complete_raw = await _fetch_cell_series(pool, cell, scale)
            result = _evaluate_cell(
                x_raw, y_raw, complete_raw, stride, cell["n_independent"],
                args.n_permutations, rng,
            )
            if result is None:
                n_skipped += 1
                continue

            n_evaluated += 1
            flag = "SUSPECT" if result["se_ratio"] > args.se_ratio_suspect_threshold else "OK"
            if flag == "SUSPECT":
                n_suspect += 1
                key = (cell["tf"], cell["is_pooled"])
                suspect_by_stratum[key] = suspect_by_stratum.get(key, 0) + 1

            print(
                f"| {cell['feature_name']} | {cell['symbol']} | {cell['tf']} | "
                f"{cell['regime']} | {scale} | {result['n_valid']} | "
                f"{result['observed_ic']:.4f} | {result['analytic_se']:.4f} | "
                f"{result['empirical_se']:.4f} | {result['se_ratio']:.3f} | "
                f"{result['shapiro_p']:.4f} | {flag} |"
            )

        print(f"\n## Summary\n")
        print(f"Evaluated: {n_evaluated}, skipped (mismatch/insufficient N): {n_skipped}, "
              f"SUSPECT: {n_suspect}\n")
        if n_suspect == 0:
            print("**Verdict: Fisher-z CI calibration confirmed across all sampled cells.**")
        else:
            print("**Verdict: SUSPECT cells found -- analytic CI may be too narrow. "
                  "Stratum breakdown:**")
            for (tf, is_pooled), count in sorted(suspect_by_stratum.items()):
                print(f"- tf={tf}, is_pooled={is_pooled}: {count} SUSPECT cell(s)")
        print("\n---\nThis report is diagnostic; remediation decisions are human/operator.")
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Verify the script imports and parses args cleanly**

Run: `python scripts/ops/alpha/ops_ic_null_calibration.py --help`
Expected: argparse help text prints, exit code 0, no import errors.

- [ ] **Step 3: Run against the live corpus**

Run: `.venv/bin/python scripts/ops/alpha/ops_ic_null_calibration.py`
Expected: a Markdown report prints to stdout, ending in a Summary section with an explicit SUSPECT count and verdict line. Exit code 0. Runtime should be low single-digit minutes (72 cells x 200 permutations, per the design doc's compute-budget estimate).

- [ ] **Step 4: Commit**

```bash
git add scripts/ops/alpha/ops_ic_null_calibration.py
git commit -m "feat(alpha): add L4-2 IC null calibration diagnostic script"
```

---

### Task 3: Record the durable outcome

**Files:**
- Modify: `docs/research/measurement-ic-engine.md`
- Modify: `.planning/todos/pending/071-measurement-diagnostics-null-calibration-ic-decomposition.md` (or move to `completed/`, see below)
- Possibly create: a new migration deleting `alpha.ic.bootstrap_*` keys (only if the verdict is all-clear)
- Possibly create: a new todo for stratum-specific bootstrap reopening (only if any stratum shows SUSPECT clustering)

**Interfaces:**
- Consumes: the Markdown report output from Task 2, Step 3 (captured as this task's input, not re-run).

- [ ] **Step 1: Read the Task 2 report output and determine the verdict**

Re-read the captured stdout from Task 2 Step 3. Determine: (a) total SUSPECT count, (b) whether any `(tf, is_pooled)` stratum shows more than one SUSPECT cell (systematic clustering) vs. isolated one-offs.

- [ ] **Step 2a (if verdict is all-clear, zero SUSPECT cells): delete the dead bootstrap APR keys**

Find the next available migration number:

Run: `ls production/migrations/ | tail -5`

Create `production/migrations/<N>_remove_dead_ic_bootstrap_keys.sql`:

```sql
-- Migration <N>: Remove dead alpha.ic.bootstrap_* APR keys.
--
-- These keys (migrations 161, 165, 177) were superseded by the Fisher z-transform CI
-- when circular block bootstrap was removed from ic_engine.py, but the keys were never
-- deleted -- zero readers since. The L4-2 empirical null calibration diagnostic
-- (docs/plans/2026-07-09-ic-null-calibration-design.md, scripts/ops/alpha/
-- ops_ic_null_calibration.py) confirmed the Fisher-z analytic SE matches the empirical
-- null across all sampled cells -- see docs/research/measurement-ic-engine.md for the
-- dated record. Deleting rather than leaving "just in case."

DELETE FROM config_state WHERE config_key IN (
    'alpha.ic.bootstrap_seed',
    'alpha.ic.bootstrap_resamples',
    'alpha.ic.bootstrap_block_size.5m',
    'alpha.ic.bootstrap_block_size.15m',
    'alpha.ic.bootstrap_block_size.1h',
    'alpha.ic.bootstrap_block_size.1d'
);

DELETE FROM config_schema WHERE config_key IN (
    'alpha.ic.bootstrap_seed',
    'alpha.ic.bootstrap_resamples',
    'alpha.ic.bootstrap_block_size.5m',
    'alpha.ic.bootstrap_block_size.15m',
    'alpha.ic.bootstrap_block_size.1h',
    'alpha.ic.bootstrap_block_size.1d'
);
```

Apply it per this project's standard migration-runner convention (check `docs/reference/cheatsheet.md` for the exact command if unfamiliar with this repo's migration tool).

- [ ] **Step 2b (if any SUSPECT cells found): file a follow-up todo instead**

Find the next pending todo number:

Run: `ls .planning/todos/pending/ | sort -t- -k1 -n | tail -3`

Create `.planning/todos/pending/<N>-fisher-z-ci-bootstrap-reopen-<affected-stratum>.md` describing exactly which `(tf, is_pooled)` strata showed SUSPECT clustering, the observed `se_ratio` values, and that circular block bootstrap needs reopening in `ic_math.py` for those strata specifically (giving `alpha.ic.bootstrap_*` their first real reader) — do not delete the APR keys in this branch.

- [ ] **Step 3: Add the dated record to `measurement-ic-engine.md`**

Read the file first to find the exact insertion point:

Run: `grep -n "^## Measurement Gaps\|^## The Measurement Gaps" docs/research/measurement-ic-engine.md`

Add a new row to the Measurement Gaps table (the `| Gap | Status | Why it matters |` table) with a new entry:

```markdown
| **L4-2: empirical null calibration** (circular-shift permutation vs. analytic Fisher-z CI) | **Checked 2026-07-09** — `scripts/ops/alpha/ops_ic_null_calibration.py`, 72 cells stratified at the CI/FDR gate boundary, 200 permutations each. Verdict: [FILL IN FROM TASK 2's actual report output — either "confirmed, zero SUSPECT cells, dead bootstrap keys removed via migration <N>" or "SUSPECT clustering found in <stratum>, see todo <N>"] | Every CI gate, BH-FDR pass/fail, and walk-forward validation in the stack inherits this assumption's correctness — this is the check that either certifies or corrects it. |
```

- [ ] **Step 4: Close out todo 071's L4-2 half**

Read `.planning/todos/pending/071-measurement-diagnostics-null-calibration-ic-decomposition.md`. Since it covers both L4-2 (this work) and L4-4 (separate, deferred), do not delete it outright — edit it to remove the L4-2 section (mark it done inline, pointing to this plan and the `measurement-ic-engine.md` record) and keep only L4-4 as the remaining open scope. If the file structure makes a clean split awkward, instead: move the current file to `.planning/todos/completed/071-...md` with an inline note that L4-2 is done and L4-4 was re-filed as a new pending todo — pick whichever produces a cleaner single-topic-per-file result, matching this project's existing todo-hygiene convention (see the todo-list audit in `project_renaissance_refinements_backlog` memory for precedent on splitting overlapping-scope todos).

- [ ] **Step 5: Commit**

```bash
git add docs/research/measurement-ic-engine.md .planning/todos/
# plus the migration file (2a) or new todo file (2b) if created
git commit -m "docs: record L4-2 null calibration verdict, close out todo 071's L4-2 scope"
```

---

## Self-Review Notes

- **Spec coverage:** Falsification target (Task 2's permutation loop), cell sampling (Task 2's `_sample_cells`), mechanics/exact-reuse (Task 2 imports production functions unchanged), verdict criteria (Task 2's `_evaluate_cell`), durable record (Task 3), testing (Task 1) — all design doc sections have a corresponding task.
- **Corrected during planning, not assumed from the design doc:** regime labels for per-symbol cells come from `market_regimes`, not `feature_vectors.regime` (verified via `regime_scope` distribution query) — the design doc's prose was directionally correct but not SQL-precise; this plan's queries reflect the verified behavior. The "latest vintage" scoping and the `n_independent` pre-completeness-filter definition were both absent from the design doc and added here after checking production code directly.
- **Type consistency:** `_circular_shift_null(Y, rng)` signature matches between Task 1's implementation and Task 2's `_evaluate_cell` usage. `_evaluate_cell`'s return dict keys (`n_valid`, `observed_ic`, `empirical_se`, `analytic_se`, `se_ratio`, `shapiro_p`) match exactly what `main()`'s report-printing loop reads.
