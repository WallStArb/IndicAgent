"""Verify I4Context has VIX/EQ fields and I6Confluence does not."""

from src.intelligence.schemas import I4Context, I6Confluence


def test_i4_context_has_vix_fields():
    ctx = I4Context()
    assert hasattr(ctx, "vix_level")
    assert hasattr(ctx, "vix_z")
    assert ctx.vix_level is None
    assert ctx.vix_z is None


def test_i4_context_has_eq_fields():
    ctx = I4Context()
    assert hasattr(ctx, "eq_spread_z")
    assert hasattr(ctx, "eq_pairs_confirming")
    assert ctx.eq_spread_z is None
    assert ctx.eq_pairs_confirming is None


def test_i6_confluence_does_not_have_vix_or_eq_fields():
    conf = I6Confluence()
    assert not hasattr(conf, "ctf_vix_level")
    assert not hasattr(conf, "ctf_vix_z")
    assert not hasattr(conf, "ctf_eq_spread_z")
    assert not hasattr(conf, "ctf_eq_pairs_confirming")


def test_i4_context_has_macro_context_fields():
    """D-11: all 5 MacroContextPlugin fields present in I4Context, defaulting to None."""
    ctx = I4Context()
    assert hasattr(ctx, "ftq_score")
    assert hasattr(ctx, "ftq_regime")
    assert hasattr(ctx, "yield_curve_slope")
    assert hasattr(ctx, "yield_curve_regime")
    assert hasattr(ctx, "corr_z")
    assert ctx.ftq_score is None
    assert ctx.ftq_regime is None
    assert ctx.yield_curve_slope is None
    assert ctx.yield_curve_regime is None
    assert ctx.corr_z is None
