# v3.0 System Design
# Two Systems: AlphaEngine + AnalogEngine

**Date:** 2026-06-20
**Status:** Partially superseded — see note below
**Milestone:** v3.0

> **AlphaEngine (System 1) sections in this doc describe the pre-ground-up incremental design and are superseded.**
> Canonical AlphaEngine design: `docs/plans/2026-06-20-alphaengine-architecture.md` + `docs/plans/2026-06-20-alphaengine-ic-spec.md`.
>
> **AnalogEngine (System 2) sections remain canonical** — this is the only plan-level doc covering the AnalogEngine design. Do not delete or replace.
>
> When reading this doc, treat every section titled "System 1" or "AlphaEngine" as historical context. Trust the ground-up architecture doc for AlphaEngine implementation decisions.

---

## Framing: Two Distinct Systems

The existing I1-I7 pipeline is sophisticated feature engineering. What it has never done is ask whether any of it actually predicts price. Two independent systems address this -- and they answer different questions by different means.

**System 1: AlphaEngine**
*"Does this feature score empirically correlate with forward returns?"*

Parametric. 35-feature `FeatureVector` computed by `FeatureFactory` from raw `market_data_ohlcv`. IC-weighted linear ensemble across orthogonal alpha source dimensions (V1 Quant, V2 Microstructure, V3 Macro, V4 Calendar). No pgvector required -- pure SQL and statistics.

> Implementation details for System 1 are in `docs/plans/2026-06-20-alphaengine-architecture.md`. The sections below describe the earlier incremental design (IC on `intelligence_features`); that approach is superseded. The two-system framing, Simons principles, DAG topology, ECL integration, and build order narrative below remain directionally correct but reference the wrong AlphaEngine data sources.

**System 2: AnalogEngine**
*"Have we seen a bar like this before, and what happened next?"*

Non-parametric. Embeds the full I1-I7 bar state as an L2-normalized vector in pgvector. Finds K nearest historical neighbors. Returns what price did after each of them. No model assumptions. The null result -- "we have never seen conditions like this" -- is a first-class output, not a failure.

These are complementary sources of extrinsic confidence, not one system described twice. AnalogEngine operates on the holistic bar state as a geometric object in embedding space. AlphaEngine operates on individual feature score time series as predictors. When they agree, conviction is high. When they disagree, that is a signal worth investigating, not a conflict to resolve by choosing one.

Both systems annotate `signal_events` as cold-path enrichment (never at emission time), feeding the ML model a richer training matrix. Neither gates emission. Both are subject to ECL boundary invariant.

---

## What Jim Simons Demands (Applies to Both Systems)

**1. Measure first, deploy second.**
No predictor enters the ensemble without measured IC on real corpus data. No embedding goes into production without validating retrieval quality on real bars. Build infrastructure does not equal build evidence.

**2. IC Sharpe, not raw IC.**
Stable IC=0.04 compounds. Volatile IC=0.07 oscillates and erodes net. The Sharpe of the IC time series is the trust weight in both systems.

**3. Effective-N, not signal count.**
Correlated predictors do not multiply edge. AlphaEngine measures plugin correlation empirically. AnalogEngine measures plugin similarity via embedding distance. Both produce an independence-adjusted count before any ensemble weight is computed.

**4. Rolling windows everywhere. No static backtests.**
All IC is measured on trailing windows. All embedding normalization is point-in-time rolling z-score. Global normalization is look-ahead contamination and silently invalidates every downstream study.

**5. The null result is first-class.**
AnalogEngine: "no close analogs" is a named, surfaced OOD event — not a fallback to nearest-available. AlphaEngine: a plugin with insufficient N (< 100) carries no weight in the ensemble. Both systems surface their own uncertainty rather than hiding it.

**6. Alpha decay is monitored and self-corrects.**
AlphaEngine: rolling IC that falls below threshold triggers automatic APR weight reduction. AnalogEngine: rising OOD rate triggers automatic conviction-widening in the Score Object. Both systems close their own feedback loops without human intervention.

