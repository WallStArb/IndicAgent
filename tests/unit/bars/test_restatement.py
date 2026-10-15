"""src/intelligence/bars/restatement.py: the non-blocking restatement detector (D-191-N)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.intelligence.bars.restatement import (
    SIGNATURE_PRICE_RATIO,
    SIGNATURE_SHARE,
    SIGNATURE_TIME_SHIFT,
    SIGNATURE_VOLUME_RATIO,
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


# Fourth review of 191-07, finding 3: robustness to cent rounding, a few unrelated corrections,
# volume units and a one-session overlap. APR values as seeded by migration 485.
SEEDED = DetectorParams(
    flag_share=0.02,
    flag_min_stored=78,
    signature_min_bars=5,
    ratio_tolerance=0.0005,
    shift_min_share=0.5,
    ratio_min_share=0.8,
    ratio_min_move=0.002,
    price_tick=0.01,
    volume_tolerance=0.01,
    volume_min_move=0.2,
)


def _session(n=78, base=4.0, volume=1_000):
    """One 5m session of a low-priced name on the cent grid, volumes varying by bar."""
    out = {}
    for i, ts in enumerate(_stamps(n)):
        p = round(base + 0.01 * (i % 13), 2)
        out[ts] = (p, round(p + 0.03, 2), round(p - 0.02, 2), round(p + 0.01, 2), volume + 37 * i)
    return out


def _rescale(values, multiple, *, volume_multiple=None):
    o, h, lo, c, v = values
    vm = 1.0 / multiple if volume_multiple is None else volume_multiple
    return (
        round(o * multiple, 2),
        round(h * multiple, 2),
        round(lo * multiple, 2),
        round(c * multiple, 2),
        int(round(v * vm)),
    )


def test_a_2_for_1_split_on_a_4_dollar_name_with_cent_rounding_and_one_correction_flags():
    stored = _session(base=4.01)
    offered = {ts: _rescale(v, 0.5) for ts, v in stored.items()}
    first = next(iter(offered))
    o, h, lo, c, v = offered[first]
    offered[first] = (o, h + 0.07, lo, c + 0.05, v + 500)  # an unrelated corrected bar
    result = detect(offered, stored, BAR, SEEDED)
    assert SIGNATURE_PRICE_RATIO in result.signatures and result.basis_change
    assert abs(result.ratio - 0.5) < 0.002
    assert SIGNATURE_VOLUME_RATIO in result.signatures and abs(result.volume_ratio - 2.0) < 0.01


def test_the_old_max_spread_rule_missed_the_rounded_split():
    stored = _session(base=4.01)
    offered = {ts: _rescale(v, 0.5) for ts, v in stored.items()}
    ratios = [n / o for ts in stored for n, o in zip(offered[ts][:4], stored[ts][:4])]
    median = sorted(ratios)[len(ratios) // 2]
    assert max(abs(r / median - 1.0) for r in ratios) > SEEDED.ratio_tolerance


def test_a_1_for_10_reverse_split_on_a_2_dollar_name_with_cent_rounding_flags():
    stored = _session(base=2.0)
    offered = {ts: _rescale(v, 10.0) for ts, v in stored.items()}
    last = list(offered)[-1]
    o, h, lo, c, v = offered[last]
    offered[last] = (o, h, lo, round(c - 0.3, 2), v)  # an unrelated corrected close
    result = detect(offered, stored, BAR, SEEDED)
    assert SIGNATURE_PRICE_RATIO in result.signatures and abs(result.ratio - 10.0) < 0.05
    assert SIGNATURE_VOLUME_RATIO in result.signatures


def test_a_one_session_overlap_is_judged():
    stored = _session(n=78, base=50.0)
    offered = {ts: _rescale(v, 0.5) for ts, v in stored.items()}
    assert detect(offered, stored, BAR, SEEDED).basis_change


def test_a_volume_unit_change_with_equal_prices_flags():
    stored = _session(base=37.5, volume=2_000)
    # lots of 100 to shares: every price equal, volume times 100 plus the sub-lot remainder
    offered = {ts: (*v[:4], v[4] * 100 + (ts.minute % 50)) for ts, v in stored.items()}
    result = detect(offered, stored, BAR, SEEDED)
    assert result.signatures == (SIGNATURE_SHARE, SIGNATURE_VOLUME_RATIO)
    assert result.basis_change and abs(result.volume_ratio - 100.0) < 0.1


def test_routine_volume_revisions_are_no_basis_change():
    # late prints: a few bars of a session gain volume by varied amounts, prices unchanged
    stored = _session(base=180.0, volume=50_000)
    offered = dict(stored)
    for k, ts in enumerate(list(stored)[-12:]):
        o, h, lo, c, v = offered[ts]
        offered[ts] = (o, h, lo, c, int(v * (1.0 + 0.004 * (k + 1) ** 1.5)))
    result = detect(offered, stored, BAR, SEEDED)
    assert result.n_changed == 12 and not result.basis_change
    assert SIGNATURE_VOLUME_RATIO not in result.signatures


def test_one_cent_corrections_on_a_2_dollar_name_are_no_basis_change():
    stored = _session(base=2.0)
    offered = dict(stored)
    for ts in list(stored)[::6]:
        o, h, lo, c, v = offered[ts]
        offered[ts] = (o, round(h + 0.01, 2), lo, round(c + 0.01, 2), v)
    result = detect(offered, stored, BAR, SEEDED)
    assert result.n_changed == 13 and not result.basis_change
