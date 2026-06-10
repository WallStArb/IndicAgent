# Phase 120: Shadow Mode Validation - Pattern Map

**Mapped:** 2026-06-10
**Files analyzed:** 7 new/modified files
**Analogs found:** 7 / 7

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/shadow_validator.py` | service (oneshot) | batch / request-response | `services/shadow_auditor.py` | exact |
| `services/shadow_auditor.py` | service (surgical edit) | batch / request-response | self | N/A (edit only) |
| `production/migrations/121_signal_ledger_shadow_view.sql` | migration | transform | `production/migrations/095_signal_ledger_split.sql` | role-match |
| `production/systemd/indicagent-shadow-validator.timer` | config | N/A | `production/systemd/indicagent-hmm-training.timer` | exact |
| `production/systemd/indicagent-shadow-validator.service` | config | N/A | `production/systemd/indicagent-hmm-training.service` | exact |
| `src/observability/metrics.py` | utility (surgical edit) | N/A | self (shadow metrics block, lines 263-280) | exact |
| `production/grafana/dashboards/shadow-validation.json` | config | N/A | `production/grafana/dashboards/operations.json` | role-match |

---

## Pattern Assignments

### `services/shadow_validator.py` (service, oneshot/batch)

**Analog:** `services/shadow_auditor.py` (entire file - copy structure verbatim)

**Imports pattern** (`services/shadow_auditor.py` lines 1-37):
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
    # ... shadow_validation_* metrics imported here
    flush_and_shutdown_metrics,
)

logger = structlog.get_logger(__name__)
```

Critical notes:
- `import _path_bootstrap` MUST be the first non-stdlib import (before `asyncpg`, `structlog`, `src.*`)
- Add `from scipy.stats import binomtest` either top-level or inside the gate function
- Add `from src.core.kafka_utils import KafkaProducerClient` for alert publishing
- Add `from src.core.stream_keys import topic_alert_requests`

**Entry point pattern** (`services/shadow_auditor.py` lines 336-358):
```python
async def _amain() -> None:
    settings = Settings()
    pool = await create_db_pool(settings.database_url, min_size=2, max_size=5)
    try:
        await _run_validator(pool, settings)
    finally:
        await pool.close()


def main() -> None:
    """Run the shadow validator once and emit a completion counter before exit."""
    try:
        asyncio.run(_amain())
        JOB_COMPLETED_TOTAL.add(1, {"job": "shadow-validator", "status": "success"})
    except Exception as error:
        JOB_COMPLETED_TOTAL.add(1, {"job": "shadow-validator", "status": "failure"})
        raise error
    finally:
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    main()
```

Note: job label is `"shadow-validator"` (matches systemd unit `%n` suffix per CLAUDE.md D-06).

**DB query pattern** (`services/shadow_auditor.py` lines 121-132, adapted for shadow_validator):
```python
async with pool.acquire() as conn:
    row = await conn.fetchrow(
        """
        SELECT
          COUNT(*) FILTER (WHERE was_selected = true) AS selected,
          COUNT(*) AS total,
          AVG(so.pnl_r) FILTER (WHERE so.pnl_r IS NOT NULL) AS avg_pnl_r,
          CORR(sl.cis_score, sl.was_selected::int) AS calibration_corr
        FROM signal_ledger sl
        LEFT JOIN signal_outcomes so USING (signal_id)
        WHERE sl.setup_plugin = $1
          AND sl.is_shadow = true
          AND sl.shadow_tracking_start_ts IS NOT NULL
        """,
        plugin_name,
    )
```

**Promotion write pattern** (`services/shadow_auditor.py` lines 224-248, adapted):
```python
async with pool.acquire() as conn:
    await conn.execute(
        """
        UPDATE shadow_registry
        SET is_shadow=FALSE, promoted_at=$1, demotion_consecutive_count=0
        WHERE component_name=$2
        """,
        datetime.now(UTC),
        plugin_name,
    )
    await conn.execute(
        """
        INSERT INTO shadow_transition_log
          (component_name, component_type, from_state, to_state,
           trigger_reason, n, ev_r, ci_lower, win_rate)
        VALUES ($1, $2, 'shadow', 'live', 'shadow_validator_5gate', $3, $4, $5, $6)
        """,
        plugin_name,
        "i7_plugin",
        total,
        avg_pnl_r,         # stored in ev_r column
        calibration_corr,  # stored in ci_lower column (schema reuse — no calibration_corr column exists)
        selection_rate,    # stored in win_rate column (schema reuse)
    )
```

