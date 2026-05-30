# Latency & Persistence Architectural Improvements

**Version:** 1.0
**Status:** draft
**Priority:** high
**Milestone:** v2.8
**Last Updated:** 2026-05-16
**Tags:** latency, persistence, hot-path, kafka, dag, signal-generation, architecture, audit

## Goal
Decouple signal generation from I/O-bound persistence to achieve sub-millisecond signal latency, while maintaining rigorous auditability and data integrity.

## Core Pillars
1.  **Hot/Cold Path Separation:**
    *   **Hot Path (Trading):** Signal generation and execution logic must never `await` database I/O. Use a "Fire-and-Forget" Kafka-first approach.
    *   **Cold Path (Analytics/Audit):** A dedicated `PersistenceCoordinator` service consumes Kafka events asynchronously and handles batch persistence (e.g., PostgreSQL `COPY` or Parquet dumps).

2.  **Zero-Copy Instrumentation:**
    *   Inject `ProvenanceChain` and `ExecutionTime` via Kafka binary headers (Zero-copy).
    *   Avoid string-based logging/serialization in the signal path. Use Protobuf/MsgPack.

3.  **Unified Intelligence Journaling:**
    *   Stop fragmented database writes.
    *   All system state, provenance, and audit data must be bundled into a single atomic `IntelligenceJournal` record published to a Kafka "Journal" topic.

4.  **Scientific Integrity:**
    *   Implement "Shadow Computation" sidecars for mathematical verification.
    *   Enforce compute budgets per-plugin (Liveness & Compute Tracker).

## Implementation Steps
1.  **Refactor Producers:** Move to Protobuf/MsgPack for Kafka serialization.
2.  **Build PersistenceCoordinator:** Create an asynchronous service to sink Kafka journals to the DB in bulk batches.
3.  **Instrument Base Class:** Create `RenaissancePlugin` base class to automate header injection (Provenance/Latency).
4.  **DAG Decoupling:** Audit the hot path for any `await db.insert()` calls and replace them with Kafka `publish()` operations.
