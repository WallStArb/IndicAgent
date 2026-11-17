---
status: in_review
priority: P1
filed: 2026-11-17
source: step 7 D4 disposition; lead ruling 2026-11-17 (indicagent-77): the check cannot be satisfied once IBKR raw is gone
---

# Retire or rework alpaca_basis_run now that IBKR is removed

## What

`alpaca_basis_run` (`integrity_checks.alpaca_basis_runs`, required for 1d in `verdict_gate.REQUIRED_CHECKS`)
compares IBKR raw and Alpaca raw 1d closes and explains a run only by a split dated inside the run or on the
first common session after it. IBKR is removed and Part F deletes its raw rows from 2003-09-10, so for 2026
the check has no IBKR input left. It is red for ITA, MTUM and QUAL in the D4 rerun (run 2026-10-07 to
2026-10-30; recorded splits effective 2026-11-03 and 2026-11-04). Those three names are unready on the verdict
gate only through this check until this todo lands. Ruling: no split is dated 2026-11-02 and no
`corporate_action` row changes; the Massive yardstick row (2026-11-04) stands.

## Requirement first (Musk step 1)

Does any vendor-comparison check survive, with Massive the yardstick and Alpaca the continuation? The
comparison that remains meaningful is Massive against Alpaca over the overlap window (nightly capture against
the archive). Decide whether that is needed beyond `split_continuity`, `split_horizon_fresh` and the
unexplained seam check; if those already catch the defect classes `alpaca_basis_run` was written for
(spin-off, split, ticker event since the D-191-Q arbitration), delete the check rather than port it.

## Ruling (2026-11-17, indicagent-55): retire, do not port

`alpaca_basis_run` was written for the D-191-Q arbitration window: IBKR and Alpaca both served 1d, and a
level run between them after 2026-10-06 meant a spin-off, split or ticker event one vendor had adjusted
and the other had not. Canonical 1d is now one vendor per span (Massive to 2026-11-16, Alpaca after, rule
d2-v6), so there is no second live vendor to disagree with. A Massive against Alpaca comparison over the
overlap would only restate what the surviving checks already judge on canonical itself:

- Split or spin-off not applied, or applied twice, at a recorded event: `split_continuity` (todo 587).
- Unrecorded level break: `unexplained_seam` judges returns from `window.judge_from` onward only; the gap before it is todo 622 (unrecorded level breaks), not this check.
- Stale split knowledge: `split_horizon_fresh` (5m) and the split rows `split_continuity` reads (1d).
- Canonical not a pure function of raw: `canonical_recompute` and `digest_fresh`.

Ported check rejected: it needs a second vendor's close on the same session, and after Part F the only
vendor with 2003 to 2026 depth is the one canonical already selects. ITA, MTUM and QUAL were red only
because the check read raw Alpaca on the pre-split scale against IBKR on the new one; with the check gone
their verdict rests on `split_continuity`.

State at the latest audit (2026-11-16 23:17Z): MTUM and QUAL are unready only through `alpaca_basis_run`. ITA is additionally red on `canonical_recompute` (value 1; green in every earlier run through 22:11Z) and `report_age`, pending a clean D7 rerun. Cause, from `integrity_monitor` and `logs/bar_derivation.log`: `bar_derivation` ran 23:01:27Z to 23:47:42Z and rewrote canonical 1d while the 23:17Z audit read it, so the recompute compared stored rows against a moving target; the run's failures are one contiguous alphabetical block (IGF to IWC) and `report_age` went negative (-0.04 h) for the same block. SCCO also fails `alpaca_basis_run` (run 2026-10-07..2026-11-02, ratio 0.9895); the check's retirement clears it. Not a defect in the check; closes after a rerun with no derivation in flight.

Done in the change: `REQUIRED_CHECKS["1d"]`, `CHECKS_1D`, `alpaca_basis_runs`, `find_basis_runs`,
`BasisRun`, `ARBITRATED_THROUGH`, `NameReport1d.alpaca_runs`, the audit's blocking-sample log, the
`vendor_basis` tests, and migration 602 retiring `threshold.bar_integrity.vendor_ratio_run_min_sessions`
and `alpaca_basis_tolerance_bp`. Kept: `BP`, `vendor_basis_closes` (read by the D-191-Q arbitration
script) and the daily rule's `fallback_basis_*` keys.

## Scope

1. Requirement ruling, written here, with the defect classes each surviving check covers.
2. Change `REQUIRED_CHECKS["1d"]` and `integrity_checks.alpaca_basis_runs` (retire, or rebase on Massive
   against Alpaca), plus the tests, the ready predicate SQL and every doc naming the check.
3. A built worker edits in a detached worktree off `origin/main` after Part F; timers and auditors import
   `integrity_checks`, so the landing waits for a quiet window.

## Gates

D7 rerun with ITA, MTUM and QUAL ready; no other name's verdict changes except through the ruling; the unit
suite exit code; independent review.
