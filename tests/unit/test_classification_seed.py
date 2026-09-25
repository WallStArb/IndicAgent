"""Unit tests for src/config/classification_seed.py (Phase 182, Plan 03).

Synthetic fixtures only: no real seed data, no DB connection.
"""

from __future__ import annotations

import dataclasses

import pytest

from src.config import classification_seed as cs
from src.config.classification_seed import (
    AssignmentSeed,
    NodeSeed,
    SchemeSeed,
    render_node_guard_sql,
    render_seed_sql,
    validate_seed,
)

_SCHEME = SchemeSeed(
    scheme="toy_v1",
    name="Toy classification",
    authority="IndicAgent",
    source_ref="phase_182_build",
)

_NODES = (
    NodeSeed("EQ", None, 1, "Equity"),
    NodeSeed("EQ.IT", "EQ", 2, "Information Technology"),
    NodeSeed("EQ.IT.SEMI", "EQ.IT", 3, "Semiconductors & Semiconductor Equipment"),
    NodeSeed("EQ.IT.SEMI.EQUIP", "EQ.IT.SEMI", 4, "Semiconductors & Semiconductor Equipment"),
    NodeSeed("EQ.BROAD", "EQ", 2, "Broad market (multi-sector)"),
    NodeSeed("FI", None, 1, "Fixed income"),
    NodeSeed("FI.RATES", "FI", 2, "Government rates"),
)

_ASSIGNMENTS = (
    AssignmentSeed("SPY", "EQ.BROAD", "fund_mandate", "SPDR S&P 500: US large caps"),
    AssignmentSeed(
        "NVDA",
        "EQ.IT.SEMI.EQUIP",
        "ibkr_contract_details+review",
        "Technology / Semiconductors / Electronic Compo-Semicon",
    ),
    AssignmentSeed("TLT", "FI.RATES", "fund_mandate", "iShares 20+ Year Treasury"),
)


def _errors(scheme=_SCHEME, nodes=_NODES, assignments=_ASSIGNMENTS) -> str:
    with pytest.raises(ValueError) as info:
        validate_seed(scheme, nodes, assignments)
    return str(info.value)


def test_seed_validate_passes_for_consistent_tree() -> None:
    validate_seed(_SCHEME, _NODES, _ASSIGNMENTS)


def test_seed_validate_rejects_bad_code_regex() -> None:
    nodes = _NODES + (NodeSeed("eq.lower", None, 1, "Bad"),)
    assert "eq.lower" in _errors(nodes=nodes)


def test_seed_validate_rejects_level_mismatch() -> None:
    nodes = tuple(dataclasses.replace(n, level=3) if n.code == "EQ.IT" else n for n in _NODES)
    assert "level" in _errors(nodes=nodes)


def test_seed_validate_rejects_parent_not_code_prefix() -> None:
    nodes = _NODES + (NodeSeed("FI.MUNI", "EQ", 2, "Municipal"),)
    assignments = _ASSIGNMENTS + (AssignmentSeed("MUB", "FI.MUNI", "fund_mandate", "munis"),)
    assert "FI.MUNI" in _errors(nodes=nodes, assignments=assignments)


def test_seed_validate_rejects_missing_parent() -> None:
    nodes = tuple(n for n in _NODES if n.code != "EQ.IT.SEMI")
    assert "EQ.IT.SEMI" in _errors(nodes=nodes)


def test_seed_validate_rejects_duplicate_code() -> None:
    nodes = _NODES + (NodeSeed("FI.RATES", "FI", 2, "Rates again"),)
    assert "duplicate node code" in _errors(nodes=nodes)


def test_seed_validate_rejects_duplicate_symbol() -> None:
    assignments = _ASSIGNMENTS + (AssignmentSeed("SPY", "EQ.BROAD", "fund_mandate", "again"),)
    assert "duplicate assignment symbol" in _errors(assignments=assignments)


