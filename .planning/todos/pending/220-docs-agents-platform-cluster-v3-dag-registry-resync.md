---
status: pending
priority: P3
filed: 2026-07-31
source: Discovered while closing todo 201 (BaseAgent -> BaseDaemon naming drift) -- a much
  larger, separate staleness problem was found in the same doc cluster and flagged rather than
  fixed, per that todo's own "flag rather than execute a big restructuring" guidance.
---

# `docs/agents/*`, `docs/platform/*`, `docs/architecture/*` service registry tables predate the v3.0 rename and need a full resync

## Context

Closing todo 201 required reading every `BaseAgent`/`BaseDaemon` mention across
`docs/agents/agents-foundation.md`, `agents-operations.md`, `agents-writers.md`,
`docs/platform/platform-foundation.md`, `platform-observability.md`, `platform-self-healing.md`,
and `docs/architecture/architecture-evolution.md`, `architecture-dag-topology.md`. That pass
turned up a second, much larger and orthogonal staleness problem in the same docs: several
embedded "current" tables and diagrams describe the ARCHIVED v2.x pipeline
(`IntelligencePipeline`, `FeatureWriter`, `feature-writer`, `intelligence-pipeline`,
`ParityAuditor`, `FeatureSnapshotWriter`) rather than the live v3.0 Feature Factory registry
(`FeatureVectorPipeline`, `FeatureVectorWriter`, `feature-vector-pipeline`,
`feature-vector-writer`, etc.). This is unrelated to the `BaseAgent` rename itself -- it's the
service registry (`_DAG_ORDER`, `_AGENT_ID_TO_UNIT` in `services/service_auditor.py`) drifting
out of sync with the docs that quote static snapshots of it.

Specific instances found and flagged in-place (inline staleness notes added, tables NOT
resynced):

1. **`docs/agents/agents-operations.md`** -- `_DAG_ORDER`, `_AGENT_ID_TO_UNIT`, and Metrics Ports
   tables reference dead v2.x service names. Also: the per-service Metrics Ports scheme described
   (each daemon on its own numbered port, scraped by the collector) is itself obsolete --
   `BaseDaemon.start()` now pushes OTel metrics via `OTLPMetricExporter` to a central collector at
   `:4317` (`src/observability/otel.py`); there is no per-service scrape port for the standard
   five signals. This part WAS corrected in todo 201's pass (the Metrics Ports section was
   rewritten), but the `_DAG_ORDER`/`_AGENT_ID_TO_UNIT` embedded tables were only flagged, not
   resynced.
2. **`docs/platform/platform-foundation.md`** -- the "L1-L10 Service DAG" ASCII diagram has the
   same v2.x-vs-v3.0 name mismatch. Flagged with an inline staleness note.
3. **`docs/architecture/architecture-dag-topology.md`** -- same issue throughout the "Active
   Services"-style tables and the mermaid diagram (file/unit/port references to
   `intelligence_pipeline_agent.py`, `feature_writer_agent.py`, etc.). Flagged with an inline
   staleness note; only the Agent Taxonomy section (base-class names) was corrected.
4. **`docs/architecture/architecture-evolution.md`** -- the entire document's header claimed
   "Status: current" / "single source of truth for the current production architecture" while
   describing the ARCHIVED v2.x I1-I7 pipeline wholesale (topics, tables, data flow diagram,
   active services list). Re-titled to "Historical Architecture Snapshot (v2.x pipeline,
   ARCHIVED)" as part of todo 201's close, with a header note pointing to CLAUDE.md for current
   state. The body content (v2.0-v2.7 evolution history, Active Services table, Redpanda Topics,
   Database Tables, Data Flow diagram) was left as-is -- it's an accurate historical record but
   was NOT rewritten to reflect v3.0. Consider whether this doc should be archived to
   `docs/architecture/archive/` entirely and replaced with a genuinely current
   "architecture-current-state.md", per this project's `docs/foundation/` canonical-home
   convention.

## Also found (not a registry issue, but same discovery pass)

**CLAUDE.md's own "OTel Health Contract" section is itself now wrong on one label key.**
CLAUDE.md states all five mandatory OTel signals are labeled `agent_id`. Verified against
`src/core/agent/base.py`: `agent_crash_total`'s label key is actually `agent`
(`self._crash_attrs = {"agent": self._agent_label}`; `AGENT_CRASH_TOTAL.add(1, self._crash_attrs)`)
-- the other four signals (`agent_last_message_timestamp_seconds`, `agent_dlq_total`,
`watchdog_notify_total`, `watchdog_notify_suppressed_total`) do use `agent_id`. This was corrected
in the three in-scope docs that had the same claim (`docs/platform/platform-self-healing.md`,
`docs/platform/platform-observability.md`) during todo 201's close, but CLAUDE.md itself was left
untouched (out of scope for a `docs/`-only todo -- CLAUDE.md is the repo root file, and editing it
wasn't part of todo 201's authorized scope). **This is probably higher priority than the rest of
this todo** -- CLAUDE.md is the override-everything reference doc; a wrong label key there could
send someone querying Prometheus with the wrong key for exactly one of the five signals.

## What needs to happen

1. **CLAUDE.md fix (do this first, it's small and high-value):** correct the OTel Health Contract
   bullet to note `agent_crash_total` uses label key `agent`, not `agent_id`, while the other four
   signals do use `agent_id`.
2. Full resync of `_DAG_ORDER` / `_AGENT_ID_TO_UNIT` / lag-threshold-key listings in
   `agents-operations.md`, `platform-foundation.md`, and `architecture-dag-topology.md` against
   the live `services/service_auditor.py` (get the complete current file, not just greps of it --
   there are ~50 entries across priorities 0-11 as of 2026-07-31, including many oneshot
   Phase 138/139/142 services that don't appear in any of the current doc tables at all).
3. Decide whether `architecture-evolution.md` should be moved to `docs/architecture/archive/` and
   replaced by a real current-state doc, or left in place with its new historical framing --
   this project's own `docs/foundation/` canonical-home convention implies stale "current" docs
   should not sit in the live tree indefinitely.

## Acceptance criteria

- [ ] CLAUDE.md's OTel Health Contract section states the correct label key per signal (four
      `agent_id`, one `agent` for `agent_crash_total`)
- [ ] `_DAG_ORDER`/`_AGENT_ID_TO_UNIT` tables in the three flagged docs match
      `services/service_auditor.py` exactly (spot-checked, not just eyeballed)
- [ ] `architecture-evolution.md`'s fate (archive vs. rewrite) is decided and executed, not left
      as an open question
