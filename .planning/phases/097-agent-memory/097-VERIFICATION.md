---
phase: 097-agent-memory
verified: 2026-06-05T12:00:00Z
status: gaps_found
score: 4/6 must-haves verified
gaps:
  - truth: "Agents receive MemoryClient via WorkerContext at compute time"
    status: failed
    reason: "WorkerContext is constructed in src/core/ai/base_agent.py:427 without memory_client=. self._memory_client is set on services/alpha_swarm.py but never injected into WorkerContext. No agent can access context.memory_client."
    artifacts:
      - path: "src/core/ai/base_agent.py"
        issue: "Line 427: WorkerContext(signal_context=context, llm_chain=self._llm) — memory_client= arg absent"
      - path: "services/alpha_swarm.py"
        issue: "self._memory_client built at line 142 but never passed to WorkerContext"
    missing:
      - "base_agent.py must accept and pass memory_client to WorkerContext construction"
      - "OR services/alpha_swarm.py must override the compute call to inject memory_client"
  - truth: "Phase goal evidence gate: recall p95 latency <= 50ms documented; RAM footprint documented"
    status: failed
    reason: "No p95 latency measurement exists (wiring gap prevents any real agent recall). RAM footprint not documented anywhere in the codebase or phase artifacts."
    artifacts:
      - path: "src/core/memory/client.py"
        issue: "Embeds context at recall time (line 113); embedding via Ollama can exceed 40ms alone, putting 50ms p95 at risk. Flagged in 097-REVIEWS.md but unresolved."
    missing:
      - "Document RAM footprint (queue memory, embedding model if resident, pool connections)"
      - "Either cache embeddings at write time (precomputed) or document that embedding latency is excluded from the 50ms budget"
      - "Once wiring gap fixed, measure and record p95 latency baseline"
---

# Phase 097: Agent Memory Verification Report

