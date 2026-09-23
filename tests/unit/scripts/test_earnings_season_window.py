"""Unit tests for the earnings-season window classifier, SQL identifier safety
guard, and family-wide vol/volume sweep in
scripts/analysis/earnings_season_conditional_ic_reverification.py
(Phase 176 Plan 01, Tasks 1-2).

No test in this module opens a DB connection -- every function under test is pure.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pytest

from scripts.analysis.earnings_season_conditional_ic_reverification import (
    _FEATURE_ALLOWLIST,
    _RETURN_COLUMN_CHOICES,
    _VOL_VOLUME_FAMILY,
    _is_broad,
    _sweep_verdict,
    _validated_identifier,
    days_since_quarter_end,
    is_earnings_season,
)
from src.intelligence.feature_factory import FeatureVector


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


class TestVolVolumeFamily:
    def test_exactly_57_names(self) -> None:
        assert len(_VOL_VOLUME_FAMILY) == 57

    def test_every_member_is_a_real_feature_vector_field(self) -> None:
        real_names = {f.name for f in dataclasses.fields(FeatureVector)}
        assert _VOL_VOLUME_FAMILY <= real_names

    def test_contains_up_vol_body_diff(self) -> None:
        assert "up_vol_body_diff" in _VOL_VOLUME_FAMILY

    def test_excludes_canary_noise_and_dist_atr_names(self) -> None:
        assert not any(name.startswith("canary_noise_") for name in _VOL_VOLUME_FAMILY)
        assert not any(name.endswith("_dist_atr") for name in _VOL_VOLUME_FAMILY)


class TestSweepVerdict:
    def test_no_survivors_is_refuted(self) -> None:
        assert _sweep_verdict(survivors=[], any_fdr_significant=False) == "REFUTED"

    def test_survivors_including_up_vol_body_diff_is_confirmed(self) -> None:
        result = _sweep_verdict(
            survivors=["up_vol_body_diff", "vol_of_vol"], any_fdr_significant=True
        )
        assert result == "CONFIRMED"

    def test_survivors_excluding_up_vol_body_diff_is_weaker(self) -> None:
        result = _sweep_verdict(survivors=["vol_of_vol"], any_fdr_significant=True)
        assert result == "WEAKER"


class TestIsBroad:
    def test_false_when_sign_agreement_below_threshold(self) -> None:
        # FDR-surviving p-values (all < 0.05) but sign agreement fraction 0.4 < 0.55
        result = _is_broad(
            sign_agreement_fraction=0.4,
            jackknife_signs=[1, 1, 1, 1, 1],
            jackknife_ps=[0.01, 0.01, 0.01, 0.01, 0.01],
            pooled_sign=1,
        )
        assert result is False

    def test_false_when_jackknife_flips_sign(self) -> None:
        result = _is_broad(
            sign_agreement_fraction=0.9,
            jackknife_signs=[1, 1, -1, 1, 1],  # one flipped
            jackknife_ps=[0.01, 0.01, 0.01, 0.01, 0.01],
            pooled_sign=1,
        )
        assert result is False

    def test_false_when_jackknife_p_exceeds_threshold(self) -> None:
        result = _is_broad(
            sign_agreement_fraction=0.9,
            jackknife_signs=[1, 1, 1, 1, 1],
            jackknife_ps=[0.01, 0.01, 0.06, 0.01, 0.01],  # one over 0.05
            pooled_sign=1,
        )
        assert result is False

    def test_true_when_all_criteria_pass(self) -> None:
        result = _is_broad(
            sign_agreement_fraction=0.9,
            jackknife_signs=[1, 1, 1, 1, 1],
            jackknife_ps=[0.01, 0.01, 0.01, 0.01, 0.01],
            pooled_sign=1,
        )
        assert result is True
