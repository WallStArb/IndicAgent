---
status: in_progress
priority: P1
filed: 2026-11-17
source: A3 sweep run 2026-11-17 (ops_split_calendar_audit --sweep --strict --witness yahoo, exit 3: 1,529 active names, 634 lone breaks, 72 unresolved, 0 recorded_unapplied, 0 double adjusted, 0 witness errors; the unresolved list is the run's _unresolved.csv)
---

# Sweep: unresolved breaks that are not clean ratios, rescale verdicts, and reused tickers

## What

Unresolved breaks whose size is not a simple split ratio (spin-offs and distributions leave a level step at an
arbitrary ratio; large positive steps are reverse splits or a different security under the same ticker), plus
the sweep's rescale verdicts. Two rows carry `unrecorded_split` (NESR 2024-10-22, SW 2016-05-16) and two
`inseries_rescale` (APTV 2017-12-05, PNR 2018-05-01), which the sweep reads as a scale error in canonical.
SNX 2020-12-02 is the day after the Concentrix spin-off already in `config/corporate_actions/spin_off_exclusions.csv`
(2020-12-01): the break needs its disposition at the break date.

- ACVA 2025-11-06 (-0.47, reported)
- APTV 2017-12-05 (-1.26, inseries_rescale)
- BAX 2015-07-01 (-0.59, reported)
- CNO 2008-09-17 (-0.55, single_bar_reversal)
- DD 2025-11-03 (-0.86, reported)
- EBAY 2015-07-20 (-0.84, reported)
- ECHO 2008-01-02 (+0.55, reported)
- ENOV 2022-04-05 (+0.59, reported)
- ENSG 2014-06-03 (-0.48, reported)
- EQT 2018-11-13 (-0.62, reported)
- FAF 2010-06-02 (-0.82, reported)
- GSAT 2014-04-21 (+1.90, reported)
- HLT 2017-01-04 (+0.75, reported)
- HON 2026-06-15 (-0.66, reported)
- MDU 2024-11-01 (-0.65, reported)
- MSI 2011-01-04 (+1.47, reported)
- NESR 2024-10-22 (+1.27, unrecorded_split)
- NI 2015-07-02 (-0.98, reported)
- OII 2020-03-10 (-0.58, reported)
- PMTS 2021-08-05 (+3.14, reported)
- PNR 2018-05-01 (-0.41, inseries_rescale)
- POWI 2006-10-30 (+0.45, reported)
- ROKU 2017-11-09 (+0.44, reported)
- RTX 2020-04-03 (-1.24, reported)
- SIRI 2009-02-11 (-0.73, reported)
- SLM 2014-05-01 (-1.05, reported)
- SMCI 2020-01-14 (+0.55, reported)
- SNEX 2020-07-06 (+0.47, reported)
- SNX 2020-12-02 (-0.74, reported)
- SPXC 2015-09-28 (-1.53, reported)
- SSB 2004-03-09 (+1.33, reported)
- SVRA 2016-02-10 (-0.59, reported)
- SVRA 2016-09-21 (-1.57, reported)
- SW 2016-05-16 (-1.86, unrecorded_split)
- THRM 2012-06-13 (+2.02, reported)
- UAMY 2020-10-08 (+0.63, reported)
- UNIT 2025-08-04 (+0.50, reported)
- VIAV 2015-08-04 (-0.56, reported)
- XPO 2021-08-02 (-0.50, reported)
- XPO 2022-11-01 (-0.46, reported)

Reused tickers (todo 624 owns the mechanism, the pit ticker map): SN reads two breaks, the 2018-12-06 end of the
earlier issuer's bars and the 2023-07-31 start of SharkNinja.

- SN 2018-12-06 (-0.55, reported)
- SN 2023-07-31 (+4.76, reported)

## Requirement first (Musk step 1)

A spin-off or distribution is a real price event for the holder, never a split row (`spin_off_exclusions.csv`);
the sweep needs only a disposition (symbol, break date, reason, evidence URL). Decide per row: a disposition,
a split row through `--apply-rows`, or an identity fix under todo 624 (reused ticker, large positive steps).

## Scope

1. Classify each row with a non-price witness (filing or exchange notice), batched by event type.
2. Write dispositions to `config/corporate_actions/sweep_dispositions.csv`, split rows through the operator
   path, and hand the reused-ticker rows to todo 624.
3. The two `inseries_rescale` and two `unrecorded_split` rows first: the sweep reads them as scale errors in
   canonical that research would read as fabricated returns.

## Gates

The sweep lists none of these rows unresolved after one rerun; no `recorded_unapplied` or
`recorded_double_adjusted` row appears; unit suite exit code.

## Triage 2026-11-17 (indicagent-55; sweep output, Yahoo calendar via `--audit`, raw closes)

Rows left after todos 627, 628 and 630: 41. Each break was matched to the Yahoo calendar event within 10 days. Primary
documents were read, from search results naming the filings, only for the first batch; the rest is evidence from the
calendar and prices, labelled as such.

Batch 1 (dispositions prepared in `sweep_dispositions.csv`): APTV 2017-12-05 (Delphi Technologies, 1 per 3), PNR
2018-05-01 (nVent, 1 per 1), SNX 2020-12-02 (Concentrix, 1 per 1; the record date 2020-11-17 rests on a press report).
The sweep read APTV and PNR as `inseries_rescale`: the calendar adjusted them by 1.193 and 1.489, not split ratios, so
they are distributions, not canonical scale errors.

Class A, calendar lists a non-split-ratio event on the break day, the incumbents adjust by it (distributions; 16 rows; a
disposition each once its filing is read, never a row): BAX 2015-07-01 (calendar 1.841), DD 2025-11-03 (2.390), EBAY
2015-07-20 (2.376), ENSG 2014-06-03 (1.833), EQT 2018-11-13 (1.837), MDU 2024-11-01 (1.805), NI 2015-07-02 (2.545), RTX
2020-04-03 (1.589), SLM 2014-05-01 (2.798), SPXC 2015-09-28 (3.971, unmeasured), VIAV 2015-08-04 (1.758), XPO 2022-11-01
(1.683). Class A2, calendar factor under 1 (a reverse split or a consolidation combined with a distribution; read the
filing before choosing between a row and a disposition): ENOV 2022-04-05 (0.581), HLT 2017-01-04 (0.487), MSI 2011-01-04
(0.247), UNIT 2025-08-04 (0.602).

Class B, no calendar event (22 rows): ACVA 2025-11-06 (-0.47), CNO 2008-09-17 (single-bar reversal), ECHO 2008-01-02
(+0.55), FAF 2010-06-02 (-0.82), GSAT 2014-04-21 (+1.90), HON 2026-06-15 (-0.66), NESR 2024-10-22 (+1.27,
`unrecorded_split`), OII 2020-03-10 (-0.58), PMTS 2021-08-05 (+3.14), POWI 2006-10-30 (+0.45), ROKU 2017-11-09 (+0.44),
SIRI 2009-02-11 (-0.73), SMCI 2020-01-14 (+0.55), SNEX 2020-07-06 (+0.47), SSB 2004-03-09 (+1.33), SVRA 2016-02-10
(-0.59) and 2016-09-21 (-1.57), SW 2016-05-16 (-1.86, `unrecorded_split`), THRM 2012-06-13 (+2.02), UAMY 2020-10-08
(+0.63), SN 2018-12-06 and 2023-07-31 (reused ticker, todo 624). Large positive steps with no calendar event are
reverse splits Yahoo lacks or a different security under the ticker; negative ones are a distribution or a split Yahoo
lacks; moves of 0.4 to 0.6 can be real (earnings, squeezes). NESR is not a reverse split: the only October 2024 event
found is the Nasdaq uplisting on 2024-10-22 (8-A of 2024-10-18), so its +1.27 is a seam or an identity case.

Next: read the primary filing for each Class A and A2 row (batches of at most 10), write the dispositions or the rows;
for Class B measure each row's raw series across the break (does every vendor step together, then it is a real move:
disposition; does one vendor step alone, then a seam: todo 624) before a filing is sought.

