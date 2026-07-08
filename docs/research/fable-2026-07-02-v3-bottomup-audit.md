# Bottom-Up Architecture Audit — v3.x (2026-07-02)

**Author:** Fable 5 (dispatched via Claude Code Agent tool)

**Method:** direct inspection of the running system — systemd state, live DB row counts/schemas, config_state cross-referenced against code greps, and full reads of the v3.0 core services (`ic_engine.py`, `ensemble_trainer.py`, `alpha_publisher.py`, `equity_regime_model.py`, `feature_vector_pipeline.py`, `forward_return_writer.py`, corpus orchestration script). Every claim below is backed by a query result or file:line. Companion top-down audit is being produced independently; this document deliberately reasons only from what the code and data actually do.

---

## 1. Executive Summary

1. **The system is, in fact, a batch research platform — the documented "two coexisting pipelines" story is false on the ground.** The v2.x real-time pipeline is dead: `indicagent-intelligence-pipeline.service` is `loaded/failed`, its `ExecStart` points at `services/intelligence_pipeline.py` which was deleted in commit `cb8f581a` (renamed to `feature_vector_pipeline.py`); `ibkr-provider`, `provider-merger`, `bar-writer`, `bar-aggregator` are all `inactive (dead)`; `signal_events` and `intelligence_features` are frozen at 2026-06-22; **42 of 70 database tables have zero rows**. PROJECT.md ("v2.x Real-Time Pipeline (live)... Active systemd services: intelligence-pipeline, signal-lifecycle, feature-writer, llm-writer, ai-narrative...") describes a fleet that does not exist. Only 6 services are enabled; **every single timer is disabled** — including `roll-batch` which CLAUDE.md describes as "nightly 8pm."

2. **The v3.0 "live" leg publishes into the void.** `feature_vector_pipeline` is running and publishing `FeatureVectorRecord`s to `topic_feature_vectors`, but `services/feature_vector_writer.py` — the only consumer of that topic — **has no systemd unit anywhere** (not in `production/systemd/`, not installed). `feature_vectors.max(bar_ts)` = 2026-06-23, all from batch backfill. A daemon burns CPU 24/7 computing feature vectors that are never persisted or consumed.

3. **Four more enabled daemons are orphaned consumers.** `signal_writer` and `signal_tracker` consume `topic_intelligence_i7_signals`, which has had **no producer since the D-09 cutover** (feature_vector_pipeline.py:6-8: "I5/I6/I7 plugin dispatch removed"). `lineage_writer` consumes `topic_signal_lineage` published only by the AI swarm (disabled; `signal_lineage`: 0 rows). `ctx_writer` runs with `ctx_events`: 0 and `ctx_snapshots`: 0 rows. Four running services, zero throughput, forever.

4. **The OOS holdout exists as a config key and is enforced nowhere.** `alpha.validation.oos_start` was written to `config_state` (config_history `changed_by='corpus_02_oos_split'`) but no file in `src/`, `services/`, or `scripts/` reads it. The corpus orchestrator (`ops_corpus_pipeline_run.sh:198`) sets `TRAINING_WINDOW_END = SELECT MAX(bar_ts) FROM feature_vectors` — IC, ensemble weights, and alpha_events are all computed through the last available bar. Walk-forward folds exist inside ic_engine, but the pre-committed OOS discipline the key was created for is aspirational. **This is the single most important rigor gap found.**

5. **98.3% of alpha_events sit in the timeframe band already shown cost-negative.** `alpha_publisher` manifest (2026-07-01): 168,479 of 172,257 events at 5m, 3,778 at 15m, zero at 1h/1d — while todo 030's Step 0 found 5m fast/mid "net-negative-to-marginal" after external costs. The `alpha.quant.cost_hurdle.*` APR keys are all **0.0** (verified in config_state), so the cost gate at alpha_publisher.py:118-125 is a no-op. Additionally, the Kafka topic `alpha.events` has **zero consumers** (grep: only stream_keys, service_auditor, publisher, report generator reference it) — the Kafka publish leg is dead transport.

