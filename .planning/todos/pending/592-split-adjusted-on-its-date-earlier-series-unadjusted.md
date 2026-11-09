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
