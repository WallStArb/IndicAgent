# Phase 097: Agent Memory - Context

**Gathered:** 2026-06-02
**Status:** In brainstorming — schema design in progress, implementation planning not yet started

<domain>
## Phase Boundary

Replace the Zep-based memory spec from the original roadmap with a pgvector-native memory substrate. Deliver a `MemoryClient` that all `BaseAIWorker` subclasses receive via `WorkerContext.memory_client` (stub already present). The client provides episodic recall, outcome-driven self-correction, cross-agent disagreement surfacing, narrative continuity, regime transition priors, cross-symbol relational recall, operator annotation injection, and agent confidence drift detection — all backed by TimescaleDB + pgvector with Renaissance-grade statistical discipline.

**In scope:**
- 6-table schema (3 episode-layer + 3 satellite tables) — see locked decisions below
- `MemoryEpisodeWriter` — writes raw episodes at signal time; background outcome back-fill job
- `MemoryClient` — `recall()`, `recall_regime_history()`, `recall_annotations()`, `calibration()` methods; reads only from labeled/promoted tables, never raw
- `MemoryClient` wired into `WorkerContext.memory_client` (currently stubbed as `Any | None`)
- Embedding model selection and `EmbeddingService` wrapper
- Offline promotion job: reads labeled episodes, computes calibration stats, gates on N≥30 + CI bounds, writes to `memory_calibration_promoted`
- `memory_assisted` lineage flag on all episodes written under memory-active conditions
- Feature flag `AGENT_MEMORY_ENABLED` (False by default); shadow validation before enabling

**Out of scope:**
- Hot-reload of memory configuration without restart
- DSPy prompt optimization (Phase 098)
- Guardrails AI validation (Phase 099)
- New agent implementations using memory (they pick it up via `WorkerContext`)
- Memory UI / operator annotation interface (CLI or API route deferred)

</domain>

<decisions>
## Locked Decisions

**D-01: pgvector over Zep**
Technology: pgvector 0.8.2 (already installed in TimescaleDB). Zero new infrastructure. Sub-5ms recall latency vs 50ms p95 Zep budget. Schema fully owned and observable. Zep's managed summarization adds no value for the `(regime, symbol, setup_type)` + vector recall pattern.

**D-02: 8 Memory Tiers**
All 8 tiers in scope for schema design. Only tiers 1-2 wired to agents in Phase 097; tiers 3-8 are schema-ready and documented. Subsequent phases add tier consumers without schema migration.

| Tier | Name | Implemented in Phase 097 |
|------|------|--------------------------|
| 1 | Episodic recall | Yes — `MemoryClient.recall()` |
| 2 | Outcome-driven self-correction | Yes — `MemoryClient.calibration()` via promoted table |
| 3 | Cross-agent disagreement | Schema only |
| 4 | Narrative continuity | Schema only |
| 5 | Regime transition memory | Schema only (`memory_regime_transitions`) |
| 6 | Cross-symbol relational | Schema only |
| 7 | Operator annotations | Schema only (`memory_annotations`) |
| 8 | Confidence drift detection | Schema only (`memory_calibration_spc`) |

**D-03: Schema Structure — B + Offline Promotion**
Six custom pgvector tables + Mem0 for tiers 4 and 7 only. No view-based gates — physical table separation only. See DISCUSSION-LOG.md for full rationale.

Tables:
- `memory_system_state` — single-row epoch registry; live pipeline polls this, batch job is sole writer
- `memory_episodes_raw` — write-only from live pipeline; outcome nullable; no HNSW index
- `memory_episodes_labeled` — physical copy with resolved outcomes; HNSW index; agents read only here
- `memory_calibration_promoted` — offline-validated stats with N≥30 CHECK; agents read only here
- `memory_regime_transitions` — Markov state machine (tier 5)
- `memory_calibration_spc` — SPC timeseries (tier 8)
- Mem0 `mem0_memories` collection — tiers 4 and 7 only

**D-04: Renaissance Constraints — Non-Negotiable**
All four council constraints are structural requirements, not guidelines:
- C-01: `regime_epoch` column on every episode; value sourced from `memory_system_state` (not settings)
- C-02: `n_eligible` column on every episode; NULL at write time; populated by offline batch only
- C-03: N≥30 hard gate on `memory_calibration_promoted` — `CHECK (sample_n >= 30)` constraint, not application logic
- C-04: `memory_assisted` boolean on every episode; TRUE when `MemoryClient.recall()` returned results

