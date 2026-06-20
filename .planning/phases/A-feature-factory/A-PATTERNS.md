# Phase A: Feature Factory - Pattern Map

**Mapped:** 2026-06-20
**Files analyzed:** 8 (new/modified)
**Analogs found:** 7 / 8

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/intelligence/feature_factory.py` | service (pure-function library) | transform | `src/intelligence/context/hurst_exponent.py` | role-match |
| `src/intelligence/feature_cache.py` | utility (state container) | transform | `src/intelligence/features/smc_context/hmm_regime.py` (state dict pattern) | role-match |
| `src/intelligence/schemas.py` (modify) | model | transform | existing file — extend with `FeatureVector` dataclass | exact |
| `src/core/stream_keys.py` (modify) | utility | request-response | existing file — add `topic_feature_vectors` | exact |
| `src/config/config_service.py` (modify) | config | - | existing file — add `"alpha."` to `OPS_PREFIXES` | exact |
| `services/feature_writer.py` (modify) | service (writer) | CRUD | `services/feature_writer.py` itself — retarget write | exact |
| `production/migrations/155_feature_vectors.sql` | migration | CRUD | `production/migrations/153_hmm_garch_kalman_apr.sql` | exact |
| `services/backfill_feature_factory.py` | service (oneshot) | batch | `production/scripts/run_historical_pipeline.py` | role-match |

---

## Pattern Assignments

### `src/intelligence/feature_factory.py` (pure-function library, transform)

**Analog:** `src/intelligence/context/hurst_exponent.py` (pure computation core),  
`src/intelligence/features/smc_context/hmm_regime.py` (forward-only state),  
`src/intelligence/context/garch_volatility.py` (APR-backed config field)

**Pure computation core pattern** — from `src/intelligence/context/hurst_exponent.py` lines 26-60:
```python
import numpy as np

def _hurst_rs(close: np.ndarray, min_window: int = 16) -> float:
    """Rescaled range (R/S) estimate. Returns 0.5 when series too short."""
    n = len(close)
    if n < min_window:
        return 0.5

    log_returns = np.diff(np.log(close))
    if len(log_returns) < min_window:
        return 0.5

    mean_r = np.mean(log_returns)
    deviations = np.cumsum(log_returns - mean_r)
    r = np.max(deviations) - np.min(deviations)
    s = np.std(log_returns, ddof=1)

    if s == 0 or r == 0:
        return 0.5

    rs = r / s
    if rs <= 0:
        return 0.5

    return float(min(1.0, max(0.0, np.log(rs) / np.log(n))))
```

**Forward-only HMM state pattern** — from `src/intelligence/features/smc_context/hmm_regime.py` lines 237/279/313/378:
```python
# Only _forward_step() is called — never _smooth().
# The file has no backward smoother path (D-07 constraint satisfied by design).
# Use _forward_step() directly in FeatureFactory; do not copy _smooth() references.
self._forward_step(obs, n_dims, hmm_state)
```

**APR-backed config field pattern** — from `src/intelligence/context/garch_volatility.py` lines 44-55:
```python
# Plugin dataclass pattern: _config_service field + get_sync() at compute time
# FeatureFactory uses frozen FeatureFactoryConfig instead — APR loaded ONCE at init
# and passed in. Do NOT replicate the _config_service field on FeatureFactory itself.
# The config is baked into the frozen dataclass before any compute() call.
_config_service: Any = field(default=None, compare=False, repr=False)

def _get_params(self) -> tuple[float, float, float]:
    cfg = self._config_service
    if cfg is None:
        return self.omega, self.alpha, self.beta
    return (
        float(cfg.get_sync("feature.garch.omega", self.omega)),
        float(cfg.get_sync("feature.garch.alpha", self.alpha)),
        float(cfg.get_sync("feature.garch.beta", self.beta)),
    )
