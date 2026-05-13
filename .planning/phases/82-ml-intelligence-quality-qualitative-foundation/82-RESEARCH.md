# Phase 82: ML Intelligence Quality & Qualitative Foundation — Research

**Researched:** 2026-05-13
**Domain:** HMM multi-TF inference, Baum-Welch training, regime gate soft multiplier, feature IC validation service, CTX qualitative schema
**Confidence:** HIGH — all findings verified directly against source code and migration files

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01: DATA-02 Gate Check** — Run `validate_alpha.py` for DerivOsc and ACOsc first (SQL gate then script). N ≥ 30 per (plugin, tf, regime_type). Pearson r > 0, p < 0.05. Pass → IS_SHADOW=False. Fail → IS_SHADOW=True.

**D-02: HMM Per-TF Instances** — Four instances: `smc_HMMRegime_1m` (lookback=200), `smc_HMMRegime_5m` (lookback=200), `smc_HMMRegime_15m` (lookback=150), `smc_HMMRegime_1h` (lookback=100). Output field names identical per TF. 1m instance is additive-unchanged.

**D-03: HMM Training Architecture** — `HMMTrainingAgent` (oneshot, separate from inference). Per-TF pooled models (4 files). Storage: `config/hmm_parameters_{tf}.json`. Hot-reload via SIGUSR1. Monthly timer `indicagent-hmm-training.timer`. Training data: `intelligence_features`, exclude `is_backfill=TRUE`.

**D-04: Regime Transition Early Detection** — New I4 fields: `hmm_regime_entropy` (Shannon entropy across 3 state probs) + `hmm_regime_velocity` (rate of change of dominant prob over last N bars). Soft multiplier replaces binary gate in `regime_gate.py` for 0.30–0.55 band. New Settings fields: `REGIME_PROB_MIN=0.30`, `REGIME_PROB_SOFT_MAX=0.55`. Prometheus counter: `regime_soft_gate_signals_total{band="soft"}`.

**D-05: FeatureValidationService** — Two layers: `FeatureValidationComputeAgent` (compute, oneshot timer) writes to `validation_results` table + `shadow_registry.promotion_evidence`. Phase 75 `ShadowAuditorAgent` acts on evidence (not this phase). Gate thresholds from `tools/validate_i6_backtest.py`: IC > 0.05, p < 0.01 Bonferroni, N ≥ 30 = VALIDATED. API endpoint: `GET /api/validation/results`. Timer: `indicagent-feature-validation.timer` daily at 02:00 ET.

**D-06: CTX Schema Foundation** — Tables: `ctx_events` + `ctx_snapshots` (migration 085). `intelligence_features.ctx` JSONB column. `CtxWriterAgent` (L6, BaseWriterAgent pattern). `topic_ctx_snapshot()` in stream_keys.py. Feature writer resolves active ctx_snapshot at bar insert time via as-of join. Data collection only — no AIContext prompt rendering until Phase 83.

### Claude's Discretion

- Placement of multi-TF HMM instances: TIER_SMC (current) or move 1m to TIER_I4 and add others. Context recommends TIER_I4 placement for all four — low-priority choice.
- N for `hmm_regime_velocity` window: design doc suggests `{1m: 5, 5m: 5, 15m: 4, 1h: 3}`. TF-adaptive.
- `validation_results` hypertable chunk interval (daily timer, low cardinality — 1 month is reasonable).

### Deferred Ideas (OUT OF SCOPE)

- Per-(symbol,tf) HMM models — Phase 83+ when 90+ days per-instrument data proves reduced error
- AIContext prompt rendering of ctx fields — Phase 83, after shadow validation gate passes
- Provider lanes (earnings, macro, news) — Phase 83+
- Full Shadow Governance automation (Phase 75) — ShadowAuditorAgent reads evidence created here
- HMM drift-triggered retraining webhook — Phase 83
</user_constraints>

---

## Summary

Phase 82 addresses five orthogonal but sequenced improvements across two concerns: ML quality hardening (DATA-02, HMM multi-TF, regime transition, feature validation) and qualitative foundation (CTX schema + writer). Every component either corrects a structural defect (1m-only HMM, binary gate) or establishes infrastructure the next phase will activate (ctx tables, validation evidence).

The code is clean and extensible. `HMMRegimePlugin` is a self-contained dataclass with `_load_parameters()` already set up for external config files — parameterizing it for per-TF instances requires minimal surgery. `regime_gate.py` is a pure function already extracting `hmm_regime_prob` from the features dict — the soft multiplier drops in without service boundary changes. The `BaseWriterAgent` pattern used by `lifecycle_writer_agent.py` is the direct template for `CtxWriterAgent`. The `MLTrainingComputeAgent` + `ml_training_agent.py` oneshot pattern is the direct template for both `HMMTrainingAgent` and `FeatureValidationComputeAgent`.

