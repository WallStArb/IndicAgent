# Post-Reboot System Repair — Design Spec

**Date:** 2026-06-18  
**Phase:** 135 (candidate)  
**Approach:** B — Full Repair + Structural Fixes  
**Council:** Renaissance engineering principles applied throughout

---

## Problem Statement

Post-reboot health check surfaced five distinct failure classes. All are being addressed in one phase. Leaving any open violates "silent wrong answers are worse than loud crashes" and "never drop data that could contain signal."

---

## Root Cause Summary

| ID | Class | Root Cause | Impact |
|----|-------|------------|--------|
| P0 | Data integrity hole | Migration 130 never applied → feature_writer failed silently for ~7.75h | 1,343 signal_events with no intelligence_features context |
| P1 | Structural: pipeline cannot stop | `async for` over Kafka in `_process_loop` never yields to check `self.running` | SIGKILL on every restart; risk of Kafka offset skew + lost in-flight computations |
| P2 | Broken plugin generating structural noise | FVGFill uses market-price entry for limit-order thesis; stop lands inside zone 86% of bars | 4,187 circuit breaker events/boot; masks real errors in logs |
| P3 | Opaque failure mode | `validate_signal` returns `bool` only; failure reason not logged | Cannot diagnose 19 schema_violation events across 6 plugins |
| P4 | Misleading telemetry | `original_inside_distance` (price units) labeled "ATR" in error string | Log analysis produces incorrect ATR distance calculations |

---

## Six Work Units

### W1: Recover Orphaned intelligence_features (P0 — Data Integrity)

**What:** Run `run_historical_pipeline.py` for the gap window `2026-06-18 11:15:00 UTC` through `2026-06-18 19:00:00 UTC`. This recomputes I1-I7 features for all bars in `market_data_ohlcv` during the outage window and writes them to `intelligence_features`.

**Why:** 1,343 `signal_events` rows exist with `feature_ts` pointing at missing `intelligence_features` rows. Those signals will have no ML training context permanently unless replayed. The bar data is intact in `market_data_ohlcv`. Replay is the only recovery path.

**Verification:** After replay, the following query must return 0:
```sql
SELECT COUNT(*) FROM signal_events se
LEFT JOIN intelligence_features inf
  ON se.feature_ts = inf.ts AND se.symbol = inf.symbol AND se.tf = inf.tf
WHERE se.ts BETWEEN '2026-06-18 11:15:00+00' AND '2026-06-18 19:10:00+00'
  AND se.feature_ts IS NOT NULL
  AND inf.ts IS NULL;
```

**Command:** `cd production/scripts && ../../.venv/bin/python run_historical_pipeline.py --client-id 40 --days 1 --replay-only --timeframes 1m,5m,15m,1h`

**Notes:**
- `--replay-only` skips IBKR fetch (bars already in market_data_ohlcv); just reruns I1-I7 pipeline and writes to intelligence_features
- `--days 1` covers today's gap; use `--timeframes 1m,5m,15m,1h` (skip 4h/1d — live pipeline uses these, no gap there)
- Use client-id 40 (provider uses 35; default 56 exceeds `_MAX_CLIENT_ID=50`)
- Do NOT restart intelligence_pipeline during replay (conflicting Kafka offsets)
- Run migration 130 Statement 3 (strip CTF keys from cross_timeframe_context JSONB) after replay completes, since the replay will write fresh rows with top-level ctf columns, not the old JSONB path

---

### W2: feature_writer Startup Pre-flight Schema Check (P0 — Prevention)

**What:** In `services/feature_writer.py`, add a `_verify_schema()` method called from `_setup()` before Kafka subscription. Queries `information_schema.columns` for all columns referenced in `_INSERT_FEATURE_SQL`. If any are missing, raises `RuntimeError` with the list of missing columns and the migration to run.

**Why:** The current failure mode is: migration not applied → feature_writer starts → subscribes to Kafka → begins receiving messages → buffer fills → flush fails → buffer overflows → data lost. This happened silently for hours. The fix converts it to: migration not applied → feature_writer crashes immediately at startup → systemd logs the error → operator sees it before the market opens.

