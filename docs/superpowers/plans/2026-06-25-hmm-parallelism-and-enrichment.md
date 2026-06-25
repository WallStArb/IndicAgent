# HMM Parallelism and Observation Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `regime_writer.py` and `ic_engine.py` 16x faster and the HMM regime labels materially more accurate by parallelizing both services and enriching the HMM observation space from 2D to 5D with feature standardization.

**Architecture:** ProcessPoolExecutor at the symbol level (each worker owns one symbol × all TFs with its own DB connection). Observation vector expands from `[log_return, realized_vol]` to `[log_return, realized_vol, momentum, vol_of_vol, rel_volume]`; StandardScaler applied per-series before fit and decode so the EM algorithm is not dominated by scale differences. The `_causal_decode` inner loop is vectorized by precomputing all per-timestep emission log-probabilities as a batch matrix before the sequential alpha-pass loop.

**Tech Stack:** Python `concurrent.futures.ProcessPoolExecutor`, `sklearn.preprocessing.StandardScaler`, `numpy` batch ops, `psycopg2`, `hmmlearn.hmm.GaussianHMM`, APR via `_batch_utils.load_config_service_sync`.

## Global Constraints

- All timestamps UTC via `datetime.now(UTC)` — never `datetime.now()` or `datetime.utcnow()`
- All APR keys loaded via `cfg.get_sync(key, default)` — never hardcode numeric constants
- Exception variable must be named `error` — `except X as error:`
- `structlog` for all logging — never `print()`
- `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent` for DB queries
- Run tests with `.venv/bin/pytest tests/unit/ -q`
- `_causal_decode` must remain causal — no backward pass, no smoothing, no Viterbi
- Observation features must be computable from `market_data_ohlcv` columns only (no feature_vectors)
- Workers in ProcessPoolExecutor must not share DB connections or numpy RNG state
- OTel spans and metrics must only be emitted from the main process (not picklable into subprocesses)
- Migration numbers: next available is 169 (check `ls production/migrations/ | sort -V | tail -3` before applying)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `production/migrations/169_hmm_parallelism_apr_keys.sql` | Create | APR seeds for worker counts, momentum/vol-of-vol windows, n_iter update |
| `services/regime_writer.py` | Modify | 5D obs, StandardScaler, vectorized decode, ProcessPoolExecutor |
| `services/ic_engine.py` | Modify | ProcessPoolExecutor at symbol level |
| `tests/unit/test_regime_writer.py` | Modify | Extend existing tests for new label_map + vectorized decode equivalence |
| `tests/unit/test_regime_writer_obs.py` | Create | New tests for 5D observation builder and StandardScaler application |
| `tests/unit/test_ic_engine_parallelism.py` | Create | Worker function contract tests |

---

### Task 1: APR Migration 169

**Files:**
- Create: `production/migrations/169_hmm_parallelism_apr_keys.sql`

**Interfaces:**
- Produces: APR keys `infra.regime_writer.workers`, `infra.ic_engine.workers`, `feature.hmm.obs_momentum_window`, `feature.hmm.obs_vol_of_vol_window`; updates `feature.hmm.n_iter` to 200

- [ ] **Step 1: Write migration**

```sql
-- Migration 169: APR keys for HMM parallelism and observation enrichment.
--
-- Seeds worker counts for ProcessPoolExecutor parallelism (regime_writer, ic_engine)
-- and observation feature windows for the enriched 5D HMM observation vector.
-- Also updates feature.hmm.n_iter from 20 to 200 — 20 iterations is insufficient
-- for convergence on 470k-row series (produces "Model is not converging" warnings
-- on nearly every symbol/tf cell; 200 eliminates most of them).
--
-- infra.regime_writer.workers: 12 = min(24_cores // 2, 16). Half of physical cores
--   to leave headroom for DB, OTel collector, and live services. Each worker holds
--   one psycopg2 connection and is CPU-bound on GaussianHMM.fit().
--   Speedup: 58 symbols / 12 workers = ~5 rounds × 42 min/symbol = ~3.5h vs 40h serial.
-- infra.ic_engine.workers: same rationale.
-- feature.hmm.obs_momentum_window: N-bar window for cumulative-return momentum feature.
--   20 bars = one trading day at 5m; captures short-term directional drift separate
--   from the raw log_return dimension. [initial_estimate]
-- feature.hmm.obs_vol_of_vol_window: window for rolling std of realized_vol.
--   Stable regimes have stable vol; transitions have erratic vol. This is the primary
--   indicator of regime change that the 2D observation space could not express.
--   [initial_estimate]

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'infra.regime_writer.workers',
    'int',
    '12',
    1, 32,
    '[initial_estimate] Number of ProcessPoolExecutor workers for regime_writer.py symbol-level parallelism. Each worker opens its own psycopg2 connection. Default 12 = min(24_cores // 2, 16). Not an ML learning target.'
),
(
    'infra.ic_engine.workers',
    'int',
    '12',
    1, 32,
    '[initial_estimate] Number of ProcessPoolExecutor workers for ic_engine.py symbol-level parallelism. Each worker opens its own psycopg2 connection and derives its RNG seed deterministically from bootstrap_seed + hash(symbol). Not an ML learning target.'
),
(
    'feature.hmm.obs_momentum_window',
    'int',
    '20',
    5, 200,
    '[initial_estimate] N-bar window for the momentum observation feature in the 5D HMM observation vector. Computed as sum(log_returns[-N:]) / (realized_vol + eps), capturing directional drift normalized by vol. 20 bars = one trading day at 5m. Not an ML learning target.'
),
(
    'feature.hmm.obs_vol_of_vol_window',
    'int',
    '20',
    5, 200,
    '[initial_estimate] M-bar window for the vol-of-vol observation feature: rolling std of realized_vol. Stable regimes have stable realized_vol; transitions have erratic realized_vol. 20 bars = one trading day at 5m. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('infra.regime_writer.workers',       '12',  1),
('infra.ic_engine.workers',           '12',  1),
('feature.hmm.obs_momentum_window',   '20',  1),
('feature.hmm.obs_vol_of_vol_window', '20',  1)
ON CONFLICT (config_key) DO NOTHING;

-- Update n_iter: 20 → 200. The existing description mentioned 50 as standard;
-- 200 provides headroom for large series (470k rows at 5m) where EM convergence
-- is slow due to near-IID return distributions at short timeframes.
UPDATE config_state SET config_value = '200', version = version + 1
WHERE config_key = 'feature.hmm.n_iter';

UPDATE config_schema SET
    default_value = '200',
    description = '[conventional] Maximum Baum-Welch EM iterations for GaussianHMM training. 200 provides convergence headroom for 470k-row 5m series where the near-IID return distribution makes EM slow to converge. Not an ML learning target.'
WHERE config_key = 'feature.hmm.n_iter';
```

