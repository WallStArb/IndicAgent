# Phase 070: ML Scoring Model — Pattern Map

**Mapped:** 2026-05-13
**Files analyzed:** 8 (5 new, 3 modified)
**Analogs found:** 8 / 8

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/intelligence/ai/alpha/ml_scorer_agent.py` | multiplier-agent | request-response (sync inference) | `src/intelligence/ai/alpha/correlation_agent.py` | exact |
| `src/intelligence/services/ml_training_compute_agent.py` | service (oneshot) | batch (nightly train) | `services/ml_orchestrator_agent.py` | role-match |
| `src/intelligence/ml/feature_builder.py` | utility (transform) | batch (SQL → DataFrame) | `src/intelligence/ml/confidence_calibrator.py` | role-match |
| `production/migrations/084_ai_enrichment_tables.sql` | migration | — | `production/migrations/082_swarm_weights_and_adjusted_confidence.sql` | exact |
| `production/systemd/indicagent-ml-training.service` + `.timer` | config | — | `production/systemd/indicagent-ml-orchestrator.service` + `.timer` | exact |
| `services/swarm_ledger_writer_agent.py` (MODIFY) | service (writer) | event-driven CRUD | self (full file read) | — |
| `services/llm_writer_service.py` (MODIFY) | service (writer) | event-driven CRUD | self (full file read) | — |
| `services/alpha_swarm_agent.py` (MODIFY) | service (group-service) | event-driven | self + `correlation_agent.py` | — |

---

## Pattern Assignments

### `src/intelligence/ai/alpha/ml_scorer_agent.py` (multiplier-agent, request-response)

**Analog:** `src/intelligence/ai/alpha/correlation_agent.py`

**Imports pattern** (`correlation_agent.py` lines 1–18):
```python
from __future__ import annotations

from typing import Any, ClassVar

import structlog

from src.core.ai.context import AIContext, Tier
from src.core.ai.multiplier_agent import BaseMultiplierAgent
from src.core.ai.output import AgentOutput
from src.core.ai.prompt_utils import clamp
```

**Key difference:** `MLScorerMultiplierAgent` does NOT import `LLMProviderChain` or any prompt module. Add instead:
```python
from src.core.ml.registry import ModelRegistry
```

**Class attribute pattern** (`correlation_agent.py` lines 57–68):
```python
class CorrelationComputeAgent(BaseMultiplierAgent):
    output_schema: ClassVar[dict] = {
        "coherence_score": float,
        "confidence": float,
        "contradicting_assets": list,
        "reasoning": str,
    }
    agent_id = "correlation_v1"
    group = "alpha"
    tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I6, Tier.I7, Tier.SMC})
    latency_budget_ms = 45000.0
    shadow_only = True
```

**For `MLScorerMultiplierAgent`, replace with:**
```python
class MLScorerMultiplierAgent(BaseMultiplierAgent):
    output_schema: ClassVar[dict] = {"multiplier": float, "ml_score": float, "segment": str}
    agent_id = "ml_scorer_v1"
    group = "alpha"
    tiers_needed = frozenset()          # No LLM tiers — local LightGBM inference
    latency_budget_ms = 50.0
    shadow_only = True
```

**`__init__` pattern** (`correlation_agent.py` line 70–72):
```python
def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
    super().__init__(name=self.__class__.__name__, **kwargs)
    self._llm = llm_chain
```

**For `MLScorerMultiplierAgent`, replace with:**
```python
def __init__(self, pool, **kwargs: Any) -> None:
    super().__init__(name=self.__class__.__name__, **kwargs)
    self._registry = ModelRegistry(pool)
    self._models: dict[str, Any] = {}   # segment_key -> loaded pyfunc model
```

**`_compute()` pattern** — no LLM call, direct LightGBM inference. Based on `_build_multiplier_output()` contract in `multiplier_agent.py` lines 44–68:
```python
async def _compute(self, context: AIContext) -> AgentOutput:
    features = self._extract_features(context)   # returns 1-row numpy array
    model, segment_key = self._select_model(context)
    if model is None:
        return self._neutral(error="no_promoted_model", latency_ms=0.0)
    ml_score = float(model.predict(features)[0])
    multiplier = clamp(ml_score * 2.0, 0.0, 2.0)   # P(win) in [0,1] → [0,2]
    return self._build_multiplier_output(
        context=context,
        multiplier=multiplier,
        confidence=ml_score,
        payload={"ml_score": ml_score, "segment": segment_key},
        prompt_version="v1",
    )
