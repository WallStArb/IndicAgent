# Phase 117: PatternCompletion Fix + Data Pipeline Validation - Research

**Researched:** 2026-06-08
**Domain:** Intelligence pipeline write-path, feature persistence, auditor services, I7 base class enforcement
**Confidence:** HIGH

## Summary

Phase 117 has four deliverables across three waves: (1) fix the `feature_writer.py` tier-to-column mapping bug that sends I5 pattern data to the wrong JSONB column, (2) build a `FeatureParityAuditor` that detects this class of bug going forward, (3) build a `ConfidenceCalibrationMonitor` that tracks whether per-setup confidence scores predict selection, and (4) add `ArchitectureViolation` enforcement on the `PatternPlugin` protocol to ensure all I7 plugins provide I6 confluence.

The write-path bug is fully diagnosed. The auditor/monitor pattern is well-established in the codebase. The I6 enforcement is the most design-sensitive piece and requires adding a new class attribute to the `PatternPlugin` Protocol.

**Primary recommendation:** Fix the column-mapping bug in `_record_to_insert_params` first (Wave 1). The FeatureParityAuditor is the regression guard for that fix. The ConfidenceCalibrationMonitor and I6 enforcement are independent and can proceed in Wave 2 / Wave 3.

## Standard Stack

### Core
| Component | Location | Purpose | Notes |
|-----------|----------|---------|-------|
| `BaseDaemon` | `src/core/agent/base.py` | Base for all daemons | All 5 OTel signals inherited automatically |
| `asyncpg` | via `src/core/database_manager.py` | DB pool + queries | `create_pool()` returns pool; JSONB as `dict`, not `json.loads()` |
| `DatabaseManager` | `src/core/database_manager.py` | DB pool wrapper | `initialize()` + `execute_batch()` |
| `point_gauge`, `counter` | `src/observability/metrics.py` | OTel metrics | `_meter.create_gauge()` for new instruments |
| `JOB_COMPLETED_TOTAL` | `src/observability/metrics.py` | Oneshot job completion | Required for timer-triggered oneshots (D-06) |
| `flush_and_shutdown_metrics` | `src/observability/metrics.py` | Flush before exit | Required at end of oneshot scripts |
| `stream_keys.py` | `src/core/stream_keys.py` | All topic keys | No hardcoded strings anywhere |
| `setup_service_logging` | `src/core/service_utils.py` | Structured logging | Requires full path: `"logs/<name>.log"` |

### Supporting
| Component | Version/Location | Purpose | When to Use |
|-----------|-----------------|---------|-------------|
| `shadow_auditor.py` | `services/shadow_auditor.py` | Oneshot pattern | Reference for timer-triggered oneshot with OTel |
| `bar_auditor.py` | `services/bar_auditor.py` | 5-min audit daemon | Reference for daemon with sleep-loop audit pattern |
| Systemd timer pair | `production/systemd/` | Schedule oneshot | `.timer` + `.service` (Type=oneshot) |

### Installation
No new packages required. All dependencies are in existing `requirements.txt`.

## Architecture Patterns

### Recommended Project Structure for New Files
```
services/
├── feature_parity_auditor.py    # FeatureParityAuditor — timer-triggered oneshot
├── confidence_calibration_monitor.py  # ConfidenceCalibrationMonitor — timer-triggered oneshot
production/systemd/
├── indicagent-feature-parity-auditor.service
├── indicagent-feature-parity-auditor.timer
├── indicagent-confidence-calibration.service
├── indicagent-confidence-calibration.timer
src/core/stream_keys.py          # Add topic_feature_parity_alerts, topic_confidence_calibration
src/intelligence/plugins/base.py  # Add requires_i6_confluence ClassVar + ArchitectureViolation
tools/pre-commit.hook             # Add check 9: I6 confluence enforcement
```

### Pattern 1: The Feature Writer Column Mapping Bug

