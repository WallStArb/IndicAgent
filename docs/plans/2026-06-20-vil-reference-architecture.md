# VIL Reference Architecture
# Vector Intelligence Layer + Intelligence Vectors + Extrinsic Confidence

**Date:** 2026-06-20
**Status:** Design — approved, pre-implementation
**Milestone:** v3.0
**Supersedes:** `2026-06-20-intelligence-vectors-architecture.md` (absorbed into this doc)

---

## Framing

The existing I1-I7 pipeline is sophisticated feature engineering. What it has never done is ask the most fundamental question: **does any of this actually predict price?**

Every bar is processed as if it is the first bar. RSI reads 67, regime is trending, CTF is aligned, a signal fires — then the bar closes, price moves, and the system forgets. The intelligence state at that bar and the outcome that followed are never connected.

This architecture closes that loop. It does not replace the existing pipeline — it adds the empirical measurement and retrieval infrastructure that makes the pipeline's output provably useful rather than intuitively plausible.

The two prior design efforts (VIL: `vil-01` through `vil-06`, and Intelligence Vectors: `2026-06-20-intelligence-vectors-architecture.md`) describe the same architecture from two angles. This document unifies them.

- **Intelligence Vectors** = the WHAT: four orthogonal alpha source dimensions; the IC engine that measures them; the ensemble that combines them
- **VIL** = the HOW: the retrieval substrate that makes IC measurement, analog finding, and scoring possible across all four vectors

The IC Engine in the Intelligence Vectors doc IS vil-02's IC Factory. Phase C's ensemble IS vil-05's Signal Combiner. VIL is the substrate beneath all four Intelligence Vectors.

---

## What Jim Simons Demands (Non-Negotiable Constraints)

These govern every design decision in this document. Violating any of them produces a system that looks correct but isn't.

**1. Measure first, deploy second.**
No predictor enters the ensemble without measured IC on real corpus data. Building the ensemble before IC measurement is guess-weighted averaging, not edge.

**2. IC Sharpe, not IC.**
The Sharpe of the IC time series is the trust weight. A predictor with IC=0.04 and IC Sharpe=1.2 compounds. One with IC=0.07 and IC Sharpe=0.3 oscillates and erodes net. Stable IC beats high volatile IC.

**3. Effective-N, not signal count.**
Two correlated predictors are one predictor with noise. Correlation is measured from embedding similarity, not assumed from tier membership or plugin names. The ensemble is weighted by independence, not count.

**4. Rolling windows everywhere - no static backtests.**
IC is measured on a trailing window (last 500 observations or 90 days, whichever is larger). All normalization for embeddings is point-in-time rolling z-score. Global or full-history normalization is look-ahead contamination and silently invalidates every downstream study.

**5. The null result is first-class.**
"We have not seen conditions like this" is a valid, important output. The OOD (out-of-distribution) monitor surfaces it. Consumers widen conviction intervals. No silent fallback to nearest-available regardless of distance.

**6. Alpha decay is monitored and self-corrects.**
Rolling IC that drops below threshold triggers automatic APR weight reduction to zero. Human review is flagged. Recovery is automatic when IC recovers with sufficient N. The system adapts without manual intervention.

**7. Regime conditioning everywhere.**
IC is measured per regime. Retrieval is filtered by regime. Scores are stratified by regime. A predictor with IC=0.08 in trending and IC=-0.02 in ranging is a trending predictor only — not a general predictor.

**8. Shadow before live — always.**
Every new predictor enters `shadow_registry` at `is_shadow=True`. Promotion to live influence requires `bootstrap_CI_lower > 0.0` at `n >= 100`. No exceptions.

**9. Every score is decomposable.**
The composite score must be traceable to contributing features, their IC weights, the analog set, and which regime conditioned the retrieval. Black-box composites are not permitted.

**10. The hot path never reads from the analytical layer.**
The only feedback channel from cold batch back to the hot pipeline is APR — a slow control plane read at startup/refresh. Per-bar reads of analytical tables in the hot path are a DAG violation.

---

## Full DAG Topology

Three distinct data planes. Data flows in one direction only. No cycles. The only cross-plane feedback is APR.

