# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-22)

**Core value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.
**Current focus:** Phase 4 — Query API

## Current Position

Phase: 4 of 6 IN PROGRESS
Plan: 1/3 complete
Status: Phase 4 Plan 1 executed — intelligence_features query route with paginated JSON + Parquet export (TDD, 7/7 tests pass).
Last activity: 2026-02-24 — 04-01: GET /api/features/{symbol}/{timeframe} + GET /api/features/export implemented in features.py

Progress: [█████░░░░░] 50% (11/16 plans complete across Phases 0-4)

## Performance Metrics

**Velocity:**
- Total plans completed: 7 (this milestone)
- Average duration: ~12min
- Total execution time: ~84min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-typed-event-schema | 3 | ~63min | ~21min |
| 02-feature-store | 3 | ~18min | ~6min |
| 03-historical-data | 1/3 | ~3min | ~3min |
| 04-query-api | 1/3 | ~2min | ~2min |

**Recent Trend:**
- Last 5 plans: 02-02 RED (~1min), 02-03 (~2min), 02-02 GREEN (~4min), 03-01 (~3min), 04-01 (~2min)
- Trend: On track, accelerating

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions logged in PROJECT.md Key Decisions table.
Recent decisions from design session (2026-02-22):

- Service consolidation: market_analysis_service.py is the sole canonical I3-I6 pipeline; intelligence_processor_service.py deprecated
- Schema: IntelligenceEvent with tiered JSONB (i1/i3/i4/i5/smc/i6), versioned, platform dimension from day 1
- Feature store: intelligence_features hypertable, NO retention policy (keep for seasonal ML), 7-day compression
- Feature Writer: standalone async service consuming feature_writer:persist consumer group
- Auth: single Depends(verify_auth) handling JWT + API keys
- External access: Cloudflare Tunnel for HTTPS to Vercel frontend

Recent decisions from execution (2026-02-23):

- 01-01: IntelligenceEvent published as single "event" JSON field in Redis stream; extra="forbid" on I3-I6 sub-models
- 01-01: I1Indicators uses extra="allow" (23 plugins, ~50+ dynamic fields); all others strict
- 01-02: _parse_intelligence_event() module-level pattern: pure function, returns None on failure (ack-and-skip)
- 01-02: features dict preserves legacy MARKET_CONTEXT_KEYS names for signal_ledger JSONB stability
- 01-02: smc_trend_direction (schema rename) mapped to SmartMoneyData.trend_direction in dashboard
- 01-02: ai_narrative_service confirmed non-consumer (reads signals: stream only)
- 01-03: Historical plan docs annotated with deprecation banners (not inline edits) to preserve historical accuracy
- 01-03: Stale worktrees out of scope — stale refs in .worktrees/ are on separate branches, not main
- 02-01: intelligence_features hypertable uses tiered JSONB NOT NULL DEFAULT '{}' — protects GIN indexes from column-level NULL
- 02-01: compress_orderby = 'ts ASC' confirmed for intelligence_features (migration 007 lesson applied)
- 02-01: feature_ts/feature_tf nullable on signal_ledger — historical signals before Phase 2 correctly have NULL
- 02-03: feature_ts defaults to None on LedgerEntry — backward compatible, no existing callsite changes needed
- 02-03: Backfill writes NULL for feature_ts/feature_tf — no IntelligenceEvent at replay time; NULL correctly indicates pre-Phase-2 signal
- 02-03: market_analysis_service.py not touched — it publishes IntelligenceEvent but never constructs LedgerEntry
- 02-02: hasattr guards in _maybe_flush for __new__-constructed test instances (metrics not initialized via __init__)
- 02-02: bar + i1 use model_dump() without exclude_none; i3-i6 use exclude_none=True for storage compactness

Recent decisions from execution (2026-02-24):

- 03-01: _pick() inner helper filters keys per sub-model before construction — required for extra='forbid' I3-I6 models receiving merged flat intelligence dict
- 03-01: _build_intelligence_event wraps entire body in try/except: returns None on any failure (never crashes replay loop)
- 03-01: feature_ts=ts populated on signal_ledger when intelligence_features row was written — enables JOIN from signal to feature context (reverses Phase 2 NULL decision which was provisional)
- 03-01: replay_symbol inserts features per bar (not per signal) — every MIN_BARS-qualified bar gets a feature row for maximum ML coverage
- 04-01: route ordering critical: /features/export registered before /features/{symbol}/{timeframe} to prevent FastAPI matching "export" as {symbol} path param
- 04-01: test_app pattern: minimal FastAPI instance mounts router directly — avoids main.py lifespan startup (no DB/Redis in unit tests)
- 04-01: _parse_jsonb() handles None, JSON string, and pre-parsed dict for asyncpg future-proofing
- 04-01: features router NOT wired into main.py in this plan — Plan 03 responsibility

### Pending Todos

None yet.

### Blockers/Concerns

- IBKR TWS must be running on Windows LAN (10.0.0.33) for Phase 3 backfill to run Stage 1 fetch
- Phase 3 backfill duration unknown — 365 days of 1m data across multiple contracts may take significant time; plan accordingly
- Auth (Phase 6) depends only on Phase 4 (API exists), not Phase 5 (ML) — phases can run in parallel if needed

## Session Continuity

Last session: 2026-02-24
Stopped at: 04-01-PLAN.md complete — intelligence_features query route (paginated JSON + Parquet export) implemented in features.py (TDD: 7/7 tests pass). Next: 04-02 (signal_ledger query route) or 04-03 (wire both routers into main.py).
Resume file: None
