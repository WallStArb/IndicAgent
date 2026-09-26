# Phase 175: ITR materiality-filtered empirical tags for breadth/peer-grouping - Pattern Map

**Mapped:** 2026-09-18
**Files analyzed:** 6 (1 modified service, 1 possibly-extended statistics module, 1 migration, 1 new script, 2 test files)
**Analogs found:** 6 / 6 (all files have a strong same-repo analog — this phase is additive work on an existing, fully-precedented subsystem)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/tag_calibrator.py` (MODIFY — add Pass 4) | service (batch compute, `BaseBatch` oneshot) | batch / CRUD (measure → decide → upsert) | itself — Pass 1-3 in the same file (`measure_matrix`/`apply_run_level_fdr`/`decide_outcome`/`_apply_decision`) | exact (self-extension, same file, same 3-pass shape) |
| `src/intelligence/statistics/factor_math.py` (MODIFY — possible new Pearson-convention partial-loading sibling) | utility (pure statistics kernel) | transform | `src/intelligence/statistics/ic_math.py::partial_spearman_ic` (lines 703-776) | exact (residualize-then-correlate shape to mirror, on raw returns instead of ranks) |
| `production/migrations/346_itr_materiality_evidence_columns.sql` (NEW) | migration | batch / DDL | `production/migrations/230_tag_calibrator_measurement_contract.sql` (schema columns) + `production/migrations/342_universe_pilot_sample_size_apr_key.sql` (APR-key seeding) + `production/migrations/343_itr_measurement_gap_fixes.sql` (idempotent UPDATE style) | exact |
| `scripts/analysis/itr_materiality_shadow_diagnostic.py` (NEW) | utility (offline read-only diagnostic script) | batch / transform (read → compare → report, no writes) | `scripts/analysis/tsmom_per_symbol_ic_screen.py` | exact (same role: read-only offline analysis script with a null-arm section, DB via `services.backfill_feature_factory._connect_db`) |
| `tests/unit/test_tag_calibrator.py` (MODIFY — extend with Pass 4 tests) | test | request-response (pure function → assertion) | itself — existing test functions in the same file | exact |
| `tests/unit/test_itr_materiality_shadow_diagnostic.py` (NEW, if diagnostic logic is substantial) | test | request-response | `tests/unit/test_tag_calibrator.py` (pure-function, no-DB test style) | role-match |

## Pattern Assignments

### `services/tag_calibrator.py` — Pass 4 addition

**Analog:** the file's own Pass 1-3 (`services/tag_calibrator.py:432-729`), since D-01 explicitly requires the new pass to live here, not in a new file.

**Imports pattern** (lines 42-72 — what Pass 4's new imports must match):
```python
from __future__ import annotations

import asyncio
import dataclasses
import math
from datetime import UTC, datetime
from typing import Any

import asyncpg
import numpy as np
import pandas as pd
import structlog

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async as _load_apr_dict
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.intelligence.statistics.factor_math import (
    loading_hac_pvalue,
    long_short_daily_returns,
    spy_realized_vol_factor,
    standardized_loading,
)
from src.intelligence.statistics.ic_math import apply_bh_fdr
from src.observability.metrics import counter
from src.observability.otel import OTelInitError, init_otel_providers
```
Pass 4 will add `check_condition_number` (already used transitively via `standardized_loading`, but needs a direct import if a new Pearson-partial-loading kernel is added to `factor_math.py`) and, if the null-arm stays inline rather than moving to the diagnostic script per Open Question 2, `from src.intelligence.statistics.ic_math import _circular_shift_null`.

**APR compile-time binding pattern** (lines 107-131 — `TagCalibratorConfig`/`from_apr`):
```python
@dataclasses.dataclass(frozen=True)
class TagCalibratorConfig:
    fdr_alpha: float
    expiry_consecutive_fails: int
    discovery_oos_days: int
    min_sample_n: int
    hac_max_lag: int
    half_life_min_days: int
    half_life_max_days: int

    @classmethod
    def from_apr(cls, cfg: dict[str, Any]) -> TagCalibratorConfig:
        return cls(
            fdr_alpha=_cfg(cfg, "alpha.tag_calibrator.fdr_alpha", 0.05),
            expiry_consecutive_fails=_cfg(cfg, "alpha.tag_calibrator.expiry_consecutive_fails", 3),
            discovery_oos_days=_cfg(cfg, "alpha.tag_calibrator.discovery_oos_days", 63),
            min_sample_n=_cfg(cfg, "alpha.tag_calibrator.min_sample_n", 60),
            hac_max_lag=_cfg(cfg, "alpha.tag_calibrator.hac_max_lag", 5),
            half_life_min_days=_cfg(cfg, "alpha.tag_calibrator.half_life_min_days", 30),
            half_life_max_days=_cfg(cfg, "alpha.tag_calibrator.half_life_max_days", 365),
        )
