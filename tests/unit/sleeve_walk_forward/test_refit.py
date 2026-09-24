import sqlite3

import numpy as np
import pytest

from scripts.analysis.sleeve_walk_forward.config import HarnessConfig
from scripts.analysis.sleeve_walk_forward.refit import eligible, run_refit, training_arrays
from scripts.analysis.sleeve_walk_forward.results import GroupArrays, Snapshot
from services import ic_engine
from services.ensemble_trainer import _eligibility_where

FEATURES = list(ic_engine._FEATURE_NAMES)
PLANTED = (FEATURES[10], FEATURES[20])
N_SESSIONS = 700
CFG = HarnessConfig(training_start="2007-01-01")


def _group(rng, symbols, labels_by_session, sessions, planted=()):
    n_sym = len(symbols)
    t = np.repeat(np.arange(len(sessions)), n_sym)
    X = rng.standard_normal((len(t), len(FEATURES))).astype(np.float32)
    returns = rng.normal(0, 0.01, (len(t), 4))
    for name in planted:
        returns += 0.004 * X[:, [FEATURES.index(name)]]
    return GroupArrays(
        symbols=np.tile(np.array(symbols), len(sessions)),
        bar_ts=sessions[t],
        session_idx=t,
        X=X,
        returns=returns,
        complete=np.ones((len(t), 4), bool),
        labels=labels_by_session[t],
    )


