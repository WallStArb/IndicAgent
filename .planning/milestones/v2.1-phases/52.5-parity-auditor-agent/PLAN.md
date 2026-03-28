# Phase 52.5: Parity Auditor Agent

**Status:** 📋 Planned

**Milestone:** v2.1 Data Foundation & Signal Confidence

**Dependencies:** Phase 52.3 (shadow table + FeatureSnapshotWriterAgent running, rows in feature_snapshots_shadow)

---

## Goals

Build `ParityAuditorAgent` — an autonomous, periodic comparison engine that validates `feature_snapshots_shadow` against `intelligence_features` with no human-in-the-loop. When every active (symbol, tf) pair achieves `CERTIFICATION_THRESHOLD` consecutive clean comparison cycles, the agent self-certifies and publishes `SHADOW_PARITY_CERTIFIED` to the system events topic. This is the automated gate for primary-write cutover.

**Renaissance principle:** Earn the right through proof. Automate the measurement so humans only see results, not process.

---

## Success Criteria

1. `ParityAuditorAgent` runs as independent process (not in Kafka hot-path — timer-based, every 5 min)
2. Compares `intelligence_features` vs `feature_snapshots_shadow` per (symbol, tf) for last N bars
3. Violations stored in `feature_parity_violations` with field-level granularity (which column diverges)
4. Per-(symbol, tf) match rate emitted as Prometheus metric: `parity_match_rate{symbol, tf}`
5. After `CERTIFICATION_THRESHOLD` consecutive clean cycles per every active (symbol, tf) → publishes `SHADOW_PARITY_CERTIFIED` event to `topic_system_events`
6. Auditor failure never affects primary write path (runs in separate process)
7. `indicagent-parity-auditor.service` systemd unit starts cleanly
8. Unit tests cover: comparison logic, certification counter, violation routing, threshold gate

---

## Architecture

```
[timer: every 5 min]
    ↓
ParityAuditorAgent._compare_cycle()
    ↓
ParityRepository.fetch_window(intelligence_features, last N bars, all symbols/tfs)
ParityRepository.fetch_window(feature_snapshots_shadow, same window)
    ↓
_compare_rows(primary, shadow) → list[FieldViolation]
    ↓
ParityRepository.insert_violations(violations)         # always store
    ↓
_update_certification_state(symbol, tf, violations)    # track consecutive clean cycles
    ↓
if certified: KafkaProducer.publish(SHADOW_PARITY_CERTIFIED, topic_system_events)
```

---

## Tasks

### Task 1: `ParityRepository` — read-side queries

**File:** `src/persistence/repository/parity_repository.py`
**Test:** `tests/unit/test_parity_repository.py`

- [ ] Write failing tests (see `docs/plans/2026-03-25-parity-auditor-agent.md` Task 1 for full spec):
  ```python
  from src.persistence.repository.parity_repository import ParityRepository

  def test_repository_exists():
      repo = ParityRepository.__new__(ParityRepository)
      assert repo is not None

  def test_has_fetch_window():
      assert hasattr(ParityRepository, "fetch_window")

  def test_has_insert_violations():
      assert hasattr(ParityRepository, "insert_violations")

  def test_fetch_window_accepts_table_name():
      # Method signature: fetch_window(table_name, since, until, symbols, tfs)
      import inspect
      sig = inspect.signature(ParityRepository.fetch_window)
      assert "table_name" in sig.parameters
  ```
  Run → FAIL

- [ ] Create `src/persistence/repository/parity_repository.py`:
  - `fetch_window(table_name, since, until, symbols, tfs) → list[dict]` — generic, works for both tables
  - `insert_violations(violations: list[FieldViolation]) → None`
  - `fetch_certification_state(symbol, tf) → int` — returns consecutive clean cycle count
  - `update_certification_state(symbol, tf, count: int) → None`
  - All via injected `asyncpg.Pool`
  - **Security:** `table_name` validated against `{"intelligence_features", "feature_snapshots_shadow"}`

- [ ] Run tests → PASS

### Task 2: `FieldViolation` schema

**File:** `src/core/schemas/parity.py`

- [ ] Create Pydantic model:
  ```python
  from pydantic import BaseModel
  from datetime import datetime

  class FieldViolation(BaseModel):
      ts: datetime
      symbol: str
      tf: str
      field_name: str          # which column diverged
      primary_value: str       # json-serialized
      shadow_value: str        # json-serialized
      abs_diff: float | None   # for numeric fields
  ```
