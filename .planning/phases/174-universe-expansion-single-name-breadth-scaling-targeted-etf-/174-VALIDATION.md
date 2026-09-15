---
phase: 174
slug: universe-expansion-single-name-breadth-scaling-targeted-etf
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-15
---

# Phase 174 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 6.0+, `pytest-asyncio` (`asyncio_mode=auto`) |
| **Config file** | `/home/bg/dev/indicagent/pytest.ini` |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_batch_utils.py tests/unit/test_ic_engine_compute_split.py -v` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~120 seconds (full suite) |

---

## Sampling Rate

- **After every task commit:** Run the relevant narrow test file(s) from the Per-Task Verification Map below.
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -q` (must stay green — standing CI gate).
- **Before `/gsd:verify-work`:** Full suite must be green, plus a manual execution-time re-run of the previously-OOM'd 182-symbol `5m/high_bear` cell under the new disk-bound path to empirically confirm D-04's fix before any Russell-3000-scale backfill/compute proceeds.
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | D-04a | — | Pre-flight estimate raises `CellTooLargeError` before any chunk fetch when `len(regime_timestamps) * len(symbol_list) > max_cell_rows` | unit | `pytest tests/unit/test_ic_engine_checkpoint_key.py -k cell_size -x` (new test file likely needed) | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | D-04b | — | `Float32ChunkAccumulator(disk_backed=True)` produces row-identical output to the existing in-RAM mode for the same input chunks | unit | `pytest tests/unit/test_batch_utils.py -k disk_backed -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | D-04c | — | Peak process RSS during a synthetic large-cell accumulation stays bounded (≈ chunk size, not cell size) | integration/performance | `@pytest.mark.performance` test using `resource.getrusage(RUSAGE_SELF).ru_maxrss` around a synthetic accumulation of N chunks | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | D-07a | T-174-01 | `get_active_contracts(dimension="compute")` returns the identical symbol set as today's unparameterized call, for all 231 existing rows | unit/regression | `pytest tests/unit/test_settings_active_contracts.py -x` (file may not yet exist — check at execution time) | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | D-07b | — | `get_active_contracts(dimension="live")` returns empty (no `live_tradeable=true` rows exist yet by design) | unit | same new test file as D-07a | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | D-08 | — | Newly onboarded instrument writes a non-null `instrument_metadata` row, or an explicit skip is logged | unit | new test asserting the onboarding script's write path | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | D-02 | — | Stratified sample RNG is reproducible given the same APR seed | unit | new test seeding `alpha.universe.stratified_sample_random_state` and asserting identical output symbol list across two runs | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | V5 | T-174-02 | New instrument symbols from the IWV holdings file are validated via `qualify_instrument()`'s IBKR contract-resolution path before any DB write — no raw ticker string is inserted directly | unit/integration | new test asserting rejection of a symbol that fails `qualify_instrument()` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] New unit test file for the pre-flight `_check_cell_size` estimate path — no existing test targets this specific code path (`test_ic_engine_compute_split.py` only tests the post-materialization check).
- [ ] `tests/unit/test_batch_utils.py` — add new `disk_backed=True` cases alongside existing `Float32ChunkAccumulator` coverage.
- [ ] Test file (new or extending an existing settings test — grep `tests/unit/` for `get_active_contracts` coverage first) for the `dimension=` parameter and its default-equivalence guarantee.
- [ ] Test for the stratified-sampling script's reproducibility given a fixed APR-seeded RNG.
- [ ] Add a `@pytest.mark.performance`-marked memory-bounded test for ic_engine (marker already registered in `pytest.ini` but not currently exercised for this module).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Full-scale ic_engine run against the disk-bound fix | D-04 | Requires real multi-GB cell materialization and wall-clock/memory observation on the live server — not reproducible in a unit test | Re-run the previously-OOM'd 182-symbol `5m/high_bear` cell after the fix ships; confirm it completes without OOM and peak RSS stays bounded via `iostat`/`pg_stat_activity` per `docs/foundation/performance-investigation-sop.md` |
| IWV holdings file structure (market cap field presence) | D-02 | Requires live inspection of the actual downloaded file, not knowable statically | Download the current IWV holdings CSV, confirm whether market cap is a direct column or must be derived from weight × fund AUM |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
