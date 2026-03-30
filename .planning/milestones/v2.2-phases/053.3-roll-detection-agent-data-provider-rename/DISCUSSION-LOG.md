# Phase 53.3 — Discussion Log

**Date:** 2026-03-28
**Mode:** Interactive (discuss)

---

## Gray Areas Presented

Three gray areas identified after design doc review and codebase scout. All three selected for discussion.

---

## Area 1: Consumer Migration

**Question:** When should `signal_generator_agent` migrate from `topic_system_events` to `topic_roll_events`?

**Options presented:**
1. Migrate in 53.3 — clean single-topic subscription, Phase 50 inherits clean consumer
2. Migrate in Phase 50 — dual-publish during 53.3, clean up later

**Selected:** Migrate in 53.3

**Rationale:** `ROLL_MONITOR_ENABLED=false` means the roll code path is dead in production today — zero risk. Phase 50 should inherit a clean DAG, not fix topic subscriptions. Renaissance principle: no technical debt forward.

---

## Area 2: ROLL_MONITOR_ENABLED Flag

**Question:** Does the env var live on in RollDetectionAgent, or does systemd service enable/disable replace it?

**Options presented:**
1. Remove — service is the gate (mirrors CROSS_ASSET_ENABLED removal in v2.0)
2. Keep as agent-level runtime gate

**Selected:** Remove entirely — systemd unit is the gate

**User notes:** "Design like Renaissance would. Jim Simons wouldn't run a daemon that silently discards all its output. Modularity, SoC, no manual tasks, prefer automation."

**Rationale:** An agent that runs but never emits output wastes compute and requires a human to flip a flag. The canonical Renaissance pattern is: start the service = enable the feature. Consistent with CROSS_ASSET_ENABLED removal precedent.

---

## Area 3: tws_daemon.py Rename Strategy

**Question:** Hard git mv now, delay to 53.2, or compatibility shim?

**Options presented:**
1. Hard rename in 53.3 — update all imports, tests, systemd unit
2. Rename in 53.2 — bundle with BarAggregatorAgent work
3. Compatibility shim — CLAUDE.md explicitly prohibits this

**Selected:** Hard rename in 53.3

**User notes:** Consistent Renaissance principles — no shims, no debt, provider-agnostic naming.

**Rationale:** CLAUDE.md prohibits backwards-compatibility re-export hacks. `tws_daemon` name violates provider-agnosticism (also in CLAUDE.md). The rename has bounded scope: one file, one class, one systemd unit.

---

## Summary

All three decisions are Renaissance-aligned: clean cuts, no flags, no shims, no backward-compat debt. The design doc already specified the target state; discussion resolved the transition mechanics.