6. **`market_data_ohlcv` is ~81% synthetic padding.** SPY 5m: 855,626 of 1,050,794 rows have `volume=0`; row counts are exactly 288 bars/day × 365 days/year (105,120/yr) — a flat-filled bar for every 5-minute interval of every calendar day, including nights and weekends, for equity ETFs that trade 6.5h × 5d. The canonical 61.8M-row bar table is mostly non-market filler. Todo 035 (active-bars view) exists but underweights the issue: this also contaminates any consumer that doesn't independently know the session mask.

7. **APR "calibration" has never happened, anywhere.** `config_history` (225 rows): 108 `initial_estimate`, ~90 migration seeds, 14 `conventional`, 4 `rca_analysis`, ~11 human edits — **zero `ml_learned` writes ever**. The parameter lifecycle "seed → ml_learned → user_override" is one-third real. Beyond that, ~15 `alpha.*` keys have **no reader at all** (§2.3) — bootstrap CIs, IC decay detection, ensemble CI assumptions, registry FDR/demotion: governance designed into APR, seeded via migration, never implemented in code.

8. **feature_ic_scores.regime mixes two label vocabularies in one column with no scope qualifier.** The ic_engine manifest's `rows_by_regime` shows 9 cross-sectional labels (`low_bull`…`high_bear`, 14K-32K rows each) *and* 5 per-symbol HMM labels (`ranging`, `transition_up`, … at 427-549 rows each) in the same `regime` column. No `regime_scope` column exists (schema verified). Consumers must know magic label strings to filter correctly. **Correction (2026-07-02, verified directly against the code):** this bullet originally claimed both label sources are look-ahead, citing `equity_regime_model.py:14-15`'s docstring ("Acceptable for batch [full-corpus rank]"). That docstring was stale — the actual `_compute_vix_pct_rank` implementation (lines 221-248) is a bisect-based *causal expanding* rank, fixed 2026-06-29 per todo 026 P1a; `_compute_breadth_fraction`'s rolling-MA is inherently causal. Both were mistaken for current behavior because the comment describing the old, non-causal version was never updated after the fix — corrected in the source file 2026-07-02. **The per-symbol HMM full-corpus-fit concern stands** (`regime_writer.py`, gated under todo 026, not yet proven to matter — Step 1's baseline-separation query this session found mixed evidence: SPY's labels separate IC reasonably, TLT's don't at all). So: one of the two claimed look-ahead sources was false and is now fixed at the doc level too; the other was already correctly tracked elsewhere, not a new finding. The schema gap (`regime_scope` column missing) remains valid and unaffected by this correction.

9. **The clustering computation exists twice, and one output is orphaned.** `ic_engine._cluster_features` (ic_engine.py:470-489, scipy single-linkage dendrogram) writes `cluster_id` to `feature_ic_scores` — **zero readers anywhere** (grep). `ensemble_trainer` independently re-clusters via `cluster_deflate_weights` (src/intelligence/ensemble/weights.py) on a Ledoit-Wolf correlation matrix — a *different algorithm on a different correlation estimate*. Two implementations of "which features are redundant," potentially disagreeing, one stored and ignored.

10. **Silent-staleness trap in ensemble retraining.** `ensemble_trainer.py:574` and `:625` use `ON CONFLICT ... DO NOTHING` with a static `weight_version='v1'` from APR. Re-running the trainer after IC scores change **silently keeps the old weights** unless the operator remembers to bump `alpha.ensemble.weight_version` or truncate. This is exactly the "silent wrong answer" the design mindset forbids. Also: 90-day staleness cliff hardcoded at ensemble_trainer.py:508 (`if days_since > 90`) next to APR-backed `weight_half_life_days` (todo 043 already captures this); dead module global `_KNOWN_FEATURE_COLS` at :159.

---

## 2. Ghost Infrastructure Inventory

### 2.1 Empty tables (42 of 70 — verified counts, 2026-07-02)

