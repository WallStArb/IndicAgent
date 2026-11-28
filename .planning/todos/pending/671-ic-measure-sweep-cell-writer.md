---
status: pending
objective: O1
priority: P1
filed: 2026-11-24
source: indicagent-3d family-order note, lead ruling 2026-11-24
---

# The sweep-cell writer: record each measured IC cell as a counted attempt through the S6 ledger

## What

E21 (methodology-change-ledger, adopted 2026-11-13) counts every measured level 1 cell (feature, timeframe, horizon) as one `research_run` evidence attempt in mode `real`, with its per-session pooled cross-sectional IC stored as the attempt's series in `research_run_series`, written only through S6. `services/ic_measure.py` writes only `feature_ic_scores` (pooled IC with a strided sample and a bootstrap interval; no per-session series), and `research_run_series` is written only by `src/intelligence/research/ledger.py` and its callers. Without this writer a sweep is an uncounted look and no IC pass may run (ledger 2026-11-24f).

## Remaining before the first counted 1d sweep (checklist, 2026-11-28, indicagent-b9)

This todo closes when item 12 is recorded here. Commands, with placeholders, are in the run section of `docs/research/draft-ledger-2026-11-27a-first-ic-sweep.md`.

Done, verified on main at 4b4e3c3a8:
- [x] Writer and recorder landed: build ed2b16c9b; review fixes d282e9ac7, 07368e980, 5f918ea8f, b1e684490 (f242515f7 records the rulings in this file); the 674 refusals in 639c244b1. All are in the successor run's pin (code key 487f4ab434).
- [x] `repro_frozen` bit-identical on the `ledger.py` change: run on 0b5af0466, which contains it.
- [x] Pilot gate (a): `session_rank_ic` agrees with `scipy.stats.spearmanr` to 1e-12 per session and feature (`tests/unit/measure/test_session_ic.py::test_matches_scipy_per_session_and_feature`, passing).
- [x] The todo 666 dividend decision is ledgered (2026-11-24e, corrected in 2026-11-24j). Todo 674 is closed.

