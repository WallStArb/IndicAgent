# Phase 50: Roll Monitor & DualDivergence Graduation - Context

**Gathered:** 2026-03-30
**Status:** Ready for planning

## Phase Boundary

Graduate (or retire) two shadow-mode features: Roll Monitor (futures roll detection) and trad_Divergence (dual OFI+CVD confirmation). Phase was originally scoped for validation and enablement, but Renaissance analysis revealed incomplete features requiring binary ship/remove decisions.

**Scope change:** Phase split into three subphases (50.1, 50.2, 50.3) per user decision.

---

## Implementation Decisions

### D-01: Remove Roll Premium Feature Entirely

Roll premium feature is half-built (column exists but never populated, agent disabled, no consumers). Renaissance principle: "Ship complete features or remove them." Dead code is technical debt.

**Actions:**
- Drop `roll_premium_pct` column from `intelligence_features` table (revert 049_roll_premium_pct.sql)
- Remove `services/roll_compute_agent.py` and `_archived_roll_compute_agent.py`
- Remove `indicagent-roll-compute.service` systemd unit (if installed)
- Remove `topic_roll_events()` from `stream_keys.py`
- Remove imports and references in `signal_generator_agent.py` (archived)
- Remove `validate_roll_detection.py` script (D-21 gate no longer applicable)
- Update ROADMAP to reflect removal, not graduation

**Rationale:** Feature has been disabled since Phase 47 (2026-03-22). No consumer uses roll events. 5m data prerequisite doesn't exist. Building end-to-end would require 5m backfill + roll premium computation + downstream consumers — high cost for unproven signal. OFI/CVD microstructure features capture similar information.

### D-02: Keep trad_DualDivergence in Shadow

DualDivergence has fired 0 signals since shadow deployment. Renaissance principle: "Let the data decide." Shadow mode has zero production cost.

**Actions:**
- No code changes
- Document in CONTEXT.md that plugin remains in shadow awaiting data
- Revisit in v2.3 (6+ months of data) — retire if still N=0

**Rationale:** Dual confirmation (OFI AND CVD both diverging) IS a valid signal segment — stricter than individual divergence signals. OFIDivergence and CVDDivergence already provide value. Shadow mode means no production impact. If pattern never fires, retirement is trivial (remove from TIER_I7, delete file).

### D-03: Create market_data_5m View and Backfill

While roll premium removal eliminates immediate need for 5m data, creating the view enables future analysis and unblocks Phase 51 validation work.

**Actions:**
- Create `market_data_5m` materialized view aggregating `market_data_ohlcv` by 5m
- Run one-time backfill from existing 1m data (TIMESTAMP_TRUNC to 5-minute buckets)
- Wire BarAggregatorComputeAgent 5m output to writer (if not already done)

**Rationale:** Renaissance principle: "Never drop data that could contain signal." 5m compression reduces storage costs while preserving intraday structure. Enables cleaner volume signals for any future roll detection work.

### D-04: Phase Split Structure

Phase 50 split into three subphases per user decision:

| Subphase | Focus | Estimated Plans |
|----------|-------|-----------------|
| 50.1 | Create market_data_5m view + backfill | 2 plans |
| 50.2 | Remove roll premium feature entirely | 2-3 plans |
| 50.3 | Document DualDivergence shadow status | 1 plan (docs only) |

### Claude's Discretion

- **Migration reversion strategy:** Use `ALTER TABLE ... DROP COLUMN` (PostgreSQL handles rewrite efficiently for nullable columns with no data)
- **Service cleanup:** If `indicagent-roll-compute.service` is installed, run `systemctl stop/disable` before removing unit file
- **5m view type:** Materialized view with CONCURRENTLY refresh (allows queries while refreshing) vs continuous aggregation — decide during planning

### Deferred Ideas

None — discussion stayed within phase scope.