**7. Regime conditioning everywhere.**
AlphaEngine: IC measured per HMM regime; the ensemble applies different weights per regime. AnalogEngine: retrieval is filtered by regime by default; analogs from a different regime are a different distribution.

**8. Shadow before live — always.**
Every new predictor, ensemble component, and AnalogEngine-derived score starts at `is_shadow=True` in `shadow_registry`. Promotion requires `bootstrap_CI_lower > 0.0` at `n >= 100`.

**9. Every score is decomposable.**
AlphaEngine ensemble alpha must be traceable to contributing plugin scores and their IC weights. AnalogEngine Score Object must be traceable to the analog set, their distances, and which regime conditioned the retrieval.

**10. Hot path never reads from analytical tables.**
The only feedback from cold batch to the live pipeline is APR — a slow control plane read at init. Per-bar DB reads in the hot path are a DAG violation regardless of which system produces the analytical state.

---

## Where They Differ

| Dimension | AnalogEngine | AlphaEngine |
|-----------|-----|---------------------|
| Question | "What happened when conditions looked like this?" | "Does this score predict returns?" |
| Approach | Non-parametric k-NN retrieval | Parametric Spearman IC |
| Unit of analysis | Full bar state as vector in embedding space | Individual plugin score as time series |
| Infrastructure | pgvector, HNSW index, embeddings table | SQL, scipy/numpy, no new DB extension |
| Strength | Captures complex regime structure; works with few parameters | Clean statistical interpretation; IC Sharpe directly comparable across plugins |
| Weakness | Needs close analogs; breaks OOD; expensive to build | Assumes linear predictability; misses complex regime interactions |
| Output | AnalogResult list → Score Object → `score_cache` | IC weights → ensemble alpha → `ensemble_alpha` |
| ECL annotation | `analog_score`, `analog_count`, `ood_flagged` | `alpha_ensemble_alpha`, `iv_ci_lower`, `iv_plugin_ics` |
| Build cost | High (pgvector infra, embedding serialization) | Low (runs on intelligence_features post-backfill; no new infra) |
| Can run standalone | Yes | Yes |
| Can run together | Yes — additive ECL annotations | Yes |

---

## Full DAG Topology

Three planes. No cycles. One-directional data flow.

