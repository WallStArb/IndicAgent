---
status: pending
priority: P1
filed: 2026-07-19
source: Fable 5 emission-threshold verdict review
  (docs/research/fable-2026-07-19-emission-threshold-alpha-verdict.md, Q4) -- a single
  corrupt $1000 print on a $25 ETF produced the largest number in the first EM-CAL sweep
  report and single-handedly fabricated a 1.05% mean-return stratum.
---

# Corrupt price prints pass the tradeable filter and poison mean-return analyses -- add a price-sanity guard

## Problem

`market_data_ohlcv` contains rare corrupt prints with real volume, e.g. UUP 5m
2007-06-20 19:00: `open=1000, high=1000, low=28.97, volume=200` on an ETF trading at
~$25. Because volume > 0, the bar passes `market_data_ohlcv_tradeable` (which guards
against synthetic fills, not bad prices) and flows into `forward_return_writer`,
producing `return_fast = 3.686` (a +368% five-minute "executable" return).

Measured blast radius (live scan, 2026-07-19): 27 rows across 13 (symbol, tf) pairs
with `abs(return_fast) > 0.5` (UUP 5m/15m/1h, XRT, EZU, ITA, VUG, CWB, VWO, IPO;
worst 3.73). Rare -- but in the EM-CAL sweep's 5m/low_bull stratum (N=260), the one
UUP row contributed +0.0142 to the mean, more than the entire reported 0.01052.
Rank-based IC layers are immune (Spearman); every mean-based consumer is not:
EM-CAL sweep, future FRAME-04 counterfactual PnL, Kelly sizing, any net-return
promotion gate. Silent wrong answer, textbook case.

## Fix (measure and flag; correct at the source where unambiguous)

1. **Source-side guard in `forward_return_writer`** (or its SQL): flag or NULL forward
   returns whose magnitude exceeds a per-tf plausibility ceiling, APR-backed
   (`alpha.quant.max_abs_return.{tf}`, seed e.g. 0.25/0.30/0.40/0.50 for 5m/15m/1h/1d,
   `[initial_estimate]` -- generous enough to keep every real crisis bar; the corrupt
   population sits at 0.5-3.7, real 5m ETF moves do not). Per Renaissance retention
   principles do NOT silently drop: write the flag, exclude from mean-based consumers,
   keep the row.
2. **Bar-level detection** for the underlying OHLCV prints (intra-bar high/low ratio
   and bar-over-bar jump-and-revert), logged to `integrity_monitor`
   (`monitor_type='price_sanity'`, same subject-as-stratum-key pattern as todos
   144/145). This catches the corruption before it fans out into features -- note
   features are also computed from these bars; rank-IC robustness limits the damage
   there but z-score features (momentum_z_*, volatility_rank) are contaminated for
   the affected windows.
3. **One-time cleanup:** enumerate the ~27 known rows, verify each underlying print,
   correct or tombstone, and re-run forward returns for the affected neighborhoods.

## Sizing

Todo-sized: the guard is one APR-backed predicate plus a flag column or exclusion in
the writer SQL; detection is a bounded scan; cleanup touches ~27 rows' neighborhoods.
Coordinate with Phase 162 corpus-rerun timing so the corrected rows ride the next
rebuild rather than forcing one.

## References

- docs/research/fable-2026-07-19-emission-threshold-alpha-verdict.md -- Q4, forensic
  queries in appendix
- services/forward_return_writer.py -- insertion point for the guard
- .planning/todos/pending/144-*.md, 145-*.md -- integrity_monitor flag precedent
