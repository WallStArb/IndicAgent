---
status: pending
priority: P3
filed: 2026-07-23
source: Phase 163 (VP/SR Structural Primitives) code review (163-REVIEW.md) --
  WR-02/IN-01/IN-02/IN-03, deliberately not fixed inline (narrow edge case, pre-existing
  unrelated debt, or needs a live migration for near-zero value)
gate: none -- each item independent, pick up opportunistically
---

# Phase 163 review: 4 minor findings deferred (DST edge case, unrelated key mismatch, missing 4h config, minor cold-start coupling)

## Context

163-REVIEW.md's two CRITICAL findings (CR-01 accumulator warm-up, CR-02 live rolling-window cap)
and WR-01 (stale docstring)/WR-03 (hot-reload comment) were fixed same-session. Four smaller
findings were deliberately left open:

### WR-02: `update_session_vp()`'s session-boundary reset is not DST-aware

**File:** `src/intelligence/feature_cache.py:216-220`. The "has today's session opened yet" check
compares a fixed UTC-clock APR value (`ny_session_start_utc_hour`/`minute`, 13:30 UTC = 9:30 ET
only during EDT) against the bar's UTC hour, not DST-aware. For ~1 hour twice a year (DST
transition weeks), a bar can be attributed to the wrong session day, causing a spurious
mid-session accumulator reset or cross-session bar contamination in `_sess_bars`. This exact
non-DST-aware pattern already exists elsewhere (`_in_ny_session()` etc.) as an accepted,
documented limitation for read-only calendar flags -- Phase 163 is the first place it gates a
*stateful* reset, so a misfire has a larger blast radius (corrupts VP inputs for the affected
bars, not just one flag's value). Fix: resolve the session boundary via `_et_from_utc(ts)`
directly (compare ET wall-clock time against `09:30` local) so it's DST-correct by construction,
or explicitly accept and document the ~1hr/2x-yearly window as a known, bounded limitation
matching the rest of the session-boundary logic.

### IN-01: `threshold.backfill.coverage_threshold` key name mismatch — seeded config is dead code

**File:** `services/backfill_feature_factory.py:769`. Reads
`threshold.backfill.coverage_threshold`, but the only APR key ever seeded (migration 153) is
`threshold.backfill.coverage_gate` -- different name, so the read always falls through to the
hardcoded 0.80 default and any dashboard edit to `coverage_gate` is silently ignored. **Pre-existing,
not part of Phase 163's diff** -- found incidentally because Phase 163's own tests exercise this
function. Fix: rename the read to `threshold.backfill.coverage_gate` (or vice versa).

### IN-02: `feature.sr.lookback_by_tf` has no `"4h"` entry despite `4h` being a live pipeline timeframe

**File:** `production/migrations/255_vp_structural_primitives.sql:211-216`,
`src/intelligence/feature_factory.py:502-504`. `FeatureVectorPipeline._STANDARD_TFS` includes
`"4h"`, but the seeded/default lookback dict has no `"4h"` key, so `_compute_sr_dist_atr()`
silently falls back to the generic 120-bar default via `.get(tf, 120)`. Not incorrect (matches the
pre-existing `_CTF_HIGHER_TF` mapping's same 4h gap, likely intentional), just an unconfigured
tunable. Needs a **new migration** (255 is already applied; can't retroactively change what was
seeded) to actually take effect live -- low enough value that it wasn't worth a migration on its
own this session. Fix when touching this area for another reason: add an explicit `"4h"` entry
(e.g. 90, interpolating 1h's 120 and 1d's 60) to both the seeded JSON (new migration) and the
`FeatureFactoryConfig` dataclass default.

### IN-03: `sr_level_count` fallback unnecessarily coupled to ATR validity

**File:** `src/intelligence/feature_factory.py` (`_compute_sr_dist_atr`, `_SR_FALLBACK` early
return). Returns the entire fallback dict (including `sr_level_count=0.0`) whenever `atr_val` is
invalid, even though counting pivot clusters has no ATR dependency -- only the *distance* fields
need ATR normalization. Slightly overstates "zero clusters found" during ATR cold-start when
clusters could genuinely exist. "Benign in practice since the ATR and S/R warm-up windows overlap
almost entirely" per the review -- minor refinement, not a correctness bug. Fix: compute
`sr_level_count` (and cluster detection generally) independently of `atr_valid`, falling back only
the ATR-normalized distance/strength fields when ATR is unavailable.

## Acceptance criteria

- [ ] WR-02: DST-aware fix applied, or explicitly accepted/documented as a known bounded limitation
- [ ] IN-01: key name mismatch resolved
- [ ] IN-02: `"4h"` entry added via a new migration + dataclass default
- [ ] IN-03: `sr_level_count` decoupled from `atr_valid`