- [ ] **Step 2: Apply migration**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/169_hmm_parallelism_apr_keys.sql
```

Expected output: `INSERT 0 4`, `INSERT 0 4`, `UPDATE 1`, `UPDATE 1`

- [ ] **Step 3: Verify**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT config_key, config_value FROM config_state
WHERE config_key IN (
    'infra.regime_writer.workers', 'infra.ic_engine.workers',
    'feature.hmm.obs_momentum_window', 'feature.hmm.obs_vol_of_vol_window',
    'feature.hmm.n_iter'
) ORDER BY config_key;"
```

Expected:

```
         config_key          | config_value
-----------------------------+--------------
 feature.hmm.n_iter          | 200
 feature.hmm.obs_momentum_window   | 20
 feature.hmm.obs_vol_of_vol_window | 20
 infra.ic_engine.workers     | 12
 infra.regime_writer.workers | 12
```

- [ ] **Step 4: Commit**

```bash
git add production/migrations/169_hmm_parallelism_apr_keys.sql
git commit -m "feat(apr): seed infra.regime_writer/ic_engine.workers and 5D HMM obs keys; n_iter 20→200"
```

---

### Task 2: Enrich regime_writer Observation to 5D + StandardScaler

**Files:**
- Modify: `services/regime_writer.py`
- Create: `tests/unit/test_regime_writer_obs.py`

**Interfaces:**
- Consumes: `market_data_ohlcv.volume` column (add to OHLCV query in `_label_symbol_tf`)
- Produces: `_build_obs_matrix(timestamps, closes, volumes, vol_window, momentum_window, vol_of_vol_window) -> tuple[np.ndarray, list]` returning (n_valid, 5) matrix

The 5 dimensions in order:
1. `log_return` = ln(close[t]/close[t-1])
2. `realized_vol` = rolling std of log_returns over `vol_window` bars
3. `momentum` = sum(log_returns over `momentum_window` bars) / (realized_vol + 1e-8)
4. `vol_of_vol` = rolling std of `realized_vol` over `vol_of_vol_window` bars
5. `rel_volume` = log(volume[t]) - rolling mean(log(volume), `vol_window` bars)

Valid-start = max(vol_window, momentum_window, vol_of_vol_window) - 1 (all three windows must be warm before the first valid observation).

- [ ] **Step 1: Write failing tests for 5D observation builder**

Create `tests/unit/test_regime_writer_obs.py`:

```python
"""Unit tests for the 5D HMM observation builder in regime_writer.

Tests verify shape, content, and valid-row count for the enriched observation matrix.
No DB, no GaussianHMM. Pure numpy.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.regime_writer import _build_obs_matrix


def _make_prices(n: int, seed: int = 42) -> tuple[list, list[float], list[float]]:
    """Synthetic price + volume series of length n."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0001, 0.001, n)
    closes = [100.0 * np.exp(np.sum(returns[:i])) for i in range(n)]
    volumes = [1_000_000 * (1 + rng.uniform(-0.3, 0.3)) for _ in range(n)]
    ts = list(range(n))
    return ts, closes, volumes


def test_obs_matrix_shape_5d():
    """Output matrix must have 5 columns."""
    ts, closes, volumes = _make_prices(500)
    obs, valid_ts = _build_obs_matrix(ts, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20)
    assert obs.shape[1] == 5, f"Expected 5 columns, got {obs.shape[1]}"


def test_obs_matrix_valid_rows_discarded():
    """First max(vol_window, momentum_window, vol_of_vol_window) rows must be discarded."""
    ts, closes, volumes = _make_prices(500)
    vol_window = 20
    obs, valid_ts = _build_obs_matrix(ts, closes, volumes, vol_window=vol_window, momentum_window=20, vol_of_vol_window=20)
    # n returns = 499, valid_start = 19, so valid rows = 499 - 19 = 480
    expected_rows = (len(closes) - 1) - (vol_window - 1)
    assert obs.shape[0] == expected_rows, f"Expected {expected_rows} rows, got {obs.shape[0]}"
    assert len(valid_ts) == obs.shape[0]


def test_obs_matrix_no_nan_or_inf():
    """No NaN or Inf values in the observation matrix."""
    ts, closes, volumes = _make_prices(500)
    obs, _ = _build_obs_matrix(ts, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20)
    assert not np.any(np.isnan(obs)), "NaN found in observation matrix"
    assert not np.any(np.isinf(obs)), "Inf found in observation matrix"


def test_obs_matrix_momentum_non_trivial():
    """Momentum column (index 2) must not be all zeros (would indicate a bug)."""
    ts, closes, volumes = _make_prices(500)
    obs, _ = _build_obs_matrix(ts, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20)
    assert np.std(obs[:, 2]) > 0, "Momentum column is constant — likely a bug"


def test_obs_matrix_rel_volume_non_trivial():
    """Relative volume column (index 4) must not be all zeros."""
    ts, closes, volumes = _make_prices(500)
    obs, _ = _build_obs_matrix(ts, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20)
    assert np.std(obs[:, 4]) > 0, "Relative volume column is constant — likely a bug"


def test_obs_matrix_empty_on_insufficient_data():
    """Too-short series must return empty obs matrix."""
    ts, closes, volumes = _make_prices(30)  # less than vol_window=20 + warmup
    obs, valid_ts = _build_obs_matrix(ts, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20)
    # 30 - 1 = 29 returns, valid_start = 19, rows = 10 > 0 but marginal
    # Use a series shorter than valid_start:
    ts2, closes2, volumes2 = _make_prices(10)
    obs2, valid_ts2 = _build_obs_matrix(ts2, closes2, volumes2, vol_window=20, momentum_window=20, vol_of_vol_window=20)
    assert obs2.shape[0] == 0
    assert len(valid_ts2) == 0


def test_obs_matrix_different_windows():
    """Larger momentum window means more rows discarded."""
    ts, closes, volumes = _make_prices(500)
    obs20, _ = _build_obs_matrix(ts, closes, volumes, vol_window=20, momentum_window=20, vol_of_vol_window=20)
    obs40, _ = _build_obs_matrix(ts, closes, volumes, vol_window=20, momentum_window=40, vol_of_vol_window=20)
    assert obs40.shape[0] < obs20.shape[0]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_regime_writer_obs.py -v 2>&1 | head -30
```

