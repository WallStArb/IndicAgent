# eAI-Style Evolutionary Optimization of APR Parameters — Idea

**Status:** Idea — not planned, gated on a specific precondition (see below), not ready to build.
Needs the same rigor pass any idea doc gets before promotion to `docs/research/`.
**Author:** Claude (Sonnet 5), interactive session, 2026-08-03.
**Origin:** User proposal, mid-session, following a `nonlinear_interaction_combiner` investigation
that found and quantified a real lookahead leak in `ctf_momentum` (todos 239/240/243/245).
Initially framed as "evolutionary AI agents with rules as genome"; the user then correctly
narrowed it to "eAI concepts applied to APR/variables — that's essentially all a genome is, the
parameters or the functions" after being shown why the broader agent-genome framing doesn't fit
this project's current architecture.

## What "agent" means in this framing — narrowed further, same session

Further clarified by the user mid-session: *"agent genomes just are the agent version of storing
some group of parameters that it uses to drive the APR and run some tests."* That's the correct,
minimal definition for this idea, worth pinning down explicitly rather than importing the
archived doc's fuller "agent" connotation (reasoning, prompts, tool use) by accident:

**An "agent" here is nothing more than a lightweight carrier for one candidate genome** — a
labeled vector of specific APR parameter values — that (1) loads those values in place of the
live APR reads `ic_engine.py`/`ensemble_trainer.py` would otherwise use, (2) runs the existing
measurement pipeline against them (a walk-forward IC/ensemble pass, same code path, no
reimplementation), and (3) reports a fitness score back from the existing statistical gates.
No reasoning loop, no LLM, no autonomy, no decision-making of its own. The population is a set
of parameter vectors; "reproduction" is producing new parameter vectors (mutation = perturb a
value, recombination = mix values from two fit parents); "an agent" is just the run-and-report
wrapper around one such vector. This keeps the entire "genome" concept exactly as narrow as
this idea doc's core claim: the genome *is* the parameters, nothing more needs to evolve.

## What this is

Apply the eAI (evolvable AI) framework already researched in
`docs/research/archive/ai-03-evolvable-ai-agents.md` and
`docs/research/archive/eai-phase-recommendations.md` — genome, fitness gates, breeding,
promotion/demotion, gene bank — but with the genome redefined as **a vector of Adaptive
Parameter Registry (APR) numeric values**, not agent chromosomes (prompts, model adapters, tool
sets, code).

## Why this is a materially better fit than the original vision, not just a smaller version of it

