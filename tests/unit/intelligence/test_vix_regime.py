"""Tests for VIXRegimePlugin - I4 context plugin."""
import pytest

from src.intelligence.context.vix_regime import VIXRegimePlugin


@pytest.fixture
def plugin():
    return VIXRegimePlugin()


def _make_vix_frame(ready: bool, level: float = 18.5, z_score: float = 1.2) -> dict:
    if not ready:
        return {"vix": {"ready": False}}
    return {"vix": {"ready": True, "level": level, "z_score": z_score}}


def test_returns_vix_level_and_z_when_ready(plugin):
    frames = _make_vix_frame(ready=True, level=22.0, z_score=-0.5)
    result = plugin.compute_full(frames)
    assert result["vix_level"] == 22.0
    assert result["vix_z"] == -0.5


def test_returns_empty_when_vix_not_ready(plugin):
    frames = _make_vix_frame(ready=False)
    result = plugin.compute_full(frames)
    assert result == {}


def test_returns_empty_when_vix_frame_absent(plugin):
    result = plugin.compute_full({})
    assert result == {}


def test_outputs_frozenset_correct(plugin):
    assert plugin.outputs == frozenset({"vix_level", "vix_z"})


def test_name_follows_i4_convention(plugin):
    assert plugin.name == "ctx_VIXRegime"


def test_compute_next_delegates_to_compute_full(plugin):
    frames = _make_vix_frame(ready=True, level=15.0, z_score=0.3)
    assert plugin.compute_next(frames) == plugin.compute_full(frames)


def test_none_level_passed_through(plugin):
    """If vix context returns level=None (shouldn't happen but guard it), passes through."""
    frames = {"vix": {"ready": True, "level": None, "z_score": 0.0}}
    result = plugin.compute_full(frames)
    assert result["vix_level"] is None
    assert result["vix_z"] == 0.0
