# Phase 63: Contract Lifecycle Automation - Context

**Gathered:** 2026-04-09 (updated from 58.1-CONTEXT.md, 2026-04-02)
**Status:** Ready for planning — Plan 06 (BarWriterAgent) to execute next
**Source:** PRD Express Path + 2026-04-09 discussion

<domain>
## Phase Boundary

Four-stage DAG that eliminates all manual futures roll tasks:
- **Stage 1 (SEED):** `ContractMetadataWriterAgent._seed_missing_contracts()` bootstraps `contract_metadata` from `settings.py` on first deployment — idempotent INSERT only
- **Stage 2 (DETECT):** `RollComputeAgent` graduates to live via backtest validation — z-score + calendar gate → `market.events.roll`
- **Stage 3 (PROMOTE):** `ContractMetadataWriterAgent` consumes `market.events.roll` → atomically promotes front-month in `contract_metadata` → broadcasts `market.events.contract_update`
- **Stage 4 (AUDIT):** `BarAuditorAgent` uses session-aligned windows and derived completeness ceiling

**Also in scope (Plan 06, added 2026-04-09):**
- `BarWriterAgent` base symbol resolution: fix `market_data_ohlcv.base` to use base symbols (ES) instead of contract codes (ESM6) via `contract_metadata` table lookup

</domain>

<decisions>
## Implementation Decisions

### Stages 1–4 (Plans 01–05, completed 2026-04-02)

All decisions from 58.1-CONTEXT.md carry forward unchanged:

- `ContractMetadataWriterAgent` — `services/contract_metadata_writer_agent.py`, port `:9124`, systemd unit `indicagent-contract-metadata-writer.service` — **DEPLOYED AND ACTIVE**
- `topic_contract_updates()` + `topic_roll_dlq()` in `stream_keys.py` — **DONE**
- `ContractUpdateEvent` schema in `market_events.py` — **DONE** (duplicate cleaned up, ruff clean)
- `TradingSession.session_window_for_date()` + `max_achievable_pct()` — **DONE**
- `BarAuditorAgent` session-aligned windows, `_COMPLETENESS_GATE = 0.97` — **DONE**
- `settings.py` base-symbol templates (no front-month codes) — **DONE**
- `roll_backtest.py` backtest script — **DONE**, graduation deferred to June M6 roll
- `build_contracts()` base-symbol templates — **DONE**

### Plan 06: BarWriterAgent Base Symbol Fix (NEW — 2026-04-09)

**Root cause:** `BarWriterAgent._load_instruments_cache()` queries `instruments` table (base symbols only). When IBKR publishes `symbol="ESM6"`, no match found → `base="ESM6"` written to `market_data_ohlcv`. This is corrupt training data.

**Renaissance judgment:** Data quality over model complexity. Every bar written with wrong `base` is a mislabeled training sample. `contract_metadata` (populated by `ContractMetadataWriterAgent`) is now the SoT for contract→base mappings. Fix applies immediately.

**Implementation:**
- **D-01:** Rename `_load_instruments_cache()` → `_load_contract_cache()` — queries `contract_metadata` table: `SELECT symbol, base_symbol FROM contract_metadata`
- **D-02:** Rename `_instruments_cache` → `_contract_cache` (dict: `symbol → base_symbol`)
- **D-03:** Subscribe to `topic_contract_updates()` in `_setup_kafka_clients()` — add `_handle_contract_update()` method that invalidates `_contract_cache` on roll promotions
- **D-04:** `_handle_contract_update()` calls `await self._load_contract_cache()` on receipt of `ContractUpdateEvent` — ensures live roll propagates within one bar
- **D-05:** Fallback: if `symbol` not in `_contract_cache` (e.g., non-futures), fall back to `symbol` as base (same behavior as today for ETFs/FX)
- **D-06:** Historical backfill — one-shot migration script: `UPDATE market_data_ohlcv m SET base = cm.base_symbol FROM contract_metadata cm WHERE m.symbol = cm.symbol AND m.base != cm.base_symbol` — run once, log affected row count, verify with SELECT COUNT(*)
- **D-07:** Update unit tests to mock `contract_metadata` query instead of `instruments` query — follow `__new__` pattern in `tests/unit/service_tests/`

