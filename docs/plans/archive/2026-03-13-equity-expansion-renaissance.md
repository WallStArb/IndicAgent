# Equity Expansion — Renaissance Spec

**Date:** 2026-03-13
**Status:** Approved — supersedes `docs/plans/2026-03-13-equity-expansion-design.md`
**Scope:** Add 38 ETFs + full global session infrastructure to IndicAgent.

---

## Primary Goal

The primary value of this phase is **a complete, clean cross-asset feature store**. Every ETF bar that flows through the pipeline deposits a full feature vector into `intelligence_features`, timestamped at bar-open time. A JOIN on `(feature_ts, feature_tf)` across all symbols reconstructs the full market state at any moment — what ES was doing, what JNK was doing, what SMH was doing — all in one query. This is the labeled training dataset for the cross-asset confluence model (future milestone).

Standalone ETF signals are a side effect, not the goal.

---

## Phase Split

**Phase A — Infrastructure + Pilot (5 ETFs)**
All model changes, session redesign, provider abstraction, plugin guard, observability, validation script, and a pilot of 5 ETFs (SPY, XLF, TLT, GLD, SMH). Pilot covers 5 distinct correlation regimes.

**Phase B — Full ETF Rollout (33 ETFs)**
Remaining 33 ETFs added once pilot validates the pipeline end-to-end.

---

## Section 1: TradingSession Model

### Model definition

Added to `src/core/models.py` after `AssetClass`, before `DataSource`:

```python
from dataclasses import dataclass
from datetime import time, datetime
from zoneinfo import ZoneInfo

@dataclass(frozen=True)
class TradingSession:
    open_time: time
    close_time: time
    timezone: str
    trading_days: frozenset[int] = frozenset({0, 1, 2, 3, 4})
    trading_breaks: tuple[tuple[time, time], ...] = ()  # (start, end) pairs in local time

    def is_open(self, utc_ts: datetime) -> bool:
        """True if market is open at this UTC timestamp (trading_breaks are NOT considered closed)."""
        local = utc_ts.astimezone(ZoneInfo(self.timezone))
        if local.weekday() not in self.trading_days:
            return False
        t = local.time().replace(second=0, microsecond=0)
        if self.open_time == self.close_time:
            return True  # all-day session on this trading day
        elif self.open_time < self.close_time:
            return self.open_time <= t < self.close_time
        else:
            return t >= self.open_time or t < self.close_time  # wraps midnight

    def in_trading_break(self, utc_ts: datetime) -> bool:
        """True if market is in a scheduled trading break (lunch, etc.)."""
        if not self.trading_breaks:
            return False
        local = utc_ts.astimezone(ZoneInfo(self.timezone))
        t = local.time().replace(second=0, microsecond=0)
        return any(start <= t < end for start, end in self.trading_breaks)

    def elapsed_fraction(self, utc_ts: datetime) -> float | None:
        """Fraction of trading session elapsed (0.0→1.0), excluding break durations.

        Returns None for all-day sessions (open_time == close_time) or when closed.
        0.0 at open, 1.0 at close.
        """
        if self.open_time == self.close_time:
            return None  # all-day session — fraction meaningless
        if not self.is_open(utc_ts):
            return None
        local = utc_ts.astimezone(ZoneInfo(self.timezone))
        t = local.time().replace(second=0, microsecond=0)
        from datetime import datetime as _dt, date as _date
        ref_date = _date(2000, 1, 2)  # Monday — safe anchor for time arithmetic
        t_dt  = _dt.combine(ref_date, t)
        op_dt = _dt.combine(ref_date, self.open_time)
        cl_dt = _dt.combine(ref_date, self.close_time)
        if self.open_time > self.close_time:  # midnight wrap
            cl_dt = _dt.combine(_date(2000, 1, 3), self.close_time)
            if t < self.open_time:
                t_dt = _dt.combine(_date(2000, 1, 3), t)
        session_total = (cl_dt - op_dt).total_seconds()
        # Subtract break durations from denominator
        for brk_start, brk_end in self.trading_breaks:
            bs_dt = _dt.combine(ref_date, brk_start)
            be_dt = _dt.combine(ref_date, brk_end)
            # Clip break to [open, close]
            bs_dt = max(bs_dt, op_dt)
            be_dt = min(be_dt, cl_dt)
            if be_dt > bs_dt:
                session_total -= (be_dt - bs_dt).total_seconds()
        # Elapsed time, excluding breaks that have already passed
        elapsed = (t_dt - op_dt).total_seconds()
        for brk_start, brk_end in self.trading_breaks:
            bs_dt = _dt.combine(ref_date, brk_start)
            be_dt = _dt.combine(ref_date, brk_end)
            if be_dt <= t_dt:  # break fully past
                elapsed -= (be_dt - bs_dt).total_seconds()
            elif bs_dt < t_dt:  # inside break — elapsed stops counting
                elapsed -= (t_dt - bs_dt).total_seconds()
        return max(0.0, min(1.0, elapsed / session_total))
```

