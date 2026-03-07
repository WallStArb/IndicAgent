# Phase 14: Feedback Loop - Context

**Gathered:** 2026-03-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Setup performance analytics flowing from resolved signal outcomes into adaptive aggregator ranking weights — zero manual intervention required. Covers: `setup_performance` table populated by a scheduled job, promotion gate (n≥30 resolved signals), and signal aggregator reading performance weights to rank setups dynamically.

Creating/modifying signals, adding new setups, or changing CIS bucket weights are out of scope — those belong to other phases.

</domain>

<decisions>
## Implementation Decisions

### Job Architecture
- Extend the **existing weight-updater job and systemd timer** (`indicagent-weight-updater.timer`, daily 02:00)
- `setup_performance` stats and `cis_weights` both derive from resolved signal outcomes — run them in the same nightly feedback pass
- One feedback clock, one failure surface, atomic update
- No new systemd unit — adding a second timer for the same cadence is noise Jim Simons wouldn't tolerate

### Table Granularity (`setup_performance`)
- Track stats **globally per `setup_plugin`** — not segmented by timeframe or regime
- Rationale: with ~5-10 resolved signals per setup per day, global n≥30 is achievable in ~1 week; TF segmentation (×4) requires 120+ samples per setup (2-3 months); regime segmentation (×3) even longer — overfitting on insufficient data
- Include `timeframe` and `regime` as **nullable columns in the schema** to enable future segmentation when data volume justifies it — schema earns the future, code earns the present
- Rolling 30-day window of resolved signals with non-null `pnl_r`
- Stats per row: `win_rate`, `avg_pnl_r`, `sample_size`, `sharpe_ratio`

### Aggregator Rank Integration
- Add a **Sharpe-normalized performance multiplier** layer applied to `composite_rank` before `SETUP_PRIORITY` tiebreaking
- Formula: `perf_multiplier = 0.5 + (sharpe_rank / n_eligible_setups)` → range `[0.5, 1.5]`
- `adjusted_rank = composite_rank * perf_multiplier`
- Sort eligible signals by `adjusted_rank`; winner selection logic otherwise unchanged
- Floor 0.5: no setup gets fully suppressed before sufficient evidence accumulates
- Ceiling 1.5: outperformers get a meaningful boost without overwhelming regime/CIS signal
- **Composable**: CIS still governs direction (high-signal decision); regime gate still hard-filters ineligible signals; performance only adjusts rank within the eligible pool — no rewrite of aggregation logic

### Promotion Gate (FEED-02, already locked)
- Setup only receives a performance weight when `sample_size >= 30` resolved signals
- Setups below threshold fall back to `perf_multiplier = 1.0` (neutral — no boost or suppression)

### Live Refresh
- Job writes `{env}:setup_performance:weights` to Redis as a JSON dict keyed by `setup_plugin`
- Signal aggregator reads at **startup** and **every 60 minutes** via a background `asyncio.create_task` loop
- No hot-path latency, no restart required after nightly update
- Same pattern as `llm_scores` already established — consistent across the system

### Claude's Discretion
- Exact Sharpe calculation method (rolling vs. annualized)
- DB schema column ordering and index choices on `setup_performance`
- Background refresh error handling (stale cache fallback)
- How to handle a setup_plugin that appears in `SETUP_PRIORITY` but has no `setup_performance` row yet (falls back to multiplier 1.0)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/intelligence/weight_updater.py`: `run_weight_update(db_manager)` — extend this to also call `run_setup_performance_update(db_manager)` in the same pass
- `indicagent-weight-updater.service` / `.timer`: existing systemd units at daily 02:00, `Persistent=true` — no new units needed
- `src/intelligence/trading/aggregator.py`: `SETUP_PRIORITY` dict + `composite_rank` sort key — performance multiplier slots in here
- `src/intelligence/trading/signal_ledger.py`: `setup_plugin`, `pnl_r`, `outcome` columns already present on resolved signals

### Established Patterns
- `llm_scores` Redis cache pattern: job writes `{env}:llm_scores:{call_type}:{regime}`, service reads at startup + every 5 min — apply same pattern for `{env}:setup_performance:weights`
- `cis_weights` table + version rows: existing weight storage pattern — `setup_performance` is a separate table (per-setup stats, not CIS bucket weights)
- Promotion gate precedent: weight_updater already uses `MIN_SAMPLES_TRAIN=50` before retraining CIS weights — FEED-02 gate (n≥30) follows same philosophy

### Integration Points
- `weight_updater.py` → extend with `setup_performance_updater.py` (or co-located function) called from same job entry point
- `signal_generator_service.py` aggregator path — reads Redis `{env}:setup_performance:weights` at startup; background task polls every 60 min
- Migration needed: `021_setup_performance_table.sql` — new table, no changes to existing hypertables

</code_context>

<specifics>
## Specific Ideas

- Jim Simons framing applied throughout: self-improving without manual intervention, segment only when data justifies it, elegant composability over rewrites
- "Schema earns the future; code earns the present" — TF/regime columns present in schema but not populated until data volume warrants it
- Multiplier range [0.5, 1.5]: worst underperformer gets half the rank weight, best outperformer gets 1.5× — keeps underperformers alive for continued learning, gives outperformers meaningful signal priority

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 14-feedback-loop*
*Context gathered: 2026-03-06*
