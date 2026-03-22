# Phase 47: Shadow Mode Graduation - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Graduate three shadow-mode items to full production participation: cross-asset intelligence service, roll monitor, and trad_DualDivergence plugin. Also move hardcoded HMM regime thresholds to Settings as safety floors, feeding Phase 49 with richer training data. True graduation means removing flag scaffolding entirely — services either participate in the DAG or they don't.

</domain>

<decisions>
## Implementation Decisions

### Area A — HMM Regime Thresholds

- **D-01:** Move `_REGIME_PROB_MIN` and `_REGIME_DUR_MIN` from hardcoded constants in `src/intelligence/trading/aggregator.py` to `Settings` fields with env var aliases `REGIME_PROB_MIN` and `REGIME_DUR_MIN`.
- **D-02:** Default values are **safety floors only** — lower than current (e.g., 0.30 / 1). Not quality filters. The hard gate's job is to catch degenerate HMM output (essentially random), not to enforce signal quality.
- **D-03:** No threshold optimization in Phase 47. Phase 49 ML model takes `hmm_regime_prob` and `hmm_regime_duration` as raw features and learns their weights. The learned weight IS the threshold, expressed continuously.
- **D-04:** Rationale for lowering: current `_REGIME_PROB_MIN=0.55` creates a selection bias hole in Phase 49 training data. Regime-suppressed signals never reach `signal_ledger` with outcomes, so the ML model cannot learn whether the gate is beneficial. Lowering to a safety floor maximises labeled training data. Phase 49 measures the actual lift.
- **D-05:** `regime_gate.py` reads from the new Settings fields — no other changes to gate logic.

### Area B — DualDivergence Shadow Promotion

- **D-06:** Extend `weight_updater.py` with `compute_shadow_plugin_stats()` function, called on every existing weight-update cycle (same 30-min cadence). No new service, no new Kafka topic.
- **D-07:** Promotion gate (all required):
  - `N >= 100` resolved shadow signals (excludes `never_activated`)
  - 95% confidence interval **lower bound** on `E[PnL_R] > 0` — computed via bootstrap on the resolved sample
  - Win definition: `target_1 | target_1_2 | target_full` = win; `stopped_at_entry | stopped_in_trade` = loss; `ttl_expired_ahead` = loss (wrong direction); `ttl_expired_behind` = neutral (exclude); `never_activated` = exclude
- **D-08:** Emit Prometheus metrics on each cycle (follow existing metrics naming pattern via `src/observability/metrics.py`):
  - `shadow_n_resolved{plugin}` — resolved signal count
  - `shadow_win_rate{plugin}` — point estimate
  - `shadow_ev_r{plugin}` — expected value in R-multiples
  - `shadow_ev_ci_lower{plugin}` — 95% CI lower bound on E[PnL_R]
  - `shadow_days_to_gate{plugin}` — estimated days to N=100 at current fire rate (rolling 30-day average)
  - `shadow_promotion_ready{plugin}` — 1 when all gate conditions met, 0 otherwise
- **D-09:** Also emit structured `WARNING` log line when `shadow_promotion_ready` flips to 1. Human makes the deliberate code change: `IS_SHADOW = False` in `dual_divergence.py` + commit. Promotion is a one-time intentional act, not automated.
- **D-10:** `shadow_days_to_gate` is informational — surfaces whether DualDivergence is firing at a viable rate. If it projects >180 days, that is itself signal that the plugin fires too rarely to be a viable live candidate; inform Phase 49 feature selection accordingly.

### Area C — Cross-Asset Graduation