**What is wrong:** In `services/feature_writer.py`, `_record_to_insert_params()` lines 192-194:
```python
event.i3.model_dump(exclude_none=True),  # $10 pattern_detections  ← WRONG: I3 is structure
event.i4.model_dump(exclude_none=True),  # $11 regime_features      ← WRONG: I4 is context
event.i5.model_dump(exclude_none=True),  # $12 confluence_scores    ← WRONG: I5 is patterns
```

**Verified by DB query (2026-06-08):**
- `pattern_detections` contains `swing_high`, `nearest_resistance` etc. (I3 Structure fields)
- `confluence_scores` contains `dt_db_confidence`, `hs_confidence`, `tri_confidence` (I5 Pattern fields)
- `regime_features` contains `in_ny_killzone`, `session_london`, `avwap_upper_band` (I4 Context fields)

**The correct mapping** (verified against column names and tier class docs):
```
$10 pattern_detections  ← event.i5  (I5Patterns — dt_db_confidence, hs_confidence, tri_confidence)
$11 regime_features     ← event.i3  (I3Structure — swing, S/R, trend structure, session levels)
$12 confluence_scores   ← event.i4  (I4Context — GARCH, Kalman, SessionContext, VWAP, VP)
```

**The fix is 3 lines:** Swap the three arguments in `_record_to_insert_params`. The schema declaration comment for each column also needs updating.

**Why PatternCompletion fires on phantom data:** `trad_PatternCompletion` reads `features.get("dt_db_confidence")` from `frames.get("i5")` (in-process dict). The in-process value is correct — I5 plugins compute real values. But when `FeatureWriter` persists the record, it writes I5 data to `confluence_scores`, not `pattern_detections`. The `FeatureParityAuditor` queries `pattern_detections ? 'dt_db_confidence'` and finds zero rows — confirming the bug. The signal FIRES correctly in-process, but the DB record shows a column that looks empty, causing the auditor to report it as a pipeline failure.

**Note on signal volume:** The 795K phantom signals cited in root-cause analysis are real signals (pattern values are present in-process). The "phantom data" interpretation was from querying the wrong column. The actual problem is the column data is queryable from the wrong column name, preventing downstream analytics and the FeatureParityAuditor from working correctly.

### Pattern 2: Timer-Triggered Oneshot (for FeatureParityAuditor and ConfidenceCalibrationMonitor)

Both auditors should be timer-triggered oneshots, not daemons. Reference: `services/shadow_auditor.py`.

```python
# services/feature_parity_auditor.py
async def main() -> None:
    pool = await create_db_pool(settings.postgres_dsn)
    try:
        await run_audit(pool)
        JOB_COMPLETED_TOTAL.add(1, {"job": "feature-parity-auditor", "status": "success"})
    except Exception as error:
        JOB_COMPLETED_TOTAL.add(1, {"job": "feature-parity-auditor", "status": "failure"})
        raise
    finally:
        flush_and_shutdown_metrics()
        await pool.close()
```

Systemd service file (`Type=oneshot`):
```ini
[Service]
Type=oneshot
WorkingDirectory=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/feature_parity_auditor.py
Environment=PYTHONUNBUFFERED=1
```

Timer file (every 5 minutes):
```ini
[Timer]
OnCalendar=*:0/5
Persistent=true
Unit=indicagent-feature-parity-auditor.service
```

### Pattern 3: FeatureParityAuditor — Audit Query Pattern

The auditor must query `intelligence_features` using the **correct** column names after the fix is deployed.

```python
# After fix: pattern_detections contains I5 pattern data
async def audit_i5_patterns(pool) -> list[str]:
    """Returns list of missing fields (empty = healthy)."""
    expected_fields = ["dt_db_confidence", "hs_confidence", "tri_confidence"]
    violations = []
    async with pool.acquire() as conn:
        for field in expected_fields:
            count = await conn.fetchval(
                """
                SELECT COUNT(*) FILTER (WHERE pattern_detections ? $1)
                FROM intelligence_features
                WHERE ts >= NOW() - INTERVAL '1 hour'
                """,
                field
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM intelligence_features WHERE ts >= NOW() - INTERVAL '1 hour'"
            )
            if total > 0 and count == 0:
                violations.append(field)
    return violations
```

