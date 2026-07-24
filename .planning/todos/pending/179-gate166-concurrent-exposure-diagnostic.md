---
status: pending
priority: P1
filed: 2026-07-23
source: Ad hoc diagnostic run against Phase 166's already-materialized gate166_scalar OOS
  population, prompted by a strategic review of "are we generating real, tradeable alpha."
  Read-only; no gate re-run, no config/DB writes, no live capital risk.
gate: none -- this is itself the gate/measurement work, not gated by anything
---

# Gate166's catastrophic max-drawdown may be a portfolio-concentration artifact, not proof of no edge -- needs a proper correlation-aware re-score

## Context

Phase 166 scored two candidates through `gate166_frame_recalibration_eval.py` against the
frozen `143.1-08-champion` OOS population (28,100-33,892 closed primary frames, 2025-12-24
onward). Both failed decisively on c4 (max drawdown ratio): baseline `9.60` and scalar (retuned
stop/target) `26.18`, both vs. a `0.25` ceiling -- see `gate_evaluations` rows
`gate166_baseline`/`gate166_scalar` and `docs/plans/2026-07-23-phase166-frame-recalibration-verdict.md`.

**c4 is computed by summing `counterfactual_pnl_r` (a full 1R-equivalent risk contribution)
across every frame sharing the same `bar_ts`** (`_aggregate_pnl_by_bar_ts`, correct and
deliberate for handling genuinely-simultaneous positions -- see that function's docstring) --
but nothing caps how many simultaneous positions get summed, or divides risk across them. The
OOS champion population fires on average ~22 concurrent positions per bar (median 5, p90 68,
max 89), ~99.5% of them the same direction (long). Summing full-R contributions across dozens
of highly-correlated same-direction bets manufactures large swings in the aggregated equity
curve regardless of whether any individual trade's edge is good or bad.

**Empirical test run this session** (scratchpad script, reused `frame_gate_passes`/
`_max_drawdown`/`_annualized_sharpe` verbatim, no reimplementation), against the currently-live
`gate166_scalar` population (28,100 rows, confirmed exact reproduction of the recorded
c2/c3/c4 before testing variants):

| Variant | c2 (mean CI lower) | c3 (Sharpe) | c4 (max DD ratio) |
|---|---|---|---|
| A: as-scored (no change) | -0.0450 | 0.441 | 26.18 |
| B: risk-scaled 1/N_concurrent | -0.0079 | **1.96** | 15.79 |
| C: risk-scaled 1/sqrt(N_concurrent) | -0.0130 | 1.64 | 17.30 |
| D: hard cap top-5/top-10 by \|alpha_score\| | -0.07 to -0.08 | negative | 13-14 |

Dividing each frame's R contribution by how many positions were open at that instant (B) --
zero change to stop/target/hold logic, zero change to which trades fire -- nearly **quadruples
Sharpe (0.44 -> 1.96, well past the 0.5 threshold)** and **cuts the drawdown ratio by ~40%**
(26.18 -> 15.79), using the exact same trades. Hard-capping to the top-K highest-conviction
concurrent signals (D) does NOT help and makes Sharpe negative -- the highest-|alpha_score|
subset is not obviously the safer one.

**Honest caveat, not glossed over:** even the best variant tested (B) still fails c4 by a wide
margin (15.79 vs 0.25 -- naive 1/N splitting is not remotely sufficient on its own) and c2's CI
lower bound stays negative in every variant. This is not "problem solved." It is evidence that
concentration/correlation risk is a first-order, previously unmeasured contributor to Gate 2's
FAIL -- large enough that Phase 166's entire investigation (both candidates tuned stop/target
*distance*, never touched concurrent-exposure sizing) may have been optimizing the wrong layer.

