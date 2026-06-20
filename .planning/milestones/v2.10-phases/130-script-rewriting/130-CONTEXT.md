# Phase 130: Script Rewriting — Context

**Gathered:** 2026-06-16
**Status:** Ready for planning
**Source:** v2.10 spec §Phase 130 + Phase 128 CONTEXT (G0 writer contract) + Phase 129 CONTEXT (column mapping) + live codebase grep

<domain>
## Phase Boundary

Rewrite all write-path services (signal_writer, lifecycle_writer, signal_tracker, signal_auditor, swarm_ledger_writer), all API endpoints, and historical backfill scripts to use the 3-table schema (signal_events / trade_frames / trade_executions). Drop signal_ledger monolith table and signal_outcomes table after 48-hour verification. Rename signal_ledger_full view to signal_ledger.

**Not in scope:**
- CounterfactualTracker daemon — v2.11. Phase 130 writes counterfactual_pnl_r=NULL; the daemon that populates it asynchronously is a v2.11 deliverable.
- I6 DB bootstrap at startup — v2.11.
- Clean replay (Phase 127) — runs after Phase 130 so the corpus lands in the final 3-table schema.

</domain>

<decisions>
## Implementation Decisions

### D-01: CounterfactualTracker is v2.11 — not Phase 130

Phase 130 writes `counterfactual_pnl_r = NULL` into every trade_frames INSERT. The CounterfactualTracker daemon (subscribes to signal_events Kafka topic, maintains per-symbol bar window, closes counterfactual positions) is a v2.11 deliverable per REQUIREMENTS.md §Future. The CLAUDE.md notation "(Phase 130)" in the v2.11 seeds list means Phase 130 creates the prerequisite table — not that the daemon is built here.

Downstream agents must not plan or implement CounterfactualTracker in Phase 130.

### D-02: G0 writer grouping strategy (locked from Phase 128 ADR)

Signals with the same signal_id (same plugin fire, different entry_types) map to ONE signal_events row and N trade_frames rows. The new signal_writer._parse_payload() must:
1. Group incoming signal dicts by signal_id
2. For each group: insert ONE signal_events row using detection fields from the first signal in the group
3. Insert N trade_frames rows (one per entry_type) per group
4. Both inserts in a single asyncpg transaction — if trade_frames fails, signal_events rolls back

This is locked in `docs/signals/signal-trade-separation-ADR.md` (Phase 128 output). Do not revisit.

### D-03: signal_outcomes table is also dropped in Phase 130

The v2.10 spec mentions only `signal_ledger` for the DROP. But `signal_outcomes` (created in migration 095) is the lifecycle state companion table — it holds status, exit_at, pnl_r, mfe, mae, etc. for signal_ledger rows. In the 3-table schema:
- Status transitions → `signal_events.status` UPDATE
- Execution outcomes → `trade_executions` INSERT
- MAE/MFE tracking → `trade_frames.counterfactual_mfe/mae` (CounterfactualTracker, v2.11)

Phase 130 must:
1. Rewrite all `signal_outcomes` writes to `signal_events`/`trade_executions` writes
2. Add `signal_outcomes` to the DROP migration alongside `signal_ledger`

DROP order: `signal_outcomes` first (no dependents), then `signal_ledger CASCADE`.

### D-04: signal_ledger drop + view rename sequence (I8)

After 48 hours of clean production operation:
```sql
DROP TABLE signal_outcomes;
DROP TABLE signal_ledger CASCADE;
ALTER VIEW signal_ledger_full RENAME TO signal_ledger;
```

After this: any code still querying `signal_ledger` hits the JOIN view. This is intentional and correct — the view provides the same columns as the old monolith view did.

Migration file: `production/migrations/NNN_drop_signal_ledger.sql` where NNN = next available after Phase 129 migrations (verify via `ls production/migrations/` during planning).

### D-05: Repository rewrite strategy

`src/persistence/repository/signal_ledger_repository.py` is the central hub — `SignalLedgerRepository` has 15+ methods targeting `signal_ledger` and `signal_outcomes`. Phase 130 rewrites this class in place:
- Rename class to `SignalEventsRepository`
- Update all SQL targets: `signal_ledger` → `signal_events`, `signal_outcomes` → `signal_events` (status) or `trade_executions`
- Update all importers (services, trackers) to import the new class name

