# Automated Roll Detection Design Review

**Date:** 2026-03-17
**Reviewer:** Claude
**Design Document:** `docs/plans/2026-03-17-automated-roll-detection-design.md`
**Status:** CRITICAL ISSUES FOUND

---

## Executive Summary

The design introduces Renaissance-style automated roll detection to IndicAgent's futures pipeline. While the high-level approach aligns with "Let the system run" principles, there are **4 critical architectural issues**, **6 significant edge case gaps**, and **missing integration points** that must be resolved before implementation.

**Recommendation:** Address CRITICAL and MAJOR issues before writing implementation plan.

---

## Critical Issues

### 1. Roll Chain Derivation Undefined

**Severity:** CRITICAL
**Location:** Design "Data Flow" diagram, line 52

**Problem:**
The design shows "roll chain (ESM6, ESU6, ESZ6)" but provides **no mechanism for deriving the roll chain**. The TWS daemon currently only knows about `Settings().contracts` (16 futures). There is no code to:
- Generate the next/previous contract symbols (e.g., ESM6 -> ESU6 -> ESZ6)
- Know which contracts belong to the same base symbol roll chain
- Determine the 3-contract window dynamically

**Impact:**
Cannot implement the feature without a roll chain derivation mechanism. Hardcoding is not viable for automated operation.

**Required Fix:**
Add a contract code derivation utility:
```python
# Example: src/providers/ibkr.py or src/config/contracts.py
def derive_roll_chain(base_symbol: str, current: str) -> list[str]:
    """Derive 3-contract roll chain: [prev, current, next]."""
    # Uses expiry codes (H=Mar, J=Apr, K=May, M=Jun, N=Jul, Q=Aug, U=Sep, V=Oct, X=Nov, Z=Dec)
    # Returns e.g., ["ESH6", "ESM6", "ESU6"]
    pass
```

**Alternative:** Read the roll chain from `contract_metadata.roll_from` / `.roll_to` after migration 036 is applied and seeded.

---

### 2. Data Consistency: Symbol Switch Creates Intelligence Features Gap

**Severity:** CRITICAL
**Location:** Design "At roll" phase, line 86

**Problem:**
When `intelligence_features` symbol switches from `ESM6` to `ESU6`, there will be:
1. No bars for `ESU6` in plugin histories (I1-I6 state is per-symbol)
2. Plugin state reset at rollover (indicators reinitialize from empty)
3. False signals from un-warmed indicators (e.g., RSI at 50, MACD flat)

The design mentions "graceful post-roll monitoring" but does not address **plugin state continuity**.

**Impact:**
- False trading signals immediately after roll
- Invalid ML training data in `intelligence_features` (features computed from empty state)
- "Never drop data" violated by losing indicator history

**Required Fix:**
Add plugin state migration mechanism:
```python
# In indicator_service.py, market_analysis_service.py
async def migrate_plugin_state(old_symbol: str, new_symbol: str):
    """Transfer plugin history from old to new contract at roll."""
    # Copy state dicts, history buffers, calculated values
    # Adjust for roll_gap in price-sensitive indicators
    pass
```

**Alternative:** Emit a "warmup in progress" flag in `intelligence_features.source` for N bars post-roll, and have `signal_generator` skip during warmup.

---

### 3. Service Contract Violation: All Services Read from `get_active_contracts()`

**Severity:** CRITICAL
**Location:** Design "Modified Files", line 98

**Problem:**
The design proposes modifying `tws_daemon.py` to read active contracts from `contract_metadata` via DB queries. However, **all other services** (indicator_service, market_analysis_service, signal_generator_service, ai_narrative_service, feature_writer_service, signal_lifecycle_service) use `get_active_contracts()` from `Settings()`.

If only `tws_daemon` switches to DB-backed contract selection, the pipeline will break:
- `tws_daemon` publishes bars for `ESU6`
- `indicator_service` subscribes to `Settings().contracts` (still `ESM6`)
- `indicator_service` ignores `ESU6` bars (not in symbol list)
- Downstream intelligence features for `ESU6` never compute

**Impact:**
Complete pipeline failure on first roll. The design does not specify updating other services.

**Required Fix:**
Two options:

**Option A: Global DB-backed contract selection (preferred)**
- Modify `get_active_contracts()` to query `contract_metadata` where `is_active=true`
- Add caching (refresh every 60 seconds) to avoid DB load
- Update all services to use the new contract list on refresh