### RollComputeAgent Graduation

- **D-08:** Graduation deferred to June 2026 M6 roll — `roll_backtest.py` exists and is ready
- **D-09:** Tracked as todo (created separately) — not blocking phase completion
- **D-10:** Process: run `.venv/bin/python production/scripts/roll_backtest.py` when M6 bars present → if passes, `sudo systemctl enable --now indicagent-roll-compute.service`

### Phase Completion

- **D-11:** Phase 63 closes after Plan 06 ships AND re-verification passes (`gsd-verify-work`)
- **D-12:** Re-verification scope: all 10 original truths + new truths for Plan 06 (`market_data_ohlcv.base` contains base symbols for futures rows)

### Claude's Discretion

- asyncpg pool usage in cache refresh (follow `database_manager.py` patterns)
- Test fixture patterns for mocking asyncpg contract_metadata query (follow existing `tests/unit/service_tests/` conventions)
- Exact `_handle_contract_update()` log message format
- Migration script filename (suggest `production/scripts/fix_bar_base_symbols.py`)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Plan 06 — BarWriterAgent
- `services/bar_writer_agent.py` — File being modified; `_load_instruments_cache()` at line 164, `_instruments_cache` at line 116
- `services/contract_metadata_writer_agent.py` — Pattern to follow for `contract_metadata` queries + `topic_contract_updates` subscription
- `src/core/stream_keys.py` — `topic_contract_updates()` at line 68
- `src/core/schemas/market_events.py` — `ContractUpdateEvent` at line 60

### Completed Plans (reference only)
- `docs/superpowers/specs/2026-04-02-contract-lifecycle-automation-design.md` — Full original design
- `.planning/phases/63-contract-lifecycle-automation/58.1-CONTEXT.md` — Original decisions (all carry forward)
- `.planning/phases/63-contract-lifecycle-automation/58.1-VERIFICATION.md` — Verification report (9/10 truths verified)

### Core Infrastructure
- `src/core/database_manager.py` — asyncpg pool patterns
- `src/core/models.py` — `TradingSession` methods added in this phase
- `src/config/settings.py` — `get_active_contracts()` (unchanged)
- `src/observability/metrics.py` — metric registration

### Existing Tests
- `tests/unit/test_bar_writer_agent.py` — Extend with contract_metadata cache tests (if exists)
- `tests/unit/test_bar_auditor_agent.py` — Already extended (12 tests passing)
- `tests/unit/test_models.py` — 27 tests passing

</canonical_refs>

<specifics>
## Specific Ideas

- Renaissance principle: `contract_metadata` is now the SoT for contract→base mappings. `BarWriterAgent` must use it — querying `instruments` for a futures contract code is semantically wrong since `instruments` only carries base symbols.
- `get_active_contracts()` API must remain unchanged — all callers unaffected
- `RollComputeAgent` internals untouched — z-score algorithm not modified
- `market.events.roll` topic unchanged — already published to by RollComputeAgent
- IBKRProviderAgent restart on roll remains manual (acceptable for quarterly events)
- systemd units in `/etc/systemd/system/` — `production/systemd/` is reference only
- Backfill script must be idempotent (safe to run twice — `WHERE base != cm.base_symbol` guard)

</specifics>

<deferred>
## Deferred Ideas

- Automated IBKRProviderAgent restart on `ContractUpdateEvent` — acceptable as manual for quarterly cadence
- Per-instrument completeness ceiling overrides — design explicitly rejects these
- RollComputeAgent graduation — tracked as todo, June 2026 M6 roll

</deferred>

---

*Phase: 63-contract-lifecycle-automation*
*Context gathered: 2026-04-09 (updated — Plan 06 added, status clarifications)*
