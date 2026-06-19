# Phase 114: Occam's Razor - Pattern Map

**Mapped:** 2026-06-03
**Files analyzed:** 5
**Analogs found:** 5 / 5

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/intelligence/ai/evaluators/baseline.py` | utility | transform | `src/intelligence/ml/confidence_calibrator.py` | role-match |
| `src/intelligence/ai/evaluators/occam_razor_evaluator.py` | agent | request-response | `src/intelligence/ai/alpha/ml_scorer_agent.py` | exact |
| `services/alpha_swarm.py` | service | event-driven | `services/alpha_swarm.py` (self) | exact (modify) |
| Migration for shadow_registry | migration | batch | `production/migrations/077_shadow_governance.sql` | exact |
| `src/observability/metrics.py` | config | request-response | `src/observability/metrics.py` (self) | exact (modify) |

## Pattern Assignments

### `src/intelligence/ai/evaluators/baseline.py` (utility, transform)

**Analog:** `src/intelligence/ml/confidence_calibrator.py`

**Imports pattern** (lines 1-22):
```python
from __future__ import annotations

import collections
from typing import Any

import numpy as np
import structlog
from sklearn.isotonic import IsotonicRegression
```

**Protocol interface pattern** (new file pattern from RESEARCH.md):
```python
from __future__ import annotations
from typing import Protocol, Any
import numpy as np
from sklearn.linear_model import LogisticRegression

class BaselineModel(Protocol):
    """Baseline model interface."""
    def predict(self, features: np.ndarray) -> np.ndarray: ...

class BaselineBuilder(Protocol):
    """Build a simple baseline for a given agent type."""
    def build(self, features: np.ndarray, targets: np.ndarray) -> BaselineModel:
        ...
```

**sklearn LogisticRegression pattern** (from `src/intelligence/weight_updater.py` lines 284-286):
```python
# Train LogisticRegression
model = LogisticRegression(C=1.0, max_iter=500, random_state=42)
model.fit(x, y)
```

**numpy array processing pattern** (from `confidence_calibrator.py` lines 53-56):
```python
x = np.array(confidences, dtype=np.float64)
y = np.array(win_labels, dtype=np.float64)
ir = IsotonicRegression(out_of_bounds="clip")
ir.fit(x, y)
```

---

### `src/intelligence/ai/evaluators/occam_razor_evaluator.py` (agent, request-response)

**Analog:** `src/intelligence/ai/alpha/ml_scorer_agent.py`

**Class definition pattern** (lines 77-98):
```python
class MLEvaluator(Evaluator):
    """LightGBM inference multiplier agent.

    Loads promoted models from ModelRegistry on startup.
    shadow_only=True: never affects live trade decisions until registry promotion.
    """

    output_schema: ClassVar[dict] = {"multiplier": float, "ml_score": float, "segment": str}

    agent_id = "ml_scorer_v1"
    group = "alpha"
    tiers_needed = frozenset()
    latency_budget_ms = 50.0
    shadow_only: bool = True

    def _apply_shadow_mode_config(self) -> None:
        """Read ai.agent.<self.agent_id>.shadow_mode from config; fail-closed on miss."""
        override = self.get_config(f"ai.agent.{self.agent_id}.shadow_mode", None)
        if override is None:
            return  # keep class default True (fail-closed)
        # override may arrive as bool (from RUNTIME_DEFAULTS) or str (from Kafka); normalize:
        if isinstance(override, bool):
            self.shadow_only = override
        elif isinstance(override, str):
            self.shadow_only = override.strip().lower() in ("true", "1", "yes")
```

**DB pool pattern** (lines 117-122):
```python
def __init__(self, *, dependencies: AgentDependencies, **kwargs: Any) -> None:
    super().__init__(**kwargs)
    if dependencies.pool is None:
        raise ValueError("MLEvaluator requires dependencies.pool")
    self._pool = dependencies.pool
```

**Bootstrap CI pattern** (from `src/core/stats_utils.py` lines 8-33):
```python
def bootstrap_ci_lower(
    pnl_r_values: list[float],
    alpha: float = 0.05,
    n_boot: int = 1000,
) -> float:
    """Bootstrap lower confidence bound on E[PnL_R].

    Returns float('-inf') if fewer than 10 samples (insufficient for reliable estimate).
    Uses a fixed RNG seed (42) for reproducibility in tests.
    """
    if len(pnl_r_values) < 10:
        return float("-inf")
    rng = np.random.default_rng(42)
    arr = np.array(pnl_r_values)
    boot_means = np.array(
        [rng.choice(arr, size=len(arr), replace=True).mean() for _ in range(n_boot)]
    )
    return float(np.percentile(boot_means, alpha / 2 * 100))
