---
created: 2026-03-10T00:44:56.985Z
title: Research and fix signal generator condition vs event firing and direction flip gate
area: signals
files:
  - services/signal_generator_service.py:560-733
  - src/intelligence/trading/fvg_fill.py:41-103
  - src/intelligence/trading/aggregator.py
  - src/intelligence/trading/cis_scorer.py
---

## Problem

Three related issues discovered during dashboard signal history review (2026-03-10):

### 1. Condition vs Event — plugins fire every bar, not on signal onset

All 17 I7 plugins are "condition detectors" not "event detectors". If FVG is open, `trad_FVGFill` fires every single bar that FVG remains open — not just when the FVG first appeared. This means:
- Same setup re-published on every bar without any new trigger
- Consecutive bars with identical direction, entry, stop — all treated as fresh signals and persisted to `signal_ledger`
- Observed in dashboard: 19:50 LONG then 19:55 SHORT on same plugin (FVGFill) — market didn't generate a new setup; the underlying `fvg_type` feature just flipped from +1 to -1 in the SMC detector between two 5m bars

### 2. Zero cross-bar memory in signal_generator_service

`_process_bar()` has no knowledge of what was published on the prior bar. There is no:
- `_last_published` cache per `(symbol, timeframe)`
- Direction flip suppression
- Cooldown / minimum bars between signals
- Check whether the prior signal is still pending/active

Every bar independently: runs all plugins → aggregates → publishes winner. A direction flip requires zero justification from the service layer.

### 3. All I7 InputSpec declarations say `timeframe="1m"` — dead code

Every I7 plugin has `inputs: InputSpec(timeframe="1m")` but signal_generator_service processes ALL configured TFs (`["1m", "5m", "15m", "1h"]`) and passes `frames["main"]` = current TF's OHLCV regardless of the InputSpec declaration. The `timeframe="1m"` in InputSpec is silently ignored. This was probably correct when signals were 1m-only but never updated when multi-TF processing was added.

### 4. 4h and 1d not processed at intelligence or signal layer

- `indicator_service`: processes `["1m", "5m", "15m", "1h", "4h", "1d"]`
- `market_analysis_service`: processes `["1m", "5m", "15m", "1h"]` — **no 4h, no 1d**
- `signal_generator_service`: processes `["1m", "5m", "15m", "1h"]` — **no 4h, no 1d**

4h and 1d bars have I1 indicators but no I3-I7 intelligence or signals. Dashboard shows 4h/1d tabs but they're mostly empty (indicators only). This may be intentional (4h bars close rarely; 1d only once/day) but should be an explicit decision with a plan.

## Research Questions

Before implementing fixes, answer:

1. **Condition vs Event**: Should plugins detect *onset* (first bar a condition becomes true) vs *persistence* (every bar it's true)? For FVG fill: the opportunity exists as long as the FVG is open — so persistence firing could be argued. But then the gate logic needs to suppress re-publishing the same signal.

2. **Direction flip gate**: What constitutes a valid reason to flip direction?
   - Prior signal must be resolved (lifecycle exit received)?
   - Or allow flip if regime changes (HMM state change)?
   - Or minimum N bars between flips regardless?

3. **Cooldown design**: Where does it live — in the service (`_process_bar` gate before publish), in the aggregator, or in a new `SignalGate` class? Service-level is simplest: `_signal_gate: dict[tuple[str,str], dict]` with `direction, bar_ts, signal_id`.

4. **4h/1d decision**: Are 4h/1d signals desirable? If yes, what's the warmup bar count needed (indicator_service already handles bars; market_analysis needs to subscribe)? If no, should they be removed from the dashboard TF switcher?

5. **InputSpec cleanup**: Should `timeframe="1m"` be changed to `timeframe=".*"` across all I7 plugins, or is InputSpec used anywhere that would break? Check `registry` and `validate_tier()` logic.

## Proposed Solution (after research)

**Service-level signal gate** in `signal_generator_service._process_bar()`, just before stream publish:

```python
# Pseudocode
gate = self._signal_gate.get((symbol, timeframe))
if gate:
    bars_since = (timestamp - gate["bar_ts"]).total_seconds() / tf_seconds
    if bars_since < MIN_BARS_BETWEEN_SIGNALS:
        return  # cooldown
    if gate["direction"] != new_direction and not gate["resolved"]:
        return  # flip suppressed — prior signal still live
self._signal_gate[(symbol, timeframe)] = {
    "direction": new_direction, "bar_ts": timestamp, "signal_id": signal_id, "resolved": False
}
```

Listen for lifecycle exit events (from `signal_lifecycle_service`) to mark `gate["resolved"] = True` when a signal exits — this unblocks direction flips after genuine resolution.

`MIN_BARS_BETWEEN_SIGNALS` should be configurable per TF (e.g., 3 bars for 1m, 2 bars for 5m+).

## Key Files

- `services/signal_generator_service.py:560` — `_process_bar()` where gate would be inserted
- `services/signal_generator_service.py:360` — `__init__` where `_signal_gate` dict would be initialized
- `services/signal_generator_service.py:424` — service config where `min_bars_between_signals` config key would live
- `src/intelligence/trading/fvg_fill.py:35` — example of dead `InputSpec(timeframe="1m")` declaration
- `services/market_analysis_service.py:153` — `["1m","5m","15m","1h"]` — missing 4h/1d
