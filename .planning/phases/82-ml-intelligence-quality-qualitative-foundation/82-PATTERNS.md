# Phase 82: ML Intelligence Quality & Qualitative Foundation — Pattern Map

**Mapped:** 2026-05-13
**Files analyzed:** 14 new/modified files
**Analogs found:** 14 / 14

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/intelligence/features/smc_context/hmm_regime.py` (modify) | plugin | transform | itself — parameterize existing class | exact |
| `src/intelligence/register_plugins.py` (modify) | config | transform | itself — add 3 new instances | exact |
| `src/intelligence/schemas.py` (modify) | model | transform | itself — add entropy/velocity fields | exact |
| `src/intelligence/services/hmm_training_compute_agent.py` (new) | service | batch | `src/intelligence/services/ml_training_compute_agent.py` | exact |
| `services/hmm_training_agent.py` (new) | entrypoint | batch | `services/ml_training_agent.py` | exact |
| `production/systemd/indicagent-hmm-training.service` (new) | config | — | `production/systemd/indicagent-data-quality.timer` + `indicagent-ml-training.service` | exact |
| `production/systemd/indicagent-hmm-training.timer` (new) | config | — | `production/systemd/indicagent-ml-training.timer` | exact |
| `src/intelligence/pipeline/regime_gate.py` (modify) | utility | transform | itself — add soft multiplier band | exact |
| `src/config/settings.py` (modify) | config | — | itself — add `REGIME_PROB_SOFT_MAX` | exact |
| `src/observability/metrics.py` (modify) | utility | — | itself — register new counters | exact |
| `src/intelligence/services/feature_validation_compute_agent.py` (new) | service | batch | `src/intelligence/services/ml_training_compute_agent.py` | role-match |
| `services/feature_validation_agent.py` (new) | entrypoint | batch | `services/ml_training_agent.py` | exact |
| `production/systemd/indicagent-feature-validation.service+timer` (new) | config | — | `production/systemd/indicagent-ml-training.service+timer` | exact |
| `production/migrations/085_ctx_schema.sql` (new) | migration | — | `production/migrations/084_ai_enrichment_tables.sql` | exact |
| `production/migrations/086_validation_results.sql` (new) | migration | — | `production/migrations/077_shadow_governance.sql` | role-match |
| `src/core/stream_keys.py` (modify) | utility | — | itself — add `topic_ctx_snapshot()` | exact |
| `services/ctx_writer_agent.py` (new) | service | event-driven | `services/lifecycle_writer_agent.py` | exact |
| `services/feature_writer_agent.py` (modify) | service | CRUD | itself — add as-of join for ctx | exact |
| `src/api/routes/validation.py` (new) | route | request-response | `src/api/routes/features.py` | role-match |
| `src/api/main.py` (modify) | config | — | itself — add validation router | exact |

---

## Pattern Assignments

### `src/intelligence/features/smc_context/hmm_regime.py` (modify — parameterize for multi-TF)

**Analog:** itself — `src/intelligence/features/smc_context/hmm_regime.py`

**Current class signature** (lines 80–111):
```python
@dataclass
class HMMRegimePlugin:
    name: str = "smc_HMMRegime"
    outputs: frozenset[str] = frozenset({
        "hmm_regime", "hmm_regime_prob", "hmm_prob_ranging",
        "hmm_prob_trending_up", "hmm_prob_trending_down",
        "hmm_regime_duration", "hmm_n_dims", "hmm_warmed_up",
    })
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"smart_money"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=200),)
    vol_window: int = 20
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._A, self._means, self._variances = _load_parameters()
        self._K = self._A.shape[0]
```

**Parameterization target** (replace class-level defaults with init params):
```python
@dataclass
class HMMRegimePlugin:
    timeframe: str = "1m"
    lookback: int = 200
    name: str = field(init=False)
    inputs: tuple[InputSpec, ...] = field(init=False)
    outputs: frozenset[str] = field(init=False)
    # ... rest unchanged

    def __post_init__(self) -> None:
        self.name = f"smc_HMMRegime_{self.timeframe}"
        self.inputs = (InputSpec(symbol=".*", timeframe=self.timeframe, lookback=self.lookback),)
        self.outputs = frozenset({
            "hmm_regime", "hmm_regime_prob", "hmm_prob_ranging",
            "hmm_prob_trending_up", "hmm_prob_trending_down",
            "hmm_regime_duration", "hmm_n_dims", "hmm_warmed_up",
            "hmm_regime_entropy", "hmm_regime_velocity",  # D-04 additions
        })
        tf_config = Path(f"config/hmm_parameters_{self.timeframe}.json")
        base_config = Path("config/hmm_parameters.json")
        self._A, self._means, self._variances = _load_parameters(
            tf_config if tf_config.exists() else base_config
        )
        self._K = self._A.shape[0]