---

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Roll Detection (for removal context)
- `services/roll_compute_agent.py` — RollComputeAgent implementation (to be removed)
- `services/indicagent-roll-compute.service` — systemd unit (to be removed)
- `production/scripts/validate_roll_detection.py` — D-21 validation script (to be removed)
- `production/migrations/049_roll_premium_pct.sql` — migration to revert
- `.planning/milestones/v2.0-phases/47-shadow-mode-graduation/47-CONTEXT.md` — Shadow mode graduation context (ROLL_MONITOR_ENABLED decision history)

### DualDivergence (for retention rationale)
- `src/intelligence/trading/dual_divergence.py` — DualDivergencePlugin (IS_SHADOW=True, keep)
- `src/intelligence/register_plugins.py` line 474 — TIER_I7 registration
- `src/intelligence/weight_updater.py` lines 500-583 — shadow stats monitoring (compute_shadow_plugin_stats, promotion gate)
- `src/observability/metrics.py` lines 232-240 — shadow_* Prometheus gauges

### 5m Data (for subphase 50.1)
- `src/core/bar_accumulator.py` — BarAccumulator class (5m aggregation logic)
- `.planning/ROADMAP.md` — Phase 49 backfill status (market_data_5m deferred to v2.3)

### Architecture Patterns
- `CLAUDE.md` — Renaissance principles, DAG architecture, shadow mode pattern
- `src/core/agent/base.py` — BaseAgent lifecycle (if any agents need creation/removal)
- `src/core/stream_keys.py` — topic naming conventions (topic_roll_events to remove)

---

## Existing Code Insights

### Reusable Assets

- **BarAccumulator** (`src/core/bar_accumulator.py`): Already implements HTF bar aggregation including 5m. Can be reused for 5m view population logic.
- **shadow stats monitoring** (`src/intelligence/weight_updater.py`): Infrastructure for tracking shadow plugin performance already exists. DualDivergence uses this — no new code needed.
- **Migration pattern**: `production/migrations/` directory contains SQL migrations. Reverting `049_roll_premium_pct.sql` follows same pattern.

### Established Patterns

- **Agent removal**: When removing agents, also remove from systemd, stream_keys, and any import references. See Phase 52.4 (signal_lifecycle → signal_tracker retirement) for pattern.
- **Shadow mode**: IS_SHADOW class attribute on I7 plugins. SignalGeneratorService checks this via `getattr(plugin_instance, "IS_SHADOW", False)` and marks entries `is_shadow=True`.
- **Feature removal**: Drop column via migration, then remove all code references. PostgreSQL handles column drops efficiently (no table rewrite for nullable columns).

### Integration Points

- **BarAggregatorComputeAgent**: Already emits HTF bars to `market.bars.htf`. 5m bars included. Subphase 50.1 may need to wire these to persistence.
- **FeatureWriterAgent**: Writes to `intelligence_features`. If roll premium were kept (it's not), this would be the integration point. Since we're removing, no changes needed.
- **Intelligence pipeline**: No roll-related integration needed since feature is being removed entirely.

---

## Specific Ideas

**Renaissance decision criteria applied:**

1. *"Never drop data that could contain signal"* → Create 5m view even though roll feature is removed. Future phases may use it.

2. *"Let the system run. Don't override data with intuition"* → DualDivergence stays in shadow. If it fires 100 times with positive EV, it graduates. If it never fires, it retires. No human judgment needed.

3. *"Earn the right through proof"* → Roll premium feature never earned the right. It was deployed shadow (disabled), never validated, never measured. Remove rather than complete.

4. *"A rule that works globally is weaker than one that works in a specific regime"* → DualDivergence IS a regime-specific rule (both OFI AND CVD must diverge). Worth keeping as a segment even if it fires rarely.

5. *"Degrade gracefully, adapt automatically"* → Shadow mode IS graceful degradation. Plugin runs, doesn't participate, no impact if buggy.

---

## Deferred Ideas

None — discussion stayed within phase scope.

---

*Phase: 50-roll-monitor-graduation*
*Context gathered: 2026-03-30*
