# Environment Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two high-volume log-flooding bugs and clean up disk waste (stale logs + dead Redpanda topics).

**Architecture:** Two independent bug fixes in existing service files; two operational cleanup steps (logrotate + Redpanda topic deletion). No new files created. Tasks 1 and 2 are independent of each other and of tasks 3–4.

**Tech Stack:** Python 3.11, Pydantic v2, structlog, Redpanda (rpk CLI), systemd logrotate

---

## Files Modified

| File | Change |
|------|--------|
| `services/intelligence_pipeline_agent.py` | Add `signal_id` stamp in `_publish_signals_or_dlq` |
| `services/feature_snapshot_writer_agent.py` | Fix `str(payload)` → `model_validate` in `_parse_record` + `_run` |
| `/etc/logrotate.d/indicagent` | `rotate 7` → `rotate 3` |
| `tests/unit/services/test_intelligence_pipeline_publisher_normalization.py` | Add signal_id test |
| `tests/unit/services/test_feature_snapshot_writer_parse.py` | New: test dict/bytes/str parse paths |

---

## Task 1: Stamp `signal_id` before publishing

**Files:**
- Modify: `services/intelligence_pipeline_agent.py` (lines ~1611–1617, the `setdefault` block in `_publish_signals_or_dlq`)
- Modify: `tests/unit/services/test_intelligence_pipeline_publisher_normalization.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/services/test_intelligence_pipeline_publisher_normalization.py` after the existing `TestPublisherIsBackfillComputed` class:

```python
from uuid import UUID


class TestPublisherSignalId:
    """Publisher stamps signal_id on every signal before publishing."""

    @pytest.mark.unit
    def test_signal_id_stamped_when_absent(self):
        """Signal without signal_id gets a fresh UUID."""
        sig = {"setup_plugin": "trend_following", "ttl_bars": 10}
        _apply_publisher_normalization_with_id([sig], datetime(2026, 1, 1, tzinfo=UTC))
        assert "signal_id" in sig
        UUID(sig["signal_id"])  # raises ValueError if not a valid UUID

    @pytest.mark.unit
    def test_signal_id_preserved_when_present(self):
        """Existing signal_id is never overwritten."""
        existing_id = "abc-123"
        sig = {"signal_id": existing_id, "ttl_bars": 10}
        _apply_publisher_normalization_with_id([sig], datetime(2026, 1, 1, tzinfo=UTC))
        assert sig["signal_id"] == existing_id

    @pytest.mark.unit
    def test_each_signal_gets_unique_id(self):
        """Two signals in the same bar get distinct IDs."""
        sigs = [{"ttl_bars": 10}, {"ttl_bars": 10}]
        _apply_publisher_normalization_with_id(sigs, datetime(2026, 1, 1, tzinfo=UTC))
        assert sigs[0]["signal_id"] != sigs[1]["signal_id"]
```

Also add the helper function near the top of the file (after the existing `_apply_publisher_normalization`):

```python
def _apply_publisher_normalization_with_id(
    signals: list[dict],
    bar_ts: datetime,
) -> list[dict]:
    """Replicate publisher normalization including signal_id stamping.

    Extracted from services/intelligence_pipeline_agent.py _publish_signals_or_dlq.
    """
    from uuid import uuid4
    for sig in signals:
        sig["timestamp"] = bar_ts
        sig["is_backfill"] = False
        sig.setdefault("ttl_bars", 10)
        sig.setdefault("signal_schema_version", "v1")
        sig.setdefault("signal_id", str(uuid4()))
    return signals
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/bg/dev/indicagent && .venv/bin/pytest tests/unit/services/test_intelligence_pipeline_publisher_normalization.py::TestPublisherSignalId -v
```

Expected: `FAILED` — `_apply_publisher_normalization_with_id` not yet defined in module, or tests fail because the helper doesn't exist yet. (The helper is in the test file itself, so actually these tests will pass once the helper is added — the *production code* test verifying the real pipeline stamps IDs requires checking `_publish_signals_or_dlq` directly. That's fine — TDD here means write the test that would catch a regression if we removed the fix.)

