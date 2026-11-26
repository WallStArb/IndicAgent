---
status: pending
priority: P3
filed: 2026-11-17
source: step 7 D4 disposition (session_coverage and proven_start_1d red for SN); ruling 2026-11-17 (indicagent-77): the pit ticker map owns identity
---

# Reused-ticker history reaches canonical (SN: Sanchez Energy bars under SharkNinja)

## What

Canonical `SN` holds one series built from two securities. Witness, non-price (Massive `reference_raw`
`pit_snapshots` month-end lists and `events`/`overview`): ticker SN is Sanchez Energy (CIK 0001528837) at
every month-end from 2011-12-30 to 2023-06-30, and SharkNinja, Inc. (CIK 0001957132) from 2023-07-31, the
date of its `ticker_change` event. Alpaca raw for SN holds real volume bars 2016-01-04 to 2019-02-19 (the
earlier issuer; 252, 251, 251 and 33 sessions in 2016 to 2019), then only zero-volume rows to mid-2023 (1,118
sessions), then real bars from 2023-07-31 (IBKR `smart_trades` starts the same day).

Before the rebuild canonical began at IBKR's first bar, so `proven_start_1d` was 2023-07-31 and
`session_coverage` 1.0. The rebuild selects Alpaca from 2016, so canonical now carries the earlier holder's
bars and a 1,118-session hole, and coverage reads 0.5907 (red in the D4 rerun). The coverage failure is the
symptom. The defect is a cross-issuer return series: the first-bar of SN's history belongs to a different
company, and any feature or IC computed across it mixes two securities.

## Ruling

The pit ticker map owns it: identity decides which history belongs to a security. A proven-start floor would
be a patch that hides the cross-issuer series, so it is not the fix.

## Requirement first (Musk step 1)

Should pre-listing and reused-ticker history be excluded by the map at selection time? Answer how that
interacts with the stage 2 universe (todo 609, identity key rule: a reused ticker is two securities) and the
held `wt-pit-map` stack (its identity map and stage 2 instrument writer; the index migration is numbered 601
in that worktree and renumbers at landing). Measure the class first: how many active names have raw bars under
a ticker before the security's own first date by the map (SN is the known case; the coverage-red set of 93
names in the D4 rerun is the first place to look, and NIQ and BELFA have raw holes of their own). Then pick
one mechanism: selection filters bars by the map's span for the instrument, or the instrument row carries the
security's first date and canonical selection starts there.

## Scope

1. Measure the class from the map and `ohlcv_raw` (read-only), with a count and the names.
2. Decide the mechanism with the 609 and `wt-pit-map` owners; write it into the unified design section on
   identity.
3. Build in a detached worktree after Part F and the post-D1 landings; rebuild affected names' canonical.

## Gates

SN canonical starts 2023-07-31 and `session_coverage` and `proven_start_1d` pass without a floor; no name's
series crosses two CIKs by the map; independent review; unit suite exit code.

## Further seam and identity cases from the A3 sweep (2026-11-17, todo 628 evidence pass)

Massive's series begins on the break date at another scale than the incumbents' series, so the break is a seam
or an identity question, not a split row:

- HLT 2016-12-13: Massive starts at 26.38 where Alpaca and IBKR read 54.13 on the same day (ratio 2.05); the
  sweep reads -0.70. The Massive reference holds a reverse split of 1/3 at 2017-01-03 (`tape_conflict`) and the
  sweep reads +0.75 at 2017-01-04 (todo 629): the Hilton spin-offs and reverse split of January 2017 interact
  with where Massive's history starts. Decide which entity the Massive series before 2017-01-03 belongs to.
- ENOV 2022-03-21: Massive starts at 39.69 where Alpaca reads 119.07 and IBKR 68.26; ENOV +0.59 at 2022-04-05
  follows (todo 629). A ticker whose security changed in March and April 2022.
- SVRA 2017-01-09 (+0.42): volume 62,829 to 1,456,548 on one session, Alpaca only (IBKR and Massive hold no
  bar); reads as a merger or listing event under one ticker.

