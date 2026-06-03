# Phase 101: Composite Fitness Function - Pattern Map

**Mapped:** 2026-06-02
**Files analyzed:** 12 new/modified files
**Analogs found:** 12 / 12

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/fitness_auditor.py` | service (oneshot) | batch / CRUD | `services/shadow_auditor.py` | exact |
| `src/intelligence/ai/fitness/__init__.py` | config | — | `src/intelligence/ai/alpha/__init__.py` | role-match |
| `src/intelligence/ai/fitness/accuracy.py` | utility | transform | `src/core/stats_utils.py` | role-match |
| `src/intelligence/ai/fitness/calibration.py` | utility | transform | `src/core/stats_utils.py` | role-match |
| `src/intelligence/ai/fitness/regime.py` | utility | transform | `src/core/stats_utils.py` | role-match |
| `src/intelligence/ai/fitness/efficiency.py` | utility | transform | `src/core/stats_utils.py` | role-match |
| `src/intelligence/ai/fitness/novelty.py` | utility | transform | `src/core/stats_utils.py` | role-match |
| `src/intelligence/ai/fitness/composite.py` | utility | transform | `src/core/stats_utils.py` | role-match |
| `src/intelligence/ai/fitness/gates.py` | utility | request-response | `services/shadow_auditor.py` (gate functions) | role-match |
| `production/migrations/115_agent_fitness.sql` | migration | CRUD | `production/migrations/086_validation_results.sql` | exact |
| `production/systemd/indicagent-fitness-auditor.service` | config | — | `production/systemd/indicagent-shadow-auditor.service` | exact |
| `production/systemd/indicagent-fitness-auditor.timer` | config | — | `production/systemd/indicagent-shadow-auditor.timer` | exact |
| `src/config/settings.py` (modify) | config | — | existing `Settings` `SWARM_*` / `SHADOW_*` fields | exact |
| `src/observability/metrics.py` (modify) | config | — | existing `SHADOW_*` block (lines 265-281) | exact |
| `services/shadow_auditor.py` (modify) | service (oneshot) | batch / CRUD | itself | exact |
| `tests/unit/services/test_fitness_auditor.py` | test | — | `tests/unit/services/test_shadow_auditor.py` | exact |
| `tests/unit/intelligence/test_fitness_gates.py` | test | — | `tests/unit/services/test_shadow_auditor.py` (gate tests) | exact |
| `tests/unit/intelligence/test_fitness_calculators.py` | test | — | `tests/unit/core/test_stats_utils.py` | exact |

---

## Pattern Assignments

### `services/fitness_auditor.py` (service, batch oneshot)

**Analog:** `services/shadow_auditor.py`

**Imports pattern** (lines 11-36):
```python
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
import structlog

from src.config.settings import Settings
from src.core.database_manager import create_pool as create_db_pool
from src.observability.metrics import (
    JOB_COMPLETED_TOTAL,
    flush_and_shutdown_metrics,
)
```

**Entry point pattern** (lines 336-358) - copy exactly, change job label to `"fitness-auditor"`:
```python
async def _amain() -> None:
    settings = Settings()
    pool = await create_db_pool(settings.database_url, min_size=2, max_size=5)
    try:
        await _run_audit(pool, settings.env_name)
    finally:
        await pool.close()


