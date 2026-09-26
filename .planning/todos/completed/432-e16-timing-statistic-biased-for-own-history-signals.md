---
status: completed
completed: 2026-09-26
update: 2026-09-26 built as E17; H0 battery run; owner decision pending on gating criterion
priority: P0
filed: 2026-09-25
source: book_v1 refusal diagnosis (phase 183 plan 10)
---

# E16 timing statistic is biased for own-history signals; book test has no power

## What

E16's decision statistic (`timing.timing_series`) is `sum (w - wbar)(r - fbar)`, with `wbar` and
`fbar` the causal expanding means per (bar of session, symbol). For a member built from the
same cell's recent target returns (every family 1 member), `fbar` contains the returns that
built `w`, so `-w * fbar` has a nonzero expectation under H0 (a Nickell-type bias). Measured on
synthetic panels planted through the real power harness (close-finite mask, book_v1's settings):

| statistic | H0 mean t | H0 sd t | power at IC 0.002 |
|---|---|---|---|
| mean40 member, E16 as built | -2.5 to -2.7 | 1.0 to 1.2 | 1-3/12 |
| book (ridge), E16 as built | -0.4 to +0.3; -1.8 with static tilts | 1.1 to 1.6 | 0/12 (real harness: 0/51) |
| mean40, fixed statistic (below) | +0.1; +0.3 with tilts | 0.8 to 1.2 | 12/12; 6/12 with tilts |
| book (ridge), fixed statistic | -0.1; +0.2 with tilts | 1.0 | 4/12; 5/12 with tilts |
| book (equal weight), fixed statistic | +0.1 with tilts | 1.15 | 10/12; 4/12 with tilts |

"Static tilts" adds a fixed per-(slot, name) mean return, sd 0.3 of the slot's idiosyncratic sd.
H0 runs: 18 per cell; planted runs: 12. The bar is t > 2.94 (one-sided p < 0.05/30).

Consequences:
- book_v1's refusal (0/51) is produced by the statistic, not by the data's resolution. Every
  book test on an own-history family would be refused, and the book's H0 sd of up to 1.6 makes a
  pass anti-conservative in the tails.
- E16's synthetic null validation ("p between 0.28 and 0.77") hid the bias: a one-sided test
  turns a negative bias into large p.
- Family 1's evidence t (13 to 18) is biased low, not high; detection stands.

## Fix (candidate, validated in synthetic only)

`T_s = sum over (bar, name) of w * (r - fbar_L)`, no weight demean, where `fbar_L` is the cell's
mean target over sessions older than the signal's declared memory L (members: their
`slot_history_sessions`; the book: its members' memory is enough, since the ridge's pooled
coefficients depend on any one cell only about 1/3000), and a cell contributes only once
`fbar_L` has at least 60 sessions of history. Without that floor, names that list late carry
their static tilt straight into `w * r` (measured: +8.7 to +12 H0 t at L = 566).

Why it is unbiased: under H0 `w` (built from the last L sessions) and `fbar_L` (older sessions)
share no inputs, and `fbar_L` still removes a static cell mean.

## Also found

- The walk-forward ridge costs about half the t at IC 0.002 (book 2.3 vs the mean40 oracle 4.4):
  252-session windows cannot estimate member weights at this effect size. A fixed equal-weight
  combination beat it without tilts; not separable with tilts at n = 12. Needs more replicates
  before any book_v2 choice.
- Power stays below 0.5 for the book at IC 0.002 under tilts with either combiner.

## Owner decisions

1. Adopt the fixed statistic as an E16 amendment (methodology-change-ledger entry). Recommended.
2. book_v2: combiner (ridge vs equal weight) and whether IC 0.002 stays the declared power target.
   book_v1 cannot rerun (spec-once); it was refused and uncharged.

## Evidence

Scripts and logs: `logs/phase183/e16_diag/power_diag{,2..6}.py` and `.log` in worktree
`../indicagent-183-02` (local, gitignored). Implementation must add these checks as tests:
H0 mean and sd of the statistic with and without static tilts, and a late-listing name.

## Owner decisions (2026-09-26)

