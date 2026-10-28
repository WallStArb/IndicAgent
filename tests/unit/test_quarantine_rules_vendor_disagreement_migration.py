"""Migration 528: the D-191-Q arbitration's quarantine rule joins the APR quarantine list
(todo 545, data lane decision 2026-10-28)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL = (ROOT / "production/migrations/528_quarantine_rule_vendor_disagreement.sql").read_text()


def test_the_rule_is_appended_once_with_a_version_bump():
    flat = " ".join(SQL.split())
    assert "config_value::jsonb || '[\"vendor_disagreement\"]'::jsonb" in flat
    assert "version = version + 1" in flat
    assert "AND NOT (config_value::jsonb ? 'vendor_disagreement')" in flat


def test_the_change_is_recorded_in_config_history_by_the_data_lane():
    flat = " ".join(SQL.split())
    assert "INSERT INTO config_history" in flat
    assert "'data_lane'" in flat and "D-191-Q arbitration quarantine" in flat