## Triage of the 45 unresolved rows 2026-11-17 (worker, read-only DB, EDGAR documents opened)

Source: the A3 strict sweep's unresolved list (45 rows after 627, 628, 630 and the first batch). Per row, raw 1d closes per vendor
and kind around the break were compared with canonical (`market_data_ohlcv_tradeable`). Result: 24 dispositions written to
`config/corporate_actions/sweep_dispositions.csv`, 1 rows file prepared (UNIT), 7 breaks that need a Massive-route market split
the loader cannot write yet, 12 seam or identity cases for todo 624, 1 residual. The strict sweep rerun from the worktree reads
21 unresolved (was 45): exactly the 24 dispositioned rows left, nothing else moved, no new row, `recorded_unapplied` 0,
`recorded_double_adjusted` 0, one unused disposition (ATRO, by design, todo 622).

Mechanical classes: (a) every unadjusted vendor steps together while IBKR smart_trades is continuous: a real event all vendors
carry unadjusted (distributions, real moves); (b) one vendor alone: seam or identity; (c) incumbents continuous while Massive
steps by the full ratio: an unrecorded market split; (d) volume signature, read with the others.

| Row | Class | Evidence | Decision |
|---|---|---|---|
| ACVA 2025-11-06 | a, real move | all three Alpaca/IBKR series 8.15 to 5.09, volume x4; Q3 8-K of 2025-11-05 cuts the outlook | disposition |
| BAX 2015-07-01 | a, distribution | Baxalta 1:1, record 2015-06-17; Massive -0.588, IBKR +0.022 | disposition |
| CNO 2008-09-17 | a, real move | Massive and IBKR agree, volume x4.7, next session 7.95; no document | disposition |
| DD 2025-11-03 | a, distribution | Qnity 1:2, record 2025-10-22, regular-way 2025-11-03 | disposition |
| EBAY 2015-07-20 | a, distribution | PayPal 1:1, record 2015-07-08 | disposition |
| ECHO 2008-01-02 | a, event open | EchoStar spin-off from DISH completed 2008-01-01, first regular session; both vendors +0.55 | disposition |
| ENOV 2022-03-21 | c, Massive route | Alpaca = 3.0008 x Massive to 2022-04-04, equal after: the 1-for-3 reverse split | row, loader gap (below) |
| ENOV 2022-04-05 | a, distribution | ESAB 1:3 (record 2022-03-22) after the reverse split | disposition line prepared, lands with the row |
| ENSG 2014-06-03 | a, distribution | CareTrust 1:1, record 2014-05-22 | disposition |
| EQT 2018-11-13 | a, distribution | ETRN 0.80, record 2018-11-01 | disposition |
| FAF 2010-06-02 | b, identity | Massive pre-bars (32.84) are the parent First American Corporation (renamed CoreLogic); IBKR 14.10 is the new FAF; canonical starts 2010-05-24 | seam, todo 624 |
| GSAT 2014-04-21 | gap | no canonical bar 2012-12-20 to 2014-04-21; IBKR continuous 5.7 to 39.8 | disposition (coverage hole) |
| GSAT 2021-02-10 | a, real move | 18.45, 30.15, 36.00 on all vendors, volume x10; canonical lacks 2021-02-09 | disposition |
| HLT 2016-12-13 | b, seam | Alpaca 54.13 against Massive 26.38 (2.052, not a split ratio) | seam, todo 624 (already listed) |
| HLT 2017-01-04 | c, Massive route | 1-for-3 reverse split plus Park and HGV spin-offs, completed 2017-01-03; Massive 27.39 to 58.00 | row (reverse split) plus disposition line, loader gap; the Alpaca bars are also spin-adjusted, see 624 |
| HON 2026-06-15 | c, Massive route | Alpaca = 2.000 x Massive from 2026-06-15; 1-for-2 reverse split 2026-06-29 (8-K opened) | row, loader gap |
| MDU 2003-10-30 | c, Massive route | Massive alone, -0.4036 against ln(1/1.5); 3-for-2 split distributed 2003-10-29 (10-Q opened) | row, loader gap |
| MDU 2006-07-27 | c, Massive route | same, 3-for-2 distributed 2006-07-26 (10-Q opened) | row, loader gap |
| MDU 2024-11-01 | a, distribution | Everus 1:4, record 2024-10-21 | disposition |
| MSI 2011-01-04 | c, Massive route | 1-for-7 reverse split plus Mobility 1:8 (8-K opened); Massive 9.11 to 39.77 | row plus disposition line, loader gap |
| NESR 2024-10-22 | gap | canonical empty 2023-04-27 to 2024-10-21 (Alpaca zero-volume 2.65); IBKR continuous 3.05 to 9.14 | disposition (coverage hole) |
| NI 2015-07-02 | a, distribution | CPG 1:1, record 2015-06-19 | disposition |
| OII 2020-03-10 | a, real move | OPEC impasse crash of 2020-03-09 (-38.8 percent), Massive and IBKR agree | disposition |
| PMTS 2021-08-05 | gap | canonical empty 2020-01-16 to 2021-08-04 (Alpaca zero-volume 0.799); IBKR continuous 0.90 to 22.2 | disposition (coverage hole) |
| POWI 2006-10-30 | gap, single vendor | Massive has one bar in 2006-08 and two in 2006-10, nothing between; no second vendor before 2007-08 | residual |
| ROKU 2017-11-09 | a, real move | first earnings 2017-11-08 after close; Alpaca and IBKR agree | disposition |
| RTX 2020-04-03 | b, seam | Alpaca before 2020-04-03 is 3.391 x IBKR on every session since 2016 and about twice the as-traded UTC close; IBKR -0.016, Massive starts that day; the Carrier and Otis distribution (1 and 0.5 per share, record 2020-03-19, 8-K opened) is real but sits under the level error | seam, todo 624; distribution line prepared |
| SIRI 2009-02-11 | a, real move | bankruptcy-preparation reports, both vendors, volume x5; the CNN page returned 503, Reuters text read from a search summary | disposition |
| SLM 2014-05-01 | a, distribution | Navient 1:1, record 2014-04-22 | disposition |
| SMCI 2020-01-14 | gap | canonical empty 2018-08-22 to 2020-01-13 (Alpaca zero-volume 1.565); IBKR continuous 1.94 to 2.69 | disposition (coverage hole) |
| SN 2018-12-06, 2023-07-31 | b, identity | Sanchez Energy under SharkNinja | seam, todo 624 (already owned) |
| SNEX 2020-07-06 | b, seam | Alpaca route steps +0.405 (= ln 1.5) at the recorded 2023-11-24 split where IBKR is flat; Alpaca to 2023-11 sits at 2/3 of IBKR and Massive; canonical joins Alpaca to Massive at this date | seam, todo 624 |
| SPXC 2015-09-28 | a, distribution | SPX FLOW 1:1, record 2015-09-16 | disposition |
| SSB 2004-03-09 | b, identity | Massive 8.45 to 32.00 while IBKR holds 30 throughout; Massive pre-bars are another security | seam, todo 624 |
| SVRA 2016-02-10, 2016-09-21, 2017-01-09 | b, identity | Massive and IBKR smart_trades start 2017-04-28; Alpaca 2016 to 2017-04 is a prior issuer's history | seam, todo 624 |
| SW 2016-05-16 | b, identity | Alpaca only (255 to 39.6); IBKR starts 2024-07-08; no second witness | seam, todo 624 |
| THRM 2012-06-13 | b, identity | Massive 1.5 (2009-01) then 11.6 (2012-06-13); IBKR and the new security start 2012-06-13 | seam, todo 624 |
| UAMY 2020-10-08 | a, real move | 0.3241, 0.506, 0.5837 on all vendors, volume x12; canonical lacks 2020-10-07; no news found | disposition |
| UNIT 2025-08-04 | c, Alpaca route | exchange 0.6029 at the merger closing 2025-08-01 (8-K opened); Alpaca 4.91 / 0.6029 = 8.144 against IBKR 8.14 | row prepared |
| VIAV 2015-08-04 | a, distribution | Lumentum 1:5, record 2015-07-27 | disposition |
| XPO 2022-11-01 | a, distribution | RXO 1:1, record 2022-10-20 | disposition |
| ZWS 2021-10-05 | a, distribution | PMC spin-off with the Regal merger, closed 2021-10-04 | disposition |

