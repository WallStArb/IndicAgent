# Phase 130: Script Rewriting — Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-16
**Phase:** 130-script-rewriting
**Areas discussed:** No interactive discussion — context derived from prior CONTEXT.md files, v2.10 spec, and codebase analysis

---

## Analysis Notes

Phase 130 was well-specified by the v2.10 spec (I1-I9) with all major design decisions locked in Phase 128 (schema ADR) and Phase 129 (column mapping). No interactive gray areas required user input.

## Claude's Discretion

All implementation decisions were made via codebase analysis and prior phase context:

- **CounterfactualTracker scope** — resolved as v2.11 only; REQUIREMENTS.md §Future is authoritative. CLAUDE.md notation "(Phase 130)" in v2.11 seeds list means Phase 130 creates the prerequisite, not the daemon itself.
- **signal_outcomes disposition** — v2.10 spec didn't mention it but it's a lifecycle companion table that must be dropped alongside signal_ledger. Lifecycle state moves to signal_events.status; execution outcomes move to trade_executions.
- **Repository rewrite strategy** — rewrite SignalLedgerRepository in place; rename class and update SQL; all importers get the behavior automatically.
- **swarm_ledger_writer FK check** — update from signal_ledger to signal_events (direct table, no JOIN overhead).
- **Read-only services** — ~10 services that SELECT from signal_ledger/signal_ledger_full work automatically after the view rename; no explicit rewrite needed unless hidden write paths found during planning.
- **New column population** — concurrent_signal_count, concurrent_plugins, regime_at_activation are Phase 130 writer responsibilities per Phase 129 CONTEXT; populated from in-memory signal_tracker state.

## Deferred Ideas

- CounterfactualTracker daemon (v2.11)
- I6 DB bootstrap at startup (v2.11)
- APR ML optimization (v2.11)
- SignalRanker LightGBM (v2.11)
- GIN indexes on context_features/factor_scores (if query patterns warrant — check during planning)
