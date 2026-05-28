# Plan: Architectural Hardening & Intelligence Layer Unification

**Version:** 1.0
**Date:** 2026-05-02
**Last Updated:** 2026-05-02
**Status:** Planning

## Executive Summary
Transition the system from a linear, quant-only TA engine to a decoupled, multi-domain "Intelligence Fabric." The strategy focuses on hardening the existing quantitative pipeline while establishing a standardized "Universal Context" interface to ingest qualitative, fundamental, and macro intelligence without introducing tight coupling.

The key refinement: use the existing `AIContext` / `AIContextCache` prompt contract as the consumer surface, and treat qualitative intelligence as an additive context layer stored in the feature table rather than a separate world-view subsystem.

Operationally, each domain must remain independently runnable. The qualitative layer cannot require the quant pipeline, and a quant outage must not stop qualitative ingestion, normalization, or persistence. Shared hot/warm/cold storage is acceptable and desirable as long as the services remain decoupled.

## Architectural Refinement

The unified intelligence layer should be a set of **domain-owned streams plus optional read models**, not a central controller. "World view" is a consumer projection assembled from durable facts; it must not become required runtime infrastructure for quant, qualitative, macro, or AI ingestion.

Canonical ownership:

| Domain | Canonical truth | Optional projection/cache |
|---|---|---|
| Quant features | `intelligence.journal`, `intelligence_features` | `AIContext`, dashboard views, ML exports |
| Signals | `signal_ledger` | model/scoring feature matrices |
| Qualitative context | `ctx_events`, `ctx_snapshots` | `intelligence_features.ctx`, prompt context |
| LLM/AI calls | `llm.calls`, `llm_calls`, `narratives` | model score summaries |
| ML decisions | model registry + shadow evaluation tables | promoted model score stream |

Integration rule: if a projection/read model is down, source-domain ingestion and compute continue. Consumers degrade by missing context, not by blocking upstream agents.

## Current vs Target Stream Contract

Current production contract:

- `intelligence.journal` is the canonical per-bar I1-I7 feature record.
- `intelligence.i7.signals` carries ranked I7 candidates before ledger write.
- Tier-specific `intelligence.i1`, `intelligence.i2`, etc. topics are not the current canonical integration path unless implemented in `src/core/stream_keys.py`.

Target contract:

- Tier-specific topics may be added only when a real consumer, replay, or scaling need justifies the extra stream surface.
- Until then, AI/ML/context consumers should use `intelligence.journal`, `intelligence_features`, or explicitly versioned derived topics.

## Phase 1: Quant Pipeline Hardening (Infrastructure/Foundation)
- [ ] **P-CTX-01: Schema Foundation**
    - [ ] Add `ctx` JSONB column to `intelligence_features` database table.
    - [ ] Add an optional bridge that resolves `ctx` by event-time validity at insert time when the quant feature store is available.
    - [ ] Update AI prompt rendering engine to automatically render `ctx` tiers into LLM features.
- [ ] **P-QUANT-01: Modularization**
    - [ ] Decouple `IntelligencePipelineComputeAgent` logic into a versioned library in `src/intelligence/indicators/vN/`.
    - [ ] Ensure full test coverage of isolated indicator logic.

## Phase 2: Unified Intelligence Layer (The Context Hub)
- [ ] **P-HUB-01: Unified Context Interface**
    - [ ] Define a single additive context contract that extends the existing `AIContext` shape.
    - [ ] Standardize output schemas for `quant`, `qual`, and `macro` pipelines at the serialization boundary only.
- [ ] **P-HUB-02: Consumer Read Model**
    - [ ] Develop an optional `WorldViewReadModel` / `ContextResolver` that aggregates streams for consumers that need a combined view.
    - [ ] Ensure the read model is never on the hot path and is not required for any domain pipeline to run.
    - [ ] Implement graceful degradation logic (e.g., if `qual` stream is silent, consumers render missing context and continue).

## Phase 3: Domain Expansion
- [ ] **P-QUAL-01: Qualitative Foundation**
    - [ ] Implement `ai-10-qualitative-intelligence-layer.md` structure (tables, writer agent).
- [ ] **P-MACRO-01: Macro Foundation**
    - [ ] Define macro stream ingestion for economic calendar/macro data.

## Design Corrections
- Do not mutate the latest bar row when qualitative context arrives. That creates hidden race conditions and can accidentally rewrite a bar after a newer bar has already landed.
- Keep `ctx_snapshots` as the source of truth for time validity and let the feature writer resolve the correct snapshot during bar persistence.
- Avoid introducing a second prompt-facing schema unless a new consumer needs one. The current `AIContext` already gives us an open-ended extension point.
- Treat macro/earnings/news ingestion as independently shippable lanes, not a single monolith.
- Treat the quant feature-store bridge as optional. The qualitative layer should remain functional if the quant stack is offline.
- Prefer shared storage tiers over duplicated stores when the schema and retention model align. Do not let shared storage become a hidden service dependency.
- Do not split additional tier topics until a concrete consumer or scaling bottleneck requires them.
- Do not let qualitative or LLM outputs affect I7 confidence, signal selection, or position sizing until they pass shadow-mode statistical validation.

## First Implementation Slice

Ship the smallest useful context path before broadening scope:

1. Add `ctx_events`, `ctx_snapshots`, and `intelligence_features.ctx`.
2. Add `topic_ctx_snapshot()` and a `CtxWriterAgent` skeleton.
3. Implement one deterministic context lane first: macro calendar or earnings.
4. Update `AIContextCache.seed_from_db_row()` and prompt rendering to include `ctx`.
5. Add staleness/provenance metadata to every context object.
6. Keep news sentiment out of the first slice; it introduces NLP quality, provider bias, and latency concerns that are easier to handle after the substrate is proven.

## Guiding Principles (Renaissance Mandate)
- **Decoupled-by-Design:** No agent requires another to run.
- **Contract over Code:** Schemas define integration; no shared internal code.
- **Instrument Everything:** Observability metrics for all stream ingestion.
- **Data-First:** Storage and history are primary.