**Option B: Contract mapping via Kafka (simpler)**
- `tws_daemon` publishes a "roll detected" event to `development.system:events`
- All services consume this event and update their symbol lists
- No DB dependency in hot path

**Missing in Design:** How/when downstream services update their contract lists.

---

### 4. Migration 037 Column Naming Conflict

**Severity:** CRITICAL
**Location:** Migration 037, line 108

**Problem:**
Migration 037 proposes adding `is_active` column to `contract_metadata`. However, `instruments` table already has an `is_active` column with different semantics:
- `instruments.is_active`: Whether the instrument is tracked at all (used for ETF activation/deactivation)
- `contract_metadata.is_active`: Whether this specific contract is the **currently front-month** active contract

This naming ambiguity will cause bugs:
- `instruments.is_active=true, contract_metadata.is_active=false` → what does this mean?
- Code querying "active instruments" gets both tables confused

**Impact:**
Data ambiguity, likely bugs in instrument management.

**Required Fix:**
Rename `contract_metadata.is_active` to `is_front_month` or `is_primary_contract`:
```sql
ALTER TABLE contract_metadata ADD COLUMN IF NOT EXISTS is_front_month BOOLEAN DEFAULT false;
COMMENT ON COLUMN contract_metadata.is_front_month IS 'Currently front-month contract (read by TWS daemon)';
```

---

## Major Issues

### 5. Roll Gap Direction Ambiguity

**Severity:** MAJOR
**Location:** Roll Detection Algorithm, line 177

**Problem:**
The design specifies `roll_gap = close_ESM6 - open_ESU6` but does not account for directionality:
- If roll is up (prices rise): `close_old < open_new`, gap is negative
- If roll is down (prices fall): `close_old > open_new`, gap is positive

The comment says "Positive = roll up, Negative = roll down" but the formula produces the opposite.

**Impact:**
Back-adjustment calculations will invert the gap direction.

**Required Fix:**
Standardize to positive value with signed direction:
```sql
roll_gap DOUBLE PRECISION,  -- Always positive (abs(close_old - open_new))
roll_direction VARCHAR(10),  -- 'up' or 'down'
```

---

### 6. No Roll Back Protection

**Severity:** MAJOR
**Location:** Configuration, line 137

**Problem:**
The design mentions "Roll back protection (verification window)" in future improvements (line 192) but does not include it in the implementation. Without verification:
- Transient volume spikes trigger premature rolls
- False rolls corrupt `intelligence_features` with data from wrong contracts

**Impact:**
False rolls create corrupted data that cannot be easily recovered (violates "Never drop data").

**Required Fix:**
Add a confirmation window (e.g., 3 consecutive bars above threshold) before committing roll:
```python
CONFIRMATION_BARS = 3  # Require N consecutive positive rolls
self._roll_confirmation: dict[str, list[bool]] = defaultdict(list)

# Only flip is_active after N consecutive confirmations
```

---

### 7. Roll Cooldown Insufficiently Defined

**Severity:** MAJOR
**Location:** Configuration, line 136

**Problem:**
`ROLL_MONITOR_COOLDOWN_MIN = 30` (minimum minutes between rolls) is insufficient. A roll is a **permanent** state change per base symbol. Rolling back and forth within 30 minutes would be catastrophic.

**Missing Logic:**
- Is this per base symbol? (likely yes)
- What happens if a false roll is triggered and the cooldown expires?
- Should the daemon recover to the correct contract?

**Required Fix:**
Add roll recovery logic:
```python
# If roll detected, verify against contract_metadata.roll_date
# If new detection is < 7 days from existing roll_date, log warning and ignore
```

---

### 8. Kafka Topic and Message Key Consistency

**Severity:** MAJOR
**Location:** Design "Data Flow" diagram

**Problem:**
The design shows publishing bars to `development.market.bars` (line 78). When `tws_daemon` switches from `ESM6` to `ESU6`:
- New bars have `symbol="ESU6"` in the payload
- Message key becomes `ESU6:1m` (via `message_key()`)
- Consumer groups (`indicator_service`, etc.) have partition assignments based on current keys
- Kafka consumer may not immediately consume new symbol if partition rebalance is delayed

**Impact:**
Potential bar loss during the brief period when symbol changes but consumers haven't rebalanced.

