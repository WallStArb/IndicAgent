# Vector Intelligence Layer

**Archived 2026-07-02.** Substrate design consolidated (kept in full, D4 rescope) into
`docs/ideas/intel-13-analog-engine.md`. Kept here for implementation-level detail (full
schema rationale, alternatives-considered reasoning) not reproduced there.

**Version:** 1.1
**Status:** under-review
**Priority:** high
**Last Updated:** 2026-06-01
**Tags:** pgvector, embedding, retrieval, similarity, substrate, analog-finder, intelligence, multi-tf

---

## What Simons Would See First

The existing pipeline is a prediction machine that does not know what it has predicted before. Every bar is processed as if it is the first bar. The I1-I7 intelligence computes indicators, patterns, regimes, confluence, and signals — but nothing in the system asks: *have we seen a bar that looked like this, and what happened next?*

Renaissance's edge is not in having better models. It is in having more observations per model. The Medallion fund runs thousands of overlapping signals, each carrying a small IC, and the edge compounds across their statistical independence. The critical infrastructure that makes this possible is not the signals themselves — it is the ability to retrieve, at any level of granularity, the historical states most similar to now and what price did after them.

That infrastructure does not exist in this system. This document defines it.

---

## What VIL Is (and Is Not)

The Vector Intelligence Layer is a **retrieval substrate**. Its job is exactly two things:

1. **Embed** — encode bar states, plugin histories, and signals as L2-normalized vectors and store them in pgvector, alongside what price did afterward (`forward_returns`)
2. **Retrieve** — given a query vector (the current bar) and a scope, return the K most similar historical vectors via k-NN, joined to their outcome labels

That is the full scope of VIL. It returns analog sets. **It does not score them.**

The boundary, stated plainly:

- VIL answers: *"what are the K historical states most similar to now, at this scope, and what did price do after each?"* — a `list[AnalogResult]`, nothing more
- Turning that analog set into a score — directional hit rate, return distribution, composite, conviction, percentile rank — is owned by the **Scoring Engine** (`analog-engine-scoring-engine`)
- Labeling outcomes and measuring which features predict (IC) is owned by **Predictive Feature Intelligence** (`analog-engine-ic-factory`)
- I7 governance, eAI fitness, and the LLM swarm consume `analog-engine-scoring-engine` scores, not VIL directly

This boundary is what keeps VIL focused, testable, and reusable. Any system that needs "find the states most similar to these" uses VIL and gets the same shape back: neighbors, distances, and their outcomes. What you conclude from them is never VIL's concern.

---

## The One Question VIL Answers

**Given a query vector at a given scope, what are the K nearest historical neighbors and what did price do after each — at T+5, T+10, T+20?**

Retrieval is *scoped* — the `scope` column lets the same query run at plugin, TF, symbol, or cross-asset resolution. But VIL only supports scoped retrieval; it does not define what each scope *means* for scoring or how scores aggregate across them. That hierarchy (Levels 0–3) is `analog-engine-scoring-engine`'s. VIL hands back neighbors; analog-engine-scoring-engine decides what a neighbor set at a given scope implies.

---

## Infrastructure Prerequisites

Any implementation building on VIL requires the pgvector extension enabled.

**Installation:**
- Current image: `timescale/timescaledb:latest-pg18` with pgvector v0.8.2 compiled in (`production/Dockerfile.timescaledb`)
- No image swap or upgrade required — the binary is already present
- One-time prerequisite: run `CREATE EXTENSION vector;` once (no migration has yet done this)

**Core operators:**
- `<=>` cosine distance — primary; use for all similarity queries
- `<#>` inner product
- `<->` L2 distance

**L2-normalization is mandatory.** All vectors stored in `embeddings` must be L2-normalized before storage. For L2-normalized vectors, cosine similarity and inner product are equivalent, and `<=>` distance scores map directly to `signed_r` (the [-1, 1] correlation metric required for effective-N computation). Normalization happens at write time — never at query time.

---

## Architectural Law: Three Separation of Concerns

Every VIL implementation obeys this separation. Collapsing any two layers produces a system that is harder to test, evolve, and reason about. This is not a guideline.

| Layer | What it owns | Where it lives |
|---|---|---|
| **Representation** | What does this entity's history look like as a mathematical object? | Stored in `embeddings` (per the serialization spec below) |
| **Similarity computation** | How do we measure distance between two representations? | Delegated to pgvector (`<=>` operator) |
| **Domain threshold** | What constitutes "similar enough" in trading terms? | Application code only (analog-engine-ic-factory/03/04) |

