"""Member inputs and smoothing in a spec (plan 184-06): optional, hash-neutral while unset."""

import typing

import pytest
from pydantic import ValidationError

from src.intelligence.research.smoothing import SMOOTHING_HALF_LIVES
from src.intelligence.research.spec import MemberSpec, _family_dump, parse_spec_text
from tests.unit.research.test_spec import FAMILY

HASH = "ab" * 32
FEATURE = f"""
    input:
      kind: feature
      column: price_percentile_slow
      tf: 1d
      max_age_rows: 1
      config_projection_hash: {HASH}
      coverage_floor: 0.8"""
KERNEL = f"""
    input:
      kind: kernel
      column: rk_price_percentile_w252
      tf: 1d
      max_age_rows: 1
      config_projection_hash: {HASH}
      windows: {{rk_price_percentile: 252}}
      max_gap_rows: 2"""
SMOOTH = "\n    smoothing_half_life: "


def _spec(member_extra="", *, tf="1d", bars=1, fields="closes_at"):
    text = FAMILY.replace("tf: 15m", f"tf: {tf}").replace(
        "bars_per_session: 26", f"bars_per_session: {bars}\n  fields: [{fields}]"
    )
    anchor = "declared_memory_rows: 7124"
    return parse_spec_text(text.replace(anchor, anchor + member_extra))


def test_unset_member_fields_leave_the_canonical_form_unchanged():
    canon = _family_dump(parse_spec_text(FAMILY))
    for member in canon["members"]:
        assert "input" not in member and "smoothing_half_life" not in member


def test_a_feature_input_loads_and_enters_the_canonical_form():
    canon = _family_dump(_spec(FEATURE))
    assert canon["members"][0]["input"]["config_projection_hash"] == HASH
    assert "input" not in canon["members"][1]
    assert canon["panel"]["fields"] == ["closes_at"]


def test_a_kernel_input_loads():
    assert _spec(KERNEL).members[0].input.kind == "kernel"


@pytest.mark.parametrize(
    "edit",
    [
        lambda s: s.replace(HASH, "AB" * 32),
        lambda s: s.replace(HASH, "ab" * 31),
        lambda s: s.replace(f"      config_projection_hash: {HASH}\n", "\n"),
        lambda s: s + "\n      apr: {a: 1}",
        lambda s: s.replace("\n      coverage_floor: 0.8", ""),
        lambda s: s + "\n      windows: {rk_price_percentile: 252}",
    ],
)
def test_bad_feature_inputs_are_refused(edit):
    assert edit(FEATURE) != FEATURE
    with pytest.raises(ValidationError):
        _spec(edit(FEATURE))


@pytest.mark.parametrize(
    "edit",
    [
        lambda s: s.replace("\n      windows: {rk_price_percentile: 252}", ""),
        lambda s: s.replace("\n      max_gap_rows: 2", ""),
        lambda s: s.replace("rk_price_percentile: 252", "rk_price_percentile: 126"),
        lambda s: s.replace("rk_price_percentile: 252", "rk_other: 252"),
        lambda s: s.replace(f"      config_projection_hash: {HASH}\n", ""),
    ],
)
def test_bad_kernel_inputs_are_refused(edit):
    assert edit(KERNEL) != KERNEL
    with pytest.raises(ValidationError):
        _spec(edit(KERNEL))


def test_kernel_window_suffix_must_match_windows():
    with pytest.raises(ValidationError, match="must be <family>_w<window>"):
        _spec(KERNEL.replace("column: rk_price_percentile_w252", "column: rk_price_percentile"))


def test_feature_no_gap():
    with pytest.raises(ValidationError, match="no windows or max_gap_rows"):
        _spec(FEATURE + "\n      max_gap_rows: 2")


def test_smoothing_without_input_is_refused_naming_b5():
    with pytest.raises(ValidationError, match="B5"):
        _spec(SMOOTH + "21")


def test_smoothing_menu_is_the_fixed_set():
    assert _spec(FEATURE + SMOOTH + "21").members[0].smoothing_half_life == 21
    with pytest.raises(ValidationError):
        _spec(FEATURE + SMOOTH + "17")
    literal = MemberSpec.model_fields["smoothing_half_life"].annotation
    (menu,) = [a for a in typing.get_args(literal) if a is not type(None)]
    assert typing.get_args(menu) == SMOOTHING_HALF_LIVES


def test_an_input_needs_closes_at_in_panel_fields():
    with pytest.raises(ValidationError, match="closes_at"):
        _spec(FEATURE, fields="high")


def test_smoothing_needs_a_daily_book_clock():
    with pytest.raises(ValidationError, match="1d book clock"):
        _spec(FEATURE + SMOOTH + "5", tf="15m", bars=26)


def test_closes_at_is_a_panel_field_and_unknown_fields_are_refused():
    assert _spec(fields="closes_at, high").panel.fields == ["closes_at", "high"]
    with pytest.raises(ValidationError):
        _spec(fields="vwap")
