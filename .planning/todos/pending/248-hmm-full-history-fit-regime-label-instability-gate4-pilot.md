---
status: pending
priority: P1
filed: 2026-08-03
source: todo 026's P4a decision gate ("validate the practical impact first"), open since
  2026-06-28 and never tested until today -- retired out of 026 into its own todo because 026 is
  a large, mostly-already-resolved 10-finding audit (P0/P1a/P1b/P2b/P2c/P3 done or forked to
  todos 108/092) and burying fresh, actionable evidence inside it would get lost; see 026 for the
  full historical audit trail, this todo is the live remainder
---

# Per-symbol HMM regime labels are highly sensitive to full-history-fit vs rolling-refit -- Gate 4 pilot (production-quality) needed before trusting regime-stratified results

## What

`regime_writer.py` fits each `(symbol, tf)` `GaussianHMM`'s parameters (5 emission means, 5x5
covariances, 5x5 transition matrix) once on the ENTIRE available history, then decodes every bar
causally (forward alpha-pass only -- the decode step itself does not see future data). This is
todo 026/034's long-tracked "parameter-level lookahead" concern: the *decode* is causal, but the
*model doing the decoding* was estimated with knowledge of the whole series, including bars far
in the future relative to any early timestamp.

Todo 026 set a 4-gate decision rule in 2026-06-28 for whether this is worth fixing, and gate 1
("validate the practical impact first") was never run. It was run today, cheaply, on one
symbol/tf, and the result is larger than the gate's own author expected.

## Evidence (2026-08-03)

`scripts/analysis/hmm_regime_parameter_lookahead_pilot_spy_1h.py` (full writeup:
`docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md`). SPY/1h, 26,415 comparable bars, two
labelings both causal at decode time:

- **Approach A** (production, unmodified `_compute_symbol_tf`): full-series parameter fit.
- **Approach B** (expanding-window periodic refit, same production helper functions): refit every
  ~1650 bars (~1 trading year) using only the training-slice prefix up to that point.

**Label agreement: 24.9%, barely above the 21.7% chance baseline given each labeling's own
marginal regime distribution.** Two of five regimes (`trending_down`, `trending_up`) flip sign in
mean executable open-to-open forward return between the two labelings.

This is direct evidence for todo 026's Gate 3 ("root cause analysis confirms parameter
look-ahead bias is the driver, not regime irrelevance") -- the shift is real and large. It is
**not** itself Gate 4 (a production-quality shadow-mode IC-improvement pilot, p<0.05, >=10%
improvement) -- read the pilot doc's caveats first: single symbol/tf, and Approach B resets its
belief state (fresh stationary prior) at each refit boundary rather than carrying forward the
previous segment's posterior, a simplification not present in a real rolling-refit design.

## Broadened pilot results (2026-08-03, same day, option 1 of "Next step" below)

