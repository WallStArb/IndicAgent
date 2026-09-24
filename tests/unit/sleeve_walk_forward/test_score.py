import numpy as np
import pytest

from scripts.analysis.sleeve_walk_forward.results import RefitOutput, StratumWeights
from scripts.analysis.sleeve_walk_forward.score import score_panel

SESSIONS = np.array(
    ["2011-01-03", "2011-01-04", "2012-01-03", "2012-01-04", "2012-01-05"], dtype="datetime64[D]"
)
FEATURE_INDEX = {"f0": 0, "f1": 1, "f2": 2}


def _sw(names, w, signs):
    return StratumWeights(names, np.array(w, float), np.array(signs, float), "ic_proportional", 1.0)


def _refit(date, strata, skipped=None):
    return RefitOutput(np.datetime64(date), strata, skipped or {}, [], 0)


def _inputs():
    # 5 sessions x 2 sleeve symbols x 3 features.
    features = np.arange(30, dtype=float).reshape(5, 2, 3)
    has_row = np.ones((5, 2), bool)
    labels = np.array(["hi", "lo", "hi", "lo", "hi"])
    refits = [
        _refit(
            "2011-01-03",
            {"hi": _sw(["f0", "f2"], [0.5, 0.5], [1, -1]), "lo": _sw(["f1"], [1.0], [1])},
        ),
        _refit("2012-01-03", {"hi": _sw(["f1"], [1.0], [-1])}, skipped={"lo": "min_features"}),
    ]
    return refits, features, has_row, labels


def _score(refits, features, has_row, labels, end="2012-12-31"):
    return score_panel(
        refits,
        features,
        has_row,
        FEATURE_INDEX,
        labels,
        SESSIONS,
        [r.refit_date for r in refits],
        np.datetime64(end),
    )


def test_composite_uses_the_days_refit_and_stratum():
    alpha, _ = _score(*_inputs())
    f = np.arange(30, dtype=float).reshape(5, 2, 3)
    np.testing.assert_allclose(alpha[0], 0.5 * f[0, :, 0] - 0.5 * f[0, :, 2])  # refit 1, hi
    np.testing.assert_allclose(alpha[1], f[1, :, 1])  # refit 1, lo
    np.testing.assert_allclose(alpha[2], -f[2, :, 1])  # refit 2 from its own date, hi


def test_missing_stratum_is_nan_and_counted():
    alpha, counts = _score(*_inputs())
    assert np.isnan(alpha[3]).all()
    assert counts[2012]["no_stratum_weights"] == 2


def test_null_feature_counts_as_zero_but_missing_row_is_nan():
    refits, features, has_row, labels = _inputs()
    features[0, 0, 2] = np.nan
    has_row[0, 1] = False
    alpha, counts = _score(refits, features, has_row, labels)
    assert alpha[0, 0] == pytest.approx(0.5 * features[0, 0, 0])
    assert np.isnan(alpha[0, 1]) and counts[2011]["no_feature_row"] == 1


def test_no_label_is_nan():
    refits, features, has_row, labels = _inputs()
    labels[4] = ""
    alpha, counts = _score(refits, features, has_row, labels)
    assert np.isnan(alpha[4]).all() and counts[2012]["no_label"] == 2


def test_days_after_end_are_not_scored():
    alpha, _ = _score(*_inputs(), end="2012-01-04")
    assert np.isnan(alpha[4]).all()


def test_refit_dates_must_match_refits():
    refits, features, has_row, labels = _inputs()
    with pytest.raises(ValueError, match="refit"):
        score_panel(
            refits,
            features,
            has_row,
            FEATURE_INDEX,
            labels,
            SESSIONS,
            [np.datetime64("2011-01-04"), refits[1].refit_date],
            np.datetime64("2012-12-31"),
        )