**Why this isn't the same population Phase 166 recorded as `gate166_baseline`:** per Phase
166's own disclosed deviation, the baseline arm's `alpha_frames` rows were overwritten by the
scalar arm's regeneration cycle and never restored -- the live table currently holds the scalar
candidate's frames (confirmed via exact reproduction of `gate166_scalar`'s recorded numbers).
The concurrency structure (which symbols fire simultaneously, how many, what direction) is
driven by `alpha_score`/ensemble firing patterns, not by stop/target geometry -- so the same
correction should transfer to the baseline and (once scoreable) structural arms too, but this
has not been verified on those exact populations.

## Follow-up sweep (same session, same population): the strong-form hypothesis is FALSIFIED

Swept a portfolio-level simultaneous risk-budget cap B (at each bar_ts, if N_concurrent <= B
every frame keeps full R; if N_concurrent > B, all frames at that bar_ts scale down by B/N so
total simultaneous risk never exceeds B*1R -- nests "no cap" and "naive 1/N" as endpoints) across
B in {1,2,3,5,8,12,22,inf}:

| Budget | c2 CI lower | c3 Sharpe | c4 max DD |
|---|---|---|---|
| 1 | -0.0079 | 1.960 PASS | 15.79 fail |
| 2 | -0.0181 | 1.394 PASS | 16.86 fail |
| 3 | -0.0167 | 1.535 PASS | 13.93 fail |
| **5 (best c4)** | -0.0159 | 1.622 PASS | **11.13** fail |
| 8 | -0.0190 | 1.473 PASS | 11.61 fail |
| 12 | -0.0234 | 1.256 PASS | 14.87 fail |
| 22 (mean conc.) | -0.0266 | 1.122 PASS | 16.01 fail |
| inf (as-scored) | -0.0450 | 0.441 fail | 26.18 fail |

**c3 (Sharpe) passes robustly and consistently at every budget level tested (1.1-2.0, all
comfortably above the 0.5 threshold)** -- concentration-aware sizing reliably triples-to-
quadruples risk-adjusted return. **But c4 (max drawdown ratio) never gets below ~11 (best at
budget=5), nowhere near the 0.25 threshold, and is NOT monotonic in the cap** -- tightening the
cap past ~5 makes it worse again, not better.

