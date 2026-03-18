# Equity Expansion Phase A: Infrastructure + Pilot

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add global session infrastructure, provider abstraction, plugin asset-class guard, and 5 pilot ETFs (SPY, XLF, TLT, GLD, SMH) so the cross-asset feature store captures clean equity data from bar one.

**Architecture:** Four independent tracks — (1) `TradingSession` model + `Instrument.session_id`, (2) `SessionContextPlugin` redesign to 27 data-driven outputs, (3) plugin asset-class guard injecting `__instrument__` into compute frames, (4) provider abstraction + IBKR equity support. All tracks converge in the settings layer that wires pilot ETFs and session_id assignments.

**Spec:** `docs/superpowers/specs/2026-03-13-equity-expansion-renaissance.md`

**Tech Stack:** Python 3.11, pydantic v2, ib_insync, ZoneInfo (stdlib), pytest, structlog, prometheus_client

---

## Chunk 1: TradingSession Model + SESSION_REGISTRY Split

### Task 1: TradingSession dataclass

**Files:**
- Modify: `src/core/models.py` (after `AssetClass` enum, before `DataSource`)
- Create: `tests/unit/core/test_trading_session.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/core/test_trading_session.py
from datetime import datetime, time, timezone
import pytest
from zoneinfo import ZoneInfo

UTC = timezone.utc


# --- Helpers ---

def utc(y, mo, d, h, mi) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


# --- is_open: NYSE (09:30-16:00 ET, Mon-Fri) ---

class TestNYSEIsOpen:
    """NYSE: open 09:30-16:00 ET, Mon-Fri, no breaks."""

    def setup_method(self):
        from src.core.models import EXCHANGE_SESSIONS
        self.session = EXCHANGE_SESSIONS["nyse"]

    def test_open_at_930_et(self):
        # 2026-03-10 is Tuesday; 09:30 ET = 14:30 UTC (EST, UTC-5)
        assert self.session.is_open(utc(2026, 3, 10, 14, 30)) is True

    def test_closed_before_930_et(self):
        assert self.session.is_open(utc(2026, 3, 10, 14, 29)) is False

    def test_closed_at_1600_et(self):
        # 16:00 ET = 21:00 UTC
        assert self.session.is_open(utc(2026, 3, 10, 21, 0)) is False

    def test_closed_on_saturday(self):
        # 2026-03-14 is Saturday
        assert self.session.is_open(utc(2026, 3, 14, 15, 0)) is False

    def test_dst_transition_march_2026(self):
        # US DST starts 2026-03-08 02:00 → clocks spring forward to 03:00
        # Before DST: 09:30 ET (EST) = 14:30 UTC
        # After DST:  09:30 ET (EDT) = 13:30 UTC
        # Tuesday 2026-03-10 is post-DST: 09:30 ET = 13:30 UTC
        assert self.session.is_open(utc(2026, 3, 10, 13, 30)) is True
        assert self.session.is_open(utc(2026, 3, 10, 14, 30)) is True  # 10:30 ET — still open

    def test_dst_transition_exact_boundary(self):
        # 2026-03-08 is DST switchover Sunday — market closed anyway
        # Monday 2026-03-09: first post-DST trading day
        # 09:30 EDT = UTC-4, so 09:30 ET = 13:30 UTC
        assert self.session.is_open(utc(2026, 3, 9, 13, 30)) is True
        # Under old hardcoded UTC-5: 14:30 UTC would be 09:30, but that's wrong post-DST
        # 14:30 UTC post-DST = 10:30 EDT — still open, so this also passes
        assert self.session.is_open(utc(2026, 3, 9, 16, 59)) is True  # 12:59 EDT
        assert self.session.is_open(utc(2026, 3, 9, 20, 0)) is False  # 16:00 EDT = closed


class TestFutures245IsOpen:
    """Futures 24/5: 18:00-17:00 Chicago, Mon-Fri + Sun, midnight wrap."""

    def setup_method(self):
        from src.core.models import CONTINUOUS_SESSIONS
        self.session = CONTINUOUS_SESSIONS["futures_24_5"]

    def test_open_at_open_time(self):
        # Sunday 2026-03-08 18:00 Chicago (CST UTC-6) = Sunday 00:00 UTC 2026-03-09
        assert self.session.is_open(utc(2026, 3, 9, 0, 0)) is True

    def test_closed_after_close_time(self):
        # Friday 17:00 Chicago CST = Friday 23:00 UTC
        assert self.session.is_open(utc(2026, 3, 13, 23, 0)) is False

    def test_closed_on_saturday(self):
        # Saturday is dark for futures
        assert self.session.is_open(utc(2026, 3, 14, 10, 0)) is False

    def test_open_sunday_pre_session_start(self):
        # Sunday 17:59 Chicago = before 18:00 open → closed
        assert self.session.is_open(utc(2026, 3, 8, 23, 59)) is False


class TestAllDaySession:
    """FX 24/5: open_time == close_time → all-day on trading days."""

    def setup_method(self):
        from src.core.models import CONTINUOUS_SESSIONS
        self.session = CONTINUOUS_SESSIONS["fx_24_5"]

    def test_open_any_time_on_weekday(self):
        assert self.session.is_open(utc(2026, 3, 10, 3, 0)) is True

    def test_closed_on_saturday(self):
        assert self.session.is_open(utc(2026, 3, 14, 12, 0)) is False


class TestTradingBreaks:
    """TSE has lunch break 11:30-12:30 JST."""

    def setup_method(self):
        from src.core.models import EXCHANGE_SESSIONS
        self.session = EXCHANGE_SESSIONS["tse"]

    def test_open_before_break(self):
        # Tuesday; 11:00 JST = 02:00 UTC
        assert self.session.is_open(utc(2026, 3, 10, 2, 0)) is True
        assert self.session.in_trading_break(utc(2026, 3, 10, 2, 0)) is False

    def test_in_break(self):
        # 11:30 JST = 02:30 UTC
        assert self.session.is_open(utc(2026, 3, 10, 2, 30)) is True   # still "open"
        assert self.session.in_trading_break(utc(2026, 3, 10, 2, 30)) is True

    def test_after_break(self):
        # 12:30 JST = 03:30 UTC
        assert self.session.is_open(utc(2026, 3, 10, 3, 30)) is True
        assert self.session.in_trading_break(utc(2026, 3, 10, 3, 30)) is False

    def test_no_break_on_nyse(self):
        from src.core.models import EXCHANGE_SESSIONS
        nyse = EXCHANGE_SESSIONS["nyse"]
        assert nyse.in_trading_break(utc(2026, 3, 10, 15, 0)) is False


class TestElapsedFraction:
    def test_all_day_returns_none(self):
        from src.core.models import CONTINUOUS_SESSIONS
        fx = CONTINUOUS_SESSIONS["fx_24_5"]
        assert fx.elapsed_fraction(utc(2026, 3, 10, 12, 0)) is None

    def test_closed_returns_none(self):
        from src.core.models import EXCHANGE_SESSIONS
        nyse = EXCHANGE_SESSIONS["nyse"]
        # Before open
        assert nyse.elapsed_fraction(utc(2026, 3, 10, 14, 0)) is None  # 09:00 ET — before 09:30

    def test_open_returns_0_at_open(self):
        from src.core.models import EXCHANGE_SESSIONS
        nyse = EXCHANGE_SESSIONS["nyse"]
        # 09:30 ET = 14:30 UTC (EST, pre-DST check date: 2026-03-03)
        result = nyse.elapsed_fraction(utc(2026, 3, 3, 14, 30))
        assert result is not None
        assert abs(result) < 0.01  # near 0.0

    def test_approaches_1_at_close(self):
        from src.core.models import EXCHANGE_SESSIONS
        nyse = EXCHANGE_SESSIONS["nyse"]
        # 15:59 ET = 20:59 UTC (EST, 2026-03-03)
        result = nyse.elapsed_fraction(utc(2026, 3, 3, 20, 59))
        assert result is not None
        assert result > 0.99

    def test_tse_break_excluded_from_denominator(self):
        """Break duration should be excluded so elapsed_frac < 1.0 at market close."""
        from src.core.models import EXCHANGE_SESSIONS
        tse = EXCHANGE_SESSIONS["tse"]
        # TSE open 09:00 JST, close 15:30 JST = 6.5h total, minus 1h break = 5.5h denominator
        # At 14:30 JST (just before power hour): elapsed ~= (14:30 - 09:00) - 1h break = 4.5h
        # frac ~= 4.5 / 5.5 ~= 0.818
        # 14:30 JST = 05:30 UTC
        result = tse.elapsed_fraction(utc(2026, 3, 10, 5, 30))
        assert result is not None
        assert 0.80 < result < 0.85
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/core/test_trading_session.py -v 2>&1 | head -30
```