```
═══════════════════════════════════════════════════════════════════
HOT PATH  (existing, unchanged)
Sub-millisecond. DB-ignorant. Never reads analytical tables.
═══════════════════════════════════════════════════════════════════

IBKR TWS
  └─ BarWriter              → market_data_ohlcv
  └─ I1-I7 in-process       → intelligence_features
      └─ I7 plugins          → signal_events  (ECL annotations attached at fire time:
          └─ TradeFramer     → trade_frames    ctf_score, ctf_confirmed,
              └─ CFLTracker  → trade_frames    zone_friction_score, hmm_regime)
                               .counterfactual_pnl_r


═══════════════════════════════════════════════════════════════════
COLD BATCH  (new analytical microservices - systemd timers)
Reads hot-path sinks. Writes analytical state. Never on the tick path.
═══════════════════════════════════════════════════════════════════

  bar-embedder        reads: intelligence_features
                      writes: embeddings (entity_type='bar')
                      schedule: nightly

  plugin-embedder     reads: signal_ledger (90-day plugin direction×confidence history)
                      writes: embeddings (entity_type='plugin')
                      schedule: nightly

  signal-embedder     reads: signal_events.context_features
                      writes: embeddings (entity_type='signal')
                      schedule: nightly

  outcome-labeler     reads: market_data_ohlcv
                      writes: outcome_labels (T+5/10/20/60 R-multiples)
                      schedule: nightly

  ic-factory          reads: embeddings + outcome_labels
                      writes: feature_ic_stats
                               (IC, IC Sharpe, FDR, decay_flagged
                                per plugin × TF × regime × lookahead)
                      schedule: weekly

  correlation-svc     reads: embeddings (entity_type='plugin')
                      writes: similarity_pairs
                              effective_n_scores
                      schedule: weekly

  scoring-engine      reads: embeddings + feature_ic_stats + outcome_labels
                      writes: score_cache (Score Objects per bar/symbol/tf)
                      schedule: nightly

  signal-combiner     reads: score_cache + effective_n_scores
                      writes: ensemble_alpha
                      schedule: nightly

  signal-enricher     reads: score_cache (by bar_ts + symbol + tf)
                      writes: signal_events.analog_score,
                              signal_events.analog_count,
                              signal_events.analog_conviction_lower,
                              signal_events.ood_flagged
                      schedule: nightly (cold enrichment — never at fire time)


═══════════════════════════════════════════════════════════════════
CONTROL PLANE  (slow feedback - hours to days, not per-bar)
Reads analytical state. Writes APR. Hot path reads APR at init.
═══════════════════════════════════════════════════════════════════

  alpha-decay-monitor  reads: feature_ic_stats (rolling window)
                       writes: APR (vil.weights.* → zero on IC decay)
                       alerts: OTel → Grafana
                       schedule: daily

  ml-discovery         reads: score_cache, ensemble_alpha
                       writes: APR (ensemble thresholds, regime weights)
                       schedule: weekly

  APR (config_state)  ──── hot pipeline reads at init/refresh ────▶
                           IntelligencePipeline._prewarm_threshold_config()
```

**The invariant stated plainly:** hot path writes; cold batch reads hot and writes analytical state; control plane reads analytical state and writes APR; hot path reads APR. Arrows point one direction. No layer reaches backward.

---

## Intelligence Vector Taxonomy

The four-vector frame is an organizational taxonomy over VIL consumers. Each vector is a set of plugins that embed into the same substrate and are measured by the same IC Factory. Adding a new vector means adding new plugins — the infrastructure does not change.

**V1: Quant** — existing I1-I7 plugins (138 plugins, measurable immediately after Phase 133)

Mathematical indicators, composites, structure, context, patterns, confluence, signal plugins. `factor_scores` from `signal_events` are the feature vectors. IC Factory runs against `counterfactual_pnl_r` from the rebuilt corpus. This is the first vector measured. It gates everything else.

**V2: Microstructure** — partially exists (OFI, CVD already in I1)

Order flow imbalance, CVD slope, trade size distribution (institutional vs retail ratio), spread-normalized return. Orthogonal to price patterns by construction — microstructure responds to WHO is trading, not what the chart looks like. The cross-feature correlation between OFI score and RSI score is near zero by design. Extend existing I1 microstructure plugins to emit continuous scores.

**V3: Macro** — partially exists (I4 cross-asset and macro context)