```
═══════════════════════════════════════════════════════════════════
HOT PATH  (v3.0 — I5/I6/I7 archived; ensemble IS the new I7)
FeatureFactory in-process. DB-ignorant. Never reads analytical tables.
═══════════════════════════════════════════════════════════════════

IBKR TWS
  └─ BarWriter              → market_data_ohlcv
  └─ FeatureFactory          → feature_vectors  (35-feature typed library)
      └─ IC Ensemble         → alpha_events     (emission = ensemble conviction
                                                 crossed threshold; no predefined
                                                 signal theory)


═══════════════════════════════════════════════════════════════════
COLD BATCH — SYSTEM 1: AlphaEngine
Parametric IC measurement. No pgvector required.
Reads: feature_vectors (IC); alpha_events (enrichment)
═══════════════════════════════════════════════════════════════════

  alpha-ic-engine        reads: intelligence_features
                                (plugin scores + LEAD()-computed executable returns)
                      writes: plugin_ic_scores
                               (Spearman IC, IC Sharpe, FDR, decay_flagged
                                per plugin × TF × regime × lookahead)
                      schedule: weekly

  alpha-decay-monitor    reads: plugin_ic_scores (rolling window)
                      writes: APR (alpha.weights.* → zero on IC decay)
                      alerts: OTel → Grafana
                      schedule: daily

  alpha-ensemble         reads: plugin_ic_scores + signal_events.factor_scores
                      writes: ensemble_alpha
                               (IC-weighted, correlation-adjusted alpha score
                                per bar × symbol × tf × regime)
                      schedule: nightly

  alpha-enricher         reads: ensemble_alpha (join on bar_ts, symbol, tf)
                      writes: signal_events.alpha_ensemble_alpha
                              signal_events.iv_ci_lower
                              signal_events.iv_plugin_count
                      schedule: nightly (cold enrichment — never at fire time)


═══════════════════════════════════════════════════════════════════
COLD BATCH — SYSTEM 2: AnalogEngine
Non-parametric retrieval substrate. Requires pgvector.
Reads: feature_vectors, market_data_ohlcv, alpha_events
═══════════════════════════════════════════════════════════════════

  outcome-labeler     reads: market_data_ohlcv
                      writes: forward_returns (T+5/10/20/60 R-multiples)
                      schedule: nightly
                      note: shared input for both systems; run once

  bar-embedder        reads: feature_vectors
                      writes: embeddings (entity_type='bar')
                      schedule: nightly

  plugin-embedder     reads: alpha_events (90-day alpha score history)
                      writes: embeddings (entity_type='plugin')
                      schedule: nightly

  signal-embedder     reads: alpha_events.context_features
                      writes: embeddings (entity_type='signal')
                      schedule: nightly

  analog-ic-factory      reads: embeddings + forward_returns
                      writes: feature_ic_stats
                               (feature-level IC used for k-NN re-ranking
                                weights in the embedding; distinct from
                                plugin_ic_scores which is plugin-level)
                      schedule: weekly

  correlation-svc     reads: embeddings (entity_type='plugin')
                      writes: similarity_pairs
                              effective_n_scores
                      schedule: weekly

  scoring-engine      reads: embeddings + feature_ic_stats + forward_returns
                      writes: score_cache (Score Objects per bar/symbol/tf)
                      note: transform only; does not execute k-NN internally
                      schedule: nightly

  analog-enricher        reads: score_cache (join on bar_ts, symbol, tf)
                      writes: alpha_events.analog_score
                              alpha_events.analog_count
                              alpha_events.analog_conviction_lower
                              alpha_events.ood_flagged
                      schedule: nightly (cold enrichment — never at fire time)


═══════════════════════════════════════════════════════════════════
CONTROL PLANE  (slow feedback — hours to days, not per-bar)
Reads analytical state. Writes APR. Hot path reads APR at init only.
═══════════════════════════════════════════════════════════════════

  alpha-decay-monitor    reads: plugin_ic_scores → writes: APR alpha.weights.*
  vil-ood-monitor     reads: score_cache (ood_flagged rate) → alerts OTel
  ml-discovery        reads: ensemble_alpha, score_cache → writes: APR thresholds

  APR (config_state)  ──── hot pipeline reads at init/refresh ────▶
                           IntelligencePipeline._prewarm_threshold_config()
```

**IC distinction in the DAG:**
- `plugin_ic_scores` (System 1) = plugin-level Spearman IC. Answer: "does plugin X's confidence score predict forward returns?" Used for ensemble weighting.
- `feature_ic_stats` (System 2, analog-ic-factory) = feature-level IC within the embedding. Answer: "which individual features in the bar embedding have predictive power?" Used for k-NN re-ranking via `candidate_k`.

These measure at different levels of granularity and serve different purposes. Do not merge the tables.

---

## AlphaEngine — System 1 Detail

> **SUPERSEDED.** This section describes the pre-ground-up incremental design (IC on `intelligence_features`, plugin score predictor variables). The approved v3.0 AlphaEngine design is in `docs/plans/2026-06-20-alphaengine-architecture.md`. Key differences: data source is `feature_vectors` from `FeatureFactory` (not `intelligence_features`); I5/I6/I7 are archived; `alpha_events` replaces `signal_events`.
>
> The V1-V4 vector framing below remains directionally correct. IC Engine and Ensemble descriptions are superseded by `docs/plans/2026-06-20-alphaengine-ic-spec.md`.