```
Pass 4 must add a **sibling frozen dataclass** (e.g. `MaterialityConfig`) or extend this one with 4-5 new fields (`min_partial_loading`, `min_sample_n` (distinct — Pitfall 2), `min_incremental_r2`, `min_sign_stable_windows`/`sign_stable_windows_total`, `null_arm_alpha`), each pulled from the new `alpha.tag_calibrator.materiality.*` namespace via the exact same `_cfg(cfg, key, default)` call shape — do not invent a second config-loading idiom.

**Core measurement (Pass 1) pattern to mirror for Pass 4** (lines 432-500, `measure_matrix`):
```python
def measure_matrix(
    active_symbols: list[str],
    measurable_rows: list[dict[str, Any]],
    price_cache: dict[str, pd.Series],
    config: TagCalibratorConfig,
    condition_max: float,
    realized_vol_window: int,
    vix_z_window: int,
) -> tuple[list[dict[str, Any]], int, int]:
    """Pass 1: measure the full instrument x measurable-tag matrix (F8).
    Returns (measured, n_self_regression_skipped, n_insufficient_data_skipped) --
    per-pair skip reasons are accumulated as counters, never logged per-row."""
    measured: list[dict[str, Any]] = []
    ...
    factor_series_cache = build_factor_series_cache(...)  # built ONCE, reused per pair
    for symbol in active_symbols:
        ...
        for tag_row in measurable_rows:
            ...
            result = _measure_pair(instrument_ret, factor_ret, extra_fitted_params, config, condition_max)
            if result is None:
                n_insufficient += 1
                continue
            measured.append({"symbol": symbol, "tag": tag_row["tag"], **result})
    return measured, n_self_regression, n_insufficient
```
A Pass 4 function (e.g. `measure_partial_loadings`) follows the identical shape: iterate the `measured` list already filtered to `keep=True` in `execute()`'s loop (not `measurable_rows` — Pass 4 only runs against pairs Pass 1-3 already decided to keep, per D-01 "for every KEPT empirical row"), build the control-factor return matrix **once** via `build_factor_series_cache(control_rows, price_cache, realized_vol_window, vix_z_window)` (reuse verbatim — do not write a second constructor, per RESEARCH.md Pattern 2/Don't-Hand-Roll), and accumulate skip-reason counters exactly the same way (never per-row logging).

**Decision/hysteresis pattern to reuse for `discovery_oos_days` enforcement (todo 125 fold-in)** (lines 576-596, `_next_evidence`):
```python
def _next_evidence(
    existing_row: dict[str, Any] | None,
    run_ts: datetime,
    discovery_oos_days: int,
    clamped_half_life: int,
) -> dict[str, Any]:
    prev_evidence = (existing_row or {}).get("evidence") or {}
    first_measured_at_raw = prev_evidence.get("first_measured_at")
    first_measured_at = (
        datetime.fromisoformat(first_measured_at_raw) if first_measured_at_raw else run_ts
    )
    elapsed_days = (run_ts - first_measured_at).days
    discovery_state = "confirmed" if elapsed_days >= discovery_oos_days else "pending_oos"
    return {
        "first_measured_at": first_measured_at.isoformat(),
        "discovery_state": discovery_state,
        "half_life_days": clamped_half_life,
    }
