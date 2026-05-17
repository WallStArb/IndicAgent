---
phase: 085-persistence-writer-migration
verified: 2026-05-17T00:00:00Z
status: gaps_found
score: 8/10 must-haves verified
gaps:
  - truth: "lineage_writer_agent declares payload_model = LineageEvent; malformed lineage events are DLQ'd not dropped"
    status: failed
    reason: "payload_model = LineageEvent is absent from lineage_writer_agent.py. The class has no payload_model class attribute. The file does not import LineageEvent at all."
    artifacts:
      - path: "services/lineage_writer_agent.py"
        issue: "No 'from src.core.ai.lineage import LineageEvent' import. No 'payload_model = LineageEvent' class attribute. _parse_payload still receives dict and still contains the dead manual check (if not payload.get('signal_id') or not payload.get('event_type'): return None)."
    missing:
      - "Add 'from src.core.ai.lineage import LineageEvent' import"
      - "Add 'payload_model = LineageEvent' class attribute on LineageWriterAgent"
      - "Change _parse_payload signature to (self, payload: LineageEvent) -> list | None and delete the manual signal_id/event_type guard"
      - "Add _to_row(self, event: LineageEvent) -> tuple helper before _flush_batch"
      - "Update _flush_batch to use [self._to_row(e) for e in batch] instead of inline dict key construction"

  - truth: "signal_metrics_writer_agent extends BaseWriterAgent; declares payload_model = SignalMetricsEvent; writes in batches via _flush_batch"
    status: failed
    reason: "signal_metrics_writer_agent.py still extends BaseAgent. No BaseWriterAgent import. No payload_model, BATCH_SIZE, or FLUSH_INTERVAL_SECS class attributes. No _flush_batch method. Still uses per-record writes in _run()."
    artifacts:
      - path: "services/signal_metrics_writer_agent.py"
        issue: "class SignalMetricsWriterAgent(BaseAgent) — base class not migrated. Imports BaseAgent from src.core.agent.base, not BaseWriterAgent. No payload_model, BATCH_SIZE, FLUSH_INTERVAL_SECS. Retains manual KafkaConsumerClient. _run() loop writes one record at a time."
    missing:
      - "Replace 'from src.core.agent.base import BaseAgent' with 'from src.core.agent.base_writer import BaseWriterAgent'"
      - "Add 'from src.intelligence.schemas import SignalMetricsEvent'"
      - "Change class declaration to SignalMetricsWriterAgent(BaseWriterAgent)"
      - "Add class attributes: BATCH_SIZE = 50, FLUSH_INTERVAL_SECS = 5.0, payload_model = SignalMetricsEvent"
      - "Implement _topic_name(), _consumer_group, _dlq_topic() abstracts"
      - "Replace _run() with _flush_batch() dispatching to existing _handle_* helpers"
      - "Remove manual KafkaConsumerClient setup from _setup()"
human_verification: []
---

# Phase 085: Persistence Writer Migration — Verification Report

**Phase Goal:** Migrate all persistence writers to Phase 084 base contracts (BaseWriterAgent with payload_model, DLQ routing, named _to_row() helpers). Fix silent data loss in FeatureSnapshotWriterAgent. Make LLM outcome DB errors observable.
**Verified:** 2026-05-17
**Status:** GAPS FOUND — Plans 01/02/03 complete; Plan 04 not executed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | LineageEvent Pydantic model exists in src/core/ai/lineage.py | VERIFIED | class LineageEvent(BaseModel) at line 24; 10 fields; ConfigDict(extra="forbid") |
| 2 | SignalMetricsEvent discriminated union exists in schemas.py with three variants | VERIFIED | MetricsComputedEvent (line 991), ICComputedEvent (line 1019), MetricsDQFailureEvent (line 1040), SignalMetricsEvent union at line 1059 |
| 3 | feature_snapshot_writer_agent _do_flush override deleted | VERIFIED | No _do_flush in file; class inherits BaseWriterAgent directly |
| 4 | llm_writer_service outcome DB errors increment counter, log outcome_write_failed, re-raise | VERIFIED | except Exception as db_exc at line 759; error_count_total.add(1); logger.error("outcome_write_failed") at line 762; bare raise at line 766 |
| 5 | lifecycle_writer_agent uses _exit_to_params() helper | VERIFIED | def _exit_to_params at line 140; called via *self._exit_to_params(entry) at line 171 |
| 6 | ctx_writer_agent uses _to_event_row() and _to_snapshot_row() helpers | VERIFIED | _to_event_row defined at line 191, _to_snapshot_row at line 211; both called at buffer.append() sites |
| 7 | bar_writer_agent uses _bar_to_row() helper | VERIFIED | def _bar_to_row at line 149; _parse_payload returns [self._bar_to_row(bar, base, source)] at line 179 |
| 8 | lineage_writer_agent declares payload_model = LineageEvent | FAILED | No payload_model attribute; no LineageEvent import; dead manual check still present in _parse_payload (line 58) |
| 9 | lineage_writer_agent _parse_payload receives LineageEvent and manual check deleted | FAILED | _parse_payload(self, payload: dict) still has manual if not payload.get("signal_id") guard |
| 10 | signal_metrics_writer_agent extends BaseWriterAgent with payload_model = SignalMetricsEvent | FAILED | class SignalMetricsWriterAgent(BaseAgent) — base class not migrated; no payload_model, no BATCH_SIZE, no _flush_batch |

