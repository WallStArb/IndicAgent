# Extreme-Volume Divergence / Confirmed-Reversal — Pre-registration (DRAFT, not yet run)

**Status:** Draft pre-registration. No script written, no statistic computed.
**Author:** Claude (Sonnet 5), interactive session, 2026-09-06.
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
reported, and (if either reaches Track 2) regime-encoded independently. Conflating them
into one signed statistic would hide which mechanism, if either, actually carries signal.

- **H-A, "divergence" (leading/contrarian):** a fresh N-bar extreme made on LIGHT volume
  warns of an impending reversal against the extreme — light volume on a new low warns of
  upside reversal; light volume on a new high warns of downside reversal.
- **H-B, "confirmation" (coincident):** heavy volume on the leg moving AWAY from a recent
  extreme confirms the reversal is real and already underway — a heavy-volume bounce off a
  low is bullish-confirming; a heavy-volume pullback from a high is bearish-confirming.

## Construction spec — built entirely from existing `feature_vectors` columns

No new `feature_factory.py` column, no new pipeline feature, no corpus recompute needed.
Both constructions are read-only derivations over columns already persisted for the full
corpus, so this can run as a standalone analysis script (same posture as
`range_pct_fast_xs_ls_h5_falsification.py` / `alpha_score_residual_single_security_15m.py`)
whenever compute is available — it does not depend on any other program's sequencing.
(Practical note, not a design constraint: hold off running anything compute-heavy while
the current `ic_engine` corpus recompute is still using 12 worker processes — resource
contention, not a program-sequencing issue.)

- **`extreme_proximity_t`**: +1 if `bars_since_low_fast_t == 0` (bar t is itself a fresh
  rolling low over the existing `dist_window_fast` window, APR-governed, no new tunable),
  −1 if `bars_since_high_fast_t == 0`, else 0 (bar t is not at an extreme — excluded from
  H-A's panel).
- **H-A statistic, `extreme_volume_divergence_t`** (defined only where
  `extreme_proximity_t != 0`): `−extreme_proximity_t × volume_z_t`, using the persisted
  `volume_z` column. Positive = light volume at a fresh low (bullish-reversal warning) or
  the equivalent light-volume-at-a-high case (bearish-reversal warning) — the statistic's
  sign convention is fixed here and not re-derived from the data. Forward return measured
  from bar t (the extreme bar itself), same `return_type='executable_open_to_open'` /
  `forward_returns` convention as every other construction in this codebase (Invariant 1).
- **H-B statistic, `confirmed_reversal_t`**: reuses the existing `swing_volume_confirmation`
  column (mean volume over the current swing leg ÷ window mean) directly — no new
  computation — signed by the leg's direction (`struct_accel_bias`'s already-computed
  high/low comparison, or the simpler `close_t − close_{leg start}` sign, to be fixed
  before running, not decided ad hoc mid-script). Positive = up-leg with
  `swing_volume_confirmation > 1` immediately following a low (bullish-confirming);
  negative = down-leg with `swing_volume_confirmation > 1` immediately following a high
  (bearish-confirming). Defined only on bars inside a leg that started at a fresh extreme
  (same `bars_since_low_fast`/`bars_since_high_fast` gating as H-A, offset by the leg's
  start).
- **Wick corroboration (reported, not gated in either primary statistic):**
  `lower_wick_ratio_t` at H-A/H-B low-side events, `upper_wick_ratio_t` at high-side
  events — the "wick size/bar characteristic" half of the user's original framing, kept
  out of the primary gated statistic to avoid a second undeclared researcher degree of
  freedom (which wick threshold, what combination rule) that would need its own
  justification. If either H-A or H-B passes, a wick-conditioned successor is the natural
  next pre-registration, not a same-run addition.

## Track 1 — signal existence (continuous statistic)

Single-security IC test, reusing this project's standard statistical machinery (not
reinvented per construction):

- Primary statistic: within-symbol Spearman IC of the construction against
  `forward_returns.return_fast` (1-bar) AND `return_mid` (this codebase's existing
  APR-governed lookahead bands), reported per band — H-A and H-B fire on sparse,
  irregularly-spaced events (only at/near extremes), so a fixed short lookahead is the
  right first test.
- Bootstrap: day-clustered / date-block, reusing `_circular_block_bootstrap_ic`.
- Null: whole-date circular shift, reusing `_circular_shift_null` / the
  panel-synchronous date-shift null pattern already hardened for a prior single-security
  diagnostic on this codebase — same event-sparsity concern applies here (H-A/H-B are much
  sparser than an every-bar signal, so the minimum-events-per-symbol floor needs its own
  calibration, not a borrowed number).
- FDR: BH across symbols (reported) and BY across symbols (gated), matching this
  codebase's precedent for a construction with per-bar cross-sectional dependence.
- Cross-sectional arm (reported, not primary): does ranking symbols by
  `extreme_volume_divergence`/`confirmed_reversal` at the same bar carry a long-short
  spread — secondary, since H-A/H-B are framed as single-security timing signals first.

**PASS rule (Track 1, either H-A or H-B independently) — pure statistical existence, no
economic/cost gate:**

1. Bootstrap ci_lower > 0 (the effect is not noise).
2. Date-shift null p < 0.05 (the effect is not an artifact of the null construction).
3. Stability: same-sign point estimate in 3/3 equal temporal subperiods (not a one-era
   artifact).
