"""Masked cells are out of every cross-section (todo 609 I1 audit, recorded as a test).

A non-member cell is NaN (no_fill). Adding all-NaN columns to a panel must leave every
cross-sectional output on the real columns exactly as it was: no rank, demean, correlation,
regression, cluster or principal component may count, weight or shift because of a masked name.
Each case below is one cross-sectional operation under research/ (the table is in
docs/reference/research-cross-section-nan-audit.md).
"""

import numpy as np
import pytest

from src.intelligence.research import combiner, factors, portfolio
from src.intelligence.research.families.common import centred_rank

N, M, EXTRA = 400, 14, 6


def _real(seed=11, nan_fraction=0.05):
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 0.01, (N, M)) + rng.normal(0, 0.01, (N, 1))
    x[rng.random((N, M)) < nan_fraction] = np.nan
    return x


def _padded(x, at="end"):
    pad = np.full((x.shape[0], EXTRA), np.nan)
    return np.concatenate([x, pad] if at == "end" else [pad, x], axis=1)


def _same(a, b):
    """Rank and count operations: bit-identical."""
    assert np.array_equal(a, b, equal_nan=True)


def _close(a, b):
    """Sum and regression operations: the same cells are finite and the values agree to
    reduction-order rounding (an added zero column changes numpy's summation tree by an ulp,
    about 1e-12 in S1), never by a count, a weight or a shifted statistic."""
    assert np.array_equal(np.isfinite(a), np.isfinite(b))
    np.testing.assert_allclose(a, b, rtol=1e-8, atol=1e-10, equal_nan=True)


@pytest.mark.parametrize("at", ["end", "start"])
def test_centred_rank_and_average_ranks(at):
    x = _real()
    cols = slice(0, M) if at == "end" else slice(EXTRA, None)
    _same(
        centred_rank(x, coverage_floor=3), centred_rank(_padded(x, at), coverage_floor=3)[:, cols]
    )
    _same(portfolio.average_ranks(x), portfolio.average_ranks(_padded(x, at))[:, cols])


def test_rank_vol_neutral_weights():
    alpha, vol = _real(1), np.abs(_real(2)) + 0.01
    base, has = portfolio.rank_vol_neutral_weights(alpha, vol=vol, direction=1.0, coverage_floor=3)
    pad_w, pad_has = portfolio.rank_vol_neutral_weights(
        _padded(alpha), vol=_padded(vol), direction=1.0, coverage_floor=3
    )
    _close(base, pad_w[:, :M])
    _same(has, pad_has)
    assert not np.any(pad_w[:, M:])


def test_row_correlation_used_by_the_combiner_signs():
    z, y = _real(3), _real(4)
    _close(combiner._row_correlation(z, y), combiner._row_correlation(_padded(z), _padded(y)))


def test_trailing_vol():
    r = _real(5)
    out = portfolio.trailing_vol(r, window_rows=60, min_finite=30)
    padded = portfolio.trailing_vol(_padded(r), window_rows=60, min_finite=30)
    _same(out, padded[:, :M])
    assert np.isnan(padded[:, M:]).all()


def test_s1_residuals_and_neutralize():
    r = _real(6, nan_fraction=0.02)
    spec = factors.VINTAGE_1
    base = factors.residual_returns(r, bars_per_session=1, spec=spec)
    padded = factors.residual_returns(_padded(r), bars_per_session=1, spec=spec)
    _close(base.residual, padded.residual[:, :M])
    assert np.isnan(padded.residual[:, M:]).all()
    alpha = _real(7)
    _close(
        factors.neutralize(alpha, base),
        factors.neutralize(_padded(alpha), padded)[:, :M],
    )


def test_contribution_attribution_scores_only_finite_cells():
    from src.intelligence.research import contribution

    terms, target = np.stack([_real(8), _real(9)], axis=2), _real(10)
    per_member, total = contribution.attribution(terms, target)
    pad_terms = np.concatenate([terms, np.full((N, EXTRA, 2), np.nan)], axis=1)
    pad_per_member, pad_total = contribution.attribution(pad_terms, _padded(target))
    np.testing.assert_allclose(per_member, pad_per_member, rtol=1e-9)
    np.testing.assert_allclose(total, pad_total, rtol=1e-9)
