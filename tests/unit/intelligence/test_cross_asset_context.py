"""Tests for CrossAssetContextPlugin - I4 macro context plugin."""
import pytest
from src.intelligence.context.cross_asset_context import CrossAssetContextPlugin


@pytest.fixture
def plugin():
    return CrossAssetContextPlugin()


def _xa_frame(ready: bool, active_pair: str = "ES_NQ",
               es_nq_spread_z: float = 1.5, es_rty_spread_z: float = -0.8,
               pairs_confirming: int = 2) -> dict:
    if not ready:
        return {"cross_asset": {"ready": False}}
    return {"cross_asset": {
        "ready": True,
        "active_pair": active_pair,
        "es_nq_spread_z": es_nq_spread_z,
        "es_rty_spread_z": es_rty_spread_z,
        "pairs_confirming": pairs_confirming,
    }}


def test_returns_eq_fields_when_ready_es_nq(plugin):
    frames = _xa_frame(ready=True, active_pair="ES_NQ", es_nq_spread_z=2.1, pairs_confirming=2)
    result = plugin.compute_full(frames)
    assert result["eq_spread_z"] == 2.1
    assert result["eq_pairs_confirming"] == 2.0


def test_returns_eq_fields_when_ready_es_rty(plugin):
    frames = _xa_frame(ready=True, active_pair="ES_RTY", es_rty_spread_z=-1.3, pairs_confirming=1)
    result = plugin.compute_full(frames)
    assert result["eq_spread_z"] == -1.3
    assert result["eq_pairs_confirming"] == 1.0


def test_returns_empty_when_not_ready(plugin):
    frames = _xa_frame(ready=False)
    assert plugin.compute_full(frames) == {}


def test_returns_empty_when_frame_absent(plugin):
    assert plugin.compute_full({}) == {}


def test_pairs_confirming_none_when_key_missing(plugin):
    """Missing pairs_confirming key -> None, not 0.0 (0.0 is a valid count value)."""
    frames = {"cross_asset": {"ready": True, "active_pair": "ES_NQ",
                               "es_nq_spread_z": 1.0}}
    result = plugin.compute_full(frames)
    assert result["eq_pairs_confirming"] is None


def test_outputs_frozenset_correct(plugin):
    assert plugin.outputs == frozenset({"eq_spread_z", "eq_pairs_confirming"})


def test_name_follows_i4_convention(plugin):
    assert plugin.name == "ctx_CrossAssetContext"


def test_compute_next_delegates(plugin):
    frames = _xa_frame(ready=True)
    assert plugin.compute_next(frames) == plugin.compute_full(frames)
