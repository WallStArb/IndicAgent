---
status: pending
priority: P2
filed: 2026-07-18
source: /simplify altitude review during todo 130's fix (drift.py broken import)
---

# `GET /api/drift` returns 200 + empty state on any DB failure, indistinguishable from "no drift"

## Finding

`src/api/routes/drift.py`'s `get_drift_state()` wraps its query in a bare
`except Exception: logger.warning(...)` and returns `{"ks": [], "cusum": [],
"last_updated": None}` on any failure — pool exhaustion, connection refused, query
timeout, whatever. That response is byte-for-byte identical to the genuine
"drift_state table has no rows" case. A caller (dashboard, monitor, alert) polling
this endpoint during a real DB outage sees a clean, empty, "nothing is drifting"
response instead of a signal that the check itself failed. Pre-existing behavior,
not introduced by todo 130's fix — that fix's regression test
(`test_db_error_returns_empty_state_not_500`) documents the current contract
faithfully but does not defend it.

Compare `src/api/routes/vocabulary.py`, which distinguishes a genuine backend
failure (503) from a real "unknown/empty" result (404/empty-but-known) — this
route collapses both into the same silent-success shape.

## Fix

Either (a) return a `degraded: bool` field (or similar) alongside `ks`/`cusum`
distinguishing "query failed" from "query succeeded with zero rows", or (b) raise
a 503 on query failure, matching `vocabulary.py`'s pattern. (a) is likely more
appropriate here since a dashboard polling loop shouldn't necessarily 5xx on a
routine drift check — but either is better than the current silent collapse.

## Gate

None, independent, small change.
