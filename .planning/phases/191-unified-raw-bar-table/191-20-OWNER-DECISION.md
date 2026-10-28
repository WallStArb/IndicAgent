# Plan 191-20 owner decision: delete the Tradier bar rows

Prepared 2026-10-28 by the data lane (indicagent-3a) from `191-TRADIER-RESIDUE.md` (plan 19
Task 2 output, readiness green 2026-10-28 01:30Z) and a read-only residue query that also counts
Alpaca SIP 1d coverage (D-191-Q). Nothing has been backed up or deleted.

## What is asked

Approve deleting Tradier's bar rows: `ohlcv_raw` and canonical `market_data_ohlcv` 1d rows of
vendor tradier, and Tradier `ohlcv_revision` rows. `ohlcv_load` and `ohlcv_request` rows stay as
lineage. A verified backup is written first and kept until about 2026-11-12. Reply "approved", or
name names to hold back (they are excluded from every delete predicate).

## What is lost

| Measure | Sessions | Names |
|---|---|---|
| Tradier sessions IBKR does not hold (the report's measure) | 586,826 to 629,171 | 853 |
| Tradier sessions neither IBKR nor Alpaca holds (after D-191-Q) | 314,522 | 799 |
| of which before 2016-01-04 | 282,487 | |
| of which from 2016-01-04 | 32,035 | |

The report counts against IBKR alone. Once D-191-Q is live, Alpaca SIP serves 2016 onward, so
the real loss is the second row, and 90% of it is before 2016.

Much of the largest residue is not the company's own history. Tradier keys by ticker and carries
predecessor companies under reused tickers: PURR (5,930 sessions back to 2000), NE (5,177, the
old Noble), S (5,094, Sprint), PATH (5,036), PLTR (4,592), LIN, EVRG, RPRX, NTR, APP, FCFS, CR and
EXE all show Tradier history decades before their listing. Deleting those rows removes wrong
data. One systematic gap: 313 names lose only 2007-02-08, a session IBKR does not hold.

204 names' first 1d bar moves later by more than a week (the report lists each name's first bar
before and after).

## The fallback proof

1,466 of 1,529 names are proven: the unchanged daily rule, run without Tradier, serves every
pre-2026-10-07 session IBKR holds. 62 of the 63 unproven names are venue-moved (sessions only a
former listing venue answered; the venue study failed, todo 433, expected residue). The other is
ETHA (528 SMART sessions unserved). The harness self-check matched 2 of 50 sampled names, because
stored canonical 1d lags raw by two sessions (canonical ends 2026-10-23, raw 2026-10-27); the
re-derive closes that.

## Held and ended names

Held by flag (their Tradier rows are residue the report lists): MOD, PSKY, CLBK (IBKR has no 1d
before 2026-08-28; Alpaca covers it from 2018 under D-191-Q), BZH (listing ended about
2026-10-19). Ended listings (`listing_end`): CCO, QRVO, WBD.

## Order, and what else gates the deletion

1. Todo 545 (D-191-Q) lands first: the Alpaca 1d policy rows from the final three-vendor
   arbitration, re-run right before the apply while Tradier still exists, because after the
   deletion it can never be re-run. The arbitration is in its third review round (open item: SW
   serves WestRock's history under a ticker handover; being held).
2. Backup, one-name trial, batched delete with per-batch content checks (`ops_tradier_delete.py`).
3. 1d re-derive under d2-v4; D7 judges it after the Alpaca-versus-IBKR check (545 step 5a) lands.
4. The data lane sends indicagent-5b the notice; testing unpauses.

Recommendation: approve. The residue that only Tradier holds is mostly pre-2016 history and
predecessor splices; the post-2016 loss is small once Alpaca serves.