1. Adopted as methodology-change-ledger E17, with conditions: one `timing_series(...,
   memory_sessions=L)` for evidence, book and power; an H0 battery (at least 1,000 simulations per
   cell, late listings, static cell means, t4, per-slot effects, one cell with S1 in the loop)
   must hold size before any real run uses it; family 1's evidence records annotated as biased
   toward zero. Independent check: `scripts/analysis/e16_null_size/own_history_bias_check.py`
   (late listings take E16's H0 mean t from -0.37 to -1.37; the fix stays near 0).
2. Combiner: next book versions default to a fixed prereg-signed equal weight of standardized
   members, pinned after about 100 more replicates confirm it beats the ridge.
3. Built by the phase 183 session (owns `timing.py`). The indicagent-63 line builds, without
   touching `timing.py`: family plants out of `synthetic.py` (dependency inversion: it imports
   family 1's `SLOT_BARS`), a spec-resolved panel-transform seam replacing the `_is_legs`
   branches, and family 2's power plant (B2). Family 2's evidence run waits for this todo.

## Status 2026-09-26

Adopted as E17 (acc54358d) and built (33ca32107, 5f3de6ca1, 6702215b4). H0 battery results
and the one open owner decision (gate at twice the measured stress sizes, with the 0.3 cells as
documented-limit diagnostics) are recorded in the E17 ledger entry. Close this todo when the
owner decides and, if accepted, when family 1's re-score spec and book_v2 are pre-registered.

## Pre-registered criterion: forward-shift calibration (written before its result, 2026-09-26)

Experiment: E17 t for the mean40 member on 400 null panels per cell (null_battery panels:
hostile at 0.3, static_vol at 0.3, hostile at measured sizes), each also scored on 199 forward
shifts (returns at s paired with weights from s + k, k >= L + 1, no wraparound); shift p =
(1 + #{t_k >= t_0}) / 200.

- Valid only if the Student-t p reproduces the known failure in both 0.3 cells (rejections
  above the 99% binomial bound at 0.05 or 0.01); otherwise the experiment cannot detect the
  problem and says nothing.
- Pass: shift-calibrated rejections within the 99% binomial bound at 0.05 (<= 29/400) and 0.01
  (<= 9/400) in all three cells. Then draft the amendment "the decision p is the forward-shift
  p of the E17 t" for the owner, conditional on a real-length check at 0.00167 with > 600
  shifts.
- Fail: the parametric per-attempt calibration stage returns to the table.
- Mixed (holds at measured sizes, fails at 0.3): recorded as mixed, not rounded to a pass.

### Addendum before the result (2026-09-26 19:37, results log still empty; peer review by the family 2 session)

Forward shifts are not independent draws: neighbouring k give nearly the same weight path, so
the effective draw count is about (sessions - L) / tau, with tau the member's persistence. At
real length that is about 90 for family 1's mean40 member and about 60 for family 2's 60-session
members, too few to resolve p < 0.00167 however the experiment turns out (the MTF design's D6
wall, and the reason E16 left the shift null for the HAC t). This experiment's shift range gives
about 11 effective draws for mean40, so it is weak even at 0.05 and 0.01. The conditional step
above ("real-length check with > 600 shifts") was wrong: 600 shifts are not 600 draws.

Consequences, fixed now: a pass cannot make the forward-shift p the screen-bar decision. At most
it bears on the 0.05 forward confirmation for books whose tau leaves enough effective draws
((sessions - L) / tau >= 200, a floor stated here). A fail or mixed result leaves the
measured-size route (gating at twice the measured stress sizes, measured by the runner and
recorded, not constants) as the path, with the 0.3 cells as documented limits.

### Result (2026-09-26 19:39), judged by the criterion above

| cell (400 panels) | Student 0.05 | Student 0.01 | shift 0.05 | shift 0.01 |
|---|---|---|---|---|
| hostile at 0.3 | 9.5% (38) | 3.0% (12) | 10.0% (40) | 3.7% (15) |
| static x vol at 0.3 | 9.0% (36) | 2.5% (10) | 11.5% (46) | 3.5% (14) |
| hostile at measured sizes | 6.0% (24) | 1.5% (6) | 7.2% (29) | 2.2% (9) |

Valid (Student reproduces the 0.3 failure). Outcome: mixed, and the shift p is more
anti-conservative than Student in every cell. The forward-shift route is rejected; the
measured-size route stands for the owner's decision (E17 ledger entry).

## Closed 2026-09-26

Owner decided E17's gating criterion (option C, 1783731c1): measured-size gating as a checked
precondition, built under todo 447. The statistic, battery, combiner and family 1 annotation are
on main; attempts continue under todo 442; dependencies for phases 186 and 187 under todo 448.
