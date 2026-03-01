# Data Pipeline Bugfix Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 11 bugs found in the data ingestion, stream processing, and hot/warm/cold storage layers.

**Architecture:** Fixes span 6 files across 3 layers: IBKR data provider, stream pipeline services (feature_writer, tws_daemon), and shared infrastructure (schemas, settings, database_manager). No new abstractions required — all changes are targeted corrections.

**Tech Stack:** Python asyncio, ib_insync, Redis streams, asyncpg/TimescaleDB, pydantic v2

---

## Task 1: Fix `OHLCVBar` field name mismatch — entire intelligence pipeline broken

**Severity:** Critical — every `_publish_intelligence` call raises `ValidationError`, `intelligence:*` streams empty.

**Files:**
- Modify: `src/intelligence/schemas.py:38`

**Change:** Rename field `low` → `l` to match the single-letter convention and fix the constructor call mismatch (all callers already use `l=`).

```python
# Before (line 38):
    low: float

# After:
    l: float
```

**Step 1: Apply the fix**

Edit `src/intelligence/schemas.py` line 38: change `low: float` → `l: float`.

**Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/ -q --tb=short 2>&1 | tail -10
```
Expected: 539 passed.

**Step 3: Verify no other callers use `low=`**

```bash
grep -rn "OHLCVBar(" src/ services/ | grep "low="
```
Expected: no output (all callers use `l=`).

**Step 4: Commit**

```bash
git add src/intelligence/schemas.py
git commit -m "fix(schemas): rename OHLCVBar.low → .l to match all constructor call sites"
```

---

## Task 2: Fix VX futures base symbol (`"VIX"` → `"VX"`)

**Severity:** Critical — VXH6 never qualifies with IBKR, never subscribed.

**Files:**
- Modify: `src/config/settings.py:121-124`

**Change:**
```python
# Before:
            # Volatility — March 2026 (IBKR uses "VIX" not "VX")
            Instrument(
                symbol="VXH6", base="VIX", exchange="CFE", expiry="20260318",

# After:
            # Volatility — March 2026
            Instrument(
                symbol="VXH6", base="VX", exchange="CFE", expiry="20260318",
```

**Step 1: Apply the fix**

Edit `src/config/settings.py` lines 121-123.

**Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short -k "settings or config or instrument" 2>&1 | tail -10
```

**Step 3: Commit**

```bash
git add src/config/settings.py
git commit -m "fix(settings): VXH6 base symbol VIX → VX (IBKR requires VX for VIX futures)"
```

---

## Task 3: Fix blocking IBKR calls inside async functions

**Severity:** Critical — `reqHistoricalData` and `reqContractDetails` block the event loop during calls.

**Files:**
- Modify: `src/providers/ibkr.py:157` (fetch_historical_bars)
- Modify: `src/providers/ibkr.py:210` (qualify_instrument)
- Modify: `src/providers/ibkr.py:312` (resolve_instrument)

**Change:** Replace sync calls with their async equivalents (confirmed available in ib_insync ≥0.9.86).

**Line 157 — `fetch_historical_bars`:**
```python
# Before:
            ib_bars = self._ib.reqHistoricalData(
                contract,
                endDateTime=chunk_end.strftime("%Y%m%d %H:%M:%S"),
                durationStr=duration_str,
                barSizeSetting=_TF_TO_IB[timeframe],
                whatToShow=what_to_show,
                useRTH=False,
                formatDate=1,
            )

# After:
            ib_bars = await self._ib.reqHistoricalDataAsync(
                contract,
                endDateTime=chunk_end.strftime("%Y%m%d %H:%M:%S"),
                durationStr=duration_str,
                barSizeSetting=_TF_TO_IB[timeframe],
                whatToShow=what_to_show,
                useRTH=False,
                formatDate=1,
            )
```

**Line 210 — `qualify_instrument`:**
```python
# Before:
            details = self._ib.reqContractDetails(contract)

# After:
            details = await self._ib.reqContractDetailsAsync(contract)
```

**Line 312 — `resolve_instrument`:**
```python
# Before:
            details = self._ib.reqContractDetails(contract)

# After:
            details = await self._ib.reqContractDetailsAsync(contract)
```

**Step 1: Apply all three changes to `src/providers/ibkr.py`**

**Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short -k "ibkr or provider" 2>&1 | tail -10
```

**Step 3: Commit**

```bash
git add src/providers/ibkr.py
git commit -m "fix(ibkr): use async reqHistoricalDataAsync/reqContractDetailsAsync to avoid blocking event loop"
```

---

## Task 4: Fix `feature_writer_service` consumer group restart + batch loss bugs

**Severity:** High (2 bugs in same file, fix together)

**Files:**
- Modify: `services/feature_writer_service.py:282-284` (consumer group except block)
- Modify: `services/feature_writer_service.py:351-369` (buffer cleared before write)

### Bug A: Missing `xgroup_setid` on restart

```python
# Before (lines 282-284):
                except Exception:
                    # Group already exists — normal on restart
                    pass

# After:
                except Exception:
                    # Group already exists — reset position to skip stale backlog
                    await self.redis_client.xgroup_setid(
                        stream_name, CONSUMER_GROUP, "$"
                    )
```

### Bug B: Buffer cleared before DB write — batch lost on error

```python
# Before (lines 351-369):
        params = list(self._buffer)
        self._buffer.clear()          # ← cleared BEFORE write
        self._last_flush = time.monotonic()

        try:
            await self.db_manager.execute_batch(_INSERT_FEATURE_SQL, params)
            ...
        except Exception as e:
            self.logger.error("Batch write failed", error=str(e), rows=len(params))
            ...

# After:
        params = list(self._buffer)
        self._last_flush = time.monotonic()

        try:
            await self.db_manager.execute_batch(_INSERT_FEATURE_SQL, params)
            self._buffer.clear()      # ← only cleared after successful write
            ...
        except Exception as e:
            self.logger.error("Batch write failed", error=str(e), rows=len(params))
            # params remain in self._buffer for retry on next flush cycle
            ...
```

**Step 1: Apply both changes to `services/feature_writer_service.py`**

**Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short -k "feature_writer" 2>&1 | tail -10
```

**Step 3: Commit**

```bash
git add services/feature_writer_service.py
git commit -m "fix(feature_writer): add xgroup_setid on restart + move buffer.clear() after successful DB write"
```

---

## Task 5: Fix parse failure logging in `feature_writer_service`

**Severity:** High — parse failures are silently acked with no observable signal.

**Files:**
- Modify: `services/feature_writer_service.py:297-300`

**Change:** Add a warning log (with distinct level) so parse failures are distinguishable from processing errors:

```python
# Before:
            event = _parse_intelligence_event(fields)
            if event is None:
                # Malformed or missing event — ack-and-skip (do not crash)
                return True

# After:
            event = _parse_intelligence_event(fields)
            if event is None:
                self.logger.warning(
                    "Malformed intelligence event — acked and skipped",
                    stream=stream_name,
                    message_id=message_id,
                )
                if hasattr(self, "error_count_total"):
                    self.error_count_total.inc()
                return True
```

**Step 1: Apply the change**

**Step 2: Commit**

```bash
git add services/feature_writer_service.py
git commit -m "fix(feature_writer): log warning with stream/message_id when parse fails, increment error counter"
```

---

## Task 6: Fix provisional bar hour boundary bug in TWS daemon

**Severity:** High — at hour rollover, minute 0 of current hour matches minute 0 of previous hour.

**Files:**
- Modify: `production/daemons/high_frequency_tws_daemon.py:482-483` (`_update_tick_accumulator`)
- Modify: `production/daemons/high_frequency_tws_daemon.py:512-516` (`_flush_provisional_bars`)

**Change:** Store `(hour, minute)` tuple instead of bare `.minute` int:

```python
# _update_tick_accumulator — line 482:
# Before:
        current_minute = now.minute
        if symbol not in self.tick_accum or self.tick_accum[symbol].get("minute") != current_minute:
            self.tick_accum[symbol] = {
                "minute": current_minute,

# After:
        current_minute = (now.hour, now.minute)
        if symbol not in self.tick_accum or self.tick_accum[symbol].get("minute") != current_minute:
            self.tick_accum[symbol] = {
                "minute": current_minute,
```

```python
# _flush_provisional_bars — lines 512-513:
# Before:
        closed_minute_ts = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
        closed_minute = closed_minute_ts.minute

# After:
        closed_minute_ts = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
        closed_minute = (closed_minute_ts.hour, closed_minute_ts.minute)
```

**Step 1: Apply both changes to `production/daemons/high_frequency_tws_daemon.py`**

**Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short -k "tws or daemon" 2>&1 | tail -10
```

**Step 3: Commit**

```bash
git add production/daemons/high_frequency_tws_daemon.py
git commit -m "fix(tws_daemon): store (hour, minute) tuple in tick_accum to avoid hour-boundary bar mismatch"
```

---

## Task 7: Fix provisional bar volume (sum tick sizes, not delta)

**Severity:** High — `vol_current - vol_start` is meaningless for per-trade tick sizes.

**Files:**
- Modify: `production/daemons/high_frequency_tws_daemon.py:490-501` (`_update_tick_accumulator`)
- Modify: `production/daemons/high_frequency_tws_daemon.py:520` (`_flush_provisional_bars`)

**Change:** Replace the cumulative delta pattern with a running sum:

```python
# _update_tick_accumulator — initialization block (~line 484):
# Before:
                "vol_start": volume or 0,
                "vol_current": volume or 0,

# After:
                "vol_total": volume or 0,
```

```python
# _update_tick_accumulator — update block (lines 500-501):
# Before:
            if volume is not None:
                acc["vol_current"] = volume

# After:
            if volume is not None:
                acc["vol_total"] = acc.get("vol_total", 0) + volume
```

```python
# _flush_provisional_bars — line 520:
# Before:
            volume = max(0, acc["vol_current"] - acc["vol_start"])

# After:
            volume = acc.get("vol_total", 0)
```

**Step 1: Apply all three changes to `production/daemons/high_frequency_tws_daemon.py`**

**Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short -k "tws or daemon" 2>&1 | tail -10
```

**Step 3: Commit**

```bash
git add production/daemons/high_frequency_tws_daemon.py
git commit -m "fix(tws_daemon): sum per-tick volumes instead of vol_current-vol_start delta for provisional bars"
```

---

## Task 8: Fix rollback exception masking original in `database_manager`

**Severity:** Medium — if rollback itself raises, the root-cause exception is lost.

**Files:**
- Modify: `src/core/database_manager.py:85-87`

**Change:**
```python
# Before:
            except Exception:
                await tr.rollback()
                raise

# After:
            except Exception as exc:
                try:
                    await tr.rollback()
                except Exception:
                    pass  # rollback failed; re-raise original exception
                raise exc
```

**Step 1: Apply the change**

**Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short -k "database" 2>&1 | tail -10
```

**Step 3: Commit**

```bash
git add src/core/database_manager.py
git commit -m "fix(database_manager): preserve original exception when rollback itself raises"
```

---

## Task 9: Fix `os.getenv` validators in `settings.py`

**Severity:** Medium — `os.getenv` bypasses `.env` file, violates project rule.

**Files:**
- Modify: `src/config/settings.py` — `ib_host` and `ib_port` field definitions + validators

**Change:** Replace the `field_validator` approaches with pydantic v2 `AliasChoices`. First check how the fields are currently declared:

```bash
grep -n "ib_host\|ib_port\|IB_HOST\|IBKR_HOST" src/config/settings.py | head -20
```

Then update the field declarations to use `AliasChoices` from `pydantic` and remove the `field_validator` methods:

```python
# Add to imports:
from pydantic import AliasChoices, Field

# Field declarations (find the ib_host and ib_port fields and update):
    ib_host: str = Field(
        default="127.0.0.1",
        validation_alias=AliasChoices("ib_host", "IBKR_HOST", "IB_HOST"),
    )
    ib_port: int = Field(
        default=7497,
        validation_alias=AliasChoices("ib_port", "IBKR_PORT", "IB_PORT"),
    )

# Remove: ib_host_aliases and ib_port_aliases field_validator methods
```

**Step 1: Read the full field declarations for ib_host and ib_port**

```bash
grep -n "ib_host\|ib_port\|field_validator\|ib_host_aliases\|ib_port_aliases" src/config/settings.py
```

**Step 2: Apply the change — update field declarations and remove validators**

**Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short -k "settings or config" 2>&1 | tail -10
```

**Step 4: Commit**

```bash
git add src/config/settings.py
git commit -m "fix(settings): replace os.getenv validators with AliasChoices for ib_host/ib_port"
```

---

## Task 10: Add clarifying comment for sub-day chunk advance in `ibkr.py`

**Severity:** Medium — code is correct by coincidence, fragile if logic changes.

**Files:**
- Modify: `src/providers/ibkr.py:180`

**Change:**
```python
# Before:
            chunk_start = chunk_end + timedelta(days=1)

# After:
            # Advance by 1 day. For sub-day windows this overshoots past `end`,
            # which exits the loop on the next iteration check — correct by design.
            chunk_start = chunk_end + timedelta(days=1)
```

**Step 1: Apply the comment**

**Step 2: Commit**

```bash
git add src/providers/ibkr.py
git commit -m "docs(ibkr): clarify sub-day chunk advance is correct by design (exits loop on next check)"
```

---

## Final Verification

```bash
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -5
.venv/bin/ruff check . 2>&1 | tail -5
```

Expected: all passing, 0 ruff errors.

Then push:
```bash
git push origin main
```
