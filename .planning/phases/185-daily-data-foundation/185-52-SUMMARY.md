---
phase: 185-daily-data-foundation
plan: 52
subsystem: data-integrity
tags: [todo-517, d2-v3, daily_rule, split, restated-fallback, vendor-basis, d7, gap_closure]
requires: [185-48, 185-49, 185-51]
provides:
  - "rule d2-v3: a date the Tradier primary answered only on a stale scale takes the fallback's current-scale answer as ibkr_fallback when the restated basis over the nearest common sessions is within the interior tolerance"
  - "basis_closes: Tradier's stale-only close divided by the recorded split factors, a measurement only; used by the rule's ratios and D7's vendor_basis_run"
  - "D7 policy_conformance accepts ibkr_fallback where Tradier has no current-scale answer"
  - "daily stage: restated report column, load detail key and run summary"
  - "346,423 compute_1d month digests relabelled d2-v3 (content unchanged)"
  - "todo 517 closed"
affects: [189-10 Task 3, 186-26, todo 516, todo 518]
key-files:
  modified:
    - src/intelligence/bars/daily_rule.py
    - src/intelligence/bars/integrity_checks.py
    - services/bar_derivation.py
    - tests/unit/bars/test_daily_rule.py
    - tests/unit/bars/test_integrity_checks.py
    - tests/unit/services/test_bar_derivation_daily.py
    - tests/unit/services/test_bar_reconciliation_audit.py
    - docs/plans/2026-10-06-data-layer-integrity-design.md
    - docs/foundation/glossary.md
    - docs/foundation/instrument-onboarding-sop.md
    - docs/foundation/canonical-truth-registry.md
    - docs/operations/operations-database.md
    - .planning/todos/PRIORITIES.md
  moved:
    - .planning/todos/pending/517-tradier-history-before-d-after-a-split.md -> completed/
decisions:
  - "Option 1 of todo 517, with a basis test: the restated answer is admitted only under the interior fallback tolerance, measured against the stale Tradier close divided by the recorded factors (never served)"
  - "One basis measurement for the head seam, the interior test, the restated path and D7's vendor_basis_run, so a basis run inside a restated span stays visible"
  - "A current-scale fallback answer is one _is_current accepts: fetched after the split's recorded_at, or a split evidence request"
  - "No migration: the version bump only relabels digests through the existing --rewrite-digests path"
requirements: [D-06, D-07, D-21]
metrics:
  completed: 2026-10-09
  duration: about 60 minutes
  tasks: 6
---

# Phase 185 Plan 52: a stale-only Tradier primary yields to the restated IBKR answer (todo 517) Summary

Rule d2-v3 keeps a name's Tradier history before D tradeable after a later split. On a date where
the policy's primary answered only on a stale scale, the fallback's current-scale answer is
served as `ibkr_fallback` when the basis over the 20 nearest common sessions is within 10 bp;
otherwise the flagged stale bar stays, as under d2-v2. Live output is unchanged on every name
today, the digests are relabelled d2-v3, and D7's 1d verdicts are identical before and after.

## Rule change (RULE_VERSION d2-v3)

- New branch in `derive_daily_v2`. When the primary has only stale observations for a date, the
  policy names a fallback, and the fallback has a current-scale answer, the date is admitted if
  `within_tolerance(day)` holds. That is the interior hole test: median IBKR/Tradier ratio over
  the `basis_window_sessions` common sessions nearest the date, within `basis_tolerance_bp`. An
  admitted date is served from the fallback (source `ibkr_fallback`, no flag) and listed in
  `DailyV2Result.restated`. A refused date, or one with no current fallback answer, keeps the
  latest stale primary bar with `pre_split_unrefetched` (quarantined per APR), the d2-v2
  behavior.
