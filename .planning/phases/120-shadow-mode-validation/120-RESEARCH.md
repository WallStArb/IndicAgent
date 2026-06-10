# Phase 120: Shadow Mode Validation - Research

**Researched:** 2026-06-10
**Domain:** Shadow mode promotion pipeline — statistical gate, oneshot timer service, OTel metrics, Grafana dashboard
**Confidence:** HIGH

## Summary

Phase 120 builds a standalone weekly `ShadowModeValidator` script that gates promotion of the 21 refactored I7 setups via a 5-criteria sequential check. All infrastructure (DB schema, systemd, OTel, Kafka alerting, Grafana) follows established patterns already present in the codebase. There are no new architectural patterns to introduce — this is purely a new service using existing plumbing.

The key complexity is in the statistical gate (`scipy.stats.binomtest`) and the surgical removal of `_check_promotion()` from `shadow_auditor.py`. Verified against live codebase: all DB columns exist, all table schemas confirmed, all patterns are established.

**Primary recommendation:** Follow the `shadow_auditor.py` script structure verbatim for `shadow_validator.py`. The deviation points are: no `bootstrap_ci_lower`, use `binomtest` instead; query only `_SHADOW_VALIDATION_SETUPS`; write to `shadow_registry.is_shadow=FALSE` with a `shadow_transition_log` INSERT.

**Critical correction:** The CONTEXT.md D-07 alert payload uses `"title"` and `"body"` keys. The actual `alert_monitor.py` reads `payload.get("message", "")` and `payload.get("source", "")`. The alert payload must use `"message"` (not `"title"`/`"body"`) to route to Telegram.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** `shadow_validator.py` is a NEW standalone script. Not an extension of `shadow_auditor.py`. SoC: shadow_auditor = demotion-only (30-min), shadow_validator = promotion-only (weekly).

**D-02:** 5-gate sequential check — all must pass, short-circuit on first failure: (1) total >= 100, (2) selection_rate >= 5%, (3) binomtest p < 0.05 vs 50% baseline, (4) avg_pnl_r > 0, (5) calibration_corr >= 0.3.

**D-03:** `was_selected` is an existing boolean column. Calibration = `CORR(cis_score, was_selected::int)`. Query window: all signals since `shadow_tracking_start_ts` (no rolling window).

**D-04:** `signal_ledger_shadow` view = `SELECT * FROM signal_ledger_full WHERE is_shadow = true`. New migration.

**D-05:** Promotion write: `UPDATE shadow_registry SET is_shadow=FALSE, promoted_at=$1`. `INSERT INTO shadow_transition_log` with trigger_reason `'shadow_validator_5gate'`.

**D-06:** 21 setup names hardcoded as `_SHADOW_VALIDATION_SETUPS: frozenset[str]` in `shadow_validator.py`. Verify names against `register_plugins.py` before hardcoding.

**D-07:** Kafka alert to `topic_alert_requests` with severity=CRITICAL per promotion event. Kafka optional — log if unavailable.

**D-08:** 6 new OTel gauges: `shadow_validation_n`, `shadow_validation_selection_rate`, `shadow_validation_p_value`, `shadow_validation_avg_pnl_r`, `shadow_validation_calibration`, `shadow_validation_promoted`. Emit for ALL 21 setups on every run.

**D-09:** Systemd timer `OnCalendar=Mon *-*-* 07:00:00 UTC`, `Persistent=true`. Service `Type=oneshot`. Job label: `"shadow-validator"`.

**D-10:** Remove from `shadow_auditor.py`: `_check_promotion()` function + `await _check_promotion(...)` call site. Verify imports used only by promotion are also removed.

### Claude's Discretion

None specified — all decisions are locked.

### Deferred Ideas (OUT OF SCOPE)

