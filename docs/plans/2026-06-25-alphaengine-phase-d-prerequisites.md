# AlphaEngine Phase D Prerequisites — Renaissance Council Review

**Date:** 2026-06-25
**Status:** UNRESOLVED — must be decided before Phase D roadmap is written
**Context:** Structural gaps identified after Phase 140 completion. These are design decisions, not implementation tasks. Each gap must have an explicit answer in the roadmap or a linked todo before Phase D planning begins.

---

## 1. IC Validation Decision Tree

**Gap:** The roadmap implicitly assumes IC > 0 will be found on the full 58-symbol corpus. This is scheduled optimism.

**Required:** Explicit fork paths after Phase C validation:

- **(a) Confirmed** — IC Sharpe >= 0.3, sufficient survivors across features and symbols → proceed to Phase D.
- **(b) Partial** — fewer than N features survive BH-FDR (define N), or IC Sharpe 0.1–0.3 (unstable) → define minimum viable feature set to proceed; document acceptable degradation.
- **(c) Null** — no feature survives, or IC < 0 ensemble-wide → diagnose (regime label quality? forward return contamination? feature construction?) and define rerun criteria before restarting.

**Decision needed:** What is the minimum survivor count and minimum IC Sharpe to proceed?

---

## 2. Null Model Baseline

**Gap:** IC engine measures IC vs. zero. "Better than random" is not the Renaissance bar.

**Required before Phase C validates:** Define the null model the ensemble must beat on risk-adjusted OOS returns:
- Equal-weight ensemble (all 54 features, equal contribution)
- Buy-and-hold (SPY or equal-weighted ETF universe)
- Simple 5-bar momentum on each symbol

IC-weighted ensemble must beat the chosen null on OOS Sharpe and/or Sortino before Phase D starts.

**Decision needed:** Which null models, measured on what metric (Sharpe? IR? max drawdown ratio?)?

---

## 3. True Out-of-Sample Holdout

**Gap:** Walk-forward (3-fold expanding) is in-sample validation with temporal structure. It protects against look-ahead but the IC engine "sees" all data up to each fold boundary.

**Required:** True OOS requires holding back the most recent N months entirely — touch nothing, measure nothing during training. Validate learned ensemble weights on that window only after training is locked.

**Decision needed:** How many months to hold out? Recommendation: 6 months. Define the holdout window boundary before the full corpus IC run populates `feature_ic_scores` for ensemble training.

---

## 4. Transaction Cost Model (Phase D Prerequisite, Not Phase E)

**Gap:** Kelly sizing requires `E[return] > estimated_transaction_cost`, but fills accumulate only after the system is live — circular dependency.

**Solution (decidable now):**
- Measure bid-ask spread from IBKR historical L1 data for each ETF in the universe
- Static slippage estimate: 0.5 × spread for liquid ETFs (SPY, QQQ, IWM); 1.0 × spread for illiquid names
- Document as `[initial_estimate]` in APR under `alpha.portfolio.transaction_cost_bps`
- Update as realized fills accumulate (the system converges to empirical estimates over time)

**Decision needed:** Confirm this approach. The cost model must exist as APR parameters before Phase D ships.

---

## 5. Vol Estimate for Kelly Sizing

**Gap:** Phase D design references "rolling realized vol" without specifying which. This feeds directly into position size — a 2× overestimate means 50% underallocation, a 0.5× underestimate means 2× overleveraging.

**Context:** FeatureVector already computes `garch_ratio` = GARCH conditional vol / realized vol. The system has GARCH vol in hand.

**Recommendation:** Use GARCH conditional vol (`garch_ratio × realized_vol`) as the Kelly denominator. It forward-estimates vol better than realized vol, especially after vol regime transitions.

**APR key needed:** `alpha.portfolio.vol_estimate_source` — values: `'garch'` (recommended), `'realized'`, `'atr'`. Default `'garch'`.

**Decision needed:** Confirm GARCH as default. Document which realized vol window is used as fallback.

---

## 6. Shadow Alpha Events Monitoring Protocol

**Gap:** Phase 139 ships `alpha_events` in shadow mode with no defined monitoring protocol — no dashboard, no review cadence, no promotion criteria. Shadow mode without active monitoring is a log sink.

**Required:** Explicit shadow monitoring spec before Phase D:
- Minimum N emissions before evaluation (recommendation: 500 events across symbols)
- Rolling win rate threshold to evaluate (directional correctness of `signal_direction` vs. `return_fast` sign)
- IC Sharpe stability check (weekly IC Sharpe should not decay >20% month-over-month)
- Comparison vs. null model on counterfactual returns
- Human review cadence (weekly? milestone-gated?)

**Decision needed:** Define promotion criteria as APR keys or as a Phase D gate. This should be a todo or a Phase D sub-plan, not assumed to happen organically.

---

## 7. IC and Ensemble Update Coherence (Document, Not Fix)

**Gap:** Alpha Decay Monitor runs daily but reads `feature_ic_scores`, which are only updated weekly. The decay monitor is always reading 0–7 day old IC. If a feature's IC collapses on Monday and the IC engine ran on Sunday, the monitor won't detect it until next Sunday.

**This is acceptable behavior**, but must be documented explicitly in the AlphaEngine methodology doc, because the decay monitor's SLA ("daily monitoring") implies fresher detection than it actually delivers.

