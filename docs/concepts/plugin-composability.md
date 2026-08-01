# Plugin Composability

**Version:** 1.0
**Status:** stale (v2.x, see banner)
**Last Updated:** 2026-05-30
**Tags:** plugins, composability, extensibility, pipeline

> Intelligence is entirely composed of plugins — the pipeline shell is empty; adding intelligence means writing a plugin, not modifying core code.

> **Staleness note (2026-08-01):** This doc describes the `IntelligencePipeline` plugin
> protocol (`TIER_I1`..`TIER_I7` registration in `register_plugins.py`) as the live
> extensibility mechanism. That v2.x plugin tier has no live consumer as of 2026-07-02 per
> CLAUDE.md. Not yet rewritten for v3.0 -- tracked for a future doc pass, not fixed here.

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

## Invariants

- No intelligence logic belongs in the pipeline shell — only in plugins.
- Every plugin must be independently testable with synthetic inputs.
- Plugin registration (`register_plugins.py`) is the only coupling point — no other file imports a plugin by name.
- A plugin must never raise on bad input data — return `None` outputs instead.
- `supports_incremental = True` is only valid if `compute_next()` produces identical results to `compute_full()` over the same bars (verifiable by test).

## Recipe

When designing a plugin system for a new domain:

1. **Define the protocol before writing any plugins.** What are the inputs, outputs, and lifecycle hooks? This is the API that all future plugins will implement.
2. **Separate declaration from implementation.** Inputs and outputs are declarations — the shell uses them to build the execution DAG. Never let a plugin hardcode its position in an execution sequence.
3. **Registration is the only coupling point.** If a plugin file imports from the pipeline, you have coupling. Invert it: the pipeline discovers plugins via registration.
4. **Error isolation is mandatory.** One bad plugin must never crash the pipeline. Catch per-plugin, log with context, continue.
5. **Validate at startup.** Schema validation, cycle detection, and interface checks should fail the service at startup with a clear error, not produce wrong results at runtime.
6. **Version plugin outputs.** When a plugin changes its output field names or semantics, downstream plugins that depend on those fields need to be updated. Schema versioning makes this visible.

## See Also

- Implementation: `docs/intelligence/intelligence-plugins.md` — full plugin protocol, DAG structure, 132-plugin registry
- Code: `src/intelligence/register_plugins.py` — canonical tier lists and registration
- Related concept: `docs/concepts/dag-execution.md` — how plugin dependency declarations become execution order
- Related concept: `docs/concepts/incremental-computation.md` — how `compute_next()` achieves O(1) per bar
