"""Unit tests for HMMTrainer — Phase 082, Plan 03.

Tests cover:
  1. No backfill filter: SQL must NOT contain is_backfill (column does not exist in schema)
  2. Per-symbol queries: training queries per symbol to avoid cross-instrument return contamination
  3. Per-TF parameter file writes: four JSON files written to tmp_path
  4. Parameter file schema: keys match HMMRegimePlugin._load_parameters() contract
  5. emission_variances shape: always (K, D) not (K, D, D)
  6. SIGUSR1 emit: subprocess.run called with exact systemctl args
  7. Skip on insufficient rows: below-threshold TF is not written; others proceed

All tests use mocks — no live DB or systemctl required.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

hmmlearn = pytest.importorskip("hmmlearn")  # Skip module if hmmlearn not installed

from src.intelligence.services.hmm_trainer import (  # noqa: E402
    _PIPELINE_UNIT,
    HMMTrainer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_N_TRAIN_ROWS = 600  # > _MIN_ROWS_FOR_TRAINING (500)
_TFS = ("1m", "5m", "15m", "1h", "4h", "1d")
_SYMBOLS = ("ESU6", "NQU6")


def _make_synthetic_rows(n: int, *, include_indicators: bool = True) -> list[dict]:
    """Build synthetic DB rows resembling intelligence_features query output."""
    rng = np.random.default_rng(42)
    closes = 100.0 + rng.normal(0, 0.5, n + 1).cumsum()
    rows = []
    for i in range(n + 1):
        row: dict = {
            "ts": f"2026-01-{(i % 28) + 1:02d}T{(i % 24):02d}:00:00Z",
            "close": float(closes[i]),
        }
        if include_indicators:
            row["rsi_14"] = float(rng.uniform(20, 80))
            row["adx_14"] = float(rng.uniform(10, 50))
            row["atr_14"] = float(rng.uniform(0.5, 3.0))
            row["macd_hist"] = float(rng.normal(0, 0.2))
        else:
            row["rsi_14"] = None
            row["adx_14"] = None
            row["atr_14"] = None
            row["macd_hist"] = None
        rows.append(row)
    return rows


def _make_db_manager(
    rows_by_tf: dict[str, list[dict]], symbols: tuple[str, ...] = _SYMBOLS
) -> MagicMock:
    """Build a mock db_manager that handles the two-phase per-symbol query pattern.

    Phase 1: SELECT DISTINCT symbol → returns mock symbol records
    Phase 2: Per-symbol query (3 params: tf, symbol, since) → returns rows for that tf
    """

    class _FakeConn:
        async def fetch(self, sql: str, *args) -> list:
            if "DISTINCT symbol" in sql:
                # Phase 1: return symbol list
                return [{"symbol": s} for s in symbols]
            # Phase 2: per-symbol fetch — args = (tf, symbol, since)
            tf = args[0] if args else None
            return rows_by_tf.get(tf, [])

    @asynccontextmanager
    async def _acquire():
        yield _FakeConn()

    mock_pool = MagicMock()
    mock_pool.acquire = _acquire
    mock_db = MagicMock()
    mock_db.pool = mock_pool
    return mock_db


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.database_url = "postgresql://localhost/indicagent"
    return settings


def _make_default_cfg() -> MagicMock:
    """Return a ConfigService mock that returns the APR default values for all HMM keys."""
    from src.config.config_service import ConfigService

    mock_cfg = MagicMock(spec=ConfigService)
    _defaults: dict[str, object] = {
        "feature.hmm.n_components": 3,
        "feature.hmm.n_iter": 50,
        "feature.hmm.min_rows_for_training": 500,
        "feature.hmm.vol_window": 20,
        **{
            f"feature.hmm.lookback_days.{tf}": days
            for tf, days in {
                "1m": 30,
                "5m": 60,
                "15m": 90,
                "1h": 180,
                "4h": 365,
                "1d": 730,
            }.items()
        },
    }
    mock_cfg.get = AsyncMock(side_effect=lambda key, default=None: _defaults.get(key, default))
    return mock_cfg


def _run_trainer(db: MagicMock, tmp_path: Path, tfs: tuple[str, ...] = _TFS) -> dict[str, str]:
    import src.intelligence.services.hmm_trainer as _mod

    original = _mod._CONFIG_DIR
    _mod._CONFIG_DIR = tmp_path
    try:
        agent = HMMTrainer(db_manager=db, settings=_make_settings(), target_tfs=tfs)
        agent._config_service = _make_default_cfg()
        return asyncio.run(agent.run())
    finally:
        _mod._CONFIG_DIR = original


# ---------------------------------------------------------------------------
# Test 1: No is_backfill filter in SQL (column doesn't exist in schema)
# ---------------------------------------------------------------------------


def test_query_does_not_filter_backfill() -> None:
    """_query_features SQL must NOT reference is_backfill (column does not exist).

    The intelligence_features table has no is_backfill column. The corpus is
    predominantly backfill data. Filtering on is_backfill causes a DB error and
    silently returns zero rows, preventing training.
    """
    source = inspect.getsource(HMMTrainer._query_features)
    assert "is_backfill" not in source, (
        "is_backfill found in _query_features SQL — column does not exist in "
        "intelligence_features; filtering on it silently prevents training"
    )


# ---------------------------------------------------------------------------
# Test 2: Per-symbol query — symbol appears in SQL
# ---------------------------------------------------------------------------


def test_query_filters_by_symbol() -> None:
    """_query_features SQL must contain a symbol filter to prevent cross-instrument contamination."""
    source = inspect.getsource(HMMTrainer._query_features)
    assert "symbol" in source, "symbol filter not found in _query_features SQL"


# ---------------------------------------------------------------------------
# Test 3: Per-TF parameter files written under config dir
# ---------------------------------------------------------------------------


def test_writes_per_tf_parameter_files(tmp_path: Path) -> None:
    """run() writes hmm_parameters_{tf}.json for each TF with enough data."""
    rows = _make_synthetic_rows(_N_TRAIN_ROWS)
    db = _make_db_manager({tf: rows for tf in _TFS})
    written = _run_trainer(db, tmp_path)

    for tf in _TFS:
        expected = tmp_path / f"hmm_parameters_{tf}.json"
        assert expected.exists(), f"Parameter file missing for tf={tf}: {expected}"
    assert set(written.keys()) == set(_TFS), f"Expected all TFs written, got: {set(written.keys())}"


# ---------------------------------------------------------------------------
# Test 4: Parameter file schema — keys and shapes
# ---------------------------------------------------------------------------


def test_parameter_file_schema(tmp_path: Path) -> None:
    """Written JSON has correct keys and transition matrix shape."""
    rows = _make_synthetic_rows(_N_TRAIN_ROWS)
    db = _make_db_manager({"1m": rows})
    _run_trainer(db, tmp_path, tfs=("1m",))

    param_file = tmp_path / "hmm_parameters_1m.json"
    assert param_file.exists(), "Parameter file not written for 1m"

    data = json.loads(param_file.read_text())

    assert "transition_matrix" in data
    assert "emission_means" in data
    assert "emission_variances" in data

    tm = data["transition_matrix"]
    assert len(tm) == 3
    for row in tm:
        assert len(row) == 3

    em = data["emission_means"]
    assert len(em) == 3

    ev = data["emission_variances"]
    assert len(ev) == 3


# ---------------------------------------------------------------------------
# Test 5: emission_variances shape is (K, D) not (K, D, D)
# ---------------------------------------------------------------------------


def test_emission_variances_is_2d(tmp_path: Path) -> None:
    """emission_variances must be (K, D) not (K, D, D).

    hmmlearn may return covars_ as (K, D, D) full matrix for 'diag' covariance.
    The trainer must extract the diagonal before writing so the HMM plugin's
    _forward_step can slice [:, :n_dims] correctly.
    """
    rows = _make_synthetic_rows(_N_TRAIN_ROWS)
    db = _make_db_manager({"1m": rows})
    _run_trainer(db, tmp_path, tfs=("1m",))

    data = json.loads((tmp_path / "hmm_parameters_1m.json").read_text())
    ev = np.array(data["emission_variances"])
    assert ev.ndim == 2, f"emission_variances must be 2D (K, D), got shape {ev.shape}"
    assert ev.shape[0] == 3, f"Expected 3 components, got {ev.shape[0]}"


# ---------------------------------------------------------------------------
# Test 6: emit_sigusr1 calls systemctl with exact args
# ---------------------------------------------------------------------------


def test_emit_sigusr1_invokes_systemctl() -> None:
    """emit_sigusr1() invokes systemctl kill --signal=SIGUSR1 <unit>."""
    db = _make_db_manager({})
    agent = HMMTrainer(db_manager=db, settings=_make_settings())

    with (
        patch("src.intelligence.services.hmm_trainer.subprocess.run") as mock_run,
        patch.object(HMMTrainer, "_find_systemctl", return_value="/usr/bin/systemctl"),
    ):
        mock_run.return_value = MagicMock(returncode=0, stderr=b"")
        agent.emit_sigusr1()

    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]

    assert "systemctl" in call_args[0], f"Expected systemctl, got {call_args[0]}"
    assert "kill" in call_args, f"Expected 'kill' in args: {call_args}"
    assert "--signal=SIGUSR1" in call_args, f"Expected --signal=SIGUSR1 in args: {call_args}"
    assert _PIPELINE_UNIT in call_args, f"Expected {_PIPELINE_UNIT!r} in args: {call_args}"


# ---------------------------------------------------------------------------
# Test 7: Skip when insufficient rows
# ---------------------------------------------------------------------------


def test_skip_when_insufficient_rows(tmp_path: Path) -> None:
    """TF with < _MIN_ROWS_FOR_TRAINING rows is skipped; other TFs proceed normally."""
    too_few = _make_synthetic_rows(10)
    enough = _make_synthetic_rows(_N_TRAIN_ROWS)

    rows_by_tf = {
        "1m": too_few,
        "5m": enough,
        "15m": enough,
        "1h": enough,
    }
    db = _make_db_manager(rows_by_tf)
    written = _run_trainer(db, tmp_path)

    assert "1m" not in written, "1m should have been skipped (too few rows)"
    assert not (tmp_path / "hmm_parameters_1m.json").exists()

    for tf in ("5m", "15m", "1h"):
        assert tf in written, f"{tf} should have been written"
        assert (tmp_path / f"hmm_parameters_{tf}.json").exists(), f"{tf} param file missing"


# ---------------------------------------------------------------------------
# Test 7: APR config loading
# ---------------------------------------------------------------------------


def test_hmm_trainer_reads_apr_config(tmp_path: Path) -> None:
    """HMMTrainer must load n_components, n_iter, min_rows, vol_window from APR.

    When _config_service is injected, training uses APR values instead of
    module-level constants.
    """
    from src.config.config_service import ConfigService

    rows = _make_synthetic_rows(_N_TRAIN_ROWS)
    db = _make_db_manager({"1m": rows})

    # Build a ConfigService with known values that differ from defaults
    mock_cfg = MagicMock(spec=ConfigService)
    mock_cfg.get = AsyncMock(
        side_effect=lambda key, default=None: {
            "feature.hmm.n_components": 3,
            "feature.hmm.n_iter": 10,  # reduced — faster test
            "feature.hmm.min_rows_for_training": 50,
            "feature.hmm.vol_window": 10,
            "feature.hmm.lookback_days.1m": 30,
            "feature.hmm.lookback_days.5m": 60,
            "feature.hmm.lookback_days.15m": 90,
            "feature.hmm.lookback_days.1h": 180,
            "feature.hmm.lookback_days.4h": 365,
            "feature.hmm.lookback_days.1d": 730,
        }.get(key, default)
    )

    import src.intelligence.services.hmm_trainer as _mod

    original = _mod._CONFIG_DIR
    _mod._CONFIG_DIR = tmp_path
    try:
        agent = HMMTrainer(db_manager=db, settings=_make_settings(), target_tfs=("1m",))
        agent._config_service = mock_cfg
        written = asyncio.run(agent.run())
    finally:
        _mod._CONFIG_DIR = original

    assert "1m" in written, "1m should have been written when APR config is injected"
    mock_cfg.get.assert_any_call("feature.hmm.n_iter", 50)
