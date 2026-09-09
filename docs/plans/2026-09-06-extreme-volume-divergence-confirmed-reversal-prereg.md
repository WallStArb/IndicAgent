# Extreme-Volume Divergence / Confirmed-Reversal — Pre-registration (DRAFT, not yet run)

**Status:** Both H-A and H-B are complete, reviewed designs. **Neither has run** — no script
written, no statistic computed. H-A cleared two review rounds with no open issues. H-B took
three attempts: dropped (round 1, wrong column), reinstated with a flawed fix (round 2, five
confirmed bugs), then redesigned from scratch independently by Fable and cleared a third
review round (conditional pass, four amendments, three locked into the spec below, one — a
gap in shared testing machinery reaching beyond this doc — filed separately as todo 372).
**Execution is blocked for both hypotheses** on compute (the corpus `ic_engine` recompute) and,
for H-B specifically, also on todo 372's null-shift gap. See "H-B redesign (2026-09-09)" below
for the full trail, including three of my own errors across the process, all recorded rather
than quietly edited away.
**Author:** Claude (Sonnet 5), interactive session, 2026-09-06. Amended 2026-09-08 (AGY review
round 1, a same-day correction to that round's H-B disposition, then AGY review round 2 on the
corrected construction). Amended 2026-09-09 (H-B redesigned from scratch by Fable, independent
subagent dispatch, then AGY review round 3 on the redesign).
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
- **H-B, "confirmation" (coincident):** **scope note, locked 2026-09-09 per AGY round 3's
  amendment 4** — this statistic measures volume expansion during a persistent pause following
  an extreme (price has not printed a *new* extreme of either type for `K_CONFIRM` bars), not
  price-directional confirmation; it does not require price to have actually moved away from
  the extreme, only that no fresh opposing extreme has invalidated it. With that scope in mind:
  elevated volume in the bars immediately following a confirmed, unbroken extreme suggests the
  reversal is real and already underway — elevated volume following an unbroken low is
  bullish-confirming; following an unbroken high, bearish-confirming. **Construction finalized
  2026-09-09** after a full from-scratch redesign (see "H-B redesign (2026-09-09)" below) —
  two prior attempts failed (round 1: wrong column; round 2: five confirmed bugs in a
  leg-averaging construction). The current construction is a single-bar-anchored,
  fixed-offset statistic with no averaging-window ambiguity, structurally immune to all five
  round-2 bugs (independently verified, not just claimed).

## Construction spec — built entirely from existing `feature_vectors` columns

