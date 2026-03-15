---
created: 2026-03-06T05:28:21.537Z
title: Audit and remove dead database tables
area: database
files:
  - production/migrations/001_timescale_schema.sql
  - production/scripts/db_verify.sh
---

## Problem

`technical_indicators` table is orphaned — 4 rows, last written Feb 22–Mar 1, no active
service writes to it. The current pipeline uses `intelligence_features` (full JSONB feature
vectors) instead. Other tables may also be dead weight from earlier architecture iterations.

Carrying dead tables creates confusion about what's authoritative, adds noise to schema
docs, and wastes storage over time.

## Solution

1. `grep -r "technical_indicators" src/ services/` — confirm zero active writes
2. Same audit for any other public tables not referenced by active services
3. For each dead table: write a DROP TABLE migration (e.g. `022_drop_dead_tables.sql`)
4. Update `docs/guides/database-management.md` and `production/scripts/db_verify.sh`
5. Do NOT drop `cis_weights` or `instruments` — referenced by config, not services

Known dead candidates: `technical_indicators`
