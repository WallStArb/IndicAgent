---
status: pending
priority: P1
filed: 2026-11-04
source: todo 587 review, per-series split audit (ops_split_calendar_audit, 2026-11-04 rerun)
---

# Splits canonical crosses adjusted on their date while an earlier raw series is off scale

## What

The 587 audit records a split only when canonical steps by the ratio on its date. With every raw
series now measured on its own (its close over Yahoo's split-adjusted close across the date, 20
sessions a side inside the neighbouring calendar events), nine splits canonical crosses cleanly
show a raw series off scale before them. When that series serves canonical before a seam, the break
lands at the seam instead (the 2016-01-04 IBKR-to-Alpaca seam for the Alpaca-era cases).

Per-series log step across the date (-log f = unadjusted, +log f = adjusted twice, null =
unmeasurable), from `config/corporate_actions/split_calendar_audit_2026_11_04.csv`:

| Split | f | canonical at the date | step per series |
|---|---|---|---|
| FBIZ 2015-08-31 | 2 | ibkr/named | ibkr/smart_trades +0.693 |
| IJR 2017-01-19 | 2 | alpaca/sip_rth | alpaca 0.000, ibkr +0.693 |
| MTCH 2020-07-01 | 3.5 | alpaca/sip_rth | alpaca 0.000, ibkr -1.129 (IAC separation) |
| MVBF 2014-04-02 | 2 | ibkr/named | ibkr null |
| NVDA 2001-09-10 | 2 | ibkr/named | ibkr -0.693 |
| PATK 2017-12-11 | 1.5 | alpaca/sip_rth | alpaca 0.000, ibkr +0.916 |
| RJF 2021-09-22 | 1.5 | alpaca/sip_rth | alpaca 0.000, ibkr +0.405 |
| UHAL 2022-11-10 | 10 | ibkr/fallback | both null |
| WST 2004-09-29 | 2 | ibkr/named | ibkr -0.693 |

NVDA and WST (ibkr/named, canonical adjusted at the date but the raw series not) mean canonical's
own step was measured on a different bar set than the series median: check for a mid-span raw
restatement. The + cases are IBKR history adjusted for a split it did not carry (or twice).

## Do

Per case, find where canonical breaks (D7's generalized split_continuity on a dry run names the
seam), decide the fact (a calendar_audit row naming the off-scale series, a quarantine, or nothing
when that series never serves canonical), and fold the rule into the audit if a class emerges.
Not part of the 587 landing.

## Measured 2026-11-09 (lead session indicagent-d8): per-case decisions

Canonical 1d log-steps measured at and around each date (70-session window, then every |step| >
0.35 over the 1,200 sessions before the split), raw series pulled per junction from `ohlcv_raw`:

| Case | Canonical break | Measured fact | Decision |
|---|---|---|---|
| FBIZ | +0.692 at 2015-08-19 (flat at the 08-31 calendar date) | IBKR's series switches from adjusted (11-level) to raw (22-level) at 08-19 while Tradier shows raw ~22 flat through August: the vendor anchored the 2015-08-31 2:1 at 08-19, serving adjusted history before it and raw after | calendar_audit row (2:1, ibkr, vendor-anchored span 08-19); rescale the off-scale span; Yahoo adjusted already witnesses the +0.693 series step; Massive adds the non-Yahoo witness later |
| IJR | +0.697 at 2017-01-18 (flat at 01-19) | Alpaca's IJR 1d history starts 2017-01-18; the pre-01-18 span falls back to IBKR, whose series is adjusted TWICE for the 2017 2:1 (pre-split closes 34.2 vs raw 136.8 and correct-adjusted 68.4, exactly 1/4 raw) | calendar_audit row (2:1 2017-01-19, ibkr double-applied); rescale the IBKR-served span x2; canonical 2016-01-04..2017-01-17 is at half the correct level today |
| MTCH | none > 0.35 in 1,200 sessions | IBKR series (-1.129, IAC separation artifact) never serves canonical; Alpaca complete | nothing; verified clean |
| MVBF | +0.693 at 2014-04-02, -0.663 at 04-03 (single doubled bar) | IBKR raw carries 33.00 on 04-02 between 16.5 neighbors; Tradier shows NO halving anywhere across the date (16.5 -> 17): the Yahoo f=2 row is contradicted by an independent vendor | quarantine the 04-02 bar (single-bar scale error); mark the 2014-04-02 split unconfirmed pending a witness (Massive); no calendar row yet |
| NVDA | -0.811 at 2001-09-17 (= -0.693 scale halving on top of the real reopen move) | canonical switches series at 09-17: the pre-09-17 serving (named plane, ends 09-14) is at 2x the level of IBKR smart from 09-17 (0.56-level vs 0.28, the latter matching Tradier adjusted) | calendar_audit row (2:1 2001-09-10; pre-2001-09-17 span unadjusted once more); rescale [start..2001-09-14] x0.5; every early-NVDA 1d close before 2001-09-17 is 2x too high today |
| PATK | +0.873 at the 2016-01-04 seam | IBKR's series sits at 2.5x BELOW correct pre-2016 (7.73 vs 19.33 on 2015-12-31; the audit's +0.916), Alpaca correct from the seam | calendar_audit row (1.5:1 2017-12-11, ibkr over-applied); rescale pre-2016 span by the measured factor (2.5015); canonical pre-2016 PATK is ~2.5x too low today |
| RJF | none > 0.35 in 1,200 sessions | IBKR series (+0.405) never serves; Alpaca complete | nothing; verified clean |
| UHAL | -2.333 at 2022-11-09, +2.317 at 11-10 (single tenth-scale bar) | canonical serves IBKR (fallback) around the split; IBKR raw carries 5.13 on 11-09 between ~53 neighbors (the post-split level printed one day early); Alpaca raw steps exactly 10x at 11-10, witnessing the 10:1 at that date | quarantine the 11-09 IBKR bar; the f=10 2022-11-10 calendar row is confirmed by Alpaca raw (no Yahoo needed) |
| WST | -0.682 at 2004-09-30 (flat at the 09-29 calendar date) | IBKR raw halves at 09-30, one session after the calendar's 09-29 (the d2-v2 one-session effective_date offset class, todo 516); canonical never applied the 2:1, so pre-09-30 WST is 2x too high and 09-30 reads a fabricated -49% | calendar_audit row (2:1, effective 2004-09-30 per vendor); rescale [start..2004-09-29] x0.5 |

