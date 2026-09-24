---
status: pending
priority: P1
filed: 2026-09-24
source: Phase 179 V4 run, logs/phase179/v4_*.json (trial snapshot 668f4b07dab9bebb, main c9ea43113)
---

# Phase 179 V4 fidelity gap: harness cells get a different row set than production for some labels

## What

V4 refits at T = 2025-12-24 in production mode and compares every pooled 1d row with
production's fresh `feature_ic_scores` (window 2025-12-24 05:15 UTC). Keys match exactly (31,800
rows both sides) but about 8% of rows differ on deterministic fields, starting with
`n_independent` (3,240 rows), so some cells are fed different rows. Concentrated in specific
labels (equity `high_bull`/`low_bull`, commodity `up_secondary_backwardation`, ...); about 92%
of rows match to 1e-6, so most assembly is right. Blocks FIDELITY = OK and the freeze.

## Suspects, in order

1. Label-to-session mapping: the snapshot maps `market_regimes` labels per UTC date; production's
   cell selects `market_regimes.ts <= window end` for the label and joins `fv.bar_ts = mr.ts`
   exactly. Groups whose `ts` isn't midnight UTC, or with gaps, gain or lose rows.
2. Row filter: production INNER-joins `forward_returns` in the cell fetch; the snapshot keeps
   `has_fr` rows per group. Check which rows each side keeps when `complete_*` is false.
3. Routing: `exclude_symbols` and universe (compute dimension) differences between the
   snapshot's routing and ic_engine's at recompute time.
4. Data drift between the trial snapshot and recompute time.

## What to do

Pick one bad cell (e.g. equity `high_bull`, lookahead 1), list its (symbol, bar_ts) rows from
the snapshot vs production's `chunk_sql` for the same group and label, diff them, fix the
snapshot or refit assembly, rerun V4 (`python -m scripts.analysis.sleeve_walk_forward.v4
--snapshot DIR`, about 90 s). Pin the RNG-field tolerance in pre-reg 12.1 once deterministic
fields match.
