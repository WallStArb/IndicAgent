"""
Unit tests for src/api/utils.py — shared API route utilities.
"""

from src.api.utils import get_settings

# ---------------------------------------------------------------------------
# get_settings
# ---------------------------------------------------------------------------


def test_get_settings_returns_settings_instance():
    from src.config.settings import Settings

    result = get_settings()
    assert isinstance(result, Settings)


def test_get_settings_is_cached():
    result1 = get_settings()
    result2 = get_settings()
    assert result1 is result2