Counts: disposition 24 (12 distributions, ECHO, 7 real moves, 4 coverage holes); row prepared 1 (UNIT); row blocked by a loader gap
7 (ENOV x2, HLT 2017-01-04, HON, MDU x2, MSI); seam or identity 12 (FAF, HLT 2016-12-13, RTX, SN x2, SNEX, SSB, SVRA x3, SW,
THRM); residual 1 (POWI).

### Finding: the operator rows path cannot write a Massive-route split

`--apply-rows` accepts only the rescalable series `ibkr/smart_trades` and `alpaca/sip_rth`; `massive/sip_flat` raises "no
rescalable 1d series". A market split divides the Massive route only through `massive_reference` or `calendar_market` rows
(`daily_rule._rescales`), and `--apply-market` needs the three-witness rule on a Yahoo calendar factor that is a recognised split
ratio. The seven breaks above are splits the incumbents already carry adjusted and Massive's reference omits, but Yahoo lists
them as a combined factor (reverse split times distribution: ENOV 0.581, HLT 0.487, MSI 0.247, HON 0.9535) or, for MDU, with no
incumbent series to witness (`route_conflict`). The audit therefore does not qualify any of them. Decision needed for the code
owner (a `src/` or script change, outside this docs-and-data pass): let an operator rows line name `massive/sip_flat` and write a
`calendar_market` row, keeping the filing as the witness. Until then the rows below stay here, ready to move into a rows file.
Their dispositions (the distribution dates) must land in the same commit as the rows, never before: a disposition alone would
hide the unrecorded reverse split from the gate.