- **D-11:** Pre-enable validation: one DB query confirming Phase 46 cross-asset fields (`ctf_vix_level`, `ctf_vix_z`, `ctf_eq_spread_z`, `ctf_eq_pairs_confirming`) are non-null in `intelligence_features` for EQ_INDEX symbols within the past 7 days. If absent, the pipeline is broken upstream — do not enable.
- **D-12:** Enable: set `CROSS_ASSET_ENABLED=true` in `.env`, restart affected services. 5-trading-day config rollback window.
- **D-13:** Operational validation via existing Prometheus: watch `feature-pipeline` (:9125) and `signal-generator` (:9112) error rate and p99 latency. No new monitoring infrastructure needed. Lift measurement is Phase 49's job — not a gate for graduation.
- **D-14:** Graduate (after 5 trading days clean): remove `cross_asset_enabled` from `Settings`, remove all `if self._cross_asset_enabled` / `if self._cross_asset_enabled` conditional branches from all four affected services: `cross_asset_service.py`, `feature_pipeline_service.py`, `signal_generator_service.py`, `feature_writer_service.py`. `cross_asset_service` always runs. Downstream services always consume `development.cross_asset`. Atomic cleanup commit — this is the real graduation.
- **D-15:** Graduation bar is operational only: no errors, latency within current bounds. The DAG principle: services either participate or they don't. `CROSS_ASSET_ENABLED=false` as a permanent code path is a maintenance liability and a separation-of-concerns violation.

### Area C — Roll Monitor Graduation

- **D-16:** `update_volume(symbol, vol, vol)` call at line 569 of `tws_daemon.py` is a confirmed bug — identical values produce ratio=1.0 always, detection can never fire. Root cause: IBKR `ibkr_max_subscriptions=80` cap makes subscribing to both front-month AND next-month contracts simultaneously infeasible.
- **D-17:** Fix: replace ratio-based detection with **calendar-driven + volume anomaly confirmation**. Two-signal design:
  - **Primary (calendar):** deterministic roll date lookup per instrument family. Calendar is a known fact, not a prediction.
  - **Confirmation (volume anomaly):** front-month volume z-score drops below -2.0 standard deviations from rolling window mean during calendar roll window. Uses only the current contract subscription — no additional IBKR subscriptions needed.
- **D-18:** No new module. Extend `src/config/contracts.py` directly — it already owns contract cycle data, chain derivation, and expiry month/year. Expiry date arithmetic and roll window bounds are natural extensions of existing contract knowledge, not a new concern. Adding a separate `src/core/roll_calendar.py` would be unnecessary indirection (thin wrapper with no independent logic). Add to `contracts.py`:
  - `get_expiry_date(base_symbol, expiry_month, expiry_year) -> date` — approximate expiry date per family (third Friday of expiry month for quarterly; last business day of prior month for energy/metals; etc.). Approximate is intentional — volume z-score is the precision layer.
  - `get_roll_window(base_symbol, ref_date) -> tuple[date, date] | None` — returns active roll window if one is upcoming, `None` otherwise. `RollMonitor.check_roll()` calls this to gate z-score detection.
  - `derive_roll_chain()` extended to include `expiry_date: date` in each chain dict alongside existing `expiry_month`/`expiry_year`.
  - `RollMonitor` imports directly from `contracts.py` — no new module, no new import chain.
- **D-19:** `RollMonitor.update_volume()` signature changes: remove `next_vol` parameter. Only `current_vol` needed. Rolling window tracks current contract volume history for z-score computation. `PAPER_SKIP_CONTRACTS` guard in `RollMonitor` also needs review — it existed because next-contract subscriptions failed on paper; with calendar-driven approach requiring no next-contract subscription, this guard may be unnecessary.
- **D-20:** `_on_roll_confirmed` fixed: call `derive_roll_chain(base_symbol)` from `contracts.py` and read `chain[0]["roll_to"]` for `new_symbol`. `roll_gap` computed from price difference if available; `roll_direction` derived from sign of gap. No new lookup logic needed — `derive_roll_chain()` already computes the full chain.
- **D-21:** Offline validation before enabling: run detection algorithm against `market_data_5m` view (5m bars give cleaner volume signal than 1m — roll shift happens over sessions, not minutes) for known historical roll dates. Accuracy gate: ≥90% detection rate, <10% false positive rate. If gate passes, enable.
- **D-22:** Enable: set `ROLL_MONITOR_ENABLED=true` in `.env`, restart `tws_daemon` + `indicator_service` + `market_analysis_service` + `signal_generator_service` + `feature_writer_service`. 5-trading-day rollback window.
- **D-23:** Graduate: remove `roll_monitor_enabled` from `Settings`, remove all conditional scaffolding from all five affected services. Same principle as cross-asset. Atomic cleanup commit.

