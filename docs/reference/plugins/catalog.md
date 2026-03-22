# IndicAgent Master Plugin & Architecture Catalog

**Version:** 2.0
**Last Updated:** 2026-03-22
**Status:** Unified Source of Truth

> This catalog serves as the single reference for IndicAgent intelligence capabilities. It contains the complete plugin list, architectural design principles, and the logic behind our pipeline.

---

## 1. Architectural Philosophy: The "Why"

IndicAgent is built on the **Plugin-Native Architecture** and **Event-Driven Microservices**.

### Separation of Concerns (SoC)
SoC is an architectural invariant, not a coding guideline. Each service has exactly one reason to change and owns exactly one responsibility.
- **Microservice-Bound:** No service calls another directly. Services are producers and consumers on a durable Redpanda stream.
- **Decoupled Persistence:** The real-time pipeline never touches the database. Persistence is handled asynchronously by `feature_writer_service`.
- **DAG Execution:** Dependencies are declared, not hardcoded. The system detects cycles and ordering at startup.

### Plugin Protocol (The "How")
Plugins are stateless workers. The DAG engine uses topological sort to ensure `I1` completes before `I2/I5` needs it.
- **Incremental Computing:** `compute_next()` enables O(1) bar updates (141x speedup over recalculation).
- **Typed Intelligence Bus:** Every tier outputs to a canonical `IntelligenceEvent` schema (tiered JSONB).

---

## 2. Plugin Catalog (125 Operational Items)

| Tier | Focus | Count | Key Features/Logic |
| :--- | :--- | :--- | :--- |
| **I1** | Raw Technical | 27 | Incremental (RSI, MA, MACD, ATR, Bollinger, VWAP, etc.) |
| **I2** | Composites | 11 | Second-derivative events (Crosses, Accelerations) |
| **I3** | Structure | 7 | Swing detection, Support/Resistance, Market Profile |
| **I4** | Context/Regime | 13 | GARCH Vol, Kalman Trend, BOCPD, VIXRegime, CrossAsset |
| **I5** | Patterns | 15 | Divergence, Squeeze, Chart Patterns (H&S, Double Top) |
| **SMC**| Smart Money | 13 | BOS/CHoCH, FVG, Order Blocks, Liquidity Sweeps, ICT |
| **I6** | Confluence | 1 | CTF Scorer (cross-timeframe alignment) |
| **I7** | Trading Setups | 36 | Trend/Reversal/Liquidity logic + Aggregator |
| **Agg** | Aggregators | 2 | CISScorer, SignalAggregator |
| **Total**| — | **125** | — |

---

## 3. Engineering Design Principles (I5-I7)

### I5: Pattern Tier
Focuses on non-incremental, structural patterns. Uses I1 feature snapshots.

### I6: Confluence Tier
Synthesizes alignment across timeframes. It acts as the final decision gate before I7 setup detection.

### I7: Signal & Adjudication Funnel
1. **Candidate Fire:** Plugins detect setup conditions.
2. **Quality Gating:** RR gate + Regime gate (p-value, HMM probability).
3. **CIS Scoring:** Multi-bucket scoring (Trend, Momentum, Structure, Pattern, Institutional, Regime).
4. **Adjudication:** `SignalAggregator` selects winner via `perf_multiplier`.

---

## 4. Operational Maintenance

### Verifying Plugin Count
Use the registry as the single source of truth: `src/intelligence/register_plugins.py`.

### Documentation Maintenance
All additions require:
1. Registration in `register_plugins.py`.
2. Update to `src/intelligence/schemas.py`.
3. Update to this `catalog.md`.
