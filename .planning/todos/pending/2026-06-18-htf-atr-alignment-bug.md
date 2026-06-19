---
name: htf-atr-alignment-bug
type: bug
priority: high
created: 2026-06-18
resolves_phase: null
---

# Bug: timeframe not propagated into features dict — TF-aware stop caps always use default

## The Bug

I7 plugins build a local `features` dict by merging tier sub-dicts:

```python
features = {
    **(frames.get("i1") or {}),
    ...
    **(frames.get("i6") or {}),
}
```

None of the tier dicts carry a `"timeframe"` key. When `frame_trade` calls
`features.get("timeframe", "")` it always gets `""`, so:
- `MAX_STOP_ATR_MULTIPLIER_BY_TF.get("", default)` → always the default stop cap
- `_cfg(f"feature.trade_framer.target_max_atr_{tf}", default)` where `tf=""` → always default
- `_select_vp(features, ...)` which branches on `tf` → always uses the 1m VP track

The ATR values from I1 are correct (live pipeline processes HTF bars with HTF ATR). The
problem is the TF string is not reaching `frame_trade`.

## Evidence

The live executor already sets `"timeframe": tf` in `plugin_input` (executor.py:853), so
`frames.get("timeframe")` is available. It just isn't injected into the local `features` dict.

Replay scripts (`run_historical_pipeline.py`, `feature_replay.py`) also omit `"timeframe"`
from their frames dict, doubling the problem during backfill.

## Fix

1. Add `features["timeframe"] = frames.get("timeframe") or frames.get("__timeframe__", "")`
   after each features merge in every I7 plugin and in `detect_spike_signal`.
2. Add `"__timeframe__": timeframe, "timeframe": timeframe` to the frames dict in both
   replay scripts.

## Key Code Locations

- `src/intelligence/pipeline/executor.py:847-857` — live frames dict (already has "timeframe")
- `src/intelligence/trading/trade_framer.py:1075` — `features.get("timeframe", "")`
- `src/intelligence/trading/trade_framer.py:729` — same in `_collect_target_candidates`
- `src/intelligence/trading/microstructure_utils.py:70-78` — features merge in detect_spike_signal
- `production/scripts/run_historical_pipeline.py:1284` — I7 frames dict (missing "timeframe")
- `production/scripts/feature_replay.py:236` — replay frames dict (missing "timeframe")

## Impact on Phase 132 APR Keys

ATR values are already correct per TF. The stop-cap and target-cap multipliers (`MAX_STOP_ATR_MULTIPLIER_BY_TF`, `feature.trade_framer.target_max_atr_<tf>`) will now
be selected by the actual TF. Phase 132 APR seeds were calibrated against live data and
remain valid; they are per-TF seeds indexed by TF suffix.

## Do Not

- Do not change `frame_trade` signature
- Do not tune `stop_multiplier_floor.*` APR keys until after a 30-day replay with this fix
- Do not run stopped_at_entry verification on FX or futures (spread/roll contamination)
