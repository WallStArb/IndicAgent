# Phase 127 — Calibration Retrain Pre-Flight & v2.11 Dependency Log

**Plan:** 127-03 (REPLAY-02)
**Date:** 2026-06-17
**Outcome:** RETRAIN **NOT TRIGGERED**. SC-05 **DEFERRED to v2.11 by design** (not by failure).
**Corpus:** rebuild corpus from `lifecycle_replay --workers 8` (the source of truth per `127-RECONCILIATION.md`).

---

## Pre-flight checks (run 2026-06-17 against the live rebuild corpus)

### (a) Migration-gap check on the training query
```
$ grep -rnE "signal_outcomes|signal_ledger_full" services/ml_training_agent.py
CLEAN — no legacy table refs
```
No Phase 130 migration gap in the service entrypoint. The service delegates to
`src/core/ml/training_data.py`.

### (b) Calibration target identification
`ml_training_agent.py` contains no SQL directly; it delegates to the ML layer. The
load-bearing query is in `src/core/ml/training_data.py`:

```sql
-- training_data.py:44-58
sl.counterfactual_pnl_r AS pnl_r,          -- :45  ← the calibration target
...
FROM intelligence_features f
JOIN signal_ledger sl                       -- :49  (3-table JOIN view)
...
AND sl.counterfactual_pnl_r IS NOT NULL     -- :58  ← only labeled rows (V2.11_ACTIVATED)
```

**Calibration target = `trade_frames.counterfactual_pnl_r`** (surfaced through the
`signal_ledger` JOIN view). The query filters to non-NULL rows only.

### (c) Target-population check against the rebuild corpus (decisive)

```
trade_frames.counterfactual_pnl_r:
  total=1,036,513   non_null=0        ← 100% NULL

trade_executions.actual_pnl_r:
  total=1,063,798   non_null=989,502  ← heavily populated by lifecycle replay

trade_executions.exit_reason distribution:
  stop_loss           539,114
  ttl_expired_ahead   244,503
  ttl_expired_behind  120,722
  target_1             94,321
  ttl_expired          65,138
```

**Decisive result:** the calibration target (`counterfactual_pnl_r`) is **all-NULL**
(0 / 1,036,513). The training query's `IS NOT NULL` filter selects **zero rows** → a
retrain would learn nothing. Retrain must NOT trigger.

---

## Trigger decision: **NOT TRIGGERED**

Rationale: the calibration target is entirely absent. Calling
`systemctl start indicagent-ml-training.service` would run the calibrator against an
empty labeled set — a silent-wrong (or no-op) calibration. No `systemctl start` invoked.

---

## Correction to the plan's premise (recorded for rigor)

Plan 03's `critical_corrections` #2 assumed `trade_executions` would be **empty**
("replay does not execute trades"). In the rebuild corpus that is **false**: the
rebuild's `lifecycle_replay` *does* populate `trade_executions` with simulated
lifecycle outcomes (`actual_pnl_r` is 93% non-null; exit_reasons fully distributed).

The blocker therefore stands for a **sharper reason than the plan assumed**: an outcome
*is* available (`actual_pnl_r`), but the ML calibrator is wired to
`counterfactual_pnl_r`, which only the **CounterfactualTracker (v2.11)** populates.
This is not "no data"; it is "the right data for the configured target is absent."

### Triage flag (out of scope for Plan 03 — raised for v2.11 design)
There are now *two* distinct PnL outcomes in the corpus:
- `actual_pnl_r` — executed/simulated lifecycle outcome (populated now)
- `counterfactual_pnl_r` — counterfactual outcome (NULL; needs v2.11)

`training_data.py` is hardcoded to `counterfactual_pnl_r`. Whether ML should instead
train on the now-available `actual_pnl_r` (or both) is a **v2.11 design decision**, not
a Phase 127 action. Surfaced here so it is not lost.

---

## Dependency chain

```
Phase 127 clean corpus (DONE — rebuild)
  → CounterfactualTracker (v2.11) populates trade_frames.counterfactual_pnl_r
    → ml-training calibration retrain (SC-05) reads via training_data.py
      → setup_performance / calibration surfaces refreshed
```

**Corpus is ML-ready now.** Once v2.11 lands and `counterfactual_pnl_r` is populated,
calibration runs with **no second replay** — the clean 1,036,513-row corpus is in place.

## SC-05 status

**DEFERRED to v2.11 — by design, not by failure.** The honest outcome: Phase 127
delivered a clean, integrity-verified corpus but cannot, by construction, support a
calibration retrain until the counterfactual outcome exists. Faking it (e.g., training
on `actual_pnl_r` while calling it calibration, or running on the empty labeled set)
would be a proxy-as-target error.

## setup_performance freshness (informational)

```
setup_performance: rows=0   newest=NULL
```
The table was emptied by the rebuild wipe and is **not refreshed** in Phase 127 (no
retrain). A NULL/empty `setup_performance` is expected this phase; do not mistake a
future non-empty timestamp for a Phase 127 calibration — calibration is gated on v2.11.

---

## Input corpus stats (source: rebuild, 2026-06-17)

| Table / field | Count |
|---------------|-------|
| signal_events | 1,036,513 |
| trade_frames | 1,036,513 |
| trade_executions | 1,063,798 |
| trade_frames.counterfactual_pnl_r non-null | **0** |
| trade_executions.actual_pnl_r non-null | 989,502 |
| setup_performance rows | 0 |
| orphan signal_events / trade_frames | 0 |
