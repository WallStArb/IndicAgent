# Phase 70: ML Scoring Model - Context

**Gathered:** 2026-05-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a statistically-validated LightGBM scoring layer that consumes `_shadow` dicts from all 36 I7 plugins and bar-level context, produces a `ml_score` per signal as an additional swarm multiplier agent, runs shadow_only=True until outcome evidence supports promotion, and simultaneously implements AI-SEP-01 (TODO-018) — separating all AI enrichment into AI-owned tables so quant tables remain pure and immutable.

Two new services: `MLScorerMultiplierAgent` (inference, in swarm) and `MLTrainingComputeAgent` (training, L8 nightly).

Does NOT include: swarm augmentation as ML features (deferred until 90+ days of co-located swarm data), replacing the Sharpe-based ranker (deferred until out-of-sample evidence), SHAP dashboard UI (deferred), per-plugin-per-TF model segmentation (sample starvation — deferred).

</domain>

<decisions>
## Implementation Decisions

### Feature Vector (D-01–D-03)
- **D-01:** Feature vector = 36-plugin `_shadow` dict fields + bar context: `hmm_regime`, `trend_regime`, `session_type`, `atr_pct`, `volume_z`, `tod_multiplier`. No swarm agent outputs — they're absent from pre-Phase-80 training data and would degrade model quality.
- **D-02:** Target variable: binary `P(win)` where win = `pnl_r > 0`. Aligns with `confidence_calibrator.py` pattern. Stationary, clean, no fat-tail issues.
- **D-03:** Feature pipeline must be built to support swarm augmentation as an opt-in layer in a future iteration (once 90+ days of co-located swarm data exists). Gate on `is_swarm_available` flag when that time comes.

### Model Segmentation (D-04–D-05)
- **D-04:** Global model (all resolved signals) + 3 per-regime models (hmm_regime 0/1/2). Use regime-specific model when `n_regime >= 100`, fall back to global otherwise. Regime is the highest-information conditioning variable for this dataset.
- **D-05:** No per-plugin or per-TF segmentation in v1 — sample starvation at current data volumes. Add as v2 extension once regime models stabilize.

### Training Pipeline (D-06–D-08)
- **D-06:** `MLTrainingComputeAgent` — new L8 systemd service. Follows the `setup_performance_updater.py` timer pattern. Runs nightly AND gates on delta: only retrain if resolved signal count has grown by >= 50 since last training run.
- **D-07:** Walk-forward cross-validation: expanding window, 60/20/20 train/val/test split by time. Zero lookahead — test set always strictly after train set. Register winning artifact via existing `ModelRegistry` at `src/core/ml/registry.py`.
- **D-08:** SHAP attribution computed at training time, stored as feature importance JSON in MLflow artifact. Not surfaced in dashboard (deferred) — but must be computed and persisted for audit.

### Inference Integration (D-09–D-11)
- **D-09:** `MLScorerMultiplierAgent` extends `BaseMultiplierAgent` (Phase 80 pattern). Lives in `src/intelligence/ai/alpha/ml_scorer_agent.py`. Loads latest promoted model via `ModelRegistry.load_latest(segment)` at startup. Sub-millisecond inference — no DB round-trip on hot path.
- **D-10:** Integration as additional swarm agent weight: `final = Σ(w_i × m_i) / Σ(w_i)` — same weighted average as other swarm agents. `shadow_only=True`. Weight starts at 1.0, learns via per-(agent,TF) outcome feedback system from Phase 80.
- **D-11:** Model reload: on startup + on `SIGUSR1` signal (allows nightly retraining to trigger inference agent to pick up new artifact without full restart). If no promoted model exists, agent returns neutral multiplier (1.0) and logs warning.

### Schema — AI-SEP-01 (D-12–D-15)
- **D-12:** Fold TODO-018 (`018-decouple-ai-enrichment-from-quant-tables.md`) into Phase 70. Quant tables stay pure and immutable after write — Jim Simons principle: clean data provenance is non-negotiable.
- **D-13:** New AI-owned table `signal_ai_enrichment`:
  ```sql
  CREATE TABLE signal_ai_enrichment (
      signal_id UUID PRIMARY KEY REFERENCES signal_ledger(signal_id),
      swarm_multiplier FLOAT,
      adjusted_confidence FLOAT,
      swarm_agent_count INT,
      ml_score FLOAT,
      ml_model_id UUID,
      enriched_at TIMESTAMPTZ NOT NULL
  );
  ```
