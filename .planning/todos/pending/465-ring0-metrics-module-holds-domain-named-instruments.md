---
status: pending
priority: P3
filed: 2026-09-29
source: 186 debt pass B10a
---

# Ring 0 metrics module carries domain vocabulary; the boundary check only greps imports

## What

`src/observability/metrics.py` is Ring 0 (portable infrastructure, no domain vocabulary), yet it
defines about 190 instruments whose names are domain terms: `FEATURE_QUALITY_FAILURES` and
`FEATURE_LIFECYCLE_TRANSITIONS` (186-09), `SIGNAL_*`, `REGIME_*`, `FEATURE_IC_SCORE`,
`BAR_AUDITOR_*` and others. The `ring0-boundary` check in `tools/check_plugin_invariants.sh`
greps for `from src.intelligence`, `from src.providers`, `from src.self_healing` and
`from services` only, so a domain name in a Ring 0 file passes.

## Options

1. Move domain instruments to Ring 1. Each domain package owns its instruments
   (`src/intelligence/<area>/metrics.py`) built on a Ring 0 factory in `metrics.py`
   (`counter`, `point_gauge`, `histogram`). Correct by the ring rule, but about 190 names move and
   every import site changes; the exporter's metric names must stay identical.
2. Extend the check with a domain-word list and a legacy allow-list. The check fails on a new
   domain-named instrument in `src/core/` or `src/observability/`; the current 190 are listed
   once and shrink as they move. Cheap, stops new debt now, and does not pretend the old names
   are clean.

## Recommendation

Option 2 now (one session: word list from the glossary's domain terms, allow-list generated from
the current file, the check fails on any name not on it), then option 1 opportunistically per
area, each move deleting its allow-list entries. The 186 instruments (`FEATURE_QUALITY_FAILURES`,
`FEATURE_LIFECYCLE_TRANSITIONS`) move first, since `feature_lifecycle` is the newest and has the
fewest dependents.

## Steps

1. Generate the allow-list and the domain-word list; add the check with a test that a synthetic
   new domain-named instrument fails it.
2. Move the two 186 instruments to `src/intelligence/measure/` or a `feature_lifecycle` module in
   Ring 1 and drop their allow-list entries.
