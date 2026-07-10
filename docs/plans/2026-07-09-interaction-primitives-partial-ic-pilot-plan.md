# Interaction Primitives Partial-IC Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer todo 037's open question -- do the 8 already-live Renaissance interaction primitives (`vol_body_product`, `ret_vol_product_fast`, `price_vol_corr_fast`, `price_vol_corr_slow`, `range_vol_product`, `up_vol_body_diff`, `ret_vol_ratio_fast`, `vol_skew_product`) carry genuine incremental IC after controlling for their 2 parent atomics each, or is their naive IC fully explained by the parents -- by building and running a partial-correlation measurement against the live corpus, then applying todo 037's decision rule.

**Architecture:** A pure-math `partial_spearman_ic()` function (Ring 1, `src/intelligence/statistics/ic_math.py`) implements rank-residual partial correlation with k>=1 controls. A new standalone ops script (`scripts/ops/alpha/ops_interaction_primitives_pilot.py`, same architectural class as `ops_ensemble_weight_compare.py`) discovers the 8 interaction features + their parent atomics from `feature_registry`, finds already-measured pooled-aggregate cells in `feature_ic_scores`, streams raw values from `feature_vectors`/`forward_returns`, computes partial IC per cell, writes results back to new `feature_ic_scores` columns, applies a dedicated BH-FDR pass over this small family, and reports the decision-rule verdict. No changes to the existing, fragile `ic_engine.py` compute loop -- this is purely additive, reusing already-computed naive-IC rows as its input population rather than re-deriving them.

**Tech Stack:** Python 3, numpy/scipy (rankdata, lstsq, t-distribution), asyncpg, PostgreSQL/TimescaleDB, pytest.

## Global Constraints