No new `feature_factory.py` column, no corpus recompute needed for either statistic — both
are pure `feature_vectors` reads, no raw-OHLCV join for either one (H-B's finalized
construction below needs no `close` value at all, unlike the two prior, now-superseded H-B
attempts). Read-only analysis script (same posture as
`range_pct_fast_xs_ls_h5_falsification.py` / `alpha_score_residual_single_security_15m.py`)
whenever compute is available; does not depend on any other program's sequencing. (Practical
note, not a design constraint: hold off running while the current `ic_engine` corpus recompute
is active — resource contention, not a program-sequencing issue; see "Not yet done" below.)

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
- **H-B statistic, `confirmed_reversal_i`** — **finalized construction, 2026-09-09** (design:
  Fable, independent from-scratch redesign; review: AGY round 3, conditional pass, amendments
  incorporated below). Per `(symbol, tf)`, ordered by `bar_ts`, index `i = 0 .. n-1`, forward
  scan carried across the whole series (fetched with a trailing buffer before the IS-window
  start per amendment 2 below, so anchor state is genuinely warmed up at the clamp boundary —
  not reset there):

  ```
  low_ext[i]  = (bars_since_low_fast[i]  == 0)
  high_ext[i] = (bars_since_high_fast[i] == 0)
  tie[i]      = low_ext[i] AND high_ext[i]        # outside bar
  clean_low[i]  = low_ext[i]  AND NOT tie[i]
  clean_high[i] = high_ext[i] AND NOT tie[i]

  anchor_idx, anchor_type = None, None            # forward-scan state, carried across i
  for i in 0 .. n-1:
      if clean_low[i]:
          anchor_idx, anchor_type = i, 'low'
      elif clean_high[i]:
          anchor_idx, anchor_type = i, 'high'
      elif tie[i]:
          anchor_idx, anchor_type = None, None    # AMENDMENT 1 (round 3): a tie hard-resets
                                                     # the anchor -- an outside bar prints a
                                                     # new opposing extreme too, invalidating
                                                     # any prior single-sided anchor. Does NOT
                                                     # carry over (round 3 caught this leaking
                                                     # invalid legs into E).
      # else: anchor unchanged, carries over
      anchor_idx_at[i], anchor_type_at[i] = anchor_idx, anchor_type

  k[i] = i - anchor_idx_at[i]   # undefined while anchor_idx_at[i] is None
  ```

  **Only ever reads `bars_since_low_fast`/`bars_since_high_fast` as an `== 0` boolean flag** —
  the one part of those columns round 2's review verified as causal and correct. Never
  re-reads their non-zero runtime value, which is what made round 2's construction able to
  silently re-anchor onto a non-extreme bar. `anchor_idx` is write-once per leg, assigned only
  when the *current* bar's own flag is true — there is no code path by which it can reference
  a bar that wasn't itself a genuine extreme when it happened (independently re-derived, not
  just asserted — see "H-B redesign" below).

  **Warmup guard (AMENDMENT, found empirically 2026-09-09):** exclude each symbol's first
  `2 * dist_window_fast` bars from eligibility as an anchor-setting event — before a full
  trailing window has accumulated, nearly every bar trivially registers `== 0`, seeding
  spurious anchors. Confirmed live on SPY/15m: 13 of the first 20 bars would otherwise
  register as fresh-low events.

  **Event set and statistic**, for `K_CONFIRM` locked before running (primary `3`, robustness
  `{1, 2, 5}` reported/ungated — see "Fixed quantities"), with `a = anchor_idx_at[i]`:

  ```
  E = { i : k[i] == K_CONFIRM  AND  anchor_type_at[i] is not None }

  leg_volume[i] = mean(volume_z[a+1 .. a+K_CONFIRM])   # NEVER includes volume_z[a] itself
  sign[i]       = +1 if anchor_type_at[i] == 'low' else -1
  confirmed_reversal[i] = sign[i] * leg_volume[i]
  ```

  `E` is `confirmed_reversal`'s entire domain of definition — undefined everywhere else, not
  zero- or NaN-filled into the panel. Empirically, on SPY/15m: `K_CONFIRM=3` fires on 6.9% of
  bars (27.1% of H-A-eligible extremes survive unbroken that long); `K_CONFIRM=1/2/5` fire on
  11.3%/8.5%/5.2% respectively. Genuinely sparse — nowhere near round 2's ~70% density bug.
  No `close` value or `market_data_ohlcv_tradeable` join anywhere in this construction (sign
  comes from which extreme type fired, never from a price delta) — simpler than either prior
  attempt, not just more correct. **Scope trade-off, made explicit per AGY round 3's amendment
  4**: because the sign never checks price, a bar can enter `E` with the "wrong" economic read
  (e.g. a low-volume-supported breakdown consolidating just above a low, still reads as
  bullish) — this is why the hypothesis description above states the narrower, honest scope
  rather than a stronger "price confirmed" claim the statistic doesn't actually support.

  Full design trail, all findings, and what's independently re-verified vs. merely asserted:
  `docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md` and its round 3
  review `docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-agy-review-round3.md`.
- **Wick corroboration (reported, not gated):** `lower_wick_ratio_t` at H-A/H-B low-side
  events, `upper_wick_ratio_t` at high-side events — the "wick size/bar characteristic" half
  of the user's original framing, kept out of the primary gated statistics to avoid a second
  undeclared researcher degree of freedom (which wick threshold, what combination rule) that
  would need its own justification. If either passes, a wick-conditioned successor is the
  natural next pre-registration, not a same-run addition.

## Track 1 — signal existence (continuous statistic)

