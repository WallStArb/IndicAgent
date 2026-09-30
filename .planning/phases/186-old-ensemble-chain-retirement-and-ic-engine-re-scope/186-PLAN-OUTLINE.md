# Phase 186 plan outline

Source: 186-CONTEXT.md (D-01..D-38, R-01..R-13; R-xx overrides D-xx), 186-RESEARCH.md "Recommended
plan decomposition" (adapted: the truncated-todo restore is already done in b45c0d84d; todo 445 runs
now per R-08; the determinism and helper promotions move ahead of every deletion so no deletion
leaves a live importer broken; `scripts/analysis/` is deleted before the old-chain services so its
scripts never sit on dead imports).

Rules for every plan: work in a git worktree with `.env` symlinked and the main venv on PATH
(R-11); never edit `src/intelligence/research/` (D-02); git history is the archive, no `archive/`
copies (D-13); every deletion or drop starts with a repo-wide grep recorded in the summary (D-08);
every migration is committed in the same commit as it is applied; check
`ls production/migrations | sort -V | tail` immediately before numbering a migration (phase 185 and
parallel plans in the same wave also add migrations). Plans marked "D-01 gate" start with a task
that runs `ps aux` for ic_engine, backfill_feature_factory, regime_writer and any rebuild process,
and stops with a clear message if one is live or resumable.

