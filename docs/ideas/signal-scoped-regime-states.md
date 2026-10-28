# Scoped regime states: a stable of world, market and sector states

**Status:** Idea, 2026-10-28. Unreviewed Sonnet 5.5 consolidation of three owner ideas; needs an Opus or Fable rigor pass before it moves to `docs/research/`. Nothing is queued or built.
**Origin:** owner, 2026-10-28: factor importance may change in identifiable regimes and at shifts; edge may sit where several regimes coincide or at their boundaries; regimes that answer scoped questions (what is the world doing, a sector, a market) are easier and less data-hungry than per-symbol ones, and a stable of them can apply to every symbol. Earlier owner idea folded in: the participation state (2026-09-25).

## The idea in two halves

**Supply: a stable of scoped states.** Each state answers one question about one scope and is computed once for everyone it applies to:

| Scope | Question | Inputs on hand |
|---|---|---|
| World | Is the world risk-on or risk-off | Four existing macro groups (equity, rates, commodity, fx in `market_regimes`), stored cross-asset features (`vix_z`, `flight_quality`, `hyg_lqd_ret_z`) |
| Market | How broad is participation | RSP/SPY concentration and breadth (`docs/ideas/signal-participation-state-style-spreads.md`) |
| Sector | What is this sector doing | The 11 sector ETFs (XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY), all onboarded; membership by point-in-time sector (carried in the S0 snapshot) |

**Demand: conditioned weights.** A member's importance is allowed to depend on a state, one pre-registered S7 combiner variant at a time:

- level: the weight depends on the state (`s` and `s x z_t` members);
- boundary: the weight depends on the state's velocity, how fast it is changing, which stands in for being near a regime shift without a bucket threshold;
- confluence: the weight depends on the product of two states, for example world risk times participation.

## How it fits the design

- The mechanism exists. `alpha.regime.groups` (an APR list) holds one entry per group: a security filter, a signal type, an enabled flag. A label is computed once per group and joined at query time; `market_regimes` also stores the probability vector, which is the continuous state. The StratificationDimension doc (`docs/research/stratification-dimension-unification.md`) defines many producers behind one contract where each dimension must earn its cells. A new scope is a new producer, and since `regime_group` gives a security one peer group, each scope is a separate dimension, not another group value.
- Regimes are disclosure only and never gate (UD-07); conditioning goes through continuous states, never through buckets, which discard information and carry post-hoc thresholds (design section 5.2).
- Owner decision 2026-10-28: macro and sector scopes first, no per-symbol regimes at the start. The per-symbol HMM columns also carry lookahead until the 186-26 rebuild (todos 248, 466).

## Constraints

- Every variant is a counted look (E18), judged at StepM selection; state inputs fall under E17's memory rule (the S7 regime slot, todo 548).
- The prior is poor: regime-conditional persistence 0 of 270 cells, the `bars_since_high` regime gate, per-symbol trend and percentile-rank regimes (todos 303, 304; ledger section 4), earnings-season conditioning 0 of 249 (section 5). Do not redo those constructions.
- Transitions and confluences are rare and episode-clustered (the `bars_since_high` standout cell was 52 days from a few macro shocks), so measure effective independent episodes first (design D6, E15 step 0) before building a variant.
- Causality: sector membership must be point in time (the equity breadth label uses today's tag set, a known defect); every state must be available at the decision time.
- The four existing groups end 2026-08-11 and stay stale until the rebuild. A group must be populated when it is enabled.

## Sequencing

1. After plan 191-20's 1d re-derive and the 186-26 rebuild, refresh the four macro groups.
2. First variant: one world or participation state with its level and its velocity (two counted looks), after the S7 regime slot exists (todo 548).
3. Sector states once point-in-time membership is confirmed; confluence last, since it multiplies variants.

## Related docs

`signal-participation-state-style-spreads.md` (the first concrete state and a time-series factor-momentum part B); `signal-sensitivity-regime-interaction-primitives.md` (ITR sensitivity tags crossed with regimes, a different idea); `signal-political-policy-regime.md` (a calendar-style state); `docs/research/correlation-regime-and-single-name-breadth-design.md` (universe breadth, not alpha).
