# Phase 82: ML Intelligence Quality & Qualitative Foundation — Context

**Gathered:** 2026-05-13
**Status:** Ready for planning

<domain>
## Phase Boundary

Five targeted improvements now that the May 10 data gate has passed. All are buildable with existing infrastructure, all follow the Renaissance discipline: simplest correct model first, shadow before live, computation and governance separated.

1. **DATA-02** — Run `validate_alpha.py` for DerivOsc and ACOsc. Gate: N ≥ 30 resolved outcomes per (plugin, tf, regime_type) slice. Promote if Pearson r > 0, p < 0.05; demote to IS_SHADOW=True if it fails.
2. **HMM Multi-TF instances** — Four per-TF HMM plugin instances (1m/5m/15m/1h) with correct lookbacks, replacing the current single 1m-only instance. Every I7 plugin on a given TF consumes its own TF's HMM regime context.
3. **HMM Training pipeline** — Offline Baum-Welch training via `HMMTrainingAgent` systemd timer. Per-TF pooled models (4 sets, not per-symbol). Monthly baseline retraining + drift-detection trigger.
4. **Regime Transition Early Detection** — `regime_entropy` + `hmm_regime_velocity` added to I4 HMM output. Soft confidence multiplier replacing binary gate for 0.30–0.55 prob band. Configurable thresholds in Settings.
5. **FeatureValidationService** — Automated daily IC/p-value computation wrapping existing `tools/validate_i6_backtest.py` logic. Writes VALIDATED/TWEAK/KILL decisions to `validation_results` table. Auto-promotes via `shadow_registry` table (Phase 75 contract seeded here).
6. **CTX Schema Foundation** — `ctx_events` + `ctx_snapshots` TimescaleDB tables, `CtxWriterAgent`, `intelligence_features.ctx` JSONB column. Data collection only — no AIContext prompt rendering until shadow validation passes (Phase 83).

Does NOT include: per-(symbol,tf) HMM models (deferred to Phase 83+ when data proves it needed), AIContext prompt rendering for ctx (deferred to Phase 83), provider lanes (earnings/macro/news — Phase 83+), full Shadow Governance automation (Phase 75).

</domain>

<decisions>
## Implementation Decisions

### Design Philosophy — Renaissance Principles Applied
Every decision in this phase follows four Renaissance rules:
- **Separation of concerns**: computation agents never govern; governance agents never compute
- **Simplest statistically robust model**: add complexity only when data proves it's needed
- **Shadow before live**: no new intelligence affects signal confidence until outcome evidence supports it
- **Configurable over hardcoded**: thresholds live in `Settings`, not in code — tune without deployment

### D-01: DATA-02 Gate Check
First step of Phase 82 — run the gate check before planning the remaining plans:
```sql
SELECT plugin_name, count(*)
FROM signal_ledger
WHERE plugin_name IN ('trad_DerivativeOscillator','trad_ACOscillator')
  AND outcome IS NOT NULL
GROUP BY plugin_name;
```
If N ≥ 30: run `production/scripts/validate_alpha.py --plugin DerivativeOscillatorPlugin` and `--plugin ACOscillatorPlugin`. Gate: Pearson r > 0, p < 0.05, N ≥ 30. Pass → promote (IS_SHADOW=False). Fail → demote (IS_SHADOW=True). Result documented in plan summary.

### D-02: HMM Per-TF Instances
Four HMM plugin instances, each with a TF-appropriate lookback:
```
smc_HMMRegime_1m  — InputSpec(timeframe="1m",  lookback=200)  → ~3.3h
smc_HMMRegime_5m  — InputSpec(timeframe="5m",  lookback=200)  → ~16h
smc_HMMRegime_15m — InputSpec(timeframe="15m", lookback=150)  → ~37h
smc_HMMRegime_1h  — InputSpec(timeframe="1h",  lookback=100)  → ~10 days
```
Output field names identical (`hmm_regime`, `hmm_regime_prob`, `hmm_regime_entropy`, `hmm_regime_velocity`). Each TF's feature dict gets its own regime context — I7 plugins on 5m bars consume the 5m HMM output. The 1m instance continues serving as-is; others are additive.

### D-03: HMM Training Architecture (Renaissance DAG)
**Separation**: `HMMTrainingAgent` (compute) is separate from the live inference plugins (HMMRegime instances read parameters, never retrain). Clean DAG: train → write params → live reload.

