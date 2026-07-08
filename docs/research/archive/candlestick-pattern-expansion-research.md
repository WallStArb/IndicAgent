# Candlestick Pattern Expansion Research

**Last Updated:** 2026-05-02

**Created:** 2026-03-03
**Status:** Research / Pre-implementation
**Related todo:** `.planning/todos/pending/2026-03-03-expand-i5-candlestickpatterns-and-i7-candlestickpatternsetup-with-additional-high-reliability-patterns.md`
**Target files:** `src/intelligence/patterns/candlestick_patterns.py`, `src/intelligence/trading/candlestick_pattern_setup.py`

---

## Current State

`CandlestickPatternsPlugin` (I5) detects 9 patterns using 2-bar lookback:

| Output Field | Type | Description | Reliability |
|---|---|---|---|
| `engulfing_bull` | 2-bar reversal | Prior bearish, current bullish body engulfs | High |
| `engulfing_bear` | 2-bar reversal | Prior bullish, current bearish body engulfs | High |
| `pin_bar_bull` | 1-bar reversal | Lower wick ≥ 2× body, upper wick ≤ body | Medium |
| `pin_bar_bear` | 1-bar reversal | Upper wick ≥ 2× body, lower wick ≤ body | Medium |
| `hammer_detected` | 1-bar reversal | Pin bar bull + near support (or no S/R data) | Medium-High |
| `shooting_star_detected` | 1-bar reversal | Pin bar bear + near resistance (or no S/R data) | Medium-High |
| `inside_bar` | 2-bar NR/coil | Current bar inside prior high/low | Low-Medium |
| `outside_bar` | 2-bar expansion | Current bar engulfs prior high/low | Medium |
| `doji_detected` | 1-bar indecision | Body < 10% of range | Low (context-dependent) |

`CandlestickPatternSetupPlugin` (I7, Phase 10) will consume 6 directional patterns from the above list:
`engulfing_bull`, `engulfing_bear`, `hammer_detected`, `shooting_star_detected`, `pin_bar_bull`, `pin_bar_bear`.

---

## Patterns to Evaluate for Expansion

### Tier 1 — High Priority (well-studied, liquid futures relevance, clear detection logic)

#### 1. Harami Bull / Harami Bear (2-bar)
**Signal:** Small current body entirely inside the prior candle's body. Reversal signal.
- **Harami Bull:** Prior bearish, current small bullish body inside prior body. Buyers stepping in but unsure.
- **Harami Bear:** Prior bullish, current small bearish body inside prior body. Sellers emerging.
- **Reliability:** Medium. More reliable with S/R confluence or regime context.
- **Vs. Inside Bar:** Inside bar uses high/low; harami uses body-to-body. Different signals. Both can coexist.
- **Futures note:** Works well in ranges; lower-value in strong trends (fade against momentum).
- **Detection:** `c_body_top < p_body_top and c_body_bot > p_body_bot` + directional color check.
- **Lookback:** 2 bars.
- **Output fields:** `harami_bull`, `harami_bear`
- **Suggested I7 base confidence:** 0.52 (requires external confirmation)

#### 2. Harami Cross (2-bar)
**Signal:** Prior bar has a real body; current bar is a doji inside the prior body.
- Stronger signal than regular Harami — doji represents maximum indecision.
- **Bullish Harami Cross:** Prior bearish, doji inside → stronger reversal signal than harami_bull.
- **Bearish Harami Cross:** Prior bullish, doji inside → stronger than harami_bear.
- **Detection:** Harami condition + `c_body / c_range < 0.10` (doji body test).
- **Lookback:** 2 bars.
- **Output fields:** `harami_cross_bull`, `harami_cross_bear`
- **Suggested I7 base confidence:** 0.58

#### 3. Dark Cloud Cover (2-bar)
**Signal:** Prior bullish bar, current bar opens above prior high but closes below the midpoint of the prior body. Bearish reversal.
- Classic 2-bar top reversal pattern. Very common at swing highs.
- **Detection:** `p_bullish AND c_o > p_h AND c_c < (p_o + p_c) / 2 AND c_bearish`
- **Lookback:** 2 bars.
- **Output field:** `dark_cloud_cover`
- **Suggested I7 base confidence:** 0.55
- **Futures note:** Gaps between open and prior high may be small in futures vs equities — the midpoint-penetration rule still makes this effective without requiring a true gap.

