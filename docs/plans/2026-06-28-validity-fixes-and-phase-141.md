# Validity Fixes + Phase 141 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three known validity threats in the v3.0 corpus pipeline, rerun affected corpus steps, then execute Phase 141 IC validation analysis.

**Architecture:** Three sequential milestones. Milestone 1 (V3) and Milestone 2 (V1) are code changes; Milestone 3 is the corpus rerun + analysis. V2 (cost-aware net scoring) is deferred until Phase 141 establishes the IC calibration constants needed for correct unit conversion. The alpha_score is in weighted-z-score product units, not return units — subtracting costs requires knowing IC × return_scale, which Phase 141 provides.

**Tech Stack:** Python 3.11, asyncpg, pandas, numpy, bisect (stdlib), TimescaleDB/psycopg2, pytest.

## Global Constraints

- All timestamps: `datetime.now(UTC)` only — never `datetime.now()` or `datetime.utcnow()`.
- Exception variable name is `error`, not `exc`.
- structlog: never pass `event=` as a keyword argument — use `signal=`, `payload=`, `data=` instead.
- `asyncpg: JSONB → dict` — no `json.loads()` / `json.dumps()` for DB params.
- APR mandate: no new numeric constants hard-coded in `src/` or `services/` without a `config_state` entry.
- Test runner: `.venv/bin/pytest tests/unit/ -q` — all tests must stay green.
- Done-coding SOP after each milestone: simplify → `/review` → pytest → commit → merge main → push.

---

## Milestone 1 (V3): BaseBatch JSONB Codec Fix

**Why:** `BaseBatch._setup_pool()` calls bare `asyncpg.create_pool()` without `init=_setup_codecs`. Every BaseBatch-derived service (AlphaPublisher, EnsembleTrainer) therefore has no JSONB codec. The workaround in `alpha_publisher.py` — `json.dumps(top_features)` + `::jsonb` cast — violates `CLAUDE.md: asyncpg: JSONB → dict`. One future "fix" that registers the codec without removing the `json.dumps()` calls silently double-encodes every JSONB column. Steps 1 and 2 MUST land in one atomic commit.

**Files:**
- Modify: `src/core/agent/base_batch.py:122-128`
- Modify: `services/alpha_publisher.py:30,132-144,308,376`
- Create: `tests/unit/test_base_batch_jsonb.py`

---

### Task 1: Write the failing test for BaseBatch JSONB codec

- [ ] **Step 1.1: Create `tests/unit/test_base_batch_jsonb.py`**

```python
"""Verify BaseBatch-derived services can pass Python dicts to JSONB columns.

The test catches the double-encode trap: BaseBatch must register the asyncpg
JSONB codec (via database_manager.create_pool) so callers pass plain dicts —
no json.dumps(), no ::jsonb cast needed.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.agent.base_batch import BaseBatch


class _MinimalBatch(BaseBatch):
    job_name = "test-batch"
    compute_version = "v0"

    async def execute(self, pool) -> None:
        pass


@pytest.mark.asyncio
async def test_setup_pool_uses_database_manager_create_pool():
    """BaseBatch._setup_pool must call database_manager.create_pool, not bare asyncpg.create_pool."""
    batch = _MinimalBatch(db_dsn="postgresql://localhost/test")

    with patch("src.core.agent.base_batch.create_pool") as mock_create_pool:
        mock_pool = AsyncMock()
        mock_create_pool.return_value = mock_pool
        await batch._setup_pool()

    mock_create_pool.assert_awaited_once()
    call_kwargs = mock_create_pool.call_args
    assert call_kwargs is not None, "create_pool was not called"


@pytest.mark.asyncio
async def test_setup_pool_does_not_call_bare_asyncpg_create_pool():
    """Bare asyncpg.create_pool (no init=) must NOT be called anywhere in _setup_pool."""
    import asyncpg

    batch = _MinimalBatch(db_dsn="postgresql://localhost/test")

    with patch("src.core.agent.base_batch.create_pool", new_callable=AsyncMock) as mock_dm_pool, \
         patch.object(asyncpg, "create_pool", new_callable=AsyncMock) as mock_raw_pool:
        mock_dm_pool.return_value = AsyncMock()
        await batch._setup_pool()
        mock_raw_pool.assert_not_awaited()
```

- [ ] **Step 1.2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/test_base_batch_jsonb.py -v
```

Expected: FAIL — `mock_create_pool.assert_awaited_once()` fails because `base_batch.py` still calls bare `asyncpg.create_pool`, not the `create_pool` imported from `database_manager`.

---

### Task 2: Apply the fix (atomic — both files in one commit)

- [ ] **Step 2.1: Update `src/core/agent/base_batch.py`**

Add the import after the existing `import asyncpg` line (line 22):

```python
from src.core.database_manager import create_pool
```

Replace `_setup_pool` (lines 122-129):

```python
async def _setup_pool(self) -> None:
    """Open asyncpg connection pool with JSONB codecs registered."""
    self._pool = await create_pool(
        self._db_dsn,
        pool_name=self.job_name,
        min_size=1,
        max_size=10,
    )
    self.logger.info("batch_computer.pool_open", job=self.job_name, min_size=1, max_size=10)
```

- [ ] **Step 2.2: Update `services/alpha_publisher.py`**

Remove `import json` (line 30) entirely.

In `_INSERT_SQL` (line 142), remove the `::jsonb` cast — change:

```python
            $11, $12, $13, $14, $15::jsonb, $16
