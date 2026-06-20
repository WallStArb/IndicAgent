# Phase 137: Feature Factory — Context

**Gathered:** 2026-06-20 (updated 2026-06-20)
**Status:** Ready for planning
**Source:** Council deliberation — Renaissance design principles applied

---

<domain>
## Phase 138oundary

Phase 137 delivers **one thing only:** a pure-function library (`FeatureFactory`) that computes 35 orthogonal primitives from raw OHLCV bars and persists them to a new `feature_vectors` hypertable. Phase 137 ends with a clean cutover: I5/I6/I7 is archived, plugin dispatch is removed from `IntelligencePipeline`, and a live bar is verified flowing through `FeatureFactory` into `feature_vectors`.

Phase 137 does NOT:
- Measure IC (Phase 138)
- Define or compute vector scores (Phase 138)
- Emit alpha events (Phase 139)
- Make any claim about which features predict returns
- Transform I7 plugins into alpha scorers (Phase 138 handles after IC discovery)
- Replace the existing live pipeline signal emission until the final cutover step — I7 runs until Phase 137's last deliverable

The output of Phase 137 is infrastructure, not evidence. A populated `feature_vectors` table proves that the machinery works — it proves nothing about whether any feature predicts price.

</domain>

<decisions>
## Implementation Decisions

### D-01: Trade Thesis Framing — Vectors Are Named Hypotheses, Not Ground Truth

**Decision:** The 35 primitives are grouped into named intelligence vectors (trade theses). A vector is a hypothesis: "these primitives together describe a coherent regime that may produce edge." Grouping is defined before IC measurement as an intellectual prior — not as a truth.

**What this means:** V1 Quant (the starting vector) is the hypothesis that quant price action primitives — momentum, range position, intra-bar conviction, vol dynamics — jointly predict short-horizon returns. The IC Engine in Phase 138 will either confirm or refute this hypothesis.

**What this does NOT mean:** vector membership determines ensemble weights. IC determines weights. The membership list is only a grouping for attribution and reporting. A primitive with zero IC contributes zero weight regardless of which vector it belongs to.

**Jim Simons' rule:** "We don't have preconceived notions. We look for things that can be replicated thousands of times." The vector is the precondition; IC is the replication test. Only one vector (V1 Quant) exists at Phase 137. V2 and beyond are added after V1 IC is proven, never before.

### D-02: V1 Quant is the Only Vector at Phase 137

**Decision:** Phase 137 builds all 35 primitives but only one vector is active: **V1 Quant (price action)**. No other vector is defined, seeded, or measured until V1 IC is empirically validated in Phase 138.

**V1 Quant constituent primitives (starting hypothesis):**
- `momentum_z_5` — 5-bar price velocity, z-scored
- `momentum_z_20` — 20-bar price velocity, z-scored
- `hma_slope_z` — smoothed momentum (Hull MA), z-scored
- `range_position` — close position within N-bar range
- `bar_close_pos` — intra-bar conviction (close vs high/low)
- `atr_z` — normalized volatility (baseline, not thesis)
- `vol_ratio` — 5-bar vol / 20-bar vol (vol momentum)
- `ctf_momentum` — cross-timeframe momentum alignment

**Not in V1:** all volume/flow primitives (ofi_z, cvd_slope_z, cmf, rel_volume, informed_flow, volume_z) — these belong to a future V2 Microstructure vector. Not in V1: structural primitives (vwap_dev_sigma, sr_support_dist, sr_resist_dist, poc_dist_atr, va_position) — these belong to a future V3 Structural vector. Not in V1: macro/cross-asset (vix_z, flight_quality, yield_slope_z) — future V3 Macro.

**Why this grouping:** V1 must be falsifiable in isolation. Mixing price action with flow data makes V1 IC ambiguous — you can't know if price or flow drove the result. Each vector must answer one distinct question. V1's question: does price itself carry forward-return signal?

