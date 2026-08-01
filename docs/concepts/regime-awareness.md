# Regime Awareness

**Version:** 1.0
**Status:** stale (v2.x, see banner)
**Last Updated:** 2026-05-30
**Tags:** market-regime, non-stationarity, context-classification, adaptive-signals

> Market behavior is non-stationary — rules that work in trending markets fail in ranging ones. Every signal must know what kind of market it is operating in.

> **Staleness note (2026-08-01):** This doc describes the I4 regime tier and the I7 regime gate
> (`signal_metrics` table) — part of the ARCHIVED v2.x pipeline, with no live consumer as of
> 2026-07-02 per CLAUDE.md. The dual regime system (per-symbol HMM vs cross-sectional
> VIX×breadth) is the current live equivalent. Not yet rewritten for v3.0 -- tracked for a
> future doc pass, not fixed here.

## The Problem It Solves

A trend-following signal that works in a trending market will bleed out in a ranging one. A mean-reversion signal that profits from oscillation fails during momentum breakouts. A model trained globally — "this pattern historically predicts X" — ignores the most important conditioning variable: market regime. The same setup in a high-volatility breakout environment and in a low-volatility compression environment are different trades. Treating them identically produces a positive expectation trade on average that masks a negative-expectation trade in the wrong regime.

## The Principle

Classify regime continuously. Condition all signals on current regime. Never apply a rule learned in one regime to a different regime without explicit regime conditioning.

This requires:
1. **Multiple independent regime dimensions** — volatility, trend, momentum, and hidden state are not the same thing and should not be collapsed into one label
2. **Continuous classification** — regime does not change discretely; every bar gets a regime label
3. **Signal gating** — signals that are invalid in the current regime are suppressed, not adjusted
4. **Per-regime performance tracking** — weights and thresholds learned in one regime are stored separately from those learned in another

## How IndicAgent Applies It

The I4 tier produces five independent regime dimensions per bar:

| Classifier | Output | Method |
|------------|--------|--------|
| `VolatilityRegime` | `low` / `normal` / `high` | ATR percentile rank over rolling window |
| `TrendRegime` | `uptrend_strong` / `uptrend_weak` / `sideways` / `downtrend_*` | SMA-20/50 alignment + ADX strength |
| `MomentumContext` | `accelerating` / `decelerating` / `neutral` | Composite of RSI, MACD, Stochastic, CCI |
| `GARCHVolatility` | Volatility forecast + expected range | Parametric GARCH(1,1) model |
| `HMMRegime` | Continuous hidden state probabilities | Hidden Markov Model (Baum-Welch) |
| `BOCPDChangepoint` | Changepoint probability | Bayesian Online Changepoint Detection |
| `KalmanTrend` | Kalman-filtered trend slope | Kalman filter state estimate |

**I7 regime gate:** Every I7 setup plugin declares which regime configurations it is valid for. The pipeline checks current regime before executing the plugin — an invalid regime means the plugin is skipped for that bar, not fired and discarded. The gate is hard: `MeanReversion` requires `low` or `normal` volatility; it does not fire during `high` volatility compression regardless of other signals.

**Per-regime weights:** The `signal_metrics` table stores rolling 30-day Sharpe and win rate per (setup_plugin, timeframe, symbol, `regime_type`). Performance multipliers are loaded per current regime at startup and refreshed hourly. A setup with strong performance in trending markets does not benefit from that when the market is ranging.

**CIS regime bucket:** The CIS scorer has a dedicated `regime` bucket (weight 0.15) that reads HMM state probabilities, BOCPD changepoint stability, and cross-TF regime agreement. Regime uncertainty reduces the CIS score.

## Invariants

- Every I7 signal must declare which regimes it is valid in — the regime gate enforces this at pipeline execution time.
- Performance weights are regime-conditioned — a global weight that ignores regime is not valid.
- A signal cannot override a regime suppression gate — regime gates are not adjustable thresholds.
- `regime_type` in `signal_metrics` and `signal_ledger` is a required column — no regime-unaware performance tracking.

## Recipe

When designing regime awareness for a new system:

1. **Define regime dimensions orthogonally.** Volatility and trend are independent. Do not collapse them into one label — you lose information and create ambiguous regime categories.
2. **Classify continuously.** Regime should be a probability or score, not a boolean flag. Discrete transitions lose the uncertainty information that matters most at regime boundaries.
3. **Gate, don't adjust.** A signal that is invalid in the current regime should be suppressed entirely, not adjusted with a multiplier. Partial suppression is unprincipled and hard to backtest.
4. **Track performance per regime separately.** A globally-good strategy may be regime-conditional. You cannot discover this without regime-stratified performance data.
5. **Handle regime uncertainty explicitly.** At the boundary between two regimes, you are in neither. Design for regime uncertainty — do not force a definitive label on ambiguous periods.
6. **Beware regime-overfitting.** More regime dimensions = more specificity = less data per regime cell = less statistical power. Start with 2-3 dimensions and add only when you have the sample size to support it.

## See Also

- Implementation: `docs/intelligence/intelligence-foundation.md` — I4 regime tier, HMM/BOCPD/Kalman detail
- Performance weights: `docs/intelligence/intelligence-foundation.md` — Adaptive Weight Systems section
- Code: `src/intelligence/features/i4_context/` — regime classifier plugins
- Related concept: `docs/concepts/evidence-graded-signals.md` — how regime feeds the CIS regime bucket
