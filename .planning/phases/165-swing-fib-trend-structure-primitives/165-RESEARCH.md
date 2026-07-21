# Phase 165: Swing/Fib/Trend Structure Primitives - Research

**Author:** Fable 5, 2026-07-20. Verifies and extends the preliminary survey already recorded in
ROADMAP.md's "### Phase 165" entry (2026-07-20, a different Claude session, "equivalent-rigor-
not-formal"). Follows the same verification discipline Phase 163's dispatch used: read every
source file directly, do not trust the prior pass's claims, actively hunt for what it missed.

## Objective

Answer: what do we need to know to plan Phase 165 well? Specifically: what do the 6 unreviewed
`src/intelligence/features/i3_structure/` plugins (`swing_detector.py`, `swing_momentum.py`,
`trend_structure.py`, `fibonacci_zones.py`, `session_levels.py`, `macd_events.py`) actually
compute, what's wrong with a literal port, what v3 `FeatureVector` columns fall out of each, and
which files are actually in scope for this phase vs. deferred.

## Section 0: Files read in full for this research

`swing_detector.py` (95 lines), `swing_momentum.py` (258 lines), `trend_structure.py` (181
lines), `fibonacci_zones.py` (108 lines), `session_levels.py` (435 lines), `macd_events.py` (94
lines), `support_resistance.py` (160 lines, Phase 163's port source, read for shared-convention
context), `archive/smc_context/bocpd_changepoint.py` (294 lines). Also read `schemas.py`'s live
`FeatureVector` dataclass in full (lines 1204-1483) and the archived `I3Structure` Pydantic model
(lines 228-341) to avoid the exact trap this task warned about — confirmed which is which before
citing either. Also read `feature_cache.py` (lines 1-200), `feature_factory.py`'s calendar-
primitive section (~1555-1600) and `FEATURE_VECTOR_DOMAIN`/session-APR-key lines, `context/
session_context.py` (full, 328 lines), `archive/smc_context/premium_discount.py` (full), and did
a grep sweep of `context/` and `archive/` for competing swing/fib/session implementations.

## Section 1: Verifying the prior pass's per-file claims

**`swing_momentum.py` — mostly confirmed, one correction.** Self-contained: confirmed, it has its
own `_detect_extremes()` static method and does not read `frames["i3"]`. Non-incremental:
confirmed, `compute_next` literally returns `self.compute_full(windows)`. ATR-normalized/bounded
claim: **mostly right but imprecise.** `swing_amplitude_ratio` is ATR-normalized (a ratio of two
already-ATR-divided amplitudes) but it is **not bounded** — nothing caps it above 1.0 (if the most
recent swing is much larger than the mean of the prior three, the ratio can be arbitrarily large).
That's fine as a `FeatureVector` column (unbounded-but-stationary is a normal shape — c.f.
`vol_ratio`, `garch_ratio`, both `normalization='unbounded_ratio'` in `feature_registry`), but
"bounded" was the wrong word for it; only `swing_amplitude_intensity`, `struct_energy`,
`swing_amplitude_expanding`, and `struct_accel_bias` are actually bounded/discrete. The
`swing_velocity_trend` string-enum-needs-encoding finding is confirmed and correct.

**`trend_structure.py` — confirmed, correct, and incomplete.** The `5.0` divisor
(`strength * (price_range/atr)/5.0`) is real and correctly flagged. **What the prior pass missed:**
a second, independent hardcoded magic number three lines earlier — `price_range = float(np.max
(high[-20:]) - np.min(low[-20:]))` (line 95) hardcodes a 20-bar lookback for the price-range
component of the ATR-normalization, completely separate from the `5.0` divisor and from the
plugin's own `neighbor: int = 5` (pivot-detection window, also unflagged by the prior pass) and
`min_lookback`/`InputSpec(lookback=120)`. That's three distinct undeclared tunables in one 181-
line file, not one. See Section 2 below for the more important finding in this file (a silent-
wrong-answer bug, not just an APR gap).

**`swing_detector.py` — confirmed self-contained, correct on the price fields, but the "valid
as-is" list is wrong.** `swing_high`/`swing_low` are raw prices needing `_dist_atr` conversion:
confirmed. But the prior pass's claim that "the rest ... are valid as-is" is **incomplete on two
counts**, both found by reading the file rather than trusting the summary:
1. `swing_high_idx`/`swing_low_idx` are in the plugin's own `outputs` frozenset but the prior
   pass's survey doesn't mention them at all. These are raw bar-array positional indices (e.g.
   `47`), not prices — but they are exactly as invalid as a raw price for the same underlying
   reason (D-16's rule generalizes: non-stationary, non-comparable, meaningless without knowing
   the window length convention, which varies by timeframe and by how much history the batch job
   happened to load). They are also **fully redundant**: `swing_high_age_bars`/
   `swing_low_age_bars` are the derived, valid version of the same information
   (`n_bars - 1 - idx`). See Section 2.
