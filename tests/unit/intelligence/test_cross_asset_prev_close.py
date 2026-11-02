"""Todo 464: the cross-asset builder tracks TIP, HYG and LQD previous closes before the first
record date (the date SPY, TLT and SHY each have two bars), so the first record's spread has a
previous close and its z-score history does not start a session late."""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, date, datetime, timedelta

import numpy as np

from src.intelligence.features.kernels.macro import build_cross_asset_series
from tests.unit.intelligence import kernel_parity_reference as ref

CONFIG = dataclasses.replace(
    ref.build_config(ref.load_manifest()["synthetic_config"]),
    tip_tlt_zscore_window=3,
    hyg_lqd_zscore_window=3,
)
DAYS = [date(2024, 1, 2) + timedelta(days=i) for i in range(14)]


def _bars(days: list[date], seed: int) -> list[dict]:
    rng = np.random.default_rng(seed)
    price = 100.0
    out = []
    for d in days:
        price *= 1.0 + rng.normal(0, 0.01)
        out.append(
            {
                "ts": datetime(d.year, d.month, d.day, tzinfo=UTC),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 1e6,
            }
        )
    return out


def _series(late_start: int):
    """SPY, TLT, SHY start `late_start` sessions after TIP, HYG and LQD."""
    early, late = DAYS, DAYS[late_start:]
    return build_cross_asset_series(
        _bars(late, 1),  # SPY
        _bars(late, 2),  # TLT
        _bars(late, 3),  # SHY
        _bars(early, 4),  # TIP
        _bars(early, 5),  # HYG
        _bars(early, 6),  # LQD
        CONFIG,
    )


def test_the_first_record_date_has_a_spread_when_tip_history_predates_the_reference_trio():
    records = _series(late_start=5)
    dates = sorted(records)
    # the first record date is the second session of SPY/TLT/SHY; its previous TIP/HYG/LQD close
    # exists, so the spread enters the history on that date and the 3-observation window fills on
    # the third record date (one session earlier than with the tracker bug)
    z = [records[d].tip_tlt_ret_z for d in dates]
    first_finite = next(i for i, v in enumerate(z) if math.isfinite(v))
    assert first_finite == CONFIG.tip_tlt_zscore_window - 1
    z2 = [records[d].hyg_lqd_ret_z for d in dates]
    assert next(i for i, v in enumerate(z2) if math.isfinite(v)) == CONFIG.hyg_lqd_zscore_window - 1


def test_a_series_that_all_start_together_also_has_a_spread_on_its_first_record_date():
    records = _series(late_start=0)
    dates = sorted(records)
    # TIP/HYG/LQD have their own first bar before the first record date (SPY's second bar), so
    # the previous close exists there too: the history fills the same session as above
    z = [records[d].tip_tlt_ret_z for d in dates]
    assert next(i for i, v in enumerate(z) if math.isfinite(v)) == CONFIG.tip_tlt_zscore_window - 1
