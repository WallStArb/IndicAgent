# Phase 50: Roll Monitor & DualDivergence Graduation

**Status:** 🚧 Ready to Execute

**Milestone:** v2.2 Operational Excellence

**Dependencies:** Phase 49 ✅ (market_data_5m exists), Phase 53.3 ✅ (RollComputeAgent validated)

**Unblocked by:** Phase 53.3 — RollComputeAgent now standalone on `topic_roll_events`, validated 2026-03-28

---

## Goals

1. **D-21 Validation** — Validate roll detection with real market_data_5m backfill
2. **Migration Application** — Apply migration `049_roll_premium_pct.sql`
3. **Roll Monitor Graduation** — Enable `ROLL_MONITOR_ENABLED` after D-21 validation passes
4. **DualDivergence Promotion** — Promote trad_DualDivergence from shadow once D-07 gate passes

---

## Success Criteria

1. D-21 validation confirms roll detection works correctly with 5m data (≥90% detection, ≤10% FP)
2. `roll_premium_pct` column populated in intelligence_features during roll windows
3. `ROLL_MONITOR_ENABLED=true` set in production environment
4. trad_DualDivergence promoted (IS_SHADOW=False) after statistical gate passes (N≥100, 95% CI E[PnL_R] > 0)

---

## Context from Phase 53.3

Phase 53.3 delivered the RollComputeAgent as a standalone service:

- **New schema:** `RollEvent` (`src/core/schemas.py`) — `event_type`, `from_contract`, `to_contract`, `detected_at`, `volume_ratio`, `premium_pct`
- **New stream key:** `topic_roll_events()` → `development.roll_events` (compacted, 7d retention)
- **New agent:** `RollComputeAgent` (`services/roll_compute_agent.py`) — standalone roll detection, DB-ignorant, publishes to `topic_roll_events`
- **Provider rename:** `tws_daemon` → `DataProviderAgent` — roll logic removed, pure data provider now
- **Migration:** `signal_generator_agent` now consumes `topic_roll_events` instead of computing rolls inline

This phase graduates the shadow mode by validating against real 5m data and enabling the feature flag.

---

## Plans

### Plan 50.1: D-21 Roll Detection Validation

**Goal:** Run `validate_roll_detection.py` against market_data_5m to confirm roll detection works correctly.

**Requirements:** [D-21]

**Tasks:**

1. Run validation script:
   ```bash
   .venv/bin/python production/scripts/validate_roll_detection.py --symbols ES NQ --days 60
   ```

2. Verify metrics meet acceptance criteria:
   - Detection rate ≥ 90% (actual rolls detected / total rolls)
   - False positive rate ≤ 10% (detected rolls not in actual roll windows)

3. If validation fails:
   - Investigate failure mode (missed rolls vs FPs)
   - Adjust `RollComputeAgent._volume_ratio_threshold` or roll window logic
   - Re-run validation

**Exit Criteria:** Validation passes with ≥90% detection, ≤10% FP

---

### Plan 50.2: Apply roll_premium_pct Migration

**Goal:** Add `roll_premium_pct` column to `intelligence_features` and populate during roll windows.

**Requirements:** [INTEL-04]

**Tasks:**

1. Apply migration:
   ```bash
   docker exec timescaledb psql -U postgres -d indicagent -f migrations/049_roll_premium_pct.sql
   ```

2. Verify column exists:
   ```sql
   \d intelligence_features
   -- Should show roll_premium_pct numeric nullable
   ```

3. Verify `feature_writer_agent` already handles `roll_premium_pct` (already implemented — `_handle_roll_event` in `services/feature_writer_agent.py:548`):
   ```bash
   grep -n "roll_premium_pct" services/feature_writer_agent.py
   # Should show _handle_roll_event reading and persisting roll_premium_pct
   ```

**Exit Criteria:** Column exists in `intelligence_features` schema AND `feature_writer_agent` persists `roll_premium_pct` into it during roll windows (verified via `SELECT roll_premium_pct FROM intelligence_features WHERE roll_premium_pct IS NOT NULL LIMIT 1` after next roll event)

---

### Plan 50.3: Enable Roll Monitor

**Goal:** Set `ROLL_MONITOR_ENABLED=true` in production and verify `signal_generator_agent` consumes roll events.

**Requirements:** [SHADOW-03]

**Tasks:**

1. Update environment variable in production (use `/etc/indicagent/production.env` — the acceptance check greps this file):
   ```bash
   echo 'ROLL_MONITOR_ENABLED=true' | sudo tee -a /etc/indicagent/production.env
   grep "ROLL_MONITOR_ENABLED" /etc/indicagent/production.env  # verify
   ```

2. Restart `indicagent-signal-generator` (now consuming `topic_roll_events`):
   ```bash
   sudo systemctl restart indicagent-signal-generator
   ```

3. Verify roll event consumption in logs:
   ```bash
   journalctl -u indicagent-signal-generator --since "5 minutes ago" | grep -i roll
   ```

4. Verify `roll_premium_pct` populated in `intelligence_features` during next roll window

**Exit Criteria:** Service consuming roll events, `roll_premium_pct` populated live

---

### Plan 50.4: DualDivergence D-07 Gate Check & Promotion

**Goal:** Run statistical gate on trad_DualDivergence shadow signals and promote if passing.

**Requirements:** [SHADOW-04]

**Tasks:**

1. Run shadow gate validation:
   ```bash
   .venv/bin/python production/scripts/validate_alpha.py --plugin trad_DualDivergence --min_samples 100
   ```

2. Check gate criteria:
   - N ≥ 100 signals in shadow ledger
   - 95% confidence interval for E[PnL_R] excludes 0 (i.e., E[PnL_R] > 0 statistically significant)

3. If gate passes:
   - Update `src/intelligence/trading/dual_divergence.py`:
     ```python
     class DualDivergencePlugin(BaseSignalPlugin):
         IS_SHADOW = False  # Promote to live
     ```
   - Restart `indicagent-intelligence-pipeline`

4. If gate fails:
   - Review failure mode (negative E[PnL_R], insufficient N, high variance)
   - Determine if shadow period needs extension or plugin needs revision
   - Document decision in memory

**Exit Criteria:** Either trad_DualDivergence promoted with IS_SHADOW=False, or documented decision to extend shadow period

---

## Acceptance Summary

After all plans complete:

```bash
# grep-verifiable acceptance
grep "ROLL_MONITOR_ENABLED=true" /etc/indicagent/production.env
grep "IS_SHADOW = False" src/intelligence/trading/dual_divergence.py
docker exec timescaledb psql -U postgres -d indicagent -c "\d intelligence_features" | grep roll_premium_pct
docker exec timescaledb psql -U postgres -d indicagent -c "SELECT COUNT(*) FROM intelligence_features WHERE roll_premium_pct IS NOT NULL"
```