**Score:** 7/10 truths verified (Plans 01-03 fully verified; Plan 04 not executed)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| src/core/ai/lineage.py | LineageEvent Pydantic model | VERIFIED | class LineageEvent(BaseModel) with 10 fields, ConfigDict(extra="forbid") |
| src/intelligence/schemas.py | SignalMetricsEvent discriminated union | VERIFIED | Three variants + union at lines 991-1062 |
| services/feature_snapshot_writer_agent.py | _do_flush override removed | VERIFIED | No _do_flush in file; inherits BaseWriterAgent |
| services/llm_writer_service.py | outcome error visibility | VERIFIED | except db_exc + log + raise at lines 759-766 |
| services/lifecycle_writer_agent.py | _exit_to_params helper | VERIFIED | Defined + called with spread operator |
| services/ctx_writer_agent.py | _to_event_row and _to_snapshot_row helpers | VERIFIED | Both defined; both called at buffer.append() sites |
| services/bar_writer_agent.py | _bar_to_row helper | VERIFIED | Defined; called in _parse_payload return |
| services/lineage_writer_agent.py | payload_model = LineageEvent + _to_row | FAILED | No import, no payload_model, no _to_row, dead manual check still live |
| services/signal_metrics_writer_agent.py | BaseWriterAgent + batch flush | FAILED | Still extends BaseAgent; no migration |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| lineage.py LineageEvent | lineage_writer_agent.py payload_model | import + class attr | NOT WIRED | File never imports LineageEvent |
| schemas.py SignalMetricsEvent | signal_metrics_writer_agent.py payload_model | import + class attr | NOT WIRED | File never imports SignalMetricsEvent; still uses BaseAgent |
| feature_snapshot_writer | base_writer._do_flush re-raise contract | inheritance after override deleted | WIRED | Override deleted; base contract active |
| llm_writer._process_outcome_message | error counter + structured log + raise | except db_exc block | WIRED | Lines 759-766 correct |
| lifecycle_writer._flush_exit_items | _exit_to_params helper | *self._exit_to_params(entry) | WIRED | Definition at 140, call at 171 |
| ctx_writer._process_message | _to_event_row / _to_snapshot_row | buffer.append(self._to_*()) | WIRED | Both helpers defined and called |
| bar_writer._parse_payload | _bar_to_row helper | return [self._bar_to_row(...)] | WIRED | Line 179 |

### Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| PERSIST-01 (lineage_writer DLQ routing via payload_model) | BLOCKED | payload_model = LineageEvent not set; Plan 04 Task 1 not executed |
| PERSIST-02 (feature_snapshot data loss fix) | SATISFIED | _do_flush override deleted |
| PERSIST-03 (llm_writer outcome error visibility) | SATISFIED | outcome_write_failed log + raise added |
| PERSIST-04 (signal_metrics BaseWriterAgent migration) | BLOCKED | class still extends BaseAgent; Plan 04 Task 2 not executed |
| PERSIST-05 (positional tuple migration) | SATISFIED | All three helpers added and wired |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| services/lineage_writer_agent.py | 58 | Dead manual guard (if not payload.get) that Plan 04 was supposed to delete | Warning | Redundant check; will be removed when Plan 04 is executed |
| services/signal_metrics_writer_agent.py | 178 | Still extends BaseAgent (pre-migration) | Blocker | No batching, no DLQ routing, no payload validation |

### Human Verification Required

None — all checks are programmatic.

## Gaps Summary

Plan 04 (085-04) was not executed. No 085-04-SUMMARY.md exists. The two target files — services/lineage_writer_agent.py and services/signal_metrics_writer_agent.py — are in their pre-Plan-04 state.

**lineage_writer_agent.py:** LineageEvent was created in Plan 01 and is importable, but was never wired into the writer. The writer still validates manually via dict.get() checks. The _to_row() helper was never added. The _flush_batch() still constructs tuples from raw dict keys inline.

**signal_metrics_writer_agent.py:** BaseWriterAgent migration was never performed. The class still extends BaseAgent, uses a manual KafkaConsumerClient, writes per-record in _run(), and has no payload_model, BATCH_SIZE, FLUSH_INTERVAL_SECS, or _flush_batch().

Plans 01, 02, and 03 are fully complete and verified. All 3260 unit tests pass with no regressions.

---

_Verified: 2026-05-17_
_Verifier: Claude (gsd-verifier)_