```
This is the exact "computed but never enforced" gap todo 125 flags. Per RESEARCH.md Pattern 4, promote `discovery_state`/`first_measured_at` to real `instrument_tags` columns (migration) and have `_apply_decision` (lines 638-729) write them directly in addition to the JSONB blob (keep the JSONB write for backward-compat unless a fresh `grep -rn "discovery_state" src/ services/` confirms no other reader exists). `passes_materiality` must be computed as `statistical_gate AND (discovery_state == 'confirmed')` — two independently AND-ed conditions (Pitfall 4), never merged into one boolean.

**Upsert/write pattern to extend** (lines 599-617, `_UPSERT_EMPIRICAL_SQL`):
```python
_UPSERT_EMPIRICAL_SQL = """
    INSERT INTO instrument_tags (
        symbol, tag, weight, source, evidence, assigned_at,
        loading, p_value, bh_adjusted_p, passes_fdr, consecutive_fails, sample_n,
        estimated_at, valid_from, valid_to
    ) VALUES ($1, $2, $3, 'empirical', $4, now(), $5, $6, $7, $8, 0, $9, $10, now(), NULL)
    ON CONFLICT (symbol, tag) DO UPDATE SET
        weight = EXCLUDED.weight, source = 'empirical', evidence = EXCLUDED.evidence,
        loading = EXCLUDED.loading, p_value = EXCLUDED.p_value,
        bh_adjusted_p = EXCLUDED.bh_adjusted_p, passes_fdr = EXCLUDED.passes_fdr,
        consecutive_fails = 0, sample_n = EXCLUDED.sample_n,
        estimated_at = EXCLUDED.estimated_at, valid_to = NULL
"""
```
Pass 4's evidence columns (`partial_loading`, `incremental_r2`, `sign_stable_windows`, `sign_stable_windows_total`, `null_arm_p_value`, `passes_materiality`, `discovery_state`, `first_measured_at`) get added to this same `INSERT ... ON CONFLICT DO UPDATE` statement (extend, do not fork a second UPSERT statement — Pass 4 writes happen unconditionally for every kept empirical row in the same `_apply_decision` write path, per D-01 "measurement, not an admission decision").

**`execute()` orchestration pattern** (lines 749-858): Pass 4 slots in after the existing `apply_run_level_fdr(measured, config.fdr_alpha)` call and before/alongside the per-pair `_apply_decision` loop — call it once over the full `measured` list (mirrors F1's "correct once" discipline extended to "measure Pass-4 evidence once per kept pair", not per-consumer).

---

### `src/intelligence/statistics/factor_math.py` (or `ic_math.py`) — Pearson-convention partial-loading kernel

**Analog:** `src/intelligence/statistics/ic_math.py::partial_spearman_ic` (lines 703-776, read in full above).

**Core pattern to adapt** (residualize-then-correlate, on **raw/centered** returns instead of **ranks** — Pitfall 1's explicit resolution if Pearson convention is chosen to match Pass 1's `standardized_loading`):
```python
# Source: src/intelligence/statistics/ic_math.py:703-776 (existing, full function read)
def partial_spearman_ic(
    x: np.ndarray, y: np.ndarray, controls: np.ndarray, condition_max: float,
) -> tuple[float, float, int]:
    n = len(x)
    if controls.ndim == 1:
        controls = controls.reshape(-1, 1)
    k = controls.shape[1]
    if n < k + 4:
        return float("nan"), float("nan"), n
    ranks_x = rankdata(x); ranks_y = rankdata(y); ranks_controls = rankdata(controls, axis=0)
    ranks_x_c = ranks_x - ranks_x.mean()
    ranks_y_c = ranks_y - ranks_y.mean()
    ranks_controls_c = ranks_controls - ranks_controls.mean(axis=0)
    cond_ok, _cond = check_condition_number(ranks_controls_c, condition_max)
    if not cond_ok:
        return float("nan"), float("nan"), n
    coefs, _, _, _ = np.linalg.lstsq(ranks_controls_c, np.column_stack([ranks_x_c, ranks_y_c]), rcond=None)
    resid_x = ranks_x_c - ranks_controls_c @ coefs[:, 0]
    resid_y = ranks_y_c - ranks_controls_c @ coefs[:, 1]
    denom = np.sqrt((resid_x**2).sum() * (resid_y**2).sum())
    if denom < 1e-10:
        return float("nan"), float("nan"), n
    partial_ic = float(_vectorized_ic(resid_x.reshape(-1, 1), resid_y)[0])
    df = n - k - 2
    if df < 1:
        return partial_ic, float("nan"), n
    p_value = float(_p_values_from_ic(np.array([partial_ic]), n, df=df)[0])
    return partial_ic, p_value, n
