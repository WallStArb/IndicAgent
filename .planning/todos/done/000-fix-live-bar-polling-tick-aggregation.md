# Fix Live Bar Polling: Tick Aggregation to Replace reqHistoricalDataAsync

**Priority: #1 — System is running on stale bar data 24/7**

## Problem

`reqHistoricalDataAsync` on the IBKR paper account always returns the previous session's close bars regardless of `endDateTime`. The pipeline has never had live 1m bars. `bars_processed` freezes at 183 (3 bars × 61 symbols) on every daemon start.

Exhaustively tested on 2026-03-21 — all fail:
- Original `endDateTime=now.strftime(...)` → yesterday's bars
- `endDateTime=""` → yesterday's bars
- `" UTC"` suffix → yesterday's bars
- EDT→UTC conversion → yesterday's bars

System timezone is **EDT (America/New_York)** — confirmed. The timezone was never the bug.

Ticks ARE live: `development.market.ticks` has real-time prices (BTC $70,356 live while historical API returns $70,153 from yesterday).

## Fix: Aggregate ticks into 1m bars in-process

### Where to change
- `services/tws_daemon.py` — replace `poll_1m_bars` / `_fetch_bars_for_symbol` with tick aggregator
- `src/providers/ibkr.py` — keep `fetch_historical_bars` for backfill only (untouched)

### Architecture

**Tick aggregator state** (per symbol):
```python
_bar_state: dict[str, dict] = defaultdict(lambda: {
    "open": None, "high": None, "low": None, "close": None,
    "volume": 0.0, "bar_minute": None  # datetime floored to minute
})
```

**On each tick** (already emitted by `_tick_loop` to `development.market.ticks` and processed in-process):
1. Floor `tick.timestamp` to the minute: `bar_minute = ts.replace(second=0, microsecond=0)`
2. If `bar_minute != _bar_state[symbol]["bar_minute"]` AND state has data → emit completed bar
3. Update state: open (if first tick of minute), high, low, close, volume += size

**Emit completed bar**: publish to `development.market.bars` with same schema as current:
```json
{
  "timestamp": "2026-03-21T13:07:00-04:00",
  "symbol": "ESM6", "timeframe": "1m",
  "open": "...", "high": "...", "low": "...", "close": "...",
  "volume": "...", "source": "authoritative", "bar_close_ts": "..."
}
```

### Tick data source
- Ticks flow through `_tick_loop()` → `_process_tick()` in tws_daemon.py
- Also published to `development.market.ticks` Redpanda topic
- Fields in tick handler: `symbol`, `last_price`, `last_size`, `timestamp`

### Dedup
Keep `seen_bar_timestamps` dedup for bars emitted from aggregator (guards against double-emit on reconnect).

### Remove
- `poll_1m_bars()` and `_fetch_bars_for_symbol()` calls — these only produce stale yesterday bars
- The `self.last_bar_poll_minute` polling trigger in main loop

### Keep
- `fetch_historical_bars` in `ibkr.py` — used by `historical_backfill.py`, `pipeline_reset.py`, `gap_fill_service.py`
- All tick collection infrastructure (unchanged)

### Crypto notes
- BTCUSD/ETHUSD: `whatToShow="AGGTRADES"` means tick size = trade size (valid volume)
- FX: `whatToShow="MIDPOINT"` means tick size is often 0 — volume will be 0 for FX bars (acceptable)
- Futures/ETFs: `whatToShow="TRADES"` with RTVolume — size is trade size

## Testing
- Unit test: inject 3 ticks in minute 1, 2 ticks in minute 2 → verify minute 1 bar emitted with correct OHLCV on first minute-2 tick
- Integration: restart tws daemon, verify `development.market.bars` starts getting today's timestamps within 2 minutes
- Verify BTCUSD/ETHUSD getting bars (crypto trades 24/7, should see bars immediately)