**Both hypotheses have complete, reviewed designs as of 2026-09-09 — see the top-of-doc
Status line for what's actually blocking execution.** Single-security IC test, reusing this
project's standard statistical machinery (not reinvented per construction). Locked quantities
below per AGY review round 1 (`tf=15m`, universe = all 231 active instruments, IS-only via
`bar_ts < alpha.validation.oos_start`, fetched with a trailing buffer per H-B's amendment 2 so
its forward scan is warmed up at the clamp boundary):

- Primary statistic: within-symbol Spearman IC of `extreme_volume_divergence` (H-A) and,
  independently, `confirmed_reversal` (H-B, `K_CONFIRM=3` primary) against
  `forward_returns.return_fast` (1-bar, primary/gated) and `return_mid` (ungated robustness
  check only, not a second chance to pass) — each hypothesis tested, reported, and gated on
  its own, never combined into one statistic. Family statistic = equal-weighted mean across
  qualifying symbols of within-symbol Spearman IC, matching
  `alpha_score_residual_single_security_15m.py`'s convention.
- Bootstrap: date-indexed panel resampler (port the `Panel` structure from
  `alpha_score_residual_single_security_15m.py`), NOT a raw call to
  `_circular_block_bootstrap_ic` on the filtered event rows — that function's row-index
  block slicing has no date awareness and would silently span unrelated dates once the
  panel is pre-filtered to sparse extreme-only bars.
- Null: whole-date circular shift on the full dense panel (extremes at date D map to
  non-extreme dates under the shift, which is the correct null), not a shift applied after
  filtering to extreme rows only. **Blocked as specified for both hypotheses**: AGY round 3
  found `Panel.sync_shift_null_p`'s per-symbol shift isn't actually calendar-synchronous when
  active-date counts vary across symbols (verified against source, filed as todo 372) —
  Track 1 execution needs that resolved first, not a same-day patch here.
- FDR: BH across symbols (reported) and BY across symbols (gated) via
  `ic_math.py::_p_values_from_ic`'s asymptotic t-approximation — same per-symbol
  significance machinery as every other BY-FDR gate in this codebase (e.g.
  `feature_ic_scores.passes_fdr`), not an empirical permutation p-value.
- Cross-sectional arm: dropped for both hypotheses (see AGY-review sections — same-bar
  ranking is degenerate at either hypothesis's event density, not worth computing even as a
  reported secondary).
- Missingness: panel requires `complete_fast = true` (`complete_mid = true` for the
  secondary band).
- **Diurnal sub-panel (AGY round 3, todo 372):** `volume_z` has no session-boundary
  detrending — report an ungated morning (9:45-11:30am) vs. afternoon (11:45am-3:45pm)
  breakdown for both hypotheses, so a PASS isn't an artifact of the market-open volume smile.

**PASS rule (Track 1, each hypothesis independently, either may pass without the other) — pure
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

1. **Regime-coverage handling:** H-A fires on 26-30% of bars, H-B (`K_CONFIRM=3`) on ~6.9%
   (SPY/15m, empirical — see "H-B redesign" below) — both a real minority, giving an honest
   "no active event" majority tier to design for. Explicit design for that majority (a
   distinct "no signal" tier, not silently defaulted into an existing tier) is required
   before either can be called a regime axis rather than an episodic trade trigger.
2. **Null-arm control:** scrambled-data control (shuffle the volume series independent of
   price, or shuffle bar order within a matched-length synthetic series) — the discretized
   regime must not be recoverable from noise at the same rate as from real data.
3. **IC separation across buckets:** does IC actually differ, monotonically, across
   `build_tiers()`'s own quantile buckets, not assumed from Track 1's continuous-signal
   result alone.

## Fixed quantities