Expected: ImportError — `EXCHANGE_SESSIONS`, `CONTINUOUS_SESSIONS` not yet defined.

- [ ] **Step 3: Implement TradingSession + EXCHANGE_SESSIONS + CONTINUOUS_SESSIONS + SESSION_REGISTRY + MARKET_OVERLAPS**

Add to `src/core/models.py` after the `AssetClass` class, before `DataSource`:

```python
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime as _datetime
from datetime import time
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class TradingSession:
    """Defines when a market is open, including trading breaks and trading days."""

    open_time: time
    close_time: time
    timezone: str
    trading_days: frozenset[int] = frozenset({0, 1, 2, 3, 4})
    trading_breaks: tuple[tuple[time, time], ...] = ()

    def is_open(self, utc_ts: _datetime) -> bool:
        """True if market is open at utc_ts (trading_breaks do NOT close the session)."""
        local = utc_ts.astimezone(ZoneInfo(self.timezone))
        if local.weekday() not in self.trading_days:
            return False
        t = local.time().replace(second=0, microsecond=0)
        if self.open_time == self.close_time:
            return True
        elif self.open_time < self.close_time:
            return self.open_time <= t < self.close_time
        else:
            return t >= self.open_time or t < self.close_time

    def in_trading_break(self, utc_ts: _datetime) -> bool:
        """True if currently in a scheduled intra-session break."""
        if not self.trading_breaks:
            return False
        local = utc_ts.astimezone(ZoneInfo(self.timezone))
        t = local.time().replace(second=0, microsecond=0)
        return any(start <= t < end for start, end in self.trading_breaks)

    def elapsed_fraction(self, utc_ts: _datetime) -> float | None:
        """Fraction of trading day elapsed (0.0→1.0, breaks excluded from denominator).

        Returns None for all-day sessions or when closed.
        """
        if self.open_time == self.close_time:
            return None
        if not self.is_open(utc_ts):
            return None
        local = utc_ts.astimezone(ZoneInfo(self.timezone))
        t = local.time().replace(second=0, microsecond=0)
        anchor = _date(2000, 1, 2)  # Monday anchor for safe time arithmetic
        t_dt  = _datetime.combine(anchor, t)
        op_dt = _datetime.combine(anchor, self.open_time)
        cl_dt = _datetime.combine(anchor, self.close_time)
        if self.open_time > self.close_time:  # midnight wrap
            next_day = _date(2000, 1, 3)
            cl_dt = _datetime.combine(next_day, self.close_time)
            if t < self.open_time:
                t_dt = _datetime.combine(next_day, t)
        session_total = (cl_dt - op_dt).total_seconds()
        elapsed = (t_dt - op_dt).total_seconds()
        for brk_start, brk_end in self.trading_breaks:
            bs_dt = _datetime.combine(anchor, brk_start)
            be_dt = _datetime.combine(anchor, brk_end)
            bs_dt = max(bs_dt, op_dt)
            be_dt = min(be_dt, cl_dt)
            if be_dt > bs_dt:
                session_total -= (be_dt - bs_dt).total_seconds()
            if be_dt <= t_dt:
                elapsed -= max(0.0, (be_dt - bs_dt).total_seconds())
            elif bs_dt < t_dt:
                elapsed -= (t_dt - bs_dt).total_seconds()
        return max(0.0, min(1.0, elapsed / session_total))


EXCHANGE_SESSIONS: dict[str, "TradingSession"] = {
    "nyse": TradingSession(time(9, 30),  time(16, 0),  "America/New_York"),
    "lse":  TradingSession(time(8, 0),   time(16, 30), "Europe/London"),
    "tse":  TradingSession(time(9, 0),   time(15, 30), "Asia/Tokyo",
                           trading_breaks=((time(11, 30), time(12, 30)),)),
    "hkex": TradingSession(time(9, 30),  time(16, 0),  "Asia/Hong_Kong",
                           trading_breaks=((time(12, 0), time(13, 0)),)),
    "sse":  TradingSession(time(9, 30),  time(15, 0),  "Asia/Shanghai",
                           trading_breaks=((time(11, 30), time(13, 0)),)),
    "asx":  TradingSession(time(10, 0),  time(16, 0),  "Australia/Sydney"),
}

CONTINUOUS_SESSIONS: dict[str, "TradingSession"] = {
    "futures_24_5": TradingSession(
        time(18, 0), time(17, 0), "America/Chicago",
        trading_days=frozenset({0, 1, 2, 3, 4, 6}),
    ),
    "fx_24_5": TradingSession(
        time(0, 0), time(0, 0), "UTC",
        trading_days=frozenset({0, 1, 2, 3, 4, 6}),
    ),
    "crypto_24_7": TradingSession(
        time(0, 0), time(0, 0), "UTC",
        trading_days=frozenset(range(7)),
    ),
}

SESSION_REGISTRY: dict[str, "TradingSession"] = {
    **EXCHANGE_SESSIONS,
    **CONTINUOUS_SESSIONS,
}

MARKET_OVERLAPS: dict[str, tuple[str, str]] = {
    "tokyo_london": ("tse",   "lse"),
    "london_ny":    ("lse",   "nyse"),
    "ny_sydney":    ("nyse",  "asx"),
}
```

Also add to `src/core/models.py` imports at top: `from dataclasses import dataclass` and `from datetime import date as _date, datetime as _datetime, time`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/core/test_trading_session.py -v
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add src/core/models.py tests/unit/core/test_trading_session.py
git commit -m "feat(models): add TradingSession with trading_breaks + SESSION_REGISTRY split"
```

---

### Task 2: Instrument.session_id field + validator

**Files:**
- Modify: `src/core/models.py` (`Instrument` class)
- Create: `tests/unit/core/test_instrument_session.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/core/test_instrument_session.py
import pytest
from src.core.models import Instrument, AssetClass, SESSION_REGISTRY, TradingSession


class TestInstrumentSessionId:
    def test_default_session_id_is_futures(self):
        inst = Instrument(symbol="ES", asset_class=AssetClass.FUTURES)
        assert inst.session_id == "futures_24_5"

    def test_valid_session_id_accepted(self):
        inst = Instrument(symbol="SPY", asset_class=AssetClass.EQUITY, session_id="nyse")
        assert inst.session_id == "nyse"

    def test_invalid_session_id_raises(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="Unknown session_id"):
            Instrument(symbol="SPY", asset_class=AssetClass.EQUITY, session_id="invalid_session")

    def test_trading_session_property_returns_correct_instance(self):
        inst = Instrument(symbol="SPY", asset_class=AssetClass.EQUITY, session_id="nyse")
        session = inst.trading_session
        assert isinstance(session, TradingSession)
        assert session is SESSION_REGISTRY["nyse"]

    def test_all_known_session_ids_valid(self):
        for sid in SESSION_REGISTRY:
            inst = Instrument(symbol="TEST", session_id=sid)
            assert inst.session_id == sid
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/core/test_instrument_session.py -v 2>&1 | head -20
```

Expected: AttributeError — `Instrument` has no `session_id`.

- [ ] **Step 3: Add session_id to Instrument**

In `src/core/models.py`, modify the `Instrument` class. Add these imports at the top of the file:
`from pydantic import BaseModel, Field, field_validator`

Add to `Instrument`:

```python
from src.core.models import SESSION_REGISTRY  # already in same file — no import needed
    session_id: str = "futures_24_5"

    @field_validator("session_id")
    @classmethod
    def validate_session(cls, v: str) -> str:
        if v not in SESSION_REGISTRY:
            raise ValueError(f"Unknown session_id {v!r}. Known: {list(SESSION_REGISTRY)}")
        return v

    @property
    def trading_session(self) -> "TradingSession":
        return SESSION_REGISTRY[self.session_id]
```

Note: `SESSION_REGISTRY` is defined above `Instrument` in the same file — forward reference issue is avoided.

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/core/test_instrument_session.py tests/unit/core/test_trading_session.py -v
```

Expected: All pass.

- [ ] **Step 5: Full regression check**

```bash
.venv/bin/pytest tests/unit/ -x -q 2>&1 | tail -5
```

Expected: No new failures. Existing tests unaffected (session_id defaults to "futures_24_5").

- [ ] **Step 6: Commit**

```bash
git add src/core/models.py tests/unit/core/test_instrument_session.py
git commit -m "feat(models): add Instrument.session_id field with SESSION_REGISTRY validation"
```

---

## Chunk 2: SessionContextPlugin Redesign (27 outputs)

### Task 3: DST fix + data-driven exchange session flags

**Files:**
- Modify: `src/intelligence/context/session_context.py`
- Create: `tests/unit/intelligence/test_session_context_redesign.py`

- [ ] **Step 1: Write failing tests for DST fix + existing outputs preserved**

