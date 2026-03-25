# Canonical Bar Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `market_data_ohlcv` a complete canonical grid by synthesizing flat bars (OHLC=prev_close, volume=0) for every session-open slot that IBKR did not return trade data for.

**Architecture:** New `src/core/bar_normalizer.py` module owns all normalization logic. `historical_backfill.py` calls it inline after every IBKR fetch (before DB insert) and gains a `--normalize` flag for a one-time historical backfill of existing gaps. Calendar-aware via `pandas_market_calendars` for trading day/holiday detection; session window hours are fixed per session_id.

**Tech Stack:** `pandas-market-calendars>=4.3`, `pytz`, existing `psycopg2`, existing `Instrument` model from `src/core/models.py`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/core/bar_normalizer.py` | **Create** | `normalize_bars()` + `_generate_session_slots()` + calendar/exchange mappings |
| `tests/unit/test_bar_normalizer.py` | **Create** | Full unit test suite for normalizer |
| `production/scripts/historical_backfill.py` | **Modify** | Update `_FETCH_BARS_*` SQL + `fetch_bars()` to include `source`; inline normalize after every IBKR fetch (futures path ~1570 AND FX/crypto deep 1m path ~1616); `--normalize` flag; add `"4h": 240` to `_TF_MINUTES` |
| `requirements.txt` | **Modify** | Add `pandas-market-calendars>=4.3` |

---

## Task 1: Add dependency + skeleton

**Files:**
- Modify: `requirements.txt`
- Create: `src/core/bar_normalizer.py`

- [ ] **Step 1: Add `pandas-market-calendars` to requirements**

In `requirements.txt`, add after the existing pandas line:
```
pandas-market-calendars>=4.3
```

- [ ] **Step 2: Install it**

```bash
.venv/bin/pip install "pandas-market-calendars>=4.3"
```

Expected: installs without error.

- [ ] **Step 3: Create `src/core/bar_normalizer.py` skeleton**

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

# Minutes per timeframe
_TF_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

# IBKR exchange string → pandas_market_calendars calendar name
# Only used for futures (session_id="futures_24_5") where exchange disambiguates.
# Equities always use "SMART" exchange — handled by session_id="nyse" branch.
_FUTURES_EXCHANGE_TO_PMC: dict[str, str] = {
    "CME": "CME_Equity",   # ES, NQ, RTY
    "CBOT": "CBOT",        # YM, ZB, ZT, ZN, ZF, ZC, ZS, ZW
    "COMEX": "CME",        # GC, SI, HG  (COMEX is a CME division)
    "NYMEX": "CME",        # CL, NG      (NYMEX is a CME division)
    "CFE": "CBOE",         # VIX futures
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_bars(
    bars: list[dict],
    symbol: str,
    timeframe: str,
    session_id: str,
    exchange: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Return bars with synthetic flat fills for every open-session slot missing
    from the input.

    Synthetic bars: OHLC = prev_close, volume = 0, source = "synthetic_fill".
    If no prev_close exists at the start of a gap the gap is skipped — prices
    are never fabricated from nothing.

    Args:
        bars:       Sorted list of OHLCV dicts. Each must have keys:
                    timestamp (datetime, UTC), open, high, low, close,
                    volume, source.
        symbol:     Base symbol (e.g. "ES", "SPY"). Used for logging only.
        timeframe:  "1m" | "5m" | "15m" | "1h" | "4h" | "1d"
        session_id: Instrument session type. Valid values:
                    "futures_24_5", "nyse", "crypto_24_7", "fx_24_5"
        exchange:   IBKR exchange string from Instrument.exchange
                    (e.g. "CME", "CBOT", "SMART", "IDEALPRO", "PAXOS").
                    Required for futures to select the right PMC calendar.
        start:      Range start, UTC-aware.
        end:        Range end, UTC-aware.

    Returns:
        Complete list ordered by timestamp. Real bars preserve source.
        Synthetic bars have source="synthetic_fill".
    """
    raise NotImplementedError
```

- [ ] **Step 4: Commit skeleton**

```bash
git add src/core/bar_normalizer.py requirements.txt
git commit -m "chore: add bar_normalizer skeleton + pandas-market-calendars dep"
```

---

## Task 2: Session slot generator — crypto and FX

**Files:**
- Modify: `src/core/bar_normalizer.py`
- Create: `tests/unit/test_bar_normalizer.py`

