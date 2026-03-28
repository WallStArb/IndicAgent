# Phase 52.3: Dual-Write Shadow Writer (FeatureSnapshotWriterAgent)

**Status:** 📋 Planned

**Milestone:** v2.1 Data Foundation & Signal Confidence

**Dependencies:** Phase 52.1 (feature_writer_service wiring fixed), Phase 52.2 (BaseAgent available)

---

## Goals

Deploy `FeatureSnapshotWriterAgent` as an independent shadow consumer of `development.intelligence.journal`. It writes an identical copy of every intelligence bar to `feature_snapshots_shadow`, enabling automated parity validation (Phase 52.5) before any primary-write cutover. Two consumer groups read the same topic independently — no coupling, no shared state, no coordinated writes.

**Renaissance principle:** Shadow before cutover. Earn the right through proof.

---

## Architecture

```
intelligence.journal topic
  ├── feature_writer_group       → intelligence_features       (existing primary)
  └── feature_snapshot_writer_group → feature_snapshots_shadow (new shadow)
```

Both consumers are independent. The shadow writer failure never affects the primary write path.

---

## Success Criteria

1. Migration `051_feature_snapshots_shadow.sql` applied: `feature_snapshots_shadow` hypertable exists; `feature_parity_violations` table exists
2. `FeatureSnapshotWriterAgent` starts, subscribes to `topic_intelligence_journal` with consumer group `feature_snapshot_writer_group`
3. Shadow rows appear in `feature_snapshots_shadow` within 5s of primary write to `intelligence_features`
4. `indicagent-feature-snapshot-writer.service` systemd unit installed and starts cleanly
5. Unit tests pass for parse + write path
6. `FeatureRepository.write_batch()` accepts configurable `table_name` parameter (DRY reuse between primary and shadow)

---

## Tasks

### Task 1: Shadow table migration

**File:** `production/migrations/051_feature_snapshots_shadow.sql`

- [ ] Check if migration file already exists:
  ```bash
  ls production/migrations/051_*.sql 2>/dev/null
  ```
- [ ] If missing, write the migration (copy from `docs/plans/2026-03-25-dual-write-parity-audit.md` Task 2 section — full SQL is there)
- [ ] Apply migration:
  ```bash
  docker exec timescaledb psql -U postgres -d indicagent -f /path/to/051_feature_snapshots_shadow.sql
  ```
- [ ] Verify tables exist:
  ```bash
  docker exec timescaledb psql -U postgres -d indicagent -c "\dt feature_snapshots_shadow" -c "\dt feature_parity_violations"
  ```

### Task 2: Make `FeatureRepository` accept configurable table name

**File:** `src/persistence/repository/feature_repository.py`
**Test:** `tests/unit/test_feature_repository.py`

- [ ] Check if `FeatureRepository` exists: `ls src/persistence/repository/feature_repository.py`
- [ ] Write failing test:
  ```python
  from src.persistence.repository.feature_repository import FeatureRepository

  def test_feature_repository_accepts_table_name():
      repo = FeatureRepository(table_name="feature_snapshots_shadow")
      assert repo.table_name == "feature_snapshots_shadow"

  def test_feature_repository_default_table():
      repo = FeatureRepository()
      assert repo.table_name == "intelligence_features"
  ```
  Run → FAIL

- [ ] Modify (or create) `FeatureRepository`:
  - Add `table_name: str = "intelligence_features"` to `__init__`
  - All SQL in `write_batch()` uses `self.table_name` via parameterized queries (never f-string directly into SQL — use `sql.Identifier` from `asyncpg` or explicit allow-list validation)
  - **Security note:** table name must be validated against an allow-list: `{"intelligence_features", "feature_snapshots_shadow"}`

- [ ] Run tests → PASS

### Task 3: `FeatureSnapshotWriterAgent` service

**File:** `services/feature_snapshot_writer_agent.py`
**Test:** `tests/unit/test_feature_snapshot_writer_agent.py`