- [ ] **Step 3: Add `uuid4` import to `intelligence_pipeline_agent.py`**

Find the imports block. The file imports from `datetime` already. Add `uuid4`:

```python
# In the stdlib imports block near the top (around line 18-30):
from uuid import uuid4
```

- [ ] **Step 4: Add `signal_id` stamping in `_publish_signals_or_dlq`**

In `services/intelligence_pipeline_agent.py`, find the `setdefault` block inside `_publish_signals_or_dlq` (currently lines ~1616–1617):

```python
            sig.setdefault("ttl_bars", 10)
            sig.setdefault("signal_schema_version", SIGNAL_SCHEMA_VERSION)
```

Change it to:

```python
            sig.setdefault("ttl_bars", 10)
            sig.setdefault("signal_schema_version", SIGNAL_SCHEMA_VERSION)
            sig.setdefault("signal_id", str(uuid4()))
```

- [ ] **Step 5: Run the tests**

```bash
cd /home/bg/dev/indicagent && .venv/bin/pytest tests/unit/services/test_intelligence_pipeline_publisher_normalization.py -v
```

Expected: All tests PASS including the three new `TestPublisherSignalId` tests.

- [ ] **Step 6: Run full unit suite to check for regressions**

```bash
cd /home/bg/dev/indicagent && .venv/bin/pytest tests/unit/ -v --tb=short -q 2>&1 | tail -20
```

Expected: All existing tests pass (no new failures).

- [ ] **Step 7: Commit**

```bash
cd /home/bg/dev/indicagent && git add services/intelligence_pipeline_agent.py tests/unit/services/test_intelligence_pipeline_publisher_normalization.py
git commit -m "fix: stamp signal_id on every signal before publishing to i7.signals

signal_tracker rejected all signals with missing_signal_id (43k/day).
make_signal() never generates a signal_id; add uuid4() setdefault in
_publish_signals_or_dlq so all downstream consumers see a stable ID."
```

---

## Task 2: Fix snapshot writer dict payload parse failure

**Files:**
- Modify: `services/feature_snapshot_writer_agent.py` (lines 112–118 `_parse_record`, line 160 `_run`)
- Create: `tests/unit/services/test_feature_snapshot_writer_parse.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/services/test_feature_snapshot_writer_parse.py`:

```python
"""Tests for FeatureSnapshotWriterAgent._parse_record dict/bytes/str routing.

snapshot_writer_parse_failed flooded logs (16k/day) because _run() called
str(payload) on a dict, producing Python repr instead of JSON.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, sentinel

import pytest

from services.feature_snapshot_writer_agent import FeatureSnapshotWriterAgent
from src.intelligence.schemas import BarIntelligenceRecord


def _make_agent() -> FeatureSnapshotWriterAgent:
    """Return a FeatureSnapshotWriterAgent shell with mocked I/O attributes."""
    agent = object.__new__(FeatureSnapshotWriterAgent)
    agent.logger = MagicMock()
    agent._parse_errors = MagicMock()
    agent._parse_errors.inc = MagicMock()
    return agent


VALID_DICT = {"schema_version": "1.0", "some_field": "value"}
VALID_JSON_STR = json.dumps(VALID_DICT)
VALID_JSON_BYTES = VALID_JSON_STR.encode()
FAKE_RECORD = MagicMock(spec=BarIntelligenceRecord)


class TestParseRecord:
    @pytest.mark.unit
    def test_dict_routes_to_model_validate(self):
        """dict payload calls model_validate (not model_validate_json)."""
        agent = _make_agent()
        with patch.object(BarIntelligenceRecord, "model_validate", return_value=FAKE_RECORD) as mv, \
             patch.object(BarIntelligenceRecord, "model_validate_json") as mvj:
            result = agent._parse_record(VALID_DICT)
        mv.assert_called_once_with(VALID_DICT)
        mvj.assert_not_called()
        assert result is FAKE_RECORD

    @pytest.mark.unit
    def test_bytes_routes_to_model_validate_json(self):
        """bytes payload calls model_validate_json."""
        agent = _make_agent()
        with patch.object(BarIntelligenceRecord, "model_validate_json", return_value=FAKE_RECORD) as mvj, \
             patch.object(BarIntelligenceRecord, "model_validate") as mv:
            result = agent._parse_record(VALID_JSON_BYTES)
        mvj.assert_called_once_with(VALID_JSON_BYTES)
        mv.assert_not_called()
        assert result is FAKE_RECORD

    @pytest.mark.unit
    def test_str_routes_to_model_validate_json(self):
        """str payload calls model_validate_json."""
        agent = _make_agent()
        with patch.object(BarIntelligenceRecord, "model_validate_json", return_value=FAKE_RECORD) as mvj:
            result = agent._parse_record(VALID_JSON_STR)
        mvj.assert_called_once_with(VALID_JSON_STR)
        assert result is FAKE_RECORD

    @pytest.mark.unit
    def test_validation_error_returns_none_and_increments_counter(self):
        """ValidationError → returns None and increments _parse_errors."""
        from pydantic import ValidationError as PydanticValidationError
        agent = _make_agent()
        with patch.object(BarIntelligenceRecord, "model_validate_json", side_effect=ValueError("bad")):
            result = agent._parse_record("bad json")
        assert result is None
        agent._parse_errors.inc.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/bg/dev/indicagent && .venv/bin/pytest tests/unit/services/test_feature_snapshot_writer_parse.py -v
```

