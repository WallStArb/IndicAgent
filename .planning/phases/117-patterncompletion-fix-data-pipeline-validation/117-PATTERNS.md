# Phase 117: PatternCompletion Fix + Data Pipeline Validation - Pattern Map

**Mapped:** 2026-06-08
**Files analyzed:** 9
**Analogs found:** 9 / 9

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/feature_writer.py` | service/writer | batch | self (3-line fix) | exact |
| `services/feature_parity_auditor.py` | oneshot auditor | request-response | `services/shadow_auditor.py` | exact |
| `services/confidence_calibration_monitor.py` | oneshot auditor | request-response | `services/shadow_auditor.py` | exact |
| `production/systemd/indicagent-feature-parity-auditor.service` | config | - | `production/systemd/indicagent-shadow-auditor.service` | exact |
| `production/systemd/indicagent-feature-parity-auditor.timer` | config | - | `production/systemd/indicagent-shadow-auditor.timer` | exact |
| `production/systemd/indicagent-confidence-calibration-monitor.service` | config | - | `production/systemd/indicagent-shadow-auditor.service` | exact |
| `production/systemd/indicagent-confidence-calibration-monitor.timer` | config | - | `production/systemd/indicagent-shadow-auditor.timer` | exact |
| `src/intelligence/plugins/base.py` | plugin protocol | - | self (additive change) | exact |
| `tools/pre-commit.hook` | config/script | - | self (additive check 9) | exact |

---

## Pattern Assignments

### `services/feature_writer.py` (3-line bug fix)

**Analog:** Self — targeted fix at lines 192-194.

**Exact lines to change** (`services/feature_writer.py` lines 192-194):
```python
# BEFORE (wrong tier-to-column mapping):
event.i3.model_dump(exclude_none=True),  # $10 pattern_detections
event.i4.model_dump(exclude_none=True),  # $11 regime_features
event.i5.model_dump(exclude_none=True),  # $12 confluence_scores

# AFTER (correct):
event.i5.model_dump(exclude_none=True),  # $10 pattern_detections (I5Patterns: dt_db_confidence, hs_*, tri_*)
event.i3.model_dump(exclude_none=True),  # $11 regime_features (I3Structure: swing, S/R, trend, session levels)
event.i4.model_dump(exclude_none=True),  # $12 confluence_scores (I4Context: GARCH, Kalman, AVWAP, VP, SessionCtx)
```

Context: the tuple is 32 elements built in `_record_to_insert_params()` starting at line 166. The SQL positions $10/$11/$12 map to column names `pattern_detections`, `regime_features`, `confluence_scores` (declared in `_INSERT_FEATURE_SQL` lines 63-97). The three arguments are at positions 9, 10, 11 (0-indexed) in the return tuple.

---

### `services/feature_parity_auditor.py` (new oneshot service)

**Analog:** `services/shadow_auditor.py`

**Imports pattern** (`shadow_auditor.py` lines 11-37):
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

logger = structlog.get_logger(__name__)
```

**Module-level OTel metrics pattern** (`bar_auditor.py` lines 78-80, adapted):
```python
# In feature_parity_auditor.py — module-level, mirrors bar_auditor pattern
from opentelemetry import metrics as _otel_metrics
_meter = _otel_metrics.get_meter("indicagent")

FEATURE_PARITY_NULL_FIELDS = _meter.create_gauge(
    "feature_parity_null_fields_total",
    description="Count of I5 pattern fields with 100% NULL in last 1 hour",
)
FEATURE_PARITY_AUDITS_RUN = _meter.create_counter(
    "feature_parity_audits_run_total",
    description="Total feature parity audit runs",
)
```

Note: `_meter.create_gauge()` is the correct call for point-in-time values (uses `.set()`). See `src/observability/metrics.py` line 82-84 for the `point_gauge()` helper that wraps this same call.

**Entry point pattern** (`shadow_auditor.py` lines 336-358):
```python
async def _amain() -> None:
    settings = Settings()
    pool = await create_db_pool(settings.database_url, min_size=2, max_size=5)
    try:
        await _run_audit(pool, settings.env_name)
    finally:
        await pool.close()


def main() -> None:
    """Run the feature parity auditor once and emit a completion counter before exit."""
    try:
        asyncio.run(_amain())
        JOB_COMPLETED_TOTAL.add(1, {"job": "feature-parity-auditor", "status": "success"})
    except Exception as error:
        JOB_COMPLETED_TOTAL.add(1, {"job": "feature-parity-auditor", "status": "failure"})
        raise error
    finally:
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    main()
```

