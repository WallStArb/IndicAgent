# Signal Quality Hardening — Phase A Design

Date: 2026-05-14
Status: Approved
Scope: Fix signal pipeline quality gates, eliminate phantom PnL, start clean

## Problem Statement

The signal pipeline produces ~50K signals/day with 99.98% TTL-expiring as noise. Root causes:

1. **TTL hardcoded at 10 bars** — 10 minutes on 1m TF, too short for structural setups. TF-aware TTL exists in `service_utils.py` but was never wired in.
2. **Price precision loss** — `signal_schema.py` rounds all prices to 2dp. EURUSD 1.16917 → 1.17, making stop == entry. This is the root cause of all micro-stops and phantom PnL.
3. **No emission gate** — signals with stop==entry, RR<1.5, or no structural stop pass through unfiltered.
4. **Market entry track broken** — 406K signals have `market_entry_price` but 0 have `market_entry_pnl_r`. Outcomes never persist.
5. **TTL check before stop/target** — signals expire even when price is at target on the TTL bar.

## Design

### W1: Wire TF_TTL_BARS into Pipeline

**Current state:** `TF_TTL_BARS` defined in `src/core/service_utils.py` with values `{1m:20, 5m:12, 15m:8, 1h:6}`. Only used by `lifecycle_replay.py`. Pipeline still uses `ttl_bars=10` default. Missing 4h and 1d entries.

**Change:**
- Update `TF_TTL_BARS` values: `{1m:20, 5m:12, 15m:10, 1h:8, 4h:6, 1d:4}`
- `make_signal_from_frame()` in `signal_schema.py`: accept `timeframe` param, look up `TF_TTL_BARS.get(timeframe, 10)` for `ttl_bars`
- `make_signal()`: change default from 10 to accept explicit value
- `intelligence_pipeline_agent.py`: remove `sig.setdefault("ttl_bars", 10)` defensive fallback
- Each I7 plugin passes `timeframe` through to `make_signal_from_frame()`

**Files:** `signal_schema.py`, `intelligence_pipeline_agent.py`, all 36 I7 plugins (timeframe param)

### W2: Move TTL Check After Stop/Target + Active-Bar Counting

**Current state:** `lifecycle_tracker.py:evaluate_signal()` checks TTL at line 226, BEFORE zone activation (257), stop (445), and target (473). TTL counts every bar including empty bars (high==low, no volume), so overnight/session-gap bars eat TTL without price moving.

**Change:**
1. Reorder `evaluate_signal()`:
   - Zone activation (pending → active)
   - Stop loss check
   - Target hit check
   - Chandelier trailing stop
   - Staleness check
   - TTL expiry (last)
2. Change `_bars_elapsed()` in `signal_tracker_compute_agent.py` to count **active bars only** — skip bars where `high == low` (no price range). This makes TTL reflect actual trading opportunity, not calendar time. An empty overnight bar doesn't decrement the signal's life.

Same reordering for `evaluate_market_entry()` (lines 549-565).

**Files:** `lifecycle_tracker.py`, `signal_tracker_compute_agent.py`

### W3: Fix Price Precision

**Current state:** `signal_schema.py:96-98` rounds to 2dp:
```python
"entry_price": round(entry_price, 2),
"stop_loss": round(stop_loss, 2),
"targets": [round(t, 2) for t in targets],
```

**Change:**
- Add `TICK_SIZES` dict to `src/core/service_utils.py` populated from instrument config in `settings.py`
- Add `round_to_tick(price: float, symbol: str) -> float` utility
- Replace `round(x, 2)` with `round_to_tick(x, symbol)` in `signal_schema.py`
- Also round zone_low, zone_high to tick precision

**Tick sizes by instrument group:**
- FX pairs: 0.00001 (pipette)
- JPY pairs: 0.001
- Index futures (ES, NQ, YM, RTY): 0.25
- Rate futures (ZN, ZB, ZF, ZT): 1/64 or 0.015625
- Commodity futures (CL, NG, ZW, ZC, ZS): varies (0.01, 0.001, 0.25)
- Equities/ETFs: 0.01

Default for unknown: preserve full precision (no rounding).

**Files:** `service_utils.py` (TICK_SIZES + round_to_tick), `signal_schema.py`, `settings.py` (instrument config)

### W4: Hard Emission Gate

**Current state:** No validation beyond TradeFrame.viable check. Signals with stop==entry or RR<1.5 pass through.