**Key detail:** Query the last 1 hour, not all-time. All-time queries on 2.7M rows are too slow for a 5-minute timer.

### Pattern 4: ConfidenceCalibrationMonitor — SQL Pattern

Signal confidence is in `cis_score` (not a dedicated `confidence` column). `was_selected` is a boolean column on `signal_ledger`.

```sql
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
ORDER BY calibration ASC;
```

**Important nuance from root-cause analysis Council Review (Problem 1):** The correlation between `cis_score` and `was_selected` is CIRCULAR — `was_selected` is determined by the aggregator which is weighted on `cis_score`. The monitor still has value (low correlation = even the aggregator isn't using this setup's score predictively), but alerts must be framed correctly: "confidence not predictive of aggregator selection" not "confidence not predictive of profitability."

### Pattern 5: PatternPlugin ArchitectureViolation Enforcement

The `PatternPlugin` class in `src/intelligence/plugins/base.py` is a Protocol. Adding enforcement requires a class attribute and a validation in `compute_full`.

**Current state:** `PatternPlugin` has `regime_type: ClassVar[str]` but no I6 enforcement.

**Proposed addition:**
```python
class PatternPlugin(Protocol):
    # ... existing attributes ...
    requires_i6_confluence: ClassVar[bool]  # Add — default True for all I7 plugins
```