```

**Zero-variance guard pattern** (from `src/intelligence/ml/information_coefficient.py` lines 99-102):
```python
# Guard: zero-variance inputs produce nan correlation
if conf_arr.std() < 1e-9 or pnl_arr.std() < 1e-9:
    logger.warning("ic_zero_variance n=%d", len(pairs))
    return None, None, len(pairs)
```

---

### `services/alpha_swarm.py` (service, event-driven - MODIFY)

**Analog:** `services/alpha_swarm.py` (existing _graduation_loop pattern)

**Graduation loop pattern** (lines 212-227):
```python
async def _graduation_loop(self) -> None:
    """Override BaseGroupCoordinator stub: evaluate all agents every 15 min.

    Runs Spearman p on (multiplier vs pnl_r) per (agent_id, timeframe) from
    signal_lineage JOIN signal_ledger_full. UPSERTs swarm_agent_weights.
    """
    interval_s: float = getattr(self.settings, "swarm_graduation_interval_s", 900)
    while self.running:
        try:
            await asyncio.sleep(interval_s)
            await self._run_graduation_cycle()
        except asyncio.CancelledError:
            break
        except Exception as error:
            self.logger.error("graduation_cycle_failed", err=str(error))
```

**DB query pattern for signal_ledger** (lines 263-280):
```python
async with self._pool.acquire() as conn:
    rows = await conn.fetch(
        """
        SELECT sl.tf AS timeframe,
               sl.multiplier AS multiplier,
               (sl.metadata->'payload'->>'confidence')::float AS stated_confidence,
               ledger.pnl_r AS pnl_r
        FROM signal_lineage sl
        JOIN signal_ledger_full ledger ON ledger.signal_id = sl.signal_id
        WHERE sl.event_type = 'agent_prediction'
          AND sl.source = $1
          AND sl.multiplier IS NOT NULL
          AND ledger.outcome IS NOT NULL
          AND ledger.pnl_r IS NOT NULL
          AND sl.ts > NOW() - INTERVAL '30 days'
        """,
        agent_id,
    )
```

**shadow_registry UPDATE pattern** (from `services/shadow_auditor.py` lines 147-158):
```python
await conn.execute(
    """
    UPDATE shadow_registry
    SET last_eval_n=$1, last_eval_ev_r=$2, last_eval_ci_lower=$3,
        last_eval_win_rate=$4, last_eval_at=$5
    WHERE component_name=$6
    """,
    n,
    ev_r,
    ci_lower,
    win_rate,
    now,
    name,
)
```

**Integration point:** Add `await self._run_occam_razor_cycle()` call after `await self._run_graduation_cycle()` in the graduation loop (lines 222-223).

---

### Migration for shadow_registry (migration, batch)

**Analog:** `production/migrations/077_shadow_governance.sql`

**Table structure pattern** (lines 5-25):
```sql
CREATE TABLE IF NOT EXISTS shadow_registry (
    component_name                TEXT PRIMARY KEY,
    component_type                TEXT NOT NULL
        CHECK (component_type IN ('i7_plugin', 'swarm_agent')),
    is_shadow                     BOOLEAN NOT NULL DEFAULT TRUE,
    enrolled_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    promoted_at                   TIMESTAMPTZ,
    demoted_at                    TIMESTAMPTZ,
    min_n                         INTEGER NOT NULL DEFAULT 100,
    -- ... additional columns
);
```

**ALTER TABLE pattern** (from `db/migrations/095_restore_signal_definition_fields.sql` lines 8-13):
```sql
ALTER TABLE signal_ledger
  ADD COLUMN IF NOT EXISTS entry_price     NUMERIC,
  ADD COLUMN IF NOT EXISTS stop_loss       NUMERIC,
  ADD COLUMN IF NOT EXISTS targets         JSONB;
```

**Migration pattern for ORE columns:**
```sql
BEGIN;

ALTER TABLE shadow_registry
  ADD COLUMN IF NOT EXISTS rejection_reason TEXT,
  ADD COLUMN IF NOT EXISTS complexity_score FLOAT,
  ADD COLUMN IF NOT EXISTS last_occam_check TIMESTAMPTZ;

COMMENT ON COLUMN shadow_registry.rejection_reason IS
    'Reason for Occam razor rejection (baseline_win, tie, insufficient_data)';
COMMENT ON COLUMN shadow_registry.complexity_score IS
    'Log-transformed complexity score from params × latency × train_time';
COMMENT ON COLUMN shadow_registry.last_occam_check IS
    'Timestamp of last Occam razor evaluation';

