# AnalogEngine — Non-Parametric Retrieval as a Predictor Family

**Version:** 1.0
**Status:** draft — consolidated from the pre-v3.0 AnalogEngine doc set for independent iteration
**Priority:** high (v3.2 build surface; the second information source this system has beyond parametric features)
**Milestone:** v3.2 Signal Diversification — AnalogEngine + Feature Expansion (Phases 148-150, renumbered 2026-07-04 — originally 145-147, gated on v3.1 OOS IC > 0)
**Last Updated:** 2026-07-02
**Tags:** pgvector, embedding, retrieval, analog, non-parametric, predictor, measurement-engine, ic
**Source:** `.planning/research/2026-07-02-v3-topdown-architecture.md` §1.2, §2.5, §3 (D4) — Author: Fable 5. Consolidates five pre-v3.0 idea docs and one design doc (see References).
**Informed by:** Fable 5 - consolidation audit corrections (forward_returns read/units, similarity_pairs, effective-N precision) and design revisions marked *(Fable's revision)* inline (2026-07-02)

---

## The Core Idea, Stated Once

Everything the intelligence pipeline knows about a bar today comes from parametric transforms — indicators, HMM states, rolling statistics. None of it asks the one question a firm with 20 years of bar history is uniquely positioned to ask: **have we seen a bar that looked like this before, and what happened next?**

AnalogEngine answers that question with retrieval, not modeling. Embed each bar's feature state as a vector, store it alongside what price actually did afterward, and at inference time find the K most similar historical bars via k-NN. No functional form assumed, no parameters fit — the answer is literally "here is what happened the last 47 times conditions looked like this."

**The rescope that matters (D4):** the original design (May-June 2026, pre-v3.0) built this as a second, parallel measurement stack — its own `forward_returns` table, its own IC factory, its own scoring engine, its own combiner. v3.0 already built one canonical version of every one of those pieces (`forward_returns`, `ic_engine.py`, `ensemble_trainer.py`). AnalogEngine's real, durable contribution is the **retrieval substrate** — that part has no v3.0 equivalent and nothing else in this codebase does what it does. Everything downstream of retrieval collapses into the existing pipeline: analog outputs become ordinary predictors, measured by the same IC machinery as every feature, weighted into the same ensemble. One measurement engine, one ensemble, one book — this is a second *evidence source*, not a second *system*.

This halves the v3.2 build surface versus the original doc set while keeping all of the alpha content.

---

## What Survives Wholesale: The Retrieval Substrate

The substrate design (originally "Vector Intelligence Layer," `analog-engine-substrate.md`) is the strongest, most load-bearing piece of the whole doc set, and D4 keeps it essentially whole; the few deltas are marked "Rescope applied" below. It earns that by getting a genuinely hard problem right: **how do you make heterogeneous, differently-scaled features comparable in one distance metric without destroying the information in any of them?**

### Why naive embedding is wrong, and what fixes it

Flattening a bar's ~50-100 numeric fields straight into a vector fails for boring, specific reasons: RSI (0-100), volume (millions), price (thousands), and z-scores (-3...3) live on wildly different scales, so cosine distance ends up dominated by whichever field happens to have the largest raw magnitude — not the field that actually matters for similarity. The serialization law that fixes this:

1. **Per-feature rolling, point-in-time standardization before concatenation** — every feature becomes a z-score or percentile rank over its own trailing window before it enters the vector, so "RSI reads like this" and "volume reads like this" are finally on the same axis.
2. **Point-in-time only, provably** — the trailing window uses only data available at or before bar T's close, same causal discipline as everywhere else in this codebase. Global or full-history normalization silently invalidates every downstream study.
3. **Categoricals are retrieval filters, not vector dimensions** — regime, structure type, session are excluded from the vector itself and applied as hard or soft filters at retrieval time. This is what makes retrieval regime-conditioned by construction rather than by afterthought.
4. **Stable, versioned feature ordering** — a fixed registry maps `feature_name -> vector index`; the vector is meaningless without it.
5. **L2-normalize the final vector** so cosine similarity equals inner product and distances map directly to a [-1, 1] correlation metric.
6. **Versioned embedding contract** (`embedding_version`) — bump on any change to the `(feature set, normalization, ordering)` triple. This is distinct from staleness (age): a version mismatch means vectors are semantically incomparable, not merely old. Comparing across versions is forbidden, and this is exactly why getting the label/dimension layer right *before* AnalogEngine is a hard sequencing dependency, not a nicety — a version bump means a full, expensive re-embed of stored history.

**Rescope applied:** substrate reads `feature_vectors` and joins retrieval to the existing canonical `forward_returns` table; it does not write outcome labels, `forward_return_writer.py` stays the sole writer of that fact. The original design's parallel tables are gone (`intelligence_features` predates v3.0 and is look-ahead-contaminated; a second `forward_returns` would violate one-canonical-writer-per-fact). One unit consequence follows: analog outcomes are the canonical executable open-to-open log returns at the gradient horizons (`return_fast`/`mid`/`slow`/`extended`), not the original design's ATR-normalized R-multiples at fixed T+5/10/20; the R-multiple convention died with the deleted outcome labeler and with v2.x `signal_ledger`. IC measurement is rank-based and indifferent to this; interpretation of `analog_expected_r` magnitudes is not. The serialization law itself is untouched.

### The four demands on retrieval

1. **Distance-weighted neighbor sets, never equal-weighted.** A neighbor at cosine distance 0.02 is more analogous than one at 0.18; discarding that gradient throws away real information.
2. **The null result is a first-class return value, never a silent fallback.** If nothing falls within the distance threshold, the honest answer is "we have not seen conditions like these" — not "nearest available anyway."
3. **Regime-conditioned retrieval is the default, resolved as a hard filter.** Same RSI reading means different things in a trending regime versus a ranging one; retrieval finds neighbors similar in feature space *and* in the same regime. Filter labels resolve as `(dimension, label)` pairs per intel-12's label-identity invariant, never a bare label. (This is exactly why AnalogEngine's correctness is downstream of [`docs/research/intel-12-stratification-dimension.md`](intel-12-stratification-dimension.md) — a bad regime label doesn't just dilute this substrate's output, it corrupts which neighbors get returned at all.)
4. **Staleness and version gates.** Retrieval filters out embeddings older than `analog.embedding.staleness_days` (default 30) and never mixes `embedding_version` values. A version bump without backfill shrinks the comparable history; that shrinkage is surfaced (via the returned analog count), never hidden.

