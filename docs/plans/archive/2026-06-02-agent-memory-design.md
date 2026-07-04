# Agent Memory System — Design Document

**Date:** 2026-06-02  
**Phase:** 097  
**Status:** Design approved — awaiting implementation planning  
**Framing:** Renaissance Technologies / Jim Simons council — absolute mathematical rigor, non-stationarity first, data integrity paramount

---

## 1. Problem Statement

`BaseAIWorker` subclasses (`skeptic`, `counterfactual`, `regime_coherence`, `narrative_v1`) generate predictions cold on every `_compute()` call. They have no access to:

- Similar past setups and their outcomes
- Their own historical calibration accuracy
- Regime transition priors
- Cross-agent disagreement history
- Temporal narrative context

`WorkerContext.memory_client` is already stubbed as `Any | None`. This document specifies what fills that stub.

---

## 2. Technology Decision

**pgvector (custom schema) + Mem0 (tiers 4, 7 only)**

| Evaluated | Decision | Rationale |
|---|---|---|
| Zep | Rejected | Designed for chatbot session memory. Remote service adds network hop against 50ms agent budget. Schema not extensible for statistical columns. |
| Mem0 only | Rejected | Fixed schema `(id, embedding, metadata jsonb)` cannot structurally satisfy Renaissance constraints C-01 through C-04. |
| pgvector only | Rejected | Mem0's LLM-based fact extraction and deduplication are genuinely useful for qualitative text (narrative facts, operator annotations). No custom code adds that value cheaply. |
| **Hybrid** | **Selected** | pgvector for all quantitative tiers. Mem0 only where LLM extraction is appropriate. Default for toss-ups: pgvector. |

pgvector 0.8.2 is already installed in TimescaleDB. Zero new infrastructure.

---

## 3. Memory Tiers

All 8 tiers are schema-complete in Phase 097. Only tiers 1-2 are wired to live agents in Phase 097.

| Tier | Name | Backend | Phase 097 |
|---|---|---|---|
| 1 | Episodic recall | Custom pgvector | Live — `MemoryClient.recall()` |
| 2 | Outcome-driven self-correction | Custom pgvector | Live — `MemoryClient.calibration()` |
| 3 | Cross-agent disagreement | Custom pgvector | Schema only |
| 4 | Narrative continuity | Mem0 | Schema only |
| 5 | Regime transition memory | Custom pgvector | Schema only |
| 6 | Cross-symbol relational | Custom pgvector | Schema only |
| 7 | Operator annotations | Mem0 | Schema only |
| 8 | Confidence drift detection | Custom pgvector | Schema only |

---

## 4. Renaissance Constraints (Non-Negotiable)

Four structural constraints applied before any schema decisions. These are not guidelines — they are encoded in the schema via CHECK constraints, physical table separation, and indexed gates.

**C-01: Non-stationarity — regime epochs**  
Markets are non-stationary. Episodes from different distributional periods are not comparable. Every episode carries `regime_epoch INTEGER NOT NULL` sourced from `memory_system_state` (single-row table, sole source of truth). Recall is epoch-weighted. In Phase 097, epoch increment is manual (operator-triggered via annotation). Automatic distributional shift detection deferred.

**C-02: Selection bias — p_signal**  
We only store episodes that generated signals. `p_signal = sample_n / n_eligible` is the propensity score: lower values mean higher selection pressure. Stored on every calibration stat. `n_eligible` is NULL at write time, populated by the nightly backfill job retrospectively from `market_data_ohlcv + signal_ledger`.

**C-03: No inference below N=30**  
`memory_calibration_promoted` carries `CHECK (sample_n >= 30)`. The batch job cannot write below this. `win_rate` and `transition_probs` on satellite tables are NULL when their respective sample counts are below 30. Two layers: DB constraint + application gate.

**C-04: Feedback loop lineage**  
Every episode written under memory-active conditions carries `memory_assisted BOOLEAN NOT NULL DEFAULT FALSE`. The calibration promotion job tests `H0: memory-assisted episodes have the same outcome rate as non-assisted` (`feedback_loop_p`). Significant result triggers `feedback_loop_quarantine = TRUE` with a `quarantine_review_at` release path.