**OTel emit pattern** (`services/shadow_auditor.py` lines 177-203, adapted):
```python
# Point gauges use .set() — emit for ALL 21 setups on every run
SHADOW_VALIDATION_N.set(total, {"setup_plugin": plugin_name})
SHADOW_VALIDATION_SELECTION_RATE.set(round(selection_rate, 4), {"setup_plugin": plugin_name})
SHADOW_VALIDATION_P_VALUE.set(round(pvalue, 4), {"setup_plugin": plugin_name})
SHADOW_VALIDATION_AVG_PNL_R.set(round(avg_pnl_r or 0.0, 4), {"setup_plugin": plugin_name})
SHADOW_VALIDATION_CALIBRATION.set(round(calibration_corr or 0.0, 4), {"setup_plugin": plugin_name})
SHADOW_VALIDATION_PROMOTED.set(1 if promoted else 0, {"setup_plugin": plugin_name})
```

**Kafka alert pattern** (from `services/alert_monitor.py` lines 70-72 — payload must use `"message"` key, not `"title"`/`"body"`):
```python
# CRITICAL: alert_monitor reads payload.get("message", ""), NOT "title" or "body"
# D-07 in CONTEXT.md shows wrong keys — use "message" per alert_monitor.py line 71
await producer.publish(
    topic_alert_requests(settings.env_name),
    {
        "severity": "CRITICAL",
        "message": (
            f"Shadow Promotion: {plugin_name}\n"
            f"N={total}, selection_rate={selection_rate:.1%}, p={pvalue:.3f}, "
            f"avg_pnl_r={avg_pnl_r:.3f}, calibration={calibration_corr:.3f}"
        ),
        "source": "shadow_validator",
    },
)
```

**Kafka producer lifecycle** (from `services/service_auditor.py` lines 279-284):
```python
producer = KafkaProducerClient(
    bootstrap_servers=settings.kafka_bootstrap_servers,
)
await producer.start()
# ... use producer.publish(topic, msg_dict) ...
# no explicit stop needed in oneshot (process exits)
```

**Error handling pattern** (`services/shadow_auditor.py` lines 172-175):
```python
try:
    # ... DB or Kafka call ...
except Exception as error:
    logger.warning("shadow_validator.kafka_unavailable", error=str(error))
    # Kafka optional — log prominently and continue (D-07)
```

**Structlog pattern** (established project convention):
```python
# Use keyword args, avoid "event=" kwarg (collision with structlog reserved key)
logger.info("shadow_validator.gate_fail", plugin=name, reason=reason, value=value, threshold=threshold)
logger.info("shadow_validator.promoted", plugin=name, n=total, p=pvalue, avg_pnl_r=avg_pnl_r)
```

---

### `services/shadow_auditor.py` (surgical edit - remove promotion path)

**Analog:** self (lines 1-358 — remove promotion-only code per D-10)

**Lines to remove** (from `services/shadow_auditor.py`):

1. **Promotion-only imports** (lines 23-35) — remove these 8 imports:
   - `bootstrap_ci_lower` (line 23 — used only by `_check_promotion` and `_check_demotion`)
   - `SHADOW_DAYS_TO_GATE` (line 25)
   - `SHADOW_EV_CI_LOWER` (line 26)
   - `SHADOW_EV_R` (line 27)
   - `SHADOW_N_RESOLVED` (line 28)
   - `SHADOW_PROMOTION_READY` (line 29)
   - `SHADOW_TAIL_GATE_DB_ERROR` (line 30)
   - `SHADOW_TAIL_RISK_BLOCKED` (line 31)
   - `SHADOW_WIN_RATE` (line 32)

   CAUTION: `bootstrap_ci_lower` is also used in `_check_demotion` (line 280). Do NOT remove it from imports; remove it only if `_check_demotion` is confirmed to not use it. Verify before removing.

2. **Module-level constants** (lines 39, 45-46):
   - `_WIN_OUTCOMES` (line 39)
   - `TAIL_GATE_MIN_SKEWNESS` (line 45)
   - `TAIL_GATE_MIN_RECOVERY` (line 46)

3. **Promotion-only pure functions** (lines 54-77):
   - `_should_promote()` (lines 54-55)
   - `_tail_risk_blocks_promotion()` (lines 66-77)

4. **`_check_promotion()` entire function** (lines 113-252)

5. **Call site in `_run_audit()`** (line 106):
   - Remove: `await _check_promotion(pool, env_name, dict(row))`
   - The `if row["is_shadow"]:` branch becomes empty or is removed entirely