**D-05: Embedding Approach**
Text serialization of `SignalContext` key fields → embedding model → `vector(768)`. Generated async after raw episode write. Back-fill job filters `WHERE embedding IS NOT NULL` — labeled table structurally enforces `embedding NOT NULL`. Embedding text stored in `embedding_text` column for audit and model-change re-embedding.

**D-06: Embedding Model**
TBD — resolved during plan phase. Candidates: `nomic-embed-text` via Ollama (768-dim, no new infra), `sentence-transformers/all-MiniLM-L6-v2` (384-dim, no Ollama dependency). Decision gate: must not add a new service. Whichever is chosen must be used identically by Mem0 config.

**D-07: Outcome Back-fill**
Oneshot timer reads resolved `signal_outcomes`, joins to `memory_episodes_raw` on `signal_id` WHERE `embedding IS NOT NULL AND outcome IS NULL`, copies to `memory_episodes_labeled`. Append-only; no updates to labeled. Runs nightly.

**D-08: Feature Flag**
`AGENT_MEMORY_ENABLED` in Settings, False by default. Shadow validation gate: after N≥200 labeled episodes, validate recall@10 shows statistically higher outcome similarity than random baseline before enabling.

**D-09: Outcome Values**
`outcome` CHECK constraint uses exact 9-value set from `signal_outcomes`: `never_activated`, `stopped_at_entry`, `stopped_in_trade`, `target_1`, `target_1_2`, `target_full`, `ttl_expired_ahead`, `ttl_expired_behind`, `condition_expired`. Never `win`/`loss`/`break_even`.

**D-10: kind ENUM**
`CREATE TYPE memory_episode_kind AS ENUM ('episodic', 'disagreement', 'relational')`. Typos fail at write time.

**D-11: ef_search Contract**
`MemoryClient.recall()` must execute `SET hnsw.ef_search = 100` per session before any HNSW query. Default of 40 gives poor recall at production episode volumes.

**D-12: Validation Gate (D-05 prerequisite)**
After N≥200 labeled episodes are accumulated, offline job computes recall@10: verify recalled episodes have statistically higher outcome-similarity than random draw. If validation fails, `embedding_text` serialization must be revised before `AGENT_MEMORY_ENABLED` is set True.

**D-13: Async Contract**
- Writes: fire-and-forget via background task; write failure never propagates to signal pipeline
- Reads: 40ms hard timeout; `MemoryClient.recall()` returns `[]` on timeout or error, never raises
- Mem0 calls: `asyncio.to_thread()` wrapper required (SDK is synchronous)

**D-14: Hybrid Backend — Mem0 scope**
Mem0 handles tiers 4 (narrative continuity) and 7 (operator annotations) only. Every other tier is in custom pgvector. Mem0 earns its place only when LLM-based extraction and deduplication are appropriate (qualitative text). Quantitative observations stay in owned schema. Default for toss-up cases: pgvector.

**D-19: MemoryClient Interface Architecture**
- `MemoryClient` is read-only — agents cannot write to memory; `MemoryEpisodeWriter` is a separate class
- Composed from four typed backend protocols: `EpisodicBackend`, `CalibrationBackend`, `RegimeBackend`, `Mem0Backend`
- `EmbeddingService` is independent — swapping the embedding model touches one class only
- Every method returns `[] | None` on timeout or error; never raises — graceful degradation is structural
- All Mem0 calls in `asyncio.to_thread()` — synchronous SDK never blocks event loop
- `MemoryEpisodeWriter.store()` enqueues to `asyncio.Queue`; background worker drains; write failures never reach signal pipeline
- 40ms hard timeout per method (10ms margin against 50ms agent budget)
- `epoch_decay=0.3` default: prior epoch weight 0.3, epoch-2+ weight 0.09 — configurable at construction

**D-20: Return Types**
- `Episode` — frozen dataclass; includes `similarity` and `epoch_weight` so agents can weight context trust
- `CalibrationStats` — includes `skill_score` (negative = worse than trivial), `correction_factor` (None when `correction_factor_stable=FALSE`), `feedback_loop_quarantine`
- `RegimeHistory` — includes `elapsed_bars` (computed at query time), Markov priors (None if transition_n < 30), win_rate (None if signal_count < 30)

**D-21: OTel Metrics from MemoryClient**
- `memory_recall_latency_ms` histogram (tier, symbol)
- `memory_recall_results_total` counter (tier, result: hit|miss|timeout)
- `memory_calibration_applied` counter (agent_id, stable: true|false)
- `memory_write_queue_depth` gauge
- `memory_embed_latency_ms` histogram (batch: true|false)

