# Phase 112: Plugin Correlation Analysis & Automated Pruning — Research

**Researched:** 2026-05-31
**Domain:** Statistical analysis batch job + schema additions + pipeline integration
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-01: Batch script at `production/scripts/plugin_correlation_batch.py`. Follows `roll_batch.py` exactly.
- D-02: Weekly Monday timer, alongside `ml-discovery`. Unit file in `production/systemd/`.
- D-03: Direction matrix from `signal_ledger` last 90 days. Group by `(feature_ts, symbol, timeframe)`. Direction: +1/−1/0.
- D-04: Minimum gate: `co_fire_count >= 30`. Pairs below threshold not written to DB.
- D-05: `directional_r = agree_count / co_fire_count`.
- D-06: Canonical ordering: `plugin_a < plugin_b` always.
- D-07: `effective_n = 1 / Σ(λ_i / Σλ)²` via participation ratio on correlation matrix eigenvalues.
- D-08: All three conditions for suppression: `directional_r >= 0.80`, `co_fire_count >= 100`, inferior plugin has strictly lower `bootstrap_ci_lower(pnl_r)`.
- D-09: Suppression self-expiring via data starvation. No manual re-activation.
- D-10: `correlation_suppressed` owned exclusively by correlation batch.
- D-11: `plugin_correlation_pairs` table — PRIMARY KEY (plugin_a, plugin_b), CHECK (plugin_a < plugin_b).
- D-12: `plugin_correlation_summary` table — computed_at PK, effective_n, redundant_pairs. History kept.
- D-13: `shadow_registry` migration: ADD COLUMN `correlation_suppressed boolean NOT NULL DEFAULT false`.
- D-14: `shadow_registry_active` VIEW: WHERE promoted = true AND NOT correlation_suppressed.
- D-15: `intelligence_pipeline` loads `shadow_registry_active` at startup. Suppressed plugins excluded before any `_compute()` call.
- D-16: `aggregator` queries `shadow_registry_active` instead of `shadow_registry` directly.
- D-17: `effective_plugin_count` point gauge, label `scope='global'`. Alert: < 6 → warning.
- D-18: `plugin_correlation_redundant_pairs_total` and `plugin_correlation_suppressed_total` point gauges.
- D-19: `job_completed_total{job="plugin-correlation-batch", status}` D-06 oneshot contract.

### Claude's Discretion
- Migration file naming and number (follow existing migration conventions).
- Whether to use numpy/scipy for eigenvalue computation or manual implementation.
- Error handling strategy for insufficient data (< 30 bars) at first run.
- Database query optimization approach for the 90-day signal_ledger scan.
- API endpoint path for serving effective_plugin_count metric.

### Deferred Ideas (OUT OF SCOPE)
- Per-symbol or per-timeframe correlation.
- Runtime concentration discount in the aggregator.
- I1–I6 feature-level correlation.
</user_constraints>

---

## Summary

Phase 112 is a weekly oneshot batch job plus three schema additions and two minimal pipeline changes. The core work is: (1) a Python script that queries `signal_ledger` for the last 90 days, builds a plugin direction matrix, computes pairwise `directional_r` and `effective_n`, writes results to two new tables, and auto-suppresses redundant plugins via a column on `shadow_registry`; (2) a DB migration adding `correlation_suppressed` to `shadow_registry` and creating the `shadow_registry_active` VIEW; (3) a one-line SQL change in `cache_manager.py` to query the VIEW instead of the base table; and (4) a systemd timer unit.

The pattern is fully established. `roll_batch.py` is the exact structural template. All libraries (`numpy`, `scipy`) are already in `requirements.txt`. The only material gap discovered during research is a **spec error** in D-14: the VIEW definition uses `promoted = true` but `shadow_registry` has no `promoted` column — it uses `is_shadow` (inverted). The correct VIEW is `WHERE NOT is_shadow AND NOT correlation_suppressed`. Similarly, D-08's suppression condition 3 references "read from `setup_performance`" but `bootstrap_ci_lower(pnl_r)` already lives in `shadow_registry.last_eval_ci_lower` (populated by `shadow_auditor.py`) — use that instead.

