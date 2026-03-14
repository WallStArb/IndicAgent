# Market Entry Dual-Track + Lifecycle Replay
**Date:** 2026-03-14
**Status:** Approved for implementation
**Scope:** signal_ledger schema, lifecycle_tracker, signal_ledger.py, signal_generator_service, signal_lifecycle_service, lifecycle_replay script

---

## Problem

Two related problems that share a solution:

1. **455k historical pending signals with no outcomes.** The lifecycle service is a live consumer — historical bars already passed before it existed. These are 455k wasted labeled training samples sitting in `signal_ledger` with `status = 'pending'` forever, degrading lifecycle query performance with every new signal inserted.

2. **Only one entry style tracked.** The current lifecycle tracks zone-based entry only (limit order at zone). A second entry style — immediate market order at signal fire — is never evaluated. This loses a complete parallel labeled dataset and makes it impossible to compare entry discipline vs. aggressive entry systematically.

Renaissance principle: every signal outcome is a labeled training sample. Once gone it cannot be recovered. Storage is the cheapest thing we own.

---

## Solution

### Dual-Track Lifecycle Evaluation

Two parallel outcome tracks for every signal, stored permanently in `signal_ledger`:

**Track A — Zone Entry (existing, formalized)**
Wait for price to re-enter the entry zone. `never_activated` = zone never reached = you would not have been in this trade. Answers: *what happens with disciplined limit-order zone entry?*

**Track B — Market Entry (new)**
Immediate fill at first tradeable price after signal fires. Always fills — `never_activated` never applies to this track.
- **Live signals:** `ask_at_signal` (long) / `bid_at_signal` (short) — tick-level, captured at signal fire
- **Historical replay:** bar N+1 `open` — best available proxy; labeled as such via `replay_gap_bars`
- Risk = `abs(market_entry_price - stop_loss)` — different from zone risk because fill differs
- Same absolute `stop_loss` and `targets` as zone track

Answers: *what happens if you take every signal immediately at market?*

**Comparison value:**

| Zone outcome | Market outcome | Meaning |
|---|---|---|
| `never_activated` | `target_full` | Signal was directionally right; you missed it waiting for pullback |
| `target_full` | `target_full` | Zone entry confirmed — worth waiting |
| `never_activated` | `stopped_in_trade` | Market entry lost; zone patience was correct |
| `stopped_in_trade` | `target_full` | Zone entry was worse fill; market was better |

---

## Three-Phase Data Model

Each phase has distinct ownership, written independently, never overwritten.

### Phase 1 — Signal (signal_generator_service, at INSERT)
What the system saw and decided at bar N close. Written once, never changed.

**Existing fields (unchanged):**
`entry_price`, `stop_loss`, `targets`, `confidence`, `cis_score`, `ask_at_signal`, `bid_at_signal`, `market_price_at_signal`, `entry_zone_low`, `entry_zone_high`

**New field:**
`market_entry_price DOUBLE PRECISION` — `ask_at_signal` (long) / `bid_at_signal` (short). NULL if unavailable (warmup, no tick received). Never fabricated. Lifecycle service skips market track when NULL.

Note: `spread_at_signal` is derivable as `ask_at_signal - bid_at_signal` — not stored as a separate column. Compute at query time.

### Phase 2 — Entry (signal_lifecycle_service, zone track only)
How/if the zone trade got on. Market track has no entry phase — fill is already set at INSERT.

**Existing fields (unchanged):**
`activated_at`, `activation_price`, `zone_entry_pct`, `bars_to_activation`

### Phase 3 — Resolution (signal_lifecycle_service, written independently per track)
How each track played out. **The two tracks resolve independently and are written independently** — market track may exit at bar 3, zone track at bar 10. Neither write corrupts the other.

**Zone track resolution (existing fields, unchanged):**
`status`, `exit_at`, `exit_price`, `exit_reason`, `pnl_ticks`, `pnl_r`, `pnl_dollars`, `signal_quality`, `mae`, `mfe`, `bars_in_trade`, `outcome`

