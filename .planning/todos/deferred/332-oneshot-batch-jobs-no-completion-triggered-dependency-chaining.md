---
**Created:** 2026-08-16
**Area:** infra
**Type:** architecture_gap
**Priority:** P2
**Effort:** 5-7 days (base-class migration + gate design + systemd changes)
**Benefit:** Closes a real data-integrity gap -- a delayed/failed upstream oneshot job can no
longer silently let a downstream stage compute over stale/partial output on a fixed clock
**Risk:** medium (production systemd unit changes across ~19 services; sequencing error could
stall the weekly ML batch chain)
**Gate:** None (not blocked on a dataset/phase) -- deferred because it's multi-session
production infra work needing a design decision first (base-class standardization order,
gate semantics), not because anything external is missing
---

# 332 - Oneshot batch jobs have zero completion-triggered dependency chaining; BaseBatch adoption far less consistent than assumed

**Filed:** 2026-08-16
**Source:** Sister project SSFI's ADR work (daily Gateway→Calc→Scoring DAG design), which used
indicagent as a reference architecture and found this gap while deciding not to copy it.

## Finding 1: no `OnSuccess=` chaining anywhere, ordering is 100% fixed wall-clock offsets

Confirmed via `grep -rn OnSuccess production/systemd/` -- zero hits across all 34 `.timer`
files. Every oneshot dependency is expressed purely as a hand-picked `OnCalendar=` offset, and
the intent is documented in-line as a comment, not enforced in code:

```
production/systemd/indicagent-ml-orchestrator.timer:2:
  Description=ML Orchestrator Timer -- Monday 04:00 UTC (before data quality at 05:00, discovery at 06:00)
production/systemd/indicagent-ml-discovery.timer:2:
  Description=ML Feature Discovery Timer -- Monday 06:00 UTC (after data quality at 05:00)
```

