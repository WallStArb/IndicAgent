---
created: 2026-03-27T11:22:20.832Z
title: Fix naive datetime.now() calls in agent services
area: services
files:
  - services/indicator_compute_agent.py:204
  - services/indicator_compute_agent.py:616
  - services/intelligence_compute_agent.py:92
  - services/intelligence_compute_agent.py:568
---

## Problem

Four `datetime.now()` calls (naive, no timezone) exist in live agent services.
The DB expects `timestamptz` and all timestamps in the codebase must be UTC-aware
per CLAUDE.md. Naive timestamps silently produce wrong values when the host
timezone differs from UTC, and asyncpg may reject them on batch insert.

`datetime.now()` → `datetime.now(UTC)` (or `datetime.now(tz=UTC)`)

## Solution

Four one-line fixes across two files:

- `services/indicator_compute_agent.py` lines 204, 616
- `services/intelligence_compute_agent.py` lines 92, 568

These files will be touched during the BaseAgent migration phase anyway —
fix these first so the migration diff is clean. Run `.venv/bin/ruff check .`
after to confirm no remaining naive datetime calls in service files.