```

to:

```python
            $11, $12, $13, $14, $15, $16
```

At line 308 (skip_kafka chunk path), change:

```python
                                json.dumps(top_features),
```

to:

```python
                                top_features,
```

At line 376 (pending_events bulk insert path), change:

```python
                                    json.dumps(e["top_features"]),
```

to:

```python
                                    e["top_features"],
```

- [ ] **Step 2.3: Grep for remaining json.dumps JSONB workarounds in all BaseBatch subclasses**

```bash
grep -n "json.dumps" services/ensemble_trainer.py services/ic_engine.py services/forward_return_writer.py services/regime_writer.py 2>/dev/null
```

Expected: no output. If any are found, remove them using the same pattern (pass the dict directly; the codec handles serialization).

- [ ] **Step 2.4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_base_batch_jsonb.py tests/unit/test_alpha_publisher.py -v
```

Expected: all PASS.

- [ ] **Step 2.5: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all green (same pass count as before this change).

- [ ] **Step 2.6: Commit (atomic — both files required)**

```bash
git add src/core/agent/base_batch.py services/alpha_publisher.py tests/unit/test_base_batch_jsonb.py
git commit -m "fix(infra): register JSONB codec in BaseBatch via database_manager.create_pool

Remove json.dumps() workarounds from alpha_publisher (lines 308, 376) and
the ::jsonb explicit cast from INSERT_SQL. BaseBatch._setup_pool now calls
database_manager.create_pool which registers the asyncpg JSONB codec.
Steps 1 and 2 are atomic: codec + workaround removal must land together
to prevent the double-encode trap."
```

---

## Milestone 2 (V1): equity_regime_model Causal Expanding Rank

**Why:** `_compute_vix_pct_rank` uses `.rank(pct=True)` over the full corpus — a global rank that knows all future vix_z values. During backfill, each bar's percentile is computed knowing future volatility regimes. In live operation the model can only rank against bars seen so far. This produces biased regime labels in `market_regimes`, which are the primary stratification source for all 54,036 cross-sectional IC scores and the 328 ensemble weights.

Two bugs fixed together:
- **V1a (critical):** Global rank → causal expanding rank in `_compute_vix_pct_rank`.
- **V1b (correctness):** Windows `_REALIZED_VOL_WINDOW=20` and `_VIX_Z_WINDOW=252` are in daily-bar units. At 5m, 252 bars = 3.2 trading days of lookback — economically meaningless. Windows must scale with TF.

**Files:**
- Modify: `services/equity_regime_model.py:74-76,161-175,351-364,225-231`
- Create: `tests/unit/services/test_equity_regime_model_causal.py`

---

### Task 3: Write the failing tests

- [ ] **Step 3.1: Create `tests/unit/services/test_equity_regime_model_causal.py`**

```python
"""Tests for equity_regime_model causal expanding rank (V1a) and TF-normalized windows (V1b)."""

from __future__ import annotations

import sys
from datetime import datetime, UTC
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services.equity_regime_model import _compute_vix_pct_rank, _tf_window


# ---------------------------------------------------------------------------
# V1b: TF-normalized windows
# ---------------------------------------------------------------------------

def test_tf_window_scales_correctly():
    """_tf_window must return daily_bars * bars_per_day for each TF."""
    assert _tf_window(20, "1d") == 20
    assert _tf_window(20, "1h") == 20 * 7
    assert _tf_window(20, "15m") == 20 * 26
    assert _tf_window(20, "5m") == 20 * 78


def test_tf_window_ma_at_5m():
    """200MA at 5m should be 200 days × 78 bars/day = 15,600 bars."""
    assert _tf_window(200, "5m") == 15_600


# ---------------------------------------------------------------------------
# V1a: Causal expanding rank — no look-ahead
# ---------------------------------------------------------------------------

def _make_spy_ts_close(n: int = 300):
    """Generate n synthetic SPY timestamps and log-normal close prices."""
    base = datetime(2020, 1, 2, 9, 30, tzinfo=UTC)
    ts = [base.replace(hour=9, minute=30).timestamp() + i * 300 for i in range(n)]
    rng = np.random.default_rng(42)
    close = 300.0 * np.cumprod(1 + rng.normal(0, 0.001, n))
    return ts, close.tolist()


def test_vix_pct_rank_causal_property():
    """rank[i] must equal (bars seen up to i where vix_z <= vix_z[i]) / (bars seen up to i).

    This is the causal definition. If global rank were used, rank[i] would
    differ because future bars shift the distribution. We verify by splitting
    the series in half and confirming rank[T] using only bars[0:T+1] matches
    the returned value.
    """
    ts, close = _make_spy_ts_close(600)
    result = _compute_vix_pct_rank(ts, close, tf="1d")

    # Find first non-NaN index
    first_valid = result.first_valid_index()
    assert first_valid is not None, "All ranks are NaN — warmup too long"

    # For a sample of valid indices, verify the causal definition independently
    valid_idx = result.dropna().index[50::30]  # sample every 30th
    for idx in valid_idx:
        pos = list(result.index).index(idx)
        # Re-compute from scratch using only bars[0:pos+1]
        partial_result = _compute_vix_pct_rank(ts[:pos + 1], close[:pos + 1], tf="1d")
        expected_rank = partial_result.iloc[-1]
        actual_rank = result.iloc[pos]
        assert abs(actual_rank - expected_rank) < 1e-9, (
            f"Look-ahead bias detected at position {pos}: "
            f"full={actual_rank:.6f}, causal={expected_rank:.6f}"
        )


def test_vix_pct_rank_monotone_for_constant_vol():
    """With constant realized vol, all valid ranks should be 0.5 (median)."""
    n = 500
    ts = list(range(n))
    # Constant returns → constant realized vol → constant vix_z → rank always 0.5
    # Use non-zero but identical returns so realized_vol is non-NaN
    close = [100.0 * (1.001 ** i) for i in range(n)]
    result = _compute_vix_pct_rank(ts, close, tf="1d")
    valid = result.dropna()
    if len(valid) > 10:
        # All ranks should be 0.5 when all vix_z values are identical
        # (only the first occurrence gets rank = 1/n, rest converge to 0.5)
        assert (valid.iloc[10:] - 0.5).abs().max() < 0.05, (
            "Constant-vol ranks deviated far from 0.5"
        )


def test_vix_pct_rank_bounds():
    """All returned ranks must be in (0, 1] (or NaN for warmup bars)."""
    ts, close = _make_spy_ts_close(400)
    result = _compute_vix_pct_rank(ts, close, tf="5m")
    valid = result.dropna()
    assert (valid > 0).all(), "rank must be > 0"
    assert (valid <= 1.0).all(), "rank must be <= 1.0"
```