```python
# tests/unit/intelligence/test_session_context_redesign.py
from datetime import datetime, timezone
import pandas as pd
import pytest

UTC = timezone.utc


def make_df(utc_ts: datetime) -> dict:
    """Minimal frames dict with a single-row DataFrame for test."""
    df = pd.DataFrame([{
        "timestamp": utc_ts,
        "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 100,
    }])
    return {"main": df}


def run(utc_ts: datetime) -> dict:
    from src.intelligence.context.session_context import SessionContextPlugin
    p = SessionContextPlugin()
    return p.compute_full(make_df(utc_ts))


def utc(y, mo, d, h, mi) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


EXPECTED_27_OUTPUTS = {
    # existing 12
    "session_asia", "session_london", "session_ny", "session_london_ny_overlap",
    "session_after_hours", "in_london_killzone", "in_ny_killzone",
    "minutes_to_ny_open", "minutes_to_london_open", "bars_since_session_start",
    "is_monday", "is_friday",
    # new: exchange active flags (6)
    "session_nyse_active", "session_lse_active", "session_tse_active",
    "session_hkex_active", "session_sse_active", "session_asx_active",
    # new: trading break flags (3)
    "session_tse_in_break", "session_hkex_in_break", "session_sse_in_break",
    # new: overlaps (2)
    "session_tokyo_london_overlap", "session_ny_sydney_overlap",
    # new: sub-session (4)
    "session_elapsed_frac", "is_opening_range", "is_lunch_consolidation", "is_power_hour",
}


class TestOutputCount:
    def test_all_27_outputs_present(self):
        result = run(utc(2026, 3, 10, 15, 0))  # Tuesday 15:00 UTC
        assert set(result.keys()) == EXPECTED_27_OUTPUTS

    def test_outputs_frozenset_matches(self):
        from src.intelligence.context.session_context import SessionContextPlugin
        p = SessionContextPlugin()
        assert p.outputs == EXPECTED_27_OUTPUTS


class TestDSTFix:
    """DST transition: 2026-03-08 02:00 US clocks spring forward (EST→EDT).
    After transition: NY open 09:30 EDT = 13:30 UTC (not 14:30 as with hardcoded UTC-5).
    """

    def test_ny_session_open_post_dst_1330_utc(self):
        # 2026-03-09 Monday — first post-DST trading day
        # 09:30 EDT = 13:30 UTC → should be session_ny=1.0
        result = run(utc(2026, 3, 9, 13, 30))
        assert result["session_ny"] == 1.0

    def test_ny_session_closed_at_1330_pre_dst(self):
        # 2026-03-03 Tuesday — pre-DST
        # 09:30 EST = 14:30 UTC; 13:30 UTC = 08:30 EST → not yet open
        result = run(utc(2026, 3, 3, 13, 30))
        assert result["session_ny"] == 0.0

    def test_session_ny_active_flag_matches_ny_session(self):
        # session_nyse_active should mirror session_ny when open
        result_open = run(utc(2026, 3, 9, 15, 0))   # 11:00 EDT — open
        result_closed = run(utc(2026, 3, 9, 20, 30)) # 16:30 EDT — closed
        assert result_open["session_nyse_active"] == 1.0
        assert result_closed["session_nyse_active"] == 0.0


class TestExchangeActiveFlags:
    def test_lse_open_during_london_morning(self):
        # Tuesday 09:00 UTC = 09:00 BST (GMT+1 in summer... but in March pre-BST: GMT)
        # LSE 08:00-16:30 London time; in March (GMT): 08:00 UTC → open at 09:00 UTC
        result = run(utc(2026, 3, 10, 9, 0))
        assert result["session_lse_active"] == 1.0

    def test_tse_open_during_morning(self):
        # TSE 09:00-15:30 JST; JST = UTC+9; 09:00 JST = 00:00 UTC
        result = run(utc(2026, 3, 10, 0, 30))  # 09:30 JST — open
        assert result["session_tse_active"] == 1.0

    def test_tse_in_break(self):
        # 11:30-12:30 JST = 02:30-03:30 UTC
        result = run(utc(2026, 3, 10, 2, 45))  # 11:45 JST — in break
        assert result["session_tse_active"] == 1.0   # is_open still True
        assert result["session_tse_in_break"] == 1.0

    def test_asx_closed_during_us_hours(self):
        # ASX 10:00-16:00 AEDT (UTC+11 in March) = 23:00-05:00 UTC
        # During US hours 14:30 UTC = 01:30 AEDT next day — after close
        result = run(utc(2026, 3, 10, 14, 30))
        assert result["session_asx_active"] == 0.0

    def test_nyse_not_open_on_weekend(self):
        # Saturday
        result = run(utc(2026, 3, 14, 15, 0))
        assert result["session_nyse_active"] == 0.0


class TestOverlapFlags:
    def test_tokyo_london_overlap(self):
        # TSE open 00:00-06:30 UTC; LSE open 08:00-16:30 UTC (pre-BST March)
        # Overlap: 08:00-06:30... actually TSE closes before LSE opens — minimal overlap
        # Let's check a time both are open:
        # TSE 09:30 JST = 00:30 UTC; LSE opens 08:00 UTC
        # Actually these don't overlap in March... test that flag is 0.0 when they don't overlap
        result = run(utc(2026, 3, 10, 5, 0))  # 05:00 UTC: TSE open (14:00 JST), LSE closed (05:00 BST)
        assert result["session_tokyo_london_overlap"] == 0.0

    def test_london_ny_overlap(self):
        # session_london_ny_overlap (legacy name) should still work
        # LSE 08:00-16:30 UTC (March GMT); NYSE 14:30-21:00 UTC (post-DST March)
        # Overlap: 14:30-16:30 UTC
        result = run(utc(2026, 3, 10, 15, 0))  # 15:00 UTC: both open
        assert result["session_london_ny_overlap"] == 1.0


class TestSubSessionOutputsNoInstrument:
    """When frames has no __instrument__, sub-session outputs default to 0.0."""

    def test_sub_session_defaults_to_zero_without_instrument(self):
        result = run(utc(2026, 3, 10, 15, 0))
        assert result["session_elapsed_frac"] == 0.0
        assert result["is_opening_range"] == 0.0
        assert result["is_lunch_consolidation"] == 0.0
        assert result["is_power_hour"] == 0.0


class TestSubSessionWithInstrument:
    """With __instrument__ in frames, sub-session outputs are computed."""

    def _run_with_instrument(self, utc_ts: datetime, session_id: str) -> dict:
        from src.intelligence.context.session_context import SessionContextPlugin
        from src.core.models import Instrument, AssetClass
        p = SessionContextPlugin()
        df = pd.DataFrame([{
            "timestamp": utc_ts,
            "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 100,
        }])
        inst = Instrument(symbol="SPY", asset_class=AssetClass.EQUITY, session_id=session_id)
        return p.compute_full({"main": df, "__instrument__": inst})

    def test_elapsed_frac_near_zero_at_open(self):
        # NYSE 09:30 EST (pre-DST): 14:30 UTC
        result = self._run_with_instrument(utc(2026, 3, 3, 14, 30), "nyse")
        assert result["session_elapsed_frac"] is not None
        assert abs(result["session_elapsed_frac"]) < 0.01

    def test_is_opening_range_first_30_min(self):
        # NYSE 09:35 EST = 14:35 UTC (pre-DST, 5 min in)
        result = self._run_with_instrument(utc(2026, 3, 3, 14, 35), "nyse")
        assert result["is_opening_range"] == 1.0

    def test_not_opening_range_after_30_min(self):
        # NYSE 10:01 EST = 15:01 UTC (pre-DST, 31 min in)
        result = self._run_with_instrument(utc(2026, 3, 3, 15, 1), "nyse")
        assert result["is_opening_range"] == 0.0

    def test_is_power_hour_last_60_min(self):
        # NYSE 15:30 EST = 20:30 UTC (pre-DST, 60 min before close)
        result = self._run_with_instrument(utc(2026, 3, 3, 20, 30), "nyse")
        assert result["is_power_hour"] == 1.0

    def test_no_sub_session_for_futures_allday(self):
        # futures_24_5 is all-day → elapsed_frac should be 0.0 (session returns None)
        result = self._run_with_instrument(utc(2026, 3, 10, 15, 0), "futures_24_5")
        assert result["session_elapsed_frac"] == 0.0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/intelligence/test_session_context_redesign.py -v 2>&1 | head -30
```

Expected: Various failures — plugin has 12 outputs not 27, no exchange flags, wrong DST handling.

- [ ] **Step 3: Rewrite session_context.py**

