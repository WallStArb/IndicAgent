# Extreme-Volume Divergence / Confirmed-Reversal — Pre-registration (DRAFT, not yet run)

**Status:** Draft pre-registration, H-A and H-B both in scope. No script written, no statistic
computed. **H-B was briefly dropped 2026-09-08 (AGY review round 1), then reinstated the same
day** after direct user pushback ("are we sure the reversal bar volume can't be determined?")
prompted a second look — the reused column (`swing_volume_confirmation`) was genuinely wrong,
but the underlying quantity IS computable from other already-persisted columns; see "AGY review
round 1" section below for the full correction trail, including my own error in concluding a
new pipeline feature was required.
**Author:** Claude (Sonnet 5), interactive session, 2026-09-06. Amended 2026-09-08 (AGY review
round 1, then a same-day correction to that round's H-B disposition).
**Origin:** User-directed hypothesis, trading-experience-derived: a bounce off a low with
volume EXPANSION, or a new low on LIGHTER volume, are classic reversal-divergence tells;
the mirror pattern applies at highs (heavy-volume pullback from a high vs. a new high on
lighter volume).

**Scope note, corrected 2026-09-06 after user clarification:** this is a signal/theory
question, evaluated on its own statistical merits — whether the pattern predicts anything
at all — independent of any account-size cost model. It is explicitly NOT part of the
Personal-Scale Edge Determination program (`docs/plans/2026-09-02-personal-scale-edge-
determination-plan.md`); that program's cost-hurdle machinery (spread/commission/impact
calibrated to a specific account size) does not gate anything here. If this construction
is ever found to have real, stable, economically-nontrivial predictive content, evaluating
it against any particular trading account's costs is a separate, later question — not a
condition of this pre-registration passing or failing. This document reuses this project's
general-purpose statistical machinery (bootstrap, null, FDR — `ic_math.py`) because that
machinery is how every construction in this codebase is tested for correctness, not
because of any connection to the personal-scale program.

---

## The two hypotheses, kept separate (no single conflated statistic)

Both read the same underlying phenomenon — volume should confirm the direction of a move;
when it doesn't, the move is suspect — but they are temporally distinct and are tested,
reported, and (if either reaches Track 2) regime-encoded independently.

- **H-A, "divergence" (leading/contrarian):** a fresh N-bar extreme made on LIGHT volume
  warns of an impending reversal against the extreme — light volume on a new low warns of
  upside reversal; light volume on a new high warns of downside reversal.
- **H-B, "confirmation" (coincident):** heavy volume on the leg moving AWAY from a recent
  extreme confirms the reversal is real and already underway — a heavy-volume bounce off a
  low is bullish-confirming; a heavy-volume pullback from a high is bearish-confirming.
  **Construction corrected 2026-09-08** (see review section): built from
  `bars_since_low_fast`/`bars_since_high_fast` + `volume_z` (both already in
  `feature_vectors`, already used by H-A) plus a join to `market_data_ohlcv_tradeable` for
  `close` — not from `swing_volume_confirmation`, which measures the wrong leg.

## Construction spec — built from existing `feature_vectors` columns (+ one raw-OHLCV join for H-B's sign)

No new `feature_factory.py` column, no corpus recompute needed for either statistic. H-A is a
pure `feature_vectors` read; H-B additionally joins `market_data_ohlcv_tradeable` (by
`symbol`/`timeframe`/`timestamp`) for raw `close`, needed only for the leg's directional sign
— still a read-only analysis script (same posture as `range_pct_fast_xs_ls_h5_falsification.py`
/ `alpha_score_residual_single_security_15m.py`) whenever compute is available; does not
depend on any other program's sequencing. (Practical note, not a design constraint: hold off
running while the current `ic_engine` corpus recompute is active — resource contention, not a
program-sequencing issue; see "Not yet done" below.)

- **`extreme_proximity_t`**: +1 if `bars_since_low_fast_t == 0` (bar t is itself a fresh
  rolling low over the existing `dist_window_fast` window, APR-governed, no new tunable),
  −1 if `bars_since_high_fast_t == 0`, else 0 if neither or if both simultaneously (outside
  bar — excluded from the panel either way, see AGY-review section).