- [ ] Write test:
  ```python
  from src.core.schemas.parity import FieldViolation
  from datetime import datetime, UTC
  def test_field_violation_schema():
      v = FieldViolation(ts=datetime.now(UTC), symbol="ES", tf="1m", field_name="i1", primary_value="{}", shadow_value="{}", abs_diff=None)
      assert v.symbol == "ES"
  ```
  Run → PASS

### Task 3: Comparison engine

**File:** `services/parity_auditor_agent.py` (partially — just the comparison logic)
**Test:** `tests/unit/test_parity_auditor_agent.py`

- [ ] Write failing tests for comparison logic:
  ```python
  from services.parity_auditor_agent import _compare_rows, NUMERIC_TOLERANCE

  def test_identical_rows_no_violations():
      row = {"ts": "2026-01-01", "symbol": "ES", "tf": "1m", "i1": {"sma": 4500.0}}
      assert _compare_rows(row, row) == []

  def test_numeric_field_violation():
      primary = {"ts": "2026-01-01", "symbol": "ES", "tf": "1m", "i1": {"sma": 4500.0}}
      shadow  = {"ts": "2026-01-01", "symbol": "ES", "tf": "1m", "i1": {"sma": 4501.0}}
      violations = _compare_rows(primary, shadow)
      assert len(violations) == 1
      assert violations[0].field_name == "i1.sma"

  def test_within_tolerance_no_violation():
      primary = {"ts": "2026-01-01", "symbol": "ES", "tf": "1m", "i1": {"sma": 4500.0}}
      shadow  = {"ts": "2026-01-01", "symbol": "ES", "tf": "1m", "i1": {"sma": 4500.0 + 1e-10}}
      assert _compare_rows(primary, shadow) == []

  def test_certification_threshold_gate():
      from services.parity_auditor_agent import ParityAuditorAgent
      import pathlib
      src = pathlib.Path("services/parity_auditor_agent.py").read_text()
      assert "CERTIFICATION_THRESHOLD" in src
  ```
  Run → FAIL

- [ ] Implement module-level `_compare_rows(primary: dict, shadow: dict) -> list[FieldViolation]`:
  - For each column in primary: if numeric, use `abs(p - s) > NUMERIC_TOLERANCE` (default `1e-9`); if JSONB dict, recurse on each key
  - Return list of `FieldViolation` (empty = clean)
  - `CERTIFICATION_THRESHOLD = 12` (12 cycles × 5 min = 60 min consecutive clean)

### Task 4: Full `ParityAuditorAgent` implementation

- [ ] Implement `ParityAuditorAgent(BaseAgent)` in `services/parity_auditor_agent.py`:
  - `_run()`: loop — `await asyncio.sleep(300)` then `await _compare_cycle()`; check `_stop_event` between sleeps
  - `_compare_cycle()`:
    1. `fetch_window("intelligence_features", ...)` and `fetch_window("feature_snapshots_shadow", ...)`
    2. Join by `(ts, symbol, tf)` — rows only in primary (shadow hasn't caught up yet) = skip, not a violation
    3. For matched rows: call `_compare_rows()`
    4. `insert_violations()` for any violations
    5. Emit `parity_match_rate{symbol, tf}` Prometheus gauge per pair
    6. Update certification state; if threshold met for ALL active pairs → publish `SHADOW_PARITY_CERTIFIED`
  - `stop()`: log final state, close DB pool

- [ ] Kafka publication uses `topic_audit(settings.env_name)` and `topic_system_events(settings.env_name)` — never hardcoded strings

- [ ] Run all parity tests → PASS

### Task 5: systemd unit

**File:** `production/systemd/indicagent-parity-auditor.service`

- [ ] Create unit (same pattern as other services, port :9119 for metrics if desired)
- [ ] Install and start:
  ```bash
  echo 'PASSWORD' | /usr/bin/sudo.ws -S cp production/systemd/indicagent-parity-auditor.service /etc/systemd/system/
  echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl daemon-reload
  echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl enable --now indicagent-parity-auditor
  ```
- [ ] Verify first comparison cycle runs within 5 min:
  ```bash
  journalctl -u indicagent-parity-auditor --since "5 minutes ago" -n 30
  ```

### Task 6: Full test suite + lint + commit

- [ ] `.venv/bin/pytest tests/unit/ -q` — pass
- [ ] `.venv/bin/ruff check . --fix && .venv/bin/black .`
- [ ] Commit: `feat(parity): add ParityAuditorAgent with automated shadow certification`

---

## Source Plan

- `docs/plans/2026-03-25-parity-auditor-agent.md`