---

## 5. Schema

### 5.1 Support Table

```sql
CREATE TABLE memory_system_state (
    id                   INTEGER PRIMARY KEY DEFAULT 1,
    current_regime_epoch INTEGER     NOT NULL DEFAULT 1,
    epoch_updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT single_row CHECK (id = 1)
);
INSERT INTO memory_system_state DEFAULT VALUES;
```

### 5.2 ENUMs

```sql
CREATE TYPE memory_episode_kind AS ENUM ('episodic', 'disagreement', 'relational');
CREATE TYPE memory_regime_label  AS ENUM ('ranging', 'trending_up', 'trending_down');
CREATE TYPE memory_spc_stat      AS ENUM (
    'calibration_error', 'brier_score', 'skill_score',
    'information_coefficient', 'mean_prediction'
);
```

### 5.3 Episode Layer: Raw

Write-only from live pipeline. No HNSW index — agents never query this table.

```sql
CREATE TABLE memory_episodes_raw (
    id               UUID                 PRIMARY KEY DEFAULT gen_random_uuid(),
    ts               TIMESTAMPTZ          NOT NULL,
    written_at       TIMESTAMPTZ          NOT NULL DEFAULT NOW(),
    kind             memory_episode_kind  NOT NULL,
    signal_id        UUID,
    symbol           TEXT                 NOT NULL,
    timeframe        TEXT                 NOT NULL,
    agent_id         TEXT,
    embedding        vector(768),                    -- async; NULL until EmbeddingWorker processes
    embedding_text   TEXT,                           -- serialized input; stored for audit + re-embedding
    hmm_regime       TEXT,
    vol_regime       TEXT,
    entry_type       TEXT,
    regime_epoch     INTEGER              NOT NULL,  -- C-01: from memory_system_state at insert time
    n_eligible       INTEGER,                        -- C-02: NULL at write; backfill job populates
    memory_assisted  BOOLEAN              NOT NULL DEFAULT FALSE,  -- C-04
    outcome          TEXT,
    CONSTRAINT chk_raw_outcome CHECK (
        outcome IS NULL OR outcome IN (
            'never_activated', 'stopped_at_entry', 'stopped_in_trade',
            'target_1', 'target_1_2', 'target_full',
            'ttl_expired_ahead', 'ttl_expired_behind', 'condition_expired'
        )
    ),
    pnl_r            FLOAT,
    -- payload structure by kind:
    --   episodic:     {failure_prob, confidence, agent_scores: {agent_id: value}}
    --   disagreement: {agent_id_a, agent_id_b, score_a, score_b, disagreement_delta}
    --   relational:   {related_symbols: [], co_regime_states: {symbol: regime}}
    payload          JSONB                NOT NULL DEFAULT '{}'
);
SELECT create_hypertable('memory_episodes_raw', 'ts');

-- Back-fill job: episodes ready to label (signal resolved + embedding present)
CREATE INDEX mem_raw_ready_for_label ON memory_episodes_raw (signal_id, ts)
    WHERE outcome IS NULL AND signal_id IS NOT NULL AND embedding IS NOT NULL;
CREATE INDEX mem_raw_signal ON memory_episodes_raw (signal_id)
    WHERE signal_id IS NOT NULL AND outcome IS NULL;
```

### 5.4 Episode Layer: Labeled

Physical copy with resolved outcomes. Agents read ONLY from here.

