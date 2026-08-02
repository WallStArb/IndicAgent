# Quarterly Seasonality / OPEX Risk-Off — Idea

**Status:** Idea — not planned. Needs a Fable rigor pass before promotion to `docs/research/`.
**Author:** Claude (Sonnet 5), interactive session, 2026-07-12 — not a Fable dispatch. Empirical
claims below were verified live against the DB in this session; the pattern itself is
**unvalidated** (see "What was actually tested" — the initial read was retracted the same
session for a statistical error, kept here as a worked cautionary example, not a result).
**Origin:** User-observed pattern, stated as an impression, not a claim: "we could see market
sell offs in weeks 9-11 [of the quarter]... some risk off I have seen or mechanical selling —
maybe it also coincides with quarterly OPEX as well."

---

## The hypothesis (two distinct claims, need separate tests)

1. **General risk-off window:** broad market weakness in roughly weeks 9-11 of the calendar
   quarter (the back half of the quarter's final month, ahead of earnings season), followed by
   a rebound into quarter-end (window dressing) and continued strength as earnings season
   delivers beats/estimate revisions.
2. **OPEX-specific, mechanically precise:** the same window plausibly coincides with quarterly
   ("quad-witching") options/futures expiration — the 3rd Friday of March/June/September/
   December, always in the quarter's final month. If real, this would be a mechanical
   hypothesis (dealer gamma-hedging unwind, block-trade positioning ahead of a known
   expiration), not a sentiment story — closer to the kind of edge Renaissance-style shops
   built on than a narrative-driven signal.

These are different claims requiring different evidence. (2) is more falsifiable and cheaper to
test precisely; (1) is broader and vaguer.

---

## What already exists (no new data needed for either hypothesis)

Confirmed live in code, not assumed:

- `quarter_position` (`src/intelligence/feature_factory.py:3084`, `_quarter_position()`) — continuous [0,1] linear
  position within the quarter, 0.0 at start, ~1.0 at end. Docstring/schema comment already
  references "earnings/rebalancing cycle" as the motivating use case — this feature was built
  with something like this hypothesis in mind, never tested against it.
- `dow_sin`/`dow_cos`, `week_of_month_sin` (`feature_factory.py`) — together these
  deterministically identify OPEX Friday: the 3rd Friday of any month always falls on day
  15-21, and `week_of_month = (day-1)//7+1` maps day 15-21 to week=3 in every case (verified
  by direct calculation, not assumed). No new primitive needed to identify quad-witching
  Friday specifically.
- `hour_of_day_sin`, `day_of_month_sin`, `week_of_year_sin`, `month_sin/cos`, `session_time_pos`
  — full calendar-coordinate primitive set, all shipped in Phase 142.5 (migration 206).
- Regime stratification: **two systems**, not one. The "bull markets" framing in the original
  hypothesis maps to the **cross-sectional** regime model (`equity_regime_model.py` →
  `market_regimes.regime_label`, 9-state `{low/mid/high}_{bull/neutral/bear}`), not the
  per-symbol HMM (`regime_writer.py` → `feature_vectors.regime`, 5-state trending/ranging).
  `ic_engine.py` already computes stratified IC against both for every feature it measures —
  no new measurement infrastructure needed once a candidate primitive exists.

**What's missing is specifically a primitive shaped to test this, not any new data or new
measurement machinery.**

---

## What was actually tested (this session, retracted — worked example of what NOT to do)

An ad hoc SQL check (join `feature_vectors.quarter_position` to `forward_returns.return_mid`,
5-trading-day-forward `executable_open_to_open`, bucketed by `quarter_position` range) found a
shape matching the hypothesis closely: negative mean forward return in the hypothesized
selloff window (t≈-4.0 unconditional, -4.5 bull-only), positive in the rebound/earnings
windows (t up to +22.8), all with large raw N (17K-117K rows per bucket).

**This was over-claimed as "confirmed" in the moment and had to be retracted in the same
session** for three compounding problems, in order of severity:

1. **Naive-N trap — the dominant issue.** Directly quantified: the -4.5 t-stat's bucket
   (`quarter_position` 0.77-0.85, bull-only) has 18,694 raw rows but only **54 distinct
   quarter-episodes** (267 calendar-days, 80 symbols moving together within each episode).
   Treating 18,694 rows as independent when the true cluster count is ~54 inflates the t-stat
   by roughly √(18694/54) ≈ 18.6x. A t of -4.5 under proper day/episode clustering could
   plausibly be t ≈ -0.24 — not significant. **This is the exact trap
   `docs/plans/SHADOW-REVIEW.md`'s day-clustered bootstrap and Phase 143.1's entire
   circular-block-bootstrap-CI fix exist to prevent** (see `docs/plans/methodology-change-ledger.md`
   E6) — it was reproduced here in an ad hoc side query the same night the official pipeline
   was being fixed for precisely this class of error.
2. **Un-pre-registered bucket boundaries.** Cutpoints (0.15/0.50/0.77/0.85/0.92/0.97) were
   chosen after two passes of looking at the data's shape, not fixed in advance — the same
   "goalposts can't move after seeing the result" violation `SHADOW-REVIEW.md` and E6 both
   explicitly freeze against.
3. **Built on an uncalibrated foundation.** The bull-only filter uses
   `equity_regime_model.py`'s VIX/breadth cut points, which are still `[initial_estimate]`
   guesses, never empirically fit (see `.planning/todos/pending/092-equity-regime-model-threshold-calibration.md`,
   already flagged as a live-path IC suspect independent of this idea).

**Do not cite the specific t-stats/effect sizes above as evidence — they are a demonstration
of a measurement error, not a result.** The only thing this exercise actually establishes: the
*direction* of the hypothesis is plausible enough to be worth testing properly, and the
project's own existing rigor apparatus (built for exactly this class of overlapping-window,
low-independent-N problem) has to be the thing that tests it, not another ad hoc query.

