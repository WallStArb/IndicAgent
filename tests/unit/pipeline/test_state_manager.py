"""Isolated unit tests for PluginStateManager.

Tests cover:
- Lock lazy-init semantics
- State read/write API (get_state, update, update_batch, get_all_states_for)
- Checkpoint roundtrip (write then read)
- Raise-on-failure contracts (OSError from I/O and ValueError from plugin_states guard)
- Background loop resilience (survives transient failures, propagates CancelledError)
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import tempfile

import pytest

from src.intelligence.pipeline.state_manager import PluginStateManager


def _make_pm(tmp_dir: str | None = None) -> tuple[PluginStateManager, pathlib.Path]:
    """Create a PluginStateManager with a temp checkpoint path."""
    d = tmp_dir or tempfile.mkdtemp()
    path = pathlib.Path(d) / "checkpoint.json"
    return PluginStateManager(checkpoint_path=path), path


_VALID_EXTRA = {
    "kalman_state": {},
    "last_bar_offset": {},
    "setup_last_fire": {},
}


# ---------------------------------------------------------------------------
# Lock tests
# ---------------------------------------------------------------------------


def test_get_lock_returns_same_lock_per_key():
    """get_lock must return the identical object on repeated calls for the same key."""
    pm, _ = _make_pm()
    lock1 = pm.get_lock(("ES", "1m"))
    lock2 = pm.get_lock(("ES", "1m"))
    assert lock1 is lock2


def test_get_lock_different_keys_return_different_locks():
    """Different (symbol, tf) keys must return different lock objects."""
    pm, _ = _make_pm()
    lock_a = pm.get_lock(("ES", "1m"))
    lock_b = pm.get_lock(("NQ", "1m"))
    lock_c = pm.get_lock(("ES", "5m"))
    assert lock_a is not lock_b
    assert lock_a is not lock_c
    assert lock_b is not lock_c


# ---------------------------------------------------------------------------
# State read/write tests
# ---------------------------------------------------------------------------


def test_update_and_get_state_roundtrip():
    """update then get_state returns the stored value; missing key returns empty dict."""
    pm, _ = _make_pm()
    pm.update(("plugA", "ES", "1m"), {"x": 1})
    assert pm.get_state(("plugA", "ES", "1m")) == {"x": 1}
    assert pm.get_state(("missing", "ES", "1m")) == {}


def test_get_all_states_for_filters_by_symbol_tf():
    """get_all_states_for must return only entries matching (symbol, tf).

    This is the HIGH finding 1 contract: per-bar read API keyed by plugin_name.
    """
    pm, _ = _make_pm()
    pm.update(("plugA", "ES", "1m"), {"a": 1})
    pm.update(("plugB", "ES", "1m"), {"b": 2})
    pm.update(("plugA", "NQ", "1m"), {"c": 3})  # different symbol — must not appear

    result = pm.get_all_states_for("ES", "1m")
    assert result == {"plugA": {"a": 1}, "plugB": {"b": 2}}


def test_get_all_states_for_returns_empty_dict_when_no_match():
    """get_all_states_for returns empty dict when no plugins have state for that (symbol, tf)."""
    pm, _ = _make_pm()
    result = pm.get_all_states_for("ES", "1m")
    assert result == {}


def test_update_batch_merges_full_tuple_keys():
    """update_batch accepts a dict keyed by full (plugin_name, symbol, tf) tuples.

    Both entries must be readable via get_state with the exact 3-tuple key.
    """
    pm, _ = _make_pm()
    batch = {
        ("plugA", "ES", "1m"): {"x": 1},
        ("plugB", "NQ", "5m"): {"y": 2},
    }
    pm.update_batch(batch)
    assert pm.get_state(("plugA", "ES", "1m")) == {"x": 1}
    assert pm.get_state(("plugB", "NQ", "5m")) == {"y": 2}


# ---------------------------------------------------------------------------
# Checkpoint write/read tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_then_read_checkpoint_roundtrip():
    """write_checkpoint then read_checkpoint on a fresh manager returns the same extra fields."""
    pm, path = _make_pm()
    extra_in = {
        "kalman_state": {"a": 1.0},
        "last_bar_offset": {"p:0": 42},
        "setup_last_fire": {},
    }
    pm.write_checkpoint(extra_in)

    # Fresh manager pointing at the same path
    pm2 = PluginStateManager(checkpoint_path=path)
    result = await pm2.read_checkpoint()

    assert result is not None
    assert result["kalman_state"] == {"a": 1.0}
    assert result["last_bar_offset"] == {"p:0": 42}


def test_write_checkpoint_raises_if_extra_contains_plugin_states():
    """write_checkpoint must raise ValueError when extra_state contains 'plugin_states'.

    This is the HIGH finding 5 single-writer contract.
    """
    pm, _ = _make_pm()
    with pytest.raises(ValueError, match="plugin_states"):
        pm.write_checkpoint({"plugin_states": {("x", "y", "z"): {}}})


def test_write_checkpoint_persists_internal_plugin_states():
    """write_checkpoint must include plugin_states from self._plugin_states in the JSON.

    Proves PluginStateManager is the single writer of plugin_states.
    """
    pm, path = _make_pm()
    pm.update(("plugA", "ES", "1m"), {"x": 1})
    pm.write_checkpoint(_VALID_EXTRA)

    raw = json.loads(path.read_text())
    assert "plugin_states" in raw
    # The tagged form uses str() of the tuple as the key
    assert any("plugA" in k for k in raw["plugin_states"])


def test_write_checkpoint_raises_on_io_error(monkeypatch, tmp_path):
    """write_checkpoint must raise on I/O error (Phase 086 D-15 contract)."""
    path = tmp_path / "ckpt.json"
    pm = PluginStateManager(checkpoint_path=path)

    # Make the parent directory a file to force an OSError on write
    tmp_file = tmp_path / "tmp_blocker.tmp"
    tmp_file.write_text("blocker")

    # Monkeypatch write_text on the .tmp path to raise
    import pathlib as _pathlib

    original_with_suffix = _pathlib.Path.with_suffix

    def _raise_on_tmp(self, suffix):
        obj = original_with_suffix(self, suffix)
        if suffix == ".tmp":
            raise OSError("simulated write failure")
        return obj

    monkeypatch.setattr(_pathlib.Path, "with_suffix", _raise_on_tmp)
    with pytest.raises(OSError):
        pm.write_checkpoint(_VALID_EXTRA)


@pytest.mark.asyncio
async def test_read_checkpoint_returns_none_on_missing_file():
    """read_checkpoint must return None when the file does not exist."""
    pm, path = _make_pm()
    # path does not exist — never written
    result = await pm.read_checkpoint()
    assert result is None


# ---------------------------------------------------------------------------
# Background loop tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_checkpoint_loop_writes_periodically(tmp_path):
    """Background loop must write the checkpoint file within the first interval."""
    path = tmp_path / "ckpt.json"
    pm = PluginStateManager(checkpoint_path=path)

    task = pm.start_checkpoint_loop(
        interval_sec=0,  # fire immediately on next iteration
        get_extra_fn=lambda: dict(_VALID_EXTRA),
    )
    # Give the loop enough time to fire at least once
    await asyncio.sleep(0.1)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert path.exists(), "Checkpoint file must have been written"
    raw = json.loads(path.read_text())
    assert "plugin_states" in raw


@pytest.mark.asyncio
async def test_start_checkpoint_loop_survives_transient_failure(tmp_path):
    """Background loop must survive transient failures and eventually write a checkpoint.

    Tests MEDIUM finding: a single transient I/O failure must not kill the loop.
    """
    path = tmp_path / "ckpt.json"
    pm = PluginStateManager(checkpoint_path=path)

    call_count = 0

    def _get_extra():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise RuntimeError("transient failure")
        return dict(_VALID_EXTRA)

    task = pm.start_checkpoint_loop(interval_sec=0, get_extra_fn=_get_extra)
    # Wait long enough for 3+ iterations
    await asyncio.sleep(0.3)

    # Task must still be running (not done) — the transient failures did not kill it
    assert not task.done(), "Loop task must still be alive after transient failures"

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # A successful checkpoint must have been written after the transient failures
    assert path.exists(), "Checkpoint must have been written after transient failures cleared"


@pytest.mark.asyncio
async def test_start_checkpoint_loop_propagates_cancellation(tmp_path):
    """CancelledError must propagate out of the loop task, not be swallowed."""
    path = tmp_path / "ckpt.json"
    pm = PluginStateManager(checkpoint_path=path)

    task = pm.start_checkpoint_loop(
        interval_sec=10,  # long interval — loop will be sleeping when cancelled
        get_extra_fn=lambda: dict(_VALID_EXTRA),
    )
    await asyncio.sleep(0.01)  # ensure task has started
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