- Basis measurement. A stale Tradier observation's close is divided by the product of the
  factors of the splits that make it stale (`corporate_action.factor` = old-scale over new-scale
  price; ETHA's reverse split is 1/3). The rescaled close is a measurement only and is never
  served, so this is not the vendor scale correction 185-49 rejected. A non-finite or
  non-positive factor measures nothing. A wrong recorded factor shows as a basis break and
  restates nothing (tested).
- The same ratio map feeds the head seam and the interior test. Without it, a split would empty
  the head seam's window and refuse every admitted IBKR head.
- "Current-scale" keeps d2-v2's `_is_current`: fetched after the split's `recorded_at`, or one of
  the split's evidence requests (the new-scale answers that revealed it, 185-51).
- Splits come from `corporate_action_current`, which hides void and superseded rows (migration
  461). A voided split never reaches the rule.
- Volume. Every fallback bar (head, interior, restated) keeps IBKR's raw volume in
  `market_data_ohlcv`. `market_data_ohlcv_tradeable` returns NULL for `ibkr_venue` and
  `ibkr_fallback`, confirmed against the live view definition. The view's `WHERE volume > 0`
  reads the raw column, so a fallback bar with zero or missing provider volume is not tradeable,
  the same as any bar. The module docstring states this and points at todo 518, the volume basis
  break.
- Where Tradier's history is only stale, there is no vendor seam flag (`fallback_seam` marks only
  the first Tradier-served bar after an admitted head). Under the interior rule, a switch between
  restated IBKR bars and current Tradier bars, when a split's effective date falls before D, is
  admitted by the tolerance test without a flag.

## D7 changes (integrity_checks.py)

- `policy_conformance` takes Tradier's current-scale dates. `ibkr_fallback` is accepted on a date
  with no current-scale Tradier answer: a hole, a head, or a stale-only date.
- `vendor_basis_run` reads `basis_closes`, the restated Tradier closes. After a split recorded
  past Tradier's last fetch, `current_closes` has no Tradier close before the split, so a run
  inside the restated span would be invisible. Through `basis_closes` an IBKR step there blocks,
  because the canonical side is IBKR (tested).

## Golden cases (tests first, 096dd3d2d)

`tests/unit/bars/test_daily_rule.py`, d2-v3 section:
- (a) split recorded after Tradier's fetch, IBKR fetched after recorded_at: every date served as
  `ibkr_fallback`, no flag, `restated` lists them, IBKR's volume kept. A split evidence request
  also counts.
- (b) IBKR stale too, or absent: Tradier served with `pre_split_unrefetched`, nothing restated.
- (b') IBKR 15 bp off the restated basis: kept flagged. At 8 bp: restated. A wrong factor (3
  instead of 2): nothing restated.
- (c) no split: unchanged.
- (d) a voided split never reaches the rule (empty split list gives the no-split result). The
  daily stage test checks that splits are read from `corporate_action_current`, and the
  migration 461 contract test checks that the view hides void rows.
- (e) dates with no IBKR answer inside a restated span stay flagged, so they are quarantined
  holes.
- An effective date inside the span: only dates before it are restated. An IBKR primary with no
  fallback still flags a stale-only answer. An admitted head stays admitted after a split.
- RJF real extract with a hypothetical 2:1 split and IBKR re-answering on the new scale: IBKR's
  own +52% step at 2021-09-22 makes the restated basis about a third off before it. Those dates
  keep the flagged stale Tradier bar; IBKR is served only after the step.

`tests/unit/bars/test_integrity_checks.py`: a restated name passes policy_conformance,
canonical_recompute, digest_fresh and vendor_basis_run, and an IBKR step inside a restated span
fails vendor_basis_run. `tests/unit/services/test_bar_derivation_daily.py`: the `restated` report
column, the load detail key and `rule_version` d2-v3.

## Dry run over all names (read-only)

`--stage daily` unscoped, 2026-10-09 01:59 to 02:01 UTC, `logs/185-52/daily_dryrun.tsv`: 1,501
derived and CTVA held, with new 0, changed 0, removed 0 and restated 0. Head 170,659, refused
head 5,128, admitted interior 10,819 and refused interior 65 equal the d2-v2 state (no bar
moved). ETHA, the only current corporate action (reverse split 1/3 at 2026-10-05, recorded
2026-10-08 21:59 UTC), has 555 unchanged bars and restates nothing, because Tradier's adjusted
refetch is the split's evidence and is current. No surprise appeared, so the brief's stop
condition was not met. No bar apply was needed.

