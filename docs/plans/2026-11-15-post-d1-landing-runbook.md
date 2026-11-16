# Post-D1 landing runbook

**Status:** DRAFT 2026-11-15, written read-only from the state of `origin/main` at `aac9e84a5` and the held worktrees below. Nothing in it has been run. The lead executes it, in order, after step 7's Part D passes; every push is the lead's.
**Scope:** land every held worktree so the rebuild code key moves once, apply migrations 595 to 597, restart what the moves touch, then pin the corpus rerun. Companion docs: `docs/operations/massive-step7-runbook.md` (Parts C, D, F), `docs/operations/corpus-rerun-runbook.md`, the stage 2 preregistration, the readiness checklist `logs/massive_step7/post_step7_readiness_20261115/README.md` (items 0 to 17).

## 1. State verified 2026-11-15

| Held work | Worktree | Tip | Base | Ahead / behind origin/main | Touches |
|---|---|---|---|---|---|
| Refactor stack (6 commits) | `/home/bg/dev/wt-refactor-land` | `abd27158a` | `67e9bbfe6` | 6 / 11 | `services/batch_support/` split (deletes the old batch helpers module), 19 services, `scripts/ops/bars` (6), `src/core`, `src/config`, `src/api`, `src/intelligence/bars` (1), `src/intelligence/features` (1); migrations 595, 596 |
| L1 kernels (551, 552, 558) | `/home/bg/dev/wt-l1-kernels` | `d4adbb2f3` | `5d724bf16` | 3 / 9 | `kernels/`, `research_kernels/`, `contract/registry.py`, `feature_vector.py`, `feature_factory.py`; no migration |
| R2 item 1 (production-path golden) | `/home/bg/dev/wt-r2-prodpin` | `4db147529` | `5d724bf16` | 1 / 9 | tests, `production_golden.json`, one capture script; no code key |
| R2 cluster remainder (items 2, 3, 6, 7, 8, 4, 5) | not built | none | | | scheduled after the stack and L1 |
| L3 universe, with the 5m tier | `/home/bg/dev/indicagent/.claude/worktrees/agent-a9b86b958ee414b2e` | `fa3fedc49` | `5d724bf16` | 9 / 9 | `universe_membership` rule, writer, `corpus_universe`, data gate, `corpus_rerun`, `backfill_feature_factory`; migration 597 |
| I1 IC wiring | not built | none | | | plan only (L3 worktree, wiring plan items 1 to 7) |
| Docs: prereg drafts | landed on main as `1f3a83b11` | | | | docs only |
| Docs: 184-12 gate, 516 plan, this runbook | `/home/bg/dev/wt-184-12` | see the report | `aac9e84a5` | 0 / 0 | docs only |
| Docs: I2 tier design | landed on main as `aa5cc47e3` | | | | docs only |

