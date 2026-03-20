---
created: 2026-03-20T22:37:58.697Z
title: Add OpenTelemetry distributed tracing to microservices pipeline
area: observability
files: []
---

## Problem

Silent pipeline failures are hard to diagnose — today's incident (AI narrative silent for hours, signals stalled) required manually correlating timestamps across 8 separate log files. No way to follow a single bar event through the full pipeline. When a service is consuming but not producing, there's no trace to show where it stalled.

## Solution

Add OTel distributed tracing with context propagation through Redpanda message headers. Deploy OTel Collector + Jaeger/Tempo. Instrument each service to emit spans at produce/consume boundaries so a bar event can be traced end-to-end: TWS → indicator_service → market_analysis_service → signal_generator_service → feature_writer_service.

Candidate for Phase 48 (after Phase 47 Renaissance Observability).