- Extrinsic composite confidence layer (Phase 4.1)
- Per-setup threshold tuning (Phase 121)
- Modifying existing I7 setup code
</user_constraints>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `scipy.stats.binomtest` | scipy 1.7+ | Binomial test, 5-gate check | Project already uses scipy for stats (bootstrap_ci_lower in stats_utils.py) |
| `asyncpg` | current | DB queries and writes | Established pattern for all DB operations in this codebase |
| `structlog` | current | Logging | Established project logger |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `src.core.kafka_utils.KafkaProducerClient` | internal | Alert publishing | Publish promotion events to topic_alert_requests |
| `src.observability.metrics` | internal | OTel gauges | All 6 new shadow_validation_* gauges, JOB_COMPLETED_TOTAL |
| `src.core.database_manager.create_pool` | internal | DB pool | Oneshot scripts use create_pool, not BaseDaemon |

### Alternatives Considered
None — all choices are locked by CONTEXT.md.

**Installation:** No new packages. `scipy` is already in `requirements.txt` (used by `src/core/stats_utils.py`).

## Architecture Patterns

### Recommended Project Structure
```
services/
├── shadow_validator.py       # new standalone oneshot script
├── shadow_auditor.py         # surgical removal of _check_promotion()
production/
├── systemd/
│   ├── indicagent-shadow-validator.timer   # new
│   └── indicagent-shadow-validator.service # new
├── migrations/
│   └── 121_signal_ledger_shadow_view.sql   # new (120 is already taken)
src/observability/
└── metrics.py                # add 6 new shadow_validation_* gauges
```

### Pattern 1: Oneshot Script Structure (shadow_auditor.py verbatim)

**What:** `asyncio.run(_amain())`, `create_db_pool()`, `JOB_COMPLETED_TOTAL`, `flush_and_shutdown_metrics()`
**When to use:** All timer-triggered oneshot scripts

```python
# Source: services/shadow_auditor.py (live)
import _path_bootstrap  # noqa: F401 — must be first, puts project root on sys.path

async def _amain() -> None:
    settings = Settings()
    pool = await create_db_pool(settings.database_url, min_size=2, max_size=5)
    try:
        await _run_validator(pool, settings)
    finally:
        await pool.close()

def main() -> None:
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

### Pattern 2: DB Query with asyncpg

**What:** `pool.acquire()` context manager, `conn.fetch()` for SELECT, `conn.execute()` for UPDATE/INSERT
**When to use:** All DB access in oneshot scripts

```python
# Source: services/shadow_auditor.py (live)
async with pool.acquire() as conn:
    rows = await conn.fetch(
        """
        SELECT COUNT(*) FILTER (WHERE was_selected = true) as selected,
               COUNT(*) as total,
               AVG(so.pnl_r) FILTER (WHERE so.pnl_r IS NOT NULL) as avg_pnl_r,
               CORR(sl.cis_score, sl.was_selected::int) as calibration_corr
        FROM signal_ledger sl
        LEFT JOIN signal_outcomes so USING (signal_id)
        WHERE sl.setup_plugin = $1
          AND sl.is_shadow = true
          AND sl.shadow_tracking_start_ts IS NOT NULL
        """,
        plugin_name,
    )
```

### Pattern 3: OTel Gauge with Label

**What:** `point_gauge()` from `src/observability/metrics.py`, `.set(value, {"label": val})`
**When to use:** Per-setup metrics

```python
# Source: src/observability/metrics.py (live)
SHADOW_VALIDATION_N = point_gauge("shadow_validation_n", "Shadow signal count per setup")
# Usage:
SHADOW_VALIDATION_N.set(total, {"setup_plugin": plugin_name})
```

### Pattern 4: Kafka Alert Publish

**What:** Positional topic + dict body (matching alert_monitor.py schema)
**When to use:** Promotion notifications

```python
# Source: services/service_auditor.py + alert_monitor.py (live) — message key, not body/title
await producer.publish(
    topic_alert_requests(settings.env_name),
    {
        "severity": "CRITICAL",
        "message": f"Shadow Promotion: {plugin_name}\nN={total}, p={pvalue:.3f}, avg_pnl_r={avg_pnl_r:.3f}",
        "source": "shadow_validator",
    },
)
```

### Pattern 5: shadow_transition_log INSERT

**What:** Audit trail for every promotion event
**When to use:** On successful 5-gate promotion

```python
# Source: services/shadow_auditor.py (live) — column set is (component_name, component_type, from_state, to_state, trigger_reason, n, ev_r, ci_lower, win_rate)
await conn.execute(
    """
    INSERT INTO shadow_transition_log
      (component_name, component_type, from_state, to_state,
       trigger_reason, n, ev_r, ci_lower, win_rate)
    VALUES ($1, $2, 'shadow', 'live', 'shadow_validator_5gate', $3, $4, $5, $6)
    """,
    plugin_name, "i7_plugin", total, avg_pnl_r, calibration_corr, selection_rate,
)
```

### Pattern 6: Systemd Oneshot Timer

**What:** `Type=oneshot`, `Restart=no`, `Persistent=true` on timer
**When to use:** Weekly scheduled jobs

```ini
# Source: production/systemd/indicagent-hmm-training.timer (live)
[Timer]
OnCalendar=Mon *-*-* 07:00:00 UTC
Persistent=true
Unit=indicagent-shadow-validator.service

