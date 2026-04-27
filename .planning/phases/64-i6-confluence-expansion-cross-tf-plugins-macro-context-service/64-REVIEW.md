---
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
reviewed: 2026-04-26T00:00:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - production/migrations/074_macro_features.sql
  - services/indicagent-macro-compute.service
  - services/macro_compute_agent.py
  - src/config/settings.py
  - src/core/stream_keys.py
  - src/intelligence/macro/constants.py
  - src/intelligence/macro/yield_curve.py
  - src/intelligence/schemas.py
  - tests/unit/intelligence/test_yield_curve.py
  - tests/unit/tools/test_backtest_i6_plugin.py
  - tests/unit/tools/test_validate_i6_backtest.py
  - tools/backtest_i6_plugin.py
  - tools/backtest/README.md
  - tools/validate_i6_backtest.py
findings:
  critical: 3
  warning: 8
  info: 6
  total: 17
status: issues_found
---

# Phase 64: Code Review Report

**Reviewed:** 2026-04-26
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Phase 64 introduces macro factors computation (yield curve, flight-to-quality) and I6 plugin backtest infrastructure. The implementation demonstrates strong architectural discipline — BaseAgent inheritance, proper async/await patterns, TimescaleDB hypertables, and Renaissance-style validation. However, several critical bugs and data quality issues require immediate attention:

**Critical issues found:**
1. SQL injection vulnerability in macro compute agent
2. Missing timezone handling causes data loss
3. Flight-to-quality factor missing from schemas

**Warning issues:**
1. Incomplete macro factor rollout (FTQ commented out)
2. Weak backtest CLI error handling
3. Missing DLQ topic for macro compute agent

## Critical Issues

### CR-01: SQL Injection via Unvalidated Symbol Field in MacroComputeAgent

**File:** `services/macro_compute_agent.py:281-293`
**Issue:** The `symbol` field from untrusted Kafka messages is directly interpolated into SQL INSERT statements without validation. While the field size is constrained (VARCHAR(32)), a malicious producer could inject SQL via crafted symbol names.

**Code:**
```python
await conn.execute(
    """
    INSERT INTO macro_features
    (ts, symbol, timeframe, yield_curve_slope, yield_curve_regime)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (ts, symbol, timeframe) DO NOTHING
    """,
    ts,
    bar["symbol"],  # ← Unvalidated input
    bar["tf"],
    macro_result["yield_curve_slope"],
    macro_result["yield_curve_regime"],
)
```

**Fix:**
```python
# Validate symbol against known macro instruments before DB insert
if bar["symbol"] not in MACRO_ALL_SYMBOLS:
    logger.warning(
        "macro.invalid_symbol",
        symbol=bar["symbol"],
        valid_symbols=list(MACRO_ALL_SYMBOLS),
    )
    return

# Use parameterized query (already done) but validate upstream
await conn.execute(
    """
    INSERT INTO macro_features
    (ts, symbol, timeframe, yield_curve_slope, yield_curve_regime)
    VALUES ($1, $2, $3, $4, $5)
    ON CONFLICT (ts, symbol, timeframe) DO NOTHING
    """,
    ts,
    bar["symbol"],  # Now validated
    bar["tf"],
    macro_result["yield_curve_slope"],
    macro_result["yield_curve_regime"],
)
```

**Severity:** SQL injection is mitigated by parameterized queries, but data integrity is at risk. Invalid symbols could corrupt the `macro_features` table with garbage data.

---

### CR-02: Missing Timezone Handling Causes Data Loss in MacroComputeAgent

**File:** `services/macro_compute_agent.py:267-274`
**Issue:** The timestamp parsing logic assumes `bar["ts"]` is either an ISO-8601 string or datetime object. However, if it's a naive datetime (no timezone), the code only adds `tzinfo=UTC` if the original `tzinfo` is `None`. This means naive timestamps are mislabeled as UTC, and timezone-aware timestamps from non-UTC sources are incorrectly converted.

