---
**Created:** 2026-06-28
**Area:** infra
**Type:** bug_fix
**Priority:** P1
**Effort:** 2-4 hours
**Benefit:** Fixes JSONB codec for all BaseBatch-derived services; eliminates manual json.dumps() workarounds
**Risk:** medium (must audit all call sites for double-encode trap)
**Gate:** None
---

# 002 — BaseBatch JSONB codec root cause: use database_manager.create_pool

## Problem

`BaseBatch._setup_pool()` (`src/core/agent/base_batch.py:124`) calls bare
`asyncpg.create_pool(self._db_dsn, ...)` with no `init=` argument. This means no
JSONB codec is registered on any BaseBatch-derived pool.

`database_manager.create_pool()` calls `asyncpg.create_pool(..., init=_setup_codecs)`
which registers `encoder=json.dumps / decoder=json.loads` for the `jsonb` and `json`
OIDs. Every other DB-using service that goes through `database_manager` gets this codec
automatically and can pass Python dicts directly to JSONB columns.

BaseBatch subclasses (`AlphaPublisher`, `EnsembleTrainer`, etc.) do not get the codec.
This has two consequences:

1. **Forced workarounds at call sites** — `alpha_publisher.py:323` must call
   `json.dumps(e["top_features"])` + explicit `$15::jsonb` cast because asyncpg cannot
   infer the JSONB type from a raw dict. This contradicts the CLAUDE.md rule
   `asyncpg: JSONB → dict (no json.loads()/json.dumps())`.

2. **Double-encode trap** — if BaseBatch is ever "fixed" to use
   `database_manager.create_pool` without simultaneously removing all the manual
   `json.dumps()` call sites, those columns will store JSONB string literals
   (`"\"{ ... }\""`) instead of objects, silently breaking `->>'key'` queries.

## Fix

1. Replace `asyncpg.create_pool(self._db_dsn, ...)` in `BaseBatch._setup_pool()` with
   `database_manager.create_pool(self._db_dsn, ...)` (or equivalent call that passes
   `init=_setup_codecs`).

2. Remove `json.dumps(e["top_features"])` at `alpha_publisher.py:323` and restore plain
   `e["top_features"]` (also remove the `import json` added by commit `af2be1b0` and the
   `::jsonb` explicit cast in the VALUES clause — the codec handles type inference from
   the column OID).

3. Audit all other BaseBatch subclasses for similar `json.dumps()` workarounds and remove
   them.

4. Add a unit test that verifies a BaseBatch-derived service can insert a Python dict into
   a JSONB column without manual serialization.

## Scope

- `src/core/agent/base_batch.py` — `_setup_pool()` change
- `services/alpha_publisher.py` — remove `json.dumps()` + `import json` + `::jsonb` cast
- Any other BaseBatch subclasses with manual `json.dumps()` for JSONB params (grep:
  `grep -n "json.dumps" services/*.py`)

## Risk

The two changes in steps 1 and 2 must land in the same commit. Applying step 1 alone
(adding the codec) without step 2 (removing `json.dumps()`) causes the double-encode
bug in `alpha_publisher`. Applying step 2 alone (removing `json.dumps()`) without step 1
causes the original `TypeError: expected str, got dict` failure.

## Reference

- Root cause confirmed during corpus pipeline completion (2026-06-27), commit `af2be1b0`
- `database_manager._setup_codecs`: `src/core/database_manager.py:21`
- CLAUDE.md rule: `asyncpg: JSONB → dict (no json.loads()/json.dumps())`
