# Market Entry Dual-Track + Lifecycle Replay
**Date:** 2026-03-14
**Status:** Shipped
**Scope:** signal_ledger schema, lifecycle_tracker, signal_ledger.py, signal_generator_service, signal_lifecycle_service, lifecycle_replay script

> **Name drift note (2026-03-28):** `signal_lifecycle_service` → `signal_tracker_agent` / `SignalTrackerAgent` (Phase 52.4). References in this doc to `signal_lifecycle_service` are historically accurate to when the feature was built.

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
market_entry_gap_bars       INTEGER           -- NULL for live signals; replay only: bars between signal fire and bar N+1
                                              --   (gap > 0 means fill was at a delayed open, not the immediate next bar)
                                              -- Persisted so gap-affected fills can be filtered from ML training sets
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
  ADD COLUMN IF NOT EXISTS market_entry_outcome        TEXT,
  ADD COLUMN IF NOT EXISTS market_entry_gap_bars       INTEGER;  -- NULL for live; set by replay when N+1 bar was delayed

-- Analytics index mirroring idx_ledger_outcome
CREATE INDEX idx_ledger_market_outcome
ON signal_ledger (market_entry_outcome, setup_plugin, timeframe)
WHERE market_entry_outcome IS NOT NULL;

```

**8 new columns. 1 new index.**

Note: `idx_ledger_sym_ts` is NOT dropped in this migration — it may be used by API query paths. Audit index usage via `pg_stat_user_indexes` + `pg_stat_statements` separately before removing.

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
    gap_bars: int | None = None  # replay only; None for live signals
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
record_market_resolution(db, signal_id, *, market_entry_exit_price, market_entry_pnl_r, market_entry_mae, market_entry_mfe, market_entry_bars_in_trade, market_entry_outcome, market_entry_gap_bars=None)
record_zone_resolution_with_activation(db, signal_id, *, activated_at, activation_price, zone_entry_pct, bars_to_activation,
                                        status, exit_at, exit_price, exit_reason, pnl_ticks, pnl_r, pnl_dollars,
                                        signal_quality, mae, mfe, bars_in_trade, outcome)
  # Atomic single-SQL write for same-bar activation + immediate exit.
  # Prevents crash window where signal is left in 'active' with activated_at set but no exit_at.
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
self._market_mae: dict[str, float] = {}          # parallel to _mae
self._market_mfe: dict[str, float] = {}          # parallel to _mfe
self._market_activated_at: dict[str, datetime] = {}  # bar_time of first evaluation (bar N+1)
```

`market_entry_bars_in_trade` is computed using `_bars_in_trade(_market_activated_at[sid], bar_time, timeframe)` — explicitly `bar_time`, not `datetime.now()`. The existing zone track live code uses `now` (processing-time), which introduces a subtle lag. Both tracks in this implementation MUST use `bar_time` for `_bars_in_trade`. As a same-PR cleanup, update the zone track `_bars_in_trade` call to also use `bar_time` — this corrects the existing inconsistency and keeps both tracks comparable. `_market_activated_at[sid]` is set to `bar_time` on the first bar a signal enters the market evaluation loop.

**Per-bar evaluation order (market BEFORE zone on every bar):**

1. Read `market_entry_price` from signal dict (already in DB from Phase 1)
2. **Market track first:** If `market_entry_price IS NOT NULL` and `sid not in resolved_market`:
   - Initialize `_market_activated_at[sid] = bar_time` on first bar
   - Call `evaluate_market_entry()` with `_market_mae[sid]`, `_market_mfe[sid]`
   - Update `_market_mae[sid]`, `_market_mfe[sid]` each bar
   - If `MarketTransition.outcome IS NOT NULL`:
     - Compute `market_entry_bars_in_trade = _bars_in_trade(_market_activated_at[sid], bar_time, tf)`
     - Call `record_market_resolution()`, clean up `_market_mae/_market_mfe/_market_activated_at[sid]`