Each needs the pit ticker map's span for the security before a mechanism is chosen.

## Further seam and identity cases from the 629 triage (2026-11-17, read-only DB; the sweep lists each as unresolved)

Raw first and last dates per vendor and the step per vendor decide them; no row and no disposition applies until the identity map
names the security's span.

- FAF 2010-06-02 (-0.82): canonical starts 2010-05-24 with Massive bars at 33 to 34 that belong to the parent First American
  Corporation (renamed CoreLogic on 2010-06-01; First American Financial 8-K https://www.sec.gov/Archives/edgar/data/0001472787/000095013010002251/d8k.htm,
  distribution 2010-06-01, record 2010-05-26); IBKR holds 14.10 for the new FAF the day before. The spin-off distributes the new
  FAF, so the pre-2010-06-02 canonical bars are another security.
- RTX 2020-04-03 (-1.24): Alpaca sits at 3.391 x IBKR smart_trades on every session from 2016 to 2020-04-02 and about twice the
  as-traded UTC close, equal to Massive and IBKR from 2020-04-03; IBKR steps -0.016, Massive starts that day. A level error in the
  Alpaca route before the event; the Carrier and Otis distribution is then a disposition (prepared in 629).
- SNEX 2020-07-06 (+0.47): canonical joins Alpaca (before) to Massive (from 2020-07-06); Alpaca to 2023-11 is exactly 2/3 of IBKR
  and of the Massive adjusted series (its route step at the recorded 2023-11-24 split reads +0.405 where IBKR reads -0.0001).
  Which side holds the extra 3:2 is open; an Alpaca-route rescale (factor 0.6667, effective 2023-11-24) is the candidate row.
- SSB 2004-03-09 (+1.33): Massive 8.45 on 2004-03-05 and 32.00 on 2004-03-09 while IBKR holds 30 to 31 throughout; Massive's
  earlier bars are another security under the ticker.
- SVRA 2016-02-10 (-0.59), 2016-09-21 (-1.57), 2017-01-09 (+0.42): Massive and IBKR smart_trades start 2017-04-28; the 2016 to
  2017-04 Alpaca bars (4.9 to 45.6) and the IBKR venue series are a prior issuer's, so the three steps are inside that history.
- SW 2016-05-16 (-1.86): Alpaca only (255.5 to 39.63 on volume x10); IBKR starts 2024-07-08, Massive holds no SW; no second witness.
- THRM 2012-06-13 (+2.02): Massive 1.54 on 2009-01-09, then 11.62 on 2012-06-13, the first IBKR bar; the 2006 to 2009 bars are an
  earlier issuer's.
- HLT 2016-12-13 (-0.70): Alpaca 54.13 against Massive 26.38 (ratio 2.052, the 1-for-3 reverse split times the spin-off value),
  already listed above; resolves with the Massive-route reverse split row in 629.

## Identity witnesses from the 629 worker pass (2026-11-17; Massive `pit_snapshots`, read-only)

- FAF: CIK 0000855182 (First American Corp, CoreLogic after 2010-06-01) at month-ends to 2010-05-31, CIK 0001472787 (First American
  Financial) from 2010-06-30; canonical's pre-2010-06-02 Massive bars belong to the first.
- SSB: the ticker is a Citigroup Global Markets structured note (STREET.COM SECTOR 06, delisted 2006-05-31) in the snapshots of
  2003-12-31 to 2010; South State Corp (CIK 0000764038) appears from 2020. Canonical holds 801 Massive 1d bars 2003-09-11 to
  2006-12-29 under SSB that are not SouthState (IBKR holds 30 throughout since 1999).
- THRM: Thermage, Inc. (delisted 2009-01-12) to 2011-12-30, Gentherm Inc (CIK 0000903129, formerly Amerigon, ARGN) from
  2012-12-31 and from the break date 2012-06-13. Canonical holds Thermage bars 2006-11-10 to 2009-01-09, then nothing until 2012-06-13.

## Rulings for the 11 strict A3 sweep breaks (2026-11-17, read-only measurement)

