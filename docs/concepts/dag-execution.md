# DAG Execution

**Last Updated:** 2026-04-22

## What Is a DAG?

A **Directed Acyclic Graph (DAG)** is a set of nodes connected by one-way edges with no cycles. The "acyclic" constraint is the critical property: data always flows forward. There is no path from any node back to itself, which means the system can always make progress and you can always reason about execution order.

In IndicAgent, every plugin is a node. Every data dependency between plugins is a directed edge. The result is a pipeline that is:

- **Deterministic** — given the same inputs and topological order, output is always the same
- **Traceable** — every value has a clear lineage back to raw OHLCV data
- **Safe** — cycles are impossible to introduce; the DAG engine rejects them at startup

---

## Why DAGs for Market Intelligence?

Market intelligence has a natural forward-only structure. You cannot compute a divergence (I5) before you have RSI (I1). You cannot score confluence (I6) before you have patterns (I5) and structure (I3). Circular dependencies would be meaningless — "RSI depends on divergence depends on RSI" has no stable solution.

A DAG gives you a clean way to:

1. **Model dependencies explicitly** — the graph is the specification
2. **Detect design errors early** — cycles fail at startup, not at runtime
3. **Enable parallel execution** — nodes with no shared dependencies can run concurrently
4. **Scale independently** — add plugins to any tier without touching others

---

## IndicAgent's Plugin DAG

The intelligence pipeline is a DAG of 123 plugins + 2 aggregation components across tiers I1–I7:

```
Raw OHLCV Data
      │
      ├──► I1 Technical Indicators (27 plugins, no dependencies)
      │         │
      │         └──► I2 Composite Events (10 plugins, 2 waves — depend on I1)
      │                   │
      │                   └──► I3 Market Structure (8 plugins, read OHLCV + I1/I2)
      │                               │
      │                               └──► I4 Context / Regime (12 plugins, 2 waves — GARCH → Kalman)
      │                                           │
      │                                           └──► I5 Patterns (16 plugins, read I1–I4)
      │
      └──► I6 SMC (13 plugins, 2 waves, read I1–I5 + OHLCV)
                │
                └──► I6 Confluence (1 plugin, cross-TF synthesis across all tiers)
                          │
                          └──► I7 Trading Setups (36 plugins + 2 aggregation, read I2–I6)
                                    │
                                    └──► I8 AI Narrative (LLM chain, reads I7 via intelligence.journal)
```

Edges flow only forward. No tier reads from a tier that comes after it.

---

## Topological Sort: Kahn's Algorithm

When the service starts, `src/intelligence/dag.py` runs **Kahn's algorithm** to produce a valid execution order:

1. Compute the **in-degree** of every node (number of upstream dependencies)
2. Add all nodes with in-degree 0 (no dependencies) to a ready queue
3. Process the queue: execute the node, decrement the in-degree of all downstream nodes
4. If any downstream node's in-degree reaches 0, add it to the queue
5. If the queue empties before all nodes are processed, a **cycle exists** — raise `ValueError`

The sorted list is computed once at startup and reused every bar. This makes per-bar execution overhead negligible.

```python
# src/intelligence/dag.py
def topological_order(self) -> list[str]:
    """Kahn's algorithm topological sort.
    Raises ValueError if DAG contains a cycle."""
    ...
```

---

## Execution Tiers in Practice

Because the DAG enforces ordering, services run each tier's plugins in sequence:

| Stage | Plugins | Runs When |
|-------|---------|-----------|
| I1 | RSI, MACD, ATR, OFI, CVD, etc. (27 plugins) | Every completed bar |
| I2 | RSIEvents, MomentumAccel (Wave A), AccelerationRegime/ExhaustionScore (Wave B) — 10 total | After I1 completes |
| I3 | MACDEvents, SwingDetector, SupportResistance, etc. (8 plugins) | After I1/I2 complete |
| I4 | GARCH/VIXRegime/CrossAsset (Wave A), KalmanTrend (Wave B) — 12 total | After I3 completes |
| I5 | MTFVolatility, RSIDivergence, BollingerSqueeze, chart patterns, etc. (16 plugins) | After I1–I4 complete |
| I6 SMC | BOS/CHoCH/FVG/OB/HMM (Wave A), SupplyDemandZones/BreakerBlocks/MitigationBlocks (Wave B) — 13 total | After I1–I5 complete |
| I6 Conf | CrossTimeframeConfluence (1 plugin) | After I6 SMC, reads multiple timeframes |
| I7 | TrendFollowing, MeanReversion, ORB15/30, OFI/CVD setups, etc. (36 plugins + 2 agg) | In IntelligencePipelineComputeAgent, after I6 |

Plugins within a stage that share no dependencies can execute concurrently. The DAG makes those safe-to-parallelize groups explicit.

**Service architecture:** I1–I7 all execute within `IntelligencePipelineComputeAgent` as a unified in-process pipeline. This eliminates inter-service Kafka latency for tight I6→I7 coupling. WriterAgents (FeatureWriterAgent, SignalWriterAgent) handle DB persistence separately.

---

## Cycle Prevention at Startup

The registry validates the DAG before any bars are processed:

```python
registry.validate_tier()  # hard-crashes on any missing plugin name
dag.topological_order()   # raises ValueError on cycle detection
```

This means misconfigured pipelines fail loudly at startup rather than producing incorrect results at runtime. The cost of a bug is a failed restart, not a silently wrong signal.

---

## Adding a Plugin to the DAG

To wire a new plugin into the execution graph:

1. Implement the plugin protocol (`compute_full`, `compute_next`, `outputs`, `inputs`)
2. Declare its `inputs` — which tier's outputs it reads
3. Register it in `src/intelligence/register_plugins.py` in the correct `TIER_I*` list
4. The DAG engine automatically places it in topological order

No manual ordering required. The graph infers the right position from declared dependencies.

---

## Related Documentation

- [Plugin Architecture](plugin-architecture.md) — plugin protocol, registry, incremental compute
- [Intelligence Tiers](intelligence-tiers.md) — what each tier computes
- [Incremental Computation](incremental-computation.md) — how plugins update state in O(1) per bar
- **Code:** `src/intelligence/dag.py`, `src/intelligence/register_plugins.py`