- **Model granularity**: per-TF pooled across all symbols (4 parameter sets). Per-symbol differentiation deferred to Phase 83+ when 90+ days data per instrument proves it reduces error vs. introducing noise.
- **Parameter storage**: `config/hmm_parameters_{tf}.json` (e.g., `hmm_parameters_5m.json`). Existing `_load_parameters()` pattern extended to accept TF suffix. Hot-reload via SIGUSR1 (same pattern as MLScorerMultiplierAgent).
- **Training schedule**: `indicagent-hmm-training.timer` — monthly baseline. Also triggered when `drift_monitor_service` emits drift detection event (Prometheus alert → systemd restart or direct Kafka trigger).
- **Training data**: `intelligence_features` — returns, volume z-score, volatility, OFI signal, directional bias. Per-TF rows only. Exclude `is_backfill=TRUE` rows (Phase 81 gate).
- **Systemd type**: `Type=oneshot`, `Restart=no`. One-shot training run, writes params, exits. No long-running service.

### D-04: Regime Transition Early Detection
Ship directly — this is a mathematical correction to a binary gate, not an ML model requiring outcome data validation.

- **New I4 output fields** in `HMMRegimePlugin` (all TFs):
  - `hmm_regime_entropy`: Shannon entropy across 3 state probabilities. High = transition window.
  - `hmm_regime_velocity`: Rate of change of dominant state probability across last N bars. High = active transition.
- **Soft confidence multiplier** replaces binary gate in `src/intelligence/pipeline/regime_gate.py`:
  - `prob < REGIME_PROB_MIN` (default 0.30): suppress (unchanged)
  - `REGIME_PROB_MIN ≤ prob < REGIME_PROB_SOFT_MAX` (default 0.55): apply `entropy_multiplier(prob, entropy)` — smooth interpolation from 0.0 to 1.0
  - `prob ≥ REGIME_PROB_SOFT_MAX`: full confidence (unchanged)
- **New Settings fields**: `REGIME_PROB_MIN: float = 0.30`, `REGIME_PROB_SOFT_MAX: float = 0.55`
- **Prometheus counter**: `regime_soft_gate_signals_total{band="soft"}` to observe signals firing in the new band vs. the old binary behavior.

### D-05: FeatureValidationService (Renaissance Computation/Governance Separation)
Two-layer design:
- **Layer 1 (this phase)**: `FeatureValidationComputeAgent` — computes IC/p-value daily, wraps existing `tools/validate_i6_backtest.py` logic, writes `ValidationResult` records to `validation_results` table.
- **Layer 2 (action)**: Minimal `shadow_registry` table seeded here as Phase 75 contract. `FeatureValidationComputeAgent` writes VALIDATED/TWEAK/KILL decisions to `shadow_registry.promotion_evidence`. Phase 75's `ShadowAuditorAgent` will read this evidence and execute promotion/demotion. Phase 82 does NOT execute the promotion directly — it produces evidence that gates Phase 75's action.

**`validation_results` table schema**:
- `plugin_name`, `timeframe`, `regime_type`, `ic`, `p_value`, `n`, `decision` (VALIDATED/TWEAK/KILL), `computed_at`, `bonferroni_corrected`
- TimescaleDB hypertable on `computed_at`

**Gate thresholds** (from `validate_i6_backtest.py`): IC > 0.05, p < 0.01 (Bonferroni-corrected), N ≥ 30 = VALIDATED. IC 0.02–0.05 = TWEAK. IC < 0.02 = KILL.

**API endpoint**: `GET /api/validation/results` — exposes latest per-plugin decisions for dashboard.

**Timer**: `indicagent-feature-validation.timer` — daily at 02:00 ET. `Type=oneshot`.

### D-06: CTX Schema Foundation (Data Collection Layer Only)
Renaissance "collect before you act" — build the infrastructure for qualitative data to flow in, but don't allow it to influence LLM prompts until shadow validation proves it adds alpha (Phase 83).

**Tables** (new TimescaleDB hypertables, migration number 084):
```sql
CREATE TABLE ctx_events (
    event_ts TIMESTAMPTZ NOT NULL,
    symbol TEXT,              -- NULL = global (FOMC etc.)
    event_type TEXT NOT NULL, -- 'earnings', 'macro', 'news'
    source TEXT NOT NULL,
    payload JSONB NOT NULL
);
SELECT create_hypertable('ctx_events', 'event_ts');

CREATE TABLE ctx_snapshots (
    symbol TEXT,
    event_type TEXT NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,
    ctx JSONB NOT NULL,
    PRIMARY KEY (symbol, event_type, valid_from)
);
```

**`intelligence_features` migration**: `ALTER TABLE intelligence_features ADD COLUMN ctx JSONB` — NULL by default. Feature writer resolves active ctx_snapshot at bar insert time (as-of join on valid_from/valid_to). Missing ctx = graceful absence, never stub values.

**`CtxWriterAgent`**: Consumes `topic_ctx_snapshot()` (new stream key). Persists to `ctx_events` + `ctx_snapshots`. Follows BaseWriterAgent pattern. DAG layer L6 (parallel with other writers).

