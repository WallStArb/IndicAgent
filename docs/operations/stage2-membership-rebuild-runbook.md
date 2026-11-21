# Stage 2 membership rebuild after the pit-map placement amendment

Status: PREPARED 2026-11-20, nothing applied. Run only after the owner adopts the amendment in `docs/plans/2026-11-20-pit-map-unplaced-names-measurement-and-amendment-draft.md` (section 5) and the preregistration records it. Steps marked CODE depend on code that is written after adoption (test first, independent review, suite exit code); the rest exist today.

## Preconditions

1. Owner adoption recorded as a dated amendment in `docs/plans/2026-11-13-stage2-universe-preregistration.md` (P1 scope, the hand list or its disclosure, the reset, the repin).
2. No heavy job: `pgrep -af 'ops_split_calendar_audit|bar_derivation|ops_massive_load|ticker_entity_map_writer|universe_membership_writer|repro_frozen|ops_canonical_rebuild'` shows nothing (the pattern matches your own `bash -c` line; read the python lines only). One heavy job at a time. Heavy slot order for this runbook:
   1. the strict sweep (`ops_split_calendar_audit --sweep --witness yahoo --strict`, log `logs/sweep_strict_members_20261120/`) finishes first and its exit code is read;
   2. any derivation run (todo 641 and later split rows) finishes and its exit code is read;
   3. then steps 3 to 7 below, each one at a time, none overlapping another;
   4. the tape slice (`logs/massive_tape_slice/`) is network and disk only and may run beside steps 1 and 2; stop it by PID if the map build, the install or the raw load slows;
   5. place the install lock window (2 to 10 minutes on `ticker_event`) and the heavy steps away from the nightly timers (alpaca-nightly 23:42 ET, bar-derivation 00:20 and 00:45, reconciliation 01:00).
3. Shared checkout clean at `origin/main`; pushes go through a scratch worktree off `origin/main`, never `git reset` in the shared checkout; a pull blocked by an untracked file is cleared by moving that file aside.
4. The live `ticker_event` spans are the base (38,097 rows on 2026-11-20, equal to `data/ticker_entity_map/20261118_6195ae11abff/spans.csv`; its `pinned_spans.csv` is the 1,745 kept spans, not the live set). The build pins the live spans' own hash, so the check only proves the table did not move between the build and the install.
5. Copy the 2026-11-19 evidence aside first: `run_609.sh` s5, s6 and s7 overwrite fixed paths (`run_609_s5_apply.log`, `members_tier_by_year.csv`, `tier_cost_*.csv`). The status file already holds `609_s5 REHEARSAL DONE` and `APPLIED` from 2026-11-19, which permit `--apply` without a fresh rehearsal: run the rehearsal anyway and read it; markers are permissive, nothing enforces it.

## Steps

1. Backup and record (read only, a minute).
   - `mkdir -p data/backups/stage2-membership-pre605-20261120`
   - `PGPASSWORD=postgres pg_dump -U postgres -h localhost -d indicagent -Fc -t universe_membership -t universe_membership_build -f data/backups/stage2-membership-pre605-20261120/membership.dump`
   - Count record: `psql ... -Atc "select (select count(*) from universe_membership), (select count(*) from universe_membership_build)"` must read `858454|278`; save it in `counts.txt` beside the dump and `sha256sum membership.dump > membership.dump.sha256`.
   - Also record the closed-list pin and the live digest: `.venv/bin/python -m services.universe_membership_report` prints both (MATCH expected before the change).
2. CODE: the planner change (P1 spans for every run of the key under the FIGI identity condition, `spanless` restricted to equities) and the install and rollback support for spans on an existing instrument's identifier (`install_pit_plan`, `plan_rollback`, `retire_install_identifiers`, `_prove_rollback` assume new symbols today), merged to `main` with its tests, `/simplify`, `/review`, the unit suite exit code. The rehearsal below runs from that commit.
3. Build the scratch map version (read only; measure the time, it is not known).
   - Same command shape as `run_609.sh` s2: `.venv/bin/python -m services.ticker_entity_map_writer --pit-anchor --map-dir <current map dir> --pinned-map-digest <its digest> --pinned-spans-sha256 <live spans sha256, computed the way run_609.sh s2 computes it> --out <new scratch dir> --version-date <today, not the pinned map's date>`. The live spans are the base; the new map differs from them by the P1 spans only (and the ten futures-collision equities that no longer attach to futures symbols).
   - Check in `span_accounting.csv`: the `already_live` rows of the 112 P1 names are now placed; no span of any other symbol changes; the ten futures symbols (CL, ES, HG, NG, NQ, SI, ZF, ZN, ZS, ZT, with HG) carry no equity span; CRH and FTAI are unplaced (hand list); ARES, CR and VLY are placed only if the claimed-ticker variant is adopted, else unchanged.
