"""Migration 543 contract: the no-trade rule keys of the 1d session_coverage verdict.

The audit's _IntegrityParams defaults must equal the seeds, so a run before the migration lands
judges as one after. Reads the .sql text only (no DB), SQL line comments stripped.
"""

from __future__ import annotations

import re

from services.bar_reconciliation_audit import _IntegrityParams
from tests.unit._source_grep_helpers import read_source

_RAW = read_source("production", "migrations", "543_bar_integrity_no_trade_rule_apr.sql")
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)
_PREFIX = "threshold.bar_integrity."
_STATE = dict(re.findall(r"\('(threshold\.bar_integrity\.[a-z_]+)', '([0-9.]+)', 1\)", _FLAT))


def test_runs_in_one_transaction_and_is_idempotent():
    assert _CODE.strip().startswith("BEGIN;") and _CODE.rstrip().endswith("COMMIT;")
    assert _FLAT.count("ON CONFLICT (config_key) DO NOTHING") == 2
    assert re.search(r"NOT EXISTS \( SELECT 1 FROM config_history h", _FLAT)
    assert "'migration:543'" in _FLAT


def test_three_keys_each_with_provenance_and_not_an_ml_target():
    assert set(_STATE) == {
        _PREFIX + "no_trade_run_max_sessions",
        _PREFIX + "no_trade_neighbor_window_sessions",
        _PREFIX + "no_trade_neighbor_median_volume_max_shares",
    }
    for key in _STATE:
        description = _FLAT.split(f"( '{key}', '")[1].split("' ),")[0]
        assert "[rca_analysis]" in description and "Not an ML learning target" in description


def test_the_audit_defaults_equal_the_seeds():
    params = _IntegrityParams.from_apr({})
    assert params.no_trade_run_max_sessions == int(_STATE[_PREFIX + "no_trade_run_max_sessions"])
    assert params.no_trade_neighbor_window_sessions == int(
        _STATE[_PREFIX + "no_trade_neighbor_window_sessions"]
    )
    assert params.no_trade_neighbor_median_volume_max_shares == float(
        _STATE[_PREFIX + "no_trade_neighbor_median_volume_max_shares"]
    )
    # the dataclass field defaults (used where from_apr is bypassed) agree as well
    bare = _IntegrityParams(0.999, 5, 30, 20, 10.0)
    assert bare.no_trade_run_max_sessions == params.no_trade_run_max_sessions
    assert bare.no_trade_neighbor_window_sessions == params.no_trade_neighbor_window_sessions
    assert (
        bare.no_trade_neighbor_median_volume_max_shares
        == params.no_trade_neighbor_median_volume_max_shares
    )


def test_defaults_match_the_schema_default_column():
    for key, value in _STATE.items():
        assert re.search(rf"\( '{key}', '(int|float)', '{re.escape(value)}'", _FLAT)
