---
**Created:** 2026-07-05
**Area:** intelligence
**Type:** tech_debt
**Priority:** P3
**Effort:** ~2-3 hours
**Benefit:** Either salvage real content into v3.0's Feature Factory / Phase 151, or clear dead weight from docs/research/
**Risk:** low
**Gate:** None
**Closed:** 2026-07-16
---

# 060 — Review Cluster 2 legacy intelligence backlog for archive vs. salvage

**Status:** completed

## Problem

`docs/research/idea-catalog.md` Cluster 2 ("Pre-v3.0 Intelligence Backlog, I1-I9 era") holds five docs
of unresolved status: `intel-01-momentum-acceleration.md`, `intel-02-second-derivative-indicators.md`,
`intel-03-future-indicators.md`, `intel-06-regime-transition-detection.md`,
`intel-08-macro-cross-asset.md`. The catalog's own note says "some content may still be salvageable
into v3.0's Feature Factory / Phase 151 — check before assuming dead," but nobody has actually done
that check. Five sibling docs in the same cluster (`intel-04/05/07/09`, plus `platform-04`) were
archived 2026-07-05 because they were already self-flagged as superseded/stale with no ambiguity;
these five are genuinely unresolved, not just stale-and-unreviewed.

## Solution / Fix / What / Why

Read each of the five against the current Feature Factory (`src/intelligence/feature_factory.py`,
~61 functions) and Phase 151's interaction-primitives scope. For each: either (a) extract any
still-missing primitive into a Feature Factory candidate and archive the doc, or (b) archive outright
as fully superseded, or (c) leave as-is with a one-line reason if genuinely still open. Update
`idea-catalog.md` rows accordingly. Not urgent — these are ideas, not blockers — but cheap to resolve
in one sitting rather than five separate context-loads later.

## Process note (2026-07-06, discovered while closing this out)

All five docs were bulk-archived the day after this todo was filed (`53871ec3`, 2026-07-06) with a
one-line blanket justification, without the individual per-doc review this todo asked for first —
a real process gap, flagged unresolved in `docs/research/catalog.md`'s Cluster 2 section from
2026-07-07 until this closure.

## Resolution (2026-07-16)

Did the review that should have happened before the 2026-07-06 archive. Read all five docs (now
in `docs/research/archive/`) against the live `src/intelligence/feature_factory.py` (154 functions,
155 registered `FEATURE_VECTOR_DOMAIN` entries — this todo's ~61 estimate was stale, that count
predates Phase 142.5's 91-primitive expansion) and Phase 151's current scope in `ROADMAP.md`.

**Verdict: the archival call itself was fine — nothing load-bearing was lost.** But that is
confirmed now, by actual evidence, not asserted on faith:

- **intel-01 + intel-02** (momentum acceleration / second-derivative indicators): the proposed
  I1/I2 plugins shipped historically in the now-dead v2.x tier, never reimplemented in v3.0.
  Feature Factory already covers the volatility-acceleration half of this idea better than
  proposed — `vol_of_vol`, `parkinson_vol_velocity`/`garman_klass_vol_velocity`/
  `yang_zhang_vol_velocity`, `realized_var_ratio_fast/slow` — via three separate estimators, not
  one crude ATR delta. Cross-TF acceleration confluence is covered by todo 066's cross-TF
  divergence primitives (already in Phase 151's scope). Jerk, divergence-adjusted exhaustion,
  intraday cycles, order-flow acceleration, and triple-smoothed MACD are all either self-rated
  low-value by the original doc, blocked on unavailable IBKR L2 data, or superseded by the newer
  `signal-temporal-atomic-primitives.md`. **Genuine gap, flagged as a Phase 151 candidate:** no
  momentum-oscillator equivalent of the `_velocity` pattern already proven for the three
  volatility estimators (e.g. `momentum_z_velocity`/`rsi_velocity`) — cheap, same naming
  convention, concrete enough to act on. VWAP acceleration is also missing and cheap.
- **intel-03** (future indicators backlog): was already self-archived 2026-03-22, three months
  before the 2026-07-06 bulk archive, with most items already shipped. Remaining classic-TA ideas
  (ADL, VWMA, Ultimate Oscillator, TSI, Force Index, VROC, Chaikin Oscillator) are functionally
  superseded by v3.0's existing volume (`mfi`, `obv_z`, `vol_trend_ratio`, `up_vol_ratio`, `cmf`)
  and momentum (`rsi`/`cci` multi-window) feature families. Cross-Contract Momentum is superseded
  by the existing cross-sectional rank features. Monte Carlo VaR is a portfolio-layer concept
  already scheduled in Phase 157. Hurst Exponent, which this doc itself rated "not prioritized,"
  actually shipped (`hurst` is live) — a doc-internal miscategorization, not a gap. Genuinely
  still open but low priority: VX contango/backwardation (same gap as intel-08) and SMC-style
  named liquidity-zone detection, which doesn't fit the atomic-feature paradigm and has no plan.
- **intel-06** (regime transition detection): superseded, and better than proposed. Its core idea
  — a Shannon-entropy field over HMM state probabilities to catch the transition window a binary
  gate discards — already shipped: `services/regime_writer.py:631` computes the exact formula
  proposed (`-sum(p * log(p))`), exposed as Feature Factory's `hmm_entropy`, a first-class
  IC-measured feature. v3.0 also abandoned binary regime-gating entirely for continuous IC
  measurement across regime strata, which structurally solves the doc's stated problem without
  the doc's proposed heuristic gate logic. Minor unshipped remainder (`hmm_regime_velocity`) is
  low priority since entropy already captures most of the signal.
- **intel-08** (macro & cross-asset): mostly superseded — Feature Factory's `vix_z`,
  `flight_quality`, `yield_slope_z` (macro tier, IC-measured) replace the doc's proposed
  wiring-then-gating pipeline wholesale. **Two genuine, now-unblocked gaps found:** the doc
  deferred "real yields" (TIP/TLT) and "credit spread" (HYG/LQD) as blocked on data availability
  (2026-06-14) — verified `TIP`, `HYG`, `LQD` are all live in the 80-instrument universe today
  (the 58→80 ETF expansion postdates this doc), so both are cheap, ready-to-build candidates
  using the identical pattern already proven for `flight_quality`. Stock-bond correlation is
  similarly now buildable with existing `TLT`/`SPY` data. VX term structure remains genuinely
  blocked pending IBKR 2-contract-month data availability.

**Net finding:** one small, concrete Feature Factory candidate batch worth a future todo —
oscillator `_velocity`/curvature features (intel-01/02) plus the two now-unblocked macro spreads
(intel-08's real-yield and credit-spread z-scores) — reasonable to fold into Phase 151's atomic
expansion, not urgent enough for a standalone phase. Everything else across the five docs is
confirmed superseded, self-archived already, or genuinely blocked on data/architecture that
hasn't changed.

Full per-doc findings written into `docs/research/catalog.md`'s Cluster 2 section, replacing the
"process conflict, unresolved" flag with the table above. The process-conflict question is
answered honestly: the archival happened without the review this todo asked for, and in
hindsight the archival was defensible — but that's now demonstrated, not asserted.
