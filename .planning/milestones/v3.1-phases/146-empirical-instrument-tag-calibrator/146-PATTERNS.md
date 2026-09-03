# Phase 146: Empirical Instrument Tag Calibrator - Pattern Map

**Mapped:** 2026-07-17
**Files analyzed:** 8 (2 new modules, 2 new migrations, 3 new test files, 1 data-migration payload)
**Analogs found:** 8 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `src/intelligence/statistics/factor_math.py` | utility (statistics module) | transform (pure compute, no I/O) | `src/intelligence/statistics/ic_math.py` | exact (same tier, same job: measurement kernel extension) |
| `services/tag_calibrator.py` | service (batch compute, `BaseBatch` oneshot) | batch (read market data + tag_vocabulary, write instrument_tags) | `services/ensemble_ic_engine.py` | exact (nightly/weekly `BaseBatch` statistical-measurement service, same DAG tier) |
| `production/migrations/237_tag_vocabulary_taxonomy_cleanup.sql` (Wave 0) | migration (data cleanup, not schema) | batch (one-time UPDATE/DELETE) | `production/migrations/227_instrument_tag_vocabulary.sql` (seed data shape) + no direct cleanup-migration analog found | role-match (seed-data shape only; no prior "merge tag + delete tag + backfill evidence" migration exists in this repo) |
| `production/migrations/238_tag_calibrator_measurement_contract.sql` (Wave 1) | migration (schema DDL + APR seed) | batch (ALTER TABLE + APR 3-table INSERT) | `production/migrations/235_ibkr_apr_migration.sql` (APR seed) + `227_instrument_tag_vocabulary.sql` (DDL shape for the two tables being altered) | exact for the APR-seed half; role-match for the ALTER TABLE half |
| `tests/unit/test_factor_math.py` | test (unit, pure-function correctness) | transform | `tests/unit/test_ensemble_ic_math.py` (closest sibling: tests `ic_math.py`-style pure statistical functions) | role-match |
| `tests/unit/test_spread_leg_pair_validity.py` | test (unit, data-contract/boundary guard) | batch (filesystem/DB-free or one-shot DB read, CI guard) | `tests/unit/test_market_data_ohlcv_boundary.py` | exact (explicitly named as the model in CONTEXT.md D-09) |
| `tests/unit/test_tag_calibrator.py` | test (unit, service decision-logic) | event-driven/batch (decision branches: keep/expire/discover, FDR wiring, self-regression skip) | `tests/unit/test_ensemble_ic_gate.py` / `tests/unit/test_ensemble_ic_bh_fdr.py` (closest siblings: gate-decision and FDR-wiring tests for `EnsembleICEngine`) | role-match |
| `src/intelligence/regime_signals/breadth_vol.py` (read-only reuse, no modification) | utility (pure signal function) | transform | N/A — reused verbatim, not created | n/a (source of `_compute_vix_pct_rank`) |

## Pattern Assignments

### `src/intelligence/statistics/factor_math.py` (utility, transform)

**Analog:** `src/intelligence/statistics/ic_math.py` (full file read, 858 lines)

**Module docstring / provenance pattern** (`ic_math.py` lines 1-18) — set the same expectation for `factor_math.py`: pure functions only, no DB, no config loading, explicit statement of what it extracts vs. reuses:
```python
"""Shared IC (Information Coefficient) math -- circular block bootstrap CI (production,
Component A / todo 091), the superseded Fisher z-transform CI (kept for
services/ensemble_ic_engine.py and scripts/ops/corpus/ops_oos_holdout_eval.py, which
stay on it this phase -- see 143.1-CONTEXT.md resolved item 3), vectorized Spearman IC,
HAC-corrected rolling Sharpe, and p-values.
...
Pure functions only -- no DB, no config loading, no module-global mutable state (besides
the _Z95 constant). config.sharpe_window_size / config.sharpe_min_windows are accessed via
the SharpeWindowConfig protocol rather than importing ICEngineConfig or EnsembleICConfig,
so this module has no dependency back on either concrete config dataclass.
"""
```