Cross-asset relationships, VIX term structure, yield curve shape. Already computed in `ctx_CrossAssetContext` and `ctx_MacroContext`. The shift: from binary regime flags to continuous scored vectors. IC measured independently of V1/V2.

**V4: Calendar** — new, trivially orthogonal

Day-of-week effects, month-end rebalancing window (+/- 2 days EOM), options expiry week (gamma suppresses realized vol), index reconstitution period, earnings blackout periods. Purely time-based — zero correlation with V1/V2/V3 by construction. New I1-tier plugins. Lowest implementation cost of any vector.

**Orthogonality is measured, not assumed.**
`correlation-svc` computes `similarity_pairs` across all plugin embeddings regardless of which vector they belong to. If a V2 plugin is correlated with a V1 plugin (correlated features → correlated embeddings), the effective-N calculation accounts for it. The vector taxonomy describes data sources; independence is empirically verified.

---

## Microservice Decomposition

Each service does one thing. Services communicate through tables only — no direct service-to-service calls.

| Service | Systemd unit | Schedule | SoC boundary |
|---------|-------------|----------|--------------|
| `bar_embedder` | `indicagent-bar-embedder` | Nightly | Serialization only — no IC, no scoring |
| `plugin_embedder` | `indicagent-plugin-embedder` | Nightly | 90-day history → L2 vector |
| `signal_embedder` | `indicagent-signal-embedder` | Nightly | Signal context features → L2 vector |
| `outcome_labeler` | `indicagent-outcome-labeler` | Nightly | Forward returns only — no interpretation |
| `ic_factory` | `indicagent-ic-factory` | Weekly | IC measurement only — no weight decisions |
| `alpha_decay_monitor` | `indicagent-alpha-decay-monitor` | Daily | Detects decay, writes APR — no trading logic |
| `correlation_service` | `indicagent-correlation-service` | Weekly | Similarity pairs + effective-N only |
| `scoring_engine` | `indicagent-scoring-engine` | Nightly | Transform only — no retrieval inside |
| `signal_combiner` | `indicagent-signal-combiner` | Nightly | Ensemble alpha only — no scoring logic |
| `signal_enricher` | `indicagent-signal-enricher` | Nightly | Cold annotation only — never at fire time |

All services are oneshot workers following the D-06 pattern: emit `job_completed_total{job=<unit-suffix>, status}` at exit on success and failure. All log to `logs/<snake_case_class_name>.log`. All numeric parameters through APR under `vil.*` namespace.

**The scoring-engine boundary Simons would enforce hardest:** it receives an analog set as input (produced by a retrieval step) and transforms it. It does NOT execute the k-NN query internally. Retrieval and transformation are separate concerns even if they eventually run in the same process. The Analog Finder (a thin retrieval wrapper) produces the analog set; the Scoring Engine transforms it into a Score Object.

---

## Schema

### Prerequisites

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

The pgvector binary is already compiled into `timescale/timescaledb:latest-pg18` (v0.8.2). This is a one-time DDL — no image change required.

### New Tables

