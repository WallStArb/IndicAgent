---
phase: 185-daily-data-foundation
plan: 51
subsystem: data-integrity
tags: [todo-515, corporate_action, split-recognition, bar_hold, held-name, void, ctva, etha, migration-461, gap_closure]
requires: [185-47, 185-50, 189-10 Task 1b]
provides:
  - "recognised_split_ratio: a rescale is a split only at p/q within 0.002 relative, q <= 4, p <= 50 (APR infra.backfill.split_ratio_*)"
  - "bar_hold / bar_hold_current: the one definition of a held name; one writer, services/bar_hold.py"
  - "corporate_action void rows and inferred_by operator; current view hides void and superseded rows"
  - "ops_split_detect.py --supersede, --void, --hold-rescale, --release-hold (dry run unless --apply)"
  - "daily stage skips held names; D7 held_names check, held_1d per name, hold cause beside freshness_1d"
  - "CTVA held and frozen at its raw 2026-09-30 bar; ETHA one reverse_split row at 2026-10-05"
  - "migration 461 live 2026-10-08 21:45:38 UTC; todo 515 closed; todo 516 filed"
affects: [189-10 Task 3, 186-26, todo 516]
key-files:
  created:
    - services/bar_hold.py
    - production/migrations/461_bar_hold_and_corporate_action_void.sql
    - tests/unit/services/test_bar_hold.py
    - tests/unit/test_bar_hold_migration_contract.py
    - .planning/todos/pending/516-spin-off-action-type-as-a-research-layer-distribution.md
  modified:
    - src/intelligence/bars/corporate_actions.py
    - src/intelligence/bars/integrity_checks.py
    - services/split_detection.py
    - scripts/ops/bars/ops_split_detect.py
    - scripts/infrastructure/backfill/ibkr_history_fetcher.py
    - services/bar_derivation.py
    - services/bar_reconciliation_audit.py
    - tests/unit/test_single_writer_registry.py
    - docs/foundation/glossary.md
    - .planning/todos/PRIORITIES.md
  moved:
    - .planning/todos/pending/515-corporate-action-spin-off-and-duplicate-split-rows-ctva-etha.md -> completed/
decisions:
  - "Split ratio rule seeds: numerator cap 50 (infer_split's snap bound), denominator cap 4 (covers 3:2, 4:3, 5:4), relative tolerance 0.002 (threshold.seam.rel_tol)"
  - "Held is a new append-only table with a current view, not an integrity_monitor fact (no detail column, no release semantics)"
  - "corporate_action gets a void action type instead of an array of superseded ids: the FK on supersedes stays, one current row is reached with one correcting row plus one void row"
  - "ETHA's correcting row uses the table's convention, effective_date = last day on the old scale (2026-10-05); the first post-split session is 2026-10-06"
  - "A newly held name is still re-fetched at full depth by the fetcher (D1 keeps the vendor's restated answer for the decision); the daily stage skips it"
requirements: [D-06, D-07, D-21]
metrics:
  completed: 2026-10-08
  duration: about 60 minutes
  tasks: 5
---

# Phase 185 Plan 51: split recognition, held names, CTVA and ETHA corrected (todo 515) Summary

The overlap judge now records a rescale as a split only when its factor is a small integer ratio.
Any other constant rescale holds the name: it is never written to corporate_action, and no daily
run applies the vendor's rewrite. CTVA is held and frozen at its raw 2026-09-30 bar, and its wrong
split row is voided. ETHA's two wrong rows are replaced by one row at the right date.

## Recognition rule and APR keys (migration 461)

`recognised_split_ratio(factor, rule)` in `src/intelligence/bars/corporate_actions.py` accepts a
factor when factor or 1/factor is within `rel_tol` (relative) of p/q, with q <= the denominator
cap, p <= the numerator cap and p != q. It returns the exact ratio. The judge tests the measured
seam factor, not the snapped one, because 39/7 snaps to itself.

| Key | Seed | Provenance |
|---|---|---|
| infra.backfill.split_ratio_max_numerator | 50 | [initial_estimate], not an ML target |
| infra.backfill.split_ratio_max_denominator | 4 | [initial_estimate], not an ML target |
| infra.backfill.split_ratio_rel_tol | 0.002 | [initial_estimate], not an ML target |

