# IndicAgent Master Plugin & Architecture Catalog

**Version:** 3.0
**Last Updated:** 2026-09-04
**Status:** Archived System — Historical Reference

> **ARCHIVED (v2.x, no live consumer since 2026-07-02).** Everything below describes the I1-I7 plugin pipeline as it was built and as its source still exists on disk — it is historically accurate, not currently executing. `indicagent-intelligence-pipeline.service` is `failed` (the file its `ExecStart` names, `services/intelligence_pipeline.py`, was renamed to `services/feature_vector_pipeline.py` in commit `911a1668c`). The live v3.0 compute path is Feature Factory (`src/intelligence/feature_factory.py`), which does not use `register_plugins.py` or the DAG engine described here at all. Do not cite this catalog as describing what the platform runs today; keep it for historical/reference value or for a future formal revival. See `docs/reference/plugins/overview.md` for the fuller archived-vs-live distinction and `src/intelligence/CLAUDE.md` for the canonical archived-system doc.

---

## 1. Architectural Philosophy: The "Why" (as designed, v2.x)

IndicAgent's v2.x intelligence tier was built on the **Plugin-Native Architecture** and **Event-Driven Microservices**. These principles describe the archived pipeline; the live v3.0 system reuses the event-driven-microservices principle (DAG Invariants in root `CLAUDE.md`) but replaced the plugin-DAG compute model with Feature Factory.

### Separation of Concerns (SoC)
SoC was an architectural invariant for this pipeline, not a coding guideline. Each service had exactly one reason to change and owned exactly one responsibility.
- **Microservice-Bound:** No service calls another directly. Services are producers and consumers on a durable Redpanda stream — this principle is still live-system-wide (DAG Invariant 5).
- **Decoupled Persistence:** The real-time pipeline never touches the database. Persistence was handled asynchronously by a dedicated writer — still true of the v3.0 pipeline (`FeatureVectorWriter`), just not `feature_writer_service` (that name belonged to the v2.x `intelligence_features` writer, itself archived).
- **DAG Execution:** Dependencies were declared, not hardcoded. The plugin registry detected cycles and ordering at startup via `registry.validate_tier()`.

### Plugin Protocol (The "How")
Plugins were stateless workers. The DAG engine used topological sort to ensure `I1` completed before `I2`/`I5` needed it.
- **Incremental Computing:** `compute_next()` enabled O(1) bar updates (141x speedup over recalculation, as measured at the time).
- **Typed Intelligence Bus:** Every tier output to a canonical `IntelligenceEvent` schema (tiered JSONB) — this schema (`src/intelligence/schemas.py`) is itself marked archived (v2.x, no live consumer) in root `CLAUDE.md`.

---

## 2. Plugin Catalog (133 items, as registered in the archived system)

Counts below are read directly from `len(TIER_I*)` in `src/intelligence/register_plugins.py`, verified 2026-09-04. They supersede the counts previously in this table (28/10/8/14/16/16/6/35 = 133, vs. the prior 28/11/9/13/16/13/1/37+2agg = 130) — the prior numbers were stale relative to current source, not a live-system regression.

| Tier | Focus | Count | Key Features/Logic |
| :--- | :--- | :--- | :--- |
| **I1** | Raw Technical | 28 | Incremental (RSI, MA, MACD, ATR, Bollinger, VWAP, OFI, CVD, etc.) |
| **I2** | Composites | 10 | Second-derivative events (Crosses, Accelerations, ExhaustionScore) |
| **I3** | Structure | 8 | Swing detection, Support/Resistance, Market Profile, FibZones |
| **I4** | Context/Regime | 14 | GARCH Vol, Kalman Trend, VIXRegime, CrossAsset, AnchoredVWAP, Macro |
| **I5** | Patterns | 16 | Divergence, Squeeze, Chart Patterns (H&S, Double Top) |
| **SMC**| Smart Money | 16 | BOS/CHoCH, FVG, Order Blocks, Liquidity Sweeps, ICT, HMM regime |
| **I6** | Confluence | 6 | Cross-timeframe alignment (CTF + 5 confluence sub-detectors) |
| **I7** | Trading Setups | 35 | Trend/Reversal/Liquidity logic |
| **Total**| — | **133** | — |

No separate "Aggregator" tier exists in `register_plugins.py` today (the prior table's "Agg: 2, CISScorer + SignalAggregator" row does not correspond to a `TIER_*` constant) — `CISScorer` lives in `src/intelligence/trading/cis_scorer.py`, adjacent to but outside the registered-plugin count.

---

## 3. Engineering Design Principles (I5-I7, as designed)

### I5: Pattern Tier
Focused on non-incremental, structural patterns. Used I1 feature snapshots.

### I6: Confluence Tier
Synthesized alignment across timeframes. Acted as the final decision gate before I7 setup detection.

### I7: Signal & Adjudication Funnel
1. **Candidate Fire:** Plugins detect setup conditions.
2. **Quality Gating:** RR gate + Regime gate (p-value, HMM probability).
3. **CIS Scoring:** Multi-bucket scoring (Trend, Momentum, Structure, Pattern, Institutional, Regime).
4. **Adjudication:** `SignalAggregator` selects winner via `perf_multiplier`.

---

## 4. Operational Maintenance (historical — this pipeline is not actively maintained)

### Verifying Plugin Count
Use the registry as the single source of truth: `src/intelligence/register_plugins.py`. This confirms the count as-written in source; it does not confirm anything is running.

### If This Subsystem Is Ever Revived
1. Confirm intent and scope first — root `CLAUDE.md` and `src/intelligence/CLAUDE.md` are the authorities on current archived/dormant status; check `systemctl status` and `git log` before assuming any part of this is live.
2. Registration in `register_plugins.py`.
3. Update to `src/intelligence/schemas.py` (also archived — verify it hasn't been superseded).
4. Update to this `catalog.md`.
