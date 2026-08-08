# Trade Construction Layer -- From Forecast to Position

**Version:** 1.4
**Status:** UNVERIFIED, re-verification pending -- `services/cross_sectional_spread_tracker.py`
productionizes cross_sectional_relative_value's construction, ranked solely on `ctf_momentum`
(`_FEATURE = "ctf_momentum"`). **The 2026-07-27 gate run below was measured against a
lookahead-leaking `ctf_momentum` join (todo 243), confirmed 2026-08-04 -- do not cite either gate
as PASSED until re-run under the corrected join.** See "Correction, 2026-08-04" below the
Validation Gates section for full detail. **Do not begin Phase 168 (this construction's
cost-hurdle-adjusted follow-on) until this is resolved.**
**Priority:** high (weakness #5 from the 2026-07-01 council review: the layer is absent, and
its absence changes what "edge" means upstream) -- **re-verification of both gates is now the
blocking precondition for the Phase 156-159 execution/sizing chain**, not a cleared precondition
**Milestone:** future -- scoping trigger was Phase 142A's OOS gate, same as PortfolioTrack;
that gate cleared 2026-07-22 (Gate 1 PASS)
**Last Updated:** 2026-08-04
**Tags:** trade-construction, portfolio, cross-sectional, long-short, sizing, cost, kelly

**Correction, 2026-08-04 (todo 243/253):** the 2026-07-27 run below ranked the construction on
`ctf_momentum` read from `feature_vectors`, populated at the time by a batch HTF join that
selected the still-forming HTF bar rather than the last completed one -- confirmed real
lookahead (todo 243). A SPY single-symbol pilot under the corrected join found 15m point_ic
(the tf this construction actually trades) collapses from +0.0746 to +0.0047 (CI
[-0.0007,0.0100], no longer significant) -- the feature this construction ranks on may not
carry the signal the 2026-07-27 gates measured. Both gates below must be re-run against the
corrected join before either verdict can be cited as current. A diagnostic-tier (not
promotion-grade) re-verification harness exists at
`scripts/analysis/phase167_gate1_ctf_join_fix_reverify_15m.py`; an authoritative re-run needs
`forward_returns` populated past `alpha.validation.oos_start` first (todo 253 -- currently
empty in that region; the normal pipeline never writes there by design, per
`docs/plans/OOS-EVAL-PROTOCOL.md`). D-04 run-once gate governance (`gate_evaluations` +
`.planning/gate_look_log.jsonl`) is now wired into `cross_sectional_spread_tracker.py`'s
`--evaluate-gate`/`--evaluate-attribution` modes (2026-08-04) -- confirmed no completed look for
this construction was ever recorded there, so a future real run is unambiguously a first look,
not a second one under `OOS-EVAL-PROTOCOL.md`'s "at most once per milestone gate" cadence rule.

**Diagnostic-tier result, 2026-08-04 (still not authoritative -- see caveat below):** the
harness above ran. Self-check against the leaked join reproduced `gate1_passes=true`, matching
the recorded 2026-07-27 verdict -- confirms the harness is faithful. **Against the corrected
join: `gate1_passes=FALSE`.** Both scales' `ci_lower` flip negative (fast: 0.000187 ->
-0.000141; slow: 0.000164 -> -0.000486), and the shuffled-ranking null no longer clears either
scale (fast `null_p` 0.0 -> 0.675, slow 0.0 -> 1.0 -- the slow-scale observed spread is now met
or exceeded by every one of 40 null draws). Same direction as the SPY single-symbol pilot.
Artifact: `logs/construction_verdicts/gate1_ctf_join_reverify_15m_DIAGNOSTIC_20260804T165458Z.json`.
**Caveat, load-bearing:** this diagnostic computes OOS returns on the fly and does NOT replicate
`forward_return_writer.py`'s suspect-value/cross-symbol-corroboration corrections -- it is
first-look evidence, not the authoritative re-verification. It materially raises confidence that
an authoritative re-run will also fail, but does not settle the question.

