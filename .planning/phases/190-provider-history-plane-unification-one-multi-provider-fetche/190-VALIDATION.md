---
phase: 190
slug: provider-history-plane-unification-one-multi-provider-fetche
status: final
nyquist_compliant: true
wave_0_complete: false
created: 2026-10-09
---

# Phase 190 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 (`.venv/bin/pytest`) |
| **Config file** | repo-level pytest config; unit tests are CI-clean (no DB, no network) |
| **Quick run command** | `.venv/bin/pytest tests/unit/scripts/test_fetch_queue.py -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~190 seconds |

---

## Sampling Rate

- **After every task commit:** Run the touched module's quick command from the Per-Task map
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 190 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 190-01-T1 | 01 | 1 | P190-conformance | T-190-01 | verdict/budget/page types pinned | unit | `.venv/bin/pytest tests/unit/providers/test_history_conformance.py -q` | ❌ W0 (190-01 T1) | ⬜ pending |
| 190-01-T2 | 01 | 1 | P190-conformance | — | conformance cases over fake + IBKR leaves | unit | `.venv/bin/pytest tests/unit/providers/ -q` | ❌ W0 (190-01 T1) | ⬜ pending |
| 190-01-T3 | 01 | 1 | P190-boundary | — | protocol-not-leaf import fence | unit (grep) | `.venv/bin/pytest tests/unit/test_provider_leaf_boundary.py -q` | ❌ W0 (190-01 T3) | ⬜ pending |
| 190-02-T1 | 02 | 1 | P190-migration | T-190-03 | additive provider columns applied live; parity-before sanity capture | live psql + unit | `psql -f 464... && .venv/bin/pytest tests/unit/ -q` | ❌ W0 (190-02 T2) | ⬜ pending |
| 190-02-T2 | 02 | 1 | P190-migration | T-190-03 | PK shapes, grants, floor seeds, labeling rule (465 written, UN-applied until 190-06) | unit (contract) | `.venv/bin/pytest tests/unit/test_provider_history_migration_contract.py -q` | ❌ W0 (190-02 T2) | ⬜ pending |
| 190-02-T3 | 02 | 1 | P190-ledger / P190-writers | T-190-02, T-190-02b, T-190-04 | provider-parameterized single writer, OLD conflict target live until the 190-06 flip; CoverageDelta provider threading | unit + integration (465 rollback fixture) | `.venv/bin/pytest tests/unit/test_ohlcv_coverage_writer_boundary.py tests/unit/scripts/test_intraday_persist.py tests/integration/test_ohlcv_coverage_atomic_write.py -q` | ✅ | ⬜ pending |
| 190-03-T1 | 03 | 2 | P190-queue | T-190-01 | per-provider plan + validation | unit | `.venv/bin/pytest tests/unit/scripts/test_fetch_queue.py -q` | ✅ | ⬜ pending |
| 190-03-T2 | 03 | 2 | P190-queue | T-190-01 | per-provider floors, failures, items | unit | `.venv/bin/pytest tests/unit/scripts/test_fetch_queue.py tests/unit/scripts/test_empty_history.py -q` | ✅ | ⬜ pending |
| 190-03-T3 | 03 | 2 | P190-queue | T-190-05 | policy read gate | unit + live dry run | `.venv/bin/pytest tests/unit/scripts/test_fetch_queue.py -q` | ✅ | ⬜ pending |
| 190-04-T1..T3 | 04 | 3 | P190-fetcher | T-190-06, T-190-07 | vendor-blind loop, registry dispatch | unit | `.venv/bin/pytest tests/unit/scripts/ -q` | ✅ | ⬜ pending |
| 190-05-T1..T2 | 05 | 4 | P190-fetcher / P190-lock | T-190-02, T-190-08 | identity freeze, rename integrity, thin wrapper keeps the live unit fetchable, boundary allow-list entry updated | unit + grep | `.venv/bin/pytest tests/unit/ -q` | ✅ | ⬜ pending |
| 190-06-T1 | 06 | 5 | P190-parity | — | 526 correctness bar: back-to-back old-worktree vs new-HEAD dry-run diff on a quiescent DB | measured dry-run | `test -s parity-old.tsv && test -s parity-new.tsv && test ! -e /tmp/indicagent-190-parity` | ❌ (captured in-task) | ⬜ pending |
| 190-06-T2 | 06 | 5 | P190-migration | T-190-09, T-190-10, T-190-13 | 465 apply + writer conflict-target flip in one breath with the drain stopped; cutover restart health; race-free started_at check | live | `systemctl is-active ...timer` + `\d ohlcv_coverage` PK grep + started_at > CUT_TS check | ✅ (live) | ⬜ pending |
| 190-07-T1..T3 | 07 | 6 | P190-fetcher / P190-ledger | T-190-11 | glossary/gotchas/todo registry | grep | `grep -c` per plan task | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/providers/test_history_conformance.py` — conformance skeleton + fake-leaf fixture mechanism (190-01 Task 1)
- [ ] `tests/unit/test_provider_leaf_boundary.py` — provider import-boundary fence, allow-list seeded from live grep (190-01 Task 3)
- [ ] `tests/unit/test_provider_history_migration_contract.py` — source-level contract tests for migrations 464 + 465 (190-02 Task 2)

Existing infrastructure covers all other phase requirements (test_fetch_queue.py, test_ibkr_history_fetcher.py family, coverage writer boundary/contract tests, single-writer registry).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Drain resumes under the unified fetcher with bars landing | P190-parity | live systemd + IBKR gateway state | 190-06 Task 2 steps; owner confirms at the blocking checkpoint |
| Real IBKR leaf fetch behavior through the new protocol surface | P190-conformance | unit tests are gateway-free by design | the drain's own post-cutover runs are the behavioral proof; existing item-mechanics suites cover the primitives |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 190s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planner 2026-10-09