```

**FeatureVector frozen dataclass** — from `A-RESEARCH.md` Pattern 1 (binding spec):
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class FeatureVector:
    # Bar-level (14)
    momentum_z_5:     float
    momentum_z_20:    float
    range_position:   float
    bar_close_pos:    float
    gap_z:            float
    informed_flow:    float
    volume_z:         float
    ofi_z:            float
    cvd_slope_z:      float
    cmf:              float
    rel_volume:       float
    vwap_dev_sigma:   float
    atr_z:            float
    vol_ratio:        float
    # Session-level (4)
    poc_dist_atr:     float
    va_position:      float
    sr_support_dist:  float
    sr_resist_dist:   float
    # Regime-level (7)
    hmm_regime_prob:  float
    hmm_entropy:      float
    hurst:            float
    shannon:          float
    garch_ratio:      float
    hma_slope_z:      float
    adx:              float
    # Cross-asset (3)
    vix_z:            float
    flight_quality:   float
    yield_slope_z:    float
    # Calendar (5)
    in_ny_session:    float
    in_overlap:       float
    dow_sin:          float
    dow_cos:          float
    month_position:   float
    # Cross-timeframe (3)
    ctf_momentum:     float
    ctf_vwap_align:   float
    ctf_regime_align: float
```

**FeatureFactoryConfig frozen dataclass** — from `A-RESEARCH.md` Pattern 2:
```python
@dataclass(frozen=True)
class FeatureFactoryConfig:
    momentum_window_short: int    # feature.momentum.window_short
    momentum_window_long: int     # feature.momentum.window_long
    momentum_zscore_window: int   # feature.momentum.zscore_window
    volume_zscore_window: int     # feature.volume.zscore_window
    ofi_zscore_window: int        # feature.ofi.zscore_window
    cvd_slope_bars: int           # feature.cvd.slope_bars
    cmf_period: int               # feature.cmf.period
    vol_short_bars: int           # feature.vol.short_bars
    vol_long_bars: int            # feature.vol.long_bars
    hma_period: int               # feature.hma.period
    adx_period: int               # feature.adx.period
    hurst_window: int             # feature.hurst.window
    garch_window: int             # feature.garch.window
    vix_zscore_window: int        # feature.vix.zscore_window
    yield_curve_zscore_window: int  # feature.yield_curve.zscore_window
    regime_cache_refresh_bars: int  # feature.regime.cache_refresh_bars
```

**Rolling z-score pattern** — from `A-RESEARCH.md` Code Examples (confirmed from `src/intelligence/context/vix_context.py`):
```python
from collections import deque
import numpy as np

def _rolling_zscore(value: float, history: deque, window: int) -> float:
    history.append(value)
    if len(history) < window:
        return 0.0
    arr = np.array(list(history)[-window:])
    std = arr.std()
    if std < 1e-8:
        return 0.0
    return float((value - arr.mean()) / std)
```

**ATR extraction pattern** — from `src/intelligence/features/i1_indicators/atr.py` lines 51-81:
```python
# Use existing ATR computation logic. For FeatureFactory (OHLCV array, not DataFrame):
# True range = max(high-low, abs(high-prev_close), abs(low-prev_close))
# Wilder's smoothing: ewm(alpha=1/period, adjust=False, min_periods=period).mean()
# The existing atr_14 / atr_20 outputs map directly to the `atr_z` primitive after z-scoring.
# Import from src/intelligence/trading/atr_utils.py for the accessor; replicate core for arrays.
```

**File structure note:** `feature_factory.py` is a single module (not a package). `FeatureFactory`, `FeatureFactoryConfig`, and `FeatureVector` all live in the same file. No `__init__.py` import chain needed. The `feature_cache.py` is a separate module (mutable state, separate from the pure-function library).

---

### `src/intelligence/feature_cache.py` (utility, state container)

**Analog:** `src/intelligence/features/smc_context/hmm_regime.py` (state dict pattern), `src/intelligence/context/garch_volatility.py` (incremental state pattern)