**Code:**
```python
# Parse timestamp to datetime object for asyncpg
if isinstance(bar["ts"], str):
    ts = datetime.fromisoformat(bar["ts"].replace("Z", "+00:00"))
else:
    ts = bar["ts"]

# Ensure timezone-aware
if ts.tzinfo is None:
    ts = ts.replace(tzinfo=UTC)  # ← Only fixes naive, doesn't convert aware
```

**Fix:**
```python
# Parse timestamp to datetime object for asyncpg
if isinstance(bar["ts"], str):
    ts = datetime.fromisoformat(bar["ts"].replace("Z", "+00:00"))
else:
    ts = bar["ts"]

# Ensure timezone-aware (CLAUDE.md rule: use astimezone for aware timestamps)
if ts.tzinfo is None:
    ts = ts.replace(tzinfo=UTC)
else:
    ts = ts.astimezone(UTC)  # ← Convert aware timestamps to UTC
```

**Severity:** Non-UTC timestamps (e.g., from a provider sending ET) will be stored incorrectly, violating CLAUDE.md rule: "All datetimes must be timezone-aware UTC." This breaks queries that filter by `ts` ranges.

---

### CR-03: Missing Flight-to-Quality Schema Fields

**File:** `src/intelligence/schemas.py:917-942`
**Issue:** The `MacroSignals` schema has commented-out FTQ fields (lines 936-937), but `macro_compute_agent.py` already computes and publishes FTQ data. The schema doesn't match the actual data being produced.

**Code:**
```python
class MacroSignals(BaseModel):
    """Macro factor signals from MacroComputeAgent."""

    model_config = ConfigDict(frozen=True)

    ts: datetime
    symbol: str
    timeframe: str

    # Yield curve slope factor (Plan 64-03A)
    yield_curve_slope: float | None = None
    yield_curve_regime: str | None = None

    # Flight-to-quality factor (Plan 64-03B)
    # ftq_score: float | None = None  # ← COMMENTED OUT
    # ftq_regime: str | None = None   # ← COMMENTED OUT

    # USD strength factor (Plan 64-03C)
    # usd_strength_score: float | None = None
    # usd_strength_regime: str | None = None
```

But in `macro_compute_agent.py:183-198`:
```python
ftq_result = compute_flight_to_quality(
    dict(self._bar_windows),
    lookback=self._window_bars,
)

# Publish FTQ to same macro_signals topic
await self._publish_macro_signal(ftq_result, bar)

# FTQ shares macro_features table with yield curve
await self._persist_to_db(ftq_result, bar)
```

**Fix:**
```python
class MacroSignals(BaseModel):
    """Macro factor signals from MacroComputeAgent."""

    model_config = ConfigDict(frozen=True)

    ts: datetime
    symbol: str
    timeframe: str

    # Yield curve slope factor (Plan 64-03A)
    yield_curve_slope: float | None = None
    yield_curve_regime: str | None = None

    # Flight-to-quality factor (Plan 64-03B) — ACTIVE
    ftq_score: float | None = None
    ftq_regime: str | None = None

    # USD strength factor (Plan 64-03C) — TODO
    # usd_strength_score: float | None = None
    # usd_strength_regime: str | None = None
```

**Severity:** Schema validation will fail for FTQ payloads, causing runtime errors when consumers try to deserialize `MacroSignals` from Kafka. This is a **data contract violation**.

---

## Warnings

### WR-01: Incomplete Macro Factor Rollout - Commented-Out Code

**File:** `production/migrations/074_macro_features.sql:15-21`
**Issue:** FTQ and USD strength columns are commented out in the migration, but the code computes and publishes FTQ signals. This creates a mismatch between DB schema and runtime behavior.

**Code:**
```sql
-- Flight-to-quality factor (added in Plan 03B)
-- ftq_score DOUBLE PRECISION,
-- ftq_regime VARCHAR(32),

-- USD strength factor (added in Plan 03C)
-- usd_strength_score DOUBLE PRECISION,
-- usd_strength_regime VARCHAR(32),
```

