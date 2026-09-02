## Executive Verdict

**The design as written is NOT sound and cannot be approved in its current form.** 

While the pre-registration commendably locks several parameters (random seeds, quintile counts, 3-subperiod splits, and cost-band sensitivities), it contains **three critical statistical flaws**, **a fatal lookahead conditioning trap**, and **direct contradictions with [`OOS-EVAL-PROTOCOL.md`](file:///home/bg/dev/indicagent/docs/plans/OOS-EVAL-PROTOCOL.md)**:

1. **The OOS "consistency check" is statistically vacuous**: under the null hypothesis of zero edge, a noise signal has a **~40% to 45% probability of passing** the pre-registered OOS drop-tolerance rule purely by chance.
2. **Eligibility conditions on the future**: requiring `complete_mid=true` at rebalance time filters out stocks that delist or halt during the holding period before quintiles are formed, introducing survivorship and lookahead bias.
3. **Silent elimination of Gate 2 (attribution / static tilt)**: the pre-registration quietly drops the static-tilt regression gate required by [`OOS-EVAL-PROTOCOL.md`](file:///home/bg/dev/indicagent/docs/plans/OOS-EVAL-PROTOCOL.md) and Phase 167, leaving the strategy completely unprotected against harvesting market/volatility beta under the guise of an alpha spread (the exact failure mode that killed Phase 148).
4. **Implementation blockers & bootstrap mismatch**: `ic_math.py` does not contain a 1D mean bootstrap, and applying an APR daily block size of 10 to a 5-day non-overlapping series creates an unjustified 50-day (10-rebalance) block structure.

The specific findings are ranked below by severity, most severe first.

---

## Ranked Findings

### Severity 1: Critical & Fatal Flaws (Invalidates Gating or Injects False Edges)

#### 1. The Pre-Registered OOS Interpretation Rule Has a ~40% False Positive Rate Under the Null
- **Text** ([`2026-09-02-personal-scale-edge-determination-plan.md:L332-337`](file:///home/bg/dev/indicagent/docs/plans/2026-09-02-personal-scale-edge-determination-plan.md#L332-L337)):
  > *"the gate look is a consistency check, not a standalone significance test — 32 rebalances cannot power one (expected t ≈ 0.8 even at annual Sharpe 1). OOS is consistent if the OOS mean per-rebalance return has the same sign as IS AND is ≥ 0.5× the IS mean (`alpha.validation.oos_significant_drop_fraction`)..."*
- **Adversarial Analysis & Math**:
  The doc correctly identifies that $N=32$ non-overlapping rebalances cannot power a standard two-sample or $t>1.96$ significance test. However, the proposed remedy—declaring OOS "consistent" if $\bar{X}_{\text{OOS}} \ge 0.5 \times \bar{X}_{\text{IS}}$—is disastrously uncalibrated under the null hypothesis $H_0: \mu = 0$.
  - At an annualized LS volatility of 16% ([`personal_cost_hurdle.py:L57`](file:///home/bg/dev/indicagent/scripts/analysis/personal_cost_hurdle.py#L57)), per-rebalance volatility is $\sigma_{5d} = 16\% / \sqrt{50} \approx 2.26\%$.
  - Across $N=32$ rebalances, the standard error of the OOS mean is:
    $$\text{SE}(\bar{X}_{\text{OOS}}) = \frac{2.26\%}{\sqrt{32}} \approx 0.40\% \quad (40\text{ bps})$$
  - If the in-sample mean return is $\approx 15\text{–}20\text{ bps}$ per rebalance (consistent with the 0c measured IC of 0.03–0.05), the threshold $0.5 \times \bar{X}_{\text{IS}}$ is only **$7.5\text{–}10\text{ bps}$** ($0.00075\text{–}0.0010$).
  - Under the null hypothesis ($\mu = 0$):
    $$Z = \frac{0.0010 - 0}{0.0040} = +0.25 \implies P(Z \ge +0.25) \approx \mathbf{40.1\%}$$
  - **Verdict**: A pure noise construction that snooped its way through IS has roughly a **40% probability of passing the OOS gate by pure luck**. This is not a gate; it is a coin flip masquerading as pre-registration discipline.
  - Furthermore, the text fails to specify whether this comparison uses **gross or net returns** (and at which cost band). If gross is used, OOS net return could be negative while passing the gate.
- **Required Fix**:
  Do not discard 80% of OOS data with a single non-overlapping phase. Either:
  1. Test all 5 interleaved rebalance phases over OOS (yielding $5 \times 32 = 160$ rebalance evaluations), restoring power so a true bootstrap CI lower bound > 0 or pooled test can be conducted; OR
  2. If keeping a single non-overlapping series, state honestly that OOS cannot validate the strategy and require walk-forward fold tests across IS, while enforcing that the OOS look requires at least a one-sided $t > 1.645$ or net positive return across all 3 cost bands.

---

#### 2. Conditioning on Future Returns: `complete_mid=true` in Portfolio Eligibility
- **Text** ([`2026-09-02-personal-scale-edge-determination-plan.md:L277-278`](file:///home/bg/dev/indicagent/docs/plans/2026-09-02-personal-scale-edge-determination-plan.md#L277-L278)):
  > *"- Eligibility per rebalance day: non-null signal AND complete eligible return; ≥ 20 eligible symbols or the day is skipped and counted in the report.*
  > *- Return (Invariant 1): `forward_returns.return_mid` ... `complete_mid=true` only."*
- **Adversarial Analysis**:
  In [`forward_return_writer.py:L253`](file:///home/bg/dev/indicagent/services/forward_return_writer.py#L253), `complete_mid = (open_mid IS NOT NULL)` where `open_mid = LEAD(open, 6)`.
  If an asset undergoes a delisting, trading halt, liquidity freeze, or corporate dissolution during the 5 days following day $T$, `open_mid` is NULL and `complete_mid` is `False`.
  - By requiring `complete eligible return` as a condition for **eligibility on day $T$ before quintiles are formed**, the backtest algorithm peeks 5 days into the future to eliminate any asset that fails to survive or print an open price at $T+6$.
  - This purges trading disasters and delisting drops from the quintiles before portfolio formation. In live trading, a trader on day $T$ cannot condition portfolio entry on whether the symbol will successfully trade on day $T+6$.
- **Required Fix**:
  Eligibility on day $T$ must depend **strictly on information known at $T$**: non-null signal, active instrument status, and tradeable price at $T$. If an eligible asset in the portfolio subsequently fails to trade at $T+6$, the return calculation must handle it via an explicit settlement rule (e.g. exit at last trade, zero, or cashout price), never by retroactively dropping the asset from day $T$'s universe.

---

#### 3. Complete Omission of Gate 2 (Attribution Honesty / Static-Tilt Regression)
- **Text** ([`2026-09-02-personal-scale-edge-determination-plan.md:L328-330`](file:///home/bg/dev/indicagent/docs/plans/2026-09-02-personal-scale-edge-determination-plan.md#L328-L330)):
  > *"Reported, never gated: per-symbol Spearman IC family with BH-FDR (`ic_math.apply_bh_fdr`, alpha=0.05) as attribution... per-subperiod CIs; skipped-day count."*
- **Adversarial Analysis & Contradiction**:
  - The program doc claims earlier ([`L9-11`](file:///home/bg/dev/indicagent/docs/plans/2026-09-02-personal-scale-edge-determination-plan.md#L9-L11), [`L134-136`](file:///home/bg/dev/indicagent/docs/plans/2026-09-02-personal-scale-edge-determination-plan.md#L134-L136)) that *"gate STRUCTURE stays rigid (null-arm, BH-FDR, pre-registration, OOS)... Gate structure unchanged"*.
  - In [`OOS-EVAL-PROTOCOL.md:L100-103`](file:///home/bg/dev/indicagent/docs/plans/OOS-EVAL-PROTOCOL.md#L100-L103) and [`services/cross_sectional_spread_tracker.py:L1589-1600`](file:///home/bg/dev/indicagent/services/cross_sectional_spread_tracker.py#L1589-L1600), construction-level gating requires **both Gate 1 (net Sharpe) AND Gate 2 (attribution honesty via static-tilt regression)**.
  - Phase 148 was killed *specifically* because Gate 2 failed: what looked like real alpha in Gate 1 was actually a disguised common market factor.
  - `range_pct_fast` (20-bar range / close) is an explicit volatility/beta proxy: high-beta, leveraged, and volatile sector ETFs will consistently populate the top quintile, while ultra-short treasuries, defensive sectors, and low-vol ETFs will populate the bottom quintile. In an 18-year bull market (2007–2025), a dollar-neutral long high-vol / short low-vol portfolio has massive positive market beta and volatility exposure.
  - By dropping Gate 2 from the PASS rule, the pre-registration allows a pure market-beta or risk-factor tilt to pass as "alpha," directly repeating the error of Phase 148.
- **Required Fix**:
  Reinstate Gate 2 as a blocking PASS/FAIL gate: require a static-tilt factor regression ($R^2 < \text{max\_static\_r2}$, per `cross_sectional_spread_tracker.py`) against SPY and the equal-weighted universe return to prove the spread is not a disguised equity-beta carry trade.

---

#### 4. Circular Block Bootstrap Mismatch and Unspecified Primitives
- **Text** ([`2026-09-02-personal-scale-edge-determination-plan.md:L311-315, L348-350`](file:///home/bg/dev/indicagent/docs/plans/2026-09-02-personal-scale-edge-determination-plan.md#L311-L315)):
  > *"circular block bootstrap 95% CI — block_size=10 (APR `alpha.ic.bootstrap_block_size.1d`), B=2000... Harness note (todo 365): this script reuses `src/intelligence/statistics/ic_math.py` primitives as-is..."*
- **Adversarial Analysis**:
  1. **Primitive does not exist in `ic_math.py`**: [`ic_math.py:L207-355`](file:///home/bg/dev/indicagent/src/intelligence/statistics/ic_math.py#L207-L355) only implements `_circular_block_bootstrap_ic`, which takes two series $(X, Y)$ and resamples bivariate Spearman rank IC. There is NO circular block bootstrap for a 1D mean in `ic_math.py`. The existing gate machinery in [`gate_math.py:L29-60`](file:///home/bg/dev/indicagent/src/intelligence/statistics/gate_math.py#L29-L60) uses day-clustered BCa/CLT (`frame_gate_passes`), not circular block bootstrap. The script cannot "reuse `ic_math.py` primitives as-is" without writing new math.
  2. **Gross block size distortion**: `alpha.ic.bootstrap_block_size.1d = 10` was calibrated for **daily** time series with 4-day overlaps. Here, the series being bootstrapped consists of **non-overlapping 5-day rebalances**. A block size of 10 applied to this series spans **10 rebalances = 50 trading days (2.5 months)**! In a sample of ~950 rebalances, this forces only ~95 blocks. If the series is already non-overlapping, what justifies a 50-day autocorrelation block?
  3. **Unspecified CI type**: The pre-registration does not state whether the bootstrap CI is percentile, basic, studentized, or BCa.
- **Required Fix**:
  Specify the exact bootstrap method and function: either use [`gate_math.frame_gate_passes`](file:///home/bg/dev/indicagent/src/intelligence/statistics/gate_math.py#L29) or specify a well-defined block size (e.g. block_size=2 rebalances = 10 days if residual serial correlation exists, or i.i.d. BCa if autocorrelation is zero) and explicitly define the CI interval computation (e.g. percentile vs BCa).

---

### Severity 2: High & Substantial Vulnerabilities

#### 5. Rule 3 (Stability) is Evaluated on Gross and is a Trivially Weak Bar
- **Text** ([`2026-09-02-personal-scale-edge-determination-plan.md:L325-327`](file:///home/bg/dev/indicagent/docs/plans/2026-09-02-personal-scale-edge-determination-plan.md#L325-L327)):
  > *"3. Stability: positive gross LS mean in ≥ 2 of 3 equal subperiods (rebalance-index thirds)."*
- **Adversarial Analysis**:
  1. **Gross vs Net**: Why is stability tested on **gross** returns when the entire foundation of workstream 0b/0c is that costs dictate edge? A construction that is net-negative across all three subperiods could pass this rule if gross returns are slightly positive in 2 of 3.
  2. **Permits modern 6-year failure**: A subperiod is ~316 rebalances $\approx$ 6.3 calendar years. A strategy that worked in 2007–2013 (Third 1) and 2013–2019 (Third 2), but **lost money continuously throughout the modern regime (2019–2025, Third 3)**, passes this gate!
  3. **Trivially weak under Rule 1**: If Rule 1 passes (full-sample net mean bootstrap lower bound > 0), the probability that gross returns are positive in $\ge 2$ of 3 subperiods is $>95\%$. It provides almost zero independent falsification value.
- **Required Fix**:
  Require **net** mean LS return > 0 in **all 3 of 3** subperiods (or a fold ratio test $\max / \min < 3\times$ per `OOS-EVAL-PROTOCOL.md:L94`), ensuring the signal did not completely decay in the post-2019 era.

---

#### 6. Mathematical Inconsistency: Log Returns, Simple Portfolio Returns, and Linear Costs
- **Text** ([`2026-09-02-personal-scale-edge-determination-plan.md:L267-272, L304-308`](file:///home/bg/dev/indicagent/docs/plans/2026-09-02-personal-scale-edge-determination-plan.md#L267-L272)):
  > *"`spread = mean(long leg) − mean(short leg)`... `forward_returns.return_mid` (executable open-to-open log return)... `Net per-rebalance LS return = gross − 2 × turnover × one_way_cost`."*
- **Adversarial Analysis**:
  1. An equal-weighted portfolio return is the arithmetic mean of *simple* returns: $R_{port} = \frac{1}{K}\sum (\frac{P_{exit}}{P_{entry}} - 1)$. 
  2. Averaging log returns $\frac{1}{K}\sum r_i$ is systematically lower than portfolio log return due to Jensen's inequality:
     $$\frac{1}{K}\sum \ln\left(\frac{P_{exit}}{P_{entry}}\right) \approx R_{port} - \frac{1}{2}\overline{\sigma_i^2}$$
  3. Because the long leg selects the highest-range (highest-volatility) ETFs and the short leg selects the lowest-range ETFs, $\overline{\sigma_{\text{long}}^2} \gg \overline{\sigma_{\text{short}}^2}$.
  4. Averaging log returns penalizes the long leg far more heavily than the short leg, creating an artificial drag of $10\text{–}30\text{ bps}$ per 5-day period solely from cross-sectional volatility disparity.
  5. Furthermore, subtracting linear basis-point costs (`2 * turnover * one_way_cost`) from a difference of log returns mixes incompatible units.
- **Required Fix**:
  Explicitly convert single-name log returns to simple returns ($R_i = e^{r_i} - 1$) before computing leg averages, calculate the net simple portfolio return ($R_{\text{long}} - R_{\text{short}} - \text{costs}$), and then evaluate statistics on simple returns or convert the net portfolio return to log return.

---

#### 7. Personal-Scale Cost Model Breakdown: The $0.35 Minimum Commission Binds
- **Text** ([`2026-09-02-personal-scale-edge-determination-plan.md:L304-308`](file:///home/bg/dev/indicagent/docs/plans/2026-09-02-personal-scale-edge-determination-plan.md#L304-L308), [`personal_cost_hurdle.py:L58-60`](file:///home/bg/dev/indicagent/scripts/analysis/personal_cost_hurdle.py#L58-L60)):
  > *"One-way cost = spread/2 + commission frac (0.0035/share, min 0.35)... price assumption USD 50/share -> 0.7 bps per side"*
- **Adversarial Analysis**:
  - The universe has 231 ETFs. A quintile long-short portfolio holds $231 \times 0.20 \approx 46$ long and 46 short = **92 positions**.
  - In a personal trading account ($50,000 to $100,000), position size per ETF is only $\$500\text{–}\$1,100$.
  - At $\$50/\text{share}$, a $\$1,000$ position is 20 shares. The per-share commission is $20 \times \$0.0035 = \$0.07$.
  - **The minimum commission of $\$0.35/\text{order}$ binds on every single trade!**
  - Commission cost is $\$0.35 / \$1,000 = \mathbf{3.5\text{ bps}}$ per trade, not 0.7 bps (5x higher). On a $\$500$ position, it is **7.0 bps** (10x higher).
  - Round-trip commissions alone would be 7–14 bps per turnover, vastly exceeding the measured 1.4 bp spread. The 0.7 bp assumption is an institutional-clip assumption ($>1000$ shares), directly contradicting the program doc's "personal-scale" mandate.
- **Required Fix**:
  Either:
  1. Scale the portfolio to a smaller, tradeable subset (e.g. top/bottom 10 names rather than 46 names); OR
  2. Incorporate the $\$0.35$ ticket minimum into the cost sensitivity band based on an explicit account equity assumption (e.g. $\$100\text{k}$ account $\implies$ commission $= 3.5\text{ bps}$).

---

#### 8. Rebalance Anchor Date & Stride Seasonality Snooping (Phase Luck)
- **Text** ([`2026-09-02-personal-scale-edge-determination-plan.md:L268-270`](file:///home/bg/dev/indicagent/docs/plans/2026-09-02-personal-scale-edge-determination-plan.md#L268-L270)):
  > *"Cadence: non-overlapping, every 5th trading day anchored at the first eligible rebalance date in the sample. Hold exactly 5 trading days."*
- **Adversarial Analysis**:
  - With a 5-day non-overlapping holding period, there are **5 distinct calendar phases** (e.g. Monday-to-Monday, Tuesday-to-Tuesday, etc.). 
  - Day-of-week seasonality or idiosyncratic calendar clustering can easily make Phase 1 pass while Phases 2–5 fail.
  - Furthermore, "first eligible rebalance date in the sample" is ambiguous. If 2007-03-23 has only 15 eligible symbols, the anchor shifts to the first date with $\ge 20$ symbols (say, 2007-04-10), shifting the entire 18-year sequence to a completely different day-of-week phase. An implementer could adjust universe filters to land on whichever phase passes.
- **Required Fix**:
  Lock the exact anchor date explicitly (e.g. `anchor_date = "2007-03-23"`), and evaluate the falsification across **all 5 stride offsets** (offset 0, 1, 2, 3, 4) as a pre-registered robustness requirement.

---

### Severity 3: Medium Gaps & Protocol Omissions

#### 9. Churn Definition Discrepancy (Rank Churn vs Bucket Churn)
- **Text** ([`2026-09-02-personal-scale-edge-determination-plan.md:L305-307`](file:///home/bg/dev/indicagent/docs/plans/2026-09-02-personal-scale-edge-determination-plan.md#L305-L307)):
  > *"Turnover = actual quintile-membership churn measured in the run (0b prior 0.17; the measured value is reported)."*
- **Adversarial Analysis**:
  In [`personal_cost_hurdle.py:L183-193`](file:///home/bg/dev/indicagent/scripts/analysis/personal_cost_hurdle.py#L183-L193), the 0.17 prior was computed as **mean absolute cross-sectional rank change** ($\frac{1}{N}\sum |\Delta \text{rank}|$). That is NOT quintile-membership churn. For an autoregressive indicator, quintile bucket churn (the fraction of names entering and exiting the top 20%) is typically 2x to 3x higher than average rank change (often 30%–50%). The doc confuses these two metrics.
- **Required Fix**:
  State explicitly that turnover is calculated via [`cross_sectional_spread_tracker.one_way_turnover`](file:///home/bg/dev/indicagent/services/cross_sectional_spread_tracker.py#L206) (fraction of leg membership replaced), and update the hurdle benchmark accordingly.

#### 10. Ambiguity in Skipped-Day Calendar Mechanics
- **Text** ([`2026-09-02-personal-scale-edge-determination-plan.md:L277-278`](file:///home/bg/dev/indicagent/docs/plans/2026-09-02-personal-scale-edge-determination-plan.md#L277-L278)):
  > *">= 20 eligible symbols or the day is skipped and counted in the report."*
- **Adversarial Analysis**:
  If scheduled rebalance date $T$ is skipped because $N < 20$:
  - Does the portfolio remain in cash until date $T+5$? If so, is that period recorded as 0.0 return (diluting the mean) or omitted from the sample (reducing $N$)?
  - Or does the engine try to rebalance on $T+1$? If it enters on $T+1$ and holds for 5 days, the non-overlapping stride is permanently desynchronized.
- **Required Fix**:
  Specify that skipping advances to the next scheduled stride date on the global calendar (cash held, period return omitted from the bootstrap sample to avoid zero-dilution).

#### 11. Omission of ETF Borrow Fees and Short Cash Haircuts
- **Text** ([`2026-09-02-personal-scale-edge-determination-plan.md:L304-308`](file:///home/bg/dev/indicagent/docs/plans/2026-09-02-personal-scale-edge-determination-plan.md#L304-L308)):
  The cost model only includes spread and commission. In retail accounts at IBKR, shorting 46 ETFs incurs borrow fees (general collateral borrow or hard-to-borrow fees on niche/sector ETFs) and interest haircuts on short sale proceeds. An annualized 50–100 bp drag is ~1–2 bps per 5 days, which doubles the 1.4 bp spread cost. Borrow cost cannot be assumed to be 0 bps.

#### 12. Unspecified Null P-Value Direction and Resolution at N=200
- **Text** ([`2026-09-02-personal-scale-edge-determination-plan.md:L316-324`](file:///home/bg/dev/indicagent/docs/plans/2026-09-02-personal-scale-edge-determination-plan.md#L316-L324)):
  *"Shuffled-null p < 0.05 (gross), N=200 replicates"*.
  The doc does not specify if the empirical $p$-value is one-sided ($P(\bar{X}_{\text{null}} \ge \bar{X}_{\text{obs}})$) or two-sided, nor whether $+1$ sample smoothing is used. At $N=200$, each replicate represents $0.005$ in $p$-value. Bumping $N$ to at least 500 or 1,000 replicates is standard to prevent sampling noise around the $\alpha=0.05$ decision boundary.

#### 13. Audit Trail Logging Omission
- **Text** ([`2026-09-02-personal-scale-edge-determination-plan.md:L291-292`](file:///home/bg/dev/indicagent/docs/plans/2026-09-02-personal-scale-edge-determination-plan.md#L291-L292)):
  Mentions recording to `gate_evaluations` under `gate1_range_pct_fast_xs_ls_h5`, but fails to mention appending to `.planning/gate_look_log.jsonl`, which is required by D-04 and [`OOS-EVAL-PROTOCOL.md:L115-119`](file:///home/bg/dev/indicagent/docs/plans/OOS-EVAL-PROTOCOL.md#L115-L119).

---

## Required Amendments Before Execution

Before `scripts/analysis/range_pct_fast_xs_ls_h5_falsification.py` is written or run, the pre-registration section in `docs/plans/2026-09-02-personal-scale-edge-determination-plan.md` must be amended with the following locked decisions:

| Area | Current Text | Required Amendment |
|---|---|---|
| **OOS Gate Rule** | $\ge 0.5\times$ IS mean (unpowered, ~40% null false positive) | Evaluate across all 5 stride offsets to achieve statistical power; require net positive return at all cost bands; state whether gross or net. |
| **Eligibility** | `non-null signal AND complete eligible return` | `non-null signal AND active instrument AND tradeable open` at $T$. Handle post-$T$ trading halts at settlement time, not at screening time. |
| **Gate 2 Attribution** | "Reported, never gated" | Mandatory Gate 2: static-tilt regression against SPY / market ($R^2 < 0.20$) to prevent buying high-beta ETFs in bull markets. |
| **Bootstrap Spec** | `circular block bootstrap... block_size=10` | Use `gate_math.frame_gate_passes` (day-clustered BCa / CLT) or define an explicit 1D mean bootstrap with block size calibrated to non-overlapping data (e.g. block=2 rebalances). |
| **Stability (Rule 3)** | Gross mean > 0 in $\ge 2$ of 3 subperiods | Net mean > 0 across all 3 of 3 subperiods at the 1.4 bp spread level. |
| **Return Math** | Arithmetic mean of log returns minus linear costs | Convert to simple returns ($e^r - 1$), compute dollar-neutral leg spread, deduct costs, then compute Sharpe/statistics. |
| **Commission Model** | 0.7 bps flat (ignores \$0.35 minimum) | Model \$0.35/order minimum on personal account equity (or restrict universe to top/bottom 10 names so clip size clears minimum). |
| **Stride Robustness** | Single phase anchored at "first eligible date" | Fix exact initial anchor date (e.g. `2007-03-23`); report results across all 5 offsets (0 to 4). |