**Change:** Add validation in `make_signal_from_frame()` AFTER TradeFrame construction:
1. `abs(entry - stop) >= tick_size` — stop must be at least 1 tick from entry
2. `abs(entry - stop) >= effective_atr * MIN_STOP_ATR (1.0)` — stop must be at least 1 ATR from entry (catches instruments where tick < ATR but stop is still too tight)
3. `rr_t1 >= MIN_RR_T1 (1.5)` — minimum risk/reward
4. `stop_type != "unknown"` — must have identified a structural stop basis
5. If any gate fails, raise ValueError (caught by plugin → `no_signal()`)

This is applied at the signal construction boundary — invisible to plugins, enforced universally.

**Files:** `signal_schema.py` (validation in make_signal_from_frame)

### W5: Wipe signal_ledger and Derivative Data

**Current state:** 2.5M rows, 99.98% noise, phantom PnL from precision loss. All derivative stats computed on garbage.

**Change:** Full wipe — clean slate for the fixed pipeline:
- `TRUNCATE signal_ledger CASCADE`
- Truncate signal derivatives: `signal_lineage`, `signal_transform_log`, `signal_metrics`, `signal_metrics_dq_failures`, `signal_metrics_ic`, `setup_performance`
- Truncate AI/LLM tables: `signal_ai_enrichment`, `intelligence_ai_enrichment`, `llm_calls`, `llm_model_scores`, `alpha_multiplier_shadow`, `swarm_agent_weights`
- All signal and AI data will be rebuilt from scratch by the fixed pipeline
- Keep: `intelligence_features`, `market_data_ohlcv`, `shadow_registry`, `instruments`, `contract_metadata` — these are clean source data

**Execution:** One-time SQL script, run after all code changes deployed and tested.

### W6: Fix Market Entry Track Persistence

**Current state:** 406K signals have `market_entry_price` but 0 have `market_entry_pnl_r`. The `evaluate_market_entry()` function runs per bar but outcomes never persist.

**Change:** Trace the `_publish_market_resolution()` path in `signal_tracker_compute_agent.py` to find where the write fails. Likely issue: the market resolution is published as a Kafka event but the lifecycle_writer doesn't handle market-track updates, OR the update SQL doesn't SET the market_entry columns.

**Files:** `signal_tracker_compute_agent.py`, `lifecycle_writer_agent.py`, `signal_ledger_repository.py`

## Execution Order

1. **W3 (price precision)** — most fundamental, fixes stop calculation
2. **W4 (emission gate)** — depends on tick sizes from W3
3. **W1 (wire TTL)** — independent of precision
4. **W2 (reorder TTL check)** — independent, small change
5. **W7 (remove confidence boost)** — one-line removal, no risk
6. **W6 (market entry track)** — independent, diagnostic fix
7. **W5 (clean data)** — LAST, after all code changes deployed and tested
8. **Restart pipeline** — with clean code and clean data

### W7: Remove Per-Agreement Confidence Boost

**Current state:** Aggregator adds +0.05 per agreeing signal (`_CONFIDENCE_BOOST_PER_AGREE` in `aggregator.py:37`). This amplifies consensus signals — the ones that are LEAST selective and have the worst PnL.

**Change:** Remove `_CONFIDENCE_BOOST_PER_AGREE` from aggregator. Signals should stand on their own quality, not get boosted because other signals agree.

**Files:** `aggregator.py`

## Phase B (Deferred)

After 3-5 days of clean data:
- Retrain isotonic calibration curves on real outcomes
- Evaluate plugins against n>=30 positive-EV gate
- Shadow or disable failing plugins
- Lower plugin base confidence floors where appropriate

## Success Metrics

After 7 days of clean pipeline:
- Signal count: <5K/day (from 50K)
- Actionable rate: >5% hitting stop or target (from 0.02%)
- No signals with stop==entry
- No signals with pnl_r > 50 (from micro-stop inflation)
- Market entry track: >0 signals with market_entry_pnl_r populated
- Confidence calibration: monotonic (higher confidence → better PnL)

## Files Changed

| File | Changes |
|------|---------|
| `src/core/service_utils.py` | Add TICK_SIZES, round_to_tick() |
| `src/intelligence/trading/signal_schema.py` | Wire TF_TTL_BARS, replace round(x,2), add emission gate |
| `src/intelligence/trading/lifecycle_tracker.py` | Reorder TTL check after stop/target |
| `services/intelligence_pipeline_agent.py` | Remove ttl_bars=10 fallback, pass timeframe |
| `services/signal_tracker_compute_agent.py` | Fix market entry track persistence |
| `src/intelligence/trading/aggregator.py` | Remove _CONFIDENCE_BOOST_PER_AGREE |
| All 36 I7 plugins | Pass timeframe to make_signal_from_frame() |

## Rollback

If issues arise:
- Revert `signal_schema.py` rounding to `round(x, 4)` (safe middle ground)
- Revert TTL to 10 bars (conservative)
- All changes are in code, not schema — rollback is `git revert`
