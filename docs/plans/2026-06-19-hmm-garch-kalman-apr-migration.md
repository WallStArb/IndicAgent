# HMM / GARCH / Kalman APR Migration Plan

**Status (verified 2026-07-18, docs reconciliation pass):** COMPLETE. Migration 153
(`production/migrations/153_hmm_garch_kalman_apr.sql`) exists and matches this plan's intent
exactly; `src/intelligence/services/hmm_trainer.py` uses the `_config_service`/`ConfigService`
pattern described below. Never had a status line or ROADMAP/todo cross-reference, so it read as
orphaned during an audit — it wasn't, just undocumented. No further action.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move all hardcoded numeric hyperparameters in `hmm_trainer.py`, `garch_volatility.py`, and `kalman_trend.py` into the Adaptive Parameter Registry so they surface in the `/config/parameters` dashboard and become ML learning targets.

**Architecture:** Three source files each contribute constants to a single SQL migration (migration 153). GARCH and Kalman are plugin dataclasses — they use the `_config_service` field + auto-injection pattern already wired in `_prewarm_threshold_config`. HMMTrainer is a standalone oneshot service — it instantiates ConfigService directly inside `run()` using the existing DB pool.

**Tech Stack:** asyncpg, ConfigService (`src/config/config_service.py`), SQL migration in `production/migrations/`, existing APR dashboard at `/config/parameters`.

## Global Constraints

- All APR keys must start with `feature.hmm.*`, `feature.garch.*`, or `feature.kalman.*`
- Migration file: `production/migrations/153_hmm_garch_kalman_apr.sql` — idempotent, ON CONFLICT DO NOTHING
- `config_schema` column is `config_key` (not `key`)
- Description format: `[conventional] <explanation>. ML learning target: <yes/no + rationale>.`
- `get_sync()` requires pre-warmed cache — always call `await cfg.get(key, default)` first in async context before `get_sync()`
- GARCH/Kalman auto-inject via the loop in `_prewarm_threshold_config` (lines 562-568) — no changes to that method needed beyond adding keys to `_THRESHOLD_KEYS`
- Run `.venv/bin/pytest tests/unit/ -q` after every task — must be green
- Done-coding SOP: simplify → review → test → commit → push

---

## Parameters Being Migrated

| APR Key | Type | Default | Source file | Constant name |
|---|---|---|---|---|
| `feature.hmm.n_components` | int | 3 | hmm_trainer.py | `_N_COMPONENTS` |
| `feature.hmm.n_iter` | int | 50 | hmm_trainer.py | `_N_ITER` |
| `feature.hmm.min_rows_for_training` | int | 500 | hmm_trainer.py | `_MIN_ROWS_FOR_TRAINING` |
| `feature.hmm.vol_window` | int | 20 | hmm_trainer.py | `vol_window` (inline) |
| `feature.hmm.lookback_days.1m` | int | 30 | hmm_trainer.py | `_LOOKBACK_DAYS_BY_TF["1m"]` |
| `feature.hmm.lookback_days.5m` | int | 60 | hmm_trainer.py | `_LOOKBACK_DAYS_BY_TF["5m"]` |
| `feature.hmm.lookback_days.15m` | int | 90 | hmm_trainer.py | `_LOOKBACK_DAYS_BY_TF["15m"]` |
| `feature.hmm.lookback_days.1h` | int | 180 | hmm_trainer.py | `_LOOKBACK_DAYS_BY_TF["1h"]` |
| `feature.hmm.lookback_days.4h` | int | 365 | hmm_trainer.py | `_LOOKBACK_DAYS_BY_TF["4h"]` |
| `feature.hmm.lookback_days.1d` | int | 730 | hmm_trainer.py | `_LOOKBACK_DAYS_BY_TF["1d"]` |
| `feature.garch.omega` | float | 0.00001 | garch_volatility.py | `omega` field |
| `feature.garch.alpha` | float | 0.10 | garch_volatility.py | `alpha` field |
| `feature.garch.beta` | float | 0.85 | garch_volatility.py | `beta` field |
| `feature.kalman.garch_r_scale` | float | 10000.0 | kalman_trend.py | `_GARCH_R_SCALE` |

---

## Task 1: DB Migration — config_schema + config_state

**Files:**
- Create: `production/migrations/153_hmm_garch_kalman_apr.sql`

**Interfaces:**
- Produces: 14 new APR keys readable by ConfigService

- [ ] **Step 1: Write the migration file**

