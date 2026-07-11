# IC Quality Improvement Strategy: Sequencing and Rationale

**Date:** 2026-07-11
**Status:** Strategy — sequencing agreed with project owner, individual fixes not yet implemented
**Scope:** Synthesizes the relationship between todos 091, 093, 094, 096, 088 — why they're
sequenced the way they are, and what "improve our IC" concretely means right now. Not an
implementation plan for any single todo; each todo file carries its own technical detail.
**Author:** Synthesized from a Fable architectural review (`Plan` agent, `fable` model) of a
Sonnet-diagnosed root cause, cross-verified against the live DB before being accepted. See todo
094's git history for the full diagnostic trail, including the corrected root cause.

---

## Motivation

The project owner's working instinct going into this session — "I feel like our IC is
suboptimal" — is supported by the numbers: EIC-04's current pass rate is 54/1425 = 3.79% of
feature/regime/timeframe cells. Rather than immediately chasing "more IC" (new features, more
interaction terms, more tuning), this session applied first the more Renaissance-appropriate
question: **is the measurement and scoring machinery itself trustworthy, or would any IC number
computed on top of it be noise-chasing?** Two real defects were found doing that, both upstream
of anything that could be called "finding better IC."

This doc exists because the two defects turned out to share a trust boundary (both live in
`ic_ci_lower`/`ic_ci_upper` and the eligibility machinery built on them), which changes the
efficient order of operations — fixing them independently would mean re-running the same
expensive corpus computation twice.

## What was found, in the order it was found

1. **Todo 091** (already filed before this session): the analytic Fisher-z CI used by every
   downstream gate may be too narrow — an empirical permutation-null diagnostic found 38% of
   sampled cells SUSPECT. If true, the real EIC-04 pass rate could be *lower* than 3.79%, not
   higher.
2. **Todo 093** (in progress): backfilling `alpha_frames`/`CounterfactualTracker` to get the
   first real, trade-shaped (not just correlation-shaped) validation of the ensemble. Early
   partial data (~7% of corpus): gross P&L is slightly negative (-0.02R/trade average), and 77%
   of frames never resolve — they just time out at `max_hold_bars`.
3. **Todo 094** (root cause found and then corrected this session): `alpha_events` is 99.99%
   long-only. Initial diagnosis (Sonnet) found a real but secondary defect — a floor formula in
   `compute_quality_weight()` that compresses low-Sharpe features' weight. A Fable review,
   verified against the live DB before being accepted, found the actual cause is upstream and
   total: two sign-asymmetric gates (`ic_ci_lower > 0` eligibility filter,
   `fold_ic > 0` walk-forward criterion) exclude **100% of contrarian features** before they ever
   reach weighting — confirmed empirically: 1,527 eligible rows, zero at `ic_sign = -1`. This
   means the ensemble's sign-correction mechanism (`ic_signs` in `compute_alpha_score`) has never
   fired in production — it's dead code, not a working-but-underweighted feature.
4. **Todo 096** (filed this session, from the same Fable review): a distinct, cheaper-to-check
   concern — frame `max_hold_bars` may not be commensurate with the `lookahead_bars` each
   feature's IC was actually measured/selected at, which could independently explain some of
   todo 093's 77%-timeout pattern.
5. **Todo 088** (pre-existing): `hold_max_bars` calibration methodology doesn't distinguish
   confirmed decay from censored (no-data) cases; 25 of 36 regime/tf cells are still
   `[initial_estimate]` guesses.

## Why 091 and 094 must share one corpus re-run, not two

Both eligibility gates in `_ELIGIBILITY_BASE_WHERE` (`services/ensemble_trainer.py:92-96`) are
built directly on `ic_ci_lower`/`ic_ci_upper` — the exact quantity todo 091 is investigating for
miscalibration. Two consequences:

- If 094's eligibility redesign (make the CI-bound check sign-aware) is done **before** 091 closes,
  and 091 then finds the CI needs recalibrating, the entire candidate population computed for 094
  would need to be recomputed from scratch — the work happens twice.
- 094's fix independently requires a full `ic_engine` re-run anyway (the walk-forward criterion
  needs to become sign-consistent, which invalidates every stored `passes_walkforward` value for
  any currently-excluded negative-IC feature — that's not a small patch, it's new data).

