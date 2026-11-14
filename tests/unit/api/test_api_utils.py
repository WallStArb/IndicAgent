"""
Unit tests for src/api/utils.py — shared API route utilities.
"""

from src.api.utils import get_settings, parse_jsonb

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


# ---------------------------------------------------------------------------
# parse_jsonb
# ---------------------------------------------------------------------------


def test_parse_jsonb_none_returns_default():
    assert parse_jsonb(None, default={}) == {}
    assert parse_jsonb(None, default=None) is None


def test_parse_jsonb_string_parsed():
    assert parse_jsonb('{"a": 1}', default={}) == {"a": 1}


def test_parse_jsonb_invalid_string_returns_default():
    assert parse_jsonb("not-json", default={}) == {}
    assert parse_jsonb("not-json", default=None) is None


def test_parse_jsonb_dict_passthrough():
    d = {"a": 1}
    assert parse_jsonb(d, default={}) is d