**D-22: EmbeddingService Serialisation Principle**
Text serialisation uses indicator percentiles, not raw values. Percentiles are comparable across instruments and market conditions; raw ATR or RSI values are not. Example: `"ES 5m at_pullback regime:trending_up vol:normal hmm_prob:0.87 trend:0.73 ctf:0.81 rsi_pct:0.62 atr_pct:0.34 swing:HL"`. Exact field selection is Claude's discretion.

**D-23: Epoch-Weighted Recall**
`EpisodicBackend` fetches `limit × 3` results by cosine similarity, applies epoch decay weights in Python, returns top `limit` after rerank. Over-fetch is intentional — HNSW does not natively support weighted distance.

### Claude's Discretion
- Exact `EmbeddingService` interface (sync vs async, batch vs single)
- Whether offline promotion job is a systemd timer or invoked by nightly batch orchestrator
- Exact text serialization format for `SignalContext` → embedding input
- Whether `memory_regime_transitions` is populated by back-fill job or separate process
- TimescaleDB retention policy duration for `memory_episodes_raw` (suggested: 90 days — labeled is permanent record)

**D-15: Calibration Promoted — Key Design Decisions**
- Wide table (one row per cohort per promotion run), append-only — history of all promotions gives free calibration drift audit
- `correction_factor` only written when `correction_factor_stable = TRUE` (low variance across rolling sub-windows, not just point significance)
- Brier decomposition stored: `reliability_score`, `resolution_score`, `base_rate`, `skill_score` — agents worse than trivial predictor flagged via `skill_score < 0` index
- `p_signal = sample_n / n_eligible` (propensity score for selection bias; not a correction formula)
- `feedback_loop_quarantine` has a release path via `quarantine_review_at`; batch job re-evaluates on schedule
- `bootstrap_block_length` stored alongside CI bounds — circular block bootstrap required (not standard bootstrap) due to temporal correlation between episodes
- `information_coefficient` + IC stats stored — primary signal quality metric at quant funds

**D-16: SPC Table — Key Design Decisions**
- `ewma_lambda` stored per row — UCL/LCL are uninterpretable without it; self-describing rows
- `cusum_h_sigma` (in σ units) + `cusum_h_absolute` (actual threshold) both stored — enables cross-agent comparability
- `memory_spc_stat` ENUM enforces type-safe stat names
- Compression after 7 days (promotion job needs recent windows only)

**D-17: Regime Transitions Table**
- `memory_regime_label` ENUM: `'ranging' | 'trending_up' | 'trending_down'` — matches HMM output values
- `UNIQUE INDEX WHERE ts_end IS NULL` — structural guarantee of at most one open period per (symbol, timeframe); not application logic
- `transition_probs` CHECK constraint: probabilities must sum to 1.0 ± 0.001 — malformed Markov vector fails at write time
- `win_rate` NULL when `signal_count < 30` — C-03 discipline applied to satellite table
- `transition_n < 30` → `transition_probs = NULL` — same gate on Markov estimates
- Duration distribution (p25/median/p75) stored on closed rows — `MemoryClient` computes elapsed bars at query time from `(NOW() - ts_start)`; never stored (would stale immediately)

**D-18: Mem0 Configuration**
- Provider: pgvector against same TimescaleDB instance, `mem0_memories` collection (separate from custom tables)
- Embedder: `nomic-embed-text` via Ollama at `localhost:11434` — locked to same model as custom tables (D-06)
- No graph store — Neo4j dependency rejected; tier 6 deferred to custom pgvector
- Scope metadata on every `add()` call: `tier`, `symbol`, `timeframe`, `agent_id`
- All Mem0 calls wrapped in `asyncio.to_thread()` — SDK is synchronous (D-13)

**Complete Table Inventory:**
| Table | Tier | Type | Agents read? |
|---|---|---|---|
| `memory_system_state` | — | Config | Pipeline reads (epoch) |
| `memory_episodes_raw` | 1,2,3,6 | Hypertable | Never |
| `memory_episodes_labeled` | 1,2,3,6 | Hypertable | Yes — recall only |
| `memory_calibration_promoted` | 2 | Regular | Yes — calibration only |
| `memory_regime_transitions` | 5 | Hypertable | Yes — regime priors |
| `memory_calibration_spc` | 8 | Hypertable | Never — batch job only |
| Mem0 `mem0_memories` | 4,7 | Mem0-managed | Yes — via `asyncio.to_thread()` |

### Deferred / Out of Scope
- Tier 3-8 consumer implementations (schema only in Phase 097)
- Operator annotation write interface
- Memory UI / dashboard
- Online stat computation in live agents (never — offline promotion only)
- Cross-symbol relational episode population (schema ready; population deferred)

</decisions>
