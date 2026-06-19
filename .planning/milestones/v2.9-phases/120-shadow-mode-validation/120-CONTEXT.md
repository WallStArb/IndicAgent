# Phase 120: Shadow Mode Validation - Context

**Gathered:** 2026-06-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the automated promotion pipeline for the 21 refactored I7 setups. A new weekly `ShadowModeValidator` script evaluates all shadow setups against 5 statistical criteria and promotes passing setups by writing `is_shadow=False` to `shadow_registry`. `shadow_auditor.py` is surgically modified to remove its existing promotion path (becomes demotion-only). A `signal_ledger_shadow` DB view is created. A Grafana dashboard and promotion Telegram alert complete the observability contract.

**In scope:**
- New `services/shadow_validator.py` (weekly oneshot, Mon 07:00 UTC) — 5-criteria promotion gate
- DB migration 120: `signal_ledger_shadow` view (`signal_ledger_full WHERE is_shadow=true`)
- Surgical modification of `shadow_auditor.py` to remove `_check_promotion()` / become demotion-only
- Systemd timer + service unit (`indicagent-shadow-validator.timer`)
- OTel metrics per setup: N, selection_rate, p_value, avg_pnl_r, calibration_correlation, promotion_status
- Grafana dashboard: per-setup status table + promotion events panel
- CRITICAL Telegram alert on promotion (via `topic_alert_requests`)

**Out of scope:**
- Empirical threshold tuning (Phase 121)
- Lifecycle replay (Phase 121)
- Extrinsic composite confidence layer (Phase 4.1 per root cause doc)
- Modifying existing I7 setup code

</domain>

<decisions>
## Implementation Decisions

### D-01: Architecture — Separate Weekly Service (SoC)

`shadow_validator.py` is a NEW standalone script. It does NOT extend `shadow_auditor.py`.

**Responsibility split (non-negotiable SoC):**
- `shadow_auditor.py` (30-min timer) → **demotion only** — fast feedback, catches live performance degradation
- `shadow_validator.py` (weekly timer) → **promotion only** — statistical graduation gate requiring full lifecycle completion

**Why separate:** Different cadence, different query patterns, different statistical purpose. Conflating promotion + demotion in one script creates a coupled, hard-to-reason-about audit loop. Weekly cadence for promotion is required because the setup needs N >= 100 resolved signals, which takes time.

**Migration from shadow_auditor.py:** Remove `_check_promotion()` function and its call in `_run_audit()`. Demotion path (`_check_demotion()`) is unchanged. This is a surgical 2-line call-site removal + function deletion.

---

### D-02: Promotion Criteria — 5-Gate Sequential Check

All 5 gates must pass for promotion. Short-circuit on first failure (cheapest checks first).

**IMPORTANT — why not `was_selected`:** Shadow signals are excluded from winner selection by design (`signal_processor.py` builds `eligible_ranked` from non-shadow only). Therefore `was_selected` is structurally always `False` for every shadow signal. Using it in Gates 2/3/5 would make promotion permanently impossible. All gates use `pnl_r`-based outcome metrics instead — consistent with the existing `shadow_auditor._check_promotion` pattern.

```python
# Gate 1: Sufficient resolved outcomes
if n_resolved < 100:
    return False, "insufficient_n", f"{n_resolved} resolved < 100"

# Gate 2: Win rate > 50% (setup produces positive outcomes more often than chance)
win_rate = wins / n_resolved
if win_rate < 0.5:
    return False, "low_win_rate", f"{win_rate:.1%} < 50%"

# Gate 3: Statistical significance (binomial test on win rate vs 50% baseline)
from scipy.stats import binomtest
result = binomtest(wins, n_resolved, p=0.5, alternative='greater')
if result.pvalue >= 0.05:
    return False, "not_significant", f"p={result.pvalue:.3f} >= 0.05"

# Gate 4: Positive expectancy
if avg_pnl_r <= 0:
    return False, "negative_expectancy", f"avg_pnl_r={avg_pnl_r:.3f}"

# Gate 5: Confidence calibration (cis_score predicts profitable outcomes)
if calibration_corr is None or calibration_corr < 0.3:
    return False, "poor_calibration", f"corr={calibration_corr:.3f} < 0.3"
```

Where: `n_resolved` = resolved shadow outcomes (pnl_r IS NOT NULL), `wins` = COUNT(pnl_r > 0).

**Note on scipy:** Use `binomtest` (not the deprecated `binom_test`). Import from `scipy.stats`.

---

### D-03: Outcome Metrics and Calibration Columns