```

**`_neutral()` call pattern** (`base_agent.py` lines 145–155):
```python
return self._neutral(error="no_promoted_model", latency_ms=0.0)
```
The `_neutral()` method populates `output_type="neutral"` and `error=` — callers use this when no model is promoted.

**SIGUSR1 model reload** — no existing pattern; implement in `AlphaSwarmComputeAgent._setup()`:
```python
import signal as _signal
loop = asyncio.get_event_loop()
loop.add_signal_handler(_signal.SIGUSR1, self._on_sigusr1)

def _on_sigusr1(self) -> None:
    asyncio.create_task(self._reload_ml_models())

async def _reload_ml_models(self) -> None:
    for agent in self._agents:
        if hasattr(agent, "_setup_models"):
            await agent._setup_models()
    self.logger.info("alpha_swarm.ml_models_reloaded_sigusr1")
```

**`_build_multiplier_output()` signature** (`multiplier_agent.py` lines 44–68):
```python
def _build_multiplier_output(
    self,
    context: AIContext,
    multiplier: float,
    confidence: float,
    payload: dict[str, Any],
    prompt_version: str,
) -> AgentOutput:
    return AgentOutput(
        agent_id=self.agent_id,
        group=self.group,
        signal_id=context.signal_id,
        symbol=context.symbol,
        timeframe=context.timeframe,
        ts=context.ts,
        output_type="multiplier",
        payload={
            "multiplier": clamp(multiplier, 0.0, 2.0),
            "confidence": clamp(confidence, 0.0, 1.0),
            "prompt_version": prompt_version,
            **payload,
        },
        shadow_only=self.shadow_only,
    )
```

---

### `src/intelligence/services/ml_training_compute_agent.py` (service/oneshot, batch)

**Analog:** `services/ml_orchestrator_agent.py`

**Imports and service skeleton** (`ml_orchestrator_agent.py` lines 1–35):
```python
from __future__ import annotations

import asyncio

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
import structlog

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.database_manager import create_pool as create_db_pool
from src.core.service_utils import setup_service_logging

logger = structlog.get_logger(__name__)
```

**Class skeleton** (`ml_orchestrator_agent.py` lines 56–70):
```python
class MLOrchestratorComputeAgent(BaseAgent):
    def __init__(self, settings: Settings) -> None:
        setup_service_logging("logs/ml_orchestrator_agent.log")
        super().__init__("MLOrchestratorComputeAgent")
        self.settings = settings
        self._pool: asyncpg.Pool | None = None

    async def _setup(self) -> None:
        self._pool = await create_db_pool(self.settings.database_url)

    async def _teardown(self) -> None:
        if self._pool:
            await self._pool.close()

    async def _run(self) -> None:
        """One-shot entry point: run pipeline and exit."""
        ...
```

**`MLTrainingComputeAgent` adapts this skeleton.** Key log file name: `"logs/ml_training_compute_agent.log"`. Class name: `"MLTrainingComputeAgent"`. The `_run()` method is the one-shot training entrypoint.

**Delta gate pattern** — modelled on `confidence_calibrator.py` N-gate (lines 95–96) + `setup_performance_updater.py` logic. Implement as:
```python
async def _should_retrain(self) -> bool:
    current_count = await self._pool.fetchval(
        "SELECT COUNT(*) FROM signal_ledger WHERE outcome IS NOT NULL AND is_shadow = FALSE"
    )
    if current_count - self._last_trained_count < 50:
        self.logger.info("ml_training.delta_gate_skip", delta=current_count - self._last_trained_count)
        return False
    self._last_trained_count = current_count
    return True
```
Persist `_last_trained_count` to a JSON checkpoint file (same approach as `setup_performance_updater.py` — read/write a small file at `logs/ml_training_checkpoint.json`).

**N-gate pattern** from `confidence_calibrator.py` lines 95–96:
```python
if n < _MIN_SAMPLE_SIZE:
    continue