**Market track resolution (new fields):**
```
market_entry_exit_price     DOUBLE PRECISION  -- price at market track exit
market_entry_pnl_r          DOUBLE PRECISION  -- P&L in R-multiples from market fill
market_entry_mae            DOUBLE PRECISION  -- max adverse excursion, market track
market_entry_mfe            DOUBLE PRECISION  -- max favorable excursion, market track
market_entry_bars_in_trade  INTEGER           -- bars from fill to exit
market_entry_outcome        TEXT              -- same taxonomy as 'outcome'
```

**Full schema addition (Migration 031):**
```sql
ALTER TABLE signal_ledger
  ADD COLUMN IF NOT EXISTS market_entry_price          DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS market_entry_exit_price     DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS market_entry_pnl_r          DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS market_entry_mae            DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS market_entry_mfe            DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS market_entry_bars_in_trade  INTEGER,
  ADD COLUMN IF NOT EXISTS market_entry_outcome        TEXT;

-- Analytics index mirroring idx_ledger_outcome
CREATE INDEX idx_ledger_market_outcome
ON signal_ledger (market_entry_outcome, setup_plugin, timeframe)
WHERE market_entry_outcome IS NOT NULL;

-- Drop redundant index (covered by idx_ledger_symbol_tf_ts + idx_ledger_open_signals)
DROP INDEX IF EXISTS idx_ledger_sym_ts;
```

**7 new columns. 1 new index. 1 index dropped.**

---

## Component Changes

### `lifecycle_tracker.py` — add `evaluate_market_entry()`

Pure function, no DB access. New `MarketTransition` dataclass:

```python
@dataclass
class MarketTransition:
    signal_id: str
    exit_price: float | None = None
    pnl_r: float | None = None
    mae: float = 0.0
    mfe: float = 0.0
    outcome: str | None = None  # None = still running
```

`evaluate_market_entry(signal, *, market_entry_price, high, low, close, current_mae, current_mfe)`:
- Risk = `abs(market_entry_price - stop_loss)`
- No zone activation check — always "active" from first bar
- Same stop/target/TTL evaluation logic as `_check_active_exit()`
- Outcome taxonomy: `stopped_at_entry`, `stopped_in_trade`, `target_1`, `target_1_2`, `target_full`, `ttl_expired_ahead`, `ttl_expired_behind`
- `never_activated` NEVER appears — market track always fills
- Returns `MarketTransition` with `outcome=None` while still running; populated on exit

### `signal_ledger.py` — three focused DB operations

Replace monolithic `update_signal_status()` with three purpose-built functions:

```python
record_activation(db, signal_id, *, activated_at, activation_price, zone_entry_pct, bars_to_activation)
record_zone_resolution(db, signal_id, *, status, exit_at, exit_price, exit_reason, pnl_ticks, pnl_r, pnl_dollars, signal_quality, mae, mfe, bars_in_trade, outcome)
record_market_resolution(db, signal_id, *, market_entry_exit_price, market_entry_pnl_r, market_entry_mae, market_entry_mfe, market_entry_bars_in_trade, market_entry_outcome)
```

Each function writes ONLY its own columns via targeted SQL. No cross-contamination.
`update_signal_status()` kept as a compatibility shim calling the appropriate new functions, deprecated internally.

Add `market_entry_price` to `LedgerEntry` dataclass and `_INSERT_SQL`.

### `signal_generator_service.py` — set `market_entry_price` at INSERT

In `build_ledger_entries()`, alongside existing ask/bid capture:
```python
market_entry_price = ask if direction == 1 else bid  # NULL if ask/bid unavailable
```
Set on `LedgerEntry`. No fallback — NULL is honest.

### `signal_lifecycle_service.py` — parallel market track

**New in-memory state:**
```python
self._market_mae: dict[str, float] = {}   # parallel to _mae
self._market_mfe: dict[str, float] = {}   # parallel to _mfe
# No _market_activated_at — bars_in_trade = bars_elapsed - 1 at exit
```

**Per-bar evaluation loop changes:**
1. Read `market_entry_price` from signal dict (already in DB from Phase 1)
2. If `market_entry_price IS NOT NULL` and market track not yet resolved:
   - Call `evaluate_market_entry()` with `_market_mae[sid]`, `_market_mfe[sid]`
   - Update `_market_mae[sid]`, `_market_mfe[sid]` each bar
   - If `MarketTransition.outcome IS NOT NULL`: call `record_market_resolution()`, clean up `_market_mae/_market_mfe[sid]`
