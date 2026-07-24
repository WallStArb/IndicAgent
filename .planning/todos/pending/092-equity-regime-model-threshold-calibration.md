# 092 — Empirical threshold calibration for `equity_regime_model.py`'s vix/breadth cuts (todo 026's P3, split out)

**Status check 2026-07-14 (corpus-rebuild idle window):** this todo's target file is stale.
`equity_regime_model.py` was deprecated at Phase 144 (2026-07-12), superseded by
`services/cross_sectional_regime_model.py` (the generic multi-group dispatcher) — the corpus
pipeline's step-4 slot now runs the new file, and it already completed for the in-progress
143.1-07 rebuild. The underlying concern is still live: the same never-recalibrated
`[initial_estimate]` guesses exist under the new `alpha.equity_regime.*` namespace
(`vix_low_pct`/`vix_high_pct`/`breadth_bear`/`breadth_bull`, one description literally says "Same
calibration as alpha.regime.vix_low_pct"). Retarget this todo's title/body to
`cross_sectional_regime_model.py` / `alpha.equity_regime.*` before acting on it. Also note: this
run's Step 4 already wrote `market_regimes` using the current guessed cuts — writing a
recalibrated value now would desync from labels already on disk for this rebuild without
re-running Step 4, so (same as todo 065/097) any real work here waits for the next corpus cycle,
not this one.

**Source:** Split out of todo 026 (HMM Regime Audit & Optimization, moved to `deferred/`
2026-07-10 since most of its remaining scope — P1b/P2a/P2b/P2c — genuinely batches into Phase
144's `ic_engine` re-run). This one sub-item, P3, is pulled back out as its own standalone
`pending/` todo because it has fresh evidence making it urgent now, unlike the rest of 026.

**Priority:** medium-high — no longer just general hygiene; see the live-path finding below.
**Gate:** none. Runs against the current corpus today.

## What's open

`equity_regime_model.py`'s cut points (`alpha.regime.vix_low_pct`/`vix_high_pct` = 0.33/0.67,
`alpha.regime.breadth_bear`/`breadth_bull` = 0.40/0.60, migration 182) were moved into APR
(tunable) but are still sitting at their original guessed `[initial_estimate]` defaults — no
empirical recalibration has ever actually happened.

## Why this is now live-path relevant, not just hygiene

Todo 026's 2026-07-09 finding: a fresh corpus IC leaderboard review found the top of
`feature_ic_scores` by `|ic_value|` dominated by regime-conditional cells (`high_bear`,
`mid_bull`, etc.) at IC 0.15-0.42. Investigated as a possible HMM parameter-lookahead leak
(P4a) — ruled out (that leak exists in code but currently measures zero live rows; per-symbol
HMM is routed around entirely by the `equity_model_enabled` toggle, which defaults to the
cross-sectional VIX×breadth model this todo's cut points feed).

Two remaining explanations were identified, one of which is this todo:
1. FDR-tail concentration (survivorship bias inherent to "top IC" leaderboard framing — not a
   bug, expected ~48 false discoveries at `fdr_alpha=0.05` across 972 qualifying cells; matches
   the observed count exactly).
2. **These arbitrary, never-recalibrated cut points** — they don't inject look-ahead bias, but
   can produce regime buckets that don't correspond to behaviorally distinct states, adding
   noise that (combined with #1) plausibly concentrates extreme IC values at the tail.

Nothing here proves #2 is the dominant explanation, but it's evidence-flagged as a live-path
suspect now, not merely "would be nice to calibrate someday."

## Proposed approach

Same shape as EM-CAL (todo 065): treat the 4 cut points as a small calibration study against
the current corpus rather than accepting the guessed defaults further. Compare candidate cut
points (e.g. percentile-based on the trailing distribution vs the current fixed 0.33/0.40/0.60/
0.67) via regime-conditional IC separation on POOLED strata, same methodology already
established for other APR threshold calibrations in this codebase.

Full context/history: `.planning/todos/deferred/026-hmm-regime-audit-optimization.md`.

## Cheapest-first-check result (2026-07-20) -- population imbalance CONFIRMED, root cause isolated

Ran the population-balance half of the calibration study (pure read-only SQL over
`market_regimes.regime_label` + its `regime_prob_vector` JSONB, which stores the raw
`vix_pct`/`breadth_frac` signal values pre-bucketing -- no new corpus computation, no
overlap with the two other active sessions' work). Result is decisive on its own, before
even getting to the (still-open, more expensive) IC-separation half of this study:

**The 9 regime cells are severely imbalanced, consistently across all 4 tfs** -- `low_bull`
is 12-17x more populated than `low_bear` (5m: 16.6x, 15m: 14.5x, 1h: 12.2x, 1d: 13.9x), and
the full population rank-order is nearly identical across tfs (`low_bull` > `mid_bull` >
`high_bear` > `high_bull` > `mid_bear` > `{high_neutral, mid_neutral}` > `low_neutral` >
`low_bear`). Not a subtle artifact -- `low_bull` alone accounts for 28-31% of every tf's
bars; `low_bear` for under 2.5%.

**Root cause isolated to the breadth cut specifically, not VIX.** `vix_pct` is already a
causal percentile RANK in [0,1] (`breadth_vol.py`'s `_compute_vix_pct_rank`), so cutting at
0.33/0.67 is close to tertile-balanced by construction. `breadth_frac`, by contrast, is an
absolute fraction (share of symbols above their MA) cut at fixed 0.40/0.60 -- never checked
against its own empirical distribution. Measured directly:

| tf | mean breadth_frac | p25 | p50 (median) | p75 |
|---|---|---|---|---|
| 5m/15m/1h | 0.60-0.61 | 0.33 | **0.70** | 0.88 |
| 1d | 0.65 | 0.45 | **0.76** | 0.90 |

The median `breadth_frac` (0.70-0.76) sits well ABOVE the current "bull" cutoff of 0.60 --
more than half of all bars already classify as bull breadth before the regime logic even
runs. That's the entire mechanism: the fixed 0.40/0.60 guessed cuts were never calibrated
against this universe's actual breadth distribution, and the true distribution is heavily
right-skewed relative to them.

**Candidate population-balanced breadth cuts** (tertile split of the measured distribution,
mirroring what VIX already does): p33/p67 ≈ **0.49 / 0.83** for 5m/15m/1h, ≈ **0.59 / 0.86**
for 1d -- vs. today's fixed 0.40/0.60. A large shift, especially the upper cut.

**What this does NOT yet establish:** whether population-balancing the buckets actually
improves regime-conditional IC separation (the deeper question this todo originally posed),
or whether the current imbalance is economically real and harmless (calm+bullish genuinely
is more common than calm+bearish in this sample, so *some* imbalance is expected --
the open question is whether 12-17x is "expected market structure" or "cut points
mis-specified to the point of wasting statistical power in the rare cells"). That
comparison is the next real step and is corpus-scale work (needs the full
`_compute_cross_sectional_tf`-equivalent IC recomputation under both cut schemes) -- proper
next-session scope, not something to rush alongside two other active corpus-writing
sessions. This session's contribution is confirming the population-imbalance finding is
real and pinpointing its mechanism, which de-risks and focuses that next study
(test the 0.49/0.83-style tertile candidate specifically, not an open-ended search).

## FIXED (2026-07-24, same session as todo 179): causal-rank breadth signal, migration 257

User pushed on this directly ("how did we choose 9 regimes, what was the empirical proof for
60/40, fix it and rerun"). Root cause confirmed precisely: `vix_pct` was already a causal
expanding percentile rank (bisect-based, look-ahead-safe), so 0.33/0.67 was
population-balanced by construction; `breadth_frac` was a raw fraction cut at fixed 0.40/0.60,
never rank-transformed -- exactly the mechanism this todo already isolated.

**Fix, not a one-time number swap:** extracted the causal-rank bisect logic (already proven
correct for `vix_pct`) into a shared `_causal_expanding_rank()` helper in
`src/intelligence/regime_signals/breadth_vol.py`, applied it to `breadth_frac` too, and cut
both axes symmetrically at 0.33/0.67. This is self-calibrating by construction (permanently
population-balanced, not just at whatever snapshot a fixed replacement number was chosen
against) rather than replacing one guessed number (0.40/0.60) with another guessed number
(0.49/0.83). `PROB_KEYS` renamed `breadth_frac` -> `breadth_pct`. Migration 257 recalibrates
`alpha.equity_regime.breadth_bear`/`breadth_bull` defaults and records full provenance/blast-
radius in `config_schema`. TDD: 6 new/updated tests in
`tests/unit/test_regime_signals_breadth_vol.py`, full unit suite green.

**Verified the fix works as intended** (`scripts/analysis/recalibrated_breadth_regime_relabel_check.py`,
re-derives labels offline from already-stored raw signal values, no live `market_regimes`
write): max/min population ratio dropped from 13.8x to 7.1x (5m), 12.7x to 6.6x (15m), 12.2x
to 6.7x (1h), 13.9x to 6.0x (1d) -- roughly halved everywhere, previously-starved neutral
buckets now properly populated (5-9% -> 9-15%).

**Re-ran today's full regime x symbol_hmm x scale sweep under the recalibrated labels**
(`scripts/analysis/recalibrated_regime_full_sweep_check.py`, current OOS window, raw
forward_returns only): 8/180 cells pass (vs. 2/234 before recalibration) -- and critically,
5 of 8 cluster on `high_bear`, across both tf, multiple symbol_hmm sub-states, and multiple
scales, a materially more internally consistent pattern than the pre-recalibration
`low_bull` x `trending_down` finding (which had already been falsified by historical
replication -- see todo 179).

**Historical replication test on `high_bear`** (`scripts/analysis/high_bear_recalibrated_historical_replication_check.py`,
same 12-episode methodology as todo 179's replication check, raw returns only -- never
`ensemble_alpha`, circular against pre-OOS training data): **every genuine structural bear
market fails uniformly, at every scale, both tf** -- 2008 GFC, 2018 Q4 selloff, 2020 COVID
crash, 2022 rate-hike bear market all FAIL cleanly (24/24 cells, 2020 COVID strongly negative,
`ci_lower` down to -0.0135). **The two cleanest, most robust passes are both non-crisis
"dip within an uptrend" periods** -- 2016-2018 grind-up and 2020-2021 recovery both PASS at
every scale, both tf (12/12 cells). The remaining episodes (2009-11, 2012-14, 2015-16,
pre-COVID, 2022-25) are mixed. The current OOS window itself is mixed/weak (5m fails, 15m
barely passes at one scale).

**This is not noise -- pure noise doesn't sort itself by well-known historical bear-market
boundaries this cleanly.** `high_bear` (high vol + bear breadth) conflates two economically
opposite situations under one label: a transient volatility scare within an ongoing bull
market (mean-reversion/dip-buying works) versus a genuine structural trend reversal (buying
the dip is catching a falling knife). The recalibration fix is real and correct, and it
surfaced a genuinely interesting, economically coherent pattern -- but the current 9-cell
cross-sectional taxonomy is missing a dimension (something like regime persistence/duration,
or longer-horizon trend context) needed to distinguish these two cases. Not yet a clean,
tradeable finding; a well-motivated next research direction, not a dead end and not a
confirmed edge either.

**Recommended next step:** investigate whether adding a trend-context or regime-duration
dimension (e.g., how long has `high_bear` persisted, or where does price sit relative to a
longer-horizon MA) separates "buyable dip" from "structural bear" within the `high_bear`
label -- before building this into anything live. Raised with the user, not yet decided.
Live production `market_regimes` recompute (the real, multi-hour corpus operation this fix
implies for the canonical table, invalidating `feature_ic_scores`/`ensemble_weights`/
`ensemble_alpha`) has NOT been run -- only the offline, read-only re-derivation above.
