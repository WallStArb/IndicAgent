---
status: partial
phase: 162-ic-engine-corpus-pipeline-throughput-incremental-recompute-t
source: [162-VERIFICATION.md]
started: 2026-07-23T07:00:00Z
updated: 2026-07-25T18:45:00Z
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
result: **FAILED for 15m, observed live 2026-07-25 during todo 092's recompute** (see prior result text below); **fixed 2026-07-29, closed as `.planning/todos/completed/182-ic-engine-15m-cross-sectional-bootstrap-threads-stale.md`.** Independently re-confirmed the same failure live during a separate equity-scoped run (same shape: one core pinned 90%+ on a 24-core idle box, 15m `high_bear` measured at 2h08m serial). Fix: `alpha.ic.cross_sectional_bootstrap_threads.{15m,1h,1d}` raised 1->8 via `ConfigService.set()`. **Not a formal wall-clock/RSS A/B benchmark as this item originally specified** -- the live production run is the de facto benchmark; a dedicated before/after timing comparison was not run separately. 1d/1h raised alongside 15m rather than left as an unverified "likely fine" guess, since they shared the identical unmeasured-`[conventional]` assumption.

Original finding (2026-07-25): `top`/`pg_stat_activity` on the running `ic_engine.py` (PID 1633901) showed 100% single-core CPU with zero active Postgres queries while the 15m `low_bull` cell ran -- pure serial compute, not I/O wait. The 15m `high_bear` cell (118,125 timestamps, 24 chunks) took 121 minutes; this is not "minutes" as the `threads=1` config description assumed. Likely cause: universe grew 58->80 symbols and features grew to 171 since the original 5m-only benchmark scoped this assumption.

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
