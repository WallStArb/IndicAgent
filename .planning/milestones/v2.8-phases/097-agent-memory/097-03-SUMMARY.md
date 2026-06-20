---
phase: 097-agent-memory
plan: "03"
subsystem: memory
tags: [pgvector, memory, embedding, episodic-recall, calibration, regime, ollama, ring-0]
dependency_graph:
  requires:
    - 097-01 (memory_episodes_labeled, memory_calibration_promoted, memory_regime_transitions tables)
    - 097-02 (Episode, CalibrationStats, RegimeHistory types; EpisodicBackend, CalibrationBackend, RegimeBackend Protocols; MEMORY_EMBED_LATENCY_MS metric)
  provides:
    - src.core.memory.embedding.EmbeddingService (percentile serialization + Ollama nomic-embed-text 768-dim)
    - src.core.memory.backends.PgvectorEpisodicBackend (tier-1 HNSW recall with epoch weighting)
    - src.core.memory.backends.PgvectorCalibrationBackend (tier-2 promoted-table reads)
    - src.core.memory.backends.PgvectorRegimeBackend (tier-5 regime transition priors)
  affects:
    - Wave 2 Plan 04 (MemoryEpisodeWriter uses EmbeddingService.embed_context())
    - Wave 2 Plan 05 (MemoryClient composes all four backends)
tech_stack:
  added:
    - httpx.AsyncClient (HTTP to Ollama /api/embeddings endpoint)
  patterns:
    - Ring 0 duck-typing via getattr for SignalContext fields (no Ring 1 import)
    - asyncio.wait_for 40ms hard timeout on every DB read (D-13/D-19)
    - SET LOCAL hnsw.ef_search = 100 per transaction before HNSW query (D-11)
    - Over-fetch limit*3 then Python-side epoch-weighted rerank (D-23)
    - asyncpg JSONB returned as dict (no json.loads); UUID stringified before use
    - elapsed_bars computed at query time from (NOW() - ts_start) / bar_duration (D-17)
key_files:
  created:
    - src/core/memory/embedding.py
    - src/core/memory/backends/episodic.py
    - src/core/memory/backends/calibration.py
    - src/core/memory/backends/regime.py
  modified:
    - src/core/memory/backends/__init__.py (added PgvectorEpisodicBackend, PgvectorCalibrationBackend, PgvectorRegimeBackend re-exports)
decisions:
  - "EmbeddingService uses a private httpx.AsyncClient created lazily in _get_client(); caller may inject a shared client for connection pooling"
  - "epoch_weight in Episode is back-computed as weighted_score/similarity to avoid storing it separately in the sort tuple"
  - "PgvectorRegimeBackend includes a _TIMEFRAME_SECONDS dict in Ring 0 rather than importing service_utils.min_bars_for_tf() to avoid circular imports"
  - "PgvectorCalibrationBackend.get_calibration() reads only memory_calibration_promoted; get_partial_sample_n() reads memory_episodes_labeled — this split is explicit in the Protocol and required by D-F3 cold-start path"
  - ".venv symlink created in worktree (symlink to /home/bg/dev/indicagent/.venv) to satisfy pre-commit hook path resolution"
metrics:
  duration_minutes: 5
  completed_date: "2026-06-05"
  tasks_completed: 3
  tasks_total: 3
  files_created: 4
  files_modified: 1
---

# Phase 097 Plan 03: Memory Read Backends Summary

**One-liner:** EmbeddingService + three pgvector read backends — percentile serialization via Ollama nomic-embed-text, HNSW recall with epoch-weighted rerank, promoted-table calibration, and at-query-time regime elapsed_bars.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | EmbeddingService — percentile serialization + Ollama nomic-embed-text | f0e8a07d | src/core/memory/embedding.py |
| 2 | PgvectorEpisodicBackend — ef_search + epoch-weighted rerank | 4d0bc9c7 | src/core/memory/backends/episodic.py |
| 3 | PgvectorCalibrationBackend + PgvectorRegimeBackend | 6d0e7695 | src/core/memory/backends/{calibration,regime}.py, backends/__init__.py |

