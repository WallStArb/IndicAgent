"""
Unit tests for src/api/utils.py — shared API route utilities.
"""

from unittest.mock import MagicMock

import pytest

from src.api.utils import get_settings, parse_jsonb, resolve_contract


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
# resolve_contract
# ---------------------------------------------------------------------------


def test_resolve_contract_already_a_code():
    # symbol with digit → return as-is, no settings lookup
    assert resolve_contract("ESH6") == "ESH6"


def test_resolve_contract_base_to_contract(monkeypatch):
    mock_contract = MagicMock()
    mock_contract.base = "ES"
    mock_contract.symbol = "ESH6"
    mock_settings = MagicMock()
    mock_settings.contracts = [mock_contract]
    monkeypatch.setattr("src.api.utils.get_settings", lambda: mock_settings)
    assert resolve_contract("ES") == "ESH6"


def test_resolve_contract_vx_regex_fallback(monkeypatch):
    # "VX" should match "VXH6" via regex fallback (VIX futures have different base prefix)
    mock_contract = MagicMock()
    mock_contract.base = "VIX"
    mock_contract.symbol = "VXH6"
    mock_settings = MagicMock()
    mock_settings.contracts = [mock_contract]
    monkeypatch.setattr("src.api.utils.get_settings", lambda: mock_settings)
    assert resolve_contract("VX") == "VXH6"


def test_resolve_contract_unknown_fallback(monkeypatch):
    mock_settings = MagicMock()
    mock_settings.contracts = []
    monkeypatch.setattr("src.api.utils.get_settings", lambda: mock_settings)
    assert resolve_contract("UNKNOWN") == "UNKNOWN"


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
