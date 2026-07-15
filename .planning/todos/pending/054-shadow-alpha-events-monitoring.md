---
**Created:** 2026-06-28
**Area:** operations
**Type:** new_feature
**Priority:** P1
**Effort:** 1-2 days
**Benefit:** Enables scientific shadow testing; prevents delayed detection of feature decay or threshold bugs
**Risk:** low (observability only)
**Gate:** alpha_events shipped (OPEN) — must be built as part of Phase 142
---

# 054 — Shadow Alpha Events Monitoring Protocol

**Numbering note (2026-07-12):** this file's heading previously read "# 011" from an earlier
renumbering pass that never updated the inline copy — normalized to 054 (the filename /
pending-folder key), matching the pattern todo 009 already documented for itself.

**Priority: High — must exist before Phase 142 ships; shadow mode without monitoring is a log sink.**
**Gate: Must be built as part of Phase 142, not deferred to Phase 143.**

**Status check 2026-07-14 (corpus-rebuild idle window):** this file is stale relative to how far
the project has moved since 2026-06-28 — "Phase 142" in the text below means what's now split
across Phases 142A/142B/142B.1/143/147/148. Checked each of the 3 deliverables against live
state:

1. **`SHADOW-REVIEW.md` — DONE, already exists** at `docs/plans/SHADOW-REVIEW.md`, and is more
   rigorous than this todo's own gate-criteria sketch (day-clustered block bootstrap, gross-vs-net
   cost basis reasoning, two frozen edge-case resolutions, explicit no-post-hoc-negotiation
   clause). This todo's "Promotion gate criteria" section above is superseded by that file — don't
   treat it as the source of truth anymore.
2. **Grafana panels — NOT done, real gap.** `production/grafana/dashboards/shadow-validation.json`
   exists but is for the **archived v2.x `shadow_registry`/`shadow_validator.py` system**
   ("Per-Setup Promotion Metrics," "N Accumulation Toward Gate (N=100)") — a different,
   no-live-consumer shadow mechanism, not v3.0's `alpha_events`/`alpha_frames`. No dashboard
   exists for the live system this todo actually means.
3. **Telegram weekly alert — NOT done, real gap.** `services/alert_monitor.py` exists as a
   pattern to extend, not yet built for this purpose.

**Also stale:** several of the 7 specified panels below reference a portfolio-construction layer
(VaR headroom, correlation cluster utilization, `minimum_notional` rejection reason) that v3.0
never built this way — `alpha_publisher.py`'s actual gate stack is `effective_n` / per-TF
threshold / direction-aware CI+cost-hurdle / non-empty `top_features` (see glossary.md, corrected
2026-07-14). The panel list needs to be re-derived from the real gate stack and real
`alpha_frames`/`counterfactual_pnl_r` schema before building, not built against this stale spec
verbatim.

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
