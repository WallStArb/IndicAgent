from collections import Counter

import numpy as np

from src.intelligence.research.factors import (
    VINTAGE_1,
    FactorSpec,
    leave_one_out_mean,
    neutralize,
    residual_returns,
)
from src.intelligence.research.panel import fwd_span

SPEC = FactorSpec(window_sessions=120, refit_sessions=10, n_components=2, min_finite_sessions=60)
# Groups of 20: a leave-one-out group mean averages 19 other names, so the other names'
# idiosyncratic noise it carries into a residual is small (about 1/19 of a name's variance).
LABELS = tuple(["a"] * 20 + ["b"] * 20 + ["c"] * 20 + ["d"] * 20 + ["solo"])


def _structured(seed: int, n: int = 600):
    """Returns = beta_m * market + beta_s * sector + gamma * hidden + idiosyncratic."""
    rng = np.random.default_rng(seed)
    m = len(LABELS)
    market = rng.normal(0, 0.010, n)
    sectors = {g: rng.normal(0, 0.008, n) for g in set(LABELS)}
    hidden = rng.normal(0, 0.008, n)  # a style factor only the PCs can see
    beta_m = rng.uniform(0.5, 1.5, m)
    beta_s = rng.uniform(0.5, 1.5, m)
    gamma = rng.normal(0, 1.0, m)
    idio = rng.normal(0, 0.004, (n, m))
    sector_ret = np.column_stack([sectors[g] for g in LABELS])
    sector_ret[:, -1] = 0.0  # the solo name has no sector exposure
    r = market[:, None] * beta_m + sector_ret * beta_s + hidden[:, None] * gamma + idio
    return r, idio


def test_spec_is_pinned():
    assert VINTAGE_1 == FactorSpec(252, 21, 5, 126, 5)
    assert VINTAGE_1.factor_names == ("market", "group", "pc1", "pc2", "pc3", "pc4", "pc5")


def test_leave_one_out_mean_excludes_own_value():
    x = np.array([[1.0, 2.0, 3.0, np.nan]])
    out = leave_one_out_mean(x, np.array([0, 0, 0, 0]))
    np.testing.assert_allclose(out[0, :3], [2.5, 2.0, 1.5])
    np.testing.assert_allclose(out[0, 3], 2.0)  # a missing name still has a factor value


def test_recovers_idiosyncratic_returns():
    r, idio = _structured(0)
    res = residual_returns(r, spec=SPEC)
    live = np.isfinite(res.residual).all(axis=1)
    assert live.sum() > 400
    rho = np.array(
        [np.corrcoef(res.residual[live, i], idio[live, i])[0, 1] for i in range(r.shape[1])]
    )
    # A sanity bound, not a calibration: clusters split each planted 20-name sector into
    # subgroups of about 6 (a leave-one-out mean over fewer names carries more of their noise),
    # and a 120-row window with a hidden cross-cutting factor misassigns the odd name. The
    # method itself was chosen on real data (FactorSpec docstring).
    assert np.median(rho) > 0.85 and rho.min() > 0.4, rho
    # Raw returns are dominated by common factors; residuals are not.
    raw_corr = np.corrcoef(r[live].T)[np.triu_indices(r.shape[1], 1)].mean()
    res_corr = np.corrcoef(res.residual[live].T)[np.triu_indices(r.shape[1], 1)].mean()
    assert raw_corr > 0.3 and abs(res_corr) < 0.05


def test_bar_returns_are_causal():
    r, _ = _structured(1)
    base = residual_returns(r, spec=SPEC).residual
    for t in (130, 287, 450):
        moved = r.copy()
        moved[t + 1 :] *= -3.0
        out = residual_returns(moved, spec=SPEC).residual
        np.testing.assert_array_equal(out[: t + 1], base[: t + 1])


def test_forward_window_never_enters_a_loading():
    # A forward return at row s is known only at s + lag: rows in (t - lag, t) must not move
    # the residual at t, whatever they hold; row t itself is the target being residualized.
    r, _ = _structured(2)
    horizon = 2
    lag = fwd_span(horizon)
    base = residual_returns(r, spec=SPEC, horizon=horizon).residual
    for t in (180, 313, 520):
        moved = r.copy()
        moved[t - lag + 1 : t] *= -5.0
        moved[t + 1 :] *= 7.0
        out = residual_returns(moved, spec=SPEC, horizon=horizon).residual
        np.testing.assert_array_equal(out[t], base[t])


