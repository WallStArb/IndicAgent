---
**Created:** 2026-07-11
**Area:** intelligence
**Type:** correctness
**Priority:** P1 — cheap to check, potentially explains a real measurement gap in todo 093's
partial results
**Effort:** S — a diagnostic query first; fix scope depends on what it finds
**Benefit:** Determines whether the 77%-of-frames-time-out pattern seen in todo 093's partial
backfill is a genuine calibration gap (already tracked, todo 088) or a distinct apples-to-oranges
bug — each has a different fix
**Risk:** low — read-only diagnostic
---

# 096 — Verify frame `max_hold_bars` is commensurate with the lookahead each feature's IC was
actually measured/selected at

**Found:** 2026-07-11, flagged during a Fable architectural review of todo 094 (the long/short
imbalance root-cause fix), as a distinct, independently-actionable gap worth checking before
trusting any post-fix FRAME-04 re-run.

## The concern

`select_features_per_stratum()` (`src/intelligence/ensemble/feature_selector.py`) picks a
**specific `lookahead_bars` per feature** — the horizon at which that feature's IC was strongest/
most reliable, per the Lookahead disambiguation rule ("never average across lookaheads — that
dilutes the signal"). This is the horizon the ensemble's predictive claim is actually calibrated
against.

But `CounterfactualTracker`'s frame hold horizon comes from a completely separate source: the
`alpha.frame.hold_max_bars.{regime}.{tf}` APR key (migration 195 origin), most of which (25/36
regime/tf cells per todo 088) are still unvalidated `[initial_estimate]` guesses, not derived
from — or even cross-checked against — the `lookahead_bars` values features were actually
selected at.

**If a stratum's features were selected because they predict well at, say, 60 bars out, but that
stratum's `hold_max_bars` is set to 20 (or 200), `CounterfactualTracker` is not measuring the
alpha the ensemble gates actually certified.** This would produce exactly the pattern seen in
todo 093's early partial backfill results: 77% of frames never resolve (hit neither stop nor
target) and just time out with near-zero average P&L — consistent with a hold window that's
mismatched (too short to let the real horizon play out, or too long and dominated by noise after
the real predictive window has passed) rather than (or in addition to) `hold_max_bars` simply
being an uncalibrated guess in the todo 088 sense.

This is a **different failure mode than todo 088**: 088 is about the *methodology* for how
`hold_max_bars` gets calibrated (confirmed-decay vs. censored-data ambiguity in the median
aggregation). This todo is about whether `hold_max_bars`, however it was set, is even measuring
the same horizon the feature-selection layer claims predictability at. Both could be true
simultaneously and compound.

## Proposed check

For a sample of (symbol, tf, regime) strata, compare:
1. The `lookahead_bars` value(s) actually selected for that stratum's top-weighted features
   (`ensemble_weights` or the `selected` rows from `select_features_per_stratum`).
2. The `hold_max_bars` value applied to frames in that same stratum
   (`alpha.frame.hold_max_bars.{regime}.{tf}`).

If these are systematically mismatched (not just noisy around each other, but structurally off —
e.g. features consistently selected at long lookaheads while `hold_max_bars` is set short, or
vice versa), that's the primary lever to fix before any further `hold_max_bars` calibration work
(todo 088) is worth doing — recalibrating a fundamentally mismatched horizon just produces a
better-tuned wrong number.

## Proposed next steps

1. Run the comparison query above across a representative sample of strata (not just the 5-6
   symbols todo 093 has processed so far — wait for more coverage, or accept a partial read with
   that caveat stated explicitly).
2. If mismatched: decide whether `hold_max_bars` should be derived FROM each stratum's selected
   `lookahead_bars` (coupling the two) rather than being an independent APR key family, or
   whether they're legitimately meant to differ (e.g. hold horizon includes a deliberate buffer
   past the predictive window) — this is a design decision, not just a data fix.
3. Fold the finding into todo 088's scope if it turns out to be the same underlying issue viewed
   from a different angle; keep separate if it's genuinely a distinct bug.

**Gate:** none — runs against `ensemble_weights`/APR config that exists today. Best done once
todo 093's backfill has more coverage than the current ~7%, but the query itself doesn't depend
on 093 finishing (it compares metadata, not frame outcomes) — could run in parallel right now for
an early read, with the caveat that early symbols may not be representative.
