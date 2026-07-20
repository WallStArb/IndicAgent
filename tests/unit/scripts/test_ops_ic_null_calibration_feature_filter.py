"""Unit tests for ops_ic_null_calibration.py's --feature-filter flag (todo 145).

145 needs a follow-up calibration run stratified toward ctf_momentum/flight_quality
specifically, instead of the script's existing boundary-nearest sampling across all
features. This adds the flag and its parsing/SQL wiring; no live corpus-scale run is
executed by this todo. No DB, no asyncio -- pure parsing + SQL-string-shape tests,
mirroring tests/unit/scripts/test_ops_feature_registry_override.py's sys.argv
monkeypatch convention and test_forward_return_writer.py's SQL-structure convention.
"""

from __future__ import annotations

import sys

from scripts.ops.alpha.ops_ic_null_calibration import (
    _BOUNDARY_CELLS_SQL,
    _NULL_CELLS_SQL,
    _STRONG_CELLS_SQL,
    _parse_args,
    _parse_feature_filter,
)


class TestParseFeatureFilter:
    def test_none_when_absent(self):
        assert _parse_feature_filter(None) is None

    def test_none_for_empty_string(self):
        assert _parse_feature_filter("") is None

    def test_splits_and_strips_comma_separated_names(self):
        assert _parse_feature_filter("ctf_momentum, flight_quality") == [
            "ctf_momentum",
            "flight_quality",
        ]

    def test_drops_empty_entries_from_trailing_comma(self):
        assert _parse_feature_filter("ctf_momentum,") == ["ctf_momentum"]

    def test_single_feature(self):
        assert _parse_feature_filter("ctf_momentum") == ["ctf_momentum"]


class TestCliFlag:
    def test_feature_filter_defaults_to_none(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog"])
        args = _parse_args()
        assert args.feature_filter is None

    def test_feature_filter_accepts_value(self, monkeypatch):
        monkeypatch.setattr(
            sys, "argv", ["prog", "--feature-filter", "ctf_momentum,flight_quality"]
        )
        args = _parse_args()
        assert args.feature_filter == "ctf_momentum,flight_quality"


class TestCellSamplingSqlIncludesOptionalFilter:
    def test_boundary_sql_has_feature_filter_clause(self):
        assert "$5::text[]" in _BOUNDARY_CELLS_SQL
        assert "feature_name = ANY($5::text[])" in _BOUNDARY_CELLS_SQL

    def test_null_sql_has_feature_filter_clause(self):
        assert "$5::text[]" in _NULL_CELLS_SQL
        assert "feature_name = ANY($5::text[])" in _NULL_CELLS_SQL

    def test_strong_sql_has_feature_filter_clause(self):
        assert "$5::text[]" in _STRONG_CELLS_SQL
        assert "feature_name = ANY($5::text[])" in _STRONG_CELLS_SQL

    def test_filter_clause_is_optional_via_null_check(self):
        """The clause must let a NULL array pass through untouched (no filter
        applied) -- existing callers with no filter must see unchanged behavior."""
        for sql in (_BOUNDARY_CELLS_SQL, _NULL_CELLS_SQL, _STRONG_CELLS_SQL):
            assert "IS NULL OR feature_name = ANY" in sql
