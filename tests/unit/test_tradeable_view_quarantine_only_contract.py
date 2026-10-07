"""The latest migration that defines market_data_ohlcv_tradeable filters on the quarantine flag
only, never on price_sanity_status (plan 185-38, todo 500): bar_quality_flag is the one
visibility rule. Reads production/migrations only (no DB)."""

from __future__ import annotations

import re

from tests.unit._migration_catalog import migration_files, strip_sql_comments

_DEFINES = "CREATE OR REPLACE VIEW market_data_ohlcv_tradeable AS"


def _latest_definition() -> tuple[str, str]:
    latest = None
    for path in migration_files():
        flat = re.sub(r"\s+", " ", strip_sql_comments(path.read_text()))
        if _DEFINES in flat:
            latest = (path.name, flat.split(_DEFINES)[-1].split(";")[0])
    assert latest is not None
    return latest


def test_latest_tradeable_view_has_no_price_sanity_predicate():
    name, view = _latest_definition()
    where = view.split(" WHERE ", 1)[1]
    assert "price_sanity_status" not in where, name
    assert "q.quarantine" in where, name
    assert "volume > 0" in where, name
