"""Migration 456 contract: the dated 1d default swap, Tradier to IBKR SMART (plan 185-47).

docs/research/1d-primary-swap-evidence.md rule R1 (shape F): the open 1d default row (primary
tradier, fallback ibkr) closes at D through the one UPDATE the append-only trigger allows, and a
new default (observed, primary ibkr, no fallback) opens at D. Every bar before D keeps its policy.
D must also be later than every Tradier observation at apply time; the plan's precondition query
and the migration's own guard assert that, not this test. Reads the .sql text only (no DB).
"""

from __future__ import annotations

import json
import re
from datetime import date

from src.intelligence.bars.sessions import nyse_sessions
from tests.unit._source_grep_helpers import read_source

_FILE = "456_swap_1d_primary_to_ibkr.sql"
_RAW = read_source("production", "migrations", _FILE)
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)

_EVIDENCE_KEYS = {
    "decision",
    "owner_decision_date",
    "basis_change_date",
    "tradier_last_bar_date",
    "volume_ratio_recent250_p10",
    "volume_ratio_recent250_p50",
    "volume_ratio_recent250_p90",
    "source_doc",
}


def _close_date() -> date:
    match = re.search(r"UPDATE bar_source_policy SET valid_to = DATE '(\d{4}-\d{2}-\d{2})'", _FLAT)
    assert match, "the default row is closed with a literal date"
    return date.fromisoformat(match.group(1))


def _evidence() -> dict:
    match = re.search(r"'(\{[^']*\})'::jsonb", _FLAT)
    assert match, "the new default carries a literal evidence object"
    return json.loads(match.group(1))


def test_swap_runs_in_one_transaction_under_lock_timeout():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")
    assert "SET LOCAL lock_timeout = '10s'" in _FLAT


def test_the_open_tradier_default_closes_at_d_by_the_one_allowed_update():
    assert _FLAT.count("UPDATE bar_source_policy") == 1
    assert re.search(
        r"UPDATE bar_source_policy SET valid_to = DATE '[\d-]+' WHERE timeframe = '1d' AND "
        r"symbol IS NULL AND valid_to IS NULL AND primary_source = 'tradier' AND "
        r"fallback_source = 'ibkr';",
        _FLAT,
    )


def test_one_ibkr_default_opens_at_d_with_no_fallback_and_is_guarded():
    d = _close_date()
    insert = re.search(
        r"INSERT INTO bar_source_policy \(timeframe, symbol, valid_from, valid_to, ingress_mode, "
        r"primary_source, fallback_source, reason, evidence\) SELECT '1d', NULL::text, "
        r"DATE '([\d-]+)', NULL::date, 'observed', 'ibkr', NULL::text, '[^']+', '\{[^']*\}'::jsonb "
        r"WHERE NOT EXISTS \( SELECT 1 FROM bar_source_policy p WHERE p.timeframe = '1d' AND "
        r"p.symbol IS NULL AND p.valid_to IS NULL \);",
        _FLAT,
    )
    assert insert, "one guarded INSERT of the IBKR default"
    assert date.fromisoformat(insert.group(1)) == d
    assert _FLAT.count("INSERT INTO bar_source_policy") == 1


def test_d_is_a_nyse_session():
    d = _close_date()
    assert d in nyse_sessions(d, d)


def test_the_migration_refuses_to_run_when_a_tradier_bar_is_dated_on_or_after_d():
    d = _close_date().isoformat()
    assert (
        f"WHERE timeframe = '1d' AND route = 'TRADIER' AND bar_date >= DATE '{d}'" in _FLAT
    ), "rule R1's stop condition is checked inside the transaction"
    assert "RAISE EXCEPTION" in _FLAT


def test_evidence_records_the_decision_d_and_the_volume_basis():
    evidence = _evidence()
    assert _EVIDENCE_KEYS <= set(evidence)
    assert evidence["basis_change_date"] == _close_date().isoformat()
    assert date.fromisoformat(evidence["tradier_last_bar_date"]) < _close_date()
    assert evidence["source_doc"] == "docs/research/1d-primary-swap-evidence.md"
    p10, p50, p90 = (evidence[f"volume_ratio_recent250_p{q}"] for q in (10, 50, 90))
    assert 0 < p10 < p50 < p90


def test_no_symbol_row_no_delete_and_no_schema_change():
    assert not re.search(r"\bsymbol\s*(=|IS NOT NULL|IN)\b", _FLAT.replace("p.symbol", ""))
    for statement in ("ALTER ", "DELETE", "TRUNCATE", "CONSTRAINT", "DROP ", "CREATE "):
        assert statement not in _FLAT, statement
