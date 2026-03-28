---
created: 2026-03-20T22:37:58.697Z
updated: 2026-03-28T00:00:00.000Z
title: Add OpenTelemetry distributed tracing to microservices pipeline
area: observability
priority: 21
tier: feature
files: []
---

## Problem

Silent pipeline failures are hard to diagnose — today's incident (AI narrative silent for hours, signals stalled) required manually correlating timestamps across 8 separate log files. No way to follow a single bar event through the full pipeline. When a service is consuming but not producing, there's no trace to show where it stalled.

## Solution

Add OTel distributed tracing with context propagation through Redpanda message headers. Deploy OTel Collector + Grafana Tempo (see ROADMAP phase 52.7). Instrument each agent to emit spans at produce/consume boundaries so a bar event can be traced end-to-end:

```
DataProviderAgent → BarAggregatorComputeAgent → FeatureComputeAgent → SignalGeneratorAgent → FeatureWriterAgent
```

Use BaseAgent's `self.tracer` (added in Phase 52.6) — do not duplicate tracer initialization in each agent. Inject trace context into Redpanda message headers at produce time; extract at consume time.

## Notes

- Depends on Phase 52.6 (BaseAgent ProcessManifest + `self.tracer`) and Phase 52.7 (Tempo infra)
- All service names now follow `<concept>_agent.py` / `PascalCaseRoleAgent` convention — use the agent name (not old service name) in span labels
- See ROADMAP phase 52.8 for full Kafka trace propagation plan