| Cluster | Tables (rows=0) | Verdict |
|---|---|---|
| v2.x signal outcome loop | `trade_executions`, `setup_performance`, `cis_weights`, `tod_multipliers`, `calibration_curves`, `confidence_calibration`, `pattern_reliability` | Dead with pipeline. The 1.44M-row ledger PROJECT.md celebrates was dropped; `signal_events`=1,601, `trade_frames`=1,601, frozen 06-22. |
| ML batch subsystem | `ml_models`, `ml_signal_training`, `ml_data_quality_runs`, `ml_discovery_runs` | Timers disabled; services never ran against v3 corpus. |
| Memory subsystem | `memory_episodes_raw`, `memory_episodes_labeled`, `memory_calibration_spc`, `memory_calibration_promoted`, `memory_regime_transitions`, `memory_system_state` | 6 tables, 0 rows; `memory-batch` unit exists in repo, never installed. |
| AI swarm | `swarm_agent_weights`, `llm_model_scores`, `signal_ai_enrichment`, `intelligence_ai_enrichment`, `signal_lineage`, `ctx_events`, `ctx_snapshots` | `llm_calls` has 39 rows total — the entire AI layer (alpha_swarm, narrative_swarm, graduation, ledger writer ≈ 4,800 LOC in services/ + 2,711 LOC src/intelligence/ai + 1,264 LOC src/core/ai) has essentially never run. |
| Drift/quality/governance | `drift_monitor`, `drift_state`, `signal_metrics`, `signal_metrics_ic`, `signal_metrics_dq_failures`, `signal_transform_log`, `transform_graduation`, `feature_transition_log`, `shadow_transition_log`, `remediation_ledger`, `parity_certification_state`, `system_events`, `market_data_gaps`, `intelligence_metrics`, `alpha_multiplier_shadow`, `dlq_events`, `config_outbox`, `batch_job_checkpoints` | `batch_job_checkpoints` has **zero code references** (grep) — table created, feature never built. `alpha_multiplier_shadow` likewise 0 rows. |

### 2.2 Dormant-but-populated

| Object | Evidence | Verdict |
|---|---|---|
| `shadow_registry` (36 rows) | `last_eval_at IS NULL` on 36/36 (re-verified). Consumers `shadow_auditor`/`shadow_validator` units disabled; timers disabled. | Confirmed dead. Drop with v2.x. |
| `instrument_tags.weight` | 410 rows, all `source='human'`, only 7 distinct weight values (re-verified). Calibrator (`docs/research/instrument-tag-calibrator.md`, todo 040) unbuilt. | Vestigial column carrying guesses used by live breadth logic. |
| `intelligence_features` (9,249 rows) | v2.x feature store; writer disabled; frozen 06-22. v3.0 explicitly rejects it for IC (selection bias). | No live purpose. |
| `feature_ic_scores.is_decaying`, `decay_detected_at`, `recovery_eligible_at` | Columns exist; ic_engine writes only the column names into its manifest (ic_engine.py:2339-2340); **no service computes decay**; the 4 `alpha.decay.*` APR keys have zero readers. | Decay detection: schema + APR shipped, algorithm never written (overlaps todo 024). |
| `feature_ic_scores.cluster_id` | Written by ic_engine, zero readers (grep confirmed). | Orphaned output (see §3). |
| `feature_registry` (61 rows, all `status='active'`) | Exactly mirrors `FeatureVector`'s 61 dataclass fields; used solely as an alignment gate (ensemble_trainer.py:275-282). Lifecycle states (candidate/shadow_only/deprecated) never used, so `feature_status_at_eval='active'` filter (ensemble_trainer.py:405) is currently a tautology. | A DB table doing the job of `dataclasses.fields()`. |
| `instruments`(102) / `instrument_metadata`(61) / `instrument_annotations`(58) / `instrument_tags`(410) / `tag_vocabulary`(71) | Four adjacent instrument-description surfaces plus `contract_metadata`(52) for dead futures. 80 active equity instruments registered, only 58 backfilled (migration 188 expansion is registered-not-materialized). | Consolidation candidate (§5.8). |

### 2.3 APR keys with zero readers (after excluding dynamically-composed keys)

Verified by grepping each of the 361 keys, then checking prefix/f-string construction (`alert.lag.*`, `alpha.quant.*`, `feature.hmm.lookback_days.*`, `feature.trade_framer.*`, `feature.zone_engine.*`, `ai.agent.*.shadow_mode` are all legitimately dynamic):