def test_seed_validate_rejects_unknown_assignment_code() -> None:
    assignments = _ASSIGNMENTS + (AssignmentSeed("XLF", "EQ.FIN", "fund_mandate", "financials"),)
    assert "EQ.FIN" in _errors(assignments=assignments)


def test_seed_validate_rejects_unknown_source_ref() -> None:
    assignments = _ASSIGNMENTS + (AssignmentSeed("IEF", "FI.RATES", "vendor_feed", "x"),)
    assert "vendor_feed" in _errors(assignments=assignments)


@pytest.mark.parametrize("field", ["name", "authority", "source_ref"])
def test_seed_validate_rejects_gics_in_scheme_fields(field: str) -> None:
    scheme = dataclasses.replace(_SCHEME, **{field: "Gics-like"})
    assert "GICS" in _errors(scheme=scheme)


def test_seed_validate_rejects_non_indicagent_authority() -> None:
    scheme = dataclasses.replace(_SCHEME, authority="MSCI")
    assert "authority" in _errors(scheme=scheme)


def test_seed_validate_rejects_unused_non_equity_node() -> None:
    nodes = _NODES + (NodeSeed("FI.MUNI", "FI", 2, "Municipal"),)
    assert "FI.MUNI" in _errors(nodes=nodes)


def test_seed_validate_rejects_unused_equity_level4() -> None:
    nodes = _NODES + (
        NodeSeed("EQ.IT.SOFTWARE", "EQ.IT", 3, "Software & Services"),
        NodeSeed("EQ.IT.SOFTWARE.SOFTWARE", "EQ.IT.SOFTWARE", 4, "Software"),
    )
    message = _errors(nodes=nodes)
    assert "EQ.IT.SOFTWARE.SOFTWARE" in message
    # An unused equity level-3 group is allowed (all 25 groups are seeded in full).
    assert "'EQ.IT.SOFTWARE'" not in message


def test_seed_validate_reports_every_problem_at_once() -> None:
    nodes = _NODES + (NodeSeed("bad", None, 1, "x"), NodeSeed("FI.MUNI", "FI", 2, "Muni"))
    message = _errors(nodes=nodes)
    assert "bad" in message and "FI.MUNI" in message


def test_seed_render_is_deterministic_and_ordered() -> None:
    first = render_seed_sql(_SCHEME, _NODES, _ASSIGNMENTS)
    second = render_seed_sql(_SCHEME, tuple(reversed(_NODES)), tuple(reversed(_ASSIGNMENTS)))
    assert first == second
    # nodes ordered by (level, code)
    assert first.index("('EQ', NULL") < first.index("('FI', NULL") < first.index("('EQ.BROAD'")
    assert first.index("('EQ.IT.SEMI', ") < first.index("('EQ.IT.SEMI.EQUIP'")
    # assignments ordered by symbol
    assert first.index("('NVDA'") < first.index("('SPY'") < first.index("('TLT'")


def test_seed_render_section_order() -> None:
    sql = render_seed_sql(_SCHEME, _NODES, _ASSIGNMENTS)
    markers = [
        "BEGIN;",
        "INSERT INTO classification_scheme",
        "ON CONFLICT (scheme) DO NOTHING",
        "authority IS DISTINCT FROM",
        "CREATE TEMP TABLE _seed_classification_node",
        "ON COMMIT DROP",
        "n.parent_code IS DISTINCT FROM s.parent_code",
        "WITH RECURSIVE",
        "ON CONFLICT (scheme, code) DO UPDATE SET name = EXCLUDED.name",
        "CREATE TEMP TABLE _seed_instrument_classification",
        "c.code <> s.code",
        "INSERT INTO instrument_classification",
        "JOIN instruments i",
        "RAISE NOTICE",
        "active instruments without a current toy_v1 assignment: %",
        "COMMIT;",
    ]
    positions = [sql.index(m) for m in markers]
    assert positions == sorted(positions)


