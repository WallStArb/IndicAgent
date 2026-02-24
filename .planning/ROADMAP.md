# Roadmap: IndicAgent Unified Data Bus

## Overview

This milestone transforms IndicAgent from a reactive signal pipeline with ephemeral Redis state into a canonical typed intelligence bus with durable feature storage, ML-ready historical data, and externally accessible APIs. Phase 0 (GARCH/Kalman quality gates) is already complete. Phases 1-6 replace the flat string stream format with a versioned Pydantic schema, build the persistence layer behind it, run the backfill to populate it, expose it via query APIs, train an ML scoring model on the accumulated data, and finally gate external access behind auth.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 0: GARCH/Kalman Quality Gates** - Wire GARCH/Kalman outputs into I7 plugins as entry filters (COMPLETE 2026-02-22)
- [ ] **Phase 1: Typed Event Schema** - Define IntelligenceEvent Pydantic schema, update publisher, migrate consumers, deprecate old service
- [x] **Phase 2: Feature Store** - intelligence_features hypertable, Feature Writer Service, signal_ledger enhancement (completed 2026-02-23)
- [ ] **Phase 3: Historical Data** - Run 365-day backfill populating signal_ledger and intelligence_features
- [ ] **Phase 4: Query API** - Historical feature and signal query endpoints on existing FastAPI
- [ ] **Phase 5: ML Scoring Model** - Train predictive model on intelligence_features, score signals at generation time
- [ ] **Phase 6: Auth and External Access** - JWT+API key auth layer, Cloudflare Tunnel, authenticated SSE for external consumers

## Phase Details

### Phase 1: Typed Event Schema
**Goal**: Every intelligence output flows through one canonical typed bus — IntelligenceEvent replaces flat string k/v stream messages and intelligence_processor_service.py is gone
**Depends on**: Nothing (Phase 0 complete)
**Requirements**: BUS-01, BUS-02, BUS-03, BUS-04
**Success Criteria** (what must be TRUE):
  1. market_analysis_service.py publishes IntelligenceEvent objects (validated by Pydantic) to the intelligence: stream — malformed events are rejected at source
  2. signal_generator_service.py, SSE route, and all downstream consumers deserialize IntelligenceEvent instead of raw field dicts — no more bare dict access
  3. intelligence_processor_service.py is deleted from the codebase and all references point to market_analysis_service.py
  4. The intelligence: stream messages contain tiered JSONB (i1/i3/i4/i5/smc/i6) with a schema_version field and platform dimension — not a flat string blob
  5. All 551+ existing tests still pass after the migration
**Plans**: 3 plans

Plans:
- [x] 01-01-PLAN.md — Define IntelligenceEvent schema (src/intelligence/schemas.py) + update market_analysis_service.py publisher (TDD)
- [x] 01-02-PLAN.md — Migrate signal_generator_service.py and dashboard parseIntelligence() to consume IntelligenceEvent
- [ ] 01-03-PLAN.md — Delete intelligence_processor_service.py, 3 test files, config, and clean up all codebase references

### Phase 2: Feature Store
**Goal**: Every IntelligenceEvent is persisted to TimescaleDB so features are queryable historically and ML training data accumulates automatically
**Depends on**: Phase 1
**Requirements**: FST-01, FST-02, FST-03, FST-04
**Success Criteria** (what must be TRUE):
  1. intelligence_features hypertable exists with tiered JSONB columns, GIN indexes on i4 and smc, and 7-day compression policy — confirmed via psql schema inspection
  2. Feature Writer Service runs as a standalone process consuming intelligence: streams via consumer group feature_writer:persist and batch-writes rows to intelligence_features without impacting pipeline latency
  3. signal_ledger has feature_ts and feature_tf columns; a JOIN between signal_ledger and intelligence_features on (symbol, feature_ts, feature_tf) returns the full feature context for any signal
  4. After 30 minutes of live pipeline operation, SELECT count(*) FROM intelligence_features returns > 0 rows with correctly structured tiered JSONB
**Plans**: 3 plans

Plans:
- [ ] 02-01-PLAN.md — DB migrations: intelligence_features hypertable (tiered JSONB, GIN indexes, 7-day compression, no retention) + signal_ledger feature_ts/feature_tf columns
- [ ] 02-02-PLAN.md — Build services/feature_writer_service.py (consumer group feature_writer:persist, buffer, batch INSERT to intelligence_features, metrics port 9115, TDD)
- [ ] 02-03-PLAN.md — Wire feature_ts/feature_tf: update LedgerEntry+_INSERT_SQL (24 params), signal_generator build_ledger_entries(), backfill _INSERT_SYNC_SQL (NULL passthrough)

### Phase 3: Historical Data
**Goal**: intelligence_features and signal_ledger are populated with 365 days of history — enough training data for the ML model and enough signals for performance analysis
**Depends on**: Phase 2
**Requirements**: HST-01, HST-02, HST-03
**Success Criteria** (what must be TRUE):
  1. signal_ledger contains 2,700+ signals covering 365 days of trading across the configured contracts and timeframes
  2. intelligence_features contains corresponding feature rows for the same date range — every signal row has a valid JOIN to a feature row
  3. Historical backfill runs to completion without crashing; a dry-run status check after completion shows no orphaned signals (signals without matching feature rows)