**Required Fix:**
Test consumer group rebalancing behavior on symbol changes. Consider publishing roll event before publishing first new-contract bar.

---

### 9. Instrument Table vs Contract Metadata Table Overlap

**Severity:** MAJOR
**Location:** Architecture overview

**Problem:**
The design introduces `contract_metadata` table but does not clarify its relationship to the existing `instruments` table:
- `instruments`: Stores `symbol` as **base symbol** (e.g., "ES", "SPY") per CLAUDE.md
- `contract_metadata`: Stores `symbol` as **contract symbol** (e.g., "ESM6") per migration 036

The two tables have overlapping concerns:
- `instruments.contract_details` stores expiry, exchange, etc.
- `contract_metadata` stores expiry_date, roll_date, exchange, etc.

**Impact:**
Data duplication, potential inconsistency between tables.

**Required Fix:**
Clarify the single source of truth for contract metadata:
- **Option A:** Use `instruments` for all metadata, add roll columns there
- **Option B:** Keep `instruments` for base-level info, `contract_metadata` for contract-level info
- **Design decision needed:** Document which table drives contract selection in `tws_daemon`

---

### 10. Missing IBKR Qualification for Non-Active Contracts

**Severity:** MAJOR
**Location:** Design "Modified Files", line 98

**Problem:**
`tws_daemon._qualify_all_instruments()` currently qualifies all instruments in `Settings().contracts`. With roll monitoring, the daemon needs to:
1. Qualify contracts in the roll chain (3 per base symbol = 48 total)
2. Subscribe to active contracts only (16 currently active)

However, IBKR `reqMktData()` has a subscription cap (current setting: 80). With 48 qualified contracts, we hit ~60% capacity.

**Missing in Design:**
- Does the daemon qualify all 3 contracts per base symbol upfront?
- How does it handle qualification failures for inactive contracts?
- What happens if IBKR rejects qualification (paper trading account, missing permissions)?

**Impact:**
Cannot poll bars for inactive contracts to compute volume ratios.

**Required Fix:**
Add roll chain qualification logic and graceful degradation:
```python
async def _qualify_roll_chain(self, base_symbols: list[str]) -> dict[str, list[str]]:
    """Qualify 3-contract roll chains for each base symbol."""
    for base in base_symbols:
        roll_chain = derive_roll_chain(base)
        for symbol in roll_chain:
            try:
                await self.provider.qualify_instrument(instrument_for(symbol))
            except Exception as e:
                logger.warning("Failed to qualify", symbol=symbol, error=str(e))
                # Mark as unavailable, skip from volume monitoring
```

---

## Edge Case Gaps

### 11. First Roll: No `roll_from` or `roll_to` Values

**Severity:** MODERATE
**Location:** Migration 037

**Problem:**
For the first automated roll (e.g., ESM6 -> ESU6), `contract_metadata` rows may not have populated `roll_from` or `roll_to` columns. The volume detection algorithm relies on knowing which contract is "next" in the chain.

**Impact:**
First roll may fail or require manual seed.

**Required Fix:**
Seed initial `contract_metadata` with roll chain before enabling automated detection:
```sql
INSERT INTO contract_metadata (symbol, base_symbol, asset_class, expiry_date, roll_from, roll_to)
VALUES
  ('ESM6', 'ES', 'futures', '2026-06-17', 'ESH6', 'ESU6'),
  ('ESU6', 'ES', 'futures', '2026-09-17', 'ESM6', 'ESZ6'),
  ...
```

---

### 12. Weekend/Holiday Gaps: Volume Ratio False Positives

**Severity:** MODERATE
**Location:** Roll Detection Algorithm

**Problem:**
On weekends or holidays:
- No bars for 48-72 hours
- Rolling volume window has old, stale data
- First trading day volume spikes artificially
- False roll detection likely

**Missing in Design:**
- Time-of-day awareness (mentioned in future improvements but not implemented)
- Market session gates (only trade during RTH hours)

**Required Fix:**
Add session-aware gating:
```python
if not self.market_hours.is_open(datetime.now()):
    return  # Skip roll detection outside market hours
```

The design has `MarketHoursManager` in `tws_daemon.py` but doesn't use it for roll detection.

---

### 13. Paper Trading Account Limitations

**Severity:** MODERATE
**Location:** Design Constraints

