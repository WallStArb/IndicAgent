---
created: 2026-06-28
priority: low
phase_target: Phase D+ (infrastructure cleanup after v3.0 corpus stable)
tags: [infrastructure, scripts, operations, organization, naming]
---

# Scripts Organization — Restructure and Standardize

## What

Reorganize `scripts/` and `production/scripts/` into a clean directory structure with consistent naming conventions and clear purpose boundaries.

Full audit: `docs/ideas/scripts-organization-audit.md`

## Current Problems

1. **Unclear directory split** — `scripts/` (1 file) vs `production/scripts/` (21 files) with no organizing principle
2. **Naming inconsistencies** — `pipeline_audit.py` vs `pipeline_status.py` (both check pipeline state, unclear difference)
3. **Purpose overlap** — 5 "replay" scripts, 2 "snapshot" scripts, 4 "pipeline" scripts
4. **Dead/one-time code mixed with operational tools** — `db_setup.sh`, `init_kafka_topics.sh` belong in infrastructure/, not production/
5. **No Ring structure** — infrastructure, domain, and ops scripts mixed with no portable layer

## Proposed Structure

```
scripts/
├── ops/                    # operational tools (run regularly)
│   ├── corpus/
│   ├── roll/
│   ├── pipeline/
│   └── signal/
├── infrastructure/         # one-time setup and infrastructure
│   ├── setup/
│   ├── backfill/
│   └── kafka/
└── debug/                  # debugging and analysis tools
    ├── replay/
    ├── validate/
    └── snapshot/
```

## Naming Convention

**Python:** `<domain>_<purpose>_<object>.py`
- `ops_corpus_progress.py`
- `infrastructure_db_setup.py`
- `debug_validate_alpha.py`

**Shell:** `<domain>_<purpose>_<object>.sh`
- `ops_corpus_pipeline_run.sh`
- `infrastructure_backfill_missing_etfs.sh`

## Migration Plan

Phase 1 — Restructure directories (non-breaking):
1. Create new directory structure
2. Move all scripts to new locations with updated names
3. Update shebangs, imports, and documentation references

Phase 2 — Cleanup and consolidation:
- Remove duplicate `validate_roll_detection.py`
- Audit `replay_*` scripts for functional overlap
- Clarify snapshot script purposes

Phase 3 — Documentation:
- Update operations-infrastructure.md
- Add scripts-reference.md catalog

## Dependency

Defer until v3.0 corpus pipeline is stable. This is infrastructure cleanup — not blocking for any active feature work.
