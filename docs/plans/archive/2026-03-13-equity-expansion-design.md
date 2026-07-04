# Equity Expansion Design

**Date:** 2026-03-13
**Status:** Approved
**Scope:** Add 38 ETFs to the IndicAgent intelligence pipeline alongside existing futures/FX/crypto instruments.

---

## Primary Goal

The primary value of this phase is not standalone ETF signals. It is **a complete, clean cross-asset feature store**. Every ETF bar that flows through the pipeline deposits a full feature vector into `intelligence_features`, timestamped at the bar's open time. At training time, a JOIN on `(feature_ts, feature_tf)` across all symbols reconstructs the full market state at any moment — what ES was doing, what JNK was doing, what SMH was doing — all in one query. This is the labeled training dataset for the cross-asset confluence model that comes in a later milestone.

Standalone ETF signals are a side effect, not the goal.

---

## Architecture: Three Parallel Tracks

### Track A — Provider Abstraction

**No behavior change. Interface enforcement only.**

`src/providers/base.py` already defines a `DataProvider` protocol with `resolve_instrument()`, `stream_ticks()`, `fetch_historical_bars()`. We do not rename or redefine these methods.

The change: `IBKRProvider` in `src/providers/ibkr.py` is extended to handle `AssetClass.EQUITY`:

- `resolve_instrument()` — adds `secType='STK'`, `exchange='SMART'` branch for equity instruments
- `fetch_historical_bars()` — adds `useRTH=True` for equities (regular trading hours only, no overnight bars)
- `stream_ticks()` — no change; equity symbols subscribe identically to futures

`SubscriptionManager` is added inside `ibkr.py` only — not on the protocol. It is IBKR-specific; other providers (Alpaca, Polygon) have no subscription limits. It tracks active subscriptions against `IBKR_MAX_SUBSCRIPTIONS` (env var, default 80) and raises `SubscriptionLimitError` rather than silently failing.

Services depend on the `DataProvider` protocol. Scripts (`historical_backfill.py`) may reference `IBKRProvider` directly — this is acceptable for scripts.

### Track B — Plugin Asset-Class Compatibility Layer

**`compute_full()` signature does not change.**

Adding `instrument: Instrument` as a third argument to 101 plugins is a brittle, noisy change. Instead:

1. **`valid_asset_classes` ClassVar** added to both `IndicatorPlugin` and `PatternPlugin` protocols in `src/intelligence/plugins.py`:

```python
valid_asset_classes: ClassVar[frozenset[AssetClass]] = frozenset(AssetClass)  # default: all
```

Fully backward compatible — existing plugins get the default (all asset classes) without any changes.

2. **Guard in compute loop** (both `indicator_service` and `market_analysis_service`):

```python
instrument = self._instrument_map[symbol]
for plugin in self._plugin_cache[tier]:
    if instrument.asset_class not in plugin.valid_asset_classes:
        continue  # skip — no feature written, no NULL
    frames["__instrument__"] = instrument  # available if plugin needs it
    plugin._state = self._plugin_states[(plugin.name, symbol, timeframe)]
    result = plugin.compute_full(frames)
    self._plugin_states[(plugin.name, symbol, timeframe)] = plugin._state
```

State swap pattern is unchanged from current services — `frames["__instrument__"]` is injected before the call and available via `frames.get("__instrument__")` inside `compute_full`. Future plugins that need asset-class-specific behavior read it from `frames`; all current plugins ignore it.

Skip = absent from output dict. Not `None`, not `0.0`, not written to `intelligence_features`. A missing field is interpretable. A garbage field is not.

3. **Plugin audit result:** Zero plugins currently need non-default `valid_asset_classes` declarations. ICTKillzones, AMDCycle, SessionContext are UTC-time-based — they produce valid output for ETFs during market hours. VWAP already handles session reset by date boundary. The layer exists for future plugins that are genuinely asset-class-specific (e.g., futures-only roll momentum, equity-only earnings proximity), not to filter current ones.

4. **DST bug fix** (in-scope, same area): `src/intelligence/context/session_context.py` uses a hardcoded `_ET_OFFSET = timedelta(hours=-5)`. This is wrong — ET is UTC-4 during daylight saving (March–November), causing systematic mis-classification for 7 months of every year. Fix: replace `_et_from_utc()` to use `ZoneInfo("America/New_York")` for the UTC→local conversion. The `_SESSIONS` and `_KILLZONES` window constants are already in local wall-clock time — they do not need to change.

### Track C — ETF Expansion

**22 futures (unchanged) + 38 ETFs added.**