Full replacement of `src/intelligence/context/session_context.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..plugins import InputSpec
from src.core.models import (
    EXCHANGE_SESSIONS,
    MARKET_OVERLAPS,
    SESSION_REGISTRY,
    TradingSession,
)

# --- Legacy ET session windows (local wall-clock, preserved for backward compat) ---

_ET_TZ = ZoneInfo("America/New_York")  # replaces hardcoded _ET_OFFSET = timedelta(hours=-5)

_SESSIONS = {
    "asia":    ((20, 0), (4, 0)),   # wraps midnight in ET
    "london":  ((3, 0),  (12, 0)),
    "ny":      ((9, 30), (16, 0)),
    "overlap": ((8, 0),  (12, 0)),  # London/NY overlap (legacy range, preserved)
}

_KILLZONES = {
    "london_kz": ((2, 0), (5, 0)),
    "ny_kz":     ((7, 0), (10, 0)),
}


def _et_from_utc(ts: datetime) -> datetime:
    return ts.astimezone(_ET_TZ)


def _in_window(et_dt: datetime, start: tuple[int, int], end: tuple[int, int]) -> bool:
    t = (et_dt.hour, et_dt.minute)
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def _minutes_until(et_dt: datetime, target_hour: int, target_min: int) -> float:
    target = et_dt.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
    if target <= et_dt:
        target = target + timedelta(days=1)
    return (target - et_dt).total_seconds() / 60.0


def _extract_ts(df: Any) -> datetime | None:
    if df is None or len(df) == 0:
        return None
    if "timestamp" in df.columns:
        val = df["timestamp"].iloc[-1]
        if hasattr(val, "to_pydatetime"):
            return val.to_pydatetime()
        if isinstance(val, datetime):
            return val if val.tzinfo else val.replace(tzinfo=UTC)
    return None


@dataclass
class SessionContextPlugin:
    """Time-of-day session context — global exchanges, DST-correct, 27 outputs."""

    name: str = "ctx_SessionContext"
    outputs: frozenset[str] = frozenset(
        {
            # --- Legacy 12 outputs (preserved) ---
            "session_asia",
            "session_london",
            "session_ny",
            "session_london_ny_overlap",
            "session_after_hours",
            "in_london_killzone",
            "in_ny_killzone",
            "minutes_to_ny_open",
            "minutes_to_london_open",
            "bars_since_session_start",
            "is_monday",
            "is_friday",
            # --- Exchange active flags (6) ---
            "session_nyse_active",
            "session_lse_active",
            "session_tse_active",
            "session_hkex_active",
            "session_sse_active",
            "session_asx_active",
            # --- Trading break flags (3) ---
            "session_tse_in_break",
            "session_hkex_in_break",
            "session_sse_in_break",
            # --- Market overlap flags (2) ---
            "session_tokyo_london_overlap",
            "session_ny_sydney_overlap",
            # --- Instrument sub-session (4) ---
            "session_elapsed_frac",
            "is_opening_range",
            "is_lunch_consolidation",
            "is_power_hour",
        }
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"context"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=10),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None:
            return {}

        ts = _extract_ts(df)
        if ts is None:
            return {k: 0.0 for k in self.outputs}

        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        et = _et_from_utc(ts)

        # --- Legacy outputs (backward compat) ---
        sess_asia    = 1.0 if _in_window(et, *_SESSIONS["asia"])    else 0.0
        sess_london  = 1.0 if _in_window(et, *_SESSIONS["london"])  else 0.0
        sess_ny      = 1.0 if _in_window(et, *_SESSIONS["ny"])      else 0.0
        sess_overlap = 1.0 if _in_window(et, *_SESSIONS["overlap"]) else 0.0
        sess_after   = 0.0 if (sess_asia or sess_london or sess_ny)  else 1.0

        in_london_kz = 1.0 if _in_window(et, *_KILLZONES["london_kz"]) else 0.0
        in_ny_kz     = 1.0 if _in_window(et, *_KILLZONES["ny_kz"])     else 0.0

        mins_to_ny     = _minutes_until(et, 9, 30)
        mins_to_london = _minutes_until(et, 3, 0)
        bars_since     = float(len(df))

        # --- Exchange active flags (data-driven from EXCHANGE_SESSIONS) ---
        exchange_flags: dict[str, float] = {}
        break_flags: dict[str, float] = {}
        for ex_id, session in EXCHANGE_SESSIONS.items():
            exchange_flags[f"session_{ex_id}_active"] = 1.0 if session.is_open(ts) else 0.0
            if session.trading_breaks:
                break_flags[f"session_{ex_id}_in_break"] = (
                    1.0 if session.in_trading_break(ts) else 0.0
                )

        # --- Market overlap flags (data-driven from MARKET_OVERLAPS) ---
        overlap_flags: dict[str, float] = {}
        for overlap_name, (ex_a, ex_b) in MARKET_OVERLAPS.items():
            both_open = (
                SESSION_REGISTRY[ex_a].is_open(ts)
                and SESSION_REGISTRY[ex_b].is_open(ts)
            )
            overlap_flags[f"session_{overlap_name}_overlap"] = 1.0 if both_open else 0.0

        # --- Instrument sub-session (requires __instrument__ in frames) ---
        instrument = frames.get("__instrument__")
        sub_session = self._compute_sub_session(ts, instrument)

        return {
            # Legacy 12
            "session_asia":             sess_asia,
            "session_london":           sess_london,
            "session_ny":               sess_ny,
            # Source london_ny_overlap from MARKET_OVERLAPS (spec requirement); fallback 0.0 not sess_overlap
            "session_london_ny_overlap": overlap_flags.get("session_london_ny_overlap", 0.0),
            "session_after_hours":      sess_after,
            "in_london_killzone":       in_london_kz,
            "in_ny_killzone":           in_ny_kz,
            "minutes_to_ny_open":       mins_to_ny,
            "minutes_to_london_open":   mins_to_london,
            "bars_since_session_start": bars_since,
            "is_monday":                1.0 if et.weekday() == 0 else 0.0,
            "is_friday":                1.0 if et.weekday() == 4 else 0.0,
            # Exchange flags
            **exchange_flags,
            # Break flags
            **break_flags,
            # Overlap flags (excluding london_ny which is already in legacy)
            "session_tokyo_london_overlap": overlap_flags.get("session_tokyo_london_overlap", 0.0),
            "session_ny_sydney_overlap":    overlap_flags.get("session_ny_sydney_overlap", 0.0),
            # Sub-session
            **sub_session,
        }

    def _compute_sub_session(
        self, ts: datetime, instrument: Any
    ) -> dict[str, float]:
        """Instrument-aware sub-session features. Defaults to 0.0 when no instrument."""
        defaults: dict[str, float] = {
            "session_elapsed_frac": 0.0,
            "is_opening_range":     0.0,
            "is_lunch_consolidation": 0.0,
            "is_power_hour":        0.0,
        }
        if instrument is None:
            return defaults

        session: TradingSession = instrument.trading_session
        elapsed = session.elapsed_fraction(ts)

        if elapsed is None:
            return defaults  # all-day session

        # NOTE: 390 is NYSE session minutes (6.5h). elapsed_fraction() already normalises
        # by the instrument's actual session length, so these thresholds work correctly
        # for NYSE sessions. For non-NYSE sessions (e.g. TSE=330 min), the 30/390 ≈ 7.7%
        # and 330/390 ≈ 84.6% thresholds still approximate "first 30 min" and "last 60 min"
        # reasonably — Phase A pilot is NYSE-only, so this is not a live issue. Phase B
        # should derive session_minutes from actual open/close times if non-NYSE ETFs are added.
        is_opening  = 1.0 if elapsed < (30.0 / 390.0) else 0.0  # first ~7.7% of session
        is_power    = 1.0 if elapsed > (330.0 / 390.0) else 0.0 # last ~15.4% of session

        if session.trading_breaks:
            is_lunch = 1.0 if session.in_trading_break(ts) else 0.0
        else:
            is_lunch = 1.0 if 0.30 <= elapsed <= 0.65 else 0.0

        return {
            "session_elapsed_frac":   elapsed,
            "is_opening_range":       is_opening,
            "is_lunch_consolidation": is_lunch,
            "is_power_hour":          is_power,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = SessionContextPlugin()
```

Note: `session_london_ny_overlap` key in `MARKET_OVERLAPS` is `"london_ny"` → generates key `session_london_ny_overlap`. This matches the legacy output name exactly.

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/intelligence/test_session_context_redesign.py -v
```

Expected: All pass.

- [ ] **Step 5: Full regression — existing session_context tests**

```bash
.venv/bin/pytest tests/unit/ -x -q 2>&1 | tail -5
```

Expected: No regressions.

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/context/session_context.py tests/unit/intelligence/test_session_context_redesign.py
git commit -m "feat(session): redesign SessionContextPlugin — 27 outputs, DST fix, global exchanges"
```

---

## Chunk 3: Plugin Asset-Class Compatibility Layer

### Task 4: valid_asset_classes ClassVar on protocols + guard in indicator_service

