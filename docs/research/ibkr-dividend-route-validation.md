# IBKR dividend route from D1: validation report (D5, phase 185 plan 21)

Status: VALIDATED WITH FINDINGS
Author: phase 185 plan 21 execution (orchestrator finish after a 429 quota kill)
Date: 2026-10-02
Data: fetch run `c9b625b5-5fc4-4656-8b49-06fd93062123` (plan 15's paired TRADES +
ADJUSTED_LAST, 931 names, 3,867,030 observations per series)

## Run

`dividend_event_writer --sources ibkr --fetch-run-id c9b625b5-5fc4-4656-8b49-06fd93062123`
over all equity names: 932 symbols considered, 921 derived, 10 failed loudly
(per-symbol rollback, stored rows untouched for those). No IBKR contact, no lease.

Totals: 45,248 events written (source `ibkr_adjusted_last_ratio`, 45,876 stored rows
after the run), 3,363 downward and 2,172 unstable steps rejected, 26 date disputes on
18 names (the exact count and name-set measured 2026-09-26 and cited in migration 403),
414 yield disagreements beyond the relative tolerance, 1,714 IBKR holes and 1,914
Yahoo holes (a hole is coverage the other source could not check, not an event).

## Known-answer validation (the plan's three names plus NVR)

| name | Yahoo ex-dates in window (2016-10-02 on) | matched within 5 days | verdict |
|---|---|---|---|
| JPM | 40 | 40 | exact |
| KO | 40 | 40 | exact |
| XLU | 40 | 39 | one real miss |
| NVR pre-2005 | (no events) | - | derives nothing, as required |

XLU's miss is 2020-03-23 (the COVID quarterly): the route derived a sub-cent event
($0.015) on 2020-02-11 instead, 41 days early. XLU also carries 20 stored IBKR events
with no Yahoo event within 5 days; all 20 are sub-cent amounts ($0.015-0.02) beside
real quarterly dates. These are ADJUSTED_LAST re-basing artifacts that cross the
derived-step threshold near real distributions, not real payouts.

## Date disputes (D-23)

26 records on 18 names in `dividend_date_dispute`, each holding both sources' dates
over a 1-5 day span, `fetch_run_id` set to the D1 run. Disputes replace the interim
writer's symbol rollback: both events stand, and the research reader marks returns
spanning the window unknown (hand-off: `185-DIVIDEND-READER-HANDOFF.md`).

## Failures (10 names, all rolled back, all loud)

1. Vanished-ex-date guard, 8 names (DE, VUG, BEN, MDLZ, STLD, VTR, ZBH, SAFE): stored
   IBKR ex-dates from the interim writer's live fetches (pre-D1, provenance not
   retained) that the D1 series does not reproduce. Sampled 18 of the dates: 16 have
   no Yahoo event within 5 days either. Reading: the interim separate-fetch path
   (TRADES and ADJUSTED_LAST as two provider calls) over-derived steps at sub-noise
   distributions; the paired-run D1 path does not reproduce them, and the guard
   correctly refuses to drop stored rows silently. Follow-up: delete the
   uncorroborated interim rows for these 8 names (derived data, not raw; the D1
   re-derivation is the rebuild), then rerun the writer for them. Recorded in the
   plan SUMMARY and deferred-items; not done inside plan 21's scope.
2. CBC: `ohlcv_observation` holds negative ADJUSTED_LAST closes (2009-07-06 -0.0283;
   2020-08-17..19 -0.0571). A provider defect kept as an observation (D-09); the
   writer refuses non-positive closes. No action on raw data; CBC stays without an
   IBKR-derived dividend set until IBKR re-serves the window.
3. CLBK: no TRADES observations in the run (plan 14's late-name class). Its D1 capture
   is incomplete; rerun after the 42 late names are resolved.

## Verdict

**IBKR rows usable alone for research: no, because (a) low-yield ETFs carry sub-cent
re-basing artifacts indistinguishable from tiny real distributions at IBKR's cent
quoting precision (XLU: 20 of 59 events over ten years), and (b) one real quarterly
(XLU 2020-03-23) is missed outright.** Yahoo stays the reference dividend source
(owner-approved, todo 428); the D1-derived IBKR set serves as D5's independent
cross-check: exact on material single-name dividends (JPM, KO 40/40), with
disagreements surfaced as dispute records rather than merged away. The reconciled
view plus `dividend_event_coverage` (holes marked unknown, never zero) remains the
read path; the reader marks dispute-spanning returns NaN per the hand-off.

## Reproduction

- Writer: `PYTHONPATH=. .venv/bin/python services/dividend_event_writer.py --sources ibkr --fetch-run-id c9b625b5-5fc4-4656-8b49-06fd93062123`
- Live checks: `tests/integration/test_dividend_d1_route_live.py` (suite blocked by
  todo 486 at time of writing; the same assertions were run live via psql 2026-10-02)