```sql
-- VIL substrate (as specified in vil-01-vector-intelligence-layer.md)

CREATE TABLE embeddings (
    entity_type       TEXT        NOT NULL,  -- 'bar', 'plugin', 'signal'
    entity_id         TEXT        NOT NULL,  -- (ts||symbol||tf), plugin_name, signal_id
    scope             TEXT        NOT NULL,  -- 'global', 'ES', '1m', 'trending'
    embedding_version INTEGER     NOT NULL,
    computed_at       TIMESTAMPTZ NOT NULL,
    embedding         vector(128) NOT NULL,  -- L2-normalized; dim fixed per entity_type
    PRIMARY KEY (entity_type, entity_id, scope, computed_at)
);
CREATE INDEX ON embeddings USING hnsw (embedding vector_cosine_ops);

CREATE TABLE outcome_labels (
    entity_type   TEXT        NOT NULL,
    entity_id     TEXT        NOT NULL,
    horizon_bars  INTEGER     NOT NULL,  -- 5, 10, 20, 60
    ret_r         DOUBLE PRECISION,
    direction     INTEGER,               -- +1 / -1
    regime        TEXT,
    symbol        TEXT,
    tf            TEXT,
    labeled_at    TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (entity_type, entity_id, horizon_bars)
);

CREATE TABLE similarity_pairs (
    entity_type    TEXT             NOT NULL,
    entity_a       TEXT             NOT NULL,
    entity_b       TEXT             NOT NULL,
    scope          TEXT             NOT NULL,
    cosine_sim     DOUBLE PRECISION NOT NULL,
    co_event_count INTEGER          NOT NULL,
    computed_at    TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (entity_type, entity_a, entity_b, scope),
    CHECK (entity_a < entity_b)
);

-- IC measurement (supersedes plugin_ic_scores from Intelligence Vectors doc)
CREATE TABLE feature_ic_stats (
    plugin_name         TEXT             NOT NULL,
    timeframe           TEXT             NOT NULL,
    hmm_regime          TEXT,                       -- NULL = all regimes
    lookahead_bars      INTEGER          NOT NULL,
    ic_value            DOUBLE PRECISION,
    ic_sharpe           DOUBLE PRECISION,
    ic_ci_lower         DOUBLE PRECISION,
    ic_ci_upper         DOUBLE PRECISION,
    fdr_adjusted_p      DOUBLE PRECISION,
    decay_flagged       BOOLEAN          DEFAULT FALSE,
    n_observations      INTEGER,
    computed_at         TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (plugin_name, timeframe, lookahead_bars, computed_at)
);

-- Correlation / independence
CREATE TABLE effective_n_scores (
    plugin_set_hash  TEXT             NOT NULL,  -- stable hash of sorted plugin names
    regime           TEXT,
    tf               TEXT,
    effective_n      DOUBLE PRECISION NOT NULL,
    computed_at      TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (plugin_set_hash, computed_at)
);

-- Score Objects (vil-03 output)
CREATE TABLE score_cache (
    bar_ts              TIMESTAMPTZ      NOT NULL,
    symbol              TEXT             NOT NULL,
    tf                  TEXT             NOT NULL,
    scope               TEXT             NOT NULL,  -- 'global', plugin, TF, asset
    level               INTEGER          NOT NULL,  -- 0=plugin, 1=symbol+tf, 2=symbol cross-tf, 3=cross-asset
    directional_hr      DOUBLE PRECISION,
    expected_r          DOUBLE PRECISION,
    sharpe_horizon      DOUBLE PRECISION,
    alignment_z         DOUBLE PRECISION,           -- L2 only: cross-TF agreement
    composite_z         DOUBLE PRECISION,
    percentile_rank     DOUBLE PRECISION,           -- cross-sectional rank; headline metric
    conviction_lower    DOUBLE PRECISION,
    conviction_upper    DOUBLE PRECISION,
    analog_count        INTEGER,
    mean_distance       DOUBLE PRECISION,
    ood_flagged         BOOLEAN          DEFAULT FALSE,
    computed_at         TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (bar_ts, symbol, tf, scope, level)
);

-- Ensemble alpha (vil-05 output)
CREATE TABLE ensemble_alpha (
    bar_ts                TIMESTAMPTZ      NOT NULL,
    symbol                TEXT             NOT NULL,
    tf                    TEXT             NOT NULL,
    alpha_score           DOUBLE PRECISION NOT NULL,  -- [-1, +1] IC-weighted, correlation-adjusted
    vector_contributions  JSONB,                      -- {"V1": 0.6, "V2": 0.3, ...}
    effective_n           INTEGER,
    regime                TEXT,
    computed_at           TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (bar_ts, symbol, tf)
);
```

### Additive Changes to `signal_events`

Written by `signal-enricher` in the cold batch — never at signal fire time. These give the ML model a richer training matrix without touching emission logic.

```sql
ALTER TABLE signal_events ADD COLUMN IF NOT EXISTS analog_score           DOUBLE PRECISION;
ALTER TABLE signal_events ADD COLUMN IF NOT EXISTS analog_count           INTEGER;
ALTER TABLE signal_events ADD COLUMN IF NOT EXISTS analog_conviction_lower DOUBLE PRECISION;
ALTER TABLE signal_events ADD COLUMN IF NOT EXISTS ood_flagged            BOOLEAN DEFAULT FALSE;
```

### APR Namespace Additions

New namespace `vil.*` under existing OPS_PREFIXES:

