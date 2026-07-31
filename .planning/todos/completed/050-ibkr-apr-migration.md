# ibkr.py — migrate hardcoded numeric constants to APR

**CLOSED 2026-07-31** — remaining rate-limiter scope done.
`infra.ibkr.rate_limit_max_requests`/`infra.ibkr.rate_limit_window_sec` (migration 276) added,
`_SlidingWindowRateLimiter` redesigned with a `reconfigure(max_requests, window_s)` method so
APR values actually reach it, called from a new `_load_ibkr_rate_limit_config()` in the backfill
script's startup sequence, same call site and fallback contract as the existing
`_load_ibkr_chunk_days_config()`/`_load_ibkr_hist_timeout_config()`/`_load_ibkr_retry_config()`
loaders. Chose `reconfigure()` over lazy construction: `_hist_rate_limiter` stays constructed
eagerly at import time exactly as before, so `tests/unit/conftest.py`'s
`_reset_ibkr_hist_rate_limiter` fixture (todo 122) needed zero changes — it still monkeypatches
`.acquire` on an always-valid, already-constructed singleton. Default behavior (55 req/600s
window) preserved byte-for-byte for every existing caller unless an operator explicitly changes
the APR values; `self._ts` (already-recorded request timestamps) is left untouched by
`reconfigure()`, only `self._max`/`self._window` change. 6 tests added
(`tests/unit/scripts/test_run_historical_pipeline.py::TestLoadIbkrRateLimitConfig` plus the
existing `TestLoadIbkrRetryConfig` re-verified): overlay applies both keys, missing keys keep
hardcoded defaults, DB error falls back without raising. `.venv/bin/pytest tests/unit/ -k ibkr`
and `tests/unit/scripts/test_run_historical_pipeline.py` both green, no regressions.

**Found:** 2026-07-02, while fixing todo 049 (Error 162 no-data heuristic hardening).

**Status check 2026-07-14 (corpus-rebuild idle window):** this todo's own premise ("zero
existing ConfigService/APR integration") was already half-stale — migrations 197
(`infra.ibkr.chunk_days.*`) and 199 (`infra.ibkr.historical_request_timeout_sec` /
`infra.ibkr.contract_details_timeout_sec`) had already landed, overlaying APR values onto
`ibkr._MAX_CHUNK_DAYS` / `_HIST_REQUEST_TIMEOUT_SEC` / `_CONTRACT_DETAILS_TIMEOUT_SEC` in place
from `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py`'s startup
(`_load_ibkr_chunk_days_config()` / `_load_ibkr_hist_timeout_config()`) — discovered only by
checking live `config_schema` before writing a new migration, which caught an in-progress
duplicate-key mistake (see below). This todo's original "**Action**" section listing
`infra.ibkr.max_chunk_days.<tf>` was wrong on two counts: the key already existed, just without
the `max_` prefix, and inventing a second name would have created exactly the kind of
two-trackers-for-one-concept mess this project has already had to clean up once (Concept
Registry).

**Landed today (migration 235):** the 3 constants NOT covered by 197/199 — retry count (was a
bare `3` literal), retry backoff base (was inline `65`), and `_NO_DATA_CONFIRMATION_CHUNKS` (was
already a module constant, just unmigrated) — promoted to `_RETRY_COUNT` /
`_RETRY_BACKOFF_BASE_S` module constants and wired into a new
`_load_ibkr_retry_config()` in the backfill script, following the *exact* existing overlay
pattern (not the constructor-injected-ConfigService design this todo originally proposed —
that would have introduced a second, inconsistent mechanism alongside 197/199's established
one). All 3 seeded to their exact pre-migration values; behavior byte-for-byte unchanged unless
an operator explicitly changes the APR values. 3 tests added
(`tests/unit/scripts/test_run_historical_pipeline.py::TestLoadIbkrRetryConfig`): overlay
applies all 3 keys, missing keys keep hardcoded defaults, DB error falls back without raising.

**Remaining scope — deliberately NOT done today:** `_IBKR_HIST_RATE_LIMIT` /
`_IBKR_HIST_WINDOW_S` (the sliding-window rate limiter). Unlike the other constants, that pair
backs a module-level `_SlidingWindowRateLimiter` singleton constructed *eagerly at import time*
— before any DB connection or overlay function could possibly run. The existing overlay
pattern (mutate a module constant in place, read fresh on every use) works cleanly for
`_MAX_CHUNK_DAYS`/timeouts/retry config because those are read at each call site, but the rate
limiter reads its config only once, at `__init__`, to build its internal `deque`/`_max`/
`_window` state — overlaying the raw constants after that point wouldn't reach the already-
constructed instance. Fixing this needs either a lazy-construction redesign or a `reconfigure()`
method on the singleton, either of which also has to account for `tests/unit/conftest.py`'s
`_reset_ibkr_hist_rate_limiter` fixture (added 2026-07-14, todo 122) which currently assumes the
singleton is always a valid, already-constructed object. Real, live-trading-critical component
— correctly deserves its own focused pass, not a same-session bundle with the lower-risk
constants above.

Original problem statement, for context: `src/providers/ibkr.py` had zero existing
`ConfigService`/APR integration for several tunable numeric values. Per CLAUDE.md's APR mandate
these should live in `config_state` under `infra.ibkr.*`. Did not migrate
`_NO_DATA_CONFIRMATION_CHUNKS` in isolation when adding it (todo 049): wiring one new constant
through APR while its neighbors stayed hardcoded would have been a worse inconsistency than
following the file's existing (at the time, believed non-compliant — actually partially
compliant via 197/199) local convention.
