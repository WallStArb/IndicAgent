---
phase: 097-agent-memory
plan: "04"
subsystem: memory
tags: [memory, client, writer, embedding, factory, otel, ring-0]
dependency_graph:
  requires:
    - 097-01 (memory_episodes_raw table)
    - 097-02 (EpisodicBackend/CalibrationBackend/RegimeBackend/Mem0Backend protocols; MEMORY_* OTel instruments; AGENT_MEMORY_ENABLED flag)
    - 097-03 (EmbeddingService, PgvectorEpisodicBackend, PgvectorCalibrationBackend, PgvectorRegimeBackend)
  provides:
    - src.core.memory.backends.mem0.Mem0BackendImpl (tier 4/7 Mem0 backend)
    - src.core.memory.client.MemoryClient (read-only facade, 4 methods, OTel)
    - src.core.memory.writer.MemoryEpisodeWriter (fire-and-forget write path)
    - src.core.memory.writer.EmbeddingWorker (background drain, asyncpg INSERT)
    - src.core.memory.factory.build_memory_client (AGENT_MEMORY_ENABLED gated)
    - src.core.memory.factory.build_memory_writer (AGENT_MEMORY_ENABLED gated)
  affects:
    - src.core.ai.worker_context.WorkerContext (memory_client: MemoryClient | None)
    - services.alpha_swarm.AlphaSwarm (self._memory_client wired in _setup)
    - All BaseAIWorker subclasses (receive MemoryClient via WorkerContext when enabled)
tech_stack:
  added:
    - asyncio.to_thread() for synchronous Mem0 SDK wrapping
    - _EpisodeContextProxy duck-typed Ring 0 proxy for EmbeddingService.serialize()
  patterns:
    - Guarded import (try/except ImportError) for optional mem0ai dependency
    - TYPE_CHECKING-only import for MemoryClient in WorkerContext (Ring 0 import-light pattern)
    - Fire-and-forget asyncio.Queue(maxsize=500) with put_nowait drop semantics
    - Lazy client initialization (Mem0BackendImpl._get_client())
    - Factory pattern with AGENT_MEMORY_ENABLED gate; never raises, returns None on failure
    - F3 cold-start path: partial CalibrationStats(bootstrapped=False) when sample_n > 0 but below N>=30
key_files:
  created:
    - src/core/memory/backends/mem0.py
    - src/core/memory/client.py
    - src/core/memory/writer.py
    - src/core/memory/factory.py
  modified:
    - src/core/ai/worker_context.py (memory_client: Any | None -> MemoryClient | None via TYPE_CHECKING)
    - services/alpha_swarm.py (build_memory_client import + _setup() wiring)
decisions:
  - "Mem0BackendImpl uses lazy initialization so unit tests without mem0ai installed import cleanly (guarded import + no-op fallback)"
  - "MemoryClient.calibration() F3 cold-start path: partial CalibrationStats when sample_n > 0 below N>=30 gate rather than None"
  - "_EpisodeContextProxy duck-typed proxy in Ring 0 avoids any Ring 1 imports in writer.py"
  - "WorkerContext.memory_client typed via TYPE_CHECKING-only import -- mirrors LLMProviderChain precedent; dataclass stays frozen"
  - "Factory functions use local (lazy) imports inside try/except -- callers never see ImportError"
  - "alpha_swarm._setup() is the reference wiring site; other services follow this pattern when they add memory support"
metrics:
  duration_minutes: 8
  completed_date: "2026-06-04"
  tasks_completed: 4
  tasks_total: 4
  files_created: 4
  files_modified: 2
---

# Phase 097 Plan 04: MemoryClient + Write Path Summary

**One-liner:** MemoryClient read-only facade over 4 backends with OTel p95 latency instrumentation, fire-and-forget MemoryEpisodeWriter with bounded asyncio.Queue, Mem0BackendImpl with graceful degradation, and AGENT_MEMORY_ENABLED-gated factory functions wired into AlphaSwarm.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Mem0BackendImpl (tiers 4/7, asyncio.to_thread) | 322da009 | src/core/memory/backends/mem0.py |
| 2 | MemoryClient facade with OTel latency instrumentation | c7166d9f | src/core/memory/client.py |
| 3 | MemoryEpisodeWriter + EmbeddingWorker + WorkerContext stub | 3e7f3b1f | src/core/memory/writer.py, src/core/ai/worker_context.py |
| 4 | MemoryClientFactory + alpha_swarm wiring | ea04ffca | src/core/memory/factory.py, services/alpha_swarm.py |

## What Was Built

### Task 1 -- Mem0BackendImpl

`src/core/memory/backends/mem0.py` -- Mem0Backend Protocol implementation for tiers 4 (narrative) and 7 (annotation).

**Key design choices:**
- Lazy `_get_client()` with guarded `from mem0 import Memory` inside `try/except ImportError`. mem0ai not installed -> single WARNING log, `self._unavailable = True`, all subsequent calls return [].
- `_search_sync()` runs the synchronous SDK call; `search()` wraps it in `asyncio.to_thread()` per D-13.
- MEM0_CONFIG: pgvector provider against TimescaleDB (`mem0_memories` collection, 768-dim), ollama embedder (`nomic-embed-text`, `ollama_base_url` from settings), `graph_store=None` (Neo4j rejected), `llm=None` (LLM-based extraction disabled -- stored verbatim, D-18).
- Tier guard: `_VALID_TIERS = {'narrative', 'annotation'}` -- returns [] for any other tier, never raises.

### Task 2 -- MemoryClient

`src/core/memory/client.py` -- read-only facade composing 4 backends + EmbeddingService.

