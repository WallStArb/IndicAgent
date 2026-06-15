# Vol SMA Self-Inflation Bug - Multi-Plugin Sweep

**Found:** 2026-06-15 during Phase 125 simplify pass

## Problem

`momentum_breakout.py` was fixed (Phase 125 WR-02/WR-03) to exclude the current bar from the volume SMA baseline. But the same self-inflation defect exists in inline fallback paths across at least 3 other plugins:

- `squeeze_expansion.py` lines 93-96: `np.mean(volume[-20:])` includes current bar
- `vwap_deviation.py` line 145: `np.mean(volume[-20:])` includes current bar
- `candlestick_pattern_setup.py` line 270: `np.mean(vol[-20:])` includes current bar

These fallbacks only fire when `features.get("volume_sma_20")` is absent, but when they do, the volume ratio is inflated by the breakout bar's own volume.

## Deeper fix

Extract a shared `volume_sma_baseline(volume_arr, periods=20)` utility in `plugin_utils.py` that always returns `mean(arr[-periods-1:-1])` with a floor guard. All inline fallbacks should call this function. Fixes the bug and enforces the exclude-current-bar contract at one site.

## Related

Also noted: `shadow_only=True` is set per-class on each plugin but is not validated in `validate_tier()` — any new plugin that omits it goes live silently. Consider adding a `validate_tier()` check that raises `ArchitectureViolation` when `shadow_only is False` for I7 plugins (or make it a default on `PatternPlugin`).
