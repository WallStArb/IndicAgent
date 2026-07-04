# MeasurementEngine — Where the Unification Actually Stands

**Version:** 1.0
**Status:** draft — investigates a proposal whose own decision window has already partially
closed; written to answer "is this still worth pursuing," not to assume yes
**Priority:** high (both `intel-12` and `intel-13` build on "the Measurement Engine" as a
settled arrival without either one defining it)
**Milestone:** none currently — this doc's job is to determine whether one is warranted
**Last Updated:** 2026-07-03
**Tags:** ic-engine, measurement, predictor, ensemble-ic, kernel-extraction, concept-registry,
cross-sectional-ic
**Source:** `.planning/research/2026-07-02-v3-topdown-architecture.md` §2.3, §3 (D1, D2, D11) —
Author: Fable 5
**Informed by:** Fable 5 - audit corrections (kernel coverage, `alpha_ensemble_ic` consumers and
row count, config-drift evidence, intel-12/13 characterization), Open Questions 1-2 resolved,
design revisions marked *(Fable's revision)* inline (2026-07-02)

---

## Why This Doc Exists

The topdown architecture review calls this "the single highest-leverage structural change
available" (§1, point 1) — yet it never got its own doc. It exists as one paragraph inside a
much larger review, and its own text contains a deadline that has already passed: *"Because
alpha_ensemble_ic (migration 187) has not landed yet and feature_ic_scores is a derived table
rebuilt every corpus run, the unification window is open now and closes when 142A executes."*

Phase 142A executed. `services/ensemble_ic_engine.py` exists, 830 lines, its own `BaseBatch`
entry point, its own DAG node (`indicagent-ensemble-ic-engine`). That is exactly the standalone
service D1's sibling decision (D2) argued against building. Two of the three docs written this
session — `docs/ideas/intel-12-stratification-dimension.md` and `docs/ideas/intel-13-analog-engine.md` —
both flag "the Measurement Engine" as proposed at first mention, then build on its arrival as
if settled: intel-13 stakes its "zero new measurement code" IC Factory claim on
`predictor_ic_scores` and predictor registration, neither of which exists. This doc's job is to
find out what actually happened, whether the gap matters, and if so, what closing it still
costs.

Verdict, stated up front: the codebase landed on the exact fallback D1 pre-authorized (shared
kernel + two tables), so most of D1's value already exists. What remains actionable is one small
refactor (shared config loader, below) plus two deliberate deferrals with named triggers: table
merge waits for a free rebuild window with no in-flight phase keyed to either schema; service
merge waits for a predictor at a grain neither engine serves. A second finding outranks the
unification question itself: three verified gaps in measurement correctness and richness
(trailing IC, IC vintage, cross-sectional effective N) plus two unscheduled scoring layers
(marginal contribution, calibration); see "The Measurement Gaps That Outrank Unification."

---

## What Actually Happened (verified against the code, not the proposal)

Checked directly, not assumed:

| D1's proposed piece | Status | Evidence |
|---|---|---|
| One stats kernel library, zero I/O, zero APR reads | **Built for the IC core; not the full hygiene chain** | `src/intelligence/statistics/ic_math.py` — Fisher-z CI, vectorized Spearman IC, p-values, HAC-corrected Sharpe/Sortino/win-rate, `SharpeWindowConfig` Protocol for duck-typed config access. Pure functions, no DB, no module-global mutable state. D1's kernel spec also listed corpus-level BH-FDR and walk-forward folds; those remain per-engine: both engines call `statsmodels.multipletests` independently, and fold construction is duplicated (the fold-stability *gates* deliberately differ per D-142A-R1, so that part is divergence by decision, not drift). |
| Both engines import the shared kernel | **Built** | `ic_engine.py:84` and `ensemble_ic_engine.py:75` both import from `ic_math.py`; `ops_oos_holdout_eval.py:49` is a third consumer. |
| One config dataclass | **Not built** | `ICEngineConfig` and `EnsembleICConfig` are two separate frozen dataclasses, each independently declaring the same 11 APR-backed fields (`fdr_alpha`, `walk_forward_folds`, `sharpe_window_size`, `sharpe_min_windows`, `subsample_min_stride`, `min_reliable_n`, `hac_max_lag`, all four lookahead gradients) plus a per-service `n_workers` (different `infra.*` keys by design, correctly not shared). `EnsembleICConfig`'s own docstring calls these out as "shared ICEngineConfig-style keys" — the duplication is acknowledged in a comment, not resolved. The fallback defaults have already drifted: `sharpe_min_windows` falls back to 10 in `ICEngineConfig.from_apr` and 30 in `EnsembleICConfig.from_apr` (live APR value: 30), latent only because config_state wins. |
| One `predictor_ic_scores` table | **Not built** | `feature_ic_scores` and `alpha_ensemble_ic` are fully separate schemas at different grains: feature-vintage PK (`feature_name, symbol, tf, regime, lookahead_bars, training_window_end`) vs event-vintage PK (`event_row_id, scored_at`). No `predictor_kind`/`predictor_ref` discriminator anywhere in the codebase. Even `is_pooled` semantics differ: `alpha_ensemble_ic` CHECK-constrains it to `symbol = 'POOLED'`; in `feature_ic_scores` it also covers per-symbol regime-pooled rows. |
| One orchestration service | **Not built** | Two separate `BaseBatch` services, two separate DAG nodes in `service_auditor.py` (`indicagent-ic-engine`, `indicagent-ensemble-ic-engine`), confirmed oneshot-and-inactive-between-runs is correct for both independently. |
| Predictor abstraction (`predictor_kind`/`predictor_ref`, anything claims to predict registers uniformly) | **Not built** | No trace anywhere in the codebase. |

**How this happened:** methodology unity was a deliberate 142A choice; the kernel module was
not. 142A's own docstring says it "Composes the SAME corrected IC methodology as ic_engine.py,"
and it did so by importing `ic_engine.py`'s underscore-prefixed "private" functions directly,
with `EnsembleICConfig` mirroring `ICEngineConfig`'s shape "by convention, not by import" (its
own comment). Commit `0d30dd28` ("fix(047,048): parallelize ensemble_ic_engine.py's DB fetch,
extract shared IC math, consolidate APR loader," 2026-07-02 16:48) then extracted `ic_math.py`
during the 142A `/simplify` review, for a narrower, purely hygiene-driven reason stated in the
module's own docstring: three Ring 2 consumers (`ic_engine.py`, `ensemble_ic_engine.py`,
`ops_oos_holdout_eval.py`) were each reaching into one module's internals. The extraction turned
a fragile deliberate reuse into a proper shared module; it produced the kernel-library piece of
D1's proposal as a side effect of routine cleanup, with no reference to D1 anywhere in the
commit.

