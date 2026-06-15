# Review/Fix Stop and Zone Logic

**Created:** 2026-06-14
**Priority:** HIGH
**Impact:** 364K stopped_at_entry signals (25% of all signals)

## Problem

Signal replay revealed 364K stopped_at_entry outcomes (25% of 1.49M signals). Root cause analysis:

### Findings

1. **Zone generation produces extremely narrow zones:**
   - QQQ zones: 2-6 cents wide
   - XLE zones: 1-2 cents wide
   - IWM zones: 2 cents wide

2. **Entry placement at zone edge:**
   - Entries often at/below zone low
   - Example: QQQ zone [723.14, 723.16], entry 723.09 (below zone)

3. **Stop calculation issue:**
   - Stop calculated as `zone_low - 1×ATR` (when no structural stop found)
   - When zone is narrow + entry at edge, stop is extremely close to entry
   - Example: XLE zone [57.46, 57.47], entry 57.49, stop 57.46 (3 cents away)

4. **Tick gate is working correctly:**
   - All stops are ≥ 1 tick (tick gate fix from June 5 is functioning)
   - Issue is not sub-tick stops — it's stop-too-close-to-entry

## Sample Data

```
symbol | zone_width | entry_price | stop_loss | stop_distance
QQQ    | 0.02       | 723.09      | 723.24    | -0.15
XLE    | 0.01       | 57.49       | 57.46     | 0.03
IWM    | 0.02       | 293.41      | 293.44    | -0.03
SMH    | 0.30       | 621.99      | 621.39    | 0.60
```

## Potential Fixes

1. **Zone generation:** Add minimum zone width constraint (e.g., 0.5×ATR minimum)
2. **Stop calculation:** Calculate minimum distance from ENTRY, not zone edge
3. **Entry placement:** Don't place entries at zone edges when zone is narrow
4. **Stop validation:** Add emission gate for stop_distance vs entry (not just tick)

## Related Code

- `src/intelligence/trading/trade_framer.py` — stop calculation
- `src/intelligence/trading/zone_engine.py` — zone generation (MIN_ZONE_WIDTH_ATR = 0.25)
- `src/intelligence/trading/signal_schema.py` — emission gates

## Related Commits

- 19f7a918 (2026-06-05): "fix(signals): address root causes of degenerate stops"
- 0f66e77b (2026-06-05): "fix(signals): close degenerate-risk pnl_r corruption"

## Next Steps

1. Review zone generation logic — why are zones so narrow?
2. Review stop calculation — should be from entry, not zone edge
3. Add minimum stop distance gate (stop_distance >= min_atr_mult × ATR)
4. Test fix on replay subset before full deployment