**Primary recommendation:** Copy `roll_batch.py` structure exactly. The single critical correctness issue is the VIEW definition (NOT is_shadow, not `promoted = true`). The integration touch-points are surgical: one line in `cache_manager.py` and one conceptual change to what the "active set" means in the executor.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | >=2.0.0 | Direction matrix, eigenvalue computation | Already in requirements.txt |
| scipy | >=1.15.0 | Eigenvalue decomposition (`scipy.linalg.eigvalsh`) | Already in requirements.txt; `eigvalsh` for symmetric matrices is faster than `eig` |
| asyncpg | (project standard) | All DB operations | Project standard; JSONB → dict natively |
| structlog | (project standard) | Structured logging | Matches roll_batch.py pattern |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| src.core.stats_utils.bootstrap_ci_lower | local | Bootstrap CI on pnl_r list | For D-08 condition 3 if computing live; can also read from shadow_registry.last_eval_ci_lower |
| src.observability.metrics.JOB_COMPLETED_TOTAL | local | D-06 oneshot counter | Required at exit — both success and failure branches |
| src.observability.metrics.flush_and_shutdown_metrics | local | OTLP drain before exit | Must call in `finally` block of `main()` |
| src.observability.metrics.point_gauge | local | effective_plugin_count, redundant_pairs, suppressed_total | Call `.set(value, {"label": val})` |

**Installation:** Nothing new — all dependencies present.

---

## Architecture Patterns

### roll_batch.py Template (EXACT pattern to follow)

```
production/scripts/plugin_correlation_batch.py
  1. sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # project root
  2. import asyncpg, structlog, opentelemetry.metrics
  3. _meter = otel_metrics.get_meter("indicagent")
  4. Create batch-specific counters (_RUNS, _ERRORS, etc.)
  5. Pure computation functions (no DB, no I/O — testable)
  6. async DB operation functions (receive asyncpg.Connection)
  7. async run(dry_run=False) → acquire pool, do work, JOB_COMPLETED_TOTAL
  8. def main() → argparse + asyncio.run(run()) + finally: flush_and_shutdown_metrics()
  9. if __name__ == "__main__": main()
```

Key structural invariants from roll_batch.py:
- Pool: `create_db_pool(settings.database_url, min_size=1, max_size=2)`
- `JOB_COMPLETED_TOTAL.add(1, {"job": "plugin-correlation-batch", "status": "success"})` inside `try` block
- `JOB_COMPLETED_TOTAL.add(1, {"job": "plugin-correlation-batch", "status": "failure"})` inside `except` block
- `await pool.close()` in `finally`
- `flush_and_shutdown_metrics()` in `main()` finally block

### _path_bootstrap pattern (services/) vs sys.path.insert (production/scripts/)

`services/shadow_auditor.py` uses `import _path_bootstrap`. `production/scripts/roll_batch.py` uses `sys.path.insert(0, str(Path(__file__).resolve().parents[2]))`. The batch script lives in `production/scripts/` so follow `roll_batch.py`: use `sys.path.insert`.

### Direction Matrix Build Pattern

```python
# Source: design spec + signal_ledger schema (direction column is integer: +1/-1/0 implicitly via sign)
# Query shape:
rows = await conn.fetch("""
    SELECT setup_plugin, feature_ts, symbol, timeframe, direction
    FROM signal_ledger
    WHERE timestamp >= NOW() - INTERVAL '90 days'
      AND signal_schema_version >= 'v1'
    ORDER BY feature_ts
""")
# Group by (feature_ts, symbol, timeframe) → build direction vector per bar
# direction column is INTEGER in signal_ledger: non-zero = fired
```

**signal_ledger index confirmed:** `idx_signal_ledger_symbol_tf ON signal_ledger (symbol, timeframe, timestamp DESC)` — present. Post-implementation `EXPLAIN ANALYZE` required per spec.

### Eigenvalue Computation Pattern

```python
import numpy as np
from scipy.linalg import eigvalsh  # symmetric matrix — use eigvalsh not eig

# Correlation matrix: rows/cols = active plugins, values = directional_r
# Fill diagonal with 1.0
corr_matrix = np.eye(n_plugins)
for (a, b), r in pairs.items():
    i, j = plugin_index[a], plugin_index[b]
    corr_matrix[i, j] = r
    corr_matrix[j, i] = r

eigenvalues = eigvalsh(corr_matrix)  # returns sorted ascending
eigenvalues = eigenvalues[eigenvalues > 0]  # clip negatives from float error
total = eigenvalues.sum()
effective_n = 1.0 / ((eigenvalues / total) ** 2).sum()
```

