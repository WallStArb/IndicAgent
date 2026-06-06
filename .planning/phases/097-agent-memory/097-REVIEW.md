---
phase: 097-agent-memory
reviewed: 2026-06-05T00:00:00Z
depth: standard
files_reviewed: 23
files_reviewed_list:
  - config/memory.yaml
  - production/migrations/118_agent_memory_schema.sql
  - production/scripts/memory_batch.py
  - production/systemd/indicagent-memory-batch.service
  - production/systemd/indicagent-memory-batch.timer
  - services/service_auditor.py
  - src/config/settings.py
  - src/core/ai/worker_context.py
  - src/core/memory/backends/calibration.py
  - src/core/memory/backends/episodic.py
  - src/core/memory/backends/__init__.py
  - src/core/memory/backends/mem0.py
  - src/core/memory/backends/regime.py
  - src/core/memory/client.py
  - src/core/memory/embedding.py
  - src/core/memory/factory.py
  - src/core/memory/__init__.py
  - src/core/memory/types.py
  - src/core/memory/writer.py
  - src/observability/metrics.py
  - tests/unit/core/test_embedding_service.py
  - tests/unit/core/test_memory_client.py
  - tests/unit/core/test_memory_writer.py
findings:
  critical: 4
  warning: 4
  info: 2
  total: 10
status: issues_found
---

# Phase 097: Code Review Report

**Reviewed:** 2026-06-05T00:00:00Z
**Depth:** standard
**Files Reviewed:** 23
**Status:** issues_found

## Summary

Reviewed the complete agent memory subsystem shipped in Phase 097: schema migration, batch script, pgvector backends, embedding service, client facade, writer, factory, and tests.

The architecture is well-structured — the read/write split (MemoryClient / MemoryEpisodeWriter), Ring 0 duck-typing discipline, graceful degradation via `asyncio.wait_for`, and the D-13/D-19 contracts are all correctly implemented. The migration is sound and idempotent.

However there are four blockers: a constructor parameter name mismatch that silently disables the entire memory subsystem at startup, a statistical correctness error in the Brier decomposition, a missing timeframe filter in the n_eligible SQL that overstates selection bias denominators by a large factor, and a non-atomic INSERT+UPDATE pair in the backfill job that can leave raw episodes permanently stuck in re-processing.

---

## Critical Issues

### CR-01: `EmbeddingService` instantiated with wrong keyword argument in factory — silently disables memory subsystem

**File:** `src/core/memory/factory.py:78` and `src/core/memory/factory.py:128`
**Issue:** Both `build_memory_client()` and `build_memory_writer()` call `EmbeddingService(base_url=settings.ollama_base_url)`. The `EmbeddingService.__init__` signature is `def __init__(self, ollama_base_url: str = ..., ...)` — the parameter is `ollama_base_url`, not `base_url`. Python raises `TypeError: unexpected keyword argument 'base_url'` at construction. Because both factory functions wrap construction in `try/except Exception`, the TypeError is silently swallowed and `None` is returned. The result: `AGENT_MEMORY_ENABLED=True` still produces `memory_client=None` in every `WorkerContext`. The memory subsystem appears enabled but delivers nothing.

**Fix:**
```python
# factory.py line 78 and line 128 — change base_url= to ollama_base_url=
embedding = EmbeddingService(ollama_base_url=settings.ollama_base_url)
```

---

### CR-02: Brier decomposition `reliability_score` is identical to `brier_score` — stored misleading values

**File:** `production/scripts/memory_batch.py:691-698`
**Issue:** `brier_score` and `reliability_score` are computed with the exact same expression:
```python
brier_score      = sum((mean_prediction - o) ** 2 for o in binary_outcomes) / len(binary_outcomes)
reliability_score = sum((mean_prediction - o) ** 2 for o in binary_outcomes) / len(binary_outcomes)
```
These are identical. Additionally `resolution_score = (actual_rate - base_rate) ** 2` is always `0.0` because `base_rate = actual_rate` is set on line 681 (`base_rate = actual_rate  # For this cohort`). Both `reliability_score` and `resolution_score` stored in `memory_calibration_promoted` are therefore meaningless numbers that do not represent their named quantities. Any downstream analysis that uses these columns from the DB will draw wrong conclusions.

**Fix:** Implement correct single-bin Brier decomposition. With a single bin (scalar forecast), reliability is the squared deviation of the mean forecast from the observed rate; resolution is 0 (no per-bin variation):
```python
# reliability = calibration error squared (how far mean forecast is from actual rate)
reliability_score = (mean_prediction - actual_rate) ** 2
# resolution = 0 for a single-bin forecast (all predictions are the same scalar)
resolution_score = 0.0
# Or: drop these columns and only store brier_score + skill_score
```