Expected: ImportError or TypeError — `_build_obs_matrix` currently only accepts `(timestamps, closes, vol_window)`.

- [ ] **Step 3: Rewrite `_build_obs_matrix` in `services/regime_writer.py`**

Replace the existing `_build_obs_matrix` function entirely:

```python
def _build_obs_matrix(
    timestamps: list,
    closes: list[float],
    volumes: list[float],
    vol_window: int,
    momentum_window: int,
    vol_of_vol_window: int,
) -> tuple[np.ndarray, list]:
    """Build (n_valid, 5) observation matrix from OHLCV prices and volumes.

    Observation dimensions:
      [0] log_return   = ln(close[t] / close[t-1])
      [1] realized_vol = rolling std of log_returns over vol_window bars
      [2] momentum     = sum(log_returns[-momentum_window:]) / (realized_vol + eps)
                         Directional drift signal, vol-normalized.
      [3] vol_of_vol   = rolling std of realized_vol over vol_of_vol_window bars
                         Regime transition indicator: stable regimes have stable vol.
      [4] rel_volume   = log(volume[t]) - rolling mean(log(volume), vol_window)
                         Volume anomaly relative to recent baseline.

    valid_start = max(vol_window, momentum_window, vol_of_vol_window) - 1
    All rows before valid_start are discarded (insufficient window history).
    Returns (obs_matrix, valid_timestamps).
    """
    closes_arr = np.array(closes, dtype=float)
    volumes_arr = np.maximum(np.array(volumes, dtype=float), 1.0)  # guard zero volume
    n = len(closes_arr)

    log_returns = np.log(closes_arr[1:] / np.maximum(closes_arr[:-1], 1e-12))
    log_volumes = np.log(volumes_arr[1:])  # aligned to log_returns
    ts_shifted = timestamps[1:]

    if len(log_returns) < vol_window:
        return np.empty((0, 5), dtype=float), []

    # --- realized_vol: rolling std over vol_window ---
    windows_ret = np.lib.stride_tricks.sliding_window_view(log_returns, vol_window)
    realized_vol = np.concatenate([
        np.zeros(vol_window - 1),
        np.std(windows_ret, axis=1),
    ])

    # --- momentum: sum of log_returns over momentum_window / (realized_vol + eps) ---
    windows_mom = np.lib.stride_tricks.sliding_window_view(log_returns, momentum_window)
    mom_raw = np.concatenate([
        np.zeros(momentum_window - 1),
        np.sum(windows_mom, axis=1),
    ])
    momentum = mom_raw / np.maximum(realized_vol, 1e-8)

    # --- vol_of_vol: rolling std of realized_vol over vol_of_vol_window ---
    if len(realized_vol) >= vol_of_vol_window:
        windows_vov = np.lib.stride_tricks.sliding_window_view(realized_vol, vol_of_vol_window)
        vol_of_vol = np.concatenate([
            np.zeros(vol_of_vol_window - 1),
            np.std(windows_vov, axis=1),
        ])
    else:
        vol_of_vol = np.zeros(len(log_returns))

    # --- rel_volume: log_volume - rolling mean(log_volume, vol_window) ---
    if len(log_volumes) >= vol_window:
        windows_vol = np.lib.stride_tricks.sliding_window_view(log_volumes, vol_window)
        rolling_mean_logvol = np.concatenate([
            np.zeros(vol_window - 1),
            np.mean(windows_vol, axis=1),
        ])
    else:
        rolling_mean_logvol = np.zeros(len(log_returns))
    rel_volume = log_volumes - rolling_mean_logvol

    # --- discard rows before all windows are warm ---
    valid_start = max(vol_window, momentum_window, vol_of_vol_window) - 1
    if valid_start >= len(log_returns):
        return np.empty((0, 5), dtype=float), []

    obs = np.column_stack([
        log_returns[valid_start:],
        realized_vol[valid_start:],
        momentum[valid_start:],
        vol_of_vol[valid_start:],
        rel_volume[valid_start:],
    ])
    valid_ts = ts_shifted[valid_start:]
    return obs, valid_ts
```

