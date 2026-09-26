---
status: pending
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