**Four public methods:**
- `recall(context, agent_id, limit)`: embeds context, extracts cohort keys via duck-typing (Ring 0), delegates to EpisodicBackend. Records `MEMORY_RECALL_LATENCY_MS{tier="1", symbol}` and `MEMORY_RECALL_RESULTS_TOTAL{tier, result=hit|miss|timeout}` (MEM-04 p95 signal).
- `calibration(agent_id, symbol, hmm_regime, entry_type, regime_epoch)`: reads promoted table via CalibrationBackend. On promoted row: increments `MEMORY_CALIBRATION_APPLIED{agent_id, stable}`. On None: calls `get_partial_sample_n()` for F3 cold-start path -- returns partial `CalibrationStats(bootstrapped=False)` when sample_n > 0, `None` when sample_n == 0.
- `recall_regime_history(symbol, timeframe)`: delegates to RegimeBackend; records `MEMORY_RECALL_LATENCY_MS{tier="5", symbol}`.
- `recall_annotations(symbol, timeframe, limit)`: delegates to Mem0Backend.search with tier `"annotation"`.

No write methods (D-19). Every method returns [] or None on error, never raises.

### Task 3 -- MemoryEpisodeWriter + EmbeddingWorker + WorkerContext

`src/core/memory/writer.py` -- write path for the live signal pipeline.

**MemoryEpisodeWriter.store():**
- `queue.put_nowait(raw_episode)` -- non-blocking.
- On `asyncio.QueueFull`: `MEMORY_WRITE_DROPPED_TOTAL.add(1, {})` + WARNING log. Drop is intentional (D-13 -- pipeline integrity over episode completeness).
- Stamps `regime_epoch` from `current_epoch_provider()` (C-01).
- `MEMORY_WRITE_QUEUE_DEPTH.set(qsize, {})` after every call.

**EmbeddingWorker._drain():**
- `await queue.get()` loop until `stop()` called.
- Calls `EmbeddingService.embed_context(context_proxy)` -- never skips the INSERT on embedding failure; rows with `embedding=NULL` are still persisted (offline back-fill handles re-embedding, D-05).
- SQL: `INSERT INTO memory_episodes_raw (..., $7::vector, ...)` -- vector parameter formatted as `[x,y,z,...]` string with `::vector` cast (asyncpg sends as text, pgvector parses -- same pattern as PgvectorEpisodicBackend).
- `MEMORY_EMBED_STALL_SECONDS.set(time.monotonic() - last_drain_completed_at, {})` every iteration (F1 stall alert > 30s).

**_EpisodeContextProxy:** Ring 0 duck-typed proxy exposing episode dict fields as attributes so `EmbeddingService.serialize()` works without Ring 1 imports.

**WorkerContext update:** `memory_client: Any | None` -> `memory_client: MemoryClient | None` via `TYPE_CHECKING` import. Docstring updated from "Zep memory integration" to "agent memory integration (Phase 097)". Dataclass remains frozen, field default unchanged (None).

### Task 4 -- MemoryClientFactory + AlphaSwarm Wiring

`src/core/memory/factory.py` -- two public functions gated on `settings.agent_memory_enabled`.

**`build_memory_client(settings, db_pool)`:**
- Returns None immediately when `agent_memory_enabled=False` (log "memory.disabled").
- When True: constructs EmbeddingService + 4 backends + MemoryClient. Any exception caught -> WARNING + return None.

**`build_memory_writer(settings, db_pool, queue_maxsize, current_epoch_provider)`:**
- Same gate pattern. Constructs EmbeddingService + MemoryEpisodeWriter.

**AlphaSwarm wiring (reference site):**
- Import: `from src.core.memory.factory import build_memory_client`
- `__init__`: `self._memory_client: Any | None = None`
- `_setup()`: `self._memory_client = build_memory_client(self.settings, self._pool)` (called after `super()._setup()` so `self._pool` is available)

## Verification

```
from src.core.memory.backends.mem0 import Mem0BackendImpl  # import ok (mem0ai absent)
grep asyncio.to_thread src/core/memory/backends/mem0.py    # found
from src.core.memory.client import MemoryClient             # import ok
grep -c "def store|def write|INSERT" src/core/memory/client.py  # 0
from src.core.memory.writer import MemoryEpisodeWriter, EmbeddingWorker  # ok
grep put_nowait src/core/memory/writer.py                  # found
grep MemoryClient src/core/ai/worker_context.py            # found
from src.core.memory.factory import build_memory_client, build_memory_writer  # ok
grep agent_memory_enabled src/core/memory/factory.py       # found
grep build_memory_client services/alpha_swarm.py           # found
ruff check src/core/memory/ src/core/ai/worker_context.py services/alpha_swarm.py  # all passed
pytest tests/unit/ -q                                      # 4310 passed, 29 skipped
```

## Deviations from Plan

None -- plan executed exactly as written.

## Self-Check

**Created files:**
- [x] `src/core/memory/backends/mem0.py` -- FOUND
- [x] `src/core/memory/client.py` -- FOUND
- [x] `src/core/memory/writer.py` -- FOUND
- [x] `src/core/memory/factory.py` -- FOUND

**Modified files:**
- [x] `src/core/ai/worker_context.py` -- FOUND
- [x] `services/alpha_swarm.py` -- FOUND

**Commits:**
- [x] 322da009 -- Task 1 Mem0BackendImpl
- [x] c7166d9f -- Task 2 MemoryClient
- [x] 3e7f3b1f -- Task 3 MemoryEpisodeWriter + WorkerContext
- [x] ea04ffca -- Task 4 factory + alpha_swarm

## Self-Check: PASSED
