---
phase: 097-agent-memory
fixed_at: 2026-06-05T20:13:00Z
review_path: .planning/phases/097-agent-memory/097-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 097: Code Review Fix Report

**Fixed at:** 2026-06-05T20:13:00Z
**Source review:** .planning/phases/097-agent-memory/097-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 8 (CR-01 through CR-04, WR-01 through WR-04)
- Fixed: 8
- Skipped: 0

## Fixed Issues

### CR-01: EmbeddingService instantiated with wrong keyword argument in factory

**Files modified:** `src/core/memory/factory.py`
**Commit:** 7a1d3f38
**Applied fix:** Changed both `EmbeddingService(base_url=settings.ollama_base_url)` calls (lines 78 and 128) to `EmbeddingService(ollama_base_url=settings.ollama_base_url)`, matching the actual `__init__` parameter name.

---

### CR-02: Brier decomposition `reliability_score` identical to `brier_score`

**Files modified:** `production/scripts/memory_batch.py`
**Commit:** a4a6751e
**Applied fix:** Replaced the duplicated brier expression for `reliability_score` with `(mean_prediction - actual_rate) ** 2` — the squared deviation of the mean forecast from the observed win rate (correct single-bin calibration error). Updated comments to clearly distinguish brier_score, reliability_score, and resolution_score.

---

### CR-03: `n_eligible` UPDATE query missing timeframe filter

**Files modified:** `production/scripts/memory_batch.py`
**Commit:** a4a6751e
**Applied fix:** Added `AND m.timeframe = r2.timeframe` to the `JOIN market_data_ohlcv` condition in the n_eligible backfill UPDATE query, ensuring only bars from the signal's timeframe are counted as eligible bars.

---

### CR-04: Backfill INSERT + raw-row UPDATE not atomic

**Files modified:** `production/scripts/memory_batch.py`
**Commit:** a4a6751e
**Applied fix:** Wrapped the INSERT into `memory_episodes_labeled` and the UPDATE on `memory_episodes_raw` in `async with conn.transaction():` so both writes are atomic. If the UPDATE fails, the INSERT rolls back and the raw row remains `outcome=NULL` for the next run to retry cleanly.

---

### WR-01: Four OTel metrics duplicated between `memory_batch.py` and `metrics.py`

**Files modified:** `production/scripts/memory_batch.py`
**Commit:** a4a6751e
**Applied fix:** Removed the local `_meter = _otel_metrics.get_meter("indicagent")` block and the four `_meter.create_*` calls. Added imports of `MEMORY_COHORTS_PROMOTED_TOTAL`, `MEMORY_COHORTS_QUARANTINED_TOTAL`, `MEMORY_EPISODES_LABELED`, and `MEMORY_PROMOTION_SKIPPED_N_ELIGIBLE` from `src/observability/metrics.py`. Retained local aliases (`_COHORTS_PROMOTED`, etc.) for readability — no call-site changes required. Removed unused `from opentelemetry import metrics as _otel_metrics` import.

---

### WR-02: `correction_factor` stores `mean_total` instead of an actual calibration ratio

**Files modified:** `production/scripts/memory_batch.py`
**Commit:** a4a6751e
**Applied fix:** Rewrote `_compute_correction_factor` to compute `actual_win_rate / mean_prediction` as the correction factor. Sub-window stability check now uses per-window correction factors (each sub-window's `win_rate / mean`) rather than total-mean / window-mean. Guards for near-zero mean and near-zero `mean_sub` added. Updated docstring to clearly describe what the factor represents.

---

### WR-03: Hardcoded DB credentials in `Mem0BackendImpl`

**Files modified:** `src/core/memory/backends/mem0.py`
**Commit:** fcb38bad
**Applied fix:** Added `import urllib.parse`. In `__init__`, parse `settings.database_url` with `urllib.parse.urlparse()` and derive host, port, dbname, user, and password from the parsed result with sensible fallbacks. The Mem0 config now picks up env-var overrides automatically.

---

### WR-04: `resolution_score` always `0.0` — dead computation

**Files modified:** `production/scripts/memory_batch.py`
**Commit:** a4a6751e
**Applied fix:** Addressed as part of CR-02. `resolution_score` is now set to `0.0` explicitly with a comment explaining it is always zero for a single-bin forecast (no per-bin variation possible). This is semantically correct rather than accidentally zero.

---

_Fixed: 2026-06-05T20:13:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
