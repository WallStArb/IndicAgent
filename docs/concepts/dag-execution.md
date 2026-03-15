# DAG Execution

**Last Updated:** 2026-03-11

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

The intelligence pipeline is a DAG of 98 plugins across 8 tiers:

```
Raw OHLCV Data
      │
      ├──► I1 Technical Indicators (25 plugins, no dependencies)
      │         │
      │         ├──► I2 Composite Events (10 plugins, read I1 outputs)
      │         │
      │         └──► I5 Patterns (14 plugins, read I1 features + I3 levels)
      │
      ├──► I3 Market Structure (8 plugins, read OHLCV directly)
      │         │
      │         └──► I4 Context / Regime (7 plugins, read OHLCV + optional I3)
      │
      └──► I6 SMC (13 plugins, read I1 features + OHLCV)
                │
                └──► I6 Confluence (1 plugin, cross-TF synthesis across all tiers)
                          │
                          └──► I7 Trading Setups (17 plugins, read I2–I6, in signal_generator_service)
                                    │
                                    └──► I8 AI Narrative (Ollama, reads I7 signals)
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
| I1 | RSI, MACD, ATR, SMA/EMA, Supertrend, etc. (25 plugins) | Every completed bar |
| I2 | MACDEvents, RSIEvents, MomentumAccel, etc. (10 plugins) | After I1 completes |
| I3 | SwingDetector, SupportResistance, SessionLevels, etc. (8 plugins) | Concurrent with I1 (reads OHLCV only) |
| I4 | VolatilityRegime, GARCHVolatility, KalmanTrend, etc. (7 plugins) | After I3 completes |
| I5 | RSIDivergence, BollingerSqueeze, chart patterns, etc. (14 plugins) | After I1 and I3 complete |
| I6 SMC | BOS/CHoCH, FairValueGap, HMMRegime, ICTKillzones, etc. (13 plugins) | After I1–I5 complete |
| I6 Conf | CrossTimeframeConfluence (1 plugin) | After I6 SMC, reads multiple timeframes |
| I7 | TrendFollowing, MeanReversion, LiquidityHunt, etc. (17 plugins + 2 agg) | In signal_generator_service, after I6 |

Plugins within a stage that share no dependencies can execute concurrently. The DAG makes those safe-to-parallelize groups explicit.

**Service boundary note:** I1 through I6 all execute within `market_analysis_service`. I7 runs in a separate `signal_generator_service` — it reads the `intelligence:SYMBOL:TF` stream produced by market_analysis_service. This boundary separates analysis from signal generation.

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