## What-if: every name splits at D (read-only)

`logs/185-52/whatif_split_at_d.py` and `.tsv`, with the summary in `whatif_summary.txt`. The
model is a split effective 2026-10-06 with factor 1.0, recorded 2026-10-07, where IBKR re-answers
every date its latest stored SMART observation covers. Over the 1,501 derived names:

| measure | value |
|---|---|
| Tradier bars before the split | 6,688,554 |
| restated (tradeable, IBKR) | 3,601,700 (53.8%) |
| kept flagged, basis refused | 121,099 (1.8%), 294 names, 66 above 5% of their history |
| kept flagged, no stored IBKR answer | 2,966,187 |
| per-name restated share p10 / p50 / p90 | 0.004 / 0.747 / 1.0 |

- Names with the most refusals: ATRO, HON, VMRK, LEN, CENT, OKE, WBD, CUBI, FTI and O. These
  are the spin-off and adjustment-basis names of the design doc's finding.
- 547 names hold fewer than 1,000 stored SMART dates. The no-answer share is therefore a lower
  bound on what survives: the fetcher's full-depth split re-fetch supplies those dates.
- A first run stamped the re-fetch at 2026-10-07 01:00, before ETHA's real split was recorded,
  which made ETHA's re-answers stale. It was rerun with the re-fetch after every recorded_at;
  ETHA then restates 553 of 553.

## Version bump and digests

- `--rewrite-digests` dry run: 346,423 months to relabel, across 1,502 names. Apply at
  02:11:58 UTC, batch rule_version d2-v3. A second dry run reported 0 to write.
- Current compute_1d 1d digests: 346,423 d2-v3 and 2,630 d2-v2. The 2,630 lie on months outside
  each name's current bar span (heads removed by earlier plans). D7 does not recompute them, so
  digest_fresh does not read them.
- Stored daily flags (205 `fallback_seam`) keep rule_version d2-v2 until the name's next applied
  daily load rewrites them. No check reads a flag's rule version, and the digest carries only
  the flag rule.

## D7 before and after (1d failing names)

The before run is 185-48's by-hand run at 2026-10-09 01:28 UTC. It used the same code for these
modules, and no ohlcv_load, corporate action or policy write happened after 2026-10-08 21:59:48
UTC. The after run started 02:12 UTC with the systemd unit's PYTHONPATH and exited 0. Records are
in `logs/185-52/` (git-ignored): verdicts_before.tsv, verdicts_after.tsv, d7_after.out.

| check | before | after |
|---|---|---|
| canonical_recompute | 1 (CTVA) | 1 (CTVA) |
| policy_conformance | 0 | 0 |
| lineage_missing | 0 | 0 |
| digest_fresh | 0 | 0 (at d2-v3) |
| vendor_basis_run | 13 | 13 |
| freshness_1d | 4 (CTVA held, PSKY, QRVO, WBD) | 4 |
| session_coverage | 263 | 263 |
| unexplained_seam | 6 | 6 |
| held_1d (info) | 1 | 1 |

Across the 16,522 per-name 1d verdicts, the only differences are report_age's elapsed hours; no
check went from pass to fail. The intraday failing counts are also unchanged (coverage_cache 11,
grid_parity 131, slot_coverage 240, digest_fresh 0, stray_vendor_rows 0).

## Migrations

