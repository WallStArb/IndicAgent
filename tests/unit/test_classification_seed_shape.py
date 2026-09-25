"""Shape tests over the real indicagent_v1 seed data (Phase 182, Plan 03). No DB.

The committed migration 365 must equal the render of the data module byte for byte, so the
reviewed data and the applied SQL cannot diverge.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

from src.config.classification_seed import render_seed_sql, validate_seed
from src.config.classification_seed_data import ASSIGNMENTS, NODES, SCHEME
from src.config.classification_service import (
    SOURCE_REF_CONTRACT_SPEC,
    SOURCE_REF_FUND_MANDATE,
    SOURCE_REF_IBKR_REVIEWED,
)

_ROOT = Path(__file__).resolve().parents[2]
_CSV = _ROOT / "config" / "classification" / "ibkr_classification_candidates.csv"
_MIGRATION = _ROOT / "production" / "migrations" / "365_indicagent_v1_classification_seed.sql"

_NODE_BY_CODE = {n.code: n for n in NODES}
_ASSIGNMENT_BY_SYMBOL = {a.symbol: a for a in ASSIGNMENTS}

_EXPECTED_ROOTS = {
    "EQ": "Equity",
    "FI": "Fixed income",
    "CMD": "Commodity",
    "CCY": "Currency",
    "CRY": "Crypto",
    "VOL": "Volatility",
    "MA": "Multi-asset",
}
_EXPECTED_EQ_SECTORS = {
    "EQ.EN": "Energy",
    "EQ.MAT": "Materials",
    "EQ.IND": "Industrials",
    "EQ.CD": "Consumer Discretionary",
    "EQ.CS": "Consumer Staples",
    "EQ.HC": "Health Care",
    "EQ.FIN": "Financials",
    "EQ.IT": "Information Technology",
    "EQ.COM": "Communication Services",
    "EQ.UTL": "Utilities",
    "EQ.RE": "Real Estate",
    "EQ.BROAD": "Broad market (multi-sector)",
}
_EXPECTED_EQ_GROUPS = {
    "EQ.EN.ENERGY": "Energy",
    "EQ.MAT.MATERIALS": "Materials",
    "EQ.IND.CAPGOODS": "Capital Goods",
    "EQ.IND.COMMSVC": "Commercial & Professional Services",
    "EQ.IND.TRANSPORT": "Transportation",
    "EQ.CD.AUTO": "Automobiles & Components",
    "EQ.CD.DURABLES": "Consumer Durables & Apparel",
    "EQ.CD.SERVICES": "Consumer Services",
    "EQ.CD.RETAIL": "Consumer Discretionary Distribution & Retail",
    "EQ.CS.RETAIL": "Consumer Staples Distribution & Retail",
    "EQ.CS.FOOD": "Food, Beverage & Tobacco",
    "EQ.CS.HOUSEHOLD": "Household & Personal Products",
    "EQ.HC.EQUIPSVC": "Health Care Equipment & Services",
    "EQ.HC.PHARMA": "Pharmaceuticals, Biotechnology & Life Sciences",
    "EQ.FIN.BANKS": "Banks",
    "EQ.FIN.FINSVC": "Financial Services",
    "EQ.FIN.INSURANCE": "Insurance",
    "EQ.IT.SOFTWARE": "Software & Services",
    "EQ.IT.HARDWARE": "Technology Hardware & Equipment",
    "EQ.IT.SEMI": "Semiconductors & Semiconductor Equipment",
    "EQ.COM.TELECOM": "Telecommunication Services",
    "EQ.COM.MEDIA": "Media & Entertainment",
    "EQ.UTL.UTILITIES": "Utilities",
    "EQ.RE.REITS": "Equity Real Estate Investment Trusts (REITs)",
    "EQ.RE.MGMT": "Real Estate Management & Development",
}


def _candidates() -> dict[str, dict[str, str]]:
    with _CSV.open(newline="") as handle:
        return {row["symbol"]: row for row in csv.DictReader(handle)}


def _triple(row: dict[str, str]) -> str:
    return f"{row['industry']} / {row['category']} / {row['subcategory']}"


def test_seed_shape_validates() -> None:
    validate_seed(SCHEME, NODES, ASSIGNMENTS)


def test_seed_shape_scheme_is_not_gics() -> None:
    assert SCHEME.scheme == "indicagent_v1"
    assert SCHEME.authority == "IndicAgent"
    for value in (SCHEME.scheme, SCHEME.name, SCHEME.authority, SCHEME.source_ref):
        assert "gics" not in value.lower()


def test_seed_shape_roots() -> None:
    roots = {n.code: n.name for n in NODES if n.level == 1}
    assert roots == _EXPECTED_ROOTS


def test_seed_shape_equity_sectors_and_groups() -> None:
    sectors = {n.code: n.name for n in NODES if n.level == 2 and n.code.startswith("EQ.")}
    groups = {n.code: n.name for n in NODES if n.level == 3 and n.code.startswith("EQ.")}
    assert sectors == _EXPECTED_EQ_SECTORS
    assert groups == _EXPECTED_EQ_GROUPS


def test_seed_shape_codes_embed_parent() -> None:
    for node in NODES:
        assert node.level <= 4
        if node.level == 1:
            assert node.parent_code is None
        else:
            assert node.code.startswith(node.parent_code + ".")
            assert node.parent_code in _NODE_BY_CODE


def test_seed_shape_d05_anchors_and_plan04_pins() -> None:
    expected = {
        "SPY": "EQ.BROAD",
        "XLK": "EQ.IT",
        "SMH": "EQ.IT.SEMI.EQUIP",
        "EMLC": "FI.EM",
        "VIXY": "VOL.EQUITY",
    }
    assert {s: _ASSIGNMENT_BY_SYMBOL[s].code for s in expected} == expected


def test_seed_shape_single_names_follow_ibkr_candidates() -> None:
    candidates = _candidates()
    for symbol, row in candidates.items():
        assert row["status"] == "ok", symbol
        assignment = _ASSIGNMENT_BY_SYMBOL.get(symbol)
        assert assignment is not None, f"{symbol} has no assignment"
        assert assignment.source_ref == SOURCE_REF_IBKR_REVIEWED, symbol
        assert _NODE_BY_CODE[assignment.code].level == 4, symbol
        assert assignment.basis == _triple(row), symbol
    others = [a for a in ASSIGNMENTS if a.symbol not in candidates]
    for assignment in others:
        assert assignment.source_ref in (
            SOURCE_REF_FUND_MANDATE,
            SOURCE_REF_CONTRACT_SPEC,
        ), assignment.symbol


def test_seed_shape_shared_triple_minorities_carry_override_reason() -> None:
    candidates = _candidates()
    by_triple: dict[str, list] = defaultdict(list)
    for symbol, row in candidates.items():
        by_triple[_triple(row)].append(_ASSIGNMENT_BY_SYMBOL[symbol])
    for triple, assignments in by_triple.items():
        counts = Counter(a.code for a in assignments)
        if len(counts) < 2:
            continue
        # At most one code group (the plurality) may go without override reasons.
        unexplained = {a.code for a in assignments if not a.override_reason.strip()}
        assert len(unexplained) <= 1, (triple, sorted(unexplained))
        if unexplained:
            (code,) = unexplained
            assert counts[code] == max(counts.values()), (triple, code)


def test_seed_shape_migration_matches_render() -> None:
    assert _MIGRATION.read_text() == render_seed_sql(SCHEME, NODES, ASSIGNMENTS)