---

### CR-03: `n_eligible` UPDATE query missing timeframe filter — overstates selection bias denominator

**File:** `production/scripts/memory_batch.py:543-560`
**Issue:** The C-02 n_eligible backfill counts OHLCV rows without filtering by timeframe:
```sql
JOIN market_data_ohlcv m ON m.symbol = r2.symbol
    AND m.timestamp >= sl.timestamp
    AND m.timestamp <= COALESCE(sl.exit_at, NOW())
WHERE r2.n_eligible IS NULL AND r2.signal_id IS NOT NULL
```
`market_data_ohlcv` stores multiple timeframes (confirmed by `UNIQUE (timestamp, symbol, timeframe)` in migration 045). For a 5m episode, this counts 1m + 5m + 15m + ... bars in the signal window — easily 15-20x the correct number. `p_signal = sample_n / n_eligible` therefore understates signal selection rate by the same factor. The C-02 bias detection mechanism is broken for any non-1m timeframe.

**Fix:**
```sql
JOIN market_data_ohlcv m ON m.symbol = r2.symbol
    AND m.timeframe = r2.timeframe          -- add this filter
    AND m.timestamp >= sl.timestamp
    AND m.timestamp <= COALESCE(sl.exit_at, NOW())
```

---

### CR-04: Backfill INSERT + raw-row UPDATE are not atomic — raw episodes can be permanently stuck

**File:** `production/scripts/memory_batch.py:482-529`
**Issue:** For each ready episode the backfill does: INSERT into `memory_episodes_labeled` ... RETURNING id, then if result is not None: UPDATE `memory_episodes_raw SET outcome = ...`. These two writes share no transaction. If the INSERT succeeds but the UPDATE fails (e.g., connection interruption, exception after line 521), the labeled row exists but the raw row still has `outcome IS NULL`. On the next nightly run:
- The ready_rows query re-joins this row (WHERE `r.outcome IS NULL`)
- INSERT fires ON CONFLICT (id, ts) DO NOTHING → RETURNING returns NULL
- `result is not None` is False → UPDATE is skipped again

The raw row stays `outcome=NULL` forever, and it accumulates in every future ready_rows fetch, growing the query result set run after run. The labeled data is actually correct (the row was inserted), but the raw table is permanently polluted.

**Fix:** Wrap the INSERT and UPDATE in a savepoint (or a nested transaction) so either both commit or both roll back:
```python
async with conn.transaction():
    result = await conn.fetchval("""
        INSERT INTO memory_episodes_labeled (...)
        VALUES (...)
        ON CONFLICT (id, ts) DO NOTHING
        RETURNING id
    """, ...)
    if result is not None:
        await conn.execute(
            "UPDATE memory_episodes_raw SET outcome = $1 WHERE id = $2 AND ts = $3",
            row["outcome"], row["id"], row["ts"]
        )
    inserted += (1 if result is not None else 0)
```
The outer `try/except` on line 530 will still catch transaction failures per row.

---

## Warnings

### WR-01: Four OTel metrics duplicated between `memory_batch.py` and `metrics.py`

**File:** `production/scripts/memory_batch.py:46-62`
**Issue:** `memory_batch.py` creates its own local meter and registers four instruments that already exist in `src/observability/metrics.py` with the same names:
- `memory_cohorts_promoted_total` (line 47 vs metrics.py:957)
- `memory_cohorts_quarantined_total` (line 51 vs metrics.py:962)
- `memory_promotion_skipped_n_eligible` (line 55 vs metrics.py:967)
- `memory_episodes_labeled` gauge (line 59 vs metrics.py:949)

The OTel SDK logs a warning and may silently deduplicate or conflict these instruments. The batch script already imports `JOB_COMPLETED_TOTAL` from `metrics.py` — it should import the memory metrics from there too.

**Fix:** Remove lines 44-62 and import from metrics:
```python
from src.observability.metrics import (
    JOB_COMPLETED_TOTAL,
    MEMORY_COHORTS_PROMOTED_TOTAL,
    MEMORY_COHORTS_QUARANTINED_TOTAL,
    MEMORY_PROMOTION_SKIPPED_N_ELIGIBLE,
    MEMORY_EPISODES_LABELED,
    flush_and_shutdown_metrics,
)
```
Replace all `_COHORTS_PROMOTED.add(...)` usages with `MEMORY_COHORTS_PROMOTED_TOTAL.add(...)` etc. Note that the gauge in `metrics.py` uses `.set()` and the batch uses `.set()` — consistent.

---

### WR-02: `correction_factor` stores `mean_total` (mean pnl_r) — semantically wrong calibration correction

