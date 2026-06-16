# DAG Execution

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-05-30
**Tags:** dag, topological-sort, parallelism, plugin-dependencies

> Plugin dependencies are declared, not scheduled — a topological sort derives execution order and reveals parallelism automatically.

## The Problem It Solves

Manual plugin sequencing requires the developer to know all transitive dependencies. Adding a new plugin that sits between two existing ones requires editing sequencing code. At 132 plugins across 7 tiers, this is untenable — a single misordering produces wrong results with no error, and adding a plugin that reads from two tiers forces a human to figure out the correct insertion point in a hand-maintained list.

## The Principle

Declare the inputs and outputs for each node. A topological sort (Kahn's algorithm) derives the execution order automatically. Parallelism emerges from the graph: nodes with no unsatisfied dependencies run concurrently without any explicit scheduling code.

Kahn's algorithm:
1. Compute the in-degree of every node (count of upstream dependencies)
2. Add all nodes with in-degree 0 (no dependencies) to a ready queue
3. Process the queue: execute the node, decrement in-degree of all downstream nodes
4. If any downstream node's in-degree reaches 0, add it to the queue
5. If the queue empties before all nodes are processed, a cycle exists — fail immediately

The "acyclic" constraint is the critical property: data always flows forward. You cannot compute divergence (I5) before RSI (I1). You cannot score confluence (I6) before patterns (I5) and structure (I3). Cycles would be meaningless and are structurally impossible.

## How IndicAgent Applies It

Two levels of DAG execution operate simultaneously.

**Plugin DAG (within a bar, I1-I7):** The dependency graph is computed once at startup from each plugin's declared `inputs`/`outputs`. Cycle detection runs at startup and fails fast. Parallel waves execute plugins with no inter-dependencies simultaneously. 132 plugins run per bar without any explicit ordering code.

```
Raw OHLCV → I1 (no deps) → I2 (depends on I1) → I3 → I4 → I5 → I6 SMC → I6 Conf → I7
```

**Service DAG (across services, L1-L10):** 25+ microservices connected via Kafka topics. `_DAG_ORDER` in `services/service_auditor_agent.py` defines the canonical restart sequence — services earlier in the DAG restart before services that depend on them.

Both DAGs enforce the same invariant: data flows forward only. A plugin or service can never create a cycle.

## Invariants

- No plugin may declare a circular dependency. The DAG engine rejects cycles at startup — never at runtime.
- Execution order must be deterministic given the same dependency graph.
- The plugin DAG is computed once at startup — not recomputed per bar. Per-bar overhead is negligible.
- A plugin's `inputs` list is its contract: it may not read from tier outputs not listed there.
- `_DAG_ORDER` in `service_auditor_agent.py` is the single source of truth for service restart order — no parallel list anywhere.

## Recipe

When designing a DAG-executed system:

1. **Define node interface before implementation** — what does each node consume and produce? These declarations are the dependency graph.
2. **Choose cycle detection strategy** — startup-fail-fast is preferable to runtime detection. A cycle discovered at 3am during a live session is catastrophically worse than one caught at service startup.
3. **Decide granularity** — too-fine nodes create scheduling overhead; too-coarse nodes prevent parallelism. Tier boundaries (I1-I7) are natural granularity points.
4. **Consider optional vs. required inputs** — nodes that can run with partial inputs need explicit fallback behavior. Better to make inputs required and fail loudly.
5. **Separate the DAG from execution** — compute topological order once; apply it repeatedly. The sort is not free; per-event recomputation is waste.
6. **Validate at registration** — check that every declared input actually exists in the graph. Typos in dependency declarations create silent data gaps.

## The Seven Invariants in Practice

The principle above describes the theory. In IndicAgent, it materialises as seven non-negotiable architectural invariants — the operational expression of the DAG mandate:

1. `ProviderMerger` is the sole writer to `market.bars`
2. I1–I7 runs entirely in-process — Kafka is a sink, not an inter-stage pipe
3. Hot-path services are DB-ignorant
4. All topic keys via `stream_keys.py` — no hardcoded strings
5. No agent calls another agent directly
6. All timestamps UTC
7. Scaling via systemd + Prometheus lag — no Kubernetes HPA

These invariants are the reason the system can be fully replayed from a Kafka offset, the reason a DB outage has zero impact on signal generation, and the reason a new data provider requires zero downstream changes.

Full system map with Mermaid diagram, agent taxonomy, topic registry, and all invariant rationale: `docs/architecture/architecture-dag-topology.md`.

## See Also

- Implementation: `docs/intelligence/intelligence-plugins.md` — plugin DAG structure, wave execution, code
- Service DAG: `docs/architecture/architecture-dag-topology.md` — full system map and service invariants
- Principles: `docs/foundation/design-principles.md` — DAG mandate as Principle 11
- Code: `src/intelligence/dag.py`, `src/intelligence/register_plugins.py`
- Related concept: `docs/concepts/plugin-composability.md` — how plugins declare their interfaces