```
vil.embedding.bar_dim          -- vector dimension for bar embeddings [128]
vil.embedding.plugin_dim       -- vector dimension for plugin history embeddings [90]
vil.embedding.staleness_days   -- reject embeddings older than N days [30]
vil.ic.min_observations        -- minimum N before IC is trusted [100]
vil.ic.decay_threshold         -- IC below this triggers weight reduction to zero [0.02]
vil.ic.rolling_window_days     -- trailing window for rolling IC [90]
vil.retrieval.k_neighbors      -- default K for k-NN queries [50]
vil.retrieval.candidate_k      -- oversample for IC-weighted re-rank [200]
vil.retrieval.max_distance     -- null result threshold (cosine) [0.25]
vil.weights.*                  -- per-plugin IC weights (written by alpha-decay-monitor)
```

---

## ECL's Role in the Unified System

ECL (Extrinsic Confidence Layer) is not replaced by VIL. It becomes the annotation layer that makes VIL measurements unbiased and stratifiable.

**Current ECL fields on `signal_events`** (fire-time annotations):
- `ctf_score`, `ctf_confirmed` — I6 cross-timeframe alignment
- `zone_friction_score` — structural context
- HMM regime at fire time (via `context_features`)

These are the metadata the IC Factory uses to stratify IC measurement by regime. Without ECL annotations, you cannot compute regime-conditioned IC ("this plugin has IC=0.06 in trending, IC=-0.01 in ranging"). ECL is the precondition for regime-stratified measurement.

**New ECL fields** (cold-path enrichment, written by `signal-enricher` after emission):
- `analog_score` — Score Object composite from vil-03
- `analog_count` — how many neighbors the score was built from
- `analog_conviction_lower` — CI lower bound (narrow CI = high conviction)
- `ood_flagged` — no close analogs found within distance threshold

The boundary invariant does not change: nothing new gates emission. These fields are observational — they tell the ML model what the analog evidence said about this bar at the time the signal fired.

---

## Embedding Serialization Contract

The embedding is the hardest seam in the architecture — the highest blast radius. Every downstream layer depends on it. A change to the serialization invalidates stored history.

**The law (per entity_type):**

1. **Per-feature rolling z-score before concatenation.** Each numeric feature is mapped to its rolling, point-in-time z-score over a trailing window. Mixed scales (RSI 0-100, volume in millions, price in thousands) would destroy cosine geometry without this.

2. **Point-in-time only.** The trailing window uses data available at or before bar T's close. Global normalization is look-ahead contamination.

3. **Categoricals are retrieval filters, not vector dimensions.** Regime, structure type, and session are excluded from the vector and applied as hard filters at retrieval time.

4. **Stable, versioned feature ordering.** A fixed registry maps `feature_name → vector_index`. The vector is meaningless without it.

5. **L2-normalize the final concatenated vector.** Cosine similarity equals inner product for L2-normalized vectors. All distance scores map to `signed_r`.

6. **Bump `embedding_version` on any change.** The `(feature set, normalization, ordering)` triple is a contract. Changing any of it bumps the version. Comparing across versions is forbidden.

| `entity_type` | Source | Approx. dim |
|---|---|---|
| `bar` | Full I1-I7 numeric surface per symbol/TF | 50-128 |
| `plugin` | 90-day direction × confidence history per plugin | 90-252 |
| `signal` | Signal feature vector at emission | ~50 |

---

## The Retrieval Primitive

Every consumer queries VIL through one interface:

```python
@dataclass
class AnalogResult:
    entity_id:   str
    distance:    float               # cosine distance — never discarded
    regime:      str
    forward_ret: dict[int, float]    # {5: ret_r, 10: ret_r, 20: ret_r}
    computed_at: datetime

def retrieve(
    query_vector: list[float],
    scope: str,
    k: int,
    candidate_k: int | None = None,  # oversample for IC-weighted re-rank
    regime: str | None = None,        # hard filter by default
    max_distance: float | None = None,
) -> list[AnalogResult]: ...
```

The null result (`[]`) is returned when no analogs fall within `max_distance`. It is a named, surfaced event — not a silent fallback. `vil_null_result_total` increments; `ood_flagged` is set downstream.

`candidate_k` supports IC-weighted re-ranking: retrieve generously by plain cosine, re-rank in the consumer with IC weights. This keeps the stored vectors IC-weight-agnostic — a weekly IC refresh does not force a full re-embed.

