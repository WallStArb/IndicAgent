# Dual-System Architecture — Discrete Confluence Signals vs. Holistic Portfolio Forecasting

**Version:** 1.0
**Status:** draft — captured from 2026-07-01 design discussion (institutional-alignment review of intel-10)
**Priority:** medium (strategic framing; shapes what "done" means for the intelligence layer)
**Milestone:** future — System 1 path is intel-10; System 2 path unscoped
**Last Updated:** 2026-07-01
**Tags:** portfolio, confluence, forecasting, architecture, renaissance, dual-system

**Companion to:** `docs/ideas/intel-10-confluence-detection-persistence-layer.md`

**Naming caution:** "System 1 / System 2" is already used in this codebase for
AlphaEngine (parametric) vs. AnalogEngine (non-parametric K-NN) — see ROADMAP.md
Phases 145-146. The two systems in THIS doc are a different axis (discrete-event
output vs. continuous-portfolio output) and cut across that existing pair. Use the
names **DiscreteTrack** and **PortfolioTrack** here to avoid collision.

---

## The Insight Being Saved

An institutional-alignment review of intel-10 (2026-07-01) concluded:

1. **The statistical hygiene in intel-10 is at or above typical institutional standard** —
   incremental-lift-over-baseline gating, winner's-curse shrinkage, effective-N correction,
   corpus-level FDR, shadow-mode promotion, decay-as-steady-state. That stack would survive
   review by a real quant council and applies to BOTH tracks below. It is track-independent
   validation discipline, not a property of the discrete design.

2. **But the discrete named-pattern architecture is a deliberate departure from how large
   systematic firms actually operate**, not the industry default. Modern firms mostly run
   continuous forecasts from large models over thousands of features, refit frequently, and
   trade the aggregate — with portfolio construction (netting, risk allocation, cost-aware
   sizing across correlated signals) at the center, where much of the realized value lives.
   Named discrete patterns are closer to discretionary-quant hybrids or earlier-generation
   shops.

3. **The right response is not to pick one — it's to be explicit that these are two different
   products with different consumers**, and let each earn its existence independently.

## DiscreteTrack — Confluence Events (intel-10, already specced)

- **Output:** sparse, named, auditable occurrence records — "validated pattern C_i present on
  this bar, calibrated E[R] = X bps at horizon H."
- **Consumer:** a human operator (or a thin execution layer) acting on discrete, interpretable,
  provenance-carrying claims. Auditability and interpretability are the point.
- **Strengths:** falsifiable claims, per-pattern lifecycle governance, cheap live detection,
  aligned with this project's scale (one operator, learning-first).
- **Known ceiling (from the review):** discards graded information between fires; the set of
  named patterns can never cover the interaction space a large learned model covers; episodic
  discovery cadence adapts slower than continuous refitting.

## PortfolioTrack — Holistic Continuous Forecasting + Portfolio Construction (unscoped)

- **Output:** a continuous expected-return / conviction vector across the whole universe every
  bar, consumed by a portfolio constructor — not events, positions. The forecast layer and the
  portfolio layer ship together; the review's sharpest point was that a firm would never call
  the forecast "terminal."
- **What it adds that DiscreteTrack structurally cannot:**
  - Cross-sectional netting: long the top of the forecast ranking, short the bottom, so
    idiosyncratic noise cancels and the market factor is hedged — the core stat-arb mechanic.
  - Risk allocation across correlated signals: two confluences firing on correlated symbols is
    one bet, not two; only a portfolio layer sees that.
  - Cost-aware sizing and turnover control: trade only the forecast changes that pay their
    costs, netted across the book.
  - Continuous refit cadence: weights re-learned on a schedule, no per-pattern ceremony.
- **Existing seeds in this codebase:** `ensemble_trainer`'s per-stratum weighting is a
  primitive forecast layer; the `alpha.*` APR namespace already reserves Kelly keys; Phase 144's
  alpha-scoring system is forecast-shaped. What is entirely missing is the portfolio
  constructor (netting, risk model, turnover/cost optimization) — no phase covers it.
- **Prerequisite honesty:** PortfolioTrack is meaningless before the forecast layer has proven
  OOS IC (Phase 142A gate). Do not scope it until then. Capacity/crowding analysis remains
  irrelevant at this account size and stays out of scope for both tracks.

## How the Two Tracks Relate (and don't)

- **Shared:** the entire validation stack (gates, shrinkage, shadow mode, decay governance),
  the feature substrate (`feature_vectors`), forward returns, regime stratification, cost
  hurdle. Build once, consumed by both.
- **Not shared:** the output object, the consumer, the promotion criteria's final target
  (a persisted event vs. a position), and the definition of "working" (calibration of discrete
  claims vs. net-of-cost portfolio Sharpe).
- **DiscreteTrack events can be a feature of PortfolioTrack** — an active confluence firing is
  itself an input the portfolio forecast may weight — but never the reverse dependency;
  PortfolioTrack must not require DiscreteTrack to exist.
- **Sequencing:** DiscreteTrack first (it is already specced, cheaper, and matches current
  scale). PortfolioTrack gets scoped only after Phase 142A proves ensemble OOS IC — at which
  point the first concrete deliverable is a design doc for the portfolio constructor, not code.

## Decision This Doc Records

Do not force intel-10 to grow portfolio semantics, and do not dismiss the portfolio track as
out of reach. They are two products on one validation substrate. Revisit and scope
PortfolioTrack when Phase 142A's gate passes.

## References

- `docs/ideas/intel-10-confluence-detection-persistence-layer.md` — DiscreteTrack spec
- ROADMAP.md Phase 142A (OOS ensemble IC gate — PortfolioTrack's scoping trigger), Phase 144
  (alpha scoring), Phases 145-147
- `docs/foundation/principles.md` — earn promotion through proof; shadow mode first
