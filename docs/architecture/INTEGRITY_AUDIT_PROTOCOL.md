# Integrity Audit Protocol (Renaissance Standard)

## 1. Objective
To maintain 100% mathematical parity between legacy database persistence and Agentic Kafka-journaled persistence. This protocol prevents silent data corruption during the transition to the `DataWriterAgent` architecture.

## 2. Parity Audit Protocol
1.  **Dual-Sink Shadowing:** During the migration window, both legacy `services/` code and the new `DataWriterAgent` publish to the database (one to production, one to `feature_snapshots_shadow`).
2.  **Continuous Comparison:** The `ParityAuditorAgent` polls both tables in real-time. It validates:
    - **Row Count Parity:** `SELECT COUNT(*) FROM intelligence_features` vs `feature_snapshots_shadow`.
    - **Vector Parity:** Row-level `WHERE ts, symbol, tf` comparison of the `feature_vector` JSONB content.
3.  **Audit Logs:** Any mismatch is immediately flagged as a `PARITY_VIOLATION` with the specific `BarSequenceID`, `timestamp`, and `diff_vector` exported to the `intelligence.audit` Kafka topic.

## 3. The "Fail-Fast" Policy
- If parity is NOT 100% after 24 hours of production data:
    - **Halt Cutover:** The Producer (Agent) must remain in Dual-Write mode.
    - **Debug:** Review the `ParityAuditorAgent` logs to identify if the error is a deserialization artifact, a timing gap, or a schema mismatch.
    - **Reset:** Flush the `feature_snapshots_shadow` table and restart the audit after code corrections.

## 4. Operational Invariant
A system is not "Production Ready" until it has achieved 100.00% parity across a full RTH (Regular Trading Hours) session without a single `PARITY_VIOLATION`.

---
**Status:** Protocol Active
**Last Updated:** 2026-03-25