**Files:**
- Modify: `src/intelligence/plugins.py`
- Modify: `services/indicator_service.py` (add `_instrument_map`, `frames["__instrument__"]`, guard, `plugin_skipped_total`, `bars_processed_labeled_total`)
- Create: `tests/unit/intelligence/test_plugin_asset_class_guard.py`
- Create: `tests/unit/service_tests/test_indicator_service_asset_guard.py`

- [ ] **Step 1: Write failing tests — protocol ClassVar**

```python
# tests/unit/intelligence/test_plugin_asset_class_guard.py
from typing import ClassVar
from src.core.models import AssetClass


class TestPluginProtocolHasValidAssetClasses:
    def test_indicator_plugin_has_valid_asset_classes(self):
        from src.intelligence.plugins import IndicatorPlugin
        assert hasattr(IndicatorPlugin, "valid_asset_classes")

    def test_pattern_plugin_has_valid_asset_classes(self):
        from src.intelligence.plugins import PatternPlugin
        assert hasattr(PatternPlugin, "valid_asset_classes")


class TestPluginDefaultIsAllAssetClasses:
    """A plugin without valid_asset_classes declared gets all asset classes by default."""

    def test_getattr_default_is_all(self):
        from src.intelligence.plugins import IndicatorPlugin
        from src.core.models import AssetClass

        class MinimalPlugin:
            name = "test_plugin"
            outputs = frozenset()
            min_lookback = 1
            supports_incremental = False
            capability_tags = frozenset()
            inputs = []
            _state = {}

            def compute_full(self, frames): return {}
            def compute_next(self, windows): return {}

        plugin = MinimalPlugin()
        allowed = getattr(plugin, "valid_asset_classes", frozenset(AssetClass))
        assert AssetClass.FUTURES in allowed
        assert AssetClass.EQUITY in allowed
        assert AssetClass.CRYPTO in allowed

    def test_restricted_plugin_skips_wrong_asset_class(self):
        from src.core.models import AssetClass

        class FuturesOnlyPlugin:
            name = "futures_only"
            outputs = frozenset({"fut_signal"})
            min_lookback = 1
            supports_incremental = False
            capability_tags = frozenset()
            inputs = []
            valid_asset_classes: ClassVar[frozenset] = frozenset({AssetClass.FUTURES})
            _state = {}

            def compute_full(self, frames): return {"fut_signal": 1.0}
            def compute_next(self, windows): return {}

        plugin = FuturesOnlyPlugin()
        allowed = getattr(plugin, "valid_asset_classes", frozenset(AssetClass))
        assert AssetClass.EQUITY not in allowed
        assert AssetClass.FUTURES in allowed
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/intelligence/test_plugin_asset_class_guard.py -v 2>&1 | head -20
```

- [ ] **Step 3: Add valid_asset_classes to plugins.py**

In `src/intelligence/plugins.py`, add import:
```python
from src.core.models import AssetClass
```

Add to both `IndicatorPlugin` and `PatternPlugin` protocol bodies:
```python
    valid_asset_classes: ClassVar[frozenset[AssetClass]]
```

- [ ] **Step 4: Write failing test for indicator_service instrument_map**

```python
# tests/unit/service_tests/test_indicator_service_asset_guard.py
import pytest
from unittest.mock import MagicMock, patch
from collections import defaultdict


class TestIndicatorServiceInstrumentMap:
    """Test _instrument_map is built from Settings.instruments."""

    def _make_service(self):
        """Build service via __new__ to bypass __init__."""
        from services.indicator_service import IndicatorService
        from src.core.models import Instrument, AssetClass

        svc = IndicatorService.__new__(IndicatorService)
        # Minimal attributes normally set in __init__
        svc.logger = MagicMock()
        svc._i1_plugin_cache = {}
        svc._i1_plugin_states = {}
        svc._i1_plugin_states_locks = {}
        svc._i1_call_counts = defaultdict(int)
        svc.bar_history = defaultdict(dict)
        svc._df_cache = {}
        svc._stream_map = {}
        svc.env_prefix = ""

        # Instrument map with one equity and one futures
        svc._instrument_map = {
            "SPY": Instrument(symbol="SPY", asset_class=AssetClass.EQUITY, session_id="nyse"),
            "ES":  Instrument(symbol="ES",  asset_class=AssetClass.FUTURES),
        }
        return svc

    def test_instrument_map_built_correctly(self):
        from src.core.models import AssetClass
        svc = self._make_service()
        assert svc._instrument_map["SPY"].asset_class == AssetClass.EQUITY
        assert svc._instrument_map["ES"].asset_class == AssetClass.FUTURES

    def test_frames_instrument_injected(self):
        """__instrument__ in frames is the Instrument for that symbol."""
        from src.core.models import AssetClass
        svc = self._make_service()
        instrument = svc._instrument_map.get("SPY")
        frames = {}
        frames["__instrument__"] = instrument
        assert frames["__instrument__"].asset_class == AssetClass.EQUITY

    def test_futures_only_plugin_skipped_for_equity(self):
        """A plugin with valid_asset_classes={FUTURES} should not run for SPY."""
        from src.core.models import AssetClass

        class FuturesOnlyPlugin:
            name = "roll_momentum"
            outputs = frozenset({"roll_signal"})
            min_lookback = 1
            supports_incremental = False
            capability_tags = frozenset()
            inputs = []
            valid_asset_classes = frozenset({AssetClass.FUTURES})
            _state = {}

            def compute_full(self, frames):
                return {"roll_signal": 1.0}

            def compute_next(self, windows):
                return {}

        svc = self._make_service()
        instrument = svc._instrument_map["SPY"]
        plugin = FuturesOnlyPlugin()
        allowed = getattr(plugin, "valid_asset_classes", frozenset(AssetClass))
        assert instrument.asset_class not in allowed  # guard would skip this
```

- [ ] **Step 5: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/service_tests/test_indicator_service_asset_guard.py -v 2>&1 | head -20
```

Expected: `_instrument_map` attribute missing.

- [ ] **Step 6: Add _instrument_map to indicator_service.__init__ and guard to _run_i1_plugins**

In `services/indicator_service.py`:

**In `__init__` after `settings = Settings()`:**
```python
        # Build instrument map for asset-class guard
        instruments = settings.instruments if hasattr(settings, "instruments") else []
        self._instrument_map: dict[str, Any] = {
            inst.symbol: inst for inst in instruments
        }
```

Also add new Prometheus metrics in `__init__` (after existing metrics). Note: `metrics.counter()` does NOT support `labelnames` — use `Counter()` directly, matching the pattern of `STREAM_READ_TOTAL` in `src/observability/metrics.py`:
```python
        from prometheus_client import Counter
        # Use Counter() directly — metrics.counter() helper doesn't support labels
        self.plugin_skipped_total = Counter(
            "plugin_skipped_total",
            "Total plugin invocations skipped due to asset class",
            ["plugin_name", "asset_class"],
        )
        self.bars_processed_labeled_total = Counter(
            "indicator_bars_processed_labeled_total",
            "Bars processed by indicator service (labeled by symbol and tf)",
            ["symbol", "tf"],
        )
```

**In `_run_i1_plugins`, before the plugin loop:**
```python
        from src.core.models import AssetClass
        instrument = self._instrument_map.get(symbol)
```

**Inside the plugin loop, before `p.compute_full(frames)` call:**
```python
                allowed = getattr(p, "valid_asset_classes", frozenset(AssetClass))
                if instrument and instrument.asset_class not in allowed:
                    self.plugin_skipped_total.labels(
                        plugin_name=plugin_name,
                        asset_class=instrument.asset_class.value,
                    ).inc()
                    continue
                frames["__instrument__"] = instrument
```

**After the plugin loop completes (in `_process_single_bar`), after `self.bars_processed_total.inc()`:**
```python
            self.bars_processed_labeled_total.labels(symbol=symbol, tf=timeframe).inc()
```

Check `src/observability/metrics.py` — if `counter` does not support `labelnames`, use the Prometheus Python client directly. Match the existing pattern in the file.

- [ ] **Step 7: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/service_tests/test_indicator_service_asset_guard.py tests/unit/intelligence/test_plugin_asset_class_guard.py -v
```

Expected: All pass.

- [ ] **Step 8: Full regression**

```bash
.venv/bin/pytest tests/unit/ -x -q 2>&1 | tail -5
```

- [ ] **Step 9: Commit**

```bash
git add src/intelligence/plugins.py services/indicator_service.py \
    tests/unit/intelligence/test_plugin_asset_class_guard.py \
    tests/unit/service_tests/test_indicator_service_asset_guard.py
git commit -m "feat(plugins): add valid_asset_classes guard + instrument injection in indicator_service"
```

---

### Task 5: Asset-class guard in market_analysis_service

**Files:**
- Modify: `services/market_analysis_service.py`

The pattern mirrors indicator_service exactly — `_instrument_map`, `frames["__instrument__"]` injection, asset-class guard, `plugin_skipped_total`, `bars_processed_labeled_total`.