**Key behavior:**
- `is_open()` does NOT treat `trading_breaks` as closed — breaks are intra-session pauses. This is correct: IBKR continues streaming bars during breaks; the break flag is a feature, not a gate.
- `in_trading_break()` is a feature flag, not a gating predicate.
- `elapsed_fraction()` returns `None` for all-day sessions (futures_24_5, fx_24_5, crypto_24_7) — fraction is meaningless when the session runs all day.
- Midnight-wrapping sessions (futures: 18:00→17:00) are handled in both `is_open()` and `elapsed_fraction()`.

---

## Section 2: SESSION_REGISTRY Split

### EXCHANGE_SESSIONS

Exchange sessions define the trading day for specific stock exchanges. Iterating this dict drives the data-driven SessionContextPlugin outputs.

```python
EXCHANGE_SESSIONS: dict[str, TradingSession] = {
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
```

### CONTINUOUS_SESSIONS

Continuous sessions (all-day, multi-day) — `open_time == close_time` signals all-day behavior.

```python
CONTINUOUS_SESSIONS: dict[str, TradingSession] = {
    "futures_24_5": TradingSession(time(18, 0), time(17, 0), "America/Chicago",
                                   trading_days=frozenset({0, 1, 2, 3, 4, 6})),  # Mon-Fri + Sun
    "fx_24_5":      TradingSession(time(0, 0),  time(0, 0),  "UTC",
                                   trading_days=frozenset({0, 1, 2, 3, 4, 6})),
    "crypto_24_7":  TradingSession(time(0, 0),  time(0, 0),  "UTC",
                                   trading_days=frozenset(range(7))),
}
```

### Unified registry + overlaps

```python
SESSION_REGISTRY: dict[str, TradingSession] = {
    **EXCHANGE_SESSIONS,
    **CONTINUOUS_SESSIONS,
}

MARKET_OVERLAPS: dict[str, tuple[str, str]] = {
    "tokyo_london":  ("tse",   "lse"),
    "london_ny":     ("lse",   "nyse"),
    "ny_sydney":     ("nyse",  "asx"),
}
```

**Backward compat:** The old singleton names still resolve via `SESSION_REGISTRY["nyse"]`, etc. Code referencing them by name does not break.

---

## Section 3: Instrument Model Changes

### session_id field

```python
class Instrument(BaseModel):
    ...existing fields...
    session_id: str = "futures_24_5"  # key into SESSION_REGISTRY

    @field_validator("session_id")
    @classmethod
    def validate_session(cls, v: str) -> str:
        if v not in SESSION_REGISTRY:
            raise ValueError(f"Unknown session_id {v!r}. Known: {list(SESSION_REGISTRY)}")
        return v

    @property
    def trading_session(self) -> TradingSession:
        return SESSION_REGISTRY[self.session_id]
```