```
symbol,effective_date,factor,route,calendar_adjusted_step,witness
ENOV,2022-04-04,0.333333333333,massive/sip_flat,0.047553,1-for-3 reverse split of Colfax after the ESAB distribution (ir.enovis.com/node/17521 from a search result, not opened; the 8-K d240014d8k.htm was opened and omits it); Alpaca/Massive ratio 3.0008
MSI,2011-01-03,0.142857142857,massive/sip_flat,0.064427,Motorola 8-K https://www.sec.gov/Archives/edgar/data/68505/000110465911001040/a11-1944_18k.htm (opened), 1-for-7 at 6:00 a.m. ET 2011-01-04
HON,2026-06-26,0.5,massive/sip_flat,-0.066332,Honeywell 8-K https://www.sec.gov/Archives/edgar/data/773840/000077384026000084/hon-20260625.htm (opened), 1-for-2 at 12:02 a.m. ET 2026-06-29
HLT,2017-01-03,0.333333333333,massive/sip_flat,(IBKR 56.20 to 58.00 = 0.0315),Hilton press release https://www.sec.gov/Archives/edgar/data/0001585689/000119312517001901/d302894dex991.htm (opened: 1-for-3 reverse split); spin-offs completed 2017-01-03 per Hilton's 10-K
MDU,2003-10-29,1.5,massive/sip_flat,0.001895,10-Q https://www.sec.gov/Archives/edgar/data/67716/000006771604000097/mdu10q.txt (opened)
MDU,2006-07-26,1.5,massive/sip_flat,-0.009236,10-Q https://www.sec.gov/Archives/edgar/data/67716/000006771607000097/mdu1stqtr10q.htm (opened)
```