```

**`_load_parameters()` extension** — add path argument (currently line 48 takes no args):
```python
def _load_parameters(
    path: Path = _CONFIG_PATH,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Load parameters from JSON if available, otherwise use defaults."""
    if path.exists():
        with open(path) as f:
            data = json.load(f)
        return (
            np.array(data["transition_matrix"], dtype=float),
            np.array(data["emission_means"], dtype=float),
            np.array(data["emission_variances"], dtype=float),
        )
    return _DEFAULT_TRANSITION.copy(), _DEFAULT_MEANS.copy(), _DEFAULT_VARIANCES.copy()
```

**`_reset_state()` extension** — add velocity history deque (currently line 266):
```python
def _reset_state(self) -> None:
    self._state = {
        "alpha": np.full(self._K, 1.0 / self._K),
        "prev_close": 0.0,
        "return_buffer": deque(maxlen=self.vol_window),
        "prev_regime": 0,
        "regime_duration": 1,
        "bars_processed": 0,
        "n_dims": 2,
        # D-04 additions — velocity history, TF-adaptive window
        "prob_history": deque(maxlen=_VELOCITY_WINDOW.get(self.timeframe, 5)),
    }
```

**`_build_output()` extension** — add entropy + velocity (currently line 278):
```python
def _build_output(self) -> dict[str, Any]:
    alpha = self._state["alpha"]
    regime = int(np.argmax(alpha))
    bars_processed = self._state.get("bars_processed", 0)
    warmed_up = bars_processed >= self.min_lookback
    regime_prob = round(float(alpha[regime]), 6)

    # D-04: Shannon entropy across 3 state probabilities
    p = np.maximum(alpha, 1e-10)
    entropy = float(-np.sum(p * np.log2(p)))

    # D-04: velocity = rate of change of dominant state prob
    prob_history = self._state.get("prob_history", deque())
    prob_history.append(regime_prob)
    velocity = 0.0
    if len(prob_history) >= 2:
        velocity = float(prob_history[-1] - prob_history[0]) / len(prob_history)

    return {
        "hmm_regime": float(regime),
        "hmm_regime_prob": regime_prob if warmed_up else 0.0,
        "hmm_prob_ranging": round(float(alpha[0]), 6) if warmed_up else 0.0,
        "hmm_prob_trending_up": round(float(alpha[1]), 6) if warmed_up else 0.0,
        "hmm_prob_trending_down": round(float(alpha[2]), 6) if warmed_up else 0.0,
        "hmm_regime_duration": float(self._state["regime_duration"]),
        "hmm_n_dims": self._state.get("n_dims", 2),
        "hmm_warmed_up": warmed_up,
        "hmm_regime_entropy": round(entropy, 6) if warmed_up else None,
        "hmm_regime_velocity": round(velocity, 6) if warmed_up else None,
    }
```

**Module bottom** — replace single `plugin = HMMRegimePlugin()` (line 297):
```python
# Velocity window is TF-adaptive (design doc: {1m:5, 5m:5, 15m:4, 1h:3})
_VELOCITY_WINDOW: dict[str, int] = {"1m": 5, "5m": 5, "15m": 4, "1h": 3}

# Four per-TF instances — registered individually in register_plugins.py
hmm_1m_plugin  = HMMRegimePlugin(timeframe="1m",  lookback=200)
hmm_5m_plugin  = HMMRegimePlugin(timeframe="5m",  lookback=200)
hmm_15m_plugin = HMMRegimePlugin(timeframe="15m", lookback=150)
hmm_1h_plugin  = HMMRegimePlugin(timeframe="1h",  lookback=100)
```

---

### `src/intelligence/register_plugins.py` (modify — replace hmm_plugin with 4 instances)

**Analog:** itself — `src/intelligence/register_plugins.py` lines 497–511

**Current TIER_SMC** (lines 497–511):
```python
TIER_SMC: list[str] = [
    bos_choch_plugin.name,
    fvg_plugin.name,
    ...
    hmm_plugin.name,        # <-- replace with 4 names
    ...
]
```

**Target** — import 4 instances, add all 4 names:
```python
from src.intelligence.features.smc_context.hmm_regime import (
    hmm_1m_plugin, hmm_5m_plugin, hmm_15m_plugin, hmm_1h_plugin,
)

TIER_SMC: list[str] = [
    bos_choch_plugin.name,
    fvg_plugin.name,
    ob_plugin.name,
    liq_sweep_plugin.name,
    bocpd_plugin.name,
    hmm_1m_plugin.name,     # replaces hmm_plugin
    hmm_5m_plugin.name,
    hmm_15m_plugin.name,
    hmm_1h_plugin.name,
    liquidity_pools_plugin.name,
    ...
]
```

---

### `src/intelligence/schemas.py` (modify — add entropy/velocity fields)

**Analog:** itself — lines 645–653 (SMCContext HMM fields)

**Current SMCContext HMM fields** (lines 645–653):
```python
class SMCContext(BaseModel):
    # ... other fields ...
    hmm_regime: float | None = None
    hmm_regime_prob: float | None = None
    hmm_prob_ranging: float | None = None
    hmm_prob_trending_up: float | None = None
    hmm_prob_trending_down: float | None = None
    hmm_regime_duration: float | None = None
    hmm_n_dims: int | None = None
    hmm_warmed_up: bool | None = None
```

**Add after `hmm_warmed_up`** (no `extra="forbid"` on SMCContext — safe to add):
```python
    # D-04: regime transition early detection fields (Phase 82)
    hmm_regime_entropy: float | None = None
    hmm_regime_velocity: float | None = None
```

---

### `src/intelligence/services/hmm_training_compute_agent.py` (new)

**Analog:** `src/intelligence/services/ml_training_compute_agent.py`

**Imports pattern** (copy from ml_training_compute_agent.py lines 22–47):
```python
from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import numpy as np
import structlog
from hmmlearn import hmm as hmmlib

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.database_manager import create_pool as create_db_pool
from src.core.service_utils import setup_service_logging
```

**Class structure** (mirror `MLTrainingComputeAgent` pattern lines 74–115):
```python
class HMMTrainingComputeAgent(BaseAgent):
    """Per-TF pooled HMM training agent.

    Systemd Type=oneshot. Reads intelligence_features (excluding is_backfill=TRUE),
    trains GaussianHMM via Baum-Welch per TF, writes config/hmm_parameters_{tf}.json,
    sends SIGUSR1 to indicagent-intelligence-pipeline.
    """

    _PIPELINE_UNIT = "indicagent-intelligence-pipeline"
    _TIMEFRAMES = ["1m", "5m", "15m", "1h"]
    _MIN_ROWS = 200  # minimum rows before training

    def __init__(self, settings: Settings) -> None:
        setup_service_logging("logs/hmm_training_compute_agent.log")
        super().__init__("HMMTrainingComputeAgent")
        self.settings = settings
        self._pool: asyncpg.Pool | None = None

    async def _setup(self) -> None:
        self._pool = await create_db_pool(self.settings.database_url)
        logger.info("hmm_training.setup_complete")

    async def _teardown(self) -> None:
        if self._pool:
            await self._pool.close()

    async def _run(self) -> None:
        """Catch all exceptions — systemd oneshot exit 0 semantics."""
        try:
            await self._train_all_tfs()
        except Exception:
            logger.exception("hmm_training.error_top_level")
            return  # intentional: exit 0 so timer fires again
```

**Delta gate pattern** (copy `_should_retrain` structure from lines 138–159):
```python
    async def _train_all_tfs(self) -> None:
        promoted_any = False
        for tf in self._TIMEFRAMES:
            success = await self._train_tf(tf)
            if success:
                promoted_any = True
        if promoted_any:
            self._signal_pipeline_reload()

    def _signal_pipeline_reload(self) -> None:
        """Send SIGUSR1 to indicagent-intelligence-pipeline."""
        result = subprocess.run(
            ["systemctl", "kill", "-s", "SIGUSR1", self._PIPELINE_UNIT],
            capture_output=True, check=False,
        )
        logger.info(
            "hmm_training.pipeline_reload_signal_sent",
            returncode=result.returncode,
        )
```

**Training query** — exclude backfill (Pitfall 5 from RESEARCH.md):
```python
    async def _fetch_observations(self, conn, tf: str) -> list[dict]:
        rows = await conn.fetch(
            """
            SELECT ts, i1
            FROM intelligence_features
            WHERE tf = $1
              AND is_backfill IS NOT TRUE
            ORDER BY ts ASC
            """,
            tf,
        )
        return [dict(r) for r in rows]
```

**Parameter write pattern** (mirror `_write_checkpoint` pattern lines 128–136):
```python
    def _write_parameters(self, tf: str, model: hmmlib.GaussianHMM) -> None:
        path = Path(f"config/hmm_parameters_{tf}.json")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "transition_matrix": model.transmat_.tolist(),
            "emission_means": model.means_.tolist(),
            "emission_variances": model.covars_.tolist(),
            "trained_at": datetime.now(UTC).isoformat(),
            "timeframe": tf,
        }))
        tmp.replace(path)
        logger.info("hmm_training.params_written", tf=tf, path=str(path))
```

---

### `services/hmm_training_agent.py` (new)

**Analog:** `services/ml_training_agent.py` (lines 1–31) — copy verbatim, change import/class name:

```python
"""HMM Training Agent — systemd oneshot entrypoint (Phase 082).

Invoked monthly by indicagent-hmm-training.timer.
Type=oneshot: runs once, exits.
"""

from __future__ import annotations

import asyncio

import _path_bootstrap  # noqa: F401 — project root on sys.path

from src.config.settings import Settings
from src.intelligence.services.hmm_training_compute_agent import HMMTrainingComputeAgent


def main() -> None:
    settings = Settings()
    agent = HMMTrainingComputeAgent(settings)
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
```

---

### `production/systemd/indicagent-hmm-training.service` (new)

**Analog:** `production/systemd/indicagent-data-quality.timer` header + ml-training.service body

Copy `indicagent-ml-training.service` exactly, change:
- `Description` → `IndicAgent HMM Training Compute Agent — monthly Baum-Welch training`
- `ExecStart` → `services/hmm_training_agent.py`
- `TimeoutStartSec=3600` (1h — smaller than ML training's 7200s)

```ini
[Unit]
Description=IndicAgent HMM Training Compute Agent — monthly Baum-Welch training
After=network.target

[Service]
Type=oneshot
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
Environment=INDICAGENT_ENV=development
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/hmm_training_agent.py
TimeoutStartSec=3600

[Install]
WantedBy=multi-user.target
```

### `production/systemd/indicagent-hmm-training.timer` (new)

**Analog:** `production/systemd/indicagent-ml-training.timer` — copy, change schedule to monthly:

```ini
[Unit]
Description=HMM Training Timer — monthly 02:00 UTC first of month

[Timer]
OnCalendar=*-*-01 02:00:00 UTC
Persistent=true
Unit=indicagent-hmm-training.service

[Install]
WantedBy=timers.target
```

---

### `src/intelligence/pipeline/regime_gate.py` (modify — soft multiplier)

**Analog:** itself — lines 1–125

**Current binary gate** (lines 95–97):
```python
        if hmm_regime_prob < prob_min:
            regime_eligible = False
            suppression_reason = "regime_prob"
```

**New function signature** — add `prob_soft_max` parameter after `prob_min`:
```python
async def apply_regime_gate(
    signals: list[dict],
    regime_data: dict | None,
    *,
    prob_min: float = 0.30,
    prob_soft_max: float = 0.55,   # NEW — D-04
    dur_min: int = 1,
    tf: str | None = None,
    recorder: TransformRecorder | None = None,
) -> list[dict]:
```

**Add helper at module top** (before `apply_regime_gate`):
```python
_SOFT_BAND_FLOOR = 0.5  # minimum multiplier at prob == prob_min boundary

def _soft_multiplier(prob: float, prob_min: float, prob_soft_max: float) -> float:
    """Linear interpolation from 0.5→1.0 across the soft band."""
    t = (prob - prob_min) / (prob_soft_max - prob_min)
    return _SOFT_BAND_FLOOR + (1.0 - _SOFT_BAND_FLOOR) * max(0.0, min(1.0, t))
```

**Replace binary check** (lines 95–97) with three-band logic:
```python
        if hmm_regime_prob < prob_min:
            regime_eligible = False
            suppression_reason = "regime_prob"
        elif hmm_regime_prob < prob_soft_max:
            # Soft band: eligible but confidence reduced
            regime_eligible = True
            suppression_reason = None
            multiplier = _soft_multiplier(hmm_regime_prob, prob_min, prob_soft_max)
            s["calibrated_confidence"] = (
                s.get("calibrated_confidence", s.get("confidence", 0.5)) * multiplier
            )
            from src.observability.metrics import REGIME_SOFT_GATE_SIGNALS_TOTAL
            REGIME_SOFT_GATE_SIGNALS_TOTAL.labels(band="soft").inc()
```

**Call site** — `services/intelligence_pipeline_agent.py` line ~1332 — add `prob_soft_max`:
```python
await apply_regime_gate(
    signals,
    regime_data=features,
    prob_min=self.settings.regime_prob_min,
    prob_soft_max=self.settings.REGIME_PROB_SOFT_MAX,  # NEW
    dur_min=self.settings.regime_dur_min,
    tf=tf,
    recorder=recorder,
)
```

---

### `src/config/settings.py` (modify — add REGIME_PROB_SOFT_MAX)

**Analog:** itself — lines 172–173 (existing `regime_prob_min` + `regime_dur_min`)

**Copy the exact pattern at line 172, add after line 173:**
```python
    regime_prob_min: float = Field(default=0.30, validation_alias="REGIME_PROB_MIN")
    regime_dur_min: int = Field(default=1, validation_alias="REGIME_DUR_MIN")
    REGIME_PROB_SOFT_MAX: float = Field(
        default=0.55,
        validation_alias="REGIME_PROB_SOFT_MAX",
        description="Upper bound of soft confidence band for HMM regime gate (D-04)",
    )
```

---

### `src/observability/metrics.py` (modify — register new counters)

**Analog:** itself — lines 39–60 (existing labeled Counter pattern with `Counter(name, doc, [labels])`)

**Add near bottom of existing named counters** (follow `PERSISTENCE_BATCH_LATENCY` style):
```python
# Phase 82: Regime soft gate band counter (D-04)
REGIME_SOFT_GATE_SIGNALS_TOTAL = Counter(
    "regime_soft_gate_signals_total",
    "Signals processed through soft confidence band in regime gate",
    ["band"],
)

# Phase 82: Feature validation decision counter (D-05)
FEATURE_VALIDATION_DECISIONS_TOTAL = Counter(
    "feature_validation_decisions_total",
    "Feature validation decisions emitted",
    ["decision", "plugin_name"],
)
```

---

### `src/intelligence/services/feature_validation_compute_agent.py` (new)

**Analog:** `src/intelligence/services/ml_training_compute_agent.py`

**Imports pattern** (follow ml_training_compute_agent.py lines 22–47):
```python
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pandas as pd
import structlog

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.database_manager import create_pool as create_db_pool
from src.core.service_utils import setup_service_logging
```

**Import from tools** (validated in RESEARCH.md):
```python
# Import validation logic from existing tool — do not hand-roll IC/p-value
sys.path.insert(0, str(Path(__file__).parents[3] / "tools"))
from validate_i6_backtest import validate_backtest_results, ValidationResults
```

**Class pattern** (mirror `MLTrainingComputeAgent`):
```python
class FeatureValidationComputeAgent(BaseAgent):
    """Daily IC/p-value validation agent.

    Systemd Type=oneshot. Reads intelligence_features + signal_ledger outcomes.
    Writes VALIDATED/TWEAK/KILL decisions to validation_results.
    Updates shadow_registry.promotion_evidence JSONB.
    """

    _TIMEFRAMES = ["1m", "5m", "15m", "1h"]

    def __init__(self, settings: Settings) -> None:
        setup_service_logging("logs/feature_validation_compute_agent.log")
        super().__init__("FeatureValidationComputeAgent")
        self.settings = settings
        self._pool: asyncpg.Pool | None = None

    async def _run(self) -> None:
        """Catch all exceptions — oneshot exit 0 semantics (same as ml_training)."""
        try:
            await self._validate_all()
        except Exception:
            logger.exception("feature_validation.error_top_level")
            return  # intentional
```

**Validation write pattern** (asyncpg dict insert — no json.dumps per CLAUDE.md):
```python
    async def _write_result(self, conn, result: ValidationResults) -> None:
        await conn.execute(
            """
            INSERT INTO validation_results
                (plugin_name, timeframe, regime_type, ic, p_value, n,
                 decision, computed_at, bonferroni_corrected)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            result.plugin_name, result.timeframe, result.regime_type,
            result.ic, result.p_value, result.n, result.decision,
            datetime.now(UTC), result.bonferroni_corrected,
        )
        # Update shadow_registry.promotion_evidence (column added in migration 086)
        evidence = {
            "ic": result.ic, "p_value": result.p_value, "n": result.n,
            "decision": result.decision, "computed_at": datetime.now(UTC).isoformat(),
        }
        await conn.execute(
            """
            UPDATE shadow_registry
               SET promotion_evidence = $2
             WHERE component_name = $1
            """,
            result.plugin_name, evidence,  # asyncpg: pass dict for jsonb, not json.dumps()
        )