### Claude's Discretion
- Bootstrap implementation for 95% CI on E[PnL_R] — sample size and iteration count
- Specific safety floor values for `REGIME_PROB_MIN` / `REGIME_DUR_MIN` defaults (must be low enough to be a floor, not a filter)
- Roll calendar exact offsets for energy/metals monthly rolls
- Whether cross-asset and roll monitor graduate in the same Phase 47 execution or sequentially (cross-asset first, roll monitor after bug fix + validation)

</decisions>

<specifics>
## Specific Ideas

- `shadow_days_to_gate` metric: if it projects >180 days for DualDivergence, surface that as an input to Phase 49 feature selection — a plugin that fires once per week is not a useful ML feature column.
- Roll calendar module should cover all instruments in `get_active_contracts()` — not just the asset families listed. Any instrument not in the calendar gets a conservative default window (last 5 trading days of the contract month).
- The cross-asset and roll monitor cleanup commits should be separate PRs — one variable changed at a time, reviewable history.
- Graduation ceremony order: (1) fix roll detection bug, (2) offline validation, (3) enable roll monitor, (4) enable cross-asset, (5) 5-day soak, (6) remove roll monitor scaffolding, (7) remove cross-asset scaffolding. Sequential — one system at a time.

</specifics>

<canonical_refs>
## Canonical References

No external specs — requirements fully captured in decisions above.

### HMM threshold
- `src/intelligence/trading/aggregator.py` — current `_REGIME_PROB_MIN`, `_REGIME_DUR_MIN`, `_REGIME_MAP` constants; aggregator gate logic
- `src/intelligence/pipeline/regime_gate.py` — pure function consuming the constants; reads from aggregator imports
- `src/config/settings.py` — Settings model; add new fields here with `REGIME_PROB_MIN` / `REGIME_DUR_MIN` env aliases

### DualDivergence shadow stats
- `services/weight_updater.py` — extend with `compute_shadow_plugin_stats()`; existing 30-min refresh cycle
- `src/intelligence/trading/dual_divergence.py` — `IS_SHADOW: ClassVar[bool] = True`; promotion is `IS_SHADOW = False` here
- `src/observability/metrics.py` — register new `shadow_*` Prometheus metrics here to prevent duplicate registration
- `src/intelligence/trading/signal_ledger.py` — `is_shadow` field; outcome taxonomy (8-class)

### Cross-asset graduation
- `services/cross_asset_service.py` — `CROSS_ASSET_ENABLED=false` exit path to remove
- `services/feature_pipeline_service.py` — `self._cross_asset_enabled` conditional branches to remove
- `services/signal_generator_service.py` — `self._cross_asset_enabled` conditional branches to remove
- `services/feature_writer_service.py` — `self._cross_asset_enabled` conditional branches to remove

### Roll monitor fix + graduation
- `services/tws_daemon.py` lines 565-575 — broken `update_volume(vol, vol)` + `_on_roll_confirmed` stub
- `services/tws_daemon.py` class `RollMonitor` lines 64-340 — full detection logic; `update_volume`, `check_roll`, `_on_roll_confirmed`
- `src/config/contracts.py` — **extend in-place**: add `get_expiry_date()`, `get_roll_window()`, extend `derive_roll_chain()` with `expiry_date` field. Single source of truth for all contract knowledge.
- `src/config/settings.py` — `roll_monitor_enabled`, `roll_monitor_window_size`, `roll_monitor_threshold_default` etc. (to remove on graduation)
- `services/indicator_service.py` line 689 — `roll_monitor_enabled` conditional subscription
- `services/market_analysis_service.py` line 768 — `roll_monitor_enabled` conditional subscription
- `services/signal_generator_service.py` line 438 — `self._roll_monitor_enabled`
- `services/feature_writer_service.py` line 269 — `self._roll_monitor_enabled`