**D-06 label constraint:** The `job` label value `"feature-parity-auditor"` must match the systemd unit suffix exactly (kebab-case suffix of `indicagent-feature-parity-auditor.timer`).

**Core asyncpg audit query pattern** (`shadow_auditor.py` lines 87-93 adapted for JSONB key check):
```python
async def _run_audit(pool: asyncpg.Pool, env_name: str) -> None:
    expected_fields = ["dt_db_confidence", "hs_confidence", "tri_confidence"]
    violations: list[str] = []

    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM intelligence_features WHERE ts >= NOW() - INTERVAL '1 hour'"
        )
        if total == 0:
            logger.warning("feature_parity_audit.no_recent_rows")
            return

        for field in expected_fields:
            count = await conn.fetchval(
                "SELECT COUNT(*) FILTER (WHERE pattern_detections ? $1) "
                "FROM intelligence_features WHERE ts >= NOW() - INTERVAL '1 hour'",
                field,
            )
            if count == 0:
                violations.append(field)

    FEATURE_PARITY_NULL_FIELDS.set(len(violations), {})
    FEATURE_PARITY_AUDITS_RUN.add(1, {})

    if violations:
        logger.error("feature_parity_audit.violations_found", fields=violations, total_rows=total)
    else:
        logger.info("feature_parity_audit.clean", fields_checked=len(expected_fields), rows=total)
```

**Key detail:** Query is bounded to `ts >= NOW() - INTERVAL '1 hour'`. The `ts` column is the primary key time dimension for TimescaleDB partitioning — time-bounded queries use chunk exclusion and are fast. All-time queries on 2.7M+ rows are too slow for a 5-minute timer.

**Exception variable name convention** (CLAUDE.md rule): always `except X as error:`, not `exc`.

---

### `services/confidence_calibration_monitor.py` (new oneshot service)

**Analog:** `services/shadow_auditor.py`

**Imports and entry point pattern:** Identical structure to `feature_parity_auditor.py` above. Change `job=` label to `"confidence-calibration-monitor"` (must match timer unit suffix).

**Core asyncpg query pattern** (asyncpg `.fetch()` returning rows):
```python
async def _run_audit(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                setup_plugin,
                CORR(cis_score, was_selected::int)::float AS calibration,
                COUNT(*) AS n
            FROM signal_ledger
            WHERE timestamp >= NOW() - INTERVAL '7 days'
              AND NOT is_shadow
              AND cis_score IS NOT NULL
            GROUP BY setup_plugin
            HAVING COUNT(*) >= 100
            ORDER BY calibration ASC
            """,
        )

    for row in rows:
        plugin = row["setup_plugin"]
        calibration = row["calibration"]
        n = row["n"]
        # asyncpg returns dicts; no json.loads() needed
        logger.info(
            "confidence_calibration.result",
            plugin=plugin,
            calibration=round(calibration, 4) if calibration is not None else None,
            n=n,
        )
```

**Framing constraint (from RESEARCH.md):** The correlation measures aggregator-selection predictiveness, not profitability. Log messages and alerts must use "confidence not predictive of aggregator selection" framing, not "not predictive of profitability."

---

### `production/systemd/indicagent-feature-parity-auditor.service` (new systemd unit)

**Analog:** `production/systemd/indicagent-shadow-auditor.service` (lines 1-14, full file):
```ini
[Unit]
Description=IndicAgent Shadow Governance Auditor
After=network.target indicagent-infrastructure.target
Requires=indicagent-infrastructure.target

[Service]
Type=oneshot
WorkingDirectory=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/shadow_auditor.py
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

**Adapt to:**
```ini
[Unit]
Description=IndicAgent Feature Parity Auditor
After=network.target indicagent-infrastructure.target
Requires=indicagent-infrastructure.target

[Service]
Type=oneshot
WorkingDirectory=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/feature_parity_auditor.py
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

---

### `production/systemd/indicagent-feature-parity-auditor.timer` (new systemd timer)