3. Zone track continues independently on same bar as always
4. When zone track resolves: call `record_activation()` (if applicable) + `record_zone_resolution()`, clean up all remaining state for sid

**Independent timeline handling:** Market track can resolve before zone track. Zone track resolution determines when signal leaves `get_active_signals()` (via `exit_at IS NOT NULL`). Market track writes and cleans up independently without affecting zone track state.

**Regime_suppressed signals:** Receive market track evaluation identically to pending/active signals. Their existing counterfactual `pnl_r` (virtual activation at bar close) and new `market_entry_pnl_r` (tick fill) are meaningfully different and both captured.

**Pre-existing limitation (document, do not fix in this plan):** `_mae`/`_mfe` and `_market_mae`/`_market_mfe` reset to 0.0 on service restart since MAE/MFE are not checkpointed mid-signal. Final excursions underestimate true extremes for signals spanning a service restart.

---

## Lifecycle Replay Script

**`production/scripts/lifecycle_replay.py`** — standalone, DB-only, no IBKR, no Redpanda.

### Algorithm

```
For each symbol + timeframe (up to 240 iterations, parallelized):

  1. VALIDATE mode (run first if --validate):
     - Sample 100 already-resolved signals with known outcomes
     - Run replay evaluation against their historical bars
     - Compare computed vs stored outcomes
     - Report match rate — block proceed if < 100% on unambiguous cases
     - Produce discrepancy report: signal_id, live_outcome, replay_outcome, diff

  2. Fetch pending signals:
     SELECT * FROM signal_ledger
     WHERE status = 'pending' AND symbol = $1 AND timeframe = $2
     ORDER BY timestamp ASC

  3. Stream bars chronologically (server-side cursor):
     DECLARE cursor FOR
     SELECT timestamp, open, high, low, close FROM market_data_ohlcv
     WHERE symbol = $1 AND timeframe = $2
       AND timestamp >= (SELECT MIN(timestamp) FROM pending_signals)
     ORDER BY timestamp ASC

  4. Walk bars, maintaining live_signals set:
     - When bar.timestamp > signal.timestamp: add to live_signals
       → market_entry_price = bar.open (bar N+1)
       → detect gap: if bar.timestamp - signal.timestamp > 1.5 × tf_seconds,
         set replay_gap_bars = round(gap / tf_seconds) - 1
     - For each live signal, compute bars_elapsed from signal.timestamp vs bar.timestamp
     - Run evaluate_signal() for zone track
     - Run evaluate_market_entry() for market track (if market_entry_price IS NOT NULL)
     - Update _zone_mae/_zone_mfe, _market_mae/_market_mfe per signal
     - When market track exits: write record_market_resolution() immediately
       (use bar.timestamp for all temporal fields — NOT datetime.now())
     - When zone track exits: write record_activation() + record_zone_resolution()
       (use bar.timestamp for all temporal fields — NOT datetime.now())
     - Remove fully resolved signals from live_signals

  5. End of bars: remaining live_signals → TTL expiry
     (bars_elapsed will be huge → TTL fires on next evaluate call if we add a sentinel bar,
      OR compute final state explicitly)

  6. Commit every --batch-size signals (default 500)

  7. Print per-symbol/TF summary statistics
```

**Critical correctness requirement:** ALL temporal fields (`activated_at`, `exit_at`) use `bar.timestamp`, never `datetime.now()`. The live service uses `datetime.now()` because it processes bars in real time. The replay must substitute bar timestamps throughout or `bars_in_trade` calculations will be corrupted for all 455k signals.

### Parallelism

Python `multiprocessing.Pool` with `--workers N` (default 4). Each worker processes one symbol at a time, owns its own DB connection. Workers assigned by symbol to avoid contention. Symbol-level granularity (not TF-level) to balance load across workers.

### No-data handling

If `market_data_ohlcv` has zero bars after `signal.timestamp` for that symbol/timeframe:
- Zone outcome: `never_activated`, `exit_at = signal.timestamp + TTL * tf_seconds`
- Market track: all fields NULL (no bars = no fill = no evaluation)
- Log as data gap, count in summary stats

