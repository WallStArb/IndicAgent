# Phase 52.1: Wiring Fixes + Doc Naming

**Status:** 📋 Planned

**Milestone:** v2.1 Data Foundation & Signal Confidence

**Dependencies:** Phase 48 completion (done)

---

## Goals

Fix active import crashes and silent metric gaps left by the March 2026 agentic DAG sprint. These are production bugs — services that reference `topic_feature_processed` (a topic that no longer exists) crash at startup with `ImportError`. Additionally wire Prometheus metrics that are defined but never published, and fix hardcoded topic strings in the parity-auditor plan doc so implementation agents don't replicate the pattern.

**No new features. No architecture changes. Fix what's broken.**

---

## Success Criteria

1. `from services import feature_compute_agent` succeeds without `ImportError`
2. `from services import feature_writer_service` succeeds without `ImportError`
3. `feature_writer_service` subscribes to `topic_intelligence_journal` (not `topic_feature_processed`)
4. `datetime.now()` → `datetime.now(UTC)` in `indicator_compute_agent.py` and `intelligence_compute_agent.py`
5. `persistence_batch_latency` and `persistence_consumer_lag` are emitted in `feature_writer_service.py` and `llm_writer_service.py` hot paths
6. All code examples in `parity-auditor-agent.md` use `topic_audit()` / `topic_system_events()` instead of hardcoded strings
7. All unit tests pass: `.venv/bin/pytest tests/unit/ -q`

---

## Tasks

### Task 1: Fix `topic_feature_processed` crash — `feature_compute_agent.py`

**TDD:**
- [ ] Write test: `tests/unit/test_stream_keys_imports.py`
  ```python
  def test_topic_feature_processed_does_not_exist():
      import src.core.stream_keys as sk
      assert not hasattr(sk, "topic_feature_processed")

  def test_topic_intelligence_journal_exists():
      from src.core.stream_keys import topic_intelligence_journal
      assert topic_intelligence_journal("development") == "development.intelligence.journal"

  def test_topic_audit_exists():
      from src.core.stream_keys import topic_audit
      assert topic_audit("development") == "development.audit"
  ```
  Run: `.venv/bin/pytest tests/unit/test_stream_keys_imports.py -v` → FAIL (`topic_audit` missing)

- [ ] Add `topic_audit` to `src/core/stream_keys.py` if not already present (it may already be there — check line 160)
  Run tests → PASS

- [ ] In `services/feature_compute_agent.py`:
  - Remove import: `from src.core.schemas.intelligence_journal import IntelligenceJournal, ProvenanceChain`
  - Remove from stream_keys import: `topic_feature_processed`
  - Remove the dead publication block (lines ~970–988): the entire `try:` block building `feature_journal` and publishing to `topic_feature_processed`

- [ ] Verify import succeeds:
  ```bash
  .venv/bin/python -c "import sys; sys.path.insert(0, '.'); from services import feature_compute_agent; print('OK')"
  ```

### Task 2: Fix `topic_feature_processed` crash — `feature_writer_service.py`

**TDD:**
- [ ] Write test: `tests/unit/test_feature_writer_imports.py`
  ```python
  def test_feature_writer_imports_cleanly():
      import sys, types
      sys.path.insert(0, '.')
      from services import feature_writer_service
      assert hasattr(feature_writer_service, 'FeatureWriterService')
  ```
  Run: `.venv/bin/pytest tests/unit/test_feature_writer_imports.py -v` → FAIL

- [ ] In `services/feature_writer_service.py`:
  - Replace `topic_feature_processed` import with `topic_intelligence_journal`
  - In `_start_consumer()`: change subscription from `topic_feature_processed(self._env_name)` to `topic_intelligence_journal(self._env_name)`
  - At line ~640: replace `topic_intelligence_record(self._env_name)` → `topic_intelligence_journal(self._env_name)`
  - At line ~671: fix `feature_processed_topic` NameError — update routing condition to match `topic_intelligence_journal(self._env_name)`
  - Update docstring/comments from "intelligence.record" → "intelligence.journal"

- [ ] Run test → PASS
- [ ] Run: `.venv/bin/python -c "import sys; sys.path.insert(0, '.'); from services import feature_writer_service; print('OK')"`

### Task 3: Fix naive UTC datetimes

**Files:** `services/indicator_compute_agent.py` lines 204, 616 | `services/intelligence_compute_agent.py` lines 92, 568

- [ ] Write test (characterization):
  ```python
  # tests/unit/test_utc_awareness.py
  import ast, pathlib
  def _find_naive_now(path):
      src = pathlib.Path(path).read_text()
      return "datetime.now()" in src and "datetime.now(UTC)" not in src
  def test_indicator_compute_agent_no_naive_now():
      assert not _find_naive_now("services/indicator_compute_agent.py")
  def test_intelligence_compute_agent_no_naive_now():
      assert not _find_naive_now("services/intelligence_compute_agent.py")
  ```
  Run → FAIL (both files have `datetime.now()`)

- [ ] In `indicator_compute_agent.py`: replace `datetime.now()` → `datetime.now(UTC)` at lines 204 and 616
- [ ] In `intelligence_compute_agent.py`: replace `datetime.now()` → `datetime.now(UTC)` at lines 92 and 568
- [ ] Verify `UTC` is imported from `datetime` in both files (should already be there)
- [ ] Run test → PASS

### Task 4: Wire `persistence_batch_latency` and `persistence_consumer_lag` metrics

**Files:** `services/feature_writer_service.py`, `services/llm_writer_service.py`

- [ ] Grep for how these metrics are defined in `src/observability/metrics.py`
- [ ] In `feature_writer_service.py`: record `persistence_batch_latency` at end of each batch write; record `persistence_consumer_lag` using consumer lag from aiokafka consumer
- [ ] In `llm_writer_service.py`: same pattern
- [ ] Write test verifying the metrics module is imported and the labels are called:
  ```python
  def test_feature_writer_records_batch_latency():
      import ast, pathlib
      src = pathlib.Path("services/feature_writer_service.py").read_text()
      assert "persistence_batch_latency" in src
      assert "persistence_consumer_lag" in src
  ```
- [ ] Run test → PASS

### Task 5: Fix hardcoded topic strings in `parity-auditor-agent.md`

- [ ] In `docs/plans/2026-03-25-parity-auditor-agent.md`: update all code examples where `"development.audit"` is used as a hardcoded string passed to Kafka producer/consumer (not in test assertions) → replace with `topic_audit(settings.env_name)`
- [ ] Replace `"development.system.events"` in code examples → `topic_system_events(settings.env_name)`
- [ ] Leave test assertions that verify the resolved string value unchanged (those are correct)

### Task 6: Full test suite + lint

- [ ] `.venv/bin/pytest tests/unit/ -q` — all pass, no regressions
- [ ] `.venv/bin/ruff check . --fix`
- [ ] `.venv/bin/black .`
- [ ] Commit: `fix(wiring): remove topic_feature_processed crash, fix UTC, wire persistence metrics`

---

## Source Plans

- `docs/plans/2026-03-25-dual-write-parity-audit.md` (Task 1 — wiring fixes section)
- `docs/plans/2026-03-25-parity-auditor-agent.md` (hardcoded topic fix)
- Memory: naming violations audit 2026-03-26
