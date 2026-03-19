# Rewrite /signals/recent tier_clause Dynamic SQL

**Created:** 2026-03-19
**Priority:** Medium
**Effort:** Small (1–2h)
**Source:** Phase 39 DB institutional audit

## Problem

`src/api/routes/signals.py` — `get_recent_signals()` builds the WHERE clause via f-string injection:

```python
if tier == "hero":
    tier_clause = "AND sl.was_selected = true AND sl.confidence >= 0.40 AND abs(sl.cis_score) > 0.35"
elif tier == "monitored":
    tier_clause = "AND sl.was_selected = true"
else:
    tier_clause = ""

query = f"""
    SELECT ...
    FROM signal_ledger sl
    WHERE ...
      {tier_clause}
    ORDER BY ...
"""
```

**Two problems:**

1. **Plan cache pollution**: asyncpg caches query plans by query string. Three different `tier_clause` values produce three different query strings → three different plans, none of which are recognized as the same query. Under load this inflates the plan cache and prevents optimization.

2. **SQL injection surface**: `tier` comes from a validated FastAPI `Literal["hero","monitored","candidate"]` parameter today — safe. But if that validation is ever weakened or the pattern is copy-pasted, it becomes an injection vector. Institutional code does not have f-strings in SQL.

## Fix

Rewrite using fixed parameterized predicates with nullable boolean logic:

```python
# hero:     was_selected=true, confidence >= 0.40, abs(cis_score) > 0.35
# monitored: was_selected=true, no confidence gate
# candidate: no filter (was_selected may be false)

query = """
    SELECT ...
    FROM signal_ledger sl
    LEFT JOIN setup_performance sp ON sp.setup_plugin = sl.setup_plugin
    WHERE ($1::text IS NULL OR sl.symbol = $1)
      AND ($2::text IS NULL OR sl.timeframe = $2)
      AND (NOT $4::boolean OR sl.was_selected = true)
      AND (NOT $5::boolean OR (sl.confidence >= 0.40 AND abs(sl.cis_score) > 0.35))
    ORDER BY COALESCE(sl.signal_computed_at, sl.feature_ts) DESC
    LIMIT $3
"""

require_selected = tier in ("hero", "monitored")
require_hero_gate = tier == "hero"

rows = await db_manager.fetch(query, resolved_symbol, timeframe, limit, require_selected, require_hero_gate)
```

Single query string → single cached plan. No f-string. No injection surface.

## Notes

- `NOT $4::boolean OR condition` is the idiomatic Postgres "optional filter" pattern — when `$4=false`, the condition short-circuits to TRUE.
- After Phase 39 adds `effective_ts` generated column, also update the `ORDER BY COALESCE(...)` to `ORDER BY sl.effective_ts DESC`.
- Add a covering index `(symbol, timeframe, effective_ts DESC) INCLUDE (was_selected, confidence, cis_score, status, outcome)` so the new fixed query can do an index-only scan.

## Files

- `src/api/routes/signals.py` — `get_recent_signals()` function, approx lines 260–400
- Add unit test: `tests/unit/api/test_signals_recent.py` — verify all 3 tier values produce correct SQL behavior
