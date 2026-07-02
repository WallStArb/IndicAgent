# ibkr.py — migrate hardcoded numeric constants to APR

**Found:** 2026-07-02, while fixing todo 049 (Error 162 no-data heuristic hardening).

`src/providers/ibkr.py` has zero existing `ConfigService`/APR integration — every tunable
numeric value in the file is a hardcoded module constant: `_MAX_CHUNK_DAYS` (per-timeframe
chunk sizing), `_IBKR_HIST_RATE_LIMIT` / `_IBKR_HIST_WINDOW_S` (rate limiter), the retry count
(3) and backoff schedule (`65 * (2**attempt)`) in `fetch_historical_bars`, and the new
`_NO_DATA_CONFIRMATION_CHUNKS` added by todo 049. Per CLAUDE.md's APR mandate these should
all live in `config_state` under `infra.ibkr.*`.

Did not migrate `_NO_DATA_CONFIRMATION_CHUNKS` in isolation when adding it (todo 049): wiring
one new constant through `ConfigService` while its five neighbors in the same function stay
hardcoded would be a worse inconsistency than following the file's existing (non-compliant)
local convention. This is a "migrate the whole file's constant set together" job, not a
one-off.

**Action:** Add a migration seeding `infra.ibkr.max_chunk_days.<tf>`,
`infra.ibkr.hist_rate_limit`, `infra.ibkr.hist_window_s`, `infra.ibkr.retry_count`,
`infra.ibkr.retry_backoff_base_s`, and `infra.ibkr.no_data_confirmation_chunks`. Since
`ibkr.py` has no existing async DB/ConfigService wiring and is used both by the (currently
inactive) real-time provider and the batch historical backfill script, work out the right
loading pattern first — likely constructor-injected `ConfigService` on `IBKRProvider.__init__`
rather than the module-level lazy-singleton pattern (that pattern's existing registration hook,
`intelligence_pipeline._prewarm_threshold_config()`, is itself archived v2.x).

**Blocked on:** nothing technical, but it's a real design decision (injection point, whether
`fetch_historical_bars` can await a config lookup without regressing the sliding-window rate
limiter's tight timing) — not a drop-in change. Low urgency: none of these values are wrong
today, they're just not adaptive/tunable without a code change.