All callers get updated behavior automatically — no service-by-service SQL patching needed.

### D-06: swarm_ledger_writer FK existence check

`services/swarm_ledger_writer.py` does `SELECT 1 FROM signal_ledger WHERE signal_id = $1` to verify the signal exists before writing to `signal_ai_enrichment` (FK race condition from AI-SEP-01). After Phase 130:
- Update this check to `SELECT 1 FROM signal_events WHERE signal_id = $1` (direct table, no JOIN overhead)
- The signal_ai_enrichment table is unchanged — it already follows the AI-SEP-01 separation pattern

### D-07: Read-only services — automatic via view rename

~10 services reference `signal_ledger` in SELECT queries only (shadow_auditor, shadow_validator, graduation_analyzer, signal_metrics_analyzer, signal_probe_auditor, signal_replay_auditor, data_quality_auditor, confidence_calibration_monitor, etc.). After Phase 130 I8, `signal_ledger` is the JOIN view — these services work automatically with no code changes.

The planner should verify each service does NOT have INSERT/UPDATE/DELETE paths into signal_ledger. If any do, add them to the explicit rewrite list.

### D-08: New columns to populate in Phase 130 writers

Phase 129 CONTEXT (D-01) marked these as "Phase 130 writer populates going forward":
- `signal_events.concurrent_signal_count` — number of active signals across all plugins for the same symbol+tf at write time. Signal_writer computes this from signal_tracker's in-memory active_signals state (zero extra DB queries).
- `signal_events.concurrent_plugins` — list of setup_plugin names for all concurrently active signals. Same source.
- `trade_frames.regime_at_activation` — HMM regime state at the time a frame transitions from pending → active. Signal_tracker already tracks hmm_regime in lifecycle events; pass it through to the trade_frames UPDATE.

All three are NULL in the Phase 129 migration (historical rows). Live writes from Phase 130 onward populate them.

### D-09: Explicit write-path file list

Files with INSERT/UPDATE into signal_ledger or signal_outcomes that need explicit rewriting:

| File | Change |
|------|--------|
| `src/persistence/repository/signal_ledger_repository.py` | Rewrite class → SignalEventsRepository; update all SQL |
| `services/signal_writer.py` | Consume repository rewrite; add G0 grouping logic |
| `services/lifecycle_writer.py` | Use new repository lifecycle methods |
| `services/signal_tracker.py` | Use signal_events + trade_frames + trade_executions via new repository |
| `services/signal_auditor.py` | Repair queries target signal_events; JOIN trade_frames for frame audits |
| `services/swarm_ledger_writer.py` | Update FK check to signal_events |
| `src/api/routes/signals.py` | Replace signal_ledger/signal_ledger_full with signal_ledger_full view or 3-table joins |
| `src/api/routes/narrative.py` | Audit for signal_ledger references |
| `production/scripts/run_historical_pipeline.py` | INSERT to signal_events + trade_frames |
| `production/scripts/lifecycle_replay.py` | UPDATE signal_events.status |
| All services that reference signal_ledger_repository (grep to confirm) | Update import to SignalEventsRepository |

### D-10: API query strategy — use signal_ledger_full view

For API endpoints: use `signal_ledger_full` (the JOIN view, which is renamed to `signal_ledger` in I8). This minimizes API rewrite risk — the view provides the same column surface as the old monolith view. For ML-specific endpoints that need trade_frames columns not in the view, write explicit 3-table JOINs.

### D-11: Transaction atomicity

All write-path operations:
- signal_events INSERT + trade_frames INSERT(s) → single asyncpg transaction
- Lifecycle UPDATE (signal_events.status) → standalone UPDATE (idempotent, can retry)
- trade_executions INSERT → standalone INSERT (happens on live execution, rare)

### D-12: APR migration mandate — all new keys required

Per the migrate-as-you-go mandate: every hardcoded numeric constant in Phase 130 target files must be migrated to APR in the same session. Constants found via audit:

