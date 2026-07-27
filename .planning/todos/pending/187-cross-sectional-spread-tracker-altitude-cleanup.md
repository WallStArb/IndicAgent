---
status: pending
priority: P3
filed: 2026-07-27
source: /simplify altitude review of Phase 167's diff (e8f993e7..HEAD), post-execution
---

## What

Two structural fixes surfaced by Phase 167's `/simplify` altitude review that were
correctly out of scope for that phase's own diff (they touch shared Ring 0 infra and
`counterfactual_tracker.py`, a file Phase 167 never modified) and were deliberately
skipped rather than fixed blind right after `cross_sectional_spread_tracker.py`
produced a live-verified Gate 1/Gate 2 PASS. Both are real, low-urgency.

**1. Bare `asyncpg.connect()` read-only evaluation connections have no shared
JSONB-codec helper.** `services/cross_sectional_spread_tracker.py`'s
`_open_evaluation_connection` (added in the same `/simplify` pass, commit `50946e79`)
now calls `_setup_codecs(conn)` once, correctly, but only within this one file.
`services/counterfactual_tracker.py:999`'s `_run_evaluate_gate` opens a bare
`asyncpg.connect()` with **no** `_setup_codecs` call at all -- it hasn't crashed
because its `_GATE_QUERY_SQL` doesn't currently select any jsonb column, but the
next jsonb column added to that query reintroduces the exact
`AttributeError: 'str' object has no attribute 'get'` bug Phase 167's Task 2 hit
and fixed locally. Fix: add a `connect_with_codecs(dsn) -> asyncpg.Connection`
helper to `src/core/database_manager.py` (thin wrapper: connect + `_setup_codecs`),
and have both `cross_sectional_spread_tracker.py`'s and `counterfactual_tracker.py`'s
read-only evaluation-mode connections call it instead of bare `asyncpg.connect()`.
Closes the bug for every current and future read-only evaluation mode in one place,
matching how `create_pool()` already centralizes it for the pooled write path.

**2. `cfg()`'s `type(default)(val)` cast is documented-broken for list defaults,
worked around locally instead of fixed at the shared layer.**
`services/cross_sectional_spread_tracker.py` reads
`alpha.construction.cost_hurdle_bps_round_trip` (a json-typed APR key whose default
is a list of ints) by bypassing `cfg()` entirely -- reading the raw dict value and
`json.loads`-ing it directly (now consolidated to one `_parse_cost_hurdle_bps`
helper by the same `/simplify` pass, but still a local workaround). The comment at
the workaround's original three call sites states plainly this is a known, general
defect in `services/_batch_utils.py`'s `cfg()`, not something specific to this key --
`list("[1,3,5,10]")` splits into characters under `type(default)(val)`.
`_batch_utils.py:168`'s `get_dict_config()` already fixes the identical class of
defect for dict-typed defaults and is reused by `backfill_feature_factory.py` and
`feature_vector_pipeline.py`; no equivalent exists for list-typed defaults. Fix:
extend `cfg()` (or add a sibling `get_list_config`-shaped helper) in
`_batch_utils.py` to detect a non-scalar default (list/dict) and `json.loads` the
raw string instead of blindly casting -- one shared fix instead of a local
workaround, available to any future caller of `load_apr_dict_async` with a
json-typed list key.

## Why P3

Both are correctness-neutral (current call sites all work correctly today) and
low-blast-radius (each only bites the *next* caller who adds a jsonb column to a
bare-connect query, or a *next* list-typed json APR key). Not worth touching
`database_manager.py`/`_batch_utils.py` -- both shared across many services -- as
a reactive fix; batch with the next phase that touches either file, or do it
standalone when convenient.
