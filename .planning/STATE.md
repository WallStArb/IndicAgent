# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-22)

**Core value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.
**Current focus:** Phase 6 — Dashboard Connected (Phase 5 complete; 06-01 and 06-02 done 2026-02-25)

## Current Position

Phase: 6 of 7 IN PROGRESS
Plan: 2/4 complete
Status: Phase 6 (Dashboard Connected) in progress. 06-01: TimeframeBuilder + ibkr currency fix. 06-02: event.tf bug fixed, session tracking, price-hero rebuilt with activeTf/VWAP/session range.
Last activity: 2026-02-25 — Phase 6 Plan 02 complete (stream audit + price hero rebuild)

Progress: [██████░░░░░] ~71% (18/25 plans complete across Phases 0-6)

## Performance Metrics

**Velocity:**
- Total plans completed: 10 (this milestone)
- Average duration: ~11min
- Total execution time: ~108min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-typed-event-schema | 3 | ~63min | ~21min |
| 02-feature-store | 3 | ~18min | ~6min |
| 03-historical-data | 1/3 | ~3min | ~3min |
| 04-query-api | 3/3 | ~6min | ~2min |
| 05-live-pipeline | 1/3 | ~4min | ~4min |
| 06-dashboard-connected | 2/4 | ~22min | ~11min |

**Recent Trend:**
- Last 5 plans: 04-02 (~2min), 04-03 (~2min), 06-01 (~4min), 06-02 (~18min)
- Trend: On track, accelerating

*Updated after each plan completion*

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 06-dashboard-connected | P01 | 4min | 2 | 4 |
| 06-dashboard-connected | P02 | 18min | 3 | 5 |

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

- 05-01: TWS false-connected check uses self.connected and self.provider guard before calling provider.is_connected() — safe even when provider is None
- 05-01: feature_writer follows market_analysis_service pattern exactly: try/except Settings() inside _load_config, pass _settings to get_active_contracts()
- 05-01: indicagent-timeframes.service created in repo; requires manual sudo install (interactive auth gate)
- 03-01: _pick() inner helper filters keys per sub-model before construction — required for extra='forbid' I3-I6 models receiving merged flat intelligence dict
- 03-01: _build_intelligence_event wraps entire body in try/except: returns None on any failure (never crashes replay loop)
- 03-01: feature_ts=ts populated on signal_ledger when intelligence_features row was written
- 03-01: replay_symbol inserts features per bar (not per signal) — every MIN_BARS-qualified bar gets a feature row for maximum ML coverage
- 04-01: route ordering critical: /features/export registered before /features/{symbol}/{timeframe}
- 04-01: test_app pattern: minimal FastAPI instance mounts router directly
- 04-01: _parse_jsonb() handles None, JSON string, and pre-parsed dict for asyncpg future-proofing
- 04-02: features key omitted entirely when include_features=False (not set to null)
- 04-02: NULL feature_ts short-circuits to signal["features"] = None
- 04-02: limit is $2 positional param; from_ts=$3, to_ts=$4
- 04-03: IntelligenceEvent constructor in tests requires full field set
- 04-03: SSE payload convention confirmed: {"event": "<IntelligenceEvent JSON string>"}
- 04-03: Pre-existing test failures (test_settings, test_ibkr_provider, test_market_analysis_service) are out-of-scope

Recent decisions from execution (2026-02-25):

- 06-01: TimeframeBuilder uses sliding window aggregation from 1m bars with configurable lookback; no DB writes in service
- 06-01: ibkr.py currency='USD' fix applies to all Future() constructor calls — resolves 6 qualify_instrument failures
- 06-02: tickFlash stored on both SymbolData.tickFlash and tick.tickFlash — price-hero reads from data prop (not internal useEffect), eliminates stale closure
- 06-02: session reset detection uses YYYY-MM-DD date string from payload.timestamp.slice(0,10)
- 06-02: IntelligenceEvent uses tf field not timeframe — event.tf fix corrects TF bucketing for all intelligence data
- 06-02: StatusDot label changed from Offline to Disconnected per DASH-08 spec

### Pending Todos

None yet.

### Blockers/Concerns

- **indicagent-timeframes.service FAILED** — import path wrong (src.data). Non-blocking, fix in Phase 6.
- **Pre-existing unit test failures** (5 tests) — separate bug-fix session, out of scope.

## Session Continuity

Last session: 2026-02-25
Stopped at: Phase 6 Plan 02 complete — stream audit + price hero rebuild done.
Resume file: None
