---
status: completed
priority: P0
filed: 2026-07-17
closed: 2026-07-17
source: 143.1-07 corpus re-run crashed twice at the identical transition point
---

# `ic_engine.py`'s cross-sectional pass holds one DB connection idle across hours of compute — same defect as todo 102, never generalized

## Finding

The 143.1-07 corpus re-run crashed twice, both times at the identical structural point: the
per-symbol pass finishes cleanly (80/80 symbols), the cross-sectional (POOLED) pass begins,
completes exactly one (regime_group, tf, regime_label) cell after several hours of clustering +
circular block bootstrap resampling, then dies on `"server closed the connection unexpectedly"`
the instant the next cell's first query runs.

Root cause, confirmed by direct code inspection: `_compute_cross_sectional_tf`
(`services/ic_engine.py`) took a live `conn` parameter, and its caller opened ONE connection
(`cs_conn = _connect_db(settings)`) held across the *entire* nested `group × tf × regime_label`
loop — every cell in the whole cross-sectional pass shared one connection. Confirmed via source
inspection that `conn` is used only during the e-value prefetch, the regime-timestamp prefetch,
and the 73-chunk data fetch — zero DB access happens during the subsequent clustering/bootstrap
computation, which for a single cell can run for hours. This is the exact same anti-pattern
already found and fixed for the per-symbol path by todo 102 (2026-07-12: `_compute_symbol_tf`
now opens/closes short-lived connections around each DB-needing phase instead of holding one
across the compute-only gap) — todo 102's fix was simply never extended to this sibling
function, which is why the identical failure mode recurred here.

A contributing/aggravating factor was also found and fixed separately: `indicagent-tempo` had
been crash-looping continuously for 3 weeks (todo 044's own fix was wrong — see
[todo 127](127-tempo-crashloop-todo044-fix-was-wrong.md)), churning the same Docker bridge
network TimescaleDB sits on every ~60 seconds. That's a plausible amplifier for a silently
dropped idle connection, but not the root cause — the architectural flaw (a 9-hour idle,
unkept-alive connection) is fragile against any cause of a dropped connection, not just this one.

## Fix

Applied todo 102's already-proven pattern to `_compute_cross_sectional_tf`:
- Signature changed `conn: Any` → `dsn: str`.
- Opens its own short-lived connection right after the (DB-free) idempotency short-circuit
  check, applies the session tuning (`SET max_parallel_workers_per_gather = 0`, `SET work_mem =
  '256MB'`) that used to be set once on the caller's long-lived connection, and closes it
  immediately after the chunked fetch loop completes — before the clustering/bootstrap compute
  begins. Both early-return paths (`no regime_timestamps`, `X_raw is None`) also close the
  connection.
- Caller no longer opens a persistent `cs_conn`; each cell's call passes
  `dsn=settings.database_url` directly. The per-group regime-label-list query (previously on
  `cs_conn`) now opens its own short-lived connection too.

TDD: added `test_compute_cross_sectional_tf_takes_dsn_not_live_connection` and
`test_compute_cross_sectional_tf_closes_connection_before_clustering` to
`tests/unit/test_ic_engine_compute_split.py` (structural regression guards, same style as the
existing `_compute_symbol_tf` tests in that file — confirmed both fail against the pre-fix code,
pass after). Full `tests/unit/` suite green, no regressions.

## Not yet done

- The corpus re-run itself needs restarting from scratch after this fix lands on `main`
  (`feature_ic_scores` was 0 rows at both crash points, so there's nothing to resume from —
  todo 121, still open, tracks the separate intra-step-checkpointing gap that makes every
  crash this costly).
- Todo 121 (no intra-step checkpoint in `ic_engine`) is a related but distinct gap — this fix
  prevents the crash; todo 121 would make a *future* crash (from an unrelated cause) cheaper to
  recover from. Both are worth having; this todo only closes the former.
