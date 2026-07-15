---
**Created:** 2026-06-28
**Area:** intelligence
**Type:** new_feature
**Priority:** P3
**Effort:** 7-10 days
**Benefit:** System 2 non-parametric K-NN pattern matching; complements HMM regime system
**Risk:** medium (new algorithm)
**Gate:** IC engine stable
---

**Closed 2026-07-13 (Musk-rules prioritization pass, "delete" step) — superseded, not built.**
Zero `feature_embeddings`/pgvector infrastructure exists. This todo's own header already flagged
its architecture as superseded by `docs/research/intel-13-analog-engine.md`'s D4 rescope; since
then, ROADMAP.md's **Phase 149/150** (PrecedentEngine) grew a fuller, more current live design
(PRECEDENT-01's embedding-dimension calibration study, `candidate_k` oversampling, deferred
IC-weighted re-ranking) that already contradicts this draft's stale specifics (raw L2-normalize,
static K=20, "System 2"/"Phase D+" framing predates the one-model-one-book invariant). Phase
149/150 is now the sole live tracker for this build — a full `/gsd-discuss-phase` workflow item,
not a todo. Keeping both was the exact duplicate-tracking pattern already caught once for
Concept Registry (todo 058 vs. 112). Kept here as frozen historical record for
`docs/research/intel-precedent-engine.md`'s 2 existing citations — see Phase 149/150 in
`.planning/ROADMAP.md` for the live design.

# 021 — AnalogEngine (System 2 — Non-Parametric K-NN)

**Priority: Phase D+ — gated on AlphaEngine Phase C showing IC > 0 with p < 0.05.**
**Plan doc (archived 2026-07-02):** `docs/plans/archive/2026-06-20-analogengine-design.md` — no
longer canonical; its AnalogEngine sections are superseded by `docs/research/intel-13-analog-engine.md`'s
D4 rescope (AnalogEngine is a predictor family inside the one pipeline, not a second system).
Read intel-13 first; this doc is kept only for detail not reproduced there.

---

## Context

AlphaEngine (System 1) answers: "Does this feature score correlate with forward returns?"
AnalogEngine (System 2) answers: "Have we seen a bar like this before, and what happened next?"

Non-parametric. Embeds full bar state as L2-normalized vector in pgvector. Finds K nearest
historical neighbors. Returns distribution of forward returns following each analog. The null
result ("no close analogs — OOD") is a first-class output, not a failure.

When both systems agree → high conviction. When they disagree → log the divergence, investigate.
Neither system gates emission — they annotate `alpha_events` as cold-path enrichment.

---

## Prerequisite

AlphaEngine must show `ic_ci_lower > 0` on the full 58-symbol corpus with p < 0.05 before
any AnalogEngine build begins. Do not build until AlphaEngine validation is complete.

---

## Architecture

**Embedding:** Full FeatureVector (61 fields) L2-normalized → float[61] vector stored in
`feature_embeddings` (pgvector column). One row per (symbol, tf, bar_ts).

**Index:** HNSW index on `feature_embeddings.embedding` for fast approximate K-NN.

**Retrieval:**
- Query: embedding for bar T in `feature_embeddings`
- Filter: regime_label matches (same regime only by default; cross-regime is OOD signal)
- Return K=20 nearest neighbors (APR: `alpha.analog.k_neighbors`)
- For each neighbor: fetch forward return from `forward_returns` for the neighbor's bar_ts
- Output: Score Object = {median_return, ci_lower, ci_upper, ood_flag, n_analogs, distances}

**OOD detection:** If nearest neighbor distance > `alpha.analog.ood_distance_threshold`,
emit `ood_flag=True` and widen CI. "No close analogs" is surfaced, not silenced.

**Alpha decay:** Rising OOD rate (rolling 30-day OOD fraction > `alpha.analog.ood_alarm_rate`)
triggers automatic conviction-widening in Score Object.

---

## DAG Rules

- AnalogEngine is cold-path only — never reads hot-path tables in real time
- Embedding population is a nightly batch job (one row per new bar in `feature_vectors`)
- Retrieval runs nightly after EnsembleBuilder; annotates `alpha_events` with Score Object JSONB
- Hot path never touches `feature_embeddings` or pgvector queries

---

## Infrastructure

- pgvector extension: verify already installed (`SELECT * FROM pg_extension WHERE extname='vector'`)
- `feature_embeddings` table: create migration if not present
- HNSW index creation: build after initial bulk insert (not during insertion)

---

## APR Keys

`alpha.analog.k_neighbors` (20), `alpha.analog.ood_distance_threshold`, `alpha.analog.ood_alarm_rate`

---

## Success Criteria

- `feature_embeddings` populated for all 58 symbols × 4 TFs
- HNSW index built, K-NN query returns in < 50ms (benchmark target)
- OOD rate < 5% for in-distribution historical bars
- `alpha_events` rows annotated with `analog_score` JSONB field
- Score Object decomposable: analog set, distances, regime match fraction all logged