The critical sequencing constraint: DATA-02 is operational (5 minutes, run first), then HMM multi-TF (no new dependencies), then regime transition (depends on new HMM fields), then feature validation (new table + timer), then CTX schema (new tables + writer). Each plan is independently mergeable.

**Primary recommendation:** Execute DATA-02 first as Plan 01 (gate check + promote/demote), then HMM multi-TF + training (Plans 02–03), then regime soft gate (Plan 04), then feature validation (Plan 05), then CTX schema (Plan 06).

---

## Current State Per Requirement

### P82-DATA02: DATA-02 Gate

**What exists:** `production/scripts/validate_alpha.py` (988 lines, full implementation). `shadow_registry` table exists (migration 077). `signal_ledger` has `outcome` column. Script supports `--plugin`, `--promote`, `--days` flags.

**What's needed:** Run the gate SQL, execute the script for both plugins, update `shadow_registry.is_shadow` based on result. Document outcome in plan summary. No code changes required — this is purely operational.

**Key constraint:** The SQL in D-01 uses `plugin_name IN ('trad_DerivativeOscillator','trad_ACOscillator')` — verify actual plugin name strings match the `shadow_registry.component_name` values before running promote.

### P82-HMM-MULTITF: HMM Multi-TF Instances

**What exists:**
- `src/intelligence/features/smc_context/hmm_regime.py` — `HMMRegimePlugin` dataclass with `name`, `inputs`, `outputs`, `min_lookback`. Currently hardcodes `name = "smc_HMMRegime"` and `inputs = (InputSpec(symbol=".*", timeframe="1m", lookback=200),)`.
- `_load_parameters()` reads `config/hmm_parameters.json` at `__post_init__`. No TF suffix logic.
- Plugin registered as `hmm_plugin` in `register_plugins.py`, placed in `TIER_SMC` (line 503).
- Single global `plugin = HMMRegimePlugin()` instance at module bottom.

**What's needed:**
1. Parameterize `HMMRegimePlugin.__init__` to accept `timeframe: str` and `lookback: int`, setting `self.name` and `self.inputs` from them.
2. Extend `_load_parameters()` (or add a method) to load `config/hmm_parameters_{tf}.json` if present, falling back to the base file, then defaults.
3. Create 4 plugin instances in `register_plugins.py`: `hmm_1m_plugin`, `hmm_5m_plugin`, `hmm_15m_plugin`, `hmm_1h_plugin`.
4. Add all 4 to `TIER_SMC` (or move to `TIER_I4` — see discretion note below).
5. Add `hmm_regime_entropy` and `hmm_regime_velocity` to `outputs` frozenset (per D-04, these are computed in the plugin, not separately).
6. Update `SMCContext` (or whichever schema class holds HMM fields) — currently `SMCContext` in `schemas.py` holds `hmm_regime`, `hmm_regime_prob`, etc. at lines 645–653. With 4 TF instances, output field collision must be handled: since each instance runs in its own TF frame, the pipeline processes them in their respective TF lanes — no collision as long as the pipeline maps each TF's SMC/I4 output to that TF's feature dict.

**Tier placement decision:** Currently in `TIER_SMC`. The design doc says HMM is "more naturally I4." Keeping in `TIER_SMC` requires no tier refactor. Moving to `TIER_I4` means adding 4 names to `TIER_I4` and removing `hmm_plugin` from `TIER_SMC`. The planner should decide and document — both work. Moving to I4 is semantically correct and aligns with `I4Context`'s docstring.

**Schema impact:** `SMCContext` already holds the HMM fields. If HMM moves to `TIER_I4`, the outputs need to move from `SMCContext` to `I4Context`. `I4Context` has `model_config = ConfigDict(extra="forbid")` — fields must be explicitly added. `SMCContext` does NOT have `extra="forbid"`, so new fields there would not error. Moving to `I4Context` is the cleaner path but requires adding `hmm_regime_entropy` and `hmm_regime_velocity` to `I4Context` explicitly.

**Training dependency:** Per D-03, HMM instances start with default (or existing 1m) parameters. Training happens after multi-TF instances are live and accumulating data. The multi-TF plan does NOT wait for trained parameters.

### P82-HMM-TRAINING: HMMTrainingAgent

**What exists:**
- `services/ml_training_agent.py` — oneshot entrypoint pattern. Instantiates `MLTrainingComputeAgent`, calls `asyncio.run(agent.start())`.
- `src/intelligence/services/ml_training_compute_agent.py` — full training compute agent. Reads from DB, trains, writes artifacts, sends SIGUSR1 to target service.
- SIGUSR1 pattern in `services/alpha_swarm_agent.py` (lines 188–193, 409, 426) — `loop.add_signal_handler(_signal.SIGUSR1, self._on_sigusr1)` → `_reload_models()`.

