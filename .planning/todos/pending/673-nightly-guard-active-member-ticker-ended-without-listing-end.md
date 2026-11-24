---
status: pending
priority: P2
filed: 2026-11-24
source: indicagent-fb, BKH data gate refusal (corpus pilot 7c5612f0, step data_gate), lead brief 2026-11-24
---

# Nightly guard: an active member whose newest 1d bar is stale and has no listing end

## What

A name whose ticker ends (a merger, a rename, a delisting) stays active and in the universe. Until someone records a
`listing_end` row (migration only, append-only) the 1d verdict judges it to the last completed session. The trailing
unanswered sessions pass quietly until session coverage over the proven span drops under the floor, then
`proven_start_1d` turns false and the corpus data gate refuses the name. BKH: bars end 2026-11-13, coverage passed with 5
trailing sessions missing (0.99914) and failed with 6 (0.99897), so the refusal arrived 6 sessions after the ticker ended,
at the worst time (the pilot). `freshness_1d` was red for the name the whole week and nothing acted on it.

## Done when

A nightly check (an existing auditor, not a new service) lists every active `universe_membership` name whose newest
`market_data_ohlcv_tradeable` 1d bar is more than 3 NYSE sessions older than the last completed session and that has no
`listing_end_current` row, and reports the count and names as a metric plus a log line (job metric through
`src/observability/metrics.py`). The 3 is an APR key (`alert.*` or `infra.*`), not a constant. Read-only: it records
nothing and never writes `listing_end`. A test seeds one stale member with and without a listing end. After the corpus run
is quiet (the verdict code is imported by the pinned rebuild closure); check whether the edit moves `rebuild_code_key()`
first and land it only when no live fingerprinted run imports the module.
