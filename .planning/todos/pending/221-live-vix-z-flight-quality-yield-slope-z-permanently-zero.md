---
status: pending
priority: P1
filed: 2026-07-31
source: side finding while investigating todo 177 (BarHistory 200-bar cap enumeration) --
  the enumeration agent flagged vix_zscore_window/yield_curve_zscore_window as sourced from a
  dead code path rather than bar_history, independently re-verified directly against live code
  before filing (not taken on the agent's word alone).
---

# Live-serving `vix_z`/`flight_quality`/`yield_slope_z` are permanently stuck at 0.0 -- the real compute method is never called

## Problem

`FeatureCache.update_cross_asset()` (`src/intelligence/feature_cache.py:531`) is the ONLY code
that actually computes `vix_z` (SPY trailing realized-vol z-score), `flight_quality`
(TLT/SPY divergence), and `yield_slope_z` (TLT/SHY z-score) from OHLCV bars. Verified directly:

```
grep -rn "\.update_cross_asset(" services/ src/
services/feature_vector_pipeline.py:1071:  await self._cache_mgr.update_cross_asset(tf, payload)
```

That is the only live call site, and it calls a **different class's method with the same
name** — `CacheManager.update_cross_asset()` (`src/intelligence/pipeline/cache_manager.py:235`),
which just stores the raw payload dict in `self._cross_asset[tf]` and does nothing else:

```python
async def update_cross_asset(self, tf: str, payload: dict) -> None:
    """Store latest cross-asset payload for the given timeframe."""
    async with self._cross_asset_lock:
        self._cross_asset[tf] = payload
```

`FeatureCache().update_cross_asset(spy_bars, tlt_bars, shy_bars, config)` -- the method that
actually populates `self.vix_z` / `self.flight_quality` / `self.yield_slope_z` -- is never
invoked anywhere in `services/` or `src/`. The `FeatureCache` instance created at
`feature_vector_pipeline.py:213` keeps these three fields at their dataclass default (`0.0`)
for the life of the process. `feature_factory.py`'s `compute()` reads them straight through at
lines 6400-6402, 6904-6906, 7360-7362 (`vix_z=cache.vix_z`, etc.) with no fallback or
staleness check -- every live-computed feature vector for every symbol/tf silently carries
`vix_z=0.0, flight_quality=0.0, yield_slope_z=0.0` at all times, not "stale" but "never once
computed."

**This is a name collision masking a wiring gap**, the same shape of bug as todo 200
(`service_auditor.py`'s registry silently pointing at the wrong unit) -- two classes named
`update_cross_asset` with completely different contracts, and nothing (no type check, no
test) catches that the pipeline calls the wrong one.

## Corpus/backfill path is NOT affected -- separate, correct implementation

`services/backfill_feature_factory.py` (lines ~250-330) has its own independent incremental
per-date computation of `(vix_z, flight_quality, yield_slope_z)` that does NOT go through
`FeatureCache.update_cross_asset()` at all -- it replicates the same math directly. This is
what populates `feature_vectors` (the training corpus `ic_engine` measures IC against), so
**the in-flight corpus rebuild and all historical IC/ensemble measurements for these three
features are unaffected** by this bug. Confirmed by reading the backfill code directly, not
assumed from the live-path finding.

## Current blast radius: live-serving only, and live ingestion is currently stopped

Per project state, the live IBKR ingestion chain is intentionally stopped (confirmed
2026-07-27) -- so nothing is actively consuming live feature vectors with this defect right
now. This is why it wasn't caught by any live-signal quality check. It WILL resurface the
moment live ingestion resumes: any live consumer of these three fields (alpha_swarm,
narrative_compute, or any real-time signal path reading `feature_vectors`-shaped live output)
would see constant zeros, not degraded-but-real values -- worth checking whether this is also
why `canary_acausal_placebo` or similar broadcast-feature checks (todo 204's still-undiagnosed
POOLED-gate anomaly) behave oddly, since a broadcast feature that's identically 0.0 for every
symbol is a different failure shape than genuine cross-sectional pseudo-replication, and could
plausibly present similarly in some diagnostics. Not confirmed as related -- flagging the
overlap for whoever picks up 204 to rule in/out, not asserting it as the cause.

## What needs to happen

1. Fix `feature_vector_pipeline.py:1071` (or wherever cross-asset bars are actually available)
   to call `FeatureCache.update_cross_asset(spy_bars, tlt_bars, shy_bars, config)` with real
   bar history, not `CacheManager.update_cross_asset(tf, payload)`'s raw-payload store. Likely
   needs the SPY/TLT/SHY bar windows to be assembled from `CacheManager`'s stored payloads (or
   directly from `BarHistory`) before calling `FeatureCache`'s method -- trace exactly what
   `payload` currently contains at the call site vs. what `FeatureCache.update_cross_asset()`
   needs as input.
2. Add a regression test that fails if `cache.vix_z`/`flight_quality`/`yield_slope_z` stay at
   their dataclass default after a full pipeline tick with cross-asset bars available --
   mirroring how todo 149/CR-02 pinned similar live-vs-backfill gaps with a dedicated test.
3. Rename one of the two `update_cross_asset` methods once the fix lands -- identical names on
   unrelated classes with totally different contracts is exactly the kind of collision that let
   this hide; `CacheManager`'s should probably become `store_cross_asset_payload` or similar.
4. Cross-check with todo 204 once picked up: does `canary_acausal_placebo`'s undiagnosed
   POOLED-gate anomaly relate to a broadcast feature being constant-zero rather than genuinely
   broadcast-but-varying? Read that todo's own diagnosis before assuming a connection.

## Acceptance criteria

- [ ] Live pipeline's `cache.vix_z`/`flight_quality`/`yield_slope_z` are non-zero and vary
      bar-to-bar once cross-asset bars are flowing (verify with a live or replayed tick, not
      just a passing unit test)
- [ ] Regression test added pinning that these fields update on a full pipeline tick
- [ ] `CacheManager.update_cross_asset` renamed to remove the collision, or `FeatureCache`'s
      method renamed -- whichever direction the fix lands, the two must not share a name
