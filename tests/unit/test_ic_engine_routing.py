"""Unit tests: ic_engine symbol -> regime group routing (Phase 144 Plan 05).

_build_symbol_regime_class is a pure function -- tested directly, mirroring the
import pattern established by test_ic_engine_staleness.py (project-root sys.path
insert, no fixtures/mocks needed for a pure dict-in/dict-out helper).

Coverage: single-group match, ambiguous multi-match raises AmbiguousRegimeGroupError,
zero-match omission (never defaulted to 'equity'), disabled-group exclusion, and
group order never being load-bearing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import AmbiguousRegimeGroupError, _build_symbol_regime_class

_EQUITY_GROUP = {"name": "equity", "tag_filter": ["eq_*", "intl_*"], "enabled": True}
_RATES_GROUP = {"name": "rates", "tag_filter": ["fi_*"], "enabled": True}
_GROUPS = [_EQUITY_GROUP, _RATES_GROUP]


class TestBuildSymbolRegimeClass:
    def test_fi_symbol_routes_to_rates(self):
        tags = {
            "TLT": {"fi_treasury"},
            "HYG": {"fi_credit_hy"},
            "AGG": {"fi_treasury", "fi_credit_ig"},
        }
        result = _build_symbol_regime_class(tags, _GROUPS)
        assert result["TLT"] == "rates"
        assert result["HYG"] == "rates"
        assert result["AGG"] == "rates"

    def test_equity_symbol_routes_to_equity(self):
        tags = {"SPY": {"eq_large_cap", "eq_blend"}, "EWT": {"intl_em", "eq_sector"}}
        result = _build_symbol_regime_class(tags, _GROUPS)
        assert result["SPY"] == "equity"
        assert result["EWT"] == "equity"

    def test_unmatched_symbol_is_excluded_not_defaulted(self):
        """No matching enabled group -> omitted from the result, not silently
        labeled 'equity'. Caller's mr_dicts_by_group.get(None) -> None, so
        the symbol is dropped from regime-stratified IC (pooled IC still
        covers it). This is the specific defect this test guards against --
        the pre-Phase-144 behavior silently mislabeled non-equity instruments
        under the SPY-vol x equity-breadth regime."""
        tags = {"GLD": {"commodity_metals"}, "BTC": {"crypto"}}
        result = _build_symbol_regime_class(tags, _GROUPS)
        assert "GLD" not in result
        assert "BTC" not in result

    def test_disabled_rates_group_excludes_fi_symbol(self):
        """When the only group a symbol's tags would match is disabled, the
        symbol is excluded -- it must NOT fall through to 'equity' just
        because equity is the remaining enabled group."""
        disabled_rates = {**_RATES_GROUP, "enabled": False}
        tags = {"TLT": {"fi_treasury"}}
        result = _build_symbol_regime_class(tags, [_EQUITY_GROUP, disabled_rates])
        assert "TLT" not in result

    def test_single_matching_group_used_regardless_of_list_order(self):
        """Group order in the config list must never be load-bearing."""
        tags = {"TLT": {"fi_treasury"}}
        result = _build_symbol_regime_class(tags, [_RATES_GROUP])
        assert result["TLT"] == "rates"
        result_reordered = _build_symbol_regime_class(tags, [_EQUITY_GROUP, _RATES_GROUP])
        assert result_reordered["TLT"] == "rates"

    def test_overlapping_tag_filters_raise_ambiguous_error(self):
        """A symbol matching two enabled groups is a config authoring error, not
        something resolved silently by array order."""
        overlapping_group = {"name": "credit", "tag_filter": ["fi_credit"], "enabled": True}
        tags = {"HYG": {"fi_credit_hy"}}
        with pytest.raises(AmbiguousRegimeGroupError):
            _build_symbol_regime_class(tags, [_RATES_GROUP, overlapping_group])

    def test_empty_tags_is_excluded(self):
        tags = {"XYZ": set()}
        result = _build_symbol_regime_class(tags, _GROUPS)
        assert "XYZ" not in result

    def test_preferred_fi_routes_to_rates(self):
        tags = {"PFF": {"fi_preferred"}}
        result = _build_symbol_regime_class(tags, _GROUPS)
        assert result["PFF"] == "rates"

    def test_exclude_symbols_carves_out_named_symbol_without_raising(self):
        """A symbol with genuine dual-categorical membership (e.g. a sector
        ETF whose earnings driver is a single commodity -- both eq_* and
        commodity_* tags legitimately weight=1.0) is routed via the group's
        exclude_symbols list instead of raising AmbiguousRegimeGroupError.
        Todo 224: AMLP/GDX/OIH/XLE/XOP carry both tags for real, not by
        tagging error -- excluding them from commodity's match is an
        explicit, auditable carve-out, not a silent precedence pick."""
        commodity_group = {
            "name": "commodity",
            "tag_filter": ["commodity_energy_crude"],
            "enabled": True,
            "exclude_symbols": ["XLE"],
        }
        excluded_tags = {"XLE": {"eq_sector", "commodity_energy_crude"}}
        result = _build_symbol_regime_class(excluded_tags, [_EQUITY_GROUP, commodity_group])
        assert result["XLE"] == "equity"

        not_excluded_tags = {"OIH": {"eq_sub_sector", "commodity_energy_crude"}}
        with pytest.raises(AmbiguousRegimeGroupError):
            _build_symbol_regime_class(not_excluded_tags, [_EQUITY_GROUP, commodity_group])

    def test_exclude_symbols_absent_defaults_to_no_exclusion(self):
        """A group with no exclude_symbols key behaves exactly as before --
        the field is opt-in, not a required key on every group config."""
        tags = {"TLT": {"fi_treasury"}}
        result = _build_symbol_regime_class(tags, _GROUPS)
        assert result["TLT"] == "rates"

    def test_build_symbol_regime_class_preserves_dual_write_field(self):
        """_build_symbol_regime_class itself only maps symbol -> group NAME; the
        dual_write_symbol_hmm field must be readable from the caller's own
        group_configs list (keyed by name), not lost anywhere in the routing path."""
        group_configs = [
            {
                "name": "rates",
                "tag_filter": ["fi_*"],
                "enabled": True,
                "dual_write_symbol_hmm": True,
            },
            {
                "name": "equity",
                "tag_filter": ["eq_*"],
                "enabled": True,
                "dual_write_symbol_hmm": False,
            },
        ]
        tags_by_symbol = {"TLT": {"fi_treasury"}, "SPY": {"eq_broad"}}
        symbol_regime_class = _build_symbol_regime_class(tags_by_symbol, group_configs)
        group_by_name = {g["name"]: g for g in group_configs}

        assert group_by_name[symbol_regime_class["TLT"]]["dual_write_symbol_hmm"] is True
        assert group_by_name[symbol_regime_class["SPY"]]["dual_write_symbol_hmm"] is False