**After removal:** `_run_audit()` loops rows, skips `swarm_agent` type, calls `_check_demotion()` for non-shadow rows, does nothing for shadow rows (or removes the `if/else` branch entirely).

---

### `production/migrations/121_signal_ledger_shadow_view.sql` (migration)

**Analog:** `production/migrations/095_signal_ledger_split.sql` (view creation pattern)

**Full migration content:**
```sql
-- Migration 121: signal_ledger_shadow view
-- Provides a clean nameable interface for all shadow-specific queries.
-- Base: signal_ledger_full (Phase 095) which JOINs signal_ledger + signal_outcomes.

CREATE VIEW signal_ledger_shadow AS
  SELECT *
  FROM signal_ledger_full
  WHERE is_shadow = true;
```

Note: Migration 120 (`120_signal_probe_results.sql`) is already deployed. This must be numbered 121.

---

### `production/systemd/indicagent-shadow-validator.timer` (config)

**Analog:** `production/systemd/indicagent-hmm-training.timer` (lines 1-10):
```ini
[Unit]
Description=Shadow Mode Validator Timer -- weekly 5-gate promotion check

[Timer]
OnCalendar=Mon *-*-* 07:00:00 UTC
Persistent=true
Unit=indicagent-shadow-validator.service

[Install]
WantedBy=timers.target
```

Differences from analog: `OnCalendar` uses day-of-week spec (`Mon *-*-* 07:00:00 UTC`) rather than `monthly`.

---

### `production/systemd/indicagent-shadow-validator.service` (config)

**Analog:** `production/systemd/indicagent-hmm-training.service` (lines 1-18):
```ini
[Unit]
Description=IndicAgent Shadow Mode Validator -- weekly 5-gate promotion script
After=network.target indicagent-infrastructure.target
Requires=indicagent-infrastructure.target

[Service]
Type=oneshot
Restart=no
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/shadow_validator.py
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
```

`TimeoutStartSec=300` (5 min) is sufficient for a weekly script querying 21 setups. The analog uses 7200 for ML training — reduce to 300 here.

---

### `src/observability/metrics.py` (surgical edit - add 6 new gauges)

**Analog:** self (shadow metrics block, lines 263-280)

**Insert after existing `SHADOW_TAIL_GATE_DB_ERROR` block** (after line 280):
```python
# ---------------------------------------------------------------------------
# Shadow validation metrics (Phase 120)
# ---------------------------------------------------------------------------

SHADOW_VALIDATION_N = point_gauge(
    "shadow_validation_n",
    "Shadow signal count per setup (weekly validator run)",
)
SHADOW_VALIDATION_SELECTION_RATE = point_gauge(
    "shadow_validation_selection_rate",
    "Fraction of shadow signals where was_selected=true",
)
SHADOW_VALIDATION_P_VALUE = point_gauge(
    "shadow_validation_p_value",
    "Binomial test p-value (one-sided, vs 50% baseline)",
)
SHADOW_VALIDATION_AVG_PNL_R = point_gauge(
    "shadow_validation_avg_pnl_r",
    "Average pnl_r for shadow signals with resolved outcomes",
)
SHADOW_VALIDATION_CALIBRATION = point_gauge(
    "shadow_validation_calibration",
    "CORR(cis_score, was_selected::int) — confidence calibration quality",
)
SHADOW_VALIDATION_PROMOTED = point_gauge(
    "shadow_validation_promoted",
    "1=promoted to live this run, 0=still in shadow",
)
```

All use `point_gauge()` (not `gauge()` or `counter()`) — these are point-in-time absolute values per the `metrics.py` docstring.
Label key is `"setup_plugin"` (consistent with how other per-plugin metrics use `"plugin"`).

---

### `production/grafana/dashboards/shadow-validation.json` (Grafana dashboard)

**Analog:** `production/grafana/dashboards/operations.json` (structure, panel layout, Prometheus datasource uid)

**Dashboard structure pattern** (from `operations.json` lines 1-55):
```json
{
  "annotations": { "list": [] },
  "editable": true,
  "graphTooltip": 1,
  "links": [],
  "panels": [
    {
      "collapsed": false,
      "type": "row",
      "title": "Shadow Validation Status",
      ...
    },
    {
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "type": "table",
      "fieldConfig": {
        "defaults": {
          "color": { "mode": "thresholds" },
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "red", "value": null },
              { "color": "green", "value": 1 }
            ]
          }
        }
      }
    }
  ],
  "schemaVersion": 38,
  "tags": ["shadow", "validation"],
  "title": "Shadow Mode Validation",
  "uid": "shadow-validation",
  "version": 1
}
```