### The Four Vectors

Each vector is an orthogonal alpha source dimension. Adding a new vector means adding new fields to `FeatureVector` -- the IC measurement infrastructure does not change.

**V1: Quant** -- 35-feature `FeatureVector` from `FeatureFactory` over `market_data_ohlcv`. IC measures against LEAD()-computed executable returns (open of T+1 to open of T+N+1). `counterfactual_pnl_r` is the ML training target, not the IC predictor.

**V2: Microstructure** -- order flow imbalance, CVD slope, trade size distribution, spread-normalized return. Orthogonal to price patterns by construction.

**V3: Macro** -- cross-asset relationships, VIX term structure, yield curve. Continuous scores, not binary flags.

**V4: Calendar** -- day-of-week, month-end window, options expiry week, index reconstitution. Purely time-based -- zero correlation with V1/V2/V3 by construction.

---

## AnalogEngine — System 2 Detail

### The One Question AnalogEngine Answers

Given the current bar's I1-I7 state as a query vector, find the K historical bars that looked most similar. Return what price did after each of them.

AnalogEngine does not score. It returns a `list[AnalogResult]`. The Scoring Engine (analog-engine-scoring-engine) transforms that into a Score Object. The separation is rigid.

### Embedding Serialization Contract

The embedding is the hardest seam in the AnalogEngine architecture — highest blast radius, hardest to evolve. Every downstream layer depends on it. Change it and all stored history is invalidated.

1. **Per-feature rolling z-score before concatenation.** Mixed scales (RSI 0-100, volume in millions, price in thousands) destroy cosine geometry without this. Each feature mapped to its point-in-time rolling z-score over a trailing window.
2. **Point-in-time only.** Trailing window uses data available at or before bar T. Global normalization is look-ahead contamination.
3. **Categoricals are retrieval filters, not vector dimensions.** Regime and session applied as hard filters at retrieval time, not encoded into the vector.
4. **Stable, versioned feature ordering.** Fixed registry maps `feature_name → vector_index`. The vector is meaningless without it.
5. **L2-normalize the final vector.** Cosine similarity equals inner product for L2-normalized vectors.
6. **Bump `embedding_version` on any change.** Comparing vectors across versions is forbidden.

| `entity_type` | Source | Approx. dim |
|---|---|---|
| `bar` | Full I1-I7 numeric surface per symbol/TF | 50-128 |
| `plugin` | 90-day direction × confidence history per plugin | 90-252 |
| `signal` | Signal feature vector at emission | ~50 |

### The Retrieval Primitive

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

Null result (`[]`) when no analogs fall within `max_distance` — named, surfaced, not a silent fallback.

`candidate_k` supports feature-IC-weighted re-ranking: retrieve generously by plain cosine, re-rank in the consumer with `feature_ic_stats` weights. This keeps stored vectors IC-weight-agnostic so a weekly IC refresh does not force full re-embedding.

### OOD Monitor

When the current bar has no close analogs, every downstream model is extrapolating out-of-sample. AnalogEngine surfaces this as a live aggregate risk signal:

- `vil_ood_rate` — rolling fraction of recent retrievals returning null/near-null
- `vil_nearest_distance` — distance to nearest neighbor even on null results

A rising `vil_ood_rate` often precedes the parametric HMM catching a regime break — "nothing looks like this" precedes "this looks like regime X." AnalogEngine measures and surfaces; consumers decide the response.

---

## Schema

### Prerequisites (AnalogEngine only)

```sql
CREATE EXTENSION IF NOT EXISTS vector;
-- Binary already in timescale/timescaledb:latest-pg18 (v0.8.2). One-time DDL, no image change.
```

### System 1: AlphaEngine Tables

