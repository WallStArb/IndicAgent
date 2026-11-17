---
status: pending
priority: P1
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
