"""Unit tests for services/batch_support/config.py (cfg)."""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.batch_support.config import cfg


class TestCfg:
    def test_returns_float_when_present(self) -> None:
        cfg_dict = {"alpha.ensemble.max_feature_weight": "0.20"}
        result = cfg(cfg_dict, "alpha.ensemble.max_feature_weight", 0.5)
        assert result == 0.20
        assert isinstance(result, float)

    def test_returns_float_default_when_missing(self) -> None:
        result = cfg({}, "alpha.ensemble.max_feature_weight", 0.25)
        assert result == 0.25

    def test_returns_int_when_present(self) -> None:
        cfg_dict = {"alpha.ensemble.min_passing_features": "5"}
        result = cfg(cfg_dict, "alpha.ensemble.min_passing_features", 3)
        assert result == 5
        assert isinstance(result, int)

    def test_returns_str_when_present(self) -> None:
        cfg_dict = {"alpha.ensemble.weight_version": "v2"}
        result = cfg(cfg_dict, "alpha.ensemble.weight_version", "v1")
        assert result == "v2"
        assert isinstance(result, str)

    def test_type_inferred_from_default_not_from_raw_value(self) -> None:
        """config_state values are always text; cfg() must cast via type(default),
        not assume the raw string is already the right type."""
        cfg_dict = {"infra.workers": "12"}
        result = cfg(cfg_dict, "infra.workers", 1)
        assert result == 12
        assert isinstance(result, int)

    def test_bool_false_string_parses_to_false(self) -> None:
        """Regression: bool("false") is True in Python (non-empty string is truthy).
        A naive type(default)(val) cast would silently invert every falsy bool APR
        flag -- found live in alpha.ensemble.sign_symmetric (stored 'false', read as
        True) while wiring alpha.publisher.is_shadow (todo 011)."""
        cfg_dict = {"alpha.ensemble.sign_symmetric": "false"}
        result = cfg(cfg_dict, "alpha.ensemble.sign_symmetric", False)
        assert result is False

    def test_bool_true_string_parses_to_true(self) -> None:
        cfg_dict = {"alpha.publisher.is_shadow": "true"}
        result = cfg(cfg_dict, "alpha.publisher.is_shadow", True)
        assert result is True

    def test_bool_default_used_when_key_absent(self) -> None:
        assert cfg({}, "alpha.publisher.is_shadow", True) is True
        assert cfg({}, "alpha.ensemble.sign_symmetric", False) is False

    def test_bool_case_and_whitespace_insensitive(self) -> None:
        assert cfg({"k": " True "}, "k", False) is True
        assert cfg({"k": "FALSE"}, "k", True) is False

    def test_list_default_json_loads_raw_string(self) -> None:
        """Regression (todo 187): a naive type(default)(val) cast against a list default
        splits a raw JSON-array string into individual characters --
        list("[1,3,5,10]") != [1, 3, 5, 10] -- found live in
        alpha.construction.cost_hurdle_bps_round_trip, worked around locally in
        cross_sectional_spread_tracker.py before being fixed here at the shared layer."""
        cfg_dict = {"alpha.construction.cost_hurdle_bps_round_trip": "[1,3,5,10]"}
        result = cfg(cfg_dict, "alpha.construction.cost_hurdle_bps_round_trip", [1, 3, 5, 10])
        assert result == [1, 3, 5, 10]

    def test_list_default_used_when_key_absent(self) -> None:
        assert cfg({}, "alpha.construction.cost_hurdle_bps_round_trip", [1, 3, 5, 10]) == [
            1,
            3,
            5,
            10,
        ]

    def test_dict_default_json_loads_raw_string(self) -> None:
        cfg_dict = {"alpha.regime.groups": '{"equity": true}'}
        result = cfg(cfg_dict, "alpha.regime.groups", {})
        assert result == {"equity": True}

    def test_dict_default_passthrough_when_already_parsed(self) -> None:
        """ConfigService's json.loads() may already have parsed the value before it
        reaches cfg() in some call paths -- must not double-decode a dict that's no
        longer a raw string."""
        cfg_dict = {"alpha.regime.groups": {"equity": True}}
        result = cfg(cfg_dict, "alpha.regime.groups", {})
        assert result == {"equity": True}