**Phase Goal:** Build the agent memory subsystem — pgvector-backed episodic recall, calibration stats, and nightly batch orchestration — so AI agents gain statistical memory of past signal performance, improving decision quality over time. Evidence gate: recall p95 latency <= 50ms; RAM footprint documented.
**Verified:** 2026-06-05T12:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (from plan must_haves + ROADMAP success criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | 6 memory tables with constraints, HNSW index, epoch seeded exist in live DB | VERIFIED | `\dt memory_*` returns 6 rows; `mem_labeled_hnsw` hnsw index confirmed; memory_system_state epoch=1 |
| 2 | Episode/CalibrationStats/RegimeHistory frozen dataclasses + 4 Protocols importable; Settings flag, config/memory.yaml, 11 OTel instruments in place | VERIFIED | All files exist and substantive; `grep` confirms 11 MEMORY_* instruments; config values match spec |
| 3 | Episodic/calibration/regime read backends implemented with ef_search=100, 40ms timeout, graceful degradation | VERIFIED | `grep ef_search` in episodic.py; `grep wait_for` present; calibration.py references memory_calibration_promoted only (5 times, 2 refs to memory_episodes in get_partial_sample_n which is correct) |
| 4 | MemoryClient is read-only facade with latency OTel; writer uses bounded Queue(500) with put_nowait; WorkerContext.memory_client typed MemoryClient | VERIFIED | client.py has no store/write/INSERT; writer.py uses put_nowait; worker_context.py line 36 typed MemoryClient | None |
| 5 | Agents receive MemoryClient via WorkerContext at compute time | FAILED | WorkerContext constructed in base_agent.py:427 WITHOUT memory_client=. self._memory_client on alpha_swarm never injected into WorkerContext. End-to-end wiring broken. |
| 6 | 4-step nightly batch (EpochJob/RegimeJob/BackfillJob/PromotionJob), 21:00 timer, _DAG_ORDER registered; unit tests green (26/26) | VERIFIED | ON CONFLICT present; sample_n>=30 gate present; timer=21:00; `_DAG_ORDER` entry at priority 8; 26 tests pass |

**Score:** 4/6 truths verified (truths 1, 2, 3, 4, 6 pass at artifact level; truth 5 fails at wiring level)

Note on truth 4: Though the individual components pass, the evidence gate from the phase goal ("recall p95 latency <= 50ms; RAM footprint documented") is unmet — no measurement exists and RAM footprint is undocumented.

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `production/migrations/118_agent_memory_schema.sql` | VERIFIED | 6 tables, 3 ENUMs, HNSW, constraints all live in DB |
| `src/core/memory/types.py` | VERIFIED | Episode/CalibrationStats/RegimeHistory frozen; epoch_weight, bootstrapped fields present |
| `src/core/memory/backends/__init__.py` | VERIFIED | Protocol, EpisodicBackend, CalibrationBackend, RegimeBackend, Mem0Backend exported |
| `src/core/memory/embedding.py` | VERIFIED | nomic-embed-text; EMBED_DIM=768; embed returns None on failure |
| `src/core/memory/backends/episodic.py` | VERIFIED | ef_search=100 SET LOCAL; epoch-weighted rerank; wait_for 40ms |
| `src/core/memory/backends/calibration.py` | VERIFIED | Only reads memory_calibration_promoted; WHERE feedback_loop_quarantine = FALSE |
| `src/core/memory/backends/regime.py` | VERIFIED | ts_end IS NULL query; elapsed_bars computed at query time |
| `src/core/memory/backends/mem0.py` | VERIFIED | asyncio.to_thread; nomic-embed-text 768-dim; graceful no-op fallback |
| `src/core/memory/client.py` | VERIFIED | MEMORY_RECALL_LATENCY_MS recorded; no write methods; hit/miss/timeout counters |
| `src/core/memory/writer.py` | VERIFIED | Queue(maxsize=500); put_nowait; MEMORY_WRITE_DROPPED_TOTAL on QueueFull |
| `src/core/memory/factory.py` | VERIFIED (partial) | build_memory_client/writer gated on agent_memory_enabled; called in services/alpha_swarm.py |
| `src/core/ai/worker_context.py` | VERIFIED (partial) | memory_client: MemoryClient | None field exists; but never populated in base_agent.py construction |
| `config/memory.yaml` | VERIFIED | epoch_decay=0.3, recall_limit=10, timeout_ms=40, queue_maxsize=500 |
| `production/scripts/memory_batch.py` | VERIFIED | 4 steps; ON CONFLICT DO NOTHING; sample_n>=30; BH-FDR; circular block bootstrap; job_completed_total |
| `production/systemd/indicagent-memory-batch.timer` | VERIFIED | OnCalendar=*-*-* 21:00:00 |
| `production/systemd/indicagent-memory-batch.service` | VERIFIED | Type=oneshot; ExecStart=memory_batch.py |
| `tests/unit/core/test_memory_client.py` | VERIFIED | 9 tests; graceful degradation proven |
| `tests/unit/core/test_memory_writer.py` | VERIFIED | 6 tests; QueueFull drop proven |
| `tests/unit/core/test_embedding_service.py` | VERIFIED | 11 tests; percentile serialization proven |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| memory_episodes_labeled | pgvector HNSW | USING hnsw (embedding vector_cosine_ops) | WIRED | Confirmed in live DB: `mem_labeled_hnsw hnsw (embedding vector_cosine_ops)` |
| PgvectorEpisodicBackend.recall | HNSW index | SET LOCAL hnsw.ef_search=100 | WIRED | episodic.py line 178 |
| PgvectorCalibrationBackend | memory_calibration_promoted | WHERE feedback_loop_quarantine = FALSE | WIRED | calibration.py; 5 references to memory_calibration_promoted; no memory_episodes references in get_calibration |
| BackfillJob | memory_episodes_labeled | INSERT ON CONFLICT (id, ts) DO NOTHING | WIRED | memory_batch.py line 485 |
| PromotionJob | memory_calibration_promoted | INSERT cohorts with sample_n >= 30 | WIRED | memory_batch.py; sample_n gate at line 624 |
| services/alpha_swarm._setup | MemoryClient | build_memory_client(self.settings, self._pool) | WIRED | services/alpha_swarm.py:142 |
| self._memory_client | WorkerContext.memory_client | memory_client= kwarg at WorkerContext construction | NOT WIRED | base_agent.py:427 constructs WorkerContext without memory_client=; self._memory_client is stored but never injected |
| MemoryEpisodeWriter.store | asyncio.Queue(500) | put_nowait; drop on QueueFull | WIRED | writer.py line 135 |

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| MEM-01: Episodic recall interface; agents receive MemoryClient via WorkerContext | BLOCKED | WorkerContext construction gap in base_agent.py:427 |
| MEM-02: Recall scoped by (regime_type, symbol, setup_type) | SATISFIED | Cohort filter in PgvectorEpisodicBackend.recall; BackfillJob populates labeled table |
| MEM-03: Memory gated behind AGENT_MEMORY_ENABLED=False | SATISFIED | Settings.agent_memory_enabled=False default; factory returns None when False |
| MEM-04: Latency OTel histogram; recall within 50ms p95 | PARTIAL | MEMORY_RECALL_LATENCY_MS recorded; 40ms timeout configured; but p95 not measured (wiring gap prevents real agent use); embedding at recall time risks the 50ms budget; no RAM footprint documented |

### Anti-Patterns Found

| File | Issue | Severity | Impact |
|------|-------|----------|--------|
| `src/core/ai/base_agent.py:427` | WorkerContext constructed without memory_client= — client stored on swarm but not injected | Blocker | Agents cannot access memory; MEM-01 functionally unmet |
| `src/core/memory/client.py:113` | Embeds context at recall time via Ollama — embedding latency ~30-50ms alone puts 50ms p95 at risk | Warning | 50ms evidence gate may be unachievable without embedding cache or precomputation |

### Human Verification Required

#### 1. p95 Latency Evidence Gate

**Test:** Enable AGENT_MEMORY_ENABLED=True, seed memory_episodes_labeled with ~100 rows for a test cohort, run 1000 recall calls via MemoryClient and measure histogram p95
**Expected:** p95 <= 50ms total (embedding + HNSW query + rerank)
**Why human:** Cannot measure live latency programmatically; Ollama embedding call is a real network call

#### 2. RAM Footprint Documentation

**Test:** With memory enabled, check RSS delta for alpha_swarm daemon; document: asyncio.Queue(500 * avg_episode_dict_size), EmbeddingService httpx client, backend asyncpg pool connections
**Expected:** Documented in phase artifacts or CONTEXT.md
**Why human:** No tooling to measure daemon RSS delta programmatically in this verification

### Gaps Summary

Two gaps block full goal achievement:

**Gap 1 — Critical wiring: WorkerContext not populated (MEM-01)**

The entire agent-facing interface depends on agents receiving `MemoryClient` via `WorkerContext.memory_client`. The WorkerContext dataclass has the field (added in Plan 04), and `build_memory_client` is called in `services/alpha_swarm._setup()` storing the result as `self._memory_client`. However, the actual WorkerContext construction in `src/core/ai/base_agent.py:427` does not pass `memory_client=`. The field is always `None` at agent compute time regardless of the flag setting.

Fix: `base_agent.py` needs a mechanism to receive and forward `memory_client` to WorkerContext. The cleanest path: add `memory_client: MemoryClient | None = None` to `BaseAIWorker.__init__`, set it from the swarm's `self._memory_client` when constructing agents, and pass `memory_client=self._memory_client` in the WorkerContext constructor.

**Gap 2 — Phase goal evidence gate: p95 latency and RAM footprint undocumented**

The phase goal specification requires `recall p95 latency <= 50ms` as an evidence gate and `RAM footprint documented`. Neither is satisfied: (a) no measurement exists because the wiring gap prevents real agent recall; (b) RAM footprint is not documented anywhere. Additionally, the current design embeds context at recall time (Ollama HTTP call), putting the 50ms budget at risk — the reviews flagged this but no resolution was implemented.

These two gaps are related: fixing the wiring gap is prerequisite to measuring the latency gate.

---

_Verified: 2026-06-05_
_Verifier: Claude (gsd-verifier)_
