---
status: pending
priority: P1
filed: 2026-11-24
source: indicagent-3d family-order note, lead ruling 2026-11-24
---

# No writer records IC sweep cells as counted attempts

## What

E21 says every measured cell is a `research_run` evidence attempt and no real-data sweep runs until the writer exists. `services/ic_measure.py` writes only `feature_ic_scores`; `research_run_series` is written only by the runner ledger. Without a writer the sweep is an uncounted look.

## Done when

A single writer (one writer per table) records each measured cell as a counted attempt with its series, spec and code key, so StepM sees the cells; the IC pass stays a proposer and any family it prompts carries `informed_by`. Prerequisite of the first real-data IC sweep, with 670 and the 666 ledger decision.