| Plan ID | Objective | Wave | Depends On | Requirements |
|---|---|---|---|---|
| 186-01 | Summary card schema, card-lint test with drop-table coverage, old-chain process and dead-cache cards | 1 | - | D-04, D-05, D-06 |
| 186-02 | The 18 research-ledger verdict cards | 2 | 186-01 | D-05, D-06 |
| 186-03 | Promote `repro_frozen` as the `determinism` tool with a remapping unpickler | 1 | - | D-11, R-05, D-02, R-11 |
| 186-04 | Promote reusable `scripts/analysis/` helpers and the compute-eligibility audit | 1 | - | D-12, R-05, D-02 |
| 186-05 | Database hygiene: duplicate index drop, primary-key inventory, settings baseline and compose drift diagnosis | 1 | - | D-36, D-37, D-38, R-12, D-16, D-08 |
| 186-06 | COPY-based bulk-load primitive with provenance batch records (todos 301, 343, 352) | 1 | - | D-24, D-16, D-01, R-11 |
| 186-07 | Todo 445: 5m-over-15m incremental IC as a counted in-sample script; record the timeframe decision | 1 | - | D-33, R-08, D-18, D-02 |
| 186-08 | Kernel registry contract, golden float32 parity fixture, causality probe | 1 | - | D-25, D-26, D-27, R-11 |
| 186-09 | Feature lifecycle shrink to data-quality checks; `feature_registry` residue cleanup | 1 | - | D-30, R-03, D-31, R-02, D-01 |
| 186-10 | Fresh IC jobs as pure functions: proposer, term structure, monitoring, kernel targets on S0 panels | 1 | - | D-17, D-18, D-19, D-02 |
| 186-11 | ctx-writer retirement: stop and disable unit, delete module, drop ctx tables | 2 | 186-01 | R-01, D-07, D-08, D-14 |
| 186-12 | feature_factory split part 1: price dynamics, volume and flow, calendar, macro kernels | 2 | 186-08 | D-25, D-26, D-01, R-11 |
| 186-17 | Postgres `shared_buffers` and `work_mem` tuning with restart (operator gate) | 2 | 186-05 | D-38, R-12 |
| 186-13 | Regime as a walk-forward-only registry kernel; verify todo 248 state; todos 290, 291 | 3 | 186-12 | D-29, R-10, D-01 |
| 186-14 | Fresh IC writer: new feature_ic_scores_v2 table with one clock, bulk-load writes, content-digest revision detection, per-kernel code key | 3 | 186-06, 186-10, 186-11 | D-20, D-23, D-24, D-17, D-01 |
| 186-15 | feature_factory split part 2: SMC, VP/SR, injected cross-asset/factor/CTF kernels; pipeline imports the registry | 4 | 186-12, 186-13 | D-25, D-28, D-01 |
| 186-16 | Delete `scripts/analysis/` except the sleeve `config.py` import closure | 3 | 186-01, 186-02, 186-03, 186-04 | D-12, D-11, D-03, D-08, D-13 |
| 186-18 | Regime bundle todos 286, 289, 292, 341, 420 | 4 | 186-13 | D-29, D-01 |
| 186-19 | Old-chain code deletion part 1: services, ensemble submodules, spread tracker, gate_math, tests, auditor entries | 4 | 186-03, 186-09, 186-11, 186-14, 186-16 | D-09, R-04, D-07, D-08, D-13, D-01 |
| 186-20 | Parity harness replaying stored cell masks plus the writer-path parity cell; the legacy table stays untouched | 4 | 186-14 | D-21, R-06, D-15 |
| 186-29 | Delete the rest of `scripts/analysis/sleeve_walk_forward/` (gated on research-lane release) | 4 | 186-16 | D-03, D-11, D-02 |
| 186-21 | Old-chain deletion part 2: ops scripts, orchestrator steps, manifest verifier names, APR keys | 5 | 186-19 | D-10, D-09, D-08 |
| 186-24 | New `feature_vectors` table schema: DDL, chunk interval, dropped columns verified by count | 5 | 186-15, 186-18 | D-34, D-37, D-16 |
| 186-22 | Old-chain table drops after the card check | 6 | 186-02, 186-09, 186-21 | D-14, D-06, R-03, R-01, D-07, D-16, D-08 |
| 186-25 | Batch feature path as the resumable rebuild writer (units, bulk load, todo 339, regime in the same pass) | 6 | 186-06, 186-15, 186-18, 186-24 | D-28, D-32a, R-10, D-24, D-01 |
| 186-23 | One-change deletion of old ic_engine, `forward_return_writer`, `forward_returns`, lookahead keys (gated on 185 D-14) | 7 | 186-16, 186-20, 186-21, 186-22 | D-22, D-01, D-08 |
| 186-26 | Rebuild: precondition checker, pilot chunk, disk guard, launch the full resumable run (gated) | 8 | 186-07, 186-22, 186-23, 186-25 | D-32, D-32a, R-09, D-33, R-13 |
| 186-27 | Rebuild close-out: sampled drift report, name swap, drop the old table | 9 | 186-26 | D-34, D-06, D-16 |
| 186-28 | Fresh ic_engine on rebuilt features writes feature_ic_scores_v2; legacy feature_ic_scores dropped whole | 10 | 186-27 | D-35, R-07, D-19, D-16 |

Plan count: 29. Rows are ordered by wave; plan IDs are stable identifiers, not execution order.

## Plan scopes