### The retrieval primitive (the entire interface)

```python
@dataclass
class AnalogResult:
    entity_id:    str                 # the historical neighbor
    distance:     float               # cosine distance from the query
    regime:       str
    forward_ret:  dict[str, float]    # {'fast': ..., 'mid': ..., 'slow': ...} - canonical
                                      # executable open-to-open log returns, joined from forward_returns
    computed_at:  datetime            # for staleness reasoning

retrieve(query_vector, scope, k, candidate_k=None, regime=None, max_distance=None) -> list[AnalogResult]
```

That's the whole VIL contract. `k` defaults to `analog.retrieval.k_neighbors` (50, placeholder). `candidate_k` supports IC-weighted re-ranking downstream: pgvector's HNSW index does plain cosine only, so a consumer that wants IC-weighted similarity asks for a generous candidate set (default 200) and re-ranks to its final K itself. This was a deliberate rejection of the "bake IC weights into the stored vector" alternative — that would force a full re-embed every time weights refresh; candidate-then-re-rank keeps the index simple and the weights always current.

### The OOD monitor — promote this, it is nearly free

The null result, escalated from a per-query edge case to a standing risk signal: track the running rate and severity of null/near-null retrievals across live queries. A spike means the current regime has decoupled from all recorded history — often *before* a parametric regime classifier would catch the same break, because "nothing looks like this" tends to precede "this looks like regime X." This is one of the cheapest, highest-value ideas in the whole doc set: no new retrieval, no new table, just an aggregate over a query VIL already runs. It reuses the null-result path and the nearest-neighbor distance the primitive already returns.