**What's needed:**
1. `src/intelligence/services/hmm_training_compute_agent.py` — reads `intelligence_features` (per-TF, excluding `is_backfill=TRUE`), builds observation sequences using same `_build_observation()` logic, runs Baum-Welch via `hmmlearn.GaussianHMM`, writes `config/hmm_parameters_{tf}.json`, sends SIGUSR1 to `indicagent-intelligence-pipeline`.
2. `services/hmm_training_agent.py` — oneshot entrypoint (mirrors `ml_training_agent.py`).
3. `production/systemd/indicagent-hmm-training.service` + `indicagent-hmm-training.timer` — `Type=oneshot`, monthly cadence.
4. SIGUSR1 handler in `intelligence_pipeline_agent.py` to reload HMM parameters on running instances.
5. `hmmlearn` added to `requirements.txt` if not already present.

**Check:** Verify `hmmlearn` is in requirements — it may already be there from earlier HMM work.

### P82-REGIME-TRANSITION: Soft Multiplier + Entropy/Velocity Fields

**What exists:**
- `src/intelligence/pipeline/regime_gate.py` — pure function `apply_regime_gate(signals, regime_data, prob_min=0.30, dur_min=1, tf=None, recorder=None)`. The binary check at line 95: `if hmm_regime_prob < prob_min: regime_eligible = False`. `regime_data` is the flat features dict (passed from `intelligence_pipeline_agent.py` line 1332 as `features`).
- `src/config/settings.py` — already has `regime_prob_min: float = Field(default=0.30)` (line 172) and `regime_dur_min: int = Field(default=1)` (line 173). No `regime_prob_soft_max` yet.
- `src/observability/metrics.py` — metrics registration hub (no `regime_soft_gate_signals_total` yet).
- `HMMRegimePlugin._build_output()` — returns 8 fields, does NOT include `hmm_regime_entropy` or `hmm_regime_velocity`.
- `HMMRegimePlugin._state` dict tracks `alpha` (the 3-state probability vector) and `regime_duration`. No velocity history.

**What's needed:**
1. **In `hmm_regime.py`:**
   - Add `hmm_regime_entropy` computation in `_build_output()` using Shannon entropy on `alpha` array.
   - Add velocity history to `_state` (a deque of recent `hmm_regime_prob` values, TF-adaptive length N).
   - Compute `hmm_regime_velocity = (alpha_prob[t] - alpha_prob[t-N]) / N` in `_build_output()`.
   - Add both to `outputs` frozenset and return from `_build_output()`.

2. **In `schemas.py`:** Add `hmm_regime_entropy: float | None = None` and `hmm_regime_velocity: float | None = None` to the class holding HMM fields (either `SMCContext` or `I4Context` depending on tier decision).

3. **In `settings.py`:** Add `REGIME_PROB_SOFT_MAX: float = Field(default=0.55, validation_alias="REGIME_PROB_SOFT_MAX")`.

4. **In `regime_gate.py`:** Replace binary check with three-band logic:
   - `prob < REGIME_PROB_MIN`: suppress (unchanged)
   - `REGIME_PROB_MIN <= prob < REGIME_PROB_SOFT_MAX`: apply `entropy_multiplier` soft confidence reduction
   - `prob >= REGIME_PROB_SOFT_MAX`: full confidence (unchanged)
   - Soft band signals set `regime_eligible = True` but signal dict gets `calibrated_confidence *= multiplier`.
   - Record `band="soft"` in Prometheus counter.

5. **In `metrics.py`:** Register `regime_soft_gate_signals_total` counter.

6. **`apply_regime_gate` signature change:** Add `prob_soft_max: float` and `entropy: float | None` parameters, or read from `regime_data`. Simplest: read `hmm_regime_entropy` from the features dict (regime_data), add `prob_soft_max` as a parameter (set from `settings.REGIME_PROB_SOFT_MAX` in `intelligence_pipeline_agent.py` call site).

### P82-FEATURE-VALIDATION: FeatureValidationService

**What exists:**
- `tools/validate_i6_backtest.py` — `ValidationResults` dataclass + `validate_backtest_results(df, field_name, min_ic=0.05, alpha=0.01, min_n=30)`. Returns VALIDATED/TWEAK/KILL decisions.
- `shadow_registry` table (migration 077) — has `last_eval_*` columns but NO `promotion_evidence` column. The CONTEXT.md D-05 says the agent writes to `shadow_registry.promotion_evidence` — this column does NOT exist yet. It must be added via migration.
- No `validation_results` table exists (confirmed: not in any migration file).
- No `FeatureValidationComputeAgent` exists (confirmed: no file in `src/` or `services/`).
- `GET /api/validation/results` endpoint does not exist.