### D-03: Vector Membership is APR-Governed, Changeable Without Code

**Decision:** Vector membership is defined in APR under `alpha.vector.v1_quant.members` as a comma-delimited list of primitive names. No primitive-to-vector mapping is hardcoded. The IC Engine reads membership at init via `ConfigService.get()`.

**Why:** Renaissance would never hardcode which inputs belong to which model. The membership is a hypothesis that the data may refute. If Phase 138 shows that `hma_slope_z` has negative IC in all regimes, it is removed from V1 by updating APR — no code change, no migration.

**Naming convention:** `alpha.vector.<vector_name>.members` — e.g.:
- `alpha.vector.v1_quant.members` = `"momentum_z_5,momentum_z_20,hma_slope_z,range_position,bar_close_pos,atr_z,vol_ratio,ctf_momentum"`

### D-04: `feature_vectors` Has No Vector Column — Primitives Only

**Decision:** `feature_vectors` stores raw computed values per primitive, not vector scores. There is no `vector` column, no `thesis` column, no aggregation at this layer. The schema is: `(symbol, tf, bar_ts)` → 35 typed float columns.

**Why:** Researcher interpretation must not contaminate the primitive layer. If `feature_vectors` stored "V1 score = 0.7," you have pre-baked a weighting decision into the data. Future IC measurement would be measuring a human-defined aggregation, not the raw signal. The Ledoit-Wolf solve in Phase 139 cannot work correctly on pre-aggregated data.

**The separation is absolute:** feature_vectors is the raw measurement layer. Vector scores are a derived analytical layer computed in Phase 138/C from primitives × IC weights.

### D-05: Phase 137 Does Not Touch `intelligence_features`

**Decision:** `intelligence_features` is the v2.x table. Phase 137 does not read from it, write to it, or depend on it. The source of truth for Phase 137 is `market_data_ohlcv` only.

**Why:** `intelligence_features` contains data computed by the backward-smoothing HMM (lookahead bias) and the old I1-I6 pipeline (researcher-defined feature combinations). Using it as a source would contaminate `feature_vectors` with the same structural flaws v3.0 is designed to eliminate.

### D-06: Historical Backfill is a Hard Gate Before Phase 138

**Decision:** Phase 138 (IC measurement) does not begin until the full backfill is verified at target depths: 58 ETFs × 4 TFs, row counts within 5% of theoretical maximum. This is not a preference — it is a correctness requirement.

**Why (from IC spec §III):** IC Sharpe requires 10 non-overlapping windows × 500 observations = 5,000 minimum independent observations per (symbol, TF). A 5m backfill over 5 years = ~98,280 bars → ~19,656 independent observations at N=5 lookahead. Anything less produces IC confidence intervals wider than the signal itself, making the walk-forward validation statistically meaningless.

**Verification criterion:** SQL count check per (symbol, tf) vs theoretical bar count at target depth. Log the per-symbol shortfall. Any symbol with < 80% of theoretical bars gets flagged and excluded from Phase 138 IC measurement (not blocked, just excluded with a known gate).

### D-07: HMM Uses Forward Viterbi Only — No Backward Smoother

**Decision:** `regime_label_source = 'filtered'` in all `feature_vectors` rows. The backward smoother (which uses future observations to smooth the regime path) is banned. This is a causal correctness requirement, not a preference.

**Why:** The backward smoother produces the best regime labels in hindsight. It cannot reproduce what the system would have known at bar t using only bars ≤ t. IC measured against smoother-derived labels is measuring a counterfactual that cannot exist in production. Every IC estimate would be optimistic relative to what is achievable. This is a correctness failure, not an optimization choice.

**Enforcement:** `regime_label_source` column in `feature_vectors` is constrained to `{'filtered', 'unknown'}`. Any write with `'smoothed'` raises a DB constraint violation.

### D-08: `FeatureFactory` is a Pure Function Library — No Side Effects

