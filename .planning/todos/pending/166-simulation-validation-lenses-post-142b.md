# 166 — Additional simulation/validation lenses (post-142B)

**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §10 (L7-1, L7-2, L7-4).
142B's frame design and SHADOW-REVIEW pre-commitment are kept-by-design, untouched — these are
additional read-only lenses over what 142B produces.
**Priority:** medium — genuine diagnostic value, no new judgment surface (nulls/attributions are
mechanical).
**Gate:** hard-blocked on Phase 142B (`alpha_frames`) shipping.

## L7-1 — Standing permutation nulls in every shadow review

Generalize `trade-construction-layer.md`'s shuffled-ranking null to the frame population: every
SHADOW-REVIEW scoring run also scores (a) a sign-permuted frame population and (b) a
random-entry population matched on (symbol, tf, regime) frequencies. Report the real
population's percentile against both nulls. A pre-committed Sharpe threshold can be passed by a
lucky draw; a percentile-vs-null cannot be argued with as cheaply. Reuses frame machinery
wholesale; ~2-3x compute on an offline batch; zero new judgment surface.

## L7-2 — Regime-conditional drawdown and contribution attribution

Counterfactual equity curve segmented by regime-at-entry (both dimensions): max drawdown, P&L
share, frame count per stratum. Answers: is the aggregate P&L one regime's bet wearing a
diversified costume? A single populated cell dominating — exactly what EIC-05 found at the IC
layer (`5m`/`high_bear` concentration) — would otherwise reappear at the P&L layer unnoticed.
Pure SQL over `alpha_frames` × `market_regimes`.

## L7-4 — Cost-sensitivity sweep instead of point costs

When the cost kernel lands (canonical simulator's build item, see todo 158's dual-use note),
report frame P&L as a *curve* over cost multipliers (0.5x, 1x, 2x, 4x calibrated cost) rather
than a single net number. Todo 030 moved the cost picture materially once already — a strategy
whose profitability dies at 2x assumed cost is a different asset from one that survives 4x. One
loop around existing arithmetic; pre-commit the multiplier grid in SHADOW-REVIEW.