- APR mandate: any new numeric threshold introduced in `services/`/`scripts/` must be a `config_schema`/`config_state`/`config_history` triad, not a module constant (CLAUDE.md "Adding a parameter").
- Exception variable name is `error`, never `exc` (CLAUDE.md).
- `datetime.now(UTC)` only, never naive `datetime.now()`.
- Migration files: `NNN_snake_case_description.sql`, idempotent (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`), wrapped in `BEGIN`/`COMMIT`.
- Pure statistics functions (`ic_math.py`) must have zero DB/Kafka dependency -- numpy/scipy only, matching the existing module's own constraint stated in its docstring.
- This is a **pilot decision gate, not a promotion-grade re-measurement**: the partial-IC pass approximates (does not byte-for-byte reproduce) `ic_engine.py`'s exact per-symbol chunk boundaries during subsampling. It reuses the same stride formula (`max(subsample_min_stride, lookahead_bars)`) applied positionally within each symbol's row block before pooling, which is a faithful analog, not an identical replay. This is stated explicitly in code comments and the final report so nobody later cites `partial_ic` as a formal promotion number without re-deriving it through the full walk-forward apparatus.

---

### Task 1: `partial_spearman_ic()` pure function

**Files:**
- Modify: `src/intelligence/statistics/ic_math.py`
- Test: `tests/unit/test_ensemble_ic_math.py`

**Interfaces:**
- Produces: `partial_spearman_ic(x: np.ndarray, y: np.ndarray, controls: np.ndarray, condition_max: float) -> tuple[float, float, int]` returning `(partial_ic, p_value, n)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_ensemble_ic_math.py` (add to the existing `from src.intelligence.statistics.ic_math import (...)` block: add `partial_spearman_ic`):

```python
def test_partial_spearman_ic_removes_fully_shared_variance():
    """x and y are correlated ONLY through a shared control z -- naive IC should be
    high, partial IC controlling for z should collapse to ~0."""
    rng = np.random.default_rng(42)
    n = 2000
    z = rng.normal(size=n)
    x = z + rng.normal(scale=0.1, size=n)
    y = z + rng.normal(scale=0.1, size=n)

    naive_ic, _ = spearmanr(x, y)
    assert naive_ic > 0.8  # sanity: strong naive correlation via shared z

    partial_ic, p_value, n_used = partial_spearman_ic(
        x, y, z.reshape(-1, 1), condition_max=1000.0
    )
    assert n_used == n
    assert abs(partial_ic) < 0.1  # shared-variance-only signal removed
    assert p_value > 0.05  # not significant once z is controlled for


def test_partial_spearman_ic_preserves_genuine_incremental_signal():
    """x and y share BOTH a common control z AND an independent signal s -- partial IC
    controlling for z alone should still detect the s-driven correlation."""
    rng = np.random.default_rng(7)
    n = 2000
    z = rng.normal(size=n)
    s = rng.normal(size=n)
    x = z + 0.8 * s + rng.normal(scale=0.1, size=n)
    y = z + 0.8 * s + rng.normal(scale=0.1, size=n)

    partial_ic, p_value, n_used = partial_spearman_ic(
        x, y, z.reshape(-1, 1), condition_max=1000.0
    )
    assert partial_ic > 0.5  # incremental signal from s survives controlling for z
    assert p_value < 0.001


def test_partial_spearman_ic_two_controls():
    """Exactly the shape every Renaissance interaction primitive has: 2 parent atomics.
    x is a genuine product-interaction of z1, z2 plus real incremental signal s;
    y shares only s incrementally beyond z1/z2."""
    rng = np.random.default_rng(11)
    n = 3000
    z1 = rng.normal(size=n)
    z2 = rng.normal(size=n)
    s = rng.normal(size=n)
    x = z1 + z2 + 0.6 * s + rng.normal(scale=0.1, size=n)
    y = z1 - 0.5 * z2 + 0.6 * s + rng.normal(scale=0.1, size=n)

    controls = np.column_stack([z1, z2])
    partial_ic, p_value, n_used = partial_spearman_ic(x, y, controls, condition_max=1000.0)
    assert n_used == n
    assert partial_ic > 0.3
    assert p_value < 0.01


def test_partial_spearman_ic_insufficient_n_returns_nan():
    rng = np.random.default_rng(1)
    n = 4  # k=1 control -> needs n >= k+4=5
    x = rng.normal(size=n)
    y = rng.normal(size=n)
    z = rng.normal(size=n)
    partial_ic, p_value, n_used = partial_spearman_ic(
        x, y, z.reshape(-1, 1), condition_max=1000.0
    )
    assert np.isnan(partial_ic)
    assert np.isnan(p_value)
    assert n_used == n


def test_partial_spearman_ic_ill_conditioned_controls_returns_nan():
    """Two near-duplicate control columns -> design matrix condition number blows up ->
    must return NaN rather than a numerically unstable partial correlation."""
    rng = np.random.default_rng(3)
    n = 500
    z1 = rng.normal(size=n)
    z2 = z1 + rng.normal(scale=1e-8, size=n)  # near-duplicate of z1
    x = rng.normal(size=n)
    y = rng.normal(size=n)
    controls = np.column_stack([z1, z2])
    partial_ic, p_value, n_used = partial_spearman_ic(x, y, controls, condition_max=1000.0)
    assert np.isnan(partial_ic)
    assert np.isnan(p_value)
    assert n_used == n
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ic_math.py -k partial_spearman -v`
Expected: FAIL with `ImportError: cannot import name 'partial_spearman_ic'`

- [ ] **Step 3: Implement `partial_spearman_ic()`**

Add to `src/intelligence/statistics/ic_math.py`, after `apply_bh_fdr` (before the `IC Sharpe computation` section):

```python
# ---------------------------------------------------------------------------
# Partial (residual) Spearman IC -- todo 037 interaction primitives pilot
# ---------------------------------------------------------------------------


def partial_spearman_ic(
    x: np.ndarray,
    y: np.ndarray,
    controls: np.ndarray,
    condition_max: float,
) -> tuple[float, float, int]:
    """Partial Spearman IC of x vs y, controlling for one or more control variables.

    Residual method: rank-transform x, y, and each control column; regress ranks_x
    and ranks_y on [1, ranks_controls] via OLS; the partial IC is the Pearson
    correlation of the two residual vectors. Equivalent to the classic single-control
    partial-correlation formula and generalizes cleanly to k>1 controls -- every
    Renaissance interaction primitive has exactly 2 parent atomics (feature_registry
    .parent_features), so k=2 is the pilot's actual shape.

    p-value uses the same t-approximation as _p_values_from_ic, with degrees of
    freedom reduced by k (one parameter fit per control, beyond the intercept):
    df = n - k - 2.

    Guards against multicollinear control sets the same way ops_ensemble_weight_
    compare.py's mean-variance path guards mv_condition_max -- an ill-conditioned
    design matrix produces numerically unstable residuals, not a genuine partial
    correlation, so this returns NaN rather than a garbage number.

    Returns (partial_ic, p_value, n) as (nan, nan, n) when n is too small for the
    adjusted df (n < k + 4), or when the control design matrix's condition number
    exceeds condition_max (see alpha.ic.partial_control_condition_max).
    """
    n = len(x)
    if controls.ndim == 1:
        controls = controls.reshape(-1, 1)
    k = controls.shape[1]
    if n < k + 4:
        return float("nan"), float("nan"), n

    design = np.column_stack([np.ones(n), rankdata(controls, axis=0)])
    cond = np.linalg.cond(design)
    if not np.isfinite(cond) or cond > condition_max:
        return float("nan"), float("nan"), n

    ranks_x = rankdata(x)
    ranks_y = rankdata(y)
    coef_x, _, _, _ = np.linalg.lstsq(design, ranks_x, rcond=None)
    coef_y, _, _, _ = np.linalg.lstsq(design, ranks_y, rcond=None)
    resid_x = ranks_x - design @ coef_x
    resid_y = ranks_y - design @ coef_y

    denom = np.sqrt((resid_x**2).sum() * (resid_y**2).sum())
    if denom < 1e-10:
        return 0.0, 1.0, n
    partial_ic = float((resid_x * resid_y).sum() / denom)

    df = n - k - 2
    if df < 1:
        return partial_ic, float("nan"), n
    t_stat = partial_ic * np.sqrt(df / max(1 - partial_ic**2, 1e-10))
    p_value = float(2.0 * (1.0 - t_dist.cdf(abs(t_stat), df=df)))
    return partial_ic, p_value, n
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ic_math.py -k partial_spearman -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/statistics/ic_math.py tests/unit/test_ensemble_ic_math.py
git commit -m "feat(ic-math): add partial_spearman_ic for todo 037 interaction primitives pilot"
```

---

### Task 2: Migration -- new `feature_ic_scores` columns + 2 APR keys

**Files:**
- Create: `production/migrations/214_partial_ic_interaction_primitives.sql`

**Interfaces:**
- Produces: `feature_ic_scores.partial_ic`, `.partial_ic_p_value`, `.partial_ic_n`, `.passes_partial_fdr` (all nullable, populated only for interaction-tier features); APR keys `alpha.ic.partial_fdr_alpha` (default 0.05), `alpha.ic.partial_control_condition_max` (default 1000.0).

- [ ] **Step 1: Check for migration number collisions before creating the file**

Run: `ls production/migrations/ | sort -t_ -k1 -n | tail -3`
Expected: highest existing is `213_ensemble_compare_fdr_alpha.sql`. If a `214_*.sql` file now exists (claimed by a concurrent session, e.g. the in-flight Phase 142B `alpha_frames` schema work), use `215` instead and rename throughout this task.

- [ ] **Step 2: Write the migration**

```sql
-- Migration 214: partial-IC columns on feature_ic_scores + APR keys for todo 037
-- (Interaction Primitives pilot).
--
-- Adds nullable partial_ic/partial_ic_p_value/partial_ic_n/passes_partial_fdr columns,
-- populated only for tier='1_interaction' features (feature_registry) by
-- scripts/ops/alpha/ops_interaction_primitives_pilot.py. NULL for every tier='0_atomic'
-- row -- naive IC there is the only meaningful measurement, there is no "parent" to
-- control for.
--
-- Two dedicated APR keys, each a distinct test/tuning family from every existing key
-- (same reasoning as migration 213's alpha.ensemble.compare_fdr_alpha: coupling
-- unrelated multiplicity budgets or numerical-stability caps to an existing key would
-- be an APR-mandate violation in spirit, not just letter):
--   alpha.ic.partial_fdr_alpha              -- BH-FDR alpha for the small
--                                               partial-IC family (~8 features x a
--                                               handful of tf/lookahead cells each),
--                                               separate from alpha.ic.fdr_alpha's
--                                               516K-hypothesis corpus-wide family.
--   alpha.ic.partial_control_condition_max  -- design-matrix condition-number ceiling
--                                               for partial_spearman_ic's ill-
--                                               conditioning guard. Seeded to 1000.0,
--                                               matching the E2 mean-variance path's
--                                               mv_condition_max precedent
--                                               (services/ensemble_ic_engine.py).
--
-- [initial_estimate] Not an ML learning target.

BEGIN;

ALTER TABLE feature_ic_scores ADD COLUMN IF NOT EXISTS partial_ic double precision;
ALTER TABLE feature_ic_scores ADD COLUMN IF NOT EXISTS partial_ic_p_value double precision;
ALTER TABLE feature_ic_scores ADD COLUMN IF NOT EXISTS partial_ic_n integer;
ALTER TABLE feature_ic_scores ADD COLUMN IF NOT EXISTS passes_partial_fdr boolean;

COMMENT ON COLUMN feature_ic_scores.partial_ic IS
    'Partial Spearman IC controlling for the feature''s parent atomics (feature_registry.parent_features). NULL for tier=0_atomic features. Populated by ops_interaction_primitives_pilot.py (todo 037).';
COMMENT ON COLUMN feature_ic_scores.partial_ic_p_value IS
    'p-value for partial_ic, t-approximation with df = n - k - 2 (k = number of parent controls).';
COMMENT ON COLUMN feature_ic_scores.partial_ic_n IS
    'Observation count used for partial_ic (post-subsampling, post-embargo).';
COMMENT ON COLUMN feature_ic_scores.passes_partial_fdr IS
    'BH-FDR pass/fail for partial_ic_p_value within the interaction-primitive family (alpha.ic.partial_fdr_alpha), corrected separately from the corpus-wide atomic-feature FDR family.';

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'alpha.ic.partial_fdr_alpha',
    'float',
    '0.05',
    0.001, 0.20,
    '[initial_estimate] Benjamini-Hochberg FDR correction alpha for the interaction-'
    'primitive partial-IC family (todo 037). Same conventional 5% as alpha.ic.fdr_alpha '
    '(migration 161) but a dedicated key: this family is ~8 features x a handful of '
    '(tf, lookahead) cells, a different multiplicity budget than the 516K-hypothesis '
    'corpus-wide atomic-feature FDR pass. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ic.partial_fdr_alpha', '0.05', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.ic.partial_fdr_alpha', 1, '0.05', 'migration_214',
    'Initial seed: same conventional 5% as alpha.ic.fdr_alpha [initial_estimate]'
);

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'alpha.ic.partial_control_condition_max',
    'float',
    '1000.0',
    10.0, 100000.0,
    '[initial_estimate] Condition-number ceiling for partial_spearman_ic''s control-'
    'design-matrix ill-conditioning guard (todo 037). Above this, the control set is '
    'too collinear for a numerically stable partial correlation and partial_ic is '
    'returned as NULL rather than a garbage number. Seeded to match the E2 mean-'
    'variance path''s mv_condition_max precedent (services/ensemble_ic_engine.py). '
    'Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ic.partial_control_condition_max', '1000.0', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.ic.partial_control_condition_max', 1, '1000.0', 'migration_214',
    'Initial seed: matches ensemble_ic_engine.py mv_condition_max precedent [initial_estimate]'
);

