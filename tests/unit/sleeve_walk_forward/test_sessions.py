import numpy as np
import pytest

from scripts.analysis.sleeve_walk_forward.sessions import (
    label_cutoff,
    refit_dates,
)


def _sessions(*days):
    return np.array(days, dtype="datetime64[D]")


def test_refit_dates_are_first_session_of_each_year():
    s = _sessions("2010-12-30", "2010-12-31", "2011-01-03", "2011-01-04", "2012-01-03")
    assert refit_dates(s, range(2011, 2013)) == [
        np.datetime64("2011-01-03"),
        np.datetime64("2012-01-03"),
    ]


def test_refit_dates_missing_year_raises():
    with pytest.raises(ValueError, match="2012"):
        refit_dates(_sessions("2011-01-03"), range(2011, 2013))


def test_label_cutoff_is_five_sessions_before_refit():
    s = np.arange(np.datetime64("2011-01-03"), np.datetime64("2011-01-20"))
    refit = np.datetime64("2011-01-17")
    idx = label_cutoff(s, refit, embargo=5)
    assert s[idx] == np.datetime64("2011-01-12")