```
A Pearson sibling (proposed name `partial_loading` in `factor_math.py`, matching this module's existing public-surface convention of re-exporting only what `tag_calibrator.py` needs) skips the `rankdata()` calls and instead centers **raw standardized returns** directly — same `check_condition_number` gate, same shared-`lstsq` two-column-at-once trick, same `n < k + 4` floor. Reuse `check_condition_number` (imported from `ic_math.py`, already imported transitively by this module) and `_p_values_from_ic` (already imported at `factor_math.py:33-36`) verbatim — do not reimplement either.

**Ill-conditioning gate** (`ic_math.py:682-696`, `check_condition_number` — reuse verbatim, do not reimplement):
```python
def check_condition_number(matrix: np.ndarray, condition_max: float) -> tuple[bool, float]:
    cond = float(np.linalg.cond(matrix))
    return (np.isfinite(cond) and cond <= condition_max), cond
```

**Sign-stability-across-rolling-windows: NO existing analog** (Pitfall 3 — genuinely new code, no reuse target found anywhere in `ic_math.py`/`factor_math.py`/`scripts/analysis/`). Budget real implementation time; do not treat this as "call an existing function N times."

---

### `production/migrations/346_itr_materiality_evidence_columns.sql`

**Analog 1 — idempotent `ADD COLUMN IF NOT EXISTS` schema pattern:** `production/migrations/230_tag_calibrator_measurement_contract.sql:19-48`
```sql
BEGIN;
ALTER TABLE instrument_tags
    ADD COLUMN IF NOT EXISTS loading float,
    ADD COLUMN IF NOT EXISTS p_value float,
    ADD COLUMN IF NOT EXISTS bh_adjusted_p float,
    ADD COLUMN IF NOT EXISTS passes_fdr boolean,
    ADD COLUMN IF NOT EXISTS consecutive_fails int NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS sample_n int,
    ADD COLUMN IF NOT EXISTS estimated_at timestamptz,
    ADD COLUMN IF NOT EXISTS valid_from timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS valid_to timestamptz;
COMMIT;
```
Copy this shape exactly for the new columns (RESEARCH.md's proposed set): `partial_loading float`, `incremental_r2 float`, `sign_stable_windows int`, `sign_stable_windows_total int`, `null_arm_p_value float`, `passes_materiality boolean`, `discovery_state text CHECK (discovery_state IN ('pending_oos','confirmed'))`, `first_measured_at timestamptz`.

**Analog 2 — APR-key-seeding 3-table pattern:** `production/migrations/342_universe_pilot_sample_size_apr_key.sql` (full file, 43 lines) — `config_schema` INSERT with `[initial_estimate]` provenance tag + `min_value`/`max_value` CHECK bounds, `config_state` INSERT, both `ON CONFLICT (config_key) DO NOTHING`:
```sql
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.universe.pilot_sample_size', 'int', '40', 30, 50,
    '[initial_estimate] ... Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('alpha.universe.pilot_sample_size', '40', 1)
