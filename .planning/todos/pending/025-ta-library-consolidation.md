# 025 — Consolidate Hand-Rolled TA Indicators to Maintained Library

**Priority: Low — correctness risk, not a bug; existing implementations are tested**
**Gate: No dependency; safe to do any time**

---

## Problem

Several standard financial indicators in `feature_factory.py` and `feature_cache.py` are
hand-rolled rather than backed by a maintained library:

- Wilder RSI (`_wilder_rsi_series` in `feature_cache.py`)
- ATR (`_atr_series_full` in `feature_factory.py`)
- CCI (`_cci` in `feature_factory.py`)
- Aroon oscillator (`_aroon_osc` in `feature_factory.py`)
- CMF (`_cmf` in `feature_factory.py`)

Each is a maintenance surface. A numerical edge case found and fixed in one place does
not propagate to the others. A new contributor must trust our implementation matches the
canonical definition.

Statistical features (skewness, ACF, Hurst, z-scores) are correctly hand-rolled since
no maintained library simplifies them — these are out of scope.

## Proposed Fix

Replace the financial indicator implementations with `pandas-ta` (pure Python, no C
dependency) or `TA-Lib` (faster, but requires C build). `pandas-ta` is the lower-friction
choice: `pip install pandas-ta`, no system dependency.

Pattern:
```python
import pandas_ta as ta

def _atr_series_full(highs, lows, closes, period):
    df = pd.DataFrame({"high": highs, "low": lows, "close": closes})
    return ta.atr(df["high"], df["low"], df["close"], length=period).fillna(0.0).to_numpy()
```

## Scope

- `src/intelligence/feature_factory.py` — replace `_cci`, `_aroon_osc`, `_cmf`, `_atr_series_full`
- `src/intelligence/feature_cache.py` — replace `_wilder_rsi_series` (verify scalar output unchanged)
- Parity tests in `tests/unit/intelligence/test_feature_factory_batch_parity.py` must stay green
- Add `pandas-ta` to `requirements.txt`

## Notes

Do NOT replace the statistical helpers (skewness, ACF, Hurst, z-scores) — those are
correct as-is and no library simplifies them.

Verify output values are numerically equivalent before shipping (especially RSI Wilder
smoothing — some libraries use EMA, not Wilder's specific alpha=1/period).