**Why:** capping concurrent exposure only helps when the loss is concentrated in isolated
high-concurrency bars. If instead the deep troughs come from EXTENDED, autocorrelated losing
stretches (many consecutive bars all losing, which also happen to have above-average
concurrency because they fall in a losing regime), no per-bar concurrency cap fixes that --
you're still summing losses across many correlated bars in a row, just each bar's loss is
individually smaller. The regime/direction breakdown supports this: the champion OOS
population is ~99.5% long, and the two loss-driving buckets are `mid_bull` (-0.084 avg) and
`mid_neutral` (-0.100 avg) -- i.e. the strategy loses money specifically while long during
"bull"/"neutral"-labeled regimes, which is either a regime-mislabeling data-quality issue or a
genuine signal/direction mismatch (the ensemble may need to flip short or flat in these
regimes, not just resize). This rhymes with the already-open sign-symmetric ensemble question
(143.1-08's HOLD verdict) and todo 147's regime-divergence finding -- worth investigating
together rather than as a pure sizing problem.

**Revised conclusion:** concentration-aware sizing is real, cheap, and worth keeping (it triples
Sharpe for free) but is NOT sufficient to clear Gate 2 alone. The deeper lever is
regime-conditional direction/exposure (why does a long-biased ensemble lose specifically in
`mid_bull`/`mid_neutral`?), not position sizing in isolation. Don't re-run Phase 166's
stop/target-tuning playbook a third time -- investigate regime-conditional sign/exposure next
(ties into the sign-symmetric ensemble weighting question and todo 147).

## Correction (same session): single-symbol test shows this is NOT primarily a basket problem

User pushback (correctly): shouldn't a signal be judged on its own merit, standalone, before
ever discussing a basket? Tested directly -- pulled 3 individual symbols (XLE, PPLT, XOP, all
`15m`, ~350 frames each) from the SAME champion OOS population, computed each symbol's OWN
standalone equity curve (its own trades only, sequential in time, ZERO aggregation with any
other symbol -- no basket, no concurrency, no portfolio math at all):

| Symbol | All-regime Sharpe | All-regime mean R | `mid_bull` mean R (n) |
|---|---|---|---|
| XLE | -3.50 | -0.043 | **-0.385 (n=21)** |
| PPLT | -5.56 | -0.028 | **-0.191 (n=17)** |
| XOP | -2.79 | -0.053 | **-0.848 (n=17)** |

Every single symbol, in complete isolation, already shows negative Sharpe overall and
catastrophic per-trade losses specifically in `mid_bull` (losing 19-85% of a full R per trade on
average) -- with zero basket, zero concentration, zero portfolio construction involved. `XOP` in
`high_neutral` alone is actually Sharpe +2.65 -- so the per-symbol edge is regime-conditional,
not uniformly bad.

**This means the concentration/risk-budget finding above, while real and still worth keeping
(free Sharpe improvement, no reason to discard it), was NOT the main story.** It was partly an
artifact of `high_neutral` being ~66% of the pooled sample and diluting `mid_bull`'s damage when
aggregated. The actual bug is visible at the cleanest possible resolution -- one signal, one
symbol, one regime, no aggregation whatsoever: **this ensemble is directionally wrong in
`mid_bull` at the individual-trade level.** Gate 1's pooled rank-IC (which passed) cannot see
this -- a signal can have real positive cross-sectional IC while still being sign-backwards in
one regime bucket; that only shows up once you simulate actual directional trades (Gate 2),
which is why Gate 2 has to exist even though signal-level validation (Gate 1) already happened
independently per the project's normal weight-earning process.

**Revised priority:** skip further basket/sizing work as the primary lever (still fine as a
free secondary improvement). Go straight to regime-conditional direction: check `mid_bull`
regime-label quality first (cheap), then test whether flipping/zeroing exposure specifically in
`mid_bull` (and checking `mid_neutral` similarly) fixes each symbol's own standalone curve
before ever re-introducing basket effects. This is a single-symbol, single-regime experiment --
no portfolio math needed to answer it.

## Regime-label asset-class-mismatch hypothesis: checked, FALSIFIED

Natural next hypothesis for "why mid_bull": `cross_sectional_regime_model.py`'s commodity
regime groups (`commodity_energy`, `commodity_metals`) are coded but `"enabled": False` (own
file, lines 105/112/119), and `ensemble_trainer.py` (line 887 comment, verbatim) admits it is
"not yet regime_group-aware" and hardcodes `JOIN market_regimes mr ON mr.regime_group = 'equity'
... ` with NO symbol/tag condition -- meaning every symbol, including commodity/energy-tagged
names like XLE/XOP/PPLT (confirmed via `instrument_tags`: `commodity_energy_crude`,
`commodity_metals_precious`, no `eq_*` tag), gets stamped with a regime computed purely from
broad EQUITY breadth/vol, economically unrelated to what actually drives an oil or platinum ETF.

Checked directly by tag class across the full champion OOS population (`direction='long'`):

| tag_class | mid_bull avg_r (n) | mid_neutral avg_r (n) |
|---|---|---|
| commodity_or_fx_tagged | +0.0117 (867) | -0.0646 (408) |
| equity_tagged | **-0.0962 (2364)** | **-0.1061 (2246)** |
| other | -0.1128 (1944) | -0.1017 (1347) |

**Falsified.** Properly equity-tagged symbols (correct regime match, no plumbing bug) lose
*worse* in `mid_bull`/`mid_neutral` than commodity/fx-tagged ones, which are actually
mildly positive in `mid_bull`. The single-symbol spot check (DIA/IWM) that motivated this
hypothesis had only 1-3 `mid_bull` frames each -- too few to be representative; other equity
names in the universe fire into `mid_bull` far more often and lose there just as badly. This is
a genuine, cross-asset-class phenomenon, not a regime-labeling data-quality artifact. Don't
re-chase the asset-class-mismatch angle -- it's a dead end, recorded here so it isn't re-tested.

**Sharper conclusion:** the ensemble is ~99.5% long-only and loses specifically in
`mid_bull`/`mid_neutral` across essentially the whole universe, regardless of asset class. This
points squarely at the ensemble's direction/exposure logic itself (does it need to reduce or
flip exposure by regime, not just by symbol?) -- exactly the question the 143.1-08
sign-symmetric ensemble weighting HOLD verdict and todo 147's regime-divergence finding already
opened. Next concrete, well-defined experiment: reuse `evaluate_frame_gate`'s existing
`group_key` parameter to test whether a regime-conditional direction/exposure rule (reduce or
zero long exposure specifically in `mid_bull`/`mid_neutral`) improves c2/c3/c4 on this same
frozen population -- no new bootstrap logic, no portfolio math, no regime-relabeling needed.

