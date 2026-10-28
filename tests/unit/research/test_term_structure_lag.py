"""The lag IC term structure and its joint shift band (phase 184 B4, design D2)."""

import dataclasses
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import rankdata

from src.intelligence.statistics.panel_null import admissible_shifts
from src.intelligence.statistics.term_structure_lag import (
    BAND_LEVEL,
    K_DAILY,
    LagTermStructure,
    lag_ic_curve,
    lag_term_structure,
)

MODULE = Path(__file__).resolve().parents[3] / "src/intelligence/statistics/term_structure_lag.py"


def _ar1(rng, n, m, phi):
    f = np.empty((n, m))
    f[0] = rng.normal(size=m)
    noise = rng.normal(scale=math.sqrt(1 - phi**2), size=(n, m))
    for t in range(1, n):
        f[t] = phi * f[t - 1] + noise[t]
    return f


def _manual_curve(alpha, target, lags, floor, session_rows=None):
    """Row-by-row reference: ranks over each array's own finite cells, Pearson on the pairs."""
    n = alpha.shape[0]
    ra = rankdata(alpha, axis=1, nan_policy="omit")
    rt = rankdata(target, axis=1, nan_policy="omit")
    out = []
    for k in lags:
        vals = []
        for t in range(n - k + 1):
            u = t + k - 1
            if session_rows and t // session_rows != u // session_rows:
                continue
            mask = np.isfinite(ra[t]) & np.isfinite(rt[u])
            if mask.sum() < floor:
                continue
            vals.append(np.corrcoef(ra[t][mask], rt[u][mask])[0, 1])
        out.append(np.mean(vals) if vals else np.nan)
    return np.array(out)


def test_closed_form_ar1():
    rng = np.random.default_rng(11)
    n, m, phi = 2000, 200, 0.9
    f = _ar1(rng, n, m, phi)
    target = 0.3 * f + rng.normal(size=(n, m))
    lags = np.arange(1, 11)
    curve = lag_ic_curve(f, target, lags, coverage_floor=20)
    rho = 0.3 * phi ** (lags - 1) / math.sqrt(0.09 + 1)
    expected = (6 / math.pi) * np.arcsin(rho / 2)
    assert np.max(np.abs(curve - expected)) < 0.02


def test_matches_row_by_row_reference_with_nans_and_ties():
    rng = np.random.default_rng(3)
    alpha = np.round(rng.normal(size=(60, 15)), 1)  # ties
    target = rng.normal(size=(60, 15))
    alpha[rng.random(alpha.shape) < 0.15] = np.nan
    target[rng.random(target.shape) < 0.15] = np.nan
    lags = [1, 2, 5]
    np.testing.assert_allclose(
        lag_ic_curve(alpha, target, lags, coverage_floor=5),
        _manual_curve(alpha, target, lags, 5),
        rtol=1e-12,
    )


def test_independent_inputs_stay_within_joint_band():
    inside = 0
    for seed in range(100):
        rng = np.random.default_rng(1000 + seed)
        alpha = rng.normal(size=(500, 50))
        target = rng.normal(size=(500, 50))
        shifts = admissible_shifts(500, 20)[::10]
        ts = lag_term_structure(alpha, target, shifts=shifts, coverage_floor=10, k_max=10)
        inside += np.nanmax(np.abs(ts.ic)) <= ts.band
    assert inside >= 90


def test_in_session_excludes_cross_session_pairs():
    bps = 4
    rng = np.random.default_rng(5)
    alpha = rng.normal(size=(40 * bps, 12))
    # within a session the target is unrelated; across a boundary it copies alpha exactly
    target = rng.normal(size=alpha.shape)
    for t in range(alpha.shape[0] - 1):
        if (t + 1) % bps == 0:
            target[t + 1] = alpha[t]
    lags = [1, 2, 3]
    in_sess = lag_ic_curve(alpha, target, lags, coverage_floor=5, session_rows=bps, in_session=True)
    np.testing.assert_allclose(
        in_sess, _manual_curve(alpha, target, lags, 5, session_rows=bps), rtol=1e-12
    )
    crossing = lag_ic_curve(alpha, target, lags, coverage_floor=5)
    assert crossing[1] > in_sess[1] + 0.1  # lag 2 picks up the copied boundary only when crossing
    ts = lag_term_structure(
        alpha, target, shifts=np.array([8, 12]), coverage_floor=5, session_rows=bps, in_session=True
    )
    assert ts.k_max == bps - 1 and list(ts.lags) == [1, 2, 3]
    with pytest.raises(ValueError, match="in_session"):
        lag_term_structure(alpha, target, shifts=np.array([8]), coverage_floor=5, session_rows=bps)
    with pytest.raises(ValueError, match="whole number"):
        lag_term_structure(
            alpha, target, shifts=np.array([6]), coverage_floor=5, session_rows=bps, in_session=True
        )


def test_row_below_coverage_floor_contributes_nothing():
    m = 10
    base = np.arange(m, dtype=float)
    alpha = np.tile(base, (6, 1))
    target = np.tile(-base, (6, 1))  # every full row is IC -1
    alpha[0, 3:] = np.nan  # row 0: 3 names, and there perfectly correlated
    target[0, :3] = base[:3]
    curve = lag_ic_curve(alpha, target, [1], coverage_floor=5)
    assert curve[0] == pytest.approx(-1.0)
    assert lag_ic_curve(alpha, target, [1], coverage_floor=3)[0] > -1.0
    assert np.isnan(lag_ic_curve(alpha[:1], target[:1], [1], coverage_floor=5)[0])


def test_result_and_record():
    rng = np.random.default_rng(9)
    alpha = rng.normal(size=(300, 20))
    target = rng.normal(size=(300, 20))
    ts = lag_term_structure(
        alpha, target, shifts=admissible_shifts(300, 20)[::20], coverage_floor=5
    )
    assert isinstance(ts, LagTermStructure)
    assert ts.k_max == K_DAILY and len(ts.lags) == len(ts.ic) == K_DAILY
    assert ts.band_level == BAND_LEVEL and ts.n_shifts > 0 and ts.band > 0
    rec = json.loads(json.dumps(ts.as_record()))
    assert set(rec) == {"lags", "ic", "band", "band_level", "n_shifts", "k_max"}
    assert rec["lags"][0] == 1 and rec["k_max"] == K_DAILY
    with pytest.raises(dataclasses.FrozenInstanceError):
        ts.band = 0.0


def test_record_nan_is_none_and_no_shifts_gives_nan_band():
    alpha = np.full((10, 5), np.nan)
    ts = lag_term_structure(alpha, alpha.copy(), shifts=np.array([], dtype=int), coverage_floor=3)
    rec = ts.as_record()
    assert rec["band"] is None and rec["n_shifts"] == 0
    assert all(v is None for v in rec["ic"])
    json.dumps(rec)


def test_module_imports_nothing_from_research_or_measure():
    text = MODULE.read_text()
    hits = [
        line
        for line in text.splitlines()
        if "import" in line
        and re.search(r"intelligence\.(research|measure)", line)
        and not line.lstrip().startswith("#")
    ]
    assert hits == []