Key panels needed:
1. **Table panel** — columns: setup_plugin, N, selection_rate, p_value, avg_pnl_r, calibration, promoted. PromQL: `shadow_validation_n`, `shadow_validation_selection_rate`, etc., all grouped by `setup_plugin` label. Color-code `shadow_validation_promoted` column (0=red, 1=green).
2. **Time-series panel** — `shadow_validation_n` over time per setup (tracks N accumulation toward N=100 gate).
3. **Promotion events panel** — counter panel showing total promotions: `sum(shadow_validation_promoted)`.

---

### `services/service_auditor.py` (surgical edit - register new unit)

**Analog:** self (lines 57-186)

**Add to `_DAG_ORDER`** (after line 96, alongside other oneshot timer services):
```python
"indicagent-shadow-validator": 8,  # oneshot: weekly timer-triggered, promotion-only
```

**Add to `_ONESHOT_UNITS`** (after line 175, `"indicagent-shadow-auditor"`):
```python
"indicagent-shadow-validator",  # Type=oneshot, weekly Mon 07:00 UTC promotion gate
```

Note: `_AGENT_ID_TO_UNIT` does NOT need an entry for oneshot scripts — that dict maps `BaseDaemon`-derived agents to units via their `agent_id` label. `shadow_validator.py` is not a `BaseDaemon` subclass.

---

## Shared Patterns

### `_path_bootstrap` Import (all services/ scripts)
**Source:** `services/shadow_auditor.py` line 17
**Apply to:** `services/shadow_validator.py`
```python
import _path_bootstrap  # noqa: F401 — project root on sys.path
```
Must be the first import after docstring and `from __future__ import annotations`. Without this, `ImportError: No module named 'src'` when running directly.

### Oneshot Job Completion (all timer-triggered scripts)
**Source:** `services/shadow_auditor.py` lines 345-354, `src/observability/metrics.py` line 416-419
**Apply to:** `services/shadow_validator.py`
```python
# In main():
try:
    asyncio.run(_amain())
    JOB_COMPLETED_TOTAL.add(1, {"job": "shadow-validator", "status": "success"})
except Exception as error:
    JOB_COMPLETED_TOTAL.add(1, {"job": "shadow-validator", "status": "failure"})
    raise error
finally:
    flush_and_shutdown_metrics()
```
`flush_and_shutdown_metrics()` is MANDATORY for oneshot scripts — without it, OTel batches never drain before process exit.

### UTC Timestamps
**Source:** `services/shadow_auditor.py` line 140
**Apply to:** all datetime usage in `shadow_validator.py`
```python
from datetime import UTC, datetime
now = datetime.now(UTC)  # never datetime.now() or datetime.utcnow()
```

### asyncpg JSONB / No json.loads
**Source:** CLAUDE.md "asyncpg" rule
**Apply to:** `shadow_validator.py` DB queries
Pass `dict` directly to asyncpg parameters. Never call `json.dumps()` / `json.loads()` on JSONB columns. asyncpg handles the conversion natively.

### Exception Variable Naming
**Source:** CLAUDE.md "Exception variable name is `error`"
**Apply to:** all `except` blocks in `shadow_validator.py`
```python
except Exception as error:
    logger.warning("...", error=str(error))
```

---

## No Analog Found

All files have close analogs. No entries in this section.

---

## Metadata

**Analog search scope:** `services/`, `production/systemd/`, `production/grafana/dashboards/`, `src/observability/`, `production/migrations/`
**Files scanned:** 7 analog files read directly; 4 grep searches across codebase
**Pattern extraction date:** 2026-06-10

### Critical Anti-Patterns (from RESEARCH.md verification)

| Wrong Pattern | Correct Pattern | Source |
|---|---|---|
| `{"title": ..., "body": ...}` alert payload | `{"message": ..., "source": ...}` | `services/alert_monitor.py` line 71 |
| `publish(msg={"message": ...})` — kwarg only | `publish(topic, {"message": ...})` — positional topic | `services/service_auditor.py` line 400 |
| `120_signal_ledger_shadow_view.sql` | `121_signal_ledger_shadow_view.sql` | `ls production/migrations/` |
| `INSERT INTO shadow_transition_log (..., calibration_corr, ...)` | map to existing `ci_lower` column | live DB schema |
| `gauge()` for point-in-time metrics | `point_gauge()` | `src/observability/metrics.py` line 82 |
| `_AGENT_ID_TO_UNIT` entry for shadow_validator | no entry needed — not a BaseDaemon | `services/service_auditor.py` lines 132-164 |