## Decisive test (same session): is this a FRAME problem or a SIGNAL problem? Measured directly, barrier-free

Before spending a third round tuning stop/target/hold parameters (global scalar and per-cell
scalar both already failed decisively), tested the one thing that settles it cleanly: pull the
SAME (symbol, tf, bar_ts) population's raw, continuous, un-barriered forward return directly
from `forward_returns` (`return_type='executable_open_to_open'`, the same table/methodology
Gate 1 itself uses) and compare it to the barrier-simulated `counterfactual_pnl_r`. If the raw
return is positive and the barrier P&L is negative, the frame is destroying real economics --
fix the frame. If the raw return is ALSO negative, no frame engineering can fix it -- the
problem is upstream of execution entirely.

| Regime | n (fast) | raw return_fast | n (slow) | raw return_slow | n (extended) | raw return_extended | barrier avg_pnl_r |
|---|---|---|---|---|---|---|---|
| mid_bull | 5,143 | -0.000125 | 4,839 | -0.000299 | 3,099 | **-0.000396** | -0.0844 |
| mid_neutral | 3,640 | +0.000050 | 580 | -0.003307 | **0** | n/a | -0.1004 |

**mid_bull: unambiguous.** The raw, zero-barrier, executable open-to-open return is NEGATIVE at
every horizon tested, and gets MORE negative the longer you'd hold. This is not a frame artifact
-- it's what the market actually did. No stop placement (ATR, S/R-structural, or otherwise), no
hold-time tuning, and no position sizing can turn a genuinely negative raw forward return into a
profitable trade. **The ensemble firing long in `mid_bull` is a direction/eligibility error, full
stop, not an execution error.**

**mid_neutral: two compounding problems, not one.** `return_fast` is flat (near-zero, +0.00005 --
essentially noise) but trends negative at `return_slow` (-0.0033, on the much smaller subset of
trades that survive that long) -- and **zero trades ever reach a complete `return_extended`
value**, because the same `hold_max_bars=1` calibration found earlier means the frame closes
every position out before the extended-horizon forward return can even be measured. The 1-bar
hold isn't just truncating trades early (already established) -- it's also making it impossible
to tell, from this population alone, whether real extended-horizon edge exists in `mid_neutral`
at all. Two separable questions, don't conflate them.

**Verdict: do not pursue Phase 163's structural (S/R) stop candidate, or any further frame-layer
work, as the fix for `mid_bull`.** All roads this session lead to the same place: single-symbol
standalone tests (no basket), the sign-symmetric shadow test (no direction assumption), and now
raw barrier-free returns (no execution assumption at all) all show the same thing independently.
The deficiency is at the ensemble's regime-conditional eligibility/direction layer, not the
frame. Fixing stop/target/hold a third time, however cleverly, cannot fix a raw negative
expected return. The real next step is: does `ensemble_trainer.py`'s regime-stratified weight
training actually suppress firing (not just down-weight) in (regime, direction) buckets with
~zero-or-negative measured conditional expectancy? Or is there no expectancy floor at emission
time at all, so any positive `alpha_score` fires regardless of its regime bucket's known history?
That's a code-level question answerable by reading `ensemble_trainer.py`'s eligibility predicate
and `alpha_publisher.py`'s emission gate directly -- not a new diagnostic, an implementation
question.