Shadow signals never have `was_selected=True` (they are excluded from winner selection by design). All promotion metrics derive from resolved `pnl_r` outcomes tracked by the lifecycle tracker.

**Per-setup query:**
```sql
SELECT
  COUNT(*) FILTER (WHERE so.pnl_r IS NOT NULL) AS n_resolved,
  COUNT(*) FILTER (WHERE so.pnl_r > 0) AS wins,
  AVG(so.pnl_r) FILTER (WHERE so.pnl_r IS NOT NULL) AS avg_pnl_r,
  CORR(sl.cis_score, (so.pnl_r > 0)::int)
    FILTER (WHERE so.pnl_r IS NOT NULL) AS calibration_corr
FROM signal_ledger sl
LEFT JOIN signal_outcomes so USING (signal_id)
WHERE sl.setup_plugin = $1
  AND sl.is_shadow = true
  AND sl.shadow_tracking_start_ts IS NOT NULL
```

**Calibration metric:** `CORR(cis_score, (pnl_r > 0)::int)` — does the aggregator's composite score predict profitable outcomes? Higher cis_score should correlate with pnl_r > 0. This is the correct signal: it measures whether the ranking system's confidence predicts actual edge, not selection (which is impossible for shadow signals).

**Sampling window:** All signals since `shadow_tracking_start_ts` — maximize N. No rolling 30-day window.

---

### D-04: `signal_ledger_shadow` DB View

New view created in migration 120:

```sql
CREATE VIEW signal_ledger_shadow AS
  SELECT *
  FROM signal_ledger_full
  WHERE is_shadow = true;
```

`signal_ledger_full` already JOINs `signal_ledger` + `signal_outcomes` and includes `was_selected`, `cis_score`, `pnl_r`. The view provides a clean, nameable interface for all shadow-specific queries (validator, dashboard, future analytics).

---

### D-05: Promotion Write Path

On gate clearance, `shadow_validator.py` writes directly to `shadow_registry` (same pattern as `shadow_auditor.py`):

```python
await conn.execute(
    "UPDATE shadow_registry SET is_shadow=FALSE, promoted_at=$1 WHERE component_name=$2",
    now, plugin_name
)
await conn.execute(
    """INSERT INTO shadow_transition_log
       (component_name, component_type, from_state, to_state, trigger_reason, n, ev_r, ci_lower, win_rate)
       VALUES ($1, 'i7_plugin', 'shadow', 'live', 'shadow_validator_5gate', $2, $3, $4, $5)""",
    plugin_name, total, avg_pnl_r, calibration_corr, selection_rate
)
```

---

### D-06: Target Setup List

Hardcode the 21 refactored setups as a module-level constant in `shadow_validator.py`:

```python
_SHADOW_VALIDATION_SETUPS: frozenset[str] = frozenset({
    # Phase 118 (5 setups)
    "trad_OFIContinuation", "trad_PatternCompletion",
    "trad_GapAnalysisSetup", "trad_CVDDivergence", "trad_DivergenceStack",
    # Phase 119 (17 setups — verified against _PHASE_119_PLUGINS in register_plugins.py)
    "trad_OFISpike", "trad_CVDSpike", "trad_OFIDivergence",
    "trad_FailedBreakout", "trad_CandlestickPatternSetup",
    "trad_SessionExtremesSetup", "trad_LiquidityHunt", "trad_DeltaExhaustion",
    "trad_LVNBreakout", "trad_VWAPReclaim", "trad_VWAPDeviation",
    "trad_MomentumBreakout", "trad_ORB15", "trad_ORB30",
    "trad_SecondLegContinuation", "trad_VCP", "trad_DualDivergence",
})
# Total: 22 (5 Phase 118 + 17 Phase 119). Verified against _PHASE_119_PLUGINS frozenset (register_plugins.py:667).
assert len(_SHADOW_VALIDATION_SETUPS) == 22
```

**Verified 2026-06-10 against `_PHASE_119_PLUGINS` in `register_plugins.py` — count is 22, not 21.** The original count of 21 was a data integrity error. All executor implementations must use `assert len == 22`.

---

### D-07: Notification on Promotion

Use existing alert infrastructure: publish to `topic_alert_requests` via `KafkaProducerClient`. Severity: CRITICAL (routes to Telegram via AlertMonitor).

```python
await producer.publish(msg={
    "severity": "CRITICAL",
    "message": f"Shadow Promotion: {name}\nN={n_resolved}, win_rate={win_rate:.1%}, p={pvalue:.3f}, avg_pnl_r={avg_pnl_r:.3f}, calibration={calibration_corr:.3f}",
    "source": "shadow_validator",
})
```