def test_own_return_never_enters_own_factors():
    # A row after its block's refit row is in no window its own loadings used: shifting one
    # name's return there by d shifts that name's residual by exactly d.
    r, _ = _structured(3)
    res = residual_returns(r, spec=SPEC)
    t = res.refit_rows[-2] + 1
    moved = r.copy()
    moved[t, 5] += 0.05
    out = residual_returns(moved, spec=SPEC).residual
    np.testing.assert_allclose(out[t, 5] - res.residual[t, 5], 0.05, rtol=0, atol=1e-12)
    others = np.arange(r.shape[1]) != 5
    assert not np.allclose(out[t, others], res.residual[t, others])  # others' factors moved


def test_sparse_name_gets_no_loadings():
    r, _ = _structured(4)
    r[::3, 0] = np.nan  # keeps 2/3 of rows: enough
    r[:400, 1] = np.where(np.arange(400) % 5 == 0, r[:400, 1], np.nan)  # 1/5: too few
    res = residual_returns(r, spec=SPEC)
    early = res.refit_rows[res.refit_rows < 400][-1]
    assert np.isfinite(res.loadings_at(early)[0]).all()
    assert np.isnan(res.loadings_at(early)[1]).all()
    assert np.isnan(res.residual[early, 1])


def test_missing_input_is_nan_never_filled():
    r, _ = _structured(5)
    r[350, 3] = np.nan
    res = residual_returns(r, spec=SPEC)
    assert np.isnan(res.residual[350, 3])
    assert np.isfinite(res.residual[350, 4])


def test_intraday_windows_count_sessions():
    r, _ = _structured(6, n=1200)
    res = residual_returns(r, spec=SPEC, bars_per_session=4)
    assert (res.refit_rows % 4 == 0).all()
    assert res.refit_rows[0] >= SPEC.window_sessions * 4 - 1
    np.testing.assert_array_equal(np.diff(res.refit_rows), SPEC.refit_sessions * 4)


def test_neutralize_removes_loading_exposure():
    r, _ = _structured(7)
    res = residual_returns(r, spec=SPEC)
    t = res.refit_rows[3] + 2
    beta = res.loadings_at(t)
    alpha = np.full(r.shape, np.nan)
    alpha[t] = 2.0 * beta[:, 0] + np.random.default_rng(0).normal(size=r.shape[1])
    out = neutralize(alpha, res)
    ok = np.isfinite(out[t])
    assert ok.sum() == r.shape[1]
    np.testing.assert_allclose(out[t, ok] @ beta[ok], 0.0, atol=1e-9)


def test_panel_saved_without_sectors_still_loads(tmp_path):
    import json

    from src.intelligence.research import panel as panel_mod
    from src.intelligence.research import store

    p = panel_mod.daily_panel(np.ones((3, 2)))
    arrays = {n: getattr(p, n) for n in ("timestamps", "valid", "open", "close", "volume")}
    meta = {"tf": "1d", "symbols": ["a", "b"], "bars_per_session": 1, "manifest": {}}
    path = store.write(tmp_path, "panel", arrays, meta)
    assert panel_mod.load(path).sectors == ()
    assert "sectors" not in json.loads((path / "meta.json").read_text())


def test_causal_groups_recover_planted_clusters():
    from src.intelligence.research.factors import _causal_groups, _market

    r, _ = _structured(8)
    rows = slice(0, 120)
    groups = _causal_groups(r[rows], _market(r)[rows], 60, 5)
    labels = np.array(LABELS)
    majority = {
        g: Counter(labels[groups == g]).most_common(1)[0][0] for g in np.unique(groups[groups >= 0])
    }
    planted = labels != "solo"
    own = np.array([majority.get(g) == x for g, x in zip(groups, labels)])
    assert own[planted].mean() >= 0.9  # names sit in a group whose majority is their sector
    sizes = np.bincount(groups[groups >= 0])
    assert sizes.min() >= 5


def test_groups_use_only_window_rows():
    # Same window rows, different later data: identical groups (and so identical loadings).
    r, _ = _structured(9)
    res = residual_returns(r, spec=SPEC)
    moved = r.copy()
    moved[res.refit_rows[3] + 1 :] = np.random.default_rng(1).normal(
        0, 0.02, moved[res.refit_rows[3] + 1 :].shape
    )
    out = residual_returns(moved, spec=SPEC)
    np.testing.assert_array_equal(out.loadings[:4], res.loadings[:4])
