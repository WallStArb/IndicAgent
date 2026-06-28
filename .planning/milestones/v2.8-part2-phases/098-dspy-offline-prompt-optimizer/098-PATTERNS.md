# Phase 098: DSPy Offline Prompt Optimizer - Pattern Map

**Mapped:** 2026-06-02
**Files analyzed:** 6 (2 Python source, 1 core class, 1 migration, 2 systemd units)
**Analogs found:** 6 / 6

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/dspy_optimizer.py` | service (oneshot entrypoint) | batch | `services/ml_training_agent.py` | exact |
| `src/intelligence/optimization/dspy_optimizer.py` | service (batch trainer class) | batch, CRUD | `src/intelligence/services/ml_trainer.py` | exact |
| `production/migrations/115_prompt_versions.sql` | migration | - | `production/migrations/084_ai_enrichment_tables.sql` | exact |
| `production/systemd/indicagent-dspy-optimizer.service` | config | - | `production/systemd/indicagent-ml-training.service` | exact |
| `production/systemd/indicagent-dspy-optimizer.timer` | config | - | `production/systemd/indicagent-ml-training.timer` | exact |
| `src/intelligence/ai/alpha/correlation_prompts.py` | utility (prompt registry) | - | self (read-only reference — no new file, DSPy reads this at compile time) | reference only |

---

## Pattern Assignments

### `services/dspy_optimizer.py` (oneshot entrypoint, batch)

**Analog:** `services/ml_training_agent.py`

**Full file — copy exactly, substituting class name and job label.**

**Imports pattern** (lines 1-17):
```python
"""DSPy Optimizer Agent — systemd oneshot entrypoint (Phase 098).

Invoked weekly by indicagent-dspy-optimizer.timer (Mon 07:00 UTC / 02:00 ET).
Type=oneshot: runs once, exits.
"""

from __future__ import annotations

import asyncio

import _path_bootstrap  # noqa: F401 — project root on sys.path

from src.config.settings import Settings
from src.intelligence.optimization.dspy_optimizer import DSPyOptimizer
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
```

**Core entrypoint pattern** (lines 20-41 of analog):
```python
def main() -> None:
    """Create agent, run, exit.

    DSPyOptimizer._run() swallows all exceptions and logs them,
    so asyncio.run() always completes cleanly (systemd oneshot exit code 0).
    The try/except here catches any unexpected outer-level exception that
    escapes the agent so the completion counter is always emitted.
    """
    try:
        settings = Settings()
        agent = DSPyOptimizer(settings)
        asyncio.run(agent.start())
        JOB_COMPLETED_TOTAL.add(1, {"job": "dspy-optimizer", "status": "success"})
    except Exception as exc:
        JOB_COMPLETED_TOTAL.add(1, {"job": "dspy-optimizer", "status": "failure"})
        raise exc
    finally:
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    main()
```

**Critical rules:**
- `import _path_bootstrap` MUST appear before any `from src.*` import (RESEARCH pitfall 6)
- `job` label value MUST be `"dspy-optimizer"` — must match systemd unit `%n` suffix exactly (CLAUDE.md D-06)
- `skipped_data_gate` is emitted from INSIDE `DSPyOptimizer._run()`, NOT from `main()`. `main()` still emits `"success"` on clean exit.
- `flush_and_shutdown_metrics()` in `finally` — without it, the OTel counter never drains to the collector

---

### `src/intelligence/optimization/dspy_optimizer.py` (batch trainer class, CRUD + batch)

**Analog:** `src/intelligence/services/ml_trainer.py`

**Imports pattern** (analog lines 22-48 — adapt for DSPy):
```python
from __future__ import annotations

import json
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import structlog

from src.config.settings import Settings
from src.core.agent.base import BaseDaemon
from src.core.database_manager import create_pool as create_db_pool
from src.core.service_utils import setup_service_logging
from src.observability.metrics import JOB_COMPLETED_TOTAL
```

**Constructor pattern** (analog lines 82-88):
```python
class DSPyOptimizer(BaseDaemon):
    def __init__(self, settings: Settings) -> None:
        setup_service_logging("logs/dspy_optimizer.log")
        super().__init__("DSPyOptimizer")
        self.settings = settings
        self._pool: asyncpg.Pool | None = None
```

**_setup / _teardown pattern** (analog lines 90-98):
```python
async def _setup(self) -> None:
    self._pool = await create_db_pool(self.settings.database_url)
    logger.info("dspy_optimizer.setup_complete")

async def _teardown(self) -> None:
    if self._pool:
        await self._pool.close()
```

**_run() top-level exception swallow pattern** (analog lines 104-121):
```python
async def _run(self) -> None:
    """One-shot optimization entry point.

    Catches all exceptions at the top level so systemd Type=oneshot exits 0,
    ensuring the timer fires again the following week regardless of failures.
    """
    try:
        await self._run_optimization()
    except Exception:
        logger.exception("dspy_optimizer.error_top_level")
        return