Tests: CTVA 39/7 (and 5.5711, and 7/39) is rejected. 1/3, 3:2, 1:20, 2, 4, 5:4 and 50 are
accepted exactly. 1.0, 1.05, 2.02, 60, 1.73 and 7/5 are rejected. Known limit, pinned by a test:
Tradier's CTVA factor 6.665 is 0.025 % from 20/3 and passes. The rule bounds the false-split
rate; it does not identify spin-offs.

## Held names

- Definition: a row in `bar_hold_current`, which holds bar_hold rows that are not releases and
  that no release names. bar_hold is append-only (UPDATE, DELETE and TRUNCATE raise), restricted
  to timeframe 1d, and its only reason is `unclassified_rescale`. Each hold carries a factor, the
  first and last affected dates, an optional action_id, and its detail (the vendors' ratios, the
  evidence and the rule).
- Single writer: `services/bar_hold.py` (`record_hold`, `release_hold`) under
  bar_derivation_writer, registered in the single-writer guard.
- Callers:
  - `ops_split_detect.act_on_detections`, shared by the fetcher's in-process judge and the by-hand
    `process`;
  - `--hold-rescale` and `--release-hold`.
- Readers:
  - The daily stage reads holds once per run. It skips a held name whether or not the run is
    scoped (outcome `held`, cause in a new `held` report column, zero counts, nothing read or
    written, no failure). This covers the fetcher's run-end `--symbols` apply and any unscoped
    or `--changed-only` apply.
  - The overlap judge: `record_hold` is idempotent per symbol, reason and factor within rel_tol,
    so the same rescale is neither held nor reported twice.
  - D7 has a run-level `held_names` check (a finding per hold, with its cause), an informational
    `held_1d` fact per compute_1d name (not a gate check), and a `held:` line plus a
    `bar_integrity.freshness_1d_held` error naming the cause when a held name fails freshness_1d.
- A new hold is an integrity fact (`bar_split_detection` / `unclassified_rescale`, value = the
  measured factor) and makes the fetcher run partial.

## CTVA (option 3)

- `ops_split_detect.py --hold-rescale 90c2dc47...` ran as a dry run first, then `--apply` at
  2026-10-08 21:59:26 UTC.
- Void row `d3618730` supersedes split row `90c2dc47`; CTVA has no current corporate action.
- Hold `72cc2b5e-8af7-4ade-b3da-0a869dc53b41`: factor 39/7 over 2019-05-24..2026-09-30. Vendor
  ratios against the canonical bars: SMART 5.5711 (1,848 dates), TRADIER 6.6652 (1,843 dates).
  Both match the todo's figures. Neither vendor factor was chosen.
- Daily dry run `--symbols ETHA CTVA`: CTVA outcome held, new 0, changed 0, removed 0. The
  rewrite of 1,848 bars is not applied.
- Unscoped daily dry run over all compute_1d names: 1,501 derived at new 0, changed 0, removed 0,
  plus CTVA held.
- Nightly judge: re-judging the 2026-10-08 fetch run 790b2d1d inside a rolled-back transaction
  gives 12 CTVA seams, all unclassified, factors 5.5685 to 5.5751. It records no corporate action,
  adds no hold and sends no report.

## ETHA

Evidence for the date:
- Nasdaq Equity Corporate Actions Alert ECA2026-713 (fetched with curl): the 1-for-3 reverse split
  became effective Tuesday 2026-10-06.
- The iShares notice says it was effectuated after the close of 2026-10-05.
- D1 agrees. Tradier's raw closes run through 2026-10-02 (fetched 2026-10-03). Its first adjusted
  answer was fetched 2026-10-06 12:38 UTC, before that session opened, and already shows
  2026-10-05 on the new scale. No raw 2026-10-05 observation exists. D1 alone cannot separate
  10-05 from 10-06; the exchange notice does.

Correction:
- `--supersede ed939e61,276f406f --effective-date 2026-10-05 --factor 1/3 --evidence
  31ea6768,3886fb26` ran as a dry run first, then `--apply` at 21:59:25 UTC.