| APR key (new) | Seed value | Current location | Provenance |
|---------------|-----------|-----------------|-----------|
| `feature.signal_writer.batch_size` | 100 | `services/signal_writer.py:50` | [initial_estimate] |
| `feature.signal_writer.flush_interval_secs` | 5.0 | `services/signal_writer.py:51` | [initial_estimate] |
| `feature.signal_writer.max_buffer_size` | 10000 | `services/signal_writer.py:52` | [initial_estimate] |
| `feature.lifecycle_writer.batch_size` | 100 | `services/lifecycle_writer.py:70` | [initial_estimate] |
| `feature.lifecycle_writer.flush_interval_secs` | 5.0 | `services/lifecycle_writer.py:71` | [initial_estimate] |
| `feature.lifecycle_writer.max_buffer_size` | 10000 | `services/lifecycle_writer.py:72` | [initial_estimate] |
| `feature.signal_tracker.bootstrap_pending_window_days` | 7 | `services/signal_tracker.py:1170` (SQL INTERVAL) | [initial_estimate] |
| `feature.signal_tracker.bootstrap_active_window_days` | 30 | `services/signal_tracker.py:1171` (SQL INTERVAL) | [initial_estimate] |
| `feature.signal_tracker.bootstrap_dedup_window_days` | 3 | `services/signal_tracker.py:1229` (SQL INTERVAL) | [initial_estimate] |
| `feature.signal_tracker.bootstrap_max_attempts` | 3 | `services/signal_tracker.py:127` | [initial_estimate] |
| `threshold.signal_tracker.staleness_score` | 0.5 | `src/intelligence/trading/lifecycle_tracker.py:48` (imported by signal_tracker) | [initial_estimate] |
| `feature.signal_auditor.audit_lookback_hours` | 1 | `services/signal_auditor.py:273` (SQL INTERVAL) | [initial_estimate] |
| `ui.signals.recent_window_days` | 90 | `src/api/routes/signals.py:33` | [initial_estimate] |
| `ui.signals.min_confidence` | 0.40 | `src/api/routes/signals.py:72,334,454` | [data-derived] breakeven threshold |
| `ui.signals.min_cis_score` | 0.35 | `src/api/routes/signals.py:334` | [initial_estimate] |
| `ui.signals.today_window_hours` | 24 | `src/api/routes/signals.py` (multiple) | [initial_estimate] |
| `ui.signals.yesterday_window_hours` | 48 | `src/api/routes/signals.py:448` | [initial_estimate] |
| `ui.signals.short_window_days` | 7 | `src/api/routes/signals.py` (multiple) | [initial_estimate] |
| `ui.signals.medium_window_days` | 30 | `src/api/routes/signals.py` (multiple) | [initial_estimate] |
| `ui.signals.latency_threshold_minutes` | 5 | `src/api/routes/signals.py:487` | [initial_estimate] |
| `ui.signals.max_results` | 500 | `src/api/routes/signals.py:203` | [initial_estimate] |
| `ui.signals.top_n_results` | 10 | `src/api/routes/signals.py:527` | [initial_estimate] |

**Load pattern for services (all new keys):**
- Load via `await config_service.get("key", default=X)` at `_setup()` time
- SQL INTERVAL literals: use parameterized SQL with integer days loaded from APR → `$N * INTERVAL '1 day'`
- All keys must have entries in both `config_schema` and `config_state` — add in the Phase 130 migration file alongside the DROP migration

**Not ML learning targets** — these are operational/UX parameters. ML targets are detection thresholds and weights (Tiers A–C from Phase 125). Mark descriptions accordingly.

### D-13: OPS_PREFIXES prerequisite for ui.* keys

`"ui."` is NOT in `OPS_PREFIXES` in `src/config/config_service.py:39`. Per CLAUDE.md: "**`ui.*` requires one-line change first:** add `"ui."` to `OPS_PREFIXES`." This must be done before seeding ui.signals.* keys, so the APR UI dashboard at `/config/parameters` can display and edit them.