```

---

### `services/feature_validation_agent.py` (new)

**Analog:** `services/ml_training_agent.py` — exact same pattern, different class:

```python
"""Feature Validation Agent — systemd oneshot entrypoint (Phase 082).

Invoked daily at 02:00 ET by indicagent-feature-validation.timer.
Type=oneshot: runs once, exits.
"""

from __future__ import annotations
import asyncio
import _path_bootstrap  # noqa: F401

from src.config.settings import Settings
from src.intelligence.services.feature_validation_compute_agent import FeatureValidationComputeAgent


def main() -> None:
    settings = Settings()
    agent = FeatureValidationComputeAgent(settings)
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
```

---

### `production/systemd/indicagent-feature-validation.service + .timer` (new)

**Analog:** `indicagent-ml-training.service` + `indicagent-ml-training.timer`

Service — copy ml-training.service, change ExecStart + Description:
```ini
[Unit]
Description=IndicAgent Feature Validation Compute Agent — daily IC/p-value validation
After=network.target

[Service]
Type=oneshot
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
Environment=INDICAGENT_ENV=development
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/feature_validation_agent.py
TimeoutStartSec=3600

[Install]
WantedBy=multi-user.target
```

Timer — copy ml-training.timer, change schedule to 02:00 ET (07:00 UTC):
```ini
[Unit]
Description=Feature Validation Timer — daily 07:00 UTC (02:00 ET)