**Problem:**
The current IBKR setup uses paper trading (memory: `192.168.1.157` is paper). Some futures contracts are unavailable on paper accounts (e.g., NGJ6, BZJ6, SR1H6 per `src/providers/CLAUDE.md`).

**Impact:**
Roll detection may fail for contracts that cannot be qualified in paper trading.

**Required Fix:**
Add paper account handling:
```python
def _is_paper_account() -> bool:
    # Detect if running against paper trading
    return self.settings.ib_host in ("192.168.1.157", "127.0.0.1")

# Skip roll monitoring for unavailable contracts on paper
```

---

### 14. Roll Detection with Insufficient Volume History

**Severity:** MODERATE
**Location:** Roll Detection Algorithm, line 166

**Problem:**
The algorithm uses a 100-bar rolling window for z-score calculation. When a contract first becomes available:
- Fewer than 100 bars of history
- `rolling_std` is undefined or unreliable
- z-score calculation may fail or produce extreme values

**Impact:**
Unreliable roll detection early in contract lifecycle.

**Required Fix:**
Add warmup gate:
```python
MIN_BARS_FOR_ROLL = 100  # Match window size
if len(volume_history) < MIN_BARS_FOR_ROLL:
    return  # Skip detection until enough data
```

---

### 15. Multiple Simultaneous Rolls

**Severity:** LOW
**Location:** Roll Detection Algorithm

**Problem:**
If multiple futures roll in the same bar (e.g., ES and NQ both trigger), the design does not specify ordering or transactionality.

**Impact:**
Potential race conditions if multiple rolls update `contract_metadata` simultaneously.

**Required Fix:**
Use row-level locking or serial processing:
```sql
UPDATE contract_metadata
SET is_front_month = false
WHERE symbol = $1;  -- Old contract

UPDATE contract_metadata
SET is_front_month = true, roll_gap = $2, roll_detected_at = NOW()
WHERE symbol = $3;  -- New contract
```

---

### 16. Deactivation Timing: When to Stop Polling Old Contract

**Severity:** LOW
**Location:** Roll Lifecycle, line 88

**Problem:**
"Deactivate: Stop polling old contract" after 10-20 bars post-roll. The design does not specify:
- Does this free the IBKR subscription slot?
- What happens if the old contract needs to be polled again (e.g., false roll)?
- Is deactivation irreversible or can we resume monitoring?

**Impact:**
Potential subscription slot exhaustion or inability to recover from false rolls.

**Required Fix:**
Define deactivation semantics clearly:
```python
# After ROLL_MONITOR_POSTROLL_BARS (10-20):
# - Unsubscribe from IBKR market data
# - Remove from polling loop
# - Keep in qualified contracts list (can re-subscribe)
# - Log "deactivated: SYMBOL" for audit
```

---

## Integration Concerns

### 17. Signal Ledger: No Symbol Field for Base Symbol Tracking

**Severity:** MODERATE
**Location:** Not in design

**Problem:**
`signal_ledger` stores `symbol` as the specific contract (e.g., "ESM6"). After roll, signals will have mixed symbols in the same base series. This complicates:
- Historical performance analysis (how did ES perform across contracts?)
- Rolling 30-day setup statistics (setup_performance table)
- ML training on continuous series

**Missing in Design:**
- Should `signal_ledger` have a `base_symbol` column?
- How do downstream services query "all ES signals across all contracts"?

**Required Fix:**
Consider adding `base_symbol` to `signal_ledger` or creating a continuous series view.

---

### 18. Feature Writer: No Roll Event Handling

**Severity:** MODERATE
**Location:** Not in design

**Problem:**
`feature_writer_service` consumes `intelligence:SYMBOL:TF` and writes to `intelligence_features`. When symbol changes from `ESM6` to `ESU6`:
- Old bars continue to arrive briefly (Kafka ordering)
- New bars for `ESU6` arrive
- Feature writer writes both to `intelligence_features`
- No mechanism to mark the roll boundary in `intelligence_features`

**Impact:**
ML training data has an implicit roll boundary (no marker). Hard to identify which bars belong to which contract.

**Required Fix:**
Publish a roll event to `development.system:events` before switching, and have `feature_writer` write a marker row:
```sql
INSERT INTO intelligence_features (feature_ts, symbol, feature_tf, i1, i7)
VALUES (NOW(), 'ES', '1m', '{}'::jsonb, '{"roll_event":"ESM6->ESU6"}'::jsonb);
```