COMMIT;
```

**ml_models enhancement pattern** (from `production/migrations/059_ml_models.sql`):
```sql
ALTER TABLE ml_models
  ADD COLUMN IF NOT EXISTS param_count INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS inference_latency_ms FLOAT DEFAULT 0.0,
  ADD COLUMN IF NOT EXISTS training_time_ms FLOAT DEFAULT 0.0;
```

---

### `src/observability/metrics.py` (config, request-response - MODIFY)

**Analog:** `src/observability/metrics.py` (self)

**OTel counter pattern** (lines 91-94):
```python
PLUGIN_FALLBACK_TOTAL = _meter.create_counter(
    "intelligence_pipeline_plugin_fallback_total",
    description="Plugin fallbacks to direct calculation",
)
```

**OTel histogram pattern** (lines 95-98):
```python
PLUGIN_DURATION_MS = _meter.create_histogram(
    "intelligence_pipeline_plugin_duration_ms",
    description="Per-plugin execution latency",
)
```

**OTel point_gauge pattern** (lines 682-685):
```python
SWARM_AGENT_WEIGHT = point_gauge(
    "swarm_agent_weight",
    "Per-agent learned weight by timeframe — key Renaissance health signal",
)
```

**ORE metrics to add:**
```python
# Occam's Razor evaluator metrics (Phase 114)
OCCAM_EVALUATIONS_TOTAL = _meter.create_counter(
    "occam_evaluations_total",
    description="Occam razor evaluations run by agent_id and outcome",
)
OCCAM_REJECTIONS_TOTAL = _meter.create_counter(
    "occam_rejections_total",
    description="Agents rejected due to Occam razor (baseline win or tie)",
)
OCCAM_COMPLEXITY_RATIO = _meter.create_histogram(
    "occam_complexity_ratio",
    description="Ratio of complex model complexity to baseline (1.0 = same complexity)",
)
OCCAM_SHARPE_DELTA = _meter.create_histogram(
    "occam_sharpe_delta",
    description="Sharpe ratio delta (complex - baseline) before complexity penalty",
)
```

**Usage pattern** (from `alpha_swarm.py` line 336):
```python
SWARM_AGENT_WEIGHT.set(weight, {"agent_id": agent_id, "timeframe": tf})
```

---

## Shared Patterns

### DB Pool Acquisition
**Source:** `services/alpha_swarm.py` lines 263-264, `services/shadow_auditor.py` lines 142-143
**Apply to:** All OccamRazorEvaluator DB operations
```python
async with self._pool.acquire() as conn:
    rows = await conn.fetch(...)
    # or
    await conn.execute(...)
```

### scipy.stats Usage
**Source:** `src/intelligence/ml/information_coefficient.py` lines 104-105
**Apply to:** Bootstrap CI fallback and statistical testing
```python
from scipy import stats

ic_score, p_value = stats.pearsonr(conf_arr, pnl_arr)
```

### numpy.random.default_rng with Fixed Seed
**Source:** `src/core/stats_utils.py` line 28
**Apply to:** All bootstrap resampling for reproducibility
```python
rng = np.random.default_rng(42)
```

### Shadow Registry ACID Update
**Source:** `services/shadow_auditor.py` lines 225-234
**Apply to:** Occam rejection updates
```python
async with pool.acquire() as conn:
    await conn.execute(
        """
        UPDATE shadow_registry
        SET is_shadow=FALSE, promoted_at=$1, demotion_consecutive_count=0
        WHERE component_name=$2
        """,
        now,
        name,
    )
```

### Exception Handling with Logging
**Source:** `services/alpha_swarm.py` lines 236-243
**Apply to:** All per-agent evaluation loops
```python
for agent in self._agents:
    try:
        await self._evaluate_agent(agent.agent_id)
    except Exception as error:
        self.logger.warning(
            "alpha_swarm.graduation_failed",
            agent_id=agent.agent_id,
            error=str(error),
        )
```

### OTel Metrics with Labels
**Source:** `services/alpha_swarm.py` line 336
**Apply to:** All ORE metrics emissions
```python
SWARM_AGENT_WEIGHT.set(weight, {"agent_id": agent_id, "timeframe": tf})
```

### Zero-Variance Guard
**Source:** `src/intelligence/ml/information_coefficient.py` lines 99-102
**Apply to:** Sharpe computation before bootstrap
```python
if arr.std() < 1e-9:
    logger.warning("zero_variance n=%d", len(arr))
    return None
```

## No Analog Found

Files with no close match in the codebase (planner should use RESEARCH.md patterns instead):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| None | - | - | All files have strong analogs in existing codebase |

## Metadata

**Analog search scope:** `src/intelligence/ai/`, `services/`, `src/core/`, `src/observability/`, `production/migrations/`, `db/migrations/`
**Files scanned:** 15
**Pattern extraction date:** 2026-06-03
