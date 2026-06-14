---
created: 2026-06-14T10:35:18.959Z
title: Fix I6 CTF cold-start in replay — 24 plugins produce zero signals
area: intelligence
files:
  - production/scripts/run_historical_pipeline.py:1595-1607
  - src/intelligence/confluence/cross_timeframe.py:91
  - src/intelligence/trading/microstructure_utils.py:84-86
---

## Problem

24 of 37 I7 plugins produce zero signals in the historical replay because
`ctf_score` is always 0.0 across every symbol, timeframe, and bar.

Root cause chain:

1. `cross_timeframe.py:91`: `if not other_intel: return {}` — when no `intel_*`
   keys are in frames, I6 returns an empty dict. `ctf_score` is never set.

2. `run_historical_pipeline.py:1600-1602`: `intel_{other_tf}` frames are
   populated from `intelligence_cache[symbol][other_tf]`. The cache is cold at
   the start of history (June 2024), so I6 returns `{}` on every early bar.

3. `ON CONFLICT DO NOTHING` in the feature INSERT means the 0-valued rows are
   never corrected by later bars.

4. Every plugin that checks `abs(ctf_score) < get_min_ctf_score()` (= 0.25)
   fails the gate and returns no_signal. This includes all 24 plugins using
   `detect_spike_signal` (microstructure_utils) or explicit CTF gates.

The 13 firing plugins survive because they are either in `_I7_I6_EXEMPT`
(no CTF gate) or declare `requires_i6_confluence=True` but don't actually
call the CTF gate in `compute_full`.

## Solution

Two options:

**Option A (preferred):** Pre-warm the I6 intelligence cache before the
signal-firing pass. Run a separate warmup pass (I1-I6 only, `skip_signals=True`)
to populate `intelligence_cache` for every symbol across the full date range
before the I7 signal pass reads from it.

**Option B:** Write `cross_timeframe.py` to gracefully degrade when
`other_intel` is empty rather than returning `{}` — emit a partial score
(e.g., 0.0 with a flag) so downstream plugins can distinguish "no data" from
"neutral alignment". Then re-run the replay.

Either requires re-running the replay after the fix. The current replay
(674K signals, all from 13 plugins) must be discarded for affected symbols.

Also need to investigate: why `ON CONFLICT DO NOTHING` is used instead of
`DO UPDATE` — if a bar is reprocessed, the old 0 value is never corrected.