**Design:**
```python
_REQUIRED_COLUMNS = frozenset({
    "ctf_score", "ctf_trend_alignment",
    "ctf_structure_alignment", "ctf_regime_agreement",
})

async def _verify_schema(self) -> None:
    rows = await self.db_manager.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'intelligence_features'"
    )
    existing = {row["column_name"] for row in rows}
    missing = _REQUIRED_COLUMNS - existing
    if missing:
        raise RuntimeError(
            f"intelligence_features schema mismatch — missing columns: {sorted(missing)}. "
            f"Run migration 130 (production/migrations/130_promote_ctf_columns.sql)."
        )
```

**Where:** Called in `_setup()` before `await self._kafka_consumer.start()`. Uses `self.db_manager.fetch()` — the correct pattern per `src/core/database_manager.py`.

---

### W3: Intelligence Pipeline Graceful Shutdown (P1 — SIGTERM)

**Two changes:**

**3a: `_process_loop` inner loop stop check**  
In `services/intelligence_pipeline.py`, inside the `async for _topic, _key, payload in self._kafka_consumer.messages():` body, add after `self._record_message_consumed()`:
```python
if not self.running:
    break
```
This allows SIGTERM to drain the current message and exit cleanly rather than requiring SIGKILL.

**3b: systemd `TimeoutStopSec`**  
Add `TimeoutStopSec=90` to `production/systemd/indicagent-intelligence-pipeline.service`. Current implicit default is 90s but making it explicit documents intent. The teardown sequence is: output queue join (10s timeout) + worker_manager stop + checkpoint write + kafka stop + db close. 90s is sufficient; 90 → SIGKILL.

**Why these two together:** 3a lets the pipeline exit its message loop within one poll cycle (typically <1s). 3b gives the `_teardown()` sequence sufficient time to write the checkpoint and drain Kafka before the OS kills it.

---

### W4: Disable FVGFill Until at_limit Redesign (P2 — Plugin Noise)

**What:** Remove `fvg_fill_plugin.name` from `TIER_I7` in `src/intelligence/register_plugins.py`. Add a comment: `# trad_FVGFill removed: entry-timing defect (see plugin docstring). Restore after at_limit redesign.`

**Why:** The plugin is `shadow_only=True`, IC=+0.001, avg_pnl_r=-0.60R. It generates 4,187 circuit breaker events per boot cycle, masking legitimate errors in the intelligence_pipeline log. The FVG zone features (fvg_type, fvg_top, fvg_bottom) are still computed by upstream SMC plugins and present in `intelligence_features` — no downstream signal loses access to FVG zone data. Disabling the I7 plugin eliminates noise without losing information.

**What is NOT changed:** The SMC-tier FVG detection plugin (which computes fvg_type, fvg_top, fvg_bottom as features) remains active. Only the I7 trade-signal generator is disabled.

**Restart required:** `indicagent-intelligence-pipeline` after deploy.

---

### W5: Instrument validate_signal — Add Failure Reason (P3 — Observability)

**What:** Change `validate_signal(signal: dict) -> bool` signature to `validate_signal(signal: dict) -> tuple[bool, str]` where the second element is the failure reason. Update the executor to log `reason=reason` alongside `schema_violation`.

**Failure reasons (string literals):**
- `"not_dict"` — signal is not a dict
- `"missing_fields"` — REQUIRED_SIGNAL_FIELDS not subset of keys
- `"type_mismatch"` — `signal["type"] != "signal.v1"`
- `"confidence_oor"` — confidence not in [0.0, 1.0]
- `"direction_invalid"` — direction not in (1, -1, 1.0, -1.0)
- `"targets_empty"` — targets list is empty or not a list
- `"stop_geometry"` — stop on wrong side of entry
- `"target_geometry"` — a target on wrong side of entry
- `"ok"` — passes (empty string or "ok")

**Executor update** (`src/intelligence/pipeline/executor.py`):
```python
valid, reason = validate_signal(sig)
if not valid:
    missing = REQUIRED_SIGNAL_FIELDS - set(sig.keys())
    self._logger.error(
        "executor.schema_violation",
        plugin=task.plugin_name,
        missing_fields=sorted(missing),
        reason=reason,
    )
    continue
```