#### 4. Piercing Line (2-bar)
**Signal:** Prior bearish bar, current bar opens below prior low (or prior close) but closes above midpoint of prior body. Bullish reversal.
- Mirror of Dark Cloud Cover.
- **Detection:** `p_bearish AND c_o < p_l AND c_c > (p_o + p_c) / 2 AND c_bullish`
- **Lookback:** 2 bars.
- **Output field:** `piercing_line`
- **Suggested I7 base confidence:** 0.55
- **Futures note:** Same gap caveat as Dark Cloud Cover. Relax open-below-prior-low to open-below-prior-close if gap frequency is low.

#### 5. Three White Soldiers (3-bar)
**Signal:** Three consecutive long bullish bars, each opening within the prior body and closing near its high. Strong bullish continuation/reversal confirmation.
- Among the highest-reliability multi-bar patterns. Indicates sustained buying.
- **Detection:**
  - All three bars: close > open (bullish)
  - Each bar's open within prior body: `bar[i].open between bar[i-1].open and bar[i-1].close`
  - Each close above prior close
  - Each body > some minimum (e.g., 0.4 × range) to exclude doji-like weak bars
- **Lookback:** 3 bars (`min_lookback=3`).
- **Output field:** `three_white_soldiers`
- **Suggested I7 base confidence:** 0.72

#### 6. Three Black Crows (3-bar)
**Signal:** Three consecutive long bearish bars, each opening within the prior body and closing near its low. Mirror of Three White Soldiers.
- **Detection:** Mirror logic.
- **Lookback:** 3 bars.
- **Output field:** `three_black_crows`
- **Suggested I7 base confidence:** 0.72

#### 7. Morning Star (3-bar)
**Signal:** Three-bar bullish reversal. Long bearish bar → small body (star, any color) → long bullish bar closing into the first bar's body.
- Classic bottom-reversal structure after a downtrend.
- **Detection:**
  - Bar[-3]: long bearish body (`body > 0.5 × range`)
  - Bar[-2]: small body (`body < 0.3 × range`) — the "star"
  - Bar[-1]: bullish, closes above the midpoint of Bar[-3]'s body
- **Lookback:** 3 bars.
- **Output field:** `morning_star`
- **Suggested I7 base confidence:** 0.65

#### 8. Evening Star (3-bar)
**Signal:** Mirror of Morning Star. Three-bar bearish reversal at a swing top.
- **Detection:** Mirror logic.
- **Lookback:** 3 bars.
- **Output field:** `evening_star`
- **Suggested I7 base confidence:** 0.65

---

### Tier 2 — Medium Priority (valid patterns, slight complexity or lower futures applicability)

#### 9. Dragonfly Doji (1-bar)
**Signal:** Open ≈ close ≈ high, long lower wick. Very bullish at a bottom — buyers completely reclaimed all seller territory.
- **Detection:** `c_upper_wick < 0.05 × c_range AND c_lower_wick > 0.70 × c_range AND doji_detected`
- **Output field:** `dragonfly_doji`
- **Suggested I7 base confidence:** 0.62 (strong when near support)
- **Note:** Complements `hammer_detected`. Dragonfly is a specific shape; hammer requires proximity to support.

#### 10. Gravestone Doji (1-bar)
**Signal:** Open ≈ close ≈ low, long upper wick. Very bearish at a top.
- **Detection:** `c_lower_wick < 0.05 × c_range AND c_upper_wick > 0.70 × c_range AND doji_detected`
- **Output field:** `gravestone_doji`
- **Suggested I7 base confidence:** 0.62 (strong when near resistance)

#### 11. Marubozu Bull / Bear (1-bar)
**Signal:** Full-body candle with no (or minimal) wicks. Strong momentum — indicates one-sided auction.
- **Bull Marubozu:** `c_bullish AND c_lower_wick < 0.05 × c_range AND c_upper_wick < 0.05 × c_range`
- **Bear Marubozu:** same for bearish
- **Use in I7:** Could be used as a momentum continuation signal (not reversal).
- **Output fields:** `marubozu_bull`, `marubozu_bear`
- **Suggested I7 base confidence:** 0.58 (continuation context required)

