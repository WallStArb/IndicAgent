---
status: pending
priority: P2
filed: 2026-07-20
source: user question mid-session ("is our code enforcing our reuse of base classes with the
  shared observability, tracability, metrics, guardrails etc"), 2026-07-20 -- direct follow-up
  to [[156-otel-span-coverage-gap-v3-pipeline]], investigated same session.
---

# No mechanical check enforces base-class reuse (BaseDaemon/BaseWriter/BaseBatch) or observability wiring -- convention only

**Items 1-2 CLOSED 2026-07-31** -- `tests/unit/test_service_base_class_compliance.py` (static
ast-based check: every daemon-shaped class in `services/*.py` -- has an async `run`/`_run`
method, or its `_to_snake_case()`-derived agent_id is a key in `service_auditor.py`'s
`_AGENT_ID_TO_UNIT` -- must reach `BaseDaemon`/`BaseWriter`/`BaseBatch` via a static
class-name -> base-name graph walk over `src/` + `services/`, equivalent to an MRO check
without importing anything) and `tests/unit/test_no_prometheus_client_import.py` (grep-based,
matching `test_market_data_ohlcv_boundary.py`'s allow-list pattern) added, both passing clean
against current code -- zero allow-list entries needed for either (the base-class check found
30 daemon-shaped candidates, all compliant, including `AlphaSwarm`/`NarrativeSwarm` which only
resolve through the transitive `BaseGroupCoordinator -> BaseDaemon` chain, not a direct base --
verified the graph-walk is load-bearing, not a check that trivially passes on direct bases
only). No ruff `TID251`/banned-api config existed to reuse (checked `pyproject.toml`), so the
prometheus_client check is grep-based like the reference test, not a ruff rule. Item 3 (spans)
remains open, gated on [[156-otel-span-coverage-gap-v3-pipeline]] resolving its own step 2
first.

## Problem

Investigated what's actually enforced vs. what's convention-only for shared infrastructure
reuse. Findings, all verified directly against the live repo (not assumed from docs):

**Mechanically enforced today** (`.git/hooks/pre-commit`, 9 checks, blocking on every commit):
plugin class/file naming, I7 `regime_type` ClassVar validation, ruff, black, duplicate test
names across a directory, a Ring 0 import-boundary check (`src/core`/`src/observability` must
not import domain layers), glossary banned-synonym enforcement, and a counterfactual-ledger
anti-duplication check. Separately, CI-enforced grep-based allow-list tests exist for specific
tables: `tests/unit/test_market_data_ohlcv_boundary.py`, `test_forward_return_session_boundary.py`,
`test_regime_boundary_churn_check.py`, `tests/unit/core/test_bar_accumulator_session_boundary.py`.

**NOT enforced anywhere** -- verified by direct search, no test/hook/lint rule found:

1. **Base-class adoption itself.** Nothing checks that a new file under `services/` actually
   extends `BaseDaemon`/`BaseWriter`/`BaseBatch` instead of hand-rolling its own asyncio loop.
   A new service that skips this silently loses all 5 mandatory OTel signals
   (`agent_last_message_timestamp_seconds`, `agent_crash_total`, `agent_dlq_total`,
   `watchdog_notify_total`, `watchdog_notify_suppressed_total`) with zero CI failure.
2. **Span usage** (see [[156-otel-span-coverage-gap-v3-pipeline]]) -- nothing requires
   `observed_span(...)` anywhere. This is exactly how todo 149's `BarAuditor` price-sanity
   audit task shipped this same session with metrics but zero tracing.
3. **"Never import `prometheus_client`"** (CLAUDE.md's explicit rule) -- convention only, no
   ruff banned-import rule (`grep` of `pyproject.toml`/`ruff.toml`/`.ruff.toml` for a
   banned-api config found nothing) and no grep-test. Currently zero real violations (checked
   directly -- the only 3 hits in the whole codebase are comments explaining the historical
   migration away from it, not live imports), but nothing would catch a future regression
   except a human reviewer noticing in review.

The existing boundary-test pattern (allow-list dict + regex scan of changed/all files,
CI-blocking) already proves this project knows how to build this kind of guardrail -- it's just
narrowly applied to a few specific tables so far, not generalized to base-class/observability
conformance.

## Fix

Not scoped in detail here (this is a capture, not a plan). Candidate shape, reusing the
existing boundary-test pattern:

1. A new `tests/unit/test_service_base_class_compliance.py`: scan `services/*.py` for
   top-level daemon-shaped classes (heuristic: has a `_run`/`run` async method, or is
   referenced in `service_auditor.py`'s `_DAG_ORDER`/`_AGENT_ID_TO_UNIT`) and assert each one's
   MRO includes `BaseDaemon`, `BaseWriter`, or `BaseBatch` -- allow-list any deliberate
   exception with a reason, matching the `market_data_ohlcv` boundary test's own convention.
2. A banned-import ruff rule (or the same grep-test pattern) for `prometheus_client` -- cheap,
   mechanical, currently-zero-cost to add since there are no real violations to grandfather in.
3. Whether to require spans is really [[156]]'s decision (step 2 there: should `BaseDaemon`
   provide a default span automatically, closing this gap architecturally rather than via a
   test that nags after the fact) -- resolve 156 first, this todo's item 1/2 don't depend on it.

## Sizing

Small-to-medium -- the boundary-test pattern to copy already exists and is proven; the main
work is defining the "which classes should extend which base" heuristic precisely enough to
avoid false positives on legitimately-exempt files (oneshot `_agent.py` scripts, thin CLI
wrappers, etc. -- see CLAUDE.md's own documented exceptions for prior art on what's exempt).

## References

- `.git/hooks/pre-commit` -- the 9 existing mechanically-enforced checks, and the general
  shape/discipline this project already applies elsewhere
- `tests/unit/test_market_data_ohlcv_boundary.py` -- the allow-list + regex-scan pattern to
  reuse for base-class and banned-import checks
- `src/core/agent/base.py` -- `BaseDaemon`, the 5 mandatory metrics signals defined here
- [[156-otel-span-coverage-gap-v3-pipeline]] -- the specific tracing-coverage gap this todo's
  investigation grew out of; resolve that one's step 2 (should spans be automatic) before
  building this todo's compliance test around span requirements specifically
