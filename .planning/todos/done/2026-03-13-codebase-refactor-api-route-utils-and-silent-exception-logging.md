---
created: 2026-03-13T09:24:07.241Z
title: "Codebase refactor: API route utils and silent exception logging"
area: api
files:
  - src/api/routes/features.py:32-57
  - src/api/routes/signals.py:24-49
  - src/api/routes/sse.py:74-101
  - src/api/utils.py
  - services/feature_writer_service.py:214-218
  - services/signal_generator_service.py:463-467
---

## Problem

Two patterns need fixing:

1. **API route duplication** — `_get_settings()`, `_resolve_contract()`, and `_parse_jsonb()` are copy-pasted across `features.py`, `signals.py`, and `sse.py`. The `features.py` comment even says "same as sse.py". Any change (e.g. contract roll logic) must be applied in 3 places.

2. **Silent exception fallbacks** — `_load_config()` in `feature_writer_service` and `signal_generator_service` both have `except Exception: _settings = None` with no log output. When Settings() fails at startup, the service silently degrades to hardcoded defaults with no trace in journalctl.

## Solution

Full plan at `docs/plans/2026-03-13-codebase-refactor.md`.

**Chunk 1 — Extract API route utilities:**
- Create `src/api/utils.py` with `get_settings()` (@lru_cache), `resolve_contract()` (sse.py's version — most complete, handles VX regex fallback), and `parse_jsonb(value, *, default=None)` (default param handles the `{}` vs `None` difference between routes).
- Update `features.py`, `signals.py`, `sse.py` to import from `src/api/utils`.

**Chunk 2 — Add logging to silent Settings() fallbacks:**
- `feature_writer_service.py`: 2 blocks — env_prefix fallback + _load_config.
- `signal_generator_service.py`: 1 block — _load_config.
- Add `logger.warning(...)` to each — behavior unchanged, failures become visible.

**Future work (separate phase):** BaseAsyncService, PluginExecutor, ConsumerGroupWarmup — tracked as backlog in the plan doc.