**Decision:** `FeatureFactory.compute(bars: list[Bar], symbol: str, tf: str) -> FeatureVector` is a pure function. No DB reads. No Kafka reads. No state mutations. All computation from the `bars` argument only.

**Why:** The intelligence pipeline calls this synchronously per bar. Any IO in the hot path violates the DAG invariant. State (e.g., rolling windows) is managed by the caller (`IntelligencePipeline`), not by `FeatureFactory`. The pure-function contract enables deterministic unit testing without mocks.

**APR loading:** APR keys (periods, z-score windows) are loaded once at pipeline init via `ConfigService.get()` and passed to `FeatureFactory` as a `FeatureFactoryConfig` frozen dataclass. `FeatureFactory` does not call `ConfigService` at compute time.

### D-09: I5/I6/I7 Archived at End of Phase 137 — No Shadow Period

**Decision:** Phase 137 ends with a cutover step: `IntelligencePipeline` switches from `PluginRegistry.process_bar()` to `FeatureFactory.compute()`, and all I5/I6/I7 code is moved to `src/intelligence/archive/`. This is Phase 137's final deliverable, not Phase 138's opening task.

**I7 runs live until cutover.** During Phase 137's development work (build, backfill, test), the existing I7 pipeline continues emitting signals to `signal_events`. The cutover is a discrete final step, not a gradual transition.

**No shadow/parallel period.** Shadow mode is appropriate when replacing an equivalent system and comparing outputs. I7 and FeatureFactory are not equivalent — I7 emits trading signals; FeatureFactory computes primitives. They write to different tables (`signal_events` vs `feature_vectors`). There is nothing to compare. Validation happens through: (1) unit tests on FeatureFactory outputs, (2) backfill verification on historical data, (3) live bar smoke test confirming real-time data flows through correctly.

**Cutover is atomic:** wire FeatureFactory into `IntelligencePipeline`, remove plugin dispatch, archive I5/I6/I7 — all in one deploy.

**Archive scope:** All I5, I6, I7 code is moved to `src/intelligence/archive/` **intact without modification**. No plugin is deleted. Phase 138 IC discovery determines which I7 plugins carry signal and survive as alpha scorers; Phase 138 prunes the rest. Phase 137's job is clean archival, not selective deletion.

**Why archived instead of deleted:** The v2.x plugins represent years of domain knowledge about market structure. The pattern definitions (e.g., what constitutes an anchored VWAP reversion) may inform future vector design decisions in Phase 138. They are preserved as institutional memory, not as active code.

**What "not running" means:** `IntelligencePipeline` calls `FeatureFactory.compute()` per bar. There is no call to `PluginRegistry.process_bar()`. I7 plugins do not fire. `signal_events` is not written by the live pipeline after cutover. The v2.x signal infrastructure continues to exist as tables — they are not dropped.

### D-10: Attribution Loop Architecture — Kafka-Native

**Decision:** `alpha_events` (emitted in Phase 139) carries a `vector_contributions` dict keyed by vector name, with IC-weighted contribution to the composite alpha score. The external execution platform receives this on Kafka. When a trade resolves, the platform publishes `outcome_events` on a return Kafka topic including `alpha_event_id`, `vector_name`, and `counterfactual_pnl_r`. The IC Engine (Phase 138, enhanced in Phase 139) joins outcomes back to vectors to update rolling IC.

**This is the thesis attribution loop the council demands:** vector fires → outcome observed → P&L attributed to thesis by name → vector IC re-measured → IC-weighted ensemble weight updated. No human judgment in the loop. The data closes the loop.

**Phase 137 scope:** Phase 137 does not implement this loop. It is noted here because the `feature_vectors` schema and `FeatureVector` dataclass must be designed with this downstream attribution in mind. No decisions made in Phase 137 should block the attribution loop.

### D-11: One Backfill Job, All 58 ETFs — Not Sequential Restarts