Open, in order:
1. [x] Todo 690 landed: `scripts/ops/ic_sweep_launch.sh` (host gate, watchdog, one heavy job; recorder modes need the stage's timer hold and never release it) and per-block spec hashes and series digests in the dry-run report.
2. [x] Owner confirms draft 2026-11-25c (regime columns stay out of the sweep): confirmed 2026-11-28 in the lead's session; ledger entry appended.
3. [ ] Ledger line for the new write path (`record_sweep_block`), required by the landing constraint above and not yet written; draft text in the draft doc.
4. [ ] Todo 670: settings line, run, disclosure line, when the recorded universe is final (its own checklist).
5. [ ] `feature_complete` of the successor run.
6. [ ] Recorder dry run on 25 names, peak RSS recorded here (review ruling 2026-11-25); check its log for `ic_measure.bar_digests_absent`, because a dry run allows names without bar digests and the real run refuses them.
7. [ ] Pilot gate (b): two full dry runs on one pin, identical reports including the item 1 digests; the numbers fill the FILL fields of the draft (never before).
8. [ ] Owner confirms the filled 2026-11-27a entry; the lead appends it and the 670 disclosure line to the ledger.
9. [x] Lead ruling 2026-11-28 (indicagent-03): the recorder runs inside the stage's held window, before the IC measure. It reads no `ic_measure` output, and the bars must not move between the features and either reader; the spec's "after `ic_measure`" is a place in the chain, not a data dependency. So items 6, 7, 11 and 12 run before item 10, and the 690 launcher refuses a recorder mode once `ic_measure` has completed.
10. [ ] (after items 11 and 12, per item 9) IC measure memory: `RSS_CHECK=1 ic_measure_launch.sh` on 25 names (peak in `logs/family10_run_status.txt`), extrapolated to the full grid at width 16 (todo 471: about 15 GiB plus the interpreter), and APR `infra.run_guarded.mem_floor_gib.ic_measure` set from the larger of that projection and the stage_1d peak, with a `config_history` reason (40 today is migration 623's seed). Then `ic_measure_launch.sh`.
11. [ ] The recorder's volume pilot (`--horizons 1`, `--declared-n-looks` from the entry) through the 690 launcher, at the place item 9 rules. After it: rows equal the declared attempts, every completed row has one series, and `n_sessions`, `span_start` and `span_end` equal its series (the first real block is the only test of the `record_sweep_block` SQL, todo 656); rows and series bytes recorded here.
12. [ ] If the pilot's volume is as expected, a second declaration for horizons 2, 5 and 10 and the recorder's run.

Sequencing condition the lead holds: the sweep stays behind the prior-driven families (design note 2026-11-24), as the draft entry lists. A bad block is a new spec and a new charge, never an edit (ruling 2026-11-25; the entry text says so).

## Spec (design 2026-11-24, indicagent-94; implementer follows this)

Two parts, each with one owner, so single_writer holds.

1. Compute: a pure function in `src/intelligence/measure/` (beside `ic.py`), `session_rank_ic(features [S, N, F], target [S, N], valid) -> ic [S, F]`: for each session s, the Spearman rank correlation across names of each feature with the target, using only names where the target and that feature are finite (the E21 "finite values only"), NaN when fewer than `min_obs` names (reuse `MeasureParams.min_obs`) or a degenerate cross-section. Ranks are taken once per (session, feature) and once per (session, horizon); Spearman is the Pearson of the ranks, a single [N x F]ᵀ[N x H] product per session. Targets come from the kernel `panel.forward_returns` (executable, open to open; never a stored table), purged so every target window ends before `alpha.validation.oos_start` (E21 rule 4; the series stops at that bound). Pure arrays in, arrays out; no database. It does not change `pooled_rank_ic`, so `feature_ic_scores` and its recorded values stay bit-identical.
2. Record: one new method on `PostgresLedger` (S6, `ledger.py`), `record_sweep_block(request, identities, series_by_concept)`, in one transaction under `LEDGER_LOCK_KEY`: insert one `research_run` row per cell (kind `evidence`, mode `real`, `concept_id` the feature's concept row, shared `run_group` for the (timeframe, horizon) block, `spec_hash` the hash of the block's spec text that pins timeframe, horizon, target definition, panel snapshot hash, feature list hash and code commit) and, in the same transaction, move each to its terminal status with its `AttemptSeries` (`completed` with a series; a cell with no tested session is `failed` with no series, and stays charged under the existing `UNCHARGED_STATUSES` and resultless-failure rules). One transaction per block means a crash leaves no `started` orphan and a rerun of the same block is refused by `PRIOR_REAL_RUN_SQL` (E18's no-silent-repeat rule), never half-written. Blocks are the four horizons of the 1d tf (about 277 cells each); a block is computed fully (and cached outside the database) before its transaction opens.

The caller is a new oneshot step in the corpus chain, run after `ic_measure` and before any family reads a cell: `services/ic_sweep_recorder.py` (concept name `ic_sweep_recorder`, class `IcSweepRecorder`, a `BaseBatch` that computes through the pure function and writes only through the ledger). It does not write `feature_ic_scores`. The service registry gets its `_DAG_ORDER` and `_AGENT_ID_TO_UNIT` entries and an `alert.lag.*` key per the project rules.

Rules it must honour: E21 rules 1 to 6 as adopted; E17 per-session granularity (the series is the same kind of object as a book's D_s, on the common date calendar); E18 selection (the cells enter the StepM universe through `select_books.py`, which already reads `evidence` runs); `no_fill` (a missing feature value drops that name from that session, never a fill); `temporal_integrity` (features read by availability time, the target from the kernel); `determinism` (the block's series is a function of the snapshot hash, the code key and the spec hash). The ledger line declares `n_looks` (the batch's cell count) before each batch; 670 runs first and sets how large a batch may be.

Where `repro_frozen` applies: the new method edits `src/intelligence/research/ledger.py`, so `.venv/bin/python -m scripts.research.determinism.repro_frozen <scratch_dir> --logs /home/bg/dev/indicagent/logs` must report bit-identical, and the methodology ledger gets a line for the new write path (it adds no statistic and moves no recorded spec hash, as E21's adoption note already says). The pure function under `src/intelligence/measure/` is outside that gate but is imported by `services/ic_measure.py`: land it in a detached worktree off `origin/main` while no run that imports `ic_measure` is live (the corpus chain stops at `feature_complete` until this lands, ledger 2026-11-24f).

Tests: `session_rank_ic` against `scipy.stats.spearmanr` per session on a small random panel with NaN holes (exact to 1e-12), invariance to name order, NaN rule below `min_obs`, no read past `oos_start` (a planted target after the bound changes nothing); `record_sweep_block` against a test database: row count equals cell count, every row has a series, a second call with the same spec is refused with no new rows, a failed block leaves zero rows, the guard trigger still refuses a second series write, `n_sessions`, `span_start` and `span_end` headline columns equal the series; the unit test that no module other than `ledger.py` inserts into `research_run` or `research_run_series` keeps passing (extend its allow-list by nothing).

Cost (estimate): rows 1,108 `research_run` plus 1,108 series; a series is about 5,500 dates and values, about 12 bytes each in the arrays, so about 73 MB of series and a few MB of rows (E21's volume gate: measure row count and series bytes on one block before the full sweep, and record the measured numbers here). Compute: ranking dominates, 277 features x 5,500 sessions x about 3,000 names, roughly 20 to 40 minutes at 4 workers and well under the memory of `ic_measure` at width 16 when run in session chunks (todo 667's time-chunk pattern, bit-identical by construction since sessions are independent); measure on one block first.

Failure modes: stored `feature_vectors` values for warmup or path-dependent columns (`ic_measure` has no such gate, so the recorder applies `refuse_path_dependent` and `refuse_builder_path_dependent` itself and reports the dropped columns as `excluded_inadmissible`); a regime column (left out and disclosed in the same list, because `refuse_regime_columns` needs the covering batches a sweep does not read); the sign problem (below); a feature whose concept row is missing; two sweeps writing the same block at once (the advisory lock and the spec-hash refusal); the target definition drifting between `ic_measure` and the recorder (both call `panel.forward_returns` with the same horizon list from APR `alpha.ic_measure.horizons`); the todo 666 decision (price-only targets skip dividends) must be ledgered before the first sweep, and the recorder inherits it.

Gates: tests by exit code, `repro_frozen` bit-identical, ruff, black, glossary, `/simplify`, `/review`, and an independent review before the first batch. Blocks nothing else; blocked by nothing but the lead's answers below.

## Decisions (methodology-change-ledger 2026-11-24i, `docs/plans/methodology-change-ledger.md:1800`)

1. Concept identity: a cell's `concept_id` is the feature's own concept row (E21 rule 3 as written). `feature` is added to `_RESEARCH_DOMAINS` in `ledger.py` (one token, under `repro_frozen` bit-identical). No research-domain member rows are minted for features.
2. Sign: every cell is recorded as two attempts, the long (the measured per-session IC) and the mirrored short (its negation), each tested one-sided positive by the shipped StepM. No sign is fitted or chosen from data. `n_looks` counts both attempts. The spec above changes accordingly: a full 1d level 1 sweep records about 2,216 `research_run` rows (1,108 cells x 2) and about 146 MB of series; `spec_text` pins the direction as a coordinate so the two attempts of a cell have different spec hashes; one block per (timeframe, horizon, direction), each in one transaction; `record_sweep_block` takes the long series and derives the short by negation inside the same transaction. The cost is a critical t about 5 percent higher than one sign per cell (3.92 to 4.12 at cell correlation 0; 3.08 to 3.34 at 0.7).
3. StepM stays as shipped for cells (no flat-top kernel; `block_mean` exceeds the longest horizon).

## Landing constraint (lead, 2026-11-24)

The `ledger.py` edit (and the new method) lands only while no ledger import and no `ic_measure` import is live, and never beside a counted run: a live run imports `src/intelligence/research/` and its `code_content_key` would change. Land it in a detached worktree off `origin/main`, with `repro_frozen` bit-identical and the methodology line already written (2026-11-24i covers the rulings; the write path itself still needs its own line).

## Build status 2026-11-24 (indicagent-94)

Superseded 2026-11-28: the build landed on main in ed2b16c9b with review fixes d282e9ac7, 07368e980, 5f918ea8f and b1e684490 (rulings recorded in f242515f7), with the 674 refusals in 639c244b1, and is in the pin of run dcb7caa4 and its successor (code key 487f4ab434). `repro_frozen` is bit-identical on 0b5af0466, which contains it (2026-11-28, indicagent-b9). The cell lookup is domain-qualified (`_FEATURE_DOMAINS`) instead of widening `_RESEARCH_DOMAINS`, because `ctf_momentum` is both a family and a feature. Migration 618 adds `alpha.ic_sweep.min_names_per_session`. No integration test of the `record_sweep_block` SQL exists (todo 656); the first real block is its test. 670 timing measured: about 81 microseconds per bootstrap draw, about 6 to 8 minutes per StepM run.

## Draft of the cell-list ledger line

Superseded by `docs/research/draft-ledger-2026-11-27a-first-ic-sweep.md`, which carries the entry text, the owner's questions and the exact run commands; the earlier draft is in git history (269d63c44).

## Review rulings applied 2026-11-25 (indicagent-8a, after indicagent-c7's review, lead rulings)

Landed on main in d282e9ac7, 07368e980, 5f918ea8f and b1e684490 on top of ed2b16c9b (the build); f242515f7 records these rulings here.

- Sweep rows are excluded from `backfill_attempt_series._RUNS_SQL` by `spec_path` (the one shared `SWEEP_SPEC_PATH_PREFIX` in `ledger.py`); a test binds it. Other `research_run.spec_blob` readers: `select_books` (counts sweep rows on purpose, now keyed on the path prefix, not a JSON sniff of the blob), `replication_subperiods` (reads only `member.*` concepts of one run group; a sweep row is a `feature` concept, so it is not reachable), the ledger's subset-refit parent read (book kinds only). No other reader resolves a blob through git.
- Service registry: `ic_measure` is in `_DAG_ORDER`, `_ONESHOT_UNITS` and the unit-file integrity test because it has a systemd unit (`indicagent-ic-measure.service`) and runs in the pipeline. The sweep recorder has no unit: it runs by hand from a detached worktree at a pushed commit, once per declared batch. The integrity test rejects a registry entry with no unit file, so the recorder is exempt from `_DAG_ORDER` and `_AGENT_ID_TO_UNIT` for that reason, and emits `job_completed_total{job="ic-sweep-recorder"}` like any oneshot. If it ever gets a timer, it is registered then.
- A real run refuses a dirty tree, a HEAD that moved during the measurement, and a HEAD that is not an ancestor of `origin/main` (`provenance.require_published`). Run it only from a detached worktree.
- Ledger line additions (append to the draft above before the first real run): unmeasured cells (no tested session at the horizon) record nothing and add nothing to `n_looks`; a column without a `feature` concept row is excluded and listed. The dry run prints `batch_attempts` (the n_looks to declare), `declared_n_looks`, `excluded_no_concept` and `unmeasured` by horizon.
- Volume pilot gate: `--horizons 1` runs only after (a) the `session_rank_ic` versus `scipy.stats.spearmanr` agreement test passes and (b) two dry runs on one pin give identical reports. Ledger line: a bad block means a new spec and a new charge, never an edit.
- Precondition before any real run: never beside a counted run; measure the 25-name dry-run RSS first (`--symbols` on 25 names, peak RSS from `/usr/bin/time -v`) and record it here. Session chunking (todo 667) is a follow-up if the full universe does not fit, not a blocker.
- Observability: `ic_sweep_recorder.measure` and `ic_sweep_recorder.record_block` spans, counters `ic_sweep_blocks_recorded_total` and `ic_sweep_cells_recorded_total` by tf, horizon and direction.