```sql
CREATE TABLE memory_episodes_labeled (
    id               UUID                 PRIMARY KEY,
    ts               TIMESTAMPTZ          NOT NULL,
    written_at       TIMESTAMPTZ          NOT NULL,
    labeled_at       TIMESTAMPTZ          NOT NULL DEFAULT NOW(),
    kind             memory_episode_kind  NOT NULL,
    signal_id        UUID                 NOT NULL,
    symbol           TEXT                 NOT NULL,
    timeframe        TEXT                 NOT NULL,
    agent_id         TEXT,
    embedding        vector(768)          NOT NULL,  -- NOT NULL: backfill filters embedding IS NOT NULL
    embedding_text   TEXT                 NOT NULL,
    hmm_regime       TEXT,
    vol_regime       TEXT,
    entry_type       TEXT,
    regime_epoch     INTEGER              NOT NULL,
    n_eligible       INTEGER,
    memory_assisted  BOOLEAN              NOT NULL DEFAULT FALSE,
    outcome          TEXT                 NOT NULL,
    CONSTRAINT chk_labeled_outcome CHECK (
        outcome IN (
            'never_activated', 'stopped_at_entry', 'stopped_in_trade',
            'target_1', 'target_1_2', 'target_full',
            'ttl_expired_ahead', 'ttl_expired_behind', 'condition_expired'
        )
    ),
    pnl_r            FLOAT                NOT NULL,
    mae              FLOAT,
    mfe              FLOAT,
    bars_in_trade    INTEGER,
    payload          JSONB                NOT NULL DEFAULT '{}'
);
SELECT create_hypertable('memory_episodes_labeled', 'ts');

-- MemoryClient.recall() hot path — ef_search=100 required at query time
CREATE INDEX mem_labeled_hnsw ON memory_episodes_labeled
    USING hnsw (embedding vector_cosine_ops) WITH (m = 32, ef_construction = 128);
CREATE INDEX mem_labeled_cohort ON memory_episodes_labeled
    (agent_id, symbol, hmm_regime, entry_type, regime_epoch) WHERE agent_id IS NOT NULL;
CREATE INDEX mem_labeled_epoch ON memory_episodes_labeled (regime_epoch DESC, ts DESC);

ALTER TABLE memory_episodes_labeled SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, hmm_regime',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('memory_episodes_labeled', INTERVAL '30 days');
```

### 5.5 Calibration Layer: Promoted

Offline-validated stats. Agents read ONLY from here. Append-only.

```sql
CREATE TABLE memory_calibration_promoted (
    id                        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    promoted_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_id                  TEXT        NOT NULL,
    symbol                    TEXT,
    hmm_regime                TEXT,
    entry_type                TEXT,
    regime_epoch              INTEGER     NOT NULL,
    window_start              TIMESTAMPTZ NOT NULL,
    window_end                TIMESTAMPTZ NOT NULL,
    -- C-03: structural gate
    sample_n                  INTEGER     NOT NULL,
    CONSTRAINT chk_cal_sample_n CHECK (sample_n >= 30),
    -- Core calibration
    mean_prediction           FLOAT       NOT NULL,
    actual_rate               FLOAT       NOT NULL,
    calibration_error         FLOAT       NOT NULL,
    calibration_error_variance FLOAT      NOT NULL,
    correction_factor         FLOAT,                 -- NULL when not statistically significant
    correction_factor_stable  BOOLEAN     NOT NULL DEFAULT FALSE,
    -- Brier decomposition
    brier_score               FLOAT       NOT NULL,
    base_rate                 FLOAT       NOT NULL,
    reliability_score         FLOAT       NOT NULL,
    resolution_score          FLOAT       NOT NULL,
    skill_score               FLOAT       NOT NULL,  -- negative = worse than trivial predictor
    -- IC
    information_coefficient   FLOAT       NOT NULL,
    ic_t_stat                 FLOAT       NOT NULL,
    ic_p_value                FLOAT       NOT NULL,
    -- Statistical significance (BH-FDR corrected; circular block bootstrap)
    ci_lower                  FLOAT       NOT NULL,
    ci_upper                  FLOAT       NOT NULL,
    bootstrap_block_length    INTEGER     NOT NULL,
    p_value_raw               FLOAT       NOT NULL,
    p_value_corrected         FLOAT       NOT NULL,  -- Benjamini-Hochberg FDR
    n_hypotheses_tested       INTEGER     NOT NULL,
    -- C-02: selection bias
    n_eligible                INTEGER,
    p_signal                  FLOAT,                 -- sample_n / n_eligible
    -- C-04: feedback loop
    memory_assisted_n         INTEGER     NOT NULL DEFAULT 0,
    memory_assisted_fraction  FLOAT       NOT NULL DEFAULT 0.0,
    feedback_loop_p           FLOAT,
    feedback_loop_quarantine  BOOLEAN     NOT NULL DEFAULT FALSE,
    quarantine_review_at      TIMESTAMPTZ
);

CREATE INDEX mem_cal_cohort_latest ON memory_calibration_promoted
    (agent_id, symbol, hmm_regime, entry_type, regime_epoch, promoted_at DESC)
    WHERE feedback_loop_quarantine = FALSE;
CREATE INDEX mem_cal_quarantine_review ON memory_calibration_promoted
    (quarantine_review_at) WHERE feedback_loop_quarantine = TRUE AND quarantine_review_at IS NOT NULL;
CREATE INDEX mem_cal_skill ON memory_calibration_promoted
    (agent_id, regime_epoch, promoted_at DESC) WHERE skill_score < 0.0;
CREATE INDEX mem_cal_drift ON memory_calibration_promoted
    (agent_id, symbol, hmm_regime, entry_type, promoted_at ASC);
```