**Call sites:** `validate_signal` is called in executor.py only. All test files using `validate_signal` must be updated to unpack the tuple.

**All call sites requiring update (5 total):**
- `src/intelligence/pipeline/executor.py:898` — primary caller (logs schema_violation)
- `services/signal_writer.py:112` — secondary gate before DLQ routing
- `src/intelligence/trading/plugin_utils.py:262` — defensive check in `build_signal_with_frame()`
- `tests/unit/intelligence/test_signal_schema.py` — asserts `is True` / `is False` (update to unpack)
- `tests/unit/intelligence/test_emit_signal_validation.py:68` — asserts result is truthy (update to unpack)

Pattern: `if not validate_signal(sig):` → `valid, reason = validate_signal(sig); if not valid:`

---

### W6: Fix plugin_utils.py Unit Label Bug (P4 — Telemetry Accuracy)

**What:** In `src/intelligence/trading/plugin_utils.py`, fix the two ValueError format strings (lines ~153-154 and ~190-191) that display `original_inside_distance` labeled as "ATR" when it is in price units.

**Current (wrong):**
```python
f"{plugin_name}: stop correction too extreme (stop {stop_loss:.2f} is "
f"{original_inside_distance:.2f} ATR inside zone [{zone_low}, {zone_high}]). "
```

**Fixed:**
```python
f"{plugin_name}: stop correction too extreme (stop {stop_loss:.2f} is "
f"{original_inside_distance / atr:.2f} ATR inside zone [{zone_low}, {zone_high}]). "
```

**Note:** `atr` is guaranteed non-None in this code path (the `if atr is None: raise` branch runs earlier). No division-by-zero risk.

---

## Migration 130 Statement 3 (Post-Replay Cleanup)

After W1 replay completes, run Statement 3 from `production/migrations/130_promote_ctf_columns.sql` to strip CTF keys from `cross_timeframe_context` JSONB. This enforces single source of truth — top-level columns only.

```sql
UPDATE intelligence_features
SET cross_timeframe_context = cross_timeframe_context
    - ARRAY['ctf_score', 'ctf_trend_alignment', 'ctf_structure_alignment', 'ctf_regime_agreement']
WHERE cross_timeframe_context ? 'ctf_score';
```

Run with `timescaledb.max_tuples_decompressed_per_dml_transaction = 0` (same pattern as backfill above).

---

## Execution Order

```
W6 → W5 → W4 → W3 → W2 → W1 → Migration 130 Statement 3
```

Rationale: W6, W5, W4, W3, W2 are code changes committed to a branch. W1 (replay) is an operational step run after deploy. Migration 130 Statement 3 is the final cleanup after replay confirms success.

W6/W5/W4/W3/W2 can be committed atomically in one PR (all code changes). W1 and the migration run operationally after.

---

## Verification Checklist

- [ ] feature_writer crash-on-startup confirmed when schema missing (test with a column temporarily dropped)
- [ ] Intelligence pipeline stops within 5s of `systemctl stop` (no SIGKILL in journalctl)
- [ ] FVGFill circuit breaker events: 0 in intelligence_pipeline.log after restart
- [ ] `validate_signal` unit tests updated and green
- [ ] `executor.schema_violation` events now include `reason=` field in logs
- [ ] `run_historical_pipeline.py` replay completes; orphan JOIN query returns 0
- [ ] `intelligence_features` rows for gap window have non-null `ctf_score` where I6 fired
- [ ] Migration 130 Statement 3 completes without error; `cross_timeframe_context ? 'ctf_score'` returns 0 rows

---

## Out of Scope

- FVGFill at_limit redesign (separate phase; requires trade_framer changes for at_limit entry type)
- Root-cause fixes for schema_violation plugins (W5 instruments first; fixes follow after one session of data with reasons logged)
- intelligence_pipeline SIGTERM timeout investigation beyond the `_process_loop` break (the `asyncio.gather` will propagate cancellation to the other tasks cleanly once `_process_loop` exits)
