# Adversarial Review (Round 2): Corrected H-B (`confirmed_reversal`) Construction

**Author:** AGY (dispatched headlessly via `agy -p --dangerously-skip-permissions`, 2026-09-08).
**Verification status:** The causality check, the density "subset" logic error, the
capitulation-volume reintroduction, and the sign-inversion issue were all independently
re-derived against the actual algorithm and confirmed real — see the main pre-reg doc's "AGY
review round 2" section. The horizon-mismatch and "this is just momentum" framing points were
not independently re-checked; treat as plausible, not confirmed.

**Document under review:** [`docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md`](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md)  
**Primary targets:**
- "H-B statistic, `confirmed_reversal_t`" ([L73–88](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L73-L88))
- "The two hypotheses" — H-B entry ([L41–48](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L41-L48))
- Related sections: AGY review correction trail ([L196–212](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L196-L212)), Track 1 testing specification ([L103–140](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L103-L140)), and Track 2 coverage handling ([L159–163](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L159-L163)).  
**Review Mode:** Strictly read-only adversarial design review. No files modified.

---

## Executive Summary

While replacing [`swing_volume_confirmation`](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py#L4653-L4658) with [`bars_since_low_fast`](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py#L3719-L3721) / [`bars_since_high_fast`](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py#L3713-L3715) successfully solves the lookahead and wrong-leg defect caught in Round 1, **the reinstated H-B construction is mathematically unsound, built on a severe misunderstanding of rolling-extreme dynamics, and completely mischaracterized in sample density.**

Specifically:
1. **The "Subset" Fallacy & Massive Sample Density Explosion:** The doc asserts that $H_B$ *"fires on a subset of that (requires $k \ge 1$, i.e. excludes the extreme bar itself)"* ([L160](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L160)). $k \ge 1$ is the **complement** of $k = 0$, not a subset. Since extreme bars ($k=0$) represent 26–30% of bars ([L289–291](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L289-L291)), **$H_B$ evaluates on ~70–74% of all bars in the entire dataset (~18 million bars at 15m)**. $H_B$ is not an episodic reversal confirmation trigger; it is active almost continuously.
2. **The "Saturation" Myth & Phantom Drop-Out Legs:** [`_bars_since_rolling_extreme_series_full`](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py#L2633-L2660) does **not** saturate at 19. It tracks the rolling argmin/argmax. When an old extreme falls off the trailing 20-bar window, $k$ jumps non-monotonically backwards (e.g. from 19 to 8), arbitrarily designating an unexceptional consolidation bar from 8 bars ago as the "start of a reversal leg" and spuriously flipping reference legs without any price extreme occurring.
3. **Capitulation Volume Contamination Re-Introduced:** `mean(volume_z_{t-k..t})` includes bar $t-k$—the extreme bar itself. If a sell-off ends in a capitulation volume spike on bar $t-k$, that spike pollutes the bounce average for every subsequent bar, falsely labeling low-volume bounces as "volume-confirmed."
4. **Catastrophic Degrees-of-Freedom Inflation in BY-FDR:** Admitting every consecutive bar of an ongoing leg creates extreme serial correlation ($r > 0.95$ across consecutive bars). Feeding nominal $n \approx 100{,}000$ into [`ic_math.py::_p_values_from_ic`](file:///home/bg/dev/indicagent/src/intelligence/statistics/ic_math.py#L486-L500) ($df = n - 2$) inflates $t$-statistics by $2.5\times\text{ to }3.5\times$, invalidating the BY-FDR gate ([L118–121](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L118-L121)).
5. **Wick Inversion in `sign(close_t - close_{t-k})`:** Because $k_{low}$ is based on bar lows, an extreme hammer candle with a large lower wick that closes near its high will cause subsequent bounce bars to have $\text{close}_t < \text{close}_{t-k}$. The formula flips the sign to $-1$, falsely classifying a heavy-volume bounce off a low as a **bearish** signal.

---

## Detailed Item-by-Item Verification

### (1) Causality: Is the claim correct?
**Claim in Doc:** `k_low_t` and `k_high_t` are *"both already causal"* ([L74–75](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L74-L75)).

- **Source Audit:**  
  [`src/intelligence/feature_factory.py:L2633-2660`](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py#L2633-L2660) implements `_bars_since_rolling_extreme_series_full`:
  ```python
  2647:     dq: deque[int] = deque()
  2648:     for i in range(n):
  2649:         v = values[i]
  2650:         if mode == "max":
  2651:             while dq and values[dq[-1]] <= v:
  2652:                 dq.pop()
  ...
  2656:         dq.append(i)
  2657:         while dq[0] <= i - window:
  2658:             dq.popleft()
  2659:         out[i] = float(i - dq[0])
  ```
  - For bar $i$, the loop reads only `values[i]` (which are `highs[i]` or `lows[i]`, [L3713–3720](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py#L3713-L3720)).
  - It maintains a monotonic deque of past indices up to $i$ and pops indices older than $i - \text{window}$.
  - The calculation never peeks forward to $i+1$.
  - At bar $t$, `close_t`, `close_{t-k}` ($k \ge 1 \implies t-k < t$), and `volume_z_{t-k..t}` use only historical data through bar $t$.
  - Under Invariant 1, target returns (`return_fast`) execute open-to-open from `open[t+1]` to `open[t+2]`.
- **Verdict:** **VERIFIED CORRECT.** There is zero lookahead. The causality claim holds strictly.

---

### (2) Saturation at Window-Minus-1: Does it bound the leg span as assumed?
**Claim in Doc:** `bars_since_low_fast` and `bars_since_high_fast` *"both saturate at `dist_window_fast − 1 = 19`, so the leg span below is always bounded"* ([L75](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L75)), described as a *"rolling-window 'bars since the extreme' counter, saturating at `dist_window_fast − 1 = 19`"* ([L204](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L204)).

- **Code vs. Math Reality:**  
  1. **Bounding:** Because `dq[0] > i - window`, $i - dq[0] \le \text{window} - 1 = 19$. The maximum value of $k$ is indeed bounded by 19.
  2. **The "Saturation" Error:**  
     The author confused [`_bars_since_rolling_extreme_series_full`](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py#L2633-L2660) with [`_bars_since_event_series_full`](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py#L2663-L2680).  
     - In `_bars_since_event_series_full` ([L2666–2667](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py#L2666-L2667)), if no event occurred inside the trailing window, the output latches/saturates at `window - 1`.
     - In `_bars_since_rolling_extreme_series_full`, the function tracks the index of the rolling $\min$ or $\max$ in a sliding window of prices $[t - 19 .. t]$. **It does not saturate.**
  3. **The Consequence (Phantom Legs from Drop-Out):**  
     Suppose at bar $t$, the rolling low was at $t-19$, so $k_{low} = 19$.  
     At bar $t+1$, bar $t-19$ rolls out of the 20-bar window (`dq.popleft()`, [L2658](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py#L2658)).  
     The new minimum in the window $[(t+1)-19 .. t+1]$ is whatever bar had the lowest low in that interval. Suppose that bar was at $t-7$.  
     Then at bar $t+1$, $k_{low}$ **abruptly jumps from 19 down to 8**, even though bar $t+1$ was not a low, and no new low occurred anywhere near $t+1$!
  4. **Spurious Reference-Leg Flipping:**  
     Suppose at bar $t$, $k_{high} = 12$ and $k_{low} = 19$. Since $k_{high} < k_{low}$, the reference leg is the high ($k=12$).  
     At bar $t+1$, price does not make a new high or low. $k_{high}$ advances to 13. But the old low rolls out, causing $k_{low}$ to jump to 8.  
     Now $k_{low} = 8 < k_{high} = 13$.  
     **The algorithm abruptly flips the reference leg from High to Low!** It begins treating bar $t-7$ (an unexceptional interior bar that was never a 20-bar low when formed) as the "extreme anchor" of a new reversal leg!
- **Verdict:** **FACTUALLY AND MECHANICALLY FLAWED.** While $k \le 19$ holds, the series does not "saturate." Rolling window drop-outs induce non-monotonic jumps in $k$, manufacturing phantom legs anchored to interior non-extreme bars.

---

### (3) Tie-Break Rule & $k \ge 1$ Requirement: Density Blunder & Double Counting
**Claim in Doc:** *"if equal (tie, including the `k=0` outside-bar case), excluded... require `k >= 1` (there must be an actual leg, not just the extreme bar itself — `k=0` is H-A's domain, not H-B's)"* ([L78–81](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L78-L81)). In Track 2, the doc claims: *"H-A fires on 26-30% of bars... H-B fires on a subset of that (requires `k >= 1`, i.e. excludes the extreme bar itself)"* ([L159–161](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L159-L161)).

- **Fatal Density Fallacy ("Subset" Error):**
  - The author states that $H_B$ fires on a "subset" of $H_A$'s 26–30% event bars because it requires $k \ge 1$.
  - This is an elementary set-theory error:
    - $H_A$ requires $k = 0$ (the extreme bar itself).
    - $H_B$ requires $k = \min(k_{low}, k_{high}) \ge 1$.
    - $k \ge 1$ is the **complement** of $k = 0$, not a subset!
  - In any 20-bar window, an extreme occurs on 26–30% of bars. On the remaining **70–74% of all bars in history**, neither a new high nor a new low occurred on that bar. On all of those bars, $k_{low} \ge 1$ AND $k_{high} \ge 1$.
  - Except for rare exact ties ($k_{low} == k_{high}$, which occur $<1\%$ of the time), **every single non-extreme bar has $k \ge 1$ and $k_{low} \ne k_{high}$**.
  - **Result:** $H_B$ is active on **~70–74% of all bars in the entire database** (~18 million bars at 15m).
  - The doc's repeated assertions that $H_B$ is an "episodic trade trigger" ([L163](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L163)) and that an explicit design is needed for the "majority of bars with no active event" ([L161–162](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L161-L162)) are completely divorced from the math of the spec. $H_A$ (~28%) and $H_B$ (~71%) together cover **~99% of all market bars**.
- **Double Counting / Cascading Multi-Bar Legs:**
  - The spec does not require $k = 1$ (the first bar of a reversal); it requires $k \ge 1$.
  - When a bounce lasts 10 bars without making a new 20-bar high, **all 10 consecutive bars are admitted into the $H_B$ panel**:
    - Bar 1: $k=1$, span $[t-1 .. t]$
    - Bar 2: $k=2$, span $[t-2 .. t]$
    - $\dots$
    - Bar 10: $k=10$, span $[t-10 .. t]$
  - These are not 10 independent reversal events; they are 10 overlapping evaluations of the same expanding leg.
- **Outside Bar Exclusion Cascades:**
  - If bar $t-m$ is an outside bar (both a 20-bar high and low), then for all subsequent bars until a new extreme is printed, $k_{low} = k_{high} = m$.
  - Because ties are excluded, an outside bar creates a dead zone where all subsequent bars (up to 19 bars) are excluded from $H_B$, regardless of subsequent price action.
- **Verdict:** **FATAL SPECIFICATION FLAW.** The author fundamentally misunderstood the event density of $k \ge 1$. $H_B$ is not a subset of $H_A$; it floods the panel with ~70% of all historical bars, double-counting every step of every leg.

---

### (4) Leg-Level Volume Statistic: Is `mean(volume_z_{t-k..t})` sound?
**Claim in Doc:** `mean(volume_z_{t-k..t})` is *"the signed mean of the persisted `volume_z` column over the leg span"* ([L82–83](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L82-L83)).

- **Flaw 4.1: Capitulation Volume Contamination (Re-creating Round 1's Bug):**
  - Notice the lower bound: $t-k$.
  - Bar $t-k$ is the **extreme bar itself** (the selling climax low or buying blow-off high).
  - The stated economic hypothesis for $H_B$ is: *"heavy volume on the leg moving AWAY from a recent extreme confirms the reversal is real"* ([L41–42](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L41-L42)).
  - The leg moving *away* from the extreme consists of bars $t-k+1 \dots t$.
  - By including $t-k$, if panic selling caused a massive volume spike at the low ($volume\_z_{t-k} = +4.5$), and the subsequent bounce at $t$ ($k=1$) occurred on dying volume ($volume\_z_t = -1.5$), the mean volume is:
    $$\text{mean} = \frac{4.5 - 1.5}{2} = +1.5$$
  - The pre-registration reads this capitulation dump into the low and falsely scores it as a **heavy-volume confirmed bounce**! This is the exact conceptual bug Round 1 flagged on `swing_volume_confirmation` ([`round1:L111–114`](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg-agy-review-round1.md#L111-L114)), now reintroduced in $H_B$'s indexing.
- **Flaw 4.2: Severe Serial Correlation & Degrees-of-Freedom Inflation:**
  - For consecutive bars in an ongoing leg, the window $[t-k .. t]$ and $[t+1 - (k+1) .. t+1]$ overlap by $k$ bars.
  - The serial correlation of `confirmed_reversal` across adjacent bars within legs is $> 0.95$.
  - In Track 1 ([L118–121](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L118-L121)), symbol significance for BY-FDR is computed via [`ic_math.py::_p_values_from_ic`](file:///home/bg/dev/indicagent/src/intelligence/statistics/ic_math.py#L486-L500):
    ```python
    497:     df = n - 2
    498:     t_stat = ic_vector * np.sqrt(df / np.maximum(1 - ic_vector**2, 1e-10))
    499:     return 2.0 * (1.0 - t_dist.cdf(np.abs(t_stat), df=df))
    ```
  - When $n$ is ~70% of all bars ($n \approx 75{,}000$ to $100{,}000$ bars per symbol), setting $df = n - 2$ assumes every bar is an independent sample.
  - Because of extreme autocorrelation across consecutive $t$, the effective sample size $n_{eff}$ is $5\times\text{ to }10\times$ smaller than $n$.
  - As a result, the standard errors are artificially compressed by $\sqrt{n / n_{eff}} \approx 2.5\times\text{ to }3.2\times$, producing artificially massive $t$-statistics and near-zero $p$-values. The 10% BY-FDR gate (Criterion 4, [L134](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L134)) will be spuriously cleared by autocorrelation alone.
- **Flaw 4.3: Variance Inhomogeneity Across $k$ Distorts Spearman Ranks:**
  - The variance of `mean(volume_z)` over $k+1$ bars scales roughly as $\frac{1}{k+1} \operatorname{Var}(volume\_z)$.
  - When $k=1$, the standard deviation is large; when $k=19$, the standard deviation is compressed by $\approx \sqrt{20/2} \approx 3.16\times$.
  - In a global Spearman ranking across time or symbols, observations with $k=1$ and $k=2$ will dominate the extreme top and bottom quantiles, while mature legs ($k \ge 10$) will be compressed into the middle quantiles. $H_B$ will effectively measure only 1-to-2 bar micro-momentum rather than leg-level reversal confirmation.
- **Flaw 4.4: Date-Shift Null and Overnight Crossings:**
  - A 20-bar leg on 15m spans 5 hours. It routinely crosses overnight boundaries (e.g. from 2:30 PM Day 1 to 10:30 AM Day 2).
  - The date-shift null ([L115–117](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L115-L117)) shifts dense scores against returns by whole calendar dates. When a feature computed across Day 1 and Day 2 is shifted by $K$ dates against Day $2+K$'s returns, it tests an arbitrary pairing of overnight-straddling features with shifted return vectors.
- **Verdict:** **FATAL STATISTICAL DEFECT.** `mean(volume_z_{t-k..t})` re-introduces the capitulation-volume error by including bar $t-k$, inflates BY-FDR degrees of freedom by $5\times\text{ to }10\times$ through autocorrelation, and distorts rank distributions via $k$-dependent variance.

---

### (5) Sign Convention: `sign(close_t - close_{t-k})`
**Claim in Doc:** `confirmed_reversal_t = sign(close_t − close_{t−k}) × mean(volume_z_{t−k .. t})` ([L82](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L82)), where *"Positive = up-leg off a low with above-average volume (bullish-confirming) or down-leg off a high with above-average volume, signed consistently with return (bearish-confirming, i.e. negative here)"* ([L85–87](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L85-L87)).

- **Sloppy Prose Drafting (Same as Round 1):**
  - Line 85 begins: *"Positive = up-leg off a low... or down-leg off a high... (bearish-confirming, i.e. negative here)"*.
  - Just as in Round 1 for $H_A$, stating "Positive = A or B (where B is negative)" is syntactically contradictory. The intent was clearly: Bullish confirmation is positive; Bearish confirmation is negative.
- **Fatal Disconnect from Extreme Type (The Wick Inversion Bug):**
  - Look at the formula:
    $$\text{confirmed\_reversal}_t = \text{sign}(\text{close}_t - \text{close}_{t-k}) \times \text{mean}(\text{volume\_z}_{t-k..t})$$
  - Notice what is missing: **The extreme type ($k_{low}$ vs $k_{high}$) is never used to sign the statistic!**
  - The sign is determined **solely** by `sign(close_t - close_{t-k})`.
  - Now consider what happens on real candlestick wicks:
    - $k_{low}$ is defined on bar **lows** (`lows` array, [L3720](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py#L3720)).
    - Suppose bar $t-k$ prints a hammer candle: $\text{low} = 100$, $\text{open} = 107$, $\text{close} = 106$. The 20-bar low is 100.
    - At bar $t$ ($k=1$), price stabilizes and advances from the low: $\text{low} = 103$, $\text{high} = 105.5$, $\text{close} = 105$.
    - Price has bounced 5 points off the low! $k_{low} = 1 < k_{high} = 15$.
    - But what is $\text{close}_t - \text{close}_{t-k}$?
      $$\text{close}_t - \text{close}_{t-k} = 105 - 106 = \mathbf{-1}$$
    - The sign is **negative** ($\mathbf{-1}$)!
    - If volume is heavy on the bounce ($\text{mean}(volume\_z) = +2.0$), the formula calculates:
      $$\text{confirmed\_reversal}_t = (-1) \times (+2.0) = \mathbf{-2.0} \quad (\text{BEARISH!})$$
    - A textbook bullish bounce off a low on heavy volume is assigned a **strongly negative, bearish score** simply because the low bar had a hammer wick!
    - Mirror case: On a shooting star high (high = 100, close = 95), a subsequent pullback bar closing at 96 has $\text{sign} = +1$, scoring a heavy-volume pullback from a high as **strongly positive (BULLISH)**!
- **Degeneracy at Flat Closes:**
  - If $\text{close}_t == \text{close}_{t-k}$, $\text{sign} = 0$, completely discarding the volume signal.
- **Verdict:** **FATAL ECONOMIC INVERSION BUG.** By signing the statistic with $\text{close}_t - \text{close}_{t-k}$ instead of conditioning on the extreme type ($+1$ if $k_{low} < k_{high}$ else $-1$), large-wick reversal candles invert the economic sign, generating bearish signals on bullish hammer bounces and vice versa.

---

### (6) Additional Flaws

#### Flaw 6.1: Horizon Mismatch (Multi-bar Leg Feature vs. 1-bar Forward Return)
- In Track 1 ([L103–106](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L103-L106)), the primary gated target is `return_fast` (1-bar, 15m forward return).
- `confirmed_reversal_t` is evaluated over a leg of length $k \in [1, 19]$ bars (up to 5 hours of trading).
- If a leg has already been underway for 15 bars with heavy volume, testing whether it predicts return on bar 16 is testing **leg exhaustion / continuation of an extended trend**, not whether the reversal was confirmed.
- $k=1$ (a nascent 15m bounce) and $k=18$ (an old, mature 4.5-hour trend) are pooled into the exact same panel and correlated against the exact same 1-bar return.

#### Flaw 6.2: $H_B$ is Not a Reversal Test; It is Plain-Vanilla Momentum Across 70% of Market Data
- Because $H_B$ evaluates on ~71% of all bars, and its formula reduces to $\text{sign}(\Delta \text{close}) \times \text{volume}$, the statistic is not testing reversal confirmation from extremes at all.
- Any bar in market history has a local 20-bar min or max. Whichever is closer ($k$) is treated as the anchor.
- $H_B$ is simply testing: *"Does a $k$-bar price move accompanied by above-average volume continue for 1 more bar?"*
- This is a standard price-volume momentum factor. Testing it under the guise of an "extreme-volume reversal pre-registration" misrepresents what is being measured.

#### Flaw 6.3: Implementation Mismatch in `market_data_ohlcv_tradeable` Join
- Lines 52–53 specify: *"joins `market_data_ohlcv_tradeable` (by `symbol`/`timeframe`/`timestamp`) for raw `close`"*.
- In `feature_vectors` ([`src/intelligence/schemas.py:L1836-1838`](file:///home/bg/dev/indicagent/src/intelligence/schemas.py#L1836-L1838)), the columns are `tf` and `bar_ts`. In `market_data_ohlcv_tradeable` ([`migrations/228_market_data_ohlcv_tradeable_view.sql:L26`](file:///home/bg/dev/indicagent/production/migrations/228_market_data_ohlcv_tradeable_view.sql#L26)), they are `timeframe` and `timestamp`.
- More critically: How is `close_{t-k}` retrieved?
  - $k$ is an integer row offset in a contiguous array.
  - Joining on `timestamp - interval '15 minutes' * k` fails across overnight sessions, weekends, and holidays.
  - To retrieve `close_{t-k}`, the join cannot be a simple SQL timestamp join; it requires pulling the dense close array per symbol and doing array indexing in Python. The doc fails to specify this, leaving an unworkable SQL specification.

---

## Summary Matrix of Findings

| Item | Focus Area | Status | Critical Impact / Line Numbers |
|---|---|---|---|
| **(1)** | Causality of `bars_since_*` | **VERIFIED CORRECT** | Purely causal in `_bars_since_rolling_extreme_series_full` ([L2633–2660](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py#L2633-L2660)); no lookahead. |
| **(2)** | Saturation at Window-1 | **FACTUALLY WRONG** | Does not saturate ([L75, L204](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L75)). Window drop-out causes $k$ to jump backwards, creating phantom legs anchored to interior non-extreme bars. |
| **(3)** | Density & Tie-Breaks | **FATAL FALLACY** | $k \ge 1$ is NOT a subset of $H_A$ ([L160](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L160)); it is the complement (~71% of all bars). $H_B$ is active on ~18M bars, double-counting every bar of every leg. |
| **(4)** | Volume Statistic | **FATAL FLAWS** | 1) Includes bar $t-k$, re-introducing capitulation volume contamination ([L82](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L82)); 2) Severe serial correlation ($r > 0.95$) inflates BY-FDR degrees of freedom by $5\times\text{--}10\times$ ([L118–121](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L118-L121)); 3) $k$-dependent variance distortion in Spearman IC. |
| **(5)** | Sign Convention | **FATAL INVERSION** | Signs by $\text{close}_t - \text{close}_{t-k}$ instead of extreme identity ([L82–85](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L82-L85)). Hammer wicks invert the economic sign, turning bullish bounces into bearish signals. |
| **(6)** | Architecture & Scope | **MULTIPLE DEFECTS** | 1) Multi-bar leg vs 1-bar forward return horizon mismatch ([L104](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L104)); 2) Re-labels generic price-volume momentum as a "reversal"; 3) `close_{t-k}` timestamp joins fail across calendar boundaries ([L52–54](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L52-L54)). |

---

## Verdict & Recommendation

**The corrected H-B construction CANNOT be run in its current specification.**

While $H_A$ is well-posed, $H_B$ must either be **dropped entirely** from this pre-registration (leaving a clean, focused pre-registration for the leading divergence hypothesis $H_A$), or **redesigned from the ground up**:

1. **If dropped:** Drop $H_B$ completely. $H_A$ (`extreme_volume_divergence_t`) is a well-defined, sparse, episodic leading indicator that is ready to run once the corpus recompute clears.
2. **If retained:** $H_B$ requires a strict event definition:
   - **Event trigger:** Lock evaluation to a single confirmation bar (e.g. exactly $k = 1$ or $k = 2$), rather than $k \ge 1$, to prevent density explosion and serial double-counting.
   - **Leg volume bounds:** Exclude bar $t-k$ from the volume average: compute `mean(volume_z_{t-k+1 .. t})` so capitulation volume does not pollute the bounce leg.
   - **Directional sign:** Sign by extreme type ($+1$ if $k_{low} < k_{high}$ else $-1$), or require price to exceed the extreme bar's extreme ($\text{close}_t > \text{high}_{t-k}$ for lows) rather than comparing closes.
   - **Drop-out filter:** Require that at bar $t-k$, `bars_since_*` was actually $0$ when formed, eliminating phantom drop-out legs.

[exited with code 0]