```

**Data gate pattern** — modeled on `_should_retrain()` (analog lines 144-165):
```python
async def _check_data_gate(self, agent_id: str) -> int:
    """Return row count for agent. Gate: >= 500 labeled rows."""
    async with self._pool.acquire() as conn:
        count = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM llm_calls
            WHERE agent_id = $1
              AND outcome IS NOT NULL
            """,
            agent_id,
        )
    return int(count or 0)
```

**Gate skip structlog + counter pattern** (analog lines 155-165):
```python
if eligible_agents == []:
    logger.info(
        "dspy_optimizer.gate_skip_all",
        agent_counts=per_agent_counts,   # dict[agent_id, int]
        required=_DATA_GATE_MIN,
    )
    JOB_COMPLETED_TOTAL.add(1, {"job": "dspy-optimizer", "status": "skipped_data_gate"})
    return
```

**Checkpoint / report write pattern** (analog lines 134-142):
```python
def _write_report(self, report: dict[str, Any]) -> None:
    """Write JSON comparison report to logs/."""
    date_str = datetime.now(UTC).strftime("%Y%m%d")
    path = Path(f"logs/dspy_optimizer_report_{date_str}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2))
    tmp.replace(path)
```

**asyncpg INSERT for `prompt_versions`** (pattern from CLAUDE.md + ml_trainer DB usage):
```python
async with self._pool.acquire() as conn:
    await conn.execute(
        """
        INSERT INTO prompt_versions
            (agent_id, version_tag, compiled_prompt, status)
        VALUES ($1, $2, $3, 'candidate')
        ON CONFLICT (version_tag) DO NOTHING
        """,
        agent_id,
        version_tag,   # str — f"{agent_id}_dspy_{YYYYMMDD}_{run_hour:02d}"
        compiled_dict, # dict — asyncpg passes dict as JSONB directly (no json.dumps())
    )
```

**CRITICAL asyncpg rule (CLAUDE.md):** Pass `dict` directly for JSONB columns — do NOT call `json.dumps()`. asyncpg handles serialization.

**Timestamps rule (CLAUDE.md):** Use `datetime.now(UTC)` only — never `datetime.now()` or `datetime.utcnow()`.

---

### `production/migrations/115_prompt_versions.sql` (migration)

**Analog:** `production/migrations/084_ai_enrichment_tables.sql` (table creation pattern) + `production/migrations/099_dlq_quarantine.sql` (CHECK constraint pattern).

**Table creation pattern** (analog 084 lines 29-37, adapted):
```sql
-- Migration 115: prompt_versions table for DSPy offline optimizer (Phase 098)
-- Idempotent: safe to re-apply.
--
-- Stores compiled DSPy BootstrapFewShot program state per agent.
-- Status lifecycle: candidate -> active -> retired.

CREATE TABLE IF NOT EXISTS prompt_versions (
    version_id      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        TEXT        NOT NULL,
    version_tag     TEXT        UNIQUE NOT NULL,
    compiled_prompt JSONB       NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'candidate'
                                CHECK (status IN ('candidate', 'active', 'retired')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    promoted_at     TIMESTAMPTZ
);
```

**Index pattern** (analog 084 + 087):
```sql
CREATE INDEX IF NOT EXISTS idx_prompt_versions_agent_status
    ON prompt_versions (agent_id, status);
```

**Style rules from analogs:**
- Header comment block: migration number, phase, idempotent declaration
- `IF NOT EXISTS` on all CREATE TABLE and CREATE INDEX
- Column alignment (tab-aligned type column at position 17)
- TIMESTAMPTZ NOT NULL DEFAULT NOW() for created_at (never bare TIMESTAMP)

---

### `production/systemd/indicagent-dspy-optimizer.service` (config)

**Analog:** `production/systemd/indicagent-ml-training.service` (exact copy, two fields change)

**Full file pattern** (analog verbatim — lines 1-15, two fields substituted):
```ini
[Unit]
Description=IndicAgent DSPy Offline Prompt Optimizer -- weekly BootstrapFewShot compilation
After=network.target indicagent-infrastructure.target
Requires=indicagent-infrastructure.target

[Service]
Type=oneshot
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/dspy_optimizer.py
TimeoutStartSec=7200

[Install]
WantedBy=multi-user.target
```

**What changes vs analog:**
- `Description` — updated
- `ExecStart` — `services/dspy_optimizer.py` (not `ml_training_agent.py`)
- Everything else is identical — `Type=oneshot`, `User=bg`, `WorkingDirectory`, `TimeoutStartSec=7200`

---

### `production/systemd/indicagent-dspy-optimizer.timer` (config)

**Analog:** `production/systemd/indicagent-ml-training.timer` (same structure, different schedule)

**Full file pattern** (analog lines 1-10, two fields substituted):
```ini
[Unit]
Description=DSPy Optimizer Timer -- weekly Monday 07:00 UTC (02:00 ET)

[Timer]
OnCalendar=Mon *-*-* 07:00:00 UTC
Persistent=true
Unit=indicagent-dspy-optimizer.service

[Install]
WantedBy=timers.target
```

**What changes vs analog:**
- `Description` — updated
- `OnCalendar` — `Mon *-*-* 07:00:00 UTC` (weekly, not nightly `*-*-* 03:00:00`)
- `Unit` — `indicagent-dspy-optimizer.service`

**Note:** Monday 02:00 ET = 07:00 UTC (UTC-5 winter anchor; close enough for weekly cadence year-round).

---

## Shared Patterns

### OTel Job Counter (D-06 Oneshot Contract)
**Source:** `src/observability/metrics.py` lines 382-385, `services/ml_training_agent.py` lines 32-35
**Apply to:** `services/dspy_optimizer.py`

```python
# Already registered in metrics.py — do not re-register:
JOB_COMPLETED_TOTAL = _meter.create_counter(
    "job_completed_total",
    description="Oneshot job completions by name and status",
)

# Emit at exit — three possible status values for this job:
JOB_COMPLETED_TOTAL.add(1, {"job": "dspy-optimizer", "status": "success"})
JOB_COMPLETED_TOTAL.add(1, {"job": "dspy-optimizer", "status": "failure"})
JOB_COMPLETED_TOTAL.add(1, {"job": "dspy-optimizer", "status": "skipped_data_gate"})
```

**`flush_and_shutdown_metrics()` in `finally`** — mandatory at process exit for OTel drain.

### asyncpg Pool
**Source:** `src/intelligence/services/ml_trainer.py` lines 38-39, 91-93
**Apply to:** `src/intelligence/optimization/dspy_optimizer.py`

```python
from src.core.database_manager import create_pool as create_db_pool

# In _setup():
self._pool = await create_db_pool(self.settings.database_url)

# In _teardown():
if self._pool:
    await self._pool.close()
```

### structlog Usage
**Source:** `src/intelligence/services/ml_trainer.py` lines 48, 157-165
**Apply to:** `src/intelligence/optimization/dspy_optimizer.py`

```python
import structlog
logger = structlog.get_logger(__name__)

# Per-agent structured events — always include agent_id + key metric:
logger.info(
    "dspy_optimizer.gate_check",
    agent_id=agent_id,
    row_count=count,
    required=_DATA_GATE_MIN,
)
logger.info(
    "dspy_optimizer.compile_complete",
    agent_id=agent_id,
    duration_s=round(elapsed, 2),
    n_demos=len(compiled_dict.get("predict", {}).get("demos", [])),
)
```

**CLAUDE.md rule:** Never pass `event=<value>` as a keyword arg — use `signal=`, `data=`, or descriptive keys instead.

### Settings Pattern
**Source:** `services/ml_training_agent.py` line 29
**Apply to:** `services/dspy_optimizer.py`

```python
from src.config.settings import Settings
settings = Settings()  # reads from .env; INDICAGENT_ENV controls env prefix
```

### UTC Timestamps
**Source:** `src/intelligence/services/ml_trainer.py` line 26, 139
**Apply to:** `src/intelligence/optimization/dspy_optimizer.py`

```python
from datetime import UTC, datetime

# Always:
datetime.now(UTC)

# Never:
datetime.now()         # wrong — no timezone
datetime.utcnow()      # wrong — deprecated
```

### PROMPT_REGISTRY Interface
**Source:** `src/intelligence/ai/alpha/correlation_prompts.py` lines 15-17
**Apply to:** `src/intelligence/optimization/dspy_optimizer.py` (read-only import at compile time)

```python
# Pattern for importing per-agent prompt registry at compile time:
from src.intelligence.ai.alpha.correlation_prompts import ACTIVE_VERSION, PROMPT_REGISTRY

template = PROMPT_REGISTRY[ACTIVE_VERSION]
# Use template docstring as DSPy Signature instructions field
```

**Rule (D-04):** The batch job imports PROMPT_REGISTRY read-only. No Python prompt file is modified. DB is the only output.

---

## No Analog Found

None. All files have close analogs in the codebase.

---

## Key Pitfalls Flagged by RESEARCH.md

| Pitfall | File | Guard |
|---|---|---|
| `import _path_bootstrap` must be first import | `services/dspy_optimizer.py` | Copy from ml_training_agent.py verbatim — do not reorder |
| JSONB: pass `dict` not `json.dumps(dict)` | `src/intelligence/optimization/dspy_optimizer.py` | asyncpg serializes automatically |
| `skipped_data_gate` emitted inside `_run()`, not `main()` | both | `main()` always emits `success` or `failure` |
| `version_tag` uniqueness on re-run | migration + optimizer | Use `INSERT ... ON CONFLICT (version_tag) DO NOTHING`; add hour suffix |
| Regime values are `'0'`, `'1'`, `'2'` (numeric strings) | optimizer | `WHERE regime IN ('0','1','2')` not string labels |
| `AgentDependencies` doesn't exist yet (Phase 096 dep) | startup injection path | Scope compile+store path in Phase 098 Group A; injection path in Group B after Phase 096 |
| DSPy package name: `dspy` not `dspy-ai` | `requirements.txt` | `dspy>=3.2.1` |

---

## Metadata

**Analog search scope:** `services/`, `src/intelligence/services/`, `production/migrations/`, `production/systemd/`, `src/intelligence/ai/alpha/`
**Files scanned:** 10
**Pattern extraction date:** 2026-06-02