```
For training: gate at `n_train < 100` before fitting any LightGBM model.

**Walk-forward split** — no existing 3-way utility; implement directly:
```python
df_sorted = df.sort("timestamp")
n = len(df_sorted)
n_train = int(n * 0.60)
n_val   = int(n * 0.80)   # 60–80% is validation
train = df_sorted[:n_train]
val   = df_sorted[n_train:n_val]
test  = df_sorted[n_val:]
```

**Post-training SIGUSR1 trigger:**
```python
import subprocess
subprocess.run(
    ["systemctl", "kill", "-s", "SIGUSR1", "indicagent-alpha-swarm"],
    capture_output=True,
)
```

**LightGBM + polars → numpy conversion** (Pitfall 4):
```python
import lightgbm as lgb
X_train = train.select(feature_cols).to_numpy()
y_train = train["win_label"].to_numpy()
dtrain = lgb.Dataset(X_train, label=y_train)
```

**main() pattern** (`ml_orchestrator_agent.py` lines 233–240):
```python
def main() -> None:
    settings = Settings()
    agent = MLTrainingComputeAgent(settings)
    asyncio.run(agent.start())

if __name__ == "__main__":
    main()
```

---

### `src/intelligence/ml/feature_builder.py` (utility/transform, batch)

**Analog:** `src/intelligence/ml/confidence_calibrator.py` (pure-function module called by a service agent)

**Module pattern** (`confidence_calibrator.py` lines 1–30):
```python
"""<module docstring>.

Called from <agent> on <trigger>.
Independent failure domain: exception caught and logged; caller is unaffected.

Algorithm:
  - Query signal_ledger ...
  - Group by ...
  - Fit ...
"""

from __future__ import annotations
import collections
from typing import Any
import numpy as np
import structlog
from ...

logger = structlog.get_logger(__name__)
_MIN_SAMPLE_SIZE = 100
```

**Training SQL** — build on `TrainingDataQuery._BASE_SQL` (`src/core/ml/training_data.py` lines 18–61). The Phase 70 query must add `features_snapshot` extraction:

From `training_data.py` lines 18–55 (pattern):
```python
_BASE_SQL = f"""
SELECT
    f.ts,
    f.symbol,
    f.tf,
    (f.i1->>'atr_14')::float          AS atr,
    (f.i4->>'hmm_regime')::int        AS hmm_regime,
    ...
FROM intelligence_features f
JOIN signal_ledger sl
  ON sl.symbol = f.symbol
 AND sl.feature_ts = f.ts
 AND sl.feature_tf = f.tf
 AND {_NO_LOOKAHEAD_SQL}   -- No lookahead: feature must precede outcome
WHERE f.symbol = $1
  AND sl.outcome IS NOT NULL
ORDER BY f.ts
"""
```

**Phase 70 extension adds** (for `feature_builder.py`):
```python
_SHADOW_FEATURES_SQL = """
SELECT
    sl.signal_id,
    sl.timestamp,
    sl.timeframe,
    sl.pnl_r,
    (sl.pnl_r > 0)::int               AS win_label,
    sl.features_snapshot,              -- JSONB column added in migration 084
    (f.i4->>'hmm_regime')::int         AS hmm_regime,
    f.session_type,
    (f.i1->>'atr_pct')::float          AS atr_pct,
    (f.i1->>'volume_z_score')::float   AS volume_z_score
FROM signal_ledger sl
JOIN intelligence_features f
  ON f.symbol = sl.symbol
 AND f.ts = sl.feature_ts
 AND f.tf = sl.feature_tf
 AND f.ts < sl.activated_at            -- NO LOOKAHEAD
WHERE sl.outcome IS NOT NULL
  AND sl.is_shadow = FALSE
  AND sl.signal_schema_version = $1
ORDER BY sl.timestamp
"""
```

**Critical field name:** `volume_z_score` NOT `volume_z` — the `i1` JSONB column key is `volume_z_score`.

**Categorical encoding for LightGBM** — one-hot encode: `hmm_regime` (0/1/2), `profile` (6 families), `session_type` (string), string regime fields (`ctf_momentum_regime`, etc.). Use `pd.get_dummies()` or polars `to_dummies()` before `.to_numpy()`.

---

### `production/migrations/084_ai_enrichment_tables.sql` (migration)

**Analog:** `production/migrations/082_swarm_weights_and_adjusted_confidence.sql`

**Migration file pattern** (`082_swarm_weights_and_adjusted_confidence.sql` lines 1–22):
```sql
-- Phase 80: Swarm Intelligence Layer — new columns + weight table
-- Idempotent: safe to re-apply.

ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS adjusted_confidence FLOAT;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS swarm_multiplier FLOAT;
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS swarm_agent_count INT;