### 5.6 Calibration Layer: SPC Timeseries

Source data for promotion job and drift alerting. Agents never read this.

```sql
CREATE TABLE memory_calibration_spc (
    ts               TIMESTAMPTZ      NOT NULL,
    agent_id         TEXT             NOT NULL,
    symbol           TEXT,
    hmm_regime       TEXT,
    entry_type       TEXT,
    regime_epoch     INTEGER          NOT NULL,
    stat_name        memory_spc_stat  NOT NULL,
    window_bars      INTEGER          NOT NULL,
    sample_n         INTEGER          NOT NULL,
    ewma_lambda      FLOAT            NOT NULL,   -- stored; UCL/LCL uninterpretable without it
    ewma_value       FLOAT            NOT NULL,
    ewma_stddev      FLOAT            NOT NULL,
    ewma_ucl         FLOAT            NOT NULL,
    ewma_lcl         FLOAT            NOT NULL,
    ewma_alarm       BOOLEAN          NOT NULL DEFAULT FALSE,
    cusum_pos        FLOAT            NOT NULL DEFAULT 0.0,
    cusum_neg        FLOAT            NOT NULL DEFAULT 0.0,
    cusum_h_sigma    FLOAT            NOT NULL,   -- threshold in σ units (typically 5.0)
    cusum_h_absolute FLOAT            NOT NULL,
    cusum_alarm      BOOLEAN          NOT NULL DEFAULT FALSE,
    ks_stat          FLOAT,
    ks_p_value       FLOAT,
    ks_alarm         BOOLEAN          NOT NULL DEFAULT FALSE
);
SELECT create_hypertable('memory_calibration_spc', 'ts');
CREATE INDEX mem_spc_alarms  ON memory_calibration_spc (agent_id, stat_name, ts DESC)
    WHERE ewma_alarm = TRUE OR cusum_alarm = TRUE OR ks_alarm = TRUE;
CREATE INDEX mem_spc_cohort  ON memory_calibration_spc
    (agent_id, symbol, hmm_regime, entry_type, stat_name, ts DESC);
ALTER TABLE memory_calibration_spc SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'agent_id, stat_name',
    timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('memory_calibration_spc', INTERVAL '7 days');
```

### 5.7 Regime Transitions (Tier 5)