Prepared dispositions for the same commit: ENOV 2022-04-05 (ESAB 1:3, record 2022-03-22, Enovis 8-K
https://www.sec.gov/Archives/edgar/data/1877322/000119312522100373/d240014d8k.htm opened), MSI 2011-01-04 (Motorola Mobility 1:8,
record 2010-12-21, same 8-K as the row), HLT 2017-01-04 (Park and HGV spin-offs completed 2017-01-03, regular-way 2017-01-04;
the opened press release gives no ratio), HON 2026-06-29 (Aerospace 1:2, record 2026-06-15, effective 12:01 a.m. 2026-06-29;
the break exists only after the row lands) and RTX 2020-04-03 (Carrier 1 and Otis 0.5 per UTC share, record 2020-03-19,
https://www.sec.gov/Archives/edgar/data/101829/000114036120008397/nc10010681x2_8k.htm opened; only after the Alpaca level in
todo 624 is fixed). The HLT 2016-12-13 seam remains until the Alpaca/Massive level (2.052) is explained.

### Rows file and dry run

`config/corporate_actions/split_rescale_rows_2026_11_17_t629.csv` (UNIT 2025-08-01, factor 0.6029, route `alpaca/sip_rth`): dry
run, "dry run, would write 1 of 1 decided rows". Applied 2026-11-17 after an independent recompute (below).