def main() -> None:
    """Run the fitness auditor once and emit a completion counter before exit."""
    try:
        asyncio.run(_amain())
        JOB_COMPLETED_TOTAL.add(1, {"job": "fitness-auditor", "status": "success"})
    except Exception as exc:
        JOB_COMPLETED_TOTAL.add(1, {"job": "fitness-auditor", "status": "failure"})
        raise exc
    finally:
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    main()
```

**Core audit loop pattern** (lines 85-111) - the `_run_audit` structure to follow:
```python
async def _run_audit(pool: asyncpg.Pool, env_name: str) -> None:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT component_name, component_type, is_shadow
            FROM shadow_registry
            """)

    for row in rows:
        name = row["component_name"]
        ctype = row["component_type"]
        # fitness_auditor: no early-continue for swarm_agent — they are evaluated here
        await _compute_agent_fitness(pool, name, ctype, settings)
```

**asyncpg write pattern** for `agent_fitness` (from research code examples, aligned to project asyncpg convention):
```python
# JSONB: pass dict directly — never json.dumps()
# timestamps: datetime.now(UTC) — never datetime.now()
await conn.execute("""
    INSERT INTO agent_fitness (
        agent_id, evaluated_at,
        accuracy_score, novelty_score, calibration_score,
        regime_score, efficiency_score, composite_score,
        n_resolved, promotion_ready, dimensions_jsonb
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
""",
    agent_id,
    datetime.now(UTC),
    accuracy, novelty, calibration, regime, efficiency, composite,
    n_resolved, promotion_ready,
    dimensions_dict,  # dict, not json.dumps(dict)
)
```

**Structlog pattern** (line 37, lines 101-103):
```python
logger = structlog.get_logger(__name__)
# ...
logger.debug("fitness_audit_skip_reason", component_name=name, reason="...")
logger.info("fitness_audit_done", agent_id=name, composite=composite)
logger.warning("fitness_audit_stale", agent_id=name, hours_stale=hours)
```

---

### `src/intelligence/ai/fitness/accuracy.py`, `calibration.py`, `regime.py`, `efficiency.py`, `novelty.py`, `composite.py` (utility, transform)

**Analog:** `src/core/stats_utils.py`

**Module header pattern** (lines 1-5):
```python
"""Statistical utility functions shared across intelligence services."""

from __future__ import annotations

import numpy as np
```

**Pure function signature pattern** (lines 8-33) - all calculator functions follow this exact shape:
```python
def bootstrap_ci_lower(
    pnl_r_values: list[float],
    alpha: float = 0.05,
    n_boot: int = 1000,
) -> float:
    """Bootstrap lower confidence bound on E[PnL_R].

    Returns float('-inf') if fewer than 10 samples (insufficient for reliable estimate).

    Args:
        pnl_r_values: PnL in R-multiples for resolved signals.
        alpha: Significance level. Default 0.05 gives 95% CI lower bound.
        n_boot: Number of bootstrap resamples. Default 1000.

    Returns:
        Lower bound float, or -inf on insufficient data.
    """
    if len(pnl_r_values) < 10:
        return float("-inf")
    ...
```

Apply this pattern to all dimension calculators: docstring with Args/Returns, early-return `None` on insufficient N (not `-inf`), no side effects, no DB access.

**bootstrap_ci_lower reuse** — import directly in `accuracy.py`:
```python
from src.core.stats_utils import bootstrap_ci_lower
```

---

### `src/intelligence/ai/fitness/gates.py` (utility, request-response)

**Analog:** `services/shadow_auditor.py` gate functions (lines 50-78)

**Pure gate function pattern to replace** (lines 50-78):
```python
def _should_promote(n: int, ci_lower: float, min_n: int, min_ev_r: float) -> bool:
    return n >= min_n and ci_lower > min_ev_r


def _should_demote(new_count: int, min_evaluations: int) -> bool:
    return new_count >= min_evaluations


def _tail_risk_blocks_promotion(
    skewness: float | None,
    recovery_factor: float | None,
    min_skewness: float,
    min_recovery: float,
) -> str | None:
    """Return the name of the breached metric, or None if promotion is not blocked."""
    if skewness is not None and skewness < min_skewness:
        return "skewness"
    if recovery_factor is not None and recovery_factor < min_recovery:
        return "recovery_factor"
    return None
```

The new `PromotionGate` and `DemotionGate` classes are a class-based generalization of this pattern. Return type `(bool, str | None)` mirrors `_tail_risk_blocks_promotion` returning `str | None` as the reason. Module header:

```python
"""Pure promotion/demotion gate logic — no DB access, directly testable."""

from __future__ import annotations
```

---

### `production/migrations/115_agent_fitness.sql` (migration, CRUD)

**Analog:** `production/migrations/086_validation_results.sql` + `095_signal_ledger_split.sql`

**Migration header pattern** (lines 1-17 of 086):
```sql
-- Migration 115: agent_fitness hypertable + shadow_registry.promotion_baseline
--
-- Purpose: Create agent_fitness hypertable for 5D composite fitness scores per
--          (agent_id, evaluated_at), and add promotion_baseline column to
--          shadow_registry for DemotionGate trigger 1.
--
-- Idempotency: All statements use IF NOT EXISTS / ADD COLUMN IF NOT EXISTS so
--              replaying this migration is safe and produces no errors.
--
-- Dependencies: 077_shadow_governance.sql (shadow_registry must exist),
--               TimescaleDB extension must be enabled.
```

**Hypertable creation pattern** from 086 (line 36):
```sql
SELECT create_hypertable('validation_results', 'computed_at', if_not_exists => TRUE);
```

**Compression policy pattern** from 095 (lines 47-52):
```sql
ALTER TABLE agent_fitness SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'agent_id',
    timescaledb.compress_orderby = 'evaluated_at DESC'
);
SELECT add_compression_policy('agent_fitness', INTERVAL '7 days', if_not_exists => TRUE);
```

**ALTER TABLE pattern** from 086 (line 52):
```sql
ALTER TABLE shadow_registry ADD COLUMN IF NOT EXISTS promotion_baseline DOUBLE PRECISION;
```

---

### `production/systemd/indicagent-fitness-auditor.service` (config)

**Analog:** `production/systemd/indicagent-shadow-auditor.service` (exact copy, change description and ExecStart)

```ini
[Unit]
Description=IndicAgent Fitness Auditor
After=network.target indicagent-infrastructure.target
Requires=indicagent-infrastructure.target

[Service]
Type=oneshot
WorkingDirectory=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/fitness_auditor.py
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

---

### `production/systemd/indicagent-fitness-auditor.timer` (config)

**Analog:** `production/systemd/indicagent-shadow-auditor.timer` (same structure, change cadence to 60 minutes per D-10)

```ini
[Unit]
Description=Fitness Auditor Timer — every 60 minutes

[Timer]
OnCalendar=hourly
Persistent=true
Unit=indicagent-fitness-auditor.service

[Install]
WantedBy=timers.target
```

---

### `src/config/settings.py` (modify — add FITNESS_* fields)

**Analog:** Existing `SWARM_*` fields in `settings.py` (lines 191-216 of settings.py)

**Field declaration pattern** (lines 191-215, using `SWARM_MIN_TF_MINUTES` as template):
```python
SWARM_MIN_TF_MINUTES: int = Field(
    default=5,
    validation_alias="SWARM_MIN_TF_MINUTES",
    description="...",
)
```

Apply to all FITNESS_* constants:
```python
fitness_accuracy_min_n: int = Field(
    default=50,
    validation_alias="FITNESS_ACCURACY_MIN_N",
    description="Minimum resolved signals required before accuracy_score is computable.",
)
fitness_calibration_min_n: int = Field(
    default=30,
    validation_alias="FITNESS_CALIBRATION_MIN_N",
    description="Minimum resolved signals with confidence values for calibration_score.",
)
fitness_regime_min_n_per_regime: int = Field(
    default=10,
    validation_alias="FITNESS_REGIME_MIN_N_PER_REGIME",
    description="Minimum signals per distinct regime for regime_score.",
)
fitness_regime_min_regimes: int = Field(
    default=2,
    validation_alias="FITNESS_REGIME_MIN_REGIMES",
    description="Minimum distinct regime values seen before regime_score is computable.",
)
fitness_efficiency_min_n: int = Field(
    default=20,
    validation_alias="FITNESS_EFFICIENCY_MIN_N",
    description="Minimum LLM calls before efficiency_score is computable.",
)
fitness_staleness_threshold_hours: int = Field(
    default=4,
    validation_alias="FITNESS_STALENESS_THRESHOLD_HOURS",
    description="Max hours since last agent_fitness row before shadow_auditor skips that agent.",
)
fitness_efficiency_token_ceiling: int = Field(
    default=4096,
    validation_alias="FITNESS_EFFICIENCY_TOKEN_CEILING",
    description="Token ceiling for efficiency normalization: efficiency = 1 - clamp(median_tokens / ceiling, 0, 1).",
)
```

---

### `src/observability/metrics.py` (modify — add FITNESS_* metrics)

**Analog:** `SHADOW_*` block at lines 265-281

**point_gauge and counter pattern** (lines 268-281):
```python
# Shadow plugin metrics
# ---------------------------------------------------------------------------

SHADOW_N_RESOLVED = point_gauge("shadow_n_resolved", "Resolved shadow signals")
SHADOW_PROMOTION_READY = point_gauge("shadow_promotion_ready", "1 when all gate conditions met")
SHADOW_TAIL_RISK_BLOCKED = _meter.create_counter(
    "shadow_tail_risk_blocked_total",
    description="Shadow promotions blocked by tail-risk gate (skewness or recovery_factor)",
)
```

Add a `# Fitness auditor metrics` section immediately after the SHADOW block using the same factory functions:
```python
# ---------------------------------------------------------------------------
# Fitness auditor metrics (Phase 101)
# ---------------------------------------------------------------------------

FITNESS_COMPOSITE_SCORE = point_gauge("fitness_composite_score", "5D composite fitness score per agent")
FITNESS_PROMOTION_READY = point_gauge("fitness_promotion_ready", "1 when PromotionGate all criteria pass")
FITNESS_DEMOTION_TRIGGERED = _meter.create_counter(
    "fitness_demotion_triggered_total",
    description="DemotionGate triggers fired per agent and trigger name",
)
FITNESS_STALE_SKIP_TOTAL = _meter.create_counter(
    "fitness_stale_skip_total",
    description="Agents skipped by shadow_auditor due to stale agent_fitness row",
)
FITNESS_POPULATION_STDDEV = point_gauge(
    "fitness_population_stddev",
    "FIT-06: stddev(composite_score) across live agent population",
)
```

---

### `services/shadow_auditor.py` (modify — staleness check + gate replacement)

**Analog:** itself

**Swarm agent skip to replace** (lines 99-103):
```python
# BEFORE — unconditional skip:
if ctype == "swarm_agent":
    logger.debug("shadow_audit_skip_swarm_agent", component_name=name)
    continue
```

Replace with staleness check pattern (gate logic → gates.py):
```python
# AFTER — staleness check for all types, route to fitness gate:
fitness_row = await _fetch_latest_fitness(pool, name)
if fitness_row is None:
    logger.debug("shadow_audit_no_fitness_row", component_name=name)
    continue
staleness_hours = (datetime.now(UTC) - fitness_row["evaluated_at"]).total_seconds() / 3600
if staleness_hours > settings.fitness_staleness_threshold_hours:
    FITNESS_STALE_SKIP_TOTAL.add(1, {"agent_id": name})
    logger.warning("shadow_audit_stale_fitness", component_name=name, hours_stale=round(staleness_hours, 1))
    continue
```

---

### `tests/unit/services/test_fitness_auditor.py` (test)

**Analog:** `tests/unit/services/test_shadow_auditor.py`

**Test module header pattern** (lines 1-19):
```python
"""Unit tests for fitness_auditor oneshot logic."""

from __future__ import annotations

import asyncio
import dataclasses
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg

from services.fitness_auditor import (
    _run_fitness_audit,
    ...
)
```

**Mock pool pattern** used throughout `test_shadow_auditor.py`:
```python
from unittest.mock import AsyncMock, MagicMock, patch
# pool.acquire().__aenter__ returns mock conn
```

---

### `tests/unit/intelligence/test_fitness_gates.py` (test)

**Analog:** `tests/unit/services/test_shadow_auditor.py` gate tests (lines 24-52)

**Pure function test pattern** — no mocks, no DB, direct assertion:
```python
def test_promotion_gate_passes_when_n_and_ci_met():
    assert _should_promote(n=150, ci_lower=0.02, min_n=100, min_ev_r=0.0) is True


def test_promotion_gate_fails_when_n_insufficient():
    assert _should_promote(n=50, ci_lower=0.05, min_n=100, min_ev_r=0.0) is False
```

Apply same pattern:
```python
def test_promotion_gate_passes_all_criteria():
    gate = PromotionGate(min_n=50, novelty_threshold=0.15, stability_threshold=0.02, ...)
    passed, reason = gate.can_promote(fitness_row, history)
    assert passed is True
    assert reason is None

def test_demotion_gate_fires_on_fitness_decay():
    gate = DemotionGate(decay_fraction=0.80, ...)
    fired, reason = gate.should_demote(fitness_row, history)
    assert fired is True
    assert "fitness_decay" in reason
```

---

### `tests/unit/intelligence/test_fitness_calculators.py` (test)

**Analog:** `tests/unit/core/test_stats_utils.py`

**Parametric boundary test pattern** (lines 10-55):
```python
def test_empty_list_returns_neg_inf():
    assert bootstrap_ci_lower([]) == float("-inf")

def test_fewer_than_10_samples_returns_neg_inf():
    assert bootstrap_ci_lower([0.1] * 9) == float("-inf")

def test_exactly_10_samples_returns_finite():
    result = bootstrap_ci_lower([0.1] * 10)
    assert math.isfinite(result)
```

Apply same boundary pattern per dimension:
```python
def test_accuracy_returns_none_below_min_n():
    assert accuracy_score(pnl_r_values=[0.1]*49, outcomes=["target_1"]*49, min_n=50) is None

def test_accuracy_returns_float_at_min_n():
    result = accuracy_score(pnl_r_values=[0.1]*50, outcomes=["target_1"]*50, min_n=50)
    assert result is not None
    assert 0.0 <= result <= 1.0

def test_composite_returns_none_if_any_dimension_none():
    assert composite_score(0.7, None, 0.8, 0.6, 0.9) is None

def test_composite_collapses_on_zero_dimension():
    assert composite_score(0.7, 0.0, 0.8, 0.6, 0.9) == 0.0
```

---

## Shared Patterns

### Oneshot script entry point
**Source:** `services/shadow_auditor.py` lines 336-358
**Apply to:** `services/fitness_auditor.py`

```python
def main() -> None:
    try:
        asyncio.run(_amain())
        JOB_COMPLETED_TOTAL.add(1, {"job": "fitness-auditor", "status": "success"})
    except Exception as exc:
        JOB_COMPLETED_TOTAL.add(1, {"job": "fitness-auditor", "status": "failure"})
        raise exc
    finally:
        flush_and_shutdown_metrics()
```

Critical: `job=` label MUST match the systemd unit name `%n` suffix (kebab-case). Unit `indicagent-fitness-auditor.service` → `job="fitness-auditor"`.

### asyncpg pool acquisition
**Source:** `services/shadow_auditor.py` lines 121-123
**Apply to:** All DB-accessing functions in `fitness_auditor.py`

```python
async with pool.acquire() as conn:
    rows = await conn.fetch("SELECT ...", arg1, arg2)
```

### JSONB — never json.dumps
**Source:** CLAUDE.md + `services/shadow_auditor.py` pattern
**Apply to:** `agent_fitness.dimensions_jsonb` writes in `fitness_auditor.py`

Pass `dict` directly to asyncpg parameter position. Never `json.dumps(d)`.

### UTC timestamps
**Source:** `services/shadow_auditor.py` line 140, 283
**Apply to:** All `datetime.now()` calls in fitness_auditor.py and dimension calculators

```python
from datetime import UTC, datetime
now = datetime.now(UTC)
```

### OTel metrics — point_gauge vs counter
**Source:** `src/observability/metrics.py` lines 268-281
**Apply to:** All new `FITNESS_*` metrics in `src/observability/metrics.py`

- Absolute values (scores, gauges): `point_gauge(name, doc)` — call `.set(value, {"label": val})`
- Cumulative events (errors, triggers): `_meter.create_counter(name, description=doc)` — call `.add(1, {"label": val})`

### Settings Field pattern
**Source:** `src/config/settings.py` lines 191-215
**Apply to:** All `FITNESS_*` constants in `settings.py`

```python
fitness_accuracy_min_n: int = Field(
    default=50,
    validation_alias="FITNESS_ACCURACY_MIN_N",
    description="...",
)
```

### Migration idempotency
**Source:** `production/migrations/086_validation_results.sql` lines 8-9
**Apply to:** `production/migrations/115_agent_fitness.sql`

All DDL statements use `IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`. The migration must be safely replayable.

### Hypertable compression
**Source:** `production/migrations/095_signal_ledger_split.sql` lines 47-52
**Apply to:** `agent_fitness` hypertable in migration 115

```sql
SELECT create_hypertable('agent_fitness', 'evaluated_at',
    chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);
ALTER TABLE agent_fitness SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'agent_id',
    timescaledb.compress_orderby = 'evaluated_at DESC'
);
SELECT add_compression_policy('agent_fitness', INTERVAL '7 days', if_not_exists => TRUE);
```

Note: D-01 specifies no retention policy — fitness history is permanent.

---

## No Analog Found

All files have close codebase analogs. No files require falling back to RESEARCH.md patterns exclusively.

---

## Metadata

**Analog search scope:** `services/`, `src/intelligence/ai/`, `src/core/`, `src/config/`, `src/observability/`, `production/migrations/`, `production/systemd/`, `tests/unit/services/`, `tests/unit/core/`
**Files scanned:** 12 analog files read
**Pattern extraction date:** 2026-06-02