```sql
CREATE TABLE memory_regime_transitions (
    id                    UUID                PRIMARY KEY DEFAULT gen_random_uuid(),
    ts_start              TIMESTAMPTZ         NOT NULL,
    ts_end                TIMESTAMPTZ,
    symbol                TEXT                NOT NULL,
    timeframe             TEXT                NOT NULL,
    regime_epoch          INTEGER             NOT NULL,
    from_regime           memory_regime_label,
    to_regime             memory_regime_label NOT NULL,
    duration_bars         INTEGER,
    duration_seconds      FLOAT,
    signal_count          INTEGER,
    win_count             INTEGER,
    win_rate              FLOAT,              -- NULL if signal_count < 30
    avg_pnl_r             FLOAT,
    avg_mae               FLOAT,
    avg_mfe               FLOAT,
    transition_probs      JSONB,              -- NULL if transition_n < 30
    transition_n          INTEGER,
    duration_median_bars  INTEGER,
    duration_p25_bars     INTEGER,
    duration_p75_bars     INTEGER,
    CONSTRAINT chk_win_rate CHECK (win_rate IS NULL OR (win_rate >= 0.0 AND win_rate <= 1.0)),
    CONSTRAINT chk_transition_probs_sum CHECK (
        transition_probs IS NULL OR
        ABS((transition_probs->>'ranging')::float +
            (transition_probs->>'trending_up')::float +
            (transition_probs->>'trending_down')::float - 1.0) < 0.001
    )
);
SELECT create_hypertable('memory_regime_transitions', 'ts_start');
CREATE UNIQUE INDEX mem_reg_open ON memory_regime_transitions (symbol, timeframe)
    WHERE ts_end IS NULL;   -- structural guarantee: at most one open period per symbol/timeframe
CREATE INDEX mem_reg_history  ON memory_regime_transitions (symbol, timeframe, ts_start DESC);
CREATE INDEX mem_reg_duration ON memory_regime_transitions
    (symbol, timeframe, to_regime, duration_bars) WHERE ts_end IS NOT NULL AND duration_bars IS NOT NULL;
```

---

## 6. MemoryClient Interface

### 6.1 Architecture

- **`MemoryClient`** — read-only; held by agents via `WorkerContext.memory_client`
- **`MemoryEpisodeWriter`** — write-only; held by signal pipeline only; agents cannot write
- **Four typed backend protocols**: `EpisodicBackend`, `CalibrationBackend`, `RegimeBackend`, `Mem0Backend`
- **`EmbeddingService`** — owns text serialisation + Ollama HTTP calls; independent of client

### 6.2 Return Types (frozen dataclasses)

**`Episode`**: `id, ts, kind, signal_id, symbol, timeframe, agent_id, hmm_regime, vol_regime, entry_type, regime_epoch, outcome, pnl_r, mae, mfe, bars_in_trade, memory_assisted, payload, similarity, epoch_weight`

- `similarity` — cosine similarity [0,1]
- `epoch_weight` — 1.0 current epoch, configurable decay for prior epochs; agents use these to weight context trust

**`CalibrationStats`**: `agent_id, symbol, hmm_regime, entry_type, regime_epoch, sample_n, mean_prediction, actual_rate, calibration_error, calibration_error_variance, correction_factor, correction_factor_stable, skill_score, information_coefficient, ic_p_value, brier_score, base_rate, ci_lower, ci_upper, p_value_corrected, p_signal, feedback_loop_quarantine, quarantine_review_at, promoted_at, window_start, window_end`

- `correction_factor` is `None` when `correction_factor_stable = FALSE`

**`RegimeHistory`**: `symbol, timeframe, current_regime, ts_start, elapsed_bars, duration_median_bars, duration_p25_bars, duration_p75_bars, transition_probs, transition_n, win_rate, avg_pnl_r`

- `elapsed_bars` computed at query time from `(NOW() - ts_start)` — never stored
- `transition_probs` / `win_rate` are `None` when sample gate not met

### 6.3 Async Contract

- **Reads**: 40ms hard timeout (`asyncio.wait_for`). Returns `[] | None` on timeout or error. Never raises. Memory recall is additive — agents proceed without context on failure.
- **Writes**: fire-and-forget via `asyncio.Queue(maxsize=500)`. Queue full → drop + counter. Write failure never propagates to signal pipeline.
- **Mem0 calls**: `asyncio.to_thread()` wrapper required. Mem0 SDK is synchronous.

### 6.4 Epoch-Weighted Recall