**186-01 Summary card schema and old-chain cards.** Creates `docs/research/summary-cards/` (one
markdown file per card, YAML front matter with the 10.2 fields; schema from RESEARCH "Summary card
sources", Claude's discretion on detail), a README for the schema, and
`tests/unit/test_summary_cards.py` (required keys and types, `reproducible: false`, 40-hex
`recipe_commit` that exists in git, every cited path exists at that commit or HEAD, and a
`DROP_TABLES` constant fully covered by the union of card `tables`). `DROP_TABLES` = the D-14 list
plus `ctx_events`, `ctx_snapshots`, `construction_spreads`, `alpha_strategy_scores`,
`forward_returns`, the old `feature_vectors` and the legacy `feature_ic_scores`. Writes the
non-ledger cards: phase 142A ensemble
IC (EIC-04/05), phase 142B frames and FRAME-04, phase 148 SCORE-01..03 (`alpha_strategy_scores`),
gate166 recalibration, `gate1_signal` and the unnamed 2026-07-23 look, `ctf_momentum` decile
long-short gates 1-2 and the ctf_join_v2 re-verification (records the decile spec for the spread
tracker, covers `construction_spreads`), EM-CAL emission threshold, the ensemble champion
(`ensemble_weights` run_2025122405150000), and one `dead_cache` card each for `context_features`,
`feature_ic_scores_history`, the ctx tables, `forward_returns`, the old `feature_vectors` and the
legacy `feature_ic_scores`.
Numbers are copied from existing tables, reports and `.planning/gate_look_log.jsonl`, never
re-scored (D-05). Must not touch code, tables or the ledger rows owned by 186-02. No gate.

**186-02 Ledger verdict cards.** Writes the 18 cards for the verdicts in
`docs/research/construction-verdict-ledger.md` section 4 (including phase 148
`alpha_score_directional` and phase 179, which cross-link the 186-01 process cards), citing the
ledger rows' docs, pre-registrations and concept_registry migrations 328-335 for recipe metadata.
Recipe script paths point at `scripts/analysis/` files pinned by commit, so this lands before
186-16. Touches only `docs/research/summary-cards/` and, if needed, adds a card pointer column to
the ledger (read-only otherwise). Card-lint test must pass on the full set. No gate.

**186-03 Determinism tool.** Creates `scripts/research/determinism/` (outside the research package,
D-02): `config.py` (HarnessConfig byte-identical), `results.py`, `sessions.py`, `signals.py`,
`snapshot_io.py` (only `verify_snapshot`/`load_snapshot`, no DB, ic_engine, ensemble_trainer or
cross_sectional_regime_model imports), `repro_frozen.py` with the s2sig stage inline and a
`pickle.Unpickler` whose `find_class` remaps only `scripts.analysis.sleeve_walk_forward.evaluate`
to `src.intelligence.research.evaluate` (R-05). Tests under `tests/unit/research_tools/` load a
real frozen S3 pickle from `logs/phase179` or `logs/phase181` (skip with a reason if absent) and a
fixture pickle carrying the old class path. The task runs the promoted tool on the phase 181 frozen
book and records a bit-identical result. Must not edit or delete anything under
`scripts/analysis/sleeve_walk_forward/` and must not switch the research tests' HarnessConfig
imports (D-03). No gate beyond the frozen artifacts being present.

**186-04 Helper promotion.** Copies `scripts/analysis/instrument_compute_eligibility_audit.py` to
`scripts/infrastructure/` and repoints `universe_expansion_promote_compute_eligible.py`, the
onboarding SOP and `tests/unit/scripts/test_compute_ready_predicate_apr.py`; promotes
`_date_panel.py`, the cost-band helpers (`personal_cost_hurdle*.py`) and only
`fetch_training_matrix` from `_nonlinear_interaction_combiner_shared.py` into `scripts/research/`
(module names are Claude's discretion; no `stratum_fit` or ensemble imports come along) and moves
their tests. Originals stay in place until 186-16 deletes the directory. Must not touch
`src/intelligence/research/` or the sleeve directory. No gate.

**186-05 Database hygiene.** Drops `market_regimes_regime_group_tf_ts` with `DROP INDEX
CONCURRENTLY` after an `EXPLAIN` of ic_engine's regime-timestamp prefetch shows the PK is used
(D-36; the `construction_spreads` duplicate is moot because 186-22 drops the table, record that).
Writes the D-37 inventory for the 11 tables without a PK: disposition per table (dropped by
186-11/186-22, v2.x empty tables dropped here after the D-08 grep, `dlq_events`/`integrity_monitor`
kept with their unique indexes recorded, `market_data_ohlcv`'s unique index over NOT NULL columns
recorded as satisfying D-37; test assumption A1 on a scratch hypertable before relying on it).
Takes the D-38 baseline under the performance-investigation SOP (buffer hit, temp spills,
`pg_stat_statements` top spills, `iostat -x 1`) and finds why the running `work_mem` (8 MB) differs
from `production/docker-compose.yml` (64 MB) (R-12). Must not change Postgres settings or restart
anything (that is 186-17). No gate beyond confirming no batch job holds `market_regimes`.

**186-06 Bulk-load primitive.** Adds to `services/_batch_utils.py` one `bulk_load()` primitive: COPY
in chunk (time) order into rowstore chunks, `compress_chunk()` per completed chunk (never
direct-compress COPY on a table with a PK), float32 clamp via `col_types`, refusal while a
compression policy job covers the target range, and a provenance batch record (writer, target,
per-kernel code key, APR snapshot hash and JSON, input content digest, symbol set, tf, range, row
count, status) whose unique key is the idempotency key, so a rerun with the same key is a no-op.
One migration creates the provenance table (name is Claude's discretion, e.g. `lineage_batch`) and
seeds `infra.bulk_load.*` APR keys. Unit tests with fakes plus `tests/integration/test_bulk_load.py`.
Reads the original bodies of todos 301, 343, 352 and closes them. Must not convert any existing
writer (consumers are 186-14 and 186-25). D-01 gate (`_batch_utils` is in ic_engine's import
closure).

**186-07 Todo 445.** A committed script in `scripts/research/` that measures whether 5m features add
incremental IC over 15m at matched horizons, in-sample only (`bar_ts < oos_start`), with targets
from `panel.forward_returns` on an S0 15m panel (read-only use of the research package), aligned at
the 15m close (the 5m row whose bar ends at the 15m close), excluding regime/HMM columns and todo
421's partial columns, reading per feature block and symbol chunk (never a wide frame). It records
itself as a counted look (the research runner's record if writable without editing the research
package, else `.planning/gate_look_log.jsonl`) and writes the decision (timeframe set and name set,
including whether 5m features stay at 233 names) into todo 445, the ledger section 5 and STATE.md.
Must not start IBKR jobs or touch `feature_vectors`' schema. No external gate (R-08).

**186-08 Kernel registry contract.** Creates `src/intelligence/features/contract/registry.py` (Kernel: name,
origin, declared inputs, declared memory in bars, dtype, pure `compute(inputs up to t)`), with
origin modules discovered automatically under `src/intelligence/features/kernels/` so later plans
add modules without editing the registry; declared memory is the single source for feature-member
memory (D-26). Creates `src/intelligence/features/contract/causality_probe.py` (truncate inputs at
availability, recompute, compare exactly or within 1 ulp in float32; cross-sectional features
truncate every symbol) with tests that fail an injected lookahead kernel. Captures a golden float32
output fixture of the current `compute_batch` on fixture bars and a stated sample of real
(symbol, tf) histories, used by 186-12 and 186-15 as the byte-identical parity check
(`tests/unit/intelligence/test_kernel_registry_parity.py`). Must not edit `feature_factory.py`.
Does not add the nightly `temporal_integrity` job (deferred). No gate.

**186-09 Lifecycle shrink.** Rewrites `services/feature_lifecycle.py` to data-quality checks only:
computed (non-NULL share), valid (finite, in dtype range), coverage above an APR floor (one
statistic shared with todo 421's coverage check and todo 435's S0 floor; seeded by migration);
removes the IC-gate paths, the `ensemble_weights` join and the `alpha.ensemble.*`/`alpha.decay.*`
reads (R-03). Rewrites `tests/unit/test_feature_lifecycle.py`. D-31 cleanup (R-02): delete
`scripts/ops/alpha/ops_concept_feature_migration_verify.py`, fix the stale comment in
`schemas.py`, mark phase 170 plans 07-08 superseded, correct ROADMAP/design 14.3 references. Must
not delete APR keys (186-21) or drop tables. D-01 gate.

**186-10 Fresh IC pure jobs.** Creates a measurement module outside the research package (layout
Claude's discretion, e.g. `src/intelligence/measure/` with `proposer.py`, `term_structure.py`,
`monitoring.py`) as pure functions over `src/intelligence/statistics/ic_math.py`: pooled
cross-sectional IC per feature x tf x horizon, term structure across horizons, per-member IC over
time; regime-stratified IC only as disclosure for `regime_volatility`. Target loading builds S0
panels via `snapshot.build_panel`/`build_grid` in symbol chunks with `end_exclusive = oos_start`
and calls `panel.forward_returns` with the session index, so no target window reaches `oos_start`
(D-19 by construction) and intraday horizons stay in-session; cross-session intraday horizons are
refused, decay beyond a session is on the daily clock. Tests in `tests/unit/measure/` on synthetic
panels. Must not write to the database or edit `services/ic_engine.py`. No gate.

**186-11 ctx-writer retirement (autonomous: false, sudo).** `sudo systemctl disable --now
indicagent-ctx-writer`, remove `/etc/systemd/system/indicagent-ctx-writer.service`, daemon-reload;
delete `services/context_writer.py`, its test, `production/systemd` unit, `service_auditor`
`_DAG_ORDER`/`_AGENT_ID_TO_UNIT` entries, and the dead readers in
`src/persistence/repository/feature_repository.py` and `infrastructure_reset_pipeline_data.py` as
the grep dictates; drop `ctx_events` and `ctx_snapshots` by migration (the 186-01 dead-cache card
covers them). Must not touch `context_features` or its writer script (186-22). Gate: card lint
passes.

**186-12 feature_factory split part 1.** Moves the price dynamics, volume and flow, calendar and
macro origins out of `src/intelligence/feature_factory.py` into
`src/intelligence/features/kernels/{price,volume,calendar,macro}.py` registered in the 186-08
registry with declared inputs and memory; `feature_factory` delegates to them. Byte-identical
float32 parity against the 186-08 golden fixture plus the existing
`test_feature_factory_batch_parity.py`; any behavior change is a separate commit. Causality probe
runs on every moved kernel. Must not touch SMC, VP/SR, regime, or `backfill_feature_factory.py`.
D-01 gate.

**186-13 Regime kernel.** First task verifies todo 248's real state (`alpha.hmm.walk_forward.enabled`
true since 2026-08-12 per `config_history`, the Aug 12/15 runs) and corrects STATE.md and the memory
entry (R-10). Extracts the walk-forward HMM (trend and volatility families) from
`services/regime_writer.py` into `src/intelligence/features/kernels/regime.py` as a pure bars-only
kernel with declared memory, deletes the full-history path, and fixes todos 290 (per-worker memory,
per-cell verify query, vocabulary_drift double scan) and 291 (duplicated function pairs, 20-tuple
worker args, OTel asymmetry), reading their bodies from git per the restore commit. Must not run
regime_writer's UPDATE path or loosen the todo 426 guard. D-01 gate.

**186-14 Fresh IC writer.** One writer (e.g. `services/ic_measure.py`, registered in
`_DAG_ORDER`/`_AGENT_ID_TO_UNIT` with an `alert.lag.*` APR key) that runs the 186-10 jobs and writes
the new `feature_ic_scores_v2` table through `bulk_load()`. The migration creates
`feature_ic_scores_v2` with `regime_scope` in the PK from creation (todo 391) and one clock
(`training_window_end` = the latest target exit bar); the legacy table is never written. Revision
detection is a bar content digest per (symbol,
tf, range) replacing the `forward_returns.computed_at` watermark (absorbs todo 412); the code key is
per kernel, not ic_engine's all-imports key (D-23). Must not delete or edit the old
`services/ic_engine.py` (strangler). D-01 gate.

**186-15 feature_factory split part 2.** Moves SMC, VP/SR (swing, trend, fib, session levels) and the
features injected by `backfill_feature_factory._compute_symbol_tf` (cross-asset, factor betas, CTF,
cross-tf divergences) into kernel modules; `feature_vector_pipeline.py` imports the same registry
(D-28). Byte-identical float32 parity and causality probe as in 186-12; a registry test asserts
every D-25 origin is present. Must not change the batch writer's unit structure (186-25). D-01 gate.

**186-16 scripts/analysis deletion.** After cards (01, 02) and promotions (03, 04): deletes
`scripts/analysis/` except `sleeve_walk_forward/config.py`, its `__init__.py` and whatever
`config.py` imports (kept only because research-lane tests import HarnessConfig, D-03); deletes
tests importing deleted scripts (62-file set per RESEARCH, re-grepped), `tests/live/test_sleeve_walk_forward_snapshot.py`,
and stale allow-list entries in boundary tests; updates docs that operate deleted scripts. Must
not delete `scripts/research/`, `gate_math.py` or `stratum_fit.py` (186-19 owns them). Gate:
186-01/02 card lint green and 186-03 bit-identical result recorded.

**186-17 Postgres tuning (autonomous: false, restart).** Gate task: no batch job running (`ps aux`
plus `pg_stat_activity`), no IBKR backfill writing; stop otherwise. Applies the 186-05 findings:
`shared_buffers` about 25% of RAM, `work_mem` sized from the spill evidence, `shm_size` raised if
assumption A2 holds, fixes the compose drift cause (R-12), `docker compose up -d` the timescaledb
service only, records before/after measurements under the SOP. Touches only
`production/docker-compose.yml` and docs.

**186-18 Regime bundle.** Fixes todos 286 (vol_of_vol nested warmup `valid_start`), 289 (1d
`refit_every_bars` re-validated against 250-bar windows), 292 (`hmm_vol_churn` rows), 341 (BIL,
ETHA, IBIT NULL regime; nightly auditor failures), 420 (`market_regimes` weekend orphans, atomic
replace per (group, tf)) on the kernel and `cross_sectional_regime_model`/`market_regimes` path, and
closes them. Must not run a corpus regime recompute into the current `feature_vectors`. D-01 gate.

**186-19 Old-chain code deletion part 1.** Deletes `ensemble_trainer`, `ensemble_ic_engine`,
`alpha_frame_writer`, `counterfactual_tracker`, `alpha_publisher`, `alpha_scorer`,
`generate_ic_discovery_report`, `cross_sectional_spread_tracker` (R1 covers the construction role;
the decile spec lives in the 186-01 card), `gate_math.py`, the old-chain `ensemble` modules
(`alpha_score`, `feature_selector`, `stratum_fit`) after rewriting `ensemble/__init__.py` to drop
eager imports while keeping `covariance`, `shrinkage`, `weights` (R-04); their tests, unit files in
`production/systemd`, `service_auditor` entries, metrics and `stream_keys` docstrings, boundary
allow-lists. `pytest --co` and the full suite green. Must not delete APR keys, ops scripts or
orchestrator steps (186-21), or tables. D-01 gate.

**186-20 Parity and purge.** A test-scoped parity harness (stated sample before running, e.g. 30
features x 4 tf x in-session horizons x 3 regime labels) that rebuilds each stored POOLED cell's
observation set (label bars, peer symbols, (bar_ts, symbol) order, stride) and computes point IC
with the 186-10 IC function twice: table targets must reproduce stored `ic_value` to float
tolerance; kernel targets' differences are attributed to gap rows and end-of-window NaNs with
counts; 1h horizons 20/60 excluded with a count (R-06). Commits the parity report, including the
writer-path parity cell section (one frozen stored pooled cell recomputed through ic_measure's
production assembly and compared with the harness replay; a difference beyond tolerance stops the
phase before 186-23 can run). Nothing is deleted in this plan: the legacy `feature_ic_scores` table
stays untouched (D-15) until 186-28 drops it whole; D-19, R-07 and D-16 are discharged by that drop.
No gate beyond no ic_engine run.

**186-29 Sleeve directory removal (gated).** Gate task: the research lane has released (STATE.md
lane table) or the five research tests no longer import `scripts.analysis.sleeve_walk_forward`;
stop with a message otherwise. If released, switch those imports to
`scripts/research/determinism/config.py` (186-03) and delete the remaining sleeve files; confirm the
determinism tool still loads the frozen pickles. Touches nothing else.

**186-21 Old-chain deletion part 2.** Deletes `scripts/ops/alpha/ops_ensemble_*`,
`ops_emission_threshold_sweep.py`, `ops_ensemble_ic_gate.py`, `ops_ic_shrinkage.py`,
`scripts/ops/corpus/ops_oos_gate1_signal_eval.py`; removes orchestrator steps after `ic_engine` and
`feature_lifecycle` in `ops_pipeline_monitor.sh` and `ops_corpus_pipeline_run.sh`; removes dead
step names from `corpus_manifest_verifier.py`; one migration deletes the old-chain APR keys per key
after grep, keeping `alpha.ensemble.mv_condition_max` (read by `tag_calibrator`),
`alpha.ic.shrinkage_k` and `alpha.ic.canary_rng_seed`. Must not touch `alpha.ic.lookahead.*`
(186-23) or tables.

**186-24 New feature_vectors schema.** One migration creates the new table (name Claude's
discretion, swapped in 186-27): PK (symbol, tf, bar_ts), compression segmentby symbol/tf orderby
bar_ts, a longer chunk interval chosen from the warmup overhead analysis (e.g. 1 year), compression
policy disabled during the build, provenance linked by batch record (no per-row provenance column).
Drops columns only after a sampled count confirms them never computed (`momentum_rank_z`,
`volume_rank_z`, `volatility_rank_z` per todo 421, the Asian session pair, `regime_rolling`) and
exact duplicates (`days_to_month_end`, todo 115); column set derived from the registry. Must not
write rows or touch the old table.

**186-22 Chain drops.** Gate: card lint green over the full set, D-08 grep clean for each table,
`pg_stat_activity` shows no session reading them. Migrations drop `ensemble_weights`,
`ensemble_alpha`, `alpha_ensemble_ic`, `alpha_events`, `alpha_frames`, `alpha_strategy_scores`,
`context_features` (with `infrastructure_context_features_writer.py`, closing todo 355),
`feature_ic_scores_history` and `construction_spreads`, committed with apply; records freed disk
(about 61 GB target with 186-23). Must not drop `forward_returns` or `feature_vectors`.

**186-25 Rebuild writer.** Turns `services/backfill_feature_factory.py` and
`src/intelligence/features/feature_vector_persistence.py` into the single rebuild writer on the
registry and `bulk_load()`: units are (symbol chunk, tf, time range) keyed by the provenance record
so kill-and-resume skips completed units; warmup from declared memory; regime computed as a kernel
in the same pass (no UPDATE, R-10); workers return bounded payloads (todo 339); orphan-worker and
leftover-backend cleanup documented per CLAUDE.md; writes only to the 186-24 table. Tests for resume
and bounded payloads. Adds the precondition checker module with unit tests
(`tests/unit/test_rebuild_preconditions.py`) that 186-26 runs. Must not run the rebuild. D-01 gate.

**186-23 One-change deletion (gated).** Gate task: the 186-20 parity report is committed and phase
185 D-14 has moved `forward_return_writer`'s bar flags to bar flags (check 185 summaries and code);
stop otherwise. In one change: delete `services/ic_engine.py` and its tests and boundary tests,
`services/forward_return_writer.py` and its unit, every script reading `forward_returns`, the
`alpha.ic.lookahead.*` keys, drop `forward_returns` by migration; the orchestrator's ic_engine step
points at the 186-14 writer; update the CLAUDE.md executable-returns rule to point at the kernel.
D-01 gate.

**186-26 Rebuild run (gated).** First task runs the 186-25 precondition checker and stops on any
failure: coverage query per (symbol, tf) against the expected span for all 931
`compute_eligible_1d` names with `ohlcv_empty_history` spans listed (todo 449's 5m backfill complete,
read-only, R-13), phase 185 D2b derived 15m/1h grid landed and tested, todo 445 decision recorded
(186-07) setting the timeframe and name set, 186-06/15/18/25 landed, drops landed (186-22, 186-23).
Runs the todo 420 orphan-delete rerun (when 186-18 deferred it with J > 0) before the launch.
Then a measured pilot chunk: wall-clock, compressed size, largest uncompressed chunk working set,
DB load against the other lanes; the R-09 disk guard (projected compressed size plus largest
chunk working set plus stated margin against free disk) must pass; state the expected wall-clock.
Then launch the full resumable run in the background with its log path recorded, and test one
kill-and-resume. Must not edit any module the rebuild imports while it is live or resumable.

**186-27 Rebuild close-out.** Gate: every unit of the run has a completed provenance record. Sampled
drift report new vs old table (stated sample, per-column exact/ulp/NaN diffs, explained), rename
swap, drop the old `feature_vectors` (card from 186-01), `VACUUM` where the rule applies, re-enable
the compression policy, record disk. Closes todos 411 and 426 step 2.

**186-28 Fresh IC on rebuilt features.** Runs the 186-14 writer on the rebuilt table into
`feature_ic_scores_v2`, verifies no row has a target end at or after `oos_start`, records counts,
and drops the legacy `feature_ic_scores` whole (R-07, D-19) once the 186-01 card covers it. Gate:
186-27 landed.

## Resume notes (2026-09-27, orchestrator)

All 29 plans are written and committed (01-19 in the first chunked run; 20-29 resumed 2026-09-27,
one planner at a time after parallel planners hit the session limit three times). The names below
stay binding for execution. Next step: the plan checker over all 29.

Names fixed by written plans, which later plans must use:
- Provenance table `provenance_batch` (186-06, not `lineage_batch`); API `bulk_load()`, `BulkLoadSpec`, `completed_provenance_batch()`, `bulk_load(replace_where=)`, `kernel_code_key()`, `bar_content_digests()` in `services/_batch_utils.py`, synchronous psycopg (async callers use `asyncio.to_thread`).
- Determinism tool `scripts/research/determinism/` (186-03); promoted helpers `scripts/research/date_panel.py`, `cost_hurdle.py`, `feature_matrix.py`, `scripts/infrastructure/instrument_compute_eligibility_audit.py` (186-04).
- Kernel registry `src/intelligence/features/contract/registry.py`, `kernels/` (auto-discovered `KERNELS` tuples), `path_dependent`, `memory_atol`, `acausal_control`, `compute_kernels()`, `UNOWNED_COLUMNS` in `registry.py` (186-08, 186-12, 186-15). 186-15 depends on 186-13 (same files).
- Fresh IC table `feature_ic_scores_v2` (186-14): `regime_scope` in the PK from creation, `training_window_end` = the latest target exit bar (one clock); the legacy `feature_ic_scores` table is untouched until 186-28 drops it whole. Fresh IC package `src/intelligence/measure/`; writer `services/ic_measure.py`, oneshot `indicagent-ic-measure` (186-10, 186-14).
- 186-18 task 3 defers the market_regimes orphan-delete rerun to 186-26 task 1 (after 186-20's parity is on main, before the rebuild launch).
- 186-19 leaves for 186-21: ops scripts importing `services.ensemble_ic_engine` (`ops_ensemble_ablation.py`, `ops_oos_gate1_signal_eval.py`), orchestrator steps 7-8, and APR keys left by 186-09 and 186-16. Delete APR keys per key after a grep, never by LIKE (live readers exist, e.g. `alpha.ensemble.mv_condition_max`, `alpha.ic.shrinkage_k`, `alpha.ic.canary_rng_seed`).
- Todos filed during planning: 449 (5m/15m/1h backfill, running in another session; the rebuild gates on 5m only), 450 (P0 intraday macro lookahead, fixed in 186-12 task 3), 451 (suspected HMM segment-gate lookahead, 186-13 task 2).
- Migration numbers are chosen by the executor at run time (`NNN` in plans).

## OUTLINE COMPLETE