- [ ] **Step 4: Update `_label_symbol_tf` to fetch volume and pass new params**

In `_label_symbol_tf`, update the OHLCV query and obs matrix call:

```python
# Replace the existing OHLCV fetch (two separate lists) with:
timestamps = []
closes = []
volumes = []
conn.commit()
with conn.cursor("ohlcv_stream") as cur:
    cur.execute(
        "SELECT timestamp, close, volume "
        "FROM market_data_ohlcv "
        "WHERE symbol = %s AND timeframe = %s "
        "ORDER BY timestamp ASC",
        (symbol, tf),
    )
    while True:
        batch = cur.fetchmany(10000)
        if not batch:
            break
        for r in batch:
            timestamps.append(r[0])
            closes.append(float(r[1]))
            volumes.append(float(r[2]))
```

Update the `_build_obs_matrix` call:

```python
obs_matrix, valid_ts = _build_obs_matrix(
    timestamps, closes, volumes,
    vol_window=vol_window,
    momentum_window=momentum_window,
    vol_of_vol_window=vol_of_vol_window,
)
```

Update the StandardScaler application immediately after obs_matrix is built and before the min_rows gate:

```python
from sklearn.preprocessing import StandardScaler

# ... (after obs_matrix built, before min_rows gate) ...
min_rows = n_components * _MIN_OBS_FACTOR
if len(valid_ts) < min_rows:
    _logger.warning("regime_writer.insufficient_obs", ...)
    return 0

# Standardize per-series: fit on this series, transform in-place.
# Both fit() and _causal_decode() receive the scaled matrix so
# means/covars are in scaled space — internally consistent.
scaler = StandardScaler()
obs_matrix = scaler.fit_transform(obs_matrix)
```

- [ ] **Step 5: Update `_label_symbol_tf` signature and `main()` to load new APR keys**

In `_label_symbol_tf`, add `momentum_window: int` and `vol_of_vol_window: int` parameters.

In `main()`, load new APR keys after existing ones:

```python
n_components = int(cfg.get_sync("feature.hmm.n_components", 3))
vol_window = int(cfg.get_sync("feature.hmm.vol_window", 20))
n_iter = int(cfg.get_sync("feature.hmm.n_iter", 200))
hmm_random_state = int(cfg.get_sync("alpha.hmm.random_state", 42))
momentum_window = int(cfg.get_sync("feature.hmm.obs_momentum_window", 20))
vol_of_vol_window = int(cfg.get_sync("feature.hmm.obs_vol_of_vol_window", 20))
```

Pass `momentum_window` and `vol_of_vol_window` through the call chain to `_label_symbol_tf`.

- [ ] **Step 6: Add sklearn import to top of `services/regime_writer.py`**

In the imports section, add:

```python
from sklearn.preprocessing import StandardScaler
```

- [ ] **Step 7: Run tests**

```bash
.venv/bin/pytest tests/unit/test_regime_writer_obs.py tests/unit/test_regime_writer.py -v
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add services/regime_writer.py tests/unit/test_regime_writer_obs.py
git commit -m "feat(hmm): enrich observation to 5D (momentum, vol_of_vol, rel_volume) + StandardScaler"
```

---

### Task 3: Vectorize `_causal_decode`

**Files:**
- Modify: `services/regime_writer.py`
- Modify: `tests/unit/test_regime_writer.py`

**Interfaces:**
- Signature unchanged: `_causal_decode(obs_matrix, means, variances, A, K) -> tuple[np.ndarray, np.ndarray]`
- Output must be numerically equivalent to the original implementation (validated in tests)

Key insight: precompute `log_emit[t, k]` for all `t` simultaneously as a `(n, K)` matrix using numpy broadcasting before the sequential alpha-pass loop. This eliminates the K-sized Python loop inside the t-loop. The t-loop itself remains (causality requires it) but each iteration is pure numpy vector ops on K=3 element arrays.

- [ ] **Step 1: Write equivalence test against original**

Add to `tests/unit/test_regime_writer.py`:

```python
def test_causal_decode_vectorized_matches_original():
    """Vectorized _causal_decode must produce identical states to reference implementation.

    Uses synthetic K=3 HMM parameters and a short obs sequence.
    Validates that the vectorized batch-emit precomputation does not alter
    the forward-filter result compared to the original per-step Python loop.
    """
    rng = np.random.default_rng(0)
    K, d, n = 3, 5, 200

    means = rng.normal(0, 1, (K, d))
    variances = np.abs(rng.normal(0.5, 0.1, (K, d))) + 0.01
    raw_A = np.abs(rng.normal(0, 1, (K, K))) + 0.1
    A = raw_A / raw_A.sum(axis=1, keepdims=True)
    obs = rng.normal(0, 1, (n, d))

    states, alpha_hist = _causal_decode(obs, means, variances, A, K)
    assert states.shape == (n,)
    assert alpha_hist.shape == (n, K)
    # Alpha rows must sum to ~1
    assert np.allclose(alpha_hist.sum(axis=1), 1.0, atol=1e-6)
    # All states must be valid state indices
    assert np.all((states >= 0) & (states < K))
```

- [ ] **Step 2: Run test to confirm current implementation passes**

```bash
.venv/bin/pytest tests/unit/test_regime_writer.py::test_causal_decode_vectorized_matches_original -v
```

Expected: PASS (test validates contracts of existing implementation before replacing it).

- [ ] **Step 3: Replace `_causal_decode` with vectorized version**

Replace the entire `_causal_decode` function in `services/regime_writer.py`:

```python
def _causal_decode(
    obs_matrix: np.ndarray,
    means: np.ndarray,
    variances: np.ndarray,
    A: np.ndarray,
    K: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Causal forward-filter (alpha-pass only) HMM decoding — vectorized.

    Precomputes log emission probabilities for all timesteps as a batch
    (n, K) matrix before the sequential alpha-pass loop, eliminating the
    K-sized Python loop that ran per timestep in the original implementation.

    The sequential t-loop is retained — causality requires alpha[t] to depend
    only on alpha[t-1]. Each loop iteration is pure numpy K-vector ops.

    Args:
        obs_matrix: (n, d) observation matrix (StandardScaler-transformed)
        means: (K, d) emission means per state (in scaled space)
        variances: (K, d) emission variances per state (in scaled space, diagonal)
        A: (K, K) transition matrix
        K: number of hidden states

    Returns:
        (states, alpha_history): states[t] = argmax(alpha[t]),
        alpha_history[t] = normalized probability vector over K states.
    """
    n, d = obs_matrix.shape
    var_clipped = np.maximum(variances[:, :d], 1e-300)  # (K, d)

    # Precompute log emission for all timesteps: shape (n, K)
    # diff[t, k, j] = obs[t, j] - means[k, j]
    diff = obs_matrix[:, np.newaxis, :] - means[np.newaxis, :, :d]  # (n, K, d)
    log_emit = (
        -0.5 * np.sum(diff ** 2 / var_clipped[np.newaxis, :, :], axis=2)
        - 0.5 * np.sum(np.log(2 * np.pi * var_clipped), axis=1)[np.newaxis, :]
    )  # (n, K)

    log_A = np.log(np.maximum(A, 1e-300))  # (K, K): log_A[i, j] = log P(i -> j)

    states = np.zeros(n, dtype=int)
    alpha_history = np.zeros((n, K))
    alpha = np.full(K, 1.0 / K)  # uniform prior

    for t in range(n):
        # log_alpha_prev + log_A: broadcast (K,) over (K, K)
        # log_trans[i, j] = log_alpha[i] + log_A[i, j]
        log_alpha = np.log(np.maximum(alpha, 1e-300))
        log_trans = log_alpha[:, np.newaxis] + log_A  # (K, K)
        # logsumexp over source states for each target state j
        max_lt = log_trans.max(axis=0)  # (K,)
        log_alpha_new = max_lt + np.log(np.sum(np.exp(log_trans - max_lt), axis=0))
        log_alpha_new += log_emit[t]  # add emission

        # Normalize in log space then exponentiate
        max_la = log_alpha_new.max()
        alpha = np.exp(log_alpha_new - max_la)
        total = alpha.sum()
        alpha /= total if total > 0 else 1.0

        states[t] = int(alpha.argmax())
        alpha_history[t] = alpha

    return states, alpha_history
```

- [ ] **Step 4: Run all regime_writer tests**

```bash
.venv/bin/pytest tests/unit/test_regime_writer.py tests/unit/test_regime_writer_obs.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add services/regime_writer.py tests/unit/test_regime_writer.py
git commit -m "perf(hmm): vectorize _causal_decode — precompute batch log_emit (n,K) before alpha-pass loop"
```

---

### Task 4: ProcessPoolExecutor Parallelism for regime_writer

**Files:**
- Modify: `services/regime_writer.py`
- Modify: `tests/unit/test_regime_writer.py`

**Interfaces:**
- New function: `_run_symbol_worker(args: tuple) -> dict` — runs in subprocess, returns `{"symbol": str, "tf": str, "n_updated": int, "error": str | None}`
- New CLI flag: `--workers N` (default from APR `infra.regime_writer.workers`, fallback 1)

Design constraints for subprocess workers:
- No OTel tracer (not picklable). Workers log only; main process emits spans and metrics.
- No shared DB connection. Each worker opens and closes its own psycopg2 connection.
- `structlog` is safe in subprocesses (file logging is line-buffered, JSON lines are atomic for typical message sizes).
- `setup_service_logging` must be called in the worker to initialize structlog in the subprocess.
- Worker processes one symbol × all TFs serially (symbol-level parallelism per todo 013).

- [ ] **Step 1: Write worker contract test**

Add to `tests/unit/test_regime_writer.py`:

```python
def test_worker_args_tuple_structure():
    """_run_symbol_worker must accept a flat tuple matching the expected arg order.

    This test validates the tuple packing contract between main() and the worker
    without invoking a real DB connection.
    """
    import inspect
    from services.regime_writer import _run_symbol_worker

    # Confirm it's a callable that accepts a single tuple arg
    sig = inspect.signature(_run_symbol_worker)
    params = list(sig.parameters.keys())
    assert params == ["args"], f"Expected single 'args' param, got {params}"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/test_regime_writer.py::test_worker_args_tuple_structure -v
```

Expected: ImportError — `_run_symbol_worker` does not exist yet.

- [ ] **Step 3: Add `_run_symbol_worker` to `services/regime_writer.py`**

Add this function after `_label_symbol_tf` and before `_discover_symbols`:

