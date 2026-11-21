# Massive dividend coverage rule

Date: 2026-11-21. Status: pre-registered constants for rule `massive-dividend-coverage-v1`
(Phase A, writer side). Code: `src/intelligence/bars/massive_dividends.py`; writer:
`services/dividend_event_writer.py --sources massive`; schema: migration 608.

## 1. Why

Yahoo dividend coverage exists only for the 1,529 names that were live when Yahoo was asked, so
total-return panels are NaN for every dead member of the stage 2 universe. The Massive dividend
capture (reference_raw, endpoint `dividends`, manifest `20261110.jsonl`, 147 pages, 733,810
records) reaches the dead names. The risk is the one the coverage table exists for: absence of a
Massive record read as "no dividend" where Massive simply lost it.

## 2. The rule

Per symbol, from every ex-date Massive reported for it (mapped through the symbol's
`ticker_event_current` spans, none after the capture date):

- no reported ex-date: no claim;
- the claim starts at the first ex-date and ends at the last ex-date plus `tail_intervals`
  payment intervals (median gap between distinct ex-dates), capped at `tail_cap_days`, the
  capture date and the end of the last ticker span; one ex-date claims only itself;
- a gap between consecutive ex-dates longer than `gap_intervals` intervals is a hole;
- days between two ticker spans of the symbol, and ex-dates the writer could not store (non-USD,
  no positive amount, no raw prior close within `threshold.dividend_event.prev_close_max_age_days`,
  or one dividend restated with a different amount: two records of the same distribution type and
  pay date whose amounts differ by at most 10%, which summing would double; or the same amount
  with two pay dates, which collapsing would halve), are holes.

Per ex-date, exact repeats of an amount collapse and distinct amounts sum (a regular and a special
dividend, dividend plus interest on capital).

| Constant | Value | Why |
|---|---|---|
| `tail_intervals` | 0.75 | Below 1, the claim never reaches the next expected payment, so a lost final dividend is unknown, not silently zero (section 3, B2). |
| `gap_intervals` | 1.5 | One missed payment doubles a gap; anything below 2 makes it a hole. No floor in days (a monthly payer missing a month is caught). |
| `tail_cap_days` | 400 | Bounds the tail of annual and irregular payers. |

The constants are rule definitions, not operator tunables; `CoverageRule` refuses values that
break the two guarantees (tail below 1, gap between 1 and 2). A change is a new `RULE_ID`.
The recon's draft (tail 1.5 intervals, gap 1.75 with a 60-day floor) is not adopted: its tail
claims the next expected payment, which B2 could not show to be safe.

## 3. Step 0 measurement

Scripts and outputs: session scratchpad `step0/` (`a_yahoo.py`, `b_test.py`, `b2_hits.py`,
`b3_bound.py`, `c_struct.py`).

A. Yahoo as the second source (live names). Under the shipped rule, 66,506 Yahoo events fall
inside a Massive claim; 66 (0.099%) have no Massive ex-date within 5 days (silent misses) and 62
(0.093%) have one 1 to 5 days off (date disagreements, the reader's dispute rule). The largest
silent misses are spin-offs Yahoo books as dividends (MO 2007 and 2008, FIS 2008, DHR 2016, CAH
2009): Massive carries cash only. The sweep over tail 0.5 to 1.5 and gap 1.25 to 1.75 moves the
silent count between 60 and 68 and the covered member-years between 51,964 and 52,630; on live
names the constants are nearly free.

B. Price drop in canonical 1d bars as the second source (dead names; stratified sample of 200
dead members with four or more events, 50 per era of last membership, plus 200 Yahoo-covered
controls). Overnight return net of SPY's on the listed ex-date:

- B1, listed events are real and correctly dated: slope on yield -0.859 dead vs -0.925 live; of
  events with yield above 3 sigma, 82.1% (dead) and 84.7% (live) show the drop on the listed day,
  2.5% and 2.6% only on a neighbouring day.
- B3, unlisted dividend-sized drops on covered non-ex days: 22.3 (dead) vs 25.5 (live, where
  Yahoo confirms no dividend) per 1,000 days; difference -3.47 (95% -5.39 to -1.61). No excess,
  but the criterion's power on a typical dividend is 13%, so this bounds only large misses.
- B2, the tail: at the next expected date after a dead name's last listed dividend, a
  dividend-shaped drop appears in a share 0.28 (95% -0.13 to 0.60; 277 probes, signal above 2
  sigma) of tails. The top hits are documented suspensions in distress (FNM 2008, TMA 2008, LEE
  2008, SMLP 2020), so the price test is confounded and cannot clear a tail past the next
  payment; hence `tail_intervals` below 1.

C. Patchiness: cadence holes per 100 claimed name-years are 17.1 / 16.4 / 14.8 (dead, eras
2003-2008 / 2009-2015 / 2016-2026) vs 10.9 / 9.1 / 5.4 (live). Dead records are patchier (and
dead names suspend more). Scaling the live silent rate by the worst ratio (2.75) gives about
0.27% of covered dead-name events as the expected silent-miss rate; this is an extrapolation, not
a direct measurement.

Verdict: safe to load. Residual risk is a few tenths of a percent of events, concentrated in
irregular and non-cash distributions; spin-offs are the material class and are outside Massive's
scope (Phase B).

## 4. Load counts (dry run, 2026-11-21, live DB read-only)

733,810 records; dropped 243,771 unmapped (no ticker span holds the ex-date), 3,340 ex-date after
the capture, 2,732 non-USD, 209 records on ex-dates whose records conflict; 473,012 events after 3,390 more lack
a raw prior close within 7 days; 14,295 names with a claim, 17,871 holes; 544,026 member-months and 52,296 member-years
covered (36,339 of them dead members).

## 5. For Phase B (the reader)

- Covered means inside `dividend_event_coverage` and outside every `dividend_event_coverage_gap`
  row of the same source. Readers that take the span alone over-claim.
- `dividend_events_reconciled` excludes `massive` (migration 608) until the reader admits it.
  Two readers read `dividend_events` without a source filter: `services/backfill_feature_factory.py`
  (`_DIVIDEND_AMOUNTS_SQL` returns NULL amounts for Massive-only dates, a TypeError in
  `reconciled_amounts`; the module is fingerprinted, so it is not edited in Phase A) and
  `services/bar_reconciliation_audit.py` (`_EXPLAINED_DATES_SQL` would gain Massive dates). The
  writer refuses a live Massive load until `MASSIVE_READERS_READY` is set in
  `services/dividend_event_writer.py`; Phase B fixes both readers and sets it. The Yahoo writer's
  own reconciliation already reads only its two sources. `src/api/routes/data.py` lists the new
  source's coverage, which is intended.
- Massive `amount` is in raw units of the ex-date; use `amount / prev_close` only.
- Massive has no spin-offs or return-of-capital type; a large unexplained ex-date drop in a
  Massive-only span needs the reader's own guard.
- `declared_on` is NULL where Massive gives no declaration date; the recon counted 1,362 records
  declared after their ex-date, so a reader at t must test `declared_on <= t` where it is known.