```sql
-- Migration 153: HMM trainer, GARCH, and Kalman hyperparameter APR keys.
--
-- Moves hardcoded numeric constants from hmm_trainer.py, garch_volatility.py,
-- and kalman_trend.py into the Adaptive Parameter Registry so they surface
-- in /config/parameters and become ML learning targets.
--
-- All inserts are idempotent: ON CONFLICT (config_key) DO NOTHING.
-- Safe to re-run.

-- -------------------------------------------------------------------------
-- config_schema entries
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'feature.hmm.n_components',
    'int',
    '3',
    2, 10,
    '[conventional] Number of hidden states in the GaussianHMM. 3 = ranging/trending-up/trending-down; conventional choice for price regime classification. Not an ML learning target (changes model topology, requires full retraining).'
),
(
    'feature.hmm.n_iter',
    'int',
    '50',
    10, 500,
    '[conventional] Maximum Baum-Welch EM iterations for GaussianHMM training. 50 is standard; increase if convergence warnings appear. Not an ML learning target.'
),
(
    'feature.hmm.min_rows_for_training',
    'int',
    '500',
    100, 10000,
    '[conventional] Minimum valid observation rows per TF required to attempt Baum-Welch training. Below this threshold the TF is skipped. Not an ML learning target.'
),
(
    'feature.hmm.vol_window',
    'int',
    '20',
    5, 100,
    '[conventional] Rolling window (bars) for realized volatility computation in the HMM observation vector. Must match HMMRegimePlugin.vol_window for trainer/inference consistency. Not an ML learning target.'
),
(
    'feature.hmm.lookback_days.1m',
    'int',
    '30',
    7, 180,
    '[conventional] Training query lookback in days for 1m bars (~43,200 bars on liquid futures). Not an ML learning target.'
),
(
    'feature.hmm.lookback_days.5m',
    'int',
    '60',
    14, 365,
    '[conventional] Training query lookback in days for 5m bars (~17,280 bars). Not an ML learning target.'
),
(
    'feature.hmm.lookback_days.15m',
    'int',
    '90',
    30, 365,
    '[conventional] Training query lookback in days for 15m bars (~8,640 bars). Not an ML learning target.'
),
(
    'feature.hmm.lookback_days.1h',
    'int',
    '180',
    60, 730,
    '[conventional] Training query lookback in days for 1h bars (~4,320 bars). Not an ML learning target.'
),
(
    'feature.hmm.lookback_days.4h',
    'int',
    '365',
    90, 730,
    '[conventional] Training query lookback in days for 4h bars (~2,190 bars). Not an ML learning target.'
),
(
    'feature.hmm.lookback_days.1d',
    'int',
    '730',
    180, 1825,
    '[conventional] Training query lookback in days for 1d bars (~730 bars). Not an ML learning target.'
),
(
    'feature.garch.omega',
    'float',
    '0.00001',
    0.000001, 0.001,
    '[conventional] GARCH(1,1) long-run variance intercept (omega). Standard prior for equity/futures returns; controls unconditional variance floor. ML learning target: tune per instrument class after sufficient trade_frames with counterfactual_pnl_r (n >= 100).'
),
(
    'feature.garch.alpha',
    'float',
    '0.10',
    0.01, 0.50,
    '[conventional] GARCH(1,1) shock coefficient (alpha). Weight on lagged squared return epsilon^2. Standard prior; 0.10 is conventional for daily-frequency equity series. ML learning target. Constraint: alpha + beta < 1 for stationarity.'
),
(
    'feature.garch.beta',
    'float',
    '0.85',
    0.50, 0.99,
    '[conventional] GARCH(1,1) persistence coefficient (beta). Weight on lagged conditional variance. 0.85 is conventional; high persistence typical of equity vol. ML learning target. Constraint: alpha + beta < 1 for stationarity.'
),
(
    'feature.kalman.garch_r_scale',
    'float',
    '10000.0',
    100.0, 1000000.0,
    '[conventional] Scale factor applied to garch_sigma when computing adaptive measurement noise R for the Kalman filter. R_adaptive = (garch_sigma * scale)^2. garch_sigma is in log-return units (~0.001-0.02); scale maps to R range 0.1-40 in price units. ML learning target: tune per instrument class after Phase 133 corpus.'
)
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_state entries (seed values = defaults)
-- -------------------------------------------------------------------------

INSERT INTO config_state (config_key, config_value, version) VALUES
('feature.hmm.n_components', '3', 1),
('feature.hmm.n_iter', '50', 1),
('feature.hmm.min_rows_for_training', '500', 1),
('feature.hmm.vol_window', '20', 1),
('feature.hmm.lookback_days.1m', '30', 1),
('feature.hmm.lookback_days.5m', '60', 1),
('feature.hmm.lookback_days.15m', '90', 1),
('feature.hmm.lookback_days.1h', '180', 1),
('feature.hmm.lookback_days.4h', '365', 1),
('feature.hmm.lookback_days.1d', '730', 1),
('feature.garch.omega', '0.00001', 1),
('feature.garch.alpha', '0.10', 1),
('feature.garch.beta', '0.85', 1),
('feature.kalman.garch_r_scale', '10000.0', 1)
ON CONFLICT (config_key) DO NOTHING;
```

