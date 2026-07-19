---
status: pending
priority: P1
filed: 2026-07-19
source: Fable 5 review (docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md,
  Q1) + this session's horizon-response diagnostic run
  (scripts/ops/alpha/ops_lookahead_horizon_response.py, 20-symbol sample)
---

# `alpha.ic.lookahead.{fast,mid,slow,extended}` is one uniform bar-count grid across
# all 4 tfs; empirically it breaks 1h/15m/5m's slow/extended tiers -- needs per-tf grids

## Problem

Confirmed live (`config_state`/`config_schema`): `alpha.ic.lookahead.{fast,mid,slow,
extended} = 1/5/20/60` bars, every one `[initial_estimate]`, never empirically
calibrated despite being tagged "ML learning target" in its own description. The same
four bar-counts apply identically to 5m/15m/1h/1d, never tf-scaled the way `_tf_window()`
scales day-denominated regime-model window params, or the way `alpha.ic.bootstrap_block_size`
is already tf-differentiated.

This is worse than an inconsistent-economic-horizon smell: it collides with
`forward_return_writer`'s intraday same-ET-session completeness gate (a deliberate,
correct Invariant-1 constraint -- overnight gaps aren't tradeable for intraday entries)
and structurally breaks a third of the design grid. Measured live from `feature_ic_scores`
before this session's fix work: **1h slow/extended have ZERO rows anywhere in the table;
15m extended has ZERO rows; 5m extended is measured on ~20% of bars (morning-entry-only,
a silent selection bias nothing downstream flags).**

## Empirical evidence (this session)

Ran a new diagnostic, `ops_lookahead_horizon_response.py` (read-only, computes forward
returns directly via the same LEAD()-based construction and same-ET-session completeness
gate as production, across a dense per-tf horizon grid, pooled across all regimes). Full
methodology in the script's docstring. 20-symbol bounded sample, vintage
`2025-12-24 05:15:00+00:00`:

| tf | horizon_bars | completeness | n_valid | median\|IC\| | median CI halfwidth |
|---|---|---|---|---|---|
| 5m | 1 | 0.973 | 389144 | 0.0030 | 0.0031 |
| 5m | 26 | 0.634 | 253771 | 0.0104 | 0.0039 |
| 5m | 39 | 0.462 | 184923 | 0.0103 | 0.0046 |
| 5m | 66 | 0.124 | 49569 | 0.0124 | 0.0088 |
| 15m | 1 | 0.922 | 368832 | 0.0027 | 0.0032 |
| 15m | 10 | 0.572 | 228607 | 0.0083 | 0.0041 |
| 15m | 22 | 0.111 | 44302 | 0.0105 | 0.0093 |
| 1h | 1 | 0.661 | 253663 | 0.0047 | 0.0039 |
| 1h | 4 | 0.163 | 62763 | 0.0066 | 0.0078 |
| 1h | 6 | **0.000** | 0 | n/a | n/a |
| 1d | 1 | 1.000 | 83895 | 0.0046 | 0.0068 |
| 1d | 40 | 0.991 | 83115 | 0.0109 | 0.0068 |
| 1d | **60** | 0.986 | 82715 | **0.0122 (peak)** | 0.0068 |
| 1d | 90 | 0.980 | 82115 | 0.0078 | 0.0068 |

Full curve (all grid points, not just the excerpt above): see the diagnostic's own
stdout, not re-persisted anywhere -- re-run `python
scripts/ops/alpha/ops_lookahead_horizon_response.py` to reproduce (read-only, no writes).

**Reading the curve (magnitude and CI width together, not magnitude alone -- a rising
median\|IC\| with a proportionally-widening CI is consistent with pure noise from
shrinking N, not real signal growth):**

- **1d is the one tf where today's guessed grid holds up.** No session boundary, so
  completeness stays 98-100% even at horizon=90; CI half-width stays flat (~0.0068)
  across the whole grid since n_valid barely shrinks (84K -> 82K). IC genuinely peaks
  at horizon=60 (0.0122) and declines by 90 (0.0078) -- a real decay curve, not noise.
  Today's `extended=60` is close to the empirical optimum for 1d specifically. No urgent
  change needed here.
