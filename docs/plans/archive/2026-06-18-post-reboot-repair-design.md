# Post-Reboot System Repair — Design Spec

**Date:** 2026-06-18  
**Phase:** 135 (candidate)  
**Approach:** B — Full Repair + Structural Fixes  
**Council:** Renaissance engineering principles applied throughout  
**Review:** Cross-AI review completed (Codex + Ollama); four structural issues corrected in this revision.

---

## Problem Statement

Post-reboot health check surfaced five distinct failure classes. All are being addressed in one phase. Leaving any open violates "silent wrong answers are worse than loud crashes" and "never drop data that could contain signal."

---

## Root Cause Summary

| ID | Class | Root Cause | Impact |
|----|-------|------------|--------|
| P0 | Data integrity hole | Migration 130 never applied → feature_writer failed silently for ~7.75h | 1,343 signal_events with no intelligence_features context |
| P1 | Structural: pipeline cannot stop | `async for` over Kafka in `_process_loop` blocks in `messages()` indefinitely; SIGTERM handler only sets a flag the blocked loop cannot check | SIGKILL on every restart; risk of Kafka offset skew + lost in-flight computations |
| P2 | Broken plugin generating structural noise | FVGFill uses market-price entry for limit-order thesis; stop lands inside zone 86% of bars | 4,187 circuit breaker events/boot; masks real errors in logs |
| P3 | Opaque failure mode | `validate_signal` returns `bool` only; failure reason not logged | Cannot diagnose 19 schema_violation events across 6 plugins |
| P4 | Misleading telemetry | `original_inside_distance` (price units) labeled "ATR" in error string | Log analysis produces incorrect ATR distance calculations |

---

## Six Work Units

### W1: Recover Orphaned intelligence_features (P0 — Data Integrity)

**What:** Run `run_historical_pipeline.py` for the gap window `2026-06-18 11:15:00 UTC` through `2026-06-18 19:10:00 UTC`. This recomputes I1-I7 features for all bars in `market_data_ohlcv` during the outage window and writes them directly to `intelligence_features` (bypasses Kafka — no conflict with live feature_writer).

**Why:** 1,343 `signal_events` rows exist with `feature_ts` pointing at missing `intelligence_features` rows. Those signals will have no ML training context permanently unless replayed. The bar data is intact in `market_data_ohlcv`. Replay is the only recovery path.

**Prerequisite:** W2 (JSONB write path fix) must be deployed and running before W1 executes, so replayed rows are written with the correct schema (CTF keys in top-level columns only, not duplicated in `cross_timeframe_context`). If W2 is not yet deployed, replay rows will themselves need Statement 3 cleanup.

**ON CONFLICT behavior:** The replay must use `ON CONFLICT (ts, symbol, tf) DO UPDATE` — not `DO NOTHING`. If any partial rows were written before feature_writer failed, DO NOTHING would leave stale partial data. Confirm `run_historical_pipeline.py` uses DO UPDATE for `intelligence_features` inserts. If not, this must be added before running.

**Verification:** After replay, the following query must return 0:
```sql
SELECT COUNT(*) FROM signal_events se
LEFT JOIN intelligence_features inf
  ON se.feature_ts = inf.ts AND se.symbol = inf.symbol AND se.tf = inf.tf
WHERE se.ts BETWEEN '2026-06-18 11:15:00+00' AND '2026-06-18 19:10:00+00'
  AND se.feature_ts IS NOT NULL
  AND inf.ts IS NULL;
```

**Command:** `cd production/scripts && ../../.venv/bin/python run_historical_pipeline.py --client-id 40 --start-ts "2026-06-18 11:15:00" --end-ts "2026-06-18 19:10:00" --replay-only --timeframes 1m,5m,15m,1h`

If `run_historical_pipeline.py` does not support `--start-ts`/`--end-ts`, fall back to `--days 1` — the gap window falls within today, so `--days 1` covers it. Confirm by spot-checking that rows at `2026-06-18 11:15:00 UTC` are present after replay.

