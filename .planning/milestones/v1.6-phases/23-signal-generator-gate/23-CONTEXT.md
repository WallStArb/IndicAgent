# Phase 23: Signal Generator Gate - Context

**Gathered:** 2026-03-10
**Status:** Ready for planning
**Source:** Todo file `.planning/todos/pending/2026-03-10-research-and-fix-signal-generator-condition-vs-event-firing-and-direction-flip-gate.md`

<domain>
## Phase Boundary

Fix `signal_generator_service` to:
1. Suppress duplicate condition fires (publish only on onset, not every bar the condition persists)
2. Add cross-bar signal memory with direction flip suppression until prior signal resolves
3. Clean up dead `InputSpec(timeframe="1m")` declarations across all I7 plugins
4. Make an explicit decision on 4h/1d TF processing scope

Out of scope: changes to I7 plugin logic itself, aggregator changes, dashboard changes.

</domain>

<decisions>
## Implementation Decisions

### Signal Gate Architecture
- **Service-level gate** in `signal_generator_service._process_bar()`, just before stream publish
- Gate state: `self._signal_gate: dict[tuple[str, str], dict]` — keyed by `(symbol, timeframe)`
- Gate dict fields: `direction`, `bar_ts`, `signal_id`, `resolved`
- Added to `__init__` alongside existing service state init

### Cooldown Logic
- `MIN_BARS_BETWEEN_SIGNALS` configurable per TF: `{"1m": 3, "5m": 2, "15m": 2, "1h": 2}`
- Cooldown check: `bars_since = (timestamp - gate["bar_ts"]).total_seconds() / tf_seconds`
- If `bars_since < MIN_BARS_BETWEEN_SIGNALS`: skip publish (return without publishing)

### Direction Flip Suppression
- Direction flip suppressed while `gate["resolved"] == False` (prior signal still live)
- Allow flip if same direction (not a flip) OR gate is resolved OR cooldown expired
- Service listens on `signals:SYMBOL:TF:aggregated` stream (or lifecycle exits) to mark `gate["resolved"] = True` when `direction == 0` (terminal/resolved event per stream contract)

### Lifecycle Resolution Signal
- Signal lifecycle service emits `direction=0` on `signals:SYMBOL:TF:aggregated` when a signal exits
- Signal generator reads its own output stream to detect resolution events
- Alternative: listen on `llm_outcomes:stream` — to be determined by researcher
- Keep it simple: consume own stream, direction=0 = resolved, set `gate["resolved"] = True`

### InputSpec Cleanup
- Change `InputSpec(timeframe="1m")` → `InputSpec(timeframe=".*")` on all I7 plugins
- Verify `InputSpec.timeframe` is not enforced anywhere in the registry or validator (confirm dead code)
- If enforced: fix enforcement logic to handle multi-TF; if dead code: cleanup only

### 4h/1d Decision
- `market_analysis_service` and `signal_generator_service` currently process `["1m", "5m", "15m", "1h"]`
- Decision to make: explicitly exclude 4h/1d (document as intentional) OR extend pipeline
- Recommendation: mark as intentional exclusion for now — 4h closes 4×/day, 1d once/day; signal latency makes them low-value for day trading. Add explicit comment to both services.

### Claude's Discretion
- Exact gate reset logic when symbol/TF first seen (no prior gate) — treat as unresolved, no flip to suppress
- How to compute `tf_seconds` cleanly from TF strings — use `src/core/service_utils.min_bars_for_tf` or a simple lookup dict
- Whether gate state should survive service restart (in-memory only is fine — gate will reset on restart, first signal fires normally)

</decisions>

<specifics>
## Key Files

- `services/signal_generator_service.py:560` — `_process_bar()` where gate is inserted
- `services/signal_generator_service.py:360` — `__init__` where `_signal_gate` dict is initialized
- `services/signal_generator_service.py:424` — service config section for `min_bars_between_signals`
- `src/intelligence/trading/fvg_fill.py:35` — example of dead `InputSpec(timeframe="1m")`
- `services/market_analysis_service.py:153` — `["1m","5m","15m","1h"]` TF list to audit

</specifics>

<deferred>
## Deferred

- 4h/1d pipeline extension — too much scope, deferred to v1.7 or later
- Rewriting I7 plugins as true event detectors at plugin level — out of scope; gate handles it at service level
- Persisting gate state across restarts — not needed; first bar after restart fires normally

</deferred>

---

*Phase: 23-signal-generator-gate*
*Context gathered: 2026-03-10 from todo analysis*
