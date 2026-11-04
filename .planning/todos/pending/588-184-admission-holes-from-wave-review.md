---
status: pending
priority: P0
filed: 2026-11-04
source: independent review of the phase-184 wiring wave (9f280d0aa..e1cca6456), lead rulings by indicagent-16
---

# Phase 184 admission holes: refuse first, then earn admission back with battery cells

## What

The wave review found that the runner admits runs no passing battery cell tested. Everything
else it checked (lookahead, no_fill, prefix rows, hashes, lineage) was clean. A counted test
admitted outside its certificate is a silent wrong answer, so these land before the first
counted test that uses an input member.

## Part A: code, one landing (research code: repro_frozen bit-identical, full gates)

1. **B1, the static gate comes from failed cells.** `null_battery_persistent.py:294-304`
   (`static_sizes.gate_from_cells`) takes the max over all gating cells, pass or fail. The only
   cells with static means failed. Build the gate per certificate from that certificate's passing
   cells only. Until part B adds static-stress cells, every passing certificate has a static gate
   of 0, so a real panel with measurable static means is refused (the honest state).
2. **B2, admission ignores the member function.** `runner.py:422-460`: an input member is
   admitted only when its signal is `families.features.centred`, the one function the battery
   certified. Any other signal is refused at spec load, naming the rule.
3. **M1, smoothing as a bypass of the persistence failure.** Drop the `feature, smoothing 5,
   1d->1d` certificate from `PASSING_CERTIFICATES` until part B tests it at tau 200.
4. **(e)** Drop the `rk_vwap_dev` certificates until S0 supplies `volume_basis` and the battery
   certifies on a mixed volume basis.
5. **m3** Refuse a book with more than one input member, or one that mixes input and
   residual-return members, until part B certifies multi-member books.
6. **m1** Resolve `source_configs` and `_check_member_memory` before `start_runs`, so a
   refusal never burns a spec hash as a failed run.
7. **m2** Refuse when `unmatched_rows > 0` inside the scored span (`snapshot.py:579-596`).
8. **Slot history (item 3, MINOR):** allow `slot_history_sessions = 0` for input members, which
   matches the certified condition.

The `test_passing_certificates_match_report` contract changes with 1, 3 and 4. The report's
table stays the evidence, and the dropped certificates are listed as withheld with the reason.

## Part B: battery extension (a counted battery run; never reclassify a failing cell)

For each certificate still passing after part A: a static-mean stress cell and a time-of-day
stress cell (sizes spanning the real-data range measured on the pilot names), a tau-200 cell,
and one two-member book cell. A certificate regains static admission only up to the largest
static size its own passing cells held. Smoothing 5 returns only if it passes at tau 200.

## Part C: real-data dry build

184-12's dry S0 build after 186-27 is the gate for real-mode `build_panel` (review item f):
row loss, the chunk grid and feature timestamp matching on live data.

## Done when

Part A has landed and its tests pin each refusal, part B's report is committed, and
`PASSING_CERTIFICATES` matches it. 184-12 has run clean before any counted test with an input
member.

## Part A landed (2026-11-04)

All eight items are in, each pinned by a refusal test. `PASSING_CERTIFICATES` is now
`feature 1h->1d`, `feature 15m->1d` and `rk_high_dist 126 1d->1d`; the smoothing-5 and both
`rk_vwap_dev` certificates are in `WITHHELD_CERTIFICATES` with reasons, and 184-05-BATTERY.md has a
"Withheld" section (the measured table is untouched). The static gate is per certificate from that
certificate's own cells (`null_battery_persistent.static_gate(certificates)`), so every passing
certificate gates at 0 until part B. Item 8 relaxes `slot_history_sessions` to 0 for input members
only. Part B and C remain.

## Part B landed (2026-11-04)

Thirteen gating cells ran at battery module commit eb6651a9f (tag `battery/588-b`, 1,000 sims, 4,000
sessions, 60 names); the table and rule are in 184-05-BATTERY.md ("Part B extension"). Twelve hold
size at 0.05 and 0.01. `PASSING_CERTIFICATES` stays feature 1h to 1d, feature 15m to 1d and
rk_high_dist 126 1d to 1d, and each now gates at the largest stress its own passing cells held:
static 0.038 (twice the measured size) for all three, time-of-day 0.0192 for the two feature routes
and 0 for rk_high_dist (no applicable cell). The two-member book feature 1h with feature 15m
(equal weight) passed both book cells and is the one certified composition (`CERTIFIED_BOOKS`);
any other count or combination of input members stays refused, and a book of the two gates at 0
(its cells carry no stress). Smoothing 5 does not return: `f1d_s5_tau200` fails in the book arm
(70 at 0.05, 23 at 0.01), so it is a failing route (todo 586). The `rk_vwap_dev` certificates stay
withheld. The stress cells cannot move the statistic (dollar-neutral weights and the lagged cell
mean remove static means and a common mean), so the ceilings record sizes tested, not a sharper
claim. Part C remains.