Add `"weights."` to OPS_PREFIXES as well — weights.* keys exist in config_state but the prefix is missing from OPS_PREFIXES, meaning they can only be written via direct SQL migration (not via ConfigService.set()). Fix this in the same one-liner commit.

### D-14: Naming and file convention enforcement

**File and class rename (mandatory — applies to Phase 130 rewrite):**
- `src/persistence/repository/signal_ledger_repository.py` → rename to `signal_events_repository.py`
- Class `SignalLedgerRepository` → `SignalEventsRepository`
- Update all `from src.persistence.repository.signal_ledger_repository import ...` across codebase

**Docstring updates (mandatory — wrong docs are worse than no docs):**
Every file modified in Phase 130 must have its module docstring corrected:
- `services/signal_writer.py` line 2: "persists all I7 signals to signal_ledger hypertable" → "persists I7 signals to signal_events/trade_frames (3-table schema)"
- `services/lifecycle_writer.py` line 2: "persists signal lifecycle transitions to signal_ledger" → "persists signal lifecycle transitions to signal_events"
- `services/signal_tracker.py`: update all docstrings referencing signal_ledger_full bootstrap query → reference signal_events
- `src/api/routes/signals.py` line 4: "Provides access to signal_ledger with optional JOIN..." → "Queries signal_events/trade_frames via signal_ledger (join view)"
- `src/persistence/repository/signal_events_repository.py`: full rewrite of class docstring

**Naming vocabulary check (verify no violations introduced by Phase 130 code):**
- New class names must use Vocabulary B categories: Writer, Tracker, Auditor, Analyzer, Monitor — no mechanism words (Compute, Process, Handle, Execute)
- No abbreviations in variable names: `cfg` ok (accepted convention for ConfigService in CLAUDE.md), `sig` → `signal`, `ctx` → context (check new code)
- Ring 0 (`src/persistence/`) should have no domain vocabulary — `SignalEventsRepository` is a pre-existing violation; do not compound it with new domain-specific classes in Ring 0

### D-15: Documentation updates — Phase 130 must update stale outer-ring docs

Phase 130 drops signal_ledger and replaces it. Per the documentation system: "When a doc's described system changes, the doc's status drops to draft automatically until re-verified." Phase 130 must re-verify and update these docs as part of the phase:

| Doc | Stale claim | Required update |
|-----|-------------|----------------|
| `docs/architecture/architecture-overview.md` | "signal_ledger … dropped Phase 129" | Change to Phase 130; update table row to signal_events/trade_frames/trade_executions |
| `docs/architecture/architecture-dag-topology.md` | Mermaid node `SIGLED[("signal_ledger…")]`; SignalWriter row | Update to signal_events + trade_frames; update I/O table |
| `docs/concepts/temporal-data-architecture.md` | "signal_ledger is the crown jewel" section | Rewrite to describe 3-table architecture as the training dataset |
| `docs/concepts/adaptive-intelligence.md` | "fitness dataset — signal_ledger" (multiple) | Update to signal_events + trade_frames |
| `docs/concepts/event-driven-fabric.md` | `topic_signal_ledger → signal_writer_service` | Update topic references |
| `CLAUDE.md` | §TimescaleDB Tables: `signal_ledger — legacy monolith (dropped Phase 129)` | Fix to Phase 130; update after actual drop |

**Doc update timing:** Update docs AFTER the DROP migration runs (I8). Do not update them before — the old table still serves reads during the 48h window.

**Status convention:** Each updated doc should have its `**Status:**` or equivalent updated. Outer-ring docs (`docs/architecture/`, `docs/concepts/`) don't use the recipe card status field, but inline notes referencing "signal_ledger (deprecated)" should be replaced, not annotated.

### Claude's Discretion

