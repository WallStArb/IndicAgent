---
phase: 070-ml-scoring-model
reviewed: 2026-05-13T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - production/migrations/084_ai_enrichment_tables.sql
  - services/alpha_swarm_agent.py
  - services/llm_writer_service.py
  - services/ml_training_agent.py
  - services/signal_writer_agent.py
  - services/swarm_ledger_writer_agent.py
  - src/core/ml/registry.py
  - src/intelligence/ai/alpha/ml_scorer_agent.py
  - src/intelligence/ml/feature_builder.py
  - src/intelligence/services/ml_training_compute_agent.py
  - src/persistence/repository/signal_ledger_repository.py
findings:
  critical: 4
  warning: 5
  info: 2
  total: 11
status: issues_found
---

# Phase 070: Code Review Report

**Reviewed:** 2026-05-13T00:00:00Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Phase 70 introduces the ML Scoring Model pipeline: two new AI-owned enrichment tables (AI-SEP-01), a nightly LightGBM training agent, a new `MLScorerMultiplierAgent` inference agent integrated into AlphaSwarm, and SIGUSR1-driven hot reload. The separation of AI enrichment from quant tables is architecturally sound and the overall pipeline structure is correct.

Four blockers are identified:

1. `ModelRegistry` passes dicts to asyncpg JSONB columns via `json.dumps()` — a direct violation of the project's asyncpg JSONB rule and a latent double-encode bug.
2. `swarm_ledger_writer_agent.py` reads `agent_outputs` from the swarm event, but `alpha_swarm_agent.py` never populates that field in the published payload — the ML score will **never** be extracted and persisted to `signal_ai_enrichment.ml_score`.
3. `_train_segment` in `MLTrainingComputeAgent` calls `encode_features(val_df, feature_cols)` twice — once to get `X_val/y_val` (line 225) and once more just to get `val_cols` (line 242). The second call is redundant but, more critically, `encode_features` returns a three-tuple and the first call already captures `val_cols` (it just ignores the name with `_`). Code is wrong: `_` is used where the third element is needed, then `encode_features` is called a second time to recover it.
4. SHAP `shap_values` indexing assumes a 2-D array but `TreeExplainer.shap_values()` on a binary classifier returns a list of two arrays (one per class); `shap_values[:, i]` on the list will raise `TypeError`.

---

## Critical Issues

### CR-01: `ModelRegistry` uses `json.dumps()` for JSONB — violates asyncpg contract, risks double-encode

**File:** `src/core/ml/registry.py:47`, `72`, `97`
**Issue:** The project rule (CLAUDE.md, asyncpg section) is explicit: "Pass dicts for jsonb columns — never `json.dumps()`." `asyncpg` registers a JSONB codec that serialises Python `dict` objects natively. Passing `json.dumps(segment)` produces a JSON *string*, which asyncpg then re-serialises as a JSONB string literal rather than a JSONB object. This means `segment @> $1::jsonb` containment queries in `load_latest` and `get_latest_run_id` will never match rows (string vs. object JSONB type mismatch), so **no model will ever be found after registration** and `MLScorerMultiplierAgent` will always return `no_promoted_model`.

**Fix:**
```python
# register() — line 47
async with self._pool.acquire() as conn:
    row = await conn.fetchrow(
        """
        INSERT INTO ml_models (model_type, segment, mlflow_run_id, artifact_path, status)
        VALUES ($1, $2, $3, $4, 'shadow')
        RETURNING model_id::text
        """,
        model_type,
        segment,        # pass dict directly — asyncpg handles JSONB serialisation
        run_id,
        artifact_path,
    )

# load_latest() — line 72 — same fix
row = await conn.fetchrow(
    "... WHERE status = 'production' AND segment @> $1::jsonb ...",
    segment,            # dict, not json.dumps(segment)
)

# get_latest_run_id() — line 97 — same fix
row = await conn.fetchrow(
    "... WHERE status = 'production' AND segment @> $1::jsonb ...",
    segment,            # dict, not json.dumps(segment)
)
```
Also remove all `import json` statements inside these methods.