`EpisodicBackend` fetches `limit × 3` results by cosine similarity, applies epoch decay in Python, returns top `limit`. Over-fetch is intentional — HNSW does not support weighted distance natively. Default `epoch_decay = 0.3` (current epoch weight 1.0, epoch-1 weight 0.3, epoch-2+ weight 0.09).

`MemoryClient.recall()` sets `hnsw.ef_search = 100` per session before executing HNSW queries.

### 6.5 OTel Metrics

| Metric | Type | Labels |
|---|---|---|
| `memory_recall_latency_ms` | histogram | `tier`, `symbol` |
| `memory_recall_results_total` | counter | `tier`, `result: hit\|miss\|timeout` |
| `memory_calibration_applied` | counter | `agent_id`, `stable: true\|false` |
| `memory_write_queue_depth` | gauge | — |
| `memory_write_dropped_total` | counter | — |
| `memory_embed_latency_ms` | histogram | `batch: true\|false` |

---

## 7. Data Flow DAG

### 7.1 Live Path (Hot)

```
SignalPipeline._process_bar()
  → MemoryEpisodeWriter.store(RawEpisode)    # non-blocking enqueue
  → asyncio.Queue(maxsize=500)               # bounded; back-pressure if Ollama stalls
       ↓ (background coroutine)
  EmbeddingWorker._drain()
  → EmbeddingService.embed(context)          # Ollama HTTP ~20-50ms
  → INSERT INTO memory_episodes_raw          # asyncpg
```

Queue full → `memory_write_dropped_total.add(1)` → drop episode. Never blocks bar processing.

### 7.2 Nightly Batch (9pm, strictly ordered)

Single orchestrator: `production/scripts/memory_batch.py`. Step N failure prevents steps N+1+.

```
Step 1: EpochJob
  Read memory_calibration_spc WHERE ks_alarm=TRUE → log findings
  Phase 097: manual epoch increment only (operator reviews log, updates memory_system_state)
  Emit: job_completed_total{job="memory-epoch", status}

Step 2: RegimeTransitionJob  (depends: Step 1)
  Read signal_ledger for HMM regime flips since last run
  Close open memory_regime_transitions rows (ts_end, duration_bars)
  Open new row for current regime
  Compute transition_probs (gated: transition_n >= 30)
  Emit: job_completed_total{job="memory-regime", status}

Step 3: BackfillJob  (depends: Step 2)
  JOIN signal_outcomes → memory_episodes_raw
  WHERE raw.outcome IS NULL AND raw.embedding IS NOT NULL AND so.outcome IS NOT NULL
  INSERT INTO memory_episodes_labeled ... ON CONFLICT DO NOTHING  ← idempotent
  Update n_eligible on raw rows (retrospective count from market_data_ohlcv)
  Emit: job_completed_total{job="memory-backfill", status}
        memory_episodes_labeled_total (gauge)

Step 4: PromotionJob  (depends: Step 3)
  Group memory_episodes_labeled by (agent_id, symbol, hmm_regime, entry_type, regime_epoch)
  Skip cohorts sample_n < 30
  Compute: Brier decomposition, IC, calibration_error, circular block bootstrap CI
  Apply: BH-FDR correction across all cohorts this run
  Test: feedback loop amplification (memory_assisted vs non-assisted outcome rates)
  INSERT INTO memory_calibration_promoted (append-only)
  INSERT INTO memory_calibration_spc
  Emit: job_completed_total{job="memory-promote", status}
        memory_cohorts_promoted_total, memory_cohorts_quarantined_total
```

### 7.3 Systemd

```
indicagent-memory-batch.timer  →  OnCalendar=*-*-* 21:00:00
indicagent-memory-batch.service → Type=oneshot, ExecStart=memory_batch.py
```

9pm: after trading session close, before `ml-training` at 11pm.

---

## 8. Mem0 Configuration

