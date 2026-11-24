---
status: completed
priority: P0
filed: 2026-11-19
source: lane 2 of the 609 chain (1d canonical for the all-ticker names), lead ruling
owner: lead
---

# Record splits for the stage 2 names before the 584 pin

## What

The all-ticker 1d load (s4) wrote raw only; canonical 1d for the 33,850 inactive instruments comes from `services.bar_derivation --stage daily --symbols ...` (the active-only daily timer never visits them). `corporate_action_current` holds no row for any inactive instrument, so their canonical closes are as traded: split jumps stay in the series and dividends are unknown (never zero). Membership needs only dates, close and volume, and as-traded close times volume is the point-in-time dollar volume, so it is not affected. Any return, residual or feature on these names is wrong until their splits are recorded, and the corpus rerun computes over every name ever in `universe_membership`.

## Done when

`ops_split_detect` (and the Massive and Yahoo witnesses of the A3 sweep) run over the stage 2 names, the confirmed splits are recorded through the split-row path with review, canonical 1d is re-derived for the affected names, and the sweep `--strict` gate covers them. The 584 pin does not move until then (add to the pin prerequisites in `scripts/ops/bars/run_609.sh` s8).

## Not blocking

The membership build (s5) and its counts.

## Status 2026-11-20 (lead lane e2)

Recorded: 3,026 Massive reference rows with a tape witness (2,357 level-step tranche, 669 adjacent-day tranche; audit e059ee9b7 and 0ace5aa04, plan `docs/plans/archive/2026-11-19-stage2-split-rows-plan.md`), canonical 1d re-derived for 1,758 + 534 names (all derived, exit 0). 114 rows that fail the adjacent-day check stay unrecorded (`logs/split_audit_646/2026-11-10/held_fail_adjacent_114.csv`); 140 reverse splits above the old numerator cap are recorded by e8 under cap 1000 (independent review 125 ok, 15 weak, 0 defect).

Evidence (all under `logs/split_audit_646/2026-11-10/`): independent 100-row stratified review `row_review_100.csv` and `row_review_100_summary.md` (99 correct, 1 wrong ratio: CURE~01R07BN0 recorded 5.0, true 4.0); Yahoo witness over all 3,026 rows `yahoo_witness_3026.csv` and `_summary.md` (1,978 confirmed, 7 mismatches, 1,041 unverified, never counted as confirmed). Corrections: five Direxion rows (CURE~01R07BN0, INDL, RETL, SPUU, MIDU, 2015-05-19, 5.0 to 4.0) and BVN (2003-11-17 to 2003-11-12) by void plus operator row; QH 2022-08-11 stays as recorded (tape x10.5 against Yahoo 1:100, disputed). Superseded ids and replacements go in `corrections_batch.csv`.

Still open before the pin: the corrections batch, the one combined derivation for the corrected and cap 1000 names, the `--strict` sweep over members, the 647 member-history audit.

## Gate scope ruling 2026-11-20 (lead 7c, owner veto reserved)

The strict sweep over members is gated on the breaks that have a Yahoo witness. The 3,551 members' breaks with no Yahoo history (1,516 names, mostly dead names) are disclosed as unwitnessed, never counted as confirmed. A second witness counts only as tape plus a vendor agreeing. The five date corrections Yahoo cannot judge (ACGN, ETS, ICA, REV, VIP) stay refused and open; the witness rule is not loosened. Detail and class counts: todo 629.

## Closure 2026-11-24 (todo consolidation pass)

Done: the corrections batch (4140d1557), the lone-bar fixes and member audit with 0 findings (6119545af), 629 closed by disclosure and readiness row 10 met (0224036b6), and the pin and data gate passed (8ce1f033c). 629 and 647 are in `completed/`.
