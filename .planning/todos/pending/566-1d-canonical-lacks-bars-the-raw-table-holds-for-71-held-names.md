---
status: pending
priority: P1
filed: 2026-10-29
source: data lane, 1d session_coverage recount (191-SESSION-COVERAGE-FIX.md)
---

# The canonical 1d series lacks bars the raw table holds, for 71 held names

After the answered-session fix (191-SESSION-COVERAGE-FIX.md), 110 of the 207 scored names still fail
`session_coverage`. For 71 of them the only remaining cause is the same one: sessions where
`ohlcv_raw` holds a canonical vendor's bar and `market_data_ohlcv` holds none. Such a session is not a
vendor answer of "no trade", so no answer evidence may cover it. It is a hole in the derived series.

Measured 2026-10-29 (read-only): 23,171 such sessions over the 71 names, 12,198 before 2016-01-04 (IBKR
era, 12 names), 10,953 from 2016-01-04 on (59 names) and 20 in the stale tail of CTVA (canonical
ends 2026-09-30, raw runs to 2026-10-28). The names are listed in 191-SESSION-COVERAGE-FIX.md. Examples:

- CUBE: canonical holds 94 IBKR `named` bars (2011-09-19..2012-02-01), then nothing until Alpaca
  `sip_rth` from 2016-01-04. Raw holds IBKR `smart_trades` for 2012-02-02..2015-12-31 (985 sessions).
- JBTM: canonical holds 8 IBKR bars (2008-07-18..2008-07-31); raw holds IBKR `smart_trades`
  2008-07-18..2015-12-31, 1,868 sessions without a canonical bar.
- APTV: 474 sessions 2016-01-04..2017-11-16 with a raw row from each vendor and no canonical bar.

The latest `derived` loads of CUBE and JBTM (2026-10-29, rule d2-v4) report `refused_head: []`,
`refused_interior: []`, `stale_only: []`, `restated: []`: the rule did not refuse these sessions by a
recorded reason, so the cause is open. Candidates to check first: the per-span hold rows of D-191-Q
(30 hold spans over 27 names in 191-D191Q-ARBITRATION.md; the 71 names are not all in that list), the
primary and fallback choice of `daily_rule.servable_primary_dates` over the pre-2016 range, and whether
these are names whose derivation stopped at the first discontinuity.

## Fix

Find why the daily stage admits no bar on these sessions, correct the rule or the policy rows, and
re-derive the 71 names. Then re-run the D7 verdicts: the names clear `session_coverage` with no change to
the coverage rule. Order against 186-26: the 71 names stay held until this lands.

## Not in scope

The 39 names with genuine holes (no raw bar and no answered window) and the freshness and seam holds:
191-SESSION-COVERAGE-FIX.md classifies them.
