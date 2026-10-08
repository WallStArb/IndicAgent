---
phase: 185-daily-data-foundation
plan: 47
subsystem: data-integrity
tags: [tradier-retirement, ibkr-1d-primary, bar_source_policy, d2-v2, d7, migration-456, gap_closure]
requires: [185-46, 185-43, 185-45, 189-10 Task 1b]
provides:
  - "1d default policy: Tradier closed at D = 2026-10-07, IBKR SMART TRADES (no fallback) from D; migration 456 live 2026-10-08 16:03:53 UTC"
  - "class C hold rows for MOD and QRVO (primary tradier, fallback ibkr, open-ended)"
  - "1,501 names re-derived: 1,424 bars of 2026-10-07 relabelled ibkr_fallback to ibkr_named, no value changed"
  - "swap_1d_primary_measure.py: check_dryrun, compare_verdicts, --export-verdicts, --check-dryrun, --compare-verdicts"
  - "docs/research/1d-primary-swap-evidence.md: Apply results (C1 to C8 measured)"
  - "todo 515 (P0): CTVA spin-off recorded as a split, ETHA reverse split recorded twice at wrong dates"
affects: [185-48, 189-10 Task 2, 189-10 Task 3, 186-26, research ledger]
key-files:
  created:
    - production/migrations/456_swap_1d_primary_to_ibkr.sql
    - tests/unit/test_swap_1d_primary_migration_contract.py
    - .planning/todos/pending/515-corporate-action-spin-off-and-duplicate-split-rows-ctva-etha.md
  modified:
    - scripts/research/swap_1d_primary_measure.py
    - tests/unit/scripts/test_swap_1d_primary_measure.py
    - docs/research/1d-primary-swap-evidence.md
    - .planning/todos/PRIORITIES.md
decisions:
  - "C1 is judged per name against its effective policy from D: a switching name's SMART dates on or after D must appear as new or as source-label-only changes, with no value change; every other name must equal its baseline"
  - "CTVA stays held: the company record shows a spin-off (one VYLR per CTVA), the two vendors' factors differ (5.5714 vs 6.665) and no CTVA WI price exists to decide continuity; single named exception to C3 and C8"
  - "ETHA's duplicate corporate actions are filed (todo 515), not edited: no sanctioned tool corrects or retires a row"
  - "QRVO's literal precondition 2 failure (no ibkr 1d request row, because IBKR refused to qualify the contract) is treated as satisfied in substance; QRVO is class C no_ibkr_yet with a hold row"
requirements: [D-01, D-06, D-07, D-21, D-26]
metrics:
  completed: 2026-10-08
  duration: about 75 minutes
  tasks: 2
---

# Phase 185 Plan 47: 1d primary swap from Tradier to IBKR Summary

The 1d default is IBKR SMART TRADES from 2026-10-07 under a dated policy row. History before D is
unchanged, and the pre-registered criteria hold on every name except CTVA, which stays held as the
single named exception.

## Dates for the research ledger

| What | Date |
|---|---|
| D (basis change date; first NYSE session after the last Tradier bar, 2026-10-06) | 2026-10-07 |
| Swap applied (migration 456 live; daily stage apply 16:06:11 to 16:09:23 UTC) | 2026-10-08 16:03:53 UTC |
| freshness_1d verdict after the swap (D7 by hand) | 2026-10-08 16:15 UTC: 2 failing, CTVA (5 sessions) and QRVO (3 sessions) |

## Commits

| Step | Commit | What |
|---|---|---|
| Task 2 RED | 3be09a4fa | failing tests for check_dryrun, compare_verdicts, read_verdicts |
| Task 2 GREEN | f7993a44b | the checkers and the three read-only modes |
| Task 1 RED | b2d76fbed | migration 456 contract test |
| Task 1 GREEN | 8ecc73d3b | migration 456, applied live in the same breath |
| Task 2 doc | 8ed27ff7e | Apply results, todo 515 and its PRIORITIES row |

## Classes and rows

