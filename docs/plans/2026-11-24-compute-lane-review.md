# Compute lane review: pilot to first counted look

Status (2026-11-24, ubuntu1, read-only; drafted by an Opus pass and spot-checked: cited paths exist, the 32,194 leftover rows and the stored 190,642 s extrapolation were confirmed in the database; the rest is the drafter's, to be ruled by the lead; main at 40b992d48, `rebuild_code_key()` 09708ae249f2 confirmed). The lane resumes cleanly at 1d: a kill loses at most two 25-name groups, a few minutes of work. Stage_1d is a hours-long job, not the 53 hours stored in `corpus_run.measured`. The largest wall-clock risks sit outside the kernels. A stale pilot unit makes chunk 0 fail for certain. The ic_measure step must not run until todo 671 lands. Todo 669 is the longest pole to a counted look. Decision: clear the stale unit before `--new-run`, run the corpus `--through feature_complete`, and build 669 and 671 while stage_1d runs. One kernel edit (the SMC order-block scan) passes the lead's 10 percent rule, but only if it proves bit-identical.

## A. Stage_1d resumability

Unit and identity. At 1d a unit is one 25-name chunk over the whole span (`rebuild_unit_ranges` returns one range for 1d, `services/backfill_feature_factory.py:475-476`). The chunk size comes from APR `infra.feature_factory.rebuild_symbols_per_chunk` = 25 (lines 424-441). That gives 515 units for 12,857 names. `batch_key` hashes writer, tf, range, `symbols_hash`, `code_key`, `apr_hash` and `input_digest` (`services/batch_support/bulk_load.py:289-302`).
- `code_key` is `unit_code_key`, a sha256 over every contributing kernel module key plus the writer's import closure (`backfill_feature_factory.py:542-548`, 61 writer modules from `writer_code_modules`, 537-539).
- `apr_snapshot` is `dataclasses.asdict(FeatureFactoryConfig)` (1534).
- `input_digest` covers the month bar digests, counts, first and last bar, and the proven start (1143-1157, built at 1222).

An edit to any hashed module renames all 515 units, and none is skipped. The run's pin gate also refuses on HEAD, code key or APR hash (`services/corpus_rerun.py:1199-1213`; runbook `docs/operations/corpus-rerun-runbook.md:276-277`: start a new run). Throughput keys (`infra.feature_factory.workers`, `infra.blas_threads_per_worker`, block rows) are not in `rebuild_apr_keys` (1253-1264) and not in the run's pinned list (checked in `corpus_run.measured->apr_keys`). They can change across a kill. `alpha.ic.feature_block_columns` and `rebuild_symbols_per_chunk` are pinned.

Kill semantics:
- bulk_load commits the `started` provenance row first, then the COPY and the `completed` mark in one transaction (`bulk_load.py:441-482`, 541-550). A killed unit leaves `started` and zero rows, and the resume takes the row over (479-481).
- The stage checks `completed_provenance_batch` per unit before dispatch (`backfill_feature_factory.py:1734-1763`). Completed units cost two planning queries per group (`_plan_group`, 1167-1225).
- The step runner re-begins a `started` step (`corpus_rerun.py:299-304`, 1094-1138). `--through` walks the chain and no-ops completed steps (1140-1147).
- Spools from a killed run are purged at the next start (1236-1240, 1649). SIGTERM gives no `finally`, so the purge does the cleanup.

What a kill loses. At most the group whose spools are loading plus the group queued behind it (pipelining, 1812-1819): 50 names, the worker in-memory series and the spool files. Wall time per unit at 4 workers (estimate): 25 names at a mean of about 2,400 bars (27.6M stored rows in the run's disk plan / 12,857, plus the 252-row skip). Scaled from the 8-name profile (about 3.1 ms per bar linear, plus an HMM term growing as n squared over 504), that is about 10 to 12 s per name profiled, so 35 to 70 s per unit. A kill therefore costs about 2 to 3 minutes of compute, 1 to 2 minutes of replanning and about 5 minutes for `compression_bound` at stage end (see B7).

Measured baseline. The failed pilot of run a4f6ad40 (12 workers, chunk 0) computed 25 names in 52 s and loaded 32,194 rows in 2.2 s. It then spent 317 s in `compression_bound` before `rebuild_complete` (`logs/corpus_rerun.log.2.gz`, 23:11:19 to 23:16:36). Its `pilot_seconds_1d_chunk` 370.2 and `extrapolated_seconds.stage_1d` 190,642 (53 h) therefore include that one-off cost 515 times (`corpus_rerun.py:1545-1549`). They are not a budget. My estimate for stage_1d at 4 workers is 6 to 10 h (unmeasured; cProfile inflation unknown).

Safe kill procedure:
1. `kill -TERM -- -<pgid>` of the `setsid` group (`scripts/ops/guarded_run_common.sh:41,51`). The forkserver and its workers share the group.
2. The `ps | awk '/backfill_feature_factory/'` pattern in `backfill_feature_factory.py:21-22` likely does not match workers under `python -m services.corpus_rerun`, whose children carry the forkserver command line (unclear, not tested). Use the pgid, then confirm no `multiprocessing.forkserver` process remains.
3. Terminate any `active`/`ClientWrite` COPY backend (docstring 23-26; gotchas line 218).
4. Keep the six timers quiesced. `corpus_pilot.sh:38` releases them after any exit, including a watchdog 143. If the derivation timers then restate bars before the horizon, input digests move and completed units stop matching at `feature_complete`. Dividend rows are not in any digest (see D).
5. Relaunch the same `--run-id <id> --through ...` from the run worktree.

Pauses are safe. `idle_in_transaction_session_timeout` is 3,600 s, above `MAX_PAUSE_S` 1,200 (`guarded_run_common.sh:11`).

## B. Wall-clock levers, ranked

| # | Lever | Saving (basis) | Risk | Moves rebuild key | Changes stored value | Proof | Recommendation |
|---|---|---|---|---|---|---|---|
| 1 | Build todo 669 (horizon-5 route plus battery cells) and 671 (sweep-cell writer) while stage_1d runs | Days: no corpus family can run as registered (todo 669); 671 is a prerequisite of any real-data sweep | Low; research code is outside the rebuild closure (no `research`/`statistics` module in `writer_code_modules`, checked) and the run worktree is pinned | No | 669: `repro_frozen` bit-identical or ledger | `repro_frozen`, battery rebind | Do it. Run the corpus `--through feature_complete`, then ic_measure only after 671, 670 and 666 |
| 2 | Clear run a4f6ad40's stale chunk 0 unit before `--new-run` | Avoids one certain failed step: 32,194 rows (old key beb8d2b6) still sit in `feature_vectors`. The rebuild is append-only (no `replace_where`, 1212-1223), so chunk 0's new COPY hits `feature_vectors_pkey (symbol, tf, bar_ts)`. That fails the pilot if chunk 0 is sampled (about 12 percent), otherwise stage_1d at its end | None | No | No | Recovery section of the runbook (264-270) | Supersede the provenance row and delete its rows by the runbook procedure now (lead DB write) |
| 3 | Workers 4 to 8 | About 40 to 50 percent of stage_1d, 3 to 5 h (estimate; tasks are independent per symbol, 24 threads) | Thermal (117 C incident); owner gate is under 85 C (`guarded_run_common.sh:8`) | No | No; workers are outside identity | Identity is unchanged; `test_resume_loads_only_the_incomplete_units` (`tests/unit/services/test_backfill_feature_factory.py:1229`) | Start at 4. Raise mid-run by kill and resume once a cool measured run clears; no new pin needed |
| 4 | Stage launcher: stage_1d to feature_complete under `run_guarded`, timers held on rc 143, automatic resume after the 60 C gate | Removes overnight idle gaps after a watchdog abort or between steps (estimate: hours per abort) | Low | No (script only) | No | `bash -n`; dry run | Write it before stage_1d; `corpus_pilot.sh` covers the pilot only |
| 5 | SMC order-block scan (`smc.py:115`, called per row over a 100-bar window, 1084-1101) as one incremental or numba pass | Up to about 15 percent of stage_1d compute (16.5 percent of profile, estimate at 10x speedup) | Medium: float order must match exactly (numpy reductions vs loops) | Yes | Must not | `tests/unit/intelligence/test_production_path_golden.py` (4 real 1d cases, 1,500 bars) plus a new random-series equality test like `test_kernel_bounded_window_equality.py` | Land before the pin only if bit-exact on both; otherwise drop. Sweeps and pools (15 percent) together are a second candidate under the same rule |
| 6 | Shared pivot input (todo 477) | About 7 percent of profile (estimate 5 to 7 percent of stage) | Low to medium | Yes | No (same `find_peaks` call) | Golden plus random equality (as todo 477 states) | Below the 10 percent bar alone; bundle with 5 only if both are ready together |
| 7 | `compression_bound` in a 1d run | About 5 min per stage call (measured 317 s) | Restricting it would let compression close chunks the later `all` run must write | No | No | n/a | Leave it. It correctly compresses nothing below the earliest pending intraday unit |
| 8 | ic_measure refetch passes (scan, then a verified refetch per job, `services/ic_measure.py:761-791`) | Digest pass about 40 percent of a 1d run, about 1.5 h by linear scaling (todo 668, not measured) | Memory if cached | No (ic job key only) | No | `tests/unit/test_ic_measure.py` block-width equality | Measure on the 25-name dry run first; width 16 doubles block passes against 32 but is pinned for memory (todo 471). Do not change before that measurement |
| 9 | HMM warm starts, a rolling training window or fewer refits | Up to about 25 percent of compute (32.7 percent profile, estimate) | High: the expanding-prefix gate is a documented design choice (`_hmm.py:896-907`) | Yes | Yes | n/a | Proposal only, with a ledger line; not before this pin |
| 10 | HMM retry continues from iteration 200 instead of refitting from scratch (`_hmm.py:795-835`) | Unknown: depends on how often the cap is hit (not measured) | Medium: convergence-monitor history must be seeded or results differ | Yes | Must not | Golden plus `test_hmm_*` | Measure the cap-hit rate in the pilot before considering it |
| 11 | `_price_percentile_series_full` (todo 550) | 2.5 percent | Golden moves where pre-warmup writes 0.5 | Yes | Yes before warmup | `test_research_kernels.py` | Not before this pin |
| 12 | `blas_threads_per_worker` above 1 | Negative: measured slower in `services/batch_support/pool.py` docstring | Floats move about 1e-10 and the key is not in identity | No | Possibly in float32 tails | n/a | Keep 1 and never change it mid-run |
| 13 | Chunk size or unit size | Negligible: planning cost per group is small and the load is overlapped | Renames every unit (pinned) | No (it is APR identity) | No | n/a | Keep 25 |
| 14 | Overlap IC with stage_1d | n/a | Refused by design: steps need their upstream completed (`corpus_rerun.py:1103-1110`); per-column digests would see a partial table; `_verified_block` would refuse | No | n/a | n/a | No |
| 15 | Pilot 65-name rule | The hashed sample (`services/corpus_pilot_sample.py:30-41`) lands in about 61 chunks, about 1,525 names, 12 percent of stage_1d. The 25-name pilot computed 1 chunk | Units are kept and stage_1d skips them, so cost is lost only if the pilot fails and a key-moving fix follows | No | No | n/a | Keep (ledger 2026-11-22d constants). Budget about 1 h at 4 workers |
| 16 | Spool and bulk load | Load measured 2.2 s per 32k-row unit, overlapped with worker compute. Spool formatting is inside the unprofiled residual (unclear share) | Low | Yes | No | Spool tests 1276-1313 | No action until the pilot measures it |

## C. Statistics on the wall-clock path

E17 and StepM run nowhere in stage_1d or ic_measure.
- The pooled rank IC is ic_measure's own cost (lever 8).
- Todo 669 is on the path to the first counted look. Its new persistent battery cells are a heavy job that competes for the single heavy slot, so its battery should run as soon as stage_1d frees the slot.
- Todo 670 is synthetic and light. It can run during stage_1d using the factor-model variant.
- Todo 671 gates the corpus ic_measure step, if that step counts as the sweep. I read it that way; the lead should confirm.

## D. Research invariants

| Invariant | Evidence | Gap |
|---|---|---|
| temporal_integrity | Horizon pinned, every fetch `< horizon` (`backfill_feature_factory.py:35-37`, 595-601, 916, 1768). HMM fits on `obs_matrix[:boundary]` and gates on its own training slice (`_hmm.py:956-1011`) | Dividend amounts and coverage are read with no horizon cut (`backfill_feature_factory.py:696-709`). The yield kernel is trailing, so whether this is harmless is unclear |
| determinism | `batch_key` identity (`bulk_load.py:289-302`); `alpha.hmm.random_state` 42; BLAS capped (`pool.py`) | `blas_threads_per_worker` moves floats but sits outside identity (`backfill_feature_factory.py:1256-1257` says it never changes a value; `pool.py` says it moves the 16th digit) |
| single_writer | `SOLE_BULK_LOAD_WRITERS` (`bulk_load.py:242-250`); compute-only workers (`backfill_feature_factory.py:954-961`); one write connection (1705) | None |
| no_fill | Tradeable view only (270-271); warmup masked (617-633); short series spool empty (986-998); dividend NaN outside coverage (720-721) | None |
| point_in_time | APR snapshot per unit (1534); proven start in the digest (1154) | The universe comes from `corpus_universe` at stage time, which is fine because the panel reads member years. The proven start is the latest fact, not an as-of fact; it is in the digest, so a change is loud |
| lineage | One provenance row per unit with run id, code key, APR snapshot, digest and unit stats (`bulk_load.py:458-478`, 541-549) | The digest covers the chunk's own bars only. Restated SPY/TLT/SHY/TIP/HYG/LQD reference bars (1769) or dividend rows change every unit's inputs without renaming it. Today only quiesced timers protect this, so they must stay held across a kill |
| asset_agnostic | Kernels are array-pure | `_TRADING_EXCHANGE = "NYSE"` (559) and the hardcoded reference ETF list (1769) are US-equity assumptions; harmless at this scope, debt for other asset classes |
| pure_compute | `_compute_series_columns` is one `compute_kernels` call over arrays (649-693) | Workers open read-only DB connections (983-1003), which is acceptable at the edge |

## Summary

1. Before `--new-run`, supersede and delete run a4f6ad40's 32,194 chunk 0 rows, or the append-only COPY fails on `feature_vectors_pkey`. Ignore the stored 53 h extrapolation; it is inflated by a one-off 317 s `compression_bound` (estimate 6 to 10 h at 4 workers).
2. Run `--through feature_complete` under a launcher that keeps timers quiesced and auto-resumes after a watchdog abort (a resume costs minutes). Raise workers to 8 mid-run once the thermal gate clears.
3. Spend engineering time during stage_1d on todos 669 and 671, which gate the first counted look. Land the SMC order-block edit before the pin only if it is bit-exact.