def test_seed_render_only_update_is_node_name() -> None:
    sql = render_seed_sql(_SCHEME, _NODES, _ASSIGNMENTS)
    assert sql.count("DO UPDATE") == 1
    assert "DO UPDATE SET name = EXCLUDED.name" in sql
    assert "UPDATE instrument_classification" not in sql
    assert "DELETE" not in sql.upper().replace("ON DELETE", "")


def test_seed_render_uses_apply_date_not_literal() -> None:
    sql = render_seed_sql(_SCHEME, _NODES, _ASSIGNMENTS)
    assert sql.count("(now() AT TIME ZONE 'UTC')::date") == 2
    import re

    assert not re.search(r"'\d{4}-\d{2}-\d{2}'", sql)


def test_seed_render_transaction_false_omits_begin_commit_only() -> None:
    with_tx = render_seed_sql(_SCHEME, _NODES, _ASSIGNMENTS)
    without_tx = render_seed_sql(_SCHEME, _NODES, _ASSIGNMENTS, transaction=False)
    assert "BEGIN;" not in without_tx and "COMMIT;" not in without_tx
    stripped = with_tx.replace("BEGIN;\n\n", "").replace("\n\nCOMMIT;\n", "\n")
    assert stripped == without_tx


def test_seed_render_escapes_single_quotes() -> None:
    nodes = tuple(
        dataclasses.replace(n, name="Investors' Broad") if n.code == "EQ.BROAD" else n
        for n in _NODES
    )
    sql = render_seed_sql(_SCHEME, nodes, _ASSIGNMENTS)
    assert "'Investors'' Broad'" in sql


def test_seed_render_never_includes_basis_text() -> None:
    sql = render_seed_sql(_SCHEME, _NODES, _ASSIGNMENTS)
    assert "Electronic Compo-Semicon" not in sql


def test_seed_render_calls_validate() -> None:
    nodes = _NODES + (NodeSeed("FI.MUNI", "FI", 2, "Muni"),)
    with pytest.raises(ValueError):
        render_seed_sql(_SCHEME, nodes, _ASSIGNMENTS)


def test_seed_render_rejects_unsafe_scheme_identifier() -> None:
    scheme = dataclasses.replace(_SCHEME, scheme="toy'; DROP TABLE x; --")
    with pytest.raises(ValueError):
        render_seed_sql(scheme, _NODES, _ASSIGNMENTS)
    with pytest.raises(ValueError):
        render_node_guard_sql(scheme.scheme, _NODES)


def test_seed_node_guard_sql_is_staging_and_guard_only() -> None:
    sql = render_node_guard_sql("toy_v1", _NODES)
    assert "CREATE TEMP TABLE _seed_classification_node" in sql
    assert "n.parent_code IS DISTINCT FROM s.parent_code" in sql
    assert "INSERT INTO classification_node" not in sql
    assert "BEGIN;" not in sql and "COMMIT;" not in sql
    assert sql in render_seed_sql(_SCHEME, _NODES, _ASSIGNMENTS)


def test_seed_node_guard_sql_skips_validation() -> None:
    inconsistent = _NODES + (NodeSeed("EQ.IT", "FI", 3, "Reparented"),)
    sql = render_node_guard_sql("toy_v1", inconsistent)
    assert "('EQ.IT', 'FI', 3, 'Reparented')" in sql


def test_seed_cli_check_and_write(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cs, "_load_data", lambda: (_SCHEME, _NODES, _ASSIGNMENTS))
    target = tmp_path / "365_seed.sql"
    assert cs.main(["--write", str(target)]) == 0
    assert target.read_text() == render_seed_sql(_SCHEME, _NODES, _ASSIGNMENTS)
    assert cs.main(["--check", str(target)]) == 0
    target.write_text(target.read_text() + "-- drift\n")
    assert cs.main(["--check", str(target)]) == 1
    assert cs.main(["--check", str(tmp_path / "missing.sql")]) == 1
