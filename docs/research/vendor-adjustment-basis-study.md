# Vendor adjustment basis study: IBKR SMART vs Tradier 1d

**Author:** Claude (Opus 5.5), 2026-10-07, at Brandon's request (plan 185-37)
**Status:** complete 2026-10-07: rule pre-registered (a2d9ca6e1), results (038a5774c), 30 IBKR
exception rows written and 25 names re-derived; vendor_basis_run blockers 46 to 31, each named
under "Undecided runs" (owner decisions in todo 508)
**Informed by:** docs/plans/2026-10-06-data-layer-integrity-design.md (sections 2, 6, 7, open
risks; spec step 5); summaries of plans 185-33 (vendor_basis_run verdict, 46 blockers), 185-38
(74 IBKR-primary exception rows, 113 names routed here, VMRK) and 185-46
(docs/research/1d-primary-swap-evidence.md: the swap to IBKR primary from D = 2026-10-07)

## Question

Where the two 1d vendors disagree for a run of sessions (an adjustment-basis disagreement: a
split, spin-off or dividend applied by one vendor and not the other, or applied differently),
which vendor's own series is continuous across the run, and does the canonical 1d series follow
it? A canonical series built from the stepping vendor carries a false return at each boundary.
The design lists the vendor treatment of IBM, BDX and LEN as unverified; this study verifies it
against the public record.

Scope: history before D (2026-10-07). The 185-46/185-47 swap decides who owns bars from D on and
does not edit any bar dated before D; this study decides bars before D only.

## Decision rule

Pre-registered (plan 185-37 objective, verbatim). Committed alone before the study script runs
against the data.

1. A run is a span of at least `threshold.bar_integrity.vendor_ratio_run_min_sessions` sessions
   where the IBKR/Tradier close ratio leaves `threshold.bar_integrity.fallback_basis_tolerance_bp`.
2. At each run boundary, the continuous vendor is the one whose own close-to-close move at the
   boundary is within the name's ordinary range (|log return| below the name's 99th percentile
   daily move over the surrounding 250 sessions) while the other vendor's move is not; a recorded
   corporate_action on the boundary date explains a step on the vendor that applies it.
3. Tradier stays primary unless Tradier is the discontinuous side with no corporate action
   explaining it and IBKR is continuous; then an exception row sets primary_source ibkr for the
   run's date range (valid_from and valid_to bound the range), evidence = the run (dates, median
   ratio, both boundary moves).
4. Spin-offs: the canonical series should not show a false return at the ex-date. If Tradier
   adjusts history for the spin-off and IBKR does not, Tradier is already right and no row is
   written; if the reverse, an exception row applies. Undecided runs get no row and are listed by
   name.

The 99th percentile and 250 sessions are study parameters recorded here, not APR keys (the study
is a one-off measurement; the daily rule's thresholds are the APR keys above).

### Operational definitions (fixed with the rule, before any result)

- Closes. Per name and date, each vendor's latest current-scale close (`current_closes` in
  `src/intelligence/bars/daily_rule.py`, the input D7's vendor_basis_run verdict reads; TRADIER
  route for Tradier, SMART TRADES for IBKR, LEGACY_IMPORT excluded). Common sessions are dates
  where both closes are positive. Runs come from `find_basis_runs` over those pairs with the two
  APR values read at run time.
- Ordinary range. For each vendor, the absolute log close-to-close moves between consecutive
  common sessions. The sample for a boundary is the 125 moves before the boundary's earlier
  session and the 125 moves after its later session (250 surrounding sessions; fewer at the ends
  of the history), excluding both boundary moves of the run. The 99th percentile is numpy's
  linear-interpolation percentile. A boundary move is in range when it is strictly below that
  percentile.