- Exact migration numbering for the DROP + APR-seed migration — use next available after Phase 129 migrations (check `ls production/migrations/` at plan time)
- Whether to rename `signal_ledger_repository.py` file to `signal_events_repository.py` at the filesystem level — YES (D-14 makes this mandatory)
- GIN index on `context_features` or `factor_scores` — deferred from Phase 128; add only if ML queries filter JSONB inline (check query patterns during planning)
- Order of service rewrites in plans — start with signal_writer (live write path), then lifecycle/tracker, then API, then scripts; this ensures no gap in live production writes
- Confidence that read-only services work via view — planner should do a grep sweep during plan creation to verify no hidden write paths
- Combine APR key seeding with DROP migration (same migration file, or separate?) — prefer separate: one migration for APR schema+state inserts, one for the DROP; keeps rollback boundaries clean

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Primary Design — 3-Table Schema
- `docs/plans/2026-06-14-v2.10-signal-architecture-refactor.md` §"Phase 130: Script Rewriting" — I1-I9 task list, writer contract, success criteria, G0 grouping strategy, CounterfactualTracker design sketch (v2.11)
- `docs/plans/2026-06-14-v2.10-signal-architecture-refactor.md` §"G0: Writer Grouping Strategy" — critical Phase 130 write-path design (signal_id → N trade_frames grouping logic)
- `docs/signals/signal-trade-separation-ADR.md` — full column specs, FK design, Phase 130 writer contract (Phase 128 output)

### Schema Authority
- `production/migrations/137_3table_schema.sql` — canonical DDL for signal_events, trade_frames, trade_executions, signal_ledger_full view
- `src/intelligence/trading/signal_schema.py` — SIGNAL_SCHEMA_VERSION constant (already bumped in Phase 129; verify current value)

### Phase Context (locked decisions to carry forward)
- `.planning/phases/128-3-table-schema-design-and-adr/128-CONTEXT.md` — D-01 (3-table non-negotiable), D-02 (signal_events schema), D-03 (trade_frames schema), D-04 (trade_executions schema), D-05 (signal_ledger_full view SQL)
- `.planning/phases/129-database-migration/129-CONTEXT.md` — D-01 (column mapping signal_ledger → signal_events), D-02 (column mapping → trade_frames), D-06/D-07 (idempotency, read-only transition), D-08 (SIGNAL_SCHEMA_VERSION bump already done)

### Code Files (MUST read before planning)
- `src/persistence/repository/signal_ledger_repository.py` — central repository with all SQL to rewrite; 15+ methods
- `services/signal_writer.py` — current write path to signal_ledger (the main rewrite target)
- `services/lifecycle_writer.py` — writes to signal_outcomes; target for signal_events.status rewrites
- `services/signal_tracker.py` — lifecycle state machine; references signal_ledger_full for bootstrap
- `services/swarm_ledger_writer.py` — FK existence check to update from signal_ledger to signal_events
- `src/api/routes/signals.py` — API endpoints to audit and update

### Requirements
- `REQUIREMENTS.md` §REWRITE-01 — primary Phase 130 requirement
- `REQUIREMENTS.md` §Future — CounterfactualTracker is v2.11, NOT Phase 130 scope

### APR and Standards
- `docs/foundation/parameter-store.md` — APR mandate, namespace conventions, migrate-as-you-go rule
- `docs/foundation/naming-system.md` — Ring architecture, Vocabulary A/B class naming, mechanism-word prohibition
- `docs/foundation/documentation-system.md` — recipe card format, status model, inner vs outer ring doc rules
- `docs/foundation/principles.md` — Renaissance design frame, data integrity first
- `src/config/config_service.py:39` — OPS_PREFIXES (add "ui." and "weights." before seeding new keys)

### Docs That Must Be Updated in Phase 130 (D-15)
- `docs/architecture/architecture-overview.md` — "dropped Phase 129" error; update to Phase 130 + 3-table
- `docs/architecture/architecture-dag-topology.md` — Mermaid node + SignalWriter I/O table
- `docs/concepts/temporal-data-architecture.md` — signal_ledger crown jewel section
- `docs/concepts/adaptive-intelligence.md` — fitness dataset references
- `docs/concepts/event-driven-fabric.md` — topic_signal_ledger reference

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `SignalLedgerRepository` in `src/persistence/repository/signal_ledger_repository.py` — the rewrite target; all SQL is here, not scattered across services. Update once, all importers benefit.
- asyncpg transaction pattern from existing signal_writer — already uses connection pool; extend with BEGIN/COMMIT wrapping signal_events + trade_frames inserts together
- `production/migrations/137_3table_schema.sql` — authoritative DDL; use for column names, types, constraints in all INSERT statements