Application code never re-implements similarity math. pgvector never makes domain decisions. Representations are stored — not computed on the fly at query time.

---

## The Embedding Serialization Spec

**This is the single determinant of retrieval quality.** Everything else — the indexes, the operators, the scoring on top — is worthless if the embedding does not faithfully represent state. Garbage embedding → meaningless neighbors → worthless scores. A Renaissance quant treats this as the first-class deliverable, not an afterthought.

**It is also the rigid seam of the whole architecture — the hardest thing to evolve.** Every layer above depends on the embedding, so it has the highest blast radius: a change to the serialization invalidates stored history (versioning handles it, but at the cost of re-embedding or carrying a version split — see `embedding_version`). Everything else in this stack extends cheaply (new `entity_type`, new consumer, new measurement sibling); the embedding does not. Treat it accordingly — scrutinize it hardest, change it least, and validate it on real data before building layers on top.

The naive approach (flatten the ~50–100 numerical fields of `intelligence_features` directly) is **wrong** and must not be implemented:

- Mixed scales: RSI (0–100), volume (millions), price (thousands), z-scores (−3…3) on one axis → cosine distance is dominated by the high-magnitude fields; RSI similarity is drowned by price magnitude
- Heavy-tailed vs bounded features distort neighbor selection
- Categorical fields (regime, structure type) cannot be flattened at all

### The serialization law (per `entity_type`)

1. **Per-feature standardization before concatenation.** Each numeric feature is mapped to its **rolling, point-in-time z-score** (or rolling percentile rank) over a trailing window. This is what makes "RSI reads like this" comparable to "volume reads like this" — every feature in standardized units. The choice between z-score and percentile rank is per-feature (percentile for bounded/non-normal features, z-score for roughly-symmetric ones).
2. **Point-in-time only.** The trailing window uses data available at or before bar T's close. Global or full-history normalization is look-ahead and silently invalidates every downstream study — the same hard gate `analog-engine-ic-factory` enforces for IC. The normalization statistics themselves must be reproducible as-of T.
3. **Categoricals are retrieval filters, not vector dimensions.** Regime, structure type, and session are excluded from the vector and applied as hard or soft filters at retrieval time (this *is* regime-conditioned retrieval). One-hot encoding them into the vector pollutes the cosine geometry.
4. **Stable, versioned feature ordering.** The ordered list of features is a contract: a fixed registry maps `feature_name → vector index`. The vector is meaningless without it.
5. **L2-normalize the final concatenated vector** so cosine equals inner product and distances map to `signed_r`.
6. **Versioned embedding contract.** The `(feature set, normalization, ordering)` triple is an `embedding_version`. Changing any of it bumps the version. Old vectors are tagged with the old version; retrieval filters by version, or a re-embed migration backfills history. This is **distinct from `computed_at` staleness** (age): a version mismatch means the vectors are semantically incomparable, not merely old. Comparing across versions is forbidden.

### Per-entity serialization