**Default `"futures_24_5"`** — all existing instruments that omit `session_id` continue working unchanged.

### session_id assignments (existing instruments)

All FX instruments: `session_id="fx_24_5"`
All crypto instruments: `session_id="crypto_24_7"`
All futures: keep default `"futures_24_5"`
ETFs: `session_id="nyse"`

### Instruments removed from defaults

- `PLJ6` (Platinum): removed. Paper trading unavailable, no signal value.
- `SOLUSD` (Solana): removed. Low signal quality, subscription slot cost.

**Total after Phase A:** 20 futures + 5 pilot ETFs = 25 instruments
**Total after Phase B:** 20 futures + 38 ETFs = 58 instruments

Note: Futures count drops from 24 to 20 (remove PLJ6 + FX 4 + Crypto 2 shift in labeling — wait, let me clarify: the 20 count is: ES NQ RTY YM CL GC SI HG VX ZN ZF ZB ZT ZS ZC ZW EURUSD GBPUSD USDJPY USDCHF BTCUSD ETHUSD = 22. Removing PLJ6 and SOLUSD = 22 instruments.)

**Corrected totals:**
- After Phase A: 22 instruments + 5 pilot ETFs = 27
- After Phase B: 22 instruments + 38 ETFs = 60

---

## Section 4: SessionContextPlugin Redesign

### Motivation

The existing plugin outputs 12 values and uses a hardcoded `_ET_OFFSET = timedelta(hours=-5)` which is wrong for DST. It also has no global exchange awareness — useful only for US-centric analysis.

The redesigned plugin outputs **27 values**, is entirely data-driven from `EXCHANGE_SESSIONS` and `MARKET_OVERLAPS`, and uses `ZoneInfo` for correct DST handling.

### Output taxonomy (27 total)

**Existing outputs — unchanged (12):**
```
session_asia, session_london, session_ny, session_london_ny_overlap
session_after_hours
in_london_killzone, in_ny_killzone
minutes_to_ny_open, minutes_to_london_open
bars_since_session_start
is_monday, is_friday
```

**New: exchange active flags — data-driven from EXCHANGE_SESSIONS (6):**
```
session_nyse_active, session_lse_active, session_tse_active
session_hkex_active, session_sse_active, session_asx_active
```

**New: trading break flags — only for sessions with trading_breaks (3):**
```
session_tse_in_break, session_hkex_in_break, session_sse_in_break
```

**New: market overlap flags — from MARKET_OVERLAPS (2):**
```
session_tokyo_london_overlap, session_ny_sydney_overlap
```
(`session_london_ny_overlap` already exists from legacy outputs — keep that name, source from MARKET_OVERLAPS)

**New: instrument sub-session — requires `frames["__instrument__"]` (4):**
```
session_elapsed_frac     — 0.0→1.0, 0.0 for all-day/closed sessions
is_opening_range         — 1.0 if first 30 min of instrument's trading_session
is_lunch_consolidation   — 1.0 if in_trading_break() when breaks exist, else 30–65% elapsed
is_power_hour            — 1.0 if last 60 min of instrument's trading_session
```

### DST fix

Replace `_ET_OFFSET = timedelta(hours=-5)` / `_et_from_utc()` with `ZoneInfo("America/New_York")`.

The `_SESSIONS` and `_KILLZONES` dicts remain in local wall-clock time — they do not change.

### Backward compat

All 12 existing outputs keep their exact names and semantics. The new 15 outputs are additive.
Any downstream consumer reading existing outputs is unaffected.

### `frames["__instrument__"]` injection

The compute loop in `indicator_service` and `market_analysis_service` injects `instrument` into `frames` before calling `compute_full()`:

```python
frames["__instrument__"] = self._instrument_map[symbol]
```

