---
status: completed
priority: P3
filed: 2026-07-29
completed: 2026-07-31
source: Discovered during a general docs/tests/code cleanup pass (background audit agent),
  cross-checked directly against live code before filing
---

## Completed 2026-07-31

Read `src/core/agent/base.py` (`BaseDaemon`), `src/core/agent/base_writer.py` (`BaseWriter`), and
`src/core/agent/base_batch.py` (`BaseBatch`) in full to establish ground truth, then went
section-by-section through the 5 named docs plus 3 more that the acceptance-criteria grep also
covers (`docs/architecture/architecture-dag-topology.md`, `docs/platform/platform-observability.md`,
`docs/platform/platform-self-healing.md` — not named in the original filing but caught by
`grep -rn "BaseAgent" docs/agents/ docs/platform/ docs/architecture/`).

**This was NOT just a naming issue** — real behavioral drift was found and fixed beyond the
rename, verified against the live code:

- `agents-foundation.md`: the `_run()` lifecycle diagram was missing the entire Phase 109 config
  integration (`_pre_setup_config_load()` / `_setup_config_consumer()` / `_teardown_config_consumer()`).
  Log event names were wrong (doc said `agent.*` prefix; code uses `daemon.*` — e.g.
  `daemon.starting`, `daemon.run_failed`, `daemon.setup_failed`). The stated log-path convention
  (`logs/<name>_agent.log`) contradicted both the code (`f"logs/{name}.log"`, no suffix) and the
  doc's own worked example. The "Minimal Agent Recipe" had a syntax error
  (`BaseAgent:(BaseAgent):`) and used `except Exception as exc:`, violating CLAUDE.md's
  `except X as error:` convention.
