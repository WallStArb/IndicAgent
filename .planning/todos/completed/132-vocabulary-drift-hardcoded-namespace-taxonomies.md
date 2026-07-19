---
status: completed
priority: P3
filed: 2026-07-17
closed: 2026-07-19
source: phase 161 execution, /simplify pass (altitude review) — flagged but out of scope for a cleanup pass
---

## Resolution

Fixed (2): added `VocabularyService.known_namespaces()` (returns the frozenset of
namespaces it actually loaded codes for) and `assert_namespace_coverage()` in
vocabulary_drift.py, called at the top of `execute()` -- raises loud if
`_WINDOWED_NAMESPACE_QUERIES`/`_UNWINDOWED_NAMESPACE_QUERIES`'s keys aren't a subset of
what the registry knows, instead of silently querying a namespace with no registered
codes (which would misread every observed code as "unregistered," a false-positive
drift alert).

Left (1) (`_REGISTERED_REGIME_GROUPS` hardcoded frozenset) as-is, per the todo's own
conditional framing -- there's no registered-namespace equivalent to assert against
until `regime_group` is promoted to its own `controlled_vocabulary` namespace, which
the todo explicitly defers to "once there's a second real consumer beyond this guard."

# `vocabulary_drift.py` hardcodes the taxonomies it exists to govern

## Finding

Two self-referential gaps in `src/config/vocabulary_drift.py`, surfaced by the altitude review
during 161's `/simplify` pass:

1. `_REGISTERED_REGIME_GROUPS: frozenset[str] = frozenset({"equity", "rates"})` (line ~48) is a
   hardcoded 2-value taxonomy embedded in the module built to catch exactly this kind of
   scattered hardcoded label set. A future third `regime_group` value requires a manual,
   unenforced Python edit in lockstep with a DB change.
2. `_WINDOWED_NAMESPACE_QUERIES` / `_UNWINDOWED_NAMESPACE_QUERIES` hardcode the six live
   namespace names as dict keys, duplicating the namespace list migration 240 seeds. Nothing
   enforces the two stay in sync if a namespace is added/retired.

Not fixed inline — (1) would require registering `regime_group` as its own
`controlled_vocabulary` namespace (a new migration + reseed), and (2) can't be fully derived
from the DB since the SQL/table mapping per namespace is inherently code, not data. Both are
real design gaps but scope-changing, not cleanup-pass material.

## Fix

- For (1): consider promoting `regime_group` to its own controlled_vocabulary namespace once
  there's a second real consumer beyond this guard, or add a startup assertion.
- For (2): add a startup assertion that `_WINDOWED_NAMESPACE_QUERIES.keys() |
  _UNWINDOWED_NAMESPACE_QUERIES.keys()` is a subset of `VocabularyService`'s known namespaces,
  so drift between the migration-seeded namespace list and this module's query dict fails loud
  instead of silently diverging.
