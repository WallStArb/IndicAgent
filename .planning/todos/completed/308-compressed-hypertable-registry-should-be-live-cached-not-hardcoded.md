# 308 - Replace _KNOWN_COMPRESSED_HYPERTABLES's hardcoded set with a process-lifetime-cached live query

**Filed:** 2026-08-14
**Closed:** 2026-09-17
**Source:** `/simplify` altitude-angle review, second pass, of the todo 306 compressed-
hypertable-write-session fix (`services/_batch_utils.py`). See that function's docstring for
context; this todo is the deferred follow-up it points to.
**Status:** CLOSED -- shipped, with a scope correction to this todo's own recommended
approach (see Resolution below).

## Resolution (2026-09-17)

Implemented steps 1, 2, and 4 of the recommended approach below largely as written:
`_known_compressed_hypertables(conn)`/`_known_compressed_hypertables_async(conn)` now
live-query `timescaledb_information.hypertables` and cache for the process lifetime,
shared between drivers; `bulk_update_by_key`'s guard uses this live-cached set.

**Step 3 was wrong and NOT implemented as written** -- caught by `/code-review`, confirmed
against the live database (which has 26 compressed hypertables today, not 2).
`_validate_compressed_hypertable` is a *different* check than `bulk_update_by_key`'s guard,
with the *opposite* risk direction, and must not share the same live-queried set:

- `bulk_update_by_key`'s guard answers "is this table compressed at all" (any compressed
  table needs a session) -- a table **missing** from a hand-maintained list is the
  dangerous direction (a write silently proceeds unprotected). The live query is the right
  fix here, exactly as this todo scoped it.
- `_validate_compressed_hypertable` (inside `compressed_hypertable_write_session`) answers
  "has THIS specific, disruptive mechanism (decompress-all, pause compression jobs,
  override session GUCs, bare VACUUM) actually been built and incident-hardened for this
  table" -- a table **present** that shouldn't be is the dangerous direction. Live-querying
  this one (as step 3 proposed) would have silently widened a tight, deliberate 2-table
  allow-list into "any of the 26 live compressed tables," including e.g.
  `market_data_ohlcv` (258 chunks, active compression policy) -- a future/mistaken call
  would have run this session's full sequence against a table it was never validated
  against, with no error.

Kept `_validate_compressed_hypertable` as a small, static, hand-curated allow-list
(renamed the underlying constant `_WRITE_SESSION_HARDENED_TABLES` for clarity, distinct
from the live-cache accessor's name) -- step 5 ("delete `_KNOWN_COMPRESSED_HYPERTABLES`
once nothing references it") still happened, just split into two differently-purposed
successors instead of one. Verified live: `_validate_compressed_hypertable("market_data_
ohlcv")` correctly raises; `_known_compressed_hypertables(conn)` correctly includes it
(26-table live count confirmed via direct query). Full unit suite green, `/simplify`
(4-agent reuse/simplification/efficiency/altitude pass) and `/code-review` both run before
commit -- the code-review pass is what caught this.

## What

`services/_batch_utils.py`'s `_KNOWN_COMPRESSED_HYPERTABLES = frozenset({"feature_vectors",
"feature_ic_scores"})` is a hardcoded literal `bulk_update_by_key`'s guard checks on every
write call (must stay a hot-path-cheap, DB-round-trip-free check). The two drift directions
are NOT equally safe:

- A table left in the set after it stops being compressed: harmless.
  `compressed_hypertable_write_session`'s own per-entry chunk query just finds zero chunks and
  no-ops.
- A table **missing** from the set -- becomes compressed later, or is used via
  `bulk_update_by_key` for the first time while already compressed, before a human remembers
  to add it here: **silently unprotected.** `bulk_update_by_key`'s guard is gated on
  membership in this exact set, so a missing entry means the guard simply never fires -- no
  error, no log, the write proceeds unwrapped, and the ~1000x-slower forced-seq-scan bug this
  entire mechanism exists to prevent reintroduces itself with zero warning.

## Why deferred, not fixed 2026-08-14

This codebase has already solved "avoid a hot-path DB call while staying synced to live
truth" twice -- `ConfigService` (APR) and `VocabularyService` (CVR) both cache at process
init, zero hot-path DB calls after that. The correct fix mirrors that: a process-lifetime
cache populated by one live query (`SELECT hypertable_name FROM timescaledb_information.
hypertables WHERE compression_enabled`) on first use, shared between the sync (`psycopg`) and
async (`asyncpg`) call paths since the underlying fact doesn't depend on which driver asks.

Not implemented in the same sweep that added `_KNOWN_COMPRESSED_HYPERTABLES` because a shared
mutable module-level cache has real cross-test-isolation implications (tests would need an
autouse fixture resetting the cache between runs to avoid one test's mocked DB response
leaking into another's assertions) and a sync/async cache-sharing design deserves its own
focused pass -- same reasoning `services/ic_engine.py`'s write paths were deferred to todo 307
under, not a double standard.

## Recommended approach

1. Add a module-level `_compressed_hypertable_names_cache: frozenset[str] | None = None` plus
   `_known_compressed_hypertables(conn) -> frozenset[str]` (sync, populates via psycopg on
   first call) and `_known_compressed_hypertables_async(conn) -> frozenset[str]` (async,
   populates via asyncpg) sharing the same cache variable.
2. `bulk_update_by_key`'s guard switches from `table in _KNOWN_COMPRESSED_HYPERTABLES` to
   `table in _known_compressed_hypertables(conn)`.
3. `_validate_compressed_hypertable` gains a `conn` parameter and uses the same live-cached
   set -- this also means a genuinely-new compressed hypertable no longer needs a manual
   `_KNOWN_COMPRESSED_HYPERTABLES` literal edit at all; it's discovered automatically.
4. Add a `pytest` autouse fixture (in `tests/unit/test_batch_utils.py`) that resets
   `services._batch_utils._compressed_hypertable_names_cache = None` before each test in the
   affected test classes, so mocked DB responses in one test can't leak into another via the
   shared module-level cache.
5. Delete `_KNOWN_COMPRESSED_HYPERTABLES` once nothing references it.

## Where

- `services/_batch_utils.py` (`_KNOWN_COMPRESSED_HYPERTABLES`, `_validate_compressed_
  hypertable`, `bulk_update_by_key`'s guard)
- `tests/unit/test_batch_utils.py` (needs the cache-reset fixture)
- Reference pattern: `src/config/config_service.py` (`ConfigService`), `src/config/
  vocabulary_service.py` (`VocabularyService`) -- both already do cache-at-init correctly for
  the structurally identical problem.
