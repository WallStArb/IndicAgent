"""Migration 598 contract: security_identifier gains the cik_ticker scheme (todo 609).

Reads the .sql text only (no DB), SQL line comments stripped.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_FILE = "598_security_identifier_cik_ticker_scheme.sql"
_CODE = re.sub(r"--[^\n]*", "", read_source("production", "migrations", _FILE))
_FLAT = re.sub(r"\s+", " ", _CODE)


def test_runs_in_one_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")


def test_both_constraints_are_dropped_if_present_and_added_back():
    for name in ("security_identifier_scheme_check", "ck_security_identifier_value_format"):
        assert f"DROP CONSTRAINT IF EXISTS {name}" in _FLAT
        assert f"ADD CONSTRAINT {name}" in _FLAT


def test_the_scheme_set_keeps_the_four_old_schemes_and_adds_cik_ticker():
    assert (
        "CHECK (scheme IN ('share_class_figi', 'composite_figi', 'isin', 'cusip', 'cik_ticker'))"
        in _FLAT
    )


def test_the_value_format_keeps_the_old_branches_and_pins_cik_colon_ticker():
    assert "WHEN 'isin' THEN value ~ '^[A-Z]{2}[0-9A-Z]{9}[0-9]$'" in _FLAT
    assert "WHEN 'cusip' THEN value ~ '^[0-9A-Z*@#]{8}[0-9]$'" in _FLAT
    assert "WHEN 'cik_ticker' THEN value ~ '^[0-9]{10}:[^[:space:]]+$'" in _FLAT
    assert "ELSE value ~ '^[B-DF-HJ-NP-TV-Z]{2}G[B-DF-HJ-NP-TV-Z0-9]{8}[0-9]$'" in _FLAT


def test_touches_no_table_data_and_owes_no_vacuum():
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|decompress_chunk|compress_chunk)\b", _CODE)