- [ ] **Step 3.2: Run to verify they fail**

```bash
.venv/bin/pytest tests/unit/services/test_equity_regime_model_causal.py -v
```

Expected: FAIL — `_tf_window` not defined, `_compute_vix_pct_rank` does not accept `tf=` parameter, causal property test fails because global rank is used.

---

### Task 4: Implement TF-normalized windows

- [ ] **Step 4.1: Add `_BARS_PER_DAY` mapping and `_tf_window` helper**

In `services/equity_regime_model.py`, add after the `_MA_WINDOW` constant (after line 76):

```python
# Trading bars per day per timeframe — used to scale daily-bar window constants to TF bar counts.
# 5m: 6.5hr session / 5min = 78 bars. 15m: 26. 1h: 7 (rounded). 1d: 1.
_BARS_PER_DAY: dict[str, int] = {"5m": 78, "15m": 26, "1h": 7, "1d": 1}


def _tf_window(daily_bars: int, tf: str) -> int:
    """Scale a daily-bar window to TF bar count. Falls back to daily-equivalent for unknown TFs."""
    return daily_bars * _BARS_PER_DAY.get(tf, 1)
```

- [ ] **Step 4.2: Run TF-window tests only**

```bash
.venv/bin/pytest tests/unit/services/test_equity_regime_model_causal.py::test_tf_window_scales_correctly tests/unit/services/test_equity_regime_model_causal.py::test_tf_window_ma_at_5m -v
```

Expected: PASS.

---

### Task 5: Implement causal expanding rank in `_compute_vix_pct_rank`

- [ ] **Step 5.1: Add `bisect` import**

Add at top of `services/equity_regime_model.py`, after the existing imports:

```python
import bisect
```

- [ ] **Step 5.2: Replace `_compute_vix_pct_rank`**

Replace the existing function (lines 161-175) with:

```python
def _compute_vix_pct_rank(spy_ts: list, spy_close: list[float], tf: str = "1d") -> pd.Series:
    """Compute SPY realized-vol z-score CAUSAL expanding percentile rank.

    For each bar T, rank[T] = fraction of bars 0..T where vix_z <= vix_z[T].
    No look-ahead: the rank at T uses only data available at T.

    Windows are TF-scaled: _REALIZED_VOL_WINDOW and _VIX_Z_WINDOW are in
    daily-bar units; _tf_window() converts them to TF-appropriate bar counts.
    """
    rv_window = _tf_window(_REALIZED_VOL_WINDOW, tf)
    z_window = _tf_window(_VIX_Z_WINDOW, tf)

    spy_s = pd.Series(spy_close, index=spy_ts, dtype=float)
    spy_log_ret = np.log(spy_s / spy_s.shift(1))
    realized_vol = spy_log_ret.rolling(window=rv_window, min_periods=rv_window).std()
    rv_mean = realized_vol.rolling(window=z_window, min_periods=z_window).mean()
    rv_std = realized_vol.rolling(window=z_window, min_periods=z_window).std()
    vix_z = (realized_vol - rv_mean) / rv_std.where(rv_std > 1e-10)

    # Causal expanding rank using a sorted list for O(log n) search per bar.
    # insort maintains sorted order; bisect_right gives the upper-bound position
    # which equals the count of values <= v (ties included, matching pct=True semantics).
    vix_z_arr = vix_z.values
    result = np.full(len(vix_z_arr), np.nan)
    sorted_seen: list[float] = []
    for i, v in enumerate(vix_z_arr):
        if np.isnan(v):
            continue
        bisect.insort(sorted_seen, v)
        pos = bisect.bisect_right(sorted_seen, v)
        result[i] = pos / len(sorted_seen)
    return pd.Series(result, index=vix_z.index)
```

- [ ] **Step 5.3: Update the call site in the main TF loop**

Around line 357, change:

```python
vix_pct_rank = _compute_vix_pct_rank(spy_ts, spy_close)
```

to:

```python
vix_pct_rank = _compute_vix_pct_rank(spy_ts, spy_close, tf=tf)
```

- [ ] **Step 5.4: Scale `_MA_WINDOW` inside `_compute_breadth_fraction`**

In `_compute_breadth_fraction`, replace the two uses of `_MA_WINDOW` (the `len(ts_list) < _MA_WINDOW` guard and the `rolling(window=_MA_WINDOW)` call) with TF-scaled values. Add at the start of the function body:

