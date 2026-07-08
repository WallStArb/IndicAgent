# Build the empirical Instrument Tag Calibrator (promote from idea to phase)

**Found:** 2026-07-01, during design discussion of `regime_group` and `instrument_tags`
multi-membership/weighting semantics.

## What exists vs what's missing

`instrument_tags.weight` (float, `[0.0, 1.0]`, PK on `(symbol, tag)`) already supports
fractional multi-membership — a symbol can carry several tags simultaneously, each with its
own weight (e.g. SDOG carries `defensive_yield` and `benchmark`; `spread_leg` weight 0.7).
Per the glossary (`docs/foundation/glossary.md:120`), weight is defined as "strength of an
instrument's association with a tag; driven by beta magnitude after empirical calibration."

But today nearly every weight in the table is a `source='human'` assertion — a guess, not a
measurement. The design to fix this already exists in full at
`docs/research/instrument-tag-calibrator.md` (status: draft, v1.1, priority: high, milestone:
post-v2.8) and does not need to be re-specced from scratch — it needs to be **picked up and
turned into a phase**. Do not re-derive its design; read that doc first.

## Renaissance-grade reasoning (why this matters, restated for when this todo is picked up)

The core critique in that doc: "The `instrument_tags` table holds human-asserted priors...
It has no measurement procedure, no p-value, no lookback window, no expiry mechanism. A
Renaissance-grade system cannot operate on beliefs — it needs falsifiable hypotheses and a
falsification engine." Every downstream consumer of tags (`regime_group` peer-group
resolution via `tag_filter`, todo 039's proposed tag-stratified IC, the commodity/fx/
international groups in the cross-sectional-regime-model plan) inherits whatever bias is
baked into a human's guess about how strongly XLE is "commodity_energy_crude" or how strongly
a convertible-bond ETF is "fixed_income" vs "equity." Silent, unvalidated priors flowing into
regime-signal peer-group membership is the same class of hidden-bias risk already flagged for
the routing invariant fix (`AmbiguousRegimeGroupError`) — it just lives one layer upstream, in
the weights instead of the group assignment.

The doc's own measurable-primitives list (linear factor betas vs SPY/TLT/GLD/HYG/EURUSD/VIX/
CL/KWEB/IEF-SHY spread; asymmetric upside/downside/crisis betas; Hurst exponent,
autocorrelation, vol-of-vol, skewness; and a `beta_stability` meta-primitive controlling
decay/expiry) is the falsification engine: derive weight from measured beta magnitude, decay
it based on `beta_stability`, and stop treating tags as permanent human beliefs.

## Timing against the ETF universe expansion (`docs/plans/2026-06-27-etf-universe-expansion.md`)

That plan (migration 188, 58 → 79 symbols) has 4 tasks: Task 0 registers + human-tags the 21
new instruments; Task 1 backfills their historical OHLCV; Task 2 runs them through the corpus
pipeline (feature_vectors, HMM, IC); Task 3 enables the new commodity/fx regime groups.

**The calibrator must run *after* Task 1 (backfill) completes for all 79 symbols, not before,
and not just against the 21 new ones.** Its factor-beta primitives (OLS regressions against
SPY/TLT/GLD/HYG/EURUSD/VIX/CL/KWEB/IEF-SHY spread, asymmetric upside/downside/crisis betas,
Hurst/autocorrelation/skewness) all require return history — calibrating against partial or
freshly-backfilled series for the new 21 produces unstable, low-`beta_stability` estimates
that the calibrator's own design would immediately discount. Waiting for full backfill avoids
running the calibration twice (once on 58, again on 79) and avoids seeding the new instruments
with noisy weights that then have to be re-decayed.

**It does NOT need to wait for Task 3 (regime groups) or for `regime_group` (migration 187)
itself.** Confirmed in `_resolve_group_symbols` (cross-sectional-regime-model plan): group
routing matches on tag *presence* via prefix match only — `any(t.startswith(pfx) for t in tags)`
— it never reads `weight`. So calibrated vs. human-guessed weights make zero difference to
which peer group a symbol routes to today. Weight only matters where it's actually consumed:
todo 039 (tag-stratified IC, if that ever needs weighted rather than binary membership) and
any future consumer that reads `instrument_tags.weight` directly.

**Recommended sequencing:**
1. ETF expansion Task 0-2 ship first (registration, backfill, corpus pipeline) — independent,
   already scoped, no reason to block on the calibrator.
2. Once Task 2's corpus pipeline confirms full-history bars exist for all 79 symbols, run the
   calibrator once, across the full 79-symbol universe (not incrementally per new-symbol
   batch) — this is the earliest point at which every symbol has real return history to
   regress against, and it's a single pass instead of "58 now, patch 21 later."
3. ETF expansion Task 3 (enabling commodity/fx regime groups) can proceed in parallel with or
   ahead of the calibrator — it's unblocked, per the routing-doesn't-read-weight finding above.
4. After the calibrator lands, re-run todo 039's population-count check using calibrated
   (not default-1.0) weights — real weights may change which tag intersections have enough
   *effective* N to be worth stratifying IC on.

**Blocked on:** ETF universe expansion Task 1 (historical OHLCV backfill) completing for the
21 new instruments — everything else in that plan can proceed independently of this todo.