**Updated 2026-07-27 (superseded by the correction above -- kept for the record, do not cite the
PASS verdicts standalone):** Phase 167 ran the construction for real: full 2006-2026 corpus
backfill into `construction_spreads` (24,924 bars), both live Validation Gates evaluated
against the real OOS population. Gate 1 (shadow spread Sharpe) PASSED and Gate 2 (attribution
honesty) PASSED. Full numeric detail, the binding pass rule, and the Gate 2 retrospective
caveat are recorded in the Validation Gates section below, transcribed from
`logs/construction_verdicts/gate1_20260727T112626Z.json` and
`logs/construction_verdicts/gate2_20260727T112642Z.json`.

**Updated 2026-07-26** -- `scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py` (deleted 2026-07-28, git-history only)
ran the falsification test this doc exists to enable: equity/15m, `ctf_momentum`, top/bottom
decile dollar-neutral spread. **Passed decisively at both lookahead scales** (fast: mean
spread 5.9bp/bar, `ci_lower`=5.6bp; slow: mean spread 11.1bp/bar, `ci_lower`=9.7bp), and
cleared a shuffled-ranking-null guard at `P(null ≥ observed)=0.0000` both times -- not a
dollar-neutral construction artifact. Gross only, no cost model yet. Full result and
methodology: `docs/research/data-edge-source-thesis.md` cross_sectional_relative_value section. This doc's v1 design
(construction + shadow measurement, 1-2 phases) is now ready to scope for real, with the
todo 030 cost-hurdle treatment applied to the spread construction specifically as the first
open item (a long-short spread's cost dynamics differ from a directional trade's -- this doc's
own point, not yet quantified for this specific construction).

**Reviewed 2026-07-25** -- re-read in full while resolving the "what other signal construction
approaches exist" question raised alongside Phase 164/165's feature-expansion fork. Still
correct and, if anything, more load-bearing than when written: `docs/research/data-edge-source-thesis.md`'s
regime_conditional_persistence (regime-conditional absolute-direction persistence) was falsified 2026-07-24 across an
exhaustive 234-cell sweep (`.planning/todos/completed/179-gate166-concurrent-exposure-diagnostic.md`)
-- the *per-symbol directional* construction row 1 of this doc's own table found no edge
anywhere. That's exactly the failure mode cross_sectional_relative_value (row 2, cross-sectional long-short) was designed
to be robust to: cross_sectional_relative_value doesn't need per-symbol absolute direction to be right, only the *ranking*
across the 58-instrument universe, which is a structurally different and easier bar. This doc
was already scoped and gated correctly -- the gate it was waiting on (Phase 142A's OOS proof)
resolved 2026-07-22, and regime_conditional_persistence's death 2026-07-24 sharpens the case further, so this is
recommended as a near-term next step alongside/before Phase 164/165 rather than an
indefinitely-deferred v4.0 concern. See `docs/research/data-edge-source-thesis.md`'s Roadmap
Demands §5 for the fuller comparison against Phase 164/165 and nonlinear_interaction_combiner (non-linear combiner,
`docs/ideas/measurement-nonlinear-interaction-combiner.md`).

**Companion to:** `docs/research/data-edge-source-thesis.md` (thesis cross_sectional_relative_value is only testable through this
layer) and `docs/research/measurement-ic-engine.md`'s Cross-Sectional Rank IC addendum (cross_sectional_relative_value's
falsification measurement, which must clear before this construction layer is warranted).
**Note (2026-07-03):** this doc's original companion, `intel-11-dual-system-discrete-vs-portfolio.md`,
was retired -- see `docs/research/archive/intel-11-dual-system-discrete-vs-portfolio.md`. Per
`docs/research/fable-2026-07-03-intel10-11-review.md` (F9), PortfolioTrack is not a track;
this doc's construction-layer content remains a v4.0 concern, gated on the addendum's falsification
result, not on a "PortfolioTrack" scoping event.

---

## The Core Point

A forecast is not a trade. The same per-bar conviction vector can be monetized at least four
structurally different ways, and they have *different edge requirements* -- the construction
choice determines how much IC is enough:

| Construction | What it needs to win | IC bar | Beta exposure |
|---|---|---|---|
| Per-symbol directional (current implicit design) | Each symbol's signal beats that symbol's full vol + market moves | Highest | Full |
| Cross-sectional long-short (dollar-neutral) | Only the *ranking* across symbols has to be right | Lowest | ~Hedged |
| Directional with index hedge | Signal beats idiosyncratic vol only | Middle | Hedged per-position |
| Overlay tilts on a passive book | Conditional tilts beat their own turnover cost | Lowest, but capped upside | Deliberate |

Everything upstream (IC engine, ensemble, frames) is currently built for row 1 -- the hardest
row. Phase 142B's stop/target/hold frames are per-symbol directional execution rules. Nothing
in the roadmap tests rows 2-4.

## Why Cross-Sectional Long-Short Is the Natural Fit for This Universe

- **58 correlated ETFs is a relative-value universe, not 58 independent directional bets**
  (effective breadth measured ~4.5-8.4, 2026-08-07, not the earlier assumed ~8-15 -- see
  `data-edge-source-thesis.md`'s Breadth section; see also feature-scoring-beyond-ic §4).
  Ranking within a correlated
  set is exactly what a cross-sectional portfolio monetizes and a directional book wastes.
- **Beta cancellation is free risk reduction.** Long the top decile of the ranking, short the
  bottom, dollar-neutral: the market factor nets out, so the P&L stream is the *spread* -- driven by the forecast, not by whether SPY went up. The Sharpe of a hedged spread on weak
  IC routinely beats the Sharpe of unhedged directional trades on the same IC.
- **It changes the falsification story.** If per-symbol directional fails the cost hurdle
  (todo 030 Step 0) but the spread portfolio pays, the edge is real and relative (thesis cross_sectional_relative_value).
  Without this layer, that outcome is indistinguishable from "no edge."
- **Costs differ:** a rebalanced spread portfolio trades *changes in the ranking*, not every
  signal -- turnover control is a portfolio property, unavailable to independent per-symbol
  frames.

## Minimal Design (deliberately small -- this is a v1 spec, not an optimizer)

Renaissance principle applied: no convex optimizer, no risk-model estimation, no borrow/
margin modeling in v1. Rank, bucket, weight, net, rebalance. Each step earns complexity later
through proof.

1. **Input:** per-bar calibrated conviction vector across the universe per tf -- requires
   feature-scoring-beyond-ic 0c (calibration) so the vector is in return units. Uncalibrated
   z-scores can rank (enough for v1 spread construction) but cannot size.
2. **Ranking → buckets:** top-N / bottom-N by conviction (APR: `alpha.construction.n_legs`),
   within the symbol's validated regime_scope only.
3. **Weights:** v1 equal-weight per leg, vol-scaled per symbol (divide by trailing ATR/vol so
   one high-vol leg doesn't dominate the spread). Kelly-fraction scaling of gross exposure
   deferred until calibrated E[R] exists (the `alpha.*` Kelly APR keys already reserved).
4. **Netting:** dollar-neutral across legs per tf. Cross-tf netting (5m signal vs 1d signal
   on the same symbol) resolved by simple priority rule in v1 (APR:
   `alpha.construction.tf_priority`), learned later.
5. **Rebalance rule:** trade only ranking changes that clear a per-trade cost floor
   (todo 030's spread estimates) -- turnover control as a first-class constraint, not an
   afterthought.
6. **Measurement:** the unit of account is the *portfolio*, not the trade. Daily spread P&L,
   net of modeled costs, vs. two benchmarks: flat, and the same construction with shuffled
   rankings (the construction-level null -- a spread portfolio can show positive P&L from
   construction artifacts alone; the shuffled-ranking null catches that).

## What This Explicitly Defers

- Convex optimization / covariance-based risk models (v1 vol-scaling is the 80/20)
- Borrow cost / hard-to-borrow modeling (ETF universe is easy-to-borrow; revisit if universe
  expands)
- Capacity/market-impact modeling (irrelevant at this account size)
- Live execution -- this layer is validated entirely in counterfactual/shadow mode first,
  same discipline as Phase 142B frames

## AegisAgent / TradeAgent Reuse Assessment (todo 059, 2026-07-16)

`docs/research/archive/vision-01-aegisagent.md` (independent risk management) and
`docs/research/archive/vision-05-tradeagent.md` (autonomous trading app) were written as
long-horizon, multi-tenant commercial-product vision -- out of scope now that the Core Value is
confirmed as personal live-trading capital (`.planning/PROJECT.md`). Re-reading both specifically
for "what transfers to a single-user version" against this doc's v1 design and the v4.0 Execution
Layer roadmap (Phases 156-159):

**Transfers directly (no descoping needed):**

- **AegisAgent's fail-safe default** -- if the risk check is unavailable, block new positions.
  Cheap, architecturally correct regardless of scale, and should be a hard rule in Phase 157.
- **AegisAgent's hard limit table** (max daily/weekly/account drawdown, margin utilization
  tiers, single-position-% caps) maps almost line-for-line onto Phase 157's already-planned
  risk ceilings (VaR ceiling, per-symbol drawdown limits, regime-conditioned caps) -- use
  AegisAgent's limit table as the starting checklist when Phase 157 is planned, not a proposal
  needing re-derivation.
- **AegisAgent's emergency halt / independent-authority principle** -- a risk check that cannot
  be silently bypassed by the sizing or execution code path. Phase 157 already independently
  designed a kill switch; AegisAgent's "fails loud, fails safe, no automated override" framing
  is the correct discipline to apply to it, single-user or not.
- **AegisAgent's VaR (95%/99%) and correlation/concentration analysis** -- directly reusable;
  Phase 156's `portfolio_state` (correlation-cluster exposure) and Phase 157's VaR ceiling are
  this same idea, already scoped.
- **AegisAgent's audit trail** (`risk_events`, `pretrade_checks` tables) -- cheap, valuable at
  any scale, no commercial framing required.
- **TradeAgent's trade lifecycle management** (stop cascade 1m→5m→15m→1H, BE/trail logic) -- pure
  position-management logic with zero multi-tenant baggage. Not yet named explicitly in Phase
  158/159's design; worth folding in when those phases are planned.
- **TradeAgent's confidence→allocation curve** -- a simple signal-confidence-to-position-size%
  map. Useful as an interim/sanity-check sizing method before Phase 157's Portfolio Kelly is
  fully calibrated (Kelly with high estimation error can produce sizes worth sanity-checking
  against a simpler curve).
- **TradeAgent's reconciliation agent** (compare internal ledger to broker positions/fills,
  flag breaks) -- directly reusable and currently a gap in Phase 158's design, which covers
  idempotent reconciliation on reconnect but not an ongoing scheduled reconciliation job.
- **TradeAgent's trade linkage/groups** (P&L, risk, and close managed as one unit for a set of
  legs) -- maps directly onto this doc's own cross-sectional spread portfolio: a long/short
  ranked bucket is exactly a "group" whose legs should be sized, measured, and closed together.