- [ ] **Step 2: Apply the migration**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent \
  -f production/migrations/153_hmm_garch_kalman_apr.sql
```

Expected: `INSERT 0 14` twice (or `INSERT 0 N` where N <= 14 if some already exist).

- [ ] **Step 3: Verify keys are present**

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT cs.config_key, cs.config_value, sch.value_type
FROM config_state cs
JOIN config_schema sch USING (config_key)
WHERE cs.config_key LIKE 'feature.hmm.%'
   OR cs.config_key LIKE 'feature.garch.%'
   OR cs.config_key LIKE 'feature.kalman.%'
ORDER BY cs.config_key;
"
```

Expected: 14 rows with correct types and values.

- [ ] **Step 4: Commit**

```bash
git add production/migrations/153_hmm_garch_kalman_apr.sql
git commit -m "migration(153): APR keys for HMM trainer, GARCH, and Kalman hyperparameters"
```

---

## Task 2: HMMTrainer — load hyperparameters from APR

**Files:**
- Modify: `src/intelligence/services/hmm_trainer.py`
- Modify: `tests/unit/services/test_hmm_trainer.py`

**Interfaces:**
- Consumes: Task 1 (migration 153 applied — keys exist in DB)
- Produces: HMMTrainer reads `feature.hmm.*` from APR at `run()` time; module-level constants become fallback defaults only

**Pattern:** HMMTrainer has `self._db` (DatabaseManager with `self._db.pool`). Instantiate `ConfigService(database_url, pool=self._db.pool)` inside `run()` — reuses the existing pool, no new connections. Call `await cfg.get(key, default)` for each key to warm cache, then read via `get_sync()` or just use the returned values directly.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/services/test_hmm_trainer.py`:

```python
def test_hmm_trainer_reads_apr_config(tmp_path: Path) -> None:
    """HMMTrainer must load n_components, n_iter, min_rows, vol_window from APR.

    When _config_service is injected, training uses APR values instead of
    module-level constants.
    """
    from unittest.mock import AsyncMock, MagicMock
    from src.config.config_service import ConfigService

    rows = _make_synthetic_rows(_N_TRAIN_ROWS)
    db = _make_db_manager({"1m": rows})

    # Build a ConfigService with known values that differ from defaults
    mock_cfg = MagicMock(spec=ConfigService)
    mock_cfg.get = AsyncMock(side_effect=lambda key, default=None: {
        "feature.hmm.n_components": 3,
        "feature.hmm.n_iter": 10,           # reduced — faster test
        "feature.hmm.min_rows_for_training": 50,
        "feature.hmm.vol_window": 10,
        "feature.hmm.lookback_days.1m": 30,
        "feature.hmm.lookback_days.5m": 60,
        "feature.hmm.lookback_days.15m": 90,
        "feature.hmm.lookback_days.1h": 180,
        "feature.hmm.lookback_days.4h": 365,
        "feature.hmm.lookback_days.1d": 730,
    }.get(key, default))

    import src.intelligence.services.hmm_trainer as _mod
    original = _mod._CONFIG_DIR
    _mod._CONFIG_DIR = tmp_path
    try:
        agent = HMMTrainer(db_manager=db, settings=_make_settings(), target_tfs=("1m",))
        agent._config_service = mock_cfg
        written = asyncio.run(agent.run())
    finally:
        _mod._CONFIG_DIR = original

    assert "1m" in written, "1m should have been written when APR config is injected"
    mock_cfg.get.assert_any_call("feature.hmm.n_iter", 50)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/services/test_hmm_trainer.py::test_hmm_trainer_reads_apr_config -v
