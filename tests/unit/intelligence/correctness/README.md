# Mathematical Correctness Tests

## Purpose

Mathematical correctness validation: each Tier 1 computation is proven against
a reference implementation (pandas-ta). This enforces the Renaissance principle
that every indicator output must be provably correct before it enters the signal
pipeline.

## Tolerance Contract

- **Default max absolute error:** < 1e-6 (element-wise, after warm-up trim and NaN drop)
- **Per-indicator overrides:** recursive indicators (MACD, ADX) may use atol=1e-4
  due to seeding differences at the start of the series
- **Directional agreement:** > 99.9% (sign of diff must match excluding zero and NaN diffs)

## File Layout

One test file per plugin:

```
tests/unit/intelligence/correctness/
    __init__.py
    conftest.py          -- shared fixtures and assert_close_to_reference helper
    README.md            -- this file
    test_atr.py          -- ATR vs pandas-ta reference
    test_rsi.py          -- RSI vs pandas-ta reference
    test_macd.py         -- MACD vs pandas-ta reference
    test_adx.py          -- ADX vs pandas-ta reference
    test_vwap.py         -- VWAP vs pandas-ta reference
```

## How to Add a New Correctness Test

1. Create `test_<indicator>.py` in this directory.
2. Import the fixture(s) you need from conftest (e.g., `synthetic_ohlcv_trending`).
3. Import `assert_close_to_reference` and `frames_from_ohlcv` from conftest.
4. Compute the production value using the plugin's `compute_full(frames)`.
5. Compute the reference using pandas-ta (e.g., `pta.atr(df.high, df.low, df.close, length=14)`).
6. Call `assert_close_to_reference(ours, reference, warmup_bars=<N>, atol=<override or default>)`.

Example:

```python
import pandas_ta as pta
from tests.unit.intelligence.correctness.conftest import (
    assert_close_to_reference,
    frames_from_ohlcv,
)

def test_atr_trending(synthetic_ohlcv_trending):
    df = synthetic_ohlcv_trending
    frames = frames_from_ohlcv(df)
    result = MyAtrPlugin().compute_full(frames)
    ours = result["atr_14"]
    ref = pta.atr(df.high, df.low, df.close, length=14)
    assert_close_to_reference(ours, ref, warmup_bars=28, name="ATR-14 trending")
```

## Reference Library

pandas-ta (https://github.com/twopirllc/pandas-ta) is the reference implementation.
Import as `import pandas_ta as pta`.

## Warm-up Policy

Each indicator passes its own `warmup_bars` to `assert_close_to_reference` so that
seeding differences at the start of the series do not produce false failures.
Standard values:

| Indicator | warmup_bars | Notes |
|-----------|-------------|-------|
| ATR       | 28          | 2x period for Wilder smoothing to stabilise |
| RSI       | 14          | 1x period |
| MACD      | 35          | slow EMA period |
| ADX       | 28          | 2x period |
| VWAP      | 0           | session-anchored, no warm-up |
