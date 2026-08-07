---
status: closed
priority: P2
filed: 2026-07-20
closed_date: 2026-08-07
source: user question mid-session ("do we have end to end traceability in v3? otel wired
  right in all base classes?"), 2026-07-20 -- prompted by todo 149's final-review fix adding
  OTel metrics (not spans) to BarAuditor's new price-sanity audit task.
---

# OTel span coverage has real gaps in the v3.0 critical path -- metrics are universal, traces are not

## Problem

Metrics (counters/histograms/gauges) ARE universal: every `BaseDaemon` subclass auto-inherits
5 mandatory signals (`agent_last_message_timestamp_seconds`, `agent_crash_total`,
`agent_dlq_total`, `watchdog_notify_total`, `watchdog_notify_suppressed_total`) with zero
per-service code, and `init_otel_providers()` hard-fails the service if the metrics collector
is unreachable (deliberate -- traces degrade gracefully, metrics do not, per
`src/observability/otel.py`'s own docstring).

Distributed **tracing** (spans) is a different story -- it is entirely opt-in, not automatic:

- No auto-instrumentation libraries are used anywhere (`grep` for `AsyncPGInstrumentor`/
  `AioKafkaInstrumentor`/etc. in `src/observability/otel.py` returns nothing) -- every span in
  the codebase is a manual `observed_span(...)` call (`src/observability/spans.py`).
- Only 6 files actually create spans: `feature_vector_pipeline.py` (2), `feature_vector_writer.py`
  (2), `forward_return_writer.py` (6), `ic_engine.py` (4), plus `llm_writer.py`, `context_writer.py`.
- **Two load-bearing v3.0 critical-path stages have zero spans:** `ensemble_trainer.py` and
  `alpha_publisher.py` -- the latter is the SOLE writer to `alpha_events`, the final output of
  the entire `IBKR -> FeatureVectorPipeline -> ... -> alpha_publisher -> alpha_events` DAG. A
  slow or silently-degraded `alpha_publisher` write is invisible in any trace view today.
- `BarAuditor` (`services/bar_auditor.py`) also has zero spans, including the price-sanity
  audit task todo 149 just added -- it got metrics (this session's final-review fix) but no
  span wrapping the DB round-trip.

What DOES work end-to-end: W3C trace-context propagation across Kafka is genuinely wired at
the transport layer -- `KafkaProducerClient.publish()` calls `inject(carrier)` before every
send, and `KafkaConsumerClient`'s consume loop calls `extract(carrier)` and attaches the
context (`src/core/kafka_utils.py`). This means wherever two services on either side of a
Kafka hop BOTH happen to create spans, those spans correctly link into one trace. But since
most services don't create spans at all, most of the DAG stays trace-invisible even though the
propagation plumbing to connect it is already universally present.

## Fix

Not scoped in detail here (this is a capture, not a plan) -- but the shape is:
1. Add `observed_span(...)` wrapping to `ensemble_trainer.py` and `alpha_publisher.py` first --
   these are the two gaps directly on the v3.0 measurement/decision-integrity critical path
   (Invariant 1's executable-return chain terminates here).
2. Decide whether `BaseDaemon`/`BaseWriter`/`BaseBatch` should provide a default span wrapping
   their main per-cycle/per-batch method automatically (closing the gap the same way the 5
   mandatory metrics signals are automatic), rather than requiring each service to remember to
   opt in -- this would prevent future services (like `bar_auditor.py`'s price-sanity task) from
   shipping with metrics but no spans.
3. Audit remaining services (gap detection's own `_run_audit`, `ml_*` batch services, etc.) for
   spans once the two critical-path gaps are closed.

## Sizing

Medium -- no new infrastructure needed (propagation already works, `observed_span` helper
already exists and is proven in 6 files); the work is applying the existing pattern to the
missing call sites, plus the base-class design decision in step 2 above.

## Step 1 done 2026-07-29

Wrapped `ensemble_trainer.py`'s and `alpha_publisher.py`'s top-level `execute()` in
`observed_span("ensemble_trainer.execute", ...)` / `observed_span("alpha_publisher.execute", ...)`
(the async `src/observability/spans.py` variant -- both are asyncpg-based `BaseBatch`
subclasses, not the sync psycopg2 pattern `ic_engine.py`/`forward_return_writer.py` use for
their `ProcessPoolExecutor` workers). Both already call `init_otel_providers(...)` in `main()`
before `.run()` invokes `execute()`, so `observed_span`'s default tracer resolution
(`trace.get_tracer("indicagent")`, used when no explicit `tracer=` is passed -- `BaseBatch`
has no `self.tracer` attribute unlike `BaseDaemon`) picks up the real configured provider, not
a no-op. `weight_version_override` attached as a span attribute on both (empty string when
unset, matching this project's existing null-safety convention for OTel attributes). Both spans
wrap the whole `_execute_inner` call including the existing manifest-error-recording try/except,
so a mid-run exception still gets recorded on the span (via `observed_span`'s own
`record_exception`/ERROR-status handling) in addition to the manifest write. No new span-testing
infrastructure added -- none of the 6 already-instrumented files (`feature_vector_pipeline.py`,
`feature_vector_writer.py`, `forward_return_writer.py`, `ic_engine.py`, `llm_writer.py`,
`context_writer.py`) have one either; consistent with the existing pattern, not a gap unique to
this change. Full `tests/unit/` suite green.

**Steps 2 and 3 still open** — the base-class default-span-wrapping design decision (should
`BaseDaemon`/`BaseWriter`/`BaseBatch` auto-wrap their main per-cycle/per-batch method the same
way the 5 mandatory metrics signals are automatic?) and the broader remaining-services audit
(gap detection's `_run_audit`, `ml_*` batch services, `bar_auditor.py`'s price-sanity task,
etc.) are real, separate scoping questions, not mechanical follow-through from step 1 — kept
open rather than attempted in the same pass.

## Step 2 decided and done 2026-07-31

Investigated whether `BaseDaemon`/`BaseWriter`/`BaseBatch` could auto-wrap spans the same
mechanical way the 5 metrics signals are automatic. Verdict: **not uniformly** — `BaseDaemon`
itself can't, because its `_run()` is abstract and runs for the life of the process (often
hours/days, consuming an unbounded Kafka stream inside a subclass-owned loop) with no per-unit
boundary the base class can see; a single span wrapping the whole call would never close until
shutdown, which is an anti-pattern for tracing backends, not a useful signal.

`BaseWriter` turned out to **already have this solved**, just not documented as such:
`_do_flush()` (`base_writer.py:270`) already wraps every `_flush_batch()` call in
`writer.flush`, and `_run()`'s default consume loop already wraps every message in
`writer.process_message` (`base_writer.py:316`) — both base-class methods, automatic for any
subclass today. Nothing needed changing here; this todo's own step-1 investigation undercounted
coverage by only grepping for direct `observed_span` call sites, missing that `BaseWriter`
wraps via `self.tracer.start_as_current_span(...)` directly instead.

`BaseBatch` was the real gap — `execute()` (the one bounded per-run unit, structurally
identical to what `BaseWriter._flush_batch` already gets) had zero automatic span coverage.
Fixed: `BaseBatch.run()` (`src/core/agent/base_batch.py`) now wraps the `execute(pool)` call in
`observed_span(f"{self.job_name}.execute", **self._span_attrs())` — `_span_attrs()` is a new
overridable hook (default `{}`) letting subclasses attach extra span attributes without needing
their own `observed_span` call. This closes the gap for all 8 live `BaseBatch` subclasses at
once: `ensemble_trainer.py`, `alpha_publisher.py` (already had manual spans — now redundant,
removed, with their `weight_version_override` attribute moved to `_span_attrs()` so no
information is lost), plus 6 subclasses that had **zero** span coverage until now:
`cross_sectional_spread_tracker.py`, `counterfactual_tracker.py`, `ensemble_ic_engine.py`,
`alpha_scorer.py`, `alpha_frame_writer.py`, `tag_calibrator.py`. None of these 8 were running
live at implementation time (all are oneshot batch jobs, not daemons); the corpus-critical
`ic_engine.py` is NOT a `BaseBatch` subclass yet (still the procedural script todo 009 Part B
tracks promoting) so this change does not touch it or risk the in-flight corpus rebuild.
`tests/unit/ -q` green (105 tests across the 3 directly-touched files, full suite unaffected).

**Resolves 157 item 3's blocker** — see that todo for the resulting compliance-test scope.

**Step 3 (broader remaining-services audit) done 2026-08-07.** Audited every `_run_audit`-
shaped `BaseDaemon` service in `services/`: `bar_auditor.py`, `signal_auditor.py`,
`compression_auditor.py`, `ml_orchestrator.py`, `ml_discovery_analyzer.py`, plus the
non-`BaseDaemon` oneshot scripts `confidence_calibration_monitor.py`, `shadow_auditor.py`,
`feature_parity_auditor.py`. Only 2 are actually v3.0-relevant (this todo's own title/scope):
`bar_auditor.py` (audits `market_data_ohlcv`, the live v3.0 OHLCV table — explicitly named in
this todo's original problem statement) and `compression_auditor.py` (generic hypertable
compression auditor, `active running` at audit time). Both had zero span coverage on their
audit-cycle methods (`_run_audit()`, plus `bar_auditor.py`'s `_run_price_sanity_audit()`) --
wrapped both in `observed_span()` using `self.tracer` (`BaseDaemon` provides it, per the
`src/core/agent/base.py` reference below), same pattern as `feature_vector_writer.py`'s
`writer.flush` span. Tests green (`test_bar_auditor.py`, `test_bar_auditor_gaps.py`,
`test_compression_auditor.py`).

The other 6 services all read v2.x-archived tables (`intelligence_features`/`signal_ledger`/
`signal_events`/`shadow_registry` -- confirmed dead per CLAUDE.md's Architecture section) --
deliberately skipped, not the "v3.0 pipeline" this todo is titled about. This todo's own
explicit scope (steps 1-3 as originally written) is now fully closed.

**Separate, real gap found while doing this audit, NOT part of this todo's scope**:
`regime_writer.py`/`backfill_feature_factory.py` (procedural scripts, not `BaseDaemon`) also
have zero span coverage -- but that's exactly todo 009 Part B's scope (promote both to
`BaseBatch`, which gets the automatic `execute()` span for free, same as `ensemble_trainer.py`/
`alpha_publisher.py`). Not duplicated here; see todo 009.

## References

- `src/observability/spans.py` -- `observed_span()`, the existing pattern to reuse
- `src/observability/otel.py` -- `init_otel_providers()`, metrics-hard-fail/traces-soft-fail
  asymmetry, confirms no auto-instrumentation is configured
- `src/core/kafka_utils.py` -- `KafkaProducerClient.publish()`/`KafkaConsumerClient`, where
  W3C traceparent inject/extract already happens universally
- `src/core/agent/base.py` -- `BaseDaemon.__init__`'s `self.tracer = get_tracer(name)` (tracer
  is available on every daemon instance, but nothing forces using it)
- CLAUDE.md's "OTel Health Contract" section -- documents the 5 mandatory METRICS signals;
  has no equivalent mandatory-spans contract today