```python
ma_window = _tf_window(_MA_WINDOW, tf)
```

Then replace `_MA_WINDOW` → `ma_window` throughout the function body (two occurrences):

```python
# guard:
if len(ts_list) < ma_window:
    return

# rolling:
ma200 = s.rolling(window=ma_window, min_periods=ma_window).mean()
```

- [ ] **Step 5.5: Run all causal rank tests**

```bash
.venv/bin/pytest tests/unit/services/test_equity_regime_model_causal.py -v
```

Expected: all PASS. The `test_vix_pct_rank_causal_property` test verifies that rank[T] using the full series matches rank[T] computed from only bars 0..T — confirming no look-ahead.

- [ ] **Step 5.6: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all green.

- [ ] **Step 5.7: Commit**

```bash
git add services/equity_regime_model.py tests/unit/services/test_equity_regime_model_causal.py
git commit -m "fix(intelligence): causal expanding rank in equity_regime_model (V1a+V1b)

Replace global vix_z.rank(pct=True) with bisect-based causal expanding
rank: rank[T] uses only bars seen up to T, matching live operation behavior.
Also fix TF-normalized windows: _REALIZED_VOL_WINDOW=20 and _VIX_Z_WINDOW=252
now scale to TF bar counts via _tf_window() so 200 days of lookback means
200 * bars_per_day bars, not 200 bars regardless of TF."
```

---

## Milestone 3: Corpus Rerun + Phase 141 IC Validation

### Task 6: Partial corpus rerun (market_regimes → ic_engine cross-sectional → ensemble → alpha)

The V1 fix invalidates: `market_regimes`, cross-sectional rows in `feature_ic_scores` (is_pooled=true), `ensemble_weights`, `ensemble_alpha`, and `alpha_events`. Per-symbol IC scores (is_pooled=false) and `feature_vectors`/`forward_returns` are unaffected.

- [ ] **Step 6.1: Truncate affected tables**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  BEGIN;
  TRUNCATE market_regimes;
  DELETE FROM feature_ic_scores WHERE is_pooled = true;
  TRUNCATE ensemble_weights;
  TRUNCATE ensemble_alpha;
  TRUNCATE alpha_events;
  COMMIT;
"
```

Verify:

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  SELECT
    (SELECT COUNT(*) FROM market_regimes) AS market_regimes,
    (SELECT COUNT(*) FROM feature_ic_scores WHERE is_pooled = true) AS cs_ic_scores,
    (SELECT COUNT(*) FROM ensemble_weights) AS ensemble_weights,
    (SELECT COUNT(*) FROM ensemble_alpha) AS ensemble_alpha,
    (SELECT COUNT(*) FROM alpha_events) AS alpha_events;
"
```

Expected: all zeros.

- [ ] **Step 6.2: Rerun equity_regime_model (regenerates market_regimes)**

```bash
.venv/bin/python services/equity_regime_model.py 2>&1 | tee logs/corpus_pipeline/equity_regime_model_v1fix.log
```

Monitor:

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT tf, COUNT(*) FROM market_regimes GROUP BY tf ORDER BY tf"
```

Expected: 4 rows (5m/15m/1h/1d), each with ~200K+ rows (819,020 total pre-fix; may differ slightly with causal rank).

- [ ] **Step 6.3: Rerun ic_engine cross-sectional only**

```bash
TRAINING_WINDOW_END=$(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
    -tAc "SELECT MAX(bar_ts) FROM feature_vectors")

.venv/bin/python services/ic_engine.py \
    --cross-sectional-only \
    --training-window-end "$TRAINING_WINDOW_END" \
    2>&1 | tee logs/corpus_pipeline/ic_engine_cs_v1fix.log
```

Monitor:

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  SELECT COUNT(*) as total, COUNT(ic_sharpe_hac) as with_sharpe
  FROM feature_ic_scores WHERE is_pooled = true
"
```

Expected: ~54,036 rows (12 strata × 54 features × ~4 TFs, some TF/regime combos may vary).

- [ ] **Step 6.4: Rerun ensemble_trainer**

```bash
.venv/bin/python services/ensemble_trainer.py 2>&1 | tee logs/corpus_pipeline/ensemble_trainer_v1fix.log
```

Verify:

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  SELECT COUNT(*) as weights FROM ensemble_weights;
  SELECT tf, COUNT(DISTINCT bar_ts) as scored_bars FROM ensemble_alpha GROUP BY tf ORDER BY tf;
"
```

Expected: ~328 weights, ensemble_alpha scored bars match pre-fix counts.

- [ ] **Step 6.5: Rerun alpha_publisher (--skip-kafka for corpus)**

```bash
.venv/bin/python services/alpha_publisher.py --skip-kafka 2>&1 | tee logs/corpus_pipeline/alpha_publisher_v1fix.log
```

Verify:

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  SELECT tf, COUNT(*) as events, AVG(ABS(alpha_score)) as mean_abs_score
  FROM alpha_events GROUP BY tf ORDER BY tf;
"
```

Expected: alpha_events populated across all 4 TFs. The row counts may differ from the pre-fix 12.47M — causal regime labels change which regime each bar is assigned to, shifting stratum membership and ensemble weights.

- [ ] **Step 6.6: Update corpus manifest in STATE.md**

Update `.planning/STATE.md` section "Current Data State" with the new row counts from the corrected corpus. Commit:

```bash
git add .planning/STATE.md
git commit -m "docs(state): update corpus row counts after V1 causal regime fix"
```

---

### Task 7: Phase 141 — IC Validation Analysis

Phase 141 is analysis-only: read existing `feature_ic_scores`, produce a ranked validation report. No new services. The goal: confirm IC > 0 at p < 0.05 for the features that will drive the ensemble in Phase 142 shadow mode.

**Output:** `docs/analysis/ic-validation-report-58sym.md`

- [ ] **Step 7.1: Feature IC Sharpe ranked table — pooled cross-sectional**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  SELECT
    feature_name,
    tf,
    regime,
    ROUND(ic_mean::numeric, 5) AS ic_mean,
    ROUND(ic_std::numeric, 5) AS ic_std,
    ROUND(ic_sharpe_hac::numeric, 3) AS ic_sharpe_hac,
    effective_n,
    ROUND(ic_ci_lower::numeric, 5) AS ci_lower,
    ROUND(ic_ci_upper::numeric, 5) AS ci_upper
  FROM feature_ic_scores
  WHERE is_pooled = true
    AND symbol = 'POOLED'
    AND regime != '_pooled'
    AND ic_sharpe_hac IS NOT NULL
  ORDER BY ABS(ic_sharpe_hac) DESC
  LIMIT 30;
" 2>/dev/null
```

Record output for the report. Features with `ABS(ic_sharpe_hac) > 0.5` pass the primary IC gate.

- [ ] **Step 7.2: Per-TF IC breakdown — how many features pass by TF**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  SELECT
    tf,
    COUNT(*) AS total_feature_regime_cells,
    COUNT(ic_sharpe_hac) AS cells_with_sharpe,
    COUNT(CASE WHEN ABS(ic_sharpe_hac) > 0.5 THEN 1 END) AS pass_sharpe_05,
    COUNT(CASE WHEN ic_ci_lower > 0 THEN 1 END) AS ci_lower_positive,
    COUNT(CASE WHEN ic_ci_upper < 0 THEN 1 END) AS ci_upper_negative
  FROM feature_ic_scores
  WHERE is_pooled = true AND symbol = 'POOLED' AND regime != '_pooled'
  GROUP BY tf ORDER BY tf;
" 2>/dev/null
```

Note: 1d will have almost no `ic_sharpe_hac` (< 5,040 bars; minimum 60K subsampled bars required). Do not report 1d IC Sharpe as a signal-bearing result.

- [ ] **Step 7.3: Per-regime IC breakdown — which regimes have IC > 0**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  SELECT
    regime,
    COUNT(*) AS feature_cells,
    COUNT(ic_sharpe_hac) AS cells_with_sharpe,
    ROUND(AVG(ic_mean)::numeric, 5) AS avg_ic_mean,
    ROUND(AVG(ic_sharpe_hac)::numeric, 3) AS avg_ic_sharpe,
    COUNT(CASE WHEN ABS(ic_sharpe_hac) > 0.5 THEN 1 END) AS pass_gate
  FROM feature_ic_scores
  WHERE is_pooled = true AND symbol = 'POOLED' AND regime != '_pooled'
  GROUP BY regime ORDER BY regime;
" 2>/dev/null
```

- [ ] **Step 7.4: Bottom features — candidates for demotion (todo 015)**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  SELECT
    feature_name,
    COUNT(*) AS regime_cells,
    COUNT(CASE WHEN ic_ci_lower > 0 OR ic_ci_upper < 0 THEN 1 END) AS cells_with_directional_ci,
    ROUND(MAX(ABS(ic_mean))::numeric, 6) AS max_abs_ic_across_regimes
  FROM feature_ic_scores
  WHERE is_pooled = true AND symbol = 'POOLED' AND regime != '_pooled'
  GROUP BY feature_name
  HAVING COUNT(CASE WHEN ABS(ic_sharpe_hac) > 0.5 THEN 1 END) = 0
  ORDER BY max_abs_ic_across_regimes ASC
  LIMIT 20;
" 2>/dev/null
```

Features with `max_abs_ic = 0` across all regimes are demotion candidates for Phase 143 (todo 015).

- [ ] **Step 7.5: V2 IC calibration constants for cost-aware scoring**

This step derives the IC-to-return-scale mapping Phase 142 needs for V2.

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  SELECT
    fis.tf,
    fis.regime,
    ROUND(AVG(ABS(fis.ic_mean))::numeric, 6) AS mean_abs_ic,
    ROUND(STDDEV(fr.return_fast)::numeric, 6) AS return_fast_std,
    ROUND(STDDEV(fr.return_mid)::numeric, 6) AS return_mid_std,
    ROUND(AVG(ABS(fis.ic_mean)) * STDDEV(fr.return_fast)::numeric, 8) AS ic_x_return_scale
  FROM feature_ic_scores fis
  JOIN forward_returns fr ON fr.tf = fis.tf
  WHERE fis.is_pooled = true AND fis.symbol = 'POOLED' AND fis.regime != '_pooled'
    AND fis.ic_sharpe_hac IS NOT NULL
    AND fr.return_type = 'executable_open_to_open'
  GROUP BY fis.tf, fis.regime
  ORDER BY fis.tf, fis.regime;
" 2>/dev/null
```

Record `ic_x_return_scale` per (tf, regime). This is the expected return in log-return units per unit of alpha_score. Used in V2 to determine the cost threshold in alpha_score units: `cost_score_units = cost_log_return / ic_x_return_scale`.

- [ ] **Step 7.6: Write `docs/analysis/ic-validation-report-58sym.md`**

Create the report with these sections:

```markdown
# IC Validation Report — 58-Symbol Corpus (V1-Corrected)