COMMIT;
```

- [ ] **Step 3: Apply the migration**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/214_partial_ic_interaction_primitives.sql`
Expected: `ALTER TABLE` x4, `COMMENT` x4, `INSERT 0 1` (or `INSERT 0 0` if already applied) x6, `COMMIT`.

- [ ] **Step 4: Verify columns and APR keys landed**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d feature_ic_scores" | grep partial`
Expected: 4 rows (`partial_ic`, `partial_ic_p_value`, `partial_ic_n`, `passes_partial_fdr`).

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.ic.partial%'"`
Expected: 2 rows.

- [ ] **Step 5: Commit**

```bash
git add production/migrations/214_partial_ic_interaction_primitives.sql
git commit -m "feat(migration): add partial_ic columns and APR keys for todo 037 pilot"
```

---

### Task 3: `ops_interaction_primitives_pilot.py`

**Files:**
- Create: `scripts/ops/alpha/ops_interaction_primitives_pilot.py`

**Interfaces:**
- Consumes: `partial_spearman_ic(x, y, controls, condition_max)` from Task 1; `apply_bh_fdr(p_values, alpha)` from `src/intelligence/statistics/ic_math.py` (already exists).
- Produces: a runnable script, `main() -> int` (always returns 0, informational report -- same convention as `ops_ensemble_weight_compare.py`).