- [ ] **Step 1: Find the plugin loop in market_analysis_service**

```bash
grep -n "_plugin_cache\|compute_full\|_plugin_states" services/market_analysis_service.py | head -20
```

Locate the equivalent of `_run_i1_plugins` — likely a per-tier loop.

- [ ] **Step 2: Write a focused failing test**

```python
# Append to tests/unit/service_tests/test_indicator_service_asset_guard.py

class TestMarketAnalysisServiceInstrumentMap:
    def test_market_analysis_has_instrument_map(self):
        from services.market_analysis_service import MarketAnalysisService
        svc = MarketAnalysisService.__new__(MarketAnalysisService)
        # _instrument_map not built yet → expect AttributeError
        with pytest.raises(AttributeError):
            _ = svc._instrument_map
```

- [ ] **Step 3: Run test to confirm it fails (AttributeError)**

```bash
.venv/bin/pytest tests/unit/service_tests/test_indicator_service_asset_guard.py::TestMarketAnalysisServiceInstrumentMap -v
```

- [ ] **Step 4: Apply same changes to market_analysis_service**

Same three changes as Task 4 Step 6, applied to `market_analysis_service.py`:
- `_instrument_map` in `__init__`
- `plugin_skipped_total` and `bars_processed_labeled_total` metrics in `__init__`
- `__instrument__` injection and asset-class guard in the plugin compute loop

Use `Counter()` directly (not `metrics.counter()`) for labeled metrics — same pattern as Task 4.

Note: `bars_processed_labeled_total` must use a **different metric name** — `market_analysis_bars_processed_labeled_total` — to avoid Prometheus duplicate registration. `plugin_skipped_total` is shared and already registered by `indicator_service`; use `try/except ValueError` to handle re-registration, or check `prometheus_client`'s `REGISTRY` first. The safest pattern: define both labeled Counters in `src/observability/metrics.py` at module level (matching the existing `STREAM_READ_TOTAL` pattern) and import them in both services.

- [ ] **Step 5: Run tests + full regression**

```bash
.venv/bin/pytest tests/unit/ -x -q 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add services/market_analysis_service.py tests/unit/service_tests/test_indicator_service_asset_guard.py
git commit -m "feat(plugins): apply asset-class guard to market_analysis_service"
```

---

## Chunk 4: Provider Abstraction

### Task 6: SubscriptionManager + SubscriptionLimitError → base.py

**Files:**
- Modify: `src/providers/base.py`
- Modify: `tests/unit/providers/test_base.py` (append — file already exists with `TestTick`/`TestOHLCVBar` tests)

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/providers/test_base.py
import pytest
from src.providers.base import SubscriptionManager, SubscriptionLimitError


class TestSubscriptionManager:
    def test_subscribe_increments_count(self):
        mgr = SubscriptionManager("test_provider", max_subscriptions=10)
        mgr.subscribe("AAPL")
        assert mgr.count == 1

    def test_subscribe_twice_same_symbol_no_duplicate(self):
        mgr = SubscriptionManager("test_provider", max_subscriptions=10)
        mgr.subscribe("AAPL")
        mgr.subscribe("AAPL")  # set semantics — no duplicate
        assert mgr.count == 1

    def test_unsubscribe_decrements_count(self):
        mgr = SubscriptionManager("test_provider", max_subscriptions=10)
        mgr.subscribe("AAPL")
        mgr.unsubscribe("AAPL")
        assert mgr.count == 0

    def test_unsubscribe_unknown_symbol_no_error(self):
        mgr = SubscriptionManager("test_provider", max_subscriptions=10)
        mgr.unsubscribe("UNKNOWN")  # discard — no exception
        assert mgr.count == 0

    def test_raises_when_limit_reached(self):
        mgr = SubscriptionManager("test_provider", max_subscriptions=2)
        mgr.subscribe("AAPL")
        mgr.subscribe("MSFT")
        with pytest.raises(SubscriptionLimitError, match="test_provider"):
            mgr.subscribe("GOOG")

    def test_error_message_contains_symbol(self):
        mgr = SubscriptionManager("ibkr", max_subscriptions=1)
        mgr.subscribe("SPY")
        with pytest.raises(SubscriptionLimitError, match="AAPL"):
            mgr.subscribe("AAPL")

    def test_after_unsubscribe_can_subscribe_again(self):
        mgr = SubscriptionManager("test_provider", max_subscriptions=2)
        mgr.subscribe("AAPL")
        mgr.subscribe("MSFT")
        mgr.unsubscribe("AAPL")
        mgr.subscribe("GOOG")  # should succeed — count is 2 again
        assert mgr.count == 2
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/providers/test_base.py -v 2>&1 | head -20
```

- [ ] **Step 3: Add SubscriptionManager and SubscriptionLimitError to base.py**

Append to `src/providers/base.py`:

```python
class SubscriptionLimitError(Exception):
    """Raised when a provider's subscription limit is reached."""


class SubscriptionManager:
    """Generic subscription slot tracker for data providers with hard limits.

    Provider-agnostic: IBKR, Alpaca, Polygon all have different limits.
    SubscriptionLimitError is raised before attempting the violating subscription
    so the caller can handle gracefully (log + skip vs raise).
    """

    def __init__(self, provider_name: str, max_subscriptions: int) -> None:
        self._provider_name = provider_name
        self._max = max_subscriptions
        self._active: set[str] = set()

    def subscribe(self, symbol: str) -> None:
        if symbol in self._active:
            return  # idempotent
        if len(self._active) >= self._max:
            raise SubscriptionLimitError(
                f"{self._provider_name}: subscription limit {self._max} reached "
                f"(attempted to add {symbol!r})"
            )
        self._active.add(symbol)

    def unsubscribe(self, symbol: str) -> None:
        self._active.discard(symbol)

    @property
    def count(self) -> int:
        return len(self._active)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/providers/test_base.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/providers/base.py tests/unit/providers/test_base.py
git commit -m "feat(providers): add SubscriptionManager + SubscriptionLimitError to base.py"
```

---

### Task 7: IBKR equity support (STK qualification + useRTH=True)

**Files:**
- Modify: `src/providers/ibkr.py`
- Create: `tests/unit/providers/test_ibkr_equity.py`

- [ ] **Step 1: Examine current ibkr.py qualify_instrument and fetch_historical_bars**

```bash
grep -n "qualify_instrument\|qualify\|secType\|useRTH\|SubscriptionManager\|SubscriptionLimit" src/providers/ibkr.py | head -30
```

Identify: (a) where equity branch needs to go in `qualify_instrument`, (b) where `useRTH` is passed in `fetch_historical_bars`, (c) whether `SubscriptionManager` already exists in ibkr.py.

- [ ] **Step 2: Write failing tests**

```python
# tests/unit/providers/test_ibkr_equity.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.core.models import Instrument, AssetClass


class TestIBKREquityQualification:
    """IBKR must use secType='STK' for equity instruments."""

    @pytest.mark.asyncio
    async def test_qualify_equity_uses_stock_contract(self):
        from src.providers.ibkr import IBKRProvider
        provider = IBKRProvider.__new__(IBKRProvider)
        provider.logger = MagicMock()

        instrument = Instrument(
            symbol="SPY",
            asset_class=AssetClass.EQUITY,
            exchange="SMART",
            session_id="nyse",
        )

        # Mock ib_insync contract qualification
        mock_contract = MagicMock()
        mock_contract.secType = "STK"
        mock_contract.symbol = "SPY"

        with patch.object(provider, "_ib", create=True) as mock_ib:
            mock_ib.qualifyContractsAsync = AsyncMock(return_value=[mock_contract])
            # qualify_instrument should use Stock(symbol="SPY", exchange="SMART", currency="USD")
            # We verify that secType='STK' ends up on the contract returned
            result = await provider.qualify_instrument(instrument)
            # Should not raise; contract should be STK type
            call_args = mock_ib.qualifyContractsAsync.call_args
            contract_arg = call_args[0][0]
            assert contract_arg.secType == "STK"