2. `swing_high_type`/`swing_low_type`/`swing_pattern` default to `0.0` (not `None`) whenever fewer
   than 2 confirmed swings of the relevant type exist in the window — a silent-wrong-answer
   pattern, not a clean "insufficient data" null. See Section 2 (this is the more serious finding).

**`fibonacci_zones.py` — confirmed on the fallback and the raw-price problem; the fix needs to be
more surgical than "resolve the fallback."** The cross-plugin fallback (`i3.get("swing_high")`)
is real and confirmed dead weight in v3's Feature Factory (single deterministic in-process
`compute()` call, no wave-based cross-plugin reads). But simply "resolving" it isn't the shape of
the fix — see Section 3 for why this phase's own `swing_detector.py` port is the natural, and
only necessary, replacement (compute swing high/low once per bar, feed both plugins from the same
local values, delete the fallback entirely rather than keep it as dead code or reimplement a
different fallback). On the field list: `nearest_fib_dist_atr`, `nearest_fib_ratio`,
`fib_cluster_strength`, `in_fib_discount_zone` are confirmed valid as-is. The "5 raw fib price
levels + swing high/low need the same distance-conversion treatment" claim is **directionally
right but the wrong fix** — converting all 5 individual fib levels to 5 separate `_dist_atr`
columns would reproduce Phase 163's D-17 exact-collinearity finding five times over (adjacent
fib ratios are evenly spaced along the same `swing_range`, so `dist_atr(fib_236)` and
`dist_atr(fib_382)` differ by a *constant* `0.146 × swing_range / atr` for a given bar — near-
total redundancy, not five independent signals). `nearest_fib_ratio` + `nearest_fib_dist_atr`
already jointly encode "where along the fib ladder is price, discretized to the 5 canonical
ratios" — the compressed, useful version of the same information. Recommendation: **drop all 8
raw-price/intermediate fields** (`fib_swing_high`, `fib_swing_low`, `fib_236`, `fib_382`,
`fib_500`, `fib_618`, `fib_786`, `nearest_fib_level`), same treatment Phase 163 gave `poc_price`/
`vah`/`val`. Keep the 4 already-valid fields, add nothing new here (unlike Phase 163's D-18
rolling-track addition, there's no comparably distinct new hypothesis hiding in the unused fib
levels — they're all restatements of the same discretized position).

**`session_levels.py` — bug confirmed, but narrower than described.** Verified the bar-math
directly: `_SESSION_BARS = 390` assumes 1-minute bars. **v3 doesn't even run FeatureVector
computation at 1m** — per `docs/foundation` / CLAUDE.md's Phase A scope, the live depths are
5m/15m/1h/1d. Recomputing the actual magnitude at each: 390 bars of 5m ≈ 5 trading sessions (not
1 day — 78 5m-bars/session); 390 bars of 15m ≈ 15 sessions (26 bars/session); 390 bars of 1h ≈ 60
sessions (~12 weeks, using ~6.5 bars/session); 390 bars of 1d ≈ 390 calendar days (~1.5 years).
The bug is not merely present "on other timeframes" — it is **wrong on every timeframe v3 actually
uses**, since the one timeframe it's correct for (1m) isn't live. **What the prior pass's bug
description over-stated:** it implies the whole file needs a session-boundary rewrite. Reading
the file line by line shows the Asian-session logic (lines 164-177, 244-255,
365-376) is **already correct and timeframe-agnostic** — it converts `timestamp` to ET via
`ZoneInfo` and masks on `hour >= 20 or hour < 4`, no bar-count anywhere. Only the
`prior_session_*`/`overnight_*`/`weekly_*` sub-features (which slice `df.iloc[-sess_n:]` etc.
using `_SESSION_BARS`/`_WEEK_BARS`/`_OVERNIGHT_BARS`) are broken. This halves the actual rewrite
surface: 3 of 4 sub-concepts need new session-boundary-timestamp logic; the 4th (Asian H/L) needs
only the standard raw-price→ATR-distance conversion, same as every other file in this phase.

**`macd_events.py` — confirmed, both findings hold.** Grepped `feature_factory.py` and the live
`FeatureVector` dataclass directly (not the archived `I1Indicators`/`I3Structure` models earlier
in `schemas.py`, which is exactly the trap the task called out) — zero MACD fields anywhere in
the live v3 path. `macd_12_26_9`/`macd_signal_12_26_9`/`macd_histogram_12_26_9` do not exist.
Porting `macd_events.py` without first building MACD itself is not "an events layer on an existing
indicator," it's building MACD as a side effect of an events layer named for something else. The
`nearest_support` cross-plugin dependency is confirmed real but not the actual blocker — once
Phase 163 ships `sr_support_dist` (an ATR-distance, not a raw price under D-16), the fix is
actually *simpler* than before: `neg_support = 1 if sr_support_dist < threshold else 0` needs no
`abs(close - nearest_support)/atr` recomputation at all, since `sr_support_dist` already is that
distance. **Confirmed: park, don't port.** If MACD itself is ever wanted, it belongs in a
momentum/oscillator-family phase, not a swing/fib/trend "structure" phase — a naming-system
mismatch as much as a scope one (MACD is a momentum oscillator, not a structural primitive).

**`bocpd_changepoint.py` — confirmed correctly parked.** Read in full. The plugin's own top-of-
file comment already documents the ~77ms p95 latency at `max_run_length=200` as an O(R) algorithmic
floor, not a bug — a real, already-self-aware cost note. Its outputs (`cp_probability`,
`cp_raw_probability`, `cp_confirmation`, `cp_detected`, `cp_run_length`) are already clean (no
raw price). Conceptually distinct from both this phase (swing/fib/trend geometry) and Phase 164
(SMC institutional footprint) — it's a third, genuinely separate regime-detection paradigm
(online Bayesian changepoint vs. the existing per-symbol HMM). **One thing worth noting, found
during the file-location sweep for Section 3 below:** `bocpd_changepoint.py` is not only in
`archive/smc_context/` but also byte-identical in `src/intelligence/features/smc_context/`
(confirmed via `diff`, zero output) — a stray uncleaned duplicate directory, not a second
implementation. `src/intelligence/features/smc_context/` is *mostly* a dead leftover copy of the
archive **except** `hmm_regime.py`, which genuinely is imported live (`pipeline/executor.py:937`,
`feature_cache.py:381` references its `_forward_step`) — that's the per-symbol regime HMM, an
unrelated live concern, not a second changepoint-detection path. This is a minor housekeeping
finding (a stray duplicate directory), not a Phase 165 scope item — noting it so it isn't
rediscovered as a surprise later; worth a one-line cleanup todo, not a phase.

## Section 2: What the prior pass missed — deeper findings

**Finding A (most important): two files have a silent-wrong-answer bug identical in shape to the
one this codebase already burned itself on once.** `trend_structure.py`'s early-return branch
(`if len(swing_highs) < 2 or len(swing_lows) < 2: return {"trend_direction": 0.0,
"trend_strength": 0.0, ..., "price_position": 0.5, ...}`) and `swing_detector.py`'s per-field
defaults (`sh_price = ... if swing_highs else 0.0`, `high_type = 0.0` when `len(swing_highs) < 2`)
both emit **plausible-looking numeric values when there is insufficient data to measure anything
real** — exactly the shape of bug that made `poc_dist_atr`/`va_position`/`sr_support_dist`/
`sr_resist_dist` sit at constant defaults and score `ic_value=0` across 5,510 cells before Phase
163 caught it (todo 153). The difference here: instead of a `FeatureCache` stub never being
populated, these two plugins *themselves* manufacture a fake-but-numeric "no signal" as if it
were a measurement (`trend_direction=0.0` reads identically to "measured, no trend" instead of
"couldn't measure"; `price_position=0.5` reads as "exactly at the midpoint" instead of "unknown").
Literally porting either function is reintroducing the same failure mode this codebase already
paid to discover. **Fix: every field in both plugins must become nullable (`float | None`,
matching the `poc_dist_atr: float | None` precedent already in `FeatureVector`), and the early-
return/default-assignment branches must return `None` per-field, not numeric placeholders.**
`swing_momentum.py` and `fibonacci_zones.py` do NOT have this bug — both correctly return `{}`
(empty dict, "not computed") on insufficient data, never a fake full record. `session_levels.py`
mostly returns `None` per-field already (see its `result[...] = None` branches) — also clean.

**Finding B: three different, undeclared pivot-detection window conventions across the phase's
own files.** `swing_detector.py`/`trend_structure.py` share `neighbor: int = 5` (via
`find_peaks`/`find_troughs`); `support_resistance.py` (Phase 163's file) uses `window: int = 10`
for the same underlying operation; `swing_momentum.py` reimplements its own hand-rolled
`_detect_extremes()` with `_CONFIRM_N: int = 3` — a third value, and a third *implementation*,
of "what counts as a confirmed swing point." This isn't necessarily wrong (`swing_momentum.py`'s
docstring is explicit that self-containment, not code reuse, was the design goal — reasonable
under the old wave-based pipeline where plugin ordering wasn't guaranteed), but it is three
undeclared magic numbers that must each become their own APR key, and it's worth the planner
explicitly deciding whether `swing_detector`/`trend_structure` should share one
`feature.swing.pivot_window` key (recommended — they use the literal same function with the
literal same value already) while `swing_momentum` keeps its own separate
`feature.swing_momentum.confirm_n` (recommended — different calculation, no forcing function to
unify, and unifying would require giving up the self-containment that makes it "cleanest of the
six").

**Finding C: `swing_momentum.py` has six undeclared magic numbers, not zero.** The prior pass's
"already ATR-normalized/bounded, cleanest of the six" framing implied this file was close to
APR-clean. It is not. Beyond `_CONFIRM_N=3` (Finding B): `_MAX_EXTREMES=6`, `_REFERENCE_BARS=20`,
the `clamp(..., 0.1, 3.0)` bounds on `speed_factor`, the `/3.0` divisor in `struct_energy`, and
the `linear_ramp(amplitude_ratio, 1.0, 2.0)` bounds on `swing_amplitude_intensity` are six
separate hardcoded numeric constants, all APR violations under CLAUDE.md's migrate-as-you-go
mandate. This file needs exactly as much APR remediation as `trend_structure.py`, just spread
across more, smaller constants instead of one big divisor.

**Finding D: `swing_high_idx`/`swing_low_idx` are dead weight even in the old pipeline's own
terms.** Checked where these two fields get *consumed* elsewhere in the archived codebase (to
make sure dropping them doesn't silently break something) — `context/anchored_vwap.py` (I4,
"migrated from I3/structure/ to I4/context/ to run after I3 swing detection") reads
`i3.get("swing_high_idx")`/`swing_low_idx"` to anchor a swing-VWAP calculation (lines 89-91). That
consumer itself is archived and out of scope, but it confirms the *only* use for the raw index
was as an anchor point for a downstream calculation, never as a standalone feature — reinforcing
that these should never have been persisted `FeatureVector` columns in the first place, only
ever an internal intermediate.

## Section 3: Alternative port source search (context/ and archive/)

Checked whether a materially better port source exists elsewhere, the way Phase 163 found
`ctx_VolumeProfile` superseded `i3_structure/market_profile.py`. Searched `src/intelligence/
context/` (13 files) and both `smc_context` directories for anything computing swing points, fib-
like retracements, or session pivots more maturely.

**No better port source exists for swing detection, fib zones, or trend structure.** Grepped every
`context/` and `archive/` file for `find_peaks`/`find_troughs`/`swing_high`/`swing_low`/`fib_`/
`weekly_pivot` — the only hits are consumers of `i3_structure`'s own output (`anchored_vwap.py`
reading `swing_high_idx`, several archived I5/SMC/trading files reading `swing_high`/`swing_low`
as inputs), not competing implementations. `src/intelligence/archive/smc_context/swing_utils.py`
(and its live-tree duplicate) is a two-line re-export of the exact same `find_peaks`/`find_troughs`
from `src/intelligence/utils.py` that `i3_structure`'s own files already call directly — there is
no separate, richer swing-detection algorithm hiding anywhere. **Unlike Phase 163, `i3_structure`'s
own swing/trend files already are the canonical implementation** — the same live utility function
everything else in the codebase (including the archived SMC tier) is built on. This is worth
stating plainly rather than silently confirming by omission: the "check for a better source" step
was done, and for this phase (unlike 163) the answer is no, port these files directly.

**`session_levels.py`'s price-pivot concept has no better alternative either, but there IS a
distinct, already-live "session" concept worth not confusing it with.** `context/
session_context.py` (`ctx_SessionContext`, 328 lines, read in full) is a mature, DST-correct,
27-output **time-of-day** session plugin (killzones, exchange-open/close gradients, opening-
range/power-hour/lunch flags) — but it computes *when* in the session a bar falls, never *what
price levels* the prior session left behind. It is not a substitute for `session_levels.py`'s
`prior_session_high`/`weekly_pivot`/etc., which is a distinct concept (price geometry, not time
geometry). Confirmed `ctx_SessionContext` is not wired into `feature_factory.py` either (grepped,
zero hits) — v3's live `in_ny_session` field is computed by `feature_factory.py`'s own minimal
`_in_ny_session()` (line 1560), not through this plugin. No overlap risk, no port-source swap
opportunity — just worth the planner knowing these are two different things with similar names so
neither gets mistaken for the other's job.

**One near-neighbor worth flagging for the promotion-bar discussion (not a port-source
correction):** `archive/smc_context/premium_discount.py` (`smc_PremiumDiscount`, filed under Phase
164, read for context — **not under `context/`, corrected path**; also byte-identical duplicated
at `features/smc_context/premium_discount.py`, same stray-duplicate pattern noted for
`bocpd_changepoint.py` above) computes `premium_discount_pct = clamp((close - equilibrium) / half_range)` where
`equilibrium = (swing_high + swing_low) / 2` — algebraically, this is `2 × (price_position - 0.5)`
using the *same* swing-range concept `trend_structure.py`'s `price_position` and `fibonacci_zones`'s
implied position both draw from. Three different files (this phase's `trend_structure.py`, this
phase's `fibonacci_zones.py`, and Phase 164's `smc_PremiumDiscount`) independently compute a
"where is price within the recent swing range" quantity. None of them is wrong to exist — Phase
163's D-07 already established that near-neighbor conceptual overlap is a promotion-bar question
(incremental IC), not a build-time exclusion — but the planner should know this family is now
three members deep across two phases, and Phase 165's own IC evaluation (whenever it runs) should
test `price_position`'s incremental contribution against `va_position` (Phase 163) too, not just
against `bb_pct_b`/`price_percentile` as D-07 originally scoped.

## Section 4: What this means for Phase 165's actual plan

- **Port sources**: `swing_detector.py`, `swing_momentum.py`, `trend_structure.py`,
  `fibonacci_zones.py` — direct port from `i3_structure`, no better source exists (Section 3).
  `session_levels.py` — direct port of the Asian-session sub-feature; genuine rewrite (not a
  port) of the prior-session/overnight/weekly sub-features, following Phase 163's
  `update_session_vp()`-style `FeatureCache` mutator pattern and reusing the existing
  `update_wk_vwap()`/`_wk_year_week` ISO-week-boundary machinery for the weekly-pivot rollup
  rather than building a second parallel weekly accumulator.
- **Two real correctness bugs to fix during the port, not carry forward**: `trend_structure.py`'s
  and `swing_detector.py`'s silent-numeric-default-instead-of-null pattern (Finding A) — the most
  important finding in this research, structurally identical to the exact bug Phase 163 was
  built to fix.
- **`fibonacci_zones.py`'s fallback should be deleted, not resolved-in-place**: this phase already
  ports `swing_detector.py` in the same wave; compute swing high/low once per bar as local
  variables inside `compute()`/`compute_batch()` and feed both plugins from that, eliminating the
  cross-plugin-read fallback entirely.
- **Do not add all 5 individual fib-level distances** — `nearest_fib_ratio` + `nearest_fib_dist_atr`
  already compress the useful signal; adding more would be Phase 163's D-17 collinearity finding
  repeated five times with no new distinct hypothesis behind it.
- **`session_levels.py` is its own plan within this phase, not its own phase** — the boundary-
  detection rewrite is real work, but every primitive it needs (timestamp-based NY-session-open
  detection, `FeatureCache` mutator pattern, ISO-week accumulator) already exists from Phase 163/
  the existing `update_wk_vwap()`. Splitting into a separate phase would add coordination overhead
  without a real dependency gap.
- **`macd_events.py` and `bocpd_changepoint.py` stay parked** — both confirmed, for different
  reasons (missing prerequisite indicator vs. deliberate algorithmic-cost gate), neither a Phase
  165 scope item.
- **APR surface is bigger than the prior survey found**: `trend_structure.py` alone needs 3 keys
  (not 1), `swing_momentum.py` needs 6 (not 0), `swing_detector.py`/`trend_structure.py` should
  share one pivot-window key, `fibonacci_zones.py` needs 1 (cluster threshold), `session_levels.py`
  needs a full new namespace for its session-boundary parameters.
- **Post-research addendum (same session, council-style rigor pass on 3 tangential ideas):** two
  survived and were added — `gap_filled` (session_levels.py, D-13) and `swing_volume_confirmation`
  (swing_momentum.py, D-15), both zero-marginal-cost columns off computation already happening.
  Fibonacci extension levels were proposed and explicitly rejected for this build (D-14) — scaling
  an unproven fib-retracement hypothesis family before its first member clears an incremental-IC
  test fails CLAUDE.md's 5-step mandate ("don't accelerate in the wrong direction"). Final column
  count: 41, not 39. See `165-CONTEXT.md`'s D-13/D-14/D-15 for full reasoning.