Method: per-vendor raw closes and volumes (Alpaca, IBKR, Massive), Massive `pit_snapshots` names and CIKs, Massive `events`
ticker_change, and filings or releases. The 9 dispositions (with a `class` column) are in `config/corporate_actions/sweep_dispositions.csv` (applied 2026-11-17; the live
file gained the `class` column, existing lines blank = real_move); the SNEX row file
`config/corporate_actions/split_rescale_rows_2026_11_17_624_prepared.csv` stays prepared, not applied (see SNEX below).

| Break | Ruling | Basis |
|---|---|---|
| FAF 2010-06-02 | identity (reused ticker, spin-off child) | parent CIK 0000855182 bars to 2010-06-01; FAF is CIK 0001472787 from 2010-06-02 |
| SN 2018-12-06, 2023-07-31 | identity (reused ticker) | Sanchez Energy 0001528837 vs SharkNinja 0001957132; both steps vanish at the cut 2023-07-31 |
| THRM 2012-06-13 | identity (reused ticker) | Thermage bars 2006-11 to 2009-01; Gentherm 0000903129 from 2012-06-13 |
| SW 2016-05-16 | identity (no existence before 2024-07-08) | Smurfit Westrock plc 0002005951 listed 2024-07-08; Alpaca's earlier SW bars are other issuers (a 255 series, then a WestRock-like series; WRK holds no bars here, so not provable) |
| SSB 2004-03-09 | identity for 2003-09-11 to 2004-03-08 only; open question 2 | note bars at 8.4 (volume 300 to 2100); from 2004-03-09 Massive equals IBKR, the South State series |
| SVRA 2016-02-10, 2016-09-21, 2017-01-09 | real moves, not identity | same CIK 0001160308 (Mast renamed Savara, 1-for-70, MSTX to SVRA 2017-04-28); 2016-09-21 is the EPIC trial failure, 2017-01-09 the merger announcement; 2016-02-10 has no catalyst found; Alpaca and IBKR venue_arca agree on all three |
| SNEX 2020-07-06 | not identity; vendor level error, row prepared | same CIK 0000913760; Alpaca is 0.6667 of IBKR on 1,987 sessions before 2023-11-24, equal after; Massive and IBKR agree with the calendar; Alpaca holds one extra 3-for-2 |
| RTX 2020-04-03 | not identity; open question 1 | same CIK 0000101829 (UTX renamed, ticker change 2020-04-03); Alpaca is 3.391 x IBKR on 1,070 sessions (3.3906 to 3.4027) |

Open questions (lead or owner):

1. RTX: no row is prepared. The constant 3.391 is not the reverse split (1.589) times anything an event explains here, UTX holds
   no raw bars, and Massive starts 2020-04-03, so no second witness exists for Alpaca's 2016 to 2020-04-02 level once IBKR is
   deleted at Part F. A rescale by the measured ratio would also absorb the Carrier and Otis distribution, which the
   spin-off rule says stays a real move. Recommendation: before Part F, fetch the as-traded UTX closes (a filing or exchange
   source), decide whether Alpaca's pre-2020-04-03 bars are usable; if not, exclude them through the identity map's span for
   RTX (start 2020-04-03) and record the loss. Then the distribution disposition prepared in 629 applies.
2. SSB: the pit map lists the structured note as the SSB holder to 2014-05-30 and South State from 2014-06-30, which contradicts
   ten years of matching Massive and IBKR South State prices (24.90 in 2009, 71.81 in 2016). If the map owns the cut literally,
   it would exclude valid history. Recommendation: the span source is the bar evidence, cut 2004-03-09, and the map records a
   known pit gap for SSB. Also the pit lists CIK 0000935113 for AMERIGON in three 2012 snapshots against Gentherm 0000903129
   (THRM); the identity key needs the CIK of the entity, not the name.