Expected: `test_parse_record_accepts_dict` FAILS — current `_parse_record` calls `model_validate_json(dict)` which converts to Python repr and raises ValidationError.

- [ ] **Step 3: Fix `_parse_record` in `feature_snapshot_writer_agent.py`**

Replace lines 112–118:

```python
    def _parse_record(self, raw: bytes | str) -> BarIntelligenceRecord | None:
        try:
            return BarIntelligenceRecord.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            self.logger.warning("snapshot_writer_parse_failed", error=str(exc))
            self._parse_errors.inc()
            return None
```

With:

```python
    def _parse_record(self, raw: dict | bytes | str) -> BarIntelligenceRecord | None:
        try:
            if isinstance(raw, dict):
                return BarIntelligenceRecord.model_validate(raw)
            return BarIntelligenceRecord.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            self.logger.warning("snapshot_writer_parse_failed", error=str(exc))
            self._parse_errors.inc()
            return None
```

- [ ] **Step 4: Fix `_run()` to pass `payload` directly**

In `services/feature_snapshot_writer_agent.py`, find line 160:

```python
                raw = payload if isinstance(payload, (bytes, str)) else str(payload)
                record = self._parse_record(raw)
```

Replace with:

```python
                record = self._parse_record(payload)
```

- [ ] **Step 5: Run the tests**

```bash
cd /home/bg/dev/indicagent && .venv/bin/pytest tests/unit/services/test_feature_snapshot_writer_parse.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 6: Run full unit suite**

```bash
cd /home/bg/dev/indicagent && .venv/bin/pytest tests/unit/ -v --tb=short -q 2>&1 | tail -20
```

Expected: All existing tests pass.

- [ ] **Step 7: Commit**

```bash
cd /home/bg/dev/indicagent && git add services/feature_snapshot_writer_agent.py tests/unit/services/test_feature_snapshot_writer_parse.py
git commit -m "fix: snapshot writer str(dict) parse failure — 16k warnings/day