### Suppression Condition 3: bootstrap_ci_lower Source

**Critical finding:** `shadow_registry.last_eval_ci_lower` is already populated by `shadow_auditor.py` using `bootstrap_ci_lower(pnl_r_values)`. Use this directly — no need to re-query `setup_performance` or re-compute from `signal_ledger`.

```python
# Query both plugins in the pair in a single SELECT
rows = await conn.fetch("""
    SELECT component_name, last_eval_ci_lower
    FROM shadow_registry
    WHERE component_name = ANY($1)
""", [plugin_a, plugin_b])
ci_by_name = {r["component_name"]: r["last_eval_ci_lower"] for r in rows}

ci_a = ci_by_name.get(plugin_a)
ci_b = ci_by_name.get(plugin_b)
# Only suppress if both have real values (not NULL, not -inf)
if ci_a is not None and ci_b is not None and ci_a != float("-inf") and ci_b != float("-inf"):
    if ci_a < ci_b:
        suppress = plugin_a  # plugin_a is inferior
    elif ci_b < ci_a:
        suppress = plugin_b  # plugin_b is inferior
    else:
        suppress = None  # tied — do not suppress
```

### VIEW Definition (CORRECTED from spec)

**Spec says:** `WHERE promoted = true AND NOT correlation_suppressed`
**Actual schema:** No `promoted` column. Use `is_shadow` (inverted: `is_shadow = false` means promoted/live).

```sql
CREATE VIEW shadow_registry_active AS
    SELECT *
    FROM shadow_registry
    WHERE NOT is_shadow
      AND NOT correlation_suppressed;
```

### cache_manager.py Integration (D-15)

Single line change in `_load_shadow_cache()`:

```python
# BEFORE (line 528):
"SELECT component_name, is_shadow FROM shadow_registry"

# AFTER:
"SELECT component_name, is_shadow FROM shadow_registry_active"
```

The `shadow_cache` dict maps `{component_name: bool(is_shadow)}`. After the VIEW change, only promoted+non-suppressed plugins appear. For the executor, a plugin absent from `shadow_cache` gets `shadow_cache.get(plugin_name, False)` → False (treated as live). This is correct: missing from VIEW means suppressed; not present in dict → `False` for `is_shadow`. **However**, the executor does NOT currently skip plugins based on shadow_cache — it only stamps `is_shadow` on the signal output. Suppressed plugins need a separate skip gate in the executor.

**Executor change needed:** In `executor.py`'s `_run_i7_plugins()`, add a check before calling `_compute()`:

```python
# Check correlation suppression — plugin absent from shadow_registry_active means suppressed
if plugin_name not in cache_snapshot.shadow_cache:
    continue  # plugin not in active view → correlation-suppressed, skip _compute()
```

Wait — this is wrong if the plugin was never enrolled. Need a separate suppression set. The better approach is to make `_load_shadow_cache` return `None` for suppressed plugins (distinguishing "not enrolled" from "suppressed"), OR to add a separate `_suppressed_plugins: set[str]` cache.

**Cleanest approach** (confirmed by reading the code): Change the shadow_cache load to query `shadow_registry` base table (all enrolled) but add a `correlation_suppressed` column to the return, so cache_manager returns two sets: `shadow_cache` (is_shadow map) and `suppressed_plugins` (set of correlation-suppressed names). Then executor checks `if plugin_name in suppressed_plugins: continue`.

**Simpler approach consistent with D-14/D-15:** The view `shadow_registry_active` represents "should run" plugins. Load it as an allowlist set. Plugins absent from the allowlist skip `_compute()`. The `shadow_cache` (is_shadow stamp) remains separate.

### Systemd Timer Pattern (from ml-discovery.timer)

```ini
[Unit]
Description=IndicAgent Plugin Correlation Analysis — Weekly Monday

[Timer]
OnCalendar=Mon *-*-* 07:00:00 UTC
Persistent=true
Unit=indicagent-plugin-correlation-batch.service

[Install]
WantedBy=timers.target
```

Service file follows `roll_batch.service` exactly:
```ini
[Service]
Type=oneshot
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
Environment=INDICAGENT_ENV=development
ExecStart=/home/bg/dev/indicagent/.venv/bin/python production/scripts/plugin_correlation_batch.py
TimeoutStartSec=600
```