**What's needed:**
1. **Migration 085 (or split off as 086):** Create `validation_results` hypertable (schema per D-05). Also `ALTER TABLE shadow_registry ADD COLUMN IF NOT EXISTS promotion_evidence JSONB` for the evidence field the agent writes.
2. `src/intelligence/services/feature_validation_compute_agent.py` — daily IC/p-value computation. Reads `intelligence_features` + `signal_ledger` (outcomes). Imports `validate_backtest_results` from `tools/validate_i6_backtest.py`. Writes rows to `validation_results`. Updates `shadow_registry.promotion_evidence` JSONB with latest decision.
3. `services/feature_validation_agent.py` — oneshot entrypoint.
4. `production/systemd/indicagent-feature-validation.service` + `indicagent-feature-validation.timer` (daily 02:00 ET).
5. `src/api/` — add `GET /api/validation/results` route returning latest per-plugin decisions from `validation_results`.

**Note on shadow_registry component_type:** Current schema has `CHECK (component_type IN ('i7_plugin', 'swarm_agent'))`. Adding 'i6_plugin' or 'feature' may require a constraint modification. Validate this before writing the migration.

### P82-CTX-SCHEMA: CTX Schema Foundation

**What exists:**
- No `ctx_events` or `ctx_snapshots` tables (confirmed: not in any migration).
- No `topic_ctx_snapshot()` in `stream_keys.py` (confirmed: no `ctx` topic functions).
- No `CtxWriterAgent` (confirmed: not in `services/`).
- No `ctx` column in `intelligence_features` (no migration adding it).
- `feature_writer_agent.py` does not reference `ctx` at all.

