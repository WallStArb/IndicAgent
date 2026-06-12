---
phase: 122
reviewers: [gemini]
reviewed_at: 2026-06-12T00:00:00Z
plans_reviewed: [122-01-PLAN.md, 122-02-PLAN.md, 122-03-PLAN.md, 122-04-PLAN.md, 122-05-PLAN.md, 122-06-PLAN.md, 122-07-PLAN.md]
notes: "Codex exec failed (exit 1); Ollama returned empty output; claude skipped (self). Gemini only."
---

# Cross-AI Plan Review — Phase 122

## Gemini Review

# Cross-AI Plan Review: Phase 122

## 1. Summary
Phase 122 is a critical infrastructure stabilization and schema hardening milestone. It addresses historical/live pipeline divergence, enforces strict I2 output contracts, eliminates UUID non-determinism, and implements a fast I7 replay path (`feature_replay.py`). The design is sound, the rollout sequence respects the required dependency chain (DDL before code), and the technical debt reduction is substantial.

## 2. Strengths
- **Pipeline Symmetry:** Using the same `tiered.get("i2", {})` construction path for both live and historical pipelines (Plan 02/04) is a textbook fix for training/production bias.
- **Contract Strictness:** Enforcing `extra="forbid"` in `I2Events` and enabling schema validation in `register_plugins.py` is the correct, proactive approach to catch plugin-tier drift.
- **Migration Safety:** The use of `ADD COLUMN IF NOT EXISTS` and explicit `UPDATE` statements for backfilling/cleaning `market_context` demonstrates a high level of operational safety.
- **Deterministic Replay:** Replacing `uuid4()` fallbacks with loud errors ensures that replay results are bit-for-bit reproducible, essential for signal integrity.
- **Optimization:** Building a dedicated I7-only replay path (`feature_replay.py`) drastically reduces the cost of shadow re-runs, facilitating faster model iteration.

## 3. Concerns
- **ID Determinism (MEDIUM):** The switch from random IDs to deterministic IDs (Plan 06) will cause duplicate key violations if replayed over existing `signal_ledger` data where random IDs were previously used. *Mitigation:* signal_ledger was already truncated before this phase — no old random-ID rows exist. ON CONFLICT DO UPDATE handles future idempotency correctly.
- **ATR Fallback (LOW):** Plan 05 (ATR floor fix): replacing hardcoded `0.5` with `get_atr_with_floor` may suppress more signals in low-volatility sessions. This is intentional (Renaissance quality gate) but signal volume should be monitored post-deploy.
- **None/None Ambiguity (LOW):** i2 columns defaulting to `'{}'` during transition window is handled correctly by migration 124.

## 4. Suggestions
- Add a metric to `feature_replay.py` tracking None results from `_reconstruct_intelligence_event` for data quality monitoring.
- Verify zone_engine ATR None guard doesn't disproportionately prune signals in low-volatility regimes.

## 5. Risk Assessment: MEDIUM
**Justification:** Core data persistence and pipeline logic touched. Designs are sound (idempotent migrations, pipeline symmetry, crash-on-drift enforcement), but column renames + schema updates + deterministic ID enforcement require coordinated deployment. Rollback paths (DDL-based) are adequate.

---

## Consensus Summary

Single reviewer — no consensus aggregation available.

### Key Findings
- Plans are well-architected and ready for execution
- Dependency ordering (migration 124 → feature_writer → intelligence_pipeline) is correctly respected in wave structure
- uuid4 concern is a non-issue given signal_ledger was truncated before this phase
- ATR floor behavioral change is worth monitoring post-deploy