---

## What This Means: The Unification Window Didn't Fully Close, It Landed on the Fallback

D1's own text pre-authorized exactly this outcome as an acceptable fallback if migration
friction proved too high mid-milestone: *"shared kernel library + two tables... the unified
table is the honest top-down answer and it is cheap this week"* — implying the fallback is what
happens when that week passes. The week passed. The fallback is what got built. That's not a
failure to execute D1 — it's D1's own contingency plan, arrived at organically rather than
deliberately.

**So the real question isn't "was D1 followed," it's "is further unification still worth
pursuing now, given what already exists, or did the window close for real."** Three components
remain genuinely unbuilt (config, table, service), each with a different cost/benefit now that
142A has shipped:

### Config unification — cheap, low-risk, worth doing regardless of anything else

`ICEngineConfig` and `EnsembleICConfig` sharing 11 fields by copy-paste is exactly the kind of
drift risk this project's own principles warn about: an APR key rename or default change
applied to one config and not the other silently desyncs the two engines' math on the same
underlying statistics. This is not hypothetical; the fallback defaults have already diverged
(`sharpe_min_windows`: 10 vs 30, latent only because config_state carries the real value).

*(Fable's revision)* The drift does not live where a Protocol can see it. A Protocol checks
field names and types; the desync risk lives in the two `from_apr` bodies, in duplicated APR
key strings and fallback defaults, which structural typing cannot inspect. The right shape is
a shared frozen base dataclass carrying the 11 shared fields plus one shared loader,
`load_shared_ic_fields(get) -> dict`, in `services/_batch_utils.py` (already the consolidated
APR-loader home from todo 048b), parameterized by a getter callable so it serves both loading
mechanisms (`ic_engine` binds `ConfigService.get_sync`; `ensemble_ic_engine` binds its raw-dict
`_cfg` reader). Each engine's `from_apr` composes the shared dict and adds its own fields;
`n_workers` stays per-engine (deliberately different `infra.*` keys). `SharpeWindowConfig` in
`ic_math.py` stays as-is; it solves a different problem (keeping the kernel free of config
imports). No schema migration, no service-restart semantics to reconsider, no risk to in-flight
corpus runs. **Recommendation: do this regardless of the table/service decision below.** It is
cheap now and gets more expensive the longer two independently-maintained copies of the same
key strings and defaults exist.

### Table unification (`predictor_ic_scores`, D11) — the real cost/benefit question

This is where "the window closed" is genuinely true in a way config unification isn't.
`alpha_ensemble_ic` (migration 195, not 187 as D1's text estimated) is now a shipped schema
with production code keyed to it: the 830-line writer, the EIC-04/EIC-05 scripts
(`ops_ensemble_ic_gate.py`, `ops_ensemble_ic_diagnosis.py`), and 142B.1's in-flight plans
(142B.1-05 keys its A/B win rule directly on `alpha_ensemble_ic` columns). The table itself is
empty today (zero rows as of 2026-07-02; it repopulates each IC pipeline run), so the retrofit
cost is not data history. It is:

- Every code consumer above needing its queries rewritten
- A real schema reconciliation, not a rename: the two tables live at different grains
  (feature-vintage `training_window_end` vs event-vintage `event_row_id, scored_at`), shape
  walk-forward facts differently (`walk_forward_stable` boolean vs
  `wf_fold_count`/`wf_pass_count`/`passes_walkforward`), and define `is_pooled` differently
  (strictly `symbol = 'POOLED'` vs also covering per-symbol regime-pooled rows)
- Timing: 142B.1 is mid-flight and its plans assume this schema; 142B.1-05 additionally expects
  a `weight_version` key the current table lacks, i.e. the schema is still evolving inside the
  phase. Merging tables under an in-progress phase keyed to both is the worst possible moment.

Against that cost, the benefit D1 claimed — "one estimator = commensurable gates across
features/ensemble/analogs" — is still real and still matters for exactly the two docs that
already assume it (`intel-12`'s substitution test, `intel-13`'s analog predictor IC
measurement). Both would need to run *some* query against *some* IC table either way; the
question is whether that's one unified query shape or two structurally similar but separately
maintained ones.

**Recommendation: do not force this now.** The coupling is in shipped code and an in-progress
phase, not in data. The honest path forward is the one D11 already named as acceptable:
keep two tables, keep them structurally parallel via the now-shared `ic_math.py` kernel (so a
methodology fix like Phase A's automatically applies to both), and revisit table unification the
next time a full corpus rebuild is already scheduled AND no in-flight phase is keyed to either
schema; that is when the migration is closest to free again, per D11's own logic ("derived
table, rebuilt every corpus run, the rename is nearly free exactly once").

### Service unification — lowest priority; the trigger is a new measurement grain, not a count

Two `BaseBatch` services with two DAG nodes is a real but small cost (one more systemd unit,
one more entry in `_LAG_THRESHOLDS`/`_AGENT_ID_TO_UNIT`) — not obviously worth collapsing on its
own.

*(Fable's revision)* The original framing here was "revisit when a third predictor kind
arrives." That is the wrong trigger. What actually forced `ensemble_ic_engine.py` into
existence was not that alpha_score is a different *kind* of predictor but that it lives at a
different *grain*: event rows in `alpha_events`, not feature columns at (symbol, tf, bar_ts).
`ic_engine.py` measures anything at feature grain generically already. intel-13's analog
predictors, as planned, land at exactly feature grain (`feature_vectors` columns or a sibling
table joined at measurement time), so they ride `ic_engine.py` with at most a join; they never
justify a third engine, and "a third predictor kind" may arrive without ever reopening this
question. The genuinely new case is a predictor at a grain neither engine serves; intel-13's
cross-TF `alignment_z`/`coherence` at (symbol, bar_ts) is the first candidate on the roadmap.
**Recommendation: defer, with the default stated now so it isn't decided by accident later:**
feature-grain predictors go through `ic_engine.py`, and only a predictor at a new grain reopens
the choice between a third standalone service and one orchestration shell parameterized by
`--predictor-kind`.

---

## What Intel-12 and Intel-13 Should Actually Say

Both docs flag the Measurement Engine as proposed at first mention (intel-12 line 116 says
"proposed L4 unification" outright; intel-13 says "the proposed Measurement Engine"), then
build on its arrival as if settled. Given the above, the accurate framing is narrower and
should be corrected wherever it's cited:

- **What's real today:** a shared statistics kernel (`ic_math.py`) that both `ic_engine.py` and
  `ensemble_ic_engine.py` already use, meaning a methodology fix in the kernel-covered math
  (IC, CI, HAC Sharpe family) structurally applies to both without separate implementation.
  BH-FDR application and walk-forward fold construction are outside the kernel and still
  per-engine; a fix there must still be applied twice.
- **What's not real today:** a single service, a single table, or a predictor-registration
  abstraction that a regime-dimension substitution test or an analog-predictor IC measurement
  could plug into generically.
- **What this means concretely for intel-12's substitution test:** it runs against whichever
  engine currently owns regime-stratified feature IC (`ic_engine.py`), using the shared kernel
  — not a separate "Measurement Engine" call. No blocker; just don't call it something that
  doesn't exist yet.
- **What this means concretely for intel-13's analog predictor IC:** its "zero new measurement
  code" claim survives, but for a different reason than it states. There is no predictor
  registration mechanism and no `predictor_ic_scores` to register into; the claim holds because
  the planned analog predictors land at feature grain, where `ic_engine.py` already measures
  any column generically. The cross-TF `alignment_z`/`coherence` scores are the exception (own
  grain) and are the first candidates that would reopen the service-unification question above.

Neither intel-12 nor intel-13 is blocked by any of this — both correctly describe consumer-side
behavior (stratify by a dimension, measure a predictor's IC) that doesn't require knowing
whether one service or two implements it underneath. But both should stop treating a unified
`MeasurementEngine` service and `predictor_ic_scores` table as things that will exist as
designed, and cite what is real instead (the kernel for shared math, `ic_engine.py` as today's
judge) when next touched.

---

## The Measurement Gaps That Outrank Unification

*(Fable's revision: added on the doc owner's request to fold in the older measurement
research.)* Two pre-topdown research docs bear directly on this doc's question and were not
referenced in it: `docs/plans/archive/2026-06-29-ic-engine-improvements.md` (a P0-P6 audit of
`ic_engine.py` itself) and `docs/plans/archive/2026-06-29-feature-scoring-beyond-ic.md` (layers 0a/0b/0c:
what IC alone cannot see). Checked against current code and DB, the improvements audit is 4/7
executed: Phase A shipped P0 (walk-forward contamination), P2 (corpus-level BH-FDR), P3
(scale-specific embargo), and P4 (single-linkage clustering, `method="single"` at
`ic_engine.py:414`). What remains open are gaps in the measurement itself, not in how many
services compute it; that makes them more load-bearing to "is the ensemble trustworthy" than
anything in the unification question above:

| Gap | Status (verified 2026-07-02) | Why it matters |
|---|---|---|
| **P1: trailing IC series** (`ic_trailing_series`, 60-trading-day rolling window) | Not built; no such table exists | The ensemble weighter reads one static IC number per cell with zero recency signal; it cannot distinguish "worked for 5 years, dead for 6 months" from "working now." Source doc scopes it as its own phase at roughly 60x the compute of a static run. |
| **P5: IC vintage** (`training_window_start` column) | Not built; `feature_ic_scores` has only `training_window_end` | A 2019-2023 estimate is silently treated as equally valid as a 2023-2026 one. The source doc itself notes P1 supersedes this for recency-sensitive use; P5 is the cheap schema-only fallback. |
| **P6: cross-sectional effective N** (`N_eff = N_raw / (1 + (n_symbols-1)·rho_bar)`) | Not built. The `n_eff` near `ic_engine.py:1501` is a metrics gauge reporting existing `n_independent`, not this correction | 58 symbols on the same bar share regime/macro exposure and are not 58 independent observations; CIs on POOLED cross-sectional rows are overconfident. Affects POOLED rows only. |
| **0a: marginal contribution** (partial IC after regressing out the active set) | Not built, unscheduled (todo 029 pending) | Standalone IC admits features that add zero marginal value over what the ensemble already holds. |
| **0b: shrinkage** (`ic_shrunk`, empirical-Bayes toward peer-group prior) | Not built, but **scheduled**: 142B.1 D-04 builds it as E1's first wave, 2 new columns on `feature_ic_scores`, with the out-of-fold acceptance test as a hard gate (D-05) | Corrects winner's-curse bias on every persisted estimate. The one piece of the beyond-IC doc with a committed home. |
| **0c: calibration** (reliability curve / Brier on predicted magnitude) | Not built, unscheduled | IC says the ordering correlates; calibration says the magnitude is honest, which is the property position sizing (Kelly) actually depends on. |

Note on 0b, stated precisely because it looks like a blocker and isn't: `ic_shrunk` does not
exist in `feature_ic_scores` today, and 142B.1's E1 variant is specced to consume it, but
142B.1's own CONTEXT.md already scopes building it in-phase (D-04/D-05/D-07), so this is
scheduled work inside the phase, not a missed dependency. The unification-relevant consequence
of this whole table is different: **each of these layers, when built, changes what a
"commensurable gate" means, and each will face the same question the kernel already answered
for the HAC/Fisher-z math**: does it land once in `ic_math.py` (or a sibling kernel module)
and get consumed by both engines, or does it get built inside one engine and recreate exactly
the per-engine methodology drift D1 was written to prevent? 142B.1's shrinkage estimator is the
first test of this: D-07 currently scopes it as columns on `feature_ic_scores` only.

---

## Addendum: Cross-Sectional Rank IC (T3 Falsification Mode)

**Added 2026-07-03**, extracted from `docs/ideas/intel-11-dual-system-discrete-vs-portfolio.md`
on its retirement (`.planning/research/2026-07-03-intel10-11-fable-review.md`, F8/R2) — a
Measurement Engine mode, not a separate track or system.

**The asymmetry this closes:** per-symbol directional trading is the hardest way to monetize a
small IC — it requires each symbol's signal to overcome that symbol's full volatility plus market
beta. Cross-sectional long-short on the 58-ETF universe is far more forgiving: relative-value
ranking cancels idiosyncratic noise and hedges beta, so an IC too weak to trade directionally can
still pay as a spread. Edge thesis T3 (`docs/ideas/edge-source-thesis.md`) — relative mispricing
across correlated instruments — is only testable through this measurement, and a time-series-only
system would silently conclude "no edge" while a spread on the same features pays.

**The minimal falsification instrument (measure first, construct later):**

1. **Cross-sectional rank IC as a kernel mode.** Per-bar Spearman of `alpha_score` (or any
   predictor) against forward returns *across the 58-symbol universe*, aggregated over bars, with
   the cross-sectional effective-N correction `edge-source-thesis.md` §P6 already flags as missing
   (58 correlated symbols on one bar are not 58 independent observations — this is the same P6 gap
   named in the Measurement Gaps table above, now with a second consumer). A kernel extension,
   weeks not quarters — bolt it onto `ensemble_ic_engine.py` as it stands if the kernel-unification
   decision (Open Questions, this doc) is still open; don't wait on that decision to run this.
2. **A counterfactual decile-spread simulation** in the 142B frame machinery — long top decile,
   short bottom decile, dollar-neutral, at the executable-return definition, cost-hurdle applied
   per leg. This is `alpha_frames` with a portfolio-shaped frame variant, not a new system.

**Decision rule:** if (1) shows cross-sectional IC materially exceeding time-series IC and (2)
shows the spread paying net of the cost floor, a portfolio-constructor design doc becomes
warranted — with evidence in hand rather than institutional analogy. If not, the thesis dies
cheaply, without ever having required a parallel "PortfolioTrack" system. Per the `one model, one
book` principle (`docs/foundation/principles.md`), this measurement's output is an input to the
single forecast, never a second book — see intel-10's rewrite for how a confirmed cross-sectional
effect would be consumed as a predictor, the same way a confluence is.

---

## Open Questions

Resolved in this pass *(Fable's revision)*:

1. **Protocol vs base dataclass for the shared config: base dataclass plus shared loader.**
   A Protocol checks field names and types; the observed drift lives in APR key strings and
   fallback defaults inside the two `from_apr` bodies, which structural typing cannot see
   (`sharpe_min_windows` fallback already diverged, 10 vs 30). `SharpeWindowConfig` stays as a
   Protocol because it solves a different problem. See the config section for the mechanism.
2. **`ops_oos_holdout_eval.py` config duplication: checked, minimal.** It has no config
   dataclass; it reads three shared keys inline (`fdr_alpha`, the four per-scale lookaheads,
   plus its own `oos_significant_drop_fraction`) via `load_config_service_sync`. A third copy
   of the key strings, but not of the 11-field block. Fold it into the shared loader when the
   file is next touched; not a blocker for the config work.
3. **Third service vs orchestration shell: reframed.** The trigger is a predictor at a grain
   neither engine serves, not a third predictor kind (see the service section). Default until
   then: feature-grain predictors ride `ic_engine.py`.

Genuinely open: measurement-methodology research this doc's scope touches but cannot settle.

4. **Is trailing IC (P1) affordable at current corpus scale?** ~60x a static run over ~232
   (symbol, tf) pairs. `alpha.ic.trailing_step_bars` (stride) is the obvious lever; nobody has
   measured what step size preserves enough recency resolution to be worth having. A one-symbol
   pilot would answer both cost and value cheaply before committing a phase.
5. **Does P6's effective-N correction change any gate outcomes today?** The correction shrinks
   N on POOLED rows, widening CIs; the question is whether any currently-passing POOLED cell
   flips to failing. A one-off diagnostic (compute rho_bar per tf, recompute the CI gate) would
   answer this without schema changes, and the answer determines P6's priority.
6. **What shrinkage prior grain actually wins?** Todo 029 specs the prior as the feature
   family x regime x tf peer-group mean; 142B.1's hard gate (shrunk must predict next-window IC
   better than raw) tests the mechanism but not the grain choice. If the gate fails, the grain
   is the first suspect, and no fallback grain is specced.
7. **Does winner's-curse correction apply at ensemble grain too?** 142B.1 selects a champion
   per (tf, regime) stratum among E1-E4 variants; selection among variants is itself a search,
   so the winning variant's measured IC in `alpha_ensemble_ic` is upward-biased by the same
   mechanism 0b corrects at feature grain. Nothing in 142B.1's plans addresses this; if real,
   the shrinkage estimator belongs in the shared kernel, not in `ensemble_trainer.py`.
8. **What replaces a static IC number as the weighter's input once P1 exists?** Trailing IC,
   vintage-weighted static IC (P5), and shrunk IC (0b) are three different answers to "what is
   this feature's IC *now*"; they overlap, and nothing yet says how they compose or which
   wins. Needs a decision before more than one of them ships, or the ensemble weighter
   accumulates competing recency mechanisms.

---

## References

- `.planning/research/2026-07-02-v3-topdown-architecture.md` §2.3 (L4 — the Measurement Engine
  proposal in full), §3 D1/D2/D11
- `src/intelligence/statistics/ic_math.py` — the kernel that already exists; its own docstring
  is the authoritative record of why it was extracted (todo 048, not D1)
- `services/ic_engine.py`, `services/ensemble_ic_engine.py` — the two still-separate
  orchestration services and their still-separate config dataclasses
- Commit `0d30dd28` — "fix(047,048): parallelize ensemble_ic_engine.py's DB fetch, extract
  shared IC math, consolidate APR loader" — the actual, unplanned origin of the kernel extraction
- `docs/ideas/intel-12-stratification-dimension.md`, `docs/ideas/intel-13-analog-engine.md` —
  both build on "the Measurement Engine" arriving as designed; both need their references
  corrected per the section above when next touched
- `.planning/todos/pending/032-ic-engine-pure-function-refactor.md` - still fully open, NOT
  superseded by 047/048: it asks for three specific extractions (`build_walk_forward_folds`,
  `compute_ic_for_window`, `apply_corpus_fdr`: fold construction, single-window IC, FDR
  application), none of which exists anywhere; the 047/048 commit extracted a different set of
  functions. Doing todo 032 is exactly what closes the "kernel covers the IC core but not the
  full hygiene chain" gap in the status table above.
- `docs/plans/archive/2026-06-29-ic-engine-improvements.md` - the P0-P6 audit; P0/P2/P3/P4 executed by
  Phase A, P1/P5/P6 open (see gaps section)
- `docs/plans/archive/2026-06-29-feature-scoring-beyond-ic.md` + `.planning/todos/pending/029-feature-scoring-beyond-ic.md`
  - layers 0a/0b/0c; 0b scheduled inside 142B.1 (CONTEXT.md D-04/D-05/D-07), 0a/0c unscheduled
- `.planning/phases/142B.1-*/142B.1-CONTEXT.md` - E1 shrinkage scope and hard acceptance gate;
  `ops_ensemble_ic_gate.py`/`ops_ensemble_ic_diagnosis.py` - the actual `alpha_ensemble_ic`
  consumers today (EIC-04/EIC-05)