**NOT in Phase 82**:
- `AIContextCache.seed_from_db_row()` ctx extension — deferred to Phase 83
- LLM prompt rendering of ctx fields — deferred until shadow gate passes
- Any provider lanes (earnings, macro, news) — Phase 83+

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### HMM Multi-TF & Training
- `src/intelligence/features/smc_context/hmm_regime.py` — Current HMM implementation (single TF). Multi-TF instances extend this class.
- `docs/ideas/hmm-multi-tf-and-training.md` — Full design: per-TF lookback table, training pipeline design, parameter file format
- `docs/ideas/regime-transition-early-detection.md` — regime_entropy + regime_velocity design, soft multiplier math

### Feature Validation
- `tools/validate_i6_backtest.py` — IC/p-value logic + ValidationResults dataclass + VALIDATED/TWEAK/KILL thresholds (IC > 0.05, p < 0.01 Bonferroni, N ≥ 30). Service wraps this.
- `tools/backtest_cross_tf_plugins.py` — Cross-TF plugin backtest runner
- `tools/backtest_macro_factors.py` — Macro factor backtest runner

### CTX Schema
- `docs/plans/2026-05-02-unified-intelligence-design.md` — Full architectural design: domain ownership table, integration rules, P-CTX-01 spec, ctx schema details
- `docs/ideas/qualitative-intelligence-layer.md` — Provider agent design, ctx_snapshots schema, as-of join pattern

### DATA-02
- `production/scripts/validate_alpha.py` — Full validate_alpha implementation (988 lines)

### Existing Patterns to Follow
- `services/ml_training_agent.py` — Systemd timer pattern for one-shot training jobs
- `services/lifecycle_writer_agent.py` — BaseWriterAgent batch persistence pattern (for CtxWriterAgent)
- `src/core/stream_keys.py` — Add `topic_ctx_snapshot()` here, not inline
- `src/intelligence/pipeline/regime_gate.py` — Current binary gate implementation to modify
- `src/config/settings.py` — Add `REGIME_PROB_MIN`, `REGIME_PROB_SOFT_MAX`, `HMM_TRAINING_SCHEDULE`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/intelligence/features/smc_context/hmm_regime.py` — `_load_parameters()` already checks `config/hmm_parameters.json` — just extend to TF-suffixed paths
- `tools/validate_i6_backtest.py` — `ValidationResults` dataclass + `validate_backtest_results()` function — import directly into service
- `services/ml_training_agent.py` — `Type=oneshot` systemd timer pattern for `HMMTrainingAgent` and `FeatureValidationComputeAgent`
- `src/observability/metrics.py` — Register `regime_soft_gate_signals_total` and `feature_validation_decisions_total` here

### Established Patterns
- **Shadow-only default**: any new compute agent (`HMMTrainingAgent`, `FeatureValidationComputeAgent`) starts shadow-only, no production writes until validated
- **BaseWriterAgent**: `CtxWriterAgent` follows this pattern — batch buffer, flush interval, idempotent upsert
- **SIGUSR1 hot-reload**: HMM instances reload parameters on signal (same as `MLScorerMultiplierAgent`)
- **`_load_parameters()` config file pattern**: already exists in `hmm_regime.py` — extend, don't rewrite

### Integration Points
- `intelligence_pipeline_agent.py` — Multi-TF HMM instances are registered as I4 plugins; output lands in `I4Context`
- `src/intelligence/pipeline/regime_gate.py` — Soft multiplier replaces binary gate here
- `services/feature_writer_agent.py` — Resolves active ctx_snapshot at bar insert time for `intelligence_features.ctx`
- `src/core/ai/base_group_service.py` `_seed_context_cache()` — ctx column extension point for Phase 83

</code_context>

<specifics>
## Specific Ideas

- **Renaissance design principle** enforced across all decisions: computation and governance are separate services; models are validated before they influence production; thresholds are configurable not hardcoded; complexity added only when data proves it's needed.
- **Per-TF pooled HMM models** — upgrade to per-(symbol,tf) in Phase 83+ when 90+ days data per instrument is available.
- **shadow_registry table** seeded in Phase 82 as the Phase 75 contract. Phase 75's `ShadowAuditorAgent` will inherit and expand it rather than rebuild.
- **DATA-02** should be executed as Plan 01 of Phase 82 (operational, 5-minute task). Result determines if DerivOsc/ACOsc remain in shadow or go live.

</specifics>

<deferred>
## Deferred Ideas

- **Per-(symbol,tf) HMM models** — Phase 83+ when 90+ days per-instrument data proves reduced error
- **AIContext prompt rendering of ctx fields** — Phase 83, after shadow validation gate passes
- **Provider lanes (earnings, macro, news)** — Phase 83+, depends on CTX schema from this phase
- **Full Shadow Governance automation (Phase 75)** — ShadowAuditorAgent reads shadow_registry evidence this phase creates
- **HMM drift-triggered retraining webhook** — Phase 83, once drift_monitor_service Kafka integration pattern is established

</deferred>

---

*Phase: 82 — ML Intelligence Quality & Qualitative Foundation*
*Context gathered: 2026-05-13*