`mid_neutral`'s 1-bar hold_max_bars floor is still worth fixing on its own terms (it's actively
truncating trades and it blinds the extended-horizon measurement), but it is secondary to the
mid_bull finding and should not be mistaken for the primary fix either.

## Full regime sweep (same session, user challenge: "why only 2 regimes?") — both axes checked

Fair challenge: prior sections only examined `mid_bull`/`mid_neutral` because that's where the
volume was, without first confirming that was the complete picture on either regime axis. Ran
the full sweep on both.

**Cross-sectional axis (`alpha_frames.regime`), all 9 equity cells, long direction:**

| Regime | n | avg R | Note |
|---|---|---|---|
| high_neutral | 18,632 | **+0.0090** | only genuinely-working bucket: real volume AND positive |
| mid_bull | 5,175 | -0.0844 | |
| mid_neutral | 4,001 | -0.1004 | |
| high_bear | 107 | -0.2671 | too thin to trust (n=107) |
| low_bull | 43 | -0.1481 | too thin to trust (n=43) |
| high_bull, low_bear, low_neutral, mid_bear | **0** | n/a | **never traded at all** |

Checked whether the OOS window ever actually saw those last 4 regimes (it's not that they didn't
occur): `market_regimes` confirms all 4 occurred during the OOS window (`high_bull`=17,054 bars,
`mid_bear`=2,425, `low_neutral`=1,313, `low_bear`=279). **The ensemble has zero eligible/weighted
features for 4 of 9 equity regimes** — a real coverage gap (silently-skipped zero-weight strata,
per `ensemble_trainer.py`'s own documented, intentional behavior — not a bug, but worth knowing:
only 5 of 9 equity regimes have ANY working model, and of those 5, only 1 (`high_neutral`) is
both liquid and net-positive). Rates side (0 rows) is separately explained: `ensemble_trainer.py`
hardcodes `regime_group='equity'`, so rates is out of scope entirely, not a new finding.

**Per-symbol HMM axis (`feature_vectors.regime`, 5 states) — never checked until now, crossed
against the cross-sectional bucket:**

| cs_regime | symbol_hmm_regime | n | avg R |
|---|---|---|---|
| mid_bull | **ranging** | 508 | **-0.0109** (near breakeven!) |
| mid_bull | trending_down | 895 | -0.0542 |
| mid_bull | transition_up | 364 | -0.0905 |
| mid_bull | trending_up | 735 | -0.0992 |
| mid_bull | transition_down | 540 | -0.1068 |
| mid_bull | (NULL, no HMM label) | 2,133 | -0.1027 |
| mid_neutral | all 4 states + NULL | 357-546 each | -0.07 to -0.13, no clear split |

**This matters: within `mid_bull`, the per-symbol HMM state is NOT redundant with the
cross-sectional label — it reveals real heterogeneity a single-axis fix would blur.** The
`ranging` sub-bucket is nearly breakeven while `trending_up`/`transition_down` are the real
losers, even though all of them share the same cross-sectional `mid_bull` tag. A regime
eligibility gate keyed ONLY on cross-sectional `(regime, direction, tf)` would suppress the
`ranging` sub-bucket along with the genuinely bad ones, discarding real signal. `mid_neutral`
shows no equivalent split (uniformly bad across HMM states) — the two regimes are NOT the same
problem and don't need the same fix. Also note: the largest single mid_bull HMM sub-bucket
(2,133 frames, NULL/no-HMM-label) performs as badly as the worst labeled buckets — likely
overlaps with the already-tracked per-symbol HMM coverage gap (todos 168/169), worth checking
whether fixing that coverage gap alone recovers some of this.