#### 12. Tweezer Top / Tweezer Bottom (2-bar)
**Signal:** Two consecutive bars with equal (or very close) highs (top) or lows (bottom). Indicates failed test of a level.
- **Tweezer Top:** Two highs within 0.05% of each other, second bar bearish after first.
- **Tweezer Bottom:** Two lows within 0.05%, second bar bullish after first.
- **Note:** Overlaps with S/R concepts already in I3. Value is in detecting the specific 2-bar structure that *creates* the level.
- **Output fields:** `tweezer_top`, `tweezer_bottom`
- **Suggested I7 base confidence:** 0.52

#### 13. Three Inside Up / Three Inside Down (3-bar)
**Signal:** Confirmed Harami. The third bar confirms the Harami reversal signal.
- **Three Inside Up:** Bar[-3] bearish → Bar[-2] bullish inside bar[-3] body (harami_bull) → Bar[-1] bullish, closes above bar[-2].
- **Three Inside Down:** Mirror.
- **Value:** Harami alone is medium reliability; the third confirmation bar raises this to high.
- **Lookback:** 3 bars.
- **Output fields:** `three_inside_up`, `three_inside_down`
- **Suggested I7 base confidence:** 0.65

---

### Tier 3 — Lower Priority (complex, rare, or already covered by other I5/I6 signals)

#### 14. Abandoned Baby (3-bar)
**Signal:** Gap-isolated doji between two opposing body candles. Very rare in futures (small gaps). Extremely strong when it occurs.
- **Futures applicability:** Low — true gaps between sessions are rare in most futures. May not occur often enough to be worth implementing.
- **Verdict:** Defer. Consider only for equity contracts (ES/NQ) where session gaps can be larger.

#### 15. Rising Three Methods / Falling Three Methods (5-bar)
**Signal:** Three small retracement bars inside a long bar's range, followed by continuation. Continuation pattern.
- **Complexity:** High — 5-bar lookback, many conditions.
- **Verdict:** Defer. Low frequency, high implementation complexity.

#### 16. Kicker (2-bar)
**Signal:** Gap in opposite direction of prior bar, no price overlap. Very strong reversal.
- **Futures applicability:** Moderate — overnight gaps needed; rare in liquid futures.
- **Verdict:** Defer unless overnight gap detection is added to data pipeline.

---

## Doji Refinement: Current vs. Proposed

The current `doji_detected` is generic (body < 10% range). Propose splitting into subtypes:

| Field | Current | Proposed |
|---|---|---|
| `doji_detected` | body < 10% range | Keep as generic doji (unchanged) |
| `dragonfly_doji` | Not implemented | Upper wick < 5% range + lower wick > 70% range |
| `gravestone_doji` | Not implemented | Lower wick < 5% range + upper wick > 70% range |
| `long_legged_doji` | Not implemented | Both wicks > 35% range (currently covered by generic doji) |

Specific doji types are more actionable in I7 than generic doji.

---

## Impact on `min_lookback`

Currently `min_lookback = 2`. Adding 3-bar patterns requires bumping to **3**.

No 4+ bar patterns are recommended in Tier 1/2, so max lookback stays at 3.

```python
min_lookback: int = 3  # was 2; needed for 3-bar patterns (morning/evening star, soldiers/crows, three inside)
```

---

## Proposed `outputs` Expansion

Current (9): `engulfing_bull`, `engulfing_bear`, `pin_bar_bull`, `pin_bar_bear`, `hammer_detected`, `shooting_star_detected`, `inside_bar`, `outside_bar`, `doji_detected`

Tier 1 additions (10 new fields): `harami_bull`, `harami_bear`, `harami_cross_bull`, `harami_cross_bear`, `dark_cloud_cover`, `piercing_line`, `three_white_soldiers`, `three_black_crows`, `morning_star`, `evening_star`

Tier 2 additions (8 new fields): `dragonfly_doji`, `gravestone_doji`, `marubozu_bull`, `marubozu_bear`, `tweezer_top`, `tweezer_bottom`, `three_inside_up`, `three_inside_down`

Total with Tier 1+2: **27 fields** (up from 9)

---

## Proposed I7 Priority Stack (expanded)

From highest to lowest priority in `CandlestickPatternSetupPlugin`:

