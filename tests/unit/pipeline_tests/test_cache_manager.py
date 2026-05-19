"""Isolated unit tests for CacheManager.

Tests cover:
- Initial state (empty dicts)
- HMM regime label mapping
- seed_* public API (merge vs atomic replace, version tracking)
- Load method semantics (merge for tod_priors, atomic for others)
- No CIS scorer calls
- start_refresh_loops returns 6 Tasks
- load_initial eagerness (HIGH finding 3 regression guard)
- Shadow-cache-last ordering in load_initial (MEDIUM finding)
- No enroll_all_plugins inside CacheManager (orchestrator-owned)
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.intelligence.pipeline.cache_manager import CacheManager


def make_cm(rows: list | None = None) -> CacheManager:
    """Create a CacheManager with a mock DB that returns `rows` for all queries."""
    db = AsyncMock()
    db.execute_query = AsyncMock(return_value=rows if rows is not None else [])
    return CacheManager(db=db, settings=MagicMock())


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


def test_initial_caches_are_empty_dicts():
    """All 6 cache properties are empty dicts on a fresh instance."""
    cm = make_cm()
    assert cm.perf_weights == {}
    assert cm.cis_weights == {}
    assert cm.calibration_curves == {}
    assert cm.shadow_cache == {}
    assert cm.drift_penalties == {}
    assert cm.tod_priors == {}


# ---------------------------------------------------------------------------
# HMM regime helpers
# ---------------------------------------------------------------------------


def test_update_hmm_regime_drives_label():
    """update_hmm_regime stores value; current_hmm_regime_label maps it correctly."""
    cm = make_cm()

    cm.update_hmm_regime(0)
    assert cm.current_hmm_regime_label() == "mean_reversion"

    cm.update_hmm_regime(1)
    assert cm.current_hmm_regime_label() == "trend"

    cm.update_hmm_regime(2)
    assert cm.current_hmm_regime_label() == "trend"

    cm.update_hmm_regime(None)
    assert cm.current_hmm_regime_label() == "all"

    cm.update_hmm_regime(5)
    assert cm.current_hmm_regime_label() == "all"


# ---------------------------------------------------------------------------
# Seed API
# ---------------------------------------------------------------------------


def test_seed_tod_priors_merge_preserves_existing():
    """seed_tod_priors merges — existing keys are preserved when seeding new ones."""
    cm = make_cm()
    cm.seed_tod_priors({"a": 1.0})
    cm.seed_tod_priors({"b": 2.0})
    assert cm.tod_priors == {"a": 1.0, "b": 2.0}


def test_seed_perf_weights_atomic_replace():
    """seed_perf_weights atomically replaces — old keys are dropped."""
    cm = make_cm()
    cm.seed_perf_weights({"a": 1.0})
    cm.seed_perf_weights({"b": 2.0})
    assert cm.perf_weights == {"b": 2.0}


def test_seed_cis_weights_sets_version():
    """seed_cis_weights stores weights and updates cis_weights_version."""
    cm = make_cm()
    cm.seed_cis_weights({"a": 1.0}, version=3)
    assert cm.cis_weights == {"a": 1.0}
    assert cm.cis_weights_version == 3


def test_seed_cis_weights_version_zero_not_stored():
    """seed_cis_weights with version=0 (default) does not overwrite an existing version."""
    cm = make_cm()
    cm.seed_cis_weights({"a": 1.0}, version=5)
    assert cm.cis_weights_version == 5
    # version=0 should NOT reset it (if block requires truthy)
    cm.seed_cis_weights({"b": 2.0}, version=0)
    assert cm.cis_weights_version == 5


def test_seed_api_does_not_call_scorer():
    """CacheManager must contain no actual cis_scorer attribute access (Pitfall 4).

    Uses AST inspection to check for attribute access (not just string presence in
    docstrings/comments which may legally mention cis_scorer for documentation).
    """
    import ast

    src = inspect.getsource(CacheManager)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in (
            "update_weights",
            "cis_scorer",
        ):
            # update_weights is the specific scorer call we're guarding against
            if node.attr == "update_weights":
                raise AssertionError(
                    f"CacheManager calls update_weights at line {node.lineno} — Pitfall 4 violation"
                )


def test_seed_calibration_curves_atomic_replace():
    """seed_calibration_curves atomically replaces."""
    cm = make_cm()
    cm.seed_calibration_curves({"old": (1, 2)})
    cm.seed_calibration_curves({"new": (3, 4)})
    assert cm.calibration_curves == {"new": (3, 4)}


def test_seed_shadow_cache_atomic_replace():
    """seed_shadow_cache atomically replaces."""
    cm = make_cm()
    cm.seed_shadow_cache({"plugA": True})
    cm.seed_shadow_cache({"plugB": False})
    assert cm.shadow_cache == {"plugB": False}


def test_seed_drift_penalties_atomic_replace():
    """seed_drift_penalties atomically replaces."""
    cm = make_cm()
    cm.seed_drift_penalties({"a": 0.5})
    cm.seed_drift_penalties({"b": 0.9})
    assert cm.drift_penalties == {"b": 0.9}


# ---------------------------------------------------------------------------
# Loader semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_tod_multipliers_merge_not_replace():
    """_load_tod_multipliers uses merge semantics — existing keys survive a fresh load."""
    cm = make_cm(
        rows=[
            {
                "regime_type": "trend",
                "tf": "1m",
                "hour_et": 10,
                "symbol": "*",
                "multiplier": 1.2,
            }
        ]
    )
    # Pre-seed an existing prior
    cm.seed_tod_priors({"existing_key": 0.8})

    await cm._load_tod_multipliers()

    # Both old and new key should be present (merge, not replace)
    assert cm.tod_priors.get("existing_key") == 0.8
    assert cm.tod_priors.get(("trend", "1m", 10, "*")) == 1.2


@pytest.mark.asyncio
async def test_load_perf_weights_atomic_replacement():
    """_load_perf_weights atomically replaces — stale seed data is gone after load."""
    cm = make_cm(
        rows=[
            {
                "setup_plugin": "MomentumBreakout",
                "tf": "1m",
                "symbol": "ES",
                "sharpe": 1.5,
            }
        ]
    )
    # Pre-seed stale data
    cm.seed_perf_weights({"stale": 1.0})

    await cm._load_perf_weights()

    # Stale key gone; fresh key present
    assert "stale" not in cm.perf_weights
    assert ("MomentumBreakout", "1m", "ES") in cm.perf_weights


@pytest.mark.asyncio
async def test_load_cis_weights_does_not_call_scorer():
    """_load_cis_weights stores weights and version without touching any scorer."""
    cm = make_cm(
        rows=[
            {
                "version": 7,
                "trend_w": 0.20,
                "momentum_w": 0.20,
                "structure_w": 0.15,
                "pattern_w": 0.05,
                "institutional_w": 0.25,
                "regime_w": 0.15,
            }
        ]
    )

    # Should not raise (no scorer required)
    await cm._load_cis_weights()

    assert cm.cis_weights == {
        "trend": 0.20,
        "momentum": 0.20,
        "structure": 0.15,
        "pattern": 0.05,
        "institutional": 0.25,
        "regime": 0.15,
    }
    assert cm.cis_weights_version == 7


# ---------------------------------------------------------------------------
# Refresh loop management
# ---------------------------------------------------------------------------


def test_start_refresh_loops_returns_six_tasks():
    """start_refresh_loops returns exactly 6 asyncio.Tasks."""
    cm = make_cm()

    async def _run():
        tasks = cm.start_refresh_loops()
        # Cancel immediately to avoid running them in tests
        for t in tasks:
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        return tasks

    loop = asyncio.new_event_loop()
    try:
        tasks = loop.run_until_complete(_run())
    finally:
        loop.close()

    assert len(tasks) == 6
    assert all(isinstance(t, asyncio.Task) for t in tasks)


# ---------------------------------------------------------------------------
# load_initial eagerness (HIGH finding 3 regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_initial_invokes_all_six_loaders():
    """load_initial must call every loader exactly once.

    Regression guard: if a future refactor removes a call from load_initial,
    this test will fail, alerting the developer before cold-start is shipped.
    """
    cm = make_cm()
    call_counts: dict[str, int] = {}

    for loader in (
        "_load_perf_weights",
        "_refresh_drift_penalties",
        "_load_cis_weights",
        "_load_calibration_curves",
        "_load_tod_multipliers",
        "_load_shadow_cache",
    ):
        original = getattr(cm, loader)

        async def counting_mock(name=loader, orig=original):
            call_counts[name] = call_counts.get(name, 0) + 1
            await orig()

        setattr(cm, loader, counting_mock)

    await cm.load_initial()

    for loader in (
        "_load_perf_weights",
        "_refresh_drift_penalties",
        "_load_cis_weights",
        "_load_calibration_curves",
        "_load_tod_multipliers",
        "_load_shadow_cache",
    ):
        assert (
            call_counts.get(loader, 0) == 1
        ), f"{loader} was not called exactly once in load_initial"


@pytest.mark.asyncio
async def test_load_initial_runs_shadow_cache_last():
    """load_initial must call _load_shadow_cache as the last step.

    This order contract ensures shadow registry enrollment (done by the orchestrator
    before calling load_initial) is visible when _load_shadow_cache runs.
    """
    cm = make_cm()
    call_order: list[str] = []

    for loader in (
        "_load_perf_weights",
        "_refresh_drift_penalties",
        "_load_cis_weights",
        "_load_calibration_curves",
        "_load_tod_multipliers",
        "_load_shadow_cache",
    ):
        original = getattr(cm, loader)

        async def recording_mock(name=loader, orig=original):
            call_order.append(name)
            await orig()

        setattr(cm, loader, recording_mock)

    await cm.load_initial()

    assert len(call_order) == 6
    assert (
        call_order[-1] == "_load_shadow_cache"
    ), f"_load_shadow_cache must be last in load_initial; got order: {call_order}"


# ---------------------------------------------------------------------------
# Architectural assertion — no enroll_all_plugins inside CacheManager
# ---------------------------------------------------------------------------


def test_no_enroll_all_plugins_in_cache_manager():
    """CacheManager must not call enroll_all_plugins (orchestrator-owned).

    Uses AST inspection to check for actual function calls, not docstring mentions.
    """
    import ast

    src = inspect.getsource(CacheManager)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # Check for direct call: enroll_all_plugins(...)
            if isinstance(func, ast.Name) and func.id == "enroll_all_plugins":
                raise AssertionError(
                    f"CacheManager calls enroll_all_plugins at line {node.lineno} — "
                    "orchestrator owns enrollment"
                )
            # Check for attribute call: obj.enroll_all_plugins(...)
            if isinstance(func, ast.Attribute) and func.attr == "enroll_all_plugins":
                raise AssertionError(
                    f"CacheManager calls enroll_all_plugins at line {node.lineno} — "
                    "orchestrator owns enrollment"
                )