- Operator row `ce003ee6` (reverse_split 1/3, effective 2026-10-05) supersedes the 2026-10-02
  tradier_refetch row `ed939e61`.
- Void row `09287e78` supersedes the 2026-09-30 nightly_overlap row `276f406f`.
- `corporate_action_current` now holds exactly one ETHA row. The 2026-10-02 row has no void of
  its own: the correcting row supersedes it, and the current view hides it.
- Evidence ids: only answers on the new scale (Tradier 31ea6768, IBKR 3886fb26).

Results:
- Daily dry run: changed 0 (555 unchanged).
- A read-only d2-v2 recompute derives no flags. The 549 stored `pre_split_unrefetched` quarantine
  flags (2024-07-23..2026-09-29, all on right bars) came from the 2026-09-30 row, which had marked
  Tradier's adjusted refetch stale.
- Daily apply at 21:59:48 UTC: new 0, changed 0, removed 0; the 549 flags were deleted. ETHA now
  has no 1d flag.

## D7 before and after (by hand, PYTHONPATH as the unit)

Before: 21:45:46 to 21:59 UTC, after migration 461 and before the corrections. After: started
22:02 UTC.

| check (1d failing names) | before | after |
|---|---|---|
| canonical_recompute | 1 (CTVA, 1,853) | 1 (CTVA, frozen by decision) |
| freshness_1d | 4 (CTVA 6 sessions, PSKY, QRVO, WBD) | 4, CTVA line names the hold |
| policy_conformance | 0 | 0 |
| vendor_basis_run | 13 | 13 |
| session_coverage | 263 | 263 |
| unexplained_seam | 6 (AVBP, EWZ, PAGS, PCVX, PTC, XP) | 6 |
| held_names (run-level) | 0 | 1 (CTVA) |
| held_1d (info) | 0 | 1 (CTVA) |

- The per-name diff of the two verdict exports changes only CTVA held_1d.
- canonical_recompute keeps failing on CTVA. The recompute is the pending rewrite, and it clears
  only with todo 516.
- Records in `logs/185-51/` (git-ignored): d7_before.out, d7_after.out, verdicts_before.tsv,
  verdicts_after.tsv, the daily dry run and apply TSVs, the correction plans as JSON, and the
  rejudge outputs.

## Migrations

461: ROLLBACK dry run first, then applied live 2026-10-08 21:45:38 UTC. A second apply was a
no-op (INSERT 0 0 three times).

## Todos

- 515 closed (moved to completed/ with a Closed section); PRIORITIES row updated.
- 516 filed (P2, Data and ingestion row):
  - the spin_off action type, with a d2-v2 rule that keeps the pre-restatement observations, the
    distribution treated as a total-return event like dividends (todo 428), then release of
    CTVA's hold;
  - ELE, IESC, MSM and TIGO (still true on 2026-10-08: no 1d symbol row, all active and
    compute_1d);
  - d2-v2's one-session effective_date offset (found here).
- The link test passes.

## Commits

| Commit | What |
|---|---|
| 04779c1db | RED tests: recognition, judge, bar_hold, ops corrections, daily held skip, D7, migration contract |
| 15df4ec86 | GREEN: rule, bar_hold, act_on_detections and corrections, fetcher wiring, daily skip, D7, glossary, registry |
| b87934760 | migration 461, applied live |
| 49ec2ae6c | fix: a split's evidence names only new-scale requests |
| 113ff0aa5 | RED: a re-judged split already recorded at a later date is the same event |
| 09824e858 | fix: record_split same-event check |
| 831bbdf84 | todo 515 closed, 516 filed, PRIORITIES |
| this commit | summary |

## Deviations from plan

1. [Interpretation] The brief puts ETHA's row "at the true first post-split session". The table,
   its three writers and D7 define effective_date as the last day on the old scale, so the row
   is dated 2026-10-05 and its detail names 2026-10-06. d2-v2 reads the date one session late
   (`bar_date >= effective_date` counts as current). No ETHA bar is affected because 2026-10-05
   has new-scale evidence answers. The fix is filed in 516, item 3.