- **1h has almost no room for 4 distinct horizon tiers within one session.**
  Completeness is already down to 66%/49% at horizon 1/2, collapses to 16% at 4, and is
  literally impossible at 6 (7 bars/session -- matches the prediction exactly). A
  `fast`/`mid` pair around 1-2 is the honest ceiling; `slow`/`extended` cannot exist as
  session-bounded measurements at 1h without accepting a badly biased, near-empty
  population.
- **15m and 5m show rising IC alongside collapsing completeness at their longest
  grid points** (15m/22: IC 0.0105 but completeness 11%, CI 3x wider than horizon=1;
  5m/66: IC 0.0124 but completeness 12%, CI ~3x wider). This is genuinely ambiguous on
  a 20-symbol sample -- could be real signal still building toward the session boundary,
  could be the classic noise-inflation-as-N-shrinks pattern. Flagging as unresolved
  rather than claiming either reading; full-corpus reproduction (Step 1 below) should
  settle it with real power instead of guessing from a 20-symbol pass.

## Fix

**Step 1 (this session, done):** the horizon-response diagnostic exists and produced
the table above. Re-run at full 80-symbol corpus scale before locking any production
grid change -- this todo's numbers are a 20-symbol proof of the method and the
qualitative story (intraday coverage collapse is real and severe), not a final
calibration.

**Step 2 (decision, per Fable's framing -- recommend (i) unless full-scale data shows
otherwise):** for intraday tfs, accept session-bounded per-tf grids honestly reflecting
what one session can measure, rather than (ii) inventing an overnight-inclusive return
type. Candidate per-tf grids to validate against the full-corpus re-run (session-bounded,
picked to keep completeness in a reasonable range -- NOT locked, needs full-N
confirmation):

| tf | fast | mid | slow | extended (candidate) |
|---|---|---|---|---|
| 5m (78/session) | 1 | 5-6 | 12 | 26-39 (needs full-N read on the 39-66 ambiguity above) |
| 15m (26/session) | 1 | 2 | 5 | 10 |
| 1h (7/session) | 1 | 2 | -- | -- (no session-bounded slow/extended tier survives; needs its own design decision, not a number) |
| 1d | 1 | 5-10 | 20-40 | 60 (keep -- empirically near-optimal already) |

**Step 3 (apply at next corpus rebuild, rides Phase 162, pre-registered in
`docs/plans/methodology-change-ledger.md`):** the gradient-naming design already pays
for this -- `forward_returns` columns are scale-named, `feature_ic_scores` stores
`lookahead_bars` explicitly, `_build_forward_return_sql` is already invoked per tf.
Making the APR keys per-tf (e.g. `alpha.ic.lookahead.{tf}.{scale}`, or a JSON per-tf
grid) requires no schema migration. **Do NOT change `alpha.ic.lookahead.*` now** -- this
would invalidate every fingerprint/checkpoint mid-corpus and force an unplanned
recompute; apply only at the next scheduled rebuild window, same discipline as Phase
162's own fingerprint-timing decision.

**1h's missing slow/extended tier is a real open design question, not just a number to
pick** -- worth its own explicit decision (accept 1h as effectively fast/mid-only, or
retire it from slow/extended-tier ensemble eligibility entirely, or something else) at
Step 2/3 time, not silently defaulted.

## Sizing

Todo-sized for Steps 1-2 (diagnostic exists, full-scale re-run is cheap -- same script,
`--max-symbols 80`). Step 3 (the actual APR/production change) is properly scoped to
ride the next corpus rebuild, not a standalone effort -- no new sizing needed beyond
what that rebuild already costs.

## References

- `docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md` Q1 --
  full analysis this todo implements Step 1-2 of
- `scripts/ops/alpha/ops_lookahead_horizon_response.py` -- the diagnostic (read-only,
  reusable, `--max-symbols`/`--max-bars-per-symbol`/`--tf` bound cost)
- `services/forward_return_writer.py` `_build_forward_return_sql` -- the production
  construction this diagnostic mirrors (same LEAD() pattern, same completeness gate)
- `services/ic_engine.py` `ICEngineConfig.from_apr` (~line 537-540) -- where the
  current flat lookahead dict loads; the eventual Step-3 change site
- `.planning/todos/pending/097-vol-normalized-return-target-pooled-ic.md` -- Component
  F, whose worst-stratum finding (1d/extended) motivated re-checking this grid; Fable's
  review found the coupling is real but resolvable by conditioning Component F's
  verdict on stratum reliability, not by sequencing this todo first (see Q3b in the
  Fable doc above)
