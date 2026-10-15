"""src/intelligence/bars/restatement.py: the non-blocking restatement detector (D-191-N)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.intelligence.bars.restatement import (
    SIGNATURE_PRICE_RATIO,
    SIGNATURE_SHARE,
    SIGNATURE_TIME_SHIFT,
    DetectorParams,
    detect,
)

BAR = timedelta(minutes=5)
T0 = datetime(2026, 9, 23, 13, 30, tzinfo=UTC)
PARAMS = DetectorParams(0.02, 50, 20, 0.0005, 0.5)


def _v(i, scale=1.0, volume=100):
    p = 10.0 + 0.01 * (i % 37)
    return (p * scale, (p + 0.1) * scale, (p - 0.1) * scale, (p + 0.05) * scale, volume)


def _stamps(n):
    return [T0 + BAR * i for i in range(n)]


def test_an_unchanged_offer_is_not_flagged():
    stored = {ts: _v(i) for i, ts in enumerate(_stamps(100))}
    result = detect(dict(stored), stored, BAR, PARAMS)
    assert (result.n_stored, result.n_changed, result.flagged) == (100, 0, False)


def test_a_share_above_the_flag_share_is_flagged_and_below_the_minimum_is_not():
    stamps = _stamps(100)
    stored = {ts: _v(i) for i, ts in enumerate(stamps)}
    offered = dict(stored)
    for ts in stamps[:5]:
        offered[ts] = (*offered[ts][:4], 999)
    assert detect(offered, stored, BAR, PARAMS).signatures == (SIGNATURE_SHARE,)
    small = DetectorParams(0.02, 500, 20, 0.0005, 0.5)
    assert not detect(offered, stored, BAR, small).flagged


def test_a_constant_price_ratio_is_a_basis_change():
    stamps = _stamps(100)
    stored = {ts: _v(i) for i, ts in enumerate(stamps)}
    offered = {ts: _v(i, scale=0.125) for i, ts in enumerate(stamps)}  # a 1:8 adjustment
    result = detect(offered, stored, BAR, PARAMS)
    assert SIGNATURE_PRICE_RATIO in result.signatures and abs(result.ratio - 0.125) < 1e-9


def test_a_one_bar_time_shift_is_a_basis_change():
    stamps = _stamps(100)
    stored = {ts: _v(i) for i, ts in enumerate(stamps)}
    offered = {ts: stored.get(ts - BAR, _v(999)) for ts in stamps}
    result = detect(offered, stored, BAR, PARAMS)
    assert SIGNATURE_TIME_SHIFT in result.signatures and result.shift_bars == -1


def test_scattered_one_cent_revisions_flag_their_share_but_no_basis_change():
    # the 2026-09-23 IBKR restatements of ADM and peers: one-cent price changes on 14 to 19 of
    # 623 stored bars (2.25 to 3.05 %): reported by share, no basis-change signature
    stamps = _stamps(623)
    stored = {ts: _v(i) for i, ts in enumerate(stamps)}
    offered = dict(stored)
    for ts in stamps[::40]:
        o, h, lo, c, v = offered[ts]
        offered[ts] = (o, h, lo, c + 0.01, v)
    result = detect(offered, stored, BAR, DetectorParams(0.02, 500, 20, 0.0005, 0.5))
    assert result.n_changed == 16 and result.signatures == (SIGNATURE_SHARE,)