> **SUPERSEDED.** `plugin_ic_scores` and `ensemble_alpha` DDL below reflects the incremental design. Approved v3.0 AlphaEngine schema (including `feature_vectors`, `feature_ic_scores`, `ensemble_weights`, `alpha_events`) is in `docs/plans/2026-06-20-alphaengine-architecture.md` Data Model section and `docs/plans/2026-06-20-alphaengine-ic-spec.md`. Kept here for historical reference only.

```sql
-- Plugin-level IC (Spearman; used for ensemble weighting)
CREATE TABLE plugin_ic_scores (
    plugin_name         TEXT             NOT NULL,
    timeframe           TEXT             NOT NULL,
    hmm_regime          TEXT,                       -- NULL = all regimes
    lookahead_bars      INTEGER          NOT NULL,
    ic_value            DOUBLE PRECISION,
    ic_sharpe           DOUBLE PRECISION,           -- primary ensemble weight
    ic_ci_lower         DOUBLE PRECISION,
    ic_ci_upper         DOUBLE PRECISION,
    fdr_adjusted_p      DOUBLE PRECISION,
    decay_flagged       BOOLEAN          DEFAULT FALSE,
    n_observations      INTEGER,
    computed_at         TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (plugin_name, timeframe, lookahead_bars, computed_at)
);

-- IC-weighted ensemble alpha per bar
CREATE TABLE ensemble_alpha (
    bar_ts                TIMESTAMPTZ      NOT NULL,
    symbol                TEXT             NOT NULL,
    tf                    TEXT             NOT NULL,
    alpha_score           DOUBLE PRECISION NOT NULL,  -- [-1, +1]
    vector_contributions  JSONB,                      -- {"V1": 0.6, "V2": 0.3, ...}
    effective_n           INTEGER,
    regime                TEXT,
    computed_at           TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (bar_ts, symbol, tf)
);
```

### System 2: AnalogEngine Tables

```sql
-- Embedding registry
CREATE TABLE embeddings (
    entity_type       TEXT        NOT NULL,  -- 'bar', 'plugin', 'signal'
    entity_id         TEXT        NOT NULL,
    scope             TEXT        NOT NULL,
    embedding_version INTEGER     NOT NULL,
    computed_at       TIMESTAMPTZ NOT NULL,
    embedding         vector(128) NOT NULL,  -- dim fixed per entity_type; calibrate before migration
    PRIMARY KEY (entity_type, entity_id, scope, computed_at)
);
CREATE INDEX ON embeddings USING hnsw (embedding vector_cosine_ops);

-- Forward returns per bar (shared input for both systems)
CREATE TABLE forward_returns (
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

-- Plugin similarity (for effective-N)
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

-- Feature-level IC (used for embedding re-ranking weights; NOT plugin ensemble weights)
CREATE TABLE feature_ic_stats (
    feature_name        TEXT             NOT NULL,  -- individual feature within embedding
    timeframe           TEXT             NOT NULL,
    hmm_regime          TEXT,
    lookahead_bars      INTEGER          NOT NULL,
    ic_value            DOUBLE PRECISION,
    ic_sharpe           DOUBLE PRECISION,
    n_observations      INTEGER,
    computed_at         TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (feature_name, timeframe, lookahead_bars, computed_at)
);

-- Effective-N per plugin set
CREATE TABLE effective_n_scores (
    plugin_set_hash  TEXT             NOT NULL,
    regime           TEXT,
    tf               TEXT,
    effective_n      DOUBLE PRECISION NOT NULL,
    computed_at      TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (plugin_set_hash, computed_at)
);

-- Score Objects (analog-based; analog-engine-scoring-engine output)
CREATE TABLE score_cache (
    bar_ts              TIMESTAMPTZ      NOT NULL,
    symbol              TEXT             NOT NULL,
    tf                  TEXT             NOT NULL,
    scope               TEXT             NOT NULL,
    level               INTEGER          NOT NULL,  -- 0=plugin, 1=symbol+tf, 2=cross-tf, 3=cross-asset
    directional_hr      DOUBLE PRECISION,
    expected_r          DOUBLE PRECISION,
    sharpe_horizon      DOUBLE PRECISION,
    alignment_z         DOUBLE PRECISION,
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
```