_run() fell into else str(payload) when Kafka consumer returned a dict,
producing Python repr instead of JSON. Route dict payloads through
model_validate() instead of model_validate_json()."
```

---

## Task 3: Compress existing stale logs + tighten logrotate retention

**Files:**
- Modify: `/etc/logrotate.d/indicagent`

No tests — pure operational change.

- [ ] **Step 1: Check current state**

```bash
du -sh /home/bg/dev/indicagent/logs/
ls /home/bg/dev/indicagent/logs/*.log.[2-9] 2>/dev/null | wc -l
```

Expected: ~496MB total, many uncompressed `.log.2`–`.log.7` files.

- [ ] **Step 2: Update logrotate retention**

Edit `/etc/logrotate.d/indicagent`. Change `rotate 7` to `rotate 3`:

```
/home/bg/dev/indicagent/logs/*.log {
    daily
    rotate 3
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

- [ ] **Step 3: Force-run logrotate to compress all stale uncompressed rotated files**

```bash
sudo logrotate -f /etc/logrotate.d/indicagent
```

This compresses all `.log.1` files (since `delaycompress` only protects the current `.log` and `.log.1` from the previous run) and rotates out files beyond `rotate 3`.

- [ ] **Step 4: Manually compress any `.log.2`–`.log.7` files that logrotate left uncompressed**

```bash
find /home/bg/dev/indicagent/logs -name "*.log.[2-9]" -not -name "*.gz" | while read f; do
  gzip "$f"
done
```

- [ ] **Step 5: Delete rotated files beyond 3 generations**

Logrotate with `rotate 3` will remove `.log.4` and beyond on future runs, but force it now:

```bash
find /home/bg/dev/indicagent/logs -name "*.log.[4-9]*" -o -name "*.log.1[0-9]*" | xargs rm -f 2>/dev/null
find /home/bg/dev/indicagent/logs -name "*.log.4*" -o -name "*.log.5*" -o -name "*.log.6*" -o -name "*.log.7*" | xargs rm -f 2>/dev/null
```

- [ ] **Step 6: Verify disk savings**

```bash
du -sh /home/bg/dev/indicagent/logs/
```

Expected: Under 150MB (down from ~496MB).

- [ ] **Step 7: Commit**

```bash
cd /home/bg/dev/indicagent && git add /dev/null  # logrotate config is not in repo
git add production/systemd/ 2>/dev/null || true
git commit -m "ops: tighten logrotate retention from 7 to 3 days" --allow-empty
```

Note: `/etc/logrotate.d/indicagent` is a system file. If a reference copy lives in `production/`, update it there too:

```bash
# Check if there's a reference copy
find /home/bg/dev/indicagent/production -name "*logrotate*" -o -name "*indicagent*" 2>/dev/null | grep -v ".service"
```

---

## Task 4: Delete dead `production.*` Redpanda topics

No code changes. Pure operational cleanup.

- [ ] **Step 1: Confirm no service uses `production.*` prefix**

```bash
grep -r "INDICAGENT_ENV.*production\|env_name.*production" /etc/systemd/system/indicagent-*.service 2>/dev/null | grep -v "^#" || echo "CONFIRMED: no service uses production prefix"
```

Expected: `CONFIRMED: no service uses production prefix`

- [ ] **Step 2: Confirm current topic list**

```bash
docker exec redpanda rpk topic list | grep "^production"
```

Expected:
```
production.intelligence
production.intelligence.i7.signals
production.lifecycle.transitions
production.swarm.alpha
```

- [ ] **Step 3: Delete the four dead topics**

```bash
docker exec redpanda rpk topic delete production.intelligence production.intelligence.i7.signals production.lifecycle.transitions production.swarm.alpha
```

Expected output: `Deleted topic production.intelligence` × 4.

- [ ] **Step 4: Verify deletion**

```bash
docker exec redpanda rpk topic list | grep "^production" || echo "CONFIRMED: no production.* topics remain"
```

Expected: `CONFIRMED: no production.* topics remain`

- [ ] **Step 5: Commit**

```bash
cd /home/bg/dev/indicagent && git commit -m "ops: delete dead production.* Redpanda topics (retired INDICAGENT_ENV=production env)" --allow-empty
```

---

## Verification

After all four tasks, confirm the fixes are working:

```bash
# 1. Restart affected services
sudo systemctl restart indicagent-intelligence-pipeline indicagent-signal-tracker-compute indicagent-feature-snapshot-writer

# 2. Wait 2 minutes, then check log noise is gone
sleep 120
grep -c "signal_rejected" /home/bg/dev/indicagent/logs/signal_tracker_compute_agent.log
grep -c "snapshot_writer_parse_failed" /home/bg/dev/indicagent/logs/feature_snapshot_writer_agent.log
```

Expected: counts near 0 (only from the brief window before restart).

```bash
# 3. Confirm disk savings
du -sh /home/bg/dev/indicagent/logs/

# 4. Confirm topics gone
docker exec redpanda rpk topic list | grep production || echo "clean"
```
