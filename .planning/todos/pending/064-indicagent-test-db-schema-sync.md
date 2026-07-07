---
**Created:** 2026-07-07
**Area:** testing-infrastructure
**Type:** infra
**Priority:** P3
**Effort:** 0.5-1 day
**Benefit:** Unblocks `tests/integration/*.py` files that use `get_settings()` and expect a live-migrated schema; removes the need for per-file real-DB override workarounds
**Risk:** low (test-only database; no production impact)
**Gate:** none — standalone infra task
---

# 064 — `indicagent_test` database has no schema (pre-existing, widespread)

**Priority: Low — workaround exists, but affects the whole `tests/integration/` suite**

## Context

Discovered while executing Phase 142.5 Plan 06 (`142.5-06-PLAN.md`), verifying
`tests/integration/test_feature_vectors_schema.py`. `tests/conftest.py` sets
`DATABASE_URL=postgresql://postgres:postgres@localhost:5432/indicagent_test`
at module import time (before any test module runs), and
`src.config.settings.get_settings()` caches a module-level `Settings`
singleton on first construction — so any integration test using
`get_settings()` transparently points at `indicagent_test`.

`indicagent_test` exists as a database but has never had the ~200 production
migrations replayed against it — confirmed via `psql -d indicagent_test -c
'\dt'`: only 3 legacy v2.x SLA tables exist (`signal_events`, `trade_frames`,
`trade_executions`). No `feature_vectors`, `feature_registry`, `config_state`,
`instruments`, etc.

**Confirmed broken (reproduced directly, unrelated to Phase 142.5):**
- `tests/integration/test_instrument_registry.py` — all 3 tests fail (no
  `instruments` table, no `trg_instruments_notify` trigger in `indicagent_test`)

**Existing workaround pattern:** `tests/integration/test_pipeline_flow.py`
hardcodes `DATABASE_URL` to the real `indicagent` DB at module level,
bypassing `get_settings()` entirely, with an explicit comment. Phase 142.5
Plan 06 applied the same idiom to `test_feature_vectors_schema.py` (the one
file in its own scope) rather than fixing the underlying gap.

## Recommended Fix (pick one)

**Option A (preferred):** Replay the full migration history against
`indicagent_test` (`for f in production/migrations/*.sql; do psql -U postgres
-d indicagent_test -f "$f"; done`, matching the existing `docs/reference/
cheatsheet.md` idiom for `indicagent`) and add this as a documented setup
step (or CI step) so it stays in sync going forward. Verify no destructive
side effects from replaying legacy `db/migrations/001/120/121` first if those
are prerequisites.

**Option B:** Audit every file in `tests/integration/` for the same latent
failure mode and standardize on the `test_pipeline_flow.py`-style explicit
real-DB override, documenting `indicagent_test` as intentionally schema-less
(used only by tests that build their own fixtures locally, if any).

## Acceptance Criteria

- [ ] `pytest tests/integration/test_instrument_registry.py -m integration`
      passes without any code changes to that test file (Option A), OR
- [ ] Every `tests/integration/*.py` file explicitly documents which database
      it targets and why (Option B)
- [ ] No regression in `tests/integration/test_pipeline_flow.py` (already
      correct)

## Related

- Phase 142.5 Plan 06 (`142.5-06-SUMMARY.md` Deviations, `deferred-items.md`)
