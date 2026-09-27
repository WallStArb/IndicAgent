# Phase 186: Old ensemble chain retirement and ic_engine re-scope - Context

**Gathered:** 2026-09-26
**Status:** Ready for planning
**Source:** PRD express path (`docs/plans/2026-09-26-unified-research-to-production-design.md`, adopted 2026-09-26 with E18, amended the same day with UD-25; track A plus refactor map items 1-6; sections 11, 14.1-14.7, 12.1)

<domain>
## Phase boundary

One route from research to capital. The phase deletes the old ensemble chain and its tables
after writing summary cards for every old verdict and dead process. It shrinks ic_engine to three
jobs (proposer, IC term structure, member monitoring) computed on the one target kernel
(`panel.forward_returns`), then deletes `forward_return_writer` and the `forward_returns` table.
It replaces the in-place `feature_vectors` refresh chain with a rebuilt append-only table with
provenance, and lands refactor map items 1-6 plus the database hygiene findings assigned to
phase 186.

Rule for every data decision: raw data is permanent, derived data is cache, conclusions are
records (design 14.2).

Two parts of the phase wait on work outside it and must be planned as gated plans that refuse to
run until their precondition holds: the `feature_vectors` rebuild waits on phase 185's derived
15m and 1h grid (D2b, todo 446) and on todo 445's 5m decision. Everything else can start now.

Alpha work runs in parallel (ALPHA FIRST). Nothing in this phase may block or edit the research
lane's code.

</domain>

<decisions>
## Implementation decisions

### Preconditions and lane boundaries
- **D-01:** No edits to any module ic_engine imports while an ic_engine corpus run is live or resumable (CLAUDE.md). Checked 2026-09-26: no ic_engine, backfill or regime_writer process running; all old-chain units inactive. Each plan that edits an ic_engine import re-checks with `ps aux` first.
- **D-02:** `src/intelligence/research/` belongs to the phase 183 session until family 2's run finishes (STATE.md lane table). Phase 186 does not edit it. Where the design says "promote into the research package", phase 186 promotes into a module outside it (`scripts/research/` or a new `src/intelligence/tools/`-style module the planner picks), and research-package imports are switched by the research lane or in a plan explicitly gated on that lane's release.
- **D-03:** Research tests import `scripts.analysis.sleeve_walk_forward.config.HarnessConfig` (tests/unit/research/test_evaluate*.py, test_portfolio*.py). The sleeve directory cannot be deleted until those imports are moved; that move is a research-lane-owned change or waits for its release (D-02).

### Summary cards before any drop (design 14.2, 10.2 item 3)
- **D-04:** Summary cards are written as checked-in structured files (one per card, YAML front matter plus prose) under `docs/research/summary-cards/`, with the 10.2 fields: idea, recipe pointer (spec or pre-registration path, git commit), result numbers, known defects, spans looked at, why closed or reopened, `reproducible: false`. Phase 187 loads them into its clean UCR schema as `kind = 'legacy_verdict'` attempts. Rationale: `research_run`'s only writer is the S6 ledger (research lane), and the clean UCR schema is phase 187; files keep 186 unblocked and git is the record.
- **D-05:** About 20-25 cards: the 18 verdicts in `docs/research/construction-verdict-ledger.md` plus the old ensemble chain (phase 148 gates, gate166, the `ctf_momentum` gates, phase 179). Numbers are read from existing tables and reports before the drop, never re-scored.
- **D-06:** A card set is checked (every table to be dropped has at least one card citing what was learned from it, and a card-lint test validates front matter) before any drop migration is applied.

### Consumer checks (design 14.1)
- **D-07:** Before deleting: `services/context_writer.py` (unit `indicagent-ctx-writer.service`, the one active unit here) gets a consumer check of `context_features` readers; if no live reader, stop and disable the unit, then delete. `services/cross_sectional_spread_tracker.py` is deleted if phase 183's R1 covers its long-short primitives; otherwise record why it stays. Check whether `feature_lifecycle` reads `alpha_ensemble_ic` beyond the removed gates.
- **D-08:** Every deletion and drop starts with a repo-wide grep for the module/table name (src, services, scripts, tests, systemd units, Grafana dashboards, docs that operate it) and records the result in the plan summary.