| `entity_type` | Source | Vector | Approx. dim |
|---|---|---|---|
| `bar` | full I1-I7 numeric surface for one symbol/TF | rolling-z per feature → concatenate → L2 | 50–100 |
| `plugin` | 90-day `direction × confidence` history for one plugin | per-bar value (optionally standardized against the plugin's own recent range) → L2 | 90–252 |
| `signal` | signal feature vector at emission | rolling-z per field → L2 | ~50 |

Dimension `N` is fixed **per `entity_type`**, not globally. Bar, plugin, and signal embeddings live in separate vector spaces and are never compared across types — they get separate HNSW indexes (see Open Questions on whether this needs separate tables or a discriminated single table).

---

## What Simons Would Demand of Retrieval

These are retrieval-level demands. The score-level demands (distributions, horizon profiles, composite, percentile rank) live in `analog-engine-scoring-engine`.

**1. Distance-weighted neighbor sets.** A neighbor at cosine distance 0.02 is more analogous than one at 0.18. VIL returns the distance with every neighbor so the consumer can weight by proximity. Equal-weighting K neighbors discards the information distance carries — VIL never throws distance away.

**2. The null result is a first-class return value.** If the K nearest neighbors are all beyond a distance threshold, that bar state is unprecedented. VIL returns this explicitly (empty/flagged analog set), never a silent fallback to "nearest available." "We have not seen conditions like these" is valid, important information.

**3. Regime-conditioned retrieval.** The same RSI reading is a continuation signal in a trending regime and a reversal in a ranging one. VIL must support a regime filter on retrieval: find K neighbors similar in feature space AND in the same regime. (Hard vs soft filter is an open question.)

**4. Staleness gates.** Every embedding carries `computed_at` and `embedding_version`. Retrievals filter out embeddings older than a configurable staleness threshold and reject any with a mismatched version. Stale or semantically-incompatible data that looks like it is contributing is worse than no data.

---

## The Out-of-Distribution Monitor

The null result (demand #2) is treated above as a per-query edge case. Promote it to a **live, aggregate risk signal** — because it is one of the most valuable things this substrate can produce for almost no cost.

When the *current* bar has no analogs within the distance threshold, the market is in a state the historical record has never seen. Every model downstream — every score, every IC weight, every analog distribution — is then extrapolating out-of-sample, where confidence collapses. A Renaissance desk's response to "we are out of distribution" is reflexive: reduce conviction, reduce size, widen intervals. You cannot react to a regime break you are not measuring.

So VIL exposes an **OOD monitor**: the running rate and severity of null/near-null results across live retrievals (distance to nearest neighbor, fraction of recent bars with no close analog). A spike is an early warning that the current environment has decoupled from history — often *before* a parametric regime classifier catches it, because "nothing looks like this" precedes "this looks like regime X."

Consistent with VIL's boundary, the monitor **measures and surfaces; it does not act.** It emits the signal (instrumentation + a queryable series); a consumer decides what to do with it — shrink conviction, widen the combiner's intervals, alert research. VIL's job is to make "we have not seen conditions like these" impossible to miss, not to decide the response.

This reuses machinery that already exists: it is the null-result path (demand #2) plus the nearest-neighbor distance VIL already returns, aggregated over time. No new retrieval, no new table — an observability series over the same queries.

---

## The Schema

Three tables. VIL owns all three. (`score_cache` — the pre-computed score surface — is owned and defined by `analog-engine-scoring-engine`, not here.)

```sql
-- Embedding registry: one vector per named entity per scope per time
CREATE TABLE embeddings (
    entity_type       TEXT        NOT NULL,  -- 'bar', 'plugin', 'signal'
    entity_id         TEXT        NOT NULL,  -- (ts||symbol||tf), plugin_name, signal_id
    scope             TEXT        NOT NULL,  -- 'global', 'ES', '1m', 'trending'
    embedding_version INTEGER     NOT NULL,  -- serialization contract version
    computed_at       TIMESTAMPTZ NOT NULL,
    embedding         vector(N)   NOT NULL,  -- L2-normalized; N fixed per entity_type
    PRIMARY KEY (entity_type, entity_id, scope, computed_at)
);
CREATE INDEX ON embeddings USING hnsw (embedding vector_cosine_ops);

-- Outcome labels: what price did after each bar
CREATE TABLE forward_returns (
    entity_type   TEXT        NOT NULL,
    entity_id     TEXT        NOT NULL,
    horizon_bars  INTEGER     NOT NULL,  -- 5, 10, 20, 60
    ret_r         DOUBLE PRECISION,      -- R-multiple (move / ATR at bar T)
    direction     INTEGER,               -- +1 / -1
    regime        TEXT,
    symbol        TEXT,
    tf            TEXT,
    labeled_at    TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (entity_type, entity_id, horizon_bars)
);

-- Similarity pairs: pairwise cosine similarity between any two entities
CREATE TABLE similarity_pairs (
    entity_type    TEXT             NOT NULL,  -- 'plugin', 'signal', 'bar'
    entity_a       TEXT             NOT NULL,
    entity_b       TEXT             NOT NULL,
    scope          TEXT             NOT NULL,
    cosine_sim     DOUBLE PRECISION NOT NULL,  -- signed_r for L2-normalized
    co_event_count INTEGER          NOT NULL,
    computed_at    TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (entity_type, entity_a, entity_b, scope),
    CHECK (entity_a < entity_b)
);
```

---

## The Retrieval Primitive

Every consumer hits VIL through one query shape: embed the current entity, k-NN against `embeddings` at a scope, join to `forward_returns`. The return is a list of analogs:

```python
@dataclass
class AnalogResult:
    entity_id:    str                 # the historical neighbor
    distance:     float               # cosine distance from the query
    regime:       str
    forward_ret:  dict[int, float]    # {5: ret_r, 10: ret_r, 20: ret_r}
    computed_at:  datetime            # for staleness reasoning
```

`retrieve(query_vector, scope, k, candidate_k=None, regime=None, max_distance=None) -> list[AnalogResult]`

That is the entire VIL interface. The null result is `[]` (or a flagged empty set) when nothing falls within `max_distance`. Scoped retrieval is supported via the `scope` argument; the meaning of each scope level and any aggregation across them is `analog-engine-scoring-engine`'s concern, not VIL's.

**`candidate_k` supports IC-weighted re-ranking by consumers.** VIL's HNSW similarity is plain cosine — every dimension equal. A consumer that wants an IC-weighted metric (analog-engine-scoring-engine weights similarity by feature IC Sharpe) asks for a generous `candidate_k` (APR: `analog.retrieval.candidate_k`, default 200) by plain cosine, then re-ranks to its final K with its own distance. This keeps VIL's index simple and current — the alternative (baking IC weights into stored vectors) would force a full re-embed on every weekly IC refresh. ANN for recall in VIL; exact weighted re-rank in the consumer.

This same primitive is exposed on `BaseAIWorker` as `_find_analogs(k, scope, regime)` (implemented by `analog-engine-ic-factory`'s Analog Finder) so the scoring engine and swarm agents share one retrieval path. For LLM swarm agents, `_find_analogs` reads the pre-computed `score_cache` — it does not issue a live pgvector query at inference time. Live k-NN retrieval at LLM inference latency violates the DAG and the latency budget. The nightly batch populates `score_cache`; agents read it.

---

## Separation of Concerns

```
┌─────────────────────────────────────────────────────┐
│              VECTOR INTELLIGENCE LAYER               │
│                                                      │
│  1. EMBED          2. LABEL           3. RETRIEVE    │
│  Encode entities   Record what price  k-NN at scope  │
│  as L2-normalized  did after each     → list[Analog  │
│  vectors (per the  bar at T+5/10/20    Result] +     │
│  serialization     in R-multiples      outcomes      │
│  spec), store      (forward_returns)                  │
└─────────────────────────────────────────────────────┘
        │                                      ▲
        ▼                                      │
   analog-engine-ic-factory (label + IC)  →  analog-engine-scoring-engine (score)  →  consumers
```

VIL returns analogs and stops. analog-engine-ic-factory labels and calibrates; analog-engine-scoring-engine scores; consumers act. Each is a distinct system, and VIL's indifference to what happens above it is what makes it reusable across all of them.

---

## Where VIL Sits in the Data Flow (hot / warm / cold)

VIL is a **cold/warm analytical layer** — it reads the sinks the hot path already populates and writes its own analytical state to tables. It is *off the hot path by design*, and that is not a limitation but the correct placement: VIL is pgvector-heavy (every retrieval is a DB round-trip) and history-heavy (90-day embeddings, IC over months), so it physically cannot live on the sub-ms tick/bar flow without violating the DAG invariants.

| Tier | VIL here? | What runs |
|---|---|---|
| **Hot** (TWS → Redpanda → services, sub-ms) | **No** | VIL never touches the live tick/bar flow |
| **Warm** (<10ms pipeline / AI inference) | **Read-only, AI workers only** | Analog Finder k-NN during LLM inference — already a slow path (LLM latency dominates); the worker reuses the feature vector it already holds in memory |
| **Cold** (batch → TimescaleDB) | **Yes — VIL's home** | Embedding, outcome labeling, IC, correlation — nightly/weekly batch, same pattern as `ml-training` / `roll-batch` |

**This respects the existing DAG invariants, not by exception but by kind:**
- *"I1–I7 runs in-process; Kafka is a sink, not an inter-stage pipe"* — VIL reads the sinks; it never inserts itself as a pipeline stage.
- *"No analyzer or pipeline daemon touches the DB — only writers/trackers/auditors"* — VIL's batch jobs are oneshot timer services (like `ml-training`), not real-time pipeline analyzers, so the real-time pipeline still never touches the DB.
- *"Kafka is transport, not a state store; bar history → TimescaleDB"* — VIL needs history, which lives in TimescaleDB (Kafka retention is minimal and cannot serve 90 days).

### Kafka: consume-where-convenient, never produce

- **Input:** read TimescaleDB in batch. Do **not** stream embeddings off Kafka — it can't serve the history VIL needs, and a stateful streaming consumer is moving parts and maintenance for freshness VIL does not require (historical similarity need not be sub-second fresh). The one live touchpoint reuses what exists: an AI worker is already consuming the intelligence stream and holds the current feature vector — it serializes that for its analog query. No new topic, no extra read.
- **Output:** analytical *state* → tables (`embeddings`, `forward_returns`, `similarity_pairs`, `feature_ic_stats`, `score_cache`); *metrics/alerts* (OOD rate, effective-N) → OTel → Grafana. **VIL produces nothing to Kafka and needs no new topics** — its outputs are state (which belongs in TimescaleDB) or signals-to-humans (which belong in the existing observability fabric).

The efficiency argument is the same as the architectural one: keeping a DB-bound layer off a sub-ms path is what *makes* the hot path fast. Measurement is asynchronous to execution — the fabric never slows the live pipeline. Automation is the existing pattern: systemd timers with `Persistent=true` (a missed run fires on next boot), zero manual steps.

## Producers (feed INTO VIL)

VIL reads from existing tables. It adds nothing to the intelligence pipeline's hot path.

| Producer | What it provides | VIL use |
|---|---|---|
| Intelligence pipeline (I1-I7) | `intelligence_features` — all plugin outputs per bar | Source for bar feature vectors → `embeddings` |
| Market data (`market_data_ohlcv`) | Raw OHLCV | Source for `forward_returns` (forward returns at T+5/10/20) |
| Signal ledger (`signal_ledger`) | Plugin output history per bar, direction, confidence | Source for plugin history vectors → `embeddings` (`entity_type='plugin'`) |

---

## Consumers of VIL Output

VIL's direct consumers are the application layers. End consumers reach VIL through analog-engine-scoring-engine, not by querying VIL directly. VIL never governs emission — that is AlphaEngine's job.

| Consumer | What it reads from VIL | What it does with it |
|---|---|---|
| **analog-engine-ic-factory** (IC Factory) | retrieval results + `forward_returns` | Labels outcomes (Outcome Labeler); measures feature-level IC for k-NN re-ranking (IC Factory); wraps retrieval (Analog Finder) |
| **analog-engine-scoring-engine** (Scoring Engine) | `list[AnalogResult]` from retrieval | Transforms analogs into the Score Object; writes `score_cache`; nightly `analog-enricher` cold-annotates `signal_events` with four enrichment columns |
| **analog-engine-correlation** (Correlation) | `embeddings` + `similarity_pairs` (`entity_type='plugin'`) | Plugin effective-N and redundancy suppression |
| **analog-engine-ideas** (platform ideas) | the fabric, scoped to new entities/questions | Holding doc: regime discovery, lead-lag, hypothesis backtester, episodic memory, decay observatory, cost-aware scoring |
| **LLM swarm / eAI / Superset** | `score_cache` (pre-computed) — *not* live VIL retrieval | Prompt grounding, agent fitness measurement, research visualization. Reads the nightly batch output; does not issue k-NN queries at inference time. |

---

## Observability Contract

Every VIL implementation must instrument these signals. This is how the substrate stays debuggable at scale and how consumers know what to trust.

**Standard retrieval metrics (every k-NN query):**
- `vil_retrieval_latency_ms` — histogram, labeled by `entity_type` and `scope`
- `vil_analog_count` — gauge, K neighbors actually returned (may be < requested K)
- `vil_mean_distance` — gauge, mean cosine distance of returned neighbors
- `vil_null_result_total` — counter, incremented when no analogs found within distance threshold

**Null result contract:**
When no analogs exist within the distance threshold, this is a named, surfaced event — not a silent fallback. `vil_null_result_total` increments and `retrieve()` returns an empty/flagged set. Consumers must handle it explicitly; silent fallback to "nearest available regardless of distance" is not permitted.

**OOD monitor signal:**
The out-of-distribution monitor (above) is an aggregate over the null-result path: `vil_ood_rate` — the rolling fraction of live retrievals returning null/near-null — plus the nearest-neighbor distance already carried on every result. A rising `vil_ood_rate` is the "we have not seen conditions like these" early warning, alertable in Grafana. VIL emits it; a consumer decides the response.

**Embedding-version contract:**
Retrieval must never mix `embedding_version` values. A query at version V retrieves only version-V vectors. A version bump without a backfill shrinks the comparable history — that shrinkage is surfaced via `vil_analog_count`, not hidden.

**Batch job contract (inherits D-06):**
All VIL batch jobs emit `JOB_COMPLETED_TOTAL{job=<unit-name>, status}` at exit on both success and failure. Job label must match the systemd unit `%n` suffix exactly. Specific jobs (e.g., `bar-embedding-batch`, `forward-return-writer`) define their own label values.

**SQL-native traceability:**
All retrievals are SQL — they appear in `pg_stat_statements`, EXPLAIN ANALYZE, and query logs automatically. Use `EXPLAIN (ANALYZE, BUFFERS)` on slow retrievals before adding instrumentation. The database provides the trace.

---

## Implementation Phases

> **The doc-set numbering is the dependency order** (a design invariant, independent of when any of this is scheduled):
> - **analog-engine-substrate** substrate — extension, tables, `bar` serialization, `retrieve()`
> - **analog-engine-ic-factory** Predictive Feature Intelligence — Outcome Labeler + IC Factory + Analog Finder (measures prediction)
> - **analog-engine-scoring-engine** Scoring Engine — consumes analog-engine-ic-factory's analog set + IC facts (scores each edge)
> - **analog-engine-correlation** Correlation Intelligence — effective-N / independence across the stack (plugins are the flagship); consumes the substrate, independent of analog-engine-ic-factory/03
> - **analog-engine-05** Signal Combiner — the capstone; consumes analog-engine-ic-factory (trust), analog-engine-scoring-engine (scores), analog-engine-correlation (independence). Built last.
> - **analog-engine-ideas** Platform Ideas — holding doc; substrate-enabled extensions not yet promoted
>
> A consumer never builds before the substrate it reads. analog-engine-ic-factory and analog-engine-correlation are independent measurement siblings; analog-engine-05 sits on top of everything. This ordering holds regardless of which milestone eventually receives the work.

VIL ships the substrate; the application layers (analog-engine-ic-factory/03/04) ship on top.

> **Evidence before more design (the architecture's own shadow-mode discipline).** This doc-set is *designed*-extensible, not yet *proven*-extensible — no data has flowed through any layer boundary. The cleanest-looking seam can be wrong until real bars run through it. So the highest-value next step is not another design doc — it is to **build analog-engine-substrate and validate the embedding spec on real data**, then let evidence confirm the boundaries before designing further on top. Apply to the architecture the same rule the architecture applies to signals: shadow first, trust on evidence.

**Phase 1 — Substrate (prerequisite for everything)**
- `CREATE EXTENSION vector` (binary already in image; extension not yet enabled)
- Schema migration: `embeddings`, `forward_returns`, `similarity_pairs`
- The embedding serialization spec implemented for `entity_type='bar'` (the hardest case — sets the pattern)
- Nightly batch: bar embedding computation + outcome labeling (forward returns in R-multiples at T+5/10/20/60)
- The `retrieve()` primitive + an API endpoint returning `list[AnalogResult]`

**Phase 2 — Plugin embeddings (enables analog-engine-correlation)**
- Plugin history vectors → `embeddings` (`entity_type='plugin'`) + `similarity_pairs`
- (Effective-N and suppression are analog-engine-correlation's, built on this)

**Phase 3 — Retrieval features**
- Regime-conditioned retrieval (filter)
- Staleness + embedding-version gating
- `_find_analogs` on `BaseAIWorker`

**Phase 4 — Index at scale**
- HNSW index tuning as bar history accumulates
- Separate indexes per `entity_type` vector space

Scoring (the granularity dial, distributions, composite, surface) is **not** a VIL phase — it is `analog-engine-scoring-engine`.

---

## Relationship to Existing Work

- **analog-engine-correlation (Correlation Intelligence):** Consumer — the independence measurement layer, generic over `entity_type`. Plugin correlation is its flagship application (writes/reads `entity_type='plugin'` rows in VIL's `embeddings`/`similarity_pairs`; owns effective-N and suppression), and supersedes the archived Phase 112 hand-rolled matrix. Generalizes to signals, agents, features, instruments.
- **analog-engine-ic-factory (Predictive Feature Intelligence):** Consumer/sibling, not subsumed. Owns the Outcome Labeler, IC Factory, and the Analog Finder retrieval wrapper. Produces `forward_returns` and `feature_ic_stats`.
- **analog-engine-scoring-engine (Scoring Engine):** The scoring layer. Consumes `list[AnalogResult]` + IC weights, produces the Score Object and owns `score_cache`. Everything VIL used to claim about "scores" lives here.
- **Phase 112 (archived):** Operational detail (systemd schedule, asyncpg patterns, suppression gating, OTel metrics) preserved in `.planning/phases/archive/112-plugin-correlation/`. Remains valid for analog-engine-correlation implementation.
- **eAI (ai-03, ai-11, eai-phase-recommendations):** Measures its fitness dimensions against analog-engine-scoring-engine scores, which rest on VIL retrieval. VIL is the foundation of that ground truth, two layers down.

---

## Alternatives Considered

**IC-weighted similarity: re-rank vs baked-in weights (rejected the latter).** The obvious way to get IC-weighted similarity is to multiply each feature by its IC weight before storing, so plain pgvector cosine does the weighted thing for free. Rejected: the weekly IC Factory refresh would then force a full re-embed of all history every week, and every weight change would bump `embedding_version` and shrink the comparable window. Chosen instead: VIL stores raw L2-normalized vectors and serves a generous `candidate_k` by plain cosine; the consumer (analog-engine-scoring-engine) re-ranks with current IC weights in memory. ANN for recall here, exact weighted distance in the consumer. If someone later asks "why not just weight the stored vector?" — this is why.

---

## What Compounds From This

Every future problem that sounds like "find conditions similar to these and see what happened" is solved without new infrastructure:

| Problem | VIL query |
|---|---|
| Plugin redundancy | `similarity_pairs`, `entity_type='plugin'` |
| Cross-TF signal deduplication | `similarity_pairs`, `entity_type='signal'` |
| Regime fingerprinting | k-NN over regime feature embeddings |
| Setup similarity search | k-NN over bar embeddings, scoped by setup_type |
| eAI agent novelty | cosine distance of agent output vector from existing agents |
| "Is this bar unprecedented?" | k-NN → no analogs within threshold → null result |
| Instrument correlation | `similarity_pairs`, `entity_type='instrument'` |

Build the substrate once. Every retrieval problem is already solved.

---

## Open Questions

- **One table or many:** does mixing `entity_type`s in one `embeddings` table (with `vector(N)` fixed per type) work with a single HNSW index, or do bar/plugin/signal each need their own table because `N` differs? Probably separate indexes; confirm whether that forces separate tables before schema finalization.
- **Rolling-window length for standardization:** how long a trailing window for the per-feature z-score/percentile? Long enough to be stable, short enough to track regime change. Needs empirical calibration. → Governed by APR: `analog.embedding.normalization_window_days` (default 90).
- ~~**Regime-conditioned retrieval gate:** hard or soft?~~ **Resolved:** default to a **hard regime filter** (only same-regime neighbors). analog-engine-scoring-engine then treats residual `regime_purity` (from analogs near a regime boundary) as a conviction cap, never a composite multiplier. Soft retrieval remains available where a consumer explicitly wants the cross-regime breakdown.
- **Null result threshold:** what cosine distance defines "no close analogs"? Needs calibration against the first 90 days of bar embeddings. → Governed by APR: `analog.retrieval.max_distance` (default 0.25).
- **Embedding-version migration policy:** on a version bump, re-embed all history (expensive, full comparability) or carry forward and let the comparable window grow from the bump date?

---

## Principles Alignment

| Principle | How VIL satisfies it |
|---|---|
| **Instrument everything** | All retrievals are SQL. EXPLAIN ANALYZE, query logs, and pgstats cover them automatically. |
| **Data quality over model complexity** | VIL makes no parametric assumptions. It retrieves what history shows. The null result is surfaced honestly rather than filled. The embedding serialization spec enforces representational rigor at the foundation. |
| **Separation of concerns** | VIL: embed + retrieve. analog-engine-ic-factory: label + measure IC. analog-engine-scoring-engine: score. analog-engine-correlation: correlation. Each is a distinct system; VIL never scores. |
| **Modularity** | Three tables, one retrieval primitive. Adding a new entity type (e.g. `'macro_indicator'`) is a new batch job writing the same tables — no schema change. |
| **Reuse** | Plugin correlation, analog retrieval, eAI novelty, cross-TF dedup — all use the same tables and the same k-NN primitive. |
| **Compounding** | Every bar added to `embeddings` makes every future retrieval more accurate. The substrate gets better with age. The older the system, the more valuable it becomes. |
