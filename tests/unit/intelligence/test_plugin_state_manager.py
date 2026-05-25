"""Regression tests for PluginStateManager — Phase 106 index parity.

Tests prove:
- _states_by_key stays consistent with _plugin_states across update/update_batch/restore
- get_all_states_for returns the same result as the old O(N) scan
- Index is rebuilt after checkpoint restore and is never serialized
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from src.intelligence.pipeline.state_manager import PluginStateManager


def _brute_force_scan(mgr: PluginStateManager, symbol: str, tf: str) -> dict[str, dict]:
    """Reference implementation: O(N) scan over _plugin_states.

    This is the pre-106-04 implementation. Tests assert the new O(1) index
    returns identical results.
    """
    return {
        plugin_name: state
        for (plugin_name, s, t), state in mgr._plugin_states.items()
        if s == symbol and t == tf
    }


def _make_manager() -> PluginStateManager:
    """Create a PluginStateManager with a temp checkpoint path."""
    tmp = Path(tempfile.mkdtemp()) / "checkpoint.json"
    return PluginStateManager(checkpoint_path=tmp)


# ---------------------------------------------------------------------------
# Index parity after update / update_batch
# ---------------------------------------------------------------------------


def test_index_matches_scan_after_update():
    """get_all_states_for returns identical result to brute-force scan after update()."""
    mgr = _make_manager()

    combos = [
        (("rsi", "ES", "1m"), {"val": 55.0}),
        (("macd", "ES", "1m"), {"histogram": 0.1}),
        (("rsi", "ES", "5m"), {"val": 60.0}),
        (("rsi", "NQ", "1m"), {"val": 45.0}),
        (("bollinger", "NQ", "1m"), {"upper": 100.0}),
    ]
    for key, state in combos:
        mgr.update(key, state)

    for symbol, tf in [("ES", "1m"), ("ES", "5m"), ("NQ", "1m"), ("MISSING", "1m")]:
        index_result = mgr.get_all_states_for(symbol, tf)
        scan_result = _brute_force_scan(mgr, symbol, tf)
        assert (
            index_result == scan_result
        ), f"Mismatch for ({symbol}, {tf}): index={index_result} scan={scan_result}"


def test_index_matches_scan_after_update_batch():
    """get_all_states_for returns identical result after update_batch()."""
    mgr = _make_manager()

    batch = {
        ("rsi", "ES", "1m"): {"val": 55.0},
        ("macd", "ES", "1m"): {"histogram": 0.1},
        ("rsi", "ES", "5m"): {"val": 60.0},
        ("adx", "NQ", "15m"): {"val": 30.0},
    }
    mgr.update_batch(batch)

    for symbol, tf in [("ES", "1m"), ("ES", "5m"), ("NQ", "15m"), ("MISSING", "5m")]:
        index_result = mgr.get_all_states_for(symbol, tf)
        scan_result = _brute_force_scan(mgr, symbol, tf)
        assert index_result == scan_result


def test_index_rebuilt_on_restore():
    """After checkpoint restore, _states_by_key is rebuilt and equals the scan.

    Also asserts:
    - Serialized checkpoint does NOT contain _states_by_key
    - Index size matches number of unique (symbol, tf) keys in _plugin_states
    """
    mgr = _make_manager()

    entries = {
        ("rsi", "ES", "1m"): {"val": 55.0},
        ("macd", "ES", "1m"): {"histogram": 0.1},
        ("rsi", "NQ", "5m"): {"val": 70.0},
        ("bollinger", "NQ", "5m"): {"upper": 105.0},
    }
    mgr.update_batch(entries)
    mgr.write_checkpoint(extra_state={})

    # Verify _states_by_key is NOT in the checkpoint file
    payload = json.loads(mgr._checkpoint_path.read_text())
    assert "_states_by_key" not in payload, "_states_by_key must not be serialized"

    # Simulate restore into a fresh manager
    mgr2 = PluginStateManager(checkpoint_path=mgr._checkpoint_path)

    import asyncio

    asyncio.run(mgr2.read_checkpoint())

    # Index should be rebuilt and match scan
    for symbol, tf in [("ES", "1m"), ("NQ", "5m"), ("MISSING", "1m")]:
        assert mgr2.get_all_states_for(symbol, tf) == _brute_force_scan(mgr2, symbol, tf)

    # Index size must equal number of unique (symbol, tf) keys
    unique_sym_tf = {(sym, tf) for (_, sym, tf) in mgr2._plugin_states}
    assert len(mgr2._states_by_key) == len(unique_sym_tf), (
        f"Index has {len(mgr2._states_by_key)} entries but "
        f"_plugin_states has {len(unique_sym_tf)} unique (symbol, tf) keys"
    )


def test_get_all_states_empty_key():
    """get_all_states_for returns empty dict for unknown (symbol, tf)."""
    mgr = _make_manager()
    mgr.update(("rsi", "ES", "1m"), {"val": 50.0})

    result = mgr.get_all_states_for("NONE", "1m")
    assert result == {}


def test_index_stays_consistent_on_overwrite():
    """Overwriting the same key updates both _plugin_states and _states_by_key."""
    mgr = _make_manager()

    key = ("rsi", "ES", "1m")
    mgr.update(key, {"val": 50.0})
    mgr.update(key, {"val": 60.0})  # overwrite

    assert mgr.get_state(key) == {"val": 60.0}
    assert mgr.get_all_states_for("ES", "1m") == {"rsi": {"val": 60.0}}
    assert mgr._states_by_key[("ES", "1m")]["rsi"] == {"val": 60.0}

    # No delete/clear/reset methods exist in 106-04 — single-key overwrite is the
    # primary mutation path. If such methods are added in future phases, extend this
    # test to assert both dicts stay consistent on deletion.
