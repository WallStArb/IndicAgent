# MomentumAcceleration I2 Plugin — Design

**Date:** 2026-03-02
**Status:** Shipped — src/intelligence/composites/momentum_accel.py
**Tier:** I2 (consumes I1 features, runs before I3)

---

## Problem

The platform currently detects *whether* momentum is bullish or bearish but not *whether it is accelerating or decelerating*. RSI decelerating toward 50 is an earlier reversal signal than RSI crossing 50. The second derivative of momentum indicators provides inflection points before price or indicator levels confirm.

---

## Design

### Plugin Identity

- **File:** `src/intelligence/composites/momentum_accel.py`
- **Name:** `evt_MomentumAcceleration`
- **Tier:** I2 — consumes `features` / `prev_features` from the I1 output dict
- **capability_tags:** `frozenset({"momentum"})`

### Outputs (4 fields)

| Field | Type | Meaning |
|---|---|---|
| `rsi_accel` | float | `rsi_14 - prev_rsi_14` |
| `macd_accel` | float | `macd_12_26_9 - prev_macd_12_26_9` |
| `roc_accel` | float | `roc_14 - prev_roc_14` |
| `inflection_flag` | int (0/1) | 1 if any of the three deltas changes sign vs prior bar |

### Inflection Detection

RSI, MACD, and ROC use different smoothing (Wilder EMA / EMA-diff / raw lookback), so their inflection points are not synchronised. Requiring agreement across indicators would add lag with no mathematical justification. `inflection_flag` fires when **any one** of the three deltas changes sign — maximising early-warning sensitivity. Downstream consumers can use the raw `*_accel` fields to apply their own confirmation logic.

### State

`_state` stores the previous delta for each indicator to detect sign changes:
- `prev_rsi_accel`, `prev_macd_accel`, `prev_roc_accel`

No additional history is needed beyond what `prev_features` already provides.

### Edge Cases

- Returns `0.0` / `0` for all fields if any required indicator is missing
- `inflection_flag` is always 0 on the first bar (no prior delta in state yet)
- Uses `is_num()` from `common.py` — safe against `None` and `MagicMock`

---

## Files to Create / Modify

| Action | File |
|--------|------|
| Create | `src/intelligence/composites/momentum_accel.py` |
| Modify | `src/intelligence/register_plugins.py` — import + register + add to `TIER_I2` |
| Create | `tests/unit/intelligence/composites/test_momentum_accel.py` |

---

## Tests (TDD — write first)

1. Returns all-zero dict when `prev_features` is absent
2. `rsi_accel` = correct delta across two bars
3. `macd_accel` = correct delta across two bars
4. `roc_accel` = correct delta across two bars
5. `inflection_flag = 0` on second bar (first delta, no prior delta in state)
6. `inflection_flag = 1` when `rsi_accel` changes sign
7. `inflection_flag = 1` when `macd_accel` changes sign
8. `inflection_flag = 1` when `roc_accel` changes sign
9. `inflection_flag = 0` when all three deltas maintain sign
10. `inflection_flag = 0` when delta goes from non-zero to zero (no sign change)
11. State persists correctly across 3+ sequential `compute_next()` calls
12. Plugin name is registered in `TIER_I2`