- **TradeAgent's learning-loop promotion gates** (minimum sample size before a weight update,
  versioning/rollback) -- not a new idea for this project, it's the same Shadow Governance /
  APR promotion-gate pattern already in use (`setup_performance`'s `sample_size >= 30` gate);
  AegisAgent/TradeAgent's version confirms the pattern rather than introducing one.

**Needs descoping (the underlying idea is right, the commercial machinery around it is not):**

- **AegisAgent's synchronous pre-trade-check protocol as an independent Ring 2 daemon**
  publishing binding `risk:halt`/`risk:reduce` Kafka events other daemons must obey -- for one
  account and one execution path, this can likely collapse into an in-process gate call inside
  Phase 157/158's sizing→execution sequence rather than a separate pub/sub service. Keep the
  *property* (a bug in sizing math cannot silently disable a drawdown limit) by hard-sequencing
  Phase 157 before Phase 158, not by building a standalone daemon architecture to enforce it.
- **AegisAgent's stress-test scenario library** -- descope from 7 scenarios (several assume an
  options book: vol spike/crush on Greeks, short gamma/vega) down to the 1-2 that apply to an
  ETF-only spot book (gap-open, vol spike on the underlying). No options are traded here.
- **AegisAgent's margin monitoring across brokers** -- single IBKR account, no
  multi-broker margin aggregation needed; keep basic utilization tiers only.