**Decision:** The historical backfill runs as a single job with checkpoint/resume capability. If interrupted, it resumes from the last completed (symbol, tf) pair. It does not restart from scratch.

**Why:** 58 ETFs × 4 TFs = 232 (symbol, tf) pairs. At estimated compute time per pair, interruption without resume would be operationally unacceptable. The backfill job writes a `backfill_status` record per (symbol, tf) with status `{pending, in_progress, complete, failed}`. The job skips `complete` pairs on resume.

### D-12: `feature_writer` Reused — Writes to `feature_vectors`, Not `intelligence_features`

**Decision:** The existing `feature_writer` service infrastructure (batching, error handling, TimescaleDB connection pooling, DLQ) is reused. Its write target is changed from `intelligence_features` to `feature_vectors`. No new writer service is built.

**Why:** The writer infrastructure is proven. Building a new one would replicate proven engineering to produce identical behavior. The change is: new table name, new schema, new APR namespace for batch size parameters.

### D-13: `pipeline_version` Migration on `intelligence_features` — Resolved, No Action Needed

**Decision:** No migration is needed on `intelligence_features`. `feature_vectors` already has `pipeline_version` in its DDL (Phase 137 FeatureFactory sets it on every INSERT). `intelligence_features` is not used in v3.0 — it is the v2.x table, read by nothing in Phase 137 or beyond.

**Why this was asked:** The STATE.md from the methodology session noted "pipeline_version migration required on `intelligence_features` before Phase 137." This was resolved during the council methodology review: the IC spec §IV.1 confirmed that `feature_vectors` carries `pipeline_version` natively, making any migration on `intelligence_features` unnecessary. The resolution is recorded here to close the open item.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Architecture
- `docs/plans/2026-06-20-v30-ground-up-architecture.md` — ground-up design: what's thrown away, Feature Factory spec, three-layer architecture, build order
- `docs/plans/2026-06-20-v30-system-design.md` — technical component spec: `feature_vectors` schema, FeatureVector contract, "What Jim Simons Demands" section
- `docs/plans/2026-06-20-v30-alphaengine-ic-spec.md` — IC methodology: §II (data inventory Phase 137 must produce), §III (backfill gate and N requirements), §III.3 (regime stratification requirement), §IV.1 (pipeline_version resolution)
- `docs/plans/2026-06-20-v30-alphaengine-strategy.md` — strategic "why": V1-V4 vector rationale, intelligence vector orthogonality principle, phasing A-E justification
- `docs/plans/2026-06-20-v30-i7-transition.md` — I7 transition path: what retires vs survives; archival approach for Phase 137; alpha scorer transformation for Phase 138. Read before planning the archival step.

### Runtime
- `src/core/database_manager.py` — TimescaleDB connection pooling (reuse pattern)
- `src/intelligence/schemas.py` — existing typed bus schemas (do not duplicate)
- `src/config/settings.py` — `get_active_contracts()` (58 ETFs, `is_active = true`)
- `services/feature_writer.py` — existing writer to extend (D-12)
- `src/intelligence/intelligence_pipeline.py` — pipeline wiring point for `FeatureFactory.compute()` call
- `docs/foundation/adaptive-parameter-registry.md` — APR pattern for `feature.*` and `alpha.vector.*` keys

### Data
- `docs/foundation/glossary.md` — canonical term definitions before naming anything new

</canonical_refs>

<specifics>
## Specific Decisions

### Feature primitive organization (from architecture doc, binding)

35 features across 5 cadence groups. All names are final — they are schema column names:

**Bar-level (14):** `momentum_z_5`, `momentum_z_20`, `range_position`, `bar_close_pos`, `gap_z`, `informed_flow`, `volume_z`, `ofi_z`, `cvd_slope_z`, `cmf`, `rel_volume`, `vwap_dev_sigma`, `atr_z`, `vol_ratio`

**Session-level (4):** `poc_dist_atr`, `va_position`, `sr_support_dist`, `sr_resist_dist`

