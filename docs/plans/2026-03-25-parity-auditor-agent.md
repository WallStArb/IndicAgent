# Plan: Parity Auditor Agent (Shadow Audit)

## Objective
Implement an `AuditAgent` that ensures mathematical parity between the legacy database persistence path and the new Agentic persistence path during the shadow rollout phase.

## Strategy
- **Continuous Comparison:** The `AuditAgent` subscribes to both `intelligence.feature.processed` (via the `FeatureHistorianAgent`) and the legacy DB `intelligence_features` table.
- **Invariant Assertions:** It checks for record-level parity (ts, symbol, feature_vector) between the two sources.
- **Reporting:** Mismatches trigger a `PARITY_VIOLATION` event on the `intelligence.audit` topic for manual review.

## Implementation Steps
1. **Audit Agent:** Create `src/intelligence/audit/parity_auditor_agent.py`.
2. **Comparison Logic:** Implement a side-by-side comparison of data frames/vectors from Kafka vs DB.
3. **Anomaly Routing:** Use `structlog` to output structured audit logs for Grafana dashboards.

## Verification
- **Success Criteria:** 0 discrepancies for a 24-hour cycle of real-time market data.
- **Audit Trace:** All violations must be actionable with specific `BarSequenceID` identifiers.
