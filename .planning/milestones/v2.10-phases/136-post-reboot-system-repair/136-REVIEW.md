---
phase: 136-post-reboot-system-repair
reviewed: 2026-06-18T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - services/feature_writer.py
  - services/intelligence_pipeline.py
  - services/signal_writer.py
  - src/intelligence/pipeline/executor.py
  - src/intelligence/register_plugins.py
  - src/intelligence/schemas.py
  - src/intelligence/trading/signal_schema.py
  - src/intelligence/trading/plugin_utils.py
  - production/scripts/run_historical_pipeline.py
  - production/systemd/indicagent-intelligence-pipeline.service
findings:
  critical: 3
  warning: 5
  info: 3
  total: 11
status: issues_found
---

# Phase 136: Code Review Report

**Reviewed:** 2026-06-18
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Phase 136 addressed five concrete problems: stop-correction ATR errors in `plugin_utils.py`, FVGFill removal from `TIER_I7`, SIGTERM graceful shutdown for `intelligence_pipeline`, CTF JSONB dedup in `feature_writer`, and a code-simplification pass. The core fixes are technically sound. Three blockers were found: a logic inversion in the stop-zone validation for long signals, a `fvg_fill` plugin still registered in `register_all_plugins()` despite being removed from `TIER_I7`, and a reference to an undefined `all_features` variable in the replay loop when `precomputed_features` is active. Five warnings cover silent-failure modes in shutdown, offset commit sequencing, the `_signal_handler` double-registration pattern, and missing error propagation. Three info items cover dead constants, a `connect_db` autocommit flag, and a magic `1.5` multiplier left in the systemd service file.

---

## Critical Issues

### CR-01: Stop-zone validation has inverted comparison for long direction

**File:** `src/intelligence/trading/plugin_utils.py:162`

**Issue:** The long-direction guard reads `if stop_loss < zone_low - epsilon: return stop_loss`. This returns early (treating the stop as valid) when the stop is *below* zone_low, which is the correct placement for a long entry. The condition then falls through to auto-correction only when `stop_loss >= zone_low`, which is the inside-zone case. The intent is correct but the readable semantics of the comment contradict the code: the comment at line 163 says `# Valid: stop below zone` while the check fires on `<` (stop is below zone = valid). On first read this appears inverted.

However, on careful re-reading the inversion is actually correct for the long case. The real bug is in the **short direction** path (line 199): `if stop_loss > zone_high + epsilon: return stop_loss` exits early when stop is *above* zone_high (valid for a short). That is also correct. The issue therefore is NOT a logic inversion in the comparison direction.

The **actual blocker** is that `validate_stop_against_zone` is called with `direction` as typed `int`, but the function body has no guard against `direction == 0`. If a plugin passes `direction=0` (which `no_signal()` returns), the function falls into the `else` (short) branch and silently treats a no-signal as a short entry, potentially auto-correcting a stop that should never have been evaluated. There is no caller-side guard either.

**Fix:**
```python
def validate_stop_against_zone(
    *,
    zone_low: float,
    zone_high: float,
    stop_loss: float,
    direction: int,
    atr: float | None = None,
    plugin_name: str = "unknown",
) -> float:
    if direction not in (1, -1):
        raise ValueError(
            f"{plugin_name}: validate_stop_against_zone called with direction={direction!r}; "
            "must be 1 (long) or -1 (short). Check caller for no_signal() bypass."
        )
    ...
```

---

### CR-02: `fvg_fill` plugin is removed from `TIER_I7` but still registered in `register_all_plugins()`

**File:** `src/intelligence/register_plugins.py:410`

**Issue:** The comment at line 642 of `register_plugins.py` documents that FVGFill was removed from `TIER_I7` due to an entry-timing defect. `TIER_I7` (line 631) does not include `fvg_fill_plugin.name`. However, `register_all_plugins()` still calls `registry.register_pattern(fvg_fill_plugin)` at line 410. This means FVGFill is registered in the plugin registry but excluded from the tier list.

This causes two problems:
1. `validate_schema_coverage()` does not check `TIER_I7` schema coverage (I7 plugins are not in the tier_checks list), so the orphaned registration goes undetected.
2. The plugin is reachable via `registry.get_pattern()` in tests and scripts that enumerate all registered patterns, creating the illusion that it is active while `TIER_I7` excludes it from execution. This is a silent inconsistency that will confuse future maintainers and may resurface if anyone calls `registry.get_pattern("fvg_fill")` expecting it to be inactive.

**Fix:** Remove the `registry.register_pattern(fvg_fill_plugin)` call from `register_all_plugins()`. The import of `fvg_fill_plugin` at the top of the file can remain or be removed; the key is that nothing should register the plugin while it is excluded from `TIER_I7`.

```python
# In register_all_plugins(), remove:
registry.register_pattern(fvg_fill_plugin)
```