- **TradeAgent's broker-agnostic canonical order model** -- the *abstraction* (internal logic
  speaks one order format, translated at the boundary) is good practice and already matches
  this project's existing invariant that `src/providers/ibkr.py` is the sole `ib_async`
  boundary. Descope everything downstream of that: no multi-broker adapters, no MCP-per-broker,
  no rule-based routing table -- there is exactly one broker connection.
- **TradeAgent's signal/universe filtering** (asset-class/sector allow-blocklists) -- descope
  from a per-tenant rules engine to one global static config list. The design shape (an
  include/exclude filter ahead of sizing) is still worth keeping.
- **TradeAgent's Lead agent (LLM-assisted take/skip/size with HITL approval modes)** -- descope
  to a deterministic decision path for v1; this project's existing pattern keeps LLMs advisory/
  narrative (`narrative_swarm`), not in the order-decision critical path. The user is already
  the human in the loop by default for a personal account -- the elaborate approve/advisory/
  autonomous mode-selection machinery isn't needed until (if ever) an LLM sits in that path.

**Commercial-only / irrelevant -- ignore:**

- Multi-tenant everything: per-tenant parameters, per-tenant broker credential encryption,
  tenant isolation and least-privilege between *other users'* credentials.
- Agent dashboards/ops and reporting agents framed as a customer-facing product surface
  (spin up/turn off per tenant, emailed/PDF/CSV report delivery) -- this project already has
  Grafana (`:3001`) for internal monitoring; no customer deliverable is needed.
- Prompt-injection/tool-injection hardening for LLM-driven order submission -- moot once the
  decision path is kept deterministic (see descoping above); revisit only if an LLM is ever
  placed in the execution critical path.
- Institutional compliance/regulatory reporting framing, and any options-Greeks-specific
  language (vega/gamma exposure, short-vol stress) -- not applicable, no options book exists.

## Validation Gates (same pattern as everything else)

1. **Shadow spread portfolio on the OOS window:** net-of-cost spread Sharpe > 0 at 95%
   bootstrap CI, and beats the shuffled-ranking null.
2. **Attribution honesty:** spread P&L must load on the forecast (rank-weighted return
   spread), not on a static factor tilt (e.g., permanently long low-vol sectors) -- regress
   spread returns on static bucket membership; if a fixed membership explains most of it,
   the "forecast" is a factor exposure in disguise (edge thesis horizon_risk_premium, cap expectations
   accordingly).
3. **Comparison to DiscreteTrack directional on the same features** -- this comparison IS the
   cross_sectional_relative_value test from the edge-source thesis; record the verdict there.

### Live verdicts (2026-07-27, Phase 167 Plan 06) -- SUPERSEDED, see "Correction, 2026-08-04" above

**Do not cite the PASS verdicts below as current.** They are an accurate historical transcription
of what the 2026-07-27 artifacts recorded, kept for the record -- but the `ctf_momentum` values
that run ranked and measured against were confirmed 2026-08-04 to carry real lookahead (todo 243).
Both gates need to be re-run under the corrected join before either verdict can be trusted again.

Every number below is transcribed from two timestamped, strict-JSON artifacts written by
`services/cross_sectional_spread_tracker.py` BEFORE this prose was written:
`logs/construction_verdicts/gate1_20260727T112626Z.json` (Gate 1) and
`logs/construction_verdicts/gate2_20260727T112642Z.json` (Gate 2). Both artifacts are
strict-JSON (`allow_nan=False`, no bare `NaN` tokens) and were spot-checked against the
matching `gate1_summary`/`gate2_summary` structlog lines in
`logs/cross_sectional_spread_tracker.log` before transcription; log and artifact agreed on
every sampled value.

**Gate 1 -- shadow spread portfolio, OOS**

