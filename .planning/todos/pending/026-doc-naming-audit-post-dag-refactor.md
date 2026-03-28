---
created: 2026-03-28T00:00:00.000Z
updated: 2026-03-28T00:00:00.000Z
title: Doc naming audit — post-DAG refactor stale references
area: documentation
priority: 26
tier: near-term
files:
  - docs/concepts/data-pipeline.md
  - docs/concepts/signal-lifecycle.md
  - docs/concepts/intelligence-tiers.md
  - docs/concepts/cis-scoring.md
  - docs/architecture/event-driven-indicator-system.md
  - docs/architecture/comprehensive-intelligence-architecture.md
  - docs/architecture/intelligence-bus.md
  - docs/architecture/dual-feed-ohlcv-strategy.md
  - docs/architecture/principles.md
  - docs/cheatsheet.md
---

## Problem

Phases 52.4, 53.2, 53.3 renamed/retired several services. The following stale names
remain in docs/ files (operational scripts already fixed 2026-03-28):

- `tws_daemon` / `indicagent-tws` → `DataProviderAgent` / `indicagent-data-provider`
- `signal_lifecycle_service` / `SignalLifecycleService` / `indicagent-signal-lifecycle` → `signal_tracker_agent` / `SignalTrackerAgent` / `indicagent-signal-tracker`
- `feature_pipeline_service` / `FeaturePipelineService` / `indicagent-feature-pipeline` → `feature_compute_agent` / `FeatureComputeAgent` / `indicagent-feature-compute`
- `indicagent-indicator` (retired Phase 52.2) — remove all references
- Architecture diagrams referencing 6-stage microservice DAG (retired Phase 44.2)

## Solution

Global search-replace across docs/ for each stale name. Update architecture diagrams
to reflect current v2.2 DAG (DataProviderAgent → BarAggregatorComputeAgent → FeatureComputeAgent
→ SignalGeneratorAgent → SignalTrackerAgent).