- [ ] Write failing tests (see `docs/plans/2026-03-25-dual-write-parity-audit.md` Task 3 for full test spec):
  ```python
  # Minimum viable:
  def test_feature_snapshot_writer_agent_class_exists():
      from services.feature_snapshot_writer_agent import FeatureSnapshotWriterAgent
      from src.core.agent.base import BaseAgent
      agent = FeatureSnapshotWriterAgent.__new__(FeatureSnapshotWriterAgent)
      assert isinstance(agent, BaseAgent)

  def test_uses_snapshot_writer_consumer_group():
      import ast, pathlib
      src = pathlib.Path("services/feature_snapshot_writer_agent.py").read_text()
      assert "feature_snapshot_writer_group" in src

  def test_subscribes_to_intelligence_journal():
      import pathlib
      src = pathlib.Path("services/feature_snapshot_writer_agent.py").read_text()
      assert "topic_intelligence_journal" in src
      assert "topic_feature_processed" not in src
  ```

- [ ] Implement `services/feature_snapshot_writer_agent.py`:
  - Inherits `BaseAgent`
  - Consumer group: `feature_snapshot_writer_group`
  - Subscribes to `topic_intelligence_journal(settings.env_name)`
  - Parses `BarIntelligenceRecord` from each message
  - Calls `FeatureRepository(table_name="feature_snapshots_shadow").write_batch()`
  - Instruments `persistence_batch_latency`, `persistence_consumer_lag`
  - DLQ routing: malformed messages → `topic_intelligence_journal` + `.dlq` suffix (log and skip, never crash)
  - SIGTERM: drain in-flight batch before exit (inherited from `BaseAgent.stop()`)

- [ ] Run tests → PASS

### Task 4: systemd unit

**File:** `production/systemd/indicagent-feature-snapshot-writer.service`

- [ ] Create systemd unit (mirror `production/systemd/indicagent-feature-writer.service` pattern):
  ```ini
  [Unit]
  Description=IndicAgent Feature Snapshot Writer (shadow parity)
  After=network.target

  [Service]
  Type=simple
  User=bg
  WorkingDirectory=/home/bg/dev/indicagent
  ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/feature_snapshot_writer_agent.py
  Restart=on-failure
  RestartSec=5
  StandardOutput=journal
  StandardError=journal
  Environment=PYTHONUNBUFFERED=1
  LimitNOFILE=65536

  [Install]
  WantedBy=multi-user.target
  ```
- [ ] Install and start:
  ```bash
  echo 'PASSWORD' | /usr/bin/sudo.ws -S cp production/systemd/indicagent-feature-snapshot-writer.service /etc/systemd/system/
  echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl daemon-reload
  echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl enable --now indicagent-feature-snapshot-writer
  ```
- [ ] Verify:
  ```bash
  echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl status indicagent-feature-snapshot-writer
  ```

### Task 5: Smoke test — shadow rows appear

- [ ] Wait 2 minutes after service start
- [ ] Query:
  ```bash
  docker exec timescaledb psql -U postgres -d indicagent -c "
  SELECT COUNT(*) FROM feature_snapshots_shadow WHERE ts > NOW() - INTERVAL '5 minutes';
  "
  ```
  Expected: count > 0 (rows flowing in)
- [ ] Compare row counts:
  ```bash
  docker exec timescaledb psql -U postgres -d indicagent -c "
  SELECT 'primary' AS tbl, COUNT(*) FROM intelligence_features WHERE ts > NOW() - INTERVAL '10 minutes'
  UNION ALL
  SELECT 'shadow', COUNT(*) FROM feature_snapshots_shadow WHERE ts > NOW() - INTERVAL '10 minutes';
  "
  ```
  Expected: counts within 10% of each other (shadow catches up within one batch window)

### Task 6: Full test suite + lint + commit

- [ ] `.venv/bin/pytest tests/unit/ -q` — pass
- [ ] `.venv/bin/ruff check . --fix && .venv/bin/black .`
- [ ] Commit: `feat(shadow-writer): add FeatureSnapshotWriterAgent + migration 051`

---

## Source Plan

- `docs/plans/2026-03-25-dual-write-parity-audit.md` (Tasks 2–4)