**Mutable state dataclass pattern** — from `A-RESEARCH.md` Pattern 3:
```python
from dataclasses import dataclass, field

@dataclass
class FeatureCache:
    # Regime-level (refreshed every regime_cache_refresh_bars bars)
    hmm_regime_prob: float = 0.0
    hmm_entropy: float = 0.0
    hurst: float = 0.5
    shannon: float = 1.0
    garch_ratio: float = 1.0
    hma_slope_z: float = 0.0
    adx: float = 0.0
    bars_since_regime_refresh: int = 0

    # Cross-asset cached from HTF bars (updated on HTF bar arrival)
    vix_z: float = 0.0
    flight_quality: float = 0.0
    yield_slope_z: float = 0.0

    # CTF from HTF cached state
    ctf_momentum: float = 0.0
    ctf_vwap_align: float = 0.0
    ctf_regime_align: float = 0.0

    # Session-level VP (reset at session open)
    poc_dist_atr: float = 0.0
    va_position: float = 0.5
    sr_support_dist: float = 0.0
    sr_resist_dist: float = 0.0
```

**Critical:** `FeatureCache` is NOT frozen (unlike `FeatureVector`). It is mutated by `IntelligencePipeline` between bars. One `FeatureCache` instance per `(symbol, tf)` pair, stored in a dict keyed by `(symbol, tf)`. Use the same `_state(key)` factory pattern as `SignalTracker._signal_states`.

---

### `src/intelligence/schemas.py` (modify — add FeatureVector dataclass)

**Analog:** `src/intelligence/schemas.py` lines 1-65 (existing file — extend, do not replace)

**Existing import block** (lines 1-31):
```python
from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.core.schemas.bar_message import SessionType
from src.core.schemas.intelligence_journal import IntelligenceJournal, ProvenanceChain  # noqa: F401
```

**Addition pattern:** Insert the `FeatureVector` and `FeatureVectorRecord` dataclasses AFTER the existing Pydantic models. Do not disturb `TIER_DB_COLUMNS`, `OHLCVBar`, `IntelligenceEvent`, or `BarIntelligenceRecord`. The `FeatureVector` is a stdlib `dataclass`, not a Pydantic model, consistent with the frozen dataclass decision (D-08).

**FeatureVectorRecord** (the Kafka-wire wrapper — add alongside `FeatureVector`):
```python
@dataclass(frozen=True)
class FeatureVectorRecord:
    """Wire envelope for Kafka transport: FeatureVector + persistence metadata."""
    symbol: str
    tf: str
    bar_ts: datetime        # UTC bar open timestamp
    pipeline_version: str   # e.g. "3.0.0"
    regime: str | None      # HMM state label: "ranging", "trending_up", "trending_down"
    regime_label_source: str  # always "filtered" (D-07)
    vector: FeatureVector
```

---

### `src/core/stream_keys.py` (modify — add topic_feature_vectors)

**Analog:** `src/core/stream_keys.py` lines 146-160 (DLQ pattern also needed)

**Addition pattern** — copy exactly from `topic_intelligence_journal` (line 147-149):
```python
def topic_feature_vectors(env_name: str) -> str:
    """Kafka topic for FeatureVectorRecord per bar, consumed by feature_writer.
    Published by IntelligencePipeline after FeatureFactory.compute().
    """
    return f"{env_prefix(env_name)}intelligence.feature_vectors"


def topic_feature_vectors_dlq(env_name: str) -> str:
    """Dead letter queue for feature_writer unparseable FeatureVectorRecord payloads."""
    return f"{env_prefix(env_name)}intelligence.feature_vectors.dlq"
```

**Insert location:** After `topic_intelligence_journal` (line 149). Before the DLQ block (line 352). The DLQ function goes in the DLQ block near `topic_feature_writer_dlq` (line 371).

---

### `src/config/config_service.py` (modify — add "alpha." prefix)

**Analog:** `src/config/config_service.py` lines 39-51 (OPS_PREFIXES tuple)

**One-line change** at line 39-51:
```python
OPS_PREFIXES: ClassVar[tuple[str, ...]] = (
    "regime.",
    "swarm.",
    "alert.",
    "ai.",
    "feature.",
    "threshold.",
    "roll.",
    "cross_asset.",
    "macro.",
    "ui.",
    "weights.",
    "alpha.",      # ADD THIS LINE — required before any alpha.* APR write (A-RESEARCH Pitfall 4)
)
```

**Critical:** This MUST be done before the APR seed migration runs, or `ON CONFLICT DO NOTHING` inserts will succeed in DB but `ConfigService.set()` calls will raise `ConfigValidationError`.

