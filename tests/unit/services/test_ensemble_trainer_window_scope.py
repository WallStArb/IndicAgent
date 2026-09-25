"""Todo 405: every EnsembleTrainer feature_ic_scores read is pinned to one training window."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from services.ensemble_trainer import (
    EnsembleConfig,
    EnsembleTrainer,
    _resolve_training_window_end,
    _window_scoped,
)

_W = datetime(2025, 12, 24, 5, 15, tzinfo=UTC)
_W2 = datetime(2026, 12, 24, 5, 15, tzinfo=UTC)


class _Conn:
    """Records SQL; fetch answers the DISTINCT-window probe with `windows`, else []."""

    def __init__(self, windows: list[datetime] | None = None) -> None:
        self.windows = windows or []
        self.sql: list[str] = []

    async def fetch(self, sql: str, *args):
        self.sql.append(sql)
        if "DISTINCT training_window_end" in sql:
            return [{"training_window_end": w} for w in self.windows]
        return []


def test_window_scoped_appends_an_exact_utc_equality():
    assert _window_scoped("a = 1", _W) == (
        "a = 1 AND training_window_end = '2025-12-24T05:15:00+00:00'::timestamptz"
    )


def test_cli_window_wins_without_a_query():
    conn = _Conn([_W, _W2])
    assert asyncio.run(_resolve_training_window_end(conn, False, _W2)) == _W2
    assert conn.sql == []


def test_the_only_eligible_window_is_used():
    assert asyncio.run(_resolve_training_window_end(_Conn([_W]), False, None)) == _W


def test_two_eligible_windows_raise_instead_of_mixing():
    with pytest.raises(RuntimeError, match="2 training windows"):
        asyncio.run(_resolve_training_window_end(_Conn([_W, _W2]), True, None))


def test_no_eligible_rows_defers_to_the_startup_gate():
    assert asyncio.run(_resolve_training_window_end(_Conn([]), False, None)) is None


def test_stratum_ic_read_is_window_scoped():
    conn = _Conn()
    config = EnsembleConfig(
        max_feature_weight=0.9,
        effective_n_gate=1.0,
        weight_version="test",
        min_passing_features=2,
        max_cluster_corr=0.8,
        max_cluster_weight=0.6,
        meta_fdr_min_fraction=0.5,
        meta_fdr_min_cells=1,
        sharpe_floor=0.025,
        ic_input="ic_sharpe_hac",
        weight_method="ic_proportional",
        mv_condition_max=1000.0,
        sign_symmetric=False,
    )
    wrote = asyncio.run(
        EnsembleTrainer(db_dsn="postgresql://fake/fake")._process_stratum(
            conn=conn,
            tf="1d",
            regime="mid_neutral",
            feature_cols=["feat_a"],
            config=config,
            cfg={},
            meta_eligible_features={"feat_a"},
            training_window_end=_W,
        )
    )
    assert wrote is False  # no IC rows from the fake
    assert "training_window_end = '2025-12-24T05:15:00+00:00'::timestamptz" in conn.sql[0]
