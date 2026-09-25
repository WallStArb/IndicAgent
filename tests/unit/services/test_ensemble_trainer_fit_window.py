"""EnsembleTrainer._process_stratum fits weights on the IC training window only.

Todo 409: the stratum covariance (cluster deflation / mean-variance solve) was fitted on
every feature_vectors bar in the stratum, holdout included, so later bars leaked into the
weights. Todo 408: quality weights were aged by the wall clock and flattened to 1/n once
the IC window was more than alpha.ensemble.weight_stale_max_days old. Both tests drive the
real _process_stratum through the same fake connection as
test_ensemble_trainer_regime_source.py.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import numpy as np

from services.ensemble_trainer import EnsembleConfig, EnsembleTrainer
from tests.unit.services.test_ensemble_trainer_regime_source import _FakeConn

_WINDOW_END = datetime(2025, 12, 24, 5, 15, tzinfo=UTC)
_WEIGHT_IDX = 6  # ensemble_weights row: (..., feature_name, raw_weight, weight, ...)


def _config() -> EnsembleConfig:
    return EnsembleConfig(
        max_feature_weight=0.90,
        effective_n_gate=1.0,
        weight_version="test",
        min_passing_features=2,
        max_cluster_corr=0.80,
        max_cluster_weight=0.60,
        meta_fdr_min_fraction=0.50,
        meta_fdr_min_cells=1,
        sharpe_floor=0.025,
        ic_input="ic_sharpe_hac",
        weight_method="ic_proportional",
        mv_condition_max=1000.0,
        sign_symmetric=False,
    )


def _ic_rows(window_end: datetime) -> list[dict]:
    def row(name: str, ic: float, lo: float, hi: float) -> dict:
        return {
            "feature_name": name,
            "ic_sharpe_hac": ic,
            "ic_shrunk": ic,
            "shrinkage_weight": 1.0,
            "ic_ci_lower": lo,
            "ic_ci_upper": hi,
            "ic_sign": 1,
            "lookahead_bars": 5,
            "training_window_end": window_end,
        }

    return [
        row("feat_a", 0.50, 0.10, 0.90),
        row("feat_b", 0.30, 0.05, 0.60),
        row("feat_c", 0.40, 0.08, 0.70),
    ]


def _pre_window_rows(n: int = 300, seed: int = 11) -> list[dict]:
    """All three features independent: no cluster, so no deflation."""
    rng = np.random.default_rng(seed)
    start = _WINDOW_END - timedelta(days=n)
    rows = []
    for i in range(n):
        a, b, c = rng.standard_normal(3)
        rows.append(
            {
                "symbol": "SPY",
                "feat_a": float(a),
                "feat_b": float(b),
                "feat_c": float(c),
                "bar_ts": start + timedelta(days=i),
            }
        )
    return rows


def _post_window_rows(n: int = 3000) -> list[dict]:
    """Bars strictly after the window end. feat_a and feat_b move together with large
    amplitude while feat_c stays independent:
    fitted on these, a and b would form one cluster and be deflated against c."""
    rng = np.random.default_rng(29)
    rows = []
    for i in range(n):
        v = 50.0 * np.sin(i / 7.0)
        rows.append(
            {
                "symbol": "SPY",
                "feat_a": v,
                "feat_b": v + 0.01,
                "feat_c": float(rng.standard_normal()),
                "bar_ts": _WINDOW_END + timedelta(days=i + 1),
            }
        )
    return rows


def _weights(ic_rows: list[dict], fv_rows: list[dict]) -> tuple[list[float], _FakeConn]:
    conn = _FakeConn(ic_rows=ic_rows, fv_rows=fv_rows)
    wrote = asyncio.run(
        EnsembleTrainer(db_dsn="postgresql://fake/fake")._process_stratum(
            conn=conn,
            tf="1d",
            regime="mid_neutral",
            feature_cols=["feat_a", "feat_b", "feat_c"],
            config=_config(),
            cfg={},
            meta_eligible_features={"feat_a", "feat_b", "feat_c"},
            training_window_end=_WINDOW_END,
        )
    )
    assert wrote is True
    return [row[_WEIGHT_IDX] for row in conn.weight_rows()], conn


def test_rows_after_the_training_window_do_not_change_the_weights() -> None:
    pre = _pre_window_rows()
    clean, _ = _weights(_ic_rows(_WINDOW_END), pre)
    with_later_rows, conn = _weights(_ic_rows(_WINDOW_END), pre + _post_window_rows())
    np.testing.assert_allclose(with_later_rows, clean, rtol=0, atol=1e-12)
    # Scoring still covers every bar, before and after the window.
    assert len(conn.alpha_rows()) == len(pre) + len(_post_window_rows())


def test_an_old_ic_window_does_not_flatten_weights_to_one_over_n() -> None:
    pre = _pre_window_rows()
    fresh, _ = _weights(_ic_rows(_WINDOW_END), pre)
    old_window = datetime.now(UTC) - timedelta(days=400)
    stale, _ = _weights(
        _ic_rows(old_window),
        [dict(r, bar_ts=r["bar_ts"] - (_WINDOW_END - old_window)) for r in pre],
    )
    assert not np.allclose(stale, 1.0 / 3)
    np.testing.assert_allclose(stale, fresh, rtol=0, atol=1e-12)