- [ ] **Step 1: Write the script**

```python
#!/usr/bin/env python3
"""
ops_interaction_primitives_pilot.py -- todo 037 partial-IC pilot.

Answers: do the 8 already-live Renaissance interaction primitives
(feature_registry.tier='1_interaction') carry genuine incremental IC after
controlling for their parent atomics, or is their naive IC fully explained by the
parents? Reuses already-measured pooled-aggregate feature_ic_scores rows
(is_pooled=true, regime='_pooled', symbol='POOLED' -- the highest-power
cross-sectional population, see project memory's EIC-04 diagnosis) as the input
population, rather than re-deriving IC from scratch.

Pilot-scoped approximation (see docs/plans/2026-07-09-interaction-primitives-
partial-ic-pilot-plan.md "Global Constraints"): subsampling reuses ic_engine.py's
stride formula (max(subsample_min_stride, lookahead_bars)) applied positionally
within each symbol's row block before pooling across symbols -- a faithful analog
of, not a byte-identical replay of, ic_engine.py's own chunk-internal subsampling.
This is a decision-gate measurement, not a promotion-grade one.

Decision rule (todo 037): genuine incremental IC (passes_partial_fdr=true) for a
meaningful fraction of the 8-feature cohort -> trigger to plan the full Interaction
Factory. Near-zero -> shelve Interaction Factory outright.

Usage:
    python scripts/ops/alpha/ops_interaction_primitives_pilot.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg
import numpy as np

from src.config.settings import Settings
from src.intelligence.statistics.ic_math import apply_bh_fdr, partial_spearman_ic

_SCALES = ("fast", "mid", "slow", "extended")


async def _load_interaction_features(conn: asyncpg.Connection) -> list[dict]:
    """tier='1_interaction' rows from feature_registry with their parent atomics."""
    rows = await conn.fetch(
        "SELECT feature_name, parent_features FROM feature_registry "
        "WHERE tier = '1_interaction' AND status = 'active' "
        "ORDER BY feature_name"
    )
    return [{"feature_name": r["feature_name"], "parents": list(r["parent_features"])} for r in rows]


async def _load_pooled_cells(conn: asyncpg.Connection, feature_names: list[str]) -> list[dict]:
    """Already-measured pooled-aggregate cells (symbol='POOLED', is_pooled=true,
    regime='_pooled') for the given features -- the highest-power population, and
    the same one used for the EIC-04 sparse-signal cross-check."""
    rows = await conn.fetch(
        "SELECT feature_name, tf, lookahead_bars, training_window_end, n_independent "
        "FROM feature_ic_scores "
        "WHERE feature_name = ANY($1::text[]) "
        "  AND symbol = 'POOLED' AND is_pooled = true AND regime = '_pooled' "
        "  AND reliable = true "
        "ORDER BY feature_name, tf, lookahead_bars",
        feature_names,
    )
    return [dict(r) for r in rows]


def _scale_stride(lookahead_bars: int, subsample_min_stride: int) -> int:
    return max(subsample_min_stride, lookahead_bars)


async def _fetch_cell_arrays(
    conn: asyncpg.Connection,
    feature_name: str,
    parents: list[str],
    tf: str,
    lookahead_bars: int,
    training_window_end,
    subsample_min_stride: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """Stream (feature, parent_1, parent_2, return) rows across all symbols for one
    (feature, tf, lookahead) pooled cell, subsampling positionally within each
    symbol's row block, then pooling across symbols.

    Named server-side cursor + itersize batching -- the same OOM-avoidance shape as
    migrations 183/209/212 (see CLAUDE.md "ProcessPoolExecutor workers are compute-
    only" gotcha and its three prior sibling fixes). This pooled cell can be up to
    ~1.5M raw rows before subsampling.
    """
    scale = _SCALES[["fast", "mid", "slow", "extended"].index(
        next(s for s in _SCALES if True)
    )] if False else None  # placeholder removed below -- see Step 1 self-review note
    lookaheads_by_bars = {}  # populated by caller; see main()
    del scale, lookaheads_by_bars  # unused, silence linters -- replaced in main() call site

    parent_1, parent_2 = parents[0], parents[1]
    stride = _scale_stride(lookahead_bars, subsample_min_stride)
    complete_col = f"complete_{_lookahead_to_scale(lookahead_bars)}"
    return_col = f"return_{_lookahead_to_scale(lookahead_bars)}"

    sql = f"""
        SELECT fv.symbol, fv.bar_ts, fv.{feature_name} AS x,
               fv.{parent_1} AS z1, fv.{parent_2} AS z2,
               fr.{return_col} AS y
        FROM feature_vectors fv
        INNER JOIN forward_returns fr
            ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
            AND fr.return_type = 'executable_open_to_open'
        WHERE fv.tf = $1 AND fv.bar_ts <= $2 AND fr.{complete_col} = true
          AND fv.{feature_name} IS NOT NULL AND fv.{parent_1} IS NOT NULL AND fv.{parent_2} IS NOT NULL
        ORDER BY fv.symbol, fv.bar_ts
    """
    x_by_symbol: dict[str, list[float]] = {}
    z1_by_symbol: dict[str, list[float]] = {}
    z2_by_symbol: dict[str, list[float]] = {}
    y_by_symbol: dict[str, list[float]] = {}

    async with conn.transaction():
        async for record in conn.cursor(sql, tf, training_window_end, prefetch=5000):
            sym = record["symbol"]
            x_by_symbol.setdefault(sym, []).append(record["x"])
            z1_by_symbol.setdefault(sym, []).append(record["z1"])
            z2_by_symbol.setdefault(sym, []).append(record["z2"])
            y_by_symbol.setdefault(sym, []).append(record["y"])

    x_parts, z1_parts, z2_parts, y_parts = [], [], [], []
    for sym in x_by_symbol:
        idx = np.arange(0, len(x_by_symbol[sym]), stride)
        x_parts.append(np.asarray(x_by_symbol[sym])[idx])
        z1_parts.append(np.asarray(z1_by_symbol[sym])[idx])
        z2_parts.append(np.asarray(z2_by_symbol[sym])[idx])
        y_parts.append(np.asarray(y_by_symbol[sym])[idx])

    if not x_parts:
        return np.array([]), np.array([]), np.array([]), 0
    x = np.concatenate(x_parts)
    controls = np.column_stack([np.concatenate(z1_parts), np.concatenate(z2_parts)])
    y = np.concatenate(y_parts)
    return x, controls, y, len(x)


_LOOKAHEAD_TO_SCALE_CACHE: dict[int, str] = {}


def _lookahead_to_scale(lookahead_bars: int) -> str:
    """Map a lookahead_bars int back to its scale name (fast/mid/slow/extended) via
    the cached APR values loaded once in main(). Populated by _init_lookahead_map()."""
    if lookahead_bars not in _LOOKAHEAD_TO_SCALE_CACHE:
        raise KeyError(
            f"lookahead_bars={lookahead_bars} not in the loaded APR lookahead map -- "
            "call _init_lookahead_map() before any cell processing."
        )
    return _LOOKAHEAD_TO_SCALE_CACHE[lookahead_bars]


async def _init_lookahead_map(conn: asyncpg.Connection) -> None:
    for scale in _SCALES:
        val = await conn.fetchval(
            "SELECT config_value FROM config_state WHERE config_key = $1",
            f"alpha.ic.lookahead.{scale}",
        )
        default = {"fast": 1, "mid": 5, "slow": 20, "extended": 60}[scale]
        _LOOKAHEAD_TO_SCALE_CACHE[int(val) if val is not None else default] = scale


async def main() -> int:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        async with pool.acquire() as conn:
            await _init_lookahead_map(conn)

            subsample_min_stride_raw = await conn.fetchval(
                "SELECT config_value FROM config_state WHERE config_key = 'alpha.ic.subsample_min_stride'"
            )
            subsample_min_stride = int(subsample_min_stride_raw) if subsample_min_stride_raw else 5

            condition_max_raw = await conn.fetchval(
                "SELECT config_value FROM config_state WHERE config_key = 'alpha.ic.partial_control_condition_max'"
            )
            if condition_max_raw is None:
                print(
                    "## Todo 037 Interaction Primitives Pilot\n\nFAILED: "
                    "alpha.ic.partial_control_condition_max missing -- run migration 214 first."
                )
                return 0
            condition_max = float(condition_max_raw)

            partial_fdr_alpha_raw = await conn.fetchval(
                "SELECT config_value FROM config_state WHERE config_key = 'alpha.ic.partial_fdr_alpha'"
            )
            if partial_fdr_alpha_raw is None:
                print(
                    "## Todo 037 Interaction Primitives Pilot\n\nFAILED: "
                    "alpha.ic.partial_fdr_alpha missing -- run migration 214 first."
                )
                return 0
            partial_fdr_alpha = float(partial_fdr_alpha_raw)

            features = await _load_interaction_features(conn)
            if not features:
                print(
                    "## Todo 037 Interaction Primitives Pilot\n\nFAILED: no "
                    "tier='1_interaction' rows found in feature_registry."
                )
                return 0
            feature_names = [f["feature_name"] for f in features]
            parents_by_feature = {f["feature_name"]: f["parents"] for f in features}

            cells = await _load_pooled_cells(conn, feature_names)
            if not cells:
                print(
                    "## Todo 037 Interaction Primitives Pilot\n\nFAILED: no reliable "
                    "pooled (symbol='POOLED', regime='_pooled') feature_ic_scores rows "
                    "found for the interaction-primitive cohort -- run ic_engine.py first."
                )
                return 0

            results = []
            for cell in cells:
                fname = cell["feature_name"]
                parents = parents_by_feature[fname]
                try:
                    x, controls, y, n = await _fetch_cell_arrays(
                        conn,
                        fname,
                        parents,
                        cell["tf"],
                        cell["lookahead_bars"],
                        cell["training_window_end"],
                        subsample_min_stride,
                    )
                except Exception as error:  # CLAUDE.md: exception variable name is `error`
                    print(f"  SKIP {fname}/{cell['tf']}/{cell['lookahead_bars']}: {error}")
                    continue

                if n < 10:
                    continue
                partial_ic, p_value, n_used = partial_spearman_ic(
                    x, y, controls, condition_max=condition_max
                )
                results.append(
                    {
                        "feature_name": fname,
                        "tf": cell["tf"],
                        "lookahead_bars": cell["lookahead_bars"],
                        "training_window_end": cell["training_window_end"],
                        "partial_ic": partial_ic,
                        "partial_ic_p_value": p_value,
                        "partial_ic_n": n_used,
                    }
                )

            valid = [r for r in results if not np.isnan(r["partial_ic_p_value"])]
            if valid:
                p_values = [r["partial_ic_p_value"] for r in valid]
                reject, p_corrected = apply_bh_fdr(p_values, partial_fdr_alpha)
                for r, rej, p_corr in zip(valid, reject, p_corrected, strict=True):
                    r["passes_partial_fdr"] = bool(rej)
                    r["partial_ic_p_corrected"] = float(p_corr)

            async with conn.transaction():
                for r in results:
                    await conn.execute(
                        "UPDATE feature_ic_scores SET partial_ic = $1, partial_ic_p_value = $2, "
                        "partial_ic_n = $3, passes_partial_fdr = $4 "
                        "WHERE feature_name = $5 AND tf = $6 AND lookahead_bars = $7 "
                        "AND training_window_end = $8 AND symbol = 'POOLED' "
                        "AND is_pooled = true AND regime = '_pooled'",
                        r["partial_ic"],
                        r["partial_ic_p_value"],
                        r["partial_ic_n"],
                        r.get("passes_partial_fdr"),
                        r["feature_name"],
                        r["tf"],
                        r["lookahead_bars"],
                        r["training_window_end"],
                    )

        n_measured = len(results)
        n_valid = len(valid)
        n_pass = sum(1 for r in valid if r.get("passes_partial_fdr"))
        frac_pass = (n_pass / n_valid) if n_valid else 0.0

        print("## Todo 037 Interaction Primitives Pilot")
        print()
        print(f"Cells measured: {n_measured} (numerically valid: {n_valid})")
        print(f"Cells passing partial-IC BH-FDR (alpha={partial_fdr_alpha}): {n_pass}/{n_valid} ({frac_pass:.1%})")
        print()
        for r in sorted(valid, key=lambda r: (r["feature_name"], r["tf"], r["lookahead_bars"])):
            verdict = "PASS" if r.get("passes_partial_fdr") else "fail"
            print(
                f"  {verdict:5s} {r['feature_name']:22s} tf={r['tf']:5s} "
                f"lookahead={r['lookahead_bars']:3d} partial_ic={r['partial_ic']:+.4f} "
                f"p_corrected={r['partial_ic_p_corrected']:.4f} n={r['partial_ic_n']}"
            )
        print()
        print("Decision rule (todo 037): a meaningful fraction of the cohort with genuine ")
        print("incremental IC surviving FDR -> plan the full Interaction Factory. ")
        print("Near-zero -> shelve Interaction Factory outright.")
        print(f"-> Observed: {frac_pass:.1%} of numerically valid cells pass.")
    finally:
        await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Self-review pass -- remove the placeholder in `_fetch_cell_arrays`**

The `scale = ...` line at the top of `_fetch_cell_arrays` in Step 1 is dead placeholder code left over from drafting (violates "No Placeholders"). Remove it -- `_lookahead_to_scale()` is already called directly where needed (`complete_col`/`return_col` construction). Edit the function to delete these two lines:

```python
    scale = _SCALES[["fast", "mid", "slow", "extended"].index(
        next(s for s in _SCALES if True)
    )] if False else None  # placeholder removed below -- see Step 1 self-review note
    lookaheads_by_bars = {}  # populated by caller; see main()
    del scale, lookaheads_by_bars  # unused, silence linters -- replaced in main() call site