---

## What NOT to do next (explicit anti-pattern, per this project's own stated conventions)

Do **not** build a bespoke primitive shaped to the specific turning points discovered in the
retracted analysis above (e.g., "reflect around `quarter_position`=0.885"). That is precisely
the theory-laden, in-sample-fit anti-pattern `docs/research/signal-renaissance-primitives-ohlcv.md`'s
"No State, No Theory, No Hand-Holding" section already bans — hand-baking a specific,
unvalidated, single-sample-derived event boundary into a feature definition is `is_opex_day`
with extra steps, and carries the same theory-bias risk the doc explicitly warns against.

---

## Open questions for Fable

1. **Primitive design.** Is the right candidate (a) a generic, symmetric, parameter-free
   transform of `quarter_position` (e.g. squared distance from quarter midpoint, or a
   genuinely new period-3 "month-of-quarter" sin/cos primitive analogous to `month_sin` — no
   such primitive currently exists, only period-12/31/52/5-ish calendar coordinates are
   built), or (b) treating this as an ordinary interaction-primitive candidate
   (`quarter_position × <existing atomic>`) following the exact methodology of the 8 already-
   measured hand-picked interactions from `.planning/todos/completed/037-interaction-primitives-pilot-ic-test.md`?
   Option (b) has the advantage of reusing already-built, already-validated infrastructure
   with zero new measurement code.
2. **OPEX-specific test design.** A precise "is this OPEX Friday" primitive (deterministic
   from `dow` + `week_of_month`, confirmed above) is a much cleaner, lower-researcher-degrees-
   of-freedom test than the fuzzy `quarter_position`-range approach used in the retracted
   analysis. Should this be tested independently of, or combined with, the broader
   `quarter_position` seasonal hypothesis?
3. **Statistical power under rare-event frequency.** Quad-witching happens 4x/year — on the
   order of 60-80 independent episodes across the corpus's full history, fewer once split by
   regime (the retracted analysis's own bull-only cut only found 54 quarter-episodes for a
   *3-week-wide* bucket; an OPEX-day-only cut would be narrower still). Is there enough power
   to say anything with this corpus's history length, or is this better filed as "revisit once
   more history accumulates"?
4. **Test methodology.** Should this go through the existing interaction-primitives pilot
   pipeline (todo 037's methodology: add as ordinary Feature Factory column, measure partial
   IC after controlling for parent atomics, BH-FDR) — or does the low-episode-count problem
   need something closer to `SHADOW-REVIEW.md`'s day/episode-clustered bootstrap specifically,
   which the standard IC engine doesn't yet apply to `feature_vectors`-level atomic/interaction
   features (only to `alpha_frames` P&L per `SHADOW-REVIEW.md` criterion 2)?
5. **Scope relative to Phase 150.** Does this belong inside Phase 150 (Feature Primitives
   Expansion + Interaction Layer) as one more candidate in that phase's existing scope, or is
   the rare-event/low-power nature different enough to warrant separate treatment?

## References

- `docs/research/signal-renaissance-primitives-ohlcv.md` — sibling doc, "No State, No Theory,
  No Hand-Holding" section, existing calendar primitive inventory
- `.planning/todos/completed/037-interaction-primitives-pilot-ic-test.md` — the methodology
  precedent for testing a new interaction/derived primitive cheaply before committing to full
  infrastructure
- `docs/plans/SHADOW-REVIEW.md` — day-clustered bootstrap methodology (criterion 2), the
  correct pattern for handling overlapping/non-independent observations
- `docs/plans/methodology-change-ledger.md` E6 — the same overlapping-observation problem,
  fixed in the official IC engine pipeline the same night this idea was retracted for the
  identical error
- `.planning/todos/pending/092-equity-regime-model-threshold-calibration.md` — the
  uncalibrated regime-boundary dependency this idea's bull-only cut inherits