## What Was Built

### Task 1 — EmbeddingService

`src/core/memory/embedding.py` — Ring 0 HTTP adapter for Ollama embedding API.

**`serialize(context: Any) -> str`:** Produces a space-delimited percentile-based string from any duck-typed context object via `getattr`. Mandatory leading tokens: `symbol timeframe entry_type regime:{hmm_regime} vol:{vol_regime}`. Optional tokens appended when present: `hmm_prob`, `trend`, `ctf`, `rsi_pct`, `atr_pct`, `swing`, `vol_pct`, `mom_pct`. Raw values (actual ATR, RSI integer) are deliberately excluded per D-22 — only percentile/normalized representations.

**`async embed(text) -> list[float] | None`:** POSTs to `{base_url}/api/embeddings` with `nomic-embed-text`, validates length == 768, records `MEMORY_EMBED_LATENCY_MS{batch="false"}`. Returns None (never raises) on HTTP error, timeout, or dimension mismatch.

**`async embed_batch(texts) -> list[list[float] | None]`:** Sequential loop over `embed()`, recording `MEMORY_EMBED_LATENCY_MS{batch="true"}` per call (Ollama API is single-prompt).

**`async embed_context(context) -> tuple[vector | None, text]`:** Convenience combining `serialize + embed` — returns both so the writer can persist `embedding_text` for model-change re-embedding (D-05).

Class constant `EMBED_DIM = 768`. No Ring 1 imports at module top.

### Task 2 — PgvectorEpisodicBackend

`src/core/memory/backends/episodic.py` — HNSW recall implementing `EpisodicBackend` Protocol.

**`recall(embedding, agent_id, symbol, hmm_regime, entry_type, regime_epoch, limit) -> list[Episode]`:**
1. Wraps `_recall_inner()` in `asyncio.wait_for(40ms)` — returns `[]` on `TimeoutError` or any exception.
2. Acquires a pool connection, opens a transaction, executes `SET LOCAL hnsw.ef_search = 100` (D-11 — `SET LOCAL` scopes to transaction, never leaks into pool state).
3. Queries `memory_episodes_labeled` with `1.0 - (embedding <=> $1::vector)` as similarity, filtered by all four cohort columns (agent_id, symbol, hmm_regime, entry_type — MEM-02), `ORDER BY embedding <=> $1::vector LIMIT limit*3` (D-23 over-fetch).
4. Embedding passed as a `[x,y,z,...]` string with `::vector` cast — asyncpg does not register the pgvector codec by default.
5. Python rerank: `epoch_weight = epoch_decay^max(0, current_epoch - row_epoch)`, score = `similarity * epoch_weight`. Sort descending, take top `limit`.
6. Maps rows to `Episode` frozen dataclasses — UUID fields stringified, JSONB payload passed as dict.

### Task 3 — PgvectorCalibrationBackend + PgvectorRegimeBackend

**`PgvectorCalibrationBackend.get_calibration()`:** Reads `memory_calibration_promoted` only (D-03). `WHERE feedback_loop_quarantine = FALSE ORDER BY promoted_at DESC LIMIT 1` — uses `mem_cal_cohort_latest` partial index. Sets `correction_factor = None` when `correction_factor_stable = False` (D-20). Returns `CalibrationStats(bootstrapped=True)` or None on no-row/timeout/error.

**`PgvectorCalibrationBackend.get_partial_sample_n()`:** Counts `outcome IS NOT NULL` rows in `memory_episodes_labeled` for the cohort. Used by MemoryClient cold-start path (D-F3) to return partial sample info below the N>=30 gate. Returns `int` (0 on error, never raises).

**`PgvectorRegimeBackend.get_regime_history()`:** Queries `memory_regime_transitions WHERE ts_end IS NULL` (open regime). Computes `elapsed_bars = int((NOW() - ts_start).total_seconds() / bar_seconds)` at query time — never stored (D-17). `transition_probs` and `win_rate` passed through as None when the DB stores NULL (C-03 discipline applied to satellite table). Returns `RegimeHistory` or None.