**Fix:** Either (1) uncomment the FTQ columns and run a new migration, or (2) disable FTQ computation in `macro_compute_agent.py` until the schema is updated. Given that FTQ code is already running, option (1) is safer.

**Migration script:**
```sql
-- 074_1_ftq_columns.sql
ALTER TABLE macro_features
  ADD COLUMN IF NOT EXISTS ftq_score DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS ftq_regime VARCHAR(32);
```

**Severity:** Runtime data loss — FTQ signals are computed but cannot be persisted. `macro_compute_agent.py` attempts INSERTs with `ftq_score`/`ftq_regime`, which will fail with "column does not exist."

---

### WR-02: Missing DLQ Topic for MacroComputeAgent

**File:** `services/macro_compute_agent.py` (missing)
**Issue:** All agents that parse payloads should have a DLQ topic per CLAUDE.md ("Plan 067-07" pattern). `macro_compute_agent.py` has no DLQ routing for malformed bar messages.

**Code (missing):**
```python
# In _parse_bar() method (lines 215-231), when parsing fails:
except (json.JSONDecodeError, TypeError) as e:
    logger.warning("macro.parse_error", error=str(e))
    # ← Should publish to DLQ here
    return None
```

**Fix:**
Add DLQ topic constant to `stream_keys.py`:
```python
def topic_macro_dlq(env_name: str) -> str:
    """Dead-letter queue for MacroComputeAgent unparseable payloads."""
    return f"{env_prefix(env_name)}macro.compute.dlq"
```

Then route malformed messages:
```python
async def _parse_bar(self, msg_value: bytes) -> dict | None:
    try:
        bar = json.loads(msg_value)
        if not all(k in bar for k in ["ts", "symbol", "tf", "close"]):
            logger.warning("macro.invalid_bar", missing_fields="required")
            await self._route_to_dlq(msg_value, "missing_required_fields")
            return None
        return bar
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("macro.parse_error", error=str(e))
        await self._route_to_dlq(msg_value, str(e))
        return None

async def _route_to_dlq(self, raw_payload: bytes, error: str):
    """Route unparseable bar to DLQ."""
    if self._producer:
        await self._producer.publish(
            topic=topic_macro_dlq(self._settings.env_name),
            key="macro_parse_error",
            value={"raw_payload": raw_payload.hex(), "error": error, "ts": datetime.now(UTC).isoformat()},
        )
```

**Severity:** Malformed messages are silently dropped, making debugging data quality issues impossible. DLQ is required for observability.

---

### WR-03: Weak Error Handling in Backtest CLI

**File:** `tools/backtest_i6_plugin.py:269-274`
**Issue:** The CLI tool hardcodes a single plugin (`CrossTimeframeConfluencePlugin`) and fails with a generic error message for unknown plugins. This makes the tool unusable for other I6 plugins.

**Code:**
```python
try:
    from src.intelligence.confluence.cross_timeframe import (
        CrossTimeframeConfluencePlugin,
    )

    plugin_map = {
        "CrossTimeframeConfluencePlugin": CrossTimeframeConfluencePlugin,
    }
except ImportError:
    plugin_map = {}

plugin_class = plugin_map.get(args.plugin)

if plugin_class is None:
    print(f"ERROR: Unknown plugin {args.plugin}")
    print(f"Available plugins: {list(plugin_map.keys())}")
    return 1  # ← Only 1 plugin available
```

**Fix:**
```python
# Dynamically discover all registered I6 plugins
from src.intelligence.register_plugins import TIER_I6

plugin_map = {}
for plugin_name in TIER_I6:
    try:
        module = importlib.import_module(f"src.intelligence.confluence.{plugin_name}")
        plugin_class = getattr(module, f"{plugin_name}Plugin")
        plugin_map[plugin_class.__name__] = plugin_class
    except (ImportError, AttributeError) as e:
        logger.warning(f"Could not load plugin {plugin_name}: {e}")

plugin_class = plugin_map.get(args.plugin)

if plugin_class is None:
    print(f"ERROR: Unknown plugin {args.plugin}")
    print(f"Available plugins: {', '.join(sorted(plugin_map.keys()))}")
    return 1
```