```python
MEM0_CONFIG = {
    "vector_store": {
        "provider": "pgvector",
        "config": {
            "collection_name": "mem0_memories",   # separate from custom tables
            "embedding_model_dims": 768,            # must match D-06 embedding model
            # connection params from Settings
        }
    },
    "embedder": {
        "provider": "ollama",
        "config": {
            "model": "nomic-embed-text",            # locked — same model as custom tables
            "ollama_base_url": "http://localhost:11434",
        }
    }
    # No graph store — Neo4j dependency rejected
}
```

Tier 4 (narrative): `agent_id="narrative_v1"`, `metadata={"tier": "narrative", "symbol": ..., "timeframe": ...}`  
Tier 7 (annotations): `agent_id="operator"`, `metadata={"tier": "annotation", "symbol": ..., "expires_at": ...}`

---

## 9. Embedding Service

**Model:** `nomic-embed-text` via Ollama (768-dim). Decision gate: must not add a new service. If `nomic-embed-text` is unavailable, fallback is `sentence-transformers/all-MiniLM-L6-v2` (384-dim, no Ollama dependency) — requires schema change to `vector(384)`.

**Serialisation principle:** indicator percentiles, not raw values. Percentiles are comparable across instruments and market conditions; raw ATR/RSI values are not.

Example: `"ES 5m at_pullback regime:trending_up vol:normal hmm_prob:0.87 trend:0.73 ctf:0.81 rsi_pct:0.62 atr_pct:0.34 swing:HL"`

`embedding_text` stored on every episode for audit and re-embedding on model change.

**Validation gate (D-12):** After N≥200 labeled episodes, compute recall@10. Verify recalled episodes have statistically higher outcome-similarity than random draw. If validation fails, revise serialisation before enabling `AGENT_MEMORY_ENABLED`.

---

## 10. Feature Flag

`AGENT_MEMORY_ENABLED = False` in Settings. Default off. Shadow validation required before enabling:
1. N≥200 labeled episodes accumulated
2. recall@10 validation passes (D-12)
3. At least one agent shows `skill_score > 0` in promoted calibration

---

## 11. Files To Create

| File | Purpose |
|---|---|
| `production/migrations/NNN_agent_memory_schema.sql` | All 6 tables + ENUMs + indexes + compression policies |
| `src/core/memory/types.py` | `Episode`, `CalibrationStats`, `RegimeHistory` dataclasses |
| `src/core/memory/backends.py` | `EpisodicBackend`, `CalibrationBackend`, `RegimeBackend`, `Mem0Backend` protocols |
| `src/core/memory/client.py` | `MemoryClient` (read-only, composed from backends) |
| `src/core/memory/writer.py` | `MemoryEpisodeWriter` + `EmbeddingWorker` |
| `src/core/memory/embedding.py` | `EmbeddingService` (text serialisation + Ollama HTTP) |
| `src/core/memory/backends/episodic.py` | `PgvectorEpisodicBackend` |
| `src/core/memory/backends/calibration.py` | `PgvectorCalibrationBackend` |
| `src/core/memory/backends/regime.py` | `PgvectorRegimeBackend` |
| `src/core/memory/backends/mem0.py` | `Mem0BackendImpl` |
| `production/scripts/memory_batch.py` | Nightly orchestrator (4 steps) |
| `production/systemd/indicagent-memory-batch.service` | Oneshot service unit |
| `production/systemd/indicagent-memory-batch.timer` | 9pm nightly timer |
| `src/core/ai/worker_context.py` | Update stub: `memory_client: MemoryClient \| None` |
| `config/memory.yaml` | `epoch_decay`, `recall_limit`, `timeout_ms`, `queue_maxsize` |
| `tests/unit/core/test_memory_client.py` | Unit tests for MemoryClient + backends |

---

## 12. Out of Scope (Phase 097)

- Tier 3-8 live agent wiring (schema ready; consumer code deferred)
- Automatic epoch increment (manual only in Phase 097)
- Operator annotation write interface (CLI or API route)
- Memory dashboard / UI
- Online stat computation in live agents (never — offline promotion only)
- Cross-symbol relational episode population (Tier 6 schema ready; population deferred)
- Hot-reload without restart