### Established Patterns
- All DB writes via asyncpg connection pool (`database_manager.py`) — no direct psycopg2 in services
- ON CONFLICT DO NOTHING (idempotent inserts) — use for signal_events (PK: signal_id, ts) and trade_frames (UNIQUE: signal_id, entry_type) as in the Phase 129 migration script
- `format_iso_ts()` from `service_utils.py` for all timestamp serialization — never inline .isoformat()
- structlog `event` kwarg collision rule: never pass `event=<value>`; use `signal=`, `payload=`, `data=`
- Exception variable naming: `except X as error:` (not `exc`)

### Integration Points
- `signal_tracker.py` maintains in-memory active_signals dict — source for concurrent_signal_count and concurrent_plugins at write time (no extra DB query needed)
- HMM regime is passed in lifecycle transition events — available to tracker for regime_at_activation population on trade_frames UPDATE
- `signal_ledger_full` view (migration 137) is already the join view from Phases 128/129 — becomes `signal_ledger` after I8 rename; API routes can use either name depending on timing
- Kafka `signal_events` topic (if it exists) — swarm_ledger_writer subscribes via Kafka; verify topic key in `stream_keys.py` during planning

</code_context>

<specifics>
## Specific Implementation Notes

### G0 grouping pseudocode (from v2.10 spec §G0)
```python
# In the Phase 130 rewrite of signal_writer.py _parse_payload():
groups = defaultdict(list)
for signal in payload["signals"]:
    groups[signal["signal_id"]].append(signal)

rows_signal_events = []
rows_trade_frames = []
for signal_id, signals in groups.items():
    detection = signals[0]  # All share same detection fields
    rows_signal_events.append(build_signal_events_row(detection))
    for s in signals:
        rows_trade_frames.append(build_trade_frames_row(s))
```

### signal_ledger_full post-I8 rename
After `ALTER VIEW signal_ledger_full RENAME TO signal_ledger`:
- Any code querying `signal_ledger` hits the JOIN view (signal_events + trade_frames + trade_executions)
- Any code querying `signal_ledger_full` breaks (view no longer exists by that name)
- Phase 130 must update all `signal_ledger_full` references to `signal_ledger` in API routes and services BEFORE running I8

### signal_outcomes column mapping
| signal_outcomes column | New target |
|----------------------|-----------|
| signal_id | signal_events.signal_id (FK) |
| status | signal_events.status (UPDATE) |
| activated_at | signal_events.signal_computed_at (already present) |
| exit_at | (drop — computable from expires_at or trade_executions.exited_at) |
| pnl_r | trade_executions.actual_pnl_r |
| outcome | trade_executions.exit_reason |
| shadow_mae, shadow_mfe, shadow_outcome | trade_frames.frame_details JSONB (archived in Phase 129 migration) |

</specifics>

<deferred>
## Deferred Ideas

- CounterfactualTracker daemon — v2.11; prerequisite is trade_frames table (created Phase 128, migrated Phase 129). Design sketch in v2.10 spec §"v2.11 Seeds"
- I6 DB bootstrap at startup — v2.11; requires intelligence_features accumulation
- GIN index on context_features/factor_scores — Phase 130 planner may add if query patterns warrant it; do not add speculatively (deferred from Phase 128 D-09 Claude's Discretion)
- APR ML optimization on factor_scores — v2.11; requires 30-90 days of counterfactual_pnl_r data
- SignalRanker (LightGBM) — v2.11; requires context_features + counterfactual_pnl_r

### Reviewed Todos (not folded)
- "Quant Pipeline Modularization (P-QUANT-01)" — architecture phase, different domain; defer beyond v2.10
- "SR Strength Calibration" — signal ledger domain but requires replay data (Phase 127) first; v2.11
- "ATR Validation Hardening" — pipeline hardening; separate from 3-table rewrite
- "Replay Rolled Contracts" — replay domain; Phase 127 scope

</deferred>

---

*Phase: 130-script-rewriting*
*Context gathered: 2026-06-16*