Gate finding: `sweep_dispositions.csv` had no identity class: any line with a reason and evidence ruled its break, so an identity
line would silence the sweep while the cross-issuer series stays in canonical (the failure this todo exists to prevent). Built
2026-11-17: an optional `class` column on the sweep dispositions (`real_move` default, a blank or absent cell too; `identity`),
read by `sweep_dispositions` through the same validation as `operator_list`. `GATE_COUNTS` gains `identity_dispositions` and
`unused_identity_dispositions`. An identity line rules only an undecided (`reported`) break; a witness-confirmed rescale or a
one-bar reversal on its day stays unresolved. An identity line whose break is gone fails `--strict` at once (remove the line); the
live file holds none. Tests cover an unknown class raising, the verdict restriction, the counts and the strict exit 3. 
Result 2026-11-17 (strict sweep after the 9 lines): 3 undecided of 609 breaks, 6 identity dispositions counted. Still listed:
RTX 2020-04-03 (open, untouched), SNEX 2020-07-06 and SW 2016-05-16. SW is an `unrecorded_split` verdict, so its identity line
does not rule it (an identity line rules only `reported`); the line stays in the file as the evidence record and the break stays
listed until the identity map cuts at 2024-07-08.

SNEX: canonical now reads Alpaca to 2020-07-02 (7.326, 2/3 of IBKR 11.7) then Massive adjusted from 2020-07-06 (11.698); across
2023-11-24 canonical is continuous (Massive adjusted 18.566 to 18.287), so the existing massive_reference 1.5 row is correct for
the Massive span and the only defect is Alpaca's pre-2020-07-06 level, one extra 3-for-2. The prepared route row (factor
0.6667, unadjusted_routes alpaca/sip_rth, effective 2023-11-24) is the right record (it is how a wrongly adjusted route is
recorded, `detail.unadjusted_routes`, as for CLBK) but `--apply-rows --commit` dry-runs "would write 0 of 1": `_apply_decided`
refuses any existing row within SAME_EVENT_DAYS, and the 1.5 market row is one. An identity or real_move disposition would be
dishonest (a vendor level error). Proposal (code, not made here): in `_apply_decided`, a row that names `unadjusted_routes` and
is a non-market operator row is blocked only by an existing row that names the same route, not by an unrelated market row; or
the operator rows path passes `market_splits_only` inverted. Needs review, tests, then apply and reselect SNEX only.

## Result 2026-11-17 (A3 sweep residue: SNEX done, RTX and SW listed)

SNEX: `_apply_decided` takes `route_scoped` for `--apply-rows` (commit 2c9eb5ca8): an operator route row is blocked only by an
existing row naming one of its routes (any state), never by an unrelated market split; a same-route row still blocks, tests
cover both. The prepared row was applied (one row), canonical SNEX 1d reselected, 5m reselected, grid rerun. Canonical is now
continuous across 2020-07-06 (10.989 to 11.698) and 2023-11-24 (17.68 to 18.57 to 18.29). Strict sweep after: 2 unresolved of
608 (RTX 2020-04-03, SW 2016-05-16); the SNEX break is gone.

RTX 2020-04-03, Alpaca level explained: the Massive flat files (`data/massive/files/day_aggs_v1`, not touched by Part F)
hold UTX as-traded daily bars under ticker UTX (2019-12-31 close 149.76, 2020-04-02 close 86.01). Alpaca's RTX close is
exactly 2.000 x the UTX as-traded close on all 1,070 sessions 2016-01-04 to 2020-04-02 (min 2.0000, max 2.0061, median 2.0000).
So the 3.391 against IBKR smart_trades is Alpaca's 2.0 x the as-traded level against IBKR's adjusted level (as-traded / 1.6955);
no corporate event explains a factor 2.0, so it is an Alpaca vendor level error, and the as-traded witness survives Part F in
the flat files (UTX is not in ohlcv_raw). The IBKR export of todo 632 covers only rows absent from canonical, so it is not the
witness. Candidate record, not applied: an Alpaca-route rescale x0.5 effective 2020-04-03 plus the Carrier and Otis
distribution disposition in 629. The owner or lead rules; the break is still listed.

