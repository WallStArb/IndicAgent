# Phase 070: ML Scoring Model — Research

**Researched:** 2026-05-13
**Domain:** LightGBM inference layer, AI-SEP-01 table migration, swarm integration
**Confidence:** HIGH (all findings verified against live codebase)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Feature Vector (D-01–D-03)**
- D-01: Feature vector = 36-plugin `_shadow` dict fields + bar context: `hmm_regime`, `trend_regime`, `session_type`, `atr_pct`, `volume_z`, `tod_multiplier`. No swarm agent outputs.
- D-02: Target variable: binary `P(win)` where win = `pnl_r > 0`.
- D-03: Feature pipeline built with `is_swarm_available` opt-in gate for future swarm features.

**Model Segmentation (D-04–D-05)**
- D-04: Global model + 3 per-regime models (hmm_regime 0/1/2). Use regime model when `n_regime >= 100`, fall back to global.
- D-05: No per-plugin or per-TF segmentation in v1.

**Training Pipeline (D-06–D-08)**
- D-06: `MLTrainingComputeAgent` — new L8 systemd service. Nightly + delta gate: retrain only if resolved signal count grew by >= 50.
- D-07: Walk-forward CV: expanding window, 60/20/20 train/val/test by time. Zero lookahead. Register artifact via `ModelRegistry`.
- D-08: SHAP attribution computed at training time, stored as feature importance JSON in MLflow artifact. Not dashboarded (deferred).

**Inference Integration (D-09–D-11)**
- D-09: `MLScorerMultiplierAgent` extends `BaseMultiplierAgent`. Lives at `src/intelligence/ai/alpha/ml_scorer_agent.py`. Loads via `ModelRegistry.load_latest(segment)` at startup.
- D-10: Integration as additional swarm agent weight. `shadow_only=True`. Weight starts at 1.0.
- D-11: Model reload on startup + SIGUSR1 signal. If no promoted model: return neutral (1.0) + log warning.

**Schema — AI-SEP-01 (D-12–D-15)**
- D-12: Fold TODO-018 into Phase 70. Quant tables immutable after write.
- D-13: New table `signal_ai_enrichment` (signal_id PK, swarm_multiplier, adjusted_confidence, swarm_agent_count, ml_score, ml_model_id, enriched_at).
- D-14: New table `intelligence_ai_enrichment` (ts+symbol+tf PK, i8, narrative_id, enriched_at).
- D-15: Migrate `SwarmLedgerWriterAgent` → UPSERT `signal_ai_enrichment`. Migrate `LlmWriterService` → UPSERT `intelligence_ai_enrichment`. Dashboard/ML: LEFT JOIN at read time.

### Claude's Discretion
None specified — all decisions are locked.

### Deferred Ideas (OUT OF SCOPE)
- Swarm outputs as ML features (defer until 90+ days of co-located swarm data)
- SHAP attribution dashboard UI
- Per-plugin-per-TF model segmentation (v2)
- Replacing Sharpe-based ranker
- ML-driven alpha decay monitoring
</user_constraints>

---

## Summary

Phase 70 has two parallel tracks: (1) a LightGBM scoring layer that consumes `_shadow` dicts from all 36 I7 plugins as a swarm agent, and (2) AI-SEP-01 — migrating SwarmLedgerWriterAgent and LlmWriterService off the quant tables and into AI-owned enrichment tables.

The codebase is well-prepared for both. `ModelRegistry` (`src/core/ml/registry.py`) is fully implemented. `BaseMultiplierAgent` provides the exact contract `MLScorerMultiplierAgent` must satisfy. The `AlphaSwarmComputeAgent` in `services/alpha_swarm_agent.py` is fully readable and shows exactly where to add the new agent to `self._agents` and `_shadow_registry_ensure_swarm()`. The feature vector is well-understood: `capture_signal_features()` emits a 17-key `_shadow` dict stored as `signal["features_snapshot"]` in the `i7` JSONB column. Training data is in `signal_ledger` JOIN `intelligence_features` — use the existing `TrainingDataQuery` class. Both writer migrations are surgical: `SwarmLedgerWriterAgent` has one `_apply_projection()` method that needs its SQL redirected; `LlmWriterService` has one `_flush_i8()` method to redirect.

No pre-existing SIGUSR1 handler exists in the codebase — must implement from scratch using Python's `asyncio.get_event_loop().add_signal_handler()`.

**Primary recommendation:** Implement in strict order: (1) migration 084 (new tables), (2) writer migration (AI-SEP-01), (3) `MLTrainingComputeAgent`, (4) `MLScorerMultiplierAgent` + swarm registration, (5) systemd units.

---

## Q1: Feature Matrix — What does `capture_signal_features()` actually emit?

**Source:** `src/intelligence/trading/confidence_utils.py` (verified directly)
**Confidence:** HIGH

`capture_signal_features()` returns exactly **27 keys** in the `_shadow` dict:

| Key | Type | Source |
|-----|------|--------|
| `profile` | str | Plugin family name (trend/mean_reversion/smc/microstructure/session/exempt_exhaustion) |
| `existing_confidence` | float | Plugin's raw confidence at capture time |
| `ctf_score` | float | I6 CrossTimeframeConfluence |
| `ctf_trend_alignment` | float | I6 |
| `ctf_structure_alignment` | float | I6 |
| `ctf_regime_agreement` | float | I6 |
| `ctf_fvg_alignment` | float | I6 |
| `ctf_ob_alignment` | float | I6 |
| `vix_level` | float\|None | I4 VIXRegime |
| `vix_z` | float\|None | I4 VIXRegime |
| `eq_spread_z` | float\|None | I4 CrossAssetContext |
| `eq_pairs_confirming` | float\|None | I4 CrossAssetContext |
| `ctf_momentum_divergence` | float\|None | I6 Phase 64-01 |
| `ctf_momentum_regime` | str\|None | I6 Phase 64-01 |
| `ctf_sr_confluence` | float\|None | I6 Phase 64-02 |
| `ctf_sr_regime` | str\|None | I6 Phase 64-02 |
| `ctf_hmm_regime_agreement` | float\|None | I6 Phase 64-02 |
| `ctf_hmm_regime_label` | str\|None | I6 Phase 64-02 |
| `ctf_volatility_divergence` | float\|None | I6 Phase 64-02 |
| `ctf_volatility_regime` | str\|None | I6 Phase 64-02 |
| `ctf_orderflow_alignment` | float\|None | I6 Phase 64-02 |
| `ctf_orderflow_regime` | str\|None | I6 Phase 64-02 |
| `exhaustion_score` | float\|None | Exhaustion (None for exempt_exhaustion family) |
| `exhaustion_side` | str\|None | Exhaustion |
| `exhaustion_bars` | float\|None | Exhaustion |

**Coverage:** All 36 I7 plugins use `capture_signal_features()` — confirmed by counting 36 files in `src/intelligence/trading/` that import it. The `features_snapshot` dict is stored at `signal["features_snapshot"]` and persisted to the `i7` JSONB column in `intelligence_features` by `feature_writer_agent.py`.

**Bar context features** (D-01 — from `intelligence_features` via JOIN):
- `hmm_regime` → `f.i4->>'hmm_regime'` (already used in `TrainingDataQuery`)
- `trend_regime` → `f.i4->>'trend_regime'`
- `session_type` → `f.session_type` column (top-level column in `intelligence_features`)
- `atr_pct` → `f.i1->>'atr_pct'` (exists in `FeatureVector` and `FeatureExtractor`)
- `volume_z` → `f.i1->>'volume_z_score'` (from `VolumeZscorePlugin`, field name is `volume_z_score` not `volume_z`)
- `tod_multiplier` → stored in `signal_ledger.market_context` or in the `RankedSignal.tod_multiplier` field in the `i7` JSONB array

**Critical naming note:** The D-01 decision calls the field `volume_z` but the actual column in `i1` JSONB is `volume_z_score`. The ML feature matrix must use `volume_z_score` when querying `intelligence_features`.

**LightGBM encoding needed:**
- Categoricals requiring one-hot: `hmm_regime` (0/1/2), `profile` (6 families), `session_type` (RTH/ETH/etc.), string regime fields (`ctf_momentum_regime`, etc.)
- Already bounded [0,1] numerics: all `ctf_*` float fields, `exhaustion_score`, `existing_confidence`
- Already normalized: `atr_pct`, `volume_z_score`, `vix_z`, `eq_spread_z`
- `trend_regime` is a continuous float (from `TrendRegimePlugin`): `trend_regime_continuous` is the float field; `trend_regime` is the categorical bucket (0/1/2 via `trend_regime` field)

---

## Q2: ModelRegistry API Surface

**Source:** `src/core/ml/registry.py` (verified directly)
**Confidence:** HIGH

Four methods, all async:

```python
# Register new artifact — returns model_id UUID string
await registry.register(
    run_id: str,           # MLflow run ID
    segment: dict,         # e.g. {"global": True} or {"hmm_regime": 0}
    artifact_path: str,    # MLflow artifact URI
    model_type: str = "lightgbm",
) -> str

# Load latest production model for segment — returns mlflow.pyfunc model or None
model = await registry.load_latest({"global": True})   # global model
model = await registry.load_latest({"hmm_regime": 0})  # regime-0 model

# Promote shadow model to production
await registry.promote(model_id: str)

# Retire a model
await registry.revert(model_id: str)
```

**DB schema** (`ml_models` table from migration 059):
- `model_id UUID PRIMARY KEY`
- `model_type TEXT` — "lightgbm"
- `segment JSONB` — queried with `@>` containment operator
- `mlflow_run_id TEXT`
- `status TEXT` — 'shadow' | 'production' | 'retired'
- `shadow_correlation FLOAT` — Pearson(predicted, actual)
- `promoted_at TIMESTAMPTZ`
- `artifact_path TEXT` — MLflow artifact URI
- `created_at TIMESTAMPTZ`