### Additive Changes to `alpha_events`

Both systems write cold-path enrichment. Neither at fire time. Neither gates emission.

`alpha_events` replaces `signal_events` in v3.0 (see `docs/plans/2026-06-20-alphaengine-architecture.md`). Enrichment columns land here.

```sql
-- System 1: AlphaEngine
ALTER TABLE alpha_events ADD COLUMN IF NOT EXISTS alpha_ensemble_alpha  DOUBLE PRECISION;
ALTER TABLE alpha_events ADD COLUMN IF NOT EXISTS iv_ci_lower           DOUBLE PRECISION;
ALTER TABLE alpha_events ADD COLUMN IF NOT EXISTS iv_plugin_count       INTEGER;

-- System 2: AnalogEngine
ALTER TABLE alpha_events ADD COLUMN IF NOT EXISTS analog_score            DOUBLE PRECISION;
ALTER TABLE alpha_events ADD COLUMN IF NOT EXISTS analog_count            INTEGER;
ALTER TABLE alpha_events ADD COLUMN IF NOT EXISTS analog_conviction_lower DOUBLE PRECISION;
ALTER TABLE alpha_events ADD COLUMN IF NOT EXISTS ood_flagged             BOOLEAN DEFAULT FALSE;
```

### APR Namespaces

```
-- AlphaEngine (System 1)
alpha.weights.*                   -- per-plugin IC Sharpe weights (written by alpha-decay-monitor)
alpha.ensemble.min_ic_ci_lower    -- minimum CI lower before plugin included [0.0]
alpha.ensemble.min_n_observations -- minimum N before IC is trusted [100]
alpha.ic.rolling_window_days      -- trailing window for rolling IC [90]
alpha.ic.decay_threshold          -- IC below this triggers weight → zero [0.02]

-- AnalogEngine (System 2) — embedding
analog.embedding.bar_dim                    -- vector dimension for bar embeddings [128]
analog.embedding.plugin_dim                 -- vector dimension for plugin history embeddings [90]
analog.embedding.staleness_days             -- reject embeddings older than N days [30]
analog.embedding.normalization_window_days  -- rolling z-score window for serialization [90]

-- AnalogEngine (System 2) — retrieval
analog.retrieval.k_neighbors         -- default K for k-NN queries [50]
analog.retrieval.candidate_k         -- oversample for IC-weighted re-rank [200]
analog.retrieval.max_distance        -- null result threshold (cosine) [0.25]

-- AnalogEngine (System 2) — IC factory
analog.ic.min_n_observations         -- minimum obs before feature IC is trusted [100]
analog.ic.rolling_window_days        -- trailing window for feature IC [90]
analog.ic.fdr_alpha                  -- Benjamini-Hochberg FDR correction alpha [0.05]

-- AnalogEngine (System 2) — scoring
analog.scoring.min_analog_count           -- below this count, conviction=NULL [10]
analog.scoring.normalization_window_days  -- rolling z-score window for composite normalization [90]
analog.scoring.horizon_flatness_floor     -- ε: min |z| to classify horizon character [0.3]
analog.scoring.horizon_decay_fraction     -- δ: fraction of peak z that counts as decayed [0.4]
analog.scoring.subscore_ic_min_obs        -- min score_cache rows before sub-score IC trusted [500]

-- AnalogEngine (System 2) — correlation
analog.correlation.redundancy_threshold       -- cosine similarity floor for redundant pair [0.80]
analog.correlation.min_co_event_write         -- min co-fires to write a similarity_pairs row [30]
analog.correlation.min_co_event_suppression   -- min co-fires before suppression gate fires [100]
analog.correlation.effective_n_floor          -- effective-N below this triggers Grafana alert [6]

-- OOD monitor
analog.ood.alert_rate_threshold      -- OOD rate that triggers Grafana alert [0.20]
```