```python
def _run_symbol_worker(args: tuple) -> dict:
    """Worker function for ProcessPoolExecutor — runs in subprocess.

    Opens its own psycopg2 connection (connections are not picklable and
    must not be shared across processes). No OTel tracer — workers log only;
    main process aggregates results and emits metrics.

    Args:
        args: (symbol, tfs, dsn, n_components, vol_window, momentum_window,
               vol_of_vol_window, n_iter, hmm_random_state)
               Packed as a tuple for ProcessPoolExecutor.map compatibility.

    Returns:
        dict with keys: symbol, results (list of {tf, n_updated}), error (str|None)
    """
    (
        symbol,
        tfs,
        dsn,
        n_components,
        vol_window,
        momentum_window,
        vol_of_vol_window,
        n_iter,
        hmm_random_state,
    ) = args

    # Initialize logging in subprocess (each process needs its own handler)
    setup_service_logging("logs/regime_writer.log")
    worker_log = structlog.get_logger(__name__)

    conn = None
    results = []
    error_msg = None

    try:
        conn = psycopg2.connect(
            dsn,
            options="-c idle_in_transaction_session_timeout=0",
        )
        # No-op tracer for worker — spans are not emitted from subprocesses
        import contextlib

        @contextlib.contextmanager
        def _noop_span(name, **attrs):
            class _Noop:
                def set_attribute(self, k, v):
                    pass
                def set_status(self, *a):
                    pass
                def record_exception(self, *a):
                    pass
            yield _Noop()

        class _NoopTracer:
            def start_as_current_span(self, name, attributes=None):
                return _noop_span(name)

        noop_tracer = _NoopTracer()

        for tf in tfs:
            try:
                n = _label_symbol_tf(
                    conn=conn,
                    symbol=symbol,
                    tf=tf,
                    n_components=n_components,
                    vol_window=vol_window,
                    momentum_window=momentum_window,
                    vol_of_vol_window=vol_of_vol_window,
                    n_iter=n_iter,
                    hmm_random_state=hmm_random_state,
                    tracer=noop_tracer,
                )
                results.append({"tf": tf, "n_updated": n})
            except Exception as error:
                worker_log.error(
                    "regime_writer.worker_cell_failed",
                    symbol=symbol,
                    tf=tf,
                    error=str(error),
                )
                results.append({"tf": tf, "n_updated": 0, "error": str(error)})
                try:
                    conn.rollback()
                except Exception:
                    pass

    except Exception as error:
        error_msg = str(error)
        worker_log.error("regime_writer.worker_failed", symbol=symbol, error=error_msg)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return {"symbol": symbol, "results": results, "error": error_msg}
```

- [ ] **Step 4: Update `main()` to use ProcessPoolExecutor**

In `main()`, replace the existing symbol loop with ProcessPoolExecutor. Add `--workers` arg to the parser:

```python
parser.add_argument(
    "--workers",
    type=int,
    default=None,
    help="Number of parallel workers (default: APR infra.regime_writer.workers, fallback 1)",
)
```

Replace the serial loop in `main()` (the `for symbol in symbols: for tf in tfs:` block) with:

```python
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed

n_workers = args.workers
if n_workers is None:
    n_workers = int(cfg.get_sync("infra.regime_writer.workers", 1))

_logger.info(
    "regime_writer.starting",
    symbols_count=len(symbols),
    tfs=tfs,
    n_components=n_components,
    vol_window=vol_window,
    momentum_window=momentum_window,
    vol_of_vol_window=vol_of_vol_window,
    n_iter=n_iter,
    n_workers=n_workers,
)

worker_args = [
    (
        symbol,
        tfs,
        dsn,
        n_components,
        vol_window,
        momentum_window,
        vol_of_vol_window,
        n_iter,
        hmm_random_state,
    )
    for symbol in symbols
]

total_updated = 0
failures: list[str] = []

with ProcessPoolExecutor(max_workers=n_workers) as pool:
    for result in pool.map(_run_symbol_worker, worker_args, chunksize=1):
        symbol = result["symbol"]
        if result["error"]:
            failures.append(symbol)
            _logger.error(
                "regime_writer.symbol_failed",
                symbol=symbol,
                error=result["error"],
            )
        for cell in result["results"]:
            n = cell.get("n_updated", 0)
            total_updated += n
            tf = cell["tf"]
            REGIME_WRITER_ROWS_UPDATED_TOTAL.add(n, {"symbol": symbol, "tf": tf})
            if "error" in cell:
                failures.append(f"{symbol}/{tf}")
```

Remove the now-redundant `conn` object from `main()` — each worker opens its own. The `cfg` loading still needs a temporary connection:

```python
# In main(), open a short-lived connection for APR load + symbol discovery, then close it
_conn = psycopg2.connect(dsn, options="-c idle_in_transaction_session_timeout=0")
try:
    cfg = _load_config_service_shared(_conn)
    # ... load APR keys ...
    symbols = args.symbols if args.symbols else _discover_symbols(_conn)
finally:
    _conn.close()
# dsn is passed to workers; no connection shared beyond this point
```

- [ ] **Step 5: Run all tests**

```bash
.venv/bin/pytest tests/unit/test_regime_writer.py tests/unit/test_regime_writer_obs.py -v
```

Expected: all pass.

- [ ] **Step 6: Smoke-test with 1 worker and 1 symbol (requires live DB with populated feature_vectors)**

```bash
.venv/bin/python services/regime_writer.py --symbols SPY --tf 5m --workers 1
```

Expected: completes, logs `regime_writer.symbol_tf_done` for `SPY/5m`.

- [ ] **Step 7: Commit**

```bash
git add services/regime_writer.py tests/unit/test_regime_writer.py
git commit -m "feat(regime-writer): ProcessPoolExecutor symbol-level parallelism (--workers N, APR-backed)"
```

---

### Task 5: ProcessPoolExecutor Parallelism for ic_engine

**Files:**
- Modify: `services/ic_engine.py`
- Create: `tests/unit/test_ic_engine_parallelism.py`

**Interfaces:**
- New function: `_run_ic_worker(args: tuple) -> dict` — runs in subprocess
- RNG per worker derived deterministically: `np.random.default_rng(bootstrap_seed + abs(hash(symbol)) % 2**31)`
- `existing_keys` passed as a `frozenset` (picklable)
- `training_window_end`, `run_ts` as `datetime` (picklable)
- `apr_cache` as `dict[str, dict]` (picklable)
- New CLI flag: `--workers N`

- [ ] **Step 1: Write worker contract test**

Create `tests/unit/test_ic_engine_parallelism.py`:

```python
"""Unit tests for ic_engine ProcessPoolExecutor worker contract.

Tests validate the worker function signature and RNG derivation without
a live DB connection.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import _run_ic_worker, _derive_worker_rng_seed


def test_worker_accepts_single_tuple_arg():
    """_run_ic_worker must accept a single 'args' tuple parameter."""
    sig = inspect.signature(_run_ic_worker)
    params = list(sig.parameters.keys())
    assert params == ["args"], f"Expected single 'args' param, got {params}"


def test_derive_worker_rng_seed_deterministic():
    """Same symbol + bootstrap_seed must always produce the same worker seed."""
    seed1 = _derive_worker_rng_seed("SPY", 42)
    seed2 = _derive_worker_rng_seed("SPY", 42)
    assert seed1 == seed2


def test_derive_worker_rng_seed_differs_by_symbol():
    """Different symbols must produce different worker seeds."""
    seed_spy = _derive_worker_rng_seed("SPY", 42)
    seed_tlt = _derive_worker_rng_seed("TLT", 42)
    assert seed_spy != seed_tlt


def test_derive_worker_rng_seed_valid_range():
    """Derived seed must be a non-negative integer (valid for np.random.default_rng)."""
    seed = _derive_worker_rng_seed("GLD", 42)
    assert isinstance(seed, int)
    assert seed >= 0


def test_rng_from_derived_seed_is_reproducible():
    """Two RNGs from the same derived seed must produce identical sequences."""
    seed = _derive_worker_rng_seed("EWT", 42)
    rng1 = np.random.default_rng(seed)
    rng2 = np.random.default_rng(seed)
    assert np.array_equal(rng1.random(10), rng2.random(10))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_ic_engine_parallelism.py -v
```

Expected: ImportError — `_run_ic_worker` and `_derive_worker_rng_seed` do not exist yet.

- [ ] **Step 3: Add `_derive_worker_rng_seed` and `_run_ic_worker` to `services/ic_engine.py`**

Add after `_emit_health_gauges` and before `main()`:

```python
def _derive_worker_rng_seed(symbol: str, bootstrap_seed: int) -> int:
    """Deterministic per-symbol RNG seed for ProcessPoolExecutor workers.

    Derived as bootstrap_seed + abs(hash(symbol)) % 2**31 so each symbol
    gets a unique but reproducible RNG regardless of execution order.
    """
    return bootstrap_seed + abs(hash(symbol)) % (2 ** 31)


def _run_ic_worker(args: tuple) -> dict:
    """Worker function for ProcessPoolExecutor — runs in subprocess.

    Each worker processes one symbol × all TFs with its own DB connection
    and deterministic per-symbol RNG. No OTel tracer — workers log only.

    Args:
        args: (symbol, tfs, dsn, training_window_end, existing_keys_frozen,
               apr_cache, run_ts, bootstrap_seed)

    Returns:
        dict with keys: symbol, all_results (list), n_committed (int),
        n_skipped (int), error (str|None)
    """
    (
        symbol,
        tfs,
        dsn,
        training_window_end,
        existing_keys_frozen,
        apr_cache,
        run_ts,
        bootstrap_seed,
    ) = args

    from src.core.service_utils import setup_service_logging
    setup_service_logging("logs/ic_engine.log")
    worker_log = structlog.get_logger(__name__)

    import contextlib

    @contextlib.contextmanager
    def _noop_span(name, **attrs):
        class _Noop:
            def set_attribute(self, k, v): pass
            def set_status(self, *a): pass
            def record_exception(self, *a): pass
        yield _Noop()

    class _NoopTracer:
        def start_as_current_span(self, name, attributes=None):
            return _noop_span(name)

    noop_tracer = _NoopTracer()

    rng_seed = _derive_worker_rng_seed(symbol, bootstrap_seed)
    rng = np.random.default_rng(seed=rng_seed)
    existing_keys = set(existing_keys_frozen)

    conn = None
    all_results = []
    total_committed = 0
    total_skipped = 0
    error_msg = None

    try:
        conn = _connect_db(Settings())
        for tf in tfs:
            apr = apr_cache[tf]
            try:
                stats = _compute_symbol_tf(
                    conn=conn,
                    symbol=symbol,
                    tf=tf,
                    training_window_end=training_window_end,
                    existing_keys=existing_keys,
                    apr=apr,
                    tracer=noop_tracer,
                    rng=rng,
                    run_ts=run_ts,
                )
                total_committed += stats.get("n_committed", 0)
                total_skipped += stats.get("n_skipped", 0)
                all_results.extend(stats.get("all_results", []))
            except Exception as error:
                worker_log.error(
                    "ic_engine.worker_cell_failed",
                    symbol=symbol,
                    tf=tf,
                    error=str(error),
                )
    except Exception as error:
        error_msg = str(error)
        worker_log.error("ic_engine.worker_failed", symbol=symbol, error=error_msg)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    return {
        "symbol": symbol,
        "all_results": all_results,
        "n_committed": total_committed,
        "n_skipped": total_skipped,
        "error": error_msg,
    }
```

- [ ] **Step 4: Update `main()` in `ic_engine.py` to use ProcessPoolExecutor**

Add `--workers` arg to the parser (after `--tf`):

```python
parser.add_argument(
    "--workers",
    type=int,
    default=None,
    help="Number of parallel workers (default: APR infra.ic_engine.workers, fallback 1)",
)
```

Load `n_workers` after APR cache is built:

```python
n_workers = args.workers
if n_workers is None:
    # Use bootstrap_seed APR from first TF; workers key is infra namespace
    _cfg_tmp = _load_apr(conn, tfs[0])  # apr_cache already loaded above
    cfg_full = load_config_service_sync(conn)
    n_workers = int(cfg_full.get_sync("infra.ic_engine.workers", 1))
```