ETF instruments in `settings.py` defaults use `asset_class=AssetClass.EQUITY`, `session_id="nyse"`, `expiry=""`, `base=symbol`, `point_value=1.0`, `tick_size=0.01`, `exchange="SMART"`.

Data flow is unchanged — ETF bars enter `indicators:SYMBOL:TF → intelligence:SYMBOL:TF → intelligence_features` exactly like futures.

---

## Section 1: Instrument Model

### TradingSession

Added to `src/core/models.py`:

```python
from dataclasses import dataclass, field
from datetime import time, datetime
from zoneinfo import ZoneInfo

@dataclass(frozen=True)
class TradingSession:
    open_time: time
    close_time: time
    timezone: str
    trading_days: frozenset[int] = field(default_factory=lambda: frozenset({0,1,2,3,4}))

    def is_open(self, utc_ts: datetime) -> bool:
        local = utc_ts.astimezone(ZoneInfo(self.timezone))
        if local.weekday() not in self.trading_days:
            return False
        t = local.time().replace(second=0, microsecond=0)
        if self.open_time == self.close_time:      # all-day session on this trading day
            return True
        elif self.open_time < self.close_time:     # normal window: 09:30–16:00
            return self.open_time <= t < self.close_time
        else:                                      # wraps midnight: 18:00–17:00 futures
            return t >= self.open_time or t < self.close_time

# Singletons — reference by session_id string
NYSE_SESSION  = TradingSession(time(9, 30), time(16, 0), "America/New_York", frozenset({0,1,2,3,4}))
FUTURES_24_5  = TradingSession(time(18, 0), time(17, 0), "America/Chicago",  frozenset({0,1,2,3,4,6}))  # Mon–Fri + Sun; Sat is dark
FX_24_5       = TradingSession(time(0, 0),  time(0, 0),  "UTC",              frozenset({0,1,2,3,4,6}))  # all-day Mon–Fri + Sun
CRYPTO_24_7   = TradingSession(time(0, 0),  time(0, 0),  "UTC",              frozenset(range(7)))        # all-day every day

SESSION_REGISTRY: dict[str, TradingSession] = {
    "nyse":         NYSE_SESSION,
    "futures_24_5": FUTURES_24_5,
    "fx_24_5":      FX_24_5,
    "crypto_24_7":  CRYPTO_24_7,
}
```

### Instrument changes

One new field, one validator:

```python
class Instrument(BaseModel):
    ...
    session_id: str = "futures_24_5"   # JSON-safe; resolved via SESSION_REGISTRY

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

Validated at construction time — invalid instruments never enter the pipeline. Existing instruments omit `session_id` and get `"futures_24_5"` by default — fully backward compatible.

FX instruments get `session_id="fx_24_5"`. Crypto gets `session_id="crypto_24_7"`. ETFs get `session_id="nyse"`.

---

## Section 2: Instrument Universe

### Futures (22, PLJ6 and SOLUSD removed from settings.py defaults)

| Sector | Symbols |
|---|---|
| Equity index | ES, NQ, RTY, YM |
| Energy | CL |
| Metals | GC, SI, HG |
| Volatility | VX |
| Interest rates | ZN, ZF, ZB, ZT |
| Agriculture | ZS, ZC, ZW |
| FX spot | EURUSD, GBPUSD, USDJPY, USDCHF |
| Crypto | BTCUSD, ETHUSD |

### ETFs (38)

| Category | Symbols |
|---|---|
| Broad market (4) | SPY, QQQ, IWM, DIA |
| Sectors (11) | XLF, XLK, XLE, XLC, XLY, XLV, XLI, XLU, XLRE, XLP, XLB |
| Industry/thematic (6) | SMH, IBB, GDX, GDXJ, XOP, ITB |
| Credit/rates (6) | HYG, LQD, TLT, IEF, SHY, EMB |
| Factor (4) | MTUM, QUAL, VLUE, USMV |
| International (4) | EFA, EEM, EWZ, FXI |
| Macro/commodity (3) | GLD, SLV, USO |

### Roll management (explicit out-of-scope)

Futures contract rolls (e.g., ESH6 → ESM6) remain manual config changes. This is a known decision, not an oversight. ETFs have no expiry — `expiry=""` is permanent. Adding automated roll detection is a separate future milestone.

---

## Section 3: Cross-Asset Feature Store Integrity

### Timestamp alignment guarantee

All instruments go through the same IBKR connection. IBKR uses bar-open time as `feature_ts`, sourced from a single clock. A 1m bar at 14:30:00 UTC for ES and for SPY will carry identical `feature_ts` values — same provider, same clock, same minute boundary.

| Window | ES bars | SPY bars | JOIN result |
|---|---|---|---|
| 09:30–16:00 ET Mon–Fri | ✓ | ✓ | Full cross-asset market state |
| 16:00–17:00 ET Mon–Fri | ✓ | absent | Futures-only — equities closed, correct |
| 17:00–09:30 ET / weekends | ✓ | absent | Overnight futures — correct |

"Absent" = no row in `intelligence_features`. Not a NULL column. The pipeline writes nothing for an ETF when the market is closed. A JOIN on `feature_ts` naturally returns no SPY row for 16:01 ET — the model interprets this as "equities closed."

### Gap handling rule (non-negotiable)

Equity market close → no bar generated → no row written. Plugin state is preserved in memory across the gap. The first bar after open is computed against the preserved prior state. This is the natural behavior of the pipeline — no synthetic gap bars, no NULL rows.

### Validation gate

After any ETF backfill, run:

```sql
SELECT COUNT(*) FROM intelligence_features
WHERE symbol = 'SPY'
  AND feature_tf = '1m'
  AND (
    EXTRACT(HOUR FROM feature_ts AT TIME ZONE 'America/New_York') < 9
    OR EXTRACT(HOUR FROM feature_ts AT TIME ZONE 'America/New_York') >= 16
    OR (EXTRACT(HOUR FROM feature_ts AT TIME ZONE 'America/New_York') = 9
        AND EXTRACT(MINUTE FROM feature_ts AT TIME ZONE 'America/New_York') < 30)
  );