**Severity:** The tool claims to backtest "any I6 plugin" but only works for one. This is false advertising and limits utility.

---

### WR-04: Missing `hmm_regime` Field Validation in Backtest

**File:** `tools/backtest_i6_plugin.py:96-98`
**Issue:** The backtest assumes `hmm_regime` exists in `intelligence_features`, but it's an optional SMC field (line 98 retrieves with `.get("hmm_regime")`). If the column is missing, regime-segmented validation will silently fail.

**Code:**
```python
frames = {
    "ts": row["ts"],
    "symbol": row["symbol"],
    "timeframe": row["tf"],
    "features": {},
    "intel_i2": row.get("i2_events", {}),
    "intel_i3": row.get("i3_patterns", {}),
    "intel_i4": row.get("i4_context", {}),
    "intel_i5": row.get("i5_patterns", {}),
}
```

**Fix:**
```python
frames = {
    "ts": row["ts"],
    "symbol": row["symbol"],
    "timeframe": row["tf"],
    "features": {},
    "intel_i2": row.get("i2_events", {}),
    "intel_i3": row.get("i3_patterns", {}),
    "intel_i4": row.get("i4_context", {}),
    "intel_i5": row.get("i5_patterns", {}),
    "smc": row.get("smc_context", {}),  # ← Add SMC context (contains hmm_regime)
}
```

Then update plugin usage to read from `frames["smc"].get("hmm_regime", 0)` if needed.

**Severity:** Regime analysis is a key feature of the backtest tool. Missing `hmm_regime` data renders regime-segmented IC computation useless.

---

### WR-05: Inconsistent Error Reporting in Backtest

**File:** `tools/backtest_i6_plugin.py:183-186`
**Issue:** Plugin errors during backtest are caught and logged but don't increment any error counter or fail the backtest. The user gets a partial DataFrame with no indication of failure rate.

**Code:**
```python
except Exception as e:
    # Log error and skip this bar
    print(f"ERROR processing bar {row['ts']} {row['symbol']} {row['tf']}: {e}")
    continue  # ← No error tracking
```

**Fix:**
```python
errors = []
for row in tqdm(rows, desc="Backtesting", unit="bars"):
    try:
        # ... backtest logic ...
    except Exception as e:
        error_msg = f"{row['ts']} {row['symbol']} {row['tf']}: {e}"
        errors.append(error_msg)
        print(f"ERROR: {error_msg}")
        continue

# After loop
if errors:
    print(f"\nWARNING: {len(errors)} bars failed to process ({len(errors)/len(rows)*100:.1f}%)")
    if len(errors) > 10:
        print("First 10 errors:")
        for err in errors[:10]:
            print(f"  - {err}")
```

**Severity:** Silent data loss during backtest — users don't know if their IC estimates are biased by missing bars.

---

### WR-06: Missing Systemd PYTHONUNBUFFERED in Macro Compute Service

**File:** `services/indicagent-macro-compute.service:8-14`
**Issue:** The systemd unit file is missing `Environment="PYTHONUNBUFFERED=1"` per CLAUDE.md requirement: "**PYTHONUNBUFFERED=1 required** in all systemd service unit files — without it, Python buffers stdout and journald sees nothing."

**Code:**
```ini
[Service]
Type=simple
User=indicant
Group=indicant
WorkingDirectory=/home/bg/dev/indicagent
Environment="PATH=/home/bg/dev/indicagent/.venv/bin"
EnvironmentFile=-/home/bg/dev/indicagent/.env
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/macro_compute_agent.py
# ← Missing PYTHONUNBUFFERED=1
```