3. **Zone track second:** evaluate zone track as before
4. **Zone track resolves:** Before writing `exit_at` via `record_zone_resolution()`, if market track is somehow still open (defensive — should not occur with identical TTL), force-resolve market track using `close` as exit price, then write zone resolution. This ensures `exit_at IS NOT NULL` never appears before both tracks are resolved.
5. Clean up all remaining state for sid after zone resolution

**Why market before zone:** Both tracks use identical TTL from the same signal. They will TTL-expire on the same bar. Processing market first, then zone, ensures `record_market_resolution()` is always called before `record_zone_resolution()` writes `exit_at`. Once `exit_at` is written the signal leaves `get_active_signals()` — market track data must be persisted first.

**Atomicity on same-bar activation + immediate exit:** If a signal activates AND immediately exits on the same bar (e.g., zone entered and stop hit on same bar), call a combined `record_zone_resolution_with_activation()` that writes both in a single SQL statement. This avoids a crash window between the two writes that would leave a signal stuck in `active` status with `activated_at` set but no `exit_at`.

**Stop outcome classification:** `_classify_stop_outcome(market_mfe, market_entry_bars_in_trade)` is called identically for the market track using `market_entry_bars_in_trade` and `_market_mfe[sid]`. Same `OUTCOME_THRESHOLD_QUICK_STOP_BARS = 2` threshold applies.

**Regime_suppressed signals:** Receive market track evaluation identically to pending/active signals. Their existing counterfactual `pnl_r` (virtual activation at bar close using `entry_price`) and new `market_entry_pnl_r` (tick fill at `ask/bid`) are meaningfully different and both captured.

**Pre-existing limitation (document, do not fix in this plan):** `_mae`/`_mfe` and market track equivalents reset to 0.0 on service restart since MAE/MFE are not checkpointed mid-signal. Final excursions underestimate true extremes for signals spanning a service restart.

---

## Lifecycle Replay Script

**`production/scripts/lifecycle_replay.py`** — standalone, DB-only, no IBKR, no Redpanda.

### Algorithm

```
For each symbol + timeframe (up to 240 iterations, parallelized):

  1. VALIDATE mode (run first if --validate):
     - Sample 100 already-resolved signals with known zone outcomes (status not in ('pending', 'regime_suppressed'))
     - Run replay evaluation against their historical bars using the same evaluate_signal() / evaluate_market_entry() functions
     - Fields compared:
         Zone track: `outcome` (exact string match), `exit_price` (±0.5 tick tolerance), `pnl_r` (±0.01 tolerance)
         Market track: `market_entry_outcome` (exact), `market_entry_pnl_r` (±0.01)
     - **Cold-start limitation:** On the first run of this feature, existing resolved signals will have NULL `market_entry_outcome`
       (the live service had no market track before this ships). Validate mode skips market track comparison when
       `market_entry_outcome IS NULL` for all sampled signals and logs: "Market track validation skipped — no resolved
       market outcomes yet. Re-run --validate after live signals accumulate." This is not a failure. The zone track
       comparison remains fully active and is the primary correctness gate. Post-deployment, once the live service has
       resolved >100 signals with both tracks, re-run `--validate` to cross-check market track.
     - Excluded from comparison (ambiguous cases):
         - Signals where bar N+1 open == stop_loss or open == any target (boundary bar — live and replay may differ by one bar)
         - Signals where `market_data_ohlcv` has a data gap > 1.5 × tf_seconds after signal.timestamp
     - Report match rate on non-excluded signals — block proceed if match rate < 100% (zone) or < 100% (market, if any market outcomes present)
     - Produce discrepancy report: signal_id, field, stored_value, replay_value

  2. Fetch unresolved signals (pending + regime_suppressed):
     SELECT * FROM signal_ledger
     WHERE status IN ('pending', 'regime_suppressed') AND symbol = $1 AND timeframe = $2
     ORDER BY timestamp ASC
     (Regime_suppressed signals are included — per Renaissance principle, every signal outcome is a labeled training sample.
      Their zone `never_activated` outcome and market `pnl_r` provide a distinct and valuable comparison class.)

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

  5. End of bars: remaining live_signals → TTL expiry (compute final state explicitly)
     For each signal still in live_signals:
       - bars_elapsed = round((last_bar.timestamp - signal.timestamp) / tf_seconds)
       - If bars_elapsed >= TTL: classify as ttl_expired_ahead (MFE > 0) or ttl_expired_behind (MFE <= 0)
         using accumulated _zone_mfe / _market_mfe at last bar seen
       - Zone track: write record_activation() if never activated (with activated_at = None, indicating never-activated),
         then record_zone_resolution() with outcome = 'never_activated' or TTL outcome
       - Market track: write record_market_resolution() with TTL outcome using last bar's close as exit_price
       - Use last_bar.timestamp for all temporal fields, never datetime.now()
       - Do NOT add a sentinel bar — synthetic data corrupts MAE/MFE accumulation

  6. Commit every --batch-size signals (default 500)

  7. Print per-symbol/TF summary statistics
```