**File:** `production/scripts/memory_batch.py:1115`
**Issue:** `_compute_correction_factor` returns `mean_total` (the mean pnl_r across all episodes) as the `correction_factor`. A calibration correction factor is conceptually `actual_rate / mean_prediction` — the ratio by which agent predictions should be scaled to match observed outcomes. Returning mean pnl_r (a value around 1.0 R for winning cohorts) conflates the correction factor with the performance statistic. An agent that multiplies its confidence by `mean_pnl_r = 1.3` is not applying a calibration correction; it is amplifying confidence proportional to historical gains, which is a feedback loop risk.

**Fix:** Compute an actual calibration correction factor:
```python
# Correction factor: ratio of observed win rate to predicted win rate
# Only meaningful when mean_prediction != 0
if abs(mean_prediction) < 1e-6:
    return None, False
correction_factor_value = actual_rate / mean_prediction
# ... stability check across sub-windows using correction_factor_value, not mean_total
```

---

### WR-03: Hardcoded DB credentials in `Mem0BackendImpl`

**File:** `src/core/memory/backends/mem0.py:68-70`
**Issue:** The Mem0 config hardcodes `"host": "localhost"`, `"port": 5432`, `"dbname": "indicagent"`, `"user": "postgres"`, `"password": "postgres"` as string literals. These are the same credentials used in the rest of the system but are sourced from `settings.database_url` everywhere else. If the DB password or host is changed via env var, Mem0 will still use the hardcoded values and fail silently (the `_unavailable` fallback masks the error as a no-op).

**Fix:** Parse `settings.database_url` (PostgreSQL DSN) and extract the components, or add explicit settings fields for the Mem0 DB config:
```python
import urllib.parse

parsed = urllib.parse.urlparse(settings.database_url)
"config": {
    "host": parsed.hostname or "localhost",
    "port": parsed.port or 5432,
    "dbname": (parsed.path or "/indicagent").lstrip("/"),
    "user": parsed.username or "postgres",
    "password": parsed.password or "",
    ...
}
```

---

### WR-04: `resolution_score` is always `0.0` — dead computation stored in DB

**File:** `production/scripts/memory_batch.py:698`
**Issue:** (Supplemental to CR-02.) Even ignoring `reliability_score`, `resolution_score = (actual_rate - base_rate) ** 2` is always `0.0` because `base_rate = actual_rate` is set on line 681 for every cohort. Both fields are stored in `memory_calibration_promoted` on every promotion run, consuming write bandwidth and misleading any consumer that queries `resolution_score` expecting a meaningful metric.

**Fix:** See CR-02 fix. Until the Brier decomposition is corrected, `resolution_score` should be stored as `None` or removed from the INSERT rather than stored as a misleading `0.0`.

---

## Info

### IN-01: `_bootstrap_p_value` docstring contradicts implementation

**File:** `production/scripts/memory_batch.py:1052`
**Issue:** The docstring says `"Bootstrap p-value: P(mean <= 0)"` but the code computes an upper-tail p-value — the fraction of bootstrap samples where the bootstrap mean (from null-shifted data) is `>= observed_mean`. This is the correct test for `H1: mean > 0` (positive signal), not `P(mean <= 0)`. The implementation logic is correct for the intended use, but the docstring is wrong and will mislead future maintainers about the null hypothesis direction.

**Fix:**
```python
def _bootstrap_p_value(data: list[float], block_len: int, n_boot: int = 500) -> float:
    """Bootstrap p-value for H0: true mean = 0 vs H1: true mean > 0.

    Returns the fraction of bootstrap samples (drawn from null-shifted data) where
    the bootstrap mean >= observed_mean. Small values indicate the observed mean is
    unlikely under H0 (positive signal). Used as p_value_raw for BH-FDR correction.
    """
```

---

### IN-02: `store()` mutates caller-owned `raw_episode` dict

**File:** `src/core/memory/writer.py:129`
**Issue:** `store()` stamps `raw_episode["regime_epoch"] = int(self._current_epoch_provider())` directly on the dict passed by the caller. If the caller holds a reference to the same dict and reuses it after `store()`, it now has a `regime_epoch` key it didn't put there. `setdefault` is used as fallback but the primary branch (`if self._current_epoch_provider is not None`) overwrites unconditionally. A defensive copy (`episode = {**raw_episode}`) at the top of `store()` would isolate the writer from the caller.

**Fix:**
```python
def store(self, raw_episode: dict) -> None:
    episode = dict(raw_episode)  # defensive copy — do not mutate caller dict
    try:
        if self._current_epoch_provider is not None:
            ...
        self._queue.put_nowait(episode)
    ...
```

---

_Reviewed: 2026-06-05T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
