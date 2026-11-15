# Draft amendment: 184-12 Task 1 gate text

**Status:** DRAFT 2026-11-15, unapplied. It edits `.planning/phases/184-multi-timeframe-research-inputs/184-12-PLAN.md` only when the lead applies it, after step 7 D1 and the corpus rerun's `feature_complete`. Nothing here runs a build, reads a counted statistic or moves a code key (docs only).
**Why:** readiness lane L6 (`logs/massive_step7/post_step7_readiness_20261115/README.md`, finding 1). Task 1 gate (a) requires a `186-27-SUMMARY.md` that does not exist, so the plan stops itself. The swap it waits for landed 2026-11-04 as migration 570 (commit `1202dd554`, "one feature table name": `feature_vectors_v2` becomes `feature_vectors`, v1 dropped). The `provenance_batch` rows it names are written by the corpus rerun, which supersedes the 186-26 rebuild (rows discarded at the new pin, migration 569). Three more premises in the plan text are stale; each is fixed below.

## Stale premises, and the fix for each

| Plan text | State today | Fix |
|---|---|---|
| Gate (a): a `186-27-SUMMARY.md` exists | never written; the swap is migration 570 | gate on the swap commit and the live table instead |
| Gate (b) and frontmatter: `target_table = ANY('{feature_vectors,feature_vectors_v2}')` | `feature_vectors_v2` is gone after 570 | `target_table = 'feature_vectors'` only |
| Gate (b): any completed batch under the rebuild writer | the rerun adopts and discards batches by code key; a stale batch from an older key would pass | all completed batches carry one `code_key`, equal to the pin of the rerun that reached `feature_complete` |
| Gate (c): "per the 186-27 summary's verification query" | no summary | the verification query is written out below |
| `universe: compute_eligible_1d` and "first 50 names of the universe sorted by symbol" | the family universe is the stage 2 membership (blocker I1, todo 609) | sample the first 50 names of `universe_membership` members at the span's last month-end, sorted by symbol; if I1 has not landed, the plan stops at this gate rather than sampling the old flag |
| Clean-data rule | owner 2026-10-30: no real-data hypothesis test until data is clean | unchanged: the dry S0 computes no member, target or statistic, so it is not a counted look; it still waits for the corpus rerun's own data gate |

## Replacement text for Task 1 gate (drop-in, for the `<action>` block)

Check the gate, all four mechanically, before any build:
- (a) The swap landed: `git merge-base --is-ancestor 1202dd554 HEAD` exits 0, and `SELECT to_regclass('public.feature_vectors_v2')` is NULL and `SELECT to_regclass('public.feature_vectors')` is not NULL.
- (b) The rerun reached `feature_complete`: the run state of the corpus rerun (`docs/operations/corpus-rerun-runbook.md`, `--run-id <id>`) lists `feature_complete` as completed, and the run id and its pinned commit are recorded in the report.
- (c) One generation of batches: `SELECT count(*) AS n, count(DISTINCT code_key) AS keys, count(DISTINCT apr_hash) AS apr FROM provenance_batch WHERE status = 'completed' AND writer = 'backfill-feature-factory' AND target_table = 'feature_vectors'` returns n greater than 0, keys = 1 and apr = 1, and that code key equals the run's pinned `rebuild_code_key()`. Any `status <> 'completed'` row for that writer and table other than a superseded generation fails the gate. Record n, the key and the hash.
- (d) For the sized 5m case only: the same query with `AND tf = '5m'` returns n greater than 0. Under stage 2 the 5m rerun covers the tier only (`corpus_universe(conn, intraday=True)`), so the sized 5m case names tier members only; if (d) alone fails, the 1d and 1h build still runs and the 5m case is recorded as not run with the query result.
If any of (a) to (c) fails, write `184-12-DRY-S0.md` with "Gate not met" and the results, commit no code, and stop the plan reporting the blocker.

## Replacement for the frontmatter prerequisite

`GATE: the corpus rerun reached feature_complete under one code key (migration 570 swap, commit 1202dd554, feature_vectors rebuilt). Task 1 checks this mechanically and stops the plan if it fails; there is no human approval step`

## Other edits the amended plan needs

- Task 2 sample: the 50 sorted names come from the membership universe (above); adversarial symbols (late listings, missing bars, half-day activity) are chosen by query from the same membership, named in the report before the build.
- Task 2 span: two years ending at least a year before `alpha.validation.oos_start` (2025-12-24), unchanged.
- The H-C and H-A families do not read stored columns for their members, so the dry S0 columns stay as the plan chose them (one price-level 1d, one 1h, the high-memory 1d, one 5m).
- 184-11 wiring (readiness lane L6, second clause): `184-11-SUMMARY.md` does not exist today; re-check at apply time, and if it is still absent the same stop rule applies to it.