```

Run: `.venv/bin/ruff check scripts/ops/alpha/ops_interaction_primitives_pilot.py --fix`
Expected: no remaining warnings about unused variables.

- [ ] **Step 3: Manual dry-run against the live DB (read-only check first)**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT feature_name, tf, lookahead_bars, n_independent FROM feature_ic_scores WHERE feature_name IN ('vol_body_product','ret_vol_product_fast','price_vol_corr_fast','price_vol_corr_slow','range_vol_product','up_vol_body_diff','ret_vol_ratio_fast','vol_skew_product') AND symbol='POOLED' AND is_pooled=true AND regime='_pooled' AND reliable=true ORDER BY feature_name, tf, lookahead_bars;"`
Expected: a non-empty result set -- confirms Task 3's `_load_pooled_cells()` query will find real rows before running the full script. If empty, STOP and investigate why (e.g. the corpus's cross-sectional pooled pass may not have run for these 8 features specifically) before proceeding to Task 5.

- [ ] **Step 4: Commit**

```bash
git add scripts/ops/alpha/ops_interaction_primitives_pilot.py
git commit -m "feat(alpha): add todo 037 interaction primitives partial-IC pilot script"
```

---

### Task 4: Unit tests for the script's pure logic

**Files:**
- Create: `tests/unit/test_interaction_primitives_pilot.py`

