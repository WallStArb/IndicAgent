---
created: 2026-03-14T19:52:42.603Z
updated: 2026-03-28T00:00:00.000Z
title: Write DistribAgent implementation plan using writing-plans skill
area: planning
priority: 24
tier: deferred
files:
  - docs/plans/2026-03-14-distribagent-design.md
---

## Problem

Design for DistribAgent (standalone signal distribution service) was completed and committed during brainstorming session. The writing-plans skill was invoked to create the implementation plan but was interrupted by a server upgrade. The plan was not written.

## Solution

In a new session, invoke the `writing-plans` superpowers skill and use the design doc at `docs/plans/2026-03-14-distribagent-design.md` as the spec. The plan should cover:

1. IndicAgent prerequisite: add `GET /api/signals/performance` endpoint to `src/api/routes/signals.py`
2. New standalone repo: `distribagent/`
3. Core modules: stream_reader, signal_buffer, quality_gate, outcome_tracker, agent, broadcast_log
4. IRC adapter with rate limiting + SASL auth
5. Config loader (pydantic-settings)
6. Main asyncio entrypoint
7. Full TDD test suite

Note: DistribAgent is a **separate repo** from IndicAgent. The plan should account for this — it will need its own pyproject.toml, venv, etc.

The brainstorming session covered all design decisions. Resume from writing-plans — no need to re-brainstorm.