```

Expected: FAIL — `HMMTrainer` has no `_config_service` attribute.

- [ ] **Step 3: Implement APR loading in HMMTrainer**

In `src/intelligence/services/hmm_trainer.py`:

1. Add `_config_service: Any | None = None` instance field in `__init__`:

```python
def __init__(
    self,
    db_manager: Any,
    settings: Settings,
    target_tfs: tuple[str, ...] = _DEFAULT_TARGET_TFS,
    lookback_days: dict[str, int] | None = None,
) -> None:
    setup_service_logging("logs/hmm_trainer.log")
    self._db = db_manager
    self._settings = settings
    self._target_tfs = target_tfs
    self._lookback_days = lookback_days or dict(_LOOKBACK_DAYS_BY_TF)
    self._config_service: Any | None = None
```

2. Add `_load_apr_config()` async method that loads all APR keys and updates instance state:

```python
async def _load_apr_config(self) -> None:
    """Load HMM hyperparameters from APR, falling back to module-level defaults."""
    from src.config.config_service import ConfigService  # noqa: PLC0415

    cfg = self._config_service
    if cfg is None:
        cfg = ConfigService(self._settings.database_url, pool=self._db.pool)

    self._n_components = int(await cfg.get("feature.hmm.n_components", _N_COMPONENTS))
    self._n_iter = int(await cfg.get("feature.hmm.n_iter", _N_ITER))
    self._min_rows = int(await cfg.get("feature.hmm.min_rows_for_training", _MIN_ROWS_FOR_TRAINING))
    self._vol_window = int(await cfg.get("feature.hmm.vol_window", 20))

    for tf in self._target_tfs:
        key = f"feature.hmm.lookback_days.{tf}"
        fallback = self._lookback_days.get(tf, 60)
        self._lookback_days[tf] = int(await cfg.get(key, fallback))
```

3. Call `_load_apr_config()` at the top of `run()`:

```python
async def run(self) -> dict[str, str]:
    await self._load_apr_config()
    written: dict[str, str] = {}
    ...
```

4. Replace all uses of module-level constants with instance attributes:
   - `_N_COMPONENTS` → `self._n_components`
   - `_N_ITER` → `self._n_iter`
   - `_MIN_ROWS_FOR_TRAINING` → `self._min_rows`
   - `vol_window = 20` (inline in `_build_symbol_obs`) → `self._vol_window`

   In `_train_tf`:
   ```python
   if n_rows < self._min_rows:
       logger.info(
           "hmm_training.insufficient_rows",
           tf=tf, n=n_rows, required=self._min_rows, reason="skipping training",
       )
   ```

   In `_fit_hmm`, replace:
   ```python
   model = hmmlib.GaussianHMM(
       n_components=self._n_components,
       covariance_type=_COVARIANCE_TYPE,
       n_iter=self._n_iter,
   )
   ```
   And update the params dict:
   ```python
   "n_components": self._n_components,
   ```
   And the start_prob prior in `_write_params`/`start_prob` calls if any.

   In `_build_symbol_obs`, replace the inline `vol_window = 20`:
   ```python
   vol_window = getattr(self, "_vol_window", 20)
   ```
   (getattr with fallback since `_build_symbol_obs` can be called before `_load_apr_config` in tests)

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/unit/services/test_hmm_trainer.py -v
```

Expected: all 8 tests pass (7 original + 1 new).

- [ ] **Step 5: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/services/hmm_trainer.py tests/unit/services/test_hmm_trainer.py
git commit -m "feat(hmm-trainer): load n_components/n_iter/min_rows/vol_window/lookback from APR"
```

---

## Task 3: GARCHVolatilityPlugin — read omega/alpha/beta from APR

**Files:**
- Modify: `src/intelligence/context/garch_volatility.py`
- Modify: `tests/unit/intelligence/test_garch_volatility.py`

**Interfaces:**
- Consumes: Task 1 (migration 153 applied)
- Produces: GARCHVolatilityPlugin reads `feature.garch.*` via `_config_service.get_sync()` with dataclass-field defaults as fallback

**Pattern:** Plugin dataclass. Add `_config_service: Any = field(default=None, compare=False, repr=False)`. At compute time, read via `cfg.get_sync(key, self.omega)` where `self.omega` stays as the dataclass default fallback. The auto-injection loop in `_prewarm_threshold_config` (lines 562-568 of `services/intelligence_pipeline.py`) already handles injection — no changes to that file beyond adding keys to `_THRESHOLD_KEYS` (Task 5).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/intelligence/test_garch_volatility.py`:

```python
def test_garch_reads_apr_config() -> None:
    """GARCHVolatilityPlugin must read omega/alpha/beta from _config_service when injected."""
    from unittest.mock import MagicMock

    plugin = GARCHVolatilityPlugin()

    mock_cfg = MagicMock()
    mock_cfg.get_sync.side_effect = lambda key, default=None: {
        "feature.garch.omega": 0.00002,   # doubled from default
        "feature.garch.alpha": 0.20,       # doubled from default
        "feature.garch.beta": 0.75,        # different from default
    }.get(key, default)

    plugin._config_service = mock_cfg

    df = _make_ohlcv(100)
    result = plugin.compute_full({"main": df})

    assert result, "Should return results with APR config injected"
    mock_cfg.get_sync.assert_any_call("feature.garch.omega", 0.00001)
    mock_cfg.get_sync.assert_any_call("feature.garch.alpha", 0.10)
    mock_cfg.get_sync.assert_any_call("feature.garch.beta", 0.85)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_garch_volatility.py::test_garch_reads_apr_config -v
```

Expected: FAIL — `GARCHVolatilityPlugin` has no `_config_service` field.

- [ ] **Step 3: Implement APR loading in GARCHVolatilityPlugin**

In `src/intelligence/context/garch_volatility.py`:

1. Add import at top: `from dataclasses import dataclass, field`  (already has `dataclass` — add `field`)

2. Add `_config_service` field to the dataclass (after `beta`):

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class GARCHVolatilityPlugin(IncrementalMixin):
    ...
    omega: float = 0.00001
    alpha: float = 0.10
    beta: float = 0.85
    _config_service: Any = field(default=None, compare=False, repr=False)
```

3. Add a `_get_params()` helper that reads from APR with fallback to dataclass defaults:

```python
def _get_params(self) -> tuple[float, float, float]:
    """Return (omega, alpha, beta), reading from APR if config_service is wired."""
    cfg = self._config_service
    if cfg is None:
        return self.omega, self.alpha, self.beta
    return (
        float(cfg.get_sync("feature.garch.omega", self.omega)),
        float(cfg.get_sync("feature.garch.alpha", self.alpha)),
        float(cfg.get_sync("feature.garch.beta", self.beta)),
    )
```

4. In `_compute_full_core`, `_seed_state`, and `_compute_next_core`, replace all three occurrences of `self.omega`, `self.alpha`, `self.beta` with a call to `_get_params()` at the top of each method:

```python
def _compute_full_core(self, frames: dict[str, Any]) -> dict[str, Any]:
    omega, alpha, beta = self._get_params()
    # ... replace self.omega → omega, self.alpha → alpha, self.beta → beta throughout
```

Do the same substitution in `_seed_state` and `_compute_next_core`.

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/unit/intelligence/test_garch_volatility.py -v
```

Expected: all tests pass including the new one.

- [ ] **Step 5: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/context/garch_volatility.py tests/unit/intelligence/test_garch_volatility.py
git commit -m "feat(garch): read omega/alpha/beta from APR via _config_service field"
```

---

## Task 4: KalmanTrendPlugin — read garch_r_scale from APR

**Files:**
- Modify: `src/intelligence/context/kalman_trend.py`
- Modify: `tests/unit/intelligence/test_kalman_trend.py`

**Interfaces:**
- Consumes: Task 1 (migration 153 applied)
- Produces: `KalmanTrendPlugin._get_R()` reads `feature.kalman.garch_r_scale` from APR

**Pattern:** Same plugin dataclass pattern as Task 3.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/intelligence/test_kalman_trend.py`:

```python
def test_kalman_reads_apr_garch_r_scale() -> None:
    """KalmanTrendPlugin must read garch_r_scale from _config_service when injected."""
    from unittest.mock import MagicMock

    plugin = KalmanTrendPlugin(use_garch_adaptive=True)

    mock_cfg = MagicMock()
    custom_scale = 5000.0  # half of default 10000
    mock_cfg.get_sync.side_effect = lambda key, default=None: (
        custom_scale if key == "feature.kalman.garch_r_scale" else default
    )
    plugin._config_service = mock_cfg

    df = _make_ohlcv(100)
    # Provide a synthetic garch_sigma in i4 features
    result = plugin.compute_full({"main": df, "i4": {"garch_sigma": 0.01}})

    assert result, "Should return results with APR config injected"
    mock_cfg.get_sync.assert_any_call("feature.kalman.garch_r_scale", 10_000.0)
```

