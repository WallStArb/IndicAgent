# Futures Roll Detection Architectural Simplification

**Version:** 1.0
**Status:** adopted
**Priority:** medium
**Milestone:** v2.8
**Last Updated:** 2026-05-26
**Tags:** futures, roll-detection, batch, simplification, sql, architecture, systemd
## Problem Statement

**Current architecture is over-engineered:**
- RollComputeAgent runs as 24/7 real-time service
- Consumes every 1-minute bar continuously
- Maintains 100-bar rolling windows per symbol
- Computes volume z-scores per bar
- Forces ibkr-provider restart on roll detection

**For a quarterly event that's typically actioned overnight.**

## Proposed Alternative

**Nightly batch job** (6pm ET after close):
```sql
UPDATE contract_metadata tgt
SET is_front_month = CASE
    WHEN front_vol < back_vol * 0.3 THEN false
    ELSE true
END
FROM (
    SELECT SUM(volume) as volume
    FROM market_data_ohlcv
    WHERE symbol = (front contract)
    AND timestamp > NOW() - INTERVAL '3 days'
) front
CROSS JOIN (
    SELECT SUM(volume) as volume
    FROM market_data_ohlcv
    WHERE symbol = (back contract)
    AND timestamp > NOW() - INTERVAL '3 days'
) back
WHERE tgt.symbol IN (front_contract, back_contract);
```

Services pick up changes naturally via `get_active_contracts()` refresh - no restarts required.

## Why Current Design Is Overkill

### 1. Futures Rolls Aren't Time-Critical
- **Reality:** Traders roll overnight or at close, not intraday
- **Current:** Sub-minute detection for quarterly event
- **Actual need:** "Was roll detected by tomorrow?" (hours/days tolerance)

### 2. Volume Shifts Are Gradual
- **Reality:** Volume shifts over days/weeks, not minutes
- **Current:** Per-bar z-score detection for instant drops
- **Actual need:** "Is front volume significantly lower?" (daily aggregates sufficient)

### 3. Service Restarts Are Expensive
- **Reality:** Restarting ibkr-provider = reconnect + resubscribe to 50+ contracts
- **Current:** Triggers restart on every roll
- **Actual need:** Update contract list, services refresh naturally

### 4. Algorithm Already Accepts Delays
- 30-minute cooldown after detection
- 3-bar confirmation (3-minute minimum)
- Calendar-based roll window (expiry - 3 days)

## Resource Cost Comparison

**Current (real-time):**
- CPU: 0.4% continuous (24/7)
- Memory: 90MB
- Bars: ~1,534/hour during market hours
- State: Rolling windows per symbol

**Proposed (batch):**
- CPU: ~1 second, once nightly
- Memory: 0
- Simplicity: One SQL query, cron job

## Research Checklist

- [ ] **Validate roll timing from signal_ledger**
  - Query historical rolls: when did they occur?
  - Check if intraday or overnight
  - Verify no time-critical use cases

- [ ] **Identify is_front_month consumers**
  - ibkr-provider (reads via get_active_contracts)
  - intelligence_pipeline_agent (contract selection)
  - Other services?
  - Can they handle periodic updates vs restarts?

- [ ] **Check existing signaling**
  - Does market.events.contract_update topic exist?
  - Can services subscribe to changes instead of polling?

- [ ] **Calibrate volume thresholds**
  - Analyze historical roll data
  - Find optimal volume ratio (proposal: 70% drop)
  - Validate 3-day lookback vs 100-bar window
  - Test if simple ratio outperforms z-score

- [ ] **Backtest both approaches**
  - Use roll_backtest.py to test current z-score algorithm
  - Test proposed volume ratio query
  - Compare accuracy: false positives/negatives

- [ ] **Implementation cost estimate**
  - Refactor RollComputeAgent → SQL script
  - Update services for natural refresh
  - Add monitoring/verification
  - Migration plan

## Decision Framework

**Implement simplification IF:**
1. ✅ Rolls occur overnight/during calm periods
2. ✅ Services can handle changes without restart
3. ✅ Volume ratio query matches/exceeds current accuracy
4. ✅ Engineering effort justified by operational savings

**Keep current design IF:**
1. ❌ Time-critical intraday rolls are common
2. ❌ Some service requires restarts
3. ❌ Z-score algorithm significantly outperforms simple ratio

## Expected Benefits

**Operational:**
- 99.9% compute reduction (24/7 → 1 second nightly)
- Eliminate service restarts
- Simpler monitoring (cron job vs continuous service)
- More reliable (no state to lose, no watchdog issues)

**Architectural:**
- Clearer separation (trading vs reference data)
- Easier to test (SQL query vs streaming state)
- Better aligns with how futures actually work
- Removes unnecessary real-time complexity

## Related Files

- `services/roll_compute_agent.py` - Current implementation
- `services/contract_metadata_writer_agent.py` - Updates contract_metadata
- `src/config/contracts.py` - Roll cycles, get_roll_window()
- `production/scripts/roll_backtest.py` - Backtesting tool
- `signal_ledger` table - Historical roll data for validation
