---
created: 2026-06-11T00:00:00.000Z
title: feature_replay.py — Feature-layer replay script (bypass I1–I6 recompute)
area: infrastructure
files:
  - production/scripts/feature_replay.py
  - production/scripts/historical_backfill.py
---

## Problem

Phase 121 replay took hours because `historical_backfill.py --replay-only` re-runs I1→I6 even when `intelligence_features` is valid (ON CONFLICT DO NOTHING discards the result). 100% of I1→I6 compute is wasted. The DAG rule: replay enters at the earliest *invalid* node.

## Action

Build `production/scripts/feature_replay.py`:
- Input: existing `intelligence_features` (already valid, skip I1–I6 entirely)
- Process: stream features in time order → reconstruct IntelligenceEvent → run specified I7 plugins → upsert signal_ledger via deterministic ID
- CLI: `--plugins shadow_setups` to scope to specific plugins
- Expected runtime: minutes, not hours

This permanently eliminates the hours-long replay cycle for all future shadow signal regeneration passes.

## Notes

- Design: `memory/project_replay_architecture.md` — full DAG analysis
- Also add decompress/recompress stages wrapping bulk DML (signal_ledger has 51 compressed chunks — DELETE across compressed chunks forces per-tuple decompression)
- Vectorized lifecycle evaluation (numpy per-bar batch) is a follow-on after this is built