SW 2016-05-16: verdict `unrecorded_split`, so an identity line cannot rule it and the identity rule is not weakened. The
ticker did not exist before 2024-07-08 (CIK 0002005951), so the honest record is an exclusion of Alpaca's SW bars before
2024-07-08 by the pit map span (this todo's mechanism, after Part F); the break stays listed against this ticket until then.

## Result 2026-11-17 (RTX applied; SW is the only sweep residue)

Independent recompute (flat files `day_aggs_v1` UTX, `ohlcv_raw` read-only): Alpaca's RTX close is 2.0000 x the as-traded UTX
close on 1,070 of 1,070 sessions 2016-01-04 to 2020-04-02 (max 2.0061); against ibkr/smart_trades 3.3906 to 3.4027, and UTX
against IBKR 1.6953 to 1.6962 (IBKR is adjusted). From 2020-04-03 Alpaca, IBKR and Massive agree (49.93). So Alpaca's span to
2020-04-02 is 2x too high and nothing after it. Row `split_rescale_rows_2026_11_17_624_rtx.csv` (factor 2, route
`alpaca/sip_rth`, effective 2020-04-02, the last bad session) dry-ran "would write 1 of 1", was applied (one row), and RTX 1d,
5m and grid were reselected. Canonical 1d is now 86.01 (2020-04-02, the as-traded UTX level) then 49.93, the Carrier and Otis
distribution; its disposition (real_move class, 8-K evidence, when-issued arithmetic 86.01 - 32.06 = 53.95 against 49.93) is in
`sweep_dispositions.csv`. Strict sweep after: 1 unresolved of 608 (SW 2016-05-16). The route guard now reads routes through
`split_row_routes` (one definition, commit fc651170c).

## SLM identity contradiction (2026-11-17, parked until the pit map owns identity)

The installed map keeps an open span for SLM from 2003-09-10, while its gap row `ticker_claimed_by_other_security`
says another security held the ticker 2005-07-11 to 2011-12-16 (security id b0b4501b). The two cannot both be right, and
the policy plan clipped the whole range to Alpaca-only (per-symbol 1d and 5m rows over 2016-01-04 to 2026-11-16), so a
Massive row of the open span in that window would have no canonical winner. Lead ruling 2026-11-17 (indicagent-75): leave
the rows alone, one low-value name; revisit with the pit map's identity for SLM. Canonical today: Massive to 2015-12-31,
then Alpaca. The same class check ran over all 268 per-symbol policy names; only ARES (also overlapping; its Alpaca row is
re-windowed to 2018-11-26 after the s3 install) and SLM have a map span inside their Alpaca-only window.

## HZN reused ticker (2026-11-24, indicagent-fb, found with the BKH data gate refusal)

Black Hills Corp merged with NorthWestern and was renamed Bright Horizon Energy (NYSE: HZN); the merger closed
2026-11-16. The BKH ticker's last bar is 2026-11-13 on both vendors, and Alpaca answers `no_data` for BKH from 2026-11-16.
`instruments` already holds an `HZN` row (inactive, `compute_eligible` false, last bar 2023-02-07, an older unrelated issuer,
proven start 2015). The new HZN listing (bars from 2026-11-16) is a reused-ticker case of the SN class: the pit
ticker map must own which issuer each HZN bar belongs to before HZN is onboarded. Per ledger 2026-11-24h the new ticker's
series is a separate instrument and is not claimed as BKH's continuation (BKH has a `listing_end`, migration 616). Onboard HZN through `docs/foundation/instrument-onboarding-sop.md`
after the pilot; it is not needed for the BKH gate fix.

BIPC (Brookfield Infrastructure Corp) merges into the new BIP Inc. (one-for-one into Class A shares; BIPC delisted from NYSE and TSX; completion Q4 2026). BIPC has a `listing_end` (migration 619, last session 2026-11-20, `merged`). The BIP Inc. listing is a separate instrument, not BIPC's continuation, and `instruments` already holds inactive `BIP` rows (an older issuer): when the new ticker has bars, onboard it through `docs/foundation/instrument-onboarding-sop.md` and let the pit ticker map own which issuer each bar belongs to.
