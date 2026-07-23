---
status: partial
phase: 162-ic-engine-corpus-pipeline-throughput-incremental-recompute-t
source: [162-VERIFICATION.md]
started: 2026-07-23T07:00:00Z
updated: 2026-07-23T07:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Full 80-symbol corpus no-op re-run wall clock
expected: Completes in minutes, not the 25-30h baseline (SC-1). Only a 5-symbol/1-tf subset was live-measured (93.9s to 3.0s, ~31x) -- mechanism proven, full-scale extrapolation not yet run.
result: [pending]

### 2. Single-symbol perturbation surgical-invalidation
expected: Perturbing one symbol's upstream data recomputes only that symbol's cells, wall clock <4h (SC-2). DELETE-scoping is unit-tested and architecturally sound; no live run has observed the real blast radius/timing.
result: [pending]

### 3. Cross-sectional bootstrap thread-count benchmark
expected: 15m/1h/1d cells (threads=1) land within ~10% of measured serial wall time; 5m (threads=6) keeps its threading speedup (SC-5). Seeded values are live in production config but unvalidated by an actual timing comparison.
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