The `--classify` rerun after Task 1b gives A 1,526 (27 outside compute_1d), B 0, C 3:
- EU: few_common. It already holds an open IBKR row, so it is decided and gets no row.
- MOD: few_common, 27 sessions, median 0.9207. Hold row written.
- QRVO: no_ibkr_yet. Hold row written.

The 8 former class B names are class A now, because Task 1b's refresh tail agrees on the last 20 sessions. All 8 keep their 185-38 IBKR rows.

| class | rows written |
|---|---|
| A | 0 |
| B | 0 |
| C | 2 (MOD, QRVO) |

Admission sweep dry run: write 76 (72 already hold a row). ELE, IESC, MSM and TIGO are class A with no row. They are out of scope under amendment item 4 and listed in the doc.

Volume basis, recent 250 sessions, over 1,528 names: p10 0.409, p50 0.528, p90 0.807. These figures are in the new default's evidence.

## Criteria

| | Result | Numbers |
|---|---|---|
| C1 | pass | 1,426 switching names: 1,424 SMART dates on or after D, 0 new, 1,424 relabelled, 0 value changes, 0 removed; 76 unchanged-policy names equal the baseline; 0 violations |
| C2 | pass | no class B name, 0 head bars lost |
| C3 | pass but CTVA | policy_conformance, lineage_missing and digest_fresh 0; canonical_recompute 1 (CTVA, 1,853, failing before the swap too) |
| C4 | pass | 0 pass-to-fail over 17,180 verdicts |
| C5 | listed | 0 fail-to-pass |
| C6 | pass | every check's failing count is equal before and after |
| C7 | listed | freshness_1d fails on CTVA (held apply) and QRVO (class C hold, IBKR has no contract definition) |
| C8 | pass but CTVA | final dry run 0/0/0 on 1,501 names; CTVA new 5, changed 1,848 |

C1 note: Task 1b's first fetch and refresh had already made 2026-10-07 canonical as ibkr_fallback bars under the Tradier default. So the swap relabelled 1,424 bars and added none, which is the case orchestrator decision 1 anticipated. The 2 switching names with no SMART date on or after D are PSKY and WBD; both fail contract qualification (fetch record).

## D7 before and after (failing names per check)

| Check | Before (15:56 UTC) | After (16:15 UTC) |
|---|---|---|
| canonical_recompute | 1 (CTVA) | 1 (CTVA) |
| freshness_1d | 2 (CTVA, QRVO) | 2 (CTVA, QRVO) |
| session_coverage | 191 | 191 |
| vendor_basis_run | 35 | 35 |
| unexplained_seam | 6 | 6 |
| grid_parity / slot_coverage (5m) | 131 / 240 | 131 / 240 |
| policy_conformance, lineage_missing, digest_fresh, coverage_cache, refused_head_1d, stray_vendor_rows, report_age | 0 | 0 |

## CTVA and ETHA

CTVA stays held and is filed in todo 515.
- Corteva's release of 2026-09-14 (corteva.com, fetched with curl, cited in the doc and the todo) records a spin-off of Vylor: one share per CTVA share, record date 2026-09-24, distribution 2026-10-01.
- IBKR's refetch scales prices by 39/7 and volume up by the same factor. Tradier's price factor is 6.665.
- Neither vendor is shown continuous without the CTVA WI close, which D1 does not hold. Volume scaling is wrong for a spin-off under any factor.
- No row was written and d2-v2 was not applied for CTVA.

ETHA has two reverse_split rows: 2026-10-02 (tradier_refetch) and 2026-09-30 (nightly_overlap). Both dates are wrong: Tradier's raw closes show the split took effect on 2026-10-05 or 10-06. The canonical values are right today. No sanctioned correction tool exists, so I edited nothing and filed it in todo 515. ETHA switched at D as class A.

## Verification