---

## Renaissance Principles Alignment

### "Let the system run"
**Alignment:** PARTIAL
- Automated detection aligns well
- Manual intervention still required to seed initial `contract_metadata` (issue #11)
- False rolls may require manual rollback (issue #6)

**Improvement:** Add full self-healing: detect and auto-revert false rolls.

---

### "Never drop data"
**Alignment:** VIOLATED
- Plugin state reset at roll creates gaps in intelligence continuity (issue #2)
- No marker in `intelligence_features` to identify roll boundary (issue #18)
- Potential bar loss during Kafka rebalance (issue #8)

**Improvement:** Implement plugin state migration and roll boundary markers.

---

### "Segment relentlessly"
**Alignment:** PARTIAL
- Design mentions segmented thresholds (line 187) but not in initial implementation
- No per-base-symbol roll timing patterns captured
- No distinction between equity index, energy, metals roll behaviors

**Improvement:** Capture roll timing patterns per base symbol and sector.

---

### "Earn the right through proof"
**Alignment:** GOOD
- Shadow mode via feature flag `ROLL_MONITOR_ENABLED` (line 132)
- No production impact when disabled
- Roll outcome tracking mentioned (line 190)

**Improvement:** Add explicit shadow mode metrics (would have rolled vs. did roll).

---

## Missing Considerations

### 19. Historical Backfill Continuity

The design does not address how `historical_backfill.py` should handle rolled contracts:
- When backfilling multi-year ES data, should it use back-adjusted continuous (`ContFuture`) or named contracts?
- If using named contracts, how does it know which contract was active at each timestamp?

**Recommendation:**
Use `contract_metadata` roll_date to determine active contract per timestamp in backfill.

---

### 20. Dashboard Display Implications

The dashboard (`dashboard/`) shows per-symbol cards. When ES rolls from ESM6 to ESU6:
- Does the card show "ESM6" or "ESU6"?
- What happens to historical signals shown on the card?
- Does the user see a "roll happened" notification?

**Missing in Design:**
UI/UX implications of contract symbol changes.

---

### 21. Metrics and Observability

The design does not define metrics for roll detection:
- `roll_detections_total` counter per base symbol
- `roll_false_positives_total` (manual revert events)
- `roll_detection_latency_seconds` (from volume threshold to `is_active` flip)
- `active_contract_switches_total` (total flips per base)

**Recommendation:**
Add Prometheus metrics for roll monitoring before production.

---

### 22. Testing Strategy

The verification section (line 199) suggests manual simulation but does not specify:
- Unit tests for volume ratio calculation
- Integration tests for roll event propagation
- E2E tests with mock IBKR data
- Backtest validation against historical roll dates

**Recommendation:**
Define a comprehensive test plan before implementation.

---

## Recommendations Summary

### Before Implementation (Critical Path)

1. **Resolve roll chain derivation** (issue #1)
   - Implement `derive_roll_chain()` utility
   - Or seed `contract_metadata` roll_from/roll_to

2. **Fix service contract consistency** (issue #3)
   - Decide: Option A (DB-backed `get_active_contracts()`) or Option B (Kafka roll events)
   - Update design with downstream service integration

3. **Rename `is_active` column** (issue #4)
   - Use `is_front_month` or similar

4. **Add plugin state migration** (issue #2)
   - Or define warmup period with suppression

### Before Production

5. **Add roll confirmation window** (issue #6)
6. **Add roll recovery logic** (issue #7)
7. **Define deactivation semantics** (issue #16)
8. **Add `base_symbol` to `signal_ledger`** (issue #17)
9. **Add roll boundary markers** (issue #18)
10. **Add Prometheus metrics** (issue #21)

### Nice-to-Have

- Roll timing patterns per base symbol
- Historical backfill continuity
- Dashboard roll notifications
- Automated false roll detection and revert

---

## Conclusion

The design has a solid foundation aligned with Renaissance principles, but requires significant architectural work before implementation. The **most critical gaps** are:

1. How to derive the roll chain programmatically
2. How downstream services update their contract lists
3. How to maintain plugin state continuity across rolls

**Recommendation:** Complete the "Before Implementation" items, then update the design document before creating an implementation plan via `/gsd:plan-phase`.

---

*Review completed: 2026-03-17*
*Next steps: Address CRITICAL issues, then proceed to implementation planning*
