---
created: 2026-06-11T00:00:00.000Z
title: Deterministic Signal IDs — Replace uuid4() fallbacks with loud errors
area: intelligence
files:
  - production/scripts/historical_backfill.py
  - src/intelligence/schemas.py
  - src/intelligence/writers/signal_writer.py
  - services/alpha_swarm.py
  - services/narrative_swarm.py
---

## Problem

`make_signal_id()` (SHA-256 deterministic hash) was shipped and is used correctly in the live executor and backfill main path. But 5 defensive `uuid4()` fallbacks silently break the contract when triggered:

- `historical_backfill.py:800` — `else: uuid4()` when `last_bar is None`
- `schemas.py:925` — `or uuid4()` fallback
- `signal_writer.py:209` — `or uuid4()` fallback
- `alpha_swarm.py:491` — `or uuid4()` fallback
- `narrative_swarm.py:117` — `or uuid4()` fallback

A random ID means: deduplication fails, replay creates duplicates, signal history fractures.

## Action

Replace all 5 fallbacks with `raise ValueError(f"signal_id missing — cannot assign random ID: {context}")`. The root cause (missing bar data) should be fixed upstream, not silently papered over.

## Notes

- `make_signal_id()` is in `src/intelligence/trading/signal_schema.py`
- This is a prerequisite for the decompress/recompress replay architecture (todo 022) to work correctly at scale