`backends/__init__.py` updated to re-export all three concrete implementations alongside the Protocols, providing a single stable import path.

## Verification

```
from src.core.memory.embedding import EmbeddingService; EmbeddingService.EMBED_DIM  # 768
from src.core.memory.backends import PgvectorEpisodicBackend, PgvectorCalibrationBackend, PgvectorRegimeBackend  # ok
EmbeddingService().serialize(FakeCtx())  # "ES 5m at_pullback regime:trending_up vol:normal hmm_prob:0.87 rsi_pct:0.62 atr_pct:0.34"
embed('ES 5m ...')  # returns None gracefully — nomic-embed-text not pulled; no exception
ruff check src/core/memory/embedding.py src/core/memory/backends/  # all passed
```

nomic-embed-text model not pulled in Ollama at verification time — `embed()` returned None gracefully as expected (no exception). Model pull is a Wave 2 operational step (Plan 05 MemoryClient wiring or pre-deployment). Noted in summary as expected behavior per D-13/D-19 contract.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree missing .venv — pre-commit hook blocked**
- **Found during:** Task 1 first commit attempt
- **Issue:** Pre-commit hook resolves `${REPO_ROOT}/.venv/bin/ruff` where REPO_ROOT is the worktree root. Worktree had no `.venv`. Hook reported `ruff not found` and `black not found`, blocking commit.
- **Fix:** Created symlink `/home/bg/dev/indicagent/.claude/worktrees/agent-a069003cec3480e7e/.venv -> /home/bg/dev/indicagent/.venv`. All subsequent commits pass.
- **Files modified:** (symlink only, not tracked by git)

### Design Choices within Spec

**`PgvectorEpisodicBackend` vector parameter:** The plan states "Pass the embedding as a Python list[float]; asyncpg will send it as text; append `::vector` cast in the SQL". Implemented as a string literal `[x,y,z,...]` with `$1::vector` cast — asyncpg parameterizes this as a string value. The `::vector` cast in SQL tells pgvector to parse it.

**`PgvectorRegimeBackend._TIMEFRAME_SECONDS` dict:** Added a local timeframe-to-seconds lookup dict rather than importing `service_utils.min_bars_for_tf()` to avoid circular imports (Ring 0 boundary). The canonical Ring 0 contract is met; service_utils is Ring 0 also but the circular import risk is real given the module load order.

**`backends/__init__.py` protocol/implementation split:** The `__all__` list was added in this plan's commit (not present in Plan 02's version). This is additive and non-breaking.

## Self-Check

**Created files:**
- [x] `src/core/memory/embedding.py` — FOUND
- [x] `src/core/memory/backends/episodic.py` — FOUND
- [x] `src/core/memory/backends/calibration.py` — FOUND
- [x] `src/core/memory/backends/regime.py` — FOUND

**Modified files:**
- [x] `src/core/memory/backends/__init__.py` — FOUND (re-exports added)

**Commits:**
- [x] f0e8a07d — Task 1 EmbeddingService
- [x] 4d0bc9c7 — Task 2 PgvectorEpisodicBackend
- [x] 6d0e7695 — Task 3 PgvectorCalibrationBackend + PgvectorRegimeBackend

**Must-haves verification:**
- [x] `EmbeddingService.embed() -> vector(768) via Ollama nomic-embed-text` — serialize produces percentile text; embed() calls nomic-embed-text endpoint
- [x] `PgvectorEpisodicBackend.recall with epoch-weighted rerank` — similarity * epoch_decay^delta, top limit after rerank
- [x] `PgvectorCalibrationBackend reading promoted table` — only `memory_calibration_promoted` in get_calibration()
- [x] `ef_search` appears in episodic.py — SET LOCAL hnsw.ef_search = {self._ef_search} (default 100)
- [x] `memory_calibration_promoted` appears in calibration.py — FROM memory_calibration_promoted
- [x] HNSW recall via `embedding <=> $1::vector` with ef_search set first — confirmed in SQL
- [x] Calibration reads from `memory_calibration_promoted WHERE feedback_loop_quarantine = FALSE` — confirmed

## Self-Check: PASSED
