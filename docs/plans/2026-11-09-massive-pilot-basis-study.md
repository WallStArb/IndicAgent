# Massive flat files: pilot basis study and admission gates

**Status:** Running (pilot agent), under the 2026-11-10 amendment (A1-A12), which governs every
gate. Executes under todo 600.
**Author:** Claude session indicagent-d8, 2026-11-09; amendment by session indicagent-22,
2026-11-10, approved by the lead.
**Informed by:** todo 600, todo 587 (the unadjusted-split class this study must detect), todo 518
(volume basis is labelled, not gated), `docs/foundation/canonical-truth-registry.md`,
`docs/plans/2026-11-10-massive-admission-db-design.md`.

## Constraints

No corpus compute (owner 2026-11-04). Downloaded files are untrusted input: parse them by explicit
path and never run an interpreter from inside the download directory.

## Step 0: layout probe (one file) - MEASURED 2026-11-10

Access opened 2026-11-10 (owner plan upgrade + regenerated S3 key in `.env`; the old free-plan
key kept listing-only). Measured facts, from the file not the docs:

- Key layout: `us_stocks_sip/minute_aggs_v1/<YYYY>/<MM>/<YYYY-MM-DD>.csv.gz` - gzip, NOT
  `.csv.zip` as the docs say. Day-aggs parallel: `us_stocks_sip/day_aggs_v1/...csv.gz`.
- Columns: `ticker,volume,open,close,high,low,window_start,transactions`.
- `window_start` is NANOSECONDS (1262614800000000000 = 2010-01-04 14:20 UTC = 09:20 ET); the
  docs' seconds-versus-nanoseconds disagreement resolves to nanoseconds.
- Extended hours are included (first bars pre-open); RTH cut is our job at read.
- `transactions` (trade count) present, free with the bars.
- One 2010 day file: 12.4 MB compressed, 66.8 MB raw, 1,217,549 rows (all symbols, full day).
- Volume units and price scale: integer share counts and plain dollar prices in 2010 (the
  fractional-share era starts 2026-02-23; the 2026-era file measures that when sampled).

Write further measured facts into this section before any comparison runs.

## Step 1: survivorship (the reason this vendor is bought)

From `listing_end` plus a hand-list of tickers listed in 2010 and delisted since, sample at least
30 delisted-in-window names. The pass rule and its reporting are in A8; survivorship never gates
the verdict.

## Step 2: basis study (pre-registered decision rules)

Both aggregates are in scope (owner 2026-11-09), so the study has a 5m arm and a 1d arm.

Sample (intraday arm; the 1d arm is a census, A7): 30 names (10 liquid, 10 mid, 10 thin, including CORT-class thin names), 5 trading days in
each era: 2007, 2010, 2013, 2015 (IBKR era), 2016-01 (the seam), 2020, 2026 (fractional-share
era). Include the todo 592 nine (FBIZ, IJR, MTCH, MVBF, NVDA, PATK, RJF, UHAL, WST) and OKE and
RSPF: Massive is an independent non-Yahoo witness for exactly those open split questions.

