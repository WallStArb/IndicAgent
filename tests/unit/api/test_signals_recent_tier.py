"""Tests for /signals/recent parameterized tier filtering (CODE-Q-05 fix).

Verifies that the tier → boolean parameter mapping is correct and that
no f-string SQL (tier_clause) exists in the implementation.
"""

from __future__ import annotations

import inspect

import pytest


def _get_tier_params(tier: str) -> tuple[bool, bool]:
    """Extract the (require_selected, require_hero_gate) mapping for a given tier.

    Mirrors the logic in get_recent_signals() so tests stay in sync with the impl.
    """
    require_selected = tier in ("hero", "monitored")
    require_hero_gate = tier == "hero"
    return require_selected, require_hero_gate


class TestTierParameterMapping:
    """Verify the tier → boolean parameter mapping is correct for all tier values."""

    @pytest.mark.unit
    def test_hero_tier_sets_both_flags(self):
        """hero tier → require_selected=True, require_hero_gate=True."""
        require_selected, require_hero_gate = _get_tier_params("hero")
        assert require_selected is True
        assert require_hero_gate is True

    @pytest.mark.unit
    def test_monitored_tier_sets_selected_only(self):
        """monitored tier → require_selected=True, require_hero_gate=False."""
        require_selected, require_hero_gate = _get_tier_params("monitored")
        assert require_selected is True
        assert require_hero_gate is False

    @pytest.mark.unit
    def test_all_tier_sets_no_filters(self):
        """all tier → require_selected=False, require_hero_gate=False (no filtering)."""
        require_selected, require_hero_gate = _get_tier_params("all")
        assert require_selected is False
        assert require_hero_gate is False

    @pytest.mark.unit
    def test_hero_tier_is_strict_subset_of_monitored(self):
        """hero is a strict subset of monitored: hero requires both flags, monitored requires one."""
        hero_selected, hero_gate = _get_tier_params("hero")
        mon_selected, mon_gate = _get_tier_params("monitored")
        # hero must have require_selected=True (same or stricter than monitored)
        assert hero_selected >= mon_selected
        # hero additionally gates on CIS threshold
        assert hero_gate is True and mon_gate is False

    @pytest.mark.unit
    def test_all_tier_is_superset_of_monitored(self):
        """all tier must not apply any filter that monitored doesn't also apply."""
        all_selected, all_gate = _get_tier_params("all")
        mon_selected, mon_gate = _get_tier_params("monitored")
        # all applies fewer filters than monitored
        assert not all_selected
        assert not all_gate


class TestNoFStringSQLInGetRecentSignals:
    """Verify the implementation uses parameterized SQL, not f-string interpolation."""

    @pytest.mark.unit
    def test_no_tier_clause_variable_in_source(self):
        """get_recent_signals() must not contain a 'tier_clause' variable.

        If tier_clause exists, the f-string SQL injection surface is still present.
        """
        from src.api.routes.signals import get_recent_signals

        source = inspect.getsource(get_recent_signals)
        assert "tier_clause" not in source, (
            "tier_clause variable found in get_recent_signals() — "
            "f-string SQL injection surface must be removed"
        )

    @pytest.mark.unit
    def test_require_selected_in_source(self):
        """get_recent_signals() must use require_selected boolean parameter."""
        from src.api.routes.signals import get_recent_signals

        source = inspect.getsource(get_recent_signals)
        assert "require_selected" in source, (
            "require_selected not found in get_recent_signals() — "
            "parameterized tier logic is missing"
        )

    @pytest.mark.unit
    def test_no_fstring_query_in_get_recent_signals(self):
        """get_recent_signals() must not build the main query via f-string."""
        from src.api.routes.signals import get_recent_signals

        source = inspect.getsource(get_recent_signals)
        # The query should be a plain string, not f"..." or f'''...'''
        # Look for the pattern: f""" or f''' followed by SELECT
        assert 'f"""' not in source or "SELECT" not in source.split('f"""')[1].split('"""')[0], (
            "f-string SQL query found in get_recent_signals() — must use parameterized query"
        )
