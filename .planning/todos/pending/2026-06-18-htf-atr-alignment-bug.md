---
name: htf-atr-alignment-bug
type: bug
priority: high
created: 2026-06-18
resolves_phase: null
---

# Bug: frame_trade uses 1m ATR for all signals regardless of timeframe

## The Bug

`frame_trade` in `src/intelligence/trading/trade_framer.py` accepts `atr: float` as a
parameter. The docstring says "ATR×14 from I1." I1 computes ATR from 1m bars only.

Every I7 plugin calls `frame_trade(..., atr=get_atr(features["i1"]))` — always the 1m ATR.

For a 1h signal, the 1m ATR is approximately `1/√60 ≈ 0.13x` the 1h ATR. Stop distances
are placed ~7-8x tighter than the signal's native volatility context requires. The signal
fires in 1h regime logic but its stop geometry is calibrated to 1m noise.

## Evidence

From lifecycle_replay analysis (2026-06-18, 30-day window, equity ETFs SPY/QQQ/IWM):

- stopped_at_entry rates by timeframe: 1m=52%, 5m=50%, 15m=48%, 1h=46%
- Rates barely move across TFs — if stops were correctly ATR-aligned, HTF signals would
  have proportionally wider stops and far lower stopped_at_entry rates
- The near-uniform distribution across TFs is the fingerprint of stops that do NOT scale
  with timeframe volatility

## Why This Matters

A 1h signal should have a stop in 1h ATR terms. With 1m ATR:
- The stop is inside the normal 1h noise band
- Price doesn't need to "move against" the trade — normal 1h volatility will hit the stop
- MFE never reaches 0.05R (in 1h R terms) because the R denominator (risk = entry - stop)
  is tiny relative to 1h bar ranges
- lifecycle_tracker classifies these as STOPPED_AT_ENTRY but they are really
  STOPPED_BY_WRONG_ATR_SCALE

## Correct Architecture

Stop geometry must always use the signal's native-timeframe ATR. Principle: **ATR alignment
— stop distance in ATR units of the signal's own TF, always.**

I1 already computes ATR per-timeframe via `intelligence_features`. The features dict passed
to `frame_trade` contains the signal's TF in `features["timeframe"]`. The fix is to:

1. Have `frame_trade` (or the calling I7 plugin) select the TF-appropriate ATR from features
2. I1 stores `atr_14` per-bar — for HTF signals the pipeline already processes HTF bars via
   `topic_market_bars_htf`, so the features dict for a 1h signal should carry the 1h ATR

## Key Code Locations

- `src/intelligence/trading/trade_framer.py:1047` — `frame_trade(atr: float)` signature
- `src/intelligence/trading/trade_framer.py:1068` — docstring: "ATR×14 from I1" (1m only)
- `src/intelligence/trading/atr_utils.py:17` — `get_atr(features)` reads `atr_14` from
  `features["i1"]` — always 1m
- `src/intelligence/trading/atr_utils.py:82` — `get_atr_with_floor_from_frames(frames)`
  reads from `frames["i1"]` — also always 1m
- Every I7 plugin calling `frame_trade` passes `atr=get_atr(features)` or equivalent

## Investigation Needed Before Fix

1. Confirm: does `intelligence_features` store per-TF ATRs for HTF bars? Check what
   `atr_14` value is stored for a 1h bar row vs a 1m bar row for the same symbol/time.

2. Confirm: when a 1h I7 plugin fires, what does `features["i1"]["atr_14"]` contain —
   is it the 1h ATR computed from 1h bars, or the most recent 1m ATR?

3. Identify all I7 plugins that call `frame_trade` and how they source `atr`:
   `grep -rn "frame_trade" src/intelligence/`

4. Check `_select_vp` (trade_framer.py:339) — it already branches on `tf` for VP track
   selection. ATR selection should follow the same pattern.

## Likely Fix Shape

Option A — pass TF-aware ATR from caller:
- `atr_utils.py`: add `get_atr_for_tf(frames, tf)` that selects the right ATR tier
- All I7 plugins: replace `get_atr(features)` with `get_atr_for_tf(frames, tf)`
- Minimal blast radius; each plugin opts in

Option B — resolve inside frame_trade:
- `frame_trade` receives `frames` (full tiered dict) instead of flat `atr: float`
- Reads `features["timeframe"]` and selects appropriate ATR internally
- Single fix point; larger refactor

Option A is safer for Phase 132 APR seed values (they were seeded against 1m ATR; changing
to HTF ATR requires re-seeding all stop multiplier keys).

## Impact on Phase 132 APR Keys

**Critical:** All 35 APR keys seeded in Phase 132 were calibrated against 1m ATR. If ATR
alignment is fixed, the seed values (e.g. `stop_demand_buffer_atr=0.25`) will produce
stops that are `√TF_ratio` wider than today. For 1h signals: stops become ~7-8x wider.

This is the CORRECT behavior — but it means:
- Phase 132 seed values are only correct for 1m signals
- HTF seeds need empirical re-derivation after the fix
- Do not ship the ATR alignment fix without a companion seed-value re-measurement plan

## Relationship to stopped_at_entry Gap-Closure

See: `2026-06-18-stopped-at-entry-gap-closure.md`

The 30-42% stopped_at_entry rate on equity ETFs (after removing GBPUSD contamination) is
partially explained by this bug. Fixing ATR alignment is prerequisite to any meaningful
stopped_at_entry floor tuning. The correct order:

1. Fix ATR alignment (this todo)
2. Re-run 30-day replay on SPY/QQQ/IWM with aligned ATR
3. Re-measure stopped_at_entry baseline — expect significant drop for HTF signals
4. Then tune stop floors based on clean per-TF, per-zone-source data

## Do Not

- Do not tune `stop_multiplier_floor.*` APR keys before fixing ATR alignment — you will
  be tuning the wrong scale
- Do not run stopped_at_entry verification on FX or futures (spread/roll contamination)
- Do not treat the near-uniform TF distribution of stopped_at_entry as "normal" — it is
  the bug's fingerprint

## Session Context

Discovered during Phase 132 post-verification discussion 2026-06-18. The conversation
thread: stopped_at_entry gate FAIL (51.11%) → GBPUSD contamination identified → equity
ETF re-analysis (30-42%) → mfe<=0.05 dominates (signal quality, not stop geometry) →
bars_in_trade integer division bug (z_bit floors to 0 for quick HTF exits) → user raised
"stops should be ATR scale of the signal not 1m" → confirmed frame_trade always uses I1
(1m) ATR regardless of signal TF.