**Interfaces:**
- Consumes: `_scale_stride`, `_lookahead_to_scale`, `_init_lookahead_map` (module-private, imported directly for testing -- same convention as `test_ensemble_ic_math.py` importing underscore-prefixed functions).

- [ ] **Step 1: Write the tests**

```python
"""Unit tests: pure-logic helpers in ops_interaction_primitives_pilot.py.

No DB, no Kafka -- these test the stride/lookahead-mapping logic only. The script's
DB-facing functions (_load_interaction_features, _load_pooled_cells,
_fetch_cell_arrays, main) are integration-tested manually per the plan's Task 3
Step 3 dry-run, not unit-tested here, matching this codebase's existing convention
of keeping DB-free unit tests DB-free (see ic_math.py's own module docstring).
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root / "scripts" / "ops" / "alpha"))

from ops_interaction_primitives_pilot import (
    _LOOKAHEAD_TO_SCALE_CACHE,
    _lookahead_to_scale,
    _scale_stride,
)


def test_scale_stride_uses_floor_when_lookahead_below_min():
    assert _scale_stride(lookahead_bars=1, subsample_min_stride=5) == 5


def test_scale_stride_uses_lookahead_when_above_min():
    assert _scale_stride(lookahead_bars=60, subsample_min_stride=5) == 60


def test_lookahead_to_scale_raises_before_init():
    _LOOKAHEAD_TO_SCALE_CACHE.clear()
    try:
        _lookahead_to_scale(999)
        raise AssertionError("expected KeyError for unmapped lookahead_bars")
    except KeyError:
        pass


def test_lookahead_to_scale_resolves_after_populated():
    _LOOKAHEAD_TO_SCALE_CACHE.clear()
    _LOOKAHEAD_TO_SCALE_CACHE[1] = "fast"
    _LOOKAHEAD_TO_SCALE_CACHE[60] = "extended"
    assert _lookahead_to_scale(1) == "fast"
    assert _lookahead_to_scale(60) == "extended"
    _LOOKAHEAD_TO_SCALE_CACHE.clear()
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_interaction_primitives_pilot.py -v`
Expected: 4 passed

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_interaction_primitives_pilot.py
git commit -m "test(alpha): add unit tests for interaction primitives pilot helpers"
```

---

### Task 5: Run the pilot, record the verdict, close the loop

**Files:**
- Modify: `.planning/todos/pending/037-interaction-primitives-pilot-ic-test.md` (moves to `completed/` or gets requeued as a concrete next-step todo, depending on the result)
- Modify: `docs/research/2026-07-08-intelligence-lifecycle-backlog-matrix.md` ("Recently shipped" section)

- [ ] **Step 1: Run the full test suite to confirm no regressions**

Run: `.venv/bin/pytest tests/unit/ -q`
Expected: same pass/fail count as the pre-existing baseline (5569 passed, 22 pre-existing failures per project memory) plus the new tests from Tasks 1 and 4, zero new failures.

- [ ] **Step 2: Run the pilot script against the live corpus**

Run: `python scripts/ops/alpha/ops_interaction_primitives_pilot.py`
Expected: a report block ending in the decision-rule verdict line. Record the exact `frac_pass` and per-cell table.

- [ ] **Step 3: Apply the decision rule and update todo 037**

If a meaningful fraction (judgment call, but the todo's own council review estimated "single digits to low tens of survivors" as the expected honest yield if real) of cells pass `passes_partial_fdr`: update `037-interaction-primitives-pilot-ic-test.md` with the empirical result, mark it as the trigger to plan Phase 150's Interaction Factory (do NOT auto-create the phase -- that's a `/gsd-discuss-phase` decision), move to `completed/`.

If near-zero cells pass: update the todo with the empirical result, state explicitly "Interaction Factory shelved, not deferred -- per the pre-registered decision rule," move to `completed/`.

Either way, write the exact observed numbers (cells measured, `frac_pass`, worst/best individual `partial_ic` values) into the todo file -- this is the actual deliverable, not just "ran the pilot."

- [ ] **Step 4: Update the priority matrix's "Recently shipped" section**

Add one line to `docs/research/2026-07-08-intelligence-lifecycle-backlog-matrix.md`'s "Recently shipped" list (same section edited 2026-07-09 for the E1/E2 judgment and EIC-04 re-run): `**Todo 037 pilot (2026-07-09):** [PASS/SHELVE] -- <frac_pass> of interaction-primitive cells carried genuine incremental IC after controlling for parent atomics.` Remove todo 037 from the "Todos" table in the HIGH tier (it's done, not pending).

- [ ] **Step 5: Final commit**

```bash
git add .planning/todos/completed/037-interaction-primitives-pilot-ic-test.md docs/research/2026-07-08-intelligence-lifecycle-backlog-matrix.md
git commit -m "docs(todo-037): record interaction primitives partial-IC pilot result"
```

(If `037-...md` was moved via `git mv` in Step 3, that move is already staged -- just add the matrix file and commit together.)

---

## Self-Review

**Spec coverage:** Todo 037's 3 "What" steps map to: step 1 (add columns) is already done (8/11 live per research) -- explicitly out of scope, noted in the plan header; step 2 (run through IC Engine) is satisfied by reusing already-measured `feature_ic_scores` pooled rows as the input population (Task 3); step 3 (partial correlation controlling for parents) is Task 1 + Task 3's core measurement. The "Decision rule" is Task 5. The 3 deferred `ret_div_*` cross-TF primitives (todo 066) are explicitly out of scope for this plan -- a separate todo, not silently dropped.

**Placeholder scan:** Task 3 Step 1's draft contains one intentional placeholder (the dead `scale = ...` lines) that Step 2 explicitly removes as a self-review step -- this is flagged inline rather than hidden, and Step 2 gives the exact deletion. No other TBD/"add error handling"-style placeholders present.

**Type consistency:** `partial_spearman_ic(x, y, controls, condition_max) -> tuple[float, float, int]` is used identically in Task 1's tests and Task 3's script. `_scale_stride(lookahead_bars, subsample_min_stride) -> int` and `_lookahead_to_scale(lookahead_bars) -> str` signatures match between Task 3's implementation and Task 4's tests.