Independent review (indicagent worker, from `ohlcv_raw`, not the prior worker's numbers): 1d closes per vendor. Alpaca sip_rth over
2,409 shared sessions up to 2025-08-01: Alpaca / IBKR smart_trades median 0.6029 (min 0.6017, max 0.6042, the spread is IBKR's
two-decimal rounding), no session outside 0.005 of 0.6029 in 2025-07; from 2025-08-04 the ratio is 1.0000 (0.9991 to 1.0031, 320
sessions). Alpaca closes 5.32, 4.91, then 8.09 on 2025-08-04 (step +0.499); IBKR, which is already on the new scale throughout,
reads 8.82, 8.14, 8.09 (step -0.006, the real move, equal to the row's calendar step -0.006162). Massive's UNIT 1d starts
2025-08-04, so it holds nothing on the old scale and needs no rescale. Direction: Alpaca closes up to 2025-08-01 rise by
1/0.6029 (4.91 becomes 8.144 against IBKR 8.14). The 8-K evidence in the row (0.6029 shares of new Uniti per old share, effective
2025-08-01) matches; effective_date 2025-08-01 is the last old-scale session as the loader defines it. Verdict ACCEPT.

Run: `--apply-rows ... --commit` wrote 1 of 1 rows (exit 0); `services.bar_derivation --stage daily --apply --symbols UNIT` (exit 0);
`ops_source_policy --reselect-only --timeframe 5m --valid-from 2003-09-01 --symbols UNIT --apply` (accepts `--symbols`; gate exit 3
from unreviewed basis flags only, as for the other names); `--stage grid --apply --symbols UNIT` (exit 0). Canonical 1d now reads
9.338, 8.824, 8.144, 8.09 across the event; 5m last pre-event bar 8.127, first post-event 7.775. The strict sweep with
`--dispositions config/corporate_actions/sweep_dispositions.csv` reads 11 unresolved (was 12), no `recorded_unapplied` or
`recorded_double_adjusted`: FAF, RTX, SN x2, SNEX, SSB, SVRA x3, THRM (todo 624) and SW 2016-05-16 (`unrecorded_split`).

### Data-integrity follow-up for the lead

The four coverage-hole dispositions (GSAT 2014, NESR, PMTS, SMCI) have real bars only in IBKR raw, which is deleted at step 7
Part F with no export, while canonical holds none for the holes (Alpaca zero-volume carry-forward rows are excluded by the
tradeable view). The evidence is recorded in the disposition lines; whether those spans should be filled before Part F is a
separate call.

## Class B mechanical test, run 2026-11-17 (read-only; raw 1d closes per vendor across each break)

Method: log step of each vendor's close from the last session before the break to the first on or after it (Massive
sip_flat, Alpaca sip_rth, IBKR smart_trades, volume above zero), against what canonical holds on the same days.

- Real moves, every vendor with data steps together (disposition `real move, all vendors agree`, no row): ACVA
  2025-11-06 (Alpaca -0.47, IBKR -0.47), CNO 2008-09-17 (Massive -0.55, IBKR -0.57), ECHO 2008-01-02 (+0.55 both),
  ROKU 2017-11-09 (+0.44 both), SIRI 2009-02-11 (Massive -0.73, IBKR -0.61; the 0.12 gap is the vendors' own
  closes, not a scale). OII 2020-03-10 and UAMY 2020-10-08 are real moves read on a volatile neighbouring session: OII
  falls 8.17, 4.81, 4.57, 3.57 across 2020-03-06 to 2020-03-11 (the oil crash, canonical Massive) while the vendors read
  -0.05 on the break day itself; UAMY goes 0.324, 0.580, 0.608, 0.420 in canonical with every vendor flat on the break day.
- Massive alone steps, IBKR flat (the incumbents carry an adjustment Massive's unadjusted series does not; the
  `calendar_market` class without a Yahoo event, so a filing decides row or disposition): FAF 2010-06-02 (Massive -0.82,
  IBKR +0.03; a distribution by size), SSB 2004-03-09 (Massive +1.33, IBKR +0.02; reverse-split-like).
  HON 2026-06-15 reads the same way (Alpaca 440 on 2026-06-12, Massive 227 on 2026-06-15, Alpaca and IBKR flat) but
  Massive's series starts that day, so it is also the seam class below; read the filing first.
- Massive's series starts on the break date, canonical joins an earlier series to it at another level (identity or seam,
  todo 624 with the pit map): GSAT 2014-04-21 (canonical Massive 40.05 against IBKR near 1.5 at the incumbents' scale),
  PMTS 2021-08-05, SMCI 2020-01-14, SNEX 2020-07-06 (Alpaca 7.33 to Massive 11.70), with HLT and ENOV of todo 628.
- Canonical hole, no price event: NESR 2024-10-22 (canonical holds no bar before 2024-10-22; the sweep step is against an
  older bar across a gap; every vendor is flat, +0.00; no reverse split exists: the only event is the Nasdaq uplisting).
  File with the coverage holes (todo 624's NESR note, `session_coverage`).
- Alpaca-only history, no second vendor to test against: SVRA 2016-02-10 (-0.59), SVRA 2016-09-21 (-1.57), SW
  2016-05-16 (-1.86): thin microcap histories; needs the filing or the identity map before any ruling.
- No volume-bearing raw bar from any vendor in the window: POWI 2006-10-30, THRM 2012-06-13: canonical's neighbours come
  from a series the raw window does not show (or a hole); trace canonical lineage for the two dates first.

Order for the next worker: (1) write `real move` disposition lines for the seven real-move rows above; (2) Class A and
A2 filings in batches of ten; (3) FAF, SSB and HON filings; (4) the seam rows into todo 624; (5) NESR, POWI, THRM
into the coverage list. The lead session (indicagent-77) was not reachable when this was written.

## Worker pass 2026-11-17 (steps 2 to 5; prepared, nothing applied, no DB write)

Class A: all eleven distribution rows already carry a disposition (the 24 of the triage above); RTX 2020-04-03 stays with the Alpaca
level error in todo 624. Class A2 and the Massive-route splits: the six rows are in
`config/corporate_actions/split_rescale_rows_2026_11_17_massive_route.csv` (ENOV, MSI, HON, HLT, MDU x2); `--apply-rows` dry run on
the writer of todo 633: "dry run, would write 6 of 6 decided rows". The draft `calendar_adjusted_step` values were wrong for
the combined-factor lines (ENOV read "conflict", HON "adjusted", HLT "conflict"): the column is the real move net of the split
alone, not Yahoo's fully adjusted step. Corrected as: ENOV -0.5088 and HON -0.7113 (Alpaca sip_rth, adjusted for the reverse split
and not for the distribution, steps across the effective date); MSI -0.4832 and HLT -0.3475 (no split-only incumbent series;
Yahoo's adjusted step less `ln(calendar_factor / factor)`, `calendar_factor` filled in the file). UNIT stays in its own rows file.
The matching distribution dispositions (ENOV 2022-04-05, MSI 2011-01-04, HLT 2017-01-04, HON 2026-06-29) are in
the pending dispositions file (moved into `sweep_dispositions.csv` on 2026-11-17), deliberately not in `sweep_dispositions.csv`: they
move there in the same commit that applies the six rows, never before (a disposition alone hides the unrecorded reverse split).
Todo 633 scope 2 is therefore down to apply, reselect and the sweep rerun.

Step 3: HON is decided by its row (above). FAF 2010-06-02: the pit snapshots name FIRST AMERICAN CORP (THE), CIK 0000855182, at every
month-end to 2010-05-31 and FIRST AMERICAN FINANCIAL CORPORATION, CIK 0001472787, from 2010-06-30, so the pre-event Massive bars
are the parent (CoreLogic) and the series is an identity seam (todo 624). SSB 2004-03-09: the pit snapshots name the ticker
CITIGRP GLB MKTS HLDGS INC STREET.COM SECTOR 06 (a structured note, delisted 2006-05-31) from 2003-12-31 to 2010, and South
State Corp only from 2020; Massive's 801 canonical bars to 2006-12-29 are not SouthState (IBKR holds 30 throughout since 1999),
so also an identity seam (624).

Step 5: THRM 2012-06-13 is an identity seam, not a hole alone: the pit snapshots read THERMAGE, INC. (delisted 2009-01-12) at
2006-12-29 to 2011-12-30 and GENTHERM INC (CIK 0000903129) from 2012-12-31 (Gentherm took the ticker from Amerigon, ARGN, on the
break date); canonical holds Thermage bars 2006-11-10 to 2009-01-09 and then nothing until 2012-06-13 (todo 624). POWI 2006-10-30:
canonical lineage is Massive alone on both sides at one adjusted scale (6.90 then 10.86, raw / 2), the same issuer by the pit names,
a two-bar raw span between 2006-08-01 and 2006-10-30, and no second vendor before 2007-08-13: disposed as a coverage hole in
`sweep_dispositions.csv`. NESR 2024-10-22 already has its coverage disposition (with GSAT, PMTS, SMCI; todo 632 owns the bar-days
ahead of Part F).

Coverage list (disposed as returns across a hole, not rescales): GSAT 2014-04-21, NESR 2024-10-22, PMTS 2021-08-05, SMCI 2020-01-14,
POWI 2006-10-30 (the last has no IBKR bars to lose at Part F; the hole is Massive's own).

Unresolved with reason: RTX 2020-04-03 (Alpaca level, 624), FAF, SSB, THRM, SNEX, SVRA x3, SW, SN x2, HLT 2016-12-13 (identity or seam
cases, ticketed in 624 with witnesses); the six Massive-route rows plus UNIT await the apply.

## Result 2026-11-17 (after the 633 apply)

The six Massive-route rows are applied. The disposition file had seven duplicate keys (ACVA, CNO, ECHO, ROKU, SIRI, OII, UAMY) that made the loader raise; the later copies are dropped. Strict sweep: 12 undecided of 610 breaks: FAF 2010-06-02, RTX 2020-04-03, SN 2018-12-06, SN 2023-07-31, SNEX 2020-07-06, SSB 2004-03-09, SVRA x3, THRM 2012-06-13, UNIT 2025-08-04 (all reported) and SW 2016-05-16 (unrecorded_split). The UNIT 0.6029 rows file is not applied: no independent review of it is recorded. Unused dispositions: ATRO 2026-06-15, HLT 2017-01-04 (its break is gone after the HLT row).

## Result 2026-11-17 (todo 624 dispositions applied)

The 9 prepared lines (FAF, SN x2, SSB, SVRA x3, SW, THRM; classes identity and real_move) moved into `sweep_dispositions.csv`. Strict sweep: 3 undecided of 609 breaks: RTX 2020-04-03 (open, untouched), SNEX 2020-07-06 (route row blocked by the existing-row guard; code proposal in todo 624) and SW 2016-05-16 (`unrecorded_split`, an identity line cannot rule it). Counts: identity 6, real_move 562.

RTX 2020-04-03 closed 2026-11-17: Alpaca x0.5 route row applied (todo 624) and the Carrier and Otis distribution disposition added
to `sweep_dispositions.csv`; strict sweep leaves only SW 2016-05-16.
