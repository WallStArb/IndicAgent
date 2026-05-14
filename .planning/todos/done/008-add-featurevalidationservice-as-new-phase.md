---
created: 2026-04-27T17:32:53.988Z
title: Add FeatureValidationService as new phase
area: planning
files:
  - .planning/ROADMAP.md
  - tools/validate_i6_backtest.py
  - tools/backtest_cross_tf_plugins.py
  - tools/backtest_macro_factors.py
  - src/intelligence/schemas.py
  - services/macro_compute_agent.py
---

## Problem

Phase 64 Plan 04 Task 3 was a human-verify checkpoint: run backtest scripts manually and review IC/p-value results. This is fragile — it requires a human to remember to run scripts, interpret output, and make promotion decisions. The backtest scripts exist but are CLI tools, not a service.

As of 2026-04-27 when Phase 64 closed, the system has ~16 days of live signal_ledger data. The 30-day data gate lifts ~May 10. The validation approach is now superseded by a planned FeatureValidationService.

## Solution

Design and build a FeatureValidationService as a new dedicated phase inserted after Phase 64:

**Service responsibilities:**
- Reads `intelligence_features` + `signal_ledger` to compute IC/p-value per plugin per regime on a schedule (e.g. daily timer)
- Applies D-25 gate: IC > 0.05 AND p < 0.01 (Bonferroni-corrected) AND N >= 30 = VALIDATED
- Exposes results via API endpoint (e.g. `GET /api/validation/results`) and dashboard panel
- Automated promotion decisions: VALIDATED → promote from shadow, KILL → demote to shadow
- Regime-segmented validation (D-26): trending vs ranging breakdown per plugin

**Replaces:**
- Manual `tools/backtest_cross_tf_plugins.py` (ad-hoc CLI)
- Manual `tools/backtest_macro_factors.py` (ad-hoc CLI)
- Phase 64-04 Task 3 human-verify checkpoint

**Design reference:** Renaissance principle "Let the system run" — automated validation gate, no human judgment required once IC > 0.05, p < 0.01.

**Data gate:** Requires 30+ signal_ledger outcomes per plugin. ~May 10 is when this becomes actionable for Phase 64 plugins (yield curve, FTQ, 5 cross-TF plugins).

## Context

- Phase 64-04 Task 3 was explicitly left as a human-verify checkpoint in the SUMMARY
- Backtest infrastructure exists: `tools/validate_i6_backtest.py` has D-25 ValidationResults dataclass with VALIDATED/TWEAK/KILL decisions — service just needs to wrap this in a timer agent + DB persistence + API
- New phase should be numbered and inserted into ROADMAP.md after Phase 64