CREATE TABLE IF NOT EXISTS swarm_agent_weights (
    agent_id          TEXT        NOT NULL,
    timeframe         TEXT        NOT NULL,
    weight            FLOAT       NOT NULL DEFAULT 1.0,
    ...
    PRIMARY KEY (agent_id, timeframe)
);
```

**Phase 70 migration creates (D-13/D-14/RESEARCH.md Q6):**

```sql
-- Migration 084: AI Enrichment Tables — AI-SEP-01 (Phase 70)
-- Idempotent: safe to re-apply.

-- signal_ai_enrichment: AI-owned swarm + ML annotations for signals
CREATE TABLE IF NOT EXISTS signal_ai_enrichment (
    signal_id          UUID        PRIMARY KEY REFERENCES signal_ledger(signal_id),
    swarm_multiplier   FLOAT,
    adjusted_confidence FLOAT,
    swarm_agent_count  INT,
    ml_score           FLOAT,
    ml_model_id        UUID,
    enriched_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- intelligence_ai_enrichment: AI-owned i8 annotations for bar rows
CREATE TABLE IF NOT EXISTS intelligence_ai_enrichment (
    ts             TIMESTAMPTZ NOT NULL,
    symbol         TEXT        NOT NULL,
    tf             TEXT        NOT NULL,
    i8             JSONB,
    narrative_id   UUID,
    enriched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ts, symbol, tf)
);

-- Also add features_snapshot column to signal_ledger for ML training
ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS features_snapshot JSONB;
```

**Note:** The `features_snapshot` column on `signal_ledger` resolves RESEARCH.md Open Question 1. `signal_writer_agent.py` must be updated to populate it at insert time.

---

### `production/systemd/indicagent-ml-training.service` + `.timer` (config)

**Analog:** `production/systemd/indicagent-ml-orchestrator.service` + `indicagent-ml-orchestrator.timer`

**Service file pattern** (`indicagent-ml-orchestrator.service` lines 1–15):
```ini
[Unit]
Description=IndicAgent ML Orchestrator Agent
After=network.target

[Service]
Type=oneshot
WorkingDirectory=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/ml_orchestrator_agent.py
Environment=PYTHONUNBUFFERED=1
Environment=INDICAGENT_ENV=development
TimeoutStartSec=7200

[Install]
WantedBy=multi-user.target
```

**`indicagent-ml-training.service` replaces:**
- `Description` → `IndicAgent ML Training Compute Agent — nightly LightGBM training`
- `ExecStart` → `.../python services/ml_training_agent.py`

**Timer file pattern** (`indicagent-ml-orchestrator.timer` lines 1–10):
```ini
[Unit]
Description=ML Orchestrator Timer -- Monday 04:00 UTC

[Timer]
OnCalendar=Mon *-*-* 04:00:00 UTC
Persistent=true
Unit=indicagent-ml-orchestrator.service