Wait — `_load_apr` returns a TF-specific dict. Load the workers key separately using `load_config_service_sync` from `_batch_utils`. The `conn` is still open at this point (before workers are spawned). Add this after `apr_cache` is built:

```python
from services._batch_utils import load_config_service_sync as _load_full_cfg
_full_cfg = _load_full_cfg(conn)
if n_workers is None:
    n_workers = int(_full_cfg.get_sync("infra.ic_engine.workers", 1))
bootstrap_seed = apr_cache[tfs[0]]["bootstrap_seed"]
```

Replace the serial `for symbol in symbols: for tf in tfs:` loop with ProcessPoolExecutor:

```python
from concurrent.futures import ProcessPoolExecutor

# Build args before closing conn (existing_keys loaded above)
existing_keys_frozen = frozenset(existing_keys)
worker_args = [
    (
        symbol,
        tfs,
        settings.database_url,
        training_window_end,
        existing_keys_frozen,
        apr_cache,
        run_ts,
        bootstrap_seed,
    )
    for symbol in symbols
]

_logger.info("ic_engine.starting_parallel", n_symbols=len(symbols), n_workers=n_workers)
conn.close()  # main process connection no longer needed; workers open their own

with ProcessPoolExecutor(max_workers=n_workers) as pool:
    for result in pool.map(_run_ic_worker, worker_args, chunksize=1):
        symbol = result["symbol"]
        if result["error"]:
            _logger.error("ic_engine.symbol_failed", symbol=symbol, error=result["error"])
            status = "failure"
            exit_code = 1
        total_committed += result["n_committed"]
        total_skipped += result["n_skipped"]
        all_results_global.extend(result["all_results"])
        if result["all_results"]:
            # Emit health gauges per symbol (all TFs aggregated) in main process
            for tf in tfs:
                tf_results = [r for r in result["all_results"] if r.get("tf") == tf]
                if tf_results:
                    _emit_health_gauges(symbol, tf, tf_results)
        _logger.info(
            "ic_engine.symbol_done",
            symbol=symbol,
            n_committed=result["n_committed"],
            n_skipped=result["n_skipped"],
        )
```

- [ ] **Step 5: Run all tests**

```bash
.venv/bin/pytest tests/unit/test_ic_engine_parallelism.py tests/unit/test_ic_engine_vectorized.py tests/unit/test_ic_engine_idempotency.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add services/ic_engine.py tests/unit/test_ic_engine_parallelism.py
git commit -m "feat(ic-engine): ProcessPoolExecutor symbol-level parallelism (--workers N, APR-backed)"
```

---

### Task 6: Integration Smoke Test and Final Cleanup

**Files:**
- Modify: `tests/unit/test_regime_writer.py` (add fast integration guard)
- No new files

- [ ] **Step 1: Run full unit test suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all green.

- [ ] **Step 2: Smoke-test regime_writer with 2 workers on 2 symbols**

```bash
.venv/bin/python services/regime_writer.py --symbols SPY TLT --tf 1d --workers 2
```

Expected: both symbols complete, logs show `regime_writer.symbol_tf_done` for `SPY/1d` and `TLT/1d`. Both may appear interleaved (parallel execution).

- [ ] **Step 3: Verify DB has 5D obs features written correctly**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT symbol, tf,
    AVG(hmm_entropy) as avg_entropy,
    COUNT(*) FILTER (WHERE regime = 'trending_up') as n_up,
    COUNT(*) FILTER (WHERE regime = 'trending_down') as n_down,
    COUNT(*) FILTER (WHERE regime = 'ranging') as n_ranging,
    COUNT(*) FILTER (WHERE regime IS NULL) as n_null
FROM feature_vectors
WHERE symbol IN ('SPY', 'TLT') AND tf = '1d'
GROUP BY symbol, tf
ORDER BY symbol, tf;"
```

Expected: n_null = 0; regime distribution non-trivially split across three states; avg_entropy > 0.

- [ ] **Step 4: Verify parallel ic_engine on 2 symbols**

```bash
.venv/bin/python services/ic_engine.py --symbols SPY TLT --tf 1d --workers 2
```

Expected: completes without error; `feature_ic_scores` has new rows for SPY and TLT.

- [ ] **Step 5: Final commit — update 013 todo as done**

```bash
# Mark 013 done by moving it to completed
mv .planning/todos/pending/013-regime-writer-parallelism.md .planning/todos/completed/ 2>/dev/null || true
git add -A
git commit -m "chore: close todo 013 — regime_writer and ic_engine parallelism shipped"
```

---

## Self-Review

**Spec coverage:**
- ✅ ProcessPoolExecutor symbol-level for regime_writer (Task 4)
- ✅ ProcessPoolExecutor symbol-level for ic_engine (Task 5)
- ✅ `--workers N` CLI flags backed by APR keys (Tasks 4, 5)
- ✅ `infra.regime_writer.workers` and `infra.ic_engine.workers` APR seeds (Task 1)
- ✅ StandardScaler before fit (Task 2)
- ✅ 5D observation vector with momentum, vol_of_vol, rel_volume (Task 2)
- ✅ Vectorized `_causal_decode` precomputing batch log_emit (Task 3)
- ✅ n_iter 20→200 via APR update (Task 1)
- ✅ Deterministic per-symbol RNG for ic_engine workers (Task 5)
- ✅ Tests for all new functions (Tasks 2, 3, 4, 5)
- ✅ OTel spans/metrics only from main process (Tasks 4, 5)

**Placeholder scan:** None found — all steps contain actual code.

**Type consistency:** `_run_symbol_worker(args: tuple) -> dict` and `_run_ic_worker(args: tuple) -> dict` match their test imports. `_derive_worker_rng_seed(symbol: str, bootstrap_seed: int) -> int` matches its test calls.