**Imports pattern** (`ic_math.py` lines 20-29) — `factor_math.py` should import the same statistical primitives plus the four functions it reuses directly from `ic_math`:
```python
from __future__ import annotations

import math
import warnings
from typing import Protocol

import numpy as np
from scipy.stats import norm, rankdata
from scipy.stats import t as t_dist
from statsmodels.stats.multitest import multipletests
```
`factor_math.py` additionally needs:
```python
from src.intelligence.statistics.ic_math import (
    _fisher_z_ci,
    _p_values_from_ic,
    apply_bh_fdr,
    _hac_sharpe_nd,  # reuse the Bartlett-kernel inflation-factor pattern (lines 754-760), not the function verbatim
)
```

**Reusable function signatures to import, not reimplement** (`ic_math.py`, exact line ranges — verified live):
```python
# ic_math.py:121-149
def _fisher_z_ci(ic_vector: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """95% CI for Spearman IC via Fisher z-transform. Returns (ci_lower, ci_upper)."""

# ic_math.py:353-366
def _p_values_from_ic(ic_vector: np.ndarray, n: int, df: int | None = None) -> np.ndarray:
    """Two-tailed p-values from IC via t-approximation. df defaults to n-2; pass
    explicit df for additional fitted parameters (e.g. long-short construction)."""

# ic_math.py:412-431
def apply_bh_fdr(p_values: list[float], alpha: float) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg FDR correction over one family of p-values.
    Returns (reject, p_corrected) as parallel arrays in input order."""

# ic_math.py:724-763
def _hac_sharpe_nd(
    window_ics: np.ndarray, max_lag: int,
    mean_ic: np.ndarray | None = None, var0: np.ndarray | None = None,
) -> np.ndarray:
    """Newey-West Bartlett-kernel HAC-corrected IC Sharpe. Reuse the inflation-factor
    loop (gamma_k/rho_k/Bartlett-weight accumulation) as the pattern for the
    OLS loading's HAC standard error -- not this exact function (Sharpe-specific),
    same kernel math."""

# ic_math.py:439-452
def check_condition_number(matrix: np.ndarray, condition_max: float) -> tuple[bool, float]:
    """Ill-conditioning gate for any Sigma^-1/lstsq solve on estimated data."""
```

**Config protocol pattern** — `ic_math.py` avoids importing concrete config dataclasses via a duck-typed `Protocol` (line 24: `from typing import Protocol`, see `SharpeWindowConfig` in the file). `factor_math.py`'s functions that need `hac_max_lag` etc. should accept the same style of minimal Protocol, not import `TagCalibratorConfig` (avoids the reverse-dependency `ic_math.py` itself is structured to avoid).

**Core new-math pattern to write** (long-short constructor — one shared function, four call sites: HYG-IEF, TIP-IEF, IEF-SHY, XLE-SPY):
```python
def long_short_daily_returns(
    long_close: np.ndarray, short_close: np.ndarray
) -> np.ndarray:
    """Long-short daily log-return spread: log(long[t]/long[t-1]) - log(short[t]/short[t-1]).

    Shared constructor for credit_beta (HYG-IEF), inflation (TIP-IEF), yield_curve (IEF-SHY),
    and oil_beta (XLE-SPY) -- one function, four call sites.
    """
    long_ret = np.diff(np.log(long_close))
    short_ret = np.diff(np.log(short_close))
    return long_ret - short_ret
```