- `agents-writers.md`: the `_parse_payload` contract was described as a single `list | [] | None`
  return (matching what CLAUDE.md's Key Rules section still says today) but the live code's
  abstract method signature is `_parse_payload(self, payload: dict) -> tuple[list, list]` —
  `(valid_rows, invalid_rows)`, with DLQ firing only when `invalid and not valid`. This is a
  materially different contract (partial-success payloads no longer force an all-or-nothing DLQ),
  and CLAUDE.md's own documented contract is now stale as a result (flagged, not fixed — CLAUDE.md
  is outside this todo's scope). Also fixed a stale pool-creation recipe (bare
  `asyncpg.create_pool()` instead of `database_manager.create_pool()`, which registers the JSONB
  codec per CLAUDE.md's asyncpg gotcha).
- `agents-operations.md`: `_LAG_THRESHOLDS` is no longer a hardcoded dict — it's now
  `alert.lag.*` APR keys in `config_state`, hot-reloaded via Kafka (`_load_lag_thresholds()`).
  `_AGENT_ID_TO_UNIT` is used by every `BaseDaemon` subclass for stall detection, not just
  `BaseWriter` as the doc claimed. The "Metrics Ports" section described a pull/scrape model
  (each service on its own numbered port) that contradicts the actual push model
  (`OTLPMetricExporter` → central collector `:4317`, confirmed via `src/observability/otel.py`).
- `platform-self-healing.md` / `platform-observability.md`: `agent_crash_total`'s documented
  label key (`agent_id`) does not match the code (`agent` — verified via
  `self._crash_attrs = {"agent": self._agent_label}` in `base.py`). The self-healing doc's
  watchdog code sample also reproduced a real, already-fixed bug (`interval_s * 2` suppress
  threshold instead of `max(max_idle_seconds, interval_s * 2)`, which used to let systemd kill
  long-`max_idle_seconds` services before `_stall_watchdog` got a chance to fire).
- `architecture-evolution.md`: beyond the `BaseAgent` → `BaseDaemon` table fix, the whole doc's
  premise ("Status: current", "single source of truth for the current production architecture")
  was wrong — it describes the ARCHIVED v2.x I1-I7 pipeline wholesale. Re-titled to "Historical
  Architecture Snapshot (v2.x pipeline, ARCHIVED)" with a header note pointing to CLAUDE.md for
  current state; the v2.1 "BaseAgent unification" bullet was left as-is since it's accurate
  history, correctly framed inside an "Architecture Evolution" narrative.

**Flagged rather than fixed** (out of scope for a naming-drift todo, filed as
[220](pending/220-docs-agents-platform-cluster-v3-dag-registry-resync.md)): the embedded
`_DAG_ORDER`/`_AGENT_ID_TO_UNIT` snapshots across `agents-operations.md`, `platform-foundation.md`,
and `architecture-dag-topology.md` reference dead v2.x service names
(`feature-writer`/`intelligence-pipeline` instead of `feature-vector-writer`/`feature-vector-pipeline`)
— a separate, much larger staleness problem caused by the v2.x→v3.0 service rename, not the
`BaseAgent`→`BaseDaemon` class rename. Also flagged: CLAUDE.md's own OTel Health Contract section
has the same wrong `agent_crash_total` label key found in the docs above — out of scope to touch
here (CLAUDE.md is outside `docs/`), captured in todo 220 instead as the first, highest-value item.

Verified `grep -rn "BaseAgent" docs/agents/ docs/platform/ docs/architecture/` — every remaining
hit is explicitly framed as historical/naming-note ("renamed from," "formerly named," "corrected
2026-07-31"), satisfying the acceptance criteria.

**Not folded into a single doc:** confirmed the 3 `docs/agents/*` files are not simply redundant
with `platform-foundation.md` — `agents-foundation.md`/`agents-writers.md` are class-contract
references (BaseDaemon/BaseWriter internals), while `platform-foundation.md` is infrastructure/
deployment-focused (systemd, Docker, env vars). Real overlap exists only in the DAG/registry
tables (now the subject of todo 220), not in the core content — no restructuring done, per this
todo's own instruction not to execute a large restructuring without it being obviously trivial.

# `docs/agents/*`, `docs/platform/platform-foundation.md` describe a `BaseAgent` class that no longer exists

## Context

`docs/agents/agents-foundation.md`, `agents-operations.md`, `agents-writers.md` (all stamped
"Version 2.8.0 | Status: current | Last Updated: 2026-05-29") and `docs/platform/platform-foundation.md`
are built around a `BaseAgent` class/contract. Confirmed by direct grep: `grep -rn "class BaseAgent"`
returns nothing anywhere in the repo. `src/core/agent/base.py` defines `BaseDaemon`; `BaseAgent`
has zero live references in `services/`/`src/core/`. The `docs/architecture/architecture-evolution.md`
table also cites `BaseAgent` as the current base class for Provider/Merger/Compute/Auditor/Writer
roles.

This is a whole-cluster staleness, stamped "current" from May 2026, that was never updated for
the v3.0 `BaseDaemon`/`BaseWriter`/`BaseBatch` split CLAUDE.md now documents as canonical.

## Why this wasn't fixed inline during the cleanup pass that found it

A same-session cleanup pass already fixed a related but mechanical defect — dead filename
references (`service_auditor_agent.py` etc. → the `_agent` suffix was retired from Ring 2 file
names, confirmed intentional policy per `docs/reference/renaissance-naming-philosophy.md:623`) —
across ~15 live docs via straight find/replace, safe because only the filename changed, not the
class's behavior.

`BaseAgent` → `BaseDaemon` is a different, riskier class of edit: these docs describe the base
class's *contract* (lifecycle hooks, method names, setup/teardown behavior), and `BaseDaemon`'s
actual current contract may have changed beyond just the name during the same refactor that
renamed it. A blind sed replace risks producing confidently-wrong documentation if any described
behavior diverged. Needs an actual review pass (read `src/core/agent/base.py`'s current contract,
compare section-by-section against what each doc claims), not a mechanical rename.

## What needs to happen

1. Read `src/core/agent/base.py` (`BaseDaemon`) and the `BaseWriter`/`BaseBatch` subclasses to
   establish the current, accurate contract.
2. Go through `docs/agents/agents-foundation.md`, `agents-operations.md`, `agents-writers.md`,
   `docs/platform/platform-foundation.md`, and `docs/architecture/architecture-evolution.md`
   section by section, correcting both the class name and any contract details that have drifted
   (not just `s/BaseAgent/BaseDaemon/`).
3. Update each doc's "Last Updated" stamp and version, or fold into a single current doc if the
   three `docs/agents/*` files turn out to be largely redundant with `docs/platform/platform-foundation.md`
   once corrected.

## Acceptance criteria

- [x] `grep -rn "BaseAgent" docs/agents/ docs/platform/ docs/architecture/` returns nothing (or
      only historical mentions clearly marked as such)
- [x] Each corrected doc's content verified against the live `src/core/agent/base.py` contract,
      not just renamed