2. [Schema, brief-directed] Migration 461 adds the bar_hold table, a void action type, inferred_by
   operator and a unique index on supersedes. One row cannot supersede two under the single
   supersedes FK, so ETHA's result is one correcting row plus one void row.
3. [Rule 1] The overlap judge listed the old-scale request among a split's evidence, and d2-v2
   counts evidence as current. The 2026-10-08 ETHA row named the 20-year d1-bootstrap request. A
   split's evidence is now new-scale requests only (49ec2ae6c).
4. [Rule 1] record_split only looked for the same date and inferred_by nightly_overlap. Re-judging
   the 2026-10-08 run re-recorded ETHA at 2026-09-30 beside the correction (measured in a
   rolled-back transaction). A current row of the same factor dated on or after the detection is
   now the same event (113ff0aa5, 09824e858).
5. [Rule 1] record_split's detail was double-encoded (a JSON string) on codec connections. It is
   now passed as `$6::text::jsonb`.
6. [Rule 2] Two readers ignore void rows: D7's explained-dates read now uses
   corporate_action_current, and the fetcher's 5m waiver excludes void rows.
7. [Scope] The daily stage got a `held` report column (last), so `error` stays failure-only.
8. [Apply] The ETHA daily apply (changed 0) was run to clear the 549 wrong quarantine flags. The
   brief asked only for the dry run, but the wrong flags were stored.
9. [Process] Pre-commit's duplicate-test check forced a rename (test_bar_hold_migration_runs_in_one_transaction).
   STATE.md, ROADMAP.md and REQUIREMENTS.md were not written (brief). There was no separate
   /simplify or /review skill pass; the diff was self-reviewed.

## For 189-10 Task 3 (fetcher timer)

- The judge now records only recognised split ratios. Any other constant rescale holds the name,
  emits `unclassified_rescale`, makes the run partial (escalation code 1) and still triggers the
  name's full-depth re-fetch. The run-end daily stage skips the held name itself, so the
  fetcher needs no CTVA exclusion. A partial run caused by a new hold needs a human decision
  (release, or a spin_off row once 516 lands); it is not a retry.
- CTVA stays held. Expect freshness_1d and canonical_recompute to fail on CTVA every D7 run until
  516. The fetcher keeps asking CTVA nightly; the answers land in D1 and are not derived.
- Re-judging a past run by hand (`ops_split_detect.py --fetch-run-id`) no longer re-records
  ETHA. Holds stay idempotent per factor.
- Residual risk: a spin-off whose rescale sits within 0.2 % of a small ratio still records as a
  split (Tradier's 6.665 vs 20/3 shows this can happen). The company record is the only
  identifier; corrections go through `--void`, `--hold-rescale` or `--supersede`.
- New APR reads: the fetcher's 1d judge raises if any `infra.backfill.split_ratio_*` key is
  missing (seeded live).
- Unchanged: the fetcher timer and service are disabled and inactive. No IBKR or Tradier request
  was made.

## Known stubs

None.

## Threat flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: correction path | scripts/ops/bars/ops_split_detect.py | By-hand writes to corporate_action (operator rows) and bar_hold. Each is a dry run unless --apply, runs as one transaction under bar_derivation_writer, validates current rows, one symbol, a recognised ratio and evidence requests of that symbol; append-only triggers unchanged |

## Self-Check: PASSED

- Files exist: services/bar_hold.py, production/migrations/461_bar_hold_and_corporate_action_void.sql,
  tests/unit/services/test_bar_hold.py, tests/unit/test_bar_hold_migration_contract.py, todo 516,
  completed/515.
- Commits 04779c1db, 15df4ec86, b87934760, 49ec2ae6c, 113ff0aa5, 09824e858, 831bbdf84 are pushed.
- Live: three APR keys; one current ETHA row (ce003ee6); CTVA hold 72cc2b5e open; no current
  CTVA action.
- Full `tests/unit/ -q` exit 0 after the last code change; link integrity passes. repro_frozen
  not run: nothing under src/intelligence/research or statistics changed.
