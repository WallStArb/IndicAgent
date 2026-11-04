"""The beta builders run on dates every series has a bar on (todo 584 8b).

A date the name has no bar on used to read as a stale close, a fabricated 0.0 return that entered
the beta window; it must emit no record and leave the neighbours' returns spanning the gap.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import numpy as np

from src.intelligence.features.kernels.macro import build_symbol_beta_series, common_bar_dates
from tests.unit.intelligence import kernel_parity_reference as ref

CONFIG = dataclasses.replace(
    ref.build_config(ref.load_manifest()["synthetic_config"]),
    factor_beta_window=10,
    factor_beta_zscore_window=10,
)
START = datetime(2024, 1, 2, tzinfo=UTC)


def _bars(closes, skip=()):
    return [
        {"ts": START + timedelta(days=i), "close": float(c)}
        for i, c in enumerate(closes)
        if i not in skip
    ]


def _walk(n, seed):
    return 100.0 * np.cumprod(1.0 + np.random.default_rng(seed).normal(0, 0.01, n))


def test_common_bar_dates_is_the_sorted_intersection():
    a = [START.date() + timedelta(days=i) for i in (0, 1, 2, 4)]
    b = [START.date() + timedelta(days=i) for i in (1, 2, 3, 4)]
    assert common_bar_dates({"a": a, "b": b}) == [a[1], a[2], a[3]]


def test_a_date_the_name_has_no_bar_on_emits_no_beta_record():
    name, spy, tlt = _walk(80, 1), _walk(80, 2), _walk(80, 3)
    records = build_symbol_beta_series(
        _bars(name, skip={40}), _bars(spy), _bars(tlt), "ABC", CONFIG
    )
    assert (START + timedelta(days=40)).date() not in records
    assert (START + timedelta(days=41)).date() in records


def test_a_gap_day_does_not_enter_the_return_window_as_zero():
    """With the name's bar missing, the run equals the run on series where that date is absent
    from all three, so no zero return was inserted."""
    name, spy, tlt = _walk(80, 1), _walk(80, 2), _walk(80, 3)
    gapped = build_symbol_beta_series(_bars(name, skip={40}), _bars(spy), _bars(tlt), "ABC", CONFIG)
    removed = build_symbol_beta_series(
        _bars(name, skip={40}), _bars(spy, skip={40}), _bars(tlt, skip={40}), "ABC", CONFIG
    )
    assert gapped.keys() == removed.keys()
    for d in gapped:
        np.testing.assert_array_equal(
            np.array(gapped[d], dtype=float), np.array(removed[d], dtype=float)
        )