- Task 1 verify: the three contract tests pass, and exactly one open 1d default (primary ibkr, no fallback) exists.
- Task 2 verify:
  - `test_swap_1d_primary_measure.py` passes and `--check-dryrun` exits 0.
  - `--compare-verdicts` exits 1, and its only failure is canonical_recompute on CTVA.
  - The final dry-run awk check fails only on CTVA.
  - Both failures are the named exception allowed by orchestrator decision 3, not a regression.
- `ohlcv_load` holds 1,501 applied rows from the apply, with none refused or failed.
- The fetcher timer is disabled and inactive.
- Full `.venv/bin/pytest tests/unit/ -q` exits 0 with no failures. It ran after the last code change.
- repro_frozen does not apply: nothing under research/ or statistics/ changed.
- Pre-commit passed 9/9 on every commit.
- No IBKR or Tradier request was made, and no fetcher was started.

## Deviations from plan

1. [Precondition, judged] Precondition 2 fails literally on QRVO. It has no ibkr 1d `ohlcv_request` row because IBKR refused contract qualification (error 200) before any request existed. The fetch reached it, so the precondition's purpose holds, and QRVO is class C with a hold row. Report this if the orchestrator reads the precondition strictly.
2. [Rule 3] The plan's D7 command (`.venv/bin/python services/bar_reconciliation_audit.py`) fails with `No module named 'scripts'`. I ran it with `PYTHONPATH` set, as the systemd unit does.
3. [Order] Task 2's checkers were built first, because Task 1's baseline needs `--export-verdicts`.
4. [C1 reading] `check_dryrun` counts new plus source-label-only changes against the SMART dates on or after D, and requires that admitted fallback dates fall by the relabelled count. This follows amendment 2 and orchestrator decision 1. The pre-registered rule text is unchanged.
5. [CTVA] The apply ran over 1,501 names (`--symbols`, CTVA excluded), not all names, so the held CTVA rewrite was not applied by accident.
6. [Rehearsal] Migration 456 was rehearsed on `indicagent_test`, which now carries the IBKR default too.
7. [Scope] STATE.md, ROADMAP.md and REQUIREMENTS.md were not written (executor brief). The orchestrator records the plan.

## For 185-48 and 189-10 Task 2

- 185-48: the Tradier default is closed, and only MOD and QRVO hold Tradier-primary rows. The loader can be deleted. The volume_basis_break research follow-up reads D = 2026-10-07 and the ratios from migration 456's evidence. The swap script's new modes can be reviewed for deletion with the rest of it.
- 189-10 Task 2 and Task 3: the nightly wiring is verified read-only.
  - Run-end order: escalate, then daily over the touched 1d names, then grid.
  - Split detection is SMART only.
  - IBKR D1 elision is pinned by tests.
  - The D7 timer is enabled and the fetcher timer is disabled.
- 189-10 Task 3: before the fetcher timer launch, todo 515 should land. The nightly overlap judge records spin-offs and repeated events as splits, and CTVA needs a decision before its next apply. Every run's daily stage over touched names would apply CTVA's held rewrite as soon as CTVA is touched.
- Open owner question: the 27 names outside compute_1d are class A and stay observation-only. Their 82,658 canonical bars were not written.
- Out of scope and untouched: todo 508, 512, 514; FUBO, LION and RCAT stay held.

## Known stubs

None.

## Threat flags

None beyond the register.
- T-185-47-01: no B or C splice without a row.
- T-185-47-02: C1 gated the apply, and no class B snapshot was needed.
- T-185-47-03: the rules section is unedited.
- T-185-47-04: no process ran, and both timers are disabled.
- T-185-47-05: the ratio is in the row's evidence.

The CTVA research made outbound read-only HTTP requests to corteva.com only. No project data or contact details were sent.

## Self-Check: PASSED

Files: migration 456, its contract test, todo 515 and the 185-47 logs (classes, three dry runs, two verdict exports) exist. Commits 3be09a4fa, f7993a44b, b2d76fbed, 8ecc73d3b, 8ed27ff7e are in history. Live: one open 1d default (ibkr, no fallback, from 2026-10-07), hold rows for MOD and QRVO.