---

### `services/feature_writer.py` (modify — retarget to feature_vectors)

**Analog:** `services/feature_writer.py` itself — all infrastructure stays, only the write target and schema change

**Topic change** — current lines 37-40 / 322-323:
```python
# BEFORE (line 39):
from src.core.stream_keys import (
    topic_cross_asset,
    topic_feature_writer_dlq,
    topic_intelligence_journal,
)

# AFTER:
from src.core.stream_keys import (
    topic_feature_vectors,
    topic_feature_vectors_dlq,
)
# Remove topic_cross_asset import (no longer needed — cross-asset is in FeatureCache)

# _topic_name() change (line 321-322):
def _topic_name(self) -> str:
    return topic_feature_vectors(self.env_name)

@property
def topics_consumed(self) -> list[str]:
    return [topic_feature_vectors(self.env_name)]
```

**Schema validation change** — current line 392-406 (`_verify_schema`):
```python
# BEFORE: verifies intelligence_features columns
_VERIFY_SCHEMA_SQL = (
    "SELECT column_name FROM information_schema.columns"
    " WHERE table_name = 'intelligence_features' AND table_schema = 'public'"
)

# AFTER: verify feature_vectors columns
_VERIFY_SCHEMA_SQL = (
    "SELECT column_name FROM information_schema.columns"
    " WHERE table_name = 'feature_vectors' AND table_schema = 'public'"
)
_REQUIRED_COLUMNS: frozenset[str] = frozenset({
    "symbol", "tf", "bar_ts", "pipeline_version",
    "momentum_z_5", "momentum_z_20", "hurst", "atr_z",  # spot-check set
})
```

**INSERT SQL change** — replace `_INSERT_FEATURE_SQL` (lines 72-114) with `_INSERT_FEATURE_VECTOR_SQL`:
```python
_INSERT_FEATURE_VECTOR_SQL = """
INSERT INTO feature_vectors (
    symbol, tf, bar_ts, pipeline_version, regime, regime_label_source,
    momentum_z_5, momentum_z_20, range_position, bar_close_pos, gap_z,
    informed_flow, volume_z, ofi_z, cvd_slope_z, cmf, rel_volume,
    vwap_dev_sigma, atr_z, vol_ratio,
    poc_dist_atr, va_position, sr_support_dist, sr_resist_dist,
    hmm_regime_prob, hmm_entropy, hurst, shannon, garch_ratio, hma_slope_z, adx,
    vix_z, flight_quality, yield_slope_z,
    in_ny_session, in_overlap, dow_sin, dow_cos, month_position,
    ctf_momentum, ctf_vwap_align, ctf_regime_align
)
VALUES (
    $1, $2, $3, $4, $5, $6,
    $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20,
    $21, $22, $23, $24,
    $25, $26, $27, $28, $29, $30, $31,
    $32, $33, $34,
    $35, $36, $37, $38, $39,
    $40, $41, $42
)
ON CONFLICT (symbol, tf, bar_ts) DO NOTHING
"""
```

**`_parse_payload` change** — replace `BarIntelligenceRecord.model_validate` with `FeatureVectorRecord` deserialization:
```python
# BEFORE: from src.intelligence.schemas import CTF_DEDICATED_COLUMNS, BarIntelligenceRecord
# AFTER:
from src.intelligence.schemas import FeatureVectorRecord

def _parse_payload(self, payload: dict) -> tuple[list, list]:
    try:
        record = FeatureVectorRecord(**payload)  # or dataclasses.asdict inverse
    except (TypeError, KeyError, ValueError):
        self._parse_errors_total.add(1)
        return [], [payload]
    params = _record_to_insert_params(record)
    return [params], []
```

**Remove:** `_build_expiry_map`, `_compute_days_to_expiry`, `_cross_asset_cache`, `_process_cross_asset_message`. None apply to `feature_vectors`. The `_periodic_flush_loop` and `_health_monitor_loop` patterns are preserved exactly.