**Enforcement location:** Not in the Protocol itself (Protocols don't run methods). Enforcement goes in the `PluginExecutor` at call time, or in a pytest CI gate that inspects all registered I7 plugins.

**Recommended approach (from root-cause analysis Council Review, Problem 4):** Do NOT enforce a minimum factor count at the base class level (cargo-cult architecture, easily gamed). DO enforce I6 presence. The enforcement should:
1. Add `requires_i6_confluence: ClassVar[bool] = True` to `PatternPlugin` Protocol
2. Add a CI test (`tests/unit/intelligence/test_i6_confluence_enforcement.py`) that iterates all registered I7 plugins and asserts `requires_i6_confluence` is declared
3. Add check 9 to `tools/pre-commit.hook` that scans new I7 files for `requires_i6_confluence`

**ArchitectureViolation exception:** Define in `src/intelligence/plugins/base.py`:
```python
class ArchitectureViolation(Exception):
    """Raised when a plugin violates a mandatory architectural constraint."""
```

The `PluginExecutor` should catch `ArchitectureViolation` in its call wrapper and route to DLQ (not crash the pipeline). New I7 plugins that don't provide `ctf_score` to `frames.get("i6")` would raise this.

### Anti-Patterns to Avoid
- **Querying all-time data in 5-min timer audits** — use `WHERE ts >= NOW() - INTERVAL '1 hour'` always
- **Using `json.dumps()`/`json.loads()` with asyncpg** — asyncpg handles JSONB natively; pass dicts directly
- **Framing calibration correlation as profitability signal** — it measures aggregator-selection predictiveness, not edge
- **Enforcing factor count in base class** — arbitrary, easily gamed with dummy factors
- **Creating new Kafka topics for audit results without named producer-consumer pair** — alerts go via existing `topic_alert_requests`

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DB connection pool | Custom pool | `create_db_pool` from `database_manager.py` | Already handles retry, settings |
| OTel metrics | Raw OTel setup | `counter()`, `point_gauge()` from `metrics.py` | Module-level singleton, dedup |
| Service logging | `logging.basicConfig` | `setup_service_logging("logs/name.log")` | Structured JSON, rotation |
| Alerting | Custom Telegram/email | `topic_alert_requests` + existing `AlertingAgent` | Already wired to Telegram |
| Timer scheduling | `asyncio.sleep` daemon | Systemd `.timer` unit | Cleaner, persistent, observable |

## Common Pitfalls

### Pitfall 1: Column Remapping Doesn't Apply Retroactively
**What goes wrong:** Fixing the column mapping in `feature_writer.py` only affects new bars going forward. Existing 2.7M rows in `intelligence_features` have the wrong column assignments.
**Why it happens:** The fix is a write-path correction, not a data migration.
**How to avoid:** The `FeatureParityAuditor` must query the last 1 hour (not historical data) so it validates the current pipeline state. Historical data is pre-fix contamination and cannot be trusted.
**Warning signs:** Auditor reports violations on `ts < deploy_time` — expected. Violations on `ts >= deploy_time` — new bug.

### Pitfall 2: PatternCompletion In-Process vs DB Discrepancy
**What goes wrong:** After the fix, `dt_db_confidence` et al. appear in `pattern_detections` in DB, but `trad_PatternCompletion` reads from `frames.get("i5")` (in-process dict), not from DB. The in-process dict was never broken.
**Why it happens:** The write-path bug only affected DB persistence; in-process signal generation was always reading correct values from `frames["i5"]`.
**How to avoid:** Understand that the fix primarily enables: (1) the `FeatureParityAuditor` to work correctly, (2) analytics queries on `pattern_detections` column to return correct data, (3) future I7 plugins that read from DB to get correct values.

### Pitfall 3: ArchitectureViolation Crashes Pipeline
**What goes wrong:** If `ArchitectureViolation` is raised inside `compute_full()`, and the `PluginExecutor` doesn't catch it, the entire intelligence pipeline crashes.
**Why it happens:** `PluginExecutor` catches `Exception` for known plugin errors but may not specifically handle new exception types.
**How to avoid:** Either catch `ArchitectureViolation` in `PluginExecutor._timed_plugin_call()` and route to DLQ, OR raise it only at startup/registration time (not per-bar). The CI gate approach (pytest test + pre-commit hook) is safer: detect violations at code review time, not at runtime.

### Pitfall 4: `JOB_COMPLETED_TOTAL` Label Key
**What goes wrong:** Oneshot exits without emitting `JOB_COMPLETED_TOTAL` or uses wrong label key.
**Why it happens:** D-06 contract requires `{job, status}` labels where `job` matches the systemd unit `%n` suffix exactly (kebab-case).
**How to avoid:** `job="feature-parity-auditor"` must match `indicagent-feature-parity-auditor.timer` suffix.

### Pitfall 5: 5-Minute Timer on Slow Query
**What goes wrong:** Auditor runs every 5 minutes but query takes >5 minutes on large tables.
**Why it happens:** `intelligence_features` has 2.7M rows; full table scans are slow.
**How to avoid:** Always add `WHERE ts >= NOW() - INTERVAL '1 hour'`. The `ts` column is the primary key time dimension for TimescaleDB partitioning; time-bounded queries use chunk exclusion and are fast.

## Code Examples

### Fix: _record_to_insert_params (3 lines changed)
```python
# services/feature_writer.py — _record_to_insert_params()
# BEFORE (wrong):
event.i3.model_dump(exclude_none=True),  # $10 pattern_detections
event.i4.model_dump(exclude_none=True),  # $11 regime_features
event.i5.model_dump(exclude_none=True),  # $12 confluence_scores

# AFTER (correct):
event.i5.model_dump(exclude_none=True),  # $10 pattern_detections (I5Patterns: dt_db_confidence, hs_*, tri_*)
event.i3.model_dump(exclude_none=True),  # $11 regime_features (I3Structure: swing, S/R, trend, session levels)
event.i4.model_dump(exclude_none=True),  # $12 confluence_scores (I4Context: GARCH, Kalman, AVWAP, VP, SessionCtx)
```

### FeatureParityAuditor DB query pattern
```python
# asyncpg — JSONB key existence check
count = await conn.fetchval(
    "SELECT COUNT(*) FILTER (WHERE pattern_detections ? $1) FROM intelligence_features "
    "WHERE ts >= NOW() - INTERVAL '1 hour'",
    "dt_db_confidence"
)
# count == 0 AND total > 0 → alert
```

### ConfidenceCalibrationMonitor query
```python
# asyncpg — CORR() with NULL-safe filter
rows = await conn.fetch(
    """
    SELECT setup_plugin,
           CORR(cis_score, was_selected::int)::float AS calibration,
           COUNT(*) AS n
    FROM signal_ledger
    WHERE timestamp >= NOW() - INTERVAL '7 days'
      AND NOT is_shadow
      AND cis_score IS NOT NULL
    GROUP BY setup_plugin
    HAVING COUNT(*) >= 100
    """,
)
```

### ArchitectureViolation in plugins/base.py
```python
class ArchitectureViolation(Exception):
    """Raised when a plugin violates a mandatory architectural constraint.
    
    Raised at startup (in PluginExecutor.__init__) when a registered I7 plugin
    is missing a required class attribute (e.g., requires_i6_confluence).
    Never raised per-bar — architecture validation is startup-time, not hot-path.
    """

class PatternPlugin(Protocol):
    # ... existing attrs ...
    requires_i6_confluence: ClassVar[bool]
    """Must be True for all I7 plugins (default) or explicitly False with documented rationale."""
```

### Pre-commit hook addition (check 9)
```bash
# In tools/pre-commit.hook — new check function
check_i6_confluence_declaration() {
    echo "[9/9] I6 confluence requirement check..."
    I7_FILES=$(git diff --cached --name-only --diff-filter=ACM | \
        grep -E '^src/intelligence/trading/[a-z][a-z0-9_]*\.py$' | \
        grep -vE '(signal_ledger|lifecycle_tracker|trade_framer|signal_aggregator|cis_scorer|weight_updater|confidence_calibrator|__init__|plugin_utils|atr_utils|state_utils|confidence_utils|microstructure_utils|volume_profile_utils|exhaustion_utils|signal_schema)\.py$' || true)
    
    for file in $I7_FILES; do
        if grep -q '^class.*Plugin' "${REPO_ROOT}/${file}" 2>/dev/null; then
            if ! grep -qE 'requires_i6_confluence\s*[:=]' "${REPO_ROOT}/${file}"; then
                echo "  FAILED: I7 plugin missing requires_i6_confluence"
                echo "    File: ${file}"
                FAILURES_LOCAL=$((FAILURES_LOCAL + 1))
            fi
        fi
    done
}
```

### Systemd service registration in _DAG_ORDER
```python
# services/service_auditor.py — add to _DAG_ORDER dict
"indicagent-feature-parity-auditor.timer": 92,
"indicagent-confidence-calibration.timer": 93,
```

### OTel metrics for auditors
```python
# In feature_parity_auditor.py — module-level
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

## State of the Art

| Old State | Current State | Impact |
|-----------|---------------|--------|
| I5 pattern data in `confluence_scores` DB column | After fix: I5 in `pattern_detections` | Pattern detection queryable from correct column |
| No validation gate between I5 output and DB | FeatureParityAuditor on 5-min timer | Silent pipeline failures caught within 5 minutes |
| Confidence-selection correlation untracked | ConfidenceCalibrationMonitor | Per-setup formula quality visible in Grafana |
| I6 confluence optional in I7 | `requires_i6_confluence` ClassVar enforced by CI | New I7 plugins fail code review without I6 declaration |

**Column naming history:** Phase 104 renamed `intelligence_features` columns from `i1..i8` to concept names (`technical_indicators`, `market_context`, `pattern_detections`, `regime_features`, `confluence_scores`, `smc`, `cross_timeframe_context`, `trading_signals`). The column names are semantically correct — the bug is that the tier data was written to the wrong semantically-named column.

## Open Questions

1. **Do any existing I7 plugins legitimately not need I6 confluence?**
   - What we know: 6 GOOD setups all use I6. 21 NEEDS_REFACTOR setups don't. `trad_AnchoredVWAPReversion` is assessed as "logic sound" but still doesn't use I6.
   - What's unclear: Whether there exist conceptually valid I7 setups where I6 confluence is genuinely inapplicable (e.g., pure session-level setups).
   - Recommendation: Set `requires_i6_confluence = True` as default but allow `False` with a code comment explaining the rationale. The CI check flags missing declaration, not `False` declarations.

2. **Should existing I7 plugins be retroactively required to add the ClassVar?**
   - What we know: The CI pre-commit hook only fires on staged files (new/modified). Existing plugins won't be checked unless they're modified.
   - What's unclear: Whether to add a full-scan test that sweeps all 37 I7 plugins at pytest runtime.
   - Recommendation: Add a pytest test in `tests/unit/intelligence/test_i6_confluence_enforcement.py` that iterates `TIER_I7` in `register_plugins.py` and asserts every plugin declares `requires_i6_confluence`. This forces retroactive addition across all existing plugins.

3. **What alert channel should FeatureParityAuditor use for critical violations?**
   - What we know: `topic_alert_requests` feeds `AlertingAgent` which sends to Telegram/Discord. OTel Alertmanager also fires on gauge thresholds.
   - Recommendation: Publish to `topic_alert_requests` for immediate Telegram alert on 100% NULL detection. Also set OTel gauge `feature_parity_null_fields_total > 0` → Alertmanager rule.

## Sources

### Primary (HIGH confidence)
- Direct DB query on `indicagent` database — verified column contents, confirmed bug location
- `services/feature_writer.py` — read directly, confirmed wrong tier-to-column mapping at lines 192-194
- `src/intelligence/schemas.py` — read directly, confirmed I3/I4/I5 field ownership
- `src/intelligence/plugins/base.py` — read directly, confirmed PatternPlugin Protocol structure
- `src/intelligence/trading/pattern_completion.py` — read directly, confirmed it reads from `frames["i5"]` (in-process, correct)
- `src/core/agent/base.py` — read directly, confirmed BaseDaemon lifecycle and OTel contract
- `services/bar_auditor.py` — read directly, confirmed 5-min audit daemon pattern
- `services/shadow_auditor.py` — read directly, confirmed oneshot timer pattern with JOB_COMPLETED_TOTAL
- `tools/pre-commit.hook` — read directly, confirmed existing 8-check structure and hook patterns
- `production/systemd/indicagent-shadow-auditor.{service,timer}` — read directly, confirmed systemd patterns

### Secondary (MEDIUM confidence)
- Root cause analysis doc (`docs/plans/2026-06-07-signal-quality-crisis-root-cause-analysis.md`) — architectural context and Council Review notes; some threshold values are explicitly labeled as directional guesses
- `signal_ledger` schema — verified `cis_score` and `was_selected` columns exist for calibration monitor

## Metadata

**Confidence breakdown:**
- Feature writer bug (Wave 1): HIGH — confirmed by direct DB query and code read; fix is 3 line swaps
- FeatureParityAuditor (Wave 2): HIGH — pattern is well-established (bar_auditor, shadow_auditor)
- ConfidenceCalibrationMonitor (Wave 2): HIGH — SQL pattern is straightforward; conceptual framing clarified by Council Review
- PatternPlugin I6 enforcement (Wave 3): MEDIUM — design decision required on retroactive enforcement scope; CI hook pattern is clear

**Research date:** 2026-06-08
**Valid until:** 2026-07-08 (codebase is stable; schema and service patterns don't change frequently)
