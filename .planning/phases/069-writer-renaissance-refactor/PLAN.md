# Phase 69: Writer Renaissance Refactor — Ship-Ready Foundation

**Status:** Ready | **Start:** 2026-04-13 | **Effort:** 2-3 days (single wave)
**Milestone:** v2.5 — Data Quality & Persistence Reliability
**Dependencies:** Phase 68 complete (hot path shipped)

## Overview

Refactor BaseWriterAgent and all 6 writer agents to eliminate dual patterns, prevent silent data loss, and add comprehensive Renaissance-required observability from day one. Current implementation violates core principles: 2 consumer creation patterns, 6 duplicated `_run()` loops, silent buffer overflows, and insufficient metrics.

**Jim Simons' verdict:** *"It's not in prod? Build it RIGHT. Ship clean. Instrument everything from day one. No technical debt. No process overhead."*

**Rationale:** This is **cold path persistence architecture**, distinct from Phase 68's hot path computation. Pre-production context enables aggressive refactoring without canary/gradual rollout overhead. Deserves its own phase as we're starting Milestone v2.5 (Data Quality & Persistence Reliability).

---

## Goals

1. ✅ **Single consumer creation pattern** — Base class creates consumer from subclass properties
2. ✅ **Single consume loop** — Base class provides `_run()`, subclasses override only for special routing
3. ✅ **Critical alerts on data loss** — Buffer overflow triggers critical severity + backpressure
4. ✅ **Offset commit verification** — Integration tests prove correctness
5. ✅ **Comprehensive observability** — 7 Prometheus metrics (e2e latency, flush latency, commit latency, DB write latency, parse failures, flush errors, commit errors, consumer lag)
6. ✅ **Load-tested reliability** — 1000 msg/sec, zero data loss, p95 < 500ms

---

## Success Criteria

### Functional Requirements
- [ ] All 6 writers use single consumer creation pattern (base class owns consumer)
- [ ] 5/6 writers use base class `_run()` loop (feature_writer keeps 3-loop pattern)
- [ ] Buffer overflow triggers `logger.error()` with `severity="critical"`
- [ ] Integration tests verify offset commits after flush
- [ ] Integration tests verify offset NOT committed on flush failure

### Observability Requirements (Non-negotiable)
- [ ] `e2e_latency_seconds` histogram (consume→commit, 10 buckets: 1ms-5s)
- [ ] `flush_latency_seconds` histogram (DB write, 7 buckets: 1ms-5s)
- [ ] `commit_latency_seconds` histogram (Kafka commit, 7 buckets: 0.1ms-100ms)
- [ ] `db_write_latency_seconds` histogram (per-batch, 7 buckets: 1ms-1s)
- [ ] `parse_failures_total` counter (DLQ rate)
- [ ] `flush_errors_total` counter (retryable failures)
- [ ] `commit_errors_total` counter (commit failures)
- [ ] `consumer_lag` gauge (messages behind head)

### Non-Functional Requirements
- [ ] Throughput > 1000 msg/sec per writer (load test)
- [ ] p95 e2e latency < 500ms (load test)
- [ ] Zero data loss in load test (1000 msg/sec, 10K messages)
- [ ] All tests passing (115 unit + integration + load)

### Renaissance Principles Compliance
- [ ] **Simplicity:** One pattern for consumer creation (no dual patterns)
- [ ] **Modularity:** Base class owns consume loop (no duplication)
- [ ] **Data Quality:** Critical alerts on buffer overflow (no silent loss)
- [ ] **Instrument Everything:** 7 metrics ship from day one
- [ ] **No Process Overhead:** Single-wave execution, no canary/baseline

---

## Artifact Links

**Design Document:** `docs/plans/2026-04-13-basewriter-renaissance-refactor-design.md`

**Implementation Plans (Single Wave):**
- Plan 01: Base class creates consumer (2h)
- Plan 02: Base class provides consume loop (3h)
- Plan 03: Buffer overflow critical alert (1h)
- Plan 04: Comprehensive observability (3h)
- Plan 05: Offset commit integration tests (2h)
- Plan 06: Comprehensive test coverage (3h)
- Plan 07: Update all 6 writers (4h)

**Total:** 18 hours (2-3 days)

---

## Dependencies

- ✅ Phase 68 complete (hot path pipeline hardening shipped)
- ✅ All writers extend BaseWriterAgent (Phase 68.2 complete)
- ✅ Test infrastructure (pytest, integration fixtures)
- ✅ Monitoring infrastructure (Prometheus)

---

## Risks

---

### Risk 1: Breaking Changes to Writers
**Mitigation:** Extensive test coverage (115 passing) + load tests before deployment

### Risk 2: Performance Regression
**Mitigation:** Load tests verify throughput + latency; no prod impact

### Risk 3: Kafka Consumer Complexity
**Mitigation:** Keep current `KafkaConsumerClient` wrapper, just move instantiation to base class

### Risk 4: Feature Writer 3-Loop Pattern
**Mitigation:** Recognize this as the CORRECT pattern for high-throughput writers; don't force into base class `_run()`

---

## Rollback Plan

Pre-production context: Simple revert if tests fail during development.

If issues detected after deployment:
1. `git revert <commit-hash>` — Revert refactor
2. `sudo systemctl restart indicagent-*` — Restart all writers
3. Verify: Tests passing, no errors

**No canary, no gradual rollout — ship when tests pass.**

---

## Execution Timeline

**Day 1: Foundation (6 hours)**
- Plans 01-03: Base class consumer creation + consume loop + critical alerts

**Day 2: Observability + Tests (8 hours)**
- Plan 04: Comprehensive observability (7 Prometheus metrics)
- Plan 05: Offset commit integration tests
- Plan 06: Comprehensive test coverage (extend 115 unit tests)

**Day 3: Migration + Ship (4 hours)**
- Plan 07: Update all 6 writers to use base class
- Run full test suite (unit + integration + load)
- Ship it

**Total:** 18 hours (2-3 days)

---

## Next Steps

1. Execute Plan 01 (Base class creates consumer)
2. Execute Plan 02 (Base class provides consume loop)
3. Execute Plan 03 (Buffer overflow critical alert)
4. Execute Plan 04 (Comprehensive observability — 7 metrics)
5. Execute Plan 05 (Offset commit integration tests)
6. Execute Plan 06 (Comprehensive test coverage)
7. Execute Plan 07 (Update all 6 writers)
8. Run full test suite (unit + integration + load)
9. Ship it
10. Update ROADMAP.md with Phase 69 complete