One Kafka publish per promoted setup. Kafka optional — if not available, log prominently and continue.

---

### D-08: OTel Metrics

New metrics in `src/observability/metrics.py`:

```python
SHADOW_VALIDATION_N = point_gauge("shadow_validation_n", "Resolved shadow outcome count per setup (weekly validator run)")
SHADOW_VALIDATION_WIN_RATE = point_gauge("shadow_validation_win_rate", "Fraction of resolved shadow outcomes with pnl_r > 0")
SHADOW_VALIDATION_P_VALUE = point_gauge("shadow_validation_p_value", "Binomial test p-value (win rate vs 50% baseline, one-sided)")
SHADOW_VALIDATION_AVG_PNL_R = point_gauge("shadow_validation_avg_pnl_r", "Average pnl_r across resolved shadow outcomes")
SHADOW_VALIDATION_CALIBRATION = point_gauge("shadow_validation_calibration", "CORR(cis_score, (pnl_r > 0)::int) — confidence predicts profitable outcomes")
SHADOW_VALIDATION_PROMOTED = point_gauge("shadow_validation_promoted", "1=promoted to live this run, 0=still in shadow")
```

Emit for ALL 22 setups on every weekly run (including those that don't promote — so Grafana shows the status). Label key: `setup_plugin`.

---

### D-09: Systemd Timer

Weekly timer, Mon 07:00 UTC (weekend data settled, new trading week just started):

```ini
# indicagent-shadow-validator.timer
[Timer]
OnCalendar=Mon *-*-* 07:00:00 UTC
Persistent=true
Unit=indicagent-shadow-validator.service
```

Service is `Type=oneshot`, same pattern as `indicagent-hmm-training.service`. Job label for `JOB_COMPLETED_TOTAL`: `"shadow-validator"` (matches unit `%n` suffix).

---

### D-10: shadow_auditor.py Modification Scope

Remove exactly:
1. `_check_promotion()` function body
2. The `await _check_promotion(pool, env_name, row)` call inside `_run_audit()`
3. Any imports only used by `_check_promotion` (verify — tail risk imports may be shared with demotion)

Do NOT change: demotion logic, OTel metrics for demotion, `JOB_COMPLETED_TOTAL`, `main()`.

After modification: `shadow_auditor.py` only iterates shadow components and calls `_check_demotion()`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Root Cause + Blueprint
- `docs/plans/2026-06-07-signal-quality-crisis-root-cause-analysis.md` — Blueprint Part 4 (Shadow Mode Validation), Section "calibration_correlation" definition, Section "selection_rate" definition. The ShadowModeValidator pseudocode lives here — validate against it.

### Phase 118/119 Context (refactored setup list + patterns)
- `.planning/phases/119-remaining-16-setup-refactoring/119-CONTEXT.md` — Canonical list of Phase 119 setup names, D-01 through D-04 decisions (gate structure, thresholds). Verify `_PHASE_119_PLUGINS` and `_I7_I6_EXEMPT` frozensets for exact plugin names.
- `.planning/phases/118-confidence-integrity-top5-setup-refactoring/118-VERIFICATION.md` — Phase 118 plugin names (5 setups) — must match against `_SHADOW_VALIDATION_SETUPS`

### Existing Shadow Infrastructure (READ before modifying)
- `services/shadow_auditor.py` — Current promotion + demotion logic. D-10 specifies exactly what to remove. Read before modifying.
- `src/core/stats_utils.py` — `bootstrap_ci_lower()` (already exists; shadow_validator uses `scipy.stats.binomtest` instead)

### Plugin Registry (source of truth for setup names)
- `src/intelligence/register_plugins.py` — `TIER_I7`, `_I7_I6_EXEMPT`, `_PHASE_119_PLUGINS` frozensets — verify all 21 setup names before hardcoding in `shadow_validator.py`

### DB Schema
- `signal_ledger` table: `is_shadow` (bool), `was_selected` (bool, existing), `cis_score` (float), `shadow_tracking_start_ts` (timestamptz)
- `signal_outcomes` table: `pnl_r` (float) — JOINed via `signal_ledger_full`
- `shadow_registry` table: `is_shadow`, `promoted_at`, `component_name` — promotion writes here
- `shadow_transition_log` table — audit trail for promotions (same INSERT pattern as shadow_auditor.py)
- `signal_ledger_full` view — base for `signal_ledger_shadow` view (migration 120)

### Systemd Timer Pattern
- `production/systemd/indicagent-hmm-training.timer` + `indicagent-hmm-training.service` — canonical oneshot timer pattern

### OTel Metrics Pattern
- `src/observability/metrics.py` — `create_gauge()`, `JOB_COMPLETED_TOTAL`, existing shadow metrics (SHADOW_N_RESOLVED, SHADOW_EV_R, etc.) — extend, don't duplicate
- `services/alert_monitor.py` — Kafka alert routing (CRITICAL → Telegram)
- `src/core/stream_keys.py` — `topic_alert_requests` key construction

### Design Principles
- `docs/foundation/principles.md` — "Earn promotion through proof", "Empirical over theoretical"
- `CLAUDE.md` — Service registry DAG note: when adding shadow_validator service, update `_DAG_ORDER`, `_LAG_THRESHOLDS`, `_AGENT_ID_TO_UNIT` in `services/service_auditor.py`

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `shadow_auditor.py` pattern: `asyncio.run(_amain())`, `create_db_pool()`, `JOB_COMPLETED_TOTAL`, `flush_and_shutdown_metrics()` — copy verbatim for shadow_validator.py structure
- `_path_bootstrap` import pattern — required at top of all service scripts
- `KafkaProducerClient.publish(msg=...)` — note kwarg is `msg=`, not `value=` (silent failure if wrong)
- `topic_alert_requests(settings)` from `src/core/stream_keys.py`
- Existing shadow OTel metrics in `src/observability/metrics.py`: `SHADOW_N_RESOLVED`, `SHADOW_EV_R`, `SHADOW_WIN_RATE`, `SHADOW_PROMOTION_READY` — new Phase 120 metrics complement these, don't replace

### Established Patterns
- **DB query pattern:** `asyncpg.Pool`, `pool.acquire()`, `conn.fetch()`/`conn.execute()` — no `json.loads()`/`json.dumps()` for JSONB
- **Oneshot job completion:** `JOB_COMPLETED_TOTAL.add(1, {"job": "shadow-validator", "status": "success/failure"})` + `flush_and_shutdown_metrics()` — mandatory per CLAUDE.md D-06
- **Timestamp:** `datetime.now(UTC)` only
- **Structlog:** `logger.info(...)` with kwargs (not positional) — avoid `event=` kwarg, use `signal=` or `data=`

### Integration Points
- `services/service_auditor.py` — `_DAG_ORDER`, `_LAG_THRESHOLDS`, `_AGENT_ID_TO_UNIT` — add `indicagent-shadow-validator` entry
- `production/systemd/` — add `indicagent-shadow-validator.timer` + `.service` files
- `src/observability/metrics.py` — add 6 new shadow_validation_* gauges
- `dashboards/` — add new Grafana dashboard JSON for shadow validation
- `migration_120.sql` — create `signal_ledger_shadow` view

</code_context>

<specifics>
## Specific Ideas

- **`scipy.stats.binomtest`** (not deprecated `binom_test`) — the new API from scipy 1.7+
- **Grafana dashboard:** Table panel with columns: setup_plugin, N, selection_rate, p_value, avg_pnl_r, calibration, status (promoted/shadow). Color-code status column. Add time-series panel showing N accumulation per setup over time (how close each is to N=100 gate).
- **Failure reasons logged:** For each non-promoting setup, log which gate it failed and the value vs threshold. This is essential for Phase 121 debugging. Use structlog: `logger.info("shadow_validator.gate_fail", plugin=name, reason=reason, value=value, threshold=threshold)`
- **Migration is a view only:** `migration_120.sql` creates one view. No schema changes, no new columns. Fast to deploy.
- **`_SHADOW_VALIDATION_SETUPS` in shadow_validator.py**: derive from `_PHASE_119_PLUGINS | {"trad_OFIContinuation", "trad_PatternCompletion", "trad_GapAnalysisSetup", "trad_CVDDivergence", "trad_DivergenceStack"}` — but since those constants live in register_plugins.py (not importable from a services/ script without coupling), hardcode as a frozenset with a comment pointing to the authoritative source.

</specifics>

<deferred>
## Deferred Ideas

- **Extrinsic composite confidence layer** — softmax-normalized composite of ctf_score + hmm_regime_weight + zone_friction + exhaustion_guard applied as a post-intrinsic multiplier at aggregator layer. Per root cause doc Phase 4.1. Belongs in its own phase after Phase 121.
- **Per-setup threshold tuning** — using Phase 120's shadow data to empirically derive optimal `_MIN_*` threshold values per setup. Phase 121 scope.

</deferred>

---

*Phase: 120-Shadow-Mode-Validation*
*Context gathered: 2026-06-10*
