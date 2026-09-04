---
status: pending
priority: P1
filed: 2026-08-08
source: found while writing docs/foundation/instrument-data-model.md -- checked
  instrument_tags coverage for the 151 symbols added in the 2026-08-05/06 universe
  expansion, expecting a thin-but-fine result and instead found most of them fail
  regime-group routing entirely.
---

# 76% of the 151 newly-expanded-universe symbols carry no `exposure`-prefix tag and are silently excluded from regime-stratified IC -- sharpens todo 280 at much larger scale

## What

Two related, verified gaps in `instrument_tags` for the 151 symbols added in the 2026-08-05/06
universe expansion (`instruments.created_at >= '2026-08-05'`):

**1. Routing-critical exposure tags are missing for most new symbols (the urgent part).**
`ic_engine.py`/`cross_sectional_regime_model.py`/`equity_regime_model.py` (ITR's three live
consumers, per `docs/foundation/instrument-tag-registry.md` §Consumers) all resolve peer groups
by prefix-matching `instrument_tags` against `eq_*`/`intl_*`/`fi_*`/`fx_*`/`commodity_*`. Verified:

```sql
SELECT count(*) FILTER (WHERE has_exposure_prefix), count(*) FROM (
  SELECT i.symbol, EXISTS (
    SELECT 1 FROM instrument_tags t WHERE t.symbol = i.symbol
      AND (t.tag LIKE 'eq_%' OR t.tag LIKE 'intl_%' OR t.tag LIKE 'fi_%'
           OR t.tag LIKE 'fx_%' OR t.tag LIKE 'commodity_%')
  ) AS has_exposure_prefix
  FROM instruments i WHERE i.created_at >= '2026-08-05'
) sub;
-- 36 | 151
```

Only 36/151 (24%) have a routing-eligible exposure tag. **115/151 (76%) of the newly expanded
universe is silently excluded from every regime-stratified IC measurement** -- same failure mode
as todo 280 (which found 5/17 unrouted single-name-equity symbols during Phase 171), but at
roughly 20x the scale, and specific to the recent expansion rather than a pre-existing handful.
Todo 280's own step 1 ("run `_build_symbol_regime_class` over the full active universe and
count/list unrouted symbols") is effectively what this check did, scoped to the new-symbol
subset -- **read todo 280 before scoping a fix; these two likely merge into one piece of work.**

**2. Zero empirical tags -- TagCalibrator hasn't run against these symbols (the lower-urgency part).**

```sql
SELECT t.source, count(*) FROM instrument_tags t
JOIN instruments i ON i.symbol = t.symbol
WHERE i.created_at >= '2026-08-05' GROUP BY t.source;
-- human | 327   (zero 'empirical' rows)
```

All 151 symbols average only 2.2 tags each (all `source='human'`) vs. 11.4 for the
pre-expansion universe (human seed priors + TagCalibrator's empirically-discovered
`sensitivity`/`macro_driver`/`factor_regime` tags, e.g. TLT's 5 human + 5 empirical). This part
is **correctly gated, not neglected**: `TagCalibrator` needs `alpha.tag_calibrator.min_sample_n`
(60) paired return observations per symbol, and the new symbols are still mid-backfill (see the
`ops_client43_progress_sample.sh`-tracked OHLCV backfill, ~50% complete as of 2026-08-08). No
live consumer reads `sensitivity`/`macro_driver` tags yet either (ITR doc's own Known Gap), so
this part has zero current blast radius -- unlike part 1.

## Why it matters

Part 1 is a live measurement-integrity gap, not a data-completeness nicety: pooled IC still
covers these symbols (no data dropped), but the entire regime-conditional IC cut -- the thing
this project's "segment by regime" principle exists for -- silently skips most of the universe
it just tripled in size. This is exactly the class of gap Renaissance-lens prioritization ranks
above routine hygiene.

## What to do

1. **Merge with todo 280's scope.** Don't fix these independently -- 280 already proposes running
   the routing check over the full active universe (not just new symbols) and deciding, per
   unrouted tag pattern, whether to extend an existing `tag_filter` or add a group. This todo's
   verified 76%-of-new-symbols number is strong evidence for how large that fix actually needs to
   be, not a separate problem.
2. Assign missing `exposure`-category (`eq_*`/`intl_*`/`fi_*`/`fx_*`/`commodity_*`) human seed
   tags to the 115 unrouted new symbols -- cheap, no OHLCV dependency, can happen immediately
   regardless of backfill state.
3. Re-run `TagCalibrator` (`python services/tag_calibrator.py`) against the new symbols once
   their OHLCV backfill clears `min_sample_n=60` paired observations -- gated, track alongside
   the backfill's own completion, not urgent today.
4. Consider whether todo 280 (currently filed P3) should be re-tiered given this todo's scale
   finding -- flagged here, not changed unilaterally in 280's own file.

## Closed 2026-09-03 (with 280)

Same fix as 280 (migration 331 + `dff6f38b7`): full-universe routing. The 9
newly tagged ETFs (BTAL/CWB/ICLN/IPO/IYT/SDOG/SPHB/VNQ/VYM, human seeds) both
route to equity measurement and are excluded from equity's signal input via
`signal_exclude_symbols` so the peer set stays at the pre-migration 63. Thin
tags on other expansion symbols ride the same routing (single names via
`single_name_equity`).
