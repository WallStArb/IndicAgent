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