```
three_white_soldiers (0.72)
three_black_crows    (0.72)
morning_star         (0.65)
evening_star         (0.65)
three_inside_up      (0.65)
three_inside_down    (0.65)
dragonfly_doji       (0.62) — near support
gravestone_doji      (0.62) — near resistance
harami_cross_bull    (0.58)
harami_cross_bear    (0.58)
marubozu_bull        (0.58)  — continuation signal
marubozu_bear        (0.58)  — continuation signal
hammer_detected      (0.57)  — existing (self-confirming)
shooting_star        (0.57)  — existing (self-confirming)
engulfing_bull       (0.55)  — existing
engulfing_bear       (0.55)  — existing
dark_cloud_cover     (0.55)
piercing_line        (0.55)
harami_bull          (0.52)
harami_bear          (0.52)
tweezer_top          (0.52)
tweezer_bottom       (0.52)
pin_bar_bull         (0.50)  — existing (requires volume or S/R)
pin_bar_bear         (0.50)  — existing (requires volume or S/R)
inside_bar           (0.35)  — context signal only (not directional)
outside_bar          (0.40)  — volatility expansion context
doji_detected        (0.30)  — generic (only useful as filter/context)
```

---

## Futures-Specific Adaptations

### Gap Handling
True price gaps are rare in 24-hour futures. Patterns that traditionally require a gap (Dark Cloud Cover, Piercing Line, Morning/Evening Star) should:
- Use **open vs. prior close** comparison instead of strict gap requirement
- Alternative: relax gap condition to "open beyond prior bar's midpoint"
- Document clearly in code that the gap rule is adapted for futures

### Session Context Integration
Several patterns improve significantly when filtered by session:
- **Morning Star / Three White Soldiers** — more reliable at Asian/London session opens
- **Evening Star / Three Black Crows** — more reliable at US session close
- Future integration: pass `session_context` from I4 `SessionContext` plugin as a feature.

### Volume Confirmation
Three White Soldiers / Three Black Crows are more reliable when each successive bar has increasing volume. Consider an optional volume check using `volume_sma_20` already in I1.

---

## Implementation Sequence (Recommended)

**Phase A — 3-bar patterns first (highest signal quality):**
1. Three White Soldiers (`three_white_soldiers`)
2. Three Black Crows (`three_black_crows`)
3. Morning Star (`morning_star`)
4. Evening Star (`evening_star`)

**Phase B — 2-bar reversals:**
5. Harami Bull/Bear (`harami_bull`, `harami_bear`)
6. Harami Cross (`harami_cross_bull`, `harami_cross_bear`)
7. Dark Cloud Cover (`dark_cloud_cover`)
8. Piercing Line (`piercing_line`)

**Phase C — 1-bar refinements:**
9. Dragonfly Doji (`dragonfly_doji`)
10. Gravestone Doji (`gravestone_doji`)
11. Marubozu (`marubozu_bull`, `marubozu_bear`)

**Phase D — Confirmed reversals (3-bar composites):**
12. Three Inside Up/Down (`three_inside_up`, `three_inside_down`)
13. Tweezer Top/Bottom (`tweezer_top`, `tweezer_bottom`)

Total new I5 output fields: 18 (Tier 1+2, minus generic doji which stays)

---

## Open Questions

1. **Dark Cloud Cover / Piercing Line gap rule**: Relax to "open beyond prior midpoint" or "open beyond prior close"? Need to check frequency in ES 1m data.
2. **Three White Soldiers volume**: Should the implementation require increasing volume on each bar, or just flag the pattern and let I7 apply volume gating?
3. **Marubozu in I7**: This is a continuation pattern, not a reversal. Should it get its own setup type in `CandlestickPatternSetupPlugin`, or be used as a filter in other setups (e.g., strengthen MomentumBreakout)?
4. **Priority ordering conflict**: If `three_white_soldiers` fires on the same bar as `engulfing_bull`, the priority stack above picks three_white_soldiers. Is this always correct? Three soldiers is a 3-bar confirmation; engulfing is a specific 2-bar structure. They could coexist as separate signals.
5. **`inside_bar` and `outside_bar` in I7**: Currently not in the I7 setup's pattern list (Phase 10). Should they be added? `outside_bar` is a breakout/volatility signal; `inside_bar` is a coil. They'd need different logic than the reversal patterns.
