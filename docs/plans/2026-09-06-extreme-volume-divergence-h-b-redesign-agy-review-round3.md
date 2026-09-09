# Adversarial Review (Round 3): H-B (`confirmed_reversal`) Redesign Candidate

**Dispatched:** via `agy -p --dangerously-skip-permissions`, 2026-09-09; the tool's own output
self-identifies its author as "Antigravity" below.
**Verification status:** independently re-verified against source, not accepted on assertion:
the write-once anchor invariant (§1), the disjoint-averaging-window proof (§2), the
`volume_z`/`_fixed_window_zscore_series` diurnal-bias claim (finding 2 in the main doc's
addendum), and the `Panel.sync_shift_null_p` per-symbol-`m` claim (flaw 6.2) — the last two
filed as todo 372 given they reach beyond this document. The tie-anchor-leak finding (flaw
6.1) and the SQL-buffer finding were checked for internal logical consistency but not
separately re-derived from scratch the way the above four were.

**Author:** Antigravity (Adversarial System Review, 2026-09-09)  
**Document Under Review:** [`docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md`](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md) (including its Addendum, [L279–311](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L279-L311))  
**Context & Precedents:** 
- Round 1 Review: [`docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg-agy-review-round1.md`](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg-agy-review-round1.md)
- Round 2 Review: [`docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg-agy-review-round2.md`](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg-agy-review-round2.md)
- Main Pre-registration Draft: [`docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md`](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md)
- Source Implementation: [`src/intelligence/feature_factory.py`](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py) (`_bars_since_rolling_extreme_series_full`, `_fixed_window_zscore_series`)  
- Null Reference Script: [`scripts/analysis/alpha_score_residual_single_security_15m.py`](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_residual_single_security_15m.py)  

**Review Mode:** Strictly read-only adversarial design review. No files modified.

---

## Executive Verdict

**CONDITIONAL PASS WITH THREE MANDATORY AMENDMENTS.**

Fable's from-scratch redesign represents a massive structural improvement over the Round 2 construction. It genuinely eliminates four of the five fatal defects identified in Round 2:
1. **The density explosion is solved:** $E$ fires on an exact integer match ($k = K\_CONFIRM$), restricting density to a clean, sparse 6.9% of bars on SPY (27.1% leg survival), down from ~70% ([§2.1, L101–109](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L101-L109)).
2. **Anchor drift is structurally eliminated:** The forward scan stores `anchor_idx = i` strictly on write-once `== 0` events, never re-reading rolling-window argmin state ([§2.2, L110–120](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L110-L120)).
3. **Capitulation contamination is eliminated:** Averaging starts strictly at $a+1$, excluding bar $a$ ([§2.3, L121–126](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L121-L126)).
4. **Window overlap between legs is mathematically impossible:** Feature averaging windows $[a+1, a+K\_CONFIRM]$ are strictly disjoint across distinct legs ([§2.4, L127–139](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L127-L139)).

**However, the redesign introduces several critical vulnerabilities and unclosed degrees of freedom that must be formally resolved prior to execution:**
- **The "Confirmation" Category Substitution:** By dropping all price follow-through checks to avoid a SQL join ([L89–91, L211–221](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L89-L91)), the statistic does not measure whether price confirmed the reversal. Heavy volume during a tight breakdown consolidation hovering 2 cents above a low is misclassified as **strongly bullish** ($+3.0$).
- **The Diurnal Volume Smile Confounder:** `volume_z` is a rolling 20-bar z-score across overnight session boundaries with no time-of-day detrending. Morning gap-reversals (9:30–10:15 AM) will be scored as systematically "volume confirmed" purely because market opens trade at 3x–5x the volume of afternoon sessions.
- **Outside Bar (Tie) Anchor Leakage:** When an outside bar occurs at $a+1$ or $a+2$, it prints a new 20-bar extreme, yet the scan carries over anchor $a$ ([L49](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L49)), generating invalid confirmation events.
- **In-Sample Data Splicing & SQL Buffer Omission:** The warmup fix ([L303–306](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L303-L306)) skips the first 40 bars of the fetched series. If the SQL query clamps to `bar_ts >= '2007-03-23'`, it throws away 40 valid bars from 2007 while losing anchor state from March 22, 2007.

