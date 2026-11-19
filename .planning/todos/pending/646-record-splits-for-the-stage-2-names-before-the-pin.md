---
status: pending
priority: P0
filed: 2026-11-19
source: lane 2 of the 609 chain (1d canonical for the all-ticker names), lead ruling
owner: lead
---

# Record splits for the stage 2 names before the 584 pin

## What

The all-ticker 1d load (s4) wrote raw only; canonical 1d for the 33,850 inactive instruments comes from `services.bar_derivation --stage daily --symbols ...` (the active-only daily timer never visits them). `corporate_action_current` holds no row for any inactive instrument, so their canonical closes are as traded: split jumps stay in the series and dividends are unknown (never zero). Membership needs only dates, close and volume, and as-traded close times volume is the point-in-time dollar volume, so it is not affected. Any return, residual or feature on these names is wrong until their splits are recorded, and the corpus rerun computes over every name ever in `universe_membership`.

## Done when

`ops_split_detect` (and the Massive and Yahoo witnesses of the A3 sweep) run over the stage 2 names, the confirmed splits are recorded through the split-row path with review, canonical 1d is re-derived for the affected names, and the sweep `--strict` gate covers them. The 584 pin does not move until then (add to the pin prerequisites in `scripts/ops/bars/run_609.sh` s8).

## Not blocking

The membership build (s5) and its counts.