`ml-orchestrator` (04:00) -> `ml-data-quality` (05:00) -> `ml-discovery` (06:00) ->
`shadow-validator` (07:00) is a real dependency chain (each stage presumably consumes the prior
stage's output) enforced by nothing but four separate `OnCalendar=` lines picked far enough
apart to *usually* leave headroom. A delayed or failed upstream run does not block the next
stage from firing on schedule -- `ml-discovery` fires at 06:00 whether or not `ml-data-quality`
finished, succeeded, or wrote anything.

For a project whose stated design mindset is "data integrity is paramount" and "silent wrong
answers are worse than loud crashes," a downstream stage silently computing over stale or
partial upstream output on a fixed clock is exactly the failure shape those principles exist to
prevent, and today nothing catches it.

## Finding 2: `BaseBatch` adoption is not "one script" bypassing it -- it's the majority of oneshot jobs

SSFI's report characterized this as "one nightly script bypasses it entirely." Actual grep
against every oneshot `.service` unit's `ExecStart` target shows only 2 of ~19 oneshot batch
scripts actually extend `BaseBatch`:

- **Extends `BaseBatch`:** `services/ensemble_trainer.py`, `services/alpha_publisher.py`
- **Extends `BaseDaemon`** (continuous-daemon base, arguably wrong for a `Type=oneshot` unit):
  `services/data_quality_auditor.py`, `services/ml_discovery_analyzer.py`,
  `services/ml_orchestrator.py`
- **Extends neither** (plain script, bare `main()`/`async def main()`, manual
  `JOB_COMPLETED_TOTAL` emission per the D-06 oneshot contract but no shared batch
  infrastructure): `services/ml_training_agent.py`, `services/ml_signal_training_agent.py`,
  `services/hmm_training_agent.py`, `services/feature_validation_agent.py`,
  `scripts/infrastructure/backfill/infrastructure_nightly_backfill.py`,
  `scripts/ops/roll/ops_roll_batch.py`, `services/regime_coverage_auditor.py`,
  `services/feature_parity_auditor.py`, `services/shadow_auditor.py`,
  `services/shadow_validator.py`, `services/signal_probe_auditor.py`,
  `services/confidence_calibration_monitor.py`, `src/intelligence/weight_updater.py`,
  `scripts/ops/memory/ops_batch_agent_memory.py`

CLAUDE.md's Ring/DAG-invariants section never states "every oneshot job must extend
`BaseBatch`" as a hard rule the way it does for `BaseDaemon`/`BaseWriter`/`BaseBatch` write
paths generally -- so this is a real drift-from-intent finding, not a violation of a stated
invariant that CI should already catch. Related open gap already tracked:
[[project_todo149_followup_todos_155_156_157]] notes there's no CI enforcement that a new
service extends the right base class at all.

## Live-state check (2026-08-16, before treating this as urgent)

`systemctl is-enabled`/`is-active` on the chain Finding 1 describes:

```
indicagent-ml-orchestrator.timer:  disabled / inactive
indicagent-ml-data-quality.timer:  disabled / inactive
indicagent-ml-discovery.timer:     disabled / inactive
indicagent-shadow-validator.timer: not-found (unit doesn't even exist under this name)
indicagent-roll-batch.timer:       disabled / inactive
indicagent-nightly-backfill.timer: enabled / active  <- the only one of this cluster actually running
```

This is the exact case CLAUDE.md already warns about ("all systemd timers are confirmed
disabled as of 2026-07-02 -- verify with `systemctl list-timers` before assuming this runs on
schedule"). The 04:00->05:00->06:00->07:00 chain Finding 1 describes is **dormant**, not live --
the silent-stale-cascade risk is currently theoretical. Nobody is exposed to it today. This
downgrades the finding from a live data-integrity gap to real, correctly-scoped architecture
debt -- confirms P2/deferred is the right tier, not P0/ASAP. Do not let this jump the queue
ahead of the actual live bottleneck (`forward_returns` staleness / discovery track, per
`.planning/STATE.md`'s Strategic Plan section) on the strength of "a sister project found it."

## Fix (5-step mandate order, not "wire up OnSuccess=" as the first move)

**1. Question the requirement -- answered, confirmed by project owner 2026-08-16.** Deliberate,
not an oversight: "many of our older services are mothballed for now." Consistent with
CLAUDE.md's own note that `ml-training`/`ml-orchestrator`/`ml-data-quality`/`ml-discovery`/
`roll-batch` being `inactive (dead)` between runs is correct, and with the Strategic Plan fork
moving priority to discovery-track work over this cluster. Fixing this cluster's internal
ordering now would be polishing a pipeline stage that has nothing valid to consume yet --
confirmed dead-end, not a needs-more-info gap anymore.

**2. Delete before adding.** Don't assume all 4 stages still deserve to exist in current form.
The Strategic Plan fork (STATE.md) moved priority to the 5 untested discovery candidates, not
to this weekly ML batch cluster -- re-justify each stage's continued existence against that
before investing in making its scheduling more robust.

**3. Simplify -- this is the actual design call, and it changes the shape of the fix.**
`OnSuccess=` chaining across 4 independently-shaped scripts (2 `BaseBatch`, 1-2 `BaseDaemon`,
rest bare) multiplies the design surface just to re-invent what a single function call already
gives for free: deterministic order and an in-process handle on what the prior stage just wrote.
**Preferred design: collapse the weekly chain into one oneshot orchestrator script that calls
each stage's `run()` sequentially in-process**, asserting a real data-quality postcondition
(row count, freshness, non-null sentinel columns -- not just "exited 0") between each call
before proceeding to the next. This kills both findings from the original report at once:
ordering stops being a clock-offset guess, and "upstream succeeded but wrote bad data" (the
exact question Fable's adversarial pass is stress-testing on SSFI's design) becomes an ordinary
in-process postcondition check instead of a separate cross-process gate-detection system. It
also collapses 4 systemd units into 1, and makes the base-class-consistency question
(Finding 2) moot for this cluster -- one script, one base class, decided once.
Only fall back to systemd-level `OnSuccess=` + external gate-checking if a real reason surfaces
to keep the stages as independently-schedulable units (e.g. wanting `ml-discovery` to run
without `ml-orchestrator` having run same-week) -- no such requirement is evident today.

**4/5. Accelerate/automate only after 1-3**, and only once the stages are back in active use.
Revisit this todo when re-enabling any of the disabled timers above, not before.