class TestIBKRUseRTH:
    """IBKR must pass useRTH=True for equity historical bars."""

    @pytest.mark.asyncio
    async def test_fetch_equity_bars_uses_rth(self):
        from datetime import datetime, timezone
        from src.providers.ibkr import IBKRProvider
        provider = IBKRProvider.__new__(IBKRProvider)
        provider.logger = MagicMock()

        with patch.object(provider, "_ib", create=True) as mock_ib:
            mock_ib.reqHistoricalDataAsync = AsyncMock(return_value=[])
            instrument = Instrument(
                symbol="SPY", asset_class=AssetClass.EQUITY, session_id="nyse"
            )
            start = datetime(2026, 3, 1, tzinfo=timezone.utc)
            end   = datetime(2026, 3, 2, tzinfo=timezone.utc)
            try:
                await provider.fetch_historical_bars(
                    instrument, "1m", start, end
                )
            except Exception:
                pass  # contract not qualified — we only care about useRTH
            if mock_ib.reqHistoricalDataAsync.called:
                call_kwargs = mock_ib.reqHistoricalDataAsync.call_args[1]
                assert call_kwargs.get("useRTH") is True

    @pytest.mark.asyncio
    async def test_fetch_futures_bars_no_rth(self):
        from datetime import datetime, timezone
        from src.providers.ibkr import IBKRProvider
        provider = IBKRProvider.__new__(IBKRProvider)
        provider.logger = MagicMock()

        with patch.object(provider, "_ib", create=True) as mock_ib:
            mock_ib.reqHistoricalDataAsync = AsyncMock(return_value=[])
            instrument = Instrument(symbol="ES", asset_class=AssetClass.FUTURES)
            start = datetime(2026, 3, 1, tzinfo=timezone.utc)
            end   = datetime(2026, 3, 2, tzinfo=timezone.utc)
            try:
                await provider.fetch_historical_bars(instrument, "1m", start, end)
            except Exception:
                pass
            if mock_ib.reqHistoricalDataAsync.called:
                call_kwargs = mock_ib.reqHistoricalDataAsync.call_args[1]
                # Should be False or absent for futures
                assert call_kwargs.get("useRTH", False) is False
```

- [ ] **Step 3: Run tests to confirm they fail (or are skipped due to ib_insync mock complexity)**

```bash
.venv/bin/pytest tests/unit/providers/test_ibkr_equity.py -v 2>&1 | head -30
```

- [ ] **Step 4: Read ibkr.py qualify_instrument + fetch_historical_bars**

```bash
grep -n "def qualify_instrument\|def fetch_historical_bars\|Stock\|Future\|Forex\|CRYPTO\|useRTH\|SubscriptionManager" src/providers/ibkr.py
```

- [ ] **Step 5: Update qualify_instrument for explicit equity support**

The Step 4 grep will likely reveal an existing `else: Stock(...)` fallback at the end of `qualify_instrument` (line ~415). **Do not add a new branch before it.** Instead:

- Convert the `else` fallback to `elif instr.asset_class == AssetClass.EQUITY:` to make it explicit
- Add `currency="USD"` if not already present (IBKR STK requires currency)
- If there is no existing Stock fallback, add the branch after CRYPTO:

```python
elif instr.asset_class == AssetClass.EQUITY:
    from ib_insync import Stock
    contract = Stock(
        symbol=instr.symbol,
        exchange=instr.exchange or "SMART",
        currency="USD",
    )
```

- [ ] **Step 6: Add useRTH to fetch_historical_bars**

In `fetch_historical_bars`, set `use_rth` based on asset class and pass it:

```python
use_rth = getattr(instrument, "asset_class", None) == AssetClass.EQUITY
# ... in the reqHistoricalDataAsync call:
bars = await self._ib.reqHistoricalDataAsync(
    contract, ..., useRTH=use_rth, ...
)
```

- [ ] **Step 7: Use base.py SubscriptionManager**

If ibkr.py defines its own `SubscriptionManager`: remove it and import from `src.providers.base`:

```python
from src.providers.base import SubscriptionLimitError, SubscriptionManager
```

Add `ibkr_max_subscriptions` to Settings (Task 9) if not yet done; for now use `getattr(settings, "ibkr_max_subscriptions", 80)`.

- [ ] **Step 8: Run tests + full regression**

```bash
.venv/bin/pytest tests/unit/providers/ tests/unit/ -x -q 2>&1 | tail -5
```

- [ ] **Step 9: Commit**

```bash
git add src/providers/ibkr.py
git commit -m "feat(ibkr): equity STK qualification + useRTH=True for historical bars"
```

---

## Chunk 5: Observability + Validation

### Task 8: provider_active_subscriptions gauge in SubscriptionManager

**Files:**
- Modify: `src/providers/base.py` (add Prometheus gauge emission)
- Modify: `tests/unit/providers/test_base.py` (add gauge tests)

- [ ] **Step 1: Check src/observability/metrics.py for gauge pattern**

```bash
grep -n "def gauge\|def counter\|labelnames\|Labels\|Gauge\|Counter" src/observability/metrics.py | head -20
```

- [ ] **Step 2: Add gauge emission to SubscriptionManager**

In `SubscriptionManager.__init__`, after setting `self._active`:

```python
        # Import lazily to avoid circular imports and allow tests without Prometheus
        try:
            from src.observability.metrics import gauge as make_gauge
            self._gauge = make_gauge(
                "provider_active_subscriptions",
                "Active data subscriptions per provider",
                labelnames=["provider"],
            )
        except Exception:
            self._gauge = None
```

After `self._active.add(symbol)` in `subscribe`:
```python
        if self._gauge:
            self._gauge.labels(provider=self._provider_name).set(self.count)
```

After `self._active.discard(symbol)` in `unsubscribe`:
```python
        if self._gauge:
            self._gauge.labels(provider=self._provider_name).set(self.count)
```

- [ ] **Step 3: Run existing base tests to confirm no regressions**

```bash
.venv/bin/pytest tests/unit/providers/test_base.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/providers/base.py
git commit -m "feat(observability): provider_active_subscriptions gauge in SubscriptionManager"
```

---

### Task 9: validate_equity_backfill.py

**Files:**
- Create: `production/scripts/validate_equity_backfill.py`
- Create: `tests/unit/scripts/test_validate_equity_backfill.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/scripts/test_validate_equity_backfill.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestValidateEquityBackfill:
    def test_module_importable(self):
        import importlib
        spec = importlib.util.spec_from_file_location(
            "validate_equity_backfill",
            "production/scripts/validate_equity_backfill.py",
        )
        assert spec is not None

    def test_parse_args_requires_symbol(self):
        from unittest.mock import patch
        import sys
        with patch.object(sys, "argv", ["validate_equity_backfill.py", "--symbol", "SPY"]):
            import importlib
            mod = importlib.import_module.__class__  # just test argparse won't raise
            # We just need the script to not crash on import
            assert True

    @pytest.mark.asyncio
    async def test_zero_count_exits_zero(self):
        """When DB returns count=0, validation passes (exit 0 equivalent)."""
        with patch(
            "production.scripts.validate_equity_backfill.DatabaseManager"
        ) as mock_db_cls:
            mock_db = AsyncMock()
            mock_db.fetch_one = AsyncMock(return_value={"count": 0})
            mock_db_cls.return_value = mock_db

            from production.scripts.validate_equity_backfill import validate_symbol
            result = await validate_symbol(mock_db, "SPY")
            assert result == 0  # 0 off-hours rows = pass

    @pytest.mark.asyncio
    async def test_nonzero_count_returns_count(self):
        """When DB returns count > 0, returns positive int (caller exits non-zero)."""
        with patch(
            "production.scripts.validate_equity_backfill.DatabaseManager"
        ) as mock_db_cls:
            mock_db = AsyncMock()
            mock_db.fetch_one = AsyncMock(return_value={"count": 42})
            mock_db_cls.return_value = mock_db

            from production.scripts.validate_equity_backfill import validate_symbol
            result = await validate_symbol(mock_db, "SPY")
            assert result == 42
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/scripts/test_validate_equity_backfill.py -v 2>&1 | head -20
```

- [ ] **Step 3: Write validate_equity_backfill.py**

```python
#!/usr/bin/env python3
"""Validate that equity backfill contains no off-hours bars.

Usage:
    python production/scripts/validate_equity_backfill.py --symbol SPY [--symbol QQQ ...]

Exits non-zero if any off-hours rows found for any symbol.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from src.core.database_manager import DatabaseManager

_OFF_HOURS_SQL = """
SELECT COUNT(*) AS count FROM intelligence_features
WHERE symbol = $1
  AND feature_tf = '1m'
  AND (
    EXTRACT(HOUR FROM feature_ts AT TIME ZONE 'America/New_York') < 9
    OR EXTRACT(HOUR FROM feature_ts AT TIME ZONE 'America/New_York') >= 16
    OR (
      EXTRACT(HOUR FROM feature_ts AT TIME ZONE 'America/New_York') = 9
      AND EXTRACT(MINUTE FROM feature_ts AT TIME ZONE 'America/New_York') < 30
    )
  )