- **H-A statistic, `extreme_volume_divergence_t`** (defined only where
  `extreme_proximity_t != 0`): `−extreme_proximity_t × volume_z_t`, using the persisted
  `volume_z` column. A single internally-consistent directional predictor: positive at a
  light-volume fresh low (value is genuinely positive there), negative at a light-volume
  fresh high (value is genuinely negative there) — both cases correlate the same direction
  with signed forward return, so pooling low-side and high-side events does not cancel (see
  AGY-review section for the worked algebra). Forward return measured from bar t (the
  extreme bar itself), same `return_type='executable_open_to_open'` / `forward_returns`
  convention as every other construction in this codebase (Invariant 1).
- **H-B statistic, `confirmed_reversal_t`** (corrected construction, 2026-09-08): let
  `k_low_t = bars_since_low_fast_t`, `k_high_t = bars_since_high_fast_t` (both already
  causal, both saturate at `dist_window_fast − 1 = 19`, so the leg span below is always
  bounded). Reference leg = whichever extreme is more recent: if `k_low_t < k_high_t`, the
  bar is `k_low_t` bars into an up-leg off a low; if `k_high_t < k_low_t`, `k_high_t` bars
  into a down-leg off a high; if equal (tie, including the `k=0` outside-bar case), excluded
  — same tie-break as `extreme_proximity_t` above, no separate rule to invent. Let `k` be
  that reference distance and require `k >= 1` (there must be an actual leg, not just the
  extreme bar itself — `k=0` is H-A's domain, not H-B's).
  `confirmed_reversal_t = sign(close_t − close_{t−k}) × mean(volume_z_{t−k .. t})` — the
  signed mean of the persisted `volume_z` column over the leg span, direction fixed by raw
  `close_t − close_{t−k}` (the already-locked close-to-close convention, now with real data
  to act on rather than a column that measured the wrong thing). Positive = up-leg off a low
  with above-average volume (bullish-confirming) or down-leg off a high with above-average
  volume, signed consistently with return (bearish-confirming, i.e. negative here) — same
  pooling logic as H-A's sign convention, not re-derived per side.
- **Wick corroboration (reported, not gated):** `lower_wick_ratio_t` at H-A/H-B low-side
  events, `upper_wick_ratio_t` at high-side events — the "wick size/bar characteristic" half
  of the user's original framing, kept out of the primary gated statistics to avoid a second
  undeclared researcher degree of freedom (which wick threshold, what combination rule) that
  would need its own justification. If either passes, a wick-conditioned successor is the
  natural next pre-registration, not a same-run addition.

## Track 1 — signal existence (continuous statistic)

Single-security IC test, reusing this project's standard statistical machinery (not
reinvented per construction). Locked quantities below per AGY review round 1
(`tf=15m`, universe = all 231 active instruments, IS-only via `bar_ts < alpha.validation.
oos_start`):

- Primary statistic: within-symbol Spearman IC of `extreme_volume_divergence` (H-A) and,
  independently, `confirmed_reversal` (H-B) against `forward_returns.return_fast` (1-bar,
  primary/gated) and `return_mid` (ungated robustness check only, not a second chance to
  pass) — each hypothesis tested, reported, and gated on its own, never combined into one
  statistic. Family statistic = equal-weighted mean across qualifying symbols of
  within-symbol Spearman IC, matching `alpha_score_residual_single_security_15m.py`'s
  convention.
- Bootstrap: date-indexed panel resampler (port the `Panel` structure from
  `alpha_score_residual_single_security_15m.py`), NOT a raw call to
  `_circular_block_bootstrap_ic` on the filtered event rows — that function's row-index
  block slicing has no date awareness and would silently span unrelated dates once the
  panel is pre-filtered to sparse extreme-only bars.
- Null: whole-date circular shift on the full dense panel (extremes at date D map to
  non-extreme dates under the shift, which is the correct null), not a shift applied after
  filtering to extreme rows only.
- FDR: BH across symbols (reported) and BY across symbols (gated) via
  `ic_math.py::_p_values_from_ic`'s asymptotic t-approximation — same per-symbol
  significance machinery as every other BY-FDR gate in this codebase (e.g.
  `feature_ic_scores.passes_fdr`), not an empirical permutation p-value.
- Cross-sectional arm: dropped (see AGY-review section — same-bar ranking is degenerate at
  this event density, not worth computing even as a reported secondary).
