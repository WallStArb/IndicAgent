---
status: pending
priority: P3
filed: 2026-07-17
moved_to_deferred: 2026-07-19
revived: 2026-07-23 — narrow scope closed via Phase 162, wider scope moved back to pending/
source: altitude finding from /simplify review of todo 128 (ic_engine cross-sectional
  connection-lifecycle fix); narrowed 2026-07-17 after a /simplify pass on todo 130's
  diff resolved the Settings-based half
---

**Narrow scope CLOSED 2026-07-23 (Phase 162-01):** the 3 dsn-based worker connections in
`_compute_symbol_tf`/`_compute_cross_sectional_tf` now use `short_lived_conn(dsn)`, a
`@contextmanager` in `services/_batch_utils.py` (tested:
`tests/unit/test_batch_utils_short_lived_conn.py`). This was the scope Phase 162 actually
covered.

**Wider scope still open, revived to pending/:** Phase 162 is now complete and, as noted below,
never covered the Settings-based sibling helper or the 4 other services (`regime_writer.py`,
`equity_regime_model.py`, `backfill_feature_factory.py`, `cross_sectional_regime_model.py`) --
that cross-service cleanup remains unclaimed. No longer appropriate to sit in `deferred/`
pointing at a phase that's already shipped without touching it.

## RESULT (2026-07-27): partially fixed -- one genuine drop-in migrated, three deliberately left alone with reasons.

**Correction (same-session /simplify pass):** initially added a `short_lived_conn_from_settings(settings)`
context-manager helper to `services/_batch_utils.py`, but the actual migration below calls
`connect_db_from_url(settings.database_url)` directly (the byte-identical replacement was
plain enough not to need the wrapper). The helper ended up with zero callers anywhere in the
repo -- caught by a /simplify altitude review, deleted rather than left as speculative dead
code. If a genuine scoped-connection caller needs it later, add it then.

Audited all 4 remaining services' actual connection code before touching anything (not just
their names):
- **`cross_sectional_regime_model.py` -- MIGRATED.** Its local `_connect_db(settings)` was
  byte-identical to `connect_db_from_url(settings.database_url)` (same `autocommit=False`,
  no special options) -- a genuinely safe drop-in, zero behavior change. Deleted the local
  function, both call sites now call `connect_db_from_url` directly. Full relevant test suite
  green.
- **`regime_writer.py` -- NOT migrated, found a real reason not to.** All 3 of its connect
  sites use `options="-c idle_in_transaction_session_timeout=0"`, a deliberate protection for
  its long-running HMM fits that `short_lived_conn`/`connect_db_from_url` don't support.
  Forcing this service onto the generic helper would silently drop that protection -- a real
  regression risk, not a style nit.
- **`backfill_feature_factory.py` -- NOT migrated, found a real reason not to.** Its
  `_connect_db` sets `autocommit=True` (the generic helper defaults `False`) and registers a
  UUID type adapter (`feature_vector_id` serialization) -- both load-bearing, not oversights.
- **`equity_regime_model.py` -- confirmed dead, not touched.** `CLAUDE.md`/STATE.md both
  confirm this was replaced by `cross_sectional_regime_model.py` in Phase 144; no systemd unit,
  no live consumer. Not worth spending effort DRY-ing up retired code.
- **`ic_engine.py`'s own local `_short_lived_conn(settings)` -- deliberately left unmigrated.**
  Its corpus recompute (todo 183) was confirmed still running live during this session
  (`ps aux`, 20+ hours elapsed) -- exactly the "too high-blast-radius to touch outside a
  dedicated, tested change" scenario this todo already flagged. The shared helper is ready and
  waiting for that dedicated pass once the recompute completes.

Net: the todo's "wider scope" turned out to be less mechanical than it looked at filing time --
2 of 4 sibling services have deliberate, incident-motivated connection configs that a
one-size-fits-all helper would have silently broken. Better to migrate the one genuine match
and document why the other two don't fit than to force a bad abstraction for the sake of
closing the todo completely.

# `ic_engine.py`'s 3 dsn-based worker connections still hand-rolled — extract a shared helper

## Problem (narrowed 2026-07-17 — main()-side half already fixed)

Originally filed against 5 hand-rolled `open → use → close` connection blocks: 3 dsn-based
ones inside worker functions (`_compute_symbol_tf` x2, `_compute_cross_sectional_tf` x1) plus
2 Settings-based ones in `main()` (`regime_list_conn`, `lifecycle_conn`). Todo 130's diff (same
day) added 4 more Settings-based instances of the same shape (`_write_symbol_results`,
`_write_cs_cell_results`, `backfill_conn`, `stats_conn`), growing the main()-side count to 6.

A `/simplify` pass on that diff (2026-07-17) added `_short_lived_conn(settings)` — a
`@contextmanager` right next to `_connect_db`, matching the file's existing `_observed_span`
idiom — and migrated all 6 Settings-based call sites onto it (`_write_symbol_results`,
`_write_cs_cell_results`, the checkpoint-resume loop, `regime_list_conn`,
`backfill_conn`/`stats_conn`/`lifecycle_conn` merged into one shared connection since they run
back-to-back with no intervening compute). That resolves the duplication and the
missing-try/finally gap for the main-process side.

**Still open:** the 3 dsn-based worker-side connections (`_compute_symbol_tf` x2,
`_compute_cross_sectional_tf` x1) are untouched — deliberately, not an oversight. Those
functions run inside a `ProcessPoolExecutor` worker (hence `dsn: str`, not `Settings`, since a
live connection/Settings object can't cross the process boundary) and are the multi-hour
compute-critical path a corpus run is actively executing against as of this same session —
too high-blast-radius to touch outside a dedicated, tested change. None of the 3 wrap their
fetch in `try/finally`, so an exception mid-fetch still leaks the connection in all three.

## Update (2026-07-18) — the Settings-based half isn't actually unique to ic_engine.py either

A `/simplify` pass on the ic_engine perf commits (28fe12ac/7c49593c/904c634d) found that
`_short_lived_conn(settings)` (added by the prior `/simplify` pass referenced above) reimplements
the same "psycopg2 connect → try/finally: conn.close()" shape independently duplicated in
`services/regime_writer.py`, `services/equity_regime_model.py`,
`services/backfill_feature_factory.py`, and `services/cross_sectional_regime_model.py` (each has
its own inline connect + try/finally). Widens this todo's scope: the target shared helper in
`services/_batch_utils.py` should cover both the DSN-based (worker-side) and Settings-based
(main-process-side) variants, and all 4 sibling services are candidate adopters alongside
`ic_engine.py`'s own remaining 3 dsn-based sites — not just an ic_engine-internal cleanup.

## Fix (not yet done)

Extract a shared `@contextmanager def short_lived_conn(dsn: str)` helper (natural home:
`services/_batch_utils.py`, next to `connect_db_from_url`) and migrate the 3 remaining
dsn-based call sites onto it, adding the missing `try/finally` in the process. Per the update
above, also consider a Settings-based sibling helper there and migrating `ic_engine.py`'s
`_short_lived_conn` plus the 4 other batch services' inline connect/close blocks onto it.

## References

- `services/ic_engine.py` — `_compute_symbol_tf` (todo 102), `_compute_cross_sectional_tf`
  (todo 128), `_short_lived_conn` (the new Settings-based helper, for reference/naming
  consistency)
- `services/_batch_utils.py` — `connect_db_from_url`, natural home for the new helper
- `.planning/todos/completed/102-...md`, `.planning/todos/completed/128-...md`,
  `.planning/todos/completed/130-...md`
