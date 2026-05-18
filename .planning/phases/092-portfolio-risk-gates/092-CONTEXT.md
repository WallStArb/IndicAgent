# Phase 092: Portfolio Risk Gates - Context

**Gathered:** 2026-05-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Add concentration limits to `SignalTrackerComputeAgent` — the single in-memory authority on all live signals. Before activating a new signal, the tracker checks two configurable gates: max active signals per direction (across all instruments) and max active signals per symbol. Signals that breach a gate are persisted as `risk_suppressed` (not silently dropped), following the existing `regime_suppressed` pattern exactly. All limits are env-var configurable with no restart required.

Zero change to signal generation (I1-I7), aggregation, or the writing path. The gate fires in the tracker, after the signal is already persisted as `pending`.

</domain>

<decisions>
## Implementation Decisions

### Gate Location and Architecture
- **D-01:** Gate fires in `SignalTrackerComputeAgent._add_to_active_index()`. When a new signal arrives for activation, check concentration before adding to `_active_index`. If either gate breaches, update signal status to `risk_suppressed` via the existing lifecycle update path and do NOT add to `_active_index`. Mirrors exactly how `regime_suppressed` works.
- **D-02:** The tracker is the right location because it has the complete live view: `_active_index: dict[(symbol, tf), list[dict]]` contains all currently active signals. No DB query needed — the check is pure in-memory dict inspection.
- **D-03:** Gate applies only to `active` status transitions. `pending` signals already in the ledger are unaffected. `regime_suppressed` signals are already not in `_active_index` and don't count toward concentration.

### Gate Types and Defaults
- **D-04:** Two gates:
  - `max_active_per_direction`: total active signals in the same direction (long=1, short=-1) across ALL symbols and timeframes. Default: 5. Prevents directional over-concentration across the whole portfolio.
  - `max_active_per_symbol`: active signals for a single base symbol (e.g. all timeframes of ES combined) regardless of direction. Default: 2. Prevents over-exposure to one instrument.
- **D-05:** Counting: `max_active_per_direction` counts all signals in `_active_index` where `sig["direction"] == new_signal["direction"]`. `max_active_per_symbol` counts all signals where `sig["symbol"] == new_signal["symbol"]` (base symbol match, not contract code).
- **D-06:** Gate evaluation order: direction check first, symbol check second. First breach encountered sets the `suppression_reason` label.

### Configuration
- **D-07:** Settings fields: `max_active_signals_per_direction: int = Field(default=5, validation_alias="INDICAGENT_MAX_ACTIVE_PER_DIRECTION")` and `max_active_signals_per_symbol: int = Field(default=2, validation_alias="INDICAGENT_MAX_ACTIVE_PER_SYMBOL")`. Readable from `get_settings()` in the tracker.
- **D-08:** Settings are read once at tracker startup in `_setup()`. To change limits, update env var + call `invalidate_active_contracts_cache()` (or restart tracker). A future phase could add hot-reload via LISTEN — not needed now.

### Suppression Flow
- **D-09:** When a signal is risk-suppressed: call existing `_update_signal_status(signal_id, "risk_suppressed", suppression_reason=reason)` lifecycle update path. This updates `signal_ledger.status` and publishes the lifecycle event to Kafka. Identical to how `regime_suppressed` is handled.
- **D-10:** `suppression_reason` string values: `"risk_direction_limit"` and `"risk_symbol_limit"`. These appear in `signal_ledger` and in logs alongside existing `"hmm_regime"`, `"shadow_suppressed"` etc.
- **D-11:** `_active_signal_count` gauge (existing) is unaffected — it tracks signals that entered `_active_index`. Risk-suppressed signals never enter `_active_index` and don't increment the gauge.

### Observability
- **D-12:** New OTel counter: `signal_tracker_risk_suppressed_total` with label `reason` (values: `direction_limit`, `symbol_limit`). Created in `_setup()` alongside existing counters. Incremented once per suppressed signal at the suppression point.
- **D-13:** structlog warning on every suppression: `log.warning("risk_gate_suppressed", signal_id=..., reason=..., direction_count=N, symbol_count=M, limits={per_dir: X, per_sym: Y})` — operator visibility without being noisy (warnings not info).

### Plan Structure
- **D-14:** Single plan. The gate is localized to `SignalTrackerComputeAgent._add_to_active_index()` plus Settings fields plus one new OTel counter. Small, self-contained, independently testable.

### Claude's Discretion
- Whether to extract the concentration check into a `_check_concentration_gate(signal) -> str | None` private method (preferred — makes unit testing cleaner)
- Exact structlog field names (follow existing signal_tracker conventions)
- Whether `max_active_per_symbol` uses base symbol or full contract code (base is correct — don't want 3 active signals across ESM6/ESU6 spread)

</decisions>

<canonical_refs>
## Canonical References

- `services/signal_tracker_compute_agent.py:100-120` — `_active_index`, `_active_symbols`, `_active_signal_count`, existing counter/gauge patterns
- `services/signal_tracker_compute_agent.py:411` — `_add_to_active_index()` — the gate insertion point
- `src/intelligence/trading/aggregator.py:157-199` — `_tag_regime_eligible()` — reference for how regime suppression works; risk gate mirrors this pattern at the tracker level
- `src/config/settings.py` — add `max_active_signals_per_direction` and `max_active_signals_per_symbol` fields
- `.planning/REQUIREMENTS.md` §RISK-01–RISK-04

</canonical_refs>

<code_context>
## Existing Code Insights

### Active Index Structure
- `_active_index: dict[tuple[str, str], list[dict]]` keyed by `(symbol, tf)`. Each signal dict has `direction` (int 1 or -1), `symbol` (contract code like ESM6), `signal_id`, etc.
- Counting per-direction: `sum(1 for signals in self._active_index.values() for s in signals if s.get("direction") == new_dir)`
- Counting per-symbol: need base symbol extraction. `new_signal["symbol"]` is contract code; base = settings lookup or just take first 2-3 chars. Cleanest: store `base_symbol` in the canonical signal dict (already present from `signal_schema.py` fields).

### Lifecycle Update Path
- `_update_signal_status()` already handles `regime_suppressed`, `expired`, `active` transitions. Adding `risk_suppressed` requires one new status string — consistent with existing `"pending"`, `"active"`, `"regime_suppressed"` literals in CLAUDE.md.
- Status must be added to the set of known string values in `signal_schema.py` or wherever status literals are documented.

### Bootstrap
- On startup, `_bootstrap_active_signals()` loads existing active signals from DB into `_active_index`. This naturally populates the concentration counts for the gate to check from day 1 — no warm-up period needed.

</code_context>

<specifics>
- "Risk management is first-class" — Medallion Fund's edge came partly from strict risk controls that prevented blowups during good signal periods. The concentration gate is not about distrust of signals; it's about systemic protection against correlated exposures.
- "Automation" — the gate fires automatically on every activation attempt. No operator needs to monitor a dashboard and manually close positions. The system enforces its own limits.
- "Observability" — every suppression is logged + metriced. Operators can see when the gate is firing frequently (signal: limits too tight or signals too correlated) vs rarely (limits appropriate).
</specifics>

<deferred>
- Per-regime concentration limits (e.g., max 3 trend-following signals in trending regime)
- Time-of-day concentration limits (e.g., reduce limits near market close)
- Automatic limit recalibration based on recent volatility
- Cross-asset correlation-aware limits (reduce limit when new signal is highly correlated with existing)
</deferred>

---
*Phase: 092-portfolio-risk-gates*
*Context gathered: 2026-05-18*