`SessionContextPlugin.compute_full()` reads it via `frames.get("__instrument__")`. When absent (e.g., in tests that don't inject it), the 4 sub-session outputs default to `0.0`.

---

## Section 5: Plugin Asset-Class Compatibility Layer

### Protocol change

Both `IndicatorPlugin` and `PatternPlugin` protocols in `src/intelligence/plugins.py` gain:

```python
from src.core.models import AssetClass

class IndicatorPlugin(Protocol):
    ...
    valid_asset_classes: ClassVar[frozenset[AssetClass]]  # default: frozenset(AssetClass)
    ...
```

Fully backward compatible — existing plugins that don't declare this field get the default (all asset classes) at runtime via `getattr(plugin, "valid_asset_classes", frozenset(AssetClass))`.

### Guard in compute loop

Both `indicator_service._run_i1_plugins()` and `market_analysis_service`'s plugin loop gain:

```python
instrument = self._instrument_map.get(symbol)
...
for plugin_name in tier_plugins:
    p = self._plugin_cache[plugin_name]
    allowed = getattr(p, "valid_asset_classes", frozenset(AssetClass))
    if instrument and instrument.asset_class not in allowed:
        plugin_skipped_total.labels(
            plugin_name=plugin_name,
            asset_class=instrument.asset_class.value,
        ).inc()
        continue
    frames["__instrument__"] = instrument
    ...compute_full()...
```

**Skip = absent from output dict.** Not `None`, not `0.0`. A missing field is interpretable; a garbage field is not.

### Current audit result

Zero existing plugins need non-default `valid_asset_classes`. ICTKillzones, AMDCycle, SessionContext produce valid output for ETFs during market hours. VWAP handles session reset by date boundary. The guard exists for future futures-only plugins (roll momentum, COT positioning, basis).

### `_instrument_map` construction

Built once at service init from `get_active_contracts()`:

```python
# indicator_service.__init__:
settings = Settings()
instruments = settings.instruments  # list[Instrument]
self._instrument_map: dict[str, Instrument] = {
    inst.symbol: inst for inst in instruments
}
```

---

## Section 6: Provider Abstraction

### SubscriptionManager moves to base.py

`SubscriptionManager` and `SubscriptionLimitError` are generic utilities — not IBKR-specific. Move them to `src/providers/base.py`:

```python
class SubscriptionLimitError(Exception):
    """Raised when provider subscription limit is reached."""

class SubscriptionManager:
    """Generic subscription slot tracker — provider-agnostic."""

    def __init__(self, provider_name: str, max_subscriptions: int) -> None:
        self._provider_name = provider_name
        self._max = max_subscriptions
        self._active: set[str] = set()

    def subscribe(self, symbol: str) -> None:
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

`IBKRProvider` instantiates: `SubscriptionManager("ibkr", settings.ibkr_max_subscriptions)`.

### Settings field

```python
ibkr_max_subscriptions: int = Field(default=80, validation_alias="IBKR_MAX_SUBSCRIPTIONS")
```

### IBKR equity support

`IBKRProvider.qualify_instrument()` gains an `AssetClass.EQUITY` branch:

```python
elif instr.asset_class == AssetClass.EQUITY:
    contract = Stock(symbol=instr.symbol, exchange="SMART", currency="USD")
```

`IBKRProvider.fetch_historical_bars()` passes `useRTH=True` for equities:

```python
use_rth = instrument.asset_class == AssetClass.EQUITY
bars = await self._ib.reqHistoricalDataAsync(
    contract, ..., useRTH=use_rth, ...
)
```

`stream_ticks()` requires no change — equity symbols subscribe identically to futures via `reqMktData`.

### Observability from SubscriptionManager

Emit a Prometheus gauge on subscribe/unsubscribe:

```python
provider_active_subscriptions_gauge.labels(provider=self._provider_name).set(self.count)
```

Gauge name: `provider_active_subscriptions` with label `provider`.

---

## Section 7: Observability

### New metrics

| Metric | Type | Labels | When emitted |
|---|---|---|---|
| `provider_active_subscriptions` | gauge | `provider` | On subscribe / unsubscribe in SubscriptionManager |
| `plugin_skipped_total` | counter | `plugin_name`, `asset_class` | In asset-class guard per skip |
| `bars_processed_labeled_total` | counter | `symbol`, `tf` | Per bar processed in indicator_service and market_analysis_service |

**`bars_processed_labeled_total` is a new metric alongside the existing unlabeled `indicator_bars_processed_total`.**
Do NOT relabel the existing counter — that would invalidate historical Prometheus data. Add a new labeled counter.

### Structured log on off-hours equity bar

If a bar arrives for an equity instrument outside `trading_session.is_open()`:

```python
log.warning(
    "equity_bar_outside_session",
    symbol=symbol, tf=tf, bar_ts=bar_ts,
    session_id=instrument.session_id,
)
```

This should never fire in production (IBKR respects `useRTH=True` for historical, doesn't stream off-hours for equities in live mode). If it fires, it surfaces a provider bug.

---

## Section 8: Validation Script

`production/scripts/validate_equity_backfill.py`

```
Usage: python validate_equity_backfill.py --symbol SPY [--symbol QQQ ...]

Runs the off-hours validation SQL for each symbol.
Exits non-zero if any off-hours rows found.
```

Off-hours SQL (NYSE session — 09:30–16:00 ET):

```sql
SELECT COUNT(*) FROM intelligence_features
WHERE symbol = $1
  AND feature_tf = '1m'
  AND (
    EXTRACT(HOUR FROM feature_ts AT TIME ZONE 'America/New_York') < 9
    OR EXTRACT(HOUR FROM feature_ts AT TIME ZONE 'America/New_York') >= 16
    OR (
      EXTRACT(HOUR FROM feature_ts AT TIME ZONE 'America/New_York') = 9
      AND EXTRACT(MINUTE FROM feature_ts AT TIME ZONE 'America/New_York') < 30
    )
  );
```

Count must be zero. Any non-zero count = `useRTH` not applied, timestamp alignment bug, or wrong `session_id`.

---

## Section 9: Instrument Universe

### Futures (22, unchanged behavior — session_id added)

| Sector | Symbols | session_id |
|---|---|---|
| Equity index | ES, NQ, RTY, YM | futures_24_5 |
| Energy | CL | futures_24_5 |
| Metals | GC, SI, HG | futures_24_5 |
| Volatility | VX | futures_24_5 |
| Interest rates | ZN, ZF, ZB, ZT | futures_24_5 |
| Agriculture | ZS, ZC, ZW | futures_24_5 |
| FX spot | EURUSD, GBPUSD, USDJPY, USDCHF | fx_24_5 |
| Crypto | BTCUSD, ETHUSD | crypto_24_7 |

PLJ6 and SOLUSD removed from defaults.

### ETFs — Phase A pilot (5)

SPY (broad market), XLF (financials), TLT (rates/credit), GLD (macro/commodity), SMH (semiconductors/thematic). Covers 5 distinct correlation regimes.

### ETFs — Phase B remaining (33)

| Category | Symbols |
|---|---|
| Broad market | QQQ, IWM, DIA |
| Sectors | XLK, XLE, XLC, XLY, XLV, XLI, XLU, XLRE, XLP, XLB |
| Industry/thematic | IBB, GDX, GDXJ, XOP, ITB |
| Credit/rates | HYG, LQD, IEF, SHY, EMB |
| Factor | MTUM, QUAL, VLUE, USMV |
| International | EFA, EEM, EWZ, FXI |
| Macro/commodity | SLV, USO |

All ETFs: `asset_class=AssetClass.EQUITY`, `session_id="nyse"`, `exchange="SMART"`, `expiry=""`, `point_value=1.0`, `tick_size=0.01`.

### Cross-asset feature store integrity

All instruments share the IBKR connection and clock. A 1m bar at 14:30:00 UTC for ES and SPY carries identical `feature_ts`. A JOIN on `feature_ts` naturally returns no SPY row outside NYSE hours — the model interprets absence as "equities closed." No NULL rows, no synthetic bars.

---

## Section 10: Files Changed

| File | Change |
|---|---|
| `src/core/models.py` | Add `TradingSession`, `EXCHANGE_SESSIONS`, `CONTINUOUS_SESSIONS`, `SESSION_REGISTRY`, `MARKET_OVERLAPS`; add `session_id` + `trading_session` to `Instrument` |
| `src/providers/base.py` | Add `SubscriptionManager`, `SubscriptionLimitError` |
| `src/providers/ibkr.py` | Equity branch in `qualify_instrument()`, `useRTH=True` in `fetch_historical_bars()`, use `base.SubscriptionManager` |
| `src/config/settings.py` | Add `ibkr_max_subscriptions`; add `session_id` to existing instruments; remove PLJ6/SOLUSD; add ETF instruments |
| `src/intelligence/plugins.py` | Add `valid_asset_classes: ClassVar[frozenset[AssetClass]]` to both protocols |
| `src/intelligence/context/session_context.py` | Full redesign: DST fix, data-driven exchange flags, break flags, overlap flags, sub-session outputs (27 total) |
| `services/indicator_service.py` | `_instrument_map`, asset-class guard, `frames["__instrument__"]` injection, `plugin_skipped_total`, `bars_processed_labeled_total` |
| `services/market_analysis_service.py` | Same guard pattern as indicator_service |
| `production/scripts/validate_equity_backfill.py` | New validation script |
| `tests/unit/core/test_trading_session.py` | New |
| `tests/unit/intelligence/test_session_context_redesign.py` | New (DST + global sessions + sub-session) |
| `tests/unit/providers/test_base.py` | SubscriptionManager tests |
| `tests/unit/providers/test_ibkr_equity.py` | useRTH + STK qualification tests |
| `tests/unit/config/test_settings_equity.py` | ETF count, session_id, ibkr_max_subscriptions |
| `src/providers/CLAUDE.md` | Update active contracts 22→27 (Phase A), then 22→60 (Phase B); remove PLJ6/SOLUSD/PL |

---

## Section 11: Testing Strategy

All implementation follows TDD. Test categories:

- `test_trading_session.py` — `is_open()` across DST transitions, midnight wrap, weekends, all-day sessions; `in_trading_break()` for sessions with/without breaks; `elapsed_fraction()` returning None for all-day, 0.0→1.0 for NYSE, break exclusion from denominator
- `test_session_context_redesign.py` — 27 outputs present, DST transition 2026-03-08 (when US DST starts), global exchange flags, break flags, overlap flags, sub-session outputs with and without `__instrument__` in frames
- `test_base.py` — SubscriptionManager subscribe/unsubscribe, SubscriptionLimitError on overflow, count tracking
- `test_ibkr_equity.py` — mocked ib_insync: `secType='STK'` in qualify, `useRTH=True` in historical fetch
- `test_settings_equity.py` — pilot ETF count=5 in Phase A, total=38 in Phase B; session_id="nyse" on ETFs; ibkr_max_subscriptions default=80
- `test_plugin_asset_class_guard.py` — plugin with restricted `valid_asset_classes` skipped, feature absent from output, counter incremented; unrestricted plugin passes through; `__instrument__` in frames

Integration tests (require live IBKR, excluded from CI):
- Off-hours bar validation: backfill SPY with `useRTH=True`, run validation script, expect exit code 0

---

## What Does Not Change

- `intelligence_features` schema — no migration
- `signal_ledger` schema — no migration
- SSE API — ETF symbols work identically
- Dashboard — ETF symbols appear via `get_active_contracts()`
- All existing plugin logic — no behavioral changes
- Data flow: `indicators:SYMBOL:TF → intelligence:SYMBOL:TF → intelligence_features`