### Code deletions (design 14.1, 14.6)
- **D-09:** Delete `services/ensemble_trainer.py`, `services/ensemble_ic_engine.py`, `services/alpha_frame_writer.py`, `services/counterfactual_tracker.py`, `services/alpha_publisher.py` (its input and output tables go; `BookTracker`/`BookPositionWriter` are new builds in phase 188, not a dependency), their systemd units, `_DAG_ORDER`/`_AGENT_ID_TO_UNIT` entries in `services/service_auditor.py`, their APR keys, and their tests.
- **D-10:** Delete old-chain ops scripts: `scripts/ops/alpha/ops_ensemble_*`, `ops_emission_threshold_sweep.py`, `ops_ensemble_ic_gate.py`, `scripts/ops/corpus/ops_oos_gate1_signal_eval.py`; orchestrator steps after `ic_engine` and `feature_lifecycle` in `ops_pipeline_monitor.sh` and `ops_corpus_pipeline_run.sh`.
- **D-11:** `scripts/analysis/sleeve_walk_forward/`: first promote `repro_frozen.py` and what it imports (todo 448 item 1, the seed of the `determinism` tool) outside the directory with its test; list every file importing the directory; delete only after D-03 is satisfied.
- **D-12:** `scripts/analysis/` (71 scripts, 26.8k lines) is deleted after summary cards exist and reusable helpers (`_date_panel.py`, cost-band helpers, `_nonlinear_interaction_combiner_shared.py`'s `fetch_training_matrix` pattern) are promoted per D-02. Tests importing deleted scripts are deleted with them; tests of promoted helpers move with the helper. `scripts/research/` stays.
- **D-13:** Git history is the archive. No `archive/` copies.

### Drops (design 14.2)
- **D-14:** Drop after cards: `ensemble_weights`, `ensemble_alpha`, `alpha_ensemble_ic`, `alpha_events`, `alpha_frames`, `context_features` (9.7 GB) and `feature_ic_scores_history` (38 GB). Each drop is a migration committed in the same commit as it is applied, after the consumer grep, never while another session's run reads the table.
- **D-15:** Keep forever: `market_data_ohlcv`, `dividend_events`, phase 185 raw observations, `.planning/gate_look_log.jsonl`. `feature_ic_scores` stays; old-grid rows (per-symbol x regime) are deleted with the ic_engine shrink, current pooled rows stay until the fresh engine writes rows on rebuilt features.
- **D-16:** Every operation on a compressed hypertable follows `docs/foundation/performance-investigation-sop.md`; any decompress/alter/recompress migration ends with a bare `VACUUM` (CI-enforced).

### Fresh ic_engine (design 11, 14.6 item 2, 14.7)
- **D-17:** Written fresh as three small pure jobs over `src/intelligence/statistics/ic_math.py` plus one writer: proposer (pooled cross-sectional IC per feature x timeframe x horizon), IC term structure (same cells across horizons), monitoring (per-member IC over time for frozen-book members). The per-symbol x regime grid is gone; regime-stratified IC survives as disclosure for `regime_volatility` only. Strangler: new engine beside the old one, parity, then the old one is deleted.
- **D-18:** Targets come only from `panel.forward_returns` (the research kernel) on an S0 panel, computed in symbol chunks (exact because columns are independent). Intraday horizons stay inside one session; decay beyond a session is measured on the daily clock. The fresh engine reads the kernel through its public API and does not edit the research package (D-02).
- **D-19:** IC rows whose target window ends at or after `alpha.validation.oos_start` are never written (todo 439's purge); existing rows crossing it are purged.
- **D-20:** The uniqueness key includes scope explicitly (todo 391). Writes go through the new COPY primitive (D-24).
- **D-21:** Parity: fresh engine pooled cells vs stored `feature_ic_scores` pooled rows on the same features, timeframes, horizons and window. The only allowed differences are the gap rows (a name not trading on a bar; the table's "N traded bars" horizon vs the kernel's fixed horizon), disclosed with counts. No old-engine recompute is needed for parity.
- **D-22:** After parity, one change deletes: the old `services/ic_engine.py`, `services/forward_return_writer.py` and its unit, the `forward_returns` table (14 GB), the fixed `alpha.ic.lookahead.*` APR keys, and every script reading the table. The CLAUDE.md executable-returns rule is updated in the same change to point at the kernel.
- **D-23:** Revision detection uses a bar content digest per (symbol, tf, range) (design 3.3), replacing the `forward_returns.computed_at` watermark (absorbs todo 412). The code key is per kernel, not ic_engine's all-imports `code_content_key`.

### Bulk-load primitive (14.6 item 3, 14.5)
- **D-24:** One primitive in `services/_batch_utils.py`: `COPY` in chunk (time) order, compress each chunk when complete, a provenance batch record (writer, per-kernel code key, APR snapshot, input content digest, symbol x tf x time range), and that record as the idempotency key (rerun with the same key is a no-op). No per-row provenance column on compressed hypertables. Every new writer in this phase uses it. Absorbs todos 301, 343, 352. Tunables are `infra.*` APR keys.

### Kernel registry and feature_factory split (14.6 item 1)
- **D-25:** `src/intelligence/feature_factory.py` (8,733 lines) splits into one module per feature origin (price dynamics, volume and flow, SMC, VP/SR, calendar, macro, regime) behind one kernel registry: declared inputs, declared memory, dtype, pure `compute(inputs up to t)`. Parity is byte-identical float32 on a feature sample before vs after; behavior changes are separate commits.
- **D-26:** Declared memory in the registry is the one source for feature-member memory (todo 448 item 2); `book_memory()` itself is phase 187.
- **D-27:** One causality probe over the pure entry point (truncate inputs at availability time, recompute, compare in float32 exactly or within 1 ulp; cross-sectional features truncate every symbol), tested on fixture panels (todo 448 item 3). The nightly `temporal_integrity` audit table and job are not in this phase; the research S3 guard adopts the probe in the research lane.
- **D-28:** The batch feature path (`services/backfill_feature_factory.py`, `feature_vector_persistence.py`) becomes the single rebuild writer on D-25 and D-24; the dormant `feature_vector_pipeline.py` only imports the same registry. Fix todo 339 (unbounded worker rows across IPC) on this path.

### regime_writer (14.6 item 5)
- **D-29:** Walk-forward is the only mode; the full-history path is deleted once todo 248's refit deploys. Todo 290 (memory and query) and 291 (duplication) fixed, bundled with 286, 292, 289, 341, 420. Lands before the rebuild consumes regime columns.

### Feature lifecycle (design 11, 14.6 item 6, 14.3)
- **D-30:** `services/feature_lifecycle.py` shrinks to data-quality checks: a feature is computed, valid, and above the coverage floor. Weak standalone IC never stops a feature being computed. The IC-gate paths go.
- **D-31:** Phase 170 plans 07-08 are rewritten as finishing the `feature_registry` retirement without the ensemble rehearsal (the `alpha_ensemble_ic` gate never clears).

### feature_vectors rebuild (14.2, 14.7) - gated plan
- **D-32:** Preconditions, checked by the plan before any work and refusing otherwise: bar backfill complete for the rebuild's names and timeframes (owner, 2026-09-26: the rebuild is multiday, so it runs once on full bar history, never on a partial backfill). The rebuild covers all 931 `compute_eligible_1d` names; 1d exists for all of them, but only 233 have intraday bars, so the 5m backfill of the other 698 (todo 449) must finish first; phase 185 D2b derived 15m and 1h grid landed and tested; todo 445 decision recorded; D-24, D-25, D-28, D-29 landed; todo 426's disk guard in place (space for about 4x the table at the chosen names against free disk). "Backfill complete" is a coverage query per (symbol, tf) against the expected history span, recorded in the plan, with any provider-empty spans (`ohlcv_empty_history`) listed, not assumed. "Complete" means what todo 449's backfill can fetch; phase 185 D3's venue-move recovery is not a precondition (185 D-19 stands: recovered history enters afterwards through content-digest keys and recomputes only affected ranges).
- **D-32a:** The rebuild is multiday, so it must be resumable. Work is split into (symbol chunk, tf, time range) units keyed by the D-24 provenance record, so a kill-and-resume skips completed units. Worker-orphan and leftover-backend cleanup follow the CLAUDE.md rules. No edits to modules the rebuild imports while it is live or resumable (the ic_engine import rule applied to the rebuild). Its DB load is measured against the other lanes (research runs, nightly backfill) before launch, and the plan states the expected wall-clock time from a measured pilot chunk.
- **D-33:** Timeframe set from todo 445: if 5m adds no incremental IC that survives costs, the rebuild covers 15m, 1h and 1d; raw 5m bars keep ingesting either way. Todo 445's test runs through the research runner in exploration mode (so it is counted) and can run now; phase 186 owns getting it run and recorded.
- **D-34:** New table written append-only in time order, each chunk compressed when complete, provenance from the first row, cleaner schema (drop never-computed columns such as todo 421's rank_z features and exact duplicates such as todo 115). Sampled drift report against the old table, then swap names, then drop the old table. Replaces todos 411 and 426 step 2. The HMM columns enter only after todo 248's refit.
- **D-35:** After the rebuild, the fresh ic_engine runs on the rebuilt features and replaces the current pooled `feature_ic_scores` rows.

### Database hygiene (14.5)
- **D-36:** Drop the duplicate non-PK index on `market_regimes` (same key as the PK, about 387-400 MB) and the duplicate on `construction_spreads`.
- **D-37:** Every surviving table gets a primary key; tables without one are dropped in the dead-table sweep (with consumer grep) or given one.
- **D-38:** `shared_buffers` (3 GB on a 29 GB host) and `work_mem` (8 MB) are measured under the performance-investigation SOP, then tuned (about 25% of RAM for `shared_buffers`; `work_mem` per batch session). The Postgres restart for `shared_buffers` happens only with no batch job running and is recorded with before/after measurements.

### Claude's discretion
- Plan and wave split, module names for promoted helpers (within D-02), card file schema details, the fresh engine's module layout, and the exact parity sample sizes (state them before running).

</decisions>

<canonical_refs>
## Canonical references

**Downstream agents MUST read these before planning or implementing.**

### Spec
- `docs/plans/2026-09-26-unified-research-to-production-design.md` - sections 3.2-3.3 (manifest, idempotency), 10.2 (summary cards), 11 (ic_engine), 12.1 (invariants, `temporal_integrity` audit details), 14.1-14.7 (deletions, drops, re-scope, todo dispositions, hygiene, refactor map with its four refactor rules, UD-25), 16 (build order)
- `docs/plans/2026-09-25-multi-timeframe-horizon-design.md` - D1 horizon rule (intraday horizons inside one session)
- `docs/plans/2026-09-26-daily-data-foundation.md` and `.planning/phases/185-daily-data-foundation/185-CONTEXT.md` - D2b derived grid (rebuild precondition), D-14 bar flags moving off `forward_return_writer`

### Todos
- `.planning/todos/pending/448-research-lane-dependencies-for-phases-186-187.md` - items 1-3 owned here
- `.planning/todos/pending/445-5m-features-incremental-ic-over-15m-before-feature-rebuild.md`
- `.planning/todos/pending/439-forward-span-integrity-write-once-oos-start-and-ic-purge.md` - IC purge part
- 248, 286, 289, 290, 291, 292, 301, 339, 341, 343, 352, 355, 390, 391, 411, 412, 420, 421, 426 in `.planning/todos/` (pending or completed); `.planning/todos/PRIORITIES.md` build lane row

### Code
- `services/ic_engine.py` (6,755), `src/intelligence/statistics/ic_math.py`, `src/intelligence/research/panel.py` (`forward_returns` kernel; read only)
- `services/forward_return_writer.py`, `services/ensemble_trainer.py`, `services/ensemble_ic_engine.py`, `services/alpha_frame_writer.py`, `services/counterfactual_tracker.py`, `services/alpha_publisher.py`, `services/context_writer.py`, `services/cross_sectional_spread_tracker.py`
- `src/intelligence/feature_factory.py`, `services/backfill_feature_factory.py`, `services/feature_vector_persistence.py`, `services/feature_vector_pipeline.py`
- `services/_batch_utils.py`, `services/regime_writer.py`, `services/feature_lifecycle.py`, `services/service_auditor.py`
- `scripts/analysis/sleeve_walk_forward/` (incl. `repro_frozen.py`, `config.py`), `scripts/ops/corpus/ops_corpus_pipeline_run.sh`, `ops_pipeline_monitor.sh`

### Project rules
- `CLAUDE.md` - ic_engine import rule, orphaned-worker kill rule, APR mandate, compressed-hypertable VACUUM rule, migration commit-with-apply rule, ProcessPoolExecutor write rule, no wide `SELECT *` corpus frames, asyncpg dtype-from-schema rule, service registry rule, file-rename test sweep
- `docs/foundation/performance-investigation-sop.md`, `docs/foundation/timescaledb-compressed-column-migration.md`
- `docs/foundation/unified-concept-registry.md`, `docs/research/construction-verdict-ledger.md` (card sources)

</canonical_refs>

<specifics>
## Specific ideas

- Measured 2026-09-26: database 174 GB; expected about 60 GB after drops, about 100 GB after the rebuild lands.
- `feature_vectors` 89 GB compressed (491 GB uncompressed), 108.6M rows, 75.1M of them 5m; 233 names carry it.
- `feature_ic_scores` 10.6M rows, 0.7 GB; `feature_ic_scores_history` 38 GB uncompressed; `forward_returns` 14 GB, covers 233 of 932 names, ends 2025-12-23, 1,008 1d bars on 4 names without a row.
- Kernel vs table (2023-2025): horizon 1 identical at 1d/5m/1h; longer 1d horizons differ on 0.03-0.06% of rows (up to 0.11 log return); 5m 1.6-6.9% differ, 467k extended rows only in the table; 1h 20/60-bar horizons only in the table. Kernel cost: four 5m horizons on 91M cells in about 5 s on one core vs 61 s reading the table.
- Row-at-a-time insert counts: `ensemble_alpha` 107M calls, `alpha_events` 66M, `feature_ic_scores` 18M.
- Units checked 2026-09-26: `indicagent-ctx-writer` active; alpha-publisher, ensemble-trainer, ensemble-ic-engine, alpha-frame-writer, counterfactual-tracker, forward-return-writer, feature-lifecycle, ic-engine, cross-sectional-spread-tracker inactive.
- Net code effect: about 34k lines of dead chain and analysis scripts deleted.

</specifics>

<deferred>
## Deferred ideas

- DAG manifest, per-writer database roles, `_DAG_ORDER` deletion, `service_auditor` reading the manifest, UCR clean schema and loading summary cards, `book_memory()`, research package refactor (item 8), StepM through the E17 battery (todo 448 item 4): phase 187.
- Nightly `temporal_integrity`, `no_fill`, `point_in_time` audit jobs (track B beyond the probe).
- `BookTracker`/`BookPositionWriter`, forward runner: phase 188.
- Todo 435 S0 wiring and the first feature family: after the rebuild, outside this phase.
- Todo 390 before `illiq` enters any family (not a phase 186 deliverable).
- A stored target cache: only if a profile of the new proposer shows recomputation dominates (14.7 item 5).
- Todo 443 (exporter scrape, idle-in-transaction timeout): quick lane.

</deferred>

---

*Phase: 186-old-ensemble-chain-retirement-and-ic-engine-re-scope*
*Context gathered: 2026-09-26 via PRD express path*