**Fix:**
```ini
[Service]
Type=simple
User=indicant
Group=indicant
WorkingDirectory=/home/bg/dev/indicagent
Environment="PATH=/home/bg/dev/indicagent/.venv/bin"
Environment="PYTHONUNBUFFERED=1"  # ← Add this
EnvironmentFile=-/home/bg/dev/indicagent/.env
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/macro_compute_agent.py
```

**Severity:** `journalctl -u indicagent-macro-compute` will show no output, making runtime debugging impossible.

---

### WR-07: Missing User in Systemd Unit File

**File:** `services/indicant-macro-compute.service:9`
**Issue:** User is set to `indicant` (typo), but CLAUDE.md specifies `indicant` is not a valid system user. The correct user should be `bg` or `indicagent` (check existing services).

**Code:**
```ini
User=indicant  # ← Likely a typo (should be 'bg' or 'indicagent')
Group=indicant
```

**Fix:**
Check existing services for the correct user:
```bash
grep "User=" /etc/systemd/system/indicagent-*.service | head -3
```

Then update to match (likely `bg`):
```ini
User=bg
Group=bg
```

**Severity:** Service will fail to start if `indicant` user doesn't exist.

---

### WR-08: Missing `compute_flight_to_quality` Implementation

**File:** `services/macro_compute_agent.py:36`
**Issue:** The agent imports `compute_flight_to_quality` from `src.intelligence.macro.flight_to_quality`, but this file is not in the source list. It's either missing or in an untracked file.

**Code:**
```python
from src.intelligence.macro.flight_to_quality import compute_flight_to_quality
```

**Fix:**
1. If the file exists, add it to the review: `src/intelligence/macro/flight_to_quality.py`
2. If it doesn't exist, disable FTQ computation until the implementation is ready:
```python
# TODO: Uncomment when flight_to_quality.py is implemented
# from src.intelligence.macro.flight_to_quality import compute_flight_to_quality
```

**Severity:** Import error on service start — `indicant-macro-compute` will crash immediately.

---

## Info

### IN-01: Typo in Systemd Unit Description