Ran the same methodology at TLT/1h (different asset class) and SPY/15m (different tf, ~4x the
bar density of 1h). Chance-level agreement computed the same way as the SPY/1h writeup
(`sum(p_a[i] * p_b[i])` over each run's own marginals):

| Symbol/tf | Observed agreement | Chance baseline | Points above chance | Sign flips (of 5 regimes) |
|---|---|---|---|---|
| SPY/1h | 24.9% | 21.7% | +3.2 | 2 |
| TLT/1h | 31.0% | 20.6% | +10.4 | 0 (magnitudes shift, no flip) |
| SPY/15m | 56.8% | 22.1% | **+34.8** | 0 |

**Not a uniform "regime labels are unreliable" finding -- it tracks bar density.** SPY/15m is far
more stable than SPY/1h for the identical symbol and identical refit-cadence design (both use the
same "~1 trading year, ~2 year warmup" schedule, just scaled 4x in bar count for 15m's higher
density). The mechanism is almost certainly effective sample size per refit window: 15m's ~1650*4
bars/year gives each periodic fit far more observations to converge on than 1h's ~1650, so
parameter estimates are less sensitive to exactly which window they were estimated on. This
sharpens the diagnosis considerably -- the actionable variable is "bars per refit window," not an
unexplained instability, and it argues for a tf-calibrated fix (1h needs this the most; 15m may
already be adequately stable under a reasonable refit schedule) rather than a uniform one.

## Fix design (2026-08-03, before implementation -- Renaissance-methodology framing)

Option 1 of "Next step" below is now done (see "Broadened pilot results" above). This section is
the design for option 2, the actual fix, written down before coding it.

**1. Causality is the actual bug, not a judgment call.** Every other producer in this codebase
already enforces "a fact computed at bar t may only use data <= t" (`docs/research/platform-canonical-simulator.md`'s
per-producer causal-construction laws: Feature Factory's causal transforms, `_causal_decode`'s
forward-filter, `equity_regime_model`'s causal expanding rank). `regime_writer.py`'s batch
full-history HMM fit is the one place that law is violated -- the decode step is clean, the model
doing the deciding is not. Walk-forward parameter estimation, no exceptions, is the fix; this is
not a tunable tradeoff.

**2. Calibrate the fix to what the data actually needs -- tf-scaled, not uniform.** The broadened
pilot's sharpened diagnosis (effective sample size per refit window, not a blanket "regime labels
are unreliable") means 1h needs this urgently and 15m may already be adequately stable under a
reasonable schedule. Scale the refit window by bars-needed-to-converge per tf, matching how this
codebase already gradient-scales embargo/lookahead by tf density elsewhere (`return_fast/mid/slow`,
the per-tf lookahead grid) -- not a fixed bar-count or calendar-time cadence applied identically
across 5m/15m/1h/1d. Don't rebuild uniformly across every timeframe; that's unjustified
acceleration per this project's own 5-step mandate.

**3. Carry the belief state across refit boundaries, not reset it.** The pilot's Approach B resets
to a fresh stationary prior at each refit -- a simplification acceptable for a cheap validation
pilot, not acceptable in the real fix, since resetting manufactures extra instability right at
boundaries that a production version must not have.

**4. Prefer the continuous posterior over the discrete label wherever a downstream consumer can
use it.** `p_up`/`p_ranging`/`p_down`/entropy are already computed at every bar
(`_alpha_pass_jit`'s alpha_history). A hard 5-way label discards that and gets treated as ground
truth downstream -- discretizing an inherently uncertain estimate and then trusting the
discretization is part of the failure mode. Never drop information a consumer could use directly,
per this project's "never drop data that could contain signal" principle.

**5. Prove it before shipping it -- the actual Simons discipline.** Don't re-architect
`regime_writer.py` in production on the strength of the pilot alone. Build the walk-forward
version with belief continuity (item 3) and tf-calibrated windows (item 2), run it in shadow mode
against real `feature_ic_scores`, bootstrap CI + BH-FDR -- the same bar as every other result in
this corpus. Point it at 1h first, given tonight's evidence says that's where the payoff is; 15m's
case for the fix is much weaker and shouldn't be assumed without its own measurement.

## Core mechanism implemented and unit-tested (2026-08-03, via `superpowers:systematic-debugging`
+ `superpowers:test-driven-development`)

`_walk_forward_hmm_labels()` and `_seed_prior_from_label()` landed in `services/regime_writer.py`,
right after `_build_label_map()`. Fixes items 1 and 3 of the fix design above (causal parameter
estimation; belief-state continuity across refit boundaries via the previous segment's own
ending label, mapped through the new model's own `_build_label_map` -- not a fresh stationary
prior, and not raw state-index carryover, which isn't meaningful across independently-fit
models). TDD red-green: 4 new tests in `tests/unit/services/test_regime_writer.py`
(`test_seed_prior_from_label_is_one_hot_on_matching_state`,
`test_seed_prior_from_label_falls_back_when_label_absent`,
`test_walk_forward_hmm_labels_unaffected_by_future_data` -- the causality property itself,
verified the same way `test_causal_decode_uses_only_past_observations` verifies the decode
step: truncating future data must not change past labels --
`test_walk_forward_hmm_labels_second_segment_seeded_from_first_segments_ending_label`), all
confirmed failing (ImportError) before implementation, all passing after. Full `tests/unit/`
suite green (0 regressions), ruff/black clean.

**Not wired into `_compute_symbol_tf` or the live `--refit` path.** Per the fix design's item 5
("prove it before shipping it"), this is deliberate -- the function exists and is correct, but
production still calls the full-history fit until the Gate 4 shadow-mode measurement below
actually runs and clears its pre-registered bar. Do not wire this into production ahead of that.

**Remaining scope, item 2 of the fix design (tf-calibrated cadence) and the Gate 4 pilot itself:**

1. **tf-calibrated `refit_every_bars`/`initial_warmup_bars`** -- the function takes these as
   parameters (not hardcoded), but no caller has picked real per-tf values yet. Should scale by
   bar density the same way the pilot scripts did (1650 bars/year at 1h, x4 at 15m, x12 at 5m),
   not a fixed schedule applied uniformly.
2. **Seed-stability check** (todo 026's bundled ask, not yet built): fit 3-5 seeds per refit
   segment, compare log-likelihood spread and label agreement across seeds.
3. **Run the real Gate 4 pilot**: `_walk_forward_hmm_labels()` in shadow mode against real
   `feature_ic_scores`, bootstrap CI + BH-FDR, measure whether regime-stratified IC actually
   improves by the pre-registered >=10% / p<0.05 bar. Point at 1h first (tonight's evidence says
   that's where the payoff is). This is the gate that, if cleared, authorizes wiring the fix into
   production (P4a/P4b in todo 026).

## Gate 4 pilot result, SPY/1h (2026-08-03) -- FAIL

`scripts/analysis/hmm_walk_forward_gate4_ic_pilot_spy_1h.py`. Item 1's tf-calibration for 1h
(refit_every_bars=1650, initial_warmup_bars=3300) reused directly from the instability pilot.
Item 2 (seed-stability check) is built and unit-tested but not yet invoked in this run -- not
load-bearing for the verdict below, since the verdict came from the IC comparison itself, not
from a convergence-instability artifact.

**Design:** each of `_build_label_map`'s 5 labels has a natural order (trending_down <
transition_down < ranging < transition_up < trending_up), mapped to an ordinal score
{-2,-1,0,1,2}. This turns "does the regime label predict returns" into one Spearman IC,
comparable via the same paired circular-block-bootstrap machinery this session used for the CTF
pilots (`_nonlinear_interaction_combiner_shared.py`'s `bootstrap_ic_stats`/
`paired_bootstrap_ic_difference`).

**Result, n=26,415 bars:**

| | point_ic | CI | passes own CI |
|---|---|---|---|
| Production (`feature_vectors.regime`) | -0.0041 | [-0.0173, 0.0081] | No -- crosses zero |
| Walk-forward (`_walk_forward_hmm_labels`) | -0.0171 | [-0.0295, -0.0054] | Yes, but **wrong sign** |
| Paired diff (wf - prod) | -0.0130 | [-0.0276, 0.0013] | Crosses zero -- not significant |

**Neither labeling shows genuine positive predictive power as a standalone ordinal score, and
the walk-forward version is not better -- if anything it's more clearly (negatively) different
from zero. Gate 4 FAILS at SPY/1h on this test.** Do not wire the walk-forward fix into
production on the strength of tonight's work. The instability finding (todo 248's main body,
25-57% label agreement depending on tf) is still real and still worth fixing on causality
grounds alone -- but "the labels disagree a lot" and "fixing the disagreement improves
predictive power" are different claims, and only the first is established.

**Real caveat on this specific test's scope, not a reason to discount the FAIL:** this pilot
tests whether the regime label ITSELF directly predicts returns (an ordinal IC). That is a
stricter, more direct test than todo 026's original Gate 4 ask, which was about whether
OTHER FEATURES' regime-*stratified* IC (e.g. a momentum feature's IC computed separately within
each regime bucket, `feature_ic_scores`' actual methodology) improves under walk-forward labels
-- production doesn't use `feature_vectors.regime` as a standalone predictor anywhere; it's a
conditioning/stratification variable. A feature could still show a real regime-stratified IC gap
even if the regime label has no direct ordinal IC of its own. **This pilot is evidence, not the
final word** -- the corpus-wide, per-feature-stratified version of Gate 4 (todo 026's original,
literal ask) has still never been run. Whether that's worth the cost given tonight's negative
first read is a real prioritization call, not an automatic next step.

## Decision correction (2026-08-04) -- fix ships regardless of the Gate 4 pilot's result

The Gate 4 FAIL above tested whether the regime label directly predicts returns as a standalone
ordinal score. That is NOT the bar for whether to fix the underlying bug. `regime_writer.py`'s
full-history HMM parameter fit is a confirmed causal-law violation -- the one producer in the
codebase that doesn't enforce "a fact computed at bar t may only use data <= t"
(`docs/research/platform-canonical-simulator.md`'s per-producer causal-construction laws). This
project's "earn promotion through proof" principle governs promoting NEW, unproven alpha/signals
to production -- it does not gate whether to repair an already-confirmed correctness bug in an
existing, central mechanism. HMM regimes themselves are not in question (Renaissance-methodology
core concept); this is a bug in one implementation detail of that mechanism.

**Verdict: wire `_walk_forward_hmm_labels()` into `_compute_symbol_tf`'s live path regardless of
the Gate 4 ordinal-IC pilot's negative result.** The pilot's actual value is measuring the fix's
downstream blast radius (which numbers move, how much) and catching regressions -- not
authorizing or blocking the fix itself. Remaining work before this can ship, given the mechanism
does not yet have real per-tf values:

1. Pick tf-calibrated `refit_every_bars`/`initial_warmup_bars` for all 4 tfs (1h's values --
   refit_every_bars=1650, initial_warmup_bars=3300 -- came from the pilot; 15m/5m need the same
   "~1 trading year refit / ~2 year warmup" schedule scaled by bar density (x4 at 15m, x12 at
   5m, matching the broadened-pilot table above); 1d needs its own value, not yet estimated
   (~252 bars/year at daily density).
2. Wire `_walk_forward_hmm_labels()` into `_compute_symbol_tf` (or a parallel code path selected
   by an APR flag) as the live labeling mechanism, replacing the full-history fit.
3. This changes `feature_vectors.regime` for every historical bar at every (symbol, tf) --
   equivalent in blast radius to an `HMM_RANDOM_STATE` change per CLAUDE.md's Key Decisions:
   requires a full regime recompute (`regime_writer.py --refit`) and, because `feature_ic_scores`
   stratifies by regime, a downstream `ic_engine` re-run to keep regime-stratified IC numbers
   consistent with the new labels.
4. Given that blast radius and that a large corpus recompute (Tier -1 in STATE.md) is already
   queued behind the CTF-leak/Phase 167 re-verification work, this is a genuine sequencing
   decision, not an automatic next step -- scope as its own phase via `/gsd-discuss-phase` rather
   than executing ad hoc, so the tf-calibration design (item 1) and the recompute's interaction
   with the in-flight CTF work get real planning attention.

## Cross-refs

- `.planning/todos/deferred/026-hmm-regime-audit-optimization.md` -- full historical audit (10
  original findings), P4a/P4b's original decision-gate text, the seed-stability check ask. This
  todo is that gate's live remainder, not a replacement for the audit trail.
- `.planning/todos/completed/034-hmm-walk-forward-refit.md` -- superseded into 026, original
  framing of the bias and why it matters ("every regime-stratified IC number downstream inherits
  this bias").
- `docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md` -- full pilot results and caveats.
- Only `feature_vectors.regime` (per-symbol HMM axis, written by `regime_writer.py`) is affected.
  `market_regimes`/`regime_group` (cross-sectional axis, causal expanding-rank construction) is a
  separate, unaffected mechanism -- see CLAUDE.md's Dual Regime System note.
