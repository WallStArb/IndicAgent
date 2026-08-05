# HMM Parameter-Lookahead Validation Pilot — SPY/1h (2026-08-03)

**What this answers:** todo 026's P4a decision gate, open since 2026-06-28 and never tested:
"Validate the practical impact first ... if the shift is negligible, the bias is small in
practice and this can be deprioritized; if IC materially changes, this must land before any
regime-stratified result is trusted." (`.planning/todos/completed/034-hmm-walk-forward-refit.md`,
folded into `.planning/todos/deferred/026-hmm-regime-audit-optimization.md`.)

**Script:** `scripts/analysis/hmm_regime_parameter_lookahead_pilot_spy_1h.py`

**Method:** two regime labelings of the same SPY/1h bars, both fully causal at decode time:

- **Approach A (production, unmodified):** `regime_writer.py`'s own `_compute_symbol_tf` called
  directly, real live APR hyperparameters. The `GaussianHMM`'s parameters (5 emission means, 5x5
  covariances, 5x5 transition matrix) are fit once on the entire 30,932-bar history.
- **Approach B (expanding-window periodic refit):** same hyperparameters and same production
  helper functions (`_build_obs_matrix`, `alpha_pass_jit`, `_smooth_states`, `_build_label_map`,
  `_stationary_distribution`, `_log_emit_full`), but the HMM is refit every ~1650 bars (~1 trading
  year) using only the training-slice prefix up to that point (2-year/3300-bar initial warmup),
  then decodes the next segment forward before refitting again. At any bar t, the model that
  labeled it was fit using only data through the most recent refit boundary <= t.

Both decode causally (forward alpha-pass only) — the difference under test is purely how much
future data the model's *parameters* were allowed to see, isolating exactly the channel todo 026
names.

## Result

Over 26,415 bars where both labelings and `forward_returns` overlap:

**Label agreement (A == B): 6,569 / 26,415 = 24.9%.** Chance-level agreement given each
labeling's own marginal regime distribution (`sum(p_a[i] * p_b[i])`) is **21.7%** — the two
labelings agree only ~3.2 percentage points more often than two independent random labelings with
the same class frequencies would. This is a much larger effect than expected going in (the prior
stated before running this test, based on the HMM's small parameter count relative to the data,
was "probably small" — that prior is now falsified by direct measurement, which is the entire
point of running the test rather than trusting the guess).

**Regime-stratified mean executable open-to-open forward return, A vs B:**

| Regime | A: N | A: mean_ret | B: N | B: mean_ret |
|---|---|---|---|---|
| ranging | 5833 | +0.000150 | 6354 | +0.000100 |
| transition_down | 5713 | +0.000037 | 4678 | +0.000084 |
| transition_up | 7102 | +0.000057 | 6186 | +0.000082 |
| trending_down | 2209 | -0.000062 | 2203 | **+0.000198** |
| trending_up | 5558 | +0.000042 | 6994 | **-0.000056** |

**Two of five regimes (`trending_down`, `trending_up`) flip sign between labelings.** Any
regime-stratified IC or return statistic computed on one labeling would not reproduce under the
other for those two regimes.

## Caveats (read before citing this as a final number)

1. **Single symbol, single tf (SPY/1h).** Magnitude may differ elsewhere; not yet tested at other
   symbols/tfs.
2. **Approach B resets its belief state at each refit boundary** (fresh stationary prior, not a
   carried-forward posterior from the prior segment's last bar) — a simplification that could add
   some spurious label churn right at the 17 refit boundaries. With ~1650 bars between boundaries
   this is unlikely to explain the full gap to chance-level agreement, but it is not ruled out as
   a partial contributor.
3. **Label semantics are rank-based within each fit** (`_build_label_map` assigns "trending_down"
   to whichever cluster has the lowest mean return *in that specific fit*, not against a fixed
   universal threshold) — this is production's own existing design, not a pilot-specific
   simplification, and it is itself part of why a differently-windowed fit produces a
   substantially different labeling: what counts as "trending" is relative to that fit's own
   sample, and the sample changes materially as the window expands or rolls.
4. **This does not, by itself, tell us which labeling (A or B) is "more correct"** — only that
   they disagree far more than expected. A is what production actually generates and is used for
   walk-forward-style live decisions; B is closer to what a genuinely walk-forward-consistent
   scheme would produce for training-time labels, but B's own boundary-reset simplification (2)
   means it is not itself production-quality.

## Verdict on todo 026's decision gate

**Todo 034's own pre-committed rule ("if IC materially changes, this must land before any
regime-stratified result is trusted") is triggered.** The shift is not negligible: near-chance
label agreement and two sign-flipped regime means is a material change by the standard the gate
itself set in advance. This does not mean the full P4a engineering fix (production rolling refit
across all ~80 symbols x 4 tfs) should be started immediately — that is still a real, expensive
project — but it does mean todo 026/P4a should move out of "deferred, gated, not started" and
into active scoping, and any regime-stratified result relying on `feature_vectors.regime` (the
per-symbol HMM axis specifically, not the cross-sectional `market_regimes` axis, which is
unaffected) should carry this caveat until it's resolved.
