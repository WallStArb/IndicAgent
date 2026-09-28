"""D0 data-quality label arithmetic tests (D-04).

The labels an attempt carries: venue truncation share, dividend label,
scrub-flag share and the survivorship bound. Pure synthetic panels pin each
behavior, including the conservative unknown-exchange mapping and the manifest
round-trip the S0 manifest and S6 evidence consume unchanged.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from src.intelligence.bars.labels import (
    DataQualityLabels,
    DividendLabel,
    SurvivorshipBound,
    SurvivorshipRule,
    build_labels,
    delisting_sensitivity,
    dividend_label,
    scrub_flag_share,
    survivorship_bound,
    venue_truncation_share,
)

_RULE = SurvivorshipRule(
    delisting_return_nasdaq=-0.55,
    delisting_return_nyse_amex=-0.30,
    hazard_nasdaq_annual=0.056,
    hazard_nyse_amex_annual=0.012,
    haircut_small_cap_annual=0.015,
    trading_days_per_year=252,
)


def _panel_symbols(n_symbols: int = 10, n_sessions: int = 100) -> np.ndarray:
    """Flattened (name, session) cell symbols: each symbol in n_sessions cells."""
    return np.repeat(np.array([f"S{i:02d}" for i in range(n_symbols)], dtype="<U8"), n_sessions)


def _cell_keys(n: int = 1000) -> np.ndarray:
    """Structured (symbol, ts_seconds) keys, n cells over 10 symbols."""
    return np.array(
        [(f"S{i % 10:02d}", 1_700_000_000 + i) for i in range(n)],
        dtype=[("symbol", "U8"), ("ts", "i8")],
    )


def test_venue_truncation_share_two_moved_of_ten_symbols():
    symbols = _panel_symbols()
    assert symbols.size == 1000
    moved = frozenset({"S03", "S07"})
    assert venue_truncation_share(symbols, moved) == pytest.approx(0.2)


def test_venue_truncation_share_no_moved_symbols_is_zero():
    assert venue_truncation_share(_panel_symbols(), frozenset()) == pytest.approx(0.0)


def test_dividend_label_uncovered_share_150_of_1000():
    covered = np.ones(1000, dtype=bool)
    covered[:150] = False
    label = dividend_label(True, covered)
    assert isinstance(label, DividendLabel)
    assert label.total_return is True
    assert label.uncovered_share == pytest.approx(0.15)


def test_dividend_label_rejects_non_boolean_coverage():
    with pytest.raises(TypeError):
        dividend_label(False, np.zeros(10))


def test_scrub_flag_share_counts_only_keys_present_in_cells():
    cells = _cell_keys()
    flagged = frozenset(
        {(str(cells["symbol"][i]), int(cells["ts"][i])) for i in range(7)}
        | {("GHOST", 9_999)}  # a flagged bar outside the attempt's cells
    )
    assert scrub_flag_share(cells, flagged) == pytest.approx(0.007)


def test_scrub_flag_share_accepts_object_tuples():
    cells = np.empty(4, dtype=object)
    cells[:] = [("A", 1), ("A", 2), ("B", 1), ("B", 2)]
    assert scrub_flag_share(cells, frozenset({("B", 2)})) == pytest.approx(0.25)


def test_scrub_flag_share_rejects_2d_keys():
    cells = np.array([[("A", 1)], [("A", 2)]], dtype=object)
    with pytest.raises(ValueError):
        scrub_flag_share(cells, frozenset({("A", 1)}))


def test_delisting_sensitivity_full_nasdaq_long_252_sessions():
    weights = np.ones((252, 1))
    got = delisting_sensitivity(weights, ["ISLAND"], _RULE)
    assert got == pytest.approx(0.056 * -0.55, abs=1e-9)


def test_delisting_sensitivity_flat_long_short_equal_exchange_mix_is_zero():
    weights = np.tile([0.5, 0.5, -0.5, -0.5], (60, 1))
    exchanges = ["ISLAND", "NYSE", "ISLAND", "NYSE"]
    assert delisting_sensitivity(weights, exchanges, _RULE) == pytest.approx(0.0, abs=1e-12)


def test_delisting_sensitivity_maps_unknown_exchange_to_nasdaq():
    weights = np.array([[1.0]])
    conservative = delisting_sensitivity(weights, ["SOMETHING_ELSE"], _RULE)
    nasdaq = delisting_sensitivity(weights, ["NASDAQ"], _RULE)
    assert conservative == nasdaq


def test_delisting_sensitivity_rejects_weight_exchange_mismatch():
    with pytest.raises(ValueError):
        delisting_sensitivity(np.ones((5, 2)), ["ISLAND"], _RULE)


def test_survivorship_rule_from_apr_reads_all_six_keys():
    apr = {
        "alpha.survivorship.delisting_return.nasdaq": -0.55,
        "alpha.survivorship.delisting_return.nyse_amex": -0.30,
        "alpha.survivorship.hazard.nasdaq_annual": 0.056,
        "alpha.survivorship.hazard.nyse_amex_annual": 0.012,
        "alpha.survivorship.haircut.small_cap_annual": 0.015,
        "alpha.survivorship.trading_days_per_year": 252,
    }
    assert SurvivorshipRule.from_apr(apr) == _RULE


def test_survivorship_bound_without_weights_is_conservative():
    bound = survivorship_bound(_RULE, small_cap_share=0.4)
    assert isinstance(bound, SurvivorshipBound)
    assert bound.haircut_annual == pytest.approx(0.4 * 0.015)
    # no weights: the conservative exchange's hazard x |delisting return|
    assert bound.expected_delisting_drag_annual == pytest.approx(0.056 * 0.55)
    assert bound.sensitivity is None


def test_survivorship_bound_with_weights_carries_signed_sensitivity():
    weights = np.tile([0.5, 0.5, -0.5, -0.5], (60, 1))
    exchanges = ["ISLAND", "NYSE", "ISLAND", "NYSE"]
    bound = survivorship_bound(_RULE, small_cap_share=0.4, weights=weights, exchange_of=exchanges)
    assert bound.sensitivity == pytest.approx(0.0, abs=1e-12)
    # gross drag: both sides carry the hazard-weighted |delisting return|
    assert bound.expected_delisting_drag_annual == pytest.approx(0.056 * 0.55 + 0.012 * 0.30)


def test_survivorship_bound_rejects_weights_without_exchanges():
    with pytest.raises(ValueError):
        survivorship_bound(_RULE, small_cap_share=0.1, weights=np.ones((3, 1)))


def test_build_labels_and_manifest_round_trip_through_json():
    covered = np.ones(1000, dtype=bool)
    covered[:150] = False
    cells = _cell_keys()
    flagged = frozenset({(str(cells["symbol"][i]), int(cells["ts"][i])) for i in range(7)})
    weights = np.tile([0.5, 0.5, -0.5, -0.5], (60, 1))
    exchanges = ["ISLAND", "NYSE", "ISLAND", "NYSE"]

    labels = build_labels(
        d2_rule_version="d2-2026-10-01.abc1234",
        cell_symbols=_panel_symbols(),
        moved_symbols=frozenset({"S03", "S07"}),
        total_return=True,
        div_covered=covered,
        cell_keys=cells,
        flagged_keys=flagged,
        rule=_RULE,
        small_cap_share=0.4,
        weights=weights,
        exchange_of=exchanges,
    )
    assert isinstance(labels, DataQualityLabels)
    assert labels.d2_rule_version == "d2-2026-10-01.abc1234"

    manifest = labels.to_manifest()
    assert set(manifest) == {
        "d2_rule_version",
        "venue_truncation_share",
        "dividends",
        "survivorship",
        "scrub_flag_share",
    }
    assert manifest["venue_truncation_share"] == pytest.approx(0.2)
    assert manifest["dividends"] == {
        "total_return": True,
        "uncovered_share": pytest.approx(0.15),
    }
    assert set(manifest["survivorship"]) == {
        "haircut_annual",
        "expected_delisting_drag_annual",
        "sensitivity",
    }
    assert manifest["scrub_flag_share"] == pytest.approx(0.007)

    round_tripped = json.loads(json.dumps(manifest))
    assert round_tripped == manifest