**Notes:**
- `--replay-only` skips IBKR fetch (bars already in market_data_ohlcv); reruns I1-I7 pipeline and writes directly to intelligence_features
- Use client-id 40 (provider uses 35; default 56 exceeds `_MAX_CLIENT_ID=50`)
- `feature_writer` can remain running — replay writes directly to DB, not via Kafka, so no dual-write conflict on this timerange (live pipeline writes only to current bars)
- Do NOT restart `intelligence_pipeline` during replay (conflicting Kafka offsets)
- I1-I7 replay is deterministic given the same bar history in `market_data_ohlcv` — no look-ahead bias; the pipeline processes bars in chronological order using only data available at each timestamp

---

### W2: feature_writer Startup Pre-flight + JSONB Write Path Fix (P0 — Prevention)

Two sub-tasks. Both are required. 2b is a prerequisite for Migration 130 Statement 3 to be durable.

**2a: Startup pre-flight schema check**

In `services/feature_writer.py`, add a `_verify_schema()` method called from `_setup()` before Kafka subscription. Queries `information_schema.columns` for the specific Phase 130 columns. If any are missing, raises `RuntimeError` with the list and the migration to run.

This guard is scoped to Phase 130 columns specifically — it is a regression guard, not a full INSERT contract validator.

```python
_REQUIRED_COLUMNS = frozenset({
    "ctf_score", "ctf_trend_alignment",
    "ctf_structure_alignment", "ctf_regime_agreement",
})

async def _verify_schema(self) -> None:
    rows = await self.db_manager.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'intelligence_features' AND table_schema = 'public'"
    )
    existing = {row["column_name"] for row in rows}
    missing = _REQUIRED_COLUMNS - existing
    if missing:
        raise RuntimeError(
            f"intelligence_features schema mismatch — missing columns: {sorted(missing)}. "
            f"Run migration 130 (production/migrations/130_promote_ctf_columns.sql)."
        )
```

The `table_schema = 'public'` filter is mandatory — without it, `information_schema.columns` can return columns from other schemas with the same table name, producing false negatives on missing columns.

**Where:** Called in `_setup()` before `await self._kafka_consumer.start()`. Uses `self.db_manager.fetch()` — the correct pattern per `src/core/database_manager.py`.

**Why this converts the failure:** Current path: migration not applied → feature_writer starts → subscribes to Kafka → buffer fills → flush fails → buffer overflows → data lost silently for hours. Fixed path: migration not applied → feature_writer crashes at startup → systemd logs the RuntimeError → operator sees it before market open.

**2b: Fix JSONB write paths — strip CTF keys from cross_timeframe_context at source**

Migration 130 Statement 3 strips CTF keys from existing `cross_timeframe_context` rows. But if the live write paths still serialize those keys into JSONB, Statement 3 will be undone immediately by the next feature write. The "single source of truth" enforcement only holds if the writers stop duplicating the data.

**Files to update:**
- `services/feature_writer.py` (line ~217): when building the JSONB dict for `cross_timeframe_context`, explicitly exclude the four promoted keys before serializing: `ctf_score`, `ctf_trend_alignment`, `ctf_structure_alignment`, `ctf_regime_agreement`.
- `production/scripts/run_historical_pipeline.py` (lines ~748-750): same — when writing `cross_timeframe_context`, call `.model_dump(exclude={'ctf_score', 'ctf_trend_alignment', 'ctf_structure_alignment', 'ctf_regime_agreement'})` or equivalent.

Pattern: wherever `event.i6.model_dump(exclude_none=True)` is used to populate `cross_timeframe_context`, add `exclude={'ctf_score', 'ctf_trend_alignment', 'ctf_structure_alignment', 'ctf_regime_agreement'}` to the call.

2b must be deployed and running before W1 (replay). W1 rows written after 2b deploy will be clean. Migration 130 Statement 3 then cleans only the pre-existing rows.

---

### W3: Intelligence Pipeline Graceful Shutdown (P1 — SIGTERM)

**Three changes. All three are required. The fix in 3a alone is insufficient.**

**Root cause clarification:** The original analysis identified that `_process_loop` never checks `self.running`. The deeper problem: when Kafka has no pending messages, `async for payload in self._kafka_consumer.messages():` blocks inside the consumer's `poll()` call indefinitely. Setting `self.running = False` in the SIGTERM handler has no effect — the `async for` loop body never executes until the broker delivers another message. The result: SIGTERM is received, `self.running = False`, and nothing happens until either (a) a new Kafka message arrives, or (b) systemd's `TimeoutStopSec` expires and sends SIGKILL. This is the deadlock.