**Date:** 2026-06-28 (rerun after causal expanding rank fix)
**Corpus:** 54,260,576 feature_vectors, 54,260,576 forward_returns (executable_open_to_open)
**IC scores:** [total cross-sectional rows] / [rows with ic_sharpe_hac populated]

## Executive Summary

[2-3 sentences: which TFs have usable IC, what the top features are, whether the Phase 141
IC gate (|ic_sharpe_hac| > 0.5) is cleared by enough features to proceed to Phase 142]

## Top Features by IC Sharpe (Cross-Sectional, All Regimes)

[Paste output from Step 7.1]

## IC by Timeframe

[Paste output from Step 7.2]

Note: 1d has insufficient data for IC Sharpe (< 5,040 bars vs 60,000 required). Do not
use 1d IC Sharpe as a decision input.

## IC by Regime

[Paste output from Step 7.3]

## Demotion Candidates (todo 015)

[Paste output from Step 7.4]

Features with zero IC across all regimes are candidates for demotion in Phase 143.
Demotion is NOT triggered here — Phase 141 identifies candidates; Phase 143 implements
the demotion system.

## V2 Cost Calibration Constants

[Paste output from Step 7.5]

ic_x_return_scale per (tf, regime) is used in V2 (cost-aware net scoring) to convert
transaction cost estimates from log-return units to alpha_score units.

## Phase 141 Gate Assessment

**Phase 142 prerequisite:** ≥ 1 feature per (tf, regime) with |ic_sharpe_hac| > 0.5 and
ic_ci_lower > 0 (for long signals) across at least 5m and 1h TFs.

[State PASS or FAIL with the specific numbers]

## Next Steps

- Phase 142: Portfolio construction + shadow mode (gated on this report — PASS)
- V2: Cost-aware net scoring using ic_x_return_scale constants from Step 7.5
- todo 015: Feature demotion system for candidates identified above
- todo 026 P1a: Empirical threshold calibration for vix/breadth regime cuts (the
  33rd/67th percentile splits are currently conventional; calibrate from data)
```

- [ ] **Step 7.7: Commit the report**

```bash
git add docs/analysis/ic-validation-report-58sym.md
git commit -m "docs(analysis): Phase 141 IC validation report — 58-symbol V1-corrected corpus"
```

---

---

## Milestone 4 (S1): HMM Numba JIT — `_alpha_pass`

**Why now:** The `_alpha_pass` t-loop is the regime_writer bottleneck — 20+ hours for a full 58-symbol corpus run. With `@numba.njit(cache=True)`, first call compiles once (~10-15s) and subsequent calls run at native LLVM speed (~30 min total). Numba 0.65.1 is already installed. This runs in parallel with Phase 141 analysis (different files, no coupling) and must be done before primitives expansion triggers the next full corpus rerun.

**Target:** Only `_alpha_pass` (the per-bar t-loop). `_log_emit_full` and `_log_emit_diag` are already vectorized numpy computed once per symbol — leave them in numpy (the try/except in `_log_emit_full` is incompatible with `njit` nopython mode anyway).

**Files:**
- Create: `src/intelligence/hmm_jit.py`
- Modify: `services/regime_writer.py:247-276,477-487`
- Create: `tests/unit/intelligence/test_hmm_jit.py`

---

### Task 8: Write failing tests for JIT alpha pass

- [ ] **Step 8.1: Create `tests/unit/intelligence/test_hmm_jit.py`**

```python
"""Tests for Numba JIT forward-filter in hmm_jit.py.

Verifies:
- Numerical identity with the Python reference implementation
- State sequence is deterministic and valid (0..K-1)
- alpha_history rows sum to 1.0 (probability simplex)
- cache=True does not change output on second call
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.intelligence.hmm_jit import alpha_pass_jit

# ---------------------------------------------------------------------------
# Reference Python implementation (mirrors regime_writer._alpha_pass exactly)
# ---------------------------------------------------------------------------

def _alpha_pass_ref(log_emit, A, pi0):
    """Python reference — numerically identical logic to regime_writer._alpha_pass."""
    n, K = log_emit.shape
    log_A = np.log(np.maximum(A, 1e-300))
    states = np.zeros(n, dtype=int)
    alpha_history = np.zeros((n, K))
    alpha = pi0.copy()
    for t in range(n):
        log_alpha = np.log(np.maximum(alpha, 1e-300))
        log_trans = log_alpha[:, np.newaxis] + log_A
        max_lt = log_trans.max(axis=0)
        log_alpha_new = max_lt + np.log(np.sum(np.exp(log_trans - max_lt), axis=0))
        log_alpha_new += log_emit[t]
        max_la = log_alpha_new.max()
        alpha = np.exp(log_alpha_new - max_la)
        total = alpha.sum()
        alpha /= total if total > 0 else 1.0
        states[t] = int(alpha.argmax())
        alpha_history[t] = alpha
    return states, alpha_history


def _make_hmm_inputs(n=200, K=5, seed=42):
    rng = np.random.default_rng(seed)
    log_emit = rng.normal(0, 1, (n, K))
    # Random row-stochastic transition matrix
    A = rng.dirichlet(np.ones(K), size=K)
    log_A = np.log(np.maximum(A, 1e-300))
    pi0 = np.ones(K) / K
    return log_emit, log_A, pi0


def test_jit_states_match_reference():
    """JIT states must be identical to Python reference for same inputs."""
    log_emit, log_A, pi0 = _make_hmm_inputs()
    A = np.exp(log_A)

    ref_states, _ = _alpha_pass_ref(log_emit, A, pi0)
    jit_states, _ = alpha_pass_jit(log_emit, log_A, pi0)

    np.testing.assert_array_equal(jit_states, ref_states)


def test_jit_alpha_history_matches_reference():
    """JIT alpha_history must match reference within float64 tolerance."""
    log_emit, log_A, pi0 = _make_hmm_inputs()
    A = np.exp(log_A)

    _, ref_hist = _alpha_pass_ref(log_emit, A, pi0)
    _, jit_hist = alpha_pass_jit(log_emit, log_A, pi0)

    np.testing.assert_allclose(jit_hist, ref_hist, rtol=1e-10, atol=1e-12)


def test_alpha_rows_sum_to_one():
    """Each row of alpha_history must sum to 1.0 (valid probability simplex)."""
    log_emit, log_A, pi0 = _make_hmm_inputs(n=500, K=5)
    _, alpha_history = alpha_pass_jit(log_emit, log_A, pi0)
    row_sums = alpha_history.sum(axis=1)
    np.testing.assert_allclose(row_sums, np.ones(500), atol=1e-10)


def test_states_valid_range():
    """All state assignments must be in [0, K)."""
    log_emit, log_A, pi0 = _make_hmm_inputs(n=300, K=5)
    states, _ = alpha_pass_jit(log_emit, log_A, pi0)
    assert states.min() >= 0
    assert states.max() < 5


def test_deterministic_on_repeat_call():
    """Second call with same inputs must return identical results (cache=True)."""
    log_emit, log_A, pi0 = _make_hmm_inputs(n=100, K=5)
    s1, h1 = alpha_pass_jit(log_emit, log_A, pi0)
    s2, h2 = alpha_pass_jit(log_emit, log_A, pi0)
    np.testing.assert_array_equal(s1, s2)
    np.testing.assert_array_equal(h1, h2)
```

- [ ] **Step 8.2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_hmm_jit.py -v
```

Expected: FAIL — `ImportError: cannot import name 'alpha_pass_jit' from 'src.intelligence.hmm_jit'` (module does not exist yet).

---

### Task 9: Implement `src/intelligence/hmm_jit.py`

- [ ] **Step 9.1: Create `src/intelligence/hmm_jit.py`**

```python
"""JIT-compiled HMM forward filter for regime_writer.

