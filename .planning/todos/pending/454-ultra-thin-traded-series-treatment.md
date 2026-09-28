---
status: pending
priority: P3
filed: 2026-09-28
source: phase 185 plan 10 historical scrub pass (docs/research/scrub-historical-pass.md, todo 052 defect-class sweep)
---

# Ultra-thin traded series: decide the treatment (RCAT-class)

## What

The historical 1d scrub pass surfaced a name class that clears the
`volume > 0` traded-bar bar while carrying no price information: RCAT's entire
1d history trades volume <= 30 shares for years, with consecutive prints
jumping orders of magnitude (559 -> 7,462 -> 2,238 -> 11,194). Six of the top
20 largest 1d log moves beyond ln(1.5) are this one name. No scrub rule fires
(vol_scaled_jump needs a 61-bar rolling window; the series is too sparse),
which is correct per rule definition, but every downstream consumer reading
`market_data_ohlcv_tradeable` sees a series whose close-to-close moves are
print noise.

## Why it matters

Never-filter-raw-signal says these bars stay stored and visible; that is not
in question. The question is whether compute/measurement eligibility should
read a thinness dimension, the same way `compute_eligible` already splits
backfill/compute/live scope, or whether an informational scrub rule should
flag the class and let research decide.

## How

1. Measure the class first: per-name 1d median volume and bar count across
   the 931-name universe; publish the distribution (how many names sit at
   median volume < some floor, e.g. 1,000 shares).
2. Decide the treatment with the owner: universe eligibility dimension
   (follows migration 337's split pattern) vs informational rule in the
   scrub library (needs a RULE_VERSION bump).
3. Either way: raw bars untouched, flags informational, no quarantine.

## Dependencies and constraints

- Depends on: nothing open; the measurement can run now.
- Blocked by: nothing.
- Do not: delete or quarantine any RCAT-class bar (D-09; they are real
  trades, just tiny).