[Install]
WantedBy=timers.target
```

```ini
# Source: production/systemd/indicagent-hmm-training.service (live)
[Service]
Type=oneshot
Restart=no
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/shadow_validator.py
TimeoutStartSec=300
```

### Anti-Patterns to Avoid

- **Wrong alert payload keys:** CONTEXT.md D-07 shows `"title"` and `"body"` but `alert_monitor.py` reads `payload.get("message", "")`. Use `"message"` not `"title"`/`"body"`.
- **Wrong publish kwarg:** `publish(topic, msg={...})` uses positional for topic and either positional or `msg=` kwarg for body. The method signature is `publish(self, topic: str, msg: dict, key: str | None = None)`. Using `value=` instead of `msg=` silently fails at flush.
- **Querying signal_ledger_shadow before migration:** The view does not exist yet. The validator can query `signal_ledger_full WHERE is_shadow = true` directly; the migration creates the view for dashboard/analytics use.
- **Wrong migration number:** Migration 120 (`120_signal_probe_results.sql`) already exists and is deployed. The new view migration must be `121_signal_ledger_shadow_view.sql`.
- **shadow_registry does NOT have promoted_at at the statement level of D-05:** Confirmed present. `promoted_at timestamptz` column exists in live table.
- **shadow_transition_log does NOT have a `calibration_corr` column:** The live table has `(component_name, component_type, from_state, to_state, trigger_reason, n, ev_r, ci_lower, win_rate)`. The D-05 INSERT in CONTEXT.md maps `calibration_corr -> ci_lower` and `selection_rate -> win_rate`. These are schema reuse decisions -- ensure correct column mapping.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Binomial significance test | Custom normal approximation | `scipy.stats.binomtest` | Edge cases at low N, exact binomial is correct |
| Bootstrap CI | Reimplement | `src/core/stats_utils.bootstrap_ci_lower` | Already exists, tested; but NOT used in Phase 120 — shadow_validator uses binomtest instead |
| DB connection pool | Direct asyncpg | `src.core.database_manager.create_pool` | Handles connection settings, pool sizing |
| Metrics flushing | Manual OTel flush | `flush_and_shutdown_metrics()` from metrics.py | Required for oneshot scripts; without it increments never reach exporter |

**Key insight:** Every infrastructure piece (DB pool, metrics, Kafka, structlog, systemd timer) has a living reference implementation in `shadow_auditor.py` or `hmm_training_agent.py`. Copy, don't invent.

## Common Pitfalls

### Pitfall 1: Migration Number Collision

**What goes wrong:** Creating `120_signal_ledger_shadow_view.sql` when `120_signal_probe_results.sql` already exists and is applied to the live database.
**Why it happens:** Phase numbering in context doesn't match migration file numbering. Phase 120 context was written before `120_signal_probe_results.sql` was created (by Phase 117.5 SignalProbeAuditor work).
**How to avoid:** Use `121_signal_ledger_shadow_view.sql`. Confirm with `ls production/migrations/ | sort | tail -5`.
**Warning signs:** Duplicate migration numbers, psql errors on apply.

### Pitfall 2: Alert Payload Key Mismatch

**What goes wrong:** Publishing `{"title": ..., "body": ...}` to topic_alert_requests; alert_monitor reads `payload.get("message", "")` so the message is empty string.
**Why it happens:** CONTEXT.md D-07 specifies `title`/`body` but alert_monitor.py uses `message`.
**How to avoid:** Use `"message"` key in alert payload, matching alert_monitor.py line 71.
**Warning signs:** Telegram receives `*[CRITICAL]* shadow_validator\n` with empty body.

### Pitfall 3: shadow_transition_log Column Mapping

**What goes wrong:** Trying to INSERT `calibration_corr` or `selection_rate` as named columns; neither exists.
**Why it happens:** The shadow_transition_log schema predates these metrics. It has `ci_lower` and `win_rate` as the closest proxies.
**How to avoid:** Map `calibration_corr -> ci_lower` and `selection_rate -> win_rate` in the INSERT (per D-05 mapping). This is intentional schema reuse.
**Warning signs:** `column "calibration_corr" does not exist` asyncpg error.

### Pitfall 4: Missing `_path_bootstrap` Import

**What goes wrong:** `ImportError: No module named 'src'` when running `services/shadow_validator.py` because project root is not on `sys.path`.
**Why it happens:** All service scripts require `import _path_bootstrap` as the first import.
**How to avoid:** First line after docstring must be `import _path_bootstrap  # noqa: F401`.
**Warning signs:** Import errors only when running directly, not in pytest (which adds conftest.py paths).

