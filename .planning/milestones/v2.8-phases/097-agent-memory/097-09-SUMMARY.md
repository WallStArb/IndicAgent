---
phase: 097-agent-memory
plan: "09"
subsystem: agent-memory / embedding
tags: [litellm, embedding, settings, gap-closure]
dependency_graph:
  requires: ["097-04", "097-06"]
  provides: ["litellm-routed EmbeddingService", "embedding_model setting"]
  affects: ["src/core/memory/embedding.py", "src/core/memory/factory.py", "src/config/settings.py"]
tech_stack:
  added: ["litellm.aembedding (async embedding route)"]
  patterns: ["litellm provider routing for embeddings", "api_base forwarding for ollama/ prefix"]
key_files:
  created: []
  modified:
    - src/core/memory/embedding.py
    - src/core/memory/factory.py
    - src/config/settings.py
    - tests/unit/core/test_embedding_service.py
decisions:
  - "litellm.aembedding replaces raw httpx POST for provider consistency with all other LLM calls"
  - "embed_batch() sends full list as input=texts in a single call; batch mode is a one-call op not a loop"
  - "ollama_base_url accepted as compat alias for api_base; callers update to model+api_base long-term"
  - "aclose() is a no-op; litellm manages HTTP transport lifecycle"
metrics:
  duration_minutes: 15
  completed_date: "2026-06-06"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 4
---

# Phase 097 Plan 09: LiteLLM Embedding Routing Summary

**One-liner:** EmbeddingService now routes through litellm.aembedding() with configurable model via Settings.embedding_model (default ollama/nomic-embed-text).

## What Was Built

Gap 3 closure: `EmbeddingService` previously called Ollama directly via raw httpx POST, breaking provider consistency (every other LLM call routes through LiteLLM). This plan replaces the direct httpx path with `litellm.aembedding()` and makes the embedding model configurable via `Settings.embedding_model`.

### Task 1 - Settings.embedding_model

Added `embedding_model: str` to `Settings` with:
- Default: `"ollama/nomic-embed-text"` (768-dim, same model as before, no infra change)
- Alias: `EMBEDDING_MODEL` (env var override)
- Positioned after `agent_memory_enabled` in the LLM/Ollama settings block

### Task 2 - LiteLLM-Routed EmbeddingService

Rewrote `src/core/memory/embedding.py`:
- `embed()`: `litellm.aembedding(model=self._model, input=[text], api_base=self._api_base)` replaces httpx POST to `/api/embeddings`
- `embed_batch()`: single `litellm.aembedding(input=texts)` call (batch) instead of sequential httpx loop; per-item dim validation preserved
- Constructor: `model` + `api_base` params; `ollama_base_url` accepted as backward-compat alias
- `aclose()`: no-op (litellm owns transport)
- httpx import removed entirely
- D-13/D-19 preserved: all paths return None on error, never raise
- 768-dim contract unchanged; `serialize()` and public method signatures unchanged

Updated `factory.py`: both `build_memory_client` and `build_memory_writer` now pass `model=settings.embedding_model, api_base=settings.ollama_base_url` to `EmbeddingService`.

Updated `tests/unit/core/test_embedding_service.py`: replaced httpx mock fixtures with `litellm.aembedding` patches. Added 5 new tests (batch dim-mismatch, batch empty, batch all-none-on-error, model/api_base forwarding, batch success). 16 tests total, all green.

## Verification

- `grep -n "litellm" src/core/memory/embedding.py` shows `litellm.aembedding` in embed() and embed_batch()
- `grep -c "httpx" src/core/memory/embedding.py` returns 0
- `from src.core.memory.embedding import EmbeddingService` succeeds
- All 16 unit tests green, CI-clean (no network)
- ruff check passes on all changed files

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- FOUND: src/core/memory/embedding.py
- FOUND: src/config/settings.py
- FOUND: tests/unit/core/test_embedding_service.py
- FOUND commit a4ec796e: feat(097-09): add embedding_model to Settings
- FOUND commit c33d2e8f: feat(097-09): route EmbeddingService through litellm.aembedding