---

## Microservice Decomposition

### System 1: AlphaEngine

> **SUPERSEDED.** Service names and responsibilities below reflect the incremental design. Approved v3.0 AlphaEngine services (`feature_factory`, `ic_engine`, `ensemble_builder`, `alpha_emitter`, `alpha_decay_monitor`) are in `docs/plans/2026-06-20-alphaengine-architecture.md` Naming Derivations section.

| Service | Unit | Schedule | SoC boundary |
|---------|------|----------|--------------|
| `alpha_ic_engine` | `indicagent-alpha-ic-engine` | Weekly | Spearman IC only — no ensemble logic |
| `alpha_decay_monitor` | `indicagent-alpha-decay-monitor` | Daily | Detects decay, writes APR — no trading logic |
| `alpha_ensemble` | `indicagent-alpha-ensemble` | Nightly | IC-weighted combination only — no IC measurement |
| `alpha_enricher` | `indicagent-alpha-enricher` | Nightly | Cold annotation of signal_events only |

### System 2: AnalogEngine

| Service | Unit | Schedule | SoC boundary |
|---------|------|----------|--------------|
| `outcome_labeler` | `indicagent-outcome-labeler` | Nightly | Forward returns only — no interpretation; shared input |
| `bar_embedder` | `indicagent-bar-embedder` | Nightly | Serialization only — no IC, no scoring |
| `plugin_embedder` | `indicagent-plugin-embedder` | Nightly | 90-day history → L2 vector |
| `signal_embedder` | `indicagent-signal-embedder` | Nightly | Signal context → L2 vector |
| `vil_ic_factory` | `indicagent-analog-ic-factory` | Weekly | Feature-level IC for re-ranking only |
| `correlation_svc` | `indicagent-correlation-service` | Weekly | Similarity pairs + effective-N only |
| `scoring_engine` | `indicagent-scoring-engine` | Nightly | Transform only — receives analog set, does not retrieve |
| `vil_enricher` | `indicagent-analog-enricher` | Nightly | Cold annotation of signal_events only |

All services: oneshot D-06 pattern (`job_completed_total{job, status}` at exit). Log to `logs/<name>.log`. Parameters through APR.

---

## Build Order

Simons would build System 1 first. It has no new infrastructure dependencies — it runs directly on the `intelligence_features` corpus using SQL and Spearman statistics. System 2 requires pgvector, HNSW indexing, and a validated embedding serialization spec. Never build infrastructure before you have evidence it will serve a measured need.

```
1.  ETF historical backfill (SPY, QQQ, IWM, TLT)
    └─ Hard gate for both systems
    └─ Target: 5,000+ independent observations per (symbol, TF) for IC Sharpe
    └─ Single ETF at 1m over 5 years ≈ 98K independent observations (19× minimum)
    └─ See AlphaEngine V1 Methodology spec Section III for full data requirements

2.  System 1 — alpha-ic-engine (Phase A)
    └─ Spearman IC on intelligence_features corpus; no pgvector needed
    └─ Forward returns via LEAD() on bar->>'o' (executable return, not counterfactual_pnl_r)
    └─ First IC report: which of 138 plugins carry IC > 0, in which regimes
    └─ This finding gates the rest of System 1 AND informs AnalogEngine embedding design

3.  System 1 — alpha-decay-monitor
    └─ First closed feedback loop to APR; weights update automatically

4.  System 1 — alpha-ensemble (Phase C)
    └─ IC-weighted V1 Quant ensemble; validate Sharpe > best single plugin

5.  System 1 — V2 Microstructure plugins
    └─ Only after V1 IC is measured and ensemble is validated

6.  System 2 — AnalogEngine substrate (analog-engine-substrate)
    └─ pgvector extension; schema; bar-embedder; outcome-labeler; retrieve() primitive
    └─ Embedding dimension calibrated using IC report from Step 2

7.  System 2 — analog-ic-factory (feature-level IC for re-ranking)
    └─ Which features in the embedding deserve more weight in k-NN

8.  System 2 — correlation-svc + scoring-engine
    └─ First analog-based Score Objects; validate retrieval quality

9.  System 2 — analog-enricher
    └─ Both systems now annotating signal_events; ML model gets full matrix

10. System 1 — V3 Macro + V4 Calendar
    └─ Lowest-cost additions; build last after V1+V2 validated
```

