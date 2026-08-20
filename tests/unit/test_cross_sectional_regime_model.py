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
    _assert_ascending_tiers,
    _assign_labels,
    _bucket,
    _parse_group_configs,
    _resolve_group_symbols,
)
from src.intelligence.regime_signals import REGISTRY

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

    def test_bucket_itself_rejects_malformed_tiers_without_main(self):
        # Code review (2026-08-20): scripts/analysis/regime_boundary_churn_check.py
        # imports and calls _bucket() directly, bypassing main()'s explicit
        # _assert_ascending_tiers calls entirely -- so validation has to live inside
        # _bucket() itself to protect that caller too, not just main()'s. This proves
        # it does: no main(), no _assert_ascending_tiers call, just _bucket() alone.
        descending = [("up_primary", 0.75), ("up_secondary", 0.0), ("down_secondary", -0.75)]
        with pytest.raises(ValueError, match="STRICTLY ascending"):
            _bucket(np.array([0.1]), descending)

    def test_exactly_at_upper_bound_goes_to_next_tier(self):
        tiers = [("low", 0.33), ("mid", 0.67), ("high", float("inf"))]
        vals = np.array([0.33])
        result = _bucket(vals, tiers)
        # 0.33 is NOT < 0.33, so it falls to "mid"
        assert result[0] == "mid"


class TestAssertAscendingTiers:
    """todo 335: this guard is the only thing standing between a REGISTRY module's
    build_tiers() and a silent label-collapse bug like commodity/fx's -- it must
    itself be proven to fire on the exact shape of input that caused that bug."""

    def test_ascending_tiers_does_not_raise(self):
        _assert_ascending_tiers(
            [("low", 0.33), ("mid", 0.67), ("high", float("inf"))], "equity", "tiers1"
        )

    def test_descending_tiers_raises(self):
        # Exact shape of commodity_momentum_ts's pre-fix tiers1.
        with pytest.raises(ValueError, match="not STRICTLY ascending-sorted"):
            _assert_ascending_tiers(
                [("up_primary", 0.75), ("up_secondary", 0.0), ("down_secondary", -0.75)],
                "commodity",
                "tiers1",
            )

    def test_single_entry_tiers_raises(self):
        # Code review (2026-08-20): originally this asserted single-entry tiers did
        # NOT raise, on the theory that this guard only catches ORDER bugs, not fx's
        # pre-fix single-entry tiers2 (a reachability bug). That left a real hole --
        # fx's ORIGINAL bug shape would have passed the guard meant to prevent it.
        # The guard now requires len(tiers) >= 2 explicitly.
        with pytest.raises(ValueError, match="only 1 tuple"):
            _assert_ascending_tiers([("risk_on", 0.0)], "fx", "tiers2")

    def test_duplicate_bound_raises(self):
        # Code review (2026-08-20): non-decreasing (`bounds == sorted(bounds)`) is not
        # sufficient -- a tied bound (e.g. primary_threshold=0.0 collapsing
        # down_secondary/up_secondary to the same upper_bound) is non-decreasing but
        # still reproduces the exact overwrite-collapse bug this guard exists to catch.
        with pytest.raises(ValueError, match="STRICTLY ascending"):
            _assert_ascending_tiers(
                [
                    ("down_primary", -0.75),
                    ("down_secondary", 0.0),
                    ("up_secondary", 0.0),
                    ("up_primary", float("inf")),
                ],
                "commodity",
                "tiers1",
            )


class TestRegistryTierContract:
    """REGISTRY completeness is explicitly independent of enablement
    (regime_signals/__init__.py's own docstring: commodity_momentum_ts and
    fx_dollar_carry are registered regardless of their group's `enabled` value in
    alpha.regime.groups). Today (verified live 2026-08-20) all four groups happen to
    be enabled=true, so main()'s runtime guard does cover them right now -- but
    coverage that depends on a live APR config toggle, which can change independently
    of any code change, is fragile insurance. This test iterates every REGISTRY entry
    directly, so a malformed build_tiers() fails at test/CI time regardless of
    whatever alpha.regime.groups says today -- including for a future 5th module or
    a group that gets disabled later."""

    # Values must match each key's real config_schema.default_value (verified live
    # 2026-08-20), not an arbitrary placeholder -- a degenerate value here (e.g. 0.0)
    # can itself collapse an otherwise-correct build_tiers() into a malformed shape
    # (see test_duplicate_bound_raises above) and would make this contract test pass
    # vacuously on production-representative code. Keep these in sync with
    # config_schema when a default changes.
    _REPRESENTATIVE_PARAMS: dict[str, dict[str, float]] = {
        "breadth_vol": {},
        "curve_credit": {},
        "commodity_momentum_ts": {"primary_threshold": 0.75},
        "fx_dollar_carry": {"dollar_strong_threshold": 0.5, "carry_risk_on_threshold": 0.0},
    }

    def test_representative_params_cover_every_registered_module(self):
        assert set(self._REPRESENTATIVE_PARAMS) == set(REGISTRY), (
            "REGISTRY gained/lost a module -- add representative params for it above "
            "so this contract test covers it too."
        )

    def test_every_registered_module_build_tiers_is_ascending(self):
        for name, module in REGISTRY.items():
            tiers1, tiers2 = module.build_tiers(self._REPRESENTATIVE_PARAMS[name])
            _assert_ascending_tiers(tiers1, name, "tiers1")
            _assert_ascending_tiers(tiers2, name, "tiers2")


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
