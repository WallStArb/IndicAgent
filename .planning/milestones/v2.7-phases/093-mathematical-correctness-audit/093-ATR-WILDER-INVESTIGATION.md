# ATR Wilder's Smoothing Convention Investigation

**Date:** 2026-05-21
**Plan:** 093-02
**Status:** Resolved — production code uses correct convention; seeding differs from pandas-ta

---

## Background

The ATR (Average True Range) indicator uses Wilder's smoothing, which is a specific form of exponential
moving average (EMA) with alpha=1/N. Two different ewm conventions appear in Python codebases, and
this document clarifies which is correct and which our production implementation uses.

---

## The Two Conventions

### Convention A: Wilder's Original Definition (alpha=1/N)

J. Welles Wilder (1978, "New Concepts in Technical Trading Systems") defined his smoothing as:

```
Smoothed_t = Smoothed_{t-1} * (N-1)/N + Value_t * (1/N)
```

This is an exponential moving average with **alpha = 1/N**.

In pandas terms: `ewm(alpha=1/N, adjust=False)`

For N=14: `ewm(alpha=1/14, adjust=False)` which means alpha ≈ 0.07143

The equivalent `span` parameter in pandas: `span = 2/alpha - 1 = 2*N - 1 = 27`

### Convention B: Standard EMA Convention (span=N)

A common but INCORRECT alternative uses `span=N`, which gives `alpha = 2/(N+1)`.

For N=14: `ewm(span=14, adjust=False)` which means alpha = 2/15 ≈ 0.1333

This is the standard EMA convention, NOT Wilder's smoothing.

---

## Investigation: pandas-ta Source Code

Inspecting `pandas_ta.overlap.rma` (Wilder's Moving Average in pandas-ta):

```python
alpha = (1.0 / length) if length > 0 else 0.5
rma = close.ewm(alpha=alpha, adjust=False).mean()
```

**Conclusion:** pandas-ta uses `alpha = 1/length` — this is **Convention A**, Wilder's original definition.

Inspecting `pandas_ta.volatility.atr`:

```python
mamode = v_mamode(mamode, "rma")  # default mode is RMA (Wilder's MA)
# ...
presma = kwargs.pop("presma", True)
if presma:
    sma_nth = tr[0:length].mean()
    tr[:length - 1] = nan
    tr.iloc[length - 1] = sma_nth
atr = ma(mamode, tr, length=length, talib=mode_tal)
```

**Key detail:** pandas-ta uses `presma=True` by default. This explicitly seeds the ewm starting at
bar `length-1` with the SMA of the first `length` TR values, then sets all earlier bars to NaN.
The ewm then runs from this single SMA-seeded starting point.

---

## Our Production Implementation

In `src/intelligence/features/i1_indicators/atr.py` (line 45):

```python
atr = tr.ewm(alpha=1 / p, adjust=False, min_periods=p).mean()
```

This uses `min_periods=p` which causes the first valid value to be at bar `p-1`, seeded
by the ewm's own internal initialization (the first data point sets the initial ewm state).

**Key difference:** Our code uses pandas' built-in ewm initialization with `min_periods=p`,
while pandas-ta explicitly seeds with `SMA(first p TR values)` at bar `p-1`. These seedings
differ because pandas ewm with `adjust=False` and `min_periods=p` uses the first value seen
as the initial state, whereas pandas-ta uses the explicit SMA as the starting value.

---

## Empirical Seeding Difference Analysis

On the 500-bar trending fixture (seed=42), the discrepancy between our code and pandas-ta:

| Bar index | max absolute error |
|-----------|-------------------|
| 14 (first bar) | ~0.011 |
| 28 | ~0.0017 |
| 100 | ~2.85e-06 |
| 120 | ~6.48e-07 |
| 128 | <1e-6 (trending) |
| 150 | ~5.25e-07 (ranging) |

The error decays exponentially as EWM "forgets" the seeding difference. For ranging data
(seed=43), convergence to atol=1e-6 requires approximately 130-150 bars.

---

## Industry Standards Verification

| Platform/Library | Convention | Alpha |
|-----------------|------------|-------|
| Welles Wilder 1978 | alpha = 1/N | 1/14 ≈ 0.0714 |
| TradingView (Pine Script) | `ta.rma(tr, length)` = Wilder smoothing | 1/N |
| TA-Lib | Wilder smoothing | 1/N |
| MetaTrader 4/5 (Wilder mode) | alpha = 1/N | 1/N |
| pandas-ta `ta.atr()` | RMA (Wilder) + presma seed | 1/N |
| Our production code | `ewm(alpha=1/p)` + pandas min_periods seed | 1/N |

**Both implementations use the correct Wilder convention (alpha=1/N).** The difference is
only in how the first `p` bars are seeded — both converge to the same result after sufficient
warmup.

---

## Tolerance and Warmup Decision

Because the seeding differs, a longer warmup is required to achieve near-exact agreement:

- **warmup_bars=28** (2*p): max error ~1.69e-3 — suitable for atol=1e-3 only
- **warmup_bars=150**: max error ~5.25e-7 — achieves atol=1e-6 on both trending and ranging

**Decision: warmup_bars=150, atol=1e-6**

Using warmup_bars=150 is the correct choice for the reference test because:
1. It proves that both implementations converge to the same ATR values (the mathematical claim)
2. It uses atol=1e-6 which reflects near-exact floating-point agreement post-warmup
3. The 500-bar fixture provides 350 valid comparison bars after warmup

The warmup_bars=28 value in the plan was based on a theoretical assumption that both implementations
share the same seed. Empirical verification shows they do not; the larger warmup is required.

---

## Conclusion

**Our production ATR implementation is mathematically correct.**

- Uses `alpha = 1/N = 1/14` — identical to Wilder's original definition (Convention A)
- Uses `adjust=False` — matches Wilder's recursive smoothing, not adjustment-weighted EMA
- Converges to pandas-ta values at atol=1e-6 after warmup_bars=150
- The seeding difference (pandas ewm min_periods vs pandas-ta presma SMA seed) causes
  temporary divergence that decays exponentially and disappears by bar 150

The correctness claim is: **both implementations compute the same ATR given sufficient history.**
This is proven by the reference test at warmup_bars=150, atol=1e-6.