ON CONFLICT (config_key) DO NOTHING;
```
Migration 230's fuller 3-table version (`config_schema` + `config_state` + `config_history`, lines 138-213) is the pattern to follow if `config_history` provenance rows are also wanted for the new keys — repeat once per new `alpha.tag_calibrator.materiality.*` key: `min_partial_loading` (0.35), `min_sample_n` (756), `min_incremental_r2` (0.05), `min_sign_stable_windows` (3, out of `sign_stable_windows_total`=4), `null_arm_alpha` (reuse `fdr_alpha`=0.05 unless a dedicated key is clearer).

**Analog 3 — idempotent `UPDATE ... WHERE tag = ...` for any vocabulary wiring (e.g. a 5th DBC control leg, if needed per Open Question 3):** `production/migrations/343_itr_measurement_gap_fixes.sql:56-73` — every statement keyed on `tag` (primary key), safe to re-run.

**View pattern (todo 126 fold-in, `instrument_tags_active`):** RESEARCH.md Pattern 5 proposes, follow migration 230's idempotent style:
```sql
CREATE OR REPLACE VIEW instrument_tags_active AS
SELECT * FROM instrument_tags WHERE valid_to IS NULL;
```
Confirmed via `grep -rn instrument_tags_active` — zero existing hits, this view does not exist yet; this migration is the first to create it.

**Migration numbering:** confirmed live via `ls production/migrations/ | tail -5` during this pattern-mapping session — highest existing is `345_factor_series_correlation.sql`, so `346` is correct as of 2026-09-18 (re-verify at plan/implementation time per RESEARCH.md Assumption A5).

---

### `scripts/analysis/itr_materiality_shadow_diagnostic.py`

**Analog:** `scripts/analysis/tsmom_per_symbol_ic_screen.py` (full file, 182 lines, read above) — same role (offline, read-only, reports findings via `print()`, no `concept_registry`/table writes) and, critically, the same D-06 null-arm mechanics this phase must reuse.

**Imports/header pattern** (lines 47-66):
```python
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.rng import hash_key_to_int  # noqa: E402
from src.intelligence.statistics.ic_math import _circular_shift_null, apply_bh_fdr  # noqa: E402
```

**Null-arm pattern to reuse verbatim for D-06** (lines 58-88, and the module's own docstring lines 34-40 — restated in RESEARCH.md Pattern 3 too):
```python
def _per_symbol_ic(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for symbol, g in df.groupby("symbol", sort=False):
        if len(g) < _MIN_ROWS_PER_SYMBOL:
            continue
        x = g["ctf_momentum"].to_numpy()
        y = g["ret"].to_numpy()
        observed, _ = spearmanr(x, y)
        if not np.isfinite(observed):
            continue
        null_draws = np.empty(_N_NULL)
        for i in range(_N_NULL):
            y_shift = _circular_shift_null(y, rng)
            null_draws[i], _ = spearmanr(x, y_shift)
        null_draws = null_draws[np.isfinite(null_draws)]
        if len(null_draws) < 0.5 * _N_NULL:
            continue
        p = (1 + int((null_draws >= observed).sum())) / (len(null_draws) + 1)
        rows.append({"symbol": symbol, "ic": observed, "p": p, "n": len(g)})
    return pd.DataFrame(rows)
```
**Critical adaptation for D-06** (do NOT copy this call site's shift target unchanged): this script shifts `y` = the **candidate's own return** series, which D-06 explicitly forbids ("NOT a candidate-return shift"). The new diagnostic must instead shift the **factor_series proxy's own return series** (e.g. `factor_ret = _circular_shift_null(factor_ret, rng)`, recompute the partial loading with the shifted factor in place, leave the candidate's return series and every control's series untouched) — same `_circular_shift_null`/`hash_key_to_int`-seeded-RNG/`(1 + sum(null_draws >= observed)) / (N + 1)` p-value mechanics, different shift target.

**Deterministic RNG seeding pattern** (line 164):
```python
rng = np.random.default_rng(hash_key_to_int(f"{_SCREEN_NAME}_null"))
```

**DB connection + read-only query pattern** (lines 118-150): fetch panel via a plain `cur.execute(...)`/`cur.fetchall()` against a psycopg connection from `_connect_db(settings)`, assert no fan-out (`panel.duplicated([...]).any()` guard, line 152), build the working frame, then dispatch to a `_report(label, panel, rng)` helper per stratum. The new diagnostic's membership-delta report (human-only vs. human-OR-materiality-eligible per group) should follow this same fetch-then-stratify-then-print shape, reading `instrument_tags_active` (the new view, todo 126 fold-in) rather than a bare `instrument_tags` query (Pitfall 5) — mirrors `_load_tags_by_symbol`'s exact stopgap query shape at `services/cross_sectional_regime_model.py:396-401` as the "today" baseline to diff against:
```python
# Source: services/cross_sectional_regime_model.py:396-401 (the exact stopgap query
# this diagnostic's "human-only" baseline arm must reproduce)
cur.execute(
    "SELECT symbol, array_agg(tag) FROM instrument_tags "
    "WHERE source = 'human' GROUP BY symbol"
)
```

**Read-only invariant (P175-03):** no `INSERT`/`UPDATE`/`DELETE` anywhere in this script — verify via `grep -n "INSERT\|UPDATE\|DELETE" scripts/analysis/itr_materiality_shadow_diagnostic.py` returning zero matches outside comments before considering the file complete.

---

### `tests/unit/test_tag_calibrator.py` — extend with Pass 4 tests

**Analog:** the file's own existing tests (full file, 436 lines, read above) — pure-function, no-DB, `monkeypatch` for call-count/call-arg assertions, deterministic synthetic data via a seeded `_synthetic_close()` helper.

**Synthetic-data helper pattern to reuse** (lines 44-51):
```python
def _synthetic_close(seed: int, n: int = 260, start: float = 100.0) -> pd.Series:
    """Deterministic synthetic daily-close series, geometric-Brownian-ish, with a real
    business-day index so pd.concat(..., join='inner') alignment behaves like live data."""
    rng = np.random.default_rng(seed)
    log_rets = rng.normal(0.0, 0.01, size=n)
    closes = start * np.exp(np.cumsum(log_rets))
    idx = pd.bdate_range("2024-01-02", periods=n)
    return pd.Series(closes, index=idx)
```
Reuse directly for Pass 4's known-value test (`test_partial_loading_known_value`) — build a candidate + controls with a known, hand-derivable relationship (e.g. candidate = 0.5 * control_1 + noise) and assert the recovered `partial_loading` matches within tolerance.

**"Call exactly once, not per-hypothesis" regression-guard pattern** (lines 103-129, `test_run_level_fdr` via `monkeypatch.setattr`):
```python
def test_run_level_fdr(monkeypatch: pytest.MonkeyPatch):
    call_count = 0
    call_sizes: list[int] = []
    def _counting_apply_bh_fdr(p_values, alpha):
        nonlocal call_count
        call_count += 1
        call_sizes.append(len(p_values))
        ...
    monkeypatch.setattr("services.tag_calibrator.apply_bh_fdr", _counting_apply_bh_fdr)
    ...
    assert call_count == 1, "apply_bh_fdr must be called exactly once per run"
```
Same pattern applies if Pass 4 adds its own FDR-style correction pass, or to assert `spy_realized_vol_factor`/`build_factor_series_cache`-style single-construction reuse (matching `test_vol_beta_uses_breadth_vol_proxy`, lines 218-254, and `test_build_factor_series_cache_reused_by_measure_matrix`, lines 367-391) for the control-factor return matrix.

**Ill-conditioning/degenerate-input NaN-guard test pattern** (implicit in `_measure_pair`'s own NaN checks, mirrored by `ic_math.py`'s `partial_spearman_ic` NaN-return contract) — write `test_pass4_ill_conditioned_controls_returns_nan` following the same "construct a degenerate/collinear control matrix, assert NaN not a crash" shape RESEARCH.md's Validation Architecture table specifies.

**Discovery-OOS gate test (the exact gap todo 125 names as missing):**
```python
# Pattern for the new test — mirrors test_expiry_hysteresis's existing_row-mutation shape
# (lines 153-174) but asserts passes_materiality stays False until discovery_oos_days elapsed,
# independent of whether the statistical gate (partial_loading/incremental_r2/sign-stability)
# already passes.
```

---

## Shared Patterns

### APR compile-time binding (`_cfg()` + `TagCalibratorConfig.from_apr`)
**Source:** `services/tag_calibrator.py:107-131`, `services/_batch_utils.py:903-918` (`cfg()`), `services/_batch_utils.py:736-751` (`load_apr_dict_async`)
**Apply to:** `services/tag_calibrator.py`'s new Pass 4 config fields, and `production/migrations/346_*.sql`'s new key defaults (every new key must resolve via this exact `_cfg(cfg, key, default)` idiom — never `os.environ` or a hardcoded constant, per CLAUDE.md's APR mandate).

### BH-FDR "correct once, never per-hypothesis" discipline (F1)
**Source:** `services/tag_calibrator.py:508-517` (`apply_run_level_fdr`), reused via `src/intelligence/statistics/ic_math.py:545-564` (`apply_bh_fdr`)
**Apply to:** if Pass 4's `null_arm_p_value` or `passes_materiality` gate needs its own multiple-comparisons correction, route through this exact same `apply_bh_fdr` wrapper — never a second direct `statsmodels.multipletests` import (`Don't Hand-Roll` table, RESEARCH.md).

### Circular-shift null-arm (D-06)
**Source:** `src/intelligence/statistics/ic_math.py:180-199` (`_circular_shift_null`), applied per `scripts/analysis/tsmom_per_symbol_ic_screen.py:79-88`
**Apply to:** `scripts/analysis/itr_materiality_shadow_diagnostic.py`'s null-arm section (or, if Open Question 2 resolves toward inline, `services/tag_calibrator.py`'s Pass 4) — shift the `factor_series` proxy's own return series only, never the candidate's return, never a symbol-shuffle.

