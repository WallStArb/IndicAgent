# Plan 086-02 Summary

## What Was Built

Wired `validate_signal()` from `src/intelligence/trading/signal_schema.py` as a per-signal gate inside `SignalWriterAgent._parse_payload`. Invalid signals are buffered in `self._invalid_signals` and drained to `topic_signal_writer_dlq` via `self._send_to_dlq()` at the top of each `_flush_batch` call, before the `insert_signals` DB write. Valid signals continue unchanged through `_payload_to_ledger_entries`.

## Tasks Completed

- [x] Task 1: Add validate_signal gate + pending DLQ buffer to SignalWriterAgent

## Key Changes

- `services/signal_writer_agent.py`: Added `validate_signal` import, `self._invalid_signals: list[dict] = []` in `__init__`, rewrote `_parse_payload` to partition signals and return `[]` (not `None`) when all are invalid, added DLQ drain loop at the top of `_flush_batch`
- `tests/unit/service_tests/test_signal_writer_agent.py`: Added `agent._invalid_signals = []` to `_make_agent` helper (required because tests use `__new__` to bypass `__init__`)

## Design Notes

### Async-bridge pattern: pending buffer in __init__

`_parse_payload` is synchronous (called from the base class consume loop), but `_send_to_dlq` is async. The chosen pattern uses a `self._invalid_signals` buffer initialized in `__init__` and drained at the start of `_flush_batch` (which runs in async context). This avoids any need to make `_parse_payload` async or change base class signatures. The drain happens within at most `FLUSH_INTERVAL_SECS = 5s` of the invalid signal being partitioned.

### Backfill-signal compatibility (Pitfall 4)

Backfill signals are tagged with `is_backfill=True` but otherwise follow the same `signal.v1` schema. `validate_signal()` checks structural fields (`type`, `targets`, `direction`, `confidence`, required fields set) - it does not inspect `is_backfill`. Backfill signals produced by `make_signal_from_frame` pass validation normally. Legacy signals published before `signal.v1` type tag adoption will fail the `type == "signal.v1"` check and be DLQ'd - this is intentional, as those are the malformed signals PIPE-02 targets.

### Recommended follow-up unit test

A test covering the partition behavior directly in `_parse_payload`:

```python
def test_parse_payload_partitions_invalid_signals():
    agent = _make_agent()
    valid_sig = _make_valid_signal()   # has all REQUIRED_SIGNAL_FIELDS + type=signal.v1
    invalid_sig = {"setup_plugin": "x"}  # missing required fields
    payload = {"symbol": "ES", "tf": "1m", "signals": [valid_sig, invalid_sig], ...}
    rows = agent._parse_payload(payload)
    assert len(rows) == 1
    assert len(agent._invalid_signals) == 1
```

## Verification

- Tests pass: yes (3260 passed, 1 skipped)
- Lint clean: yes (ruff exits 0, black applied)

## Self-Check: PASSED

- `services/signal_writer_agent.py` exists and contains `validate_signal`, `_invalid_signals`, `_send_to_dlq`
- Commit `afdf6718` present in git log
- All acceptance criteria verified via grep
