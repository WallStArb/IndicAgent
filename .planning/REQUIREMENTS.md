# Requirements: v2.10 Data Architecture Evolution

**Defined:** 2026-06-14
**Core Value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.

## v1 Requirements

### ECL Boundary Restoration (Phase 123)

- [x] **ECL-01**: Zero I7 plugins call `no_signal()` based on any extrinsic vector (CTF score, zone_friction, exhaustion state) — all extrinsic vectors are annotations on the emitted signal, never emission gates
- [x] **ECL-02**: `signal_events` schema has five new fields: `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `factor_scores` (JSONB), `context_features` (JSONB) — all populated at emit time
- [x] **ECL-03**: `SIGNAL_SCHEMA_VERSION` is incremented; `context_features` is populated in `signal_processor.py` (not the `_shadow` dict); all 37 I7 plugins collect `factor_scores` dict before compositing

### Signal Universe Integrity (Phase 124)

- [ ] **QUALITY-01**: All 5 over-firing plugins (firing > 3%/bar) are corrected to event-onset detection; post-fix fire rate confirmed < 3%/bar per SQL validation
- [ ] **QUALITY-02**: `intelligence_features` ON CONFLICT guard uses `WHERE ctf_score IS NULL` only — the `OR ctf_score = 0.0` branch that overwrites valid neutral-CTF readings is removed; `--warmup` pass operational in `run_historical_pipeline.py`

### APR Full Migration (Phase 125)

- [x] **APR-01**: All 26 Tier A detection gate constants (`threshold.*`, `feature.*`) externalized to `config_state`; zero hard-coded values in `src/` (grep confirms); all Tier A plugins load from ConfigService at `compute_full()` time
- [x] **APR-02**: All 22 Tier B confidence weight constants (`weights.*`) externalized to `config_state`; weight sum invariant enforced via `_validate_weights_sum()` in all Tier B plugins
- [x] **APR-03**: All 6 Tier C zone engine geometry constants (`feature.zone_engine.*`, `weights.zone_engine.*`) externalized to `config_state`; `zone_engine.py` loads from ConfigService at startup

### Signal Universe Hardening (Phase 126)

- [ ] **SIGNAL-QUALITY-01**: `_resolve_zone_bounds()` in `trade_framer.py` returns `no_signal()` when `zone_width < min_zone_width_atr × ATR` for all zone source types (supply_demand, fvg, ob, structural); `feature.zone_engine.min_zone_width_atr` in APR with per-asset-class seeds (equity_etf: 0.5, forex: 0.25, futures: 0.35); `stopped_at_entry` rate < 15% on 10K-signal replay sample — target set at 3× forex upper bound (forex baseline 3-5%; equity allows wider margin for tick-size structure)
- [ ] **SIGNAL-QUALITY-02**: `_CONFLUENCE_EXEMPT_PLUGINS` frozenset deleted; all 8 formerly-exempt plugins have `requires_i6_confluence = True` and call `capture_signal_features()`; all 37 registered signal-generation plugins emit > 0 signals in 30-day replay window; `trad_MeanReversion` dual-gate conflict resolved (fires > 100 signals/30d) or retired with documented rationale; unverifiable plugins from detection correctness audit retired from `TIER_SIGNALS` or demoted to `shadow_only=True` with explicit rationale

### Clean Replay and Validation (Phase 127)

- [ ] **REPLAY-01**: Full historical replay completes on the corrected pipeline (Phases 123-126 applied) with `--warmup`; `context_features` coverage > 99% for non-cold-start signals; all 5 over-firing plugins confirmed < 3% fire rate in replay output
- [ ] **REPLAY-02**: Phase 121-02 deferred validation report produced using correct methodology — signal volume delta (pre/post ECL fix), CTF as feature analysis, firing rate distribution, cold-start null distribution; no cross-population Welch's t-test; calibration curves retrained on clean corpus; RCA Part VI updated

### 3-Table Signal Architecture (Phases 128-130)

- [ ] **ARCH-01**: `signal_events`, `trade_frames`, `trade_executions` tables created with full schemas, FK constraints, and indexes as defined in `docs/plans/2026-06-14-v2.10-signal-architecture-refactor.md`; `signal_ledger_v2` backward-compat view deployed; `counterfactual_pnl_r` is a required first-class column on `trade_frames`
- [ ] **MIGRATE-01**: All `signal_ledger` data migrated into the 3-table schema with row-count verification; `signal_ledger` retained read-only during the 48-hour transition window
- [ ] **REWRITE-01**: All writers, trackers, auditors, API endpoints, and historical backfill scripts write to and read from the 3-table schema; `signal_ledger` dropped after the verification window; `signal_ledger_v2` is the sole backward-compatibility surface

---

## Future Requirements (v2.11)

| Requirement | Trigger |
|-------------|---------|
| CounterfactualTracker daemon — populates `counterfactual_pnl_r` on every trade frame regardless of execution | Requires `trade_frames` table (Phase 128) |
| I6 DB bootstrap at daemon startup — eliminates cold-start permanently | Requires `intelligence_features` accumulation |
| APR ML optimization — regress `factor_scores` against `counterfactual_pnl_r` to discover optimal weights | Requires 30-90 days of `counterfactual_pnl_r` data; all 54 APR keys already externalized (Phase 125) |
| SignalRanker (LightGBM) — replace calibration + `perf_multiplier` chain with end-to-end trained ranking model | Requires `context_features` (Phase 123) + `counterfactual_pnl_r` (Phase 130 CounterfactualTracker) |

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Moving signal generation or trade framing out of IntelligencePipeline | Principle 12 (Signal Generation Invariant) — settled, not revisited in v2.10 |
| Execution engine / order routing | Intelligence platform only |
| v2.8 Part 2 AI platform phases (096-099, 101-103) | Separate milestone; unblocked after v2.10 completes |
| CounterfactualTracker daemon | v2.11 Phase 130 seed — requires trade_frames to exist and accumulate first |

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ECL-01 | Phase 123 | Complete |
| ECL-02 | Phase 123 | Complete |
| ECL-03 | Phase 123 | Complete |
| QUALITY-01 | Phase 124 | Pending |
| QUALITY-02 | Phase 124 | Pending |
| APR-01 | Phase 125 | Complete |
| APR-02 | Phase 125 | Complete |
| APR-03 | Phase 125 | Complete |
| SIGNAL-QUALITY-01 | Phase 126 | Pending |
| SIGNAL-QUALITY-02 | Phase 126 | Pending |
| REPLAY-01 | Phase 127 | Pending |
| REPLAY-02 | Phase 127 | Pending |
| ARCH-01 | Phase 128 | Pending |
| MIGRATE-01 | Phase 129 | Pending |
| REWRITE-01 | Phase 130 | Pending |

**Coverage:**
- v1 requirements: 15 total
- Mapped to phases: 15
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-14*
*Last updated: 2026-06-14 — Phase 126 inserted; SIGNAL-QUALITY-01/02 added; REPLAY/ARCH/MIGRATE/REWRITE renumbered +1; coverage 15 total*