### Ill-conditioning gate on any estimated-matrix linear solve
**Source:** `src/intelligence/statistics/ic_math.py:682-696` (`check_condition_number`), shared by `partial_spearman_ic` and `standardized_loading` (`factor_math.py:126`)
**Apply to:** any new partial-loading kernel Pass 4 introduces (control design matrix), and the sign-stability rolling-window recomputation (each window's own control matrix needs the same gate).

### `market_data_ohlcv_tradeable`-only price reads
**Source:** `services/tag_calibrator.py:860-879` (`_fetch_price_cache`) — `SELECT ... FROM market_data_ohlcv_tradeable WHERE ... AND timeframe = '1d'`
**Apply to:** any new price/return fetch Pass 4 or the diagnostic script needs for the commodity-leg proxy (DBC) or an extended lookback window — never the raw `market_data_ohlcv` calendar grid (CLAUDE.md invariant, also D-11 in this module's own docstring).

### Idempotent migration shape (`ADD COLUMN IF NOT EXISTS` / `ON CONFLICT ... DO NOTHING`)
**Source:** `production/migrations/230_tag_calibrator_measurement_contract.sql`, `342_universe_pilot_sample_size_apr_key.sql`, `343_itr_measurement_gap_fixes.sql` (all three, full text read)
**Apply to:** `production/migrations/346_itr_materiality_evidence_columns.sql` in full — every block must be safe to re-run with zero errors and zero additional effect (project convention; no automated migration-test harness exists, verified via re-read of all three prior migrations — manual `psql -f` re-run-twice is the established verification method).

### `source='human'`-only stopgap query (the exact baseline the diagnostic diffs against)
**Source:** `services/cross_sectional_regime_model.py:379-401` (`_load_tags_by_symbol`)
**Apply to:** `scripts/analysis/itr_materiality_shadow_diagnostic.py`'s "today" arm must reproduce this exact query (or read it through the new `instrument_tags_active` view with the same `source = 'human'` filter) before comparing against the "human-OR-materiality-eligible" arm — any drift from this literal query would make the diagnostic's delta untrustworthy.

## No Analog Found

| File/Capability | Role | Data Flow | Reason |
|---|---|---|---|
| Sign-stability-across-rolling-windows computation (inside Pass 4) | utility (pure statistics) | transform | RESEARCH.md Pitfall 3 / Assumption A4: no existing rolling-window-split-and-recompute-per-window pattern found anywhere in `ic_math.py`, `factor_math.py`, or `scripts/analysis/*.py` during this session's targeted search. Every existing rolling-window-shaped computation in this codebase (`regime_writer.py`'s per-bar HMM smoothing, `breadth_vol.py`'s causal expanding rank) is a per-bar streaming computation, not a disjoint/overlapping-window-summary-statistic pattern. Genuinely new implementation work — plan real time for it, do not scope it as a reuse. |
| `instrument_tags_active` view itself | view (schema object) | — | Confirmed via `grep -rn instrument_tags_active` (zero hits) that this view has never been built — todo 126 proposed it but it was never shipped. This migration is the first to create it; there is no existing view definition to copy beyond the one-line `SELECT * WHERE valid_to IS NULL` shape already given inline above. |

## Metadata

**Analog search scope:** `services/tag_calibrator.py`, `src/intelligence/statistics/ic_math.py`, `src/intelligence/statistics/factor_math.py`, `scripts/analysis/tsmom_per_symbol_ic_screen.py`, `tests/unit/test_tag_calibrator.py`, `src/intelligence/regime_signals/breadth_vol.py`, `services/cross_sectional_regime_model.py`, `production/migrations/{230,342,343,345}*.sql`, `services/_batch_utils.py` (targeted `cfg`/`load_apr_dict_async` reads).
**Files scanned:** 10 (all fully or near-fully read; no file exceeded 2,000 lines, so single-pass full reads were used throughout except `ic_math.py` (1,200 lines — 2 targeted non-overlapping reads: `partial_spearman_ic`/`check_condition_number` region and `_vectorized_ic`/`_circular_shift_null`/`apply_bh_fdr` region) and `cross_sectional_regime_model.py` (706 lines — 1 targeted read of the pure-helper + DB-helper region containing `_resolve_group_symbols`/`_load_tags_by_symbol`)).
**Pattern extraction date:** 2026-09-18
