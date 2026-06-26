---
title: Restore IntelligencePipeline alongside FeatureVectorPipeline
priority: high — dashboard/SSE feeds depend on intelligence_features being live
depends_on: nothing (dashboard is already stale)
---

## What

Run restored I1-I7 IntelligencePipeline alongside the new FeatureVectorPipeline as two
independent systemd services on separate consumer group IDs.

## Why

Phase 137 replaced IntelligencePipeline in-place — `intelligence_features` is no longer being
populated. Dashboard screens and SSE feeds wired to v2.x APIs depend on this table being live.
Restoring the old pipeline keeps the UI working while v3.0 is built out in parallel.

Secondary benefit: once IC engine produces results, the two pipelines enable empirical comparison
of which old-tier plugin outputs add signal beyond the 36 Feature Factory primitives.

## Steps

1. Rename current `intelligence_pipeline.py` → `feature_vector_pipeline.py`, class to `FeatureVectorPipeline`
2. Update `indicagent-intelligence-pipeline.service` unit to point at new file
3. Restore pre-Phase 137 `IntelligencePipeline` (with I1-I7 dispatch) to `intelligence_pipeline.py`
4. Add new `indicagent-intelligence-pipeline.service` unit for the restored pipeline
5. Both services use distinct Kafka consumer group IDs; no write contention
6. Verify `intelligence_features` population resumes + dashboard SSE feeds are live

## Notes

- Restoration requires pre-137 code from git history (I5-I7 archived during cutover)
- Do not wait for IC results — dashboard staleness is already happening
