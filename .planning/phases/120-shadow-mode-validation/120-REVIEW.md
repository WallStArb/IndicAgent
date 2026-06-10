---
phase: 120-shadow-mode-validation
reviewed: 2026-06-10T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - docs/reference/cheatsheet.md
  - production/grafana/dashboards/shadow-validation.json
  - production/migrations/121_signal_ledger_shadow_view.sql
  - production/systemd/indicagent-shadow-validator.service
  - production/systemd/indicagent-shadow-validator.timer
  - services/service_auditor.py
  - services/shadow_auditor.py
  - services/shadow_validator.py
  - src/observability/metrics.py
  - tests/unit/services/test_shadow_auditor.py
findings:
  critical: 1
  warning: 3
  info: 3
  total: 7
status: issues_found
---

# Phase 120: Code Review Report

**Reviewed:** 2026-06-10T00:00:00Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Phase 120 introduces the weekly shadow-mode promotion validator (`shadow_validator.py`), a migration adding the `signal_ledger_shadow` view, Grafana dashboard, and systemd service/timer units. The auditor (`shadow_auditor.py`) was also reviewed as part of the scope.

The core 5-gate promotion logic is sound: sequential short-circuit, correct binomial test parameters, asyncpg patterns, and OTel metric emission all look correct. The DB write-before-Kafka ordering is correct (D-07 compliance). The test suite covers the demotion path but has a coverage gap on the promotion gate function.

One blocker: two timer-triggered oneshot units are missing from `_ONESHOT_UNITS` in `service_auditor.py`, meaning the service auditor will attempt to restart them when they appear `inactive` between runs -- the exact failure mode the set was designed to prevent. Three warnings follow. Three informational items round out the report.

---

## Critical Issues

### CR-01: Two oneshot units missing from `_ONESHOT_UNITS` -- service auditor will restart them spuriously

**File:** `services/service_auditor.py:98-99`
**Issue:** `indicagent-feature-parity-auditor` and `indicagent-confidence-calibration-monitor` appear in `_DAG_ORDER` with comments explicitly calling them "oneshot: timer-triggered, not a daemon", but neither is present in `_ONESHOT_UNITS`. The `_evaluate_service_dynamic` method (line 506) and the stall-detection loop (line 444) both gate on `unit in _ONESHOT_UNITS` to suppress restarts. Without that membership, the service auditor will call `_restart_service_by_unit()` on these units whenever systemd reports them `inactive` between scheduled runs. For `indicagent-confidence-calibration-monitor` this fires every 30 minutes (timer cadence); for `indicagent-feature-parity-auditor` on every check cycle after its daily run completes. Each spurious restart increments `SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL`, pollutes `service_health_events`, and may interfere with the timer's scheduled execution.

**Fix:**
```python
_ONESHOT_UNITS: frozenset[str] = frozenset(
    {
        "indicagent-redpanda-ready",
        "indicagent-redpanda-watchdog",
        "indicagent-timescaledb-ready",
        "indicagent-weight-updater",
        "indicagent-shadow-auditor",
        "indicagent-shadow-validator",
        "indicagent-signal-probe-auditor",
        "indicagent-ml-orchestrator",
        "indicagent-ml-data-quality",
        "indicagent-ml-discovery",
        "indicagent-ml-training",
        "indicagent-ml-signal-training-materialize",
        "indicagent-roll-batch",
        "indicagent-memory-batch",
        "indicagent-feature-validation",
        "indicagent-hmm-training",
        "indicagent-feature-parity-auditor",        # ADD
        "indicagent-confidence-calibration-monitor", # ADD
    }
)
```

---

## Warnings

### WR-01: `signal_ledger_shadow` view (migration 121) is never queried -- dead migration artifact

**File:** `production/migrations/121_signal_ledger_shadow_view.sql:9`
**Issue:** The migration creates `signal_ledger_shadow AS SELECT * FROM signal_ledger_full WHERE is_shadow = true`. The stated purpose in the file header is to be used by `shadow_validator.py`. However, `shadow_validator.py` queries `signal_ledger sl LEFT JOIN signal_outcomes so` directly (line 171) with an inline `is_shadow = true` filter. The view is not referenced anywhere in Python, SQL, or dashboard code outside its own migration. Deploying a named DB view that nothing reads adds schema surface area with no payoff, and creates future confusion ("why does this view exist if nothing uses it?").

**Fix:** Either rewrite the validator query to use `signal_ledger_shadow` (eliminating the inline filter) so the view earns its place, or drop the migration and the view. Using the view would be the cleaner option:
```sql
-- shadow_validator.py query using the view:
SELECT
  COUNT(*) FILTER (WHERE so.pnl_r IS NOT NULL) AS n_resolved,
  COUNT(*) FILTER (WHERE so.pnl_r > 0)         AS wins,
  AVG(so.pnl_r) FILTER (WHERE so.pnl_r IS NOT NULL) AS avg_pnl_r,
  CORR(sl.cis_score, (so.pnl_r > 0)::int)
    FILTER (WHERE so.pnl_r IS NOT NULL) AS calibration_corr
FROM signal_ledger_shadow sl
LEFT JOIN signal_outcomes so USING (signal_id)
WHERE sl.setup_plugin = $1
  AND sl.shadow_tracking_start_ts IS NOT NULL
```

### WR-02: Binomial test computed twice per setup when `n_resolved > 0`