**Critical correctness requirement:** ALL temporal fields (`activated_at`, `exit_at`) use `bar.timestamp`, never `datetime.now()`. The live service uses `datetime.now()` because it processes bars in real time. The replay must substitute bar timestamps throughout or `bars_in_trade` calculations will be corrupted for all 455k signals.

### Parallelism

Python `multiprocessing.Pool` with `--workers N` (default 4). Each worker owns its own DB connection.

Work is distributed via a shared work queue (not static symbol assignment). The coordinator builds a flat list of `(symbol, timeframe)` tuples ordered by estimated row count descending (largest first, from `pg_class.reltuples` on signal_ledger). Workers pull from the queue one task at a time — a free worker takes the next `(symbol, tf)` pair. This prevents one slow large-symbol job from holding a worker while others are idle. Each `(symbol, tf)` tuple is processed by exactly one worker — no cross-worker state sharing.

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

**Mathematical invariants (assert on final MarketTransition values only — not intermediate per-bar state):**
- `MAE ≤ pnl_r ≤ MFE` always — final P&L bounded by excursion range
- MAE ≤ 0 for losing trades; MFE ≥ 0 for winning trades
- `pnl_r == (exit_price - market_entry_price) * direction / abs(market_entry_price - stop_loss)` exactly
- When stop hit: `exit_price == stop_loss` exactly
- When target hit: `exit_price == targets[i]` exactly

Note: do NOT assert intermediate `_market_mae`/`_market_mfe` values mid-bar-loop — these are internal accumulator state and may not match final written values if the exit bar updates both accumulator and exit price in the same call.

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

# 9. Post-deployment market track validation (run after live signals accumulate, >100 with both tracks resolved)
.venv/bin/python production/scripts/lifecycle_replay.py --validate --dry-run
# On first run this will log "Market track validation skipped — no resolved market outcomes yet" — expected.
# After live service has processed 100+ signals with market_entry_outcome set, re-run to validate market track.
```

---

## Files Changed

| File | Change |
|---|---|
| `production/migrations/031_market_entry_dual_track.sql` | New — 8 columns, 1 new index |
| `src/intelligence/trading/lifecycle_tracker.py` | Add `MarketTransition` + `evaluate_market_entry()` |
| `src/intelligence/trading/signal_ledger.py` | Add `market_entry_price` + `market_entry_gap_bars` to `LedgerEntry`+`_INSERT_SQL`; add `record_activation()`, `record_zone_resolution()`, `record_market_resolution()`, `record_zone_resolution_with_activation()`; deprecate `update_signal_status()` |
| `services/signal_generator_service.py` | Set `market_entry_price` at INSERT |
| `services/signal_lifecycle_service.py` | Add `_market_mae/_market_mfe`; parallel market evaluation; independent resolution writes |
| `production/scripts/lifecycle_replay.py` | New — chronological streaming replay, dual-track, parallel, validated |
| `tests/unit/trading/test_lifecycle_tracker.py` | Extend |
| `tests/unit/service_tests/test_signal_lifecycle_service.py` | Extend |
| `tests/unit/scripts/test_lifecycle_replay.py` | New |