**Binding pass rule (single source of truth, reproduced verbatim from
`services/cross_sectional_spread_tracker.py`'s design):** Gate 1 passes iff, at the most conservative
configured cost tier (`max(cost_bps)`), BOTH the fast and slow cells have `passes` true, AND
both scales' `null_p` is strictly below 0.05.

**Verdict: PASS.** `gate1_passes=true`, binding cost tier = 10bp round-trip. OOS window:
`bar_ts >= 2025-12-24T05:15:00Z` (`alpha.validation.oos_start`), 650 rows across 130 distinct
day-clusters -- well clear of `alpha.scoring.min_strategy_n=30`, so this is an evaluated
verdict, not UNDERPOWERED.

| Scale | cost_bps | n_bars | n_clusters | ci_lower | passes |
|---|---|---|---|---|---|
| fast | 1  | 650 | 130 | 0.0006019 | true |
| fast | 3  | 650 | 130 | 0.0005682 | true |
| fast | 5  | 650 | 130 | 0.0005345 | true |
| fast | 10 (binding) | 650 | 130 | 0.0004493 | true |
| slow | 1  | 650 | 130 | 0.0001669 | true |
| slow | 3  | 650 | 130 | 0.0001323 | true |
| slow | 5  | 650 | 130 | 0.0000990 | true |
| slow | 10 (binding) | 650 | 130 | 0.0000144 | true |

Shuffled-ranking null (40 draws, `bootstrap_random_state=42`, same 650-bar OOS eligible set
for both scales): fast `null_p=0.0`, `null_mean=-0.0000033`, `null_std=0.0000603`; slow
`null_p=0.0`, `null_mean=0.0000010`, `null_std=0.0001451`. Both clear the required
`null_p < 0.05` by a wide margin -- the real ranking-driven spread is not distinguishable from
a dollar-neutral-bucketing artifact at the 0.0000 level in 40 draws.

**In-sample diagnostic (NOT the gate)** -- the comparable figures to cross_sectional_relative_value's published
full-2006-2026-history result, measured on `bar_ts < oos_start`, 24,273 bars / 4,855
day-clusters: fast `ci_lower` ranges 0.0005 (1bp) down to 0.0004 (10bp), slow `ci_lower`
ranges 0.0009 (1bp) down to 0.0008 (10bp), all `passes=true`. These in-sample cells are never
fed into `gate1_passes` -- they exist only so a reader can compare against cross_sectional_relative_value's own published
full-history numbers.

**Gate 2 -- attribution honesty**

**How Gate 2 was operationalized:** static bucket membership is each symbol's time-averaged
net leg membership over the OOS window (`w_s = (n_bars_long_s - n_bars_short_s) / n_bars`,
one fixed weight per symbol for the whole window), collapsed into a single benchmark return
series (`sum_s w_s * r_s,t`). The realized spread is regressed on this ONE series
(`spread_t = alpha + beta * static_t + eps_t`), and the residual is gated through the same
day-clustered bootstrap Gate 1 uses. The naive reading of "regress on static bucket
membership" as one dummy regressor per symbol (80 regressors against a scalar-per-bar
dependent variable) was rejected as overfit before implementation -- see
`services/cross_sectional_spread_tracker.py`'s `attribution_verdict` docstring for the full
reasoning.

