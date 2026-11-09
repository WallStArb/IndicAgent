# Massive flat files: pilot basis study and admission gates

**Status:** Plan (runbook), 2026-11-09. Executes under todo 600 the moment the owner's plan
upgrade lands (the S3 key lists but downloads 403 today, re-verified 2026-11-09).
**Author:** Claude session indicagent-d8, 2026-11-09.
**Informed by:** todo 600 and its design notes, `docs/ideas/base-feature-scouting-and-the-research-ladder.md`
(rung 0), todo 587 (the unadjusted-split class this study must detect), todo 518 (volume basis is
labelled, not gated), `docs/foundation/canonical-truth-registry.md` (the provider matrix it would
extend), vendor docs read 2026-11-09 (todo 603 "Source findings").

## Preconditions

1. Plan upgraded: a ranged GET on `us_stocks_sip/minute_aggs_v1/2010/01/2010-01-04.csv.zip`
   returns 200 (probe command verified working: curl `--aws-sigv4 aws:amz:us-east-1:s3` against
   `files.massive.com/flatfiles/...` with the `MASSIVE_S3_*` keys from `.env`).
2. Disk: 715 GB free at last check; the pilot needs under 2 GB, the full archive about 80 GB.
3. The IBKR 5m backfill (534) keeps running until admission; no corpus compute (owner 2026-11-04).
4. Downloaded files are untrusted input: store under `data/massive/pilot/`, parse with explicit
   paths, never run an interpreter from inside the download directory.

## Step 0: layout probe (one file)

Download one 2010 day file. Record, from measurement not docs: file name and compression; CSV
columns; `window_start` unit (docs disagree, seconds versus nanoseconds); timestamp timezone
(align against the 09:30 ET open); price scale; volume units; `transactions` presence; rows per
symbol for a full RTH session (expect 390 minute bars) versus extended rows; symbol casing.
Write the measured facts into this doc's evidence section before any comparison runs.

## Step 1: survivorship (the reason this vendor is bought)

From `listing_end` plus a hand-list of tickers listed in 2010 and delisted since, sample at least
30 delisted-in-window names; a name passes if it appears in the 2010 files with bars. Report the
presence rate. The survivorship caveat on pre-2016 results lifts only for spans where Massive is
selected, and only with this rate on record.

## Step 2: basis study (pre-registered decision rules)

Sample: 30 names (10 liquid, 10 mid, 10 thin, including CORT-class thin names), 5 trading days in
each era: 2007, 2010, 2013, 2015 (IBKR era), 2016-01 (the seam), 2020, 2026 (fractional-share
era). Include the todo 592 nine (FBIZ, IJR, MTCH, MVBF, NVDA, PATK, RJF, UHAL, WST) and OKE and
RSPF: Massive is an independent non-Yahoo witness for exactly those open split questions.

Compare minute bars after RTH cut (09:30 to 16:00 ET) against IBKR (pre-2016) and Alpaca SIP
(2016 onward) from `ohlcv_raw`, like-for-like on (symbol, minute):

- **Price gates (admission):** per name-day, median |close diff| / close at or under 1 bp; p99 at
  or under 10 bp; at least 99 percent of RTH minutes matched both directions on normal sessions;
  unmatched minutes counted and listed, never assumed no-trade (the gate-by-evidence rule).
- **Scale-factor gate (the 587 class):** per name-year, the median log close ratio within 10 bp
  of 0 after corporate-action alignment. Any name outside is investigated, listed with its factor
  and the corporate actions in window; it does not silently pass.
- **OHLC sanity:** high at or above max(open, close), low at or below min(open, close) on at
  least 99.9 percent of bars; violations listed.
- **Volume, recorded not gated:** ratio distributions per vendor pair (IBKR and Massive, Alpaca
  and Massive), per name and vendor-wide. A vendor-wide median ratio outside 0.5 to 2.0 gates
  (units error, for example lots versus shares); name-level basis differences are labelled data
  (todo 518 pattern), not refusals.
- **Seam rule:** the same tolerances hold on both sides of 2016-01-04; that continuity is the
  point of admission.

## Step 3: verdict and what follows

Write the evidence tables under `logs/massive_pilot/`, one summary in this doc, and a
recommendation to the owner: admit, admit with caveats (named, per gate), or refuse. Admission
then runs todo 600 steps 3 to 6 (archive raw unmodified, vendor onboarding under the capture law,
ticker-to-entity map, `bar_source_policy` switch with the docs move in the same commit). If
admitted, draft the deletion list (IBKR pre-2016 leg, the 596 ask-ledger readers, the completeness
gates the file manifest replaces) for the owner's call, per the 2026-11-07 simplify ruling.

Record before sizing the full load: one full year of raw row counts (the design note's measure
first, widen in stages).

## Handling

Downloads via curl SigV4 (verified) or awscli if present; no boto3 in the venv. Raw files archived
unmodified the day they are downloaded (permanent raw). Every comparison script lives under
`scripts/ops/`, reads by explicit path, and writes only under `data/` or `logs/`.
