# AGY adversarial review — Pre-registration 2 (alpha_score residual single-security @ 15m)

**Reviewed:** 2026-09-03, pre-run, second invocation of the same prompt (first invocation's
output was truncated at finding 4; both runs' findings adjudicated in the program doc's
Amendment 1 — run-1 findings 4-11 overlap run-2 findings 3-12).
**Reviewer:** AGY (cross-AI), file-pointing prompt, --dangerously-skip-permissions.
**Outcome:** Amendment 1 adopted (findings 1,2 fatal; 4,5,6,8,9,10 adopted; 3,7,11,12
partially adopted; pseudo-OOS split, master-grid reindex, median demeaning rejected).

### Adversarial Review: Pre-Registration 2 (`alpha_score` Residual Single-Security Diagnostic @ 15m)

Reviewed files:
- [2026-09-02-personal-scale-edge-determination-plan.md](file:///home/bg/dev/indicagent/docs/plans/2026-09-02-personal-scale-edge-determination-plan.md#L510-L605) (Section: *Pre-registration 2 — alpha_score residual single-security diagnostic @ 15m*)
- [alpha_score_residual_diagnostic_15m.py](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_residual_diagnostic_15m.py)
- [alpha_score_single_security_diagnostic_15m.py](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_single_security_diagnostic_15m.py)
- [`_circular_block_bootstrap_ic`](file:///home/bg/dev/indicagent/src/intelligence/statistics/ic_math.py#L207-L325) and [`_circular_shift_null`](file:///home/bg/dev/indicagent/src/intelligence/statistics/ic_math.py#L180-L200) in [ic_math.py](file:///home/bg/dev/indicagent/src/intelligence/statistics/ic_math.py)

---

### Finding 1: Conflation of Cross-Sectional and Time-Series Covariance in the Pooled Global-Rank Spearman
- **Severity**: **HIGH** (Fatal Conceptual & Statistical Flaw)
- **Mechanism**:
  The pre-registered research mandate is strictly single-security: *"does residual_t predict THAT symbol's own forward return — single-security, no cross-sectional ranking, no short leg"*. Yet the primary gated statistic is defined as the *pooled Spearman IC across all 14.76M (symbol, bar) pairs, ranked globally over the whole panel*.
  
  Algebraically, per-bar demeaning enforces $\sum_{i=1}^{N_t} r_{i,t} = 0$, but leaves the within-bar cross-sectional covariance $\sum_{i=1}^{N_t} r_{i,t} y_{i,t}$ completely unperturbed. When calculating sample covariance across the pooled panel:
  $$\widehat{\text{Cov}}_{\text{pooled}}(r, y) = \frac{1}{NT}\sum_{t=1}^T \sum_{i=1}^{N_t} r_{i,t} y_{i,t} = \frac{1}{T}\sum_{t=1}^T \left( \frac{1}{N_t} \sum_{i=1}^{N_t} r_{i,t} y_{i,t} \right) = \mathbb{E}_t \left[ \text{Cov}_{\text{CS}}(r_t, y_t) \right]$$
  The pooled covariance across all $(i, t)$ pairs is mathematically identical to the *mean cross-sectional covariance*. Global ranking monotonically preserves this cross-sectional order. 
  
  The prior diagnostic ([alpha_score_residual_diagnostic_15m.py](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_residual_diagnostic_15m.py)) already proved that the cross-sectional rank IC is positive and statistically significant ($\text{mean\_ic} = 0.01202, ci\_lower = 0.00363, p = 0.0000$). Consequently, **the pooled global Spearman IC will pick up this cross-sectional relative-value signal directly**. A signal with exactly zero single-security time-series predictive power for all 231 symbols will still yield a positive, statistically significant pooled Spearman IC. This statistic does not test the single-security hypothesis; it re-tests the portfolio decile-spread under pooled notation.
- **Concrete Fix**:
  Demote or eliminate pooled global-rank Spearman from the primary gating criteria. Gate instead on genuine single-security metrics:
  1. The distribution of within-symbol time-series Spearman ICs (e.g., median or trimmed mean of the 231 per-symbol ICs must have a bootstrap $ci\_lower > 0$).
  2. A minimum qualifying fraction of individual symbols (e.g., $\ge 15\%$ of symbols must individually pass a two-sided test at $\alpha=0.05$ after FDR adjustment), directly honoring the single-security standard set in [alpha_score_single_security_diagnostic_15m.py](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_single_security_diagnostic_15m.py#L113-L120).

---

### Finding 2: Within-Symbol Circular-Shift Null Scrambles Contemporaneous Structure and Guarantees a Spurious PASS
- **Severity**: **HIGH** (Fatal Null Calibration Flaw)
- **Mechanism**:
  Gated PASS Rule 2 requires `RESIDUAL pooled shuffled-null p < 0.05`, where the null is constructed via [`_circular_shift_null`](file:///home/bg/dev/indicagent/src/intelligence/statistics/ic_math.py#L180-L200) by drawing an independent random offset $k_i \in [1, T_i - 1]$ for each symbol $i \in \{1, \dots, 231\}$.
  
  Because each symbol is rolled by a different offset, the alignment of symbols at bar $t$ is destroyed: Symbol A's return at bar $t$ is paired with its residual from bar $t - k_A$, while Symbol B's return at bar $t$ is paired with its residual from bar $t - k_B$. This **completely destroys the contemporaneous cross-sectional correlation** across symbols at every bar $t$.
  
  Under this null, the expected pooled correlation drops to zero. But as established in Finding 1, the observed panel has an expected pooled correlation of $\sim 0.012$ driven by real contemporaneous cross-sectional alpha. The test is therefore comparing a statistic containing cross-sectional signal against a null distribution where cross-sectional structure was selectively obliterated. The observed statistic will beat the null on virtually every iteration ($p \approx 1/(N_{\text{null}}+1) \approx 0.001$). The test is a strawman: PASS is mathematically guaranteed regardless of whether single-security predictability exists.
- **Concrete Fix**:
  If a pooled null distribution is retained, the circular shift must be **panel-synchronous**: draw a single random offset $k \in [1, T-1]$ per replicate and roll all 231 symbols simultaneously by the exact same $k$ bars. This preserves the cross-sectional covariance across symbols at each bar while breaking the temporal lag alignment between $t$ and $t+1$. 
  
  Even better: test null $p$-values strictly within each symbol's own series (where [`_circular_shift_null`](file:///home/bg/dev/indicagent/src/intelligence/statistics/ic_math.py#L180-L200) is mathematically valid) and evaluate the family of 231 $p$-values.

---

### Finding 3: In-Sample Double-Dipping Framed as "Fresh Data"
- **Severity**: **HIGH** (Methodological Validity & Governance Risk)
- **Mechanism**:
  The plan justifies abandoning the out-of-sample (OOS) window (`bar_ts >= 2025-12-24`) in favor of the full in-sample (IS) panel (`bar_ts < 2025-12-24`, 2006–2025) by asserting that the IS panel is *"fresh relative to todo 277's selection, which was measured on the OOS window — testing there would double-dip the window the hypothesis was found on"*.
  
  This reasoning inverts fundamental statistical protocol. `alpha_score` is a composite indicator whose feature definitions, weights, and regimes were fitted, tuned, and selected on the **2006–2025 IS panel**. Evaluating the residual of `alpha_score` on the very 20-year corpus that birthed it is in-sample backtesting, not validation on "fresh" data. Any residual predictability in the IS panel may simply be in-sample overfit that survived per-bar demeaning. 
- **Concrete Fix**:
  Do not classify the IS panel as "fresh holdout data". If the true OOS window must be preserved virgin for a future gate, split the historical data into a pseudo-OOS block (e.g., fit/train on 2006–2019; run this residual diagnostic on 2020–2025), or run a rolling temporal cross-validation. Explicitly label the current test as an *In-Sample Diagnostic Hurdle*, not an out-of-sample edge determination.

---

### Finding 4: Large-Sample Fallacy ($N = 14.76\text{M}$) With Zero Effect-Size Floor (`ci_lower > 0`)
- **Severity**: **MEDIUM-HIGH** (Spurious PASS Risk)
- **Mechanism**:
  Gated PASS Rule 1 requires: `RESIDUAL pooled Spearman day-clustered bootstrap ci_lower > 0`.
  With $N = 14,757,726$ rows across $\sim 5,000$ calendar days, the standard error of the pooled Spearman IC is $\approx 1/\sqrt{N} \approx 0.00026$. Even after accounting for day clustering ($\sim 5,000$ day clusters), the standard error of the cluster mean is $O(10^{-3})$.
  
  At this scale, a completely negligible correlation of $\text{IC} = 0.0010$ (which explains $0.0001\%$ of variance and cannot survive a single 15m bid-ask spread of 1–2 bps) will yield a $t$-statistic $> 3.5$ and a confidence interval strictly above 0 ($ci\_lower \approx 0.0004 > 0$). Testing against a point null of zero ($\text{IC} > 0$) rather than an economically viable effect-size hurdle turns high statistical power into a pathology where microscopic noise artifacts pass the gate.
- **Concrete Fix**:
  Add an explicit, economically motivated effect-size floor to PASS Rule 1:
  $$\text{RESIDUAL pooled Spearman } ci\_lower \ge 0.010 \quad (\text{or } \ge 0.015)$$
  A diagnostic that cannot clear the friction hurdle of 15m execution costs (turnover $\times$ bid-ask spread) should fail immediately, regardless of its $p$-value.

---

### Finding 5: Scalar Circular Shifts Scramble the 15m Intraday Diurnal Volatility Cycle
- **Severity**: **MEDIUM-HIGH** (Spurious Null Distortion)
- **Mechanism**:
  [`_circular_shift_null`](file:///home/bg/dev/indicagent/src/intelligence/statistics/ic_math.py#L180-L200) executes `offset = int(rng.integers(1, n)); return np.roll(Y, offset)`.
  At a 15m timeframe, returns and volatilities follow a pronounced U-shaped diurnal curve: the market open (9:30 AM, 26 bars per regular day) and market close (3:45 PM) have variance orders of magnitude higher than the midday lull.
  
  When $Y$ is circularly shifted by an arbitrary scalar offset $k \in [1, n-1]$ that is not a multiple of 26:
  - High-volatility open returns are systematically paired with low-volatility midday residuals.
  - Return variance becomes heteroskedastically decoupled from the feature's intraday profile.
  - The circular boundary condition (`np.roll`) wraps 2025 returns directly into 2006 residuals across a 20-year regime gulf.
  
  This destroys the joint time-of-day distribution that real execution operates within, producing an invalid null distribution.
- **Concrete Fix**:
  Constrain the circular shift offset to integer multiples of the daily cycle:
  $$\text{offset} = 26 \times k, \quad k \in [1, \lfloor n/26 \rfloor - 1]$$
  This shifts entire calendar days relative to each other while preserving the exact 15m time-of-day slot alignment.

---

### Finding 6: Decoupling the Gating Rule from the Per-Symbol Family Creates a False-Pass Loophole
- **Severity**: **MEDIUM-HIGH** (Governance & Metric Incoherence)
- **Mechanism**:
  Pre-registration 2 includes the 231-symbol family test ([alpha_score_single_security_diagnostic_15m.py](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_single_security_diagnostic_15m.py) methodology), but classifies it as *"reported, ungated"* (line 565). The only criteria that govern PASS/FAIL are the pooled metrics.
  
  This creates an unacceptable loophole:
  If **0 out of 231 symbols** show a statistically significant positive residual IC under per-symbol block-bootstrap testing (or if the result repeats the 2026-08-08 diagnostic where only 1/80 qualified and 3 were significantly negative), the script **will still output PASS** as long as the pooled global Spearman clears zero. Advancing a strategy to a new `gate_id` as a "single-security construction" when zero individual symbols show statistically significant single-security alpha directly violates the stated goal of the research.
- **Concrete Fix**:
  Bind the PASS verdict to the per-symbol family. Mandate that at least $X\%$ (e.g., $\ge 15\%$, $\ge 35$ symbols) must reject the null with positive IC at FDR $\alpha=0.05$, AND the number of significantly negative symbols must not exceed the expected false discovery count ($231 \times 0.05 / 2 \approx 6$).

---

### Finding 7: Violation of Benjamini-Hochberg Assumptions by Structural Negative Dependence
- **Severity**: **MEDIUM** (Statistical Validity)
- **Mechanism**:
  The plan specifies Benjamini-Hochberg FDR ($\alpha=0.05$) across the 231 per-symbol tests.
  The BH procedure guarantees FDR control only under independent test statistics or Positive Regression Dependency on Subsets (PRDS).
  
  However, the signal under test is explicitly constructed as:
  $$r_{i,t} = s_{i,t} - \frac{1}{N_t}\sum_{j=1}^{N_t} s_{j,t} \implies \sum_{i=1}^{N_t} r_{i,t} \equiv 0$$
  By mathematical construction, the residuals are **negatively cross-sectionally dependent** across symbols at every single bar. When test statistics exhibit arbitrary or negative cross-dependence, standard BH-FDR is known to become anticonservative, rejecting null hypotheses at a true FDR significantly higher than $\alpha=0.05$.
- **Concrete Fix**:
  Replace standard BH-FDR with the Benjamini-Yekutieli (BY, 2001) procedure, which guarantees FDR control under arbitrary dependence by scaling the threshold by $\sum_{m=1}^M 1/m$ ($\approx \ln(231) + 0.577 \approx 6.02$). Alternatively, compute empirical family-wise error or FDR control using a Romano-Wolf step-down permutation procedure that resamples time bars synchronously across all symbols.

---

### Finding 8: Day-Clustered Bootstrap Ignores Multi-Day Autocorrelation and Volatility Clustering
- **Severity**: **MEDIUM** (Anticonservative Confidence Intervals)
- **Mechanism**:
  The pooled bootstrap resamples calendar dates independently with replacement.
  While day clustering accounts for intraday 15m autocorrelation and cross-sectional correlation within a date, it explicitly assumes independence *across* dates.
  
  In reality, equity volatility, macroeconomic regimes, and alpha factor drawdowns cluster across multiple consecutive days and weeks (long-memory / ARCH effects). Resampling single calendar dates at random destroys this multi-day persistence, leading to artificially narrow bootstrap distributions for the pooled correlation and underestimating standard errors.
- **Concrete Fix**:
  Resample blocks of calendar days (e.g., circular block bootstrap over dates with a block size of 5 to 10 consecutive trading days), analogous to the within-symbol [`_circular_block_bootstrap_ic`](file:///home/bg/dev/indicagent/src/intelligence/statistics/ic_math.py#L207-L325) discipline, rather than drawing independent single dates.

---

### Finding 9: Implementation Trap: Memory Exhaustion via Single-Batch Fetch and Dict Accumulation
- **Severity**: **HIGH** (Execution / OOM Failure)
- **Mechanism**:
  The previous diagnostic scripts fetched all rows into memory at once using `cur.fetchall()` and unpacked them into nested Python dictionary-of-lists structures (`by_symbol`, `raw_by_bar`).
  
  At 14,757,726 rows with 5 columns:
  - A single `cur.fetchall()` will buffer $\sim 15\text{M}$ Python tuples, consuming $\approx 3.5\text{–}5.0\text{ GB}$ of RAM in psycopg2.
  - Converting these tuples into `dict[str, list[float]]` (over 83,903 bars or 231 symbols) instantiates tens of millions of Python float and string objects, adding another $6\text{–}10\text{ GB}$ of heap allocations and triggering catastrophic garbage-collection latency or Linux OOM-killer termination.
- **Concrete Fix**:
  1. Stream database rows using a server-side cursor (`conn.cursor(name="...")` with `itersize=200_000`) or read directly into Apache Arrow / Polars memory-mapped frames.
  2. Avoid Python dictionaries of lists completely. Ingest directly into contiguous, pre-allocated NumPy 1D arrays: `bar_ts_int64`, `symbol_id_int16`, `alpha_score_f32`, `return_mid_f32`. Compute per-bar means using `np.bincount` or Polars group-by expressions.

---

### Finding 10: Implementation Trap: 14.76M-Row Re-Ranking Compute Bottleneck ($B=2000, N_{\text{null}}=1000$)
- **Severity**: **HIGH** (Computational Feasibility)
- **Mechanism**:
  Pre-registration 2 specifies:
  - 2,000 day-clustered bootstrap replicates of pooled Spearman, re-ranking the resampled subset every iteration.
  - 1,000 circular-shift null replicates of pooled Spearman, re-ranking the shifted panel.
  
  Ranking a 14.76M-element float array in NumPy (`np.argsort(np.argsort(x))` or `scipy.stats.rankdata`) takes $\approx 1.5\text{–}2.5\text{ seconds}$ on modern hardware.
  - Bootstrap: $2,000 \times 2 \text{ ranks} \times 2.0\text{s} = 8,000\text{ seconds} \approx 2.22\text{ hours}$.
  - Null replicates: $1,000 \times 1 \text{ rank} \times 2.0\text{s} = 2,000\text{ seconds} \approx 0.56\text{ hours}$.
  Total execution time exceeds **2.8 hours** of single-threaded compute solely spent in sorting routines.
  
  If the script attempts to parallelize via `ThreadPoolExecutor` or `ProcessPoolExecutor`, spinning up 16 workers holding 14.76M-element arrays ($\approx 118\text{ MB}$ per array $\times$ multiple buffers) will consume tens of gigabytes, saturate memory bus bandwidth, and thrash CPU L3 caches.
- **Concrete Fix**:
  If the primary test is restructured around the 231 per-symbol series (Finding 1), each symbol has only $\approx 64,000$ bars. Sorting 64k elements takes $< 1.5\text{ ms}$. Computing 2,000 replicates for 231 symbols takes $\approx 231 \times 3.0\text{s} \approx 11\text{ minutes}$, fits entirely within CPU L2/L3 cache, and parallelizes cleanly across symbols with zero memory pressure.

---

### Finding 11: Ragged Time Series and Gaps Corrupt the Circular Rolling Mechanic
- **Severity**: **MEDIUM** (Data Integrity & Signal Distortion)
- **Mechanism**:
  The 231 symbols do not share a uniform, contiguous time grid:
  - Step (2) of panel construction drops bars with $< 5$ symbols present.
  - Newer ETFs (launched between 2010 and 2021) have no rows from 2006 to their inception.
  - Illiquid symbols have missing intraday bars (as noted in prior diagnostics: FXA has 52.5% and SDOG has 82.8% of maximum row count).
  
  Executing `np.roll` directly on an array of filtered, non-contiguous rows shifts observations across arbitrary temporal gaps (e.g., shifting across weekends, holidays, or a 5-year pre-inception void as if it were a 15-minute step). The serial autocorrelation structure that [`_circular_shift_null`](file:///home/bg/dev/indicagent/src/intelligence/statistics/ic_math.py#L180-L200) was chosen to preserve is corrupted.
- **Concrete Fix**:
  Reindex every symbol's time series onto a master calendar grid of 15m regular market bars before computing circular shifts or block bootstraps. Fill unobserved bars with `NaN`, perform the block roll on the regular grid, and filter out `NaN` pairs only at the final correlation step.

---

### Finding 12: Unweighted Arithmetic Demeaning on Asymmetric Cross-Sections Distorts Early Years
- **Severity**: **LOW-MEDIUM** (Noise Injection)
- **Mechanism**:
  `residual_t` is defined as `alpha_score - per-bar mean`, with a minimum threshold of only 5 symbols per bar.
  In early years (2006–2008), when only a handful of symbols are present, a simple arithmetic mean has high sampling variance. An outlier score on a single volatile symbol will distort the mean, injecting noise into the residuals of all other symbols at that bar. In contrast, in 2024 (with 200+ symbols), the mean is highly stable.
  
  Pooling noisy residuals from sparse 2006 cross-sections with clean residuals from dense 2024 cross-sections introduces systematic heteroskedasticity over time. Furthermore, an arithmetic mean gives equal weight to micro-cap/illiquid ETFs and large-cap benchmark ETFs when defining the market-wide common component.
- **Concrete Fix**:
  1. Raise `min_symbols_per_bar` from 5 to at least 20 (or require symbols present to represent a minimum market-cap / liquidity coverage).
  2. Use a robust location estimator (e.g., median or Huber trimmed mean) rather than an unweighted arithmetic mean to prevent individual symbol anomalies from contaminating the common factor.

---

### Summary of Priority Actions Before Script Execution

| # | Vulnerability | Severity | Priority Fix |
|---|---|---|---|
| **1** | Pooled Spearman measures cross-sectional covariance, not single-security alpha | **HIGH** | Gate on median per-symbol IC and qualifying fraction; demote pooled Spearman. |
| **2** | Independent circular shift null destroys cross-sectional alignment, guaranteeing false PASS | **HIGH** | Use panel-synchronous shift across all symbols, or evaluate null strictly per-symbol. |
| **3** | IS panel (2006-2025) is the training set, not fresh holdout data | **HIGH** | Label as in-sample diagnostic; test on pseudo-OOS block (e.g. 2020–2025). |
| **4** | $N=14.76\text{M}$ allows untradable noise ($\text{IC} \sim 0.001$) to pass $ci\_lower > 0$ | **MED-HIGH** | Impose explicit economic hurdle: $ci\_lower \ge 0.010$. |
| **5** | Arbitrary scalar circular shift scrambles intraday 15m diurnal volatility curve | **MED-HIGH** | Restrict shift offsets to whole-day multiples ($26 \times k$ bars). |
| **6** | Gating rule decouples from per-symbol family | **MED-HIGH** | Require $\ge 15\%$ of symbols to qualify under per-symbol FDR test. |
| **7** | BH-FDR invalid under construction-induced negative cross-sectional dependence | **MEDIUM** | Replace with Benjamini-Yekutieli (BY) or Romano-Wolf step-down. |
| **8** | Day-clustered bootstrap ignores multi-day volatility/regime clustering | **MEDIUM** | Use block bootstrap over dates (5–10 day blocks). |
| **9** | Single-batch `cur.fetchall()` and Python dicts will OOM on 14.76M rows | **HIGH** | Stream via server-side cursor directly into columnar NumPy / Arrow buffers. |
| **10** | Re-ranking 14.76M rows $\times$ 3000 replicates will take $> 2.8$ hours or crash | **HIGH** | Shift primary compute to per-symbol arrays (64k rows each). |
| **11** | Gaps and ragged ETF histories corrupt circular roll | **MEDIUM** | Align on a uniform master timestamp grid before rolling. |
| **12** | Unweighted mean on sparse early bars ($\ge 5$ symbols) injects outlier noise | **LOW-MED** | Use median / Huber mean and raise `min_symbols_per_bar` to $\ge 20$. |
