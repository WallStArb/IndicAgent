---
status: pending
priority: P3
filed: 2026-11-27
source: stage_1d data watch, unit c6364f4d of run dcb7caa4 (lead ruling 2026-11-27)
---

# The stored dividend_yield column ignores Massive dividend coverage

## What

The feature factory reads only Yahoo coverage and Yahoo or IBKR events for `dividend_yield` (`services/backfill_feature_factory.py`, `_DIVIDEND_COVERAGE_SQL` and `_DIVIDEND_AMOUNTS_SQL`; the comment cites todo 651). The research snapshot counts Yahoo else Massive as `div_covered`. The two disagree for every name that only Massive covers.

Numbers (2026-11-27): `dividend_event_coverage` holds 1,529 Yahoo names, 14,295 Massive names and 930 IBKR-derived names. In unit c6364f4d of run dcb7caa4 (25 names, ABVT to ACET), none of the names has Yahoo coverage and `dividend_yield` is non-null on 0 of 38,945 rows. Massive covers ACC (70 events, 2004-11-18 to 2022-04-12), ACCO (35, 2018-02-28 to 2026-10-28), ACES (31, 2018-12-20 to 2026-11-10), ACAT (31, 2004-02-10 to 2016-01-31) and ACAS (24, 2003-12-12 to 2009-08-24); their stored yield is all NaN.

## Consequence

Stored `dividend_yield`, and every column derived from it, treats Massive-only names as unknown. The snapshot's total-return path counts them as covered. A family that reads the stored yield sees a thinner panel than the one its returns come from. The yield-linked columns are already flagged non-evidence on price-only targets in the first IC report draft (ledger draft 2026-11-27a), so no recorded result is wrong.

## Options

1. The kernel reads Massive coverage and events at the next re-pin. This is a recompute of the stored column under a new pin, and the factory edit moves the code key (never edit it under a live run).
2. A family that needs the yield reads it from the snapshot (`div_covered` and the total-return path) and the stored column stays Yahoo-only, disclosed.

Recommendation: option 2 until a re-pin is scheduled for another reason, then option 1 in the same pin.

## Gates

Option 1: /simplify and /review, a recompute of the stored column, and the research determinism check if `src/intelligence/research/` moves. Option 2 is a family design note, no code.

## Not blocking

No counted test reads `dividend_yield` today.
