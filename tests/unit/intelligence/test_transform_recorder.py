"""Tests for TransformRecorder — async batch writer for signal_transform_log."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.core.ml.transform_recorder import TransformRecorder


def _make_pool():
    """Mock pool: acquire() yields a conn with AsyncMock executemany."""
    conn = MagicMock()
    conn.executemany = AsyncMock()
    pool = MagicMock()
    acquire_ctx = MagicMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = MagicMock(return_value=acquire_ctx)
    return pool, conn


@pytest.mark.asyncio
async def test_record_buffers_until_batch_size():
    """99 calls → 0 flushes; 100th call triggers 1 executemany."""
    pool, conn = _make_pool()
    rec = TransformRecorder(pool=pool, batch_size=100)
    for _ in range(99):
        await rec.record(signal_id=str(uuid4()), transform_id="t", dag_order=0, multiplier=1.0)
    assert conn.executemany.await_count == 0
    await rec.record(signal_id=str(uuid4()), transform_id="t", dag_order=0, multiplier=1.0)
    assert conn.executemany.await_count == 1


@pytest.mark.asyncio
async def test_flush_drains_pending():
    """pending=[1,2,3], call flush() → executemany called with 3-tuple batch, _pending now empty."""
    pool, conn = _make_pool()
    rec = TransformRecorder(pool=pool, batch_size=100)
    for _ in range(3):
        await rec.record(signal_id=str(uuid4()), transform_id="t", dag_order=0, multiplier=1.0)
    assert len(rec._pending) == 3
    await rec.flush()
    assert conn.executemany.await_count == 1
    args = conn.executemany.await_args[0]
    batch = args[1]
    assert len(batch) == 3
    assert rec._pending == []


@pytest.mark.asyncio
async def test_record_with_metadata_serializes_json():
    """metadata={"k": "v"} → row[7] is the JSON string '{"k": "v"}'."""
    pool, conn = _make_pool()
    rec = TransformRecorder(pool=pool, batch_size=1)
    await rec.record(
        signal_id="s1",
        transform_id="t",
        dag_order=0,
        multiplier=1.0,
        metadata={"k": "v"},
    )
    args = conn.executemany.await_args[0]
    batch = args[1]
    row = batch[0]
    assert json.loads(row[7]) == {"k": "v"}


@pytest.mark.asyncio
async def test_record_with_no_metadata_passes_none():
    """metadata=None → row[7] is None."""
    pool, conn = _make_pool()
    rec = TransformRecorder(pool=pool, batch_size=1)
    await rec.record(signal_id="s1", transform_id="t", dag_order=0, multiplier=1.0, metadata=None)
    args = conn.executemany.await_args[0]
    batch = args[1]
    row = batch[0]
    assert row[7] is None


@pytest.mark.asyncio
async def test_record_coerces_signal_id_to_str():
    """Pass UUID → row[1] is its str(uuid) form."""
    pool, conn = _make_pool()
    rec = TransformRecorder(pool=pool, batch_size=1)
    uid = uuid4()
    await rec.record(signal_id=uid, transform_id="t", dag_order=0, multiplier=1.0)
    args = conn.executemany.await_args[0]
    batch = args[1]
    row = batch[0]
    assert row[1] == str(uid)
    assert isinstance(row[1], str)


@pytest.mark.asyncio
async def test_flush_swallows_executemany_exceptions():
    """mock conn raises → flush completes, pending cleared, no re-raise."""
    pool, conn = _make_pool()
    conn.executemany.side_effect = RuntimeError("DB down")
    rec = TransformRecorder(pool=pool, batch_size=1)
    await rec.record(signal_id="s1", transform_id="t", dag_order=0, multiplier=1.0)
    # auto-flush triggered, exception swallowed — no raise expected
    # Pending should be empty (drained before exception)
    assert rec._pending == []


@pytest.mark.asyncio
async def test_default_segment_key_is_global():
    """Omit segment_key → row[5] == '__global__'."""
    pool, conn = _make_pool()
    rec = TransformRecorder(pool=pool, batch_size=1)
    await rec.record(signal_id="s1", transform_id="t", dag_order=0, multiplier=1.0)
    args = conn.executemany.await_args[0]
    batch = args[1]
    row = batch[0]
    assert row[5] == "__global__"


@pytest.mark.asyncio
async def test_default_transform_version_is_v1():
    """Omit transform_version → row[3] == 'v1'."""
    pool, conn = _make_pool()
    rec = TransformRecorder(pool=pool, batch_size=1)
    await rec.record(signal_id="s1", transform_id="t", dag_order=0, multiplier=1.0)
    args = conn.executemany.await_args[0]
    batch = args[1]
    row = batch[0]
    assert row[3] == "v1"


@pytest.mark.asyncio
async def test_default_is_shadow_true():
    """Omit is_shadow → row[8] is True."""
    pool, conn = _make_pool()
    rec = TransformRecorder(pool=pool, batch_size=1)
    await rec.record(signal_id="s1", transform_id="t", dag_order=0, multiplier=1.0)
    args = conn.executemany.await_args[0]
    batch = args[1]
    row = batch[0]
    assert row[8] is True


@pytest.mark.asyncio
async def test_record_with_explicit_values():
    """Explicit segment_key, transform_version, is_shadow land in correct row positions."""
    pool, conn = _make_pool()
    rec = TransformRecorder(pool=pool, batch_size=1)
    await rec.record(
        signal_id="sig-123",
        transform_id="tod",
        dag_order=3,
        multiplier=0.85,
        segment_key="trend.1m.14",
        metadata={"hour": 14},
        transform_version="v2",
        is_shadow=False,
    )
    args = conn.executemany.await_args[0]
    batch = args[1]
    row = batch[0]
    # ts at index 0 — just check it's a datetime
    from datetime import datetime

    assert isinstance(row[0], datetime)
    assert row[1] == "sig-123"
    assert row[2] == "tod"
    assert row[3] == "v2"
    assert row[4] == 3
    assert row[5] == "trend.1m.14"
    assert row[6] == 0.85
    assert json.loads(row[7]) == {"hour": 14}
    assert row[8] is False