The archived docs were written May 2026 for the **v2.x LLM-agent swarm**
(`BaseAIWorker`/`alpha_swarm`/`narrative_swarm`). That substrate has been dormant since the v3.0
rebuild (2026-06-20); its surface form in v3.0 is still undecided per its own governing note
(`src/intelligence/CLAUDE.md`'s top banner). v3.0's actual live signal path
(`ic_engine` → `ensemble_trainer` → `alpha_publisher`) has no agents in it at all — there is
currently nothing for an "agent genome" to attach to.

APR-parameter evolution sidesteps that entirely and lands on something that **already exists,
already has a designed slot for exactly this, and was simply never implemented:**

- APR's own foundational doc (`docs/foundation/adaptive-parameter-registry.md`) states outright:
  *"ML discovery writes calibrated values back after sufficient sample sizes and p < 0.05."* The
  parameter lifecycle is literally `seed → operator_tuning → ml_learned → user_override →
  ml_learned again` — `ml_learned` has been a named, designed provenance category since Phase 109.
- Checked before writing this doc, not assumed: `grep -rn "ml_learned" src/ services/ scripts/`
  returns **zero hits**. Nothing writes `ml_learned` values anywhere in the live codebase. This
  is a confirmed, real gap in an already-designed system, not a hypothetical opportunity.
- The eAI doc's own risk ranking names the fitness function as *"the single most dangerous
  component... 80% of the effort"* and recommends building it before any reproduction is enabled.
  For APR-parameter fitness, that work is **already done and already trusted**: bootstrap-CI
  lower-bound gates, BH-FDR correction, walk-forward OOS discipline, multi-regime validation —
  the exact machinery Phase 148/167's OOS Proof Gates and `shadow_registry`'s promotion gate
  (n≥100, `bootstrap_ci_lower(pnl_r) > 0`) already use for every other promotion decision in this
  project. No new composite score needs to be invented or adversarially stress-tested from
  scratch.
- The genome itself is small and closed-form: a fixed, already-catalogued set of numeric APR
  keys (`config_schema`/`config_state`), not open-ended code, prompts, or tool sets. Candidate
  chromosome members (illustrative, not exhaustive): `alpha.ensemble.max_feature_weight`,
  `alpha.ic.shrinkage_k`, `alpha.ensemble.mv_condition_max`, `alpha.ensemble.max_cluster_weight`,
  `alpha.ic.bootstrap_block_size.{tf}`, embargo/lookahead calibration constants. CLAUDE.md's
  existing APR-exempt list (mathematical constants, schema identifiers, DAG topology) already
  defines what's *not* a legitimate mutation target — that boundary doesn't need to be redrawn.

In the original doc's own recommended build sequence, this maps to *"Phase 3 — Config parameter
mutation"* — but arrives there without needing Phases 1-2 (prompt mutation doesn't apply; the
fitness function doesn't need building) first. It is, in effect, the lowest-risk, most-ready
slice of the original eAI vision, reachable directly.

## The governance risk is real, not theoretical — today's own session is a live demonstration of it

The eAI doc's own words: *"A poorly specified composite score doesn't produce weak agents — it
produces agents that are excellent at gaming your scoring system... Agents that appear to perform
well by exploiting evaluation artifacts (look-ahead bias, data leakage, fitness function
loopholes) must be detected and hard-killed."*

This is not a hypothetical caveat here. Todo 245's diagnostic, run this same session, showed a
LightGBM tree's headline cross-sectional-neutral point_ic collapse 90.6% (0.1811 → 0.0171) once a
single lookahead-contaminated column (`ctf_momentum`) was removed from its inputs — the tree had
found and was disproportionately exploiting a data leak, not primarily genuine structure, and the
only reason this was caught is that the tree's `feature_importances_` happened to be legible
enough to trace back to one column. An automated search over APR parameters run against a corpus
with a known, unresolved integrity gap would very plausibly evolve *toward* whatever parameter
settings lean harder on that same contaminated signal — the identical failure mode, one level
removed from feature space into parameter space, and considerably harder to catch after the fact
because there's no single feature-importance number to trace it back to.

## Precondition — do not start before this clears

Todos 243/245 (`ctf_momentum` batch-join lookahead bias and its blast radius into
`nonlinear_interaction_combiner`) must be resolved — either the join is fixed and the corpus
recomputed, or a scoped, verified-clean measurement basis is otherwise established — before any
automated parameter search touches live `feature_ic_scores`/`ensemble_weights` data. Pointing an
optimizer at ground truth known to contain an unresolved leak is not a corner to cut; it is the
exact mechanism this project spent this session diagnosing, applied one level deeper.

## Sketch of what "Phase 3, adapted" would actually look like (not a plan — a shape)

1. **Genome definition:** enumerate the specific APR keys eligible for evolutionary tuning
   (ensemble weighting + IC-measurement calibration constants, not schema/DAG/mathematical
   constants) and their valid ranges.
2. **Fitness = existing gates, unchanged.** A candidate parameter set's fitness is whatever this
   project already uses to judge a construction or an ensemble weighting method: bootstrap CI
   lower bound on OOS point_ic, BH-FDR-corrected significance, multi-regime stability — reusing
   `ic_engine`/`ensemble_trainer`'s own measurement code paths, not a parallel implementation.
3. **Selection pressure design, explicit from day one (per the eAI doc's own governance
   section):** any candidate whose fitness gain traces disproportionately to a feature currently
   flagged under active data-integrity review must be excluded or down-weighted, not merely
   noted after the fact. This is the direct, concrete lesson from todo 245 — build the defense
   in before running the search, not as a post-hoc audit.
4. **Provenance:** every evolved parameter write goes through `config_history` with
   `changed_by='ml_discovery'` (or similar), same as every other APR write — `ml_learned` was
   designed for exactly this from the start.
5. **Human gate at promotion**, mirroring the eAI doc's "breeder scenario" discipline: automated
   fitness gates operate in shadow/candidate space; promoting an evolved parameter set to the
   value `ensemble_trainer.py`/`ic_engine.py` actually read live still requires explicit sign-off,
   not automatic replacement.

## Cross-refs

- `docs/research/archive/ai-03-evolvable-ai-agents.md` — the original eAI vision (agent genome);
  this idea is a narrower derivative, not a supersession — the original may still be relevant if
  v3.0's AI surface form is ever decided (see `src/intelligence/CLAUDE.md`'s dormant-stack note).
- `docs/research/archive/eai-phase-recommendations.md` — the phased build-out recommendations
  this idea's "Phase 3, adapted" sketch is grounded in.
- `docs/foundation/adaptive-parameter-registry.md` — the `ml_learned` provenance category this
  idea would be the first real implementation of.
- [todo 245](../../.planning/todos/pending/245-nonlinear-interaction-combiner-trains-on-lookahead-contaminated-ctf-momentum.md),
  [todo 243](../../.planning/todos/pending/243-ctf-momentum-batch-join-lookahead-bias.md) — the
  precondition this idea is gated on, and the live demonstration of why the gating matters.