- **D-14:** New AI-owned table `intelligence_ai_enrichment`:
  ```sql
  CREATE TABLE intelligence_ai_enrichment (
      ts TIMESTAMPTZ NOT NULL,
      symbol TEXT NOT NULL,
      tf TEXT NOT NULL,
      i8 JSONB,
      narrative_id UUID,
      enriched_at TIMESTAMPTZ NOT NULL,
      PRIMARY KEY (ts, symbol, tf)
  );
  ```
- **D-15:** Migrate writers: `SwarmLedgerWriterAgent` → UPSERT `signal_ai_enrichment` (no `signal_ledger` touch). `LlmWriterService` → UPSERT `intelligence_ai_enrichment` (no `intelligence_features` touch). Dashboard and ML training queries: LEFT JOIN enrichment tables at read time.

### Folded Todos
- **TODO-018 (AI-SEP-01):** `018-decouple-ai-enrichment-from-quant-tables.md` — folded into Phase 70. New tables `signal_ai_enrichment` + `intelligence_ai_enrichment`, migrate `SwarmLedgerWriterAgent` and `LlmWriterService`. See D-12–D-15 above.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing ML Infrastructure
- `src/core/ml/registry.py` — `ModelRegistry`: asyncpg-backed, MLflow artifacts. Use `register()`, `load_latest()`, `promote()`. This is the only model lifecycle API.
- `src/core/ml/shadow.py` — ARCHIVED (Phase 78). Do not use. Replaced by `LineageRecorder`.
- `src/core/ml/transform_recorder.py` — ARCHIVED (Phase 78). Do not use. Replaced by `LineageRecorder`.
- `src/core/ai/lineage.py` — `LineageRecorder`: current shadow/lineage write path.

### AI Agent Patterns
- `src/core/ai/multiplier_agent.py` — `BaseMultiplierAgent`: the base class for all inference agents. `MLScorerMultiplierAgent` MUST extend this.
- `src/intelligence/ai/alpha/correlation_agent.py` — Reference implementation of a concrete `BaseMultiplierAgent`.
- `src/intelligence/ai/AUTHORING.md` — 5-step authoring protocol for all AI agents.
- `src/intelligence/ai/TEMPLATE_agent.py` — Skeleton for new agents.

### Feature Engineering Sources
- `src/intelligence/schemas.py` — `IntelligenceEvent` schema: all `_shadow` dict field names are defined here. Read this before building the feature matrix.
- `src/intelligence/utils/confidence_utils.py` — `capture_confluence_features()`: the function that emits `_shadow` dicts from all I7 plugins. Defines exactly what fields are available.

### Training Data Source
- `signal_ledger` table — training labels (`pnl_r`, `outcome`, `signal_schema_version`). Filter: `signal_schema_version = SIGNAL_SCHEMA_VERSION` (import from `src/intelligence/trading/signal_schema.py`), `outcome IS NOT NULL`, `is_shadow = FALSE`.
- `intelligence_features` table — bar-level features (`hmm_regime`, `trend_regime`, `atr`, volume fields). JOIN on `(symbol, tf, ts)` to get bar context at signal fire time.

### Existing Calibration Pattern
- `src/intelligence/ml/confidence_calibrator.py` — isotonic regression per (plugin, tf); same N>=100 sample gate pattern used here. Study before implementing the training pipeline.
- `src/intelligence/setup_performance_updater.py` — nightly timer + delta-gate pattern. `MLTrainingComputeAgent` uses the same approach.

### Schema Change Reference
- `.planning/todos/pending/018-decouple-ai-enrichment-from-quant-tables.md` — full spec for `signal_ai_enrichment` + `intelligence_ai_enrichment` tables and migration plan.

### Phase 80 Context (swarm weight system)
- `.planning/phases/080-renaissance-swarm-intelligence-layer/080-CONTEXT.md` — D-07 defines the swarm dispatch layer and `Σ(w_i × m_i) / Σ(w_i)` weighted average. `MLScorerMultiplierAgent` integrates as peer agent in this system.