**What's needed:**
1. **Migration 085 (or 086):** Create `ctx_events` + `ctx_snapshots` tables per D-06 schema. `ALTER TABLE intelligence_features ADD COLUMN IF NOT EXISTS ctx JSONB`.
2. `src/core/stream_keys.py`: Add `topic_ctx_snapshot(env_name: str) -> str` returning `f"{env_prefix(env_name)}ctx.snapshot"`.
3. `services/ctx_writer_agent.py` — `CtxWriterAgent(BaseWriterAgent)`. Consumes `topic_ctx_snapshot()`. Writes to `ctx_events` + `ctx_snapshots` (open the previous snapshot's `valid_to` on new write). DAG layer L6.
4. `services/feature_writer_agent.py` — add as-of join logic at bar insert time to resolve `ctx_snapshots` → set `intelligence_features.ctx`. The INSERT SQL at line 63 must include `ctx` column. The as-of join SQL is documented in `qualitative-intelligence-layer.md`.
5. Add `indicagent-ctx-writer` to `_DAG_ORDER` in `service_auditor_agent.py` at layer 6.

---

## Migration Number

**Next available migration: 085**

Confirmed: `production/migrations/084_ai_enrichment_tables.sql` is the current highest. Migration 085 is free.

**Recommended split:**
- `085_ctx_schema.sql` — `ctx_events`, `ctx_snapshots`, `intelligence_features.ctx` column
- `086_validation_results.sql` — `validation_results` hypertable + `shadow_registry.promotion_evidence` column

Alternatively both in 085 if kept together. Split is cleaner for rollback isolation.

---

## Standard Stack

| Component | Library/Pattern | Source | Confidence |
|-----------|----------------|--------|------------|
| HMM inference | Custom forward algorithm in `hmm_regime.py` (numpy) | Verified | HIGH |
| HMM training | `hmmlearn.GaussianHMM` (Baum-Welch) | Design doc + hmmlearn API | HIGH |
| IC/p-value | `scipy.stats.pearsonr` (already in `tools/validate_i6_backtest.py`) | Verified | HIGH |
| Oneshot timer pattern | `ml_training_agent.py` + `MLTrainingComputeAgent` | Verified | HIGH |
| Writer agent pattern | `lifecycle_writer_agent.py` + `BaseWriterAgent` | Verified | HIGH |
| SIGUSR1 hot-reload | `alpha_swarm_agent.py` lines 188–193 | Verified | HIGH |
| Soft gate math | `lerp(0.5, 1.0, (prob - 0.30) / (0.55 - 0.30))` | Design doc + regime_gate.py | HIGH |
| Shannon entropy | `H = -sum(p * log2(p))` (numpy, no external lib) | Design doc | HIGH |
| TimescaleDB hypertable | `SELECT create_hypertable(table, 'ts_col')` | Existing migrations | HIGH |
| Metrics registration | `src/observability/metrics.py` | Verified | HIGH |

**Installation (likely already present, verify):**
```bash
uv pip show hmmlearn  # Check if present
uv pip install hmmlearn  # If missing
```

---

## Architecture Patterns

### Recommended Plan Decomposition (5–6 PLAN.md files)

```
Plan 01: DATA-02 Gate (operational)
  - Gate SQL check + validate_alpha.py execution + shadow_registry update
  - Dependency: none (run first, 5 min)
  - Owner: human executes script, documents result

Plan 02: HMM Multi-TF Instances
  - Parameterize HMMRegimePlugin + 4 instances + register_plugins.py + schema fields
  - Dependency: none (additive)
  - Also: add hmm_regime_entropy + hmm_regime_velocity fields (needed by Plan 04)

Plan 03: HMM Training Pipeline
  - HMMTrainingComputeAgent + hmm_training_agent.py + systemd timer + SIGUSR1 handler
  - Dependency: Plan 02 (multi-TF instances must be live before training makes sense)
  - hmmlearn dependency check

Plan 04: Regime Soft Gate
  - regime_gate.py soft multiplier + settings.REGIME_PROB_SOFT_MAX + metrics counter
  - Dependency: Plan 02 (hmm_regime_entropy field must exist in features dict)

Plan 05: FeatureValidationService
  - Migrations 085/086 + FeatureValidationComputeAgent + systemd timer + API endpoint
  - Dependency: none (independent schema + service)

Plan 06: CTX Schema Foundation
  - Migration 085 (ctx tables) + stream_keys + CtxWriterAgent + feature_writer as-of join
  - Dependency: none (fully additive)
```

### Dependency Graph

```
Plan 01 (DATA-02)        — standalone, run first
Plan 02 (HMM Multi-TF)  — standalone (additive to existing)
Plan 03 (HMM Training)  — after Plan 02 (needs multi-TF instances live)
Plan 04 (Soft Gate)     — after Plan 02 (needs entropy field)
Plan 05 (Feature Valid.) — standalone
Plan 06 (CTX Schema)    — standalone

Merge order: 01 → 02 → (03 + 04 parallel) → (05 + 06 parallel)
```

### HMMRegimePlugin Parameterization Pattern

```python
# src/intelligence/features/smc_context/hmm_regime.py

@dataclass
class HMMRegimePlugin:
    timeframe: str = "1m"
    lookback: int = 200
    name: str = field(init=False)
    inputs: tuple[InputSpec, ...] = field(init=False)

    def __post_init__(self) -> None:
        self.name = f"smc_HMMRegime_{self.timeframe}"
        self.inputs = (InputSpec(symbol=".*", timeframe=self.timeframe, lookback=self.lookback),)
        tf_config = Path(f"config/hmm_parameters_{self.timeframe}.json")
        base_config = Path("config/hmm_parameters.json")
        self._A, self._means, self._variances = _load_parameters(tf_config if tf_config.exists() else base_config)
        self._K = self._A.shape[0]

# register_plugins.py
hmm_1m_plugin  = HMMRegimePlugin(timeframe="1m",  lookback=200)
hmm_5m_plugin  = HMMRegimePlugin(timeframe="5m",  lookback=200)
hmm_15m_plugin = HMMRegimePlugin(timeframe="15m", lookback=150)
hmm_1h_plugin  = HMMRegimePlugin(timeframe="1h",  lookback=100)
```

### Soft Gate Multiplier Pattern

```python
# src/intelligence/pipeline/regime_gate.py (modified section)

SOFT_BAND_FLOOR = 0.5  # minimum multiplier at prob == prob_min boundary

def _entropy_multiplier(prob: float, prob_min: float, prob_soft_max: float) -> float:
    """Linear interpolation from 0.5 to 1.0 across the soft band."""
    t = (prob - prob_min) / (prob_soft_max - prob_min)
    return SOFT_BAND_FLOOR + (1.0 - SOFT_BAND_FLOOR) * max(0.0, min(1.0, t))

# In apply_regime_gate():
if hmm_regime_prob < prob_min:
    regime_eligible = False
    suppression_reason = "regime_prob"
elif hmm_regime_prob < prob_soft_max:
    # Soft band: reduce confidence, still eligible
    multiplier = _entropy_multiplier(hmm_regime_prob, prob_min, prob_soft_max)
    s["calibrated_confidence"] = s.get("calibrated_confidence", s.get("confidence", 0.5)) * multiplier
    suppression_reason = None
    REGIME_SOFT_GATE_SIGNALS_TOTAL.labels(band="soft").inc()
elif ...:  # existing regime_type check
```

### CTX Writer Pattern (from lifecycle_writer_agent.py)

```python
# services/ctx_writer_agent.py
class CtxWriterAgent(BaseWriterAgent):
    BATCH_SIZE = 50
    FLUSH_INTERVAL_SECS = 10.0

    async def _process_message(self, msg: dict) -> None:
        # Append to ctx_events
        # Upsert ctx_snapshots: INSERT + UPDATE prior valid_to
        ...
```

### As-Of Join in feature_writer_agent.py

```sql
-- Add to INSERT query at bar insert time
(
  SELECT jsonb_object_agg(event_type, ctx ORDER BY event_type)
  FROM ctx_snapshots
  WHERE (symbol = $1 OR symbol IS NULL)
    AND valid_from <= $bar_ts
    AND (valid_to IS NULL OR valid_to > $bar_ts)
) AS ctx_resolved
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Baum-Welch EM for HMM | Custom EM loop | `hmmlearn.GaussianHMM.fit()` |
| IC / p-value | Custom Pearson | `scipy.stats.pearsonr` (already in validate_i6_backtest.py) |
| Oneshot training service | Long-running daemon | `Type=oneshot` systemd + existing `ml_training_agent.py` pattern |
| Shannon entropy | Custom implementation | `numpy` one-liner: `-np.sum(p * np.log2(p + 1e-10))` |
| Writer agent | Custom consumer loop | `BaseWriterAgent` (lifecycle_writer_agent.py pattern) |
| SIGUSR1 hot-reload | Custom IPC | `loop.add_signal_handler(_signal.SIGUSR1, ...)` (alpha_swarm pattern) |
| Bonferroni correction | Custom p-value adjustment | Already in `validate_i6_backtest.py` (multiply alpha by n_tests) |

---

## Common Pitfalls

### Pitfall 1: HMM Output Field Naming Collision Between TF Instances

**What goes wrong:** Four `HMMRegimePlugin` instances all output fields named `hmm_regime`, `hmm_regime_prob`, etc. If the pipeline merges their outputs into a single dict, later instances overwrite earlier ones.

**Why it happens:** The plugin system accumulates outputs from all plugins at a given tier into a single feature dict. If all four HMM instances are in the same tier and same TF frame, only the last one's output survives.

**How to avoid:** Each TF instance uses `InputSpec(timeframe="X")` — the pipeline only runs a plugin against bars matching its TF. The 5m HMM runs when processing 5m bars; the 1m HMM runs for 1m bars. Verify `intelligence_pipeline_agent.py`'s per-TF dispatch logic correctly routes each HMM instance to its target TF — do not place all four in the same wave execution for the same bar TF.

**Warning signs:** All 4 HMM instances producing identical output values in `intelligence_features`.

### Pitfall 2: `I4Context(extra="forbid")` Rejects New HMM Fields

**What goes wrong:** If `hmm_regime_entropy` and `hmm_regime_velocity` are added to HMM plugin outputs but NOT added to `I4Context` (or `SMCContext`), the `model_validate()` call in `intelligence_pipeline_agent.py` line 925 raises `ValidationError` and the pipeline crashes.

**Why it happens:** `I4Context` has `model_config = ConfigDict(extra="forbid")`. `SMCContext` does not — so if HMM stays in TIER_SMC, new fields added to SMCContext require no config change but fields must still be declared.

**How to avoid:** Add `hmm_regime_entropy: float | None = None` and `hmm_regime_velocity: float | None = None` to the correct schema class before enabling the new outputs. Also update the field count in the docstring comment.

**Warning signs:** `ValidationError: extra fields not permitted` in `intelligence_pipeline_agent.log`.

### Pitfall 3: `shadow_registry.component_type` CHECK Constraint Rejects New Plugin Types

**What goes wrong:** `FeatureValidationComputeAgent` tries to write to `shadow_registry.promotion_evidence` but the migration adding that column may also need to handle `component_type` values like `'i6_feature'` not in the current CHECK constraint.

**Why it happens:** Migration 077 defines `CHECK (component_type IN ('i7_plugin', 'swarm_agent'))`. The validation service registers I6 plugins in the shadow_registry — those plugins may already be registered with type `'i7_plugin'` if they fire signals. Verify actual component_type values before writing.

**How to avoid:** Check `SELECT DISTINCT component_type FROM shadow_registry` before writing the migration. Decide whether to expand the CHECK or use an existing type.

### Pitfall 4: ctx As-Of Join Adds Latency to Feature Writer

**What goes wrong:** The as-of query against `ctx_snapshots` runs per-bar during the hot write path of `feature_writer_agent.py`. If `ctx_snapshots` is large or unindexed, this adds measurable latency to `intelligence_features` writes.

**Why it happens:** The feature writer currently does one INSERT per bar (line 63). Adding a correlated subquery for ctx resolution runs that subquery on the write hot-path.

**How to avoid:** Ensure `CREATE INDEX ON ctx_snapshots (symbol, valid_from, valid_to)` is in the migration (documented in the design doc). Since Phase 82 has no actual ctx data yet (no provider lanes), the query will return NULL for every bar — effectively zero cost in Phase 82. Performance matters in Phase 83+ when providers start writing.

**Warning signs:** `feature_writer.log` showing increased batch flush latency after Phase 82 deployment.

### Pitfall 5: HMM Training Data Has `is_backfill=TRUE` Rows

**What goes wrong:** Training includes historical backfill rows which may have different statistical properties than live data (gaps, different market conditions, synthetic bars).

**Why it happens:** Phase 81 added `is_backfill` column to `intelligence_features`. The training query must explicitly filter it out.

**How to avoid:** Every query in `HMMTrainingComputeAgent` must include `WHERE is_backfill IS NOT TRUE`. Add this as a unit-tested assertion.

### Pitfall 6: `promotion_evidence` Column Does Not Exist Yet

**What goes wrong:** `FeatureValidationComputeAgent` tries to UPDATE `shadow_registry SET promotion_evidence = ...` but the column was never added (migration 077 doesn't have it).

**How to avoid:** The Plan 05 migration must `ALTER TABLE shadow_registry ADD COLUMN IF NOT EXISTS promotion_evidence JSONB`. Execute before the service runs.

---

## Validation Architecture

### Plan 01: DATA-02 Gate

- Manual validation: confirm `SELECT COUNT(*) FROM signal_ledger WHERE plugin_name IN (...) AND outcome IS NOT NULL` matches gate requirement before running script.
- Verify `shadow_registry` row for each plugin reflects correct `is_shadow` value after script completes.

### Plan 02: HMM Multi-TF Instances

- Unit test: instantiate `HMMRegimePlugin(timeframe="5m", lookback=200)` — assert `name == "smc_HMMRegime_5m"` and `inputs[0].timeframe == "5m"`.
- Unit test: `compute_full()` returns `hmm_regime_entropy` and `hmm_regime_velocity` in output dict.
- Unit test: 4 instances produce `name` values `["smc_HMMRegime_1m", "smc_HMMRegime_5m", "smc_HMMRegime_15m", "smc_HMMRegime_1h"]`.
- Integration: `pytest tests/unit/test_intelligence_pipeline_agent.py` must remain clean.
- Integration: after restart, `intelligence_features` rows for 5m bars contain `hmm_regime_entropy` (not NULL) in the `smc` JSONB tier.

### Plan 03: HMM Training Pipeline

- Unit test: `HMMTrainingComputeAgent` with mock `intelligence_features` rows produces 3-state GaussianHMM and writes `config/hmm_parameters_5m.json`.
- Validate JSON output schema: keys `transition_matrix`, `emission_means`, `emission_variances` with correct shapes.
- Semantic check: trained state 1 (`trending_up`) has higher mean return component than state 0 (`ranging`).
- Systemd test: `systemctl start indicagent-hmm-training` exits 0.

### Plan 04: Regime Soft Gate

- Unit test `regime_gate.py`: signal with `hmm_regime_prob=0.42` (in soft band) gets `regime_eligible=True` and `calibrated_confidence < original_confidence`.
- Unit test: signal with `hmm_regime_prob=0.25` still gets `regime_eligible=False, suppression_reason="regime_prob"`.
- Unit test: signal with `hmm_regime_prob=0.70` gets `regime_eligible=True` with no confidence modification.
- Prometheus: `regime_soft_gate_signals_total{band="soft"}` counter increments in live run.
- Regression: existing unit tests for `regime_gate.py` must all pass unchanged for signals outside soft band.

### Plan 05: FeatureValidationService

- Unit test: `validate_backtest_results()` called with mock DataFrame returns correct VALIDATED/TWEAK/KILL.
- Integration: `validation_results` table exists after migration, hypertable verified with `\d validation_results`.
- Integration: `shadow_registry.promotion_evidence` column exists after migration.
- API: `GET /api/validation/results` returns 200 with JSON list (empty initially).
- Systemd: `systemctl start indicagent-feature-validation` exits 0.

### Plan 06: CTX Schema Foundation

- Migration test: `\d ctx_events`, `\d ctx_snapshots` show correct columns and hypertable.
- `intelligence_features` test: `\d intelligence_features` shows `ctx jsonb` column.
- Unit test `ctx_writer_agent.py`: publish mock `topic_ctx_snapshot` message → assert `ctx_events` row inserted and `ctx_snapshots` upserted with correct `valid_to` on prior row.
- Integration: `feature_writer_agent.py` inserts bar with `ctx=NULL` (no snapshots yet) without error.
- Stream key test: `topic_ctx_snapshot("dev") == "dev.ctx.snapshot"`.
- `service_auditor_agent.py`: `indicagent-ctx-writer` present in `_DAG_ORDER`.

---

## Open Questions

1. **HMM tier placement decision**
   - What we know: currently in `TIER_SMC`, design doc recommends `TIER_I4`, both work.
   - What's unclear: moving to `TIER_I4` requires moving HMM fields from `SMCContext` to `I4Context` in schemas.py — larger schema change.
   - Recommendation: Keep in `TIER_SMC` for Phase 82 (minimizes schema churn). Document intent to move in Phase 83.

2. **`shadow_registry.component_type` CHECK expansion**
   - What we know: current CHECK only allows `'i7_plugin'` and `'swarm_agent'`.
   - What's unclear: what component_type value the FeatureValidationComputeAgent should use when writing `promotion_evidence`. It may write for I6 plugin features that are already registered under `'i7_plugin'` if they have signals in `signal_ledger`.
   - Recommendation: Query `SELECT DISTINCT component_type, component_name FROM shadow_registry` at Plan 05 start to determine actual values before writing migration.

3. **`hmmlearn` already in requirements?**
   - What we know: custom forward algorithm exists; training was always the plan per design doc.
   - What's unclear: whether `hmmlearn` was ever added to `requirements.txt`.
   - Recommendation: Check `grep hmmlearn requirements.txt` as first task of Plan 03.

4. **How regime_gate.py receives `prob_soft_max`**
   - What we know: `apply_regime_gate` currently takes `prob_min` as an explicit parameter, set from `settings.regime_prob_min` at the call site in `intelligence_pipeline_agent.py`.
   - Recommendation: Add `prob_soft_max: float = 0.55` parameter to `apply_regime_gate` and pass `settings.REGIME_PROB_SOFT_MAX` from the call site. Avoids importing Settings inside the pure function.

---

## Sources

### PRIMARY (HIGH confidence — verified against source code)
- `src/intelligence/features/smc_context/hmm_regime.py` — Full HMMRegimePlugin implementation, `_load_parameters()`, `_build_output()`, `_state` structure
- `src/intelligence/pipeline/regime_gate.py` — Binary gate logic, parameter interface, TransformRecorder usage
- `src/intelligence/register_plugins.py` lines 497–520 — `TIER_SMC` and `TIER_I4` contents, `hmm_plugin` registration
- `src/intelligence/schemas.py` lines 268–476, 645–653 — `I4Context`, `SMCContext`, HMM field locations
- `src/config/settings.py` lines 172–173 — `regime_prob_min`, `regime_dur_min` already exist
- `production/migrations/` directory listing — confirmed 084 is highest, 085 is next
- `production/migrations/077_shadow_governance.sql` — `shadow_registry` schema, no `promotion_evidence` column
- `services/lifecycle_writer_agent.py` — `BaseWriterAgent` pattern
- `services/ml_training_agent.py` + `src/intelligence/services/ml_training_compute_agent.py` — oneshot pattern, SIGUSR1 emit
- `services/alpha_swarm_agent.py` lines 188–193 — SIGUSR1 handler pattern for hot-reload
- `services/intelligence_pipeline_agent.py` lines 1332–1338 — `apply_regime_gate` call site, `features` dict as `regime_data`
- `services/feature_writer_agent.py` — INSERT SQL, no ctx handling, as-of join extension point
- `tools/validate_i6_backtest.py` — `ValidationResults`, `validate_backtest_results()`, VALIDATED/TWEAK/KILL thresholds
- `production/scripts/validate_alpha.py` lines 1–65 — full validate_alpha, --promote flag

### SECONDARY (HIGH confidence — design documents)
- `docs/ideas/hmm-multi-tf-and-training.md` — per-TF lookback table, Baum-Welch training design, parameter file format
- `docs/ideas/regime-transition-early-detection.md` — entropy/velocity math, soft gate lerp formula, phase taxonomy
- `docs/plans/2026-05-02-unified-intelligence-design.md` — CTX domain ownership, integration rules
- `docs/ideas/qualitative-intelligence-layer.md` — ctx_events/ctx_snapshots schema, as-of join SQL, topic design, CtxWriterAgent

---

## Metadata

**Confidence breakdown:**
- DATA-02 gate: HIGH — script exists, shadow_registry exists, operational only
- HMM Multi-TF: HIGH — plugin code fully read, parameterization path clear
- HMM Training: HIGH — training compute agent pattern verified in ml_training_compute_agent.py; hmmlearn availability unverified (LOW for that specific item)
- Regime soft gate: HIGH — pure function, math is trivial, all integration points verified
- FeatureValidationService: HIGH — validate_backtest_results imports confirmed; `promotion_evidence` column absence confirmed (must be added in migration)
- CTX Schema: HIGH — no existing infrastructure confirmed, full design available

**Research date:** 2026-05-13
**Valid until:** 2026-06-13 (30 days — stable project, no external dependency churn)