def _snapshot(seed=0, min_features="2"):
    rng = np.random.default_rng(seed)
    sessions = np.busday_offset(np.datetime64("2007-01-01"), np.arange(N_SESSIONS), roll="forward")
    eq_labels = np.where((np.arange(N_SESSIONS) // 50) % 2 == 0, "hi", "lo")
    rates_labels = np.where((np.arange(N_SESSIONS) // 70) % 2 == 0, "steep", "flat")
    equity = _group(rng, [f"E{i}" for i in range(8)], eq_labels, sessions, PLANTED)
    rates = _group(rng, [f"R{i}" for i in range(4)], rates_labels, sessions)
    apr = {
        "alpha.ensemble.ic_input": ("ic_shrunk", "str"),
        "alpha.ensemble.min_passing_features": (min_features, "int"),
        # Production's switches (numba bootstrap, early stop); sizes scaled to 600 sessions.
        "alpha.ic.bootstrap_numba_kernel": ("true", "bool"),
        "alpha.ic.bootstrap_early_stop.enabled": ("true", "bool"),
        "alpha.ic.bootstrap_resamples": ("200", "int"),
        "alpha.ic.sharpe_window_size": ("50", "int"),
        "alpha.ic.sharpe_min_windows": ("10", "int"),
        "alpha.ic.sharpe_window_size_subsampled": ("20", "int"),
    }
    return Snapshot(
        sessions=sessions,
        groups={"equity": equity, "rates": rates},
        all_1d=equity,
        sleeve_features=np.zeros((N_SESSIONS, 1, len(FEATURES))),
        sleeve_has_row=np.ones((N_SESSIONS, 1), bool),
        sleeve_opens=np.ones((N_SESSIONS, 1)),
        sleeve_closes=np.ones((N_SESSIONS, 1)),
        equity_labels=eq_labels,
        feature_names=FEATURES,
        broadcast_mask=np.zeros(len(FEATURES), bool),
        feature_to_group={f: "g0" for f in FEATURES},
        apr=apr,
        manifest={},
    )


@pytest.fixture(scope="module")
def snap():
    return _snapshot()


@pytest.fixture(scope="module")
def refit(snap):
    return run_refit(snap, snap.sessions[650], CFG, frozenset())


def test_embargo_marks_late_labels_incomplete():
    g = GroupArrays(
        symbols=np.array(["A"] * 20),
        bar_ts=np.arange(20).astype("datetime64[D]"),
        session_idx=np.arange(20),
        X=np.zeros((20, 1), np.float32),
        returns=np.zeros((20, 4)),
        complete=np.ones((20, 4), bool),
        labels=np.array(["x"] * 20),
    )
    keep, complete, n_excl = training_arrays(
        g, cutoff=15, lookaheads=[1, 2, 5, 10], start_idx=0, refit_idx=14
    )
    # h=1 exit is t+2: last kept row is t=13.
    assert keep.nonzero()[0].max() == 13
    # t=10 trains h=1,2 (exits 12, 13) but not h=5,10 (exits 16, 21).
    assert complete[10].tolist() == [True, True, False, False]
    assert n_excl == sum(int(t + h + 1 > 15) for t in range(14) for h in (1, 2, 5, 10))


_PASSING = {
    "symbol": "POOLED",
    "is_pooled": True,
    "regime": "hi",
    "regime_scope": "cross_sectional",
    "ic_sign": 1,
    "ic_ci_lower": 0.1,
    "ic_ci_upper": 0.2,
    "reliable": True,
    "ic_sharpe_hac": 0.3,
    "passes_walkforward": True,
    "passes_fdr": True,
}
_ALTERNATIVES = {
    "symbol": ("SPY",),
    "is_pooled": (False, None),
    "regime": ("_pooled", None),
    "regime_scope": ("earnings_season",),
    "ic_sign": (-1,),
    "ic_ci_lower": (-0.1, None),
    "ic_ci_upper": (-0.05, None),
    "reliable": (False, None),
    "ic_sharpe_hac": (None,),
    "passes_walkforward": (False, None),
    "passes_fdr": (False, None),
}


def _random_rows(rng, n):
    """Passing rows with 0-2 fields perturbed, so both branches of every clause occur."""
    keys = list(_ALTERNATIVES)
    rows = []
    for _ in range(n):
        row = dict(_PASSING)
        for key in rng.choice(keys, size=rng.integers(0, 3), replace=False):
            options = _ALTERNATIVES[key]
            row[key] = options[rng.integers(len(options))]
        rows.append(row)
    return rows


@pytest.mark.parametrize("sign_symmetric", [False, True])
def test_eligible_matches_production_sql(sign_symmetric):
    rows = _random_rows(np.random.default_rng(7), 400)
    cols = list(rows[0])
    db = sqlite3.connect(":memory:")
    db.execute(f"CREATE TABLE t (i INTEGER, {', '.join(cols)})")
    db.executemany(
        f"INSERT INTO t VALUES (?, {', '.join('?' * len(cols))})",
        [(i, *[r[c] for c in cols]) for i, r in enumerate(rows)],
    )
    base_sql, full_sql = _eligibility_where(sign_symmetric)
    for sql, require_fdr in ((base_sql, False), (full_sql, True)):
        want = {i for (i,) in db.execute(f"SELECT i FROM t WHERE {sql}")}
        got = {
            i for i, r in enumerate(rows) if eligible(r, sign_symmetric, require_fdr=require_fdr)
        }
        assert got == want
        assert want  # the fixture exercises the passing branch


def test_planted_features_are_selected_and_weighted(refit):
    weighted = {
        f for s in refit.strata.values() for f, w in zip(s.feature_names, s.weights) if w > 0
    }
    assert set(PLANTED) <= weighted
    assert refit.n_embargo_excluded > 0


def test_refit_is_deterministic(snap, refit):
    again = run_refit(snap, snap.sessions[650], CFG, frozenset())
    assert again.strata.keys() == refit.strata.keys()
    for label, s in refit.strata.items():
        assert again.strata[label].feature_names == s.feature_names
        np.testing.assert_array_equal(again.strata[label].weights, s.weights)


def test_excluded_feature_emits_no_row_and_no_weight(snap):
    out = run_refit(snap, snap.sessions[650], CFG, frozenset({PLANTED[0]}))
    assert all(r["feature_name"] != PLANTED[0] for r in out.ic_rows)
    assert all(PLANTED[0] not in s.feature_names for s in out.strata.values())


def test_stratum_skip_reason_recorded():
    snap = _snapshot(min_features="50")
    out = run_refit(snap, snap.sessions[650], CFG, frozenset())
    assert out.strata == {}
    assert set(out.skipped.values()) <= {"min_features", "no_ic_rows"}
    assert set(out.skipped) == {"hi", "lo"}


def test_rows_on_or_after_refit_date_never_reach_the_fit(snap, refit):
    after = snap.all_1d.bar_ts >= snap.sessions[650]
    X = snap.all_1d.X.copy()
    X[after] = 1e6
    poisoned = Snapshot(
        **{**snap.__dict__, "all_1d": GroupArrays(**{**snap.all_1d.__dict__, "X": X})}
    )
    out = run_refit(poisoned, snap.sessions[650], CFG, frozenset())
    for label, s in refit.strata.items():
        np.testing.assert_array_equal(out.strata[label].weights, s.weights)


def test_embargo_assert_rejects_exits_and_unsorted_lookaheads():
    from scripts.analysis.sleeve_walk_forward.refit import assert_embargo

    t = np.array([10])
    with pytest.raises(AssertionError, match="V6"):
        assert_embargo(t, [1, 2, 5, 10], np.array([[True, True, True, False]]), cutoff=13)
    with pytest.raises(AssertionError, match="ascending"):
        assert_embargo(t, [2, 1, 5, 10], np.array([[True, False, False, False]]), cutoff=13)
    assert_embargo(t, [1, 2, 5, 10], np.array([[True, True, False, False]]), cutoff=13)


def test_embargo_count_includes_rows_dropped_whole():
    g = GroupArrays(
        symbols=np.array(["A"] * 25),
        bar_ts=np.arange(25).astype("datetime64[D]"),
        session_idx=np.arange(25),
        X=np.zeros((25, 1), np.float32),
        returns=np.zeros((25, 4)),
        complete=np.ones((25, 4), bool),
        labels=np.array(["x"] * 25),
    )
    _k, _c, n_excl = training_arrays(
        g, cutoff=15, lookaheads=[1, 2, 5, 10], start_idx=0, refit_idx=20
    )
    partial = sum(int(t + h + 1 > 15) for t in range(14) for h in (1, 2, 5, 10))
    # Rows 14..19 fall between the h=1 cutoff and the refit date: every scale is embargoed.
    # Rows 20.. are on or after the refit date, not embargo exclusions.
    assert n_excl == partial + 6 * 4


def test_control_feature_is_measured_but_never_weighted(snap):
    out = run_refit(snap, snap.sessions[650], CFG, frozenset(), controls=frozenset({PLANTED[0]}))
    assert any(r["feature_name"] == PLANTED[0] for r in out.ic_rows)
    assert all(PLANTED[0] not in s.feature_names for s in out.strata.values())


def test_fidelity_mode_trains_through_the_window_end_without_embargo(snap):
    window_end = snap.sessions[649]  # later than the embargoed run's window (session 643)
    out = run_refit(snap, snap.sessions[650], CFG, frozenset(), fidelity_window_end=window_end)
    assert out.n_embargo_excluded == 0
    assert {r["training_window_end"] for r in out.ic_rows} == {window_end}
    # Production's rule: every bar up to the window end, with its stored completeness flags.
    normal = run_refit(snap, snap.sessions[650], CFG, frozenset())
    assert max(r["n_independent"] or 0 for r in out.ic_rows) >= max(
        r["n_independent"] or 0 for r in normal.ic_rows
    )