---

### CR-02: `agent_outputs` never populated in swarm event — ML score never persisted

**File:** `services/swarm_ledger_writer_agent.py:150-158` (reader) / `services/alpha_swarm_agent.py:583-594` (writer)
**Issue:** `SwarmLedgerWriterAgent._handle_event()` extracts `ml_score` and `ml_model_id` by iterating `payload.get("agent_outputs")`. However, `AlphaSwarmComputeAgent._process_one_signal()` builds `event_payload` at lines 583–594 and never includes an `agent_outputs` key. The result: `agent_outputs` is always `[]`, `ml_score` is always `None`, and `_UPSERT_ML_SCORE_SQL` is never executed. The ML scorer's output is collected in memory (correctly) but the `ml_score` and `ml_model_id` columns in `signal_ai_enrichment` will always be NULL.

**Fix:** Populate `agent_outputs` in the published event in `alpha_swarm_agent.py`:
```python
# In _process_one_signal(), build agent_outputs from results before publishing
agent_outputs_list = []
for agent, result in zip(agents_with_context, results):
    if isinstance(result, AgentOutput) and not result.error:
        agent_outputs_list.append({
            "agent_id": agent.agent_id,
            "payload": result.payload,
        })

event_payload = {
    "signal_id": str(signal_id),
    "symbol": enriched.symbol,
    "timeframe": tf,
    "swarm_multiplier": final_multiplier,
    "adjusted_confidence": adjusted_confidence,
    "swarm_agent_count": agent_count,
    "agent_outputs": agent_outputs_list,   # ADD THIS
    "ts": _now_utc_iso(),
}
```

---

### CR-03: SHAP `shap_values` indexing fails for binary LightGBM classifier

**File:** `src/intelligence/services/ml_training_compute_agent.py:282-285`
**Issue:** `shap.TreeExplainer.shap_values()` on a LightGBM binary classifier returns a **list of two arrays** — one per output class — not a single 2-D array. The code does:
```python
shap_values = explainer.shap_values(X_val[:n_shap])
feature_importance = {
    col: float(np.abs(shap_values[:, i]).mean())   # TypeError: list indices must be integers
    ...
}
```
`shap_values[:, i]` on a list raises `TypeError`, crashing `_train_segment` and preventing model registration. With the top-level `except Exception` swallowing the error, this will silently skip all model training.

**Fix:**
```python
shap_values = explainer.shap_values(X_val[:n_shap])
# For binary classification, shap_values is a list[ndarray]; take class-1 values.
sv = shap_values[1] if isinstance(shap_values, list) else shap_values
feature_importance = {
    col: float(np.abs(sv[:, i]).mean())
    for i, col in enumerate(list(final_cols))
}
```

---

### CR-04: `encode_features` called twice on val/test splits — `_` silently discards needed return value

**File:** `src/intelligence/services/ml_training_compute_agent.py:223-245`
**Issue:** At line 223–225, `encode_features` is called for train, val, and test splits. The val and test calls use `_` to discard `val_cols` and `test_cols`. Then at lines 242–243, `encode_features` is called a *second* time on `val_df` and `test_df` just to recover those column lists. This wastes CPU but, more critically, it is fragile: if `val_df` or `test_df` contains a different cardinality of categorical values than on the first call (possible with small splits), the second call may return a *different* column list than the first, causing `_align_X` to silently misalign features. The correct fix is to capture the column lists from the first call.

**Fix:**
```python
X_train, y_train, final_cols = encode_features(train_df, feature_cols)
X_val,   y_val,   val_cols   = encode_features(val_df,   feature_cols)  # capture val_cols
X_test,  y_test,  test_cols  = encode_features(test_df,  feature_cols)  # capture test_cols

# Remove the redundant second encode_features calls (lines 242-243):
# _, _, val_cols  = encode_features(val_df, feature_cols)   <-- DELETE
# _, _, test_cols = encode_features(test_df, feature_cols)  <-- DELETE

X_val  = _align_X(X_val,  list(val_cols),  list(final_cols))
X_test = _align_X(X_test, list(test_cols), list(final_cols))
```