These two session types need no calendar library — crypto is always open, FX is Mon–Fri.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_bar_normalizer.py
from datetime import datetime, timezone, timedelta
import pytest
from src.core.bar_normalizer import _generate_session_slots, _TF_MINUTES

UTC = timezone.utc


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


class TestCrypto24_7:
    def test_fills_every_slot_no_gaps(self):
        start = ts("2026-03-10 00:00:00")
        end   = ts("2026-03-10 00:05:00")
        slots = _generate_session_slots("crypto_24_7", "PAXOS", "1m", start, end)
        assert slots == [
            ts("2026-03-10 00:00:00"),
            ts("2026-03-10 00:01:00"),
            ts("2026-03-10 00:02:00"),
            ts("2026-03-10 00:03:00"),
            ts("2026-03-10 00:04:00"),
            ts("2026-03-10 00:05:00"),
        ]

    def test_weekend_included(self):
        # Saturday/Sunday — crypto trades
        start = ts("2026-03-14 12:00:00")  # Saturday
        end   = ts("2026-03-14 12:02:00")
        slots = _generate_session_slots("crypto_24_7", "PAXOS", "1m", start, end)
        assert len(slots) == 3


class TestFx24_5:
    def test_weekday_slots_included(self):
        # Monday 2026-03-09 00:00 UTC — FX open
        start = ts("2026-03-09 00:00:00")
        end   = ts("2026-03-09 00:02:00")
        slots = _generate_session_slots("fx_24_5", "IDEALPRO", "1m", start, end)
        assert len(slots) == 3

    def test_saturday_excluded(self):
        # Saturday 2026-03-14 — FX closed
        start = ts("2026-03-14 12:00:00")
        end   = ts("2026-03-14 12:05:00")
        slots = _generate_session_slots("fx_24_5", "IDEALPRO", "1m", start, end)
        assert slots == []

    def test_sunday_excluded(self):
        # Sunday 2026-03-15 — FX closed (opens 17:00 ET = 22:00 UTC)
        start = ts("2026-03-15 10:00:00")
        end   = ts("2026-03-15 10:05:00")
        slots = _generate_session_slots("fx_24_5", "IDEALPRO", "1m", start, end)
        assert slots == []
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/test_bar_normalizer.py -v 2>&1 | head -30
```

Expected: `ImportError` or `NotImplementedError`.

- [ ] **Step 3: Implement `_generate_session_slots` for crypto and FX**

Add to `src/core/bar_normalizer.py` (replace the `raise NotImplementedError` stub — add before `normalize_bars`):

```python
def _generate_session_slots(
    session_id: str,
    exchange: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> list[datetime]:
    """Return every expected bar timestamp within [start, end] for this session.

    Only timestamps that fall within a verified open session window are included.
    Overnight gaps, weekends, and exchange closures are excluded.
    """
    interval = timedelta(minutes=_TF_MINUTES[timeframe])

    if session_id == "crypto_24_7":
        return _slots_always_open(start, end, interval)

    if session_id == "fx_24_5":
        return _slots_fx(start, end, interval)

    if session_id == "nyse":
        return _slots_nyse(start, end, interval)

    if session_id == "futures_24_5":
        return _slots_futures(exchange, start, end, interval)

    raise ValueError(f"Unknown session_id: {session_id!r}")


def _slots_always_open(start: datetime, end: datetime, interval: timedelta) -> list[datetime]:
    slots = []
    t = start
    while t <= end:
        slots.append(t)
        t += interval
    return slots


def _slots_fx(start: datetime, end: datetime, interval: timedelta) -> list[datetime]:
    """Mon 00:00 UTC through Fri 24:00 UTC (weekday == 0..4)."""
    slots = []
    t = start
    while t <= end:
        if t.weekday() < 5:  # Mon=0 .. Fri=4
            slots.append(t)
        t += interval
    return slots
```

- [ ] **Step 4: Run tests — should pass**

```bash
.venv/bin/pytest tests/unit/test_bar_normalizer.py::TestCrypto24_7 tests/unit/test_bar_normalizer.py::TestFx24_5 -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/core/bar_normalizer.py tests/unit/test_bar_normalizer.py
git commit -m "feat(bar-normalizer): session slot generator — crypto and FX"
```

---

## Task 3: Session slot generator — equities (NYSE, 4am–8pm ET)

**Files:**
- Modify: `src/core/bar_normalizer.py`
- Modify: `tests/unit/test_bar_normalizer.py`

NYSE calendar determines which DAYS are trading days and when half-days end. Session window is always 04:00–20:00 ET on trading days (or until early close on half-days).

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/unit/test_bar_normalizer.py

class TestNyse:
    def test_regular_trading_day_premarket_filled(self):
        # 2026-03-10 is a Tuesday — regular trading day
        # 05:00 ET = 10:00 UTC
        start = ts("2026-03-10 09:00:00")  # 04:00 ET
        end   = ts("2026-03-10 09:02:00")  # 04:02 ET
        slots = _generate_session_slots("nyse", "SMART", "1m", start, end)
        assert len(slots) == 3

    def test_regular_trading_day_afterhours_filled(self):
        # 22:00 UTC = 18:00 ET — within after-hours window (ends 20:00 ET = 01:00 UTC next day)
        start = ts("2026-03-10 22:00:00")
        end   = ts("2026-03-10 22:02:00")
        slots = _generate_session_slots("nyse", "SMART", "1m", start, end)
        assert len(slots) == 3

    def test_overnight_gap_excluded(self):
        # 02:00 UTC = 22:00 ET previous day — outside 4am-8pm ET window
        start = ts("2026-03-10 02:00:00")
        end   = ts("2026-03-10 02:05:00")
        slots = _generate_session_slots("nyse", "SMART", "1m", start, end)
        assert slots == []

    def test_market_holiday_excluded(self):
        # 2026-01-19 is MLK Day — NYSE closed
        start = ts("2026-01-19 14:30:00")  # 9:30 ET — would be RTH open
        end   = ts("2026-01-19 14:35:00")
        slots = _generate_session_slots("nyse", "SMART", "1m", start, end)
        assert slots == []

    def test_weekend_excluded(self):
        start = ts("2026-03-14 14:30:00")  # Saturday
        end   = ts("2026-03-14 14:35:00")
        slots = _generate_session_slots("nyse", "SMART", "1m", start, end)
        assert slots == []
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/test_bar_normalizer.py::TestNyse -v 2>&1 | head -20
```

Expected: `NotImplementedError` from `_slots_nyse`.

- [ ] **Step 3: Implement `_slots_nyse`**

Add to `src/core/bar_normalizer.py`:

```python
def _slots_nyse(start: datetime, end: datetime, interval: timedelta) -> list[datetime]:
    """NYSE trading days, 04:00–20:00 ET (pre-market through after-hours).
    Half-days: session ends at early_close time instead of 20:00 ET.
    Holidays: entire day excluded.
    """
    cal = mcal.get_calendar("NYSE")

    # Fetch trading schedule for the date range (+1 day buffer)
    start_date = start.astimezone(ET).date()
    end_date = end.astimezone(ET).date()
    # IMPORTANT: tz="America/New_York" is mandatory here.
    # Without it, market_close is returned as UTC and the half-day check
    # (pmc_close_et.hour < 16) silently fails — half-days are missed.
    schedule = cal.schedule(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        tz="America/New_York",
    )

    # Build set of valid (date, open_et, close_et) tuples.
    # We override PMC's RTH times with our extended window (4am–8pm),
    # but respect early closes on half-days.
    SESSION_OPEN_ET  = {"hour": 4,  "minute": 0}
    SESSION_CLOSE_ET = {"hour": 20, "minute": 0}

    # Build per-day windows
    trading_windows: list[tuple[datetime, datetime]] = []
    for _, row in schedule.iterrows():
        day_et = row["market_open"].date()
        day_open  = datetime(day_et.year, day_et.month, day_et.day,
                             SESSION_OPEN_ET["hour"], SESSION_OPEN_ET["minute"],
                             tzinfo=ET)
        # PMC market_close is the RTH close; for half-days this is 13:00 ET.
        # We cap session end at the earlier of PMC close (for half-days) or 20:00 ET.
        pmc_close_et = row["market_close"].astimezone(ET)
        full_close_et = datetime(day_et.year, day_et.month, day_et.day,
                                 SESSION_CLOSE_ET["hour"], SESSION_CLOSE_ET["minute"],
                                 tzinfo=ET)
        # If PMC close < 16:00 ET it's a half-day — use PMC close; otherwise use 20:00 ET
        is_half_day = pmc_close_et.hour < 16
        day_close = pmc_close_et if is_half_day else full_close_et
        trading_windows.append((day_open, day_close))

    # Generate slots that fall within any trading window
    slots = []
    t = start
    while t <= end:
        t_et = t.astimezone(ET)
        for win_open, win_close in trading_windows:
            if win_open <= t_et <= win_close:
                slots.append(t)
                break
        t += interval
    return slots
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_bar_normalizer.py::TestNyse -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/core/bar_normalizer.py tests/unit/test_bar_normalizer.py
git commit -m "feat(bar-normalizer): NYSE session slot generator — 4am-8pm ET, calendar-aware"
```

---

## Task 4: Session slot generator — futures

**Files:**
- Modify: `src/core/bar_normalizer.py`
- Modify: `tests/unit/test_bar_normalizer.py`

Futures use PMC calendars via `_FUTURES_EXCHANGE_TO_PMC` mapping. The PMC calendar encodes Globex session hours including the Sunday maintenance window.

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/unit/test_bar_normalizer.py

class TestFutures24_5:
    def test_cme_weekday_session_filled(self):
        # Tuesday 2026-03-10 02:00 UTC — CME Globex open
        start = ts("2026-03-10 02:00:00")
        end   = ts("2026-03-10 02:02:00")
        slots = _generate_session_slots("futures_24_5", "CME", "1m", start, end)
        assert len(slots) == 3

    def test_cbot_weekday_session_filled(self):
        start = ts("2026-03-10 02:00:00")
        end   = ts("2026-03-10 02:02:00")
        slots = _generate_session_slots("futures_24_5", "CBOT", "1m", start, end)
        assert len(slots) == 3

    def test_weekend_excluded(self):
        # Saturday 2026-03-14 — Globex closed
        start = ts("2026-03-14 12:00:00")
        end   = ts("2026-03-14 12:05:00")
        slots = _generate_session_slots("futures_24_5", "CME", "1m", start, end)
        assert slots == []

    def test_unknown_exchange_raises(self):
        with pytest.raises((KeyError, ValueError)):
            _generate_session_slots("futures_24_5", "UNKNOWN_XYZ", "1m",
                                    ts("2026-03-10 02:00:00"),
                                    ts("2026-03-10 02:05:00"))
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/test_bar_normalizer.py::TestFutures24_5 -v 2>&1 | head -20
```

- [ ] **Step 3: Implement `_slots_futures`**

Add to `src/core/bar_normalizer.py`:

```python
def _slots_futures(
    exchange: str,
    start: datetime,
    end: datetime,
    interval: timedelta,
) -> list[datetime]:
    """CME/CBOT/COMEX/NYMEX/CFE Globex sessions via pandas_market_calendars.

    PMC encodes Globex hours including the Sunday maintenance window.
    Falls back gracefully: if PMC returns no schedule for a date range
    (e.g. extremely short range), returns empty list.
    """
    pmc_name = _FUTURES_EXCHANGE_TO_PMC[exchange]  # KeyError on unknown exchange
    cal = mcal.get_calendar(pmc_name)

    start_date = start.astimezone(UTC).date()
    end_date = end.astimezone(UTC).date()

    try:
        schedule = cal.schedule(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
    except Exception:
        return []

    if schedule.empty:
        return []

    # Build list of (session_open_utc, session_close_utc) from PMC schedule
    windows: list[tuple[datetime, datetime]] = []
    for _, row in schedule.iterrows():
        win_open  = row["market_open"].to_pydatetime().astimezone(UTC)
        win_close = row["market_close"].to_pydatetime().astimezone(UTC)
        windows.append((win_open, win_close))

    slots = []
    t = start
    while t <= end:
        for win_open, win_close in windows:
            if win_open <= t <= win_close:
                slots.append(t)
                break
        t += interval
    return slots
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_bar_normalizer.py::TestFutures24_5 -v
```

Expected: all green. If CME Sunday maintenance test fails, verify by inspecting PMC schedule:
```python
import pandas_market_calendars as mcal
cal = mcal.get_calendar("CME_Equity")
print(cal.schedule(start_date="2026-03-14", end_date="2026-03-16"))
```

- [ ] **Step 5: Commit**

```bash
git add src/core/bar_normalizer.py tests/unit/test_bar_normalizer.py
git commit -m "feat(bar-normalizer): futures session slot generator — CME/CBOT/COMEX/NYMEX/CFE"
```

---

## Task 5: `normalize_bars` core algorithm

**Files:**
- Modify: `src/core/bar_normalizer.py`
- Modify: `tests/unit/test_bar_normalizer.py`

- [ ] **Step 1: Write failing tests**

```python
# Add to tests/unit/test_bar_normalizer.py
from src.core.bar_normalizer import normalize_bars


def make_bar(timestamp: str, close: float, source: str = "historical_backfill") -> dict:
    t = datetime.fromisoformat(timestamp).replace(tzinfo=UTC)
    return {
        "timestamp": t, "open": close, "high": close,
        "low": close, "close": close, "volume": 100,
        "source": source,
    }


class TestNormalizeBars:
    def test_no_gaps_returns_unchanged(self):
        bars = [
            make_bar("2026-03-10 14:00:00", 100.0),
            make_bar("2026-03-10 14:01:00", 101.0),
            make_bar("2026-03-10 14:02:00", 102.0),
        ]
        result = normalize_bars(
            bars, "SPY", "1m", "nyse", "SMART",
            ts("2026-03-10 14:00:00"), ts("2026-03-10 14:02:00"),
        )
        assert len(result) == 3
        assert all(b["source"] == "historical_backfill" for b in result)

    def test_gap_filled_with_prev_close(self):
        bars = [
            make_bar("2026-03-10 14:00:00", 100.0),
            # 14:01 missing
            make_bar("2026-03-10 14:02:00", 102.0),
        ]
        result = normalize_bars(
            bars, "SPY", "1m", "nyse", "SMART",
            ts("2026-03-10 14:00:00"), ts("2026-03-10 14:02:00"),
        )
        assert len(result) == 3
        synthetic = result[1]
        assert synthetic["timestamp"] == ts("2026-03-10 14:01:00")
        assert synthetic["open"]   == 100.0
        assert synthetic["high"]   == 100.0
        assert synthetic["low"]    == 100.0
        assert synthetic["close"]  == 100.0
        assert synthetic["volume"] == 0
        assert synthetic["source"] == "synthetic_fill"

    def test_no_prev_close_gap_at_start_skipped(self):
        # First two bars missing — no prev_close to fill from
        bars = [make_bar("2026-03-10 14:02:00", 102.0)]
        result = normalize_bars(
            bars, "SPY", "1m", "nyse", "SMART",
            ts("2026-03-10 14:00:00"), ts("2026-03-10 14:02:00"),
        )
        # 14:00 and 14:01 have no prev_close — skipped
        assert len(result) == 1
        assert result[0]["timestamp"] == ts("2026-03-10 14:02:00")

    def test_source_preserved_on_real_bars(self):
        bars = [
            make_bar("2026-03-10 14:00:00", 100.0, source="derived_1m"),
            make_bar("2026-03-10 14:01:00", 101.0, source="historical_backfill"),
        ]
        result = normalize_bars(
            bars, "SPY", "1m", "nyse", "SMART",
            ts("2026-03-10 14:00:00"), ts("2026-03-10 14:01:00"),
        )
        assert result[0]["source"] == "derived_1m"
        assert result[1]["source"] == "historical_backfill"

    def test_overnight_gap_not_filled(self):
        # 20:00 ET Friday → 04:00 ET Monday — overnight/weekend, no fills
        bars = [
            make_bar("2026-03-13 01:00:00", 100.0),  # 20:00 ET Friday (UTC+5)
            make_bar("2026-03-16 09:00:00", 101.0),  # 04:00 ET Monday (UTC+5)
        ]
        result = normalize_bars(
            bars, "SPY", "1m", "nyse", "SMART",
            ts("2026-03-13 01:00:00"), ts("2026-03-16 09:00:00"),
        )
        # Only the two real bars — no synthetic fills across session boundary
        assert len(result) == 2

    def test_idempotent(self):
        bars = [
            make_bar("2026-03-10 14:00:00", 100.0),
            make_bar("2026-03-10 14:02:00", 102.0),
        ]
        result1 = normalize_bars(
            bars, "SPY", "1m", "nyse", "SMART",
            ts("2026-03-10 14:00:00"), ts("2026-03-10 14:02:00"),
        )
        result2 = normalize_bars(
            result1, "SPY", "1m", "nyse", "SMART",
            ts("2026-03-10 14:00:00"), ts("2026-03-10 14:02:00"),
        )
        assert len(result1) == len(result2)
        for b1, b2 in zip(result1, result2):
            assert b1["timestamp"] == b2["timestamp"]
            assert b1["source"] == b2["source"]

    def test_crypto_fills_across_weekend(self):
        # 2026-03-14 Sat → 2026-03-15 Sun — crypto always open
        bars = [
            make_bar("2026-03-14 12:00:00", 50000.0),
            make_bar("2026-03-14 12:02:00", 50010.0),
        ]
        result = normalize_bars(
            bars, "BTC", "1m", "crypto_24_7", "PAXOS",
            ts("2026-03-14 12:00:00"), ts("2026-03-14 12:02:00"),
        )
        assert len(result) == 3
        assert result[1]["source"] == "synthetic_fill"
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/test_bar_normalizer.py::TestNormalizeBars -v 2>&1 | head -20
```

Expected: `NotImplementedError`.

- [ ] **Step 3: Implement `normalize_bars`**

Replace the `raise NotImplementedError` stub in `normalize_bars`:

```python
def normalize_bars(
    bars: list[dict],
    symbol: str,
    timeframe: str,
    session_id: str,
    exchange: str,
    start: datetime,
    end: datetime,
) -> list[dict]:
    expected_slots = _generate_session_slots(session_id, exchange, timeframe, start, end)
    if not expected_slots:
        return list(bars)

    # Index real bars by timestamp (normalize to UTC, strip sub-second)
    bar_index: dict[datetime, dict] = {}
    for b in bars:
        t = b["timestamp"]
        if t.tzinfo is None:
            t = t.replace(tzinfo=UTC)
        bar_index[t.replace(microsecond=0)] = b

    result: list[dict] = []
    prev_close: float | None = None

    for slot in expected_slots:
        slot_utc = slot.replace(microsecond=0)
        if slot_utc in bar_index:
            bar = bar_index[slot_utc]
            result.append(bar)
            prev_close = float(bar["close"])
        else:
            if prev_close is None:
                # No price context yet — skip
                continue
            result.append({
                "timestamp": slot_utc,
                "open":   prev_close,
                "high":   prev_close,
                "low":    prev_close,
                "close":  prev_close,
                "volume": 0,
                "source": "synthetic_fill",
            })
            # prev_close stays the same for chained flat bars

    return result
```

- [ ] **Step 4: Run all tests**

```bash
.venv/bin/pytest tests/unit/test_bar_normalizer.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/core/bar_normalizer.py tests/unit/test_bar_normalizer.py
git commit -m "feat(bar-normalizer): normalize_bars core algorithm with session-aware fill"
```

---

## Task 6: Wire into `historical_backfill.py` — inline fetch normalization

**Files:**
- Modify: `production/scripts/historical_backfill.py`

Two fetch paths need normalization: (1) the futures gap-fill loop at ~line 1570, (2) the FX/crypto deep 1m fetch at ~line 1616. The derived-TF aggregation path (~line 1624) does NOT need normalization — it derives from the 1m bars which are already canonical after the 1m fetch is normalized.

`run_normalize()` in Task 7 calls `fetch_bars()` and passes results to `normalize_bars()` — this requires `fetch_bars()` to return `source` in each bar dict. Currently it does not (SQL SELECTs only 6 columns, no `source`). Fix this first.

- [ ] **Step 1: Update all 4 `_FETCH_BARS_*` SQL constants to include `source`**

All four constants at lines 991–1017 need `source` added to the SELECT:

```python
# Lines 991–996:
_FETCH_BARS_SQL = """
SELECT timestamp, open, high, low, close, volume, source
FROM market_data_ohlcv
WHERE symbol = %s AND timeframe = %s
ORDER BY timestamp ASC
"""

# Lines 998–1003:
_FETCH_BARS_SINCE_SQL = """
SELECT timestamp, open, high, low, close, volume, source
FROM market_data_ohlcv
WHERE symbol = %s AND timeframe = %s AND timestamp >= %s
ORDER BY timestamp ASC
"""

# Lines 1005–1010:
_FETCH_BARS_BASE_SQL = """
SELECT timestamp, open, high, low, close, volume, source
FROM market_data_ohlcv
WHERE symbol LIKE %s AND timeframe = %s
ORDER BY timestamp ASC
"""

# Lines 1012–1017:
_FETCH_BARS_BASE_SINCE_SQL = """
SELECT timestamp, open, high, low, close, volume, source
FROM market_data_ohlcv
WHERE symbol LIKE %s AND timeframe = %s AND timestamp >= %s
ORDER BY timestamp ASC
"""
```

- [ ] **Step 2: Update `fetch_bars()` dict construction to include `source` (line 1132–1144)**

```python
# Before:
bars = [
    {
        "timestamp": row[0] if row[0].tzinfo else row[0].replace(tzinfo=UTC),
        "symbol": symbol,
        "timeframe": timeframe,
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
    }
    for row in rows
]

# After:
bars = [
    {
        "timestamp": row[0] if row[0].tzinfo else row[0].replace(tzinfo=UTC),
        "symbol": symbol,
        "timeframe": timeframe,
        "open": float(row[1]),
        "high": float(row[2]),
        "low": float(row[3]),
        "close": float(row[4]),
        "volume": float(row[5]),
        "source": row[6] or "historical_backfill",
    }
    for row in rows
]
```

- [ ] **Step 3: Add `"4h": 240` to `_TF_MINUTES`**

In `historical_backfill.py` at line 1069:

```python
# Before:
_TF_MINUTES: dict[str, int] = {"5m": 5, "15m": 15, "1h": 60, "1d": 1440}

# After:
_TF_MINUTES: dict[str, int] = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
```

- [ ] **Step 4: Add import for `normalize_bars`**

At the top of `historical_backfill.py` with other local imports:

```python
from src.core.bar_normalizer import normalize_bars
```

- [ ] **Step 5: Wire normalization into the futures gap-fill path (~line 1558–1570)**

```python
# Before:
bar_dicts = [
    {
        "timestamp": b.timestamp,
        "open": b.open,
        "high": b.high,
        "low": b.low,
        "close": b.close,
        "volume": b.volume,
        "source": b.source,
    }
    for b in ohlcv_bars
]
n = store_bars(db_conn, bar_dicts, instrument.symbol, tf)

# After:
bar_dicts = [
    {
        "timestamp": b.timestamp,
        "open": b.open,
        "high": b.high,
        "low": b.low,
        "close": b.close,
        "volume": b.volume,
        "source": b.source,
    }
    for b in ohlcv_bars
]
canonical = normalize_bars(
    bar_dicts,
    symbol=instrument.symbol,
    timeframe=tf,
    session_id=instrument.session_id,
    exchange=instrument.exchange,
    start=gap_start,
    end=gap_end,
)
n = store_bars(db_conn, canonical, instrument.symbol, tf)
```

- [ ] **Step 6: Wire normalization into the FX/crypto deep 1m fetch path (~line 1604–1616)**

```python
# Before:
deep_dicts = [{"timestamp": b.timestamp, "open": b.open, "high": b.high,
               "low": b.low, "close": b.close, "volume": b.volume,
               "source": b.source} for b in deep_bars]
n = store_bars(db_conn, deep_dicts, instrument.symbol, "1m")

# After:
deep_dicts = [{"timestamp": b.timestamp, "open": b.open, "high": b.high,
               "low": b.low, "close": b.close, "volume": b.volume,
               "source": b.source} for b in deep_bars]
canonical_1m = normalize_bars(
    deep_dicts,
    symbol=instrument.symbol,
    timeframe="1m",
    session_id=instrument.session_id,
    exchange=instrument.exchange,
    start=start_dt,
    end=end_dt,
)
n = store_bars(db_conn, canonical_1m, instrument.symbol, "1m")
```

Note: the derived-TF aggregation path at ~line 1624 (`aggregate_bars_from_1m`) does NOT need normalization — it derives from the now-canonical 1m bars.

- [ ] **Step 7: Verify lint passes**

```bash
.venv/bin/ruff check production/scripts/historical_backfill.py
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add production/scripts/historical_backfill.py
git commit -m "feat(backfill): normalize_bars inline after every IBKR fetch — canonical grid on all writes"
```

---

## Task 7: `--normalize` flag for historical data

**Files:**
- Modify: `production/scripts/historical_backfill.py`

- [ ] **Step 1: Add `--normalize` argument to argparse**

Find the `add_argument` block in `main()` and add:

```python
parser.add_argument(
    "--normalize",
    action="store_true",
    default=False,
    help="Fill gaps in existing market_data_ohlcv rows with synthetic flat bars. "
         "Idempotent — safe to re-run. Combines with --symbols to limit scope.",
)
```

- [ ] **Step 2: Implement `run_normalize()` function**

Add before `main()`:

```python
def run_normalize(
    db_conn: Any,
    contracts: list[Any],
    timeframes: list[str],
    settings: Settings,
) -> None:
    """One-time pass: fill gaps in existing market_data_ohlcv with synthetic
    flat bars so the table holds a complete canonical grid.

    Idempotent — existing rows are never overwritten (ON CONFLICT DO NOTHING).
    """
    print("\nNormalization pass — filling gaps in market_data_ohlcv")
    print(f"  Symbols   : {[c.symbol for c in contracts]}")
    print(f"  Timeframes: {timeframes}")

    total_inserted = 0

    for instrument in contracts:
        for tf in timeframes:
            rows = fetch_bars(db_conn, instrument.symbol, tf)
            if not rows:
                print(f"  {instrument.symbol}/{tf}: no existing rows — skipping")
                continue

            # Determine stored range
            start = min(b["timestamp"] for b in rows)
            end   = max(b["timestamp"] for b in rows)

            canonical = normalize_bars(
                rows,
                symbol=instrument.symbol,
                timeframe=tf,
                session_id=instrument.session_id,
                exchange=instrument.exchange,
                start=start,
                end=end,
            )

            # Only insert bars that don't already exist
            existing_ts = {b["timestamp"] for b in rows}
            new_bars = [b for b in canonical if b["timestamp"] not in existing_ts]

            if not new_bars:
                print(f"  {instrument.symbol}/{tf}: already canonical ({len(rows)} rows)")
                continue

            n = store_bars(db_conn, new_bars, instrument.symbol, tf)
            total_inserted += n
            print(f"  {instrument.symbol}/{tf}: inserted {n} synthetic fills "
                  f"(was {len(rows)} rows, now {len(rows) + n})")

    print(f"\nNormalization complete: {total_inserted} synthetic fills inserted")
```

- [ ] **Step 3: Call `run_normalize()` in `main()` when flag is set**

After the contracts/timeframes are resolved in `main()`, add:

```python
if args.normalize:
    run_normalize(db_conn, contracts, timeframes, settings)
    db_conn.close()
    return
```

Place this before the Stage 1 / Stage 2 blocks so `--normalize` is a standalone operation.

- [ ] **Step 4: Verify lint**

```bash
.venv/bin/ruff check production/scripts/historical_backfill.py
```

- [ ] **Step 5: Run unit tests to confirm nothing broken**

```bash
.venv/bin/pytest tests/unit/test_bar_normalizer.py -v
```

- [ ] **Step 6: Commit**

```bash
git add production/scripts/historical_backfill.py
git commit -m "feat(backfill): --normalize flag — canonical gap fill for existing market_data_ohlcv"
```

---

## Task 8: Smoke test + run `--normalize` on live data

- [ ] **Step 1: Verify `normalize_bars` import works end-to-end**

```bash
.venv/bin/python -c "
from src.core.bar_normalizer import normalize_bars
print('normalize_bars import OK')
"
```

- [ ] **Step 2: Dry-run `--normalize` on one symbol**

```bash
.venv/bin/python production/scripts/historical_backfill.py \
  --normalize --symbols ESM6 --timeframes 1m
```

Review output — confirm it reports inserted synthetic fills and no errors.

- [ ] **Step 3: Verify canonical rows in DB**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "
SELECT source, COUNT(*)
FROM market_data_ohlcv
WHERE symbol = 'ESM6' AND timeframe = '1m'
  AND timestamp > NOW() - INTERVAL '2 days'
GROUP BY source
ORDER BY source;
"
```

Expected: rows with `source='synthetic_fill'` appearing alongside `historical_backfill` / `authoritative`.

- [ ] **Step 4: Run full `--normalize` across all symbols**

```bash
.venv/bin/python production/scripts/historical_backfill.py --normalize
```

This will take a few minutes. Monitor output for errors.

- [ ] **Step 5: Verify canonical row counts**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "
SELECT timeframe, source, COUNT(*), MAX(timestamp)
FROM market_data_ohlcv
GROUP BY timeframe, source
ORDER BY timeframe, source;
"
```

- [ ] **Step 6: Full test suite**

```bash
.venv/bin/pytest tests/unit/ -v
```

- [ ] **Step 7: Final commit**

```bash
git add -A
git commit -m "feat: canonical bar normalization complete — market_data_ohlcv is now a canonical grid"
```
