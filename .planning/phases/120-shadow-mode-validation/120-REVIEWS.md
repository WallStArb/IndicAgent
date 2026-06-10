---
phase: 120
reviewers: [gemini]
reviewed_at: 2026-06-10T00:00:00Z
plans_reviewed: [120-01-PLAN.md, 120-02-PLAN.md, 120-03-PLAN.md]
reviewer_notes:
  codex: "usage limit exhausted (resets 2026-07-02)"
  ollama: "skipped — live alpha_swarm/narrative_compute services hold persistent Ollama connections"
  claude: "skipped — running inside Claude Code (self-review excluded for independence)"
---

# Cross-AI Plan Review — Phase 120

## Gemini Review

## Cross-AI Plan Review: Phase 120 (Shadow Mode Validation)

### 1. Summary
The plan is highly robust, adhering strictly to the non-negotiable project invariants and the desired Separation of Concerns (SoC) between audit/demotion (shadow_auditor) and promotion (shadow_validator). The logic is well-partitioned, and the sequential 5-gate short-circuit approach efficiently minimizes unnecessary computation while enforcing the promotion criteria. The plan successfully balances observability (OTel gauges), maintainability (surgical removal of legacy promotion logic), and operational rigor (systemd/Grafana).

### 2. Strengths
- **Architectural Alignment**: The decision to separate the weekly promotion validator from the 30-minute demotion auditor is an excellent application of SoC.
- **Gate Logic**: The 5-gate short-circuit (D-02) is logically sound, statistically appropriate, and prioritizes safety by failing fast on insufficient data or negative expectancy.
- **Observability**: Mapping the 6 metrics directly to Grafana and OTel gauges ensures immediate visibility into both the validation process and the status of refactored setups.
- **Operational Rigor**: The use of systemd timers with persistence ensures that the weekly promotion cycle is reliable and standard-compliant.
- **Surgical Precision**: Plan 02's focus on removing only promotion-specific logic while keeping the necessary `bootstrap_ci_lower` for demotion demonstrates a high level of codebase awareness.

### 3. Concerns
- **Migration Numbering (LOW)**: PLAN 01 proposes migration `121`, but migration `120` was already deployed. Verify `production/migrations/` for the latest integer — if `120` is the last deployed, `121` is correct (which the plan already specifies).
- **DB View vs. Table Scan (MEDIUM)**: Creating a view over `signal_ledger_full` (D-04) may result in a sequential scan as the table grows. The query filtering `shadow_tracking_start_ts IS NOT NULL` needs an adequate index to remain performant over time.
- **Metric Dimensionality (LOW)**: Emitting 6 OTel gauges per setup for 21 setups = 126 gauges per run. Within Prometheus limits, but worth confirming the resource footprint stays within the 300s TimeoutStartSec.

### 4. Suggestions
- **Index Verification**: Add a task to confirm `signal_ledger` has an index on `(is_shadow, shadow_tracking_start_ts)` to keep the weekly validator query performant as signal history grows.
- **Alert Payload Completeness**: D-07's CRITICAL Kafka alert should include the full 5-gate result details (which gates passed/failed, actual values vs thresholds) so operators can verify promotions without SQL.
- **Dry-run Flag**: Add a `--dry-run` CLI flag to `shadow_validator.py` that outputs 5-gate results to stdout without writing to `shadow_registry`. Essential for testing against real historical data before the first scheduled run.

### 5. Risk Assessment
**Risk Level: LOW**

The plans are highly specific, follow existing project patterns (`_path_bootstrap`, OTel helpers, Kafka publishing), and the fail-closed promotion logic (must pass all 5 gates) significantly reduces the risk of incorrect promotions. The separation of audit and validation ensures that even if the validator fails, the system remains safe and demotion continues unaffected.

---

## Consensus Summary

Single reviewer (Gemini) — no cross-reviewer consensus to compute.

### Agreed Strengths
- SoC split (shadow_auditor=demotion, shadow_validator=promotion) is architecturally sound
- 5-gate sequential short-circuit is statistically correct and fail-closed
- OTel + Grafana coverage gives full operational visibility
- Surgical removal of _check_promotion from shadow_auditor is precise (bootstrap_ci_lower retained)
- systemd Persistent=true ensures missed weekly fires are caught

### Agreed Concerns
- **MEDIUM**: `signal_ledger_full` view query may need index on `(is_shadow, shadow_tracking_start_ts)` for long-term performance
- **LOW**: Migration numbering (121) should be verified against actual `production/migrations/` directory before execution
- **LOW**: 126 OTel gauge emissions per run — confirm stays within 300s timeout

### Divergent Views
No divergent views (single reviewer).

### Recommendations for Planning
1. The plans are ready to execute as-is. All three concerns are LOW/MEDIUM and can be addressed during execution.
2. Consider adding a `--dry-run` flag to Plan 01 Task 3 as a low-cost safety net for the first live run.
3. Index verification for `signal_ledger(is_shadow, shadow_tracking_start_ts)` can be a one-line check added to Plan 01 Task 2 (or a note in the migration SQL).