### Service DAG
- `src/intelligence/services/service_auditor_agent.py` — `_DAG_ORDER`: add `MLTrainingComputeAgent` to L8, `MLScorerMultiplierAgent` registers in `_agents` list of `AlphaSwarmComputeAgent`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ModelRegistry` (`src/core/ml/registry.py`): fully implemented. Use `load_latest({"global": True})` for global model, `load_latest({"hmm_regime": N})` for regime model. No reimplementation needed.
- `BaseMultiplierAgent` (`src/core/ai/multiplier_agent.py`): `_parse_multiplier_response()`, `_build_multiplier_output()`, `output_schema` ClassVar. `MLScorerMultiplierAgent` gets multiplier directly from LightGBM prediction — no LLM call, no JSON parsing needed. Override `_compute()` directly.
- `confidence_calibrator.py`: isotonic regression + N-gate pattern directly applicable to the training pipeline. Copy/adapt the groupby-and-gate logic.
- `setup_performance_updater.py`: nightly timer pattern + delta tracking. Adapt for `MLTrainingComputeAgent`.

### Established Patterns
- All AI agents: `agent_id`, `group`, `tiers_needed`, `latency_budget_ms`, `shadow_only` (5 mandatory class attributes).
- Walk-forward CV must use time-based splits, never random splits. `signal_ledger.timestamp` is the time axis.
- asyncpg: pass `dict` for JSONB columns, never `json.dumps()`. JSONB columns return `dict` on read, never call `json.loads()`.
- structlog: never pass `event=<value>` as kwarg. Use `signal=`, `payload=`, `data=` instead.
- Metrics: create via `src/observability/metrics.py` to prevent duplicate registration.

### Integration Points
- `AlphaSwarmComputeAgent._agents` list: add `MLScorerMultiplierAgent` here (constructed in `_setup()` after `super()._setup()` because `self._llm_chain` must exist).
- `SwarmLedgerWriterAgent`: migrate writes from `signal_ledger` UPDATE to `signal_ai_enrichment` UPSERT.
- `LlmWriterService`: migrate writes from `intelligence_features` UPDATE to `intelligence_ai_enrichment` UPSERT.
- `signal_auditor_agent.py` / `parity_auditor_agent.py`: may need read-side updates to LEFT JOIN enrichment tables.

</code_context>

<specifics>
## Specific Ideas

- **Renaissance design principle** applied throughout: training and inference are completely separate concerns. `MLTrainingComputeAgent` produces artifacts, `MLScorerMultiplierAgent` consumes them. No coupling.
- **Model reload via SIGUSR1**: nightly training completes → sends SIGUSR1 to swarm service → swarm agent calls `ModelRegistry.load_latest()` and hot-swaps model. No restart required.
- **Promotion gate**: bootstrap CI on `pnl_r` improvement vs baseline (no-ML swarm) over the most recent 100 resolved signals — mirrors Phase 80 swarm graduation gate. Minimum 100 resolved signals before any promotion is considered.
- **Stationarity note**: `_shadow` dict values are bounded scores (mostly [0,1]) — no stationarity transformation needed. `atr_pct` and `volume_z` are already normalized. `hmm_regime`, `trend_regime`, `session_type` are categoricals — one-hot encode for LightGBM.

</specifics>

<deferred>
## Deferred Ideas

- **Swarm outputs as ML features** — defer until 90+ days of co-located swarm shadow data. Build feature pipeline with `is_swarm_available` gate so this is a config flip, not a code change.
- **SHAP attribution dashboard** — SHAP values computed and stored at training time; surface in dashboard UI as a future phase.
- **Per-plugin-per-TF model segmentation** — v2 after regime models stabilize and sample sizes justify it.
- **Replacing Sharpe ranker** — not until ML model has 3+ months of out-of-sample evidence showing it outperforms.
- **ML-driven alpha decay monitoring** — detecting when model edge degrades; future observability phase.

</deferred>

---

*Phase: 70-ML Scoring Model*
*Context gathered: 2026-05-13*