- `alpha.decay.ci_lower_threshold`, `.materiality_threshold`, `.recovery_min_observations`, `.regime_shift_fraction` — decay detector never built
- `alpha.ic.bootstrap_block_size.{5m,15m,1h,1d}`, `.bootstrap_resamples` (self-described `[deprecated]`), `.bootstrap_seed` — bootstrap CI never implemented (Fisher-z analytic CI used instead, ic_engine.py:376)
- `alpha.ic.min_obs_per_regime` — description promises a BH-FDR gate contribution that doesn't exist
- `alpha.ensemble.ci_independence_assumption`, `.lookahead_selection`, `.wf_consistency_factor`
- `alpha.feature_registry.demotion_periods`, `.fdr_alpha` — note `.fdr_alpha` duplicates the *live* `alpha.ic.fdr_alpha` (ic_engine.py:282) in a second namespace
- `alpha.validation.oos_start` — see Exec §4
- `alpha.vector.v1_quant.members` — behavioral list, never loaded
- `infra.ensemble_trainer.workers` — trainer is single-threaded; key promises parallelism that doesn't exist

**Pattern:** APR has become a place where *planned* features get seeded ahead of implementation, then the implementation doesn't land and the key silently lies about system capability. An APR key whose description says "gate" or "used by X" with no reader is worse than a TODO — it looks operational.

### 2.4 systemd drift (both directions)

- Installed-but-broken: `indicagent-intelligence-pipeline.service` enabled, failed, ExecStart→deleted file.
- Repo-but-never-installed: `memory-batch`, `shadow-validator`, `signal-probe-auditor`, `feature-parity-auditor`, `confidence-calibration-monitor` (units exist in `production/systemd/`, absent from `systemctl list-unit-files`).
- Missing entirely: **no unit for `feature_vector_writer`** — the v3.0 live persistence leg was never deployed.
- `_DAG_ORDER` in service_auditor.py:57 lists ~40 services as the "canonical registry"; 6 are enabled. The canonical registry describes an aspirational fleet, so the auditor cannot distinguish "correctly dormant" from "wrongly dead."
- All 13 timers disabled (`systemctl list-timers`: zero indicagent entries), including `roll-batch` documented in CLAUDE.md as live nightly.

---

## 3. Duplicated / Overlapping Logic

1. **APR loading idiom, copy-pasted 4-6×.** `_load_apr` + `_cfg_float/_cfg_int/_cfg_str` verbatim in `ensemble_trainer.py:79-101` and `alpha_publisher.py:62-80`; variants in `feature_vector_writer.py`, `generate_ic_discovery_report.py`, `src/intelligence/services/hmm_trainer.py`, `src/observability/corpus_manifest_verifier.py`. Meanwhile `ic_engine.py` uses a *different* idiom (`ConfigService.get_sync`, ICEngineConfig.from_apr at :278). Two config-access dialects across sibling steps of the same pipeline.
2. **`_connect_db` ×3:** `ic_engine.py:223` (+ `_connect_db_from_url` :228), `equity_regime_model.py:107`, `backfill_feature_factory.py:365`.
3. **Correlation clustering ×2:** `ic_engine.py:470` (single-linkage on raw `np.corrcoef`) vs `src/intelligence/ensemble/weights.py::cluster_deflate_weights` (cluster detection on LW-shrunk correlation). Different algorithms answering the same question; ic_engine's answer (`cluster_id`) is persisted and ignored.
4. **Lookahead fallback constants ×2:** `alpha.ic.lookahead.*` defaults `1/5/20/60` duplicated in `ic_engine.py:290-293` and `forward_return_writer.py:78` (`_SCALE_FALLBACKS`). If the APR row is ever missing, both fall back — but nothing guarantees they fall back to the *same* numbers over time. Same class of issue: emission threshold defaults duplicated between APR seeds and `alpha_publisher.py:110-115` hardcoded dict.
5. **No-op tracer shim:** `ic_engine.py:185-207` reimplements a noop `observed_span` that `src/observability/spans.py` already owns.
6. **TF-arithmetic maps ×3:** `equity_regime_model.py:82` (`_BARS_PER_DAY`), `forward_return_writer.py:335` (`_TF_MINUTES`), plus `TF_SECONDS` in `stream_keys.py`. Three encodings of "how long is a bar/day per TF" — the session-aware one (`_BARS_PER_DAY`) is the only one that knows NYSE hours, and it's private to one service.
7. **Three regime systems, two live + one dormant:** `regime_writer.py` (per-symbol GaussianHMM → `feature_vectors.regime`), `equity_regime_model.py` (cross-sectional → `market_regimes`), and `src/intelligence/services/hmm_trainer.py` + `services/hmm_training_agent.py` (v2.x pipeline HMM, unit disabled). The dormant third still carries `feature.hmm.lookback_days.*` APR keys.
8. **FDR alpha in two namespaces** (`alpha.ic.fdr_alpha` live, `alpha.feature_registry.fdr_alpha` dead) — a collision the glossary rule ("every term one definition") should have caught.

