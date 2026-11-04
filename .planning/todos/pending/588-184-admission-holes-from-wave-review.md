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