### Migration File Naming Convention

Files use zero-padded three-digit prefix with underscore: `NNN_description.sql`. Last migration is `109_config_foundation.sql`. Next available: **`110_plugin_correlation.sql`**.

### OTel Metrics Creation Pattern

From `metrics.py`:

```python
# point gauge (absolute value, use .set()):
EFFECTIVE_PLUGIN_COUNT = point_gauge("effective_plugin_count", "Effective independent plugin count")
PLUGIN_CORR_REDUNDANT = point_gauge("plugin_correlation_redundant_pairs_total", "Redundant plugin pairs above threshold")
PLUGIN_CORR_SUPPRESSED = point_gauge("plugin_correlation_suppressed_total", "Plugins currently correlation-suppressed")

# Usage:
EFFECTIVE_PLUGIN_COUNT.set(effective_n, {"scope": "global"})
PLUGIN_CORR_REDUNDANT.set(redundant_pairs, {})
PLUGIN_CORR_SUPPRESSED.set(suppressed_count, {})
```

Add these three to `src/observability/metrics.py` (not inside the batch script itself — centralized registry pattern).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Eigenvalue computation | Manual power iteration | `scipy.linalg.eigvalsh` | `scipy>=1.15.0` already in requirements; handles numeric stability, negative eigenvalue clipping needed regardless |
| Bootstrap CI | Custom resampling loop | `src.core.stats_utils.bootstrap_ci_lower` | Already exists, tested, seeded RNG for reproducibility |
| OTLP flush | Manual HTTP flush | `flush_and_shutdown_metrics()` from metrics.py | Identical pattern to roll_batch.py; critical for OTLP exporter drain |
| DB connection pooling | Custom pool | `src.core.database_manager.create_pool` | Project standard; min_size=1, max_size=2 for oneshot scripts |
| asyncpg JSONB | json.loads/json.dumps | Pass dict directly | asyncpg auto-serializes; CLAUDE.md rule |

---

## Common Pitfalls

### Pitfall 1: VIEW Uses Wrong Column Name
**What goes wrong:** Spec DDL says `WHERE promoted = true` but column is `is_shadow` (inverted). Applying the spec verbatim causes a DB error at migration time.
**Prevention:** Use `WHERE NOT is_shadow AND NOT correlation_suppressed`.

### Pitfall 2: suppress_condition_3 Uses Wrong Source
**What goes wrong:** Spec says "read `bootstrap_ci_lower(pnl_r)` from `setup_performance`" but `setup_performance` has no such column. `setup_performance` stores `avg_pnl_r`, `sharpe_ratio`, `win_rate`, `sample_size` only.
**Prevention:** Read `last_eval_ci_lower` from `shadow_registry` directly (populated by shadow_auditor). Fall back to `avg_pnl_r` if `last_eval_ci_lower` is NULL or -inf (plugin has no resolved signals yet).

### Pitfall 3: Cache Change Doesn't Skip _compute()
**What goes wrong:** Changing `_load_shadow_cache` to query `shadow_registry_active` changes which plugins are marked `is_shadow`, but the executor only uses `shadow_cache` to **stamp** signals — it does not skip `_compute()` calls. Suppressed plugins still run.
**Prevention:** Add an explicit skip gate in the executor. The cleanest approach: cache_manager adds a `suppressed_plugins: set[str]` property that the executor checks. Alternatively, add a second query in `_load_shadow_cache` for correlation-suppressed names.

### Pitfall 4: OTLP Counter Never Reaches Collector
**What goes wrong:** Calling `JOB_COMPLETED_TOTAL.add(...)` without `flush_and_shutdown_metrics()` in `main()` finally block — counter never drains before process exits.
**Prevention:** Verbatim from roll_batch.py: `try: asyncio.run(run()) finally: flush_and_shutdown_metrics()`.

