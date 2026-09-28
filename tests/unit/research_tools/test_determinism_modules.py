"""Tests of the promoted determinism modules (phase 186-03, D-11/R-05)."""

import ast
import dataclasses
from pathlib import Path

import numpy as np
import pytest

from scripts.research.determinism.config import DEFAULT_CONFIG
from scripts.research.determinism.results import GroupArrays, Snapshot
from scripts.research.determinism.sessions import refit_dates
from scripts.research.determinism.signals import SIGNALS, tsmom
from scripts.research.determinism.snapshot_io import load_snapshot, verify_snapshot
from src.intelligence.research import store

REPO = Path(__file__).resolve().parents[3]
SLEEVE = REPO / "scripts" / "analysis" / "sleeve_walk_forward"
DETERMINISM = REPO / "scripts" / "research" / "determinism"

FORBIDDEN_PREFIXES = (
    "scripts.analysis",
    "services.ic_engine",
    "services.ensemble_trainer",
    "services.cross_sectional_regime_model",
    "asyncpg",
)

_N_SESSIONS = 6
_N_SLEEVE = 2
_N_FEATURES = 3


def _rows(n):
    return {
        "all_symbol": np.array(["AAA"] * n, dtype="U3"),
        "all_bar_ts": np.array(["2020-01-02"] * n, dtype="datetime64[D]"),
        "all_session_idx": np.arange(n),
        "all_X": np.zeros((n, _N_FEATURES), dtype="float32"),
        "all_returns": np.zeros((n, 1), dtype="float32"),
        "all_complete": np.ones((n, 1), dtype=bool),
        "all_group": np.array(["equity"] * n),
        "all_has_fr": np.ones(n, dtype=bool),
    }


def _write_minimal_snapshot(tmp_path):
    sessions = np.array(
        ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-07", "2020-01-08", "2020-01-09"],
        dtype="datetime64[D]",
    )
    arrays = {
        "sessions": sessions,
        "labels_equity": np.array(["hi", "", "", "lo", "", ""]),
        "broadcast_mask": np.zeros(_N_FEATURES, dtype=bool),
        "sleeve_features": np.zeros((_N_SESSIONS, _N_SLEEVE, _N_FEATURES), dtype="float32"),
        "sleeve_has_row": np.ones((_N_SESSIONS, _N_SLEEVE), dtype=bool),
        "sleeve_opens": np.full((_N_SESSIONS, _N_SLEEVE), 100.0),
        "sleeve_closes": np.full((_N_SESSIONS, _N_SLEEVE), 100.0),
        **_rows(_N_SESSIONS),
    }
    meta = {
        "manifest": {
            "groups": ["equity"],
            "feature_names": [f"f{i}" for i in range(_N_FEATURES)],
        },
        "feature_to_group": {f"f{i}": "equity" for i in range(_N_FEATURES)},
        "apr": {"alpha.ic.shrinkage_k": ("100", "float")},
    }
    return store.write(tmp_path, "snapshot", arrays, meta)


class TestConfig:
    def test_config_matches_sleeve_bytes(self):
        sleeve_config = SLEEVE / "config.py"
        if not sleeve_config.exists():
            pytest.skip("sleeve config removed")
        assert (DETERMINISM / "config.py").read_bytes() == sleeve_config.read_bytes()

    def test_default_config_is_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            DEFAULT_CONFIG.seed = 180


class TestRefitDates:
    def test_refit_dates_are_first_session_of_each_year(self):
        s = np.array(
            ["2010-12-30", "2010-12-31", "2011-01-03", "2011-01-04", "2012-01-03"],
            dtype="datetime64[D]",
        )
        assert refit_dates(s, range(2011, 2013)) == [
            np.datetime64("2011-01-03"),
            np.datetime64("2012-01-03"),
        ]

    def test_refit_dates_missing_year_raises(self):
        with pytest.raises(ValueError, match="2012"):
            refit_dates(np.array(["2011-01-03"], dtype="datetime64[D]"), range(2011, 2013))


class TestSignals:
    def test_tsmom_is_the_trailing_log_return(self):
        closes = np.exp(np.arange(10.0))[:, None] * np.array([[1.0, 2.0]])
        alpha = tsmom(closes, lookback=3)
        assert np.isnan(alpha[:3]).all()
        np.testing.assert_allclose(alpha[3:], 3.0)

    def test_tsmom_missing_or_bad_close_gives_no_position(self):
        closes = np.full((10, 1), 100.0)
        closes[5, 0] = np.nan
        closes[2, 0] = 0.0
        alpha = tsmom(closes, lookback=4)
        assert np.isnan(alpha[[5, 9], 0]).all()
        assert np.isnan(alpha[6, 0])
        np.testing.assert_array_equal(alpha[[4, 7, 8], 0], 0.0)

    def test_tsmom_is_causal(self):
        rng = np.random.default_rng(0)
        closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (400, 3)), axis=0))
        changed = closes.copy()
        changed[300:] *= 1.5
        np.testing.assert_array_equal(tsmom(closes)[:300], tsmom(changed)[:300])

    def test_signals_registry_has_tsmom(self):
        assert "tsmom" in SIGNALS


class TestSnapshotIo:
    def test_verify_snapshot_detects_tampering(self, tmp_path):
        path = store.write(
            tmp_path, "snapshot", {"a": np.arange(5.0), "b": np.ones(3)}, {"manifest": {}}
        )
        verify_snapshot(path)
        np.save(path / "a.npy", np.arange(5.0) + 1)
        with pytest.raises(ValueError, match="hash"):
            verify_snapshot(path)

    def test_load_snapshot_round_trips_minimal_snapshot(self, tmp_path):
        path = _write_minimal_snapshot(tmp_path)
        snap = load_snapshot(path)
        assert snap.sessions.dtype == np.dtype("datetime64[D]")
        assert snap.sessions.shape == (_N_SESSIONS,)
        assert set(snap.groups) == {"equity"}
        g = snap.groups["equity"]
        assert isinstance(g, GroupArrays)
        assert g.X.shape == (_N_SESSIONS, _N_FEATURES)
        assert g.X.dtype == np.dtype("float32")
        assert g.labels.tolist() == ["hi", "", "", "lo", "", ""]
        assert snap.all_1d.X.shape == (_N_SESSIONS, _N_FEATURES)
        assert snap.sleeve_features.shape == (_N_SESSIONS, _N_SLEEVE, _N_FEATURES)
        assert snap.sleeve_opens.dtype == np.dtype("float64")
        assert snap.sleeve_closes.shape == (_N_SESSIONS, _N_SLEEVE)
        assert snap.equity_labels.tolist() == ["hi", "", "", "lo", "", ""]
        assert snap.feature_names == [f"f{i}" for i in range(_N_FEATURES)]
        assert snap.feature_to_group == {f"f{i}": "equity" for i in range(_N_FEATURES)}
        assert snap.apr == {"alpha.ic.shrinkage_k": ("100", "float")}
        assert snap.manifest["groups"] == ["equity"]
        assert isinstance(snap, Snapshot)
        assert snap.broadcast_mask.dtype == np.dtype(bool)


class TestNoForbiddenImports:
    @pytest.mark.parametrize("py", sorted(DETERMINISM.glob("*.py")), ids=lambda p: p.name)
    def test_no_forbidden_import(self, py):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert not name.startswith(FORBIDDEN_PREFIXES), (py.name, name)