Consistent with the substrate's boundary, the monitor *measures and surfaces; it does not act.* A consumer decides whether to shrink conviction, widen an interval, or alert research (alert threshold: `analog.ood.alert_rate_threshold`, default 0.20, placeholder).

*(Fable's revision)* Precision worth nailing down: the monitor introduces no new quantity. The per-bar nearest-neighbor distance is **one fact with three consumers**: it is the `analog_nn_dist` column the nightly predictor batch already writes, it is intel-12's `ood_distance` candidate stratification dimension, and its threshold crossing (`analog.retrieval.max_distance`) is the null result whose time aggregate is this monitor. Whether it conditions IC as a stratum, caps conviction as a multiplier, or both, is intel-12's Open Question 3 (recommendation there: both, staged, gated independently). One DAG constraint carries over from intel-12 verbatim: the distance may condition anything downstream but must never feed back into `retrieve()`'s own filter set; retrieval conditioning on its own output is a cycle.

### Schema (one new table)

Prerequisite: pgvector v0.8.2 is already compiled into the running TimescaleDB image (`timescale/timescaledb:latest-pg18`); the one-time `CREATE EXTENSION vector;` has not yet been run anywhere. No image change needed.

```sql
CREATE TABLE embeddings (
    entity_type       TEXT        NOT NULL,  -- 'bar' is the only v3.2 entity; type column is extensibility
    entity_id         TEXT        NOT NULL,
    scope             TEXT        NOT NULL,
    embedding_version INTEGER     NOT NULL,
    computed_at       TIMESTAMPTZ NOT NULL,
    embedding         vector(N)   NOT NULL,  -- L2-normalized; N fixed per entity_type
    PRIMARY KEY (entity_type, entity_id, scope, computed_at)
);
CREATE INDEX ON embeddings USING hnsw (embedding vector_cosine_ops);
```

`forward_returns` is not a second new table — it is the existing v3.0 `forward_returns`, read as-is. This is D4's most concrete deletion: the original design's own `forward_returns` DDL is gone entirely.

*(Fable's revision)* `similarity_pairs`, the original design's third table, is cut from the v3.2 schema rather than carried: its only specified consumer was the correlation layer D4 deletes, and the topdown doc's canonical-truth registry lists only `embeddings`, `analog_scores`, and `predictor_ic_scores` as new rows. Its DDL stays in `analog-engine-correlation.md` as reference design; build it when a consumer exists, not before.

---

## What Gets Deleted as Separate Systems, and Where the Value Goes

The original doc set built three more layers on top of the substrate, each a well-designed piece of measurement in its own right. None of them needs to exist as an independent system in v3.0 — but the design thinking inside them is too good to discard, so it's promoted below into concrete specs for what the unified pipeline should compute.

### IC Factory -> absorbed into the Measurement Engine (D1)

The original design measured feature-level IC (which embedding dimensions predict returns) with its own Spearman/FDR/walk-forward machinery, explicitly parallel to `ic_engine.py`. That parallel machinery is now redundant by construction: the proposed **Measurement Engine** (`predictor_ic_scores`, one estimator for every predictor kind — feature, ensemble, analog) already does exactly this job, generically. Registering an analog output as a `predictor` and running the Measurement Engine over it *is* the IC Factory, with zero new code.

One genuinely good idea from this doc survives and generalizes beyond its original scope: **IC-weighted candidate re-ranking.** VIL's HNSW index treats every embedding dimension equally; a consumer that wants predictive similarity (not just geometric similarity) re-ranks a generous candidate set by current feature IC weights before taking the final K. This is a real refinement, not busywork — but per the sequencing discipline this whole doc set inherits, it should wait until plain-cosine analog predictors have demonstrated IC on their own. Optimizing a retrieval step before the thing it retrieves for has earned its place is solving step 2 before step 1.

The **Analog Finder** — a thin wrapper exposing `retrieve()` as `_find_analogs(k, scope, regime)` on `BaseAIWorker`, shared by the scoring path and LLM swarm agents — survives unchanged as the one retrieval entry point every consumer uses.

### Scoring Engine -> the best of it becomes a nightly analog-predictor batch

This was the largest and most carefully worked-out doc in the set (511 lines), and most of its actual content is a specification of *what a good analog-derived predictor looks like* — which is exactly what survives, reframed as ordinary `feature_vectors`-adjacent columns computed by a nightly `BaseBatch` (`analog_expected_r`, `analog_hit_rate`, `analog_ret_dispersion`, `analog_nn_dist`, per the topdown doc §2.5), not as a bespoke scoring system with its own combiner.

**The return distribution as the shared primitive, worth keeping in full.** Before any scalar is computed, the K analogs produce a full empirical distribution of forward returns at the target horizon — percentiles, moments, skew/kurtosis, scenario probabilities, and a shape label (`tight_unimodal`, `bimodal`, `fat_left_tail`, `flat`, `null`). A bare mean alone hides whether it comes from a tight consensus or a coin-flip between two very different outcomes; the distribution shape is the difference between those two situations, and it's nearly free once the K neighbors are retrieved. This should be computed once per horizon per query and is the substrate every derived score reads from — worth preserving as-is.

**The four sub-scores, each a candidate predictor in its own right:**

| Sub-score | What it measures | Formula |
|---|---|---|
| `directional_hr` | Fraction of K analogs that moved in the predicted direction, distance-weighted | `count(same direction) / K`, weighted by proximity |
| `expected_r` | Distance-weighted mean forward return | In canonical executable open-to-open log-return units (see the unit note in the substrate section); the original R-multiple framing is gone with v2.x |
| `sharpe_horizon` | Risk-adjusted return from the analog distribution | `expected_r / std(analog returns)` — separates a high-mean/high-variance setup from a lower-mean/low-variance one at the same expected_r; unit-free |
| `alignment_z` (multi-TF only) | Conviction-weighted cross-timeframe agreement, paired with `coherence` (how unanimous the TFs are) | Replaces a discretionary "I see confluence" with two measured numbers instead of a crude fraction-agreeing count. **Deferred to second order, see below** |

Each of these is a legitimate predictor, and the doc's own insight is that **they are all measured by the identical IC machinery as everything else**. For the three single-TF sub-scores this is literal: they land at exactly feature grain, one value per (symbol, tf, bar_ts), which is precisely why registering them costs zero new measurement code; this is the Measurement Engine unification (D1) working exactly as intended. Register each, let the Measurement Engine tell you which ones actually carry IC, weight the ensemble accordingly.

*(Fable's revision)* **`alignment_z`/`coherence` are the exception, on two counts, and both push them to second order.** Grain: they live at (symbol, bar_ts) *across* TFs, not (symbol, tf, bar_ts); registration requires its own declared grain in the Measurement Engine and an explicit decision about which TF's forward return they are measured against, so they cannot silently reuse the single-TF predictor plumbing. Dependency: as originally specced they aggregate per-TF *composite* z-scores, and the composite is exactly what this rescope deletes; they must be redefined over a surviving first-order predictor (e.g. per-TF z-scores of `analog_expected_r`) before they mean anything. Same sequencing discipline as IC-weighted re-ranking: build them only after single-TF analog predictors have demonstrated IC, not alongside.

*(Fable's revision)* **Definedness rules for analog predictors, the one way they differ from parametric features.** A parametric feature exists on every bar; an analog predictor exists only where history contains analogs. Three rules follow, none requiring new gate machinery:

1. **NULL, never zero.** On a null result, or when `analog_count` falls below `analog.scoring.min_analog_count` (default 10, placeholder), every analog predictor column for that bar is NULL. Imputing 0.0 would be a silent wrong answer that poisons IC downstream.
2. **The existing min-obs gates handle the sparsity.** A high null rate means fewer non-NULL observations, and `alpha.ic.min_obs_per_regime` and friends already refuse to score data-starved cells. No bespoke pre-gate needed; record per-predictor coverage (fraction of bars non-NULL) as a fact so a starved predictor is diagnosable, and let the standard gates do their job.
3. **Analog IC is conditional on being in-distribution; say so.** By construction the predictor is only measured on bars that had analogs. That is a legitimate conditionality (the predictor genuinely does not exist elsewhere), not a bias to fix, but it must never be read as unconditional IC. Corollary: stratifying analog predictors *by* `ood_distance` is near-degenerate (high-OOD cells have no analog predictor values by definition); `ood_distance` is a stratum for *other* predictors, and the definedness rule above is how it applies to analog predictors themselves.

**The conviction envelope is worth promoting nearly whole.** Every analog predictor row should carry, as sibling columns: `analog_count`, `mean_distance`, `regime_purity`, `distribution_shape`, and `analog_novelty` (distance to nearest single neighbor, the same fact as `analog_nn_dist`). One field is dropped for v1 *(Fable's revision)*: `ic_sharpe_stability` (rolling std of IC Sharpe for contributing features) has no referent until IC-weighted re-ranking exists, since with plain-cosine retrieval there are no per-feature IC weights contributing to the analog set. It returns if and when re-ranking earns its build. The sharpest design decision buried in here: **`regime_purity` is a conviction cap, never a composite multiplier.** Scaling a genuinely strong signal down just because a few off-regime analogs slipped into a soft-matched retrieval conflates "how clean is the evidence" with "what does the evidence say" — two different questions that should never collapse into one number. With the hard regime filter as the retrieval default (per the substrate section above), `regime_purity` mostly measures residual contamination near a regime boundary, and it should cap conviction at LOW below a purity floor rather than shrink the score itself.

**Horizon profile — a genuinely reusable piece of classification logic.** Running the same query at the canonical gradient horizons (fast/mid/slow, the same horizons `forward_returns` already labels) and comparing the resulting z-scores classifies what *kind* of edge this is, with a small, explicit, tunable rule:

```
peak = argmax|z_h|
if max|z_h| < ε:                                    character = flat        # no edge at any horizon
elif sign(z_fast) != sign(z_slow):                  character = mean_revert # early move reverses
elif |z_fast| is peak and |z_slow| < δ·|z_fast|:    character = scalp       # edge concentrated early, decays
elif |z_slow| >= |z_fast| (same sign throughout):   character = structural  # edge builds / persists
else:                                               character = mixed       # report profile, no clean label
```

(`ε`, `δ` = `analog.scoring.horizon_flatness_floor` / `analog.scoring.horizon_decay_fraction`, defaults 0.3 / 0.4, placeholders.) This tells a consumer *which horizon to act on*, not just that an edge exists — `scalp` means the fast horizon is the actionable read, `structural` means the slow one is, `mean_revert` is an explicit warning that a single-horizon read would mislead. Worth keeping as a candidate feature for the ensemble, not just a display artifact.

**What does not survive:** the bespoke Score Object, the `score_cache` table, and the composite z-score's own weighting/orthogonalization machinery. That entire apparatus exists because the original design needed its own combiner independent of AlphaEngine's ensemble. It doesn't, now — the sub-scores above enter `feature_vectors` (or a sibling table, see Open Question 1) as ordinary predictor columns, `ic_engine`/Measurement Engine measures them, `ensemble_trainer` weights them alongside every parametric feature using the same Ledoit-Wolf/mean-variance machinery it already has. One combiner, not two.

### Correlation Intelligence -> largely already solved elsewhere

The original design's core insight — effective-N via eigenvalue decomposition on a signed correlation matrix, generic over any embeddable entity (plugin, signal, agent, feature, instrument) — is genuinely elegant. Per D4's reasoning, this job is already done for predictors by the ensemble's existing decorrelation step; building a second, parallel independence-measurement layer for analog predictors specifically would duplicate machinery the ensemble already runs on every predictor it weights, analog or otherwise.

*(Fable's revision)* "Already done" deserves precision, because it is true for D4's purpose but not literally the same computation. What `ensemble_trainer.py` actually runs (`src/intelligence/ensemble/weights.py`): a Ledoit-Wolf shrunk correlation estimate, greedy union-find clustering of features whose pairwise `|corr|` exceeds `alpha.ensemble.max_cluster_correlation`, proportional weight deflation of over-weight clusters, and an `effective_n` reported as the inverse HHI of the final *weight vector*. That is redundancy control for weighting, per regime stratum, over only the predictors admitted to that stratum's ensemble; it is not the correlation doc's participation ratio over the eigenvalue spectrum of a signed correlation matrix, and it never measures entities outside the ensemble (agents, instruments, live signals). For analog predictors this is exactly sufficient: they enter the ensemble and get decorrelated against parametric momentum features automatically, so no new layer is warranted. Two further notes keep this honest:

- **The `|corr|` treatment is correct at the predictor grain.** The correlation doc's "anti-correlation is independence" rigor applies to directional trade sources (two agents consistently betting opposite ways are independent bets); for *predictors*, a perfectly anti-correlated feature is the same information with the sign flipped, and clustering on `|corr|` (as the ensemble does) is the right call. Do not import the signed-independence framing into predictor decorrelation.
- **The codebase already has two divergent redundancy implementations** (bottomup audit §finding 9): `ic_engine._cluster_features` writes a `cluster_id` with zero readers, via a different algorithm than the ensemble's cluster deflation. A third implementation for analogs is precisely the failure mode D4 exists to avoid; if anything, that finding argues for deleting the orphan, not adding a sibling.

**What's worth keeping as a documented idea, not built now:** the entity-generic framing itself. The eigenvalue/participation-ratio computation doesn't care what it's measuring redundancy across — plugin, signal, agent, feature, instrument are all "how many independent things are actually in this set," and today that question only gets asked at the ensemble-weighting stage (predictors). If a future need arises to ask it somewhere else in the stack (e.g., swarm agent decorrelation, or a live redundancy check ahead of the ensemble rather than baked into it), this doc's math is the reference design — not because it needs building, but because re-deriving it from scratch later would be wasted effort when a correct version already exists here.

---

## What's Worth Promoting From the Ideas Backlog

The original holding doc (`analog-engine-ideas.md`) explicitly pruned itself to ideas that either reuse the substrate near-free or constitute a measurable edge — that discipline is worth inheriting rather than re-litigating. Ranked by the same value-per-effort logic the source doc used, re-evaluated against what's now built-in vs. deleted:

1. **Cost-aware net scoring** — subtract a modeled transaction cost from `expected_r` before it's consumed anywhere. At this system's short horizons, a gross +0.2R that costs 0.25R to capture is a losing trade dressed as a winner. This is now a v4.0 concern (cost model belongs where fill data exists), not a v3.2 one — but the idea itself (net, not gross, expected return) should be the default framing whenever `expected_r` is discussed later, so it isn't silently forgotten.
2. **Agent episodic memory** — ground LLM swarm agents in their own past decisions and outcomes via the same `_find_analogs` retrieval path, rather than reasoning from pattern intuition in a vacuum. High value, reuses the retrieval primitive exactly as built, and the caveat is sharp and worth repeating: retrieval must be grounded in *outcomes*, not the agent's own prior *opinions* — otherwise it's a feedback loop that entrenches bad reasoning rather than correcting it.
3. **Non-parametric hypothesis backtester** — point the retrieval primitive at a *proposed* setup instead of a live bar, and read the empirical outcome distribution as a backtest with no parametric model. Answers "is this edge real?" for any hypothesis expressible as a feature-state query vector, using infrastructure that already exists once the substrate ships. (This is the deferred todo `017-non-parametric-hypothesis-backtester.md`, explicitly gated on the substrate landing first — todo `021-analog-engine.md` is the substrate's own gated entry.)
4. **Decay/redundancy observatory** — a pure read layer fusing IC decay with correlation drift into "what's dying, what's crowding" — trivial once the Measurement Engine and ensemble decorrelation both exist, since it reads facts both already produce.
5. **Regime discovery / cross-asset lead-lag** — genuinely interesting (data-discovered regimes instead of parametric ones; time-shifted cross-instrument similarity), but higher validation cost and more spurious-discovery risk. Correctly sequenced last; not a v3.2 concern.

Two architecture-hardening ideas from the same doc are worth flagging as *already partially answered* by decisions elsewhere: the "Entity/Predictor Registry" idea is explicitly killed by D1/D9's Concept Registry (predictors map 1:1 to `concept_registry` rows — no separate registry needed), and "Pinned Inter-Layer Contracts" is largely satisfied by `AnalogResult` being the one interface this doc defines and the Measurement Engine owning the rest.

---

## Ring Placement and DAG Compliance

Unchanged from the original design's own reasoning, which was already correct: AnalogEngine is a **cold/warm analytical layer**, never a hot-path participant.

| Tier | AnalogEngine here? | What runs |
|---|---|---|
| Hot (TWS -> Redpanda -> services, sub-ms) | No | Never touches the live tick/bar flow |
| Warm (AI inference) | Read-only, AI workers only | `_find_analogs` reads pre-computed state; an LLM worker reuses the feature vector it already holds, no live pgvector query at inference latency |
| Cold (batch -> TimescaleDB) | Yes — this is AnalogEngine's home | Embedding, retrieval-adjacent predictor computation, same pattern as `ml-training`/`roll-batch` |

Kafka posture: consume-where-convenient (batch reads TimescaleDB directly, never streams off Kafka — historical similarity doesn't need sub-second freshness), never produce (outputs are state, which belongs in TimescaleDB, or metrics/alerts, which belong in the existing OTel/Grafana fabric). This respects the DAG invariants by kind, not by exception: batch jobs are oneshot timer services, never pipeline-stage analyzers touching the DB directly.

---

## Sequencing

**Hard prerequisite, not a preference:** [`intel-12-stratification-dimension.md`](intel-12-stratification-dimension.md)'s conditioning-layer unification must land first. AnalogEngine's retrieval *hard-filters* on regime labels — a bad label doesn't dilute an estimate the way it would in the IC engine, it silently corrupts which neighbors come back at all, with no downstream signal anything went wrong. Worse, embeddings are versioned and expensive to rebuild; building the substrate on top of known-suspect strata bakes the bias into stored vectors before anyone notices. This is the concrete reason v3.15 (Conditioning & Identity Foundation) is sequenced before v3.2 in the roadmap.

Within v3.2 itself, the original doc set's own dependency order still holds and is worth preserving as a design invariant independent of scheduling:

```
substrate (embed, retrieve, forward_returns join)
    -> Analog Finder wrapper (_find_analogs)
    -> nightly analog-predictor batch (sub-scores, conviction envelope, horizon profile)
    -> Measurement Engine registration (predictor_ic_scores)
    -> EnsembleTrainer weighting (same Ledoit-Wolf/mean-variance machinery as every other predictor)
```

A consumer never builds before the substrate it reads. The substrate itself should ship and be validated on real data — the original doc's own instinct here was right: this doc-set was *designed*-extensible but not yet *proven*-extensible when it was written, and the highest-value next step after landing the substrate is confirming the embedding spec holds up on real bars, not designing further layers on top of an unvalidated foundation.

---

## Open Questions

1. **Storage grain for analog predictor columns.** Columns directly on `feature_vectors` (simplest for the Measurement Engine to consume, but couples the fabric's schema to substrate availability and `embedding_version`) versus a sibling `analog_scores` table keyed `(symbol, tf, bar_ts, embedding_version)` joined at measurement time (cleaner versioning, one more join). Leaning sibling-table for version hygiene, per the topdown doc — needs a schema decision at v3.2 planning, not before.
2. **One `embeddings` table across entity types, or one per type.** Mixing `entity_type`s in one table (with `vector(N)` fixed per type) may not work cleanly with a single HNSW index if dimensions differ meaningfully across `bar`/`plugin`/`signal`. Needs confirming before schema finalization, not a blocking decision now.
3. **Rolling-window length for per-feature standardization.** Long enough to be stable, short enough to track regime change — genuinely needs empirical calibration once real data flows, default `analog.embedding.normalization_window_days = 90` is a placeholder, not a result.
4. **Null-result distance threshold** (`analog.retrieval.max_distance`, default 0.25) — same story, needs calibration against the first meaningful window of real bar embeddings before it means anything.
5. **Does IC-weighted candidate re-ranking ever get built**, or does plain-cosine retrieval prove sufficient once analog predictors are measured? Per the sequencing discipline above, this should not be built speculatively — only once plain-cosine analog predictors have demonstrated IC and someone can show re-ranking measurably improves it.
6. **Embedding-version migration policy.** On a version bump: re-embed all history (expensive, full comparability) or carry forward and let the comparable window grow from the bump date? Coupled question: embedding membership (all 54+ `feature_vectors` columns, or a curated subset?) is the versioned recipe itself, one `concept_registry` row per `embedding_version` per D9; note that IC-informed membership selection is a milder form of the rejected bake-IC-into-vectors alternative and changes what "similar" means, so it needs the same scrutiny. **Open per 2026-07-04 cluster review (F5.3):** an embedding recipe doesn't fit any of [Concept Registry](platform-unified-concept-registry.md)'s seven current domains — that doc now carries an "anticipated eighth-plus domain" note for this, to be named (`embedding_spec` or a widened `feature` reading) at v3.2 planning rather than assumed into an undefined domain here.
7. **Distance-weighting kernel.** Inverse distance, Gaussian kernel, or rank-based, for the distance-weighted sub-scores? All defensible; pick one at build time, measure calibration, revisit. Carried over verbatim from the scoring doc's own open list because it directly shapes every sub-score value.

---

## References

- `.planning/research/2026-07-02-v3-topdown-architecture.md` — source rescoping decision (§1.2, §2.5, §3 D4)
- `docs/research/archive/analog-engine-substrate.md` — Vector Intelligence Layer; substrate design kept nearly whole (`similarity_pairs` deferred, outcome labels read from canonical `forward_returns`), consolidated above
- `docs/research/archive/analog-engine-ic-factory.md` — Predictive Feature Intelligence; superseded by Measurement Engine unification (D1), Analog Finder wrapper survives
- `docs/research/archive/analog-engine-scoring-engine.md` — Scoring Engine; composite/combiner deleted, sub-scores and conviction envelope promoted above as predictor specs
- `docs/research/archive/analog-engine-correlation.md` — Correlation Intelligence; largely superseded by existing ensemble Ledoit-Wolf decorrelation, entity-generic design kept as reference
- `docs/research/archive/analog-engine-ideas.md` — holding doc; top candidates promoted above, ranked
- `docs/plans/archive/2026-06-20-analogengine-design.md` — original v3.0 System 2 design doc; its AlphaEngine sections were already marked superseded in the doc itself, and its AnalogEngine sections (which the doc's header still calls canonical) are now consolidated and rescoped here; this doc supersedes that claim
- `.planning/research/2026-07-02-v3-bottomup-audit.md` — companion review; finding 9 (two divergent redundancy implementations, one orphaned) informs the effective-N precision note above
- `services/forward_return_writer.py` — sole canonical writer of `forward_returns` (gradient horizons, `return_type='executable_open_to_open'`); the substrate reads it, never writes it
- `.planning/todos/deferred/021-analog-engine.md`, `.planning/todos/deferred/017-non-parametric-hypothesis-backtester.md` — gated backlog entries
- `docs/foundation/principles.md` — the "one model, one book" invariant this doc's rescope is a
  direct application of (promoted 2026-07-03 from `docs/research/archive/intel-11-dual-system-discrete-vs-portfolio.md`)
- `docs/research/intel-12-stratification-dimension.md` — hard sequencing prerequisite; regime labels this substrate hard-filters on
- ROADMAP.md v3.2 entry (Phases 148-150, renumbered 2026-07-04 — originally 145-147)