[Timer]
OnCalendar=*-*-* 07:00:00 UTC
Persistent=true
Unit=indicagent-feature-validation.service

[Install]
WantedBy=timers.target
```

---

### `production/migrations/085_ctx_schema.sql` (new)

**Analog:** `production/migrations/084_ai_enrichment_tables.sql`

**Copy header style** (migration 084 lines 1–25):
```sql
-- Migration 085: CTX Schema Foundation — qualitative intelligence collection (Phase 082)
-- Idempotent: safe to re-apply.
--
-- Creates qualitative context tables for collection-only phase.
-- No AIContext prompt rendering until Phase 083 shadow validation gate passes.
--
-- Tables created:
--   ctx_events     — append-only qualitative event log
--   ctx_snapshots  — keyed point-in-time snapshots for as-of join
--
-- Column added:
--   intelligence_features.ctx JSONB  — resolved at bar insert time via as-of join

CREATE TABLE IF NOT EXISTS ctx_events (
    event_ts    TIMESTAMPTZ NOT NULL,
    symbol      TEXT,                    -- NULL = global (FOMC etc.)
    event_type  TEXT NOT NULL,           -- 'earnings', 'macro', 'news'
    source      TEXT NOT NULL,
    payload     JSONB NOT NULL
);
SELECT create_hypertable('ctx_events', 'event_ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS ctx_snapshots (
    symbol      TEXT,
    event_type  TEXT NOT NULL,
    valid_from  TIMESTAMPTZ NOT NULL,
    valid_to    TIMESTAMPTZ,
    ctx         JSONB NOT NULL,
    PRIMARY KEY (symbol, event_type, valid_from)
);

