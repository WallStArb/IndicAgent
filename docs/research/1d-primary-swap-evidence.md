# 1d primary swap: Tradier to IBKR SMART, evidence

**Author:** Claude (Opus 5.5), 2026-10-07, at Brandon's request (plan 185-46 Task 2)
**Status:** in progress (rules pre-registered; results follow in a second commit)
**Informed by:** docs/plans/2026-10-06-data-layer-integrity-design.md; summaries of plans 185-33, 185-36,
185-38 and 185-41; owner decision 2026-10-07 (Tradier will not be funded, 1d primary moves to IBKR; D-01)

Plan 185-46 measures and prepares; 185-47 applies the swap; 185-48 retires the Tradier loader. This
document fixes the rules that judge 185-47 before any number below exists, then records the
measurements (request rate, nightly cost, volume basis, per-name classes) that 185-47 and 189-10 read.
The Tradier daily timer was disabled on 2026-10-07; the freeze point is the last Tradier bar date,
2026-10-06, on all 1,529 active names (last loaded row 2026-10-07 11:52:38 UTC).

## Pre-registered rules

Committed before the measurement script ran against the data. Thresholds named here are APR keys read
at run time; no number in this section is copied into code.

Standing of the Tradier history (owner answer 2026-10-07). Tradier bars dated before D are canonical
history under the dated policy rows and keep their full standing in d2-v2, the verdict gate and the
rebuild. What stops is new Tradier fetching (the account is unfunded), not the use of what was
fetched. The class tests in R2 decide only who owns bars from D on and whether a Tradier head is kept;
they never decide whether pre-D Tradier bars are trusted.

R1, shape F (forward from D). The open 1d default row of bar_source_policy (primary tradier, fallback
ibkr) is closed at D and a new default (primary ibkr, no fallback) opens at D. D is the first NYSE
session after the maximum Tradier observation date (route TRADIER, timeframe 1d) at the time 185-47
runs. Every bar dated before D stays as it is. Stop condition: 185-47 does not run if any Tradier
observation is dated on or after D.

R2, per-name classes. Over the common sessions of a name (date, Tradier close, IBKR SMART TRADES
close), current scale as d2-v2 chooses it (`common_session_closes`), with window_sessions,
tolerance_bp, min_overlap and min_agree_share read from APR
(threshold.bar_integrity.fallback_basis_window_sessions, fallback_basis_tolerance_bp,
tradier_admission_min_overlap_sessions, tradier_admission_min_agree_share):
- Class A: at least one common session exists and the median IBKR/Tradier close ratio over the last
  min(window_sessions, n_common) common sessions is within tolerance_bp of 1.
- Class B: that median is outside tolerance and the 185-38 admission test (`tradier_admission`) over
  the same pairs reports recent_disagrees with at least min_overlap common sessions.
- Class C: otherwise (no common session, or outside tolerance with fewer than min_overlap sessions).
  A name with no SMART TRADES observation yet is class C with reason no_ibkr_yet; 185-47 reruns the
  classification after the one-time IBKR fetch (189-10 Task 1b).

Head candidate. The Tradier head is the run of Tradier dates before IBKR's first SMART TRADES bar. It
is kept only when the median IBKR/Tradier close ratio over the first window_sessions common sessions
from IBKR's first bar is within tolerance_bp of 1; with no common session it is not kept.

R3, what each class gets in 185-47.
- A: no symbol row; the new default applies from D.
- B: a whole-history primary-ibkr symbol row (the existing admission sweep or `--add`). When the head
  candidate keeps the Tradier head, two rows instead: primary tradier before IBKR's first bar, primary
  ibkr from it, so the head is not lost.
- C: a hold row (primary tradier, fallback ibkr, from the name's first observation, open-ended), so no
  IBKR bar is spliced where no seam evidence exists; the name is listed as frozen.

R4, nightly cost bound. The update lane (owner answer 2026-10-07: one request per name per timeframe
for 1d and 5m, short span since the last stored bar, widened by the revision-window overlap required by
the design review) for every active name costs at most 120 minutes a night (half of
infra.backfill.run_budget_minutes). The gap-fill lane has its own budget row in the results and is not
bounded by R4. Above the bound nothing changes here: the figure is carried into 189-10 Task 2's
extrapolation and a todo is filed.

R5, volume basis. The IBKR SMART over Tradier volume ratio is recorded, never rescaled or spliced, and
has no pass line.

R6, apply criteria for 185-47.
- C1: for every class A and C name the dry run shows changed 0 and removed 0, and new bars equal to the
  count of distinct SMART TRADES dates on or after D for class A and 0 for class C.
- C2: class B changes and removals are listed per name with the Tradier head bars lost.
- C3: the four zero-tolerance checks (policy_conformance, lineage_missing, canonical_recompute,
  digest_fresh) have 0 failing names after the apply.
- C4: no (symbol, check) pair goes from pass to fail.
- C5: fail-to-pass transitions are listed.
- C6: the failing-name count of every check is at most its count before.
- C7: freshness_1d failures after the apply are listed with a reason per name (class C, IBKR never
  answered, fetch gap).
- C8: one dry run after the apply shows 0 new, 0 changed, 0 removed.

## Deferred

A replacement or second 1d vendor is Stage V (D-01) and is not added here.
