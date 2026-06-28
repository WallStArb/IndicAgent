---
**Created:** 2026-06-28
**Area:** infra
**Type:** new_feature
**Priority:** P2
**Effort:** 2-3 days
**Benefit:** PostgreSQL ENUM prevents typos; schema-level validation of status/entry_type values
**Risk:** medium (migration required)
**Gate:** Phase 134 completion
---

---
created: 2026-06-18
priority: low
phase_target: Phase C+ (v3.0 alpha_events era)
v3_note: Phase 134 dependency is v2.x signal_events; v3.0 equivalent would seed alpha_events taxonomy; defer until alpha_events schema is stable post-Phase 138
tags: [architecture, vocabulary, taxonomy, modularity, dashboard, api]
---

# Controlled Vocabulary System (Phase 135)

## What

Build a central, reusable vocabulary and taxonomy registry — the APR equivalent for symbolic codes. Three tables (`controlled_vocabulary`, `vocabulary_group`, `vocabulary_group_member`), one `VocabularyService`, one `/api/vocabulary/{namespace}` endpoint. Any domain registers its enum vocabulary into a namespace; any consumer reads it without hardcoding.

Full design: `docs/plans/2026-06-18-controlled-vocabulary-system.md`

## Why

Ten+ enums scattered across Ring 0 and Ring 1 with zero discoverable metadata. Taxonomy groupings (`WIN_OUTCOMES`, `STOP_OUTCOMES`, `TTL_OUTCOMES`) are Python frozensets invisible to SQL and the dashboard. Every filter panel and API consumer that needs "all winning outcomes" either hardcodes the list or re-imports the frozenset — distributed maintenance debt that compounds as the analyst surface grows.

## Dependency

**Blocked on Phase 134 completion.** Plan 03 of Phase 134 converts `signal_outcome`, `entry_type`, and `signal_status` to PostgreSQL ENUM types. The vocabulary seeding must reference values already enforced at the DB level.

## Scope for Phase 135

- Migration: create 3 tables
- Seed: `signal_outcome`, `entry_type`, `signal_status` with labels, descriptions, taxonomy groups
- `VocabularyService` with startup enum-divergence check (hard crash on mismatch)
- `/api/vocabulary/{namespace}` endpoint
- First consumer: dashboard signal filter dropdowns

Add `market_regime`, `signal_grade`, `timeframe` namespaces only when a concrete consumer needs them.