**Analog:** `production/systemd/indicagent-shadow-auditor.timer` (lines 1-10, full file):
```ini
[Unit]
Description=Shadow Governance Auditor Timer — every 30 minutes

[Timer]
OnCalendar=*:0/30
Persistent=true
Unit=indicagent-shadow-auditor.service

[Install]
WantedBy=timers.target
```

**Adapt to (5-minute interval):**
```ini
[Unit]
Description=Feature Parity Auditor Timer — every 5 minutes

[Timer]
OnCalendar=*:0/5
Persistent=true
Unit=indicagent-feature-parity-auditor.service

[Install]
WantedBy=timers.target
```

---

### `production/systemd/indicagent-confidence-calibration-monitor.service` and `.timer`

**Analog:** Same shadow-auditor pair as above. Adapt `Description` and `ExecStart` path. Timer interval: decision for planner (RESEARCH.md suggests same 5-minute interval as feature parity auditor, but calibration monitor queries 7 days so less urgency — every 30 minutes is reasonable).

---

### `src/intelligence/plugins/base.py` (additive change to PatternPlugin Protocol)

**Analog:** Self — additive `ClassVar` attribute following the existing `_state_migration_complete` and `fast_path` pattern.

**Existing ClassVar pattern to follow** (`src/intelligence/plugins/base.py` lines 51-58):
```python
# PERF-03 migration flag: True when plugin has been audited and confirmed to
# correctly use the state= parameter in compute_next() (not cold-starting every bar).
# PluginExecutor.__init__ raises RuntimeError if any supports_incremental=True plugin
# has this set to False. All 34 incremental plugins must set this to True.
_state_migration_complete: ClassVar[bool]
# fast_path flag: True when plugin meets fast-path execution criteria:
# supports_incremental=False AND P99 latency < 100µs (verified from 24h histogram).
# fast_path execution branch ships in Plan 05. Here only the attribute is added.
fast_path: ClassVar[bool]
```

**Addition to PatternPlugin Protocol** (insert after `fast_path: ClassVar[bool]` at line 58):
```python
# I6 confluence requirement: True (default) if this I7 plugin consumes at least one
# ctf_* sub-score from frames["i6"]. Set to False only with explicit documented rationale.
# Enforcement: pytest test in tests/unit/intelligence/test_i6_confluence_enforcement.py
# sweeps all TIER_I7 plugins and asserts this attribute is declared.
requires_i6_confluence: ClassVar[bool]
```

**ArchitectureViolation exception** (add at top of file, before `InputSpec` dataclass):
```python
class ArchitectureViolation(Exception):
    """Raised when a plugin violates a mandatory architectural constraint.

    Raised at startup (in PluginExecutor.__init__) when a registered I7 plugin
    is missing a required class attribute (e.g., requires_i6_confluence).
    Never raised per-bar — architecture validation is startup-time, not hot-path.
    """
```

**Existing `validate_tier()` I7 enforcement pattern** (`base.py` lines 113-131) shows where to add `requires_i6_confluence` validation:
```python
# I7 regime_type validation (existing, lines 114-131)
if tier == "I7":
    valid_regimes = {"trend", "mean_reversion", "any"}
    for name in names:
        plugin = self.patterns.get(name)
        if plugin is None:
            continue
        if not hasattr(plugin, "regime_type"):
            raise ValueError(
                f"I7 plugin '{name}' missing regime_type declaration. ..."
            )
        regime = plugin.regime_type
        if regime not in valid_regimes:
            raise ValueError(...)
```

Follow the same `hasattr` guard pattern to add `requires_i6_confluence` validation in the same `if tier == "I7":` block.

---

### `tools/pre-commit.hook` (additive check 9)

**Analog:** Self — follow check 3 (`check_regime_type_declaration`) structure exactly.

