---
priority: P2
status: pending
source: /simplify pass on Phase 173's diff, 2026-08-26 (efficiency review agent)
---

# `bar_ts_arr` carried as `dtype=object` + a 3rd redundant pass over `batch` in the
# broadcast-cell chunked fetch (services/ic_engine.py, the OOM-history function family)

## Two related findings, same function, same fix session

**1. `bar_ts_arr` is `dtype=object` (Python `datetime` per element) on the exact function
family with the 2026-07-08 OOM incident.** `services/ic_engine.py` ~line 3938:
`bar_ts_chunks.append(np.array([r[0] for r in batch], dtype=object))`. At the documented
largest real cell (~9.4M rows), an object array of `datetime` costs ~500-600MB more than an
`int64`/`datetime64[ns]` column, and makes the core boundary-scan comparison
(`bar_ts_arr[1:] != bar_ts_arr[:-1]`, ~line 3383 — the mechanism `_compute_one_broadcast_cell`'s
whole design is built around) fall back to per-element Python `__ne__` instead of a vectorized
kernel. DAG invariant 6 (all timestamps UTC everywhere) should make a `datetime64[ns]` cast safe
— the code's own docstring worry about tz-loss shouldn't apply if the source is already
normalized UTC, but this needs verifying against the actual upstream row values before changing.

**2. A third full pass over `batch` added solely to extract `bar_ts`.** Same loop already
walks `batch` twice (`X_acc.append_chunk([...for r in batch])` and
`for i, row in enumerate(batch): ...`); the `bar_ts_chunks.append(...)` list comprehension is a
third independent walk of the same rows, purely to pull `row[0]`. Capturing `row[0]` inside the
existing `for i, row in enumerate(batch):` loop would cost nothing extra.

## Why not fixed inline during /simplify

Both touch `_compute_cross_sectional_tf`'s chunked fetch loop — live-merged, smoke-tested
against production, reviewed by two independent AI reviewers already. Fixing #1 correctly
requires confirming the UTC-normalization guarantee actually holds for every upstream row
source feeding this function (not just asserting DAG invariant 6 in the abstract), and ideally
re-running the live smoke test to confirm memory/behavior are unchanged — a multi-hour
verification budget this /simplify pass didn't have. Deferred rather than hand-edited under
time/context pressure on a live significance-gate function.

## Recommendation

Fix both together in one pass (same function, same session, natural to verify jointly): cast
`bar_ts_arr` to `datetime64[ns]` (or raw epoch `int64`) at construction, and fold the `bar_ts`
extraction into the existing per-row loop instead of a separate comprehension. Re-run the
smallest-and-one-medium-cell smoke test (per Plan 04's own precedent) to confirm no behavior
change before merging.