**Revised design implication:** the regime-eligibility-gate design (see below) should stratify
jointly on `(cross_sectional_regime, symbol_hmm_regime, direction, tf)`, not cross-sectional
regime alone — that's where the actual differentiating signal lives. Small-N cells (most
combinations here are 350-900 frames, below any comfortable day-cluster count) mean this joint
gate needs the same `min_clusters` coverage floor already established for todo 165's
regime-stratified re-evaluation — expect many cells to land `coverage=insufficient`, which is
itself useful information (says where we genuinely don't know yet, vs. where we do).

## What needs to happen

The risk-budget sweep already answers "is this purely a sizing artifact?" -- no. Don't repeat
that experiment. The real open question is why a long-biased ensemble loses specifically in
`mid_bull`/`mid_neutral` regimes (extended, autocorrelated losing stretches, not isolated
concentration spikes):

1. Check regime-labeling data quality first (cheapest, per "data quality over model complexity"):
   confirm `mid_bull`/`mid_neutral` labels on the OOS champion population aren't stale/misapplied
   (e.g. forward-filter lag, wrong `regime_group`) before concluding it's a real signal-direction
   problem.
2. If labels check out: quantify whether a regime-conditional direction/exposure rule (e.g.
   reduce or flip long exposure specifically in `mid_bull`/`mid_neutral`, keep it in
   `high_neutral`/`high_bear` where the champion is flat-to-profitable) recovers c2/c3/c4 on the
   same frozen population -- reuse `evaluate_frame_gate`'s existing `group_key` machinery, no new
   bootstrap logic needed.
3. Connect to the two already-open, thematically identical questions rather than treating this
   as a fresh investigation: the 143.1-08 sign-symmetric ensemble weighting HOLD verdict, and
   todo 147's `low_bull` divergence finding. All three are pointing at the same underlying
   question -- does this ensemble need real regime-conditional direction, not just
   regime-agnostic long bias with a global stop/target?
4. Keep the concentration-aware sizing result (Sharpe 1.1-2.0 vs 0.44) as a real, low-cost
   improvement worth carrying into whatever candidate is scored next regardless of how the
   regime question resolves -- it triples risk-adjusted return for zero cost, it just isn't
   sufficient alone.
5. Re-verify on the true baseline population (frames were overwritten by the scalar arm's
   regen cycle, never restored) before treating any of the above as final: flip
   `alpha.frame.geometry_source` back to `global`, regenerate the OOS window, confirm exact
   reproduction of the recorded `9.596` c4 before drawing conclusions specific to baseline.

## Tier-1 validation, run for real (2026-07-24): does ANY regime-conditional expectancy floor exist? No.

Confirmed by direct code read first (not assumed): neither `ensemble_trainer.py`'s
`_eligibility_where()` nor `alpha_publisher.py`'s emission gate validates a stratum's
realized OOS outcome -- both operate purely on `feature_ic_scores` predictor significance
(CI/FDR/walkforward/reliable) or a per-bar CI-vs-cost-hurdle check on that bar's own alpha
score. Confirms the framing above precisely: if a regime-conditional floor existed, it would
have to be built fresh; nothing today implicitly provides one.

Built `scripts/analysis/regime_eligibility_joint_stratification_validation.py` (reuses
`evaluate_frame_gate`/`frame_gate_passes` verbatim, same day-clustered block-bootstrap
machinery as FRAME-04/todo 165, same `alpha.validation.regime_gate_min_clusters=20` floor).
Ran it against the champion OOS population (`143.1-08-champion`, 19,237 rows with a
symbol_hmm label out of 28,100 total -- 8,863 excluded for missing per-symbol HMM regime,
the still-open todo 168/092/167 Layer-1 coverage gap):

**Coarse cut (tf, direction, cross_sectional_regime):** 9 cells have any data at all (matches
the "4 of 9 equity regimes never traded" finding above). Only 2 clear the day-cluster
coverage floor (both `mid_bull`) and both fail (`ci_lower` -0.24 at 15m, -0.07 at 5m).
**`high_neutral`/15m -- the bucket this file's own naive-average table above called "the only
genuinely-working bucket" (+0.0090 avg R) -- lands `n_clusters=19`, one cluster short of the
20 floor, AND its properly-bootstrapped `ci_lower` is -0.16.** The naive per-trade average
being positive does not survive accounting for day-cluster autocorrelation -- this reframes
that earlier finding from "genuinely working" to "not statistically distinguishable from
noise, and one day-cluster short of even being evaluable."

**Joint cut (+ symbol_hmm_regime):** 42 cells have any data; only 5 clear the coverage floor
(all `mid_bull`/5m/long, split by symbol_hmm sub-regime) and all 5 fail, including the
`ranging` sub-bucket flagged above as "near breakeven" on a naive average (`-0.0109`) --
properly bootstrapped, its `ci_lower` is **-0.177**, solidly negative, not breakeven.

**Verdict: zero cells pass at any tested granularity, coarse or joint.** A
`regime_eligibility_gate.py` built today, at either stratification, would find nothing to
let through -- not a partial gate, a full stop. This is a stronger, more rigorous version of
the file's earlier "mid_bull raw return is negative at every horizon" finding: it's not just
that the raw return is bad in the one regime with the most volume, it's that no regime slice
in the entire champion population -- including the two buckets that looked promising under
naive per-trade averaging -- clears a proper statistical bar. Full detail (per-cell numbers,
methodology, reusable script) in the script itself; script output is reproducible and not
duplicated verbatim here.

**What this changes:** the original framing of this todo ("build a regime eligibility gate,
restrict emission to the passing strata") assumed some strata would pass. None do. This
doesn't just reinforce Phase 148's Gate 2 FAIL -- it closes off the "maybe a finer regime cut
finds a hidden good subset" hope that motivated this whole investigation thread. The open
question is no longer "which regime slice is safe to keep emitting in" but "does this
ensemble construction (current feature set + IC-weighted linear combination + barrier
execution) have ANY OOS-detectable edge at the frame level, at all, in the current data" --
which is a much bigger question than a gate script can answer. Recommend surfacing this to
the user as a real strategic fork rather than picking a direction unilaterally.

## The Gate1/Gate2 divergence mechanism, found and confirmed directly against live data (2026-07-24)

Renaissance-council-style challenge to the Tier-1 validation above: how can Gate 1 pass with
a 10x margin (140/640 cells, later independently reproduced as 55/640 under a stricter
recomputation of the same criteria) while Gate 2 and every regime-stratified re-test since
show zero profitable cells anywhere? Two hypotheses were tested and one confirmed directly:

**Confirmed mechanism: Gate 1's IC is pooled ACROSS ALL REGIMES per (symbol, tf, lookahead)
-- it never checked whether the relationship holds up broken out by regime.** Verified by
reading `gate1_signal`'s own recorded evidence in `gate_evaluations` directly: all 640 cell
dicts have keys `{tf, scale, symbol, n_valid, p_value, ic_value, reliable, passes_fdr,
ic_ci_lower, ic_ci_upper, bh_adjusted_p, walk_forward_stable}` -- no `regime` key anywhere.
640 = 80 symbols x 2 tf (5m/15m) x 4 scales, pooling all regimes' bars into one time series
per cell. Confirmed `run_2025122405150000` (Gate 1's weight_version) and `143.1-08-champion`
(Gate 2's weight_version) carry byte-identical `ensemble_weights` rows -- same underlying
ensemble, just two labels for the same weights, so this isn't a stale-weights mismatch.

Recomputing Gate 1's own qualifying criterion (`ic_ci_lower > 0 AND passes_fdr AND
walk_forward_stable`) against the live evidence gives 55/640 qualifying cells (the discrepancy
from the recorded 140 is unexplained -- possibly a criterion or snapshot difference not yet
traced, doesn't affect the finding below). For every one of those 55 cells, pulled the SAME
(symbol, tf, lookahead)'s regime-decomposed IC from `alpha_ensemble_ic`'s own `is_pooled=false`
rows (computed and stored, just never consulted by the gate) and tabulated, per regime, what
fraction agree in SIGN with the pooled IC (built and verified in
`scripts/analysis/gate1_pooled_vs_regime_decomposed_ic_check.py`; an initial scratch pass also
tallied "independently significant" counts using only `ic_ci_lower > 0` -- that metric was
wrong, since it dropped Gate 1's own `passes_fdr`/`walk_forward_stable` conditions; applying
the full 3-condition bar per-regime correctly shows almost no cell independently significant
anywhere, unsurprising given the much smaller per-regime N -- the sign-agreement rate below is
the metric that actually carries the finding, not a significance count):

| Regime | cells with a same-regime row | % same sign as pooled IC |
|---|---|---|
| `high_neutral` | 47 | **83%** |
| `high_bear` | 29 | 79% |
| `mid_neutral` | 19 | 79% |
| `low_bull` | 29 | 59% |
| `mid_bull` | 55 | 58% |

**`high_neutral` is where the real signal concentrates** -- consistently the best regime by
sign-agreement rate, corroborating (not just repeating) this file's earlier naive-average
finding ("only genuinely-working bucket," +0.0090 avg R) and the Tier-1 validation's finding
that `high_neutral`/15m came within 1 day-cluster of clearing a real bootstrap CI
(`n_clusters=19` vs a 20 floor, `ci_lower=-0.16`). **`mid_bull`/`low_bull` -- with `mid_bull`
dominating trade volume and shown catastrophically unprofitable by Gate 2 and every
regime-stratified re-test since -- sit right at a coin flip (58-59% sign agreement, barely
above the 50% no-information baseline).** The pooled Gate 1 test's apparent per-symbol
strength is being carried by whichever regime that symbol happens to have the most pooled
observations in and/or the strongest relationship in (often `high_neutral`/`high_bear`/
`mid_neutral`), not necessarily the regime the ensemble is actually firing trades into.

**This is the actual answer to "why does Gate 1 pass and Gate 2 fail everywhere":** the
proof-of-signal gate and the actual traded population were never the same population. Gate 1
never validated that its pooled IC survives being regime-conditional; alpha_publisher's
emission gate is regime-blind (a single per-tf CI/cost hurdle, no per-regime term) and, in
practice, ends up firing overwhelmingly into `mid_bull`/`mid_neutral`/`high_neutral` by trade
count, not into the regimes (`high_bear`/`low_bull`) where the per-symbol IC is most often
correctly signed.

**Recommended next step, cheaper than either building new features or abandoning this
branch:** `high_neutral` has now looked like the best regime under three independent methods
today (naive averaging, within-symbol median-split monotonicity, and this regime-decomposed
IC breakdown) and missed a clean bootstrap pass by one day-cluster. Before concluding "no
edge, pivot to Phase 164/165" or "build a regime-eligibility gate broadly," the cheapest next
test is: does `high_neutral` alone, given a slightly larger OOS window or a relaxed/re-examined
day-cluster floor, actually clear a rigorous positive CI? If yes, the fix is architectural
(make `alpha_publisher`'s eligibility/threshold regime-conditional, so it concentrates
exposure in `high_neutral` and pulls back in `mid_bull`) rather than a features-or-give-up
choice. This is a decision point, not something to build unilaterally -- surfaced to the user
2026-07-24.

## Acceptance criteria

- [x] Regime-conditional direction/exposure rule tested against c2/c3/c4 on the same frozen
      data, generalized to the full joint stratification -- zero cells pass, see above
- [x] Explicit connection made to the 143.1-08 sign-symmetric HOLD verdict and todo 147's
      regime-divergence finding -- same underlying question, now answered empirically: no,
      there is no regime/direction slice with real conditional edge in this data
- [ ] Regime labels on the OOS champion population spot-checked for staleness/mislabeling
      (lower priority now -- even if labels were perfect, no slice passes)
- [ ] True baseline population re-verified (not just the scalar arm currently live in the table)
- [x] Clear recommendation: the frame/execution/ensemble construction as currently built does
      not clear a rigorous regime-conditional bar anywhere tested -- pursuing Phase 149+
      (portfolio/execution infra) on this signal is not supported; the open strategic
      question is whether to invest in better features/signal (Phase 164/165) or accept this
      branch has no detectable live edge yet