### Output statistics (printed at completion per symbol/TF)

```
ES  1m  12,847 signals processed in 4.2s
  Zone:   never_activated 34% | stopped 28% | target_1+ 38%
  Market: stopped 31%         | target_1+ 69%
  Comparison: market won 41% | zone won 35% | tied 24%
  avg zone pnl_r: +0.18 | avg market pnl_r: +0.31
  gaps: 142 signals (1.1%) had missing bar N+1
```

### CLI

```bash
python production/scripts/lifecycle_replay.py \
  [--symbols ES,NQ]       # default: all active contracts
  [--timeframes 1m,5m]    # default: all timeframes
  [--validate]            # run validation against resolved signals first
  [--dry-run]             # compute outcomes, print stats, write nothing
  [--batch-size 500]      # commit frequency
  [--workers 4]           # parallel symbol processing
  [--resume]              # skip symbols already fully processed (idempotent by design)
```

---

## Testing Strategy

### `tests/unit/trading/test_lifecycle_tracker.py` — extend

**Mechanical correctness (new `evaluate_market_entry()`):**
- Long immediate stop → `stopped_at_entry`
- Long moves favorable then stopped → `stopped_in_trade`
- Long hits target_1, target_full
- TTL with positive MFE → `ttl_expired_ahead`; zero MFE → `ttl_expired_behind`
- Risk uses `market_entry_price - stop_loss` not `entry_price - stop_loss`
- MAE/MFE tracked correctly across bars
- `never_activated` never appears in market track outcomes — assert raises/returns None

**Mathematical invariants:**
- `MAE ≤ pnl_r ≤ MFE` always — final P&L bounded by excursion range
- MAE ≤ 0 for losing trades; MFE ≥ 0 for winning trades
- `pnl_r == (exit_price - market_entry_price) * direction / abs(market_entry_price - stop_loss)` exactly
- When stop hit: `exit_price == stop_loss` exactly
- When target hit: `exit_price == targets[i]` exactly

### `tests/unit/service_tests/test_signal_lifecycle_service.py` — extend

Uses `__new__` pattern (existing convention).

**Market track mechanics:**
- `market_entry_price` read from signal dict, market track initialized on first bar
- `market_entry_price = NULL` → market track silently skipped, no error, no crash
- Regime_suppressed signals get market track evaluation

**Independent timeline tests:**
- Market resolves bar 3, zone still pending bar 3 → `record_market_resolution()` called at bar 3, zone evaluation continues
- Zone resolves bar 8, market already resolved bar 3 → only `record_zone_resolution()` called at bar 8
- Both resolve same bar → both writes happen, order: market then zone
- In-memory `_market_mae/_market_mfe` cleaned up at market resolution
- All state cleaned up at zone resolution

**DB write isolation:**
- `record_market_resolution()` writes only market columns — assert zone columns not in SQL
- `record_zone_resolution()` writes only zone columns — assert market columns not in SQL
- `record_activation()` writes only activation columns

### `tests/unit/scripts/test_lifecycle_replay.py` — new

**Correctness:**
- Chronological ordering: signal with earlier timestamp activates before later timestamp signal
- Bar timestamps used for `activated_at`/`exit_at` — assert no `datetime.now()` calls
- Gap detection: 2-bar gap after signal fire → `replay_gap_bars = 2`
- No-data: zero bars available → zone `never_activated`, market all NULL

**Statistical invariants (run against synthetic bar sequences):**
- `never_activated` rate < 100% when bars overlap the zone — activation must be detectable
- `market_entry_bars_in_trade ≤ TTL` always — can't exceed TTL
- `market_entry_outcome` never `never_activated` — assert across 1000 synthetic signals
- `market_entry_pnl_r` not systematically higher than zone `pnl_r` on same signals — no look-ahead bias

**Track comparison invariants:**
- Zone `never_activated` + market `target_full` → valid, allowed
- Zone `target_full` + market `never_activated` → **impossible**, assert raises/flags bug
- When both tracks hit same target: `market_entry_exit_price == zone exit_price`
- When `market_entry_price == entry_price` (same fill): `market_entry_pnl_r == pnl_r` exactly