None. The rule version lives in code. The relabel uses the existing `--rewrite-digests` path
(the 185-38 cutover's step 5b), and no schema or APR key changed: the restated test reuses
`threshold.bar_integrity.fallback_basis_window_sessions` (20) and
`fallback_basis_tolerance_bp` (10).

## Todos

- 517 closed (completed/, closing note, PRIORITIES row). The link integrity test passes.
- 516 and 519 keep their scope. 516's item 3 (d2-v2 reads effective_date one session late)
  applies unchanged to d2-v3. 519's MOD refusal is an interior basis refusal, not a split.
- 518 unchanged. Restated bars read NULL volume, like every fallback bar.

## Commits

| Commit | What |
|---|---|
| 096dd3d2d | RED: golden cases, D7 judge cases, daily stage report and version |
| e950720eb | GREEN: d2-v3 rule, basis_closes, D7 conformance and basis run, daily stage wiring |
| 9545f7e8e | docs: design amendment, glossary, onboarding SOP, truth registry, operations; todo 517 closed |
| this commit | summary |

## Deviations from plan

1. [Rule 2, design within option 1] The todo's option 1 names no basis test. Serving IBKR in place
   of a stale Tradier span without one could reintroduce RJF-type IBKR steps as false returns.
   D7's vendor_basis_run would not see them, because Tradier has no current close there. So the
   restated path uses the interior tolerance test, measured on the stale Tradier close divided
   by the recorded factor (measurement only).
2. [Rule 2] D7's vendor_basis_run now measures the restated closes, and policy_conformance
   judges against Tradier's current-scale dates. Without these, a restated name would fail
   policy_conformance, and a basis run inside a restated span would be invisible.
3. [Rule 1] The head seam and interior windows use the restated ratios too. After a split, the
   d2-v2 ratio map has no pre-split common sessions, so every admitted IBKR head would have
   become a refused head.
4. [Process] The D7 "before" is 185-48's by-hand run 44 minutes earlier, not a fresh run. The data
   and these modules were unchanged in between, and the before and after tables match on every
   check.
5. [Process] No /simplify or /review skill pass inside this executor; the diff was self-reviewed.
   STATE.md, ROADMAP.md and REQUIREMENTS.md not written (brief). The daily stage unit tests write
   fake-run lines to `logs/bar_derivation.log` (a pre-existing test side effect, for example the
   01:44 UTC "symbols 2" line); nothing was written to the database by them.
6. [Dates] Recorded in UTC: work ran 2026-10-09 01:30 to 02:35 UTC (2026-10-08 evening EDT).

## For 189-10 Task 3 (fetcher timer)

- After a split recorded on a name with Tradier history before D, the run-end daily stage
  applies d2-v3. Every date before the split where IBKR's re-fetch answered on the new scale and
  the basis passes moves from `tradier` to `ibkr_fallback` in one load. That load can rewrite most
  of a name's history, and the revision waiver allows it because a corporate action was recorded
  after the last applied load. Nothing extra is needed in the fetcher.
- The split re-fetch must be full depth and must land in D1 before that daily stage reads the
  name; the in-process re-fetch (todo 507) does this. Dates IBKR does not answer stay flagged
  stale and quarantined.
- Expect loud, correct D7 failures after a split on a basis-disagreeing name: session_coverage
  (quarantined dates), and vendor_basis_run if IBKR steps inside the restated span. The
  candidates are the 294 names above, worst ATRO, HON, VMRK, LEN, CENT, OKE, WBD, CUBI, FTI and
  O. Such a name needs a 185-37 or 185-49 policy judgment (todo 517 option 2's row), not a retry.
- Pre-D restated bars read NULL volume in the tradeable view (todo 518).
- D7 now expects 1d digests at d2-v3. Every compute_1d month is relabelled. A daily apply writes
  d2-v3 digests for the months it changes.
- Unchanged: CTVA held, no IBKR or Tradier request made, the fetcher timer and service stay
  disabled.

## Known stubs

None.

## Threat flags

None. The change is pure computation plus a digest relabel through the existing writer, with no
IBKR or Tradier request, no fetcher start and no write to an observation row.

## Self-Check: PASSED

- Commits 096dd3d2d, e950720eb and 9545f7e8e are in history and pushed.
- `.planning/todos/completed/517-tradier-history-before-d-after-a-split.md` exists, and the
  pending copy is gone.
- Live: the daily dry run changed 0; the digest relabel's second dry run writes 0; D7 after exited
  0 with digest_fresh 0 failing.
- Full `tests/unit/ -q` exit 0 after the last code change; link integrity passes. repro_frozen not
  run: nothing under src/intelligence/research or statistics changed, and neither imports
  daily_rule, integrity_checks or vendor_basis (grep).