**Standardized-loading pattern** (per RESEARCH.md's Assumptions Log A2 — univariate OLS beta standardized by `sigma_factor/sigma_instrument` reduces to Pearson correlation): implement as a direct `cov(x,y)/(std(x)*std(y))` computation, do not pull in `statsmodels.regression.linear_model.OLS`.

---

### `services/tag_calibrator.py` (service, batch)

**Analog:** `services/ensemble_ic_engine.py` (targeted reads: header/docstring, imports, `EnsembleICConfig`, `EnsembleICEngine` class def + `execute()` + entrypoint — full class spans lines 877-1137)

**Imports pattern** (`ensemble_ic_engine.py` lines 66-106):
```python
from __future__ import annotations

import asyncio
import dataclasses
import sys
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import psycopg2
import psycopg2.extras
import structlog
from scipy.stats import rankdata
from statsmodels.stats.multitest import multipletests

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import cfg as _cfg
from services._batch_utils import connect_db_from_url
from services._batch_utils import load_apr_dict_async as _load_apr_dict
from src.config.config_service import ConfigService
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.intelligence.statistics.ic_math import (
    _compute_ic_rolling_metrics,
    _fisher_z_ci,
    _nan_to_none,
    _p_values_from_ic,
    _vectorized_ic,
)
from src.observability.corpus_manifest import CorpusManifest
from src.observability.otel import OTelInitError, init_otel_providers
```
`tag_calibrator.py` swaps the `ic_math` import list for `factor_math`'s equivalents and drops `ProcessPoolExecutor`/`psycopg2` unless the full-matrix loop needs parallelism (small universe: 80 symbols x ~20 tags — likely serial is fine; confirm at planning time). Per RESEARCH.md A1, `CorpusManifest` is probably unnecessary — plain try/except logging suffices (see Error handling pattern below, simplified).

**`BaseBatch` contract** (`src/core/agent/base_batch.py`, full file, 171 lines — read in full):
```python
# base_batch.py:30-68
class BaseBatch(abc.ABC):
    """Abstract base for batch compute oneshot services.

    Subclasses define:
      job_name: str         -- D-06 job label (must match systemd unit %n suffix, kebab-case)
      compute_version: str  -- version tag written to DB rows for auditability
      execute(pool) -> None -- async compute method; receives an open asyncpg Pool
    """
    job_name: str
    compute_version: str

    def __init__(self, db_dsn: str) -> None:
        self._db_dsn = db_dsn
        self._pool: asyncpg.Pool | None = None
        log_name = getattr(self, "job_name", type(self).__name__).replace("-", "_")
        setup_service_logging(f"logs/{log_name}.log")
        self.logger = structlog.get_logger(type(self).__name__)

    @abc.abstractmethod
    async def execute(self, pool: asyncpg.Pool) -> None: ...
```
`run()` (lines 74-97) handles pool setup/teardown, D-06 `job_completed_total` emission (success/failure), and OTel metric flush automatically — `TagCalibrator` never needs to touch this, only implement `execute()`.

**Class skeleton + entrypoint pattern** (`ensemble_ic_engine.py` lines 877-891, 903-911, plus the file's own `if __name__ == "__main__":` block at the end — not re-quoted here, same shape cited in RESEARCH.md):
```python
class EnsembleICEngine(BaseBatch):
    job_name = "ensemble-ic-engine"
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str, weight_version_override: str | None = None) -> None:
        super().__init__(db_dsn)
        self._weight_version_override = weight_version_override

    async def execute(self, pool: asyncpg.Pool) -> None:
        manifest = CorpusManifest("ensemble_ic_engine", CorpusManifest.DEFAULT_MANIFEST_DIR)
        try:
            await self._execute_inner(pool, manifest)
        except Exception as error:  # CLAUDE.md: exception variable name is `error`
            manifest.add_error(str(error))
            try:
                manifest.write()
            except Exception:
                pass
            raise

    async def _execute_inner(self, pool: asyncpg.Pool, manifest: CorpusManifest) -> None:
        run_ts = datetime.now(UTC)
        self.logger.info("ensemble_ic.run_ts_locked", run_ts=str(run_ts))
        async with pool.acquire() as conn:
            apr_cfg = await _load_apr_dict(conn, extra_like_patterns=_INFRA_LIKE_PATTERNS)
            config = EnsembleICConfig.from_apr(apr_cfg)
            ...
```
`job_name = "tag-calibrator"` (per RESEARCH.md F9 rename — "auditor" is reserved for health-check daemons); `compute_version = "1.0.0"`. For `TagCalibrator`, replace `CorpusManifest`-based error handling with plain logging unless a manifest consumer is confirmed to exist (RESEARCH.md A1):
```python
async def execute(self, pool: asyncpg.Pool) -> None:
    try:
        await self._execute_inner(pool)
    except Exception as error:
        self.logger.error("tag_calibrator.failed", error=str(error))
        raise
```

**Config dataclass pattern (`from_apr` classmethod)** — `EnsembleICConfig` (`ensemble_ic_engine.py` lines 145-220, full class):
```python
@dataclasses.dataclass(frozen=True)
class EnsembleICConfig:
    fdr_alpha: float
    walk_forward_folds: int
    # ... (16 fields total)

    @classmethod
    def from_apr(cls, cfg: dict[str, Any]) -> EnsembleICConfig:
        """Load all EnsembleIC APR parameters from the raw config dict in one pass."""
        return cls(
            fdr_alpha=_cfg(cfg, "alpha.ic.fdr_alpha", 0.05),
            walk_forward_folds=_cfg(cfg, "alpha.ic.walk_forward_folds", 3),
            ...
        )
```
`TagCalibratorConfig` should follow this exact shape — one frozen dataclass, one `.from_apr(apr_cfg)` classmethod, loaded once per run — per RESEARCH.md Open Question 2's own recommendation. Seven fields needed: `fdr_alpha`, `expiry_consecutive_fails`, `discovery_oos_days`, `min_sample_n`, `hac_max_lag`, `half_life_min_days`, `half_life_max_days`.

**APR loading helpers** (`services/_batch_utils.py`, lines 109-140, read in full):
```python
async def load_apr_dict_async(conn: Any, extra_like_patterns: list[str] | None = None) -> Any:
    """Load alpha.* (+ optional extra LIKE patterns) APR keys via asyncpg into a raw
    {config_key: config_value} dict. Returns a plain dict -- callers cast with cfg()."""
    patterns = ["alpha.%", *(extra_like_patterns or [])]
    rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key LIKE ANY($1::text[])",
        patterns,
    )
    return {r["config_key"]: r["config_value"] for r in rows}

def cfg(cfg_dict: dict[str, Any], key: str, default: Any) -> Any:
    """Cast a raw config_value to default's type, or return default if unset."""
```
`TagCalibrator` calls `_load_apr_dict(conn, extra_like_patterns=["alpha.tag_calibrator.%"])` if the APR namespace isn't already covered by the default `"alpha.%"` pattern (it is — `alpha.tag_calibrator.*` matches `alpha.%` directly, so `extra_like_patterns` may not even be needed unless keys live under a different top-level namespace).

**Error handling pattern:** `except Exception as error:` (CLAUDE.md mandate, verified consistently in `ensemble_ic_engine.py` line 895 and `base_batch.py` lines 85, 144) — never `except Exception as exc:`.

---

### `production/migrations/238_tag_calibrator_measurement_contract.sql` (migration, schema DDL + APR seed)

**Analog:** `production/migrations/235_ibkr_apr_migration.sql` (full file, 59 lines) for the APR half; `production/migrations/227_instrument_tag_vocabulary.sql` (targeted read, DDL section lines 1-46) for the ALTER TABLE shape being extended.

**APR 3-table seed pattern** (`235_ibkr_apr_migration.sql`, full file):
```sql
BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.ibkr.retry_count',
    'int',
    '3',
    1, 10,
    '[conventional] Number of retry attempts on an ambiguous ... Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.ibkr.retry_count', '3', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.ibkr.retry_count', 1, '3', 'migration_235', 'Initial value: matches pre-migration hardcoded constant exactly [conventional]')
ON CONFLICT DO NOTHING;

COMMIT;
```
Apply this identical pattern for each of the 7 `alpha.tag_calibrator.*` keys (`fdr_alpha`, `expiry_consecutive_fails`, `discovery_oos_days`, `min_sample_n`, `hac_max_lag`, `half_life_min_days`, `half_life_max_days`) — `changed_by = 'migration_238'`, description provenance tag `[initial_estimate]` (these are new statistical thresholds, not pre-existing hardcoded constants being migrated, so `[conventional]`/`[rca_analysis]` don't apply — use `[initial_estimate]` per CLAUDE.md's provenance-tag rule).

**Existing table shape to extend** (`227_instrument_tag_vocabulary.sql` lines 12-26):
```sql
CREATE TABLE tag_vocabulary (
    tag         text PRIMARY KEY,
    category    text NOT NULL CHECK (category IN ('exposure', 'regime', 'signal_role', 'macro_driver')),
    description text NOT NULL
);

CREATE TABLE instrument_tags (
    symbol      text        NOT NULL REFERENCES instruments(symbol) ON DELETE CASCADE,
    tag         text        NOT NULL REFERENCES tag_vocabulary(tag),
    weight      float       NOT NULL DEFAULT 1.0 CHECK (weight >= 0.0 AND weight <= 1.0),
    source      text        NOT NULL DEFAULT 'human' CHECK (source IN ('human', 'empirical', 'ai')),
    evidence    jsonb,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, tag)
);
```
Note: live schema's `category` CHECK is now the 6-value set from migration 228 (`exposure`, `sensitivity`, `factor_regime`, `cycle_position`, `signal_role`, `macro_driver`) — per RESEARCH.md Pitfall 4, do NOT re-migrate this CHECK; migration 238 only needs `ALTER TABLE instrument_tags ADD COLUMN valid_from timestamptz NOT NULL DEFAULT now(), ADD COLUMN valid_to timestamptz;` plus the design doc's revised-schema columns (`loading`, `p_value`, `bh_adjusted_p`, `passes_fdr`, `consecutive_fails`, `sample_n`, `estimated_at`) and `tag_vocabulary`'s new columns (`factor_series`, `measurement_type`, `lookback_days`, `loading_threshold`, `half_life_days`). `instrument_annotations` already has `valid_from`/`valid_to` (migration 227 line ~29-38) — no changes needed there.

---

### `production/migrations/237_tag_vocabulary_taxonomy_cleanup.sql` (migration, Wave 0 data cleanup)

**Analog:** No direct prior "merge tag / delete tag / backfill evidence" migration exists in this codebase (verified: `grep -rl "DELETE FROM\|UPDATE instrument_tags\|UPDATE tag_vocabulary"` across all migrations returns only index/constraint-modification migrations, none matching this shape). Use `227_instrument_tag_vocabulary.sql`'s seed-data literal shape as the nearest precedent for `evidence` JSONB structure and row-literal style, and general migration file header-comment conventions from `235_ibkr_apr_migration.sql`.

**Evidence JSONB shape precedent** (`227_instrument_tag_vocabulary.sql` — `spread_leg` rows, e.g. line 158):
```sql
('SPY', 'eq_broad', 1.0, 'human'), ('SPY', 'benchmark', 1.0, 'human'),
('SPY', 'regime_classifier', 1.0, 'human'), ('SPY', 'spread_leg', 1.0, 'human'),
```
Current `spread_leg` rows have NULL `evidence` for 17/28 rows (D-09) — the Wave 0 migration must backfill `evidence = '{"pair": "<SYM>", "reason": "..."}'::jsonb` for the mechanically-recoverable pairs (LQD←CWB, TLT←EDV, SPY←IPO/EZU, SCHD←VYM) and add reciprocal rows for UUP/USMV/FXI. Write this migration as plain `UPDATE instrument_tags SET evidence = '...'::jsonb WHERE symbol = '...' AND tag = 'spread_leg';` statements — no existing house pattern to deviate from since none exists; keep it `BEGIN`/`COMMIT` wrapped per house convention (both prior migrations use this).

**credit_cycle → credit_risk merge (D-03):** verified live weights HYG (0.9/1.0) and LQD (0.8/0.8) — max-weight-on-collision means both already have `credit_risk` at >= `credit_cycle`'s weight, so the merge is effectively `DELETE FROM instrument_tags WHERE tag = 'credit_cycle'` (no `credit_risk` row needs a weight bump) followed by `DELETE FROM tag_vocabulary WHERE tag = 'credit_cycle'`.

**housing_cycle deletion (D-07):** `DELETE FROM instrument_tags WHERE tag = 'housing_cycle'; DELETE FROM tag_vocabulary WHERE tag = 'housing_cycle';` — single holder (XHB), no merge needed, delete outright per the tautology finding.

---

### `tests/unit/test_spread_leg_pair_validity.py` (test, boundary/data-contract)

**Analog:** `tests/unit/test_market_data_ohlcv_boundary.py` (full file, 162 lines — read in full)

**Pattern to model directly** (full file structure):
```python
"""CI guard: no new raw `market_data_ohlcv` reads outside this checked-in allow-list.
...
CI-clean: no DB, no network -- pure filesystem grep.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
_RAW_TABLE_PATTERN = re.compile(r"\b(?:FROM|JOIN)\s+market_data_ohlcv\b(?!_tradeable)")
_SEARCH_DIRS = ("services", "src", "scripts")

_ALLOW_LIST: dict[str, str] = {
    "services/signal_replay_auditor.py": (
        "PERMANENT: Dead v2.x Signal Ledger Architecture code ..."
    ),
    ...
}

@functools.lru_cache(maxsize=1)
def _find_raw_table_references() -> dict[str, int]:
    ...

def test_every_raw_market_data_ohlcv_reference_is_on_the_allow_list():
    hits = _find_raw_table_references()
    unexpected = set(hits) - set(_ALLOW_LIST)
    assert not unexpected, (...)

def test_allow_list_has_no_stale_entries():
    hits = _find_raw_table_references()
    stale = set(_ALLOW_LIST) - set(hits)
    assert not stale, (...)
```
`test_spread_leg_pair_validity.py` adapts this exact two-test shape (positive assertion + no-stale-entries assertion) but swaps the filesystem-grep data source for a live DB query (or a fixture snapshot, per D-09's note that this is a data-contract check, not a call-site grep):
```python
def test_every_spread_leg_pair_resolves_to_a_valid_symbol():
    """Every instrument_tags row with tag='spread_leg' must have
    evidence->>'pair' resolving to a real instruments.symbol."""
    # query: SELECT symbol, evidence->>'pair' AS pair FROM instrument_tags
    #        WHERE tag = 'spread_leg'
    # assert every pair value exists in instruments.symbol

def test_spread_leg_pairs_are_symmetric():
    """If A's spread_leg evidence names B as its pair, B's spread_leg
    evidence must name A back (reciprocal reference)."""
```

---

### `tests/unit/test_factor_math.py` (test, unit correctness)

**Analog:** `tests/unit/test_ensemble_ic_math.py` (closest sibling testing `ic_math.py`-derived pure functions used by `ensemble_ic_engine.py`) — file not read in full for this pass (role-match confidence sufficient: same-tier pure-function test, synthetic-fixture style is the established house pattern per RESEARCH.md's own listed test IDs: `test_ols_loading_synthetic`, `test_hac_se_inflation`, `test_long_short_constructor`). Structure: construct synthetic arrays with a known true beta/correlation, assert computed loading matches within tolerance; construct autocorrelated synthetic data, assert HAC SE inflates vs. naive SE.

---

### `tests/unit/test_tag_calibrator.py` (test, service decision logic)

**Analog:** `tests/unit/test_ensemble_ic_gate.py` / `tests/unit/test_ensemble_ic_bh_fdr.py` (closest siblings — gate/decision and FDR-wiring tests for the sibling `EnsembleICEngine` service). Not read in full this pass; role-match is sufficient since RESEARCH.md's own Validation Architecture table already specifies the exact test function names and behaviors required:
- `test_skips_self_regression` (F6.1 guard: `symbol == factor_series`)
- `test_run_level_fdr` (BH-FDR applied once per run, not per-hypothesis)
- `test_expiry_hysteresis` (`consecutive_fails` gate before `valid_to = now()`)
- `test_vol_beta_uses_breadth_vol_proxy` (import/call correctness against `breadth_vol._compute_vix_pct_rank`, not a re-derivation)
- `test_skips_definitional_tags` (`fed_policy`/`geopolitical`/etc. never written by the calibration loop)

---

## Shared Patterns

### `except Exception as error:` naming convention
**Source:** `services/ensemble_ic_engine.py:895`, `src/core/agent/base_batch.py:85,144`
**Apply to:** `services/tag_calibrator.py`, any error-handling branch in `src/intelligence/statistics/factor_math.py`
```python
except Exception as error:  # CLAUDE.md: exception variable name is `error`, never `exc`
    ...
```

### `BaseBatch` lifecycle (pool setup/teardown, D-06 emission)
**Source:** `src/core/agent/base_batch.py` (full file)
**Apply to:** `services/tag_calibrator.py` — inherit, never reimplement `run()`/`_setup_pool()`/`_teardown_pool()`/`_emit_completion()`. Only `execute(pool)` needs a subclass implementation.

### APR 3-table seed migration
**Source:** `production/migrations/235_ibkr_apr_migration.sql` (full file)
**Apply to:** `production/migrations/238_tag_calibrator_measurement_contract.sql`'s APR-key section
```sql
BEGIN;
INSERT INTO config_schema (...) VALUES (...) ON CONFLICT (config_key) DO NOTHING;
INSERT INTO config_state (...) VALUES (...) ON CONFLICT (config_key) DO NOTHING;
INSERT INTO config_history (...) VALUES (...) ON CONFLICT DO NOTHING;
COMMIT;
```

### Measurement-kernel reuse (never reimplement CI/p-value/FDR/HAC math)
**Source:** `src/intelligence/statistics/ic_math.py` (`_fisher_z_ci`, `_p_values_from_ic`, `apply_bh_fdr`, `_hac_sharpe_nd` pattern, `check_condition_number`)
**Apply to:** `src/intelligence/statistics/factor_math.py` exclusively — `services/tag_calibrator.py` should call into `factor_math.py`, never import `ic_math.py` directly for these five functions (keeps the reuse boundary at the statistics-module tier, matching how `ensemble_ic_engine.py` imports `ic_math` functions directly only because `ic_math.py` IS the shared kernel module — `factor_math.py` plays that same role for `tag_calibrator.py`).

### `breadth_vol.py` proxy reuse for `vol_beta`
**Source:** `src/intelligence/regime_signals/breadth_vol.py:91-135` (`_compute_vix_pct_rank`)
**Apply to:** `src/intelligence/statistics/factor_math.py` or `services/tag_calibrator.py` (planner's call per RESEARCH.md option a/b) — import the underscore-prefixed function directly (consistent with house style of importing `ic_math.py`'s own underscore-prefixed functions across 3 other Ring 2 consumers), or add a one-line public re-export (`compute_vix_pct_rank = _compute_vix_pct_rank`) in `breadth_vol.py` for clarity. Reuse verbatim — do NOT re-derive a non-causal (whole-series percentile) version; the causal bisect-based expanding rank is a hard correctness invariant (Phase 141 P0-T2 look-ahead fix).

### Data-boundary compliance (`market_data_ohlcv_tradeable`, not raw table)
**Source:** `tests/unit/test_market_data_ohlcv_boundary.py` (CI guard, full file)
**Apply to:** All daily-return reads inside `services/tag_calibrator.py` and any DB-touching helper in `factor_math.py` — must query `market_data_ohlcv_tradeable`, not `market_data_ohlcv`, per D-11. Expected: zero new allow-list entries required for this phase's new files (RESEARCH.md's Validation Architecture table confirms this expectation explicitly).

## No Analog Found

None — every file in this phase's scope has at least a role-match analog. The one partial gap is noted above: `production/migrations/237_tag_vocabulary_taxonomy_cleanup.sql`'s "merge tag / delete tag / backfill evidence" shape has no direct prior migration to copy verbatim (this codebase's migrations are overwhelmingly additive — DDL + seed inserts — not corrective data cleanups). Plain `UPDATE`/`DELETE` statements wrapped in `BEGIN`/`COMMIT` following the house header-comment style is sufficient; no new pattern needs to be invented, just no exact precedent to point to.

## Metadata

**Analog search scope:** `src/intelligence/statistics/`, `src/intelligence/regime_signals/`, `services/`, `src/core/agent/`, `production/migrations/`, `tests/unit/`
**Files scanned:** `ic_math.py` (858 lines, read in full), `base_batch.py` (171 lines, read in full), `ensemble_ic_engine.py` (1137 lines, targeted reads: 1-115, 145-235, 877-937), `breadth_vol.py` (155 lines, read in full), `_batch_utils.py` (targeted read: 100-140), `test_market_data_ohlcv_boundary.py` (162 lines, read in full), `235_ibkr_apr_migration.sql` (59 lines, read in full), `227_instrument_tag_vocabulary.sql` (targeted reads: 1-60, spread_leg grep), migration directory listing for cleanup-pattern precedent search (none found)
**Pattern extraction date:** 2026-07-17