---

## Detailed Item-by-Item Verification

### (1) Forward-Scan Anchor Tracking & Anchor Drift

**Target:** Does the write-once forward-scan anchor tracking in Section 1.1 ([L34–55](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L34-L55)) genuinely eliminate the Round 2 anchor-drift bug against [`src/intelligence/feature_factory.py:L2633-2660`](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py#L2633-L2660)?

#### Algorithmic Audit
In [`feature_factory.py:L2633-2660`](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py#L2633-L2660):
```python
2648:     for i in range(n):
2649:         v = values[i]
2650:         if mode == "max":
2651:             while dq and values[dq[-1]] <= v:
2652:                 dq.pop()
2653:         else:  # "min"
2654:             while dq and values[dq[-1]] >= v:
2655:                 dq.pop()
2656:         dq.append(i)
2657:         while dq[0] <= i - window:
2658:             dq.popleft()
2659:         out[i] = float(i - dq[0])
```
By definition, `out[i] == 0.0` occurs if and only if `dq[0] == i`. Because `dq` pops all earlier values that are $\ge v$ (for min) or $\le v$ (for max), `out[i] == 0.0` guarantees that `values[i]` is less than or equal to (or greater than or equal to) every single bar in the trailing window `values[max(0, i - window + 1) : i + 1]`. 

Now trace Section 1.1 ([L44–51](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L44-L51)):
```python
for i in 0 .. n-1:
    if clean_low[i]:
        anchor_idx, anchor_type = i, 'low'
    elif clean_high[i]:
        anchor_idx, anchor_type = i, 'high'
    # tie[i] or neither: anchor unchanged, carries over
    anchor_idx_at[i]  = anchor_idx
    anchor_type_at[i] = anchor_type
```

1. **Write-once invariance:** `anchor_idx` is mutated in exactly two places: lines 46 and 48. Both are conditioned on `clean_low[i]` or `clean_high[i]`, which strictly require `bars_since_*[i] == 0`. It is physically impossible for `anchor_idx` to receive an index $j$ where `bars_since_*[j] != 0`.
2. **Elimination of runtime sliding-window subtraction:** In Round 2, the anchor was computed at bar $t$ as $t - k_t$, where $k_t$ was read from the live column. When a leg exceeded 19 bars without a new extreme, `dq.popleft()` evicted the true extreme, causing $k_t$ to jump from 19 down to 8. In Fable's forward scan, $k[i] = i - anchor\_idx\_at[i]$ strictly increments by $+1$ on every bar where no clean extreme occurs. It cannot jump backwards.
3. **Waterfall / Cascading extremes:** If a downtrend prints 4 consecutive lower lows ($i=10, 11, 12, 13$), `clean_low` fires on each bar. `anchor_idx` is rewritten on each bar ($10 \to 11 \to 12 \to 13$). The counter $k$ resets to 0 on each bar. The confirmation countdown $k=1, 2, 3$ begins **only after the final extreme of the cascade** ($i=13$). Bar $13$ is the genuine lowest low of the cluster.

**Verdict:** **VERIFIED ELIMINATED.** The forward-scan state machine completely severs the dependency on non-zero sliding-window values. Anchor drift onto interior non-extreme bars is mathematically impossible under this scan.

---

### (2) Disjoint Averaging Windows Across Legs

**Target:** Is the claim in Section 2 item 4 ([L127–139](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L127-L139)) that included legs' averaging windows `[a+1, a+K_CONFIRM]` cannot overlap between different legs actually correct?

#### Mathematical Proof
Let Leg 1 have anchor $a_1$. 
- Leg 1 enters $E$ if and only if $k[i] = K\_CONFIRM$ at bar $i_1 = a_1 + K\_CONFIRM$.
- By definition of the scan, for $i_1$ to enter $E$, no clean extreme could have fired on any bar in the interval $[a_1 + 1, a_1 + K\_CONFIRM]$. (If one had fired at bar $j$, `anchor_idx` would have reset to $j$, setting $k[j] = 0$, so $k[i_1]$ would be $i_1 - j < K\_CONFIRM$).
- Leg 1's averaging window is:
  $$W_1 = [a_1 + 1, a_1 + K\_CONFIRM]$$
  The rightmost bar in $W_1$ is $\max(W_1) = a_1 + K\_CONFIRM = i_1$.

Now, let $a_2$ be the anchor of the very next included leg (Leg 2) that reaches confirmation:
1. Because no clean extreme occurred in $[a_1 + 1, a_1 + K\_CONFIRM]$, the earliest bar at which $a_2$ could possibly occur is:
   $$a_2 \ge a_1 + K\_CONFIRM + 1$$
   *(Note: Bar $i_1 = a_1 + K\_CONFIRM$ cannot be an extreme, because if it were, $k[i_1]$ would be $0 \ne K\_CONFIRM$, excluding it from $E$.)*
2. Leg 2 enters $E$ at bar $i_2 = a_2 + K\_CONFIRM$.
3. Leg 2's averaging window is:
   $$W_2 = [a_2 + 1, a_2 + K\_CONFIRM]$$
4. The leftmost bar in $W_2$ is:
   $$\min(W_2) = a_2 + 1 \ge (a_1 + K\_CONFIRM + 1) + 1 = a_1 + K\_CONFIRM + 2$$
5. Comparing the bounds:
   $$\max(W_1) = a_1 + K\_CONFIRM < a_1 + K\_CONFIRM + 2 \le \min(W_2)$$
   $$\implies W_1 \cap W_2 = \emptyset$$

Between $W_1$ and $W_2$, there is a mandatory gap of **at least one bar** (specifically, bar $a_2$, the anchor of Leg 2, which is never included in any volume average). 

If any candidate leg starts between $a_1$ and $a_2$ but resets before reaching $K\_CONFIRM$, it contributes zero rows to $E$.

**Verdict:** **VERIFIED CORRECT.** Fable's proof is algebraically rigorous. No two rows in the panel can share any volume bar in their averaging windows.

> [!NOTE]
> While the *volume averaging windows* are strictly disjoint, forward return targets can still overlap under secondary horizons:
> - For `return_fast` (1-bar open-to-open: $i_1+1 \to i_1+2$), return spans are strictly disjoint since $i_2 \ge i_1 + 4$.
> - For `return_mid` (5-bar open-to-open: $i_1+1 \to i_1+6$), the forward return of Leg 1 spans into the confirmation window of Leg 2 when $i_2 = i_1 + 4$. This is acceptable because `return_mid` is explicitly locked as an ungated secondary robustness check ([L93–95](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L93-L95)).

---

### (3) Sign Convention & Economic Hypothesis Alignment

**Target:** Is the sign convention free of the Round 2 wick-inversion bug? Does dropping price-based confirmation ([L89–91, L211–221](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L89-L91)) undermine the claim that this measures "confirmation," or does it gut the hypothesis?

#### 1. Wick Inversion Verification
In Round 2, `confirmed_reversal` was signed by $\text{sign}(close_t - close_{t-k})$. On a hammer candle at a low ($low=100, close=106$), a bounce to $close_t = 105$ produced $105 - 106 = -1$, inverting a heavy-volume bounce into a bearish score.
In Fable's Section 1.3 ([L85–87](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L85-L87)):
$$\text{sign}[i] = +1 \text{ if anchor\_type\_at}[i] == \text{'low' else } -1$$
$$\text{confirmed\_reversal}[i] = \text{sign}[i] \times \text{leg\_volume}[i]$$
Because this touches neither `close` nor bar wicks, **the wick-inversion bug is 100% eliminated.**

#### 2. Does Dropping Price Confirmation Gut the Economic Hypothesis?
In the pre-registration doc ([L43–45](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L43-L45)), the stated economic hypothesis for $H_B$ is:
> *"heavy volume on the leg moving AWAY from a recent extreme confirms the reversal is real and already underway — a heavy-volume bounce off a low is bullish-confirming..."*

Look closely at what Fable's statistic requires:
1. $low_j > low_a$ for all $j \in [a+1, a+K\_CONFIRM]$. (Price did not print a lower low).
2. $high_j < \text{rolling\_max}$ for all $j \in [a+1, a+K\_CONFIRM]$. (Price did not print a fresh 20-bar high).
3. No tie (outside bar) occurred.

**Notice what is missing:** Price does NOT have to move AWAY from the extreme!
Consider the following market reality:
- **High-Volume Stall / Breakdown Consolidation:** 
  - Bar $a$: prints a low at $100.00$ and closes at $101.50$.
  - Bar $a+1$: dumps to $100.10$ on massive volume ($volume\_z = +2.5$).
  - Bar $a+2$: churns at $100.05$ on massive volume ($volume\_z = +3.0$).
  - Bar $a+3$: hovers at $100.02$ on massive volume ($volume\_z = +3.5$).
  - **What actually happened:** Sellers are aggressively slamming bids against the $100.00$ support level. This is a high-volume descending triangle breakdown pattern. Price made zero upward progress off the low.
  - **What Fable's statistic computes:** 
    $$\text{sign} = +1, \quad \text{leg\_volume} = +3.0 \implies \mathbf{\text{confirmed\_reversal} = +3.0 \quad (\text{STRONGLY BULLISH!})}$$
  - At bar $a+4$, the level breaks and price plunges. Forward return is sharply negative.

#### Verdict on the Trade-Off
Fable candidly admits this trade-off in Section 4 ([L211–221](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L211-L221)), claiming it was necessary to buy immunity from the wick-inversion bug. But examining lines 89–91 reveals the primary driver was avoiding an SQL join to `market_data_ohlcv_tradeable` (*"No close values, no market_data_ohlcv_tradeable join, anywhere in this construction... a real simplification"*).

**Does it gut the hypothesis?**
It does not render the math ill-posed, but **it alters the hypothesis under test.** 
$H_B$ is no longer testing *"volume-confirmed price reversal."* It is testing:
$$\text{"Signed volume magnitude in the immediate wake of an unbroken extreme."}$$
In high-volume absorption/breakdown setups, heavy volume at support is bearish continuation volume, not bullish reversal volume. Scoring this as bullish will introduce noise and dilution into the Spearman IC.
**Recommendation:** This trade-off is acceptable for a pure `feature_vectors`-only first pass, **provided the pre-registration text is explicitly revised** to state that $H_B$ tests *volume expansion conditional on non-violation of the extreme*, not price-directional confirmation.

---

### (4) Defensibility of $K\_CONFIRM = 3$ as Primary

**Target:** Is $K\_CONFIRM = 3$ (locked in the addendum with SPY/15m density 6.9%, survival 27.1%) a defensible choice?

#### Empirical Density Calibration
From the Addendum ([L288–292](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L288-L292)):
- $K = 1$: Density 11.3%, Leg Survival 43.9%
- $K = 2$: Density 8.5%, Leg Survival 33.1%
- $K = 3$: Density 6.9%, Leg Survival 27.1%
- $K = 5$: Density 5.2%, Leg Survival 20.2%

1. **Statistical Power & Sample Size:**
   - On SPY (130,632 bars at 15m), $6.9\%$ yields $\approx 9{,}013$ events.
   - Across the 231-symbol ETF universe (~25.3M bars at 15m), $6.9\%$ yields $\approx 1.74 \text{ million}$ events.
   - Per symbol, mean events $\approx 7{,}500$, crushing the `_MIN_BARS_PER_SYMBOL = 100` floor by $75\times$.
2. **Noise vs. Promptness Trade-Off:**
   - At $K = 1$, the volume metric is a single 15m bar (`mean(volume_z[a+1..a+1])`), which is highly noisy.
   - At $K = 3$, volume is averaged across 3 bars (45 minutes of trading), effectively smoothing single-bar execution noise.
3. **The Survivorship Conditioning:**
   - A survival rate of $27.1\%$ means **$72.9\%$ of all extremes are reset within 3 bars**.
   - In a trending regime, price cascades down: $low_1 \to low_2 \to low_3$. Each new low resets the anchor.
   - Conditioning on surviving 3 bars ensures that we only evaluate situations where the selling/buying climax has paused for at least 45 minutes.
4. **The Horizon Mismatch Tension:**
   - At bar $a+3$, the trade enters at `open[a+4]` and evaluates return to `open[a+5]`.
   - The test evaluates return **1 hour after the extreme low**.
   - On a 15-minute timeframe, mean-reverting bounces off 20-bar extremes often reach exhaustion within 3–5 bars. Testing bar 4-to-5 return risks catching the tail end of the bounce rather than the initiation.

**Verdict:** **DEFENSIBLE AS PRIMARY.** $K\_CONFIRM = 3$ is mathematically sound and statistically powered. The 72.9% drop-out is an inherent property of requiring multi-bar confirmation. Locking $K\_CONFIRM = 3$ as primary with $K \in \{1, 2, 5\}$ reported as ungated sensitivity checks follows house standards.

---

### (5) Warmup-Exclusion Fix & Subtler Contamination Modes

**Target:** Does the Addendum's fix (skip each symbol's first $2 \times dist\_window\_fast = 40$ bars, [L303–306](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L303-L306)) actually close the warmup gap, or is there a subtler version?

#### 1. Inception Warmup Audit
In [`feature_factory.py:L2633-2660`](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py#L2633-L2660), `_bars_since_rolling_extreme_series_full` expands its window from $1 \dots 20$ during bars $0 \dots 19$. In [`feature_factory.py:L1054`](file:///home/bg/dev/indicagent/src/intelligence/feature_factory.py#L1054), `_fixed_window_zscore_series` explicitly zeros out the first 19 bars (`z[:19] = 0.0`).
- By bar 20, both rolling windows have 20 bars of actual data.
- By bar 40 ($2 \times 20$), the entire initial 20-bar expanding-window transient has rolled out of the 20-bar deque.
- **For a symbol's very first listing bars, $2 \times dist\_window\_fast$ fully clears inception warmup.**

#### 2. Subtler Mode A: The SQL In-Sample Date Clamp Truncation (CRITICAL GAP)
Look at how the analysis script fetches data:
The pre-registration requires restricting analysis to the In-Sample window `bar_ts >= '2007-03-23' AND bar_ts < '2025-12-24'`.
- If the script queries Postgres with:
  ```sql
  SELECT ... FROM feature_vectors WHERE bar_ts >= '2007-03-23' AND bar_ts < '2025-12-24'
  ```
  Then for SPY (which has data back to 2006), row $i=0$ in the returned Python DataFrame is `2007-03-23 09:30:00`.
- In Postgres, SPY's `bars_since_low_fast` on `2007-03-23` was already clean (computed with 2006 data).
- **The Bug:** If the Python script naively executes `skip first 40 bars of the fetched dataframe`, it drops 40 perfectly valid bars from March/April 2007, while **initializing `anchor_idx = None` on March 23, 2007**!
- If an extreme was printed on March 22, 2007 at 3:45 PM, the script is blind to it because the SQL query clipped off March 22.
- **Mandatory Fix:** The SQL query must fetch a trailing buffer of at least 40 bars prior to `2007-03-23` (`WHERE bar_ts >= '2007-03-01'`) to warm up the forward scan's `anchor_idx`, and only filter rows where `bar_ts >= '2007-03-23'` when building the final `E` panel.

#### 3. Subtler Mode B: The Diurnal Overnight Gap (Recurring Daily Warmup)
There is a far subtler and more damaging "warmup" artifact that recurs **every single trading day**:
- There are 26 bars of 15m in a trading day (9:30 AM – 4:00 PM).
- `volume_z` is computed via `_fixed_window_zscore_series(volumes, 20)` on a flat 1D array across session boundaries.
- At 9:30 AM, 9:45 AM, and 10:00 AM, the 20-bar trailing window includes 17–19 bars from the **previous afternoon's low-volume session** (11:45 AM – 4:00 PM).
- Because market opens trade at 3x–5x the volume of afternoon sessions (the standard U-shaped intraday volume smile), `volume_z` at 9:45 AM, 10:00 AM, and 10:15 AM is **systematically inflated to $+2.0$ to $+4.0$ purely due to time-of-day**.
- Overnight news regularly causes opening gaps, printing a 20-bar high or low at 9:30 AM (`bars_since_* == 0`).
- The confirmation window for a 9:30 AM extreme is bars 9:45, 10:00, and 10:15 AM.
- **Consequence:** Morning reversals are virtually guaranteed to receive massive positive `leg_volume` scores, while midday/afternoon reversals receive low/negative scores, purely driven by diurnal volume seasonality. The 40-bar symbol-level warmup skip does nothing to catch this.

---

### (6) New Researcher Degrees of Freedom, Implementation Gaps & Statistical Flaws

#### Flaw 6.1: Outside Bar (Tie) Anchor Carry-Over Leaks Invalid Legs
In Section 1.1 ([L37–49](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L37-L49)):
```python
tie[i]      = low_ext[i] AND high_ext[i]
clean_low[i]  = low_ext[i]  AND NOT tie[i]
clean_high[i] = high_ext[i] AND NOT tie[i]
...
# tie[i] or neither: anchor unchanged, carries over
```
Suppose Bar $a$ is a clean low ($low=100.00$).
At Bar $a+1$, an outside bar occurs: $low = 99.50$ and $high = 104.00$.
- Bar $a+1$ made a **lower low** ($low\_ext = True$) AND a **higher high** ($high\_ext = True$).
- Under Fable's pseudocode, `tie[a+1]` is True.
- Line 49 says: **anchor unchanged, carries over!**
- At Bar $a+2$, normal bar.
- At Bar $a+3$, $k[a+3] = 3 = K\_CONFIRM$. Bar $a+3$ enters $E$ anchored to Bar $a$!
- **The Defect:** Bar $a+1$ violated the low of Bar $a$ by printing a lower low! Yet the algorithm ignores it because it was an outside bar, and falsely claims that Bar $a$ was an unviolated low that bounced for 3 bars!
- Furthermore, Section 5 item 3 ([L251–254](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L251-L254)) explicitly leaves "anchor unchanged" vs "tie hard-resets" as an open comparison. **This is an undeclared researcher degree of freedom.**
- **Required Fix:** A tie must hard-reset `anchor_idx = None`. If a bar prints a new rolling low and high simultaneously, the prior leg is broken and no valid single-sided anchor exists.

#### Flaw 6.2: Scrambled Block Permutation in `Panel.sync_shift_null_p`
Section 3 ([L164–169](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L164-L169)) claims that `Panel.sync_shift_null_p` can be reused directly on the filtered sparse panel $E$ to provide a panel-synchronous date-shift null that "preserves within-date structure."
Examining [`alpha_score_residual_single_security_15m.py:L215-223`](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_residual_single_security_15m.py#L215-L223):
```python
216:             for s in self.family:
217:                 starts, counts, sl = self.sym_blocks[s]
218:                 m = len(starts)
219:                 perm = (np.arange(m) + k % m) % m
...
222:                 idx = _concat_ranges(starts[perm], counts[perm])
223:                 vals.append(_spearman(sc[idx], self.returns[sl]))
```
1. `m = len(starts)` is the number of active event dates for symbol $s$. Since different symbols have different active dates in sparse event sets, $m$ varies across symbols.
2. `perm = (np.arange(m) + k % m) % m` shifts each symbol by $k \pmod{m_s}$. **Because $m_s$ varies, symbols are shifted by different relative calendar offsets!** It is NOT panel-synchronous across calendar dates.
3. Because `counts[perm]` varies across dates (Date A had 1 event, Date B had 3 events), concatenating `starts[perm]` with `counts[perm]` shifts the row boundaries relative to `self.returns[sl]`. If Date A had 1 return and Date B had 3 scores, the 3 scores from Date B spill over into Date A and Date A+1. Within-date structure is destroyed.
4. **Required Fix:** In the sparse panel, the null must shift dates synchronously on the global calendar dates `self.calendar`, matching date-to-date, or perform a synchronous circular date shift before slicing.

#### Flaw 6.3: Unclosed Degree of Freedom on Horizon Gating
In Section 1.3 ([L93–95](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L93-L95)), Fable locks `return_fast` as primary/gated and `return_mid` as ungated/reported. However, in Section 5 item 7 ([L273–277](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L273-L277)), Fable introduces an unclosed qualitative check:
> *"check that the sign and approximate size of the Track 1 point estimate are qualitatively stable across K_CONFIRM ∈ {1, 2, 3, 5} ... not as a second gated chance to pass"*

The pre-registration must clearly specify what happens if $K=3$ passes all 5 criteria, but $K=1$ or $K=2$ has a negative point estimate. Does the candidate PASS or FAIL? Without a clear rule, a researcher can dismiss negative results at $K=1$ as "noise" or use them retroactively to invalidate a failure.

---

## Comparison Matrix: Round 2 vs. Round 3 Redesign

| Design Aspect | Round 2 Flawed Follow-Up | Round 3 Redesign (Fable) | Round 3 Audit Status |
|---|---|---|---|
| **Sample Density** | $k \ge 1$ (complement of $k=0$); fired on ~71% of all bars (~18M bars) | $k == K\_CONFIRM$ ($K=3$); fires on 6.9% of bars | **VERIFIED FIXED** ([§2.1](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L101-L109)) |
| **Anchor Tracking** | Re-read runtime `bars_since_*` column; window drop-out created phantom legs | Forward-scan state machine; writes `anchor_idx = i` strictly on `== 0` | **VERIFIED FIXED** ([§2.2](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L110-L120)) |
| **Capitulation Volume** | Included bar $t-k$ in average; polluted bounce with dump volume | Window starts at $a+1$; bar $a$ strictly excluded | **VERIFIED FIXED** ([§2.3](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L121-L126)) |
| **Window Overlap** | Sliding $k \ge 1$ windows overlapped across consecutive bars ($r > 0.95$) | Disjoint averaging windows $[a+1, a+K]$ across distinct legs | **VERIFIED FIXED** ([§2.4](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L127-L139)) |
| **Sign Convention** | $\text{sign}(close_t - close_{t-k})$; inverted on candle wicks | Signed by extreme identity ($+1$ for low, $-1$ for high) | **VERIFIED FIXED** ([§2.5](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L140-L145)) |
| **Price Confirmation** | Compared $close_t$ to $close_{t-k}$ | Completely dropped; no price check | **THEORETICALLY DILUTED** (measures volume, not reversal) |
| **Outside Bar Handling** | Undefined tie-breaking | Carried over unchanged | **FLAW IDENTIFIED** (leaks broken legs, [L49](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L49)) |
| **Warmup Exclusion** | Omitted | Excludes first $2 \times dist\_window\_fast$ bars | **PARTIAL** (omits SQL buffer & diurnal volume smile) |

---

## Required Mandatory Amendments Before Execution

Before the analysis script for $H_B$ is written or merged into [`docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md`](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md), the following four amendments must be locked:

1. **Tie Hard-Reset Rule ([L49](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md#L49)):**
   Change line 49 from:
   ```python
   # tie[i] or neither: anchor unchanged, carries over
   ```
   to:
   ```python
   if tie[i]:
       anchor_idx, anchor_type = None, None  # hard reset; outside bar breaks the leg
   ```
   An outside bar prints both a rolling low and rolling high; it invalidates the integrity of any preceding single-sided anchor.

2. **SQL Fetch Trailing Buffer for In-Sample Clamp:**
   The analysis script's data loader must NOT use `WHERE bar_ts >= '2007-03-23'`. It must fetch data starting 50 bars prior:
   ```sql
   WHERE bar_ts >= '2007-03-01' AND bar_ts < '2025-12-24'
   ```
   The forward scan runs over the buffered series to establish true anchor state on `2007-03-23`. The warmup exclusion ($40$ bars) applies to the symbol's true inception in `feature_vectors`, not the sliced query start. Only bars with `bar_ts >= '2007-03-23'` are admitted into the evaluation panel $E$.

3. **Time-of-Day Sub-Analysis (Diurnal Control):**
   Because `volume_z` is not intraday-standardized and morning volume is structurally elevated, add a mandatory **reported (ungated) morning vs. afternoon breakdown**:
   - Morning sub-panel: events occurring between 9:45 AM and 11:30 AM.
   - Afternoon sub-panel: events occurring between 11:45 AM and 3:45 PM.
   This guarantees that an overall PASS is not an artifact of the market-open volume smile.

4. **Hypothesis Scope Re-Alignment in Pre-Reg Text:**
   Amend the description of $H_B$ in [`docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md:L43-45`](file:///home/bg/dev/indicagent/docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md#L43-L45) to explicitly acknowledge that the statistic measures *volume expansion during a persistent pause ($K=3$) following an extreme*, without requiring price follow-through away from the anchor.

---
*End of Round 3 Adversarial Review. Conducted strictly read-only; no files were modified.*

[exited with code 0]