-- Index for as-of join: symbol, valid_from, valid_to (per qualitative-intelligence-layer.md)
CREATE INDEX IF NOT EXISTS ctx_snapshots_symbol_valid_from_idx
    ON ctx_snapshots (symbol, valid_from, valid_to);

-- Add ctx column to intelligence_features (NULL by default — graceful absence)
ALTER TABLE intelligence_features ADD COLUMN IF NOT EXISTS ctx JSONB;
```

---

### `production/migrations/086_validation_results.sql` (new)

**Analog:** `production/migrations/077_shadow_governance.sql` (hypertable + index pattern)

```sql
-- Migration 086: Validation Results + shadow_registry promotion_evidence (Phase 082)
-- Idempotent: safe to re-apply.
--
-- Tables created:
--   validation_results — IC/p-value decisions from FeatureValidationComputeAgent
--
-- Column added:
--   shadow_registry.promotion_evidence JSONB  — evidence written by Phase 082 agent,
--   consumed by Phase 075 ShadowAuditorAgent for promotion/demotion action.

CREATE TABLE IF NOT EXISTS validation_results (
    plugin_name         TEXT        NOT NULL,
    timeframe           TEXT        NOT NULL,
    regime_type         TEXT,               -- NULL = pooled across regimes
    ic                  FLOAT       NOT NULL,
    p_value             FLOAT       NOT NULL,
    n                   INTEGER     NOT NULL,
    decision            TEXT        NOT NULL
        CHECK (decision IN ('VALIDATED', 'TWEAK', 'KILL')),
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    bonferroni_corrected BOOLEAN    NOT NULL DEFAULT TRUE
);
SELECT create_hypertable('validation_results', 'computed_at',
    chunk_time_interval => INTERVAL '1 month', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS validation_results_plugin_tf_idx
    ON validation_results (plugin_name, timeframe, computed_at DESC);

-- Add promotion_evidence to shadow_registry (Phase 075 ShadowAuditorAgent reads this)
ALTER TABLE shadow_registry
    ADD COLUMN IF NOT EXISTS promotion_evidence JSONB;

COMMENT ON COLUMN shadow_registry.promotion_evidence IS
    'Latest IC/p-value evidence from FeatureValidationComputeAgent. '
    'Read by ShadowAuditorAgent to execute promotion/demotion decisions.';
```

---

### `src/core/stream_keys.py` (modify — add topic_ctx_snapshot)

**Analog:** itself — any existing `topic_*` function (lines 46–79)

**Copy pattern of `topic_llm_calls` (line 131–132):**
```python
def topic_ctx_snapshot(env_name: str) -> str:
    """Kafka topic for qualitative context snapshot events from provider agents.

    Consumed by CtxWriterAgent (L6) to persist to ctx_events + ctx_snapshots.
    Published by provider lanes (earnings, macro, news) — Phase 083+.
    Phase 082 creates the topic infrastructure only; no producers yet.
    """
    return f"{env_prefix(env_name)}ctx.snapshot"
```

---

### `services/ctx_writer_agent.py` (new)

**Analog:** `services/lifecycle_writer_agent.py` — direct template

**Imports pattern** (lifecycle_writer_agent.py lines 1–36):
```python
#!/usr/bin/env python3
"""CTX Writer Agent — persists ctx_events and ctx_snapshots from topic_ctx_snapshot.

Consumes ctx.snapshot Kafka topic, buffers events,
and batch-writes to ctx_events + ctx_snapshots via asyncpg.

WriterAgent role: DB-only, zero compute. No ctx evaluation.
Consumer group: ctx_writer_group
"""

from __future__ import annotations

import asyncio
import time

import _path_bootstrap  # noqa: F401

from src.core.agent.base_writer import BaseWriterAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.service_utils import parse_iso_ts
from src.core.stream_keys import topic_ctx_snapshot
from src.observability.metrics import PERSISTENCE_BATCH_LATENCY, counter
```

**Class structure** (lifecycle_writer_agent.py lines 65–98 — copy pattern):
```python
CONSUMER_GROUP = "ctx_writer_group"

class CtxWriterAgent(BaseWriterAgent):
    """WriterAgent: ctx.snapshot -> ctx_events + ctx_snapshots."""

    BATCH_SIZE = 50
    FLUSH_INTERVAL_SECS = 10.0
    MAX_BUFFER_SIZE = 5_000

    def __init__(self) -> None:
        super().__init__(name="ctx_writer_agent")
        self._db: DatabaseManager | None = None
        self._events_consumed = counter(
            "ctx_writer_events_consumed_total", "Kafka messages consumed"
        )
        self._rows_written = counter(
            "ctx_writer_rows_written_total", "Rows written to ctx_events"
        )
        self._write_errors = counter(
            "ctx_writer_write_errors_total", "Failed batch writes"
        )
        self._batch_latency = PERSISTENCE_BATCH_LATENCY.labels(agent_id="ctx_writer_agent")

    def _topic_name(self) -> str:
        return topic_ctx_snapshot(self.settings.env_name)

    @property
    def _consumer_group(self) -> str:
        return CONSUMER_GROUP
```

**`_flush_batch` pattern** (lifecycle_writer_agent.py lines 172–194):
```python
    async def _flush_batch(self, batch: list) -> None:
        t0 = time.perf_counter()
        assert self._db is not None
        async with self._db.pool.acquire() as conn:
            for item in batch:
                # Append to ctx_events (append-only log)
                await conn.execute(
                    """
                    INSERT INTO ctx_events (event_ts, symbol, event_type, source, payload)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    parse_iso_ts(item["event_ts"]),
                    item.get("symbol"),
                    item["event_type"],
                    item["source"],
                    item["payload"],  # asyncpg: pass dict directly for JSONB
                )
                # Upsert ctx_snapshots: close prior valid_to, open new snapshot
                await conn.execute(
                    """
                    UPDATE ctx_snapshots
                       SET valid_to = $1
                     WHERE (symbol = $2 OR (symbol IS NULL AND $2 IS NULL))
                       AND event_type = $3
                       AND valid_to IS NULL
                    """,
                    parse_iso_ts(item["event_ts"]),
                    item.get("symbol"),
                    item["event_type"],
                )
                await conn.execute(
                    """
                    INSERT INTO ctx_snapshots (symbol, event_type, valid_from, ctx)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (symbol, event_type, valid_from) DO NOTHING
                    """,
                    item.get("symbol"),
                    item["event_type"],
                    parse_iso_ts(item["event_ts"]),
                    item["ctx"],  # asyncpg: pass dict for JSONB
                )
        self._rows_written.inc(len(batch))
        self._batch_latency.observe(time.perf_counter() - t0)

    async def _setup(self) -> None:
        self._db = DatabaseManager(self.settings.database_url)
        await self._db.initialize()
        self._create_consumer()
        await self._consumer.start()
        self._last_flush = time.monotonic()
        self.logger.info("ctx_writer.started", topic=self._topic_name())

    def _on_message_consumed(self, payload: dict) -> None:
        self._events_consumed.inc()

    async def _teardown(self) -> None:
        await super()._teardown()
        if self._consumer:
            await self._consumer.stop()
        if self._db:
            await self._db.close()


if __name__ == "__main__":
    agent = CtxWriterAgent()
    asyncio.run(agent.start())
```

---

### `services/feature_writer_agent.py` (modify — add as-of join for ctx)

**Analog:** itself — `_INSERT_FEATURE_SQL` lines 62–85

**Add `ctx` column to INSERT SQL** (after `days_to_expiry` on line 84):
```sql
INSERT INTO intelligence_features (
    ts, symbol, tf, platform, source, schema_version,
    bar, i1, i2, i3, i4, i5, smc, i6, i7,
    bar_close_ts, i1_computed_at, computed_at,
    winner_plugin, winner_confidence, winner_direction,
    signals_evaluated, signals_after_quality, signals_after_regime,
    signals_after_tod, signals_after_calibration,
    ledger_written, pipeline_latency_ms,
    i7_computed_at, session_type, days_to_expiry,
    ctx                                                    -- NEW Phase 082
)
VALUES (
    $1, $2, $3, $4, $5, $6,
    $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb,
    $12::jsonb, $13::jsonb, $14::jsonb, $15::jsonb,
    $16, $17, $18,
    $19, $20, $21,
    $22, $23, $24,
    $25, $26,
    $27, $28,
    $29, $30, $31,
    (                                                      -- as-of join for ctx
      SELECT jsonb_object_agg(event_type, ctx ORDER BY event_type)
      FROM ctx_snapshots
      WHERE (symbol = $2 OR symbol IS NULL)
        AND valid_from <= $1
        AND (valid_to IS NULL OR valid_to > $1)
    )
)
ON CONFLICT (ts, symbol, tf) DO NOTHING
```

**NOTE:** No Python change needed for this — the subquery runs entirely in SQL. The `ctx` value resolves to NULL for every bar in Phase 082 (no provider lanes yet), so query cost is zero. Index on `ctx_snapshots(symbol, valid_from, valid_to)` in migration 085 guards Phase 083+ performance.

---

### `src/api/routes/validation.py` (new)

**Analog:** `src/api/routes/features.py`

**Imports pattern** (features.py lines 1–27):
```python
"""
Validation Results API Routes

Exposes GET /validation/results — latest per-plugin IC/p-value decisions
from FeatureValidationComputeAgent.
"""

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ...core.database_manager import DatabaseManager
from ..dependencies import get_db_manager

logger = structlog.get_logger(__name__)
router = APIRouter()
```

**Route pattern** (features.py lines 36–60):
```python
@router.get("/validation/results")
async def get_validation_results(
    plugin_name: str | None = Query(None, description="Filter by plugin name"),
    timeframe: str | None = Query(None, description="Filter by timeframe"),
    limit: int = Query(100, le=1000),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> JSONResponse:
    """Latest validation decisions per plugin from validation_results table."""
    try:
        async with db_manager.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (plugin_name, timeframe)
                    plugin_name, timeframe, regime_type,
                    ic, p_value, n, decision, computed_at, bonferroni_corrected
                FROM validation_results
                WHERE ($1::text IS NULL OR plugin_name = $1)
                  AND ($2::text IS NULL OR timeframe = $2)
                ORDER BY plugin_name, timeframe, computed_at DESC
                LIMIT $3
                """,
                plugin_name, timeframe, limit,
            )
        return JSONResponse([dict(r) for r in rows])
    except Exception:
        logger.exception("validation_results.query_error")
        raise
```

**Registration in `src/api/main.py`** (follow existing router import pattern lines 17–26):
```python
from .routes import (
    drift, features, health, indicators, instruments,
    market_data, narrative, signals, sse,
    validation,  # NEW Phase 082
)

# In app setup:
app.include_router(validation.router, prefix="/api")
```

---

### `services/service_auditor_agent.py` (modify — add ctx-writer to DAG)

**Analog:** itself — `_DAG_ORDER` list

Add `"indicagent-ctx-writer"` to `_DAG_ORDER` at layer L6, adjacent to other writer services. Also add to `_LAG_THRESHOLDS` and `_AGENT_ID_TO_UNIT` following the existing writer pattern.

---

## Shared Patterns

### SIGUSR1 Hot-Reload (HMM parameter reload in intelligence_pipeline_agent)

**Source:** `services/alpha_swarm_agent.py` lines 188–193
**Apply to:** `services/intelligence_pipeline_agent.py` SIGUSR1 handler addition

```python
# In intelligence_pipeline_agent._setup() — add after existing setup:
loop = asyncio.get_running_loop()
loop.add_signal_handler(_signal.SIGUSR1, self._on_sigusr1)

def _on_sigusr1(self) -> None:
    """Hot-reload HMM parameters on all running HMM instances."""
    from src.intelligence.features.smc_context.hmm_regime import (
        hmm_1m_plugin, hmm_5m_plugin, hmm_15m_plugin, hmm_1h_plugin,
    )
    for plugin in [hmm_1m_plugin, hmm_5m_plugin, hmm_15m_plugin, hmm_1h_plugin]:
        plugin.__post_init__()  # re-runs _load_parameters() with TF-suffixed path
    self.logger.info("intelligence_pipeline.hmm_params_reloaded")
```

### asyncpg JSONB Pattern

**Source:** `CLAUDE.md` + `services/lifecycle_writer_agent.py`
**Apply to:** All new DB write code (`CtxWriterAgent._flush_batch`, `FeatureValidationComputeAgent._write_result`)

- Pass `dict` objects directly for `JSONB` columns — never `json.dumps()`
- asyncpg returns `dict` for JSONB reads — never `json.loads()`

### Oneshot Exit-0 Pattern

**Source:** `src/intelligence/services/ml_training_compute_agent.py` lines 104–115
**Apply to:** `HMMTrainingComputeAgent._run()`, `FeatureValidationComputeAgent._run()`

```python
async def _run(self) -> None:
    try:
        await self._do_work()
    except Exception:
        logger.exception("agent.error_top_level")
        return  # intentional: exit 0 so timer fires again
```

### Structlog `event` Kwarg Collision

**Source:** `CLAUDE.md`
**Apply to:** All new log calls in all new files

Never use `event=` as a keyword argument in structlog calls. Use `signal=`, `data=`, `payload=` etc.:
```python
# WRONG:
logger.info("hmm_training.complete", event={"tf": "5m"})
# CORRECT:
logger.info("hmm_training.complete", data={"tf": "5m"})
```

### Timestamp Handling

**Source:** `CLAUDE.md` + `services/lifecycle_writer_agent.py` lines 53–62
**Apply to:** All new files with datetime handling

```python
from datetime import UTC, datetime
from src.core.service_utils import parse_iso_ts

# Always UTC:
datetime.now(UTC)  # correct
# Never: datetime.now() or datetime.utcnow()

# ISO string from Kafka → datetime for asyncpg:
parse_iso_ts(item["event_ts"])  # not datetime.fromisoformat()
```

---

## No Analog Found

All files have close analogs in the codebase. No files require falling back to RESEARCH.md patterns only.

| File | Resolution |
|------|-----------|
| `config/hmm_parameters_{tf}.json` (output artifact) | Structure defined in RESEARCH.md: keys `transition_matrix`, `emission_means`, `emission_variances` — matches existing `config/hmm_parameters.json` format extended with `"trained_at"` and `"timeframe"` |

---

## Critical Pitfall Reminders for Planner

1. **`I4Context(extra="forbid")` vs `SMCContext` (no forbid):** New `hmm_regime_entropy` + `hmm_regime_velocity` fields must be added to `SMCContext` (keeping HMM in TIER_SMC per RESEARCH.md recommendation). If moved to TIER_I4, add to `I4Context` explicitly or pipeline crashes with `ValidationError: extra fields not permitted`.

2. **`shadow_registry.component_type` CHECK constraint** only allows `('i7_plugin', 'swarm_agent')`. The `promotion_evidence` column migration (086) does NOT change this constraint. `FeatureValidationComputeAgent` writes `promotion_evidence` for rows already in the registry — it does not INSERT new rows, so the CHECK is not triggered. Verify before writing migration.

3. **`promotion_evidence` column does NOT exist yet** in `shadow_registry`. Migration 086 must `ALTER TABLE shadow_registry ADD COLUMN IF NOT EXISTS promotion_evidence JSONB` before the feature validation service runs.

4. **HMM output field collision** across 4 TF instances is avoided by `InputSpec(timeframe=X)` routing — the pipeline only runs a plugin against bars matching its TF. Verify dispatch logic in `intelligence_pipeline_agent.py` correctly routes per-TF before registering all 4 instances.

5. **`is_backfill IS NOT TRUE`** — every `HMMTrainingComputeAgent` query against `intelligence_features` must include this filter (Phase 81 gate).

---

## Metadata

**Analog search scope:** `src/intelligence/`, `services/`, `production/migrations/`, `production/systemd/`, `src/api/routes/`, `src/core/`, `src/config/`, `src/observability/`
**Files scanned:** 18 source files read directly
**Pattern extraction date:** 2026-05-13