**Temporal correctness:**
- `activated_at` between `signal.timestamp` and `signal.timestamp + TTL`
- `exit_at >= activated_at` always
- `bars_in_trade == round((exit_at - activated_at) / tf_seconds)` ± 1

**Validate mode:**
- 100% match on unambiguous resolved signals → proceeds
- Mismatch → produces discrepancy report, does not commit
- Dry-run → computes full outcome set, writes nothing, asserts DB unchanged

**Idempotency with statistical verification:**
- Run twice on same pending signals → identical outcome distributions
- Hash outcome set before and after second run → identical

**Parallelism:**
- 4-worker run produces identical outcome distributions as single-worker run
- No cross-symbol state contamination between workers

---

## Verification (post-implementation)

```bash
# 1. Run validate mode first
.venv/bin/python production/scripts/lifecycle_replay.py --validate --dry-run

# 2. Dry-run full replay — review statistics before committing
.venv/bin/python production/scripts/lifecycle_replay.py --dry-run

# 3. Execute replay
.venv/bin/python production/scripts/lifecycle_replay.py --workers 4

# 4. Confirm pending count near zero
docker exec timescaledb psql -U postgres -d indicagent -c "
  SELECT status, COUNT(*) FROM signal_ledger GROUP BY status ORDER BY count DESC;"

# 5. Confirm dual-track coverage
docker exec timescaledb psql -U postgres -d indicagent -c "
  SELECT
    COUNT(*) FILTER (WHERE market_entry_price IS NOT NULL)    AS market_price_set,
    COUNT(*) FILTER (WHERE market_entry_outcome IS NOT NULL)  AS market_resolved,
    COUNT(*) FILTER (WHERE outcome IS NOT NULL)               AS zone_resolved,
    COUNT(*) FILTER (WHERE outcome IS NOT NULL
                      AND market_entry_outcome IS NOT NULL)   AS both_resolved
  FROM signal_ledger WHERE timestamp < NOW() - INTERVAL '1 day';"

# 6. Cross-track comparison
docker exec timescaledb psql -U postgres -d indicagent -c "
  SELECT outcome, market_entry_outcome, COUNT(*),
    ROUND(AVG(pnl_r)::numeric, 3)              AS avg_zone_pnl_r,
    ROUND(AVG(market_entry_pnl_r)::numeric, 3) AS avg_market_pnl_r
  FROM signal_ledger
  WHERE outcome IS NOT NULL AND market_entry_outcome IS NOT NULL
  GROUP BY outcome, market_entry_outcome ORDER BY count DESC;"

# 7. ANALYZE after bulk updates
docker exec timescaledb psql -U postgres -d indicagent -c "ANALYZE signal_ledger;"

# 8. Run full test suite
.venv/bin/pytest tests/unit/trading/test_lifecycle_tracker.py \
                 tests/unit/service_tests/test_signal_lifecycle_service.py \
                 tests/unit/scripts/test_lifecycle_replay.py -v
```

---

## Files Changed

| File | Change |
|---|---|
| `production/migrations/031_market_entry_dual_track.sql` | New — 7 columns, 1 index, drop redundant index |
| `src/intelligence/trading/lifecycle_tracker.py` | Add `MarketTransition` + `evaluate_market_entry()` |
| `src/intelligence/trading/signal_ledger.py` | Add `market_entry_price` to `LedgerEntry`+`_INSERT_SQL`; add `record_activation()`, `record_zone_resolution()`, `record_market_resolution()`; deprecate `update_signal_status()` |
| `services/signal_generator_service.py` | Set `market_entry_price` at INSERT |
| `services/signal_lifecycle_service.py` | Add `_market_mae/_market_mfe`; parallel market evaluation; independent resolution writes |
| `production/scripts/lifecycle_replay.py` | New — chronological streaming replay, dual-track, parallel, validated |
| `tests/unit/trading/test_lifecycle_tracker.py` | Extend |
| `tests/unit/service_tests/test_signal_lifecycle_service.py` | Extend |
| `tests/unit/scripts/test_lifecycle_replay.py` | New |