**Regime-level (7):** `hmm_regime_prob`, `hmm_entropy`, `hurst`, `shannon`, `garch_ratio`, `hma_slope_z`, `adx`

**Cross-asset (3):** `vix_z`, `flight_quality`, `yield_slope_z`

**Calendar (5):** `in_ny_session`, `in_overlap`, `dow_sin`, `dow_cos`, `month_position`

**Cross-timeframe (3) — CTF from HTF cached state:** `ctf_momentum`, `ctf_vwap_align`, `ctf_regime_align`

**Total: 36 columns** (35 features + `pipeline_version` metadata column)

### V1 Quant vector — starting membership hypothesis (APR-governed, mutable)

`alpha.vector.v1_quant.members`: `momentum_z_5,momentum_z_20,hma_slope_z,range_position,bar_close_pos,atr_z,vol_ratio,ctf_momentum`

This seeded value is a starting hypothesis. Phase 138 IC measurement may remove members with negative or insignificant IC.

### `feature_vectors` table — new hypertable, no JSONB

Schema must be all typed columns. No JSONB blobs. Every primitive is a first-class column. Schema defined in `docs/plans/2026-06-20-v30-system-design.md` — planner reads that as ground truth.

Chunk interval: 3 months. Compression policy: compress after 6 months. Retention: indefinite (IC measurement requires years of data).

### Pipeline change: one call replaces the plugin registry

Before Phase 137: `IntelligencePipeline` calls `PluginRegistry.process_bar(bar)` → 138 plugin calls.
After Phase 137: `IntelligencePipeline` calls `FeatureFactory.compute(bars, symbol, tf)` → 1 function call → 35 typed outputs.

The DAG topology is unchanged. Feature Factory is an in-process computation unit. `feature_writer` subscribes to the Kafka topic carrying `FeatureVector` events and persists to `feature_vectors`.

### Phase 137 cutover done gate

Phase 137 is complete when ALL of the following are true:
1. `feature_vectors` row counts within 5% of theoretical max per (symbol, tf) at target depths
2. A live 1m bar produces a `FeatureVector` row in `feature_vectors` (smoke test)
3. `src/intelligence/archive/` contains all I5, I6, I7 code
4. `IntelligencePipeline` has zero references to `PluginRegistry.process_bar()`
5. Unit tests green

</specifics>

<deferred>
## Deferred — Explicitly Out of Phase 137 Scope

- **IC measurement** — Phase 138. Phase 137 produces data; Phase 138 asks what the data means.
- **V2, V3, and beyond** — no vector is defined or seeded until V1 IC is proven. See D-02.
- **Vector score computation** — Phase 138 derives these from primitive IC weights.
- **Attribution loop (Kafka return path)** — Phase 139 architecture. Phase 137 must not block it (D-10), but does not implement it.
- **Alpha Decay Monitor** — post-Phase 139. Cannot monitor decay before IC is measured.
- **Analog Engine** — separate system; shares `market_data_ohlcv` but has no Phase 137 dependency.
- **Portfolio construction, Kelly sizing** — out of scope for v3.0 on this platform. Live execution and position sizing run on the external platform connected via Kafka.
- **I7 alpha scorer transformation** — Phase 138. Phase 137 archives I5-I7 intact without modification. Phase 138 IC discovery determines which I7 plugins carry positive IC and converts them to score producers (removes emission decision logic, preserves feature computation and directional conviction). Phase 137 creates no `alpha_scorers/` directory — that belongs to Phase 138.
- **I5/I6/I7 deletion** — archived but preserved. Deletion requires IC proof that the new system surpasses the old. That is Phase 139 or later.

</deferred>

---

*Phase: 137-feature-factory*
*Context gathered: 2026-06-20 — Renaissance council deliberation*
*Context updated: 2026-06-20 — I7 cutover timing, canonical refs, pipeline_version resolution*