[Install]
WantedBy=timers.target
```

**`indicagent-ml-training.timer` replaces:**
- `Description` → `ML Training Timer — nightly 03:00 UTC`
- `OnCalendar` → `*-*-* 03:00:00 UTC` (daily, not weekly; runs before orchestrator at 04:00)
- `Unit` → `indicagent-ml-training.service`

---

### `services/swarm_ledger_writer_agent.py` (MODIFY — AI-SEP-01)

**Source for change:** `swarm_ledger_writer_agent.py` lines 115–162 (`_apply_projection`)

**Current SQL** (lines 131–141):
```python
result = await conn.execute(
    """
    UPDATE signal_ledger
       SET adjusted_confidence = $2,
           swarm_multiplier = $3,
           swarm_agent_count = $4
     WHERE signal_id = $1
    """,
    signal_id,
    adjusted_confidence,
    swarm_multiplier,
    swarm_agent_count,
)
```

**Replace module-level SQL constant with:**
```python
_UPSERT_ENRICHMENT_SQL = """
INSERT INTO signal_ai_enrichment
    (signal_id, swarm_multiplier, adjusted_confidence, swarm_agent_count, enriched_at)
VALUES ($1::uuid, $2, $3, $4, NOW())
ON CONFLICT (signal_id) DO UPDATE SET
    swarm_multiplier     = EXCLUDED.swarm_multiplier,
    adjusted_confidence  = EXCLUDED.adjusted_confidence,
    swarm_agent_count    = EXCLUDED.swarm_agent_count,
    enriched_at          = NOW()
"""
```

**Retry logic** (lines 128–157) stays unchanged — FK constraint on `signal_ai_enrichment.signal_id REFERENCES signal_ledger(signal_id)` creates the same race condition as before.

**`ml_score` / `ml_model_id` population:** Add a second branch in `_handle_event()` — when payload contains `ml_score`, issue a separate UPSERT setting `ml_score` and `ml_model_id` fields. The aggregate swarm event from `AlphaSwarmComputeAgent` already contains all agent payloads.

**Metric label** (line 150): `SWARM_SIGNAL_LEDGER_UPDATE_TOTAL.labels(status="success").inc()` — keep unchanged; label semantics are "enrichment write" now.

---

### `services/llm_writer_service.py` (MODIFY — AI-SEP-01)

**Source for change:** lines 111–115 (SQL constant) and lines 768–787 (`_flush_i8`)

**Current SQL constant** (lines 111–115):
```python
_UPDATE_I8_SQL = """
UPDATE intelligence_features
SET i8 = $4::jsonb
WHERE ts = $1::timestamptz AND symbol = $2 AND tf = $3
"""
```

**Replace with:**
```python
_UPSERT_I8_SQL = """
INSERT INTO intelligence_ai_enrichment (ts, symbol, tf, i8, enriched_at)
VALUES ($1::timestamptz, $2, $3, $4::jsonb, NOW())
ON CONFLICT (ts, symbol, tf) DO UPDATE SET
    i8 = EXCLUDED.i8,
    enriched_at = NOW()
"""
```

**`_flush_i8()` method** (lines 768–787): update only the SQL reference — `_UPDATE_I8_SQL` → `_UPSERT_I8_SQL`. All other flush logic (buffer management, error handling, retry) stays identical.

**Docstring update** on `_flush_i8()` (line 769): remove mention of "phantom rows if FeatureWriterAgent hasn't yet written the base row" — UPSERT to the new AI-owned table does not have that constraint.

**No other methods change:** `_insert_llm_call()`, `_update_outcome()`, `_recompute_scores()`, the score-recompute timer, the dual-consumer `_run()` — all unaffected.

---

### `services/alpha_swarm_agent.py` (MODIFY — add MLScorerMultiplierAgent)

**Source for change:** lines 148–180 (`_setup()` method)

**Current `_agents` list construction** (lines 159–164):
```python
self._agents = [
    SkepticComputeAgent(llm_chain=self._llm_chain),
    CorrelationComputeAgent(llm_chain=self._llm_chain),
    RegimeCoherenceComputeAgent(llm_chain=self._llm_chain),
    CounterfactualComputeAgent(llm_chain=self._llm_chain),
]
```

**Replace with:**
```python
self._agents = [
    SkepticComputeAgent(llm_chain=self._llm_chain),
    CorrelationComputeAgent(llm_chain=self._llm_chain),
    RegimeCoherenceComputeAgent(llm_chain=self._llm_chain),
    CounterfactualComputeAgent(llm_chain=self._llm_chain),
    MLScorerMultiplierAgent(pool=self._pool),   # NEW — no llm_chain needed
]
await self._agents[-1]._setup_models()          # load promoted models at startup
```

**Add import at top of file:**
```python
from src.intelligence.ai.alpha.ml_scorer_agent import MLScorerMultiplierAgent
```

**`_SWARM_AGENT_TO_TRANSFORM`** (lines 71–76): add entry:
```python
"ml_scorer_v1": ("swarm_ml_scorer", 6),
```

**SIGUSR1 wiring** — add after `_setup()` constructs agents (line 177, after `_shadow_registry_ensure_swarm()`):
```python
import signal as _signal
loop = asyncio.get_event_loop()
loop.add_signal_handler(_signal.SIGUSR1, self._on_sigusr1)
```

---

### `services/service_auditor_agent.py` (MODIFY — DAG registration)

**Source for change:** `_DAG_ORDER` (lines 49–87), `_LAG_THRESHOLDS` (lines 90–110)

**`_DAG_ORDER` addition** (line 80, after existing L8 entries):
```python
"indicagent-ml-training": 8,
```

**`_LAG_THRESHOLDS` — no entry needed:** `Type=oneshot` timer services are not Kafka consumers and have no consumer lag metric.

**`_AGENT_ID_TO_UNIT` — no entry needed:** `MLTrainingComputeAgent` is a oneshot service with no Prometheus `PERSISTENCE_CONSUMER_LAG` gauge.

---

## Shared Patterns

### asyncpg JSONB rule (exception)
**Source:** `src/core/ml/registry.py` lines 37–48
**Apply to:** `MLTrainingComputeAgent` when building segment dicts for `ModelRegistry.register()`
```python
# ModelRegistry.register() calls json.dumps(segment) internally — do NOT pass json.dumps() yourself
await registry.register(
    run_id=run_id,
    segment={"global": True},   # pass dict directly — registry handles json.dumps()
    artifact_path=artifact_uri,
)
```
This is the ONE place in the codebase where `json.dumps()` is used before asyncpg — do not "fix" it.

### structlog event= kwarg collision
**Source:** CLAUDE.md and all existing agents
**Apply to:** All new files
```python
# WRONG — collides with structlog's reserved 'event' parameter:
logger.info("ml_scorer.computed", event=output_type)
# CORRECT:
logger.info("ml_scorer.computed", output_type=output_type, signal=signal_id)
```

### UTC timestamps
**Source:** All existing agents (e.g., `swarm_ledger_writer_agent.py`, `base_agent.py`)
**Apply to:** All new files
```python
from datetime import UTC, datetime
datetime.now(UTC)  # always; never datetime.now() or datetime.utcnow()
```

### Error handling pattern (neutral fallback)
**Source:** `src/core/ai/base_agent.py` lines 145–155
**Apply to:** `MLScorerMultiplierAgent._compute()` on model-absent or inference-error path
```python
return self._neutral(error="no_promoted_model", latency_ms=0.0)
```

### N-gate before any model training
**Source:** `src/intelligence/ml/confidence_calibrator.py` lines 95–96
**Apply to:** `MLTrainingComputeAgent` — both global model and per-regime models
```python
if n < _MIN_SAMPLE_SIZE:     # _MIN_SAMPLE_SIZE = 100
    logger.info("ml_training.gate_skip", n=n, segment=segment)
    continue