**`_flush_batch` change** — line 376: replace `_INSERT_FEATURE_SQL` with `_INSERT_FEATURE_VECTOR_SQL`. All OTel/span patterns stay identical.

**Consumer group rename:** `"feature_writer_group"` → `"feature_vector_writer_group"` to avoid offset collision with any existing consumer state.

---

### `production/migrations/155_feature_vectors.sql` (migration)

**Analog:** `production/migrations/153_hmm_garch_kalman_apr.sql` — idempotent APR seeding pattern

**Migration structure pattern** — from `production/migrations/153_hmm_garch_kalman_apr.sql` lines 1-134:
```sql
-- Migration 155: feature_vectors hypertable + backfill_status + APR seed keys.
-- All inserts are idempotent: ON CONFLICT ... DO NOTHING.
-- Safe to re-run.

-- -------------------------------------------------------------------------
-- 1. feature_vectors hypertable
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feature_vectors (
    symbol              text             NOT NULL,
    tf                  text             NOT NULL,
    bar_ts              timestamptz      NOT NULL,
    pipeline_version    text             NOT NULL,
    regime              text,
    regime_label_source text             NOT NULL DEFAULT 'filtered'
                        CHECK (regime_label_source IN ('filtered', 'unknown')),
    -- Bar-level (14)
    momentum_z_5        double precision,
    momentum_z_20       double precision,
    -- [... all 35 columns per CONTEXT.md <specifics> — column list is binding]
    PRIMARY KEY (symbol, tf, bar_ts)
);

SELECT create_hypertable(
    'feature_vectors', 'bar_ts',
    chunk_time_interval => INTERVAL '3 months',
    if_not_exists => TRUE
);
SELECT add_compression_policy('feature_vectors', INTERVAL '6 months', if_not_exists => TRUE);

-- -------------------------------------------------------------------------
-- 2. backfill_status checkpoint table
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS backfill_status (
    symbol       text NOT NULL,
    tf           text NOT NULL,
    status       text NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'in_progress', 'complete', 'failed')),
    rows_written bigint,
    theoretical_max bigint,
    started_at   timestamptz,
    completed_at timestamptz,
    error_msg    text,
    PRIMARY KEY (symbol, tf)
);

-- -------------------------------------------------------------------------
-- 3. APR config_schema entries (feature.* keys)
-- -------------------------------------------------------------------------
INSERT INTO config_schema (config_key, value_type, default_value, description) VALUES
    ('feature.momentum.window_short', 'int', '5',   '[conventional] Short momentum lookback bars'),
    ('feature.momentum.window_long',  'int', '20',  '[conventional] Long momentum lookback bars'),
    -- [all feature.* keys per A-RESEARCH.md Code Examples: APR Seeding Migration]
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- 4. APR config_state entries (seed values = defaults)
-- -------------------------------------------------------------------------
INSERT INTO config_state (config_key, config_value, version) VALUES
    ('feature.momentum.window_short', '5', 1),
    -- [all feature.* and alpha.vector.v1_quant.members entries]
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- 5. alpha.vector APR keys (requires "alpha." in OPS_PREFIXES — code change first)
-- -------------------------------------------------------------------------
INSERT INTO config_schema (config_key, value_type, default_value, description) VALUES
    ('alpha.vector.v1_quant.members', 'str',
     'momentum_z_5,momentum_z_20,hma_slope_z,range_position,bar_close_pos,atr_z,vol_ratio,ctf_momentum',
     '[initial_estimate] V1 Quant vector constituent primitives. Mutable via APR. IC discovery may prune members.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('alpha.vector.v1_quant.members',
     'momentum_z_5,momentum_z_20,hma_slope_z,range_position,bar_close_pos,atr_z,vol_ratio,ctf_momentum',
     1)
ON CONFLICT (config_key) DO NOTHING;
```

**Column list authority:** CONTEXT.md `<specifics>` section is the binding column list. The DDL snippet in `v30-ground-up-architecture.md` is illustrative and contains extra columns not in the locked 35-primitive list — do NOT use it as the DDL source.

---

### `services/backfill_feature_factory.py` (oneshot service, batch)

**Analog:** `production/scripts/run_historical_pipeline.py` — chunked IBKR fetch + psycopg2 batch insert pattern

