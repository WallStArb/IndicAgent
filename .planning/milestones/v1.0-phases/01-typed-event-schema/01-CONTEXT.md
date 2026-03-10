# Phase 1: Typed Event Schema - Context

**Gathered:** 2026-02-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Define `IntelligenceEvent` as the single canonical typed Pydantic model for all intelligence pipeline output. Update `market_analysis_service.py` to publish validated `IntelligenceEvent` objects. Migrate all consumers (signal_generator_service, SSE route, any other readers) to deserialize via the model. Delete `intelligence_processor_service.py` and all references to it. The stream format changes from flat string k/v to structured tiered JSONB.

Feature persistence (intelligence_features hypertable) is Phase 2. Auth is Phase 6. This phase is purely the schema + migration.

</domain>

<decisions>
## Implementation Decisions

### Sub-tier typing depth
- Every tier gets a **dedicated typed Pydantic sub-model** — not `dict[str, Any]`
- Models live in `src/intelligence/schemas.py` alongside `IntelligenceEvent`
- All models use `model_config = ConfigDict(extra="forbid")` — unknown fields are rejected at the publisher, not silently dropped downstream
- This is the point of the phase: real typed validation, not organized k/v bags
- Sub-models: `OHLCVBar`, `I1Indicators`, `I3Structure`, `I4Context`, `I5Patterns`, `SMCContext`, `I6Confluence`

### i7 exclusion from IntelligenceEvent
- `IntelligenceEvent` does **NOT** include i7 signal output
- Rationale: `IntelligenceEvent` is the feature vector that signal generators *consume* — including i7 creates a circular dependency (publisher would need to know signals before publishing what signal generators read)
- i7 signals live in their own stream (`signals:SYMBOL:TF:aggregated`) and `signal_ledger` — that's the correct boundary
- `source: Literal["live", "backfill"] = "live"` is included for provenance tracking

### i3 tier — keep as distinct tier
- i3 = **structural facts about price**: swing highs/lows (most recent N), support/resistance levels + strength, trend structure state (HH/HL vs LH/LL), session boundaries
- Distinct from i4 ("quantitative regime assessment" — GARCH, Kalman, vol/trend confidence numbers) and i5 ("pattern detection" — squeeze, divergence, BB formations)
- Boundary is meaningful: i3 is the "map" of price structure, i4 is the "assessment" of current regime, i5 is "what's forming right now"
- Keeps tier-specific DB queries surgical (Phase 2 will GIN-index per tier)

### Migration strategy — sequential by service, no compat shim
- **No backward-compatibility layer** — no `to_legacy_dict()`, no dual-format publishing
- Three stages matching the three plan tasks:
  1. `01-01`: Define all schema models + update publisher (market_analysis_service.py) + update all publisher-related tests
  2. `01-02`: Migrate signal_generator_service.py and SSE route + update their tests
  3. `01-03`: Delete intelligence_processor_service.py, audit and migrate any remaining consumers, update remaining tests
- Each commit is a complete, green-tests migration of one service — never leave the repo in a broken state between stages
- 551+ tests stay passing across all three commits

### Schema versioning
- `schema_version: Literal["1.0"] = "1.0"` on `IntelligenceEvent`
- Version is a string literal ("1.0") not an int — allows minor versions ("1.1") without breaking consumers that check for "1.x"
- Consumers that receive an unknown version should log a warning and skip the event (not crash)

### Claude's Discretion
- Exact field names within each sub-model tier (e.g., `rsi_14` vs `rsi14` within I1Indicators)
- Whether to use `model_validator` for cross-field validation within sub-models
- Exact type annotations for complex i3/i5/smc fields (e.g., list of swing points as `list[float]` vs named struct)
- How to handle None/optional fields within sub-models for plugins that may not run on all timeframes

</decisions>

<specifics>
## Specific Ideas

- Design doc at `docs/plans/2026-02-22-unified-intelligence-data-bus-design.md` has the proposed field lists per tier — use as reference for populating sub-model fields
- The `intelligence` table in TimescaleDB currently writes scalar-only via `market_analysis_service.py` — that write path gets updated in `01-02` to emit the structured event (though full persistence moves to Phase 2's feature_writer_service)
- GARCH fields (4) and Kalman fields (7) belong in `I4Context` — they're already computed by Phase 0 and published to the intelligence stream; this migration makes them first-class typed fields
- `extra="forbid"` will catch any plugin that publishes unexpected field names — treat these as test failures, not silently-swallowed data

</specifics>

<deferred>
## Deferred Ideas

- `intelligence_features` hypertable and Feature Writer Service — Phase 2
- Plugin state persistence (get_state/restore_state protocol) — Phase 2 or separate task
- Auth layer — Phase 6
- Cloudflare Tunnel / external access — Phase 6
- ML export endpoint — Phase 5+

</deferred>

---

*Phase: 01-typed-event-schema*
*Context gathered: 2026-02-22*