Provides alpha_pass_jit — a Numba njit replacement for the Python _alpha_pass
in regime_writer. Numerically identical; ~40x faster via LLVM compilation.

cache=True: compiled artifact written to __pycache__/ on first call.
Subsequent runs (including corpus pipeline reruns) skip recompilation.
First call is slow (~10-15s warmup) — expected and logged by regime_writer.

Ring 1: domain intelligence module. No DB imports. No Ring 2 imports.
"""

from __future__ import annotations

import numpy as np
import numba


@numba.njit(cache=True)
def alpha_pass_jit(
    log_emit: np.ndarray,
    log_A: np.ndarray,
    pi0: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Causal forward filter (JIT). Numerically identical to regime_writer._alpha_pass.

    Args:
        log_emit: (n, K) log emission probabilities — precomputed outside hot loop.
        log_A:    (K, K) log transition matrix — caller computes np.log(max(A, 1e-300)).
        pi0:      (K,)   initial state distribution.

    Returns:
        states:        (n,) int64 — argmax of alpha at each timestep.
        alpha_history: (n, K) float64 — normalized forward probabilities.
    """
    n, K = log_emit.shape
    states = np.zeros(n, dtype=numba.int64)
    alpha_history = np.zeros((n, K))
    alpha = pi0.copy()

    for t in range(n):
        # log(clip(alpha, 1e-300)) — avoid log(0)
        log_alpha = np.empty(K)
        for k in range(K):
            v = alpha[k] if alpha[k] > 1e-300 else 1e-300
            log_alpha[k] = np.log(v)

        # alpha_new[j] = log-sum-exp_i(log_alpha[i] + log_A[i,j]) + log_emit[t,j]
        log_alpha_new = np.empty(K)
        for j in range(K):
            max_lt = -1e300
            for i in range(K):
                v = log_alpha[i] + log_A[i, j]
                if v > max_lt:
                    max_lt = v
            s = 0.0
            for i in range(K):
                s += np.exp(log_alpha[i] + log_A[i, j] - max_lt)
            log_alpha_new[j] = max_lt + np.log(s) + log_emit[t, j]

        # Subtract max for numerical stability before exp
        max_la = log_alpha_new[0]
        for k in range(1, K):
            if log_alpha_new[k] > max_la:
                max_la = log_alpha_new[k]

        total = 0.0
        for k in range(K):
            alpha[k] = np.exp(log_alpha_new[k] - max_la)
            total += alpha[k]

        if total <= 0.0:
            total = 1.0

        best_state = 0
        best_val = -1.0
        for k in range(K):
            alpha[k] /= total
            alpha_history[t, k] = alpha[k]
            if alpha[k] > best_val:
                best_val = alpha[k]
                best_state = k

        states[t] = best_state

    return states, alpha_history