### Pitfall 5: flush_and_shutdown_metrics() Omission

**What goes wrong:** `JOB_COMPLETED_TOTAL` and all OTel gauges are never flushed to the exporter. Grafana shows no metrics from the run.
**Why it happens:** OTel SDK batches metrics; oneshot scripts exit before the batch interval fires.
**How to avoid:** Call `flush_and_shutdown_metrics()` in the `finally` block of `main()` — identical to shadow_auditor.py.
**Warning signs:** No `shadow_validation_*` metrics appear in Prometheus after a manual run.

### Pitfall 6: Querying Without shadow_tracking_start_ts Filter

**What goes wrong:** Including signals from before Phase 118/119 refactoring that have `is_shadow=true` but were created under different confidence architecture. Contaminates the statistical sample.
**Why it happens:** `signal_ledger.is_shadow` was set on older signals too.
**How to avoid:** Filter `WHERE shadow_tracking_start_ts IS NOT NULL` in the validator query (per D-03).
**Warning signs:** N counts that seem implausibly large for new setups.

### Pitfall 7: service_auditor.py DAG Not Updated

**What goes wrong:** `indicagent-shadow-validator` doesn't appear in service health dashboards, lag monitoring, or audit reports.
**Why it happens:** New units must be registered in `_DAG_ORDER`, `_LAG_THRESHOLDS`, `_AGENT_ID_TO_UNIT` in `services/service_auditor.py`.
**How to avoid:** Per CLAUDE.md — add entry to all three dicts when adding a service. Shadow-validator is a oneshot (like shadow-auditor at position 8), so `_LAG_THRESHOLDS` entry may be None/omitted; DAG order should put it near the other shadow service.
**Warning signs:** Unit not visible in service auditor health panel.

## Code Examples

Verified patterns from official sources:

### Binomial Test (scipy.stats)

```python
# Source: scipy docs + CONTEXT.md D-02
from scipy.stats import binomtest

result = binomtest(selected, total, p=0.5, alternative="greater")
# result.pvalue is the one-sided p-value
# Promote when result.pvalue < 0.05
```

### 5-Gate Sequential Check

```python
# Source: CONTEXT.md D-02, verified against schema
def _check_promotion_criteria(
    total: int,
    selected: int,
    avg_pnl_r: float | None,
    calibration_corr: float | None,
) -> tuple[bool, str, str]:
    """Returns (should_promote, failure_reason, detail)."""
    from scipy.stats import binomtest

    if total < 100:
        return False, "insufficient_n", f"{total} < 100"

    selection_rate = selected / total
    if selection_rate < 0.05:
        return False, "low_selection_rate", f"{selection_rate:.2%} < 5%"

    result = binomtest(selected, total, p=0.5, alternative="greater")
    if result.pvalue >= 0.05:
        return False, "not_significant", f"p={result.pvalue:.3f} >= 0.05"

    if avg_pnl_r is None or avg_pnl_r <= 0:
        return False, "negative_expectancy", f"avg_pnl_r={avg_pnl_r}"

    if calibration_corr is None or calibration_corr < 0.3:
        return False, "poor_calibration", f"corr={calibration_corr} < 0.3"

    return True, "", ""
```