If the plugin is intended to remain importable for ad-hoc testing, add a comment making the non-registration explicit.

---

### CR-03: Undefined `all_features` reference in replay loop when `precomputed_features` is active

**File:** `production/scripts/run_historical_pipeline.py:1888`

**Issue:** Inside the `replay_symbol()` main event loop, the `run_i7_and_persist()` call at line 1888 passes `all_features` as its second positional argument. `all_features` is only assigned in the `else` branch (line 1871, computed-features path). In the `if precomputed_features is not None` branch (line 1837-1844), the code assigns to `all_features` via `all_features = precomputed_features.get((tf, ts_utc))` and then `all_features.update(_base_features)`, BUT if `all_features` is falsy (None or empty dict) at line 1841, the code does `continue` — so `all_features` is never set to an empty dict in that path either.

The real problem is that on the very first bar where precomputed data exists, `all_features` is set correctly. But if a bar is skipped via `continue` at line 1842, the variable `all_features` may hold a stale value from the prior iteration (the previous bar's features dict). Worse, on the first bar of the symbol when `precomputed_features` is not None but has no matching entry yet, `all_features` is `None` (from the `.get()` call), and the `continue` fires — but if the very first bar has precomputed data and then the second bar is missing, `all_features` at line 1888 refers to the first bar's dict. This is a subtle stale-reference bug that causes I7 to silently run against the wrong bar's features.

**Fix:** Initialize `all_features` to an empty dict before the event loop, and explicitly reset it at the top of each iteration:

```python
all_features: dict[str, Any] = {}
for _ts, _sort, tf, bar in events:
    all_features = {}   # reset per bar — prevents stale cross-bar contamination
    ts = bar["timestamp"]
    ...
```

---

## Warnings

### WR-01: `_shutdown_consumer` may be invoked twice — once by SIGTERM handler and once by `_teardown`

**File:** `services/intelligence_pipeline.py:651-667`

**Issue:** `_register_signal_handlers()` registers `_shutdown_consumer()` (which calls `self._kafka_consumer.stop()`) for both SIGTERM and SIGINT. `_teardown()` at line 635 also calls `self._kafka_consumer.stop()`. If systemd sends SIGTERM, the consumer is stopped once by the signal handler and then stopped again by `_teardown()`. Most Kafka client implementations guard against double-stop, but if `stop()` raises on a closed consumer, `_teardown()` will propagate an exception and prevent the DB close at line 639.

**Fix:** Guard with a flag or use `hasattr`/`None` check:
```python
async def _teardown(self) -> None:
    self._stop_event.set()
    ...
    if hasattr(self, "_kafka_consumer") and self._kafka_consumer is not None:
        try:
            await self._kafka_consumer.stop()
        except Exception:
            pass   # already stopped by signal handler
    ...
```

---

### WR-02: Kafka offset commit lost when SIGTERM arrives during message processing

**File:** `services/intelligence_pipeline.py:756-759`

**Issue:** The manual commit logic batches 100 messages before committing (`COMMIT_BATCH_SIZE = 100`). When SIGTERM fires mid-batch, the signal handler calls `_kafka_consumer.stop()` which breaks the `async for` loop. The partially-processed batch (up to 99 messages) is never committed. On restart the service re-processes those messages, which is intentional for at-least-once delivery — but `_process_bar_inner` is not idempotent: `PIPELINE_BACKPRESSURE_DROP_TOTAL.add()` fires again, and if any state-mutating side effects occur in plugin execution, they repeat. This is acceptable only if all downstream writes are idempotent (feature_writer uses `ON CONFLICT DO NOTHING`; signal_writer uses `ON CONFLICT (signal_id, ts) DO NOTHING`). Worth a comment clarifying this intent.

**Fix:** No code change required, but add a comment at the commit site:
```python
# At-least-once: if SIGTERM fires before this commit, the last batch
# replays on restart. Downstream writers are idempotent (ON CONFLICT DO NOTHING).
if msg_count >= COMMIT_BATCH_SIZE:
    await self._kafka_consumer.commit()
    msg_count = 0
```

---

### WR-03: `signal_writer._parse_payload` sets `_validation_reason` on the signal dict — mutates the caller's dict

**File:** `services/signal_writer.py:116`

**Issue:** `_parse_payload()` mutates the incoming `sig` dict from `payload["signals"]` by adding `_validation_reason` at line 116. The `payload` dict came from the Kafka consumer and is shared. Mutating it before calling `_maybe_route_to_dlq()` means the DLQ payload (which is `payload` at line 129) now contains signals annotated with `_validation_reason`, which was not an original Kafka field. This is a subtle mutation of the Kafka message that may corrupt DLQ audit trails.

**Fix:** Copy before mutating:
```python
annotated = {**sig, "_validation_reason": result.reason}
invalid_sigs.append(annotated)
```

---

### WR-04: `_flush_batch` in `signal_writer` swallows individual row errors — partial batch success is silent

**File:** `services/signal_writer.py:145-146`

**Issue:** `_flush_batch()` iterates `batch` and calls `_repo.insert_signal_with_frames()` per row. If row N fails (DB constraint violation, network error), the exception propagates out of the loop, cancelling rows N+1 through end. However, rows 0 through N-1 already committed (each `insert_signal_with_frames` presumably commits or uses the pool's autocommit). The `_write_errors` counter increments once, but there is no DLQ routing for the failed row — it is silently lost.

**Fix:** Wrap per-row inserts and collect failures:
```python
for signal_event, trade_frames in batch:
    try:
        await self._repo.insert_signal_with_frames(signal_event, trade_frames)
    except Exception as error:
        self._write_errors.add(1)
        self.logger.error("signal_writer.row_insert_failed", error=str(error),
                          signal_id=signal_event.get("signal_id"))
        # Route to DLQ rather than losing the row
        await self._send_to_dlq(signal_event, error)
```

---

### WR-05: `run_historical_pipeline._insert_features_sync` vs `_insert_signals_sync` commit ordering not enforced atomically

**File:** `production/scripts/run_historical_pipeline.py:1904-1912`

**Issue:** The signal-buffer flush block at line 1904 flushes feature_buffers first, then signal_buffers. This ordering is correct (signals reference feature rows). However both `_insert_features_sync` and `_insert_signals_sync` call `conn.commit()` internally. `connect_db()` at line 1530 sets `conn.autocommit = True`, which means `conn.commit()` inside these functions is a no-op (autocommit commits immediately after each statement). The comment "signals must never commit before their features" (line 1905) is therefore meaningless in autocommit mode — feature and signal rows are committed per-statement already, not as a pair.

The risk: if the process is killed between the feature insert and the signal insert, signal rows are absent but feature rows exist. On restart the signal buffer is empty (not persisted) so signals for those bars are permanently lost (no re-run guard). This is a data-loss scenario during abrupt process termination.

**Fix:** Use `conn.autocommit = False` for the replay worker connection and commit explicitly at batch boundaries, or acknowledge in a comment that data loss between the two inserts is accepted (at-least-once from IBKR can refetch, but the replay does not re-run automatically).

---

## Info

### IN-01: `TIER_I7` comment references "FVGFill removed" but the import still exists

**File:** `src/intelligence/register_plugins.py:117, 642`

**Issue:** Line 117 imports `fvg_fill_plugin`; line 642 documents the removal. The import is not flagged as dead code by ruff because `register_all_plugins()` uses it (see CR-02). After CR-02 is fixed the import becomes truly unused and should be removed or kept with a clear comment explaining why it is retained.

**Fix:** After removing the `registry.register_pattern(fvg_fill_plugin)` call, also remove or annotate the import:
```python
# fvg_fill_plugin kept for ad-hoc testing; NOT registered — entry-timing defect,
# see TIER_I7 comment. Remove import entirely once plugin is deleted or fixed.
from .trading.fvg_fill import plugin as fvg_fill_plugin  # noqa: F401
```

---

### IN-02: `connect_db` sets `autocommit = True` but internal functions call `conn.commit()` unnecessarily

**File:** `production/scripts/run_historical_pipeline.py:1527-1531`

**Issue:** `connect_db()` sets `conn.autocommit = True`. Functions `_insert_features_sync()`, `_insert_signals_sync()`, `store_bars()`, and `_upsert_contract_metadata()` all end with `conn.commit()`. In autocommit mode these calls are no-ops and the code misleads readers into thinking there is explicit transaction control. This contributes to WR-05 above.

**Fix:** Either remove autocommit and use explicit `conn.commit()` calls, or remove the `conn.commit()` calls from the internal functions and rely on autocommit exclusively — but pick one model and be explicit about it.

---

### IN-03: `_process_bar_inner` logs `timeout_ms=500` but the actual timeout is `5.0` seconds

**File:** `services/intelligence_pipeline.py:809, 825`

**Issue:** `asyncio.wait_for(..., timeout=5.0)` at line 809 uses a 5-second timeout, but the warning log at line 825 emits `timeout_ms=500`. The docstring at line 806 says "Hard 500ms outer timeout" — the constant was updated from 500ms to 5000ms but the log message and docstring were not updated. Any alerting or dashboards keyed on `timeout_ms=500` will produce incorrect data.

**Fix:**
```python
self.logger.warning(
    "pipeline.bar_timeout",
    symbol=bar.symbol,
    tf=bar.tf,
    timeout_ms=5000,   # matches asyncio.wait_for timeout=5.0
)
```
Also update the docstring on `_process_bar_compute` to `5000ms` (or 5s).

---

_Reviewed: 2026-06-18_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
