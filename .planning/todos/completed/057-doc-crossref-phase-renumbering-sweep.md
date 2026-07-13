# Idea docs referenced pre-renumbering phase numbers — swept and closed

**Closed 2026-07-13.** This todo tracked stale phase-number prose across two ROADMAP
renumbering rounds (2026-07-04 and 2026-07-13). Both are now fully swept — every file
identified in either round has been corrected to current numbers. Nothing currently in
`docs/research/`, `.planning/ROADMAP.md`, `.planning/todos/PRIORITIES.md`, or any `pending/`/
`deferred/` todo references a stale phase number.

Files touched, second round (2026-07-13): `.planning/ROADMAP.md` (full pass, including the
v3.0a IntegrityMonitor details block), `docs/research/2026-07-08-intelligence-lifecycle-backlog-matrix.md`,
`.planning/todos/PRIORITIES.md`, `docs/research/data-edge-source-thesis.md`,
`docs/research/platform-canonical-simulator.md`,
`docs/research/intel-confluence-detection-persistence-layer.md`,
`docs/research/stratification-dimension-unification.md`,
`docs/research/measurement-governance-monitor.md`, and todos 111, 056, 083, 077, 036, 019, 070,
097, 060, 104, 026, 033, 074, 073.

Two files from the original list needed no changes: `docs/research/concept-governance-registries.md`
and `docs/research/intel-case-substrate.md` were already current.

`docs/research/archive/*`, `docs/plans/archive/*`, and `.planning/todos/completed/*` were
deliberately left untouched in both rounds — frozen historical record, not live
cross-references.

**Why this is closed instead of kept open for "next time":** a todo that tracks documentation
staleness but never gets executed isn't tracking work, it's tracking a decision not to do the
work. If a phase gets renumbered again, that's a new, bounded sweep against the live grep
output at the time — not a reason to reopen this list.