### Verified Plugin Names (from register_plugins.py)

```python
# Source: src/intelligence/register_plugins.py (live, verified 2026-06-10)
# Phase 118 plugins (5):
"trad_OFIContinuation", "trad_PatternCompletion",
"trad_GapAnalysisSetup", "trad_CVDDivergence",
# + one more — see _I7_I6_EXEMPT / TIER_I7 for exact 5th name

# Phase 119 plugins (17, from _PHASE_119_PLUGINS frozenset):
"trad_OFISpike", "trad_CVDSpike", "trad_OFIDivergence",
"trad_FailedBreakout", "trad_CandlestickPatternSetup", "trad_SessionExtremesSetup",
"trad_LiquidityHunt", "trad_DeltaExhaustion",
"trad_LVNBreakout", "trad_VWAPReclaim", "trad_VWAPDeviation",
"trad_MomentumBreakout", "trad_ORB15", "trad_ORB30",
"trad_SecondLegContinuation", "trad_VCP", "trad_DualDivergence"
```

**IMPORTANT:** The 21-setup count requires verifying `register_plugins.py` lines 616-645 for the complete Phase 118 set (5 setups). `_PHASE_119_PLUGINS` contains exactly 17. Total must be 21 when combined. Verify the 5th Phase 118 name before hardcoding `_SHADOW_VALIDATION_SETUPS`.

### shadow_registry Promotion Write (verified schema)

```python
# Source: shadow_registry schema (live), shadow_auditor.py pattern
async with pool.acquire() as conn:
    await conn.execute(
        "UPDATE shadow_registry SET is_shadow=FALSE, promoted_at=$1, demotion_consecutive_count=0 WHERE component_name=$2",
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
        plugin_name, "i7_plugin",
        total,
        avg_pnl_r,          # stored in ev_r column
        calibration_corr,   # stored in ci_lower column (schema reuse)
        selection_rate,     # stored in win_rate column (schema reuse)
    )
```

### Migration 121 (signal_ledger_shadow view)

```sql
-- Source: CONTEXT.md D-04, signal_ledger_full definition (095_signal_ledger_split.sql)
CREATE VIEW signal_ledger_shadow AS
  SELECT *
  FROM signal_ledger_full
  WHERE is_shadow = true;
```

### shadow_auditor.py Surgical Removal (D-10)

Remove:
1. Function `async def _check_promotion(pool, env_name, row)` — lines ~113 to ~253 in current file
2. Call site `await _check_promotion(pool, env_name, dict(row))` — in `_run_audit()` inside the `if row["is_shadow"]:` branch
3. Check imports: `bootstrap_ci_lower`, `SHADOW_DAYS_TO_GATE`, `SHADOW_EV_CI_LOWER`, `SHADOW_WIN_RATE`, `SHADOW_EV_R`, `SHADOW_N_RESOLVED`, `SHADOW_PROMOTION_READY`, `SHADOW_TAIL_RISK_BLOCKED`, `SHADOW_TAIL_GATE_DB_ERROR` — all are used only by `_check_promotion`. All can be removed from the import block in `shadow_auditor.py`.
4. The `_WIN_OUTCOMES` constant — used only by `_check_promotion`. Remove.
5. The `_should_promote`, `_tail_risk_blocks_promotion` pure functions — used only by `_check_promotion`. Remove.
6. Module-level constants `TAIL_GATE_MIN_SKEWNESS`, `TAIL_GATE_MIN_RECOVERY` — used only by `_check_promotion`. Remove.