- Missingness: panel requires `complete_fast = true` (`complete_mid = true` for the
  secondary band).

**PASS rule (Track 1, H-A and H-B independently, either may pass without the other) — pure
statistical existence plus a minimum effect-size floor:**

1. Bootstrap ci_lower > 0 (the effect is not noise).
2. Date-shift null p < 0.05 (the effect is not an artifact of the null construction).
3. Stability: **positive** point estimate in 3/3 equal calendar-date temporal subperiods
   (not a one-era artifact; same-sign-but-negative does not qualify).
4. Qualifying fraction of symbols individually significant at BY-FDR α=0.05, positive
   direction, floor = 10% (matches this codebase's established precedent; no
   minimum-events-per-symbol adjustment needed — see density calibration below).
5. Effect-size floor: family-mean IC ≥ 0.003 (matches this codebase's established economic
   floor convention, e.g. the residual pre-reg's 0.0027) — pure statistical significance
   with no magnitude floor would let an economically inert IC of +0.0003 pass criteria 1-4.

Reported, never gated: per-regime table, per-symbol BH table (less conservative
comparison point), negative-qualifier count, raw (non-divergence-adjusted) arm for
comparison.

## Track 2 — regime candidate

Gated on Track 1 passing first, per hypothesis — a construction with no continuous-signal
content has no basis for a regime encoding. **Do not** build
`regime_extreme_volume_divergence` or `regime_confirmed_reversal` as an HMM `regime_*`
column under any circumstance; if either reaches Track 2, the discrete cut is deterministic
quantile tiering via `build_tiers()`, never HMM (same reasoning as the closely related
rejected candidate, todo 281: identifiability by construction, no EM — an
identifiability-vs-signal curve is therefore not a meaningful check here, since
`build_tiers()` identifiability is trivially 1.0; that check was testing a path — HMM —
this design already forbids reaching, per AGY review round 1).

Re-scoped checks, if either H-A or H-B passes Track 1:

1. **Regime-coverage handling:** H-A fires on 26-30% of bars (density calibration below) —
   still a minority; H-B fires on a subset of that (requires `k >= 1`, i.e. excludes the
   extreme bar itself). Explicit design for the majority of bars with no active event (a
   distinct "no signal" tier, not silently defaulted into an existing tier) is required
   before this can be called a regime axis rather than an episodic trade trigger.
2. **Null-arm control:** scrambled-data control (shuffle the volume series independent of
   price, or shuffle bar order within a matched-length synthetic series) — the discretized
   regime must not be recoverable from noise at the same rate as from real data.
3. **IC separation across buckets:** does IC actually differ, monotonically, across
   `build_tiers()`'s own quantile buckets, not assumed from Track 1's continuous-signal
   result alone.

## Fixed quantities

`dist_window_fast` per its current APR value (not re-derived) · lookahead = `return_fast`
(gated) and `return_mid` (reported) · B=2000 (bootstrap replicates) · N_null=1000 (date-shift
null replicates for the single overall existence test — the per-symbol BY-FDR gate uses
`_p_values_from_ic`'s asymptotic t-approximation instead, not this empirical null, so no
resolution-floor concern) · BY/BH alpha=0.05 · `IC_min=0.003` (both hypotheses) · seed via
`hash_key_to_int("extreme_volume_divergence…")` / `hash_key_to_int("confirmed_reversal…")`.

## AGY review round 1 (2026-09-08) — and a same-day correction to my own follow-through

Full raw review:
`docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg-agy-review-round1.md`.
Two of its claims were checked against source and found overstated/wrong; one is a confirmed
real bug. Treat every other item in the raw review as plausible but not independently
re-verified — it is a genuinely useful adversarial pass, not a rubber stamp.

**Confirmed real (source-verified): H-B's originally *proposed* feature primitive is wrong.**
`swing_volume_confirmation` (`src/intelligence/feature_factory.py:4653-4658`) computes mean
volume over `[extremes[-2], extremes[-1]]` — the span between the two most recently
*confirmed* swing extremes (confirmation requires `confirm_n` bars past the pivot). The
still-forming bounce leg away from the latest extreme is NOT `extremes[-1]` yet (it isn't
confirmed); `extremes[-1]` is the prior *completed* leg. So this column measures the sell-off
*into* a low, not the bounce *off* it — the opposite of H-B's stated construction.

**My error, corrected same day after direct user pushback:** I initially concluded from this
that "H-B as specified cannot be built from existing `feature_vectors` columns" and dropped it
from this pre-registration entirely, reasoning that a correct version would need a genuinely
new `feature_factory.py` column (real code change, out of this doc's read-only scope). That
conclusion conflated two different claims: "the one column I proposed reusing measures the
wrong thing" is true; "no existing data can measure this" is false. Checked properly:
`bars_since_low_fast`/`bars_since_high_fast` (`feature_factory.py:2633`,
`_bars_since_rolling_extreme_series_full`) are a simple, already-causal, already-persisted
rolling-window "bars since the extreme" counter, saturating at `dist_window_fast − 1 = 19` —
no dependency on `swing_volume_confirmation`'s confirmed-swing-detection logic at all, and
already the exact columns H-A's own `extreme_proximity_t` gate uses. Combined with the
already-persisted `volume_z` and one join to `market_data_ohlcv_tradeable` for raw `close`
(confirmed to carry a `volume` and `close` column), H-B's actual economic quantity — volume on
the leg away from a recent extreme — is fully computable, read-only, no new pipeline column,
no corpus recompute. **H-B reinstated** with the corrected construction (see "The two
hypotheses" and "Construction spec" sections above). Recorded here rather than silently
edited away, matching this doc's own standard for tracking corrections, including my own.

**Overstated/incorrect on verification (kept only for the record, not actioned):**
- H-A "self-contradictory sign formula, washes out to zero": wrong. `stat =
  -extreme_proximity_t × volume_z_t` is a single internally-consistent directional predictor
  — positive stat correlates with positive return at lows, negative stat with negative return
  at highs, both cases pooling to the SAME correlation direction, not cancelling. The
  original doc's prose ("positive = ... or the equivalent... case") was loosely worded (the
  high-side value is literally negative, not positive) — a clarity fix below, not a math bug.
- "BY-FDR mathematically impossible at N_null=1000": conflates two different statistics.
  `N_null=1000` here is for the single overall date-shift existence test (Track 1's headline
  bootstrap/null). This codebase's actual per-symbol significance gate feeding BY-FDR (used
  everywhere else, e.g. `feature_ic_scores.passes_fdr`) is `ic_math.py::_p_values_from_ic`, an
  asymptotic t-approximation with no discrete resolution floor — not an empirical permutation
  p-value. The doc should say this explicitly (real, minor gap, fixed below); it is not the
  blocking defect claimed.

**Real, valid, now locked (from the raw review's list of unclosed degrees of freedom):**
- **Timeframe:** locked to `15m` (matches this codebase's default single-security-diagnostic
  tf, e.g. `alpha_score_residual_single_security_15m.py`; also the tf with the largest N for
  a first pass — 6.6M extreme bars per the density calibration above).
- **Universe:** the standard 231-symbol active-instrument universe, no filtering.
- **IS/OOS clamp:** explicit `bar_ts < alpha.validation.oos_start` filter, matching every
  other pre-registration in this codebase (Invariant on the virgin holdout).
- **Outside-bar handling:** a bar that is simultaneously a fresh 20-bar high AND low
  (`bars_since_low_fast == 0 AND bars_since_high_fast == 0`) sets `extreme_proximity_t = 0`
  (excluded from H-A's panel) rather than defaulting to one side — prevents the low-side
  tie-break bias the raw review flagged.
- **Family IC aggregation:** equal-weighted mean across qualifying symbols of within-symbol
  Spearman IC, matching `alpha_score_residual_single_security_15m.py`'s convention.
- **Lookahead-band gating:** `return_fast` is the primary gated horizon (all 4 PASS criteria);
  `return_mid` is reported as an ungated robustness check only, not a second independent
  chance to pass — closes the "either/both/multiplied-false-positive-rate" gap.
- **Temporal subperiods:** calendar-date thirds (matching this codebase's established
  "3 equal temporal subperiods" convention elsewhere, e.g. the residual pre-reg), not
  event-count thirds — accepting the resulting sample-size imbalance across subperiods as
  reported context, not a gate.
- **Criterion 3 sign:** tightened to require a *positive* point estimate in 3/3 subperiods
  (not merely "same sign," which the raw review correctly noted would also pass 3/3 negative).
- **Missingness:** panel requires `complete_fast = true` (`complete_mid = true` for the
  secondary band) — same house convention as prior pre-registrations, explicit here to close
  the gap the raw review flagged.
- **Bootstrap harness:** `_circular_block_bootstrap_ic` operates on contiguous row-index
  arrays with no date awareness — correct for a dense per-bar panel, wrong for a panel
  pre-filtered to sparse extreme-only rows (a block would silently span unrelated dates
  months apart). Track 1 must build a date-indexed panel resampler (porting the pattern from
  `alpha_score_residual_single_security_15m.py`'s `Panel` structure) rather than reusing the
  dense-panel bootstrap directly on the filtered event rows.
- **Cross-sectional arm:** demoted from "secondary, reported" to **dropped**. At any given
  bar, only a handful of the 231 symbols are at a fresh 20-bar extreme simultaneously — a
  same-bar cross-sectional rank is degenerate (mostly zero/NaN) except on broad market-wide
  extreme days, which would make the arm dominated by crash-day survivorship rather than a
  general reversal-timing signal. Not worth computing even as a reported secondary.
- **Effect-size floor:** added `IC_min = 0.003` (matching this codebase's established
  economic-floor convention, e.g. the residual pre-reg's `IC >= 0.0027`) as a 5th PASS
  criterion — pure statistical existence with no magnitude floor lets an economically inert
  IC of +0.0003 pass criteria 1-4.
- **Track 2 identifiability-curve scoping:** the original phrasing applied one "identifiability
  curve" check across both the HMM and `build_tiers()` discretization paths. For
  `build_tiers()` (deterministic quantile tiering, the path this doc already mandates if
  Track 2 is ever reached — see below), identifiability is trivially 1.0 by construction; an
  identifiability-vs-signal curve is only a meaningful check for the HMM path, which this doc
  already forbids reaching. Track 2, if either hypothesis ever gets there, is re-scoped to: (1) explicit
  regime-coverage handling for the ~74-97% of bars with no active event (an episodic signal is
  not automatically a 100%-coverage regime axis — this needs its own design, not assumed away);
  (2) monotonic IC separation across `build_tiers()` quantile buckets; (3) a scrambled-volume
  null control. HMM is not reachable in this design regardless, so an identifiability-vs-signal
  curve is dropped as its own check, not "insufficient" — it was testing the wrong path.

**AGY round 2:** recommended on the amended design (both hypotheses, H-B's corrected
construction specifically) before writing Track 1's script — not yet requested. Given round 1
caught a real construction bug and I separately over-corrected past it once already this same
day, a round 2 pass is a stronger recommendation now than "not strictly required" — the H-B
construction above has not been adversarially checked at all yet.

## Density calibration (2026-09-08)

Live SQL aggregation against `feature_vectors` (`bars_since_low_fast = 0 OR
bars_since_high_fast = 0`, cheap aggregation, no bootstrap): extreme-bar fraction is **26-30%
of all bars at every tf** (5m: 21.6M/73.2M; 15m: 6.6M/25.3M; 1h: 1.77M/6.88M; 1d: 252K/956K;
all 231 symbols present at every tf). This corrects this doc's original framing ("fire on
sparse, irregularly-spaced events") — at `dist_window_fast=20` a fresh 20-bar extreme is
roughly 3x denser than the ~10% naive random-walk baseline (autocorrelated/trending price
action inflates fresh-extreme frequency), not sparse in absolute terms. No
minimum-events-per-symbol floor is needed: even at 1d, the sparsest tf, mean events/symbol is
~1092 (252,310 / 231), comfortably above any BY-FDR per-symbol floor this codebase has used.

**Not yet done:** no script written, no statistic computed. Track 1 execution deliberately
held as of 2026-09-08 — the corpus `ic_engine` recompute is mid-run using ~20GB RSS + heavy
CPU on a box that OOM'd once already this week (see
`.planning/todos/pending/371-ic-engine-cross-sectional-cell-size-guard-post-materialization-ooms-at-universe-scale.md`);
launching a second compute job now is exactly the contention this doc's own construction
section already cautioned against. Write + run Track 1 once AGY's review lands and the
recompute clears (or once there's confirmed headroom, whichever first).