`dist_window_fast` per its current APR value (not re-derived) · `K_CONFIRM=3` primary
(gated) for H-B, `K_CONFIRM ∈ {1, 2, 5}` reported/ungated robustness · warmup exclusion =
`2 * dist_window_fast` bars per symbol (H-B) · lookahead = `return_fast` (gated) and
`return_mid` (reported) · B=2000 (bootstrap replicates) · N_null=1000 (date-shift null
replicates for the single overall existence test — the per-symbol BY-FDR gate uses
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

## AGY review round 2 (2026-09-08) — H-B's round-1-corrected construction: confirmed flawed

Full raw review:
`docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg-agy-review-round2.md`.
Requested specifically on H-B's new construction after round 1's fix, given the pattern of
this document already having one confirmed self-correction earlier the same day. Every
substantive claim below was independently re-derived against the actual algorithm (not just
accepted from AGY's assertion) before being recorded here.

**Confirmed real, re-verified independently:**
- **Causality: verified correct.** `_bars_since_rolling_extreme_series_full` reads only
  `values[i]` at each step and never looks forward — the causality claim in the prior section
  holds. Not a flaw; recorded here because round 2 checked it explicitly and it's the one
  claim about this construction that survives intact.
- **"Subset" claim was a pure logic error, mine.** `k >= 1` is the complement of `k = 0`, not
  a subset — trivially true, no verification needed beyond reading the two sets. H-B as
  specified fires on ~70% of bars (everything H-A's `k=0` gate excludes), not a sparse
  episodic subset of H-A's 26-30%. This inverts the density picture the "Regime-coverage
  handling" bullet above relied on.
- **"Saturates" was the wrong word, and the substance matters, not just the word.**
  Re-derived the monotonic-deque algorithm by hand: for a leg shorter than `window` (20)
  bars, the reference index stays correctly anchored to the true extreme bar throughout —
  this part of the design is sound. But once a leg runs 19+ bars without a new extreme, the
  true anchor ages out of the trailing window (`dq[0] <= i - window` pops it), and the new
  `dq[0]` can be a bar that was never itself a fresh extreme (`bars_since_low_fast == 0`
  never true for it) — it only became "the window's current min" because the real extreme
  aged out from under it. From that point on, `k` silently tracks a fabricated anchor,
  indistinguishable in the data from a genuine reversal leg. This is a real design gap in
  reusing a sliding-window column for "leg since a confirmed extreme" — not present in H-A,
  which only ever reads the `k=0` case (always a genuine fresh extreme by definition).
- **Capitulation-volume contamination, reintroduced.** `mean(volume_z_{t-k..t})` as written
  includes `t-k` (the extreme bar) in its own range — the same conceptual bug round 1 found
  in `swing_volume_confirmation`, now self-inflicted in the replacement formula. Confirmed by
  rereading my own range notation; not in dispute.
- **Sign-convention wick-inversion: real.** `sign(close_t - close_{t-k})` never references
  which type of extreme (`k_low` vs `k_high`) is active — an extreme bar whose close sits far
  from its own high/low (a hammer or shooting-star candle) can flip the sign of an otherwise
  correctly-identified bullish or bearish leg. Signing by extreme-type identity directly
  (`+1` if `k_low_t < k_high_t` else `-1`) avoids this and is closer to the original
  intent anyway ("up-leg off a low is bullish" is about which extreme, not the exact
  close-to-close delta).
- **Serial correlation, a real consequence of the density finding.** Given H-B is dense
  (~70% of bars) and adjacent bars within one leg share nearly the entire `[t-k, t]`
  averaging window, treating each bar as an independent observation for the BY-FDR gate's
  `df = n - 2` t-approximation would understate standard errors substantially. Any
  redesign needs either a much sparser event definition (one observation per leg, not one
  per bar) or an explicit autocorrelation adjustment — not the current per-bar panel as
  specified.

**Not independently re-verified, plausible:** the horizon-mismatch point (multi-bar leg
statistic vs. a 1-bar forward return) and the "this is just momentum, not reversal
confirmation" framing critique are reasonable but weren't algebraically checked the way the
items above were — worth weighing in a redesign, not asserted as confirmed fact here.

**Disposition (superseded 2026-09-09):** at the time this section was written, H-B sat in a
known-flawed, needs-redesign state. See "H-B redesign (2026-09-09)" immediately below for
what happened next — a full from-scratch redesign, not a same-day patch on this construction.

## H-B redesign (2026-09-09) — from-scratch, independent of the round-2 attempt

Round 2 left H-B needing a genuine redesign, not a fourth inline patch on the same flawed
structure. Per user direction, this was done properly: dispatched Fable (a separate model, via
the Claude Code Agent tool, isolated worktree) to design H-B **completely blind** — given the
economic hypothesis and both prior review rounds' findings, but deliberately NOT shown any
candidate replacement, so its design would be a genuinely independent second opinion rather
than a critique of one.

**Fable's design**, full detail in `docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md`:
traced round 2's bugs to one root cause — reading `bars_since_low_fast`/`bars_since_high_fast`'s
*runtime value* to infer both leg-length and extreme-type at once, when only their `== 0`
boolean was ever verified causal and correct. Its fix: a forward-scan state machine that only
ever reads the `== 0` flag, tracking a write-once "last confirmed extreme" anchor that cannot
drift onto a non-extreme bar, with the event set locked to an exact fixed offset
(`k == K_CONFIRM`) rather than an open-ended `k >= 1` range — this single change eliminates
the density explosion, the anchor-drift bug, the capitulation contamination, and the serial
correlation all at once, as a consequence of the same structural fix, not four separate
patches.

**Empirical verification, before trusting the design** (SPY/15m, 130,632 bars, live query):
confirmed genuine sparsity (6.9% of bars at `K_CONFIRM=3`, vs. round 2's ~70%), a real
27.1% leg-survival rate (not degenerate), negligible tie frequency (0.059%), and — a new
finding neither AGY nor Fable anticipated — real warmup contamination (13 of the first 20
bars in a symbol's history falsely register as fresh-extreme events before a full trailing
window accumulates). Fixed by excluding each symbol's first `2 * dist_window_fast` bars.

**AGY review round 3** (full review: `docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-agy-review-round3.md`):
conditional pass. Independently re-verified (not accepted on assertion) that the write-once
anchor invariant genuinely eliminates round 2's drift bug, and that included legs' averaging
windows are provably disjoint across legs — both confirmed by working through the logic
directly, not trusting the review's proof. Four amendments required, three locked into this
doc's construction spec above (tie hard-reset; a trailing SQL fetch buffer so the IS-window
clamp doesn't falsely reset anchor state at the boundary; a reported diurnal sub-panel, since
`volume_z` has no session-boundary detrending — verified against `feature_factory.py`, and
found to affect H-A too, not just H-B). The fourth — `Panel.sync_shift_null_p`'s per-symbol
date-shift not actually being calendar-synchronous when active-date counts vary across
symbols — is shared testing machinery reaching beyond this document; independently verified
against source and filed as todo 372 rather than patched inline, since it may also bear on
the already-closed `alpha_score_residual_single_security_15m.py` result (not claimed to
invalidate it — that needs its own check).

**Net result:** H-B's construction is done and twice-reviewed. It cannot run yet — blocked on
todo 372 (the null-shift gap) independent of compute headroom, same as H-A's own compute
block is independent of this.

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

**Not yet done:** no script written, no statistic computed for either hypothesis. Both
constructions are finalized and reviewed (H-A: two rounds; H-B: three, including a full
from-scratch redesign) — nothing left to design, only two independent blockers left to clear:
- **Compute:** the corpus `ic_engine` recompute is running, using ~20GB RSS + heavy CPU on a
  box that already OOM'd once this week (see
  `.planning/todos/pending/371-ic-engine-cross-sectional-cell-size-guard-post-materialization-ooms-at-universe-scale.md`,
  and as of 2026-09-08 18:11 UTC it also hit a clean `alpha.ic.max_cell_rows` failure on a
  different cell, unresolved as of this writing) — launching a second compute job now is
  exactly the contention this doc's own construction section cautioned against. Blocks both
  hypotheses equally.
- **The null-shift gap (todo 372):** `Panel.sync_shift_null_p` isn't actually
  calendar-synchronous across symbols with varying active-date counts — blocks trusting
  either hypothesis's Track 1 null test as specified, independent of compute. Needs its own
  fix and review, not a same-day patch, given it's shared infrastructure.