**File:** `services/shadow_validator.py:191,113`
**Issue:** `_validate_setup` calls `binomtest(wins, n_resolved, ...)` at line 191 to compute `p_value` for the gauge, then `_check_promotion_criteria` calls `binomtest(wins, n_resolved, ...)` again at line 113 for the promotion decision. For any setup with `n_resolved >= 100` that passes Gate 2, the binomial test is executed twice per weekly run with identical inputs. `binomtest` is computationally cheap, so this is not a performance issue, but it creates a maintenance risk: if the test parameterization ever diverges between the two call sites (e.g., one is updated to `alternative="two-sided"` and the other is not), the p-value emitted to Prometheus will silently disagree with the gate that controls promotion.

**Fix:** Pass `p_value` into `_check_promotion_criteria` as a parameter so the result is computed once:
```python
def _check_promotion_criteria(
    n_resolved: int,
    wins: int,
    p_value: float,      # pre-computed at call site
    avg_pnl_r: float | None,
    calibration_corr: float | None,
) -> tuple[bool, str, str]:
    ...
    # Gate 3: Statistical significance
    if p_value >= 0.05:
        return False, "not_significant", f"p={p_value:.3f} >= 0.05"
    ...
```

### WR-03: Stale IBKR host in `docs/reference/cheatsheet.md` environment variables section

**File:** `docs/reference/cheatsheet.md:125`
**Issue:** The "Environment Variables" section documents `IBKR_HOST="192.168.1.157"`. CLAUDE.md states the IBKR gateway was moved to a Docker container and is now bound to `127.0.0.1:7497`. A developer following the cheatsheet to configure their environment will set the wrong host and get a connection failure that is non-obvious to diagnose. The pipeline_reset.py comment at line 89 (`192.168.1.157`) is a second instance of the same stale reference.

**Fix:**
```bash
# Environment Variables (cheatsheet.md lines 120-127)
INDICAGENT_ENV="development"
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/indicagent"
KAFKA_BOOTSTRAP_SERVERS="localhost:19092"
IBKR_HOST="127.0.0.1"   # Docker ib-gateway container (was 192.168.1.157)
IBKR_PORT=7497
```
Also update line 89 in the Pipeline Reset section to remove the stale `192.168.1.157:7497` reference.

---

## Info

### IN-01: No unit tests for `_check_promotion_criteria` in `shadow_validator.py`

**File:** `tests/unit/services/test_shadow_auditor.py:1`
**Issue:** `shadow_auditor.py` has good test coverage for both pure gate functions (`_should_demote`, `_ev_r_below_threshold`) and an integration-style test for `_run_audit`. `shadow_validator.py` exposes the equally important `_check_promotion_criteria` pure function, but the test file has no tests for it. Edge cases with real risk of latent bugs include: `n_resolved == 99` (just below Gate 1), `wins == n_resolved / 2` (exactly 50% win rate, passes Gate 2 but is unlikely to pass Gate 3), `avg_pnl_r == 0.0` (fails Gate 4 due to `<= 0` check), and `calibration_corr == None` (Gate 5 null guard).

**Fix:** Add a `test_shadow_validator.py` covering the pure gate function at each boundary:
```python
from services.shadow_validator import _check_promotion_criteria

def test_gate1_insufficient_n():
    ok, reason, _ = _check_promotion_criteria(99, 60, 0.1, 0.4)
    assert ok is False and reason == "insufficient_n"

def test_gate4_zero_avg_pnl_r_fails():
    ok, reason, _ = _check_promotion_criteria(100, 60, 0.0, 0.4)
    assert ok is False and reason == "negative_expectancy"

def test_gate5_none_calibration_fails():
    ok, reason, _ = _check_promotion_criteria(100, 60, 0.1, None)
    assert ok is False and reason == "poor_calibration"
```

### IN-02: Kafka alert severity `"CRITICAL"` used for promotion events

**File:** `services/shadow_validator.py:270`
**Issue:** The Kafka alert payload for a successful promotion uses `"severity": "CRITICAL"`. Shadow promotions are good news (a setup passed all 5 statistical gates). `CRITICAL` severity typically implies a system failure or urgent intervention required. Using `CRITICAL` for a positive lifecycle event will cause alerting consumers to page on-call for something that requires no action. `INFO` or `HIGH` would better reflect the importance-but-not-urgency of a promotion notification.

**Fix:** Change `"severity": "CRITICAL"` to `"severity": "INFO"` (or `"HIGH"` if the alerting channel treats this as worthy of a non-page notification).

### IN-03: `shadow_validator.service` missing `[Install]` section `WantedBy` relative to timer, and `User=bg` inconsistency

**File:** `production/systemd/indicagent-shadow-validator.service:17`
**Issue:** The service file has `WantedBy=multi-user.target` in `[Install]`. For a timer-driven oneshot, the service itself should not be `WantedBy` any target -- it should only be started by its companion `.timer` unit. Having `WantedBy=multi-user.target` means `systemctl enable indicagent-shadow-validator.service` would start it at boot independently of the timer, which is almost certainly unintended. Compare with `indicagent-confidence-calibration-monitor.service`, which has the same structure. Note also that `indicagent-shadow-validator.service` explicitly sets `User=bg` while `indicagent-confidence-calibration-monitor.service` does not -- this inconsistency is minor but creates drift in the unit file convention.

**Fix:** Remove `[Install]` section from the `.service` file (the timer unit handles enablement). The `.timer` file already has `WantedBy=timers.target` which is the correct activation path.

---

_Reviewed: 2026-06-10T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
