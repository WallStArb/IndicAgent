"""Unit tests for the earnings-season window classifier and SQL identifier safety
guard in scripts/analysis/earnings_season_conditional_ic_reverification.py
(Phase 176 Plan 01, Task 1).

No test in this module opens a DB connection -- every function under test is pure.
"""

from __future__ import annotations

from datetime import date

import pytest

from scripts.analysis.earnings_season_conditional_ic_reverification import (
    _FEATURE_ALLOWLIST,
    _RETURN_COLUMN_CHOICES,
    _validated_identifier,
    days_since_quarter_end,
    is_earnings_season,
)


class TestDaysSinceQuarterEnd:
    def test_day_after_quarter_end(self) -> None:
        assert days_since_quarter_end(date(2026, 4, 1)) == 1

    def test_quarter_end_day_itself(self) -> None:
        assert days_since_quarter_end(date(2026, 3, 31)) == 0

    def test_crosses_year_boundary(self) -> None:
        assert days_since_quarter_end(date(2026, 1, 1)) == 1

    def test_leap_year_february_does_not_shift_march_quarter_end(self) -> None:
        # 2028 is a leap year (Feb has 29 days). Mar 31 is still the quarter end,
        # and Mar 1 is still exactly 0 days after Dec 31 of the prior year... no,
        # Mar 1 2028's most recent quarter end is Dec 31 2027. Check that leap-day
        # existing does not perturb the Mar-31-relative count for a date just after
        # Mar 31 of a leap year.
        assert days_since_quarter_end(date(2028, 4, 1)) == 1
        assert days_since_quarter_end(date(2028, 3, 31)) == 0

    def test_other_quarter_ends(self) -> None:
        assert days_since_quarter_end(date(2026, 7, 1)) == 1  # after Jun 30
        assert days_since_quarter_end(date(2026, 10, 1)) == 1  # after Sep 30
        assert days_since_quarter_end(date(2026, 12, 31)) == 0  # quarter end itself


class TestIsEarningsSeason:
    def test_day_13_is_false(self) -> None:
        d = date(2026, 3, 31)  # quarter end
        # day 13 after Mar 31 -> Apr 13
        assert is_earnings_season(date(2026, 4, 13), 14, 42) is False
        del d

    def test_day_14_is_true(self) -> None:
        assert is_earnings_season(date(2026, 4, 14), 14, 42) is True

    def test_day_42_is_true(self) -> None:
        assert is_earnings_season(date(2026, 5, 12), 14, 42) is True

    def test_day_43_is_false(self) -> None:
        assert is_earnings_season(date(2026, 5, 13), 14, 42) is False

    def test_quarter_end_day_itself_is_false(self) -> None:
        assert is_earnings_season(date(2026, 3, 31), 14, 42) is False


class TestValidatedIdentifier:
    def test_allowed_name_returns_identifier(self) -> None:
        import psycopg

        result = _validated_identifier("up_vol_body_diff", allowed={"up_vol_body_diff"})
        assert isinstance(result, psycopg.sql.Identifier)

    def test_sql_injection_attempt_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="up_vol_body_diff; DROP TABLE feature_vectors"):
            _validated_identifier(
                "up_vol_body_diff; DROP TABLE feature_vectors",
                allowed={"up_vol_body_diff"},
            )

    def test_unknown_name_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="not_a_real_column"):
            _validated_identifier("not_a_real_column", allowed={"up_vol_body_diff"})

    def test_feature_and_return_allowlists_are_separate(self) -> None:
        # A forward_returns scale column name is rejected against the FeatureVector
        # allow-list, and vice versa.
        with pytest.raises(ValueError):
            _validated_identifier("return_fast", allowed=_FEATURE_ALLOWLIST)
        with pytest.raises(ValueError):
            _validated_identifier("up_vol_body_diff", allowed=set(_RETURN_COLUMN_CHOICES))

    def test_feature_allowlist_accepts_real_feature(self) -> None:
        _validated_identifier("up_vol_body_diff", allowed=_FEATURE_ALLOWLIST)

    def test_return_column_allowlist_accepts_real_column(self) -> None:
        _validated_identifier("return_fast", allowed=set(_RETURN_COLUMN_CHOICES))