**Imports pattern** — from `run_historical_pipeline.py` lines 55-119:
```python
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
import structlog

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings, get_active_contracts
from src.core.database_manager import DatabaseManager
from src.core.service_utils import TF_SECONDS
from src.intelligence.feature_factory import FeatureFactory, FeatureFactoryConfig
```

**Checkpoint/resume pattern** — from `run_historical_pipeline.py` `pending` status pattern (lines 969/1043):
```python
# Write checkpoint at start of each (symbol, tf) pair
conn.execute(
    "INSERT INTO backfill_status (symbol, tf, status, started_at)"
    " VALUES (%s, %s, 'in_progress', NOW())"
    " ON CONFLICT (symbol, tf) DO UPDATE SET status='in_progress', started_at=NOW()",
    (symbol, tf),
)

# On completion
conn.execute(
    "UPDATE backfill_status SET status='complete', rows_written=%s,"
    " theoretical_max=%s, completed_at=NOW() WHERE symbol=%s AND tf=%s",
    (rows_written, theoretical_max, symbol, tf),
)

# Skip complete pairs on resume
pending = conn.execute(
    "SELECT symbol, tf FROM backfill_status WHERE status NOT IN ('complete')"
    " ORDER BY symbol, tf"
).fetchall()
```

**Chunked bar read pattern** — from `run_historical_pipeline.py` lines 499-540 (sliding window, no full-table load):
```python
# For each chunk (500-bar window advancing one bar at a time):
# Read from market_data_ohlcv with LIMIT/OFFSET or cursor-based pagination
# Apply FeatureFactory.compute(bars_window, symbol, tf) -> FeatureVector
# Accumulate into batch list; flush every 500 rows via executemany
```

**Service type:** Oneshot (not a daemon). Follows the `_agent.py` exception pattern from CLAUDE.md — use `argparse` + `asyncio.run(main())` entrypoint, same as `run_historical_pipeline.py`. Emit `job_completed_total{job=backfill-feature-factory, status=success|failure}` OTel counter at exit (D-06 from CLAUDE.md oneshot contract).

**Client ID:** Always `--client-id 40` for IBKR fetch. Never 35 (provider) or 56+ (exceeds `_MAX_CLIENT_ID=50`).

**Target timeframes:** `5m`, `15m`, `1h`, `1d` only — backfill at full configured depths. `1m` is not a backfill target (90d depth, 58 ETFs × 75k bars = operationally large; use live pipeline for 1m).

---

## Shared Patterns

### APR Prewarm Registration
**Source:** `services/intelligence_pipeline.py` lines 540-579 (`_prewarm_threshold_config`)
**Apply to:** `services/intelligence_pipeline.py` (modify) + `services/backfill_feature_factory.py` (init)

```python
# In _prewarm_threshold_config() — extend _THRESHOLD_KEYS with all feature.*:
_THRESHOLD_KEYS: tuple[tuple[str, Any], ...] = (
    # ... existing keys ...
    # ADD:
    ("feature.momentum.window_short", 5),
    ("feature.momentum.window_long", 20),
    ("feature.momentum.zscore_window", 252),
    ("feature.volume.zscore_window", 20),
    ("feature.ofi.zscore_window", 20),
    ("feature.cvd.slope_bars", 5),
    ("feature.cmf.period", 20),
    ("feature.vol.short_bars", 5),
    ("feature.vol.long_bars", 20),
    ("feature.hma.period", 20),
    ("feature.adx.period", 14),
    ("feature.hurst.window", 252),
    ("feature.garch.window", 100),
    ("feature.vix.zscore_window", 252),
    ("feature.yield_curve.zscore_window", 252),
    ("feature.regime.cache_refresh_bars", 30),
)

# In _prewarm_threshold_config() body — add FeatureFactory injection:
from src.intelligence import feature_factory
feature_factory.set_config_service(self._config_service)
```

### Kafka Publish Pattern
**Source:** CLAUDE.md key rule — `KafkaProducerClient.publish()` kwarg is `msg=` not `value=`
**Apply to:** `services/intelligence_pipeline.py` (FeatureFactory publish call)