**Plans**: 3 plans

Plans:
- [x] 03-01-PLAN.md — Extend historical_backfill.py Stage 2 to write to intelligence_features alongside signal_ledger; set source='backfill' (TDD)
- [ ] 03-02-PLAN.md — Run backfill for 365 days (--days 365) and validate row counts and JOIN integrity
- [ ] 03-03-PLAN.md — Post-backfill SQL validation audit: row counts, date coverage, JOIN integrity, JSONB structure check

### Phase 4: Query API
**Goal**: Historical intelligence data is queryable via REST endpoints — feature context, signal history, and SSE stream all speak IntelligenceEvent
**Depends on**: Phase 3
**Requirements**: API-01, API-02, API-03
**Success Criteria** (what must be TRUE):
  1. GET /api/features/{symbol}/{timeframe}?from=...&to=... returns paginated intelligence_features rows as structured JSON — usable by curl or any HTTP client
  2. GET /api/signals/{symbol} returns signal history; with ?include_features=true each signal includes its full feature context via JOIN
  3. The SSE stream endpoint publishes typed IntelligenceEvent payloads — not flat string dicts — so a dashboard subscriber receives structured tier objects
  4. A GET /api/features/export?format=parquet request returns a Parquet file that pd.read_parquet() loads without error
**Plans**: TBD

Plans:
- [ ] 04-01: Add GET /api/features/{symbol}/{timeframe} and GET /api/features/export endpoints to FastAPI
- [ ] 04-02: Update GET /api/signals/{symbol} with optional feature JOIN; update SSE route to emit IntelligenceEvent payloads

### Phase 5: ML Scoring Model
**Goal**: Every generated signal has an ml_score predicting its probability of success — derived from the feature context at signal time
**Depends on**: Phase 4
**Requirements**: ML-01, ML-02, ML-03
**Success Criteria** (what must be TRUE):
  1. A trained ML model artifact exists that was trained on intelligence_features joined to signal_ledger outcomes — training script runs without error and produces a model file
  2. When signal_generator_service.py generates a signal, it includes ml_score (0.0-1.0) in the signal record written to signal_ledger
  3. The model can be retrained by running the training script against fresh intelligence_features data — old model is versioned and new model replaces it without service restart required
**Plans**: TBD

Plans:
- [ ] 05-01: Build ML training pipeline (feature extraction from intelligence_features JOIN signal_ledger, model training, versioned artifact output)
- [ ] 05-02: Integrate ML scoring into signal_generator_service.py as a post-I7 scoring step; add ml_score column to signal_ledger
- [ ] 05-03: Add model versioning, retraining CLI, and model swap without service restart

### Phase 6: Auth and External Access
**Goal**: External consumers — Vercel frontend, external apps — can access the intelligence bus over HTTPS with proper authentication
**Depends on**: Phase 4
**Requirements**: AUTH-01, AUTH-02, AUTH-03
**Success Criteria** (what must be TRUE):
  1. An unauthenticated request to any /api/ endpoint returns HTTP 401 — no data leaks without auth
  2. A request with a valid JWT (Authorization: Bearer ...) or a valid API key (X-API-Key: ...) succeeds against the same endpoint — single Depends(verify_auth) handles both
  3. The FastAPI server is reachable at a public HTTPS URL (via Cloudflare Tunnel) — a curl from an external network returns a valid response
  4. An authenticated SSE subscriber on Vercel receives IntelligenceEvent payloads in real time — live signal data flows to the external consumer
**Plans**: TBD

Plans:
- [ ] 06-01: Build src/api/auth.py (verify_auth dependency, JWT verification, API key verification, api_keys table migration)
- [ ] 06-02: Apply Depends(verify_auth) to all /api/ routes; configure and start Cloudflare Tunnel as systemd service

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 0. GARCH/Kalman Quality Gates | 3/3 | Complete | 2026-02-22 |
| 1. Typed Event Schema | 3/3 | Complete | 2026-02-23 |
| 2. Feature Store | 3/3 | Complete   | 2026-02-23 |
| 3. Historical Data | 3/3 | In progress | - |
| 4. Query API | 0/2 | Not started | - |
| 5. ML Scoring Model | 0/3 | Not started | - |
| 6. Auth and External Access | 0/2 | Not started | - |

## Backlog

Items decided but not yet scheduled into a phase. Pull into a milestone when ready.

| Item | Notes | Analysis |
|------|-------|---------|
| Gap-fill service | Detect + backfill gaps in `market_data_ohlcv` from downtime/TWS disconnects. Fetch only missing windows, replay Stage 2 for those windows only. | — |
| Days-to-expiry feature | Compute `(expiry_date - bar_ts).days` → store in `intelligence_features`. Roll proximity affects behavior. | — |
| Roll premium/discount feature | Front/back month spread at roll = contango/backwardation signal. Valuable for CL and equity index. | — |