- Boundaries. Before: (last common session before the run, the run's first session). After:
  (the run's last session, first common session after it). A run touching the first or last
  common session has one boundary.
- Boundary votes. A boundary whose window (prev, cur] contains the effective_date of a recorded
  corporate_action casts no vote (explained). Otherwise it votes for the vendor that is in range
  when the other is not; both in range (a gradual drift) or both out (a common shock) cast no
  vote.
- Run verdict. ibkr or tradier when at least one boundary votes and every vote names the same
  vendor; otherwise undecided. The D7 detector's own classification (`classify_run`) is recorded
  next to it for every run, and disagreements are listed; the rule above decides rows.
- Proposed row (rule 3). For a run decided ibkr whose dates are canonical under a Tradier-primary
  policy (stored 1d source tradier on at least one run date, and no open IBKR symbol row): one
  symbol row, primary ibkr, no fallback (d2-v2 refuses an IBKR-primary row with a Tradier
  fallback), valid_from = the run's first session, valid_to = the day after the run's last session
  (the table's range is [valid_from, valid_to)). Its evidence holds the run's dates, n_sessions,
  median ratio, every boundary's dates and both vendors' log moves and percentiles, and the D7
  classification. A run decided tradier on a name whose run dates are stored from IBKR is listed;
  rule 3 writes no Tradier row.
- Spin-off cases (rule 4). For IBM, BDX and LEN, the ex-date and distribution are taken from the
  public record (SEC EDGAR filings or the company's investor relations pages), retrieved with
  WebFetch and cited with URL and retrieval date. The vendor that adjusts is the one whose
  pre-ex-date closes sit below the other's by about the distribution's value share with the ratio
  returning to 1 at the ex-date. A failed fetch or an ambiguous record leaves the case undecided:
  no row, listed by name. No date is filled from memory.
- Decomposition of the disagreement. Re-measure the spec's figure first: name-dates where both
  vendors' latest raw closes (no scale correction) differ by more than 1%. Each such name-date is
  then: inside a run (its date is inside a basis run found on current-scale closes), isolated
  (current-scale out of tolerance in a stretch shorter than the run minimum), or other (on the
  current scale it is within tolerance or not comparable, a scale artifact such as a pre-split
  answer). The same split is reported for the current-scale count.

Study parameters: percentile 99, surrounding window 250 sessions (125 each side), disagreement
threshold 1% for the decomposition.

## Results

Measured 2026-10-07 at 18:46 UTC by `scripts/research/vendor_basis_study.py --tsv
logs/185-37/vendor_basis_study.tsv --out logs/185-37/vendor_basis_study.json --evidence-dir
logs/185-37/evidence` (read-only connection, 62 s wall, 215 MB peak). APR at run time:
fallback_basis_tolerance_bp 10, vendor_ratio_run_min_sessions 5.

### Runs

| measure | value |
|---|---|
| names with both TRADIER and SMART TRADES 1d observations | 1,037 |
| names with at least one basis run | 459 (456 compute_1d) |
| basis runs | 2,173 |
| decided ibkr continuous (rule) | 100 |
| decided tradier continuous (rule) | 29 |
| undecided (rule) | 2,044 on 375 names |
| D7 `classify_run` decided | 65 (58 ibkr, 7 tradier) |
| D7 blocking runs, reproduced | 46 on 46 names, the same names the live verdict lists |

The rule and D7's detector agree on every run D7 decides except two (one each way, both left
undecided by the rule). The rule decides 66 runs D7 leaves open, because D7 requires a boundary
move above everything in the vendor's whole history while the rule compares with the 99th
percentile of the surrounding 250 sessions.

Why runs are undecided: in 1,978 of the 2,044 every boundary has both vendors inside their
ordinary range (a gradual drift, a dividend-adjustment difference accumulating over time); in 64 at
least one boundary has both vendors outside it (a market shock on the boundary day, or a real
corporate-action price move such as KDP on 2018-07-10); 2 carry conflicting votes. 1,814 of
them are shorter than 20 sessions, and 1,759 have a median ratio within 1% of 1 (159 within 10 bp,
126 beyond 1%).

### Runs by proposed action

| action | runs | names | sessions |
|---|---|---|---|
| row_ibkr (rule 3, ends measured) | 30 | 25 | 18,922 |
| withheld_unmeasured_seam (see "Range ends") | 45 | 45 | 63,350 |
| withheld_ibkr_no_trade (see "Range ends") | 2 | 1 | 230 |
| none_already_ibkr (decided ibkr, dates already IBKR under a symbol row) | 23 | 23 | 24,002 |
| none_tradier_continuous (decided tradier, canonical Tradier) | 25 | 22 | 16,457 |
| listed_tradier_continuous_ibkr_stored (decided tradier, canonical IBKR) | 4 | 4 | 5,176 |
| undecided | 2,044 | 375 | 116,648 |

### What the decided runs are

The decided runs are not drift. In almost every one the IBKR/Tradier ratio is a constant factor
(2.0, 0.5, 3.0, 4.0, 1/3, 16, 0.04) over years and returns to exactly 1 on one date, and the
stepping vendor's own series jumps by that factor on that date. Two families dominate:

- Tradier history on a stale split basis. Tradier's closes before a fixed date are not adjusted for
  a later split or reverse split that IBKR's are. 25 decided runs end on 2011-05-20 (the first
  Tradier session on the current scale is 2011-05-23; ABT, BAX, CHD, EBAY, ROST, VIXM and VIXY among
  them); 8 span 2011-05-23 to 2015-09-10 (the SPDR sector ETFs XBI, XHE, XPH, XSD, XTN among them);
  6 end 2016-11-04, the iShares country ETFs EWI, EWJ, EWM, EWS, EWT, EWU (Tradier steps by a
  factor of 2 or 4 on 2016-11-07). Example, CHD: Tradier 41.08 on 2011-05-20 then 20.465 on 2011-05-23, IBKR 20.54 then
  20.47. Canonical 1d is Tradier on these names, so it carries a false log return of about ln(ratio)
  at the boundary: +1.39 on EWJ, -0.69 on CHD, -3.19 on VIXY. The same stale scale holds in Tradier's
  volume: inside these runs the IBKR/Tradier volume ratio is the inverse of the price ratio (BIL
  0.486, COPX 0.324, VIXY 29.0), and it returns to about 0.92 to 0.97 after the boundary.
- IBKR answers unadjusted for a distribution that Tradier adjusts (IBM and LEN, checked against the
  record below), or on another scale before a fixed date (RJF before 2021-09-22, PATK before
  2017-12-11). Here IBKR steps and Tradier is continuous.

Two decided runs rest on a single bad Tradier print at the boundary rather than a basis: DOV
2018-05-08 (Tradier 60.33 against IBKR 75.67, with both within 1.3% on either side) and YUM
2016-10-31 (Tradier 44.52 against IBKR 62.04, both within 20 bp on either side).

### Range ends (deviation, added after the first run; it only withholds rows)

The pre-registered row bounds the range at the run's first and last sessions. The first run showed
two cases the rule did not anticipate, in which that row would make the canonical series worse or
hide the defect. Both are withheld and listed. Neither adds a row the rule would not write.

1. A run that starts at IBKR's first common session while Tradier holds earlier dates. The run's
   start is where IBKR's history begins, not where the basis begins: Tradier's head before it is on
   the same stale basis (checked on ABT: Tradier 46.35 on 2006-10-05 and 46.19 on 2006-10-06, IBKR
   22.13 on 2006-10-06, ratio 0.479 from the first common session; LEGACY_IMPORT holds 4 days). A
   row from the run's start moves the false return from the run's end to the head seam. That seam
   is outside every run, and D7's unexplained_seam judges only a recent window, so no check would
   see it. Withheld when an end has no common session next to it agreeing within the tolerance and
   Tradier holds dates beyond it: 45 runs on 45 names, 67,209 Tradier head dates in total.
2. An IBKR series that is not observing trades. WBD in 2016: IBKR answers a flat 25 on zero volume
   (65 of 116 and 87 of 114 run sessions) while Tradier trades 3 to 5 million shares a day; the rule
   reads the flat series as continuous. Withheld when more than half of IBKR's run sessions have
   zero volume: 2 runs on WBD. Every other proposed row has at most 3.2% zero-volume IBKR sessions
   (BNO 26 of 816, XHE 15 of 1,047).

### Decomposition of the disagreement

Re-measured first: name-dates where both vendors' latest raw closes differ by more than 1%:
**216,056 on 821 names** (the design measured 216,057 on 821 names on 2026-10-06). Of them:

| part | name-dates | share |
|---|---|---|
| inside a basis run (current scale) | 209,945 | 97.2% |
| isolated (out of tolerance for fewer than 5 sessions) | 5,561 | 2.6% |
| other (agree on the current scale: a pre-split raw answer) | 550 | 0.3% |

On the current scale 215,506 name-dates differ by more than 1%, 209,945 inside runs and 5,561
isolated. The disagreement is almost entirely basis runs, not isolated bad prints.

## Known cases

| name | run | ratio (IBKR/Tradier) | continuous vendor | canonical 1d follows | row | source |
|---|---|---|---|---|---|---|
| RJF | 2006-10-06 to 2021-09-21 | 0.6667 | Tradier (IBKR steps +52% on 2021-09-22) | Tradier, yes | none | data (design section, verified) |
| REX | 2006-10-06 to 2025-09-08 | 2.0002 | IBKR (Tradier steps on 2025-09-09) | IBKR under the 185-38 symbol row, yes | none (already IBKR) | data |
| IBM | 2006-10-06 to 2021-11-03 | 1.0469 | Tradier adjusts for Kyndryl, IBKR does not: on 2021-11-04 IBKR 127.13 to 120.85 (-4.9%), Tradier 121.43 to 120.85 (-0.5%); rule 2 undecided (IBKR's move 0.0507 just under its 0.0513 percentile) | Tradier, yes (rule 4) | none | [1] |
| BDX | 2006-10-06 to 2026-02-09 | 1.0176 | Both vendors adjust history for the Waters distribution, by factors that differ by 1.8%: the distribution is about 0.135 x 328.14 (WAT close 2026-02-09) = 44.30 per BD share, and neither series drops by that on 2026-02-10 (IBKR +3.4%, Tradier +5.2%). Which factor is right needs BD's unadjusted close on 2026-02-09, which neither the record fetched nor the data holds | Tradier; undecided (rule 4) | none (rule 2 votes ibkr, row withheld under "Range ends" anyway) | [2], [3] |
| LEN | 2006-10-06 to 2025-01-17 | 1.0568 (1.0381 at the end) | Tradier adjusts for Millrose, IBKR does not: the basis ends on the record date 2025-01-21 (shares settling after it carry no entitlement); IBKR 136.01 to 133.14 (-2.1%), Tradier 131.02 to 133.14 (+1.6%). Both vendors equal through the 2025-02-07 distribution | Tradier, yes (rule 4) | none | [4], [5], [6] |
| ETHA | none | none | no current-scale IBKR answer exists: every SMART answer (last fetch 2026-10-01) predates the recording of the 2026-10-02 reverse split, so no common session and no run; canonical ETHA is Tradier on the post-recording scale (Tradier refetch) | Tradier | none | data; decided again after 189-10 Task 1b's refresh |

Spin-off record, each retrieved 2026-10-07 by HTTP fetch (the WebFetch tool was not available to
this executor; SEC EDGAR documents refused an undeclared user agent, so the companies' own pages
were used):

1. IBM, "IBM Board of Directors Approves Separation of Kyndryl", 2021-10-12,
   https://newsroom.ibm.com/2021-10-12-IBM-Board-of-Directors-Approves-Separation-of-Kyndryl :
   one Kyndryl share for every five IBM shares held on the record date 2021-10-25; distribution
   after the close of market on 2021-11-03.
2. BD, "BD Announces Record Date for the Spin-Off of its Biosciences & Diagnostic Solutions
   Business", 2026-01-27,
   https://investors.bd.com/news-events/press-releases/detail/932/bd-announces-record-date-for-the-spin-off-of-its-biosciences-diagnostic-solutions-business
   : record date 2026-02-05, closing expected 2026-02-09, due bills through the closing date, BD
   quoted ex-distribution from the first trading day after the closing.
3. BD, "BD Completes Combination of Biosciences & Diagnostic Solutions Business with Waters
   Corporation", 2026-02-09,
   https://investors.bd.com/news-events/press-releases/detail/937/bd-completes-combination-of-biosciences-diagnostic-solutions-business-with-waters-corporation
   : completed 2026-02-09; about 0.135 Waters shares per BD share held on 2026-02-05.
4. Lennar, "Lennar Declares Dividend and Sets Dates for Millrose Spin-off", 2025-01-10,
   https://investors.lennar.com/press-releases/2025/01-10-2025-230022870 : one Millrose share per
   two Lennar shares held at the close on 2025-01-21; distribution before the open on 2025-02-07.
5. Lennar, record-date reminder, 2025-01-21,
   https://investors.lennar.com/press-releases/2025/01-21-2025-140503880 : shares acquired in
   trades settling after the record date receive no Millrose shares.
6. Lennar, "Lennar Completes Spin-off of Millrose Properties", 2025-02-07,
   https://investors.lennar.com/press-releases/2025/02-07-2025 : distribution completed before the
   open on 2025-02-07 to holders of record on 2025-01-21.

Other names routed here by 185-38 (113 plus VMRK): 19 get rows (BIL, BNO, BWX, COPX, DNTH, GDXJ,
NVDA, SIL, THC, UNG, URA, VCIT, VCSH, XBI, XHE, XPH, XSD, XTN, YUM); 39 are withheld for the
unmeasured seam and WBD for no-trade prints; 11 are decided tradier and need nothing (APO, BH,
CUBI, FTNT, HSIC, HST, OKE, RJF, SSP, VMRK, WY); 44 hold only undecided runs, none of them blocking
except EWT. VMRK's 2000-01-03 bar stays absent: it sits under VMRK's closed 185-38 row
[2000-01-03, 2000-01-04), and the append-only table cannot give that date another row. SIL's 276
refused IBKR head dates (185-38) stay refused; the row below covers only its run.

## Proposed exception rows

Primary ibkr, no fallback, valid_from = the run's first session, valid_to = the day after its last
session, one evidence file each in `logs/185-37/evidence/` (run, boundaries with both vendors'
moves and percentiles, D7's classification, range ends, IBKR zero-volume share).

| symbol | run (first to last session) | sessions | median IBKR/Tradier | boundaries voting ibkr | Tradier-only dates in range |
|---|---|---|---|---|---|
| BIL | 2007-05-30 to 2017-11-28 | 2,644 | 2.0000 | after | 0 |
| BNO | 2010-06-03 to 2013-08-28 | 788 | 0.5000 | after | 0 |
| BWX | 2007-10-05 to 2016-09-27 | 2,261 | 0.5000 | after | 0 |
| CHTR | 2010-09-14 to 2011-05-20 | 174 | 1.1059 | after | 0 |
| COPX | 2010-04-20 to 2015-11-17 | 1,404 | 3.0000 | after | 0 |
| DNTH | 2018-06-21 to 2023-09-11 | 1,314 | 16.0000 | after | 0 |
| GDXJ | 2011-05-23 to 2013-06-28 | 529 | 4.0000 | before, after | 0 |
| HYG | 2008-09-18 to 2008-09-24 | 5 | 1.0045 | before | 0 |
| IWC | 2007-07-27 to 2007-08-02 | 5 | 1.0020 | after | 0 |
| NVDA | 2007-10-31 to 2007-11-09 | 8 | 0.9994 | after | 0 |
| NVDA | 2011-08-04 to 2011-08-16 | 9 | 0.9938 | before | 0 |
| NVDA | 2012-04-17 to 2012-05-10 | 18 | 0.9981 | after | 0 |
| NVDA | 2012-06-19 to 2012-07-11 | 16 | 1.0050 | before | 0 |
| SIL | 2011-05-23 to 2015-11-17 | 1,130 | 3.0000 | after | 0 |
| THC | 2012-06-28 to 2012-07-09 | 7 | 0.9981 | before | 0 |
| UNG | 2007-04-18 to 2011-03-08 | 975 | 0.5000 | after | 6 |
| URA | 2010-11-05 to 2015-11-17 | 1,267 | 2.0002 | after | 0 |
| VCIT | 2011-01-14 to 2011-03-14 | 40 | 1.0051 | after | 0 |
| VCIT | 2011-08-05 to 2011-10-07 | 45 | 1.0050 | before | 0 |
| VCSH | 2009-12-07 to 2010-11-10 | 235 | 1.0051 | before | 0 |
| VCSH | 2012-02-21 to 2012-03-02 | 9 | 1.0057 | before | 0 |
| VIXM | 2011-01-04 to 2011-05-20 | 96 | 0.2500 | after | 0 |
| VIXY | 2011-01-04 to 2011-05-20 | 96 | 0.0400 | after | 0 |
| XBI | 2011-05-23 to 2015-09-10 | 1,083 | 0.3333 | before, after | 0 |
| XHE | 2011-05-23 to 2015-09-10 | 1,033 | 0.5000 | before, after | 0 |
| XLB | 2007-08-21 to 2007-09-17 | 19 | 0.9990 | after | 0 |
| XPH | 2011-05-23 to 2015-09-10 | 1,083 | 0.5000 | before, after | 0 |
| XSD | 2011-05-23 to 2015-09-10 | 1,083 | 0.5000 | before, after | 0 |
| XTN | 2011-05-23 to 2015-09-10 | 1,052 | 0.5000 | before, after | 0 |
| YUM | 2014-11-14 to 2016-10-31 | 494 | 1.0020 | after | 0 |

30 rows on 25 names. 15 of them (BIL, BNO, BWX, COPX, DNTH, GDXJ, SIL, UNG, VIXM, VIXY, XBI, XHE,
XPH, XSD, XTN) clear a blocking vendor_basis_run verdict. The short NVDA, HYG, IWC, THC, VCIT, VCSH
and XLB runs are 6 to 62 bp bases decided by one boundary; their rows move a handful of bars by
that much and are written because the rule decides them. UNG's 6 Tradier-only dates inside the
range become holes (IBKR primary has no fallback; those Tradier bars are on the stale basis).
Volume inside each range becomes IBKR's, which on the stale-basis names repairs a factor-of-2 to
29 volume step; at the range ends IBKR volume runs about 3 to 11% under Tradier's in these years
(DNTH 21%, YUM 16%).

## Applied

2026-10-07, 18:57 to 19:15 UTC, outside the 00:30 to 03:00 and 05:30 to 06:30 UTC windows; the
IBKR fetcher and the Tradier loader stopped and disabled throughout.

1. Rows. `ops_source_policy.py --add --symbol S --valid-from <run start> --valid-to <run end + 1>
   --primary ibkr --reason "..." --evidence "$(cat logs/185-37/evidence/S_<start>.json)"`, a dry run
   of all 30 first (`logs/185-37/policy_add_dryrun.log`), then `--apply`
   (`logs/185-37/policy_add_apply.log`): 30 inserted, 0 refused, recorded 18:57:38 to 18:57:58
   UTC. 1d symbol rows 75 to 105.
2. Re-derivation. A daily dry run of the 25 names before the rows showed 0 new, changed or removed
   (`logs/185-37/daily_dryrun_before_rows.tsv`). With the rows, the dry run showed exactly the
   study's sessions (`daily_dryrun_after_rows.tsv`), and `python -m services.bar_derivation --stage
   daily --symbols <25 names> --apply` (6.1 s, exit 0, `daily_apply.tsv`) wrote one ohlcv_load row
   per name, outcome applied, every revision-ratio breach waived because the policy row is newer
   than the name's last load. A dry run afterwards shows 0 new, 0 changed, 0 removed.

| symbol | bars after | new | changed | removed | revision rows |
|---|---|---|---|---|---|
| BIL | 4,870 | 2 | 2,644 | 0 | 2,644 |
| BNO | 4,111 | 28 | 788 | 0 | 788 |
| BWX | 4,780 | 0 | 2,261 | 0 | 2,261 |
| CHTR | 4,040 | 0 | 174 | 0 | 174 |
| COPX | 4,142 | 3 | 1,404 | 0 | 1,404 |
| DNTH | 2,084 | 0 | 1,314 | 0 | 1,314 |
| GDXJ | 4,250 | 0 | 529 | 0 | 529 |
| HYG | 4,904 | 0 | 5 | 0 | 5 |
| IWC | 5,182 | 0 | 5 | 0 | 5 |
| NVDA | 6,730 | 0 | 51 | 0 | 51 |
| SIL | 3,866 | 1 | 1,130 | 0 | 1,130 |
| THC | 6,730 | 0 | 7 | 0 | 7 |
| UNG | 4,893 | 0 | 975 | 6 | 981 |
| URA | 4,002 | 0 | 1,267 | 0 | 1,267 |
| VCIT | 4,242 | 0 | 85 | 0 | 85 |
| VCSH | 4,242 | 0 | 244 | 0 | 244 |
| VIXM | 3,962 | 0 | 96 | 0 | 96 |
| VIXY | 3,962 | 0 | 96 | 0 | 96 |
| XBI | 5,199 | 0 | 1,083 | 0 | 1,083 |
| XHE | 3,907 | 14 | 1,033 | 0 | 1,033 |
| XLB | 6,730 | 0 | 19 | 0 | 19 |
| XPH | 5,080 | 0 | 1,083 | 0 | 1,083 |
| XSD | 5,195 | 0 | 1,083 | 0 | 1,083 |
| XTN | 3,913 | 1 | 1,052 | 0 | 1,052 |
| YUM | 6,730 | 0 | 494 | 0 | 494 |

Totals: 18,922 changed (every session of the 30 runs), 49 new, 6 removed, 18,928 revision rows.
The 49 new bars are IBKR interior dates d2-v2 had refused against Tradier's stale basis (BNO 28,
XHE 14, COPX 3, BIL 2, SIL 1, XTN 1). The 6 removed are UNG's Tradier-only dates inside its run
(2007-07-02, 2008-11-25, 2008-11-26, 2008-11-28, 2008-12-01, 2008-12-02), on the stale half scale,
with no IBKR answer; their old values are in ohlcv_revision.

3. D7 by hand (`services/bar_reconciliation_audit.py`, 18:59 to 19:10 UTC, 709 s wall, exit 0;
   `logs/185-37/d7_run.out`). Across all 1,502 compute_1d names: vendor_basis_run 1,471 pass and 31
   fail (46 before); policy_conformance, lineage_missing, canonical_recompute and digest_fresh 0
   fail; session_coverage 240 fail (240 before); unexplained_seam 8 (8 before). On the 25
   re-derived names: vendor_basis_run, canonical_recompute and policy_conformance 25 of 25 pass.
   session_coverage fails on 4 of them: UNG newly (1.00000 to 0.99878, its 6 holes; the 189-10
   gap-fill lane asks IBKR for them), XHE (0.98657 to 0.99012), XPH (0.99530, unchanged) and XTN
   (0.99138 to 0.99164).

Rollback. The plan assumed `--close` reverses an exception row. That holds only for an open row:
the table's trigger lets an UPDATE close an open row and refuses every change to a closed one, and
a row bounded by the pre-registered rule is closed from insertion. These 30 rows are therefore
permanent decisions; no other row can cover their dates (exclusion constraint), and DELETE raises.
Reversing one needs a migration that supersedes the append-only rule for that row. The bars
themselves are recoverable: the old values are in ohlcv_revision, and re-derivation is the same
daily command.

## Undecided runs

Remaining blocking vendor_basis_run names after the rows, each with the reason no pre-registered
rule writes a row for it:

- Withheld, unmeasured head seam (decided ibkr; a row bounded at IBKR's first session would move the
  false return into the Tradier head): ABT, BAX, BF.B, CAH, CF, CHD, COP, CPAY, DOV, DUK, EBAY, EQT,
  EWI, EWJ, EWM, EWS, EWU, FIS, FLO, GL, IBB, KIE, MGM, NI, NSC, ROST, WELL, XRT (28).
- EWT: undecided. Tradier's 2x step on 2016-11-07 is unambiguous, but IBKR's boundary move 0.033085
  sits just above its 99th percentile 0.032910, so both vendors are out of range and the boundary
  casts no vote; it would be withheld for its 1,563-date head anyway.
- KDP: undecided. On 2018-07-10 IBKR moves 1.718 and Tradier 0.108 in log terms, both above their
  0.049 percentiles; D7 says Tradier is continuous. The corporate action behind the date was not
  checked against the record. Canonical is IBKR under the 185-38 symbol row. Rule 3 writes only
  IBKR rows.
- PATK: decided tradier (IBKR jumps 2.5x on 2017-12-11, log 0.914; Tradier moves 0.2%). Canonical
  is IBKR under the 185-38 symbol row, so canonical PATK carries that false return on 2017-12-11.
  Rule 3 writes only IBKR rows.

The same 185-38 mismatch, not blocking under D7: FTV (ends 2020-10-08), IP (ends 2021-09-30) and
STE (2014-02-03 to 2014-03-17) are decided tradier and their canonical series is IBKR under 185-38
rows.

Not blocking, withheld for the same head seam: AAON, ADP, BDX, BNY, CVBF, DRI, IRM, KMB, MAS, MS,
OUT, PPL, SPG, TT, VTR, VZ, WMB (17); withheld for no-trade prints: WBD.

Owner decisions these leave open (todo 508):
1. The 45 stale-basis heads. Options: a row from the name's first observation (the 185-38
   precedent; the Tradier head becomes holes, 67,209 head dates, keeping returns correct and levels
   absent), or a vendor scale correction of the Tradier head by the measured factor (new mechanism),
   or leave the false return where D7 sees it (today's state).
2. PATK, KDP, FTV, IP and STE: the 185-38 admission sweep gave them IBKR rows because Tradier
   disagreed; the continuity evidence says Tradier is the continuous side on those runs. Closing a
   whole-history row can only shorten it to its first day.

undecided_blocking: 31