**Action:** Add a "Monitoring Lag" section to `docs/intelligence/intelligence-alphaengine.md` documenting this lag. No code change required.

---

## 8. AnalogEngine Embedding Dimension Calibration

**Gap:** Embedding dimension (`embedding_dim`) is a one-way door — changing it invalidates all stored `analog_vectors`. You cannot know the optimal dimension without a corpus to measure on.

**Required before committing to a dimension:**
1. Embed 3–6 months of bars at candidate dimensions (64, 128, 256)
2. Measure recall@k and mean reciprocal rank (MRR) against known-outcome analogs
3. Pick the winner, lock it as APR key `alpha.analog.embedding_dim`, then run full historical embedding

**Decision needed:** Build this calibration step into the AnalogEngine plan (todo 012) before the full historical embedding run. Without it, you pick 128 by convention and discover 18 months later that 64 retrieved better analogs.

---

## 9. v2.x Retirement Gate

**Gap:** Dual pipeline comparison (todo 007) implies v2.x I7 is still running alongside v3.0, but when v2.x retires is undefined. Without an explicit gate, v2.x either runs forever (operational debt) or gets killed prematurely (risk).

**Required:** Define the empirical retirement gate before Phase D ships:
- v3.0 must demonstrate N months of live `alpha_events` with positive counterfactual_pnl_r at 95% CI
- Recommendation: 3 months of live shadow data, p < 0.05 on bootstrapped mean return
- Gate should live as APR key `alpha.portfolio.v2_retirement_ci_threshold` = 0.95

**Decision needed:** Confirm N months, CI threshold. Write the gate explicitly in the roadmap rather than "after sufficient validation."

---

## 10. BH-FDR Budget for Interaction Factory

**Gap:** IC engine currently tests ~54 features × 4 lookaheads × 4 TFs × 3 regimes ≈ 2,600 cells. Interaction Factory adds ~30K compound features × same dimensions ≈ 1.44M new tests. BH-FDR at 5% over 1.44M tests sets a far stricter p-value threshold than over 2,600.

**Required design decision:**
- **(a) Separate correction pools** — atomics and compounds get separate BH-FDR corrections. Simplest; preserves atomic survivor rates.
- **(b) Pre-screen** — compound features are pre-screened by simple correlation with each atomic before entering full IC machinery. Reduces test count but adds pipeline complexity.
- **(c) Combined pool** — run BH-FDR over all tests jointly. Most conservative; compound features will mostly not survive. Correct behavior but may render the Interaction Factory low-yield.

**Recommendation:** Separate correction pools (option a). Atomics are the primary signal; compounds are augmentation. Mixing the pools penalizes the atomic features.

**Decision needed:** Confirm approach before todo 015 (Interaction Factory) is planned.

---

## 11. Regime-Conditioned Cluster Membership (Document Known Limitation)

**Context:** Phase 140 P2 implemented hierarchical clustering on the feature correlation matrix — one representative per cluster, globally. But correlations change across regimes: two features uncorrelated in trending might be 0.8 correlated in ranging.

**This is a known, acceptable limitation for the current milestone.** The clustering is global (one membership for all time). Document it explicitly in the IC engine methodology with a Phase G+ extension: regime-conditioned clusters, one membership table per HMM state.

**Action:** Add "Known Limitations" section to `docs/intelligence/intelligence-alphaengine.md` with this item.

---

## 12. Minimum Position Size Filter

**Gap:** Kelly sizing produces a continuous position size. IBKR trades integer shares. For SPY at $500+, Kelly might compute 0.3 shares → rounds to 0 (no position) or 1 share (333% of intended size). For small accounts, Kelly will produce sub-threshold positions for most alpha events and the system will effectively do nothing.

**Required before Phase D ships:**
- APR key: `alpha.portfolio.min_position_notional` — minimum dollar notional per position, default $500
- Positions below threshold are discarded (not rounded up to 1 share)
- Document in Phase D plan as an explicit filter step in the Kelly sizing path

**Decision needed:** Confirm default ($500). This affects whether the system actually trades at all for small accounts, so it must be explicit, not discovered post-launch.

---

## Resolution Status

| # | Gap | Status | Owner |
|---|-----|--------|-------|
| 1 | IC validation decision tree | UNRESOLVED | Phase D plan |
| 2 | Null model baseline | UNRESOLVED | Phase C/D boundary |
| 3 | True OOS holdout | UNRESOLVED | Before corpus IC run |
| 4 | Transaction cost model | UNRESOLVED — decidable now | APR seed |
| 5 | Kelly vol estimate | UNRESOLVED — recommendation: GARCH | APR key |
| 6 | Shadow monitoring protocol | UNRESOLVED | Todo or Phase D sub-plan |
| 7 | IC/ensemble update lag | Document only | `intelligence-alphaengine.md` |
| 8 | AnalogEngine embedding calibration | UNRESOLVED | todo 012 |
| 9 | v2.x retirement gate | UNRESOLVED | Roadmap |
| 10 | BH-FDR budget for Interaction Factory | UNRESOLVED — recommendation: separate pools | todo 015 plan |
| 11 | Regime-conditioned clustering | Document only | `intelligence-alphaengine.md` |
| 12 | Minimum position size filter | UNRESOLVED — recommendation: $500 | Phase D APR |

**Blocking (must resolve before Phase D roadmap is written):** 1, 2, 3, 4, 5, 6, 9, 12
**Non-blocking (document/defer):** 7, 8, 10, 11