---

## ECL Integration

Neither system changes emission logic. Both extend what the ML model sees about every alpha event.

In v3.0 the emission record is `alpha_events` (replaces v2.x `signal_events`). Cold-path enrichment from both systems annotates `alpha_events` after the fact.

**System 1 adds (cold-path enrichment to `alpha_events`):**
`alpha_ensemble_alpha` — what the IC-weighted Quant Vector said about this bar's direction.
`iv_ci_lower` — lower bound of the IC confidence interval (narrows as N grows).

**System 2 adds (cold-path enrichment to `alpha_events`):**
`analog_score` — what the K most similar historical bars produced on average.
`analog_count` — how many close analogs existed (conviction proxy).
`analog_conviction_lower` — CI lower bound from the analog return distribution.
`ood_flagged` — TRUE when the bar state had no close analogs.

The ML model trains on the outcome target in `alpha_events`. All six enrichment fields become features in that training matrix. The model learns which combinations of context produce better outcomes — no human encodes that relationship.

---

## What This Does Not Change

- FeatureFactory hot pipeline is DB-ignorant
- ECL boundary invariant is unchanged — annotate, never gate
- `alpha_events` schema changes are additive only
- HMM regime detection remains the regime-conditioning mechanism
- APR governs all thresholds and weights
- Shadow mode governs promotion
- DAG invariants hold — hot path is DB-ignorant

---

## Relationship to Prior Design Documents

| Document | Status | Disposition |
|----------|--------|-------------|
| `docs/ideas/analog-engine-substrate.md` | under-review | Canonical detail for AnalogEngine substrate; schema section superseded by this doc |
| `docs/ideas/analog-engine-ic-factory.md` | under-review | Canonical detail for analog-ic-factory and Analog Finder |
| `docs/ideas/analog-engine-scoring-engine.md` | under-review | Canonical detail for scoring-engine (Score Object, granularity dial) |
| `docs/ideas/analog-engine-correlation.md` | under-review | Canonical detail for correlation-svc and effective-N |
| `docs/ideas/analog-engine-ideas.md` | under-review | Holding doc; unaffected |
| `docs/plans/2026-06-20-alphaengine-ic-spec.md` | active | Strategic foundation: core thesis, V1-V4 rationale, Quant Vector seed feature library, phasing A-E with success criteria. This doc is the conceptual "why"; the VIL reference is the technical "how." Read together. |

---

## Open Questions

- **Embedding vector dimension per entity_type:** needs calibration on real `feature_vectors` output before the migration is written. Dimension is a migration-time constant.
- **Rolling z-score window length:** long enough to be stable, short enough to track regime change. Calibrate on `feature_vectors` corpus after alpha-ic-engine confirms which features carry IC.
- **AnalogEngine null result distance threshold:** calibrate against first 90 days of bar embeddings. alpha-ic-engine results (Step 2) inform which features to include in the embedding, which affects the natural distance distribution.
- **Separate tables per entity_type vs single `embeddings` table:** different `vector(N)` dims per entity type likely force separate tables with separate HNSW indexes. Confirm before migration is written.
- **Embedding version migration policy on a version bump:** re-embed all history (full comparability, expensive) or carry forward with version-split (cheaper, shrinks comparable window). Decide before first production embedding.
