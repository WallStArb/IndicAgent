---
status: pending
priority: P0
filed: 2026-09-26
source: owner decision on E17's H0 battery gating criterion (methodology-change-ledger E17, option C)
---

# E17 per-family static-size guard: refuse a family whose static effects exceed the gated size

## What

E17's H0 battery holds size with its gating cells at twice the static effect sizes measured on
family 1 and family 2 (static per-(slot or leg, name) mean sd about 0.019 to 0.045 of the
idiosyncratic slot sd; time-of-day means up to about 0.06). At 0.3 it is oversized (book 11
rejections in 1,000 at 0.00167). The owner chose option C: keep the measured-size gate, and make
it a checked precondition for every family instead of an assumption.

Build, in the phase 183 runner (owner: the phase 183 lane):

1. Before a family's first real run, measure on its own panel, by the same method the battery
   used: the static per-(slot or leg, name) mean sd and the time-of-day mean sizes, each as a
   fraction of the idiosyncratic slot sd.
2. Refuse the run, the same way the power refusal does, if any measured size exceeds the gated
   size of the battery cells. The refusal names the offending measure and the battery a family
   that large would need.
3. Record the measurements and the gate in the family's evidence record.

## Done when

- The runner refuses a synthetic family whose planted static means exceed the gate, and passes
  one below it (unit tests).
- Family 1's and family 2's measurements are recorded and pass.
- The gate values come from the battery's recorded configuration, not a second hand-typed copy.

## Requirements added 2026-09-26 (phase 183 session, from the family 2 session's review)

- Measure on the panel the run scores: the output of `runner._analysis_panel` (after the
  members' universe filter, `panel.total_return`, and any transform such as session legs), never
  the S0 source panel.
- Split segments (`<sym>~<k>`) count as separate names, as the run sees them.
- Measured on residual returns or on raw cross-sectionally demeaned returns: pick the one the
  battery's gated sizes were measured on (raw, cross-sectionally demeaned slot or leg returns,
  2010 onward) and record which.
- Gate values are read from the battery's recorded configuration
  (`null_battery.MEASURED_*`-derived gating cells), never a second hand-typed copy; the
  `MEASURED_*` constants become the recorded outputs of this measurement for the families they
  came from.
- Unit test with a `total_return` spec where the measurement differs from price-only.
- Refusal is uncharged and recorded like the power refusal, with the measured sizes in the
  evidence record.

## Closed 2026-09-27

Built: `src/intelligence/research/static_sizes.py` (measurement, gate, exceedances, record),
`static_gate()` in each battery module (elementwise max over the gating cells, so the gate is
never typed twice), and the runner check in `run_family` and `run_book` after S0 and before S1.
A family module with no battery is refused before the ledger; a family above the gate ends
`refused` (uncharged) with its sizes; a pass records them in every evidence record (schema v4).
Driver for a pre-run look: `scripts/research/static_sizes.py --spec <spec>`.
Tests: `tests/unit/research/test_static_sizes.py` (planted above the gate refused, null passes,
real-mode refusal recorded and uncharged, total_return legs differ from price-only, split
segments counted as names).

Method: raw cross-sectionally demeaned cell returns, 2010 on; reproduces family 1's recorded
0.019 / 0.21 / 0.0096. One deviation, recorded in the ledger: the time-of-day size is gated net
of sampling noise (the raw rms is mostly noise and refused null test panels).

Measured (logs/phase183/static_sizes/): family 1 pooled static 0.0191 (gate 0.038), time of
day 0.0036 net (gate 0.0192); family 2 total-return legs, 189 names: static 0.054, 0.049,
0.016 (gates 0.088, 0.090, 0.034), time of day 0.052, 0.020, 0 (gates 0.118, 0.053, 0.025).
Both pass. The `MEASURED_*` constants stay as the sizes the batteries ran at; each module's
comment records the measurement.
