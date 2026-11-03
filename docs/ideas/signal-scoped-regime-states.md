# Scoped regime states: a stable of world, market and sector states

**Status:** Idea, 2026-10-28, extended 2026-11-03 with the fragile-divergence state. Unreviewed Sonnet 5.5 consolidation of three owner ideas; needs an Opus or Fable rigor pass before it moves to `docs/research/`. Nothing is queued or built.
**Origin:** owner, 2026-10-28: factor importance may change in identifiable regimes and at shifts; edge may sit where several regimes coincide or at their boundaries; regimes that answer scoped questions (what is the world doing, a sector, a market) are easier and less data-hungry than per-symbol ones, and a stable of them can apply to every symbol. Earlier owner idea folded in: the participation state (2026-09-25).

## The idea in two halves

**Supply: a stable of scoped states.** Each state answers one question about one scope and is computed once for everyone it applies to:

| Scope | Question | Inputs on hand |
|---|---|---|
| World | Is the world risk-on or risk-off | Four existing macro groups (equity, rates, commodity, fx in `market_regimes`), stored cross-asset features (`vix_z`, `flight_quality`, `hyg_lqd_ret_z`) |
| Market | How broad is participation | RSP/SPY concentration and breadth (`docs/ideas/signal-participation-state-style-spreads.md`); net 52-week extremes (the fragile-divergence state, below) |
| Sector | What is this sector doing | The 11 sector ETFs (XLB, XLC, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, XLY), all onboarded; membership by point-in-time sector (carried in the S0 snapshot) |

**A third market kernel: the fragile-divergence state (2026-11-03).** Owner question: the
breadth-divergence picture (index near an all-time high while net new 52-week lows outnumber
highs) as a market regime. The salvageable core is one observable the stable lacks; the
surrounding HMM proposal it arrived in needs rework to fit the design.

- New kernel: net 52-week highs minus lows as a fraction of panel names, causal expanding
  percentile rank (`causal_rank.py`, the same transform as `breadth_vol.py`'s two axes).
  Extremes-based participation: the existing breadth axis (fraction above the 200-day MA) is
  level-based and cannot separate narrowing leadership from a broad selloff.
- The state is a confluence of continuous states: index position high (distance from ATH on
  panel SPY), net extremes low, and the concentration state `c_t` negative
  (`signal-participation-state-style-spreads.md`). The demand half's confluence variant already
  defines how a state is used; this is its first concrete triple.
- Survivorship guard: net extremes are counted on the S0 point-in-time universe only. A fixed
  today's-names count over history silently understates deterioration (dead names are absent
  pre-onboarding); the span where the panel universe is representative is part of the power
  statement.
- An HMM posterior over these kernels is one legal producer of the continuous state
  (`market_regimes` stores the probability vector), sequenced behind the simpler composite:
  walk-forward only (in-sample fit-then-predict is lookahead; the per-symbol HMM columns carry
  that defect until the 186-26 rebuild, todos 248, 466), semantic labels assigned by a declared
  rule on emission means (state indices are a permutation, never an assumption), state count
  and every feature set counted as looks, the seed an APR key with the invalidation warning,
  and it must clear the scrambled-data null-arm control and beat the causal-rank composite
  before it displaces them. Macro tightening stays out of the emissions: rate direction and
  slope are the four-quadrant axis (`signal-macro-context-layer.md`), a separate declared
  dimension.
- Dropped from the proposal: the 0.65-probability defensive overlay (regimes are disclosure
  only and never gate, UD-07; the threshold is post-hoc), the dispersion/mean-reversion
  strategy shift (the honest form is a preregistered conditional test: momentum and trend
  members' importance degrades, level, or is falling, velocity, in the fragile state),
  yfinance sourcing (RSP and SPY are panel names), and NFCI (weekly FRED, banned until
  todo 482).
- Cost and inputs: one `regime_signals/` module following `breadth_vol.py` (pure function over
  pre-fetched bars, causal expanding rank). SPY and RSP are onboarded panel names (verified
  2026-11-03); the extremes count runs over the existing universe, which is the measuring
  instrument, not something to expand. No new securities, no new data paths.
- No new atomic features: these are market-wide states; conditioning goes through the S7 regime
  slot (todo 548) and stratification joins, never as per-symbol feature columns. A member-level
  interaction column (member z x state) would be a new feature and a new look, which the
  combiner routing exists to avoid; an HMM posterior, if ever built, follows
  `features/kernels/regime.py`'s walk-forward template (186-13) as a state producer.
- Sequenced with the rest: independent divergence episodes are measured first (E15 step 0,
  constraint above) before any variant runs; the poor regime-conditional prior applies
  unchanged.

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