Since a full corpus re-run is required either way, sequencing **091 first** means engineering
effort is spent once: fix the CI, then run the corrected `ic_engine` with the new sign-consistent
walk-forward criterion in the same pass, and 094's eligibility redesign reads correct
`ic_ci_lower`/`ic_ci_upper` values from the start rather than needing a second re-run.

## Agreed sequence

```
093 (backfill, in progress — baseline data collection, not a decision)
  → 091 (fix the CI — everything downstream depends on this number being right)
  → 094 (sign-symmetric eligibility + walk-forward + quality-weight redesign,
         one ic_engine re-run serves both 091 and 094)
  → shadow-mode validation of the new weight_version (mandatory — this changes
    champion scoring behavior, not a tunable parameter)
  → re-run E1-vs-E2 A/B judgment on the now-genuinely-symmetric input universe
    (the prior 20/20 result was all-long vs all-long and doesn't carry forward)
  → 096 (horizon-mismatch check — can run in parallel with the above, it's a
    read-only metadata comparison, not blocked on either fix)
  → 088 (hold_max_bars calibration — deliberately last; calibrating a
    possibly-mismatched horizon, per 096, produces a well-tuned wrong number,
    and calibrating against long-only-scored, CI-unverified frames is exactly
    the noise-chasing this whole session has been trying to avoid)
```

093 continues running in the background throughout — it's collecting baseline data that
characterizes the *current* (long-only, CI-unverified) champion, which is the correct thing to
compare the fixed pipeline against later. One caveat carried into any interpretation of 093's
results: exclude the 1,479 existing short events from short-side inference — they were emitted
by machinery structurally incapable of expressing short conviction; they're threshold-crossing
noise, not evidence about real short-side edge one way or the other.

## Calibrated expectations — what 094 does and doesn't promise

Explicitly avoiding the trap of treating a correctness fix as a P&L guarantee:

- **What's confirmed:** an entire feature population (568 significantly-negative pooled
  FDR-passing cells, pre-walk-forward, vs. 788 significantly-positive) is currently discarded
  entirely, and a real sign-correction mechanism built to use it has never executed.
- **What's not confirmed:** that recovering this population produces meaningfully better P&L.
  The positive/negative score magnitude asymmetry (2.5 vs -0.2 average, pre-fix) may partly
  reflect genuine right-skew in an 18-year mostly-rising equity corpus, not pure exclusion
  artifact — some of that asymmetry could persist even in a fully sign-symmetric system. And
  todo 093's partial data shows the *long* side, where the pipeline already works as designed, is
  itself roughly breakeven gross. Doubling the candidate feature universe doesn't by itself fix a
  signal-to-P&L conversion problem if one exists.
- **The honest framing:** 094 is a correctness fix that activates dead machinery and roughly
  doubles the candidate population size, which then lets FRAME-04 (a properly-powered
  significance test on real trade outcomes) arbitrate whether short-side edge actually exists —
  rather than the current state, where the question can't even be asked because the data was
  never generated.

## Material gaps to close before any of this ships to production scoring

Carried forward from the Fable review, not yet resolved:

1. Pre-commit the FRAME-04 decision rule for todo 093's full-corpus result *before* seeing the
   final number (halt further promotion on FAIL? re-parameterize frames? revisit thresholds?) —
   deciding after seeing -0.02R-and-dropping is how goalposts quietly move.
2. Diagnostic on the ~57-row "inconsistent" population from the superseded 094 finding (positive
   full-sample IC, negative window Sharpe) — check whether their edge is concentrated in an early,
   decayed subperiod before deciding floor-vs-exclude for that population specifically.
3. Emission threshold recalibration is part of 094's blast radius, not an afterthought — a
   symmetric score distribution changes emission volume on both sides; naive before/after
   comparisons across the fix are invalid without re-measuring.
4. Fix documentation drift in the same commits as the code: `derive_weights()`'s docstring
   ("features with non-positive IC Sharpe are excluded") is stale/inaccurate, and its `ic_sharpes`
   parameter name is misleading (it actually receives derived quality weights, not raw Sharpe
   values).

## Cross-references

Full technical detail lives in the todo files, not duplicated here: `094` (root cause, fix design,
interaction audit), `091` (CI diagnostic detail), `096` (horizon-mismatch check), `088`
(hold_max_bars methodology gap), `.planning/todos/PRIORITIES.md` (current sequencing/priority
index — this doc explains the *why*, PRIORITIES.md is the source of truth for current state).
