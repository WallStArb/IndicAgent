"""Unit tests for cross_sectional_regime_model. CI-clean: no DB, no network."""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from services.cross_sectional_regime_model import (
    _assign_labels,
    _bucket,
    _parse_group_configs,
    _resolve_group_symbols,
)

_TS = datetime.datetime(2024, 1, 15, tzinfo=datetime.UTC)


class TestParseGroupConfigs:
    def test_parses_valid_json(self):
        raw = json.dumps(
            [
                {
                    "name": "equity",
                    "tag_filter": ["eq_*", "intl_*"],
                    "signal_type": "breadth_vol",
                    "params_prefix": "alpha.equity_regime",
                    "enabled": True,
                },
                {
                    "name": "rates",
                    "tag_filter": ["fi_*"],
                    "signal_type": "curve_credit",
                    "params_prefix": "alpha.rates_regime",
                    "enabled": True,
                },
            ]
        )
        configs = _parse_group_configs(raw)
        assert len(configs) == 2
        assert configs[0]["name"] == "equity"
        assert configs[1]["name"] == "rates"

    def test_filters_disabled_groups(self):
        raw = json.dumps(
            [
                {
                    "name": "equity",
                    "tag_filter": ["eq_*"],
                    "signal_type": "breadth_vol",
                    "params_prefix": "alpha.equity_regime",
                    "enabled": True,
                },
                {
                    "name": "rates",
                    "tag_filter": ["fi_*"],
                    "signal_type": "curve_credit",
                    "params_prefix": "alpha.rates_regime",
                    "enabled": False,
                },
            ]
        )
        configs = _parse_group_configs(raw)
        assert len(configs) == 1
        assert configs[0]["name"] == "equity"

    def test_empty_json_returns_empty(self):
        assert _parse_group_configs("[]") == []

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="alpha.regime.groups"):
            _parse_group_configs("not json")

    def test_accepts_already_parsed_list(self):
        """The JSON-typed APR key returns an already-parsed list[dict] once cached
        (config_service.py's _parse_value() calls json.loads() at cache-load time) —
        _parse_group_configs must accept this shape directly, WITHOUT a second
        json.loads() call (which would raise TypeError on a list input) and WITHOUT
        going through str() first (which would produce an invalid-JSON repr string).
        """
        parsed_list = [
            {
                "name": "equity",
                "tag_filter": ["eq_*", "intl_*"],
                "signal_type": "breadth_vol",
                "params_prefix": "alpha.equity_regime",
                "enabled": True,
            },
            {
                "name": "rates",
                "tag_filter": ["fi_*"],
                "signal_type": "curve_credit",
                "params_prefix": "alpha.rates_regime",
                "enabled": False,
            },
        ]
        configs = _parse_group_configs(parsed_list)
        assert len(configs) == 1
        assert configs[0]["name"] == "equity"

    def test_str_and_list_inputs_normalize_identically(self):
        """Both input shapes (already-parsed list[dict], raw JSON string) must
        produce the SAME normalized (enabled-filtered) config — this is the
        JSON-parse-fix regression coverage required by 144-04-PLAN.md.
        """
        group_dicts = [
            {
                "name": "equity",
                "tag_filter": ["eq_*", "intl_*"],
                "signal_type": "breadth_vol",
                "params_prefix": "alpha.equity_regime",
                "enabled": True,
            },
            {
                "name": "rates",
                "tag_filter": ["fi_*"],
                "signal_type": "curve_credit",
                "params_prefix": "alpha.rates_regime",
                "enabled": True,
            },
            {
                "name": "fx",
                "tag_filter": ["fx_*", "crypto"],
                "signal_type": "fx_dollar_carry",
                "params_prefix": "alpha.fx_regime",
                "enabled": False,
            },
        ]
        raw_json_str = json.dumps(group_dicts)

        configs_from_list = _parse_group_configs(group_dicts)
        configs_from_str = _parse_group_configs(raw_json_str)

        assert configs_from_list == configs_from_str
        assert [g["name"] for g in configs_from_list] == ["equity", "rates"]


class TestResolveGroupSymbols:
    def test_eq_filter_matches_eq_prefixed_tags(self):
        tags_by_symbol = {
            "SPY": {"eq_large_cap", "eq_blend"},
            "TLT": {"fi_treasury"},
            "EWT": {"intl_em"},
        }
        result = _resolve_group_symbols(tags_by_symbol, ["eq_*", "intl_*"])
        assert "SPY" in result
        assert "EWT" in result
        assert "TLT" not in result

    def test_fi_filter_matches_fi_prefixed_tags(self):
        tags_by_symbol = {
            "TLT": {"fi_treasury"},
            "HYG": {"fi_credit_hy"},
            "SPY": {"eq_large_cap"},
        }
        result = _resolve_group_symbols(tags_by_symbol, ["fi_*"])
        assert "TLT" in result
        assert "HYG" in result
        assert "SPY" not in result

    def test_returns_sorted_list(self):
        tags_by_symbol = {
            "ZZZ": {"eq_x"},
            "AAA": {"eq_x"},
            "MMM": {"eq_x"},
        }
        result = _resolve_group_symbols(tags_by_symbol, ["eq_*"])
        assert result == sorted(result)


