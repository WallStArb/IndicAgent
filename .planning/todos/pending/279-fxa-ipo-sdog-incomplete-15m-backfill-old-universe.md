---
status: pending
priority: P2
filed: 2026-08-08
source: found while sanity-checking the alpha_score single-security diagnostic
  (project_single_security_alpha_refinement_gating_2026_08_08 memory) -- SDOG's
  significantly-negative IC result prompted a completeness check across all 80
  symbols in that population. Downgraded P1->P2 same day after a second pass found
  the likely explanation is genuine thin liquidity, not a real backfill defect.
---

# FXA/IPO/SDOG have lower 15m bar counts than their universe peers -- likely genuine
# thin liquidity, not an incomplete backfill. `backfill_status`'s own bookkeeping is
# still wrong regardless (rows_written > theoretical_max).

## What

Checked 15m row counts across all 80 symbols used in `gate1_signal`'s original
population, OOS window (`bar_ts >= 2025-12-24`), against `market_data_ohlcv_tradeable`
(real bars only). 77/80 sit at 100% of the max observed row count (3,809). Three
don't: FXA (52.5%), IPO (77.9%), SDOG (82.8%).

## Root-cause check (2026-08-08, same session) -- revises the original hypothesis

All three, plus 18 batch-mates, were added in one shot at the exact same timestamp
(`instruments.created_at = 2026-07-02T03:29:58.204064Z`) -- not part of the
currently-tracked client-43 backfill (different, newer symbol list) and not the
original ~80-symbol universe either. Checked the full 21-symbol batch's completeness,
not just the 3 flagged ones:

| symbol | pct of max | symbol | pct of max |
|---|---|---|---|
| FXA | 52.5% | BTAL | 99.8% |
| IPO | 77.9% | DBA | 99.9% |
| SDOG | 82.8% | DBC/IYT | 100.0% |
| FXE | 96.1% | EWG/EZU/PPLT/EWZ/FXI/EDV/VWO/MCHI/UUP/VYM | 100.0% |
| SPHB | 99.5% | | |
| DBB | 99.6% | | |

**This is a smooth gradient correlated with real-world instrument liquidity, not a
binary pass/fail split** -- the 3 currency ETFs in the batch (FXA, FXE, FXY) cluster
toward the low end, small/niche names (IPO, SDOG, SPHB) too, while large heavily-
traded country/commodity ETFs (EWZ, EZU, FXI, VWO, MCHI, DBC, etc.) all sit at
99.5-100%. A fetch/backfill defect would more plausibly produce a sharp cutoff (clean
data then a hard stop), not a smooth liquidity-correlated gradient. FXA's year-by-year
bar counts (2006-2026) show continuous data in every year with no missing chunk,
also inconsistent with an interrupted fetch. No fetch-error log evidence found either
way -- the original 2026-07-02 backfill logs appear to have rotated out, so this
isn't fully certain, but the evidence points toward genuine thin liquidity (currency
and small/niche ETFs legitimately don't trade every 15-minute window) rather than a
real gap.

**Practical implication, reversed from the original filing**: if genuine, this does
NOT undermine the alpha_score single-security diagnostic's SDOG finding -- excluding
real non-trading windows from an IC test is correct behavior, not an artifact, and
the bootstrap CI already accounts for the resulting smaller N (SDOG's result cleared
significance despite the wider interval that implies).

**What IS still confirmed wrong, independent of the liquidity question**:
`backfill_status` shows `status='complete'`, `fetch_complete=true` for all three at
15m, with `rows_written` (85,790 for SDOG) *exceeding* `theoretical_max` (65,268) --
a real bookkeeping bug in that table (a cumulative counter across multiple runs being
compared against a single-pass ceiling, or similar), not just the already-known
staleness/no-client-43-coverage issue.

## What to do

1. **Not urgent**: confirm genuine-liquidity hypothesis with more certainty only if a
   future backfill run's logs are available to check directly (don't go looking for
   already-rotated logs specifically for this).
2. **Real, standalone bug**: `backfill_status`'s `rows_written > theoretical_max`
   inconsistency for these (and possibly other) rows should be understood/fixed --
   separate from the liquidity question, this table's own correctness is
   compromised for anyone who queries it expecting a completeness signal.

## Sizing

Small. Mostly done as an investigation; remaining work is the `backfill_status`
bookkeeping fix, not a data backfill.
