---
status: pending
priority: P3
filed: 2026-07-29
source: Discovered during a general docs/tests/code cleanup pass (background audit agent),
  cross-checked directly against live code before filing
---

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

- [ ] `grep -rn "BaseAgent" docs/agents/ docs/platform/ docs/architecture/` returns nothing (or
      only historical mentions clearly marked as such)
- [ ] Each corrected doc's content verified against the live `src/core/agent/base.py` contract,
      not just renamed