```

Count must be zero. This gates on the full NYSE window (09:30–16:00 ET exactly — bars before 09:30 and from 16:00 onward are invalid). Any rows = timestamp alignment bug or `useRTH` not being applied, investigate before proceeding.

### Explicitly out of scope

- Real-time cross-asset aggregator publishing regime state to futures pipelines
- Plugin changes to consume cross-asset features in signal generation
- The confluence model itself

The data capture is this phase. The model comes later — but only works if the data is clean from bar one.

---

## Section 4: Observability

60 symbols at 4 timeframes = 240 potential stream paths. "Instrument everything" requires knowing when any path goes silent.

### New metrics

| Metric | Labels | Alert threshold |
|---|---|---|
| `bars_processed_total` | `symbol`, `tf` | absent for >5 min during market hours |
| `plugin_skipped_total` | `plugin_name`, `asset_class` | informational only |
| `ibkr_active_subscriptions` | — | >80% of `IBKR_MAX_SUBSCRIPTIONS` |

`bars_processed_total` already exists in the indicator service. Verify during implementation that it carries `symbol` and `tf` labels — if it is currently an aggregate-only counter, adding labels is a label-breaking Prometheus change that invalidates historical data. Address explicitly: either accept the break or add a new labeled metric alongside the existing one.

### Subscription headroom

`IBKR_MAX_SUBSCRIPTIONS` env var (default 80). 60 instruments × live tick feed = 60 subscriptions (bars are derived, not separate subscriptions). `SubscriptionManager` raises `SubscriptionLimitError` before attempting the 81st subscription, logs structured error with `symbol` and current count.

### Structured log on off-hours bar

If a bar arrives for an equity instrument outside `trading_session.is_open()`, log a structured warning:

```python
log.warning("equity_bar_outside_session",
            symbol=symbol, tf=tf, bar_ts=bar_ts,
            session_id=instrument.session_id)
```

This should never fire in production. If it does, it surfaces a data provider bug or misconfigured session.

---

## Testing Strategy

All implementation follows TDD. Key test categories:

- `test_trading_session.py` — `is_open()` correctness across DST transitions, midnight wrap, weekends
- `test_session_registry.py` — invalid `session_id` raises at Instrument construction
- `test_ibkr_equity_qualification.py` — mocked IBKR, verifies `secType='STK'`
- `test_plugin_asset_class_guard.py` — plugin with restricted `valid_asset_classes` is skipped, no feature written
- `test_equity_gap_no_row.py` — backfill with `useRTH=True` produces no off-hours rows in `intelligence_features` (integration test — requires TimescaleDB, excluded from CI); the live pipeline relies on IBKR not streaming equity bars outside market hours, so no active gate is needed in service code
- `test_timestamp_alignment.py` — ES and SPY 1m bars at same minute carry identical `feature_ts`

Integration tests require live IBKR paper account connection — excluded from CI, documented in `tests/integration/README.md`.

---

## What Does Not Change

- `intelligence_features` schema — no migration needed
- `signal_ledger` schema — no migration needed
- SSE API — no changes; ETF symbols work identically to futures
- Dashboard — ETF symbols appear automatically via `get_active_contracts()`
- All existing plugin logic — no behavioral changes
- Data flow: `indicators:SYMBOL:TF → intelligence:SYMBOL:TF → intelligence_features`