## The class emerged: junction breaks away from calendar dates

A corpus sweep of canonical 1d (ln-step per name-day; a break is |step| > 0.4 on a day when 20 or
fewer names step, which separates lone breaks from market crash days) finds **1,624 lone breaks on
379 names**. Seven of the nine cases above are members (FBIZ, IJR, MVBF, NVDA, PATK, UHAL, WST);
none of their breaks sits at a calendar split date, which is why the 587 audit (anchored at
calendar dates) never saw them. Rule to fold into `ops_split_calendar_audit`: sweep every lone
big step, not only calendar dates; classify each as (a) a series junction with inconsistent
adjustment (rescale via a calendar_audit row naming the series), (b) a single-bar scale error
(quarantine), (c) a real single-name crash (verified against a second vendor, left alone), or
(d) a real split with a vendor-offset effective date (calendar row at the vendor's date). The
1,624 need that classification; the nine above are decided.

Landing order: the nine decided cases first (quarantines and rows through the existing 587
tooling, corrected CSV), then the sweep as the audit-rule extension (a worker lane; the pin's
data gate is unaffected - none of this touches 5m coverage).

Sweep triage, measured 2026-11-09 (lead session; read-only): of the 1,624 lone breaks, only 1
sits within 3 sessions of a recorded `corporate_action` (the recorded calendar explains none of
this class); 144 are single-bar reversals (next-day step reverses within 0.1 - the MVBF/UHAL
quarantine class); 22 on 21 names sit at an `ohlcv_raw` series first/last-bar boundary (the
IJR/PATK fallback-junction class; internal gap-fill boundaries are invisible to this cut and need
the audit's per-series view); 870 drops versus 754 jumps, and the jump side points at unrecorded
reverse splits - the 587 calendar was forward splits only. The remaining ~1,450 need the audit
tool's per-series cross-check (in-series adjustment switches like FBIZ, unrecorded
splits/reverse splits, and real single-name crashes, which vendor agreement confirms and leaves
alone).

## Landed 2026-11-09 (worker session, the nine decided cases)

Mechanism: the audit tool gained `--apply-rows` (operator rows file, todo 592 class; the calendar
cannot confirm these, so `--apply`'s re-judgment cannot express them):
`config/corporate_actions/split_rescale_rows_2026_11_09.csv` (6 rows, every line its evidence).
Quarantines ride the existing `--quarantine-unconfirmed` step with two lines added to
`config/corporate_actions/operator_bad_bars.csv` (MVBF 2014-04-02, UHAL 2022-11-09); the re-run
rewrites the 13 existing 587 flags unchanged and adds 2.

Rows (inferred_by calendar_audit, d2-v5 rescales on or before effective_date):
- FBIZ 2015-08-18 f=0.5 ibkr: pre-08-19 span is exactly half correct (Yahoo/2 at every sampled
  date back to 2008); vendor anchored the 2015-08-31 2:1 at 08-19.
- IJR 2017-01-17 f=0.5 ibkr: the whole IBKR span (2016-01-04..2017-01-17) sits at half correct
  (Alpaca 68.02 vs IBKR 34.01 on 01-17); IBKR restates from 01-18.
- NVDA 2001-09-14 f=2.0 ibkr: the named plane is 2x too high through 09-14 (Yahoo 0.31567 vs IBKR
  0.63); composes with the existing 2000-06-26 row (/4 before it, /2 between).
- PATK 2015-12-31 f=0.4 ibkr: IBKR pre-2016 is uniformly at exactly 1/2.5 of correct (Yahoo x2.5
  at 2001, 2005, 2010, 2011, 2014); the measured factor is exactly 2.5, not the lead's point
  estimate 2.5015. The 2000-2010 vs 2012-2015 Tradier/IBKR ratio difference (1.667 vs 2.500) is a
  Tradier restatement artifact; Tradier serves nothing.
- WST 2004-09-29 f=2.0 ibkr: IBKR halves at 09-30, one session after the calendar (todo 516
  offset class); effective_date is 09-29 by migration 400's definition, so the rescale span is
  [start..09-29] and the fabricated -49% at 09-30 becomes a normal day.
- UHAL 2022-11-09 f=10.0 alpaca: Alpaca raw is unadjusted 10x over its prefix (528.92 -> 52.02 at
  11-10, the witness); IBKR is deliberately not named (already adjusted before the split, raw
  from 11-10), so no served value changes; the row is the recorded fact.

Not expressible finding: none beyond the tool extension above. MVBF takes no calendar row (split
unconfirmed pending Massive); RJF and MTCH took nothing and re-verified clean (no canonical step
> 0.35 in 1,200 sessions; their stray IBKR series never serves canonical).

## Completed 2026-11-09 (lead indicagent-d8, after the worker hit the API limit)

- **MTCH became the tenth case**: the worker found a -1.503 canonical step at the 2016-01-04 seam
  that the lead's windowed scan missed (the corpus sweep had it). IBKR's series sits at 4.4963x
  above correct over its whole pre-2016 span (60.05 vs Alpaca/Tradier 13.36/13.55, constant
  across 2015-12-28..2016-01-08). Row added to split_rescale_rows_2026_11_09.csv and written via
  `--apply-rows --commit`; re-derived with MVBF and UHAL.
- **The two quarantines are effective on the consumed surface**: canonical (`market_data_ohlcv`)
  keeps the flagged row by design; `market_data_ohlcv_tradeable` (what compute reads) excludes
  it. MVBF 2014-04-02 and UHAL 2022-11-09 are absent from the tradeable view, as are the 587
  thirteen (verified on FTNT/CMCSA/CDE/CME). The lead's earlier "junctions unchanged" reading
  was a wrong-surface check against raw canonical plus a race with the worker's in-flight apply.
- **All junctions verified on the tradeable surface** (max |step| at the junction window,
  2026-11-09): FBIZ 0.005, IJR 0.013, MTCH 0.023, MVBF 0.030, NVDA 0.038, PATK 0.043, UHAL
  0.017, WST 0.045. All normal daily moves.
- Open: the D7 split_continuity confirm rides tonight's 06:00 UTC nightly; the sweep (the
  1,624 lone breaks, triage in this file) is the follow-up lane; MVBF's split stays unconfirmed
  pending a Massive witness.

## Sweep landed 2026-11-10 (worker indicagent-0b, brief d8)

The audit tool gained `--sweep` (commit 14e844081): every lone canonical 1d break (|ln step| >
0.4 on a day at most 20 names step) classified by the per-series method - Yahoo's adjusted
close as the continuity witness, every rescalable raw series measured on its own across the
break. Fresh enumeration after the ten-case landing: 1,389 breaks on 371 names.

| verdict | count | disposition |
|---|---|---|
| real_move | 799 | Yahoo adjusted carries the step (two witnesses); left alone |
| reported | 449 | 393 no Yahoo witness across the break (vendor absence is not a witness; Massive can revisit), 51 a tape that steps neither flat nor the break, 3 junction levels undecided, 2 post-side-off junctions a prefix rescale cannot express |
| single_bar_reversal | 123 | quarantined as operator_bad_bar (batch 2, commit f544bd8f7); 0 of the 131 listed bars remains in the tradeable view |
| junction_rescale | 5 | 4 landed (batch 1): ELS 2019-10-15 x0.5, GYRE 2023-01-12 x0.673, OKE 2015-12-31 x2.836, QBTS 2022-08-05 x0.688; NEXN 2025-02-14 x2.0 held (587 bad-bar conflict) |
| inseries_rescale | 5 | OKE 2012-06-01 x0.504 landed (calendar 2.0 matches the measured factor); BHP, F, INSM, XPO held (below) |
| unrecorded_split | 8 | GSAT 2021-02-08 x0.610 landed (both tapes step together: ibkr and alpaca 16.05 -> 26.32); HSIC, OVV, TMUS, RCAT x3, OKE-2005 held (below) |

Batch 1 (6 rows, 5 names) applied via `--apply-rows --commit`, re-derived (14,465 rows
rewritten), junctions verified: every fixed break session now steps at its recorded real move
(ELS -0.003, GSAT +0.174, GYRE -0.875, OKE +0.019/+0.000, QBTS +0.144); the scale component
is gone. The whole-history max-step check does not apply here: GYRE's 2023 -0.875 and QBTS's
+0.215 are real same-window moves the rows preserve by design.

Held rows, no fix without vendor agreement (lead decides):

- Spin-off suspects (fractional calendar factor, the 587 exclusion class): BHP 2001-07-12
  (calendar 2.0651, measured 2.173), F 2000-08-02 (1.748 / 1.704), XPO 2021-07-30
  (1.718 / 1.627). A spin-off's value drop looks identical to a split on tape + Yahoo flat;
  these belong to the dividend layer if the calendar confirms them as spin-offs.
- Factor/calendar mismatch: INSM 2000-07-28 (calendar 0.25, measured 0.199, 28-day anchor gap).
- Single tape, no ratio corroboration: HSIC 2013-03-12 (1.53x), OVV 2009-12-03 (1.96x, the
  Encana spin-off era) - unrecorded split and unrecorded-to-Yahoo spin-off are not separable
  from one tape; needs Massive or a second vendor.
- Thin-series names (todo 454): RCAT x3.
- Hole span: TMUS (pre-break span ends 2013-04-30, break 2015-10-27, a 2.5-year hole; the
  pre-IPO-era data is suspect).
- 587 bad-bar conflicts: NEXN 2025-02-14 x2.0 and OKE 2005-04-12 x1.985 - the sweep's
  junction/unrecorded diagnosis contradicts the landed 587 quarantine of the same event; the
  lead rules whether the rescale row replaces the quarantine.

## Sweep rulings (lead indicagent-d8, 2026-11-10, on 0b's held list)

1. Spin-off suspects with fractional calendar factors (BHP 2.0651, F 1.748, XPO 1.718): NO split
   rescale. A spin-off's value drop is a distribution, not a split; rescaling would fabricate
   price continuity across a real value transfer. Recorded as spin_off-suspect rows; they belong
   to the distribution/dividend layer (todo 516's class), confirmed by Massive corporate events
   or the 516 design.
2. INSM (calendar 0.25 vs measured 0.199): hold. Never rescale against a contradicting
   calendar; a witness decides (Massive).
3. HSIC, OVV (single tape, no corroboration): hold, the no-witness-no-fix rule.
4. RCAT x3: todo 454's ultra-thin series class owns it.
5. TMUS (pre-break span ends 2013-04-30, break 2015-10-27): hold; the hole makes it undecidable
   until coverage fills.
6. NEXN x2.0 and OKE-2005 x1.985 vs the 587 quarantines: conditional land - if Yahoo-adjusted
   corroborates the SUSTAINED factor, land the rescale row and retire the 587 quarantine in the
   same change (a single-bar quarantine inside a sustained mis-scaled span is incoherent, and
   the quarantine's no-corporate-action premise is superseded). If tape-only evidence, hold with
   the others.
Systemic: rerun `--sweep` after Massive is admitted (393 of the 449 reported are Yahoo-coverage
holes; the reported mass should shrink materially).

## Parked 2026-11-10 (owner directive: "stop wasting time on that data, we will get Massive")

The sweep follow-ups (GSAT's D7 diagnosis, NEXN/OKE ruling 6, the 393 Yahoo-hole holds) are
PARKED pending Massive admission: every remaining case is a pre-2016 or replaceable-era span
that Massive's independent files either fix outright or witness, so further IBKR/Alpaca-era
polishing is wasted motion. The three D7 split_continuity red rows (GSAT, NEXN, OKE|1d) are
KNOWN-ACCEPTED until the Massive-era sweep rerun resolves them; do not chase them. The landed
fixes stay (done, verified, no ongoing cost). Resume point: after admission, rerun
ops_split_calendar_audit --sweep with Massive as witness per the ruling above.