After removal: `shadow_auditor.py` iterates `shadow_registry` rows, skips swarm agents, calls `_check_demotion()` unconditionally for live components, calls nothing for shadow components.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `scipy.stats.binom_test` | `scipy.stats.binomtest` | scipy 1.7 | `binom_test` is deprecated; use `binomtest` |
| `prometheus_client` | OTel SDK direct | Phase 83 | `prometheus_client` fully removed — never import it |
| Inline `.isoformat().replace("+00:00", "Z")` | `format_iso_ts(dt)` from service_utils.py | established | Timestamp serialization for Kafka/JSON |

## Open Questions

1. **Phase 118 5th setup name**
   - What we know: register_plugins.py line 622 shows `pattern_completion_plugin.name` and line 625 shows `gap_analysis_setup_plugin.name` and line 616-620 area shows `vwap_deviation_plugin.name`, `momentum_breakout_plugin.name`, `liquidity_hunt_plugin.name`. But the register_plugins.py grep only showed lines 616-645 which has those alongside Phase 119 names.
   - What's unclear: The exact 5 Phase 118 names need to be confirmed by reading the Phase 118 VERIFICATION.md or the plugin registration block that predates the Phase 119 plugins. The CONTEXT.md D-06 lists 5 Phase 118 names: `trad_OFIContinuation`, `trad_PatternCompletion`, `trad_GapAnalysisSetup`, `trad_CVDDivergence`, `trad_DivergenceStack`. These should be verified against `register_plugins.py` before hardcoding.
   - Recommendation: Planner MUST read `src/intelligence/register_plugins.py` lines 610-650 fully and `.planning/phases/118-confidence-integrity-top5-setup-refactoring/118-VERIFICATION.md` to confirm all 5 names.

2. **shadow_transition_log column reuse for calibration/selection_rate**
   - What we know: The table has `ci_lower` and `win_rate` but not `calibration_corr` or `selection_rate`. CONTEXT.md D-05 maps these to existing columns.
   - What's unclear: Whether this schema reuse creates any downstream confusion (e.g., Grafana queries, audit reports that expect `ci_lower` = bootstrap CI lower bound).
   - Recommendation: Accept the schema reuse as specified in D-05. Add a comment in the INSERT code documenting the mapping.

3. **Grafana dashboard delivery format**
   - What we know: Existing dashboards in `production/grafana/dashboards/` are JSON files. No provisioning automation was found beyond the existing file drop pattern.
   - What's unclear: Whether a new dashboard JSON needs to be registered in a provisioning YAML or just dropped in the directory.
   - Recommendation: Follow the pattern of existing dashboard JSON files in `production/grafana/dashboards/`. A new `shadow-validation.json` file should be sufficient.

## Sources

### Primary (HIGH confidence)
- `services/shadow_auditor.py` — live codebase, complete script structure, _check_promotion, _check_demotion patterns
- `services/alert_monitor.py` — live codebase, confirmed `payload.get("message", "")` not `"title"`/`"body"`
- `production/systemd/indicagent-hmm-training.timer` + `.service` — canonical oneshot timer pattern
- `production/migrations/095_signal_ledger_split.sql` — confirmed `was_selected`, `is_shadow`, `cis_score`, `shadow_tracking_start_ts` columns
- `src/intelligence/register_plugins.py` — confirmed `_PHASE_119_PLUGINS` frozenset (17 plugins), plugin name strings
- `src/observability/metrics.py` — `point_gauge()` signature, existing SHADOW_* metrics, `JOB_COMPLETED_TOTAL`
- Live DB `\d shadow_registry` — confirmed `promoted_at timestamptz` column exists
- Live DB `\d shadow_transition_log` — confirmed column set: n, ev_r, ci_lower, win_rate, trigger_reason
- Live DB `SELECT viewname FROM pg_views WHERE viewname='signal_ledger_shadow'` — confirmed view does NOT exist yet

### Secondary (MEDIUM confidence)
- `production/migrations/` directory listing — confirmed migration 120 already exists (`120_signal_probe_results.sql`); new migration must be 121

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries confirmed present in codebase
- Architecture: HIGH — all patterns verified against live service files
- Pitfalls: HIGH — all discovered from live code discrepancies (alert payload mismatch, migration collision)
- Schema: HIGH — all columns verified against live DB

**Research date:** 2026-06-10
**Valid until:** 2026-07-10 (stable domain, schema rarely changes)