---

## Warnings

### WR-01: `swarm_ledger_writer_agent` catches `ForeignKeyViolationError` but `signal_ai_enrichment` has no FK

**File:** `services/swarm_ledger_writer_agent.py:222-225`
**Issue:** The retry loop catches `asyncpg.exceptions.ForeignKeyViolationError` as the signal for "signal_ledger row not yet visible." However, migration 084 explicitly documents that `signal_ai_enrichment` has **no** declarative FK on `signal_id` (TimescaleDB limitation). This means the exception can never be raised — the UPSERT will always succeed immediately regardless of whether the `signal_ledger` row exists, and the backoff logic provides no actual race protection. If the logical FK check is important for data quality, it must be enforced via an application-layer existence check before the UPSERT.

**Fix:** Either document that the race is now inconsequential (application-layer FK is advisory only and the UPSERT succeeds regardless), or add an explicit existence check:
```python
# Inside the retry loop, before the UPSERT:
exists = await conn.fetchval(
    "SELECT 1 FROM signal_ledger WHERE signal_id = $1::uuid LIMIT 1",
    str(signal_id),
)
if not exists:
    raise _SignalNotYetVisible()  # custom sentinel to trigger retry
```

---

### WR-02: `_on_sigusr1` calls `asyncio.create_task()` without a running loop reference — task may be garbage-collected

**File:** `services/alpha_swarm_agent.py:413`
**Issue:** `asyncio.create_task(self._reload_ml_models())` in the synchronous SIGUSR1 handler creates a task but does not store it. Python's asyncio documentation warns that tasks not held by a strong reference may be garbage-collected before they complete. The handler itself is safe (it uses `asyncio.get_running_loop()` indirectly via `create_task`), but if the task is GC'd mid-execution the reload silently aborts with no log or error.

**Fix:** Hold a reference to the task, e.g. via a module-level or instance-level set:
```python
def _on_sigusr1(self) -> None:
    self.logger.info("alpha_swarm.sigusr1_received")
    task = asyncio.create_task(self._reload_ml_models())
    # Prevent GC before completion
    self._background_tasks.add(task)
    task.add_done_callback(self._background_tasks.discard)
```
Add `self._background_tasks: set = set()` to `__init__`.

---

### WR-03: `_process_i8_message` silently swallows unparseable `i8` field values as strings

**File:** `services/llm_writer_service.py:762-767`
**Issue:** The `i8_dict` built in `_process_i8_message` casts all values to `str` via `_field()`, including `confidence` which is stored as a string `"0.0"` rather than a float. If downstream consumers query `intelligence_ai_enrichment.i8->>'confidence'` and cast to float, this works. But if the row is queried via `(i8->>'confidence')::float` in a plan where `confidence` was supposed to be a numeric JSONB value, unexpected string JSONB semantics may surface. More importantly, the `_field()` helper uses `or ""` with no error logging — if any field is missing, the empty-string default is silently stored.

**Fix:** Store numeric fields as their actual types in the JSONB dict:
```python
i8_dict = {
    "model": _field("model") or "unknown",
    "confidence": float(_field("confidence") or 0.0),   # store as float, not str
    "summary": _field("summary") or None,
    "generated_at": _field("generated_at") or None,
}
```

---

### WR-04: `build_training_matrix` filters on `existing_confidence IS NOT NULL` but this key may legitimately be zero

**File:** `src/intelligence/ml/feature_builder.py:177-178`
**Issue:** The post-fetch filter `df.filter(pl.col("existing_confidence").is_not_null())` drops rows where `existing_confidence` was not present in `features_snapshot` (correctly mapped to `None`). However, the SQL query already filters `features_snapshot IS NOT NULL` at line 114. The Python-side filter is a defensive no-op in the happy path, but it silently removes any signal where `features_snapshot` exists but the `existing_confidence` key was missing (e.g. signals from older plugins that predated this key). This could reduce the training set size unexpectedly, particularly early in Phase 70 deployment before all plugins populate the field.