---

## 4. Emergent Concepts Needing a Name

1. **The Corpus Run.** The real production line of this system is the 6-step batch DAG (`backfill_feature_factory → regime_writer → [equity_regime_model] → forward_return_writer → ic_engine → ensemble_trainer → alpha_publisher`) orchestrated by a bash script with a freeze-point (`TRAINING_WINDOW_END`) and per-step `CorpusManifest`s. It has no first-class identity: no `run_id` threads through the manifests or output tables (manifests are single-file overwrites; `training_window_end` acts as an accidental run key in `feature_ic_scores` but not in `ensemble_weights`/`alpha_events`). Every recent operational incident in memory (orphan pools, wedges, seed gotchas, truncate scripts) is about this unnamed thing. Name it, give it a run_id, make each step record `(run_id, step, inputs_hash, outputs)` — the manifests are 80% of the way there.
2. **Regime scope.** Two vocabularies in one `regime` column (Exec §8). The recent naming commit "sanctions domain-specific naming" for regime groups, but the *schema* needs the dimension: `regime_scope ∈ {symbol_hmm, cross_sectional}` or two columns. Today the distinction is encoded in "which strings you know about."
3. **Session mask / canonical trading bar.** `volume=0` flat-fill vs real bars (Exec §6) is a load-bearing distinction with no schema representation — consumers infer it (feature factory filters correctly; forward_return_writer needed an ET session-boundary fix per the corpus script comment at :210-211, i.e., it was burned by exactly this).
4. **Weight epoch.** `weight_version` currently conflates three things: methodology version ("v1"), retraining epoch (nothing — DO NOTHING collisions), and APR-configured pointer for the publisher. The missing concept is a monotonically identified *training epoch* per corpus run.
5. **Orphaned consumer / producer contract.** Four daemons run against producer-less topics (Exec §3). There is no mechanism — in service_auditor or elsewhere — that asserts "every subscribed topic has ≥1 live producer." The DAG is declared in `_DAG_ORDER` comments, not checked against reality.
6. **Emission tier vs research tier.** `alpha_events` conflates "statistically qualifying bar-level scores" (research artifact, 172K rows, 98% likely untradeable) with "events worth acting on" (should be cost-hurdle-gated, ~unknown count). Todo 011's `is_shadow` column idea circles this; the real concept is two tiers with different gates.

---

## 5. Proposed Restructuring

Ordered by the 5-Step mandate: delete first.

### 5.1 DELETE: Decommission v2.x in fact and in docs (biggest single win)
The data already voted: 42 empty tables, frozen ledgers, failed unit, no producer for the signal topic. Proposal:
- Disable/remove units: `signal-writer`, `signal-tracker-compute`, `ctx-writer`, `lineage-writer`, `intelligence-pipeline` (failed), plus repo units never installed.
- Archive/delete code: `src/intelligence/trading/` (13,636 LOC), `pipeline/` signal-path modules (signal_processor, ranker, winner_selector, regime_gate, tod_adjuster, calibrator, quality_gate — the D-09 cutover already removed their dispatch), `composites/`, `confluence/`, `plugins/`, `context/`, `swarm/`, `ml/`, `monitoring/`, most of `services/` v2.x files (~19 dormant service files ≈ 4,845 LOC). Git history preserves everything; the unit description's "restore from git for dual-pipeline comparison" is the right instinct applied to 35K+ LOC that should live *only* in git.
- Drop tables: all 42 empty ones plus `shadow_registry`, `intelligence_features`, `llm_calls`(39 rows), after a final `pg_dump` archive. Keep `signal_events`/`trade_frames` only if the 1,601-row remnant has audit value (doubtful).
- Rewrite CLAUDE.md/PROJECT.md sections that describe v2.x as live. Roughly half of CLAUDE.md's per-turn context (SLA tables, signal status strings, plugin tiers, swarm gotchas, I7 rules) governs a dead system — that is real cost on every session.
- **Why this serves the two goals:** every hour of attention and every doc token spent on a dead pipeline is taken from the alpha loop; and a system whose docs describe phantom services is one you can fool yourself with.