4. Independent review of the map version before anything is installed: every placed name above $100M a day (61 of them are in the 128 at L) and a 30-name sample of the rest, each against the pit lists (run start, CIK, FIGI, instrument identifier) and canonical bars (same issuer, no step at the first placed month).
5. Install rehearsal, then apply (the `ticker_event` table is locked for the run, about 2 to 10 minutes; quiet window, detached with `setsid`).
   - Rehearsal: `.venv/bin/python -m services.ticker_entity_map_writer --pit-install <map dir> --install-digest <digest> --install-spans-sha256 <sha256 the build printed>`; read `outcome rolled_back`, the written counts (spans only, no instruments or identifiers for P1), `rollback_proof` (`live_rows_equal_pre_install true`, `replan_files_identical true`).
   - Apply: the same command with `--apply`. Record the install id (for `--rollback INSTALL_ID`).
   - Verify: the reach SQL of `logs/unplaced_reach_20261120/reach2.sql` again; unplaced at L must fall from 128 to 18 (110 placed; the other 18 are the hand list, the futures-collision equities at L and the residual names), and `unplaced_active_cs_adrc.csv` is regenerated as the after list. POINT OF NO RETURN: the next step is a Massive load citing the new spans, after which `--rollback` refuses without `--accept-loaded-rows`.
5b. Massive 1d raw load for the new spans, then canonical (the new spans have Alpaca bars only; the 2003 to 2015 history is empty until this step). `.venv/bin/python -m scripts.ops.bars.ops_massive_load --timeframe 1d --years <2026 down to 2003> --all-tickers --gap-list <new map>/gap_list.csv --out <dir>` dry run first, as `run_609.sh` s4 does (set `RUN609_NEWMAP`), then selection, the split audit (`ops_massive_split_audit`) and `services.bar_derivation --stage daily --symbols <the names> --apply`; hours, not measured. Then run the 647 audit (21 s): zero findings, and the `proven_start_1d` and strict-sweep scope reruns for the new members.
6. Reset the membership (migration 605, written and rehearsed in a rolled-back transaction on 2026-11-20; do not run before step 5 is verified).
   - `psql -v ON_ERROR_STOP=1 -f production/migrations/605_universe_membership_reset_for_rebuild.sql`; it refuses unless the live build is 858,454 rows over 278 month-ends and `research_run` is empty, copies the old build to `universe_membership_pre605` and `universe_membership_build_pre605`, truncates, and checks the four insert-only triggers are enabled.
   - Verify (the query at the end of the file): `0 | 0 | 858454 | 278 | 4`. The writer's `corpus_run` and `research_run` guards must still read 0.
   - The migration is committed in the same breath as it is applied (CLAUDE.md).
6b. Security type (todo 648; needs the owner's adoption of the 2026-11-21 amendment; after step 5 because the labels attach through the live spans, before step 7).
   - `psql -v ON_ERROR_STOP=1 -f production/migrations/606_security_type.sql` (committed in the same breath), then `.venv/bin/python -m services.security_type_writer` (rehearsal, rolls back; read the log counts), then the same with `--apply`. A second run reports `up_to_date`.
   - The membership build refuses while `security_type` holds no row for the current rule.
7. Rebuild and repin.
   - `bash scripts/ops/bars/run_609.sh s5` (rehearsal), read the counts, then `RUN609_CONFIRM=s5 bash scripts/ops/bars/run_609.sh s5 --apply` (156 s and 232 s on 2026-11-19; the stage gates in the script may need the `609_s5 REHEARSAL DONE` and `APPLIED` markers cleared: read `run_609.sh` before running and do not edit the status file by hand).
   - Repin before any closed-list month is built (the first is 2026-11-30; migration 605's guard fails once a 2026-11-30 month exists, so the reset precedes it): run `.venv/bin/python -m services.universe_membership_report`, which prints the live candidate-set digest next to the pinned one, set `CLOSED_LIST_CANDIDATES_SHA256` in `src/intelligence/universe_membership.py`, record the new digest and the line count in the dated amendment, update the two tests that name the old value (`tests/unit/test_universe_membership.py` locks only the format; the report test compares to the constant), run the unit suite, push. The membership report must print MATCH.
   - s6 (counts by year) and s7 (5m tier cost estimate) re-run through `run_609.sh`; the owner sees the member counts by year and the tier count before any compute that counts. The 2004 to 2015 member counts (about 2,000 against a preregistered 2,950) are expected to rise by the placed names; report both.
8. Rerun the unplaced reach script and the 647 audit once more; file the after numbers in the amendment; close the todo.

## Rollback

- Step 5: `--rollback INSTALL_ID` on the install (retires the inserted rows; proven in the rehearsal). Step 5b onward: not cleanly reversible (loaded rows cite the new spans). Step 6: the old build is in `universe_membership_pre605` and `universe_membership_build_pre605` and in the dump; once step 7 has repopulated the new build, returning to the old one needs another truncate with a changed guard and a new owner-approved migration, because the tables are insert only. Nothing reads the membership yet (no research run exists), so the cost is time, not data.
- A failed step stops the run; no step is retried blind. Report the log and the exit code.

## Evidence kept

`data/backups/stage2-membership-pre605-20261120/`, the scratch map directory (digests in the amendment), the install log with the install id, `logs/unplaced_reach_20261120/` before and after, the 647 audit outputs.