**3a: `_process_loop` inner loop stop check (belt-and-suspenders)**

In `services/intelligence_pipeline.py`, inside the `async for` body, add after `self._record_message_consumed()`:
```python
if not self.running:
    break
```
This handles the case where `self.running` becomes False while a message is being processed (i.e., during the processing of a message rather than while waiting for one). Without this, the loop would process one more message after the stop signal before checking again.

**3b: Consumer stop in shutdown path (the actual fix)**

In `services/intelligence_pipeline.py`, override the shutdown hook (BaseDaemon's `_stop()` or equivalent signal handler) to call `await self._kafka_consumer.stop()` as part of the stop sequence, BEFORE waiting for `_process_loop` to return:

```python
async def _stop(self) -> None:
    self.running = False
    await self._kafka_consumer.stop()  # unblocks messages() — causes StopAsyncIteration in _process_loop
    await super()._stop()
```

Calling `self._kafka_consumer.stop()` closes the consumer, which causes the `async for` in `_process_loop` to terminate (the async generator receives `aclose()`, which raises `StopAsyncIteration`). `_process_loop` then exits cleanly, and `_teardown()` runs normally.

If BaseDaemon does not expose `_stop()` override, an alternative: add an `asyncio.Event` shutdown signal and `select` between the consumer and the event in `_process_loop`. But the consumer stop approach is simpler and correct.

**Verification requirement:** SIGTERM test must be run with Kafka idle (no active messages flowing). If the test only passes when messages are flowing, the fix is incomplete.

**3c: systemd `TimeoutStopSec`**

Add `TimeoutStopSec=90` to `production/systemd/indicagent-intelligence-pipeline.service`. The implicit default is 90s, but making it explicit documents the shutdown budget: output queue join (10s timeout) + worker_manager stop + checkpoint write + kafka stop + db close. 90s → SIGKILL.

With 3a+3b in place, the pipeline should stop in <2s under normal conditions. 90s remains the hard backstop for pathological cases.

---

### W4: Disable FVGFill Until at_limit Redesign (P2 — Plugin Noise)

**What:** Remove `fvg_fill_plugin.name` from `TIER_I7` in `src/intelligence/register_plugins.py`. Add a comment: `# FVGFill removed: entry-timing defect (see plugin docstring). Restore after at_limit redesign.`

**Why:** The plugin is `shadow_only=True`, IC=+0.001, avg_pnl_r=-0.60R. It generates 4,187 circuit breaker events per boot cycle, masking legitimate errors in the intelligence_pipeline log. The FVG zone features (fvg_type, fvg_top, fvg_bottom) are still computed by upstream SMC plugins and present in `intelligence_features` — no downstream signal loses access to FVG zone data. Disabling the I7 plugin eliminates noise without losing information.

**What is NOT changed:** The SMC-tier FVG detection plugin (which computes fvg_type, fvg_top, fvg_bottom as features) remains active. Only the I7 trade-signal generator is disabled.

**Shadow registry:** FVGFill's entry in `shadow_registry` retains its historical stats. No new shadow signals will accumulate. The governance cycle will not promote it (insufficient N). No cleanup required — the data is valid historical performance evidence.

**Test sweep required:** `TIER_I7` membership is used in registration, replay defaults, validator checks, and tier size assertions. After removing `fvg_fill_plugin.name`, run `grep -r "fvg_fill\|FVGFill\|TIER_I7" tests/` and update all affected test assertions. Do not assume only the listed tests are affected.

**Restart required:** `indicagent-intelligence-pipeline` after deploy.

---

### W5: Instrument validate_signal — Add Failure Reason (P3 — Observability)

**What:** Change `validate_signal` to return `ValidationResult` — a NamedTuple with `__bool__` — so the failure reason is accessible without breaking any existing call site.

**Why the return-type design matters:** Changing `validate_signal() -> bool` to `-> tuple[bool, str]` is a silent correctness disaster. A non-empty tuple is always truthy in Python. Any call site using `if validate_signal(sig):` would pass validation for every signal, valid or not — the exact opposite of the intended behavior. `ValidationResult` with `__bool__` is backward-compatible and adds the reason without this risk.

**Implementation:**

In `src/intelligence/trading/signal_schema.py`, define:

```python
from typing import NamedTuple

class ValidationResult(NamedTuple):
    valid: bool
    reason: str

    def __bool__(self) -> bool:
        return self.valid
```

Change `validate_signal` signature and all return statements:
```python
def validate_signal(signal: dict) -> ValidationResult:
    if not isinstance(signal, dict):
        return ValidationResult(False, "not_dict")
    ...
    return ValidationResult(True, "")
```

**Failure reason string literals:**
- `"not_dict"` — signal is not a dict
- `"missing_fields"` — REQUIRED_SIGNAL_FIELDS not subset of keys
- `"type_mismatch"` — `signal["type"] != "signal.v1"`
- `"confidence_oor"` — confidence not in [0.0, 1.0]
- `"direction_invalid"` — direction not in (1, -1, 1.0, -1.0)
- `"targets_empty"` — targets list is empty or not a list
- `"stop_geometry"` — stop on wrong side of entry
- `"target_geometry"` — a target on wrong side of entry
- `""` — valid (empty string; do not use `"ok"`)

**Backward compatibility:** All existing call sites using `if validate_signal(sig):` or `if not validate_signal(sig):` continue to work unchanged — `__bool__` delegates to `.valid`. No call site requires modification merely to remain correct.

**Executor update** (`src/intelligence/pipeline/executor.py:898`): update to log the reason:
```python
result = validate_signal(sig)
if not result:
    missing = REQUIRED_SIGNAL_FIELDS - set(sig.keys())
    self._logger.error(
        "executor.schema_violation",
        plugin=task.plugin_name,
        missing_fields=sorted(missing),
        reason=result.reason,
    )
    continue
```

**Call sites that should be updated to use `.reason` for richer logging (not required for correctness):**
- `src/intelligence/pipeline/executor.py:898` — update to log `reason=result.reason`
- `services/signal_writer.py:112` — optionally log reason on DLQ path

**Test files requiring update (tuple unpacking patterns only):**
- `tests/unit/intelligence/test_signal_schema.py` — if it does `valid, reason = validate_signal(...)`, update to `result = validate_signal(...); valid, reason = result`
- `tests/unit/intelligence/test_emit_signal_validation.py:68` — same

---

### W6: Fix plugin_utils.py Unit Label Bug (P4 — Telemetry Accuracy)

**What:** In `src/intelligence/trading/plugin_utils.py`, fix the two ValueError format strings (lines ~153-154 and ~190-191) that display `original_inside_distance` labeled as "ATR" when it is in price units.

**Current (wrong label, wrong value):**
```python
f"{plugin_name}: stop correction too extreme (stop {stop_loss:.2f} is "
f"{original_inside_distance:.2f} ATR inside zone [{zone_low}, {zone_high}]). "
```

**Fixed (correct ratio, epsilon guard for zero ATR):**
```python
_ATR_EPSILON = 1e-8  # guards against zero-ATR bars (market close, zero-range candles)

f"{plugin_name}: stop correction too extreme (stop {stop_loss:.2f} is "
f"{original_inside_distance / max(atr, _ATR_EPSILON):.2f} ATR inside zone [{zone_low}, {zone_high}]). "
```

**Note on `atr` guarantee:** `atr` is guaranteed non-None in this code path (the `if atr is None: raise` branch runs earlier). However, `atr` can be zero during market-close bars or sessions with zero-range candles (open == high == low == close). `max(atr, _ATR_EPSILON)` prevents a `ZeroDivisionError` from replacing the intended `ValueError`. The resulting ATR ratio will be astronomically large in the zero-ATR case, which is correct behavior — the log message should reflect that the stop is infinitely far inside the zone, not crash.

---

## Migration 130 Statement 3 (Post-Replay Cleanup)

**Prerequisite:** W2 sub-task 2b (JSONB write path fix) must be deployed first. If live writers still inject CTF keys into `cross_timeframe_context`, Statement 3 cleans existing rows but new writes reintroduce the keys immediately, making the cleanup worthless.

**After W1 replay confirms success (orphan JOIN query returns 0)**, run Statement 3 to strip CTF keys from `cross_timeframe_context` in all existing rows. Enforce in a transaction:

```sql
BEGIN;

UPDATE intelligence_features
SET cross_timeframe_context = cross_timeframe_context
    - ARRAY['ctf_score', 'ctf_trend_alignment', 'ctf_structure_alignment', 'ctf_regime_agreement']
WHERE cross_timeframe_context ? 'ctf_score';

COMMIT;
```

Set `timescaledb.max_tuples_decompressed_per_dml_transaction = 0` before running to handle compressed chunks.

The `WHERE cross_timeframe_context ? 'ctf_score'` predicate makes this idempotent — safe to re-run if the transaction was interrupted.

**Post-Statement-3 spot check:**
```sql
-- Must return 0
SELECT COUNT(*) FROM intelligence_features WHERE cross_timeframe_context ? 'ctf_score';

-- Sample 10 recent rows — cross_timeframe_context must NOT contain ctf_score key
SELECT ts, symbol, tf, cross_timeframe_context
FROM intelligence_features
ORDER BY ts DESC LIMIT 10;
```

---

## Execution Order

```
W6 → W5 → W4 → W3 → W2 (2a + 2b) → deploy → W1 → Migration 130 Statement 3
```

**Phase 1 — Code changes (commit to branch, merge, deploy):**
W6, W5, W4, W3, W2a, W2b are all code changes. Commit atomically in one PR. The JSONB write path fix (W2b) must be running before W1.

**Phase 2 — Operational (run after deploy):**
W1 replay. Run with Kafka consumer on the gap window. Confirm orphan count = 0.

**Phase 3 — Cleanup:**
Migration 130 Statement 3, inside a transaction. Run spot-check queries after commit.

---

## Verification Checklist

**W2 — Schema guard:**
- [ ] feature_writer crashes at startup with RuntimeError when a required column is missing (test by temporarily dropping a column in dev, confirming the error message names the column and migration)
- [ ] feature_writer starts normally after migration 130 columns are present

**W3 — Graceful shutdown:**
- [ ] `systemctl stop indicagent-intelligence-pipeline` completes within 5s with NO SIGKILL in journalctl — tested while Kafka is IDLE (no messages flowing). This is the critical case. If the test only passes when messages are flowing, 3b is incomplete.
- [ ] No Kafka offset skew after stop/start cycle (consumer resumes from correct offset)

**W4 — FVGFill disabled:**
- [ ] Zero FVGFill circuit breaker events in intelligence_pipeline.log after restart
- [ ] `grep -r "fvg_fill\|FVGFill" tests/` sweep done; all affected test assertions updated and green

**W5 — validate_signal observability:**
- [ ] `validate_signal` unit tests green (no tuple-unpacking breakage)
- [ ] `executor.schema_violation` log events now include `reason=` field — confirmed by grep of recent log
- [ ] `if validate_signal(sig):` and `if not validate_signal(sig):` call sites confirmed correct via grep — no false positives

**W1 — Data recovery:**
- [ ] Orphan JOIN query returns 0
- [ ] Spot-check: 5 replayed `intelligence_features` rows in gap window have non-null `ctf_score` where I6 was expected to fire
- [ ] No duplicate `intelligence_features` rows for gap window: `SELECT ts, symbol, tf, COUNT(*) FROM intelligence_features WHERE ts BETWEEN '2026-06-18 11:15:00+00' AND '2026-06-18 19:10:00+00' GROUP BY ts, symbol, tf HAVING COUNT(*) > 1` returns 0 rows

**W2b + Migration 130 Statement 3:**
- [ ] Live feature_writer is no longer writing `ctf_score` key into `cross_timeframe_context`: spot-check 10 recent rows post-deploy, confirm key absent
- [ ] Migration 130 Statement 3 commits without error
- [ ] `SELECT COUNT(*) FROM intelligence_features WHERE cross_timeframe_context ? 'ctf_score'` returns 0

**W6 — Telemetry accuracy:**
- [ ] No `ZeroDivisionError` in plugin_utils error paths after deploy (confirmed by log grep)
- [ ] ATR ratio in stop-correction errors is now a dimensionless float (not a raw price distance)

---

## Out of Scope

- FVGFill at_limit redesign (separate phase; requires trade_framer changes for at_limit entry type)
- Root-cause fixes for schema_violation plugins (W5 instruments first; fixes follow after one session of data with reasons logged)
- Full INSERT contract validation in W2 (the pre-flight check is scoped to Phase 130 regression guard; full column coverage is a future hardening task)