### Pitfall 5: Signal Direction Mapping
**What goes wrong:** `signal_ledger.direction` is an integer. The spec says +1/−1/0 but the actual firing check needs to account for "did not fire" being the absence of a row (direction=0 rows may not exist for non-firing plugins).
**Prevention:** When building the direction matrix per bar-group, initialize all plugins to 0, then overwrite with actual direction from rows. Direction 0 means the plugin fired with no direction (which shouldn't happen for I7) or did not fire. In practice, query rows WHERE direction != 0 and treat absence as 0.

### Pitfall 6: eigenvalues Can Be Negative from Float Error
**What goes wrong:** Floating-point correlation matrices can have tiny negative eigenvalues (−1e-15). These break the participation ratio formula.
**Prevention:** Clip eigenvalues to 0 before computation: `eigenvalues = eigenvalues[eigenvalues > 1e-10]`.

### Pitfall 7: co_fire_count Denominator on Self-Join
**What goes wrong:** Computing co-fire from separate per-plugin grouped data misses the bar-level joint events.
**Prevention:** Build a full direction matrix (bars × plugins) first, then compute pairwise co-fire as vectorized dot products: for each pair, `co_fire = (abs(dir_a) * abs(dir_b)).sum()`, `agree = (dir_a == dir_b) & (dir_a != 0)`.sum().

### Pitfall 8: Canonical Ordering Enforced in Two Places
**What goes wrong:** Forgetting the CHECK constraint is advisory in some DBs — code must also enforce `plugin_a < plugin_b` before INSERT.
**Prevention:** Sort pair tuple in Python before building the UPSERT: `(a, b) = (min(a,b), max(a,b))`.

---

## Code Examples

### D-06 Exit Pattern (from roll_batch.py)

```python
# Source: production/scripts/roll_batch.py lines 456-462
async def run(dry_run: bool = False) -> None:
    pool = await create_db_pool(settings.database_url, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            # ... do work ...
        JOB_COMPLETED_TOTAL.add(1, {"job": "plugin-correlation-batch", "status": "success"})
    except Exception as exc:
        _ERRORS.add(1, _ATTRS)
        JOB_COMPLETED_TOTAL.add(1, {"job": "plugin-correlation-batch", "status": "failure"})
        raise
    finally:
        await pool.close()

def main() -> None:
    parser = argparse.ArgumentParser(...)
    parser.add_argument("--dry-run", ...)
    args = parser.parse_args()
    try:
        asyncio.run(run(dry_run=args.dry_run))
    finally:
        flush_and_shutdown_metrics()
```

### UPSERT Pattern for plugin_correlation_pairs

```python
# ON CONFLICT DO UPDATE — idempotent, latest snapshot only
await conn.executemany("""
    INSERT INTO plugin_correlation_pairs
        (plugin_a, plugin_b, directional_r, co_fire_count, computed_at)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (plugin_a, plugin_b) DO UPDATE SET
        directional_r = EXCLUDED.directional_r,
        co_fire_count  = EXCLUDED.co_fire_count,
        computed_at    = EXCLUDED.computed_at
""", rows)
```

### Suppression Update (idempotent, clears stale suppression)

```python
# Set correlation_suppressed on inferior plugins
await conn.execute("""
    UPDATE shadow_registry
    SET correlation_suppressed = true
    WHERE component_name = ANY($1)
""", to_suppress)

# Clear correlation_suppressed for pairs that no longer qualify
# (co_fire_count decayed below 30 threshold — data starvation expiry)
await conn.execute("""
    UPDATE shadow_registry
    SET correlation_suppressed = false
    WHERE component_name NOT IN (
        SELECT CASE WHEN directional_r >= 0.80 AND co_fire_count >= 100
                    THEN ... END  -- build suppression list from current run
    )
    AND correlation_suppressed = true
""")
```

### shadow_cache Integration (executor change)

```python
# In cache_manager._load_shadow_cache() — add second property
async def _load_shadow_cache(self) -> None:
    rows = await self._db.execute_query(
        "SELECT component_name, is_shadow FROM shadow_registry"
    )
    self._shadow_cache = {r["component_name"]: bool(r["is_shadow"]) for r in rows}

    # Load suppressed set separately (correlation_suppressed is a new column)
    suppressed_rows = await self._db.execute_query(
        "SELECT component_name FROM shadow_registry WHERE correlation_suppressed = true"
    )
    self._suppressed_plugins = {r["component_name"] for r in suppressed_rows}

# In executor._run_i7_plugins() — add skip gate:
if plugin_name in cache_snapshot.suppressed_plugins:
    continue  # correlation-suppressed: skip _compute()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `SELECT ... FROM shadow_registry` | `SELECT ... FROM shadow_registry_active` | Phase 112 | Suppressed plugins excluded from execution set automatically |
| Manual signal correlation tracking | Automated weekly batch with self-expiring suppression | Phase 112 | No human intervention for redundancy management |

---

## Open Questions

1. **Aggregator D-16 scope**
   - What we know: `aggregator.py` does not directly query `shadow_registry`. The `aggregate()` function receives signals that already passed through the executor. The `shadow_cache` in `cache_manager` is the only DB-facing integration point.
   - What's unclear: D-16 says "aggregator queries shadow_registry_active instead of shadow_registry directly" — this may refer to the aggregator's consumption of the shadow_cache signal (which flows from cache_manager), not a direct DB query.
   - Recommendation: Confirm by grep of aggregator for any direct shadow_registry query. If none exists, D-16 is satisfied by the cache_manager change alone.

2. **bootstrap_ci_lower for recently-suppressed plugins**
   - What we know: `shadow_registry.last_eval_ci_lower` is `-inf` for plugins with fewer than 10 resolved signals (shadow_auditor sets `-inf` as sentinel).
   - What's unclear: If both plugins in a pair have `last_eval_ci_lower = -inf`, condition 3 cannot be evaluated.
   - Recommendation: When both are -inf, fall back to `last_eval_ev_r` for comparison. Document this fallback explicitly. If both ev_r are also equal or NULL, skip suppression for that pair (require valid data).

3. **effective_plugin_count API endpoint**
   - What we know: `/metrics` returns a redirect to OTel Collector. No dedicated endpoint pattern exists.
   - Recommendation: Emit `effective_plugin_count` as a point gauge in the batch (and register in metrics.py). The OTel Collector at `:8889/metrics` scrapes it automatically. No new API route needed — Grafana reads from Prometheus at `:8889`.

---

## Sources

### Primary (HIGH confidence)
- `production/scripts/roll_batch.py` — structural pattern confirmed (lines 1-481)
- `services/shadow_auditor.py` — shadow_registry query patterns, `last_eval_ci_lower` population, bootstrap_ci_lower usage
- `src/observability/metrics.py` — OTel metric creation patterns, `JOB_COMPLETED_TOTAL`, `flush_and_shutdown_metrics`, `point_gauge()`
- `src/intelligence/pipeline/cache_manager.py` — `_load_shadow_cache` at line 522-530, `shadow_cache` property
- `src/intelligence/pipeline/executor.py` — `_is_shadow()` and shadow_cache usage at lines 220-226, 723
- `src/core/stats_utils.py` — `bootstrap_ci_lower()` implementation
- Live DB schema: `\d shadow_registry`, `\d setup_performance`, `\d signal_ledger` — confirmed column names
- `requirements.txt` — numpy>=2.0.0 and scipy>=1.15.0 confirmed present

### Secondary (MEDIUM confidence)
- `production/systemd/indicagent-ml-discovery.timer` — confirmed weekly Monday OnCalendar pattern
- `production/systemd/indicagent-roll-batch.service` — confirmed oneshot service file structure
- `production/migrations/109_config_foundation.sql` — confirmed migration naming convention (next: 110)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries confirmed in requirements.txt via file read
- Architecture: HIGH — all patterns confirmed by reading actual source files
- Schema: HIGH — live DB queries confirmed column names and schema
- Pitfalls: HIGH — derived from direct code inspection (not assumption)

**Research date:** 2026-05-31
**Valid until:** 60 days (schema stable, no fast-moving dependencies)

---

## Critical Corrections to Spec (Must inform planner)

These are errors in the design spec/CONTEXT.md that the planner must correct:

1. **D-14 VIEW DDL wrong column**: Spec says `WHERE promoted = true`. Actual column: `is_shadow` (boolean, inverted). Correct VIEW: `WHERE NOT is_shadow AND NOT correlation_suppressed`.

2. **D-08 condition 3 data source**: Spec says "read `bootstrap_ci_lower(pnl_r)` from `setup_performance`". `setup_performance` has no such column. Correct source: `shadow_registry.last_eval_ci_lower` (populated by shadow_auditor every 30 min). Fallback for -inf values: use `last_eval_ev_r`.

3. **D-15/D-16 executor integration is non-trivial**: Changing the VIEW in cache_manager only affects the `is_shadow` stamp on signals — it does NOT skip `_compute()` calls. A separate `suppressed_plugins: set[str]` cache property must be added to CacheManager, and a skip gate must be added to the executor's I7 loop. This is a slightly larger change than "minimal plumbing."