### 5.2 DELETE: Stop the void-publishing live leg
Either install a `feature_vector_writer` unit (if live parity data is wanted now) or — better, per "don't automate what isn't proven" — stop `feature_vector_pipeline` until Phase 142's gates pass. Live feature computation before batch alpha is proven is premature automation; today it's worse: it's automation with the output wire cut.

### 5.3 NAME + FORMALIZE: The Corpus Run (§4.1)
Make the bash script's implicit contract explicit: a `corpus_runs` table (run_id, started_at, training_window_end, step statuses, git SHA, APR snapshot hash), thread run_id into every manifest and into `ensemble_weights`/`ensemble_alpha`/`alpha_events`. This directly fixes the `ON CONFLICT DO NOTHING` silent-staleness trap (5.6) and gives the falsifiability audit trail (which exact config produced which alpha) that Renaissance discipline demands. The APR snapshot matters: today a re-run after an APR edit is unrecorded provenance.

### 5.4 ENFORCE: the OOS holdout, or delete the key
Two honest options: (a) implement it — corpus script derives `TRAINING_WINDOW_END` from `min(MAX(bar_ts), alpha.validation.oos_start)` and a separate, rare, pre-committed OOS evaluation step scores the holdout; or (b) delete the key and openly state walk-forward folds are the only OOS mechanism. The current state — a seeded holdout timestamp nothing reads — is the worst option: it *documents* a discipline that isn't practiced. Recommend (a); it is cheap and it is the project's stated core epistemology.

### 5.5 FIX: regime label integrity before more IC is trusted
- Add `regime_scope` to `feature_ic_scores` (and stop writing per-symbol-HMM-stratified IC rows unless something consumes them — currently 488-row cells that no ensemble path reads, since ensemble consumes only `symbol='POOLED'` cross-sectional rows: ensemble_trainer.py:4-5).
- Replace full-corpus percentile rank in `equity_regime_model.py:14` with an expanding/rolling causal rank; same decision for the HMM fit window (todo 026's evidence gate is the right process — but note the equity model's look-ahead is *admitted in its own docstring* and feeds the primary IC stratification today).
- Seriously evaluate **deleting the per-symbol HMM regime system**: todo 026 already found its labels are asset-class-dependent (good SPY, inverted TLT); the ensemble doesn't consume it; it costs a 976-line service, JIT work, refit wedges, and monitor scripts. If the baseline-separation query doesn't prove value, this is a Musk-step-2 deletion of an entire subsystem.

### 5.6 FIX: weight lifecycle
Replace `DO NOTHING` with per-run epochs (5.3) or explicit delete-and-replace within a transaction; move the 90-day cliff to APR (todo 043); either consume `cluster_id` in the ensemble or stop computing/storing it — one clustering implementation, owned by the ensemble math library.

### 5.7 SIMPLIFY: batch-service common layer
One `src/core/agent/batch_config.py` (or extend BaseBatch): APR dict loader + typed getters + `_connect_db`. Six copies today (§3.1-2). Adopt one config idiom for all corpus steps. Delete ic_engine's noop tracer shim; also split ic_engine (2,384 lines: per-symbol IC, cross-sectional IC, FDR, walk-forward, HAC, clustering, health gauges, manifest) into pure functions under `src/intelligence/` + a thin runner — todo 032 already proposes this; this audit endorses it as the highest-value refactor for testability of the statistical core.

### 5.8 CONSOLIDATE: registries
- `feature_registry`: keep only if lifecycle states start being used (they're the hook for §2.3's demotion keys); otherwise generate the alignment check from `dataclasses.fields(FeatureVector)` and drop the table. Don't build the proposed Concept Registry / Controlled Vocabulary as *new* systems while five existing registries sit at 0-or-static rows — fold vocabulary governance into `tag_vocabulary`+glossary, which are the two that demonstrably work.
- Instruments: fold `instrument_metadata` + `instrument_annotations` into `instruments.contract_details`/`instrument_tags` unless a concrete consumer distinguishes them (open question §7.3).
- APR: delete the 15 reader-less keys or file each as an explicit todo with the key marked `[unimplemented]` in its description; add a CI check "every config_state key is grepped-referenced (with dynamic-prefix allowlist)" so this class of drift can't recur.