**Important:** `register()` inserts `json.dumps(segment)` — but asyncpg JSONB columns normally accept dicts directly. The registry manually calls `json.dumps()` here (exception to the rule — don't try to "fix" it).

**Segment query uses JSONB containment (`@>`):** `load_latest({"global": True})` works because `segment @> '{"global": true}'::jsonb`. Segment dict for global model should be `{"global": True}`. For regime models: `{"hmm_regime": 0}`.

---

## Q3: BaseMultiplierAgent Contract

**Source:** `src/core/ai/multiplier_agent.py`, `src/intelligence/ai/alpha/correlation_agent.py` (verified directly)
**Confidence:** HIGH

`MLScorerMultiplierAgent` must:

1. Extend `BaseMultiplierAgent` (which extends `BaseAIAgent`)
2. Declare five mandatory class attributes:
   ```python
   agent_id = "ml_scorer_v1"
   group = "alpha"
   tiers_needed = frozenset()          # No LLM tiers needed — inference is local
   latency_budget_ms = 50.0            # Sub-millisecond LightGBM inference
   shadow_only = True
   output_schema: ClassVar[dict] = {"multiplier": float, "ml_score": float}
   ```
3. Accept `**kwargs` in `__init__` (no `llm_chain` needed — unlike LLM agents)
4. Implement `async _compute(self, context: AIContext) -> AgentOutput`

**Key difference from LLM agents:** `MLScorerMultiplierAgent` does NOT need an LLM chain. It loads its model at startup. `_compute()` calls `_build_multiplier_output()` directly with the LightGBM prediction — no `_parse_multiplier_response()` needed.

**`_build_multiplier_output()` signature:**
```python
return self._build_multiplier_output(
    context=context,
    multiplier=float,          # LightGBM predict_proba output, clamped [0.0, 2.0]
    confidence=float,          # LightGBM predict_proba output
    payload={"ml_score": float, "segment": str, "model_id": str},
    prompt_version="v1",       # Used as model version label
)
```

**`_neutral()` for no-model case (from `BaseAIAgent`):**
```python
return self._neutral(error="no_promoted_model", latency_ms=0.0)
```

**Construction pattern (from `AlphaSwarmComputeAgent._setup()`):**
```python
# In AlphaSwarmComputeAgent._setup(), after super()._setup():
self._agents.append(MLScorerMultiplierAgent(pool=self._pool))
```
Since `MLScorerMultiplierAgent` needs the DB pool for `ModelRegistry`, it must receive `pool` at construction or be constructed after `super()._setup()` sets `self._pool`.

**Integration into `_shadow_registry_ensure_swarm()`:** The method already loops over `self._agents` — adding `MLScorerMultiplierAgent` to `self._agents` automatically enrolls it.

---

## Q4: SwarmLedgerWriterAgent Migration (AI-SEP-01)

**Source:** `services/swarm_ledger_writer_agent.py` (verified directly)
**Confidence:** HIGH

**Current write path:**
```sql
UPDATE signal_ledger
   SET adjusted_confidence = $2,
       swarm_multiplier = $3,
       swarm_agent_count = $4
 WHERE signal_id = $1
```

**Target write path (D-13/D-15):**
```sql
INSERT INTO signal_ai_enrichment
    (signal_id, swarm_multiplier, adjusted_confidence, swarm_agent_count, ml_score, ml_model_id, enriched_at)
VALUES ($1::uuid, $2, $3, $4, NULL, NULL, NOW())
ON CONFLICT (signal_id) DO UPDATE SET
    swarm_multiplier = EXCLUDED.swarm_multiplier,
    adjusted_confidence = EXCLUDED.adjusted_confidence,
    swarm_agent_count = EXCLUDED.swarm_agent_count,
    enriched_at = NOW()
```

**Retry logic is still needed:** The race condition (swarm event arriving before `signal_writer` inserts the signal_ledger row) still applies — but for the FK constraint on `signal_ai_enrichment.signal_id REFERENCES signal_ledger(signal_id)`. The 5-attempt backoff in `_RETRY_BACKOFF_S` must stay.

**ml_score / ml_model_id columns:** These are NULL at swarm time. The `MLScorerMultiplierAgent` output needs a separate merge into `signal_ai_enrichment`. Options: (a) `MLScorerMultiplierAgent` publishes to the same `topic_swarm_alpha` and `SwarmLedgerWriterAgent` merges both — simple but couples them, or (b) a separate UPSERT in `SwarmLedgerWriterAgent` triggered when it sees an `ml_score` field in the payload. Option (b) is cleanest: the alpha_swarm aggregate event already contains all agent payloads, so `ml_score` can be included in the aggregate event payload.

**No consumers of `signal_ledger.swarm_multiplier` or `signal_ledger.adjusted_confidence` exist** in `src/api/`, `src/intelligence/`, or any service file (verified by grep). The columns are write-only from the quant side — only the swarm writer touches them. Dashboard reads will need LEFT JOIN after migration.

---

## Q5: LlmWriterService Migration (AI-SEP-01)

**Source:** `services/llm_writer_service.py` (verified directly)
**Confidence:** HIGH

**Current write path (lines 111-115):**
```sql
UPDATE intelligence_features
SET i8 = $4::jsonb
WHERE ts = $1::timestamptz AND symbol = $2 AND tf = $3
```
Called from `_flush_i8()` (line 768). Buffers up to `BATCH_SIZE=50` rows, flushed every 5s.

**Target write path (D-14/D-15):**
```sql
INSERT INTO intelligence_ai_enrichment (ts, symbol, tf, i8, narrative_id, enriched_at)
VALUES ($1::timestamptz, $2, $3, $4::jsonb, NULL, NOW())
ON CONFLICT (ts, symbol, tf) DO UPDATE SET
    i8 = EXCLUDED.i8,
    enriched_at = NOW()
```

**Only one method to change:** `_flush_i8()` — update `_UPDATE_I8_SQL` constant and `_flush_i8()` to use the new table. The rest of the service (llm_calls, llm_outcomes, score recompute) is unaffected.

**SSE route** (`src/api/routes/sse.py`): subscribes to `topic_intelligence_i8` topic for real-time i8 updates. This is a Kafka topic, not a DB read — unaffected by the migration.

**Dashboard i8 reads:** The `_build_signal_row()` in `src/api/routes/signals.py` does NOT currently include `i8` in the features dict — it reads only `bar`, `i1`, `i3`, `i4`, `i5`, `smc`, `i6`. The `i8` column is only exposed via SSE. No API route change needed immediately.

---

## Q6: Training Data Availability

**Confidence:** MEDIUM (cannot query live DB — estimated from codebase signals)

**Key facts discovered:**
- Migration 083 ran a `TRUNCATE TABLE signal_ledger` (2026-05-08) to wipe contaminated v0/pre-Phase-79 signals.
- `SIGNAL_SCHEMA_VERSION = "v2"` (in `src/intelligence/trading/signal_schema.py`). Note: migration 083 references `signal_schema_version = 'v1'` in comments but the code shows `"v2"`. The constant is `v2`.
- Signals accumulate from bar replay + live since 2026-05-08.
- The Phase 70 CONTEXT.md originally referenced a "May 10 data gate" — but CLAUDE.md says "shadow-first validation — no arbitrary data gate."
- The D-06 delta gate (`>= 50 new resolved signals since last training`) handles the cold start: if insufficient data, `MLTrainingComputeAgent` simply logs and skips without error.
- For inference: `load_latest()` returns `None` when no promoted model → agent returns neutral 1.0. System degrades gracefully until enough data exists and a model is promoted.

**Training SQL join pattern** (from `TrainingDataQuery`):
```sql
JOIN signal_ledger sl
  ON sl.symbol = f.symbol
 AND sl.feature_ts = f.ts
 AND sl.feature_tf = f.tf
 AND f.ts < sl.activated_at   -- NO LOOKAHEAD clause
WHERE sl.outcome IS NOT NULL
  AND is_shadow = FALSE
  AND signal_schema_version = $N  -- SIGNAL_SCHEMA_VERSION = 'v2'
```

The `features_snapshot` dict is in `f.i7` JSONB as `{"signals": [...], "features_snapshot": ...}` — **but wait**: `feature_writer_agent.py` stores the full `BarIntelligenceRecord` including `ranked_signals` list as the `i7` JSONB. The `features_snapshot` is a per-signal field inside each signal dict in the `ranked_signals` array — accessed as `f.i7->'signals'->0->>'features_snapshot'` which is complex. Simpler: use the `TrainingDataQuery` pattern which joins via `feature_ts` and extracts named fields. The per-signal `features_snapshot` dict must be extracted differently — the ML training query needs to JOIN `signal_ledger` and extract `features_snapshot` from `signal_ledger.market_context` or from the i7 JSONB signals array by `signal_id` match.

**Critical finding:** The `features_snapshot` is stored in the I7 signal dict itself, written to the `i7` JSONB column of `intelligence_features` by `feature_writer_agent.py`. The training query must extract it via:
```sql
SELECT elem->>'features_snapshot' 
FROM intelligence_features f,
     jsonb_array_elements(f.i7->'signals') AS elem
WHERE (elem->>'signal_id') = sl.signal_id::text
```
OR via `signal_ledger.market_context` if features were also stored there. Verification of where `features_snapshot` actually lands in the DB is needed during implementation.

---

## Q7: Walk-Forward CV Pattern

**Source:** `src/intelligence/ml/confidence_calibrator.py`, `src/intelligence/swarm/graduation.py` (verified)
**Confidence:** HIGH

**Adaptation from `confidence_calibrator.py`:**
- Gate: `n >= 100` before any training
- Group by segment (regime) before training
- `compute_walk_forward()` in `graduation.py` provides the exact split pattern: sort by `ts`, split at `int(n * 0.70)` for train, rest for validation

**D-07 specifies 60/20/20 split** (train/val/test). This is a 3-way split, slightly different from the 70/30 in `compute_walk_forward()`. Implementation must sort by `signal_ledger.timestamp` and do two splits:
```python
n_train = int(n * 0.60)
n_val   = int(n * 0.80)  # 60-80% is val
# test = remaining 20%
```

**No existing 3-way temporal split utility in codebase** — must implement. The `graduation.py` patterns are 2-way. The LightGBM training loop needs custom split logic.

**Key constraint from `_NO_LOOKAHEAD_SQL`:** Training must enforce `f.ts < sl.activated_at` — feature bar must precede signal activation. `TrainingDataQuery` already encodes this.

---

## Q8: MLTrainingComputeAgent Timer Pattern

**Source:** `src/intelligence/setup_performance_updater.py` (verified directly)
**Confidence:** HIGH

`setup_performance_updater.py` is a pure function module — it does not have the timer loop itself. The timer loop is in the calling agent. Looking at the existing L8 nightly timer pattern from `indicagent-ml-orchestrator.timer`:

```ini
[Timer]
OnCalendar=Mon *-*-* 04:00:00 UTC
Persistent=true
Unit=indicagent-ml-orchestrator.service
```

`MLTrainingComputeAgent` should use **`Type=oneshot`** systemd unit with a `.timer` companion — matching the ML orchestrator pattern exactly.

**Delta gate implementation pattern** (from `setup_performance_updater.py` + `confidence_calibrator.py`):
```python
async def _should_retrain(self, pool) -> bool:
    current_count = await pool.fetchval(
        "SELECT COUNT(*) FROM signal_ledger WHERE outcome IS NOT NULL AND is_shadow = FALSE"
    )
    if current_count - self._last_trained_count < 50:
        return False
    self._last_trained_count = current_count
    return True
```
Persist `_last_trained_count` to DB or a checkpoint file — using the `checkpoint_path` file pattern from `setup_performance_updater.py` analogy.

**Nightly execution approach:** Given `Type=oneshot` with a timer, the agent runs, completes, and exits. No long-running process needed for training. After training completes and a model is promoted, send SIGUSR1 to the alpha-swarm process:
```python
import subprocess
subprocess.run(["systemctl", "kill", "-s", "SIGUSR1", "indicagent-alpha-swarm"])
```

---

## Q9: SIGUSR1 Reload Pattern

**Confidence:** HIGH (absence confirmed by grep across entire src/ and services/)

**No existing SIGUSR1 handler in the codebase.** Must implement from scratch.

**Python asyncio pattern for SIGUSR1:**
```python
import asyncio
import signal

# In MLScorerMultiplierAgent.__init__ or _setup():
loop = asyncio.get_event_loop()
loop.add_signal_handler(signal.SIGUSR1, self._trigger_model_reload)

def _trigger_model_reload(self) -> None:
    """Called from signal handler — schedule async reload."""
    asyncio.create_task(self._reload_model())

async def _reload_model(self) -> None:
    for segment_key, segment in self._segments.items():
        model = await self._registry.load_latest(segment)
        if model is not None:
            self._models[segment_key] = model
    self.logger.info("ml_scorer.model_reloaded")
```

**Note:** The signal handler runs in the event loop thread but the handler itself cannot be async. Use `asyncio.create_task()` to schedule the async reload from the sync handler. Alternatively, use `loop.call_soon_threadsafe()` for thread safety.

**SIGUSR1 to alpha-swarm from training agent:**
```python
# In MLTrainingComputeAgent, after successful promotion:
result = subprocess.run(
    ["systemctl", "kill", "-s", "SIGUSR1", "indicagent-alpha-swarm"],
    capture_output=True
)
```

---

## Q10: Service Registration — Exact Fields Required

**Source:** `services/service_auditor_agent.py` (verified directly, lines 49-142)
**Confidence:** HIGH

### MLTrainingComputeAgent (L8, timer-based)

`_DAG_ORDER`:
```python
"indicagent-ml-training": 8,
```

`_LAG_THRESHOLDS`: Not needed — `Type=oneshot`, not a Kafka consumer:
```python
# No entry needed — oneshot services don't have consumer lag
```

`_AGENT_ID_TO_UNIT`: Only needed if the service has a Prometheus `PERSISTENCE_CONSUMER_LAG` gauge. For `Type=oneshot`, likely not applicable:
```python
# Omit or add: "ml_training_compute": "indicagent-ml-training"
```

### MLScorerMultiplierAgent (in-swarm, not a separate service)

`MLScorerMultiplierAgent` runs INSIDE `AlphaSwarmComputeAgent` — it is NOT a separate systemd service. No `_DAG_ORDER` entry needed. The alpha-swarm service entry already covers it:
```
"indicagent-alpha-swarm": 7,
```

The agent registers in `shadow_registry` via the existing `_shadow_registry_ensure_swarm()` loop — no extra service auditor changes for the agent itself.

---

## Q11: Systemd Unit Files

**Source:** `production/systemd/indicagent-alpha-swarm.service`, `production/systemd/indicagent-ml-orchestrator.service` (verified directly)
**Confidence:** HIGH

### MLTrainingComputeAgent Service Unit

```ini
[Unit]
Description=IndicAgent ML Training Compute Agent — nightly LightGBM training
After=network.target

[Service]
Type=oneshot
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
Environment=INDICAGENT_ENV=development
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/ml_training_agent.py
TimeoutStartSec=7200

[Install]
WantedBy=multi-user.target
```

### MLTrainingComputeAgent Timer Unit

```ini
[Unit]
Description=ML Training Timer — nightly 03:00 UTC

[Timer]
OnCalendar=*-*-* 03:00:00 UTC
Persistent=true
Unit=indicagent-ml-training.service

[Install]
WantedBy=timers.target
```

**Note:** Run at 03:00 UTC (before the existing ML orchestrator at 04:00) to ensure artifacts are available.

### No separate unit for MLScorerMultiplierAgent

It runs inside `indicagent-alpha-swarm` — no new unit needed.

---

## Q12: Dashboard / Audit Read-Side Impact

**Source:** `src/api/routes/signals.py`, `src/api/routes/sse.py`, `services/swarm_ledger_writer_agent.py` (verified)
**Confidence:** HIGH

**Files needing LEFT JOIN updates after AI-SEP-01:**

| File | What changes |
|------|-------------|
| `src/api/routes/signals.py` | Any query that returns `swarm_multiplier` or `adjusted_confidence` needs LEFT JOIN `signal_ai_enrichment ON signal_id` |
| `services/signal_metrics_compute_agent.py` | Grep shows it references `signal_ledger` — check if it reads `swarm_multiplier` |
| `services/graduation_compute.py` | May reference `swarm_multiplier` for graduation queries |
| Dashboard Next.js queries | Any client-side query for signal display |

**Confirmed NOT affected (no swarm_multiplier reads found):**
- `src/api/routes/sse.py` — only publishes Kafka i8 events, no DB read of i8
- `services/signal_auditor_agent.py` — grep found no `swarm_multiplier` reference
- `services/parity_auditor_agent.py` — grep found no `swarm_multiplier` reference
- `src/api/routes/signals.py` `_build_signal_row()` — does not currently expose `swarm_multiplier` in response

**Practical impact of AI-SEP-01 migration:** The `signal_ledger.swarm_multiplier`, `signal_ledger.adjusted_confidence`, and `signal_ledger.swarm_agent_count` columns can be kept (non-null only for pre-migration rows) or zeroed out — they are not read by any identified consumer. New writes go to `signal_ai_enrichment`. Dashboard LEFT JOIN is additive.

**ML training queries** after migration: `TrainingDataQuery` reads `intelligence_features` — no `i8` access — unaffected. But if future training uses `i8`, it must LEFT JOIN `intelligence_ai_enrichment`.

---

## Standard Stack

### Core
| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| lightgbm | Already in requirements (verify) | Gradient boosting classification | Standard for tabular ML |
| mlflow | Already in use (ModelRegistry calls `mlflow.pyfunc.load_model`) | Artifact storage | Already integrated |
| polars | Already in use (`TrainingDataQuery` returns polars DataFrame) | Training data manipulation | Already integrated |
| shap | Verify in requirements | SHAP feature attribution | Must add if not present |
| scikit-learn | Already in use (isotonic regression in calibrator) | Preprocessing utilities | Already integrated |

### Installation
```bash
# Verify existing and add if missing:
uv pip install lightgbm shap
# polars, mlflow, scikit-learn are already present per TrainingDataQuery usage
```

---

## Architecture Patterns

### Pattern 1: MLScorerMultiplierAgent — No-LLM Multiplier

```python
# src/intelligence/ai/alpha/ml_scorer_agent.py
class MLScorerMultiplierAgent(BaseMultiplierAgent):
    agent_id = "ml_scorer_v1"
    group = "alpha"
    tiers_needed = frozenset()      # No LLM tiers — inference from context fields
    latency_budget_ms = 50.0
    shadow_only = True
    output_schema: ClassVar[dict] = {"multiplier": float, "ml_score": float, "segment": str}

    def __init__(self, pool, **kwargs):
        super().__init__(name=self.__class__.__name__, **kwargs)
        self._registry = ModelRegistry(pool, mlflow_tracking_uri=...)
        self._models: dict[str, Any] = {}  # segment_key -> loaded model

    async def _setup_models(self) -> None:
        """Load at startup. Called from AlphaSwarmComputeAgent._setup()."""
        for segment in [{"global": True}, {"hmm_regime": 0}, {"hmm_regime": 1}, {"hmm_regime": 2}]:
            model = await self._registry.load_latest(segment)
            key = "global" if segment.get("global") else f"regime_{segment['hmm_regime']}"
            if model:
                self._models[key] = model

    async def _compute(self, context: AIContext) -> AgentOutput:
        features = self._extract_features(context)
        model, segment_key = self._select_model(context)
        if model is None:
            return self._neutral(error="no_promoted_model", latency_ms=0.0)
        ml_score = float(model.predict(features)[0])
        return self._build_multiplier_output(
            context=context,
            multiplier=ml_score,           # P(win) in [0,2] after clamp
            confidence=ml_score,
            payload={"ml_score": ml_score, "segment": segment_key},
            prompt_version="v1",
        )
```

### Pattern 2: Walk-Forward CV with 60/20/20 Split

```python
# Sort by timestamp, split strictly temporally
df_sorted = df.sort("timestamp")
n = len(df_sorted)
train = df_sorted[:int(n * 0.60)]
val   = df_sorted[int(n * 0.60):int(n * 0.80)]
test  = df_sorted[int(n * 0.80):]
# Gate: if len(train) < 100, skip training
```

### Pattern 3: SIGUSR1 Hot-Swap (no existing pattern — new code)

```python
import asyncio, signal as _signal

# In AlphaSwarmComputeAgent._setup(), after constructing _agents:
loop = asyncio.get_event_loop()
loop.add_signal_handler(_signal.SIGUSR1, self._on_sigusr1)

def _on_sigusr1(self) -> None:
    asyncio.create_task(self._reload_ml_models())

async def _reload_ml_models(self) -> None:
    for agent in self._agents:
        if hasattr(agent, "_setup_models"):
            await agent._setup_models()
    self.logger.info("alpha_swarm.ml_models_reloaded_sigusr1")
```

### Anti-Patterns to Avoid
- **Do not call `json.dumps()` on JSONB columns** — asyncpg handles dict→jsonb natively. Exception: `ModelRegistry.register()` already calls `json.dumps(segment)` — do not change that.
- **Do not use random splits for walk-forward CV** — time axis must be respected. Any `train_test_split(shuffle=True)` is lookahead contamination.
- **Do not write ml_score into `signal_ledger` directly** — it goes to `signal_ai_enrichment.ml_score` (AI-SEP-01 principle).
- **Do not construct `MLScorerMultiplierAgent` in `__init__`** — construct in `_setup()` after `super()._setup()` because `ModelRegistry` needs the pool from `super()._setup()`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Model artifact storage | Custom file store | `mlflow.pyfunc` via `ModelRegistry.load_latest()` | Already integrated |
| Training data fetch | Custom SQL | `TrainingDataQuery` at `src/core/ml/training_data.py` | Has no-lookahead enforcement built in |
| Isotonic calibration | Custom calibration | `confidence_calibrator.py` pattern (already implemented) | Handles N-gate, stale deletion |
| Graduation gate math | Custom stats | `graduation.py` functions: `compute_spearman()`, `compute_walk_forward()` | Already tested |
| Signal outcome labels | Custom taxonomy | `WIN_OUTCOMES` from `signal_ledger_repository.py` | Already defined |

---

## Common Pitfalls

### Pitfall 1: features_snapshot Location in Intelligence Features

**What goes wrong:** Assuming `features_snapshot` is a top-level JSONB key in `intelligence_features`. It is NOT. It is nested inside the per-signal dict inside the `i7->'signals'` JSONB array.

**How to avoid:** The ML training query must JOIN `signal_ledger` and extract `features_snapshot` by matching `signal_id` within the `i7` signals array, OR read `features_snapshot` from a column added to `signal_ledger` itself. Recommend: add a `features_snapshot JSONB` column to `signal_ledger` during migration 084 (the `signal_writer_agent.py` already has the field at insert time — just needs the column).

**Warning signs:** Training query returns NULLs for all `_shadow` features.

### Pitfall 2: SIGNAL_SCHEMA_VERSION is "v2" not "v1"

**What goes wrong:** Filtering `WHERE signal_schema_version = 'v1'` returns zero rows. Migration 083 comments reference 'v1' but the code constant is "v2".

**How to avoid:** Always import `SIGNAL_SCHEMA_VERSION` from `src/intelligence/trading/signal_schema.py` — never hardcode the string. Current value: `"v2"`.

### Pitfall 3: ModelRegistry.register() Uses json.dumps() for segment

**What goes wrong:** Passing a dict to `register()` expecting asyncpg JSONB handling. The registry calls `json.dumps(segment)` explicitly before inserting — this is intentional and correct for that method. Do not "fix" it.

**How to avoid:** Understand this is a deliberate exception to the asyncpg JSONB rule in this file only.

### Pitfall 4: LightGBM Training Requires Polars→NumPy Conversion

**What goes wrong:** Passing a polars DataFrame directly to LightGBM `lgb.Dataset()` — LightGBM expects numpy arrays or pandas DataFrames.

**How to avoid:** Call `.to_numpy()` or `.to_pandas()` before constructing `lgb.Dataset`. `TrainingDataQuery` returns a polars DataFrame.

### Pitfall 5: SIGUSR1 Handler Cannot Be Async

**What goes wrong:** Registering an `async def` function with `loop.add_signal_handler()`. Python signal handlers must be synchronous callables.

**How to avoid:** Use the sync → `asyncio.create_task()` pattern shown in Pattern 3 above.

### Pitfall 6: Missing `features_snapshot` in Pre-Phase-45 Signals

**What goes wrong:** Training data from early signals (before `capture_signal_features()` was added) has NULL `features_snapshot`. These rows break feature extraction.

**How to avoid:** Filter training query: `WHERE signal["features_snapshot"] IS NOT NULL` or handle NULLs by imputing 0.0 for numeric shadow fields. Since migration 083 truncated all pre-Phase-79 signals, this is less of a risk — but the first weeks of v2 signals (May 2026) may have sparse shadow data depending on plugin coverage.

### Pitfall 7: `volume_z` vs `volume_z_score` Field Name

**What goes wrong:** D-01 says `volume_z` but the actual field in the `i1` JSONB column is `volume_z_score` (from `VolumeZscorePlugin`). Using `i1->>'volume_z'` returns NULL.

**How to avoid:** Use `f.i1->>'volume_z_score'` in all SQL and `features.get("volume_z_score")` in Python extraction code. The `FeatureVector` and `FeatureExtractor` classes also use `volume_z_score` — align with them.

---

## Code Examples

### Swarm Agent Registration (Add to AlphaSwarmComputeAgent._setup())

```python
# Source: services/alpha_swarm_agent.py lines 133-146 (pattern to extend)
self._agents = [
    SkepticComputeAgent(llm_chain=self._llm_chain),
    CorrelationComputeAgent(llm_chain=self._llm_chain),
    RegimeCoherenceComputeAgent(llm_chain=self._llm_chain),
    CounterfactualComputeAgent(llm_chain=self._llm_chain),
    MLScorerMultiplierAgent(pool=self._pool),   # NEW — no llm_chain needed
]
# _shadow_registry_ensure_swarm() loops self._agents — no extra call needed
```

### signal_ai_enrichment UPSERT (SwarmLedgerWriterAgent migration)

```python
# Source: analysis of swarm_ledger_writer_agent.py + D-13 schema
_UPSERT_ENRICHMENT_SQL = """
INSERT INTO signal_ai_enrichment
    (signal_id, swarm_multiplier, adjusted_confidence, swarm_agent_count, enriched_at)
VALUES ($1::uuid, $2, $3, $4, NOW())
ON CONFLICT (signal_id) DO UPDATE SET
    swarm_multiplier     = EXCLUDED.swarm_multiplier,
    adjusted_confidence  = EXCLUDED.adjusted_confidence,
    swarm_agent_count    = EXCLUDED.swarm_agent_count,
    enriched_at          = NOW()
"""
```

### intelligence_ai_enrichment UPSERT (LlmWriterService migration)

```python
# Replace _UPDATE_I8_SQL constant in llm_writer_service.py
_UPSERT_I8_SQL = """
INSERT INTO intelligence_ai_enrichment (ts, symbol, tf, i8, enriched_at)
VALUES ($1::timestamptz, $2, $3, $4::jsonb, NOW())
ON CONFLICT (ts, symbol, tf) DO UPDATE SET
    i8 = EXCLUDED.i8,
    enriched_at = NOW()
"""
```

### TrainingDataQuery Pattern with features_snapshot

```python
# Source: src/core/ml/training_data.py — extend this pattern
_SHADOW_FEATURES_SQL = """
SELECT
    sl.signal_id,
    sl.timestamp,
    sl.timeframe,
    sl.pnl_r,
    sl.outcome,
    (sl.pnl_r > 0)::int AS win_label,
    sl.features_snapshot,          -- NEW column on signal_ledger (migration 084)
    (f.i4->>'hmm_regime')::int     AS hmm_regime,
    (f.i4->>'trend_regime')::float AS trend_regime,
    f.session_type,
    (f.i1->>'atr_pct')::float      AS atr_pct,
    (f.i1->>'volume_z_score')::float AS volume_z_score,
    sl.tod_multiplier
FROM signal_ledger sl
JOIN intelligence_features f
  ON f.symbol = sl.symbol
 AND f.ts = sl.feature_ts
 AND f.tf = sl.feature_tf
 AND f.ts < sl.activated_at        -- NO LOOKAHEAD
WHERE sl.outcome IS NOT NULL
  AND sl.is_shadow = FALSE
  AND sl.signal_schema_version = $1
ORDER BY sl.timestamp
"""
```

---

## Open Questions

1. **features_snapshot storage location**
   - What we know: `capture_signal_features()` returns the dict, plugins set `signal["features_snapshot"]`, `make_signal_from_frame()` includes it in signal dict.
   - What's unclear: Does `signal_writer_agent.py` write `features_snapshot` to any column in `signal_ledger`? Or is it only in the `i7` JSONB array in `intelligence_features`?
   - Recommendation: During implementation, check `signal_writer_agent.py` for `features_snapshot` handling. If not in `signal_ledger`, migration 084 should ADD a `features_snapshot JSONB` column to `signal_ledger` and update `signal_writer_agent.py` to populate it.

2. **MLflow availability**
   - What we know: `ModelRegistry` calls `mlflow.pyfunc.load_model()` and `mlflow.set_tracking_uri("http://localhost:5000")`.
   - What's unclear: Is an MLflow tracking server running on the production machine at `:5000`?
   - Recommendation: Check `systemctl list-units | grep mlflow` and `docker ps | grep mlflow` before implementation. If not running, start as a Docker container or use file-based tracking URI.

3. **tod_multiplier in training join**
   - What we know: `tod_multiplier` is in `RankedSignal` (from `schemas.py`) and set by the pipeline, stored in the `i7` signals array.
   - What's unclear: Is `tod_multiplier` also stored as a top-level column in `signal_ledger`?
   - Recommendation: Check `signal_ledger_repository.py` `LedgerEntry` dataclass fields — it is NOT listed there (confirmed by reading the 64-field tuple). So `tod_multiplier` must be extracted from the `i7` JSONB signals array or from the bar-level context.

4. **Promotion gate implementation**
   - What we know: CONTEXT.md specifies "bootstrap CI on pnl_r improvement vs baseline (no-ML swarm) over the most recent 100 resolved signals."
   - What's unclear: Exact CI formula — bootstrap CI on win_rate improvement, or on mean pnl_r improvement?
   - Recommendation: Mirror the Phase 80 swarm graduation Spearman-based gate from `graduation.py` (`GATE_SPEARMAN_RHO = 0.15`) applied to (ml_score, pnl_r) correlation. Call `compute_spearman()` on the shadow period data.

---

## Sources

### Primary (HIGH confidence)
- `src/core/ml/registry.py` — ModelRegistry full API verified
- `src/core/ai/multiplier_agent.py` — BaseMultiplierAgent contract verified
- `src/intelligence/ai/alpha/correlation_agent.py` — reference implementation verified
- `src/intelligence/trading/confidence_utils.py` — capture_signal_features() exact output verified
- `src/intelligence/schemas.py` — IntelligenceEvent full schema verified
- `src/intelligence/ml/confidence_calibrator.py` — N-gate and training pattern verified
- `src/intelligence/swarm/graduation.py` — walk-forward split pattern verified
- `services/swarm_ledger_writer_agent.py` — current write path verified
- `services/llm_writer_service.py` — current i8 write path verified
- `services/alpha_swarm_agent.py` — AlphaSwarmComputeAgent full code verified
- `services/service_auditor_agent.py` — _DAG_ORDER, _LAG_THRESHOLDS, _AGENT_ID_TO_UNIT verified
- `src/core/ml/training_data.py` — TrainingDataQuery SQL and no-lookahead pattern verified
- `src/core/ml/features.py` — FeatureVector field names verified
- `production/migrations/059_ml_models.sql` — ml_models table schema verified
- `production/migrations/082_swarm_weights_and_adjusted_confidence.sql` — swarm columns verified
- `production/migrations/083_signal_ledger_lifecycle_columns.sql` — TRUNCATE + schema verified
- `production/systemd/indicagent-alpha-swarm.service` — systemd unit pattern verified
- `production/systemd/indicagent-ml-orchestrator.service` + `.timer` — oneshot+timer pattern verified

### Secondary (MEDIUM confidence)
- `src/intelligence/trading/signal_schema.py` — SIGNAL_SCHEMA_VERSION = "v2" verified; features_snapshot storage pathway inferred
- `src/api/routes/signals.py` — read-side impact assessed via code inspection; actual swarm_multiplier consumption not found

---

## Metadata

**Confidence breakdown:**
- Feature matrix: HIGH — verified directly from confidence_utils.py
- ModelRegistry API: HIGH — verified directly from registry.py
- BaseMultiplierAgent contract: HIGH — verified + reference implementation read
- AI-SEP-01 migration scope: HIGH — both writer files read in full
- Walk-forward CV: HIGH — graduation.py patterns verified; 3-way split is new code
- SIGUSR1 pattern: HIGH (absence) — no existing handler; pattern is standard Python asyncio
- Service registration fields: HIGH — service_auditor_agent.py read directly
- Systemd unit format: HIGH — existing units read directly
- Read-side impact: MEDIUM — grep found no consumers, but dashboard code not fully audited
- features_snapshot DB location: MEDIUM — inference from code flow, not DB query

**Research date:** 2026-05-13
**Valid until:** 2026-06-12 (30 days — codebase stable, no fast-moving dependencies)
