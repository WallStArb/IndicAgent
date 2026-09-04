# Plugin Composability

**Version:** 2.0
**Status:** archived (implementation) — pattern superseded, not carried forward, see banner
**Last Updated:** 2026-09-04
**Tags:** plugins, composability, extensibility, pipeline, v2.x-archived

> Intelligence is entirely composed of plugins — the pipeline shell is empty; adding intelligence means writing a plugin, not modifying core code.

> **Rewritten for v3.0 (2026-09-04):** This doc described the `IntelligencePipeline` plugin
> protocol (`TIER_I1`..`TIER_I7` self-registration in `register_plugins.py`) as the live
> extensibility mechanism. That v2.x plugin tier has had no live consumer since 2026-07-02.
> Unlike other archived v2.x concept docs in this library, the composability *pattern* itself
> did not carry forward into v3.0 — it was deliberately rejected, not reimplemented. V3.0's own
> framing (`docs/intelligence/intelligence-alphaengine.md`): "138 plugins produced roughly 15
> genuinely independent views, because a human had already decided what 'confluence' meant
> before any data was measured... the fix is not better plugins, it's a different epistemology."
> The rest of this doc is kept as a design record of the pattern IndicAgent used to run and
> rejected — see "What Replaced It in v3.0" below for what extensibility looks like today.

## The Problem It Solves

Hardcoded intelligence logic cannot be extended without modifying the core pipeline. A monolithic pipeline where "add RSI divergence detection" means editing the main processing loop creates merge conflicts, entangles unrelated features, and makes it impossible to test individual intelligence components in isolation. At 132 plugins, this is untenable.

## The Principle

The pipeline shell declares a protocol and executes it. All intelligence is externalized into plugins that implement the protocol. The shell does not know what plugins do — it only knows their declared inputs and outputs. This separation means:

- Adding a new intelligence capability = writing a new plugin file, no other files touched
- Removing an intelligence capability = deleting a plugin file, no other files touched
- Testing an intelligence capability = testing the plugin class in isolation with synthetic inputs
- Changing execution order = updating the dependency declaration, no logic changes needed

The shell is responsible for DAG construction, execution ordering, state management, and error isolation. Plugins are responsible for exactly one thing: transforming inputs into outputs.

## How IndicAgent Applies It

**Plugin protocol:** Every plugin implements two methods:
- `compute_full(windows)` — full batch computation over a window of bars (warmup, O(N))
- `compute_next(windows)` — single-bar incremental update (post-warmup, O(1))

Plugins declare:
- `inputs` — which tier outputs they need (DAG dependency declarations)
- `outputs` — which fields they populate in `IntelligenceEvent`
- `supports_incremental` — whether `compute_next()` is available

**Registration:** Plugins self-register by being added to `TIER_I1`..`TIER_I7` lists in `src/intelligence/register_plugins.py`. This is the only coupling point between a plugin and the rest of the system.

**Shell-plugin separation:** `IntelligencePipeline` executes the DAG but contains no market intelligence logic. It handles state management, wave execution, error isolation, and metrics — not RSI or BOS or FVG computation.

**Error isolation:** Each plugin runs inside try/except. A plugin that raises is skipped for that bar; the pipeline continues. A plugin must return `None` outputs (not raise) when inputs are insufficient or warmup is incomplete.

**Startup validation:** `PluginValidator` checks all plugins at startup — output field names match schema, no DAG cycles, warmup requirements are valid. Fails fast; prevents silent bad-data propagation.

## Invariants (as they applied to the v2.x implementation — not enforced today)

- No intelligence logic belongs in the pipeline shell — only in plugins.
- Every plugin must be independently testable with synthetic inputs.
- Plugin registration (`register_plugins.py`) is the only coupling point — no other file imports a plugin by name.
- A plugin must never raise on bad input data — return `None` outputs instead.
- `supports_incremental = True` is only valid if `compute_next()` produces identical results to `compute_full()` over the same bars (verifiable by test).

## What Replaced It in v3.0

`register_plugins.py` and the `TIER_I1`..`TIER_I7` lists are gone with the rest of I5/I6/I7 — "no transitional shims, no parallel operation" (`docs/intelligence/intelligence-alphaengine.md`). What computes intelligence now is `FeatureFactory.compute()` (`src/intelligence/feature_factory.py`): a single stateless, pure function spanning roughly 8,600 lines that produces all ~298 `FeatureVector` fields from one call. There is no per-feature file, no self-registration list, no declared per-unit `inputs`/`outputs`, and no per-unit try/except shell — a handful of inline numeric guards (`_guard_counted`) substitute degenerate values, but nothing isolates one feature's bug from corrupting the whole `FeatureVector` row the way a plugin exception used to be caught and skipped.