### 5.9 DATA: session-canonical bars
Add `is_synthetic`/session-mask representation (or the todo-035 view) and make it the default read surface. 50M synthetic rows in the canonical table is a standing invitation for the next forward-return-style contamination bug.

### 5.10 RECONSIDER phases in flight
- **Phase 142A (ensemble IC proof)** survives bottom-up scrutiny — it is the right next question and its inputs exist. But it should run **after** 5.4 (OOS enforcement) and 5.5 (regime scope + causal labels), or its result inherits the label look-ahead and full-sample measurement; proving "ensemble IC > 0" on look-ahead-stratified, in-sample data would be a hollow gate.
- **Phase 142B (frame simulation)**: unchanged in concept, but its cost-model deferral should be revisited given Exec §5 — the emission population it will simulate is 98% in the cost-negative band; either calibrate `cost_hurdle` first (todo 030 → B2) or 142B's counterfactual P&L will be dominated by untradeable 5m events.
- **v4.1 health-guardian phases (149A/149B/150)**: these build drift/lifecycle monitoring on top of columns and keys shown here to be ghost infrastructure (`is_decaying`, `alpha.decay.*`). Fine — but they should be scoped as "implement the already-seeded contracts," and the seeded keys audited against their designs first.

---

## 6. What's Actually Solid

- **`forward_returns` integrity:** 10.08M rows, 100% `return_type='executable_open_to_open'` (verified) — Invariant 1 holds in the data, not just the docs; the theoretical return type isn't even stored. The complete_{scale}/session-boundary fix shows the team catches gap contamination.
- **Corpus coverage matches spec exactly:** 58 symbols × 4 TFs; depths verified (5m from 2022≈5y, 15m from 2016≈10y, 1h from 2011≈15y, 1d from 2007≈20y). `regime` uniformity gate in the orchestrator is a good invariant check.
- **Ensemble math library** (`src/intelligence/ensemble/`, 445 LOC): genuinely clean Ring-1 pure functions; APR params passed as arguments; documented APR-exemptions; careful iterative cap-redistribution in `derive_weights`.
- **Crash-loud startup gates** in ic_engine/ensemble_trainer/alpha_publisher (`_assert_prerequisites`) — the "loud crashes over silent wrong answers" principle is real in the v3 core.
- **CorpusManifest per step** — the right primitive; just needs run_id lineage (5.3).
- **Registry↔dataclass alignment gate** (ensemble_trainer.py:279) — cheap schema-drift tripwire.
- **APR coverage in the v3 hot loop is genuinely broad** — ICEngineConfig binds 17 keys; the violations found are at the edges (90-day cliff, fallback dicts), not the core.
- **The meta-FDR gate + LW deflation + effective-N gate stack** is a thoughtful multiple-testing defense; the gaps found are provenance/lifecycle, not statistical design.

## 7. Open Questions (need operator)

1. **Is "dual-pipeline comparison" still intended?** The failed unit's description implies deliberate v2.x resurrection someday. If yes, 5.1 becomes "archive cleanly" rather than "delete"; if no, the unit and the description are noise.
2. **Are the 4 orphaned writer daemons intentional keep-warm** for an anticipated I7-topic revival, or an oversight from the D-09 cutover?
3. **`instrument_metadata` vs `instrument_annotations`** — contents not deeply inspected; is either consumed by anything live? (Grep suggests thin usage; confirm before folding.)
4. **`alpha.validation.oos_start` provenance** — was the intent that the *operator* manually respects it when invoking runs? If so, that's a manual step the corpus script should absorb (Musk step 5, but only after step-4 enforcement design).
5. **Is the Kafka leg of alpha_publisher speculative for a future consumer** (dashboard/simulator), or should `--skip-kafka` become the only mode until one exists?
6. **The 21 newly registered ETFs (migration 188)** — backfill scheduled? Registered-but-empty instruments will silently shrink breadth denominators if any consumer counts actives rather than symbols-with-data (equity_regime_model counts via tags JOIN — verify behavior when tagged symbols have no bars).