(Check `tests/unit/intelligence/test_kalman_trend.py` for `_make_ohlcv` — add it if missing, same signature as in GARCH test.)

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_kalman_trend.py::test_kalman_reads_apr_garch_r_scale -v
```

Expected: FAIL — `KalmanTrendPlugin` has no `_config_service` field.

- [ ] **Step 3: Implement APR loading in KalmanTrendPlugin**

In `src/intelligence/context/kalman_trend.py`:

1. Import `field` and `Any` (already has `dataclass, field` and `Any` via `typing`).

2. Add `_config_service` field to the dataclass (after `use_garch_adaptive`):

```python
@dataclass
class KalmanTrendPlugin(IncrementalMixin):
    ...
    use_garch_adaptive: bool = False
    _config_service: Any = field(default=None, compare=False, repr=False)
```

3. In `_get_R()`, replace the module-level `_GARCH_R_SCALE` with an APR lookup:

```python
def _get_R(self, features: dict[str, Any]) -> float:
    """Return measurement noise R, optionally GARCH-adapted."""
    if self.use_garch_adaptive:
        garch_sigma = features.get("garch_sigma")
        if garch_sigma and float(garch_sigma) > 0:
            cfg = self._config_service
            scale = (
                float(cfg.get_sync("feature.kalman.garch_r_scale", _GARCH_R_SCALE))
                if cfg is not None
                else _GARCH_R_SCALE
            )
            R_adaptive = (float(garch_sigma) * scale) ** 2
            return max(0.1, R_adaptive)
    return self._R_fixed
```

Keep `_GARCH_R_SCALE` module constant as the fallback — do not delete it.

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/unit/intelligence/test_kalman_trend.py -v
```

Expected: all tests pass including the new one.

- [ ] **Step 5: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/context/kalman_trend.py tests/unit/intelligence/test_kalman_trend.py
git commit -m "feat(kalman): read garch_r_scale from APR via _config_service field"
```

---

## Task 5: Wire GARCH + Kalman keys into pipeline _THRESHOLD_KEYS

**Files:**
- Modify: `services/intelligence_pipeline.py` — add 4 keys to `_THRESHOLD_KEYS`

**Interfaces:**
- Consumes: Tasks 1, 3, 4 (migration applied, plugins have `_config_service` field)
- Produces: APR values pre-warmed in cache at pipeline startup; GARCH/Kalman `get_sync()` calls guaranteed to hit cache (not DB) during hot-path computation

**Note:** The auto-injection loop at lines 562-568 already handles passing `_config_service` to all plugins that have the field. No changes to that loop or to `_prewarm_threshold_config` logic. Only `_THRESHOLD_KEYS` needs new entries.

- [ ] **Step 1: Add keys to `_THRESHOLD_KEYS`**

In `services/intelligence_pipeline.py`, find the end of `_THRESHOLD_KEYS` (after line 533 closing paren `)`). Add before the closing paren:

```python
        # --- migration 153: HMM trainer and GARCH/Kalman plugin APR keys ---
        ("feature.garch.omega", 0.00001),
        ("feature.garch.alpha", 0.10),
        ("feature.garch.beta", 0.85),
        ("feature.kalman.garch_r_scale", 10_000.0),
```

Note: HMM trainer keys (`feature.hmm.*`) are NOT added here — HMMTrainer is a standalone oneshot service that loads ConfigService directly in `run()`. Pipeline `_THRESHOLD_KEYS` is only for the intelligence_pipeline runtime.

- [ ] **Step 2: Verify no tests broken**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add services/intelligence_pipeline.py
git commit -m "feat(pipeline): pre-warm GARCH and Kalman APR keys in _THRESHOLD_KEYS"
```

---

## Task 6: Mark todo complete and push

- [ ] **Step 1: Run full unit suite one final time**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all green.

- [ ] **Step 2: Delete the todo file**

```bash
rm .planning/todos/pending/hmm-training-fix.md
```

- [ ] **Step 3: Push**

```bash
git push origin main
```

- [ ] **Step 4: Verify APR keys visible in dashboard**

Open `http://localhost:8000/config/parameters` and confirm `feature.garch.*`, `feature.kalman.*`, and `feature.hmm.*` keys appear with correct values and types.