```python
# Correct:
await self._kafka_producer.publish(
    topic_feature_vectors(self.env_name),
    msg=record_dict,
    key=message_key(symbol, tf),
)
# NEVER: publish(topic, value=...)  -- silently fails at flush
```

### Error Handling (writer)
**Source:** `services/feature_writer.py` lines 344-364 (`_parse_payload`)
**Apply to:** Modified `feature_writer.py` `_parse_payload`

```python
def _parse_payload(self, payload: dict) -> tuple[list, list]:
    try:
        # parse FeatureVectorRecord
        ...
    except (TypeError, KeyError, ValueError):
        self._parse_errors_total.add(1)
        return [], [payload]   # [], [invalid] — no DLQ for single row, but counted
    if record is None:
        return [], [payload]
    params = _record_to_insert_params(record)
    return [params], []
```

**Return contract (from CLAUDE.md):** `None` → DLQ whole payload. `[]` → all-invalid (no DLQ). Return `None` only for truly unparseable payloads (wrong schema entirely).

### Timestamp Handling
**Source:** CLAUDE.md key rule
**Apply to:** All new files

```python
# Always:
from datetime import UTC, datetime
datetime.now(UTC)

# Serialize with:
from src.core.service_utils import format_iso_ts
format_iso_ts(dt)   # never .isoformat().replace("+00:00", "Z")
```

### OTel Metrics Pattern
**Source:** `services/feature_writer.py` lines 283-312
**Apply to:** `services/backfill_feature_factory.py` (oneshot exit metric)

```python
# Oneshot: emit job_completed_total at exit
from src.observability.metrics import counter
job_completed = counter("job_completed_total", "Oneshot job completions")
job_completed.add(1, {"job": "backfill-feature-factory", "status": "success"})
```

### structlog event kwarg collision
**Source:** CLAUDE.md key rule
**Apply to:** All new log calls

```python
# NEVER:
logger.info("msg", event="something")   # collides with structlog reserved kwarg

# ALWAYS use alternative keys:
logger.info("msg", data="something", payload="...", signal="...")
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `services/backfill_feature_factory.py` (new-style checkpoint) | service (oneshot) | batch | `run_historical_pipeline.py` has a "pending" concept but no `backfill_status` table pattern. The checkpoint/resume logic in the new script is a novel pattern; planner should implement per D-11 spec in A-CONTEXT.md. |

---

## Metadata

**Analog search scope:** `src/intelligence/context/`, `src/intelligence/features/`, `services/feature_writer.py`, `services/intelligence_pipeline.py`, `src/core/stream_keys.py`, `src/config/config_service.py`, `production/migrations/`, `production/scripts/run_historical_pipeline.py`

**Files scanned:** 12 source files read directly; 6 grepped for pattern location

**Key findings that affect planning:**

1. `OPS_PREFIXES` in `config_service.py` (line 39) does NOT contain `"alpha."` — the code change must precede the migration or `config_state` inserts for `alpha.*` keys will be orphaned (readable from DB but rejected by `ConfigService.set()`).

2. `topic_cross_asset` import in `feature_writer.py` is futures/cross-asset specific and is removed entirely in the retargeted writer. The `_process_cross_asset_message` and `_cross_asset_cache` code blocks are deleted — cross-asset values come from `FeatureCache` pre-populated by `IntelligencePipeline`.

3. `FeatureWriter` consumer group must be renamed (`feature_vector_writer_group`) — the existing `feature_writer_group` has committed offsets on `intelligence.journal` topic; a name collision would cause the new writer to attempt reading from the old topic's offset position.

4. `_THRESHOLD_KEYS` in `intelligence_pipeline.py` already uses the `feature.*` namespace (lines 411-538) — the new `feature.momentum.*`, `feature.vol.*`, etc. keys are additive entries, not replacements.

5. HMM forward-only path is confirmed: `hmm_regime.py` only calls `_forward_step()` (lines 237, 279, 313, 378) — no backward smoother function exists in the file. D-07 is satisfied by the existing implementation.

**Pattern extraction date:** 2026-06-20