This is a deliberate trade, not an oversight, and it maps onto why the plugin pattern was rejected rather than reimplemented:

- **Composability moved from software architecture to statistics.** The old model: a developer decides which named patterns (RSI divergence, BOS, confluence rules) exist and how they combine — that decision *is* the plugin file. The new model: the Feature Factory emits orthogonal, atomic measurements with no opinion about what matters; `ic_engine` and `ensemble_trainer` decide which features combine into an edge, weighted by measured IC. The composition step still exists — it just happens statistically, downstream, instead of architecturally, upstream, at plugin-registration time.
- **Extensibility is a schema migration, not a registration.** Per `docs/intelligence/intelligence-alphaengine.md`: "Adding a feature = schema migration, not a registration." Concretely: write a pure function inside `feature_factory.py`, add the field to `FeatureVector` (`src/intelligence/schemas.py`), and insert its `concept_registry` row (Unified Concept Registry genesis exemption — see `docs/foundation/unified-concept-registry.md`). There is no plugin file to add or delete, and no DAG-cycle validator to satisfy, because there is no plugin DAG.
- **Evidence gates promotion instead of a startup validator gating registration.** `PluginValidator`'s job — catch a broken unit before it reaches production — is now UCR's job: a new feature genesis-seeds as `candidate`/`active` at migration time, but only `ConceptRegistryService` can transition it later, gated by measured IC evidence, not by a schema check at process start.
- **The DAG got shallower, not deeper.** The old shell built a dependency graph across up to seven tiers of plugins. The new pipeline is one flat compute call followed by a handful of table-boundary stages (`feature_vectors` → `forward_returns` → IC → ensemble → `alpha_events`) — see `docs/concepts/progressive-intelligence-extraction.md`. There is no plugin-level DAG left to be composable within.

The net effect: IndicAgent still believes in decomposing a hard problem into independently-measurable units — that instinct didn't disappear. It just no longer expresses itself as a software plugin protocol. Read the Recipe below as a historical pattern IndicAgent tried and moved past for this specific problem (rule-based intelligence composition), not as current guidance for how to extend this codebase.

## Recipe (general pattern — not what IndicAgent does today; see banner)

When designing a plugin system for a new domain:

1. **Define the protocol before writing any plugins.** What are the inputs, outputs, and lifecycle hooks? This is the API that all future plugins will implement.
2. **Separate declaration from implementation.** Inputs and outputs are declarations — the shell uses them to build the execution DAG. Never let a plugin hardcode its position in an execution sequence.
3. **Registration is the only coupling point.** If a plugin file imports from the pipeline, you have coupling. Invert it: the pipeline discovers plugins via registration.
4. **Error isolation is mandatory.** One bad plugin must never crash the pipeline. Catch per-plugin, log with context, continue.
5. **Validate at startup.** Schema validation, cycle detection, and interface checks should fail the service at startup with a clear error, not produce wrong results at runtime.
6. **Version plugin outputs.** When a plugin changes its output field names or semantics, downstream plugins that depend on those fields need to be updated. Schema versioning makes this visible.

This recipe is still sound advice for a domain where the extensibility unit genuinely is a piece of hand-authored logic whose composition with other units is itself a design decision (rule engines, ETL transform chains, middleware stacks). It stopped being the right recipe for IndicAgent's feature layer once the composition decision moved from "which plugins does a developer wire together" to "which measured features does the data support" — see What Replaced It in v3.0 above.

## See Also

- Live equivalent: `docs/intelligence/intelligence-alphaengine.md` — "What Gets Cut" section; the direct statement that the plugin registry was replaced by a typed function library, not reimplemented
- Live pipeline: `docs/architecture/architecture-v3-alphaengine-pipeline.md` — full v3.0 layer detail
- Superseded implementation: `docs/architecture/architecture-v2-event-driven-pipeline.md` — the archived plugin-tier pipeline this doc describes
- Governance for the new extensibility path: `docs/foundation/unified-concept-registry.md` — evidence-gated feature lifecycle replacing `PluginValidator`
- Related concept: `docs/concepts/dag-execution.md` — how plugin dependency declarations became execution order (v2.x)
- Related concept: `docs/concepts/incremental-computation.md` — how the bounded-window/incremental-state split survived independently of the plugin protocol
- Related concept: `docs/concepts/progressive-intelligence-extraction.md` — the shallower v3.0 DAG that replaced the plugin-tier DAG