**Verdict: PASS (overall).** `gate2_passes_overall=true` -- both scales independently pass
(binding rule: BOTH scales' `gate2_passes` must be true). `max_static_r2` ceiling in force:
0.50.

| Scale | beta | intercept | static_r2 | static_dominates | residual_ci_lower | residual_passes | gate2_passes |
|---|---|---|---|---|---|---|---|
| fast | 0.007761 | 0.0007528 | 0.000168 | false | 0.0006210 | true | true |
| slow | -0.141458 | 0.0013836 | 0.049327 | false | 0.0004682 | true | true |

Both scales' `static_r2` sit far below the 0.50 ceiling (fast 0.02%, slow 4.9%) -- a fixed,
retrospective leg-membership tilt explains almost none of the realized spread, and what
remains after removing it still clears its own 95% bootstrap CI at both scales.

**Interpretation caveat (verbatim from the artifact's `interpretation_caveat` field, load-bearing):**

> The static-tilt benchmark is a retrospective, time-averaged summary of realized leg
> membership over the same window whose returns it is used to explain, not a live or causal
> decomposition of the strategy's mechanism. A surviving residual therefore falsifies the
> static-tilt explanation without establishing what does explain the return.

In this doc's own words: `w_s` above is computed from the SAME OOS window whose returns it
explains -- no live strategy could have held those weights in advance, since they are only
knowable in hindsight. This makes Gate 2 a falsification test in ONE direction only. A HIGH
`static_r2` would be strong evidence the P&L is a disguised fixed tilt; a LOW `static_r2` plus
a surviving residual (what happened here) is evidence only that the P&L is NOT explained by
this particular retrospective summary. It is NOT proof that the forecast is what generated the
return, and it identifies no mechanism. "The residual survives" must not be read as "we have
proven WHY it survives."

**What the tilt actually was** (the concrete, interpretable content of Gate 2's static weight
vector, whatever the verdict -- 80 symbols total):

- **Top 5 most-positive weights (structurally long over the OOS window):** EWT 0.3108, BIL
  0.2677, EWY 0.2338, EEM 0.1246, CIBR 0.1154
- **Bottom 5 most-negative weights (structurally short over the OOS window):** BTAL -0.2185,
  KWEB -0.2138, FXY -0.1831, FXI -0.1431, INDA -0.1415

**Gate 3 -- comparison to per-symbol directional on the same features**

Already satisfied by the regime_conditional_persistence-vs-cross_sectional_relative_value comparison in `docs/research/data-edge-source-thesis.md` --
regime_conditional_persistence (per-symbol directional, regime-conditional) was falsified 2026-07-24 across an exhaustive
234-cell sweep, and cross_sectional_relative_value (this cross-sectional construction) passed decisively on the identical
features. No new work required for this gate; the comparison already exists and is not
re-run here.

### Intentional divergences from the cross_sectional_relative_value falsification script, and the equivalence check

`services/cross_sectional_spread_tracker.py` productionizes
`scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py` (deleted 2026-07-28, git-history only). Four differences are
DESIGNED, not bugs:

1. **Deterministic `(feature_value, symbol)` tie-break** replacing pandas' input-order-dependent
   `sort_values` -- a reproducibility improvement, numerically irrelevant on a continuous
   z-scored feature.
2. **`one_way_turnover` is `NULL`** for the corpus's genuinely-first bar, where the script used
   `0.0` -- affects exactly one row out of 24,924.
3. **A non-finite or missing feature value raises** instead of being silently sorted -- should
   never fire in practice, since the panel query filters `ctf_momentum IS NOT NULL`.
4. **Gate 1 is evaluated on the OOS segment** (`bar_ts >= alpha.validation.oos_start`) while
   the cross_sectional_relative_value script reported full-history numbers -- this is why the in-sample diagnostic cells
   above exist; they are the comparable figures, and the OOS cells above are not expected to
   match the script's originally published values exactly.

Any difference NOT on this list would be a bug until proven otherwise. Before trusting the
gates above, the productionized construction's turnover and gross-spread statistics were
checked against four tolerance bands FIXED BEFORE the backfill ran (a pre-registration, not a
post-hoc justification), each +/-20% relative of cross_sectional_relative_value's originally published full-history
values:

| Statistic | cross_sectional_relative_value reference | Band | Observed | Result |
|---|---|---|---|---|
| mean `one_way_turnover` | 0.195 | [0.156, 0.234] | 0.1949 | PASS |
| median `one_way_turnover` | 0.0625 | [0.0500, 0.0750] | 0.0625 | PASS (exact) |
| mean `gross_spread_fast` | 5.9 bp/bar | [4.72, 7.08] bp/bar | 5.87 bp/bar | PASS |
| mean `gross_spread_slow` | 11.1 bp/bar | [8.88, 13.32] bp/bar | 11.15 bp/bar | PASS |

All four cleared. The productionized construction also processed exactly 24,924 bars
(`n_bars_processed`), matching cross_sectional_relative_value's own published full-history `n_bars=24,924` for both scales
to within zero (one distinct-bar-count difference between the two runs' corpus snapshots,
consistent with a single trading bar added to the corpus between cross_sectional_relative_value's 2026-07-26 run and this
2026-07-27 run, not a discrepancy requiring investigation).

## Sequencing

**Was blocked on Phase 142A (proven OOS ensemble IC -- no point constructing portfolios from an
unproven forecast). That gate cleared 2026-07-22 (Gate 1 PASS, Phase 148).** Unblocked as of
2026-07-25 -- see the review note in the header. This doc's v1 was built in Phase 167 as
`services/cross_sectional_spread_tracker.py`: a BaseBatch oneshot with `--backfill`,
incremental, `--evaluate-gate`, and `--evaluate-attribution` CLI modes, reading
`feature_vectors`/`forward_returns` and writing `construction_spreads` like everything else.
It is shadow-measurement only -- no live capital, deliberately not on a systemd timer (see
`docs/operations/operations-infrastructure.md`).

**Current state (2026-07-27, SUPERSEDED 2026-08-04 -- see "Correction, 2026-08-04" at the top of
this doc):** all three Validation Gates above were evaluated for real, and all three recorded a
PASS at the time. Gate 1 (shadow spread Sharpe) PASS, Gate 2 (attribution honesty) PASS, Gate 3
(comparison to per-symbol directional) already satisfied by regime_conditional_persistence's
falsification. **That PASS record is not currently trustworthy**: `ctf_momentum`, the sole
ranking feature both gates were measured against, was confirmed 2026-08-04 to carry real
lookahead in its batch join (todo 243) -- Gate 1/Gate 2 must be re-run under the corrected join
before the Phase 156-159 execution/sizing chain's precondition can be treated as met again.
**Do not begin Phase 168 (this construction's own cost-hurdle follow-on) or Phase 156-159 on
this record.** The next decision -- how and when to run the re-verification -- is the user's;
see todo 253 for the authoritative-tier prerequisite (`forward_returns` needs OOS-region rows,
which the normal pipeline never writes there by design) and the diagnostic-tier harness already
built (`scripts/analysis/phase167_gate1_ctf_join_fix_reverify_15m.py`).

## References

- `docs/research/archive/intel-11-dual-system-discrete-vs-portfolio.md` -- retired strategic frame (historical only)
- `docs/research/measurement-ic-engine.md` -- Cross-Sectional Rank IC addendum, cross_sectional_relative_value's falsification gate
- `docs/research/data-edge-source-thesis.md` -- thesis regime_conditional_persistence (falsified 2026-07-24), cross_sectional_relative_value (this doc),
  nonlinear_interaction_combiner (non-linear combiner) -- the full candidate comparison
- `docs/ideas/measurement-nonlinear-interaction-combiner.md` -- nonlinear_interaction_combiner, the sibling construction/
  modeling-change candidate to test alongside this doc
- `.planning/todos/completed/179-gate166-concurrent-exposure-diagnostic.md` -- regime_conditional_persistence's falsification,
  the finding that sharpened this doc's priority
- Todo 030 (cost-hurdle APR calibration) -- Step 0 cost floors feed the rebalance rule and the
  net-of-cost measurement; closed and removed from `.planning/todos/`, its result summarized in
  `docs/research/data-edge-source-thesis.md`
- `docs/plans/archive/2026-06-29-feature-scoring-beyond-ic.md` -- 0c calibration (sizing prerequisite),
  §4 effective breadth (why relative-value fits this universe)
- ROADMAP.md Phase 142A (scoping trigger), Phase 142B (the per-symbol directional counterpart
  this doc complements, not replaces)
- `docs/research/archive/vision-01-aegisagent.md`, `docs/research/archive/vision-05-tradeagent.md` -- commercial-product vision docs; see the Reuse Assessment section above for what transfers
  to a single-user version (todo 059, 2026-07-16)
- ROADMAP.md Phases 156-159 (v4.0 Execution Layer -- Portfolio State, Position Sizing & Risk,
  Live Execution, Cost Calibration) -- where the "transfers directly" items above should land
