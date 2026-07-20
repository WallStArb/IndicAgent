# 153 — VP/SR features are stub fields never wired up anywhere in v3, not a batch-vs-live gap

**Found:** 2026-07-19, while re-verifying todo 033's "4 zero-IC features" against the
post-143.1-07 corpus.

**Correction 2026-07-19 (same day, caught by the project owner):** my first pass at this todo
took the code comments at face value and concluded these features were live-computable but
batch-uncomputable ("requires I3 intraday injection"). That's wrong — **v3 doesn't use I3.**
Traced it properly:

- `FeatureCache` (`src/intelligence/feature_cache.py`) declares `poc_dist_atr`/`va_position`/
  `sr_support_dist`/`sr_resist_dist` with static defaults (`0.0`/`0.5`/`0.0`/`0.0`) and comments
  "reset at session open by the caller" — but grepping the entire live codebase
  (`src/`, `services/`) for an assignment to any of these four attributes finds **nothing**. The
  cache's own mutator methods (`refresh_regime`, `update_wk_vwap`, `advance_bar`,
  `update_cross_asset`) never touch them. `feature_factory.py` only *reads* `cache.poc_dist_atr`
  etc. (lines 3452-3455, 3838-3841, 4261-4264) — always the untouched default.
- The only place that actually *computes* a real `poc_dist_atr` value is
  `src/intelligence/features/i3_structure/market_profile.py` (`MarketProfilePlugin`,
  `_compute_full_core`) — but its sole importer is `src/intelligence/register_plugins.py`, the
  **archived v2.x plugin registry** (confirmed: `grep -rl "i3_structure" src/ services/` returns
  only `register_plugins.py`, `schemas.py`, and the module itself — nothing in
  `feature_vector_pipeline.py` or `backfill_feature_factory.py`, v3's actual live/batch entry
  points). `i3_structure` is a v2.x-era directory name (structural tier) that happens to share
  the "I3" label with the archived plugin system's terminology — it was never connected to v3's
  `FeatureCache`.

**Corrected finding:** these 4 features are **permanently stuck at their dataclass defaults in
both the live and batch paths** — not "live-only, batch-blocked." Nothing in v3 has ever computed
real values for them. The `compute_batch`/`backfill_feature_factory.py`/`schemas.py` comments
citing "I3 intraday injection" as the batch blocker are themselves stale/wrong — carried over
from when this code was scaffolded, describing a live-path connection to the archived plugin
that was never actually built.

`feature_ic_scores.ic_value = 0` for these features (5,510 cells, all regime scopes, all TFs) is
therefore a rank-correlation-over-constant-input artifact in exactly the same way as before, just
for a different underlying reason: **the input is constant (stub default), not merely null in one
path.**

## Why this matters

Same as before: no way to earn promotion through proof for 4 features `feature_factory.py`
already registers in its `structural` domain. Todo 033's proposed refinements (session-phase
normalization, sr_strength multiplier, interaction terms) remain moot — there is no real
computation to refine yet, in either path.

## Options (not yet decided)

1. **Implement it for real, in v3's own terms** — port the actual computation logic from
   `i3_structure/market_profile.py` (TPO market profile / POC / value area) and
   `i3_structure/support_resistance.py` into `FeatureCache`/`FeatureFactory` directly (a new
   mutator method, e.g. `cache.update_session_vp(...)`, called by both the live daemon and the
   batch job at session boundaries) — the underlying math already exists and is tested in the
   archived module, it just needs a new v3-native home and caller. Real effort, but "port working
   logic to a new call site" is smaller than "invent new logic."
2. **Delete the 4 stub fields entirely** — `FeatureCache`, `FeatureVector`/`schemas.py`,
   `feature_factory.py`'s `structural` domain registration, and drop the columns' relevance from
   `feature_ic_scores`. Matches the 5-step mandate (delete before rebuilding) if nobody has near-
   term plans to implement option 1 — a permanently-defaulted stub column is dead weight, not a
   placeholder worth preserving.
3. **Leave as-is, don't measure** — document the gap (this todo), exclude these 4 from any IC-
   based promotion/weighting decision, revisit if/when option 1 becomes a priority.

**Blocked on:** an operator call on whether these features are worth building for real (option 1)
or should be deleted (option 2) — no technical unknown left, purely a priority/scope call. Given
they've never been implemented since v3's inception and nothing currently depends on them,
option 2 (delete) is the lower-effort correct default per the project's own 5-step mandate unless
there's a specific reason to want session-level VP/S-R features that hasn't been named yet.

## References

- `src/intelligence/feature_cache.py:31-84` (`FeatureCache` — no VP/SR mutator exists)
- `src/intelligence/feature_factory.py:3700-3841` (`compute_batch` — reads-only, stale comment)
- `src/intelligence/features/i3_structure/market_profile.py` (real computation, archived-plugin-only)
- `src/intelligence/register_plugins.py:63-69` (sole importer of `i3_structure`)
- `services/backfill_feature_factory.py:995-1013` (stale "requires I3" docstring)
- `src/intelligence/schemas.py:1262` (stale "requires I3 intraday injection" comment)
- Supersedes the VP/SR half of todo 033 (see that file for the corrected pointer)
