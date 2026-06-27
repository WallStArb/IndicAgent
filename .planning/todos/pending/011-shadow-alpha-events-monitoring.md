# 011 — Shadow Alpha Events Monitoring Protocol

**Priority: High — must exist before Phase 142 ships; shadow mode without monitoring is a log sink.**
**Gate: Must be built as part of Phase 142, not deferred to Phase 143.**

---

## Problem

Phase 139 ships alpha_events in shadow mode (`is_shadow=true`). Phase 142 adds portfolio construction, Kelly sizing, and counterfactual_pnl_r measurement — also in shadow. But there is currently no defined monitoring protocol:

- No dashboard showing shadow emission rate, win rate, P&L distribution
- No review cadence (who reviews, when, with what criteria)
- No promotion gate criteria defined upfront
- No alert if shadow emissions suddenly drop (feature decay) or spike (threshold bug)

"Shadow mode" without active monitoring is not scientific testing — it is deployment with delayed detection. A Renaissance shadow deployment has explicit review gates and a live pulse on the key metrics.

---

## What Needs to Exist Before Phase 142 Exits Shadow

**Grafana panels (add to existing board):**
- Shadow emission rate per (symbol, TF, regime): emissions/day rolling 7-day. Alert if drops > 50% week-over-week (feature decay or threshold bug).
- Counterfactual P&L distribution: histogram of counterfactual_pnl_r across all shadow trade_frames. Primary health metric.
- Rolling win rate: 20-day rolling fraction of counterfactual_pnl_r > 0 per (symbol, TF). Gate: must be > 0.52 at 80% CI before promotion is considered.
- VaR headroom: current portfolio VaR utilization vs limit. Alert at > 0.80.
- Correlation cluster utilization: how often is the correlation constraint blocking additional emissions?
- Rejection reason breakdown: ci_lower_negative / effective_n_low / threshold_miss / below_minimum_notional. High rejection rates reveal emission threshold calibration issues.
- Alpha score distribution at emission: monitors score drift over time; a collapsing distribution signals ensemble weight decay.

**Review cadence:**
- Weekly review of shadow P&L distribution and win rate trend. Not automated — human eyes on the distribution shape, not just the mean.
- Alert (Telegram/Grafana) if rolling win rate drops below 0.48 (worse than coin flip) for 10 consecutive trading days.

**Promotion gate criteria (defined upfront, not negotiated after):**
These are the Phase 144 LIVE-01 criteria — they must be documented in a SHADOW-REVIEW.md file at Phase 142 launch, not derived post-hoc from the data:
- ≥ 60 trading days of shadow emissions
- Mean counterfactual_pnl_r > 0 at 95% CI (bootstrap, one-tailed)
- Sharpe of counterfactual_pnl_r > 0.5 annualized
- Max drawdown of cumulative counterfactual_pnl_r < 25%
- IC Sharpe across shadow period stable (no cliff in the last 20 days)

Post-hoc gate negotiation ("the numbers were almost there, let's lower the threshold") is not allowed. Gates are set before shadow starts.

---

## Deliverables

1. `SHADOW-REVIEW.md` at Phase 142 launch — promotion gate criteria, review cadence, alert thresholds. One page. Written before shadow emissions start.
2. Grafana dashboard row: "Shadow AlphaEngine" — 7 panels as specified above.
3. Weekly alert summary (Telegram) — emission count, win rate, cumulative P&L. Automated. No manual summary writing.

---

## Why This Is High Priority

Without this, Phase 143 (feature lifecycle + decay infrastructure) will be built while flying blind on shadow performance. The decay monitor needs signal that features are decaying — but if no one is watching the shadow dashboard, decay may not be detected until it has already materially damaged the counterfactual P&L record that is the only evidence base for Phase 144 promotion.
