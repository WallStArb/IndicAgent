# Market Entry Dual-Track Design
**Date:** 2026-03-14
**Status:** Approved for implementation

---

## Problem

455k historical pending signals in `signal_ledger` have no outcomes. They were created by the backfill replay pipeline but lifecycle service never evaluated them — it's a live consumer, historical bars already passed. These are 455k wasted labeled training samples.

Additionally, the current lifecycle only tracks one entry style: zone-based (limit order at zone). There's a second equally valid question: *what would have happened if we entered immediately at market when the signal fired?*

---

## Solution: Dual-Track Lifecycle Evaluation

Two parallel outcome tracks for every signal — both stored permanently in `signal_ledger`:

### Track A: Zone Entry (existing)
- Wait for price to re-enter the entry zone
- `never_activated` = zone never reached → **you wouldn't have been in this trade**
- Fields: `activation_price`, `zone_entry_pct`, `bars_to_activation`, `mae`, `mfe`, `bars_in_trade`, `outcome`, `pnl_r`
- Answers: *what happens with disciplined limit-order zone entry?*

### Track B: Market Entry (new)
- Immediate fill at first tradeable price after signal fires
- Always fills — `never_activated` never applies to this track
- **Live signals**: fill at `ask_at_signal` (long) / `bid_at_signal` (short) — tick-level, already captured
- **Historical replay**: fill at bar N+1 `open` — best available proxy
- Risk computed from market fill: `abs(market_entry_price - stop_loss)` (different from zone risk because fill is at a different level)
- Same absolute stop and targets as zone track
- Fields: `market_entry_price`, `market_entry_pnl_r`, `market_entry_outcome`
- Answers: *what happens if you take every signal immediately at market?*

### Value of comparison

| Scenario | Zone Outcome | Market Outcome | Insight |
|----------|-------------|----------------|---------|
| Signal fired, zone never hit | `never_activated` | `target_full` | Signal was directionally right; you missed it waiting for a pullback |
| Signal fired, zone hit, both win | win | win | Confirms zone entry was worth waiting for |
| Signal fired, zone hit, zone loses worse | loss | better R | Market entry had tighter stop → better R |

---

## New Schema Fields

```sql
-- Migration 031
ALTER TABLE signal_ledger
  ADD COLUMN market_entry_price        DOUBLE PRECISION,  -- tick (live) or bar N+1 open (replay)
  ADD COLUMN market_entry_pnl_r        DOUBLE PRECISION,  -- P&L in R-multiples from market fill
  ADD COLUMN market_entry_outcome      TEXT,              -- same outcome taxonomy as 'outcome'
  ADD COLUMN market_entry_mae          DOUBLE PRECISION,  -- max adverse excursion from market fill
  ADD COLUMN market_entry_mfe          DOUBLE PRECISION,  -- max favorable excursion from market fill
  ADD COLUMN market_entry_bars_in_trade INTEGER,          -- bars from market fill to exit
  ADD COLUMN market_entry_exit_price   DOUBLE PRECISION,  -- exit price for market track
  ADD COLUMN market_entry_gap_bars     INTEGER;           -- bars between signal fire and bar N+1 fill
```

---

## Lifecycle Replay Script

New standalone script: `production/scripts/lifecycle_replay.py`

**Design:**
- No IBKR, no Redpanda — purely DB-driven (reads `signal_ledger` + `market_data_ohlcv`, writes `signal_ledger`)
- Parallelizable by symbol (`--symbols` flag)
- For each pending signal:
  1. Fetch bars from `market_data_ohlcv` WHERE `symbol = sig.symbol AND timeframe = sig.timeframe AND timestamp > sig.timestamp` ORDER BY timestamp ASC
  2. Skip evaluation if fewer than 2 bars (can't even compute bar N+1)
  3. Bar N+1 open → `market_entry_price`
  4. Evaluate bars N+1 onwards: run BOTH zone evaluation AND market-entry simulation per bar
  5. Write all outcome fields on resolution

**Zone evaluation (Track A):**
- Same logic as live `evaluate_signal()` — zone activation check, stop/target/TTL
- `bars_elapsed` computed from timestamps

**Market entry evaluation (Track B):**
- New `evaluate_market_entry()` in `lifecycle_tracker.py`
- No activation check — always "active" from bar N+1
- Uses `market_entry_price` as fill, same `stop_loss` and `targets`
- Risk = `abs(market_entry_price - stop_loss)`

**Performance:** Process in batches per symbol/timeframe. `market_data_ohlcv` is indexed on `(symbol, timeframe, timestamp DESC)` so bar fetch is fast. Expect ~10-30 minutes for 455k signals across 60 symbols.

---

## Live Service Changes (`signal_lifecycle_service.py`)

Add in-memory tracking:
```python
_market_entry_price: dict[str, float]   # signal_id → fill price
_market_mae: dict[str, float]
_market_mfe: dict[str, float]
```

On the **first bar** after a signal fires (first call where `sid not in _market_entry_price`):
- Long: `fill = ask_at_signal if ask_at_signal else bar["open"]`
- Short: `fill = bid_at_signal if bid_at_signal else bar["open"]`
- Store in `_market_entry_price[sid]`

On every bar for a signal with market entry set:
- Run `evaluate_market_entry(...)` → update `_market_mae[sid]`, `_market_mfe[sid]`

On exit (zone track resolves):
- Write `market_entry_price`, `market_entry_pnl_r`, `market_entry_outcome` alongside existing exit fields
- Clean up all three in-memory dicts

---

## Index Cleanup (from original audit)

After lifecycle replay: all 455k historical pending signals will have `exit_at IS NOT NULL` → fall off `idx_ledger_open_signals` naturally. No bulk-expire needed.

Also drop `idx_ledger_sym_ts` — redundant, covered by `idx_ledger_symbol_tf_ts` and `idx_ledger_open_signals`.

Run `ANALYZE signal_ledger` after replay to refresh planner stats.

---

## Critical Files

| File | Change |
|---|---|
| `production/migrations/031_market_entry_dual_track.sql` | New columns |
| `src/intelligence/trading/lifecycle_tracker.py` | Add `evaluate_market_entry()` + `MarketTransition` dataclass |
| `src/intelligence/trading/signal_ledger.py` | Add fields to `LedgerEntry`, `_UPDATE_STATUS_SQL`, `update_signal_status()` |
| `services/signal_lifecycle_service.py` | In-memory market track, write on exit |
| `production/scripts/lifecycle_replay.py` | New script — dual-track offline replay |

---

## Verification

```sql
-- After replay: pending should be ~0
SELECT status, COUNT(*) FROM signal_ledger GROUP BY status ORDER BY count DESC;

-- Market entry outcomes should be populated for resolved signals
SELECT
  COUNT(*) FILTER (WHERE market_entry_price IS NOT NULL) AS market_entry_filled,
  COUNT(*) FILTER (WHERE market_entry_outcome IS NOT NULL) AS market_entry_resolved,
  COUNT(*) FILTER (WHERE outcome IS NOT NULL) AS zone_resolved
FROM signal_ledger
WHERE timestamp < NOW() - INTERVAL '1 day';

-- Compare tracks
SELECT
  outcome AS zone_outcome,
  market_entry_outcome,
  COUNT(*),
  ROUND(AVG(pnl_r)::numeric, 3) AS avg_zone_pnl_r,
  ROUND(AVG(market_entry_pnl_r)::numeric, 3) AS avg_market_pnl_r
FROM signal_ledger
WHERE outcome IS NOT NULL AND market_entry_outcome IS NOT NULL
GROUP BY outcome, market_entry_outcome
ORDER BY count DESC;
```