Passing the 1d arm also qualifies Massive 1d as the independent witness for the 592 sweep's held
cases (the 393 Yahoo-coverage holes, the spin-off suspects' confirmation, INSM, HSIC, OVV, TMUS),
and the sweep reruns `--sweep` with it once admitted.

Gates that still stand from the original text:
- Scale-factor (the 587 class): per name-year, the median log close ratio is within 10 bp of 0
  after alignment by the A1 factor. Any name outside is investigated and listed with its factor
  and the corporate actions in window.
- OHLC sanity: high at or above max(open, close), low at or below min(open, close) on at least
  99.9 percent of bars; violations listed (A11 adds the record checks).
- Seam rule: the same tolerances hold on both sides of 2016-01-04.

Replaced by the amendment: the price gates (per name-day median at or under 1 bp and p99 at or
under 10 bp, 99 percent of RTH minutes matched) by A2 and A6; the vendor-wide volume median
(0.5 to 2.0) by A9. The original text is in git (b371b84c9).

## Interpretation ruling (owner, 2026-11-10): Massive is the yardstick

The gates stay symmetric (agreement measures with pre-registered tolerances; nothing is re-tuned
after seeing data). What changes is the burden of proof: where Massive and IBKR/Alpaca disagree
beyond a gate, the finding is recorded as a suspected INCUMBENT defect (span-level error of the
592 class - our incumbents are proven carriers of wrong adjustment bases and mis-anchored
splits), not a Massive failure. Post-admission, integrity checks and the sweep adjudicate
against Massive as the reference standard. One limit, stated: paid does not mean infallible - a
units, session-boundary or scale error on Massive's own side is still possible, and the verdict
must say so plainly if the evidence points there.

## Amendment 2026-11-10 (adversarial review, pre-verdict)

The study's gates are amended before any verdict is computed. Reason: an adversarial review
(Fable subagent of session indicagent-22, 2026-11-10) established by calibration probes, not
outcome peeking, that three gates fail for benign known reasons. Under the yardstick ruling
above, those failures would be filed as incumbent defects, leaving the verdict to discretion.
Amendments are dated. The pilot agent states in its report which gate outcomes, if any, were
computed before this amendment. Where this section conflicts with steps 1 and 2, this section
governs. Probe evidence: 10 sessions of 2010-03 1d (835 matched names), 2010-01-04 5m, and the
2003-09-10 day and minute files.

### A1. Adjustment factor: frozen, never fitted

Probe: 286 of 835 names show a Massive/IBKR 1d close ratio away from 1. `corporate_action_current`
(394 rows) explains 1 of them; it lacks AAPL's 2014 and 2020 splits (ratio 27.9994) and NVDA's
last two (ratio 40.2 on 2010-01-04). 103 of the 286 sit near no simple split ratio (ABT 2.0897,
ADP 1.1399, BDX 1.2816), so IBKR `smart_trades` carries non-split adjustments that no split table
reproduces.

Rule. The alignment factor is never fitted from the compared series.
- Its source is a split list frozen and hashed (sha256 recorded in the evidence tables) before any
  comparison runs.
- Massive's reference splits may enter that list, labelled non-independent of the Massive bars.
- Each name-era is pre-classified from the frozen list, before comparison, as one of:
  (a) no corporate action after the compared date, (b) splits only, (c) non-split adjustment.
- The price and scale-factor gates apply to classes (a) and (b). Class (c) is reported as a
  convention difference and left out of the admission count.

Massive's splits endpoint is being captured today by a parallel lane. Under section 5 of
`docs/plans/2026-11-10-massive-admission-db-design.md`, it becomes the input for reconciling
corporate actions. The calendar gap this probe found (AAPL's and NVDA's missing splits) is fixed
from that capture, separately from this study. A1 holds either way: the list this study uses is
whichever list is frozen and hashed before comparison.

### A2. Price agreement: increment-aware band

Probe: IBKR stores adjusted prices at cent precision; NVDA's 2010 close of 0.46 carries a rounding
band of about 108 bp. Among the adjusted names, 254 of 286 move more than 1 bp around their own
median ratio. Among the 549 ratio-1 names, 102 breach 1 bp and 48 breach 10 bp on at least one
day. At 78 bars a day, a p99 is effectively the maximum. The 1 bp median and 10 bp p99 gates of
step 2 are replaced.

Rule.
- A bar agrees when |Massive / F - incumbent| is at most half the incumbent's stored price
  increment plus 1 bp of the incumbent price, with F the A1 factor.
- Gates: at least 99 percent of matched bars agree per name-era, pooled over the era's days; at
  least 99.5 percent agree vendor-wide.
- Each disagreeing bar is classified by a pre-set list: rounding, last-print eligibility, scale,
  time shift, other. "Other" above 0.5 percent of matched bars vendor-wide is investigated and
  listed before any verdict.

### A3. Identity: a frozen ticker-as-of-date map

Probe: Massive `BNY` in 2010 closes at 14.62 on 17,634 shares; our `BNY` is Bank of New York
Mellon at 28.42 (Massive carries it as `BK`), a ratio of about 0.5 that would read as a split
defect. 86 of 921 IBKR-held names have no Massive row under the same ticker (QQQ is QQQQ, MSCI is
MXB). Massive `BSC` on 2009-06-15 trades 500 shares a year after Bear Stearns was acquired.

Rule. Before step 2 runs, a ticker-as-of-date map for every sample name is frozen and hashed, with
evidence that does not come from price: Massive ticker events and details (share-class FIGI),
IBKR contract details, filings.
- Known corrections enter the map: MTCH is `IACI` in Massive's 2010 files, RSPF is `RYF`, QQQ is
  `QQQQ`. The map is the complete list, not just these three.
- A mapped pair whose daily return correlation is under 0.9 over the era is identity-unresolved.
  It is listed, never counted as a scale or split finding.

### A4. Tie-break for the yardstick ruling

The ruling above sets the burden of proof but names no test. A disagreement beyond a gate is
recorded as an incumbent defect only when a third witness sides with Massive:
- Massive's own continuity across eras;
- an exchange-official close;
- a split dated by a filing.

Without one it is unresolved. Unresolved disagreements above 2 percent of name-eras count against
admission (A10). From 2016-01-04, agreement with Alpaca SIP is recorded as non-independent (same
upstream as Massive) and carries no weight on units, session or scale. IBKR 5m and 1d are the
independent arm for the 2016 seam, 2020 and 2026.

### A5. Internal consistency: day file against its own minute file

Probe, 2003-09-10, 7,716 tickers. Against the RTH minute aggregate, the day file's close differs
on 1,976 names and its volume on 4,273. Against the all-hours aggregate, 1,807 and 3,337. AA's
day volume is 3,543,400 against 3,239,500 summed from all its minutes.

Rule. Per era, compare each day file's O, H, L, C and V with both the RTH and the all-hours
aggregate of the same day's minute file. Report mismatch rates per field. Pre-set consequence: if
close mismatches the RTH minute aggregate on more than 1 percent of names in any era, canonical 1d
is built from RTH minutes (admission design section 3), and the served day file stays archived
only.

### A6. Intraday comparison at 5m on traded buckets

No 1m incumbent exists before 2026-05, so "RTH minutes matched" in step 2 is undefined. IBKR emits
zero-volume bars where Massive has none: CORT 57 of 78 bars on 2010-01-04, PATK 60 of 78, FBIZ 44
of 47.

Rule. Compare at 5m, keyed by window start, after the RTH cut. Aggregate Massive minutes per
admission design section 4: cut to session first, traded minutes only. The match denominator is
traded buckets only (incumbent volume > 0). Zero-volume incumbent bars, and incumbent traded
buckets that Massive lacks, are counted and listed separately, never assumed no-trade.

### A7. Sample: a 1d census, 592 straddles, seeded draws

Probe: five days per name-year sit on one side of a split, so a mis-anchored split date is
invisible; 30 names miss a defect affecting 5 percent of names 21 percent of the time.

Rule.
- The 1d arm is a census: every held name, every session in the archive, all of O, H, L and C (the
  day files total about 1 GB).
- For the todo 592 names and OKE, add the ten sessions on either side of each disputed date, in
  both arms.
- The 5m days are fixed by a seeded draw (seed recorded) before comparison. Each era includes at
  least one early close and one session after a DST change.
- The 30-name intraday sample stays as specified, with A3's identity map applied.

### A8. Survivorship: presence through the last exchange session

Probe: LEH, BSC, MER, WB, WM and CFC are present on 2008-03-03; GM and LEH are absent on
2009-06-15 (OTC trading is not on the SIP).

Rule. A delisted name passes when its bars run through its last exchange session and its last
price is consistent with the delisting event (acquisition price, bankruptcy collapse). Trading
after an OTC move is stated as out of coverage, not counted as missing.

Survivorship is measured and disclosed, never a gate (owner 2026-11-10: "there's no better option
- it's the best choice regardless if 70% or 100%"). Every alternative (IBKR, Alpaca) holds no
delisted names at all, so any presence rate improves on the incumbents. Step 1 reports the
presence rate, its era breakdown, and the list of names that fail. The caveat lifts per name and
span: a name that passes is survivorship-clean for its covered span; the residual caveat on
pre-2016 results names the measured rate and the missing names.

### A9. Volume bands per era and listing exchange

Probe: IBKR/Massive volume ratio p50 0.943, p1 0.537, p99 1.572. A single vendor-wide median
catches only a global units error.

Rule. Per era and per listing exchange (`listing_venue`), the median ratio must lie in 0.8 to
1.25. Vendor-wide, at most 2 percent of names may have a median ratio outside 0.5 to 2.0. Name-level
basis differences inside these bands stay labelled data (todo 518).

### A10. Verdict mapping

| Gate | Unit | Threshold | Consequence if missed |
|---|---|---|---|
| Units (A2 scale classes, A9 bands) | era, exchange | as A2 and A9 | refuse |
| Session (A6 grid alignment, early closes, DST) | era | zero systematic offset | refuse |
| Internal consistency (A5) | era | 1 percent rule | 1d built from RTH minutes; refuse only if RTH minutes also fail A2 |
| Price agreement (A2) | name-era and vendor | 99 / 99.5 percent | vendor miss: refuse; name-era miss with a third witness: caveat, that name's incumbent span listed as defect; without one: unresolved |
| Unresolved (A4) | name-era | at most 2 percent | above: refuse |
| Survivorship (A8) | delisted sample | none (measured, disclosed) | never affects the verdict; the rate and failing names go into the caveat text |
| OHLC and record sanity (A11) | bar | 99.9 percent; zero duplicates | refuse |
| Publish lag, manifest (A12) | file | recorded | informational; feeds the nightly decision |

"Admit with caveats" is allowed only for the classes this table names. A gate outcome outside it
goes to the owner, recorded as outside the pre-registration.

### A11. Record sanity

The OHLC gate is satisfied by internally consistent wrong data (zero violations in 870,880 rows of
2003 minutes). Add these checks:
- price strictly positive and volume at or above zero on every bar;
- (ticker, window_start) unique within a file;
- the same checks on the day files.

### A12. Publish lag and manifest completeness

Record the time each of the last 20 sessions' files first appeared (from LastModified in
`data/massive/manifest/servetimes_*.jsonl`), as lag after the 16:00 ET close. Record the manifest
completeness proof: every NYSE session in the archive range has both files, each parses, with row
counts and sha256 (the 2026-11-10 inventory check found 5,829 of 5,829 per dataset).

## Step 3: verdict and what follows

Write the evidence tables under `logs/massive_pilot/`, one summary in this doc, and a
recommendation to the owner: admit, admit with caveats, or refuse, mapped from the gate outcomes
by the A10 table. Admission then runs section 8 of the admission design. If admitted, the deletion
list (todo 600, open item 4) is drafted for the owner's call. Before sizing the full load, record
one full year of raw row counts.

## Handling

Files come from the downloader (`scripts/infrastructure/massive/massive_download.py`) into
`data/massive/files/`, archived as delivered. Every comparison script lives under `scripts/ops/`,
reads by explicit path, and writes only under `data/` or `logs/`.
