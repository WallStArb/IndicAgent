---
status: pending
priority: P1
filed: 2026-10-29
source: data lane, 1d session_coverage recount (191-SESSION-COVERAGE-FIX.md)
---

# The canonical 1d series lacks bars the raw table holds, for 71 held names

After the answered-session fix and its review correction (191-SESSION-COVERAGE-FIX.md), 162 of the 207 scored
names still fail `session_coverage` (the first version showed 110; its no-trade rule was too loose). For 71 of them the only remaining cause is the same one: sessions where
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
re-derive the 71 names. Then re-run the D7 verdicts: 55 of the 71 clear `session_coverage` with no change to
the coverage rule. The other 16 (APLD AUGO BCML BELFA BMNR CBAN COFS CPER FUBO IDR KCE MPB RCAT SAFE WULF
XTL) also carry runs of 5 to 23 no-bar sessions in thin names that the corrected no-trade rule refuses to
answer; they need a source outside IBKR or an owner decision on the run cap. Order against 186-26: the 71 names stay held until this lands.

## Not in scope

The 39 names with genuine holes (no raw bar and no answered window) and the freshness and seam holds:
191-SESSION-COVERAGE-FIX.md classifies them.

## Resolved cause and stage 1 drift (data lane, 2026-10-30)

The derivation gap is not a defect. After the Tradier delete the IBKR history fetcher backfills 1d
`smart_trades` for the pre-2016 era on the names Tradier used to cover (1,165 names now have it).
CUBE: its 3,664 new IBKR bars (2011-11-03 on) landed 2026-10-29 22:52Z, after the last daily
derive (11:54Z), so canonical holds IBKR 2011-09-19..2012-02-01 and Alpaca from 2016-01-04 until the
fetcher's daily stage derives the touched series at the end of its run. Expect the 71 names to clear
without code. Recount after the next daily derive and the next audit; a name that still has raw bars
canonical lacks after that is a real derivation defect.

Drift in the 186-26 stage 1 output (feature_vectors_v2, 1d): 27 of its 1,257 names have IBKR 1d raw
earlier than their canonical head, so the pending derive extends their history. Days gained:
NCMI 3252, DE 2555, ELS 2555, HUBB 2555, DOC 2555, FE 2555, EOG 2555, EZU 2170, PRI 2104, MDLZ 1937,
ZBH 1895, EPAM 1426, NRG 1035, NEXN 936, ASC 886, ESI 711, HUBS 452, XENE 425, EU 339, LNTH 193,
FTV 22, RKLB 7, DELL 7, PWP 4, ROIV 4, AUR 3, BOC 1. Rolling-window features keep their values past
the new warmup; expanding-state features (the HMM walk-forward, the never-reset VWAP series) differ for
these names. Handle at the 186-27 drift read: delete those names' stage 1 rows (derived cache) and
rebuild them as their own units with the same pin; the primary key is append-only, so a rerun cannot
overwrite. Names whose gain is under 30 days (FTV, RKLB, DELL, PWP, ROIV, AUR, BOC) change by warmup
only and can wait for the next full rebuild.