**Fix:** Log the dropped row count so the training operator is aware:
```python
pre_filter_len = len(df)
if "existing_confidence" in df.columns:
    df = df.filter(pl.col("existing_confidence").is_not_null())
    dropped = pre_filter_len - len(df)
    if dropped > 0:
        logger.warning(
            "feature_builder.existing_confidence_filter_dropped",
            dropped=dropped,
            total=pre_filter_len,
        )
```

---

### WR-05: `_should_retrain` updates `self._last_trained_count` before training completes — checkpoint inconsistency on failure

**File:** `src/intelligence/services/ml_training_compute_agent.py:155`
**Issue:** `_should_retrain()` sets `self._last_trained_count = current_count` (line 155) as a side effect before returning `True`. If `_train_all_segments()` subsequently fails (exception caught at line 113), `_write_checkpoint()` is never called but the in-memory count is already advanced. On the next nightly run, `_read_checkpoint()` reads the *stale* on-disk value (the previous run's count), but `self._last_trained_count` is re-initialised from disk in `_setup()`, so the race only manifests within a single process lifetime. However, if `_write_checkpoint` does succeed (line 174), it writes the count set during `_should_retrain`, which is the correct value. This is actually safe across process restarts. The real risk is subtler: if `_train_all_segments` is refactored to be called more than once per process lifetime, the in-memory mutation in `_should_retrain` would prevent subsequent retraining in the same process run.

**Fix:** Defer the in-memory mutation to after successful training:
```python
async def _should_retrain(self) -> tuple[bool, int]:
    # Return (should_retrain, current_count) — let caller decide when to update
    ...
    return delta >= _DELTA_GATE_MIN, current_count

async def _train_all_segments(self) -> None:
    should, current_count = await self._should_retrain()
    if not should:
        return
    ...
    self._last_trained_count = current_count   # only after successful run
    self._write_checkpoint(self._last_trained_count)
```

---

## Info

### IN-01: `_CHECKPOINT_PATH` is a relative path — fails if working directory is not project root

**File:** `src/intelligence/services/ml_training_compute_agent.py:57`
**Issue:** `_CHECKPOINT_PATH = "logs/ml_training_checkpoint.json"` is a relative path. If the systemd unit's `WorkingDirectory` is not set to the project root, `Path(_CHECKPOINT_PATH)` resolves to the wrong location and `_read_checkpoint()` returns 0 on every run (bypassing the delta gate: with `last_trained_count=0` and a large enough corpus the gate will always pass). This is an operability risk.

**Fix:** Derive the path relative to the project root using `__file__`:
```python
_CHECKPOINT_PATH = Path(__file__).parents[3] / "logs" / "ml_training_checkpoint.json"
```
Or ensure the systemd unit sets `WorkingDirectory=` to the project root.

---

### IN-02: `MLScorerMultiplierAgent._compute` measures `latency_ms=0.0` hardcoded on all early-exit paths

**File:** `src/intelligence/ai/alpha/ml_scorer_agent.py:288`, `292`, `296`
**Issue:** The three early-exit `_neutral()` calls all pass `latency_ms=0.0`. Prometheus latency metrics will never reflect actual inference time (even partial), making it impossible to distinguish "no model loaded" from "inference took zero time." At minimum, the predict path at line 299 should time the inference and pass the observed latency to `_build_multiplier_output`.

**Fix:**
```python
import time
t0 = time.perf_counter()
try:
    ml_score = float(model.predict(features)[0])
except Exception as exc:
    ...
    return self._neutral(error="predict_exception", latency_ms=(time.perf_counter() - t0) * 1000)

latency_ms = (time.perf_counter() - t0) * 1000
return self._build_multiplier_output(..., latency_ms=latency_ms)
```

---

_Reviewed: 2026-05-13T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