### Roll monitor — tests that change vs. stay
- `tests/unit/test_roll_detection_algorithm.py` — **rewrite**: tests the broken ratio logic; replace with tests for calendar window + z-score algorithm
- `tests/unit/test_roll_chain_derivation.py` — **unchanged**: tests `derive_roll_chain()` in `contracts.py`, unaffected
- `tests/unit/test_seed_roll_chain.py` — **unchanged**: tests historical backfill seed logic, unaffected
- `tests/unit/test_roll_kafka_events.py` — **unchanged**: tests `_handle_roll_event()` in downstream services, unaffected
- `tests/unit/test_plugin_state_migration.py` — **unchanged**: plugin state migration at roll boundary, unaffected

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `weight_updater.py` 30-min refresh cycle: extend in-place with `compute_shadow_plugin_stats()` — no new service, no new cadence
- `src/observability/metrics.py`: all new Prometheus metrics registered here to prevent duplicate registration
- `market_data_5m` TimescaleDB view: use for offline roll validation — cleaner signal than 1m for session-level volume trends
- `src/config/contracts.py`: extend in-place with `get_expiry_date()` + `get_roll_window()` — single source of truth, no wrapper module needed
- `derive_roll_chain(base_symbol)`: returns chain with `roll_to` field — directly provides `new_symbol` for `_on_roll_confirmed` fix; will also include `expiry_date` after extension

### Established Patterns
- Settings fields pattern: `field_name: type = Field(default=X, validation_alias="ENV_VAR_NAME")` in `Settings` — follow exactly for `regime_prob_min` / `regime_dur_min`
- Metrics registration: `src/observability/metrics.py` — all `shadow_*` metrics go here
- Pure module pattern for `src/core/roll_calendar.py`: no Kafka, no DB, no IBKR — pure date arithmetic, imports from `contracts.py`, returns roll windows. Testable in isolation. Same pattern as `src/core/stream_keys.py`.
- Service test `__new__` pattern: any new `__init__` attributes added to services must also be set in corresponding `tests/unit/service_tests/` test setup

### Integration Points
- `regime_gate.py` imports `_REGIME_PROB_MIN`, `_REGIME_DUR_MIN` from `aggregator.py` — after D-01, these move to Settings; `regime_gate.py` must accept them as parameters rather than module-level imports
- `weight_updater.py` already queries `signal_ledger` and `setup_performance` — shadow stats query adds `WHERE is_shadow=TRUE AND setup_plugin='trad_DualDivergence'` on the same connection
- Roll calendar integrates at `tws_daemon.py` `_emit_bar()` — called once per completed 1m bar, replace broken `update_volume(vol, vol)` call

</code_context>

<deferred>
## Deferred Ideas

- Threshold optimization (segment by TF, asset cluster, sensitivity sweep) — Phase 49 ML learns this as feature weights
- Automated shadow promotion (DB flag flip without human code change) — Phase 49 scope; promotion affects live trading and deserves a deliberate commit
- Dynamic IBKR subscription management to add next-month contracts during roll week — Option 2 was considered and rejected; calendar + volume anomaly is sufficient and subscription-safe
- Roll monitor consuming 5m bars directly (instead of accumulating from 1m) — offline validation uses 5m for clarity, but live detection on 1m is fine once the algorithm is correct
- Cross-asset lift measurement — Phase 49 assigns feature weight to cross-asset fields; if negligible, Phase 50 can evaluate removal

</deferred>

---

*Phase: 47-shadow-mode-graduation*
*Context gathered: 2026-03-22*