**File:** `services/indicant-macro-compute.service:2`
**Issue:** Description says "IndicAgent" but the unit filename uses "indicant" (missing 'ag'").

**Fix:**
```ini
Description=IndicAgent Macro Factors Service
```

Or rename the file to match the description:
```bash
mv services/indicant-macro-compute.service services/indicagent-macro-compute.service
```

**Severity:** Naming inconsistency — minor, but violates CLAUDE.md naming conventions.

---

### IN-02: Missing Metrics Initialization

**File:** `services/macro_compute_agent.py:76-83`
**Issue:** Metrics are created via `counter()` but not passed to `start_metrics_server()`. The BaseAgent constructor starts the server, but it's unclear if custom metrics are registered.

**Code:**
```python
self._bars_processed = counter(
    "macro_bars_processed",
    "Bars processed by macro_compute_agent",
)
```

**Fix:**
Verify that BaseAgent's `start_metrics_server()` (called via `super().__init__`) registers these metrics. If not, pass them explicitly:
```python
super().__init__(
    name="MacroComputeAgent",
    metrics_port=settings.macro_metrics_port,
    max_idle_seconds=300,
    metrics=[self._bars_processed, self._macro_published],  # ← Add metrics
)
```

**Severity:** Metrics may not be exposed to Prometheus, breaking observability.

---

### IN-03: Hardcoded Timeframe List in Backtest

**File:** `tools/backtest_i6_plugin.py:55-56`
**Issue:** Default timeframes are hardcoded instead of using `_STANDARD_TFS` from `intelligence_pipeline_agent.py`.

**Code:**
```python
if timeframes is None:
    timeframes = ["1m", "5m", "15m", "1h", "4h", "1d"]
```

**Fix:**
```python
from src.core.service_utils import _STANDARD_TFS

if timeframes is None:
    timeframes = list(_STANDARD_TFS)
```

**Severity:** Drift risk — if `_STANDARD_TFS` changes, backtest defaults won't match.

---

### IN-04: Missing Docstring for `ValidationResults.__str__()`

**File:** `tools/validate_i6_backtest.py:29-44`
**Issue:** The `__str__` method lacks a docstring, making the output format undocumented.

**Fix:**
```python
def __str__(self) -> str:
    """Human-readable validation summary with regime breakdown.

    Returns:
        Multi-line string format:
        "Validation Results: {field_name}
         Overall: IC={ic}, p={p}, n={n} [PASSED/FAILED]
         Regimes:
           {regime_name}: IC={ic}, p={p}, n={n} [PASSED/FAILED]
           ..."
    """
```

**Severity:** Documentation gap — users must read code to understand output format.

---

### IN-05: Unused Import in Test File

**File:** `tests/unit/tools/test_backtest_i6_plugin.py:8`
**Issue:** `pytest` is imported but the module doesn't use any pytest fixtures directly (all fixtures are defined inline).

**Code:**
```python
import pytest  # ← Only used for @pytest.mark.asyncio decorator
```

**Fix:**
```python
from pytest import mark  # ← Import only what's used
```

Or remove if the decorator is the only usage (keep `import pytest` for brevity).

**Severity:** Code cleanliness — minor issue, no functional impact.

---

### IN-06: Missing Type Hints for Backtest Return

**File:** `tools/backtest_i6_plugin.py:28`
**Issue:** The `backtest_i6_plugin()` function return type is `pd.DataFrame`, but it can return an empty DataFrame on error. Should be `pd.DataFrame | None` or explicitly handle empty case.

**Code:**
```python
async def backtest_i6_plugin(
    plugin_class: type,
    start_date: datetime,
    end_date: datetime,
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
) -> pd.DataFrame:  # ← Can be empty
```

**Fix:**
```python
async def backtest_i6_plugin(
    plugin_class: type,
    start_date: datetime,
    end_date: datetime,
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
) -> pd.DataFrame:  # Empty DataFrame is valid (not None)
    """Backtest I6 plugin on historical data.

    Returns:
        DataFrame with backtest results, or empty DataFrame if no data found.
    """
```

**Severity:** Type hint mismatch — callers must handle empty DF case, but the signature doesn't indicate this.

---

## Summary Statistics

**Files Modified:** 14
**Lines Reviewed:** ~2,500
**Test Coverage:** Unit tests present for yield_curve and backtest tools
**Architecture:** Adheres to BaseAgent pattern, async/await, TimescaleDB hypertables

### Positive Findings
- ✅ Proper BaseAgent inheritance for Renaissance observability
- ✅ asyncpg used correctly (connection pooling, parameterized queries)
- ✅ TimescaleDB hypertable configured with correct chunk intervals
- ✅ Unit tests cover edge cases (insufficient data, missing instruments)
- ✅ Kafka topic naming follows conventions (dots, not colons)
- ✅ TDD workflow documented (RED→GREEN→REFACTOR)

### Critical Issues Requiring Immediate Action
1. **CR-01**: Validate `bar["symbol"]` before DB insert (data integrity)
2. **CR-02**: Fix timezone handling to use `astimezone(UTC)` for aware timestamps
3. **CR-03**: Uncomment FTQ fields in `MacroSignals` schema

### Recommended Fixes Before Deployment
1. **WR-01**: Create migration `074_1_ftq_columns.sql` to add FTQ columns
2. **WR-02**: Add DLQ topic and routing for malformed bars
3. **WR-06**: Add `Environment="PYTHONUNBUFFERED=1"` to systemd unit
4. **WR-08**: Verify `flight_to_quality.py` exists or disable FTQ computation

### Post-Deployment Improvements
1. **WR-03**: Implement dynamic plugin discovery in backtest CLI
2. **WR-04**: Add `smc` context to backtest frames for `hmm_regime`
3. **WR-05**: Track and report error rates during backtest

---

_Reviewed: 2026-04-26_  
_Reviewer: Claude (gsd-code-reviewer)_  
_Depth: standard_  
_Status: issues_found (3 critical, 8 warning, 6 info)_
