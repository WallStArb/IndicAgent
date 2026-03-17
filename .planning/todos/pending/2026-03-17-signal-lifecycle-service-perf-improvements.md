---
created: 2026-03-17T11:15:53.893Z
title: Signal lifecycle service performance improvements (3 items)
area: general
files:
  - services/signal_lifecycle_service.py:833-886
  - services/signal_lifecycle_service.py:655-677
  - services/signal_lifecycle_service.py:202-208
---

## Problem

Three performance/quality issues identified during phase 32 simplify pass but deferred as too complex/risky for that pass:

1. **Shadow signal O(N) loop** (`signal_lifecycle_service.py:833`): `_shadow_signals` is a flat dict iterated on every bar with a symbol/timeframe filter skip. With 50 shadow signals across many symbols/timeframes, this is O(N) per bar. Fix: index by `(symbol, timeframe)` key at insertion → only iterate relevant subset.

2. **Chandelier DB write per bar** (`signal_lifecycle_service.py:655-677`): `_UPDATE_CHANDELIER_SQL` fires on every bar where `trailing_stop is not None` — regardless of whether the stop actually tightened. Fix: only write when `trailing_stop` changed (long: moved up; short: moved down). Also consider deferring full history write to exit time only.

3. **3 separate lifecycle state dicts** (`signal_lifecycle_service.py:202-208`): `_chandelier_state`, `_staleness_consecutive`, `_shadow_signals` are separate keyed-by-signal-id dicts. Risky to merge but easy to miss cleanup when one is cleared without the others. Consider a unified `_signal_state: dict[str, dict]` per signal with sub-keys.

## Solution

- Item 1: `self._shadow_by_symtf: dict[tuple, dict[str, dict]] = defaultdict(dict)` — insert shadow at `(symbol, timeframe)` key; iterate only `self._shadow_by_symtf.get((symbol, timeframe), {})`.
- Item 2: Track `_chandelier_last_stop: dict[str, float]` and only write when value changed.
- Item 3: Lower priority — only worthwhile if a bug is found from inconsistent cleanup.