```

- [ ] **Step 9.2: Run the tests (expect first run to be slow — JIT compile)**

```bash
.venv/bin/pytest tests/unit/intelligence/test_hmm_jit.py -v -s
```

First run takes ~10-20 seconds for Numba to compile. Expected: all PASS. Subsequent runs are fast (cache hit).

- [ ] **Step 9.3: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all green.

- [ ] **Step 9.4: Commit the module and tests**

```bash
git add src/intelligence/hmm_jit.py tests/unit/intelligence/test_hmm_jit.py
git commit -m "feat(intelligence): Numba JIT forward filter for HMM regime inference

alpha_pass_jit is a drop-in replacement for _alpha_pass in regime_writer.
Numerically identical; cache=True means compile once, fast on every
subsequent corpus run. Target: 20+ hr regime_writer run → ~30 min."
```

---

### Task 10: Wire `alpha_pass_jit` into `regime_writer.py`

- [ ] **Step 10.1: Add import to `regime_writer.py`**

After the existing imports (after line 58), add:

```python
from src.intelligence.hmm_jit import alpha_pass_jit as _alpha_pass_jit
```

- [ ] **Step 10.2: Replace the `_alpha_pass` call in `_causal_decode`**

Find the call site around line 477-487:

```python
    log_emit = _log_emit_full(obs_matrix, model.means_, model.covars_)
    # or the diagonal path:
    log_emit = _log_emit_diag(obs_matrix, model.means_, covars_diag)

    raw_states, alpha_history = _alpha_pass(log_emit, model.transmat_, pi0)
```

Replace the `_alpha_pass` call with the JIT version. The key change: pre-compute `log_A` once outside the call (it's currently computed inside `_alpha_pass` every call):

```python
    log_A = np.log(np.maximum(model.transmat_, 1e-300))

    if model.covariance_type == "full":
        log_emit = _log_emit_full(obs_matrix, model.means_, model.covars_)
    else:
        log_emit = _log_emit_diag(obs_matrix, model.means_, covars_diag)

    raw_states, alpha_history = _alpha_pass_jit(log_emit, log_A, pi0)
```

- [ ] **Step 10.3: Add warmup log at service startup**

In the `_causal_decode` function or the worker initializer, add a one-time warmup call so the JIT compiles before the first real symbol is processed. Find where workers are initialized (around the `ProcessPoolExecutor` setup) and add:

```python
# Trigger Numba JIT compile on first worker call (cache=True means disk-cached after this).
# Warmup on a tiny synthetic input so the first real symbol is not delayed 10-15s.
_warmup_log_emit = np.zeros((10, 5), dtype=np.float64)
_warmup_log_A = np.log(np.full((5, 5), 0.2))
_warmup_pi0 = np.full(5, 0.2)
_alpha_pass_jit(_warmup_log_emit, _warmup_log_A, _warmup_pi0)
```

Add this at the module level (runs on worker process startup, before any symbol is processed).

- [ ] **Step 10.4: Run regime_writer smoke test on a single small symbol**

```bash
.venv/bin/python services/regime_writer.py --symbols SPY --tf 5m 2>&1 | tail -20
```

Expected: completes without error. Log should show regime labels written for SPY 5m. The first run triggers Numba compile; if cache exists from Task 9, it loads from cache immediately.

- [ ] **Step 10.5: Run unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all green.

- [ ] **Step 10.6: Commit**

```bash
git add services/regime_writer.py
git commit -m "feat(services): wire alpha_pass_jit into regime_writer hot path

Replace Python _alpha_pass with Numba JIT version. Pre-compute log_A once
per symbol outside the JIT call. Add warmup call at worker init so first
symbol does not pay the 10-15s compile cost."
```

---

## Self-Review

**Spec coverage:**
- V3 (BaseBatch JSONB codec): Tasks 1-2. Covers `base_batch.py`, `alpha_publisher.py`, unit test, atomic commit requirement. ✓
- V1a (causal expanding rank): Task 5. Covers `_compute_vix_pct_rank` replacement with bisect-based expanding rank, call site update, causal property test. ✓
- V1b (TF-normalized windows): Task 4 + Task 5.4. Covers `_tf_window()` helper, scaling in both `_compute_vix_pct_rank` and `_compute_breadth_fraction`. ✓
- Corpus rerun: Task 6. Covers selective truncation (preserves per-symbol IC scores), ordered rerun steps, manifest update. ✓
- Phase 141 analysis: Task 7. Covers top features table, per-TF and per-regime breakdown, demotion candidates, V2 calibration constants, gate assessment. ✓
- HMM Numba JIT: Tasks 8-10. Covers `hmm_jit.py` module, numerical identity tests, warmup call, `regime_writer.py` wiring. ✓

**Placeholder scan:** No TBD or TODO in any step. All SQL queries are complete. All code blocks are complete. ✓

**Type consistency:** `_compute_vix_pct_rank(spy_ts: list, spy_close: list[float], tf: str = "1d") -> pd.Series` — same signature in test imports and function definition. `_tf_window(daily_bars: int, tf: str) -> int` — same in tests and implementation. `alpha_pass_jit(log_emit, log_A, pi0) -> tuple[np.ndarray, np.ndarray]` — same in `hmm_jit.py` and test imports. ✓

**V2 deferred:** Correctly deferred — Step 7.5 produces the calibration constants V2 needs. V2 gets its own plan after Phase 141 results are in hand.

**JIT warmup placement:** Step 10.3 notes "module level" for the warmup call — this means at worker process startup (inside the worker initializer function passed to `ProcessPoolExecutor`), not at module import time in the main process. Confirm the exact location in `regime_writer.py` during implementation.