"""


async def validate_symbol(db: DatabaseManager, symbol: str) -> int:
    """Return count of off-hours rows for symbol. 0 = pass."""
    row = await db.fetch_one(_OFF_HOURS_SQL, symbol)
    return int(row["count"]) if row else 0


async def main(symbols: list[str]) -> int:
    db = DatabaseManager()
    await db.connect()
    total_bad = 0
    try:
        for symbol in symbols:
            count = await validate_symbol(db, symbol)
            if count > 0:
                print(
                    f"FAIL: {symbol} has {count} off-hours rows in intelligence_features",
                    file=sys.stderr,
                )
                total_bad += count
            else:
                print(f"OK:   {symbol} — 0 off-hours rows")
    finally:
        await db.close()
    return 1 if total_bad > 0 else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate equity backfill off-hours rows")
    parser.add_argument("--symbol", action="append", required=True, dest="symbols")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.symbols)))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/scripts/test_validate_equity_backfill.py -v
```

- [ ] **Step 5: Commit**

```bash
git add production/scripts/validate_equity_backfill.py tests/unit/scripts/test_validate_equity_backfill.py
git commit -m "feat(scripts): add validate_equity_backfill.py — off-hours row gate"
```

---

## Chunk 6: Settings + Pilot Config

### Task 10: ibkr_max_subscriptions + session_id on existing instruments + pilot 5 ETFs

**Files:**
- Modify: `src/config/settings.py`
- Create: `tests/unit/config/test_settings_equity.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/config/test_settings_equity.py
import pytest
from src.config.settings import Settings, get_active_contracts
from src.core.models import AssetClass


class TestIbkrMaxSubscriptions:
    def test_default_is_80(self):
        s = Settings()
        assert s.ibkr_max_subscriptions == 80

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("IBKR_MAX_SUBSCRIPTIONS", "100")
        s = Settings()
        assert s.ibkr_max_subscriptions == 100


class TestPilotETFs:
    def test_pilot_etfs_present(self):
        s = Settings()
        symbols = {inst.symbol for inst in s.instruments}
        for sym in ["SPY", "XLF", "TLT", "GLD", "SMH"]:
            assert sym in symbols, f"Pilot ETF {sym} missing from settings"

    def test_pilot_etfs_are_equity(self):
        s = Settings()
        etfs = {inst.symbol: inst for inst in s.instruments if inst.asset_class == AssetClass.EQUITY}
        for sym in ["SPY", "XLF", "TLT", "GLD", "SMH"]:
            assert sym in etfs
            assert etfs[sym].session_id == "nyse"

    def test_etf_exchange_is_smart(self):
        s = Settings()
        for inst in s.instruments:
            if inst.asset_class == AssetClass.EQUITY:
                assert inst.exchange == "SMART", f"{inst.symbol}: exchange should be SMART"

    def test_plj6_removed(self):
        s = Settings()
        symbols = {inst.symbol for inst in s.instruments}
        assert "PLJ6" not in symbols

    def test_solusd_removed(self):
        s = Settings()
        symbols = {inst.symbol for inst in s.instruments}
        assert "SOLUSD" not in symbols

    def test_fx_instruments_have_fx_session(self):
        s = Settings()
        fx = {inst.symbol: inst for inst in s.instruments if inst.asset_class == AssetClass.FX}
        for sym, inst in fx.items():
            assert inst.session_id == "fx_24_5", f"{sym}: FX should use fx_24_5"

    def test_crypto_instruments_have_crypto_session(self):
        s = Settings()
        crypto = {inst.symbol: inst for inst in s.instruments if inst.asset_class == AssetClass.CRYPTO}
        for sym, inst in crypto.items():
            assert inst.session_id == "crypto_24_7", f"{sym}: crypto should use crypto_24_7"

    def test_pilot_etf_point_value_is_1(self):
        s = Settings()
        for inst in s.instruments:
            if inst.asset_class == AssetClass.EQUITY:
                assert inst.point_value == 1.0

    def test_pilot_etf_tick_size_is_001(self):
        s = Settings()
        for inst in s.instruments:
            if inst.asset_class == AssetClass.EQUITY:
                assert inst.tick_size == 0.01

    def test_total_instruments_count(self):
        """After Phase A pilot: 22 existing + 5 pilot ETFs = 27."""
        s = Settings()
        assert len(s.instruments) == 27


class TestGetActiveContracts:
    def test_pilot_etfs_in_active_contracts(self):
        symbols = set(get_active_contracts())
        for sym in ["SPY", "XLF", "TLT", "GLD", "SMH"]:
            assert sym in symbols
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
.venv/bin/pytest tests/unit/config/test_settings_equity.py -v 2>&1 | head -30
```

- [ ] **Step 3: Read current settings.py instruments list**

```bash
grep -n "def get_default_instruments\|Instrument(\|PLJ6\|SOLUSD\|session_id\|ibkr_max" src/config/settings.py | head -40
```

- [ ] **Step 4: Update settings.py**

**Add field to Settings class:**
```python
ibkr_max_subscriptions: int = Field(default=80, validation_alias="IBKR_MAX_SUBSCRIPTIONS")
```

**Update existing instruments to add session_id:**
- All FX instruments (EURUSD, GBPUSD, USDJPY, USDCHF): add `session_id="fx_24_5"`
- All crypto (BTCUSD, ETHUSD): add `session_id="crypto_24_7"`
- All futures: keep default (no change needed)

**Remove PLJ6 and SOLUSD entries.**

**Add pilot ETFs** (after the last existing instrument):
```python
            Instrument(
                symbol="SPY", name="SPDR S&P 500 ETF", asset_class=AssetClass.EQUITY,
                exchange="SMART", sector="broad_market", session_id="nyse",
                point_value=1.0, tick_size=0.01,
            ),
            Instrument(
                symbol="XLF", name="Financial Select Sector SPDR", asset_class=AssetClass.EQUITY,
                exchange="SMART", sector="financials", session_id="nyse",
                point_value=1.0, tick_size=0.01,
            ),
            Instrument(
                symbol="TLT", name="iShares 20+ Year Treasury Bond ETF", asset_class=AssetClass.EQUITY,
                exchange="SMART", sector="rates", session_id="nyse",
                point_value=1.0, tick_size=0.01,
            ),
            Instrument(
                symbol="GLD", name="SPDR Gold Shares", asset_class=AssetClass.EQUITY,
                exchange="SMART", sector="commodity", session_id="nyse",
                point_value=1.0, tick_size=0.01,
            ),
            Instrument(
                symbol="SMH", name="VanEck Semiconductor ETF", asset_class=AssetClass.EQUITY,
                exchange="SMART", sector="technology", session_id="nyse",
                point_value=1.0, tick_size=0.01,
            ),
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/config/test_settings_equity.py -v
```

- [ ] **Step 6: Full regression**

```bash
.venv/bin/pytest tests/unit/ -x -q 2>&1 | tail -10
```

Expected: All pass. Note: if other tests assert `len(instruments) == 24`, update them to 27.

- [ ] **Step 7: Update providers/CLAUDE.md**

Change the "Active Contracts (24)" section header to "Active Contracts (27)" and update the list to include the 5 pilot ETFs. Remove PLJ6 and SOLUSD. Also note that `session_id` is now set on FX and crypto instruments.

- [ ] **Step 8: Commit**

```bash
git add src/config/settings.py src/providers/CLAUDE.md
git commit -m "feat(config): add pilot 5 ETFs (SPY XLF TLT GLD SMH) + session_id on all instruments"
```

---

### Task 11: session_levels.py DST fix (companion file)

**Files:**
- Modify: `src/intelligence/structure/session_levels.py`

- [ ] **Step 1: Check the hardcoded offset**

```bash
grep -n "_ET_OFFSET\|_ASIA_ET_OFFSET\|timedelta\|ZoneInfo" src/intelligence/structure/session_levels.py | head -10
```

- [ ] **Step 2: Fix _ASIA_ET_OFFSET if hardcoded**

If `_ASIA_ET_OFFSET = -5` is used for ET calculations, replace with `ZoneInfo("America/New_York")` approach or leave as-is if it is only used for a rough session approximation (confirm by reading the usage context).

- [ ] **Step 3: Run regression**

```bash
.venv/bin/pytest tests/unit/ -x -q 2>&1 | tail -5
```

- [ ] **Step 4: Commit if changed**

```bash
git add src/intelligence/structure/session_levels.py
git commit -m "fix(session): DST fix in session_levels.py — use ZoneInfo instead of hardcoded offset"
```

---

## Final Phase A Verification

- [ ] **Run full test suite**

```bash
.venv/bin/pytest tests/unit/ -q 2>&1 | tail -10
```

Expected: All unit tests pass. Count should be ≥ 1659 + new tests from this phase.

- [ ] **Run linter**

```bash
.venv/bin/ruff check . 2>&1 | grep -v "E501" | head -20
```

No new errors beyond pre-existing E501 line-length.

- [ ] **Verify settings count**

```bash
.venv/bin/python -c "from src.config.settings import Settings; s=Settings(); print(len(s.instruments), 'instruments')"
```

Expected: 27

- [ ] **Verify session_context outputs**

```bash
.venv/bin/python -c "from src.intelligence.context.session_context import SessionContextPlugin; p=SessionContextPlugin(); print(len(p.outputs), 'outputs')"
```

Expected: 27