```

### Polars → numpy before LightGBM
**Source:** `src/core/ml/training_data.py` lines 100–111 (polars DataFrame returned)
**Apply to:** `feature_builder.py` / `MLTrainingComputeAgent` training loop
```python
X = df.select(feature_cols).to_numpy()   # polars → numpy
y = df["win_label"].to_numpy()
```

### SIGNAL_SCHEMA_VERSION import
**Source:** `src/intelligence/trading/signal_schema.py` (constant = `"v2"`)
**Apply to:** `feature_builder.py` SQL query parameter
```python
from src.intelligence.trading.signal_schema import SIGNAL_SCHEMA_VERSION
# Use in query: WHERE signal_schema_version = $1 → params: [SIGNAL_SCHEMA_VERSION]
```

---

## No Analog Found

All files have analogs. No entries needed here.

---

## Key Pitfalls (from RESEARCH.md)

| Pitfall | Risk | Mitigation |
|---|---|---|
| `features_snapshot` nested in `i7` JSONB | Training returns NULLs | Migration 084 adds `features_snapshot JSONB` column to `signal_ledger`; `signal_writer_agent.py` populates it at insert |
| `volume_z` vs `volume_z_score` | NULL features | Always use `i1->>'volume_z_score'` (not `volume_z`) in SQL and Python |
| SIGUSR1 handler cannot be async | Runtime error | Sync handler → `asyncio.create_task()` only |
| Polars DataFrame passed to LightGBM | TypeError | Call `.to_numpy()` before `lgb.Dataset()` |
| `ModelRegistry.register()` uses `json.dumps(segment)` | Do not double-encode | Pass dict directly — registry handles it internally |
| SIGNAL_SCHEMA_VERSION = `"v2"` not `"v1"` | Zero training rows | Import constant from `signal_schema.py`; never hardcode |

---

## Metadata

**Analog search scope:** `src/intelligence/ai/alpha/`, `src/core/ai/`, `src/core/ml/`, `services/`, `src/intelligence/ml/`, `production/migrations/`, `production/systemd/`
**Files read:** 18
**Pattern extraction date:** 2026-05-13