---

## OOD Monitor

When the current bar has no analogs within the distance threshold, every model downstream is extrapolating out-of-sample. Renaissance's response: reduce conviction, reduce size, widen intervals.

The OOD monitor is the aggregate of null results across live retrievals:

- `vil_ood_rate` — rolling fraction of recent retrievals returning null/near-null
- `vil_nearest_distance` — nearest neighbor distance even on null results (severity proxy)

VIL measures and surfaces. Consumers decide the response. A rising `vil_ood_rate` often precedes a parametric regime classifier catching the break — because "nothing looks like this" precedes "this looks like regime X."

---

## Build Order

Simons would insist on evidence before each next layer. No skipping.

```
1.  Phase 133 corpus rebuild         prerequisite (underway)
    ↓
2.  vil-01 substrate                 pgvector extension + schema
                                     bar-embedder + outcome-labeler
                                     retrieve() primitive
    ↓
3.  vil-02 IC Factory                Run on Phase 133 corpus
                                     First IC report (gates everything downstream)
                                     Shows which of 138 plugins carry IC
    ↓
4.  alpha-decay-monitor              First closed feedback loop to APR
    ↓
5.  vil-04 correlation-svc           effective-N; plugin independence measured
    ↓
6.  vil-03 scoring-engine            Score Objects; first analog-based scores
    ↓
7.  vil-05 signal-combiner           Ensemble alpha; V1 Quant only
                                     Validate: ensemble Sharpe > best single plugin Sharpe
    ↓
8.  V2 Microstructure plugins        Only after V1 IC measured + ensemble validated
    ↓
9.  V3 Macro continuous scores       Extend existing I4 plugins
    ↓
10. V4 Calendar plugins              Lowest cost; add last
```

Steps 2-7 are V1 Quant only. The substrate, measurement, scoring, and ensemble are validated on existing plugins before any new vector is built.

---

## What This Does Not Change

- I1-I7 pipeline is unchanged — it produces the features VIL embeds
- ECL boundary invariant is unchanged — annotate, never gate
- Signal ledger schema changes are additive only (new columns, never dropped)
- HMM regime detection remains the regime-conditioning mechanism
- APR governs all thresholds and weights
- Shadow mode governs promotion — VIL components also enroll in `shadow_registry`
- DAG invariants hold — hot path is DB-ignorant; VIL is cold-only

The architecture does not discard current work. It adds the empirical measurement layer that was always the missing piece: a mechanism to verify whether the intelligence the pipeline generates actually predicts what it claims to predict.

---

## Relationship to Prior Design Documents

| Document | Status | Disposition |
|----------|--------|-------------|
| `vil-01-vector-intelligence-layer.md` | under-review | Substrate design remains canonical; schema here supersedes its schema section |
| `vil-02-predictive-feature-intelligence.md` | under-review | IC Factory and Analog Finder design remains canonical |
| `vil-03-scoring-engine.md` | under-review | Scoring Engine design remains canonical |
| `vil-04-correlation-intelligence.md` | under-review | Correlation and effective-N design remains canonical |
| `vil-05-signal-combiner.md` | under-review | Signal Combiner design remains canonical |
| `vil-06-platform-ideas.md` | under-review | Holding doc; unaffected |
| `2026-06-20-intelligence-vectors-architecture.md` | superseded | Concepts absorbed here; V1-V4 taxonomy, IC engine, alpha decay monitoring all incorporated |

---

## Open Questions

- **Vector dimension per entity_type:** 50-128 for bars needs calibration on real `intelligence_features` output before the migration is written. Dimension is a migration-time constant — hard to change after history accumulates.
- **Rolling window length for z-score normalization:** long enough to be stable, short enough to track regime change. Needs empirical calibration on Phase 133 corpus.
- **Null result distance threshold:** what cosine distance defines "no close analogs"? Calibrate against first 90 days of bar embeddings.
- **Embedding version migration policy:** on a version bump, re-embed all history (expensive, full comparability) or carry forward and let the comparable window grow from the bump date?
- **`embeddings` table structure:** separate tables per entity_type (different `vector(N)` dims force it) vs discriminated single table with separate HNSW indexes. Probably separate tables — confirm before schema migration is written.