Not mine and not in this runbook: `wt-refactor-batch` (`14b852606`, another session's), `wt-cleanup-audit`, `wt-runbook-partdf`.

**Migration numbers against `origin/main` today.** The highest file on main is `594_retire_alert_lag_bar_writer_apr.sql`. 595 and 596 (stack) and 597 (L3) are free on main and unique across the three branches. The IBKR raw delete (Part F migration, readiness item 2) must therefore be numbered **598 or higher**, not 597 as the readiness list says; `tools/gate.py` stops on a clash, so re-run it at landing. Any migration the R2 cluster adds takes the next free number above the highest then on main, checked at its landing.

**Pit-anchor branch (stage 2 identity map, lead ruling 2026-11-16: install after D4 at the 2026-11-09 anchor).** It lands with its own gate and a rolled-back install rehearsal, not in the order below. Migration 598 (the `cik_ticker` scheme) is already applied live and on main. Its index migration (a partial index on `ticker_event (security_identifier_id)` for unretired spans) is currently numbered 601 in its worktree because the R2 cluster takes 599; renumber to the next free number at landing (`tools/gate.py` stops on a clash). The index is needed: the retire trigger probes `ticker_event` once per identifier retired, measured 10.3 ms a probe on 39,600 rows without the index and 0.01 ms with it, so the install rehearsal's own rollback (47,674 identifiers) costs about 8 minutes without it. It rewrites no compressed table, so no `VACUUM` clause is owed.

**Applied state live (no version table; checked by object).**
- 594: applied. `config_schema` holds no `alert.lag.bar-writer` key. STATE.md still says "not applied"; the file is idempotent, so re-running it is harmless, and STATE should be corrected.
- 595: not applied (no `infra.bar_replay.bars_per_sec` key).
- 596: not applied (`alpha.ic.active_scales.5m`, `.15m`, `.1h`, `.1d` still present).
- 597: not applied (`to_regclass('public.universe_membership')` is NULL).
- Compression: none of 595 to 597 rewrites or changes the type of a compressed column, so none owes a `VACUUM` clause. The CLAUDE.md rule (decompress, `ALTER COLUMN TYPE`, recompress ends with a bare `VACUUM <table>;`) binds only the Part F migration (598+), which already carries its own bare `VACUUM ohlcv_raw;`.

## 2. The ordering principle

1. Everything that moves `rebuild_code_key()` lands before the corpus rerun pins, in one window, so the key moves once. The closure includes `services/backfill_feature_factory.py`, the factory, `corpus_universe` and the rule module (L3), `batch_support` (the stack), and the kernels and registry (L1). Nothing in it is edited after `--new-run`.
2. Landing starts only after **all of Part D** (D1 to D4, D6): D4 runs `bar_reconciliation_audit` for 77 minutes, and the stack edits it and `bar_derivation`, `bar_auditor`, `bar_scrub`, step 7 imports. D1 alone is not enough.
3. Land **before D5** (restart of the quiet list). All timers and the compression auditor are stopped today, so no live process holds the old code; restarting once at D5 puts every unit on the new code with no second restart. This reorders the readiness list's items 1 and 4 (it has D5 first); the reason is the single restart. If the lead prefers D5 first, every oneshot still picks up new code on its next run and only the two long-lived enabled units in section 6 need a restart.
4. Order of landing minimizes conflicts: stack, then L1, then R2 item 1, then the R2 remainder, then L3. L3 touches `services/backfill_feature_factory.py` and `services/corpus_rerun.py`, which the stack also edits, so it goes last and takes the conflict.

## 3. The per-landing procedure (applies to every code landing)

From the worktree (detached; there is no `.venv` there, so use the main checkout's interpreter):

```bash
cd <worktree>
git fetch origin
git rebase origin/main                     # conflicts: resolve, re-run the tests of every file touched by a conflict
PY=/home/bg/dev/indicagent/.venv/bin
$PY/python tools/gate.py --dry-run         # prints the plan: diff class, migration clash check, suite, repro_frozen if research/statistics moved
$PY/python tools/gate.py                   # runs it; exit code is the verdict
$PY/ruff check . && $PY/black --check .
$PY/python tools/check_glossary.py
$PY/python tools/check_duplicate_tests.py
$PY/mypy src/ --ignore-missing-imports | $PY/mypy-baseline filter   # exit 0 required
```

- Judge by exit codes, never a tail. `mypy-baseline filter` exits 2 when violations were resolved: run `mypy-baseline sync`, review that the baseline only shrank, and commit it with the landing.
- `repro_frozen` (bit-identical) runs inside `gate.py` when `src/intelligence/research/` or `statistics/` changed. For L1 run it explicitly after the push too: `$PY/python -m scripts.research.determinism.repro_frozen <scratch_dir> --logs /home/bg/dev/indicagent/logs` (it must report bit-identical).
- Each code landing gets an independent review before the push (the Done-Coding SOP). The stack, L1 and L3 reviews are recorded; a rebase that changed content (a conflict resolution) is re-reviewed on the conflict hunks.
- Push: `git push origin HEAD:main` (never chained with a first commit). Then fast-forward the shared checkout (`git -C /home/bg/dev/indicagent merge --ff-only origin/main`) only when no live process imports the changed modules (the quiet list is stopped, no rerun is live).
- A migration applied live is committed in the same breath: apply with
  `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -v ON_ERROR_STOP=1 -f production/migrations/<file>.sql`, then verify with the object check in section 1, in the same step as the push.

## 4. The steps, in order

| # | Step | Needs first | Gate | Owner adoption it waits on |
|---|---|---|---|---|
| 0 | Part D passed: D1 `--verify` exit 0, D2, D3, D4 (`bar_reconciliation_audit`), D6 docs | step 7 Part C done | the readiness item 0 gate | none |
| 1 | Land the refactor stack `abd27158a` | 0 | per-landing gate, plus `tests/unit/test_table_and_apr_key_readers.py` (it covers 596's key retirement); the stack's own review | none |
| 1a | Apply 595 then 596 | step 1 pushed | after each: the object check (section 1); `psql -c "select count(*) from config_schema where config_key like 'alpha.ic.active_scales%'"` returns 0 | none |
| 2 | Land L1 `d4adbb2f3` (rebase onto step 1) | 1 | per-landing gate; kernel parity bit-equal float32 at and after warmup; `repro_frozen` after the push | none |
| 3 | Land R2 item 1 `4db147529` (rebase onto step 2) | 2 | `tests/unit/intelligence/test_production_path_golden.py`. L1 moves two kernels the golden reads (`high_52w_dist`, VWAP deviation): if the golden fails after the rebase, regenerate with `features_capture_kernel_parity_golden.py --production`, read the diff, and record the reason in the commit; never regenerate silently | none |
| 4 | R2 cluster remainder (items 2, 3, 6, 7, 8; item 4 deletes `ctf_regime_align`; item 5 retires the dormant streaming stack after item 2): each its own commit, rebased onto the last, same gate | 3 | per-landing gate each; a deletion also passes the repo-wide grep for dangling references (todo 614 row 22 (4)) | none |
| 5 | Land L3 `fa3fedc49` (rebase last; expect conflicts in `backfill_feature_factory.py` and `corpus_rerun.py`, resolve and re-run `tests/unit/services/test_backfill_feature_factory.py`, `test_corpus_rerun.py`, `test_corpus_rerun_data_gate.py`, `test_universe_membership_writer.py`, `tests/unit/test_universe_membership.py`) | 4 | per-landing gate; the I1 and I2 docs ride in it | 5m tier amendment: the code carries $25M / $12.5M; adopt before the tier load, but the code may land first because the load is gated separately |
| 5a | Apply 597 | step 5 pushed | `to_regclass('public.universe_membership')` and `to_regclass('public.universe_membership_build')` are not NULL; both tables empty | none |
| 6 | Build I1 (IC wiring, wiring plan items 1 to 7), review, land | 5 | per-landing gate; `repro_frozen` bit-identical; a methodology-change ledger entry written before any real-data look; `check_ic_universe_aligned` passes per timeframe | seen-name holdout (item 7 of the plan, B-U) is an optional inclusion; ledger entry E23 (prereg drafts doc) |
| 7 | Docs landings: prereg drafts (`023457eae`), 184-12 gate and 516 plan drafts, the I2 tier design `45cb4e9f7`, this runbook | any time after step 0 (they touch no code key) | `tests/unit/test_doc_schema_numbers.py`, `test_todo_priorities_link_integrity.py`, glossary check, em-dash grep; the prereg drafts and the I2 tier design landed 2026-11-15 (I2 `aa5cc47e3`, prereg drafts `1f3a83b11`) and cross-reference by path | none; they are drafts and stay labelled DRAFT |
| 8 | Operator steps from STATE (sudo): remove the installed bar-writer, cross-asset, macro-compute, roll-batch and hmm-training units, reinstall the wave targets, `daemon-reload`, restart `service_auditor` | 4 (item 5 and 7 of R2 deleted their sources) | `systemctl list-unit-files 'indicagent-*'` shows none of the removed units; `_DAG_ORDER` and units consistent | none |
| 9 | D5: restart the quiet list on the new code (timers and the compression auditor, `service-auditor` by hand, Alpaca nightly last) | 1 to 8 | the first nightly completes and backfills the missed sessions; `job_completed_total` ok | none |
| 10 | Part F: apply the IBKR raw delete migration (number 598 or above) | D evidence final; D5 done | `ohlcv_raw` rows with `vendor = 'ibkr'` and `timestamp >= '2003-09-10'` are 0; bare `VACUUM ohlcv_raw;` ran; the Part F gate | the owner exception to law 528 (the ledger entry the lead is landing) |
| 11 | Stage 2 gates 4 and 3: dead-name instrument rows through the onboarding SOP exception; the entity map rebuilt on the pit anchor (`--pit-snapshots`, `reference_raw` already loaded); then `ops_massive_load.py --all-tickers` 1d, gated per year, `--apply` | 9 | per the preregistration amendments of 2026-11-13 and 2026-11-14 | none (adopted 2026-11-13) |
| 12 | Stage 2 gate 5: `PYTHONPATH=. $PY -m services.universe_membership_writer` (rehearsal), then `--apply`; show member count by year to the owner | 5a, 11 | the writer's own guards; the count by year agrees with the preregistration's 4,150 typical month-end; the owner sees it before any compute | the 5m tier amendment (the writer records `tier_5m` under rule id `stage2-2026-11-15`; a different adoption moves the rule id and rebuilds) |
| 13 | The 5m tier: the measured cost estimate, then the tier load | 12 | the estimate recorded as an amendment before loading | the tier amendment, adopted |

## 5. The rerun pin sequence (after step 12; step 13 may follow the pin for 5m, see the note)

All code that moves `rebuild_code_key()` is on main by step 6. Then, from the main checkout at the pin commit:

1. Readiness item 11, read-only: every 584 manifest row reads landed with `git log` matching; 566's 71 held names closed.
2. `$PY -m services.corpus_rerun --new-run --plan-only [--horizon YYYY-MM-DD]` (writes nothing; needs `universe_membership` built, else `corpus_universe` refuses). The plan must fit the limit; the 1d and tier terms are in the preview.
3. `$PY -m services.corpus_rerun --quiesce` (records and stops the blocking timers; D5 restarted them, so this stops them again).
4. `$PY -m services.corpus_rerun --new-run --commit <sha of main after step 6>`: creates `<main>-corpus-run-<id>`, computes the code key and APR hash in it, inserts `corpus_run`. Record the run id, the commit and the code key. From here edit nothing the rebuild imports.
5. `cd <worktree> && $PY -m services.corpus_rerun --run-id <id> --step data_gate`, then `--step pilot`, then detached with `setsid`: `--through canary` (the runbook's step list). The 5m stages cover tier members only; the tier load (step 13) must have completed first or the 5m term has nothing to read.
6. After the run: `--release` restores the recorded timer set.

Owner items the rerun waits on: the clean-data lift (readiness item 19) before any counted test, not before the rerun; the tier amendment before step 13; the E23 ledger entry and A1, A2 before the first counted test.

## 6. What to restart after each code-key move

Code lands on main, not in a running process. Oneshot units load the new code at their next run and need no restart; only a long-lived process holding old modules does.

| Landing | Units whose code moved | Action |
|---|---|---|
| Stack (step 1), R2 (step 4), L1 (step 2) | `indicagent-api` (enabled; `src/api`, `src/config`, `src/core` changed) | `sudo systemctl restart indicagent-api` after the fast-forward |
| same | oneshots and timers: `bar-derivation-daily`, `bar-derivation-grid`, `bar-reconciliation-audit`, `dividend-event-writer`, `economic-series-writer`, `regime-coverage-auditor`, `feature-parity-auditor`, `research-ledger-render`, `alpaca-nightly`, `ic-measure` | none while stopped; they start on the new code at D5. If D5 runs first, nothing to restart |
| same | `service-auditor` (started by hand at D5; its `_DAG_ORDER` moved with the R2 deletions) | start it after step 8 so it reads the new registry |
| L3 (step 5) | `corpus_rerun`, `backfill_feature_factory`, the universe writer (oneshot, run by hand) | none; no unit runs them. `ic-measure` reads the same factory modules: confirm it is stopped until the rerun's `ic_measure` step |
| Part F migration | none | the nightly and derivation timers stay on their D5 state |

`systemctl list-unit-files 'indicagent-*'` before and after each restart confirms the set; a unit that fails to start after a landing means rollback of that landing (section 7), not a patch on main.

## 7. Rollback

Each landing is one push of a contiguous commit range, so rollback is `git revert` of that range (never reset a pushed main). Migrations: 595 and 596 are reversible by re-inserting the keys from `config_history`'s retained rows (596 deletes history; its rollback is the migration text of 271 re-applied, so apply 596 only after the stack's suite and the key-reader test pass); 597 is reversible by `DROP TABLE universe_membership, universe_membership_build` while both are empty, and not after the first `--apply` (the tables are append-only by trigger; a correction is a new rule id, never an edit). Nothing here touches a live canonical table.

## 7a. R2 item 4 and 5c landing notes (ctf_regime_align, migration 600, key re-measurement)

- Migration 600 drops `feature_vectors.ctf_regime_align` and raises unless the table is empty with no chunks. Apply it before any `ic_measure` run: the measure and its job keys must be made against the final column set, not one that the migration then changes. First verify, read-only: `SELECT count(*) FROM feature_vectors;` is 0 and `SELECT count(*) FROM timescaledb_information.chunks WHERE hypertable_name = 'feature_vectors';` is 0. If either is non-zero, stop; the migration refuses by design and the compressed-column procedure applies instead.
- The `concept_registry` row for `ctf_regime_align` is not touched by the migration (only `ConceptRegistryService` flips a status, UCR). At landing, after migration 600, deprecate it through the service: `ConceptRegistryService.record_transition(conn, domain=<the row's domain>, name="ctf_regime_align", from_status=<current status>, to_status="deprecated", reason="operator_override", notes="column dropped, migration 600, R2 item 4")`. `deprecated` is operator-only, so no automated reason is accepted. Read the row's domain and current status first and pass them as found; a stale `from_status` fails the optimistic lock instead of writing.
- After the final rebase of the whole R2 stack onto main (items 4, 5a, 5b, 5c and any later item), re-measure the `ic_measure` job keys and `rebuild_code_key()`, then run `repro_frozen`. The keys hash AST-normalized source (`normalized_source_for_hash` in `src/core/code_identity.py` drops comments and docstrings), so the comment and docstring edits of 5c move nothing. Item 5c moves the key only through `kernels/control.py`, `kernels/price.py` and `kernels/volume.py` (scalar helper deletions and import trims). Record the measured keys at the pin commit; do not carry them across a rebase.
- `record_transition` returns `LOCK_MISS` on a stale `from_status` and writes nothing, so a rerun is a safe no-op; check the returned `TransitionResult` and re-read the row if it is `LOCK_MISS`.

## 8. Open items found while writing this

- STATE.md says 594 is not applied; live state says it is. Correct STATE.
- The readiness list numbers the Part F migration 597; 597 is L3's, so it is 598 or above.
- The prereg drafts and the I2 doc have landed and reference each other by path. The prereg drafts still name the I1 wiring plan in words, because it lands with L3.
- R2 remainder is not built; its migrations (if any) will need the next free number at landing, above 597 unless Part F lands first.

## 9. Pre-land dry run (2026-11-15, scratch worktree off `0c539367b`, nothing pushed)

Each held worktree was cherry-picked in landing order onto a scratch detached worktree off the then-current `origin/main` (`0c539367b`), with `tools/gate.py` after each step (unit suite and `repro_frozen`; the gate plans `repro_frozen` for every step from the stack on because `scripts/research` is touched), plus mypy-baseline filter, ruff, black and the glossary check where noted. Landing after D4 is a replay of these commits in this order; rebase moves only the base.

| Step | Replayed | Scratch tip | Conflicts | Gate |
|---|---|---|---|---|
| 1 stack (6 commits) | `abd27158a` | `66613b3f9` | none | unit failed once: `test_no_dangling_references` (this runbook named the deleted batch helpers module by path); fixed by a docs commit `7cef9b90e`, then unit ok, `repro_frozen` ok, mypy-baseline filter exit 0, ruff 0, black 0. The stack's baseline sync removes 2 baseline lines and adds none |
| 2 L1 (3 commits) | `d4adbb2f3` | `620136bf7` | none (auto-merged `feature_vector_persistence.py`) | unit ok, `repro_frozen` bit-identical ("phase 181 S2 ... bit-identical", "S3 bit-identical"), mypy filter exit 0 |
| 3 R2 item 1 | `4db147529` | `e55f6fa25` | none | `test_production_path_golden.py` passes on the L1 base with no regeneration: the section 4 step 3 warning did not bite (L1's kernel moves leave the production-path digests equal). First gate run died with an xdist `INTERNALERROR: KeyError: <WorkerController gw2>` at 23 s (no test failure; worker-controller flake); the rerun passed unit (131 s) and `repro_frozen` |
| 4 R2 remainder | not built | | | not replayable yet; each item replays the same way when built |
| 5 L3 (9 commits) | `fa3fedc49` | `e91619386` | one: `.planning/todos/pending/609-...md`, because main now holds the short I2 pointer section and L3's first commit adds a "Build status" section at the same place. Resolved by keeping both, then a fixup commit `878aba8d0` merging the duplicate Blocker I2 sections into the L3 one and restoring the path-form references (the six files exist now) | unit ok (130 s), `repro_frozen` ok, mypy filter exit 0, ruff 0, black 0, glossary 0 |
| 5 fixup | one new commit | `8477f7cef` | | `tools/check_duplicate_tests.py` exited 1 on the L3 branch: `test_runs_in_one_transaction` in `test_universe_membership_migration_contract.py` duplicates the test of the same name in `test_ohlcv_load_revision_migration_contract.py` on main. Renamed to `test_universe_membership_migration_runs_in_one_transaction`; the check exits 0. Neither the gate nor the suite runs this check, so it must be run by hand at every landing |

Findings the replay adds to the procedure:
- Run `tools/check_duplicate_tests.py` explicitly at every landing; `tools/gate.py` does not.
- Run `tests/unit/test_no_dangling_references.py` before every docs push; a landing that deletes a file (the stack) makes docs that name it dangle.
- Replay the two docs-only fixups (`7cef9b90e`, `878aba8d0`) and the test rename (`8477f7cef`) with their steps; they are the only edits beyond the held commits.
- The L3 step's `repro_frozen` is bit-identical with migration 597 in the diff (no spec hash moved).
- Applying migrations 595 to 597 was not part of the dry run (no live writes); the object checks of section 1 stand.
