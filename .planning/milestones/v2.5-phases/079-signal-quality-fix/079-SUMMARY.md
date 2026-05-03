# Phase 79: Signal Quality Fix — Zone Width + Entry Price

**Status:** COMPLETE (2026-05-03)
**Branch:** `fix/phase-79-signal-quality` (merged to main)

## Problem

All I7 signals had zero-width zones (entry==stop==target) because plugins built signal dicts manually instead of using the centralized helper. This caused 99.7% of signals to never activate (price never exactly hits a point-level entry).

## Solution

1. **`make_signal_from_frame()`** — new helper in `src/intelligence/trading/signal_schema.py` that propagates zone high/low from FVG/OB/SR context and resolves entry_price correctly for at_pullback and at_limit entry types.

2. **All 36 I7 plugins migrated** — every plugin now calls `make_signal_from_frame()` instead of building signal dicts manually. Manual construction was the root cause of zero-width zones.

3. **`signal_schema_version` column** — 'v0' = pre-fix (contaminated, zero-width zones, potentially wrong entry_price), 'v1' = post-fix. ML training queries MUST filter `WHERE signal_schema_version = 'v1'`.

4. **`entry_type` column** — populated by `make_signal_from_frame()`. Values: `at_close`, `at_pullback`, `at_limit`, `at_reclaim`, `zone_proximal`.

5. **Co-fire tracking** — `co_fire_count` and `co_fire_partners` columns track signals firing on the same bar with identical entry/stop/target levels.

6. **Signal quality metrics** — Prometheus metrics for zone width, entry type distribution, co-fire rates.

## Commits (10)

1. `708d1b4d` — docs: implementation plan
2. `0f4fb4b2` — docs: design spec
3. `1e6b08f8` — feat(079-01): make_signal_from_frame() helper with zone propagation
4. `b36eeaa0` — feat(079-02): wire zone mapping + extend LedgerEntry
5. `08d89ac0` — fix(079-04): migrate batch 1 plugins
6. `729e3900` — fix(079-05): migrate batch 2 plugins
7. `1e77655f` — fix(079-06): migrate batch 3 + microstructure_utils
8. `c1b27eb0` — fix(079-07): migrate remaining plugins
9. `d8a2bd17` — feat(079-08): signal quality metrics + co-fire tracking
10. `ad778fb1` — docs: update CLAUDE.md
11. `d0c0082a` — simplify: hoist import, fix missing outcome metric, tighten types