4. Qualifying fraction of symbols individually significant at BY-FDR α=0.05, positive
   direction — floor to be set from this codebase's established precedent range (10% has
   been used before; adjust only if the sparse-event minimum-observations floor forces a
   different number, and say so explicitly if it does).

Reported, never gated: per-regime table, per-symbol BH table (less conservative
comparison point), negative-qualifier count, raw (non-divergence-adjusted) arm for
comparison.

## Track 2 — regime candidate

This project's standing rule applies without exception: **any regime candidate must clear
a null-arm (scrambled-data) control before it is trusted**, and a closely adjacent
volume-price statistic (rolling corr(|return|, rel_volume)) was already found to have HMM
identifiability move in the OPPOSITE direction from signal quality as the window
strengthened — the exact failure mode that got it rejected as a regime axis (todo 281).
Track 2 tests for that failure mode explicitly rather than discovering it after the fact:

1. **Identifiability-vs-signal curve:** fit the discretization (HMM or `build_tiers()`
   deterministic quantile tiering — tried FIRST, since it carries no EM/seed/local-optima
   identifiability question by construction) at 3+ event-density thresholds (how close to
   the extreme counts as "at" it) and report both signal fraction (adjacent-disjoint-window
   correlation, the same diagnostic used for the rejected volume-price candidate) and
   identifiability side by side. If identifiability falls as signal strengthens across
   these thresholds, Track 2 is DEAD on that shape alone, regardless of what Track 1
   found — check this first, since it is cheaper to falsify than the null-arm control.
2. **Null-arm control:** scrambled-data control (shuffle the volume series independent of
   price, or shuffle bar order within a matched-length synthetic series) — the discretized
   regime must not be recoverable from noise at the same rate as from real data.
3. **IC separation across buckets:** does IC actually differ across the statistic's own
   quantile buckets, not assumed from Track 1's continuous-signal result alone.

**Do not** build `regime_extreme_volume_divergence` or `regime_confirmed_reversal` as an
HMM `regime_*` column under any circumstance — if Track 2's three checks all pass, the
discrete cut is deterministic quantile tiering via `build_tiers()`, never HMM, per the
already-adjudicated reasoning for the closely related rejected candidate (identifiability
by construction, no EM). If Track 1 fails outright, Track 2 does not run — a construction
with no continuous-signal content has no basis for a regime encoding either.

## Fixed quantities (draft — to be locked before running)

`dist_window_fast` per its current APR value (not re-derived) · lookahead = `return_fast`
and `return_mid` (both reported) · B=2000 · N_null=1000 (this codebase's established
defaults; adjust only with a stated reason) · BY/BH alpha=0.05 · seed via
`hash_key_to_int("extreme_volume_divergence…")` / `hash_key_to_int("confirmed_reversal…")`.

## Open items before this can run

1. **AGY adversarial review** of this design, matching house practice for prior
   pre-registrations in this codebase — requested 2026-09-08, in flight.
2. **Minimum-events-per-symbol floor** — live calibration run 2026-09-08 against
   `feature_vectors` (`bars_since_low_fast = 0 OR bars_since_high_fast = 0`, cheap SQL
   aggregation, no bootstrap): extreme-bar fraction is **26-30% of all bars at every tf**
   (5m: 21.6M/73.2M; 15m: 6.6M/25.3M; 1h: 1.77M/6.88M; 1d: 252K/956K; all 231 symbols
   present at every tf). This corrects this doc's own framing above ("H-A/H-B fire on
   sparse, irregularly-spaced events") — at `dist_window_fast=20` a fresh 20-bar extreme is
   roughly 3x denser than the ~10% naive random-walk baseline (autocorrelated/trending
   price action inflates fresh-extreme frequency), not sparse in absolute terms. Per-symbol
   floor is a non-issue at this density: even at 1d, the sparsest tf, mean events/symbol is
   ~1092 (252,310 / 231) — comfortably above any BY-FDR per-symbol floor this codebase has
   used. No minimum-events gate needed; drop this as an open item.
3. **Leg-direction sign convention** for H-B — **locked 2026-09-08: close-to-close
   (`close_t − close_{leg start}`), not `struct_accel_bias`.** Rationale: `struct_accel_bias`
   is a composite feature with its own untested-in-this-context assumptions; the simpler
   sign is directly auditable against the stated economic hypothesis (an up-leg is up-leg
   because price closed higher, full stop) and avoids importing a second construction's
   assumptions into this one's PASS/FAIL result. Revisit only if AGY's review or Track 1
   results suggest `struct_accel_bias` materially changes leg segmentation.
4. **Event-density threshold(s)** for Track 2's identifiability curve — given finding (2)
   above, thresholds should be framed as "how many bars since the extreme still counts as
   at it" (e.g. 0, 1-2, 3-5 bars) rather than a sparsity cutoff — proposed 0 / ≤2 / ≤5,
   still to be confirmed against AGY's review before Track 2 runs (Track 2 is gated on
   Track 1 passing first regardless).

**Not yet done:** no script written, no statistic computed. Track 1 execution deliberately
held as of 2026-09-08 — the corpus `ic_engine` recompute is mid-run using ~20GB RSS + heavy
CPU on a box that OOM'd once already this week (see
`.planning/todos/pending/371-ic-engine-cross-sectional-cell-size-guard-post-materialization-ooms-at-universe-scale.md`);
launching a second compute job now is exactly the contention this doc's own construction
section already cautioned against. Write + run Track 1 once AGY's review lands and the
recompute clears (or once there's confirmed headroom, whichever first).