class TestBucket:
    def test_value_below_first_upper_bound(self):
        tiers = [("low", 0.33), ("mid", 0.67), ("high", float("inf"))]
        vals = np.array([0.1])
        result = _bucket(vals, tiers)
        assert result[0] == "low"

    def test_value_between_tiers(self):
        tiers = [("low", 0.33), ("mid", 0.67), ("high", float("inf"))]
        vals = np.array([0.5])
        result = _bucket(vals, tiers)
        assert result[0] == "mid"

    def test_value_above_all_thresholds(self):
        tiers = [("low", 0.33), ("mid", 0.67), ("high", float("inf"))]
        vals = np.array([0.9])
        result = _bucket(vals, tiers)
        assert result[0] == "high"

    def test_exactly_at_upper_bound_goes_to_next_tier(self):
        tiers = [("low", 0.33), ("mid", 0.67), ("high", float("inf"))]
        vals = np.array([0.33])
        result = _bucket(vals, tiers)
        # 0.33 is NOT < 0.33, so it falls to "mid"
        assert result[0] == "mid"


class TestAssignLabels:
    def test_basic_label_format(self):
        rows = _assign_labels(
            group_name="equity",
            tf="1d",
            ts_arr=[_TS],
            sig1_arr=np.array([0.2]),
            sig2_arr=np.array([0.7]),
            tiers1=[("low", 0.33), ("mid", 0.67), ("high", float("inf"))],
            tiers2=[("bear", 0.40), ("neutral", 0.60), ("bull", float("inf"))],
            prob_keys=("vix_pct", "breadth_frac"),
        )
        assert len(rows) == 1
        group, tf, ts, label, prob = rows[0]
        assert group == "equity"
        assert tf == "1d"
        assert ts == _TS
        assert label == "low_bull"
        assert prob == {"vix_pct": 0.2, "breadth_frac": 0.7}

    def test_regime_group_set_on_every_row(self):
        n = 10
        rows = _assign_labels(
            group_name="rates",
            tf="1h",
            ts_arr=[_TS] * n,
            sig1_arr=np.linspace(-1, 1, n),
            sig2_arr=np.linspace(-1, 1, n),
            tiers1=[("inverted", -0.5), ("flat", 0.5), ("steep", float("inf"))],
            tiers2=[("wide", 0.0), ("tight", float("inf"))],
            prob_keys=("curve_z", "credit_z"),
        )
        assert all(r[0] == "rates" for r in rows)

    def test_all_six_rates_labels_possible(self):
        sig1 = np.array([-1.0, -1.0, 0.0, 0.0, 1.0, 1.0])
        sig2 = np.array([-1.0, 1.0, -1.0, 1.0, -1.0, 1.0])
        tiers1 = [("inverted", -0.5), ("flat", 0.5), ("steep", float("inf"))]
        tiers2 = [("wide", 0.0), ("tight", float("inf"))]
        rows = _assign_labels(
            group_name="rates",
            tf="1d",
            ts_arr=[_TS] * 6,
            sig1_arr=sig1,
            sig2_arr=sig2,
            tiers1=tiers1,
            tiers2=tiers2,
            prob_keys=("curve_z", "credit_z"),
        )
        labels = {r[3] for r in rows}
        assert labels == {
            "inverted_wide",
            "inverted_tight",
            "flat_wide",
            "flat_tight",
            "steep_wide",
            "steep_tight",
        }

    def test_output_length_matches_input(self):
        n = 50
        rows = _assign_labels(
            group_name="equity",
            tf="5m",
            ts_arr=[_TS] * n,
            sig1_arr=np.random.rand(n),
            sig2_arr=np.random.rand(n),
            tiers1=[("low", 0.33), ("mid", 0.67), ("high", float("inf"))],
            tiers2=[("bear", 0.40), ("neutral", 0.60), ("bull", float("inf"))],
            prob_keys=("vix_pct", "breadth_frac"),
        )
        assert len(rows) == n

    def test_no_single_label_exceeds_sane_share_of_synthetic_fixture(self):
        """Sanity check per PLAN.md's <behavior>: on a uniform synthetic fixture,
        no single label should dominate (this guards against a degenerate
        _bucket/_assign_labels wiring bug, not a statistical claim about real data).
        """
        n = 900
        rng = np.random.default_rng(42)
        sig1 = rng.uniform(0.0, 1.0, n)
        sig2 = rng.uniform(0.0, 1.0, n)
        rows = _assign_labels(
            group_name="equity",
            tf="1d",
            ts_arr=[_TS] * n,
            sig1_arr=sig1,
            sig2_arr=sig2,
            tiers1=[("low", 0.33), ("mid", 0.67), ("high", float("inf"))],
            tiers2=[("bear", 0.40), ("neutral", 0.60), ("bull", float("inf"))],
            prob_keys=("vix_pct", "breadth_frac"),
        )
        counts: dict[str, int] = {}
        for r in rows:
            counts[r[3]] = counts.get(r[3], 0) + 1
        max_share = max(counts.values()) / n
        assert max_share < 0.5