**Check 3 pattern to copy** (`tools/pre-commit.hook` lines 118-155):
```bash
check_regime_type_declaration() {
    echo "[3/8] I7 regime_type check..."

    I7_FILES=$(git diff --cached --name-only --diff-filter=ACM | \
        grep -E '^src/intelligence/trading/[a-z][a-z0-9_]*\.py$' | \
        grep -vE '(signal_ledger|lifecycle_tracker|trade_framer|signal_aggregator|cis_scorer|weight_updater|confidence_calibrator|__init__)\.py$' || true)

    if [ -z "$I7_FILES" ]; then
        echo "  OK No I7 trading plugins changed"
        return 0
    fi

    FAILURES_LOCAL=0
    for file in $I7_FILES; do
        if [ -f "${REPO_ROOT}/${file}" ]; then
            if ! grep -q '^class.*Plugin' "${REPO_ROOT}/${file}" 2>/dev/null; then
                continue
            fi
            if ! grep -qE 'regime_type\s*[:=]' "${REPO_ROOT}/${file}"; then
                echo "  FAILED: I7 plugin missing regime_type declaration"
                echo "    File: ${file}"
                FAILURES_LOCAL=$((FAILURES_LOCAL + 1))
            fi
        fi
    done

    if [ $FAILURES_LOCAL -gt 0 ]; then
        return 1
    fi

    echo "  OK All I7 plugins declare regime_type"
    return 0
}
```

**Check 9 adapts to:**
- Function name: `check_i6_confluence_declaration`
- Echo prefix: `[9/9]`
- Same I7 file filter (same exclusion list, extended by `plugin_utils|atr_utils|state_utils|confidence_utils|microstructure_utils|volume_profile_utils|exhaustion_utils|signal_schema`)
- Grep pattern: `requires_i6_confluence\s*[:=]`
- Error message: `"I7 plugin missing requires_i6_confluence declaration"`

**Run-all block** (lines 402-409, add one line):
```bash
check_i6_confluence_declaration || FAILURES=$((FAILURES + 1))
```

Also update the header comment count from `[8/8]` to `[9/9]` in the header and in all existing check echo lines, and update the `Checks:` list comment at the top.

---

## Shared Patterns

### asyncpg pool acquisition
**Source:** `services/shadow_auditor.py` lines 87-93, 121-123
**Apply to:** `feature_parity_auditor.py`, `confidence_calibration_monitor.py`
```python
# Always use context manager — pool.acquire() is async context manager
async with pool.acquire() as conn:
    rows = await conn.fetch("SELECT ...", param1, param2)
    # asyncpg returns asyncpg.Record — access by column name: row["col"]
    # JSONB columns return dict directly — no json.loads() needed
    # Timestamps return datetime — no manual parsing
```

### OTel metrics call convention
**Source:** `src/observability/metrics.py` lines 72-84, `services/shadow_auditor.py` lines 178-202
**Apply to:** all new oneshot services
```python
# Counters: .add(1, {"label_key": value})
FEATURE_PARITY_AUDITS_RUN.add(1, {})

# Point gauges (create_gauge): .set(value, {"label_key": value})
FEATURE_PARITY_NULL_FIELDS.set(len(violations), {})

# Histograms: .record(value, {"label_key": value})
# Up-down counters: .add(delta, {"label_key": value})
# Never import prometheus_client
```

### Settings + DB pool initialization
**Source:** `services/shadow_auditor.py` lines 336-342
**Apply to:** all new oneshot services
```python
async def _amain() -> None:
    settings = Settings()
    pool = await create_db_pool(settings.database_url, min_size=2, max_size=5)
    try:
        await _run_audit(pool, settings.env_name)
    finally:
        await pool.close()
```

### JOB_COMPLETED_TOTAL + flush_and_shutdown_metrics
**Source:** `services/shadow_auditor.py` lines 345-358, `src/observability/metrics.py` lines 381-384
**Apply to:** all new oneshot services (D-06 mandatory)
```python
def main() -> None:
    try:
        asyncio.run(_amain())
        JOB_COMPLETED_TOTAL.add(1, {"job": "job-name-matching-unit-suffix", "status": "success"})
    except Exception as error:
        JOB_COMPLETED_TOTAL.add(1, {"job": "job-name-matching-unit-suffix", "status": "failure"})
        raise error
    finally:
        flush_and_shutdown_metrics()
```

---

## No Analog Found

All files have strong codebase analogs. No entries needed here.

---

## Metadata

**Analog search scope:** `services/`, `production/systemd/`, `src/intelligence/plugins/`, `tools/`, `src/observability/`
**Files scanned:** 7 (shadow_auditor.py, feature_writer.py, bar_auditor.py, base.py, pre-commit.hook, metrics.py, indicagent-shadow-auditor.{service,timer})
**Pattern extraction date:** 2026-06-08
