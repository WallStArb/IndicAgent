"""S1: residual returns against a causal factor model (architecture doc section 3.2, step 3).

The vintage-1 specification is pinned in FactorSpec before any candidate data is seen; changing
a field is a methodology change. Every factor is leave-one-out: a name's own return never enters
the factor it is regressed on.

Factors per name i at row s, from the return panel R [n, m] itself:
  1. market: equal-weighted mean of the other names' returns;
  2. sector: equal-weighted mean of the other members of i's group (groups with at least
     min_group_size members; a name outside such a group has this factor fixed at 0);
  3. k principal components of the market-and-sector residuals: the eigenvectors of the
     window's standardized residual correlation give portfolio weights, and a PC factor return
     is that portfolio of the other names' raw returns. Building the factor from raw returns,
     not from residuals, keeps it strictly leave-one-out: another name's residual depends on
     name i through its own market and sector factors. The joint regression with the market and
     sector factors absorbs the portfolio's market and sector content.

Loadings. At each refit row p (every refit_sessions sessions, on a session boundary) the model
is fitted by OLS with an intercept, per name, on the window of rows known at p: rows s with
p - lag - W < s <= p - lag. The caller gives the return's horizon, and lag follows from it:
bar returns (horizon None) are known at their own close, lag 0; a forward return over
`horizon` rows spans s+1 ... s+1+horizon, lag fwd_span(horizon). So no row inside a target's
forward window ever enters a loading. The loadings then apply to rows [p, next refit). The
intercept is estimated but never subtracted: the residual keeps each name's drift. All names'
regressions are solved together from masked normal equations; the pseudo-inverse gives the
minimum-norm solution, so a factor fixed at 0 (an ungrouped name's sector) gets beta 0.

residual[t, i] = R[t, i] - sum_k beta[i, k] * F_k[t, i], NaN when R[t, i], any factor value, or
the loadings are missing (a name with fewer than min_finite_sessions finite rows in the window,
in sessions' worth of rows, gets no loadings). Missing is never filled.

Intraday panels count windows in sessions (window_sessions * bars_per_session rows), so a
window's loadings pool every time-of-day slot.

Two uses for a candidate:
  - a return target or a return-built signal input: residual_returns(R, ...);
  - a score-type signal: neutralize(alpha, result), a cross-sectional regression of each row's
    alpha on the loadings in force at that row.

Classification caveat: groups come from instruments.contract_details->>'sector' as captured in
the panel's snapshot, which is today's label, not point-in-time (todo 384).
"""

from __future__ import annotations

import dataclasses

import numpy as np

from src.intelligence.research.panel import fwd_span

FACTOR_NAMES_BASE = ("market", "sector")


@dataclasses.dataclass(frozen=True)
class FactorSpec:
    """S1 methodology, pinned per data vintage. Lengths in sessions."""

    window_sessions: int = 252
    refit_sessions: int = 21
    n_components: int = 5
    min_finite_sessions: int = 126
    min_group_size: int = 3

    @property
    def factor_names(self) -> tuple[str, ...]:
        """Column labels of Residualized.loadings."""
        return FACTOR_NAMES_BASE + tuple(f"pc{k + 1}" for k in range(self.n_components))


# Vintage 1 (data before alpha.validation.oos_start), pinned 2026-09-25 by the owner's S1 spec.
VINTAGE_1 = FactorSpec()


@dataclasses.dataclass(frozen=True)
class Residualized:
    residual: np.ndarray  # [n, m]
    refit_rows: np.ndarray  # [B] first row each block's loadings apply to
    loadings: np.ndarray  # [B, m, K] per block, columns FactorSpec.factor_names, NaN where none

    def loadings_at(self, t: int) -> np.ndarray:
        """[m, K] loadings in force at row t (NaN before the first refit)."""
        b = int(np.searchsorted(self.refit_rows, t, side="right")) - 1
        if b < 0:
            return np.full(self.loadings.shape[1:], np.nan)
        return self.loadings[b]


def group_ids(labels: list[str] | tuple[str, ...], min_size: int) -> np.ndarray:
    """int [m]: a group id for names in a group of at least min_size, -1 otherwise ('' is no
    group)."""
    labels = np.asarray(labels, dtype=object)
    out = np.full(len(labels), -1)
    for g, label in enumerate(sorted({x for x in labels if x})):
        members = labels == label
        if members.sum() >= min_size:
            out[members] = g
    return out


def leave_one_out_mean(x: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """[T, m]: per row, the mean of the other finite members of each name's group; NaN for a
    name without a group or with no other finite member that row."""
    out = np.full(x.shape, np.nan)
    finite = np.isfinite(x)
    x0 = np.where(finite, x, 0.0)
    for g in np.unique(groups[groups >= 0]):
        cols = groups == g
        total = x0[:, cols].sum(axis=1, keepdims=True)
        others = finite[:, cols].sum(axis=1, keepdims=True) - finite[:, cols]
        with np.errstate(invalid="ignore", divide="ignore"):
            out[:, cols] = np.where(others > 0, (total - x0[:, cols]) / others, np.nan)
    return out


def _ols_loadings(y: np.ndarray, xs: np.ndarray, min_rows: int) -> tuple[np.ndarray, np.ndarray]:
    """Per name OLS with intercept, all names at once. y [W, m], xs [W, m, K] -> (intercepts
    [m], betas [m, K]); NaN for a name with fewer than min_rows complete rows."""
    w, m, _ = xs.shape
    design = np.concatenate([np.ones((w, m, 1)), xs], axis=2)
    ok = np.isfinite(y) & np.isfinite(design).all(axis=2)
    design = np.where(ok[:, :, None], design, 0.0)
    target = np.where(ok, y, 0.0)
    xtx = np.einsum("wik,wil->ikl", design, design)
    xty = np.einsum("wik,wi->ik", design, target)
    coef = (np.linalg.pinv(xtx) @ xty[:, :, None])[:, :, 0]
    coef[ok.sum(axis=0) < min_rows] = np.nan
    return coef[:, 0], coef[:, 1:]


def _base_factors(r: np.ndarray, sector_groups: np.ndarray) -> np.ndarray:
    """[T, m, 2]: leave-one-out market and sector returns; sector fixed at 0 for ungrouped."""
    market = leave_one_out_mean(r, np.zeros(r.shape[1], dtype=int))
    sector = leave_one_out_mean(r, sector_groups)
    sector[:, sector_groups < 0] = 0.0
    return np.stack([market, sector], axis=2)


def _pc_weights(e1: np.ndarray, k: int, min_rows: int) -> np.ndarray:
    """[m, k] portfolio weights: the top-k eigenvectors of the standardized residuals'
    pairwise-complete correlation, divided by each name's residual sd. Zero rows for names
    with fewer than min_rows finite residuals."""
    m = e1.shape[1]
    weights = np.zeros((m, k))
    finite = np.isfinite(e1)
    use = finite.sum(axis=0) >= min_rows
    if use.sum() <= k:
        return weights
    sd = np.nanstd(e1[:, use], axis=0)
    scale = np.where(sd > 0, sd, 1.0)
    z = np.where(finite[:, use], (e1[:, use] - np.nanmean(e1[:, use], axis=0)) / scale, 0.0)
    counts = finite[:, use].astype(float)
    corr = (z.T @ z) / np.maximum(counts.T @ counts, 1.0)
    eigval, eigvec = np.linalg.eigh(corr)
    weights[use] = eigvec[:, np.argsort(eigval)[::-1][:k]] / scale[:, None]
    return weights


def _pc_factors(r: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """[T, m, k]: name i's PC factor returns, the weighted raw returns of every other name
    (a missing return contributes 0)."""
    r0 = np.where(np.isfinite(r), r, 0.0)
    total = r0 @ weights  # [T, k]
    return total[:, None, :] - r0[:, :, None] * weights[None, :, :]


def residual_returns(
    r: np.ndarray,
    sector_labels: tuple[str, ...],
    *,
    bars_per_session: int = 1,
    horizon: int | None = None,
    spec: FactorSpec = VINTAGE_1,
) -> Residualized:
    """Residualize a return panel r [n, m]: bar returns (horizon None) or forward returns over
    `horizon` rows (panel.forward_returns). Rows before the first full window are NaN."""
    n, m = r.shape
    if len(sector_labels) != m:
        raise ValueError(f"{len(sector_labels)} sector labels for {m} names")
    lag = 0 if horizon is None else fwd_span(horizon)
    window = spec.window_sessions * bars_per_session
    step = spec.refit_sessions * bars_per_session
    min_rows = spec.min_finite_sessions * bars_per_session
    k = spec.n_components
    base = _base_factors(r, group_ids(sector_labels, spec.min_group_size))  # pure per row

    residual = np.full((n, m), np.nan)
    first = -(-(window - 1 + lag) // bars_per_session) * bars_per_session
    refit_rows = np.arange(first, n, step)
    loadings = np.full((len(refit_rows), m, 2 + k), np.nan)
    for b, p in enumerate(refit_rows):
        rows = slice(p - lag - window + 1, p - lag + 1)
        r_w, base_w = r[rows], base[rows]
        a1, b1 = _ols_loadings(r_w, base_w, min_rows)
        weights = _pc_weights(r_w - a1 - np.einsum("tmk,mk->tm", base_w, b1), k, min_rows)
        _, beta = _ols_loadings(
            r_w, np.concatenate([base_w, _pc_factors(r_w, weights)], 2), min_rows
        )
        loadings[b] = beta

        block = slice(p, min(p + step, n))
        x_t = np.concatenate([base[block], _pc_factors(r[block], weights)], axis=2)
        residual[block] = r[block] - np.einsum("tmk,mk->tm", x_t, beta)
    return Residualized(residual, refit_rows, loadings)


def neutralize(alpha: np.ndarray, fitted: Residualized) -> np.ndarray:
    """Cross-sectional residual of alpha [n, m] on the loadings in force at each row (with an
    intercept), for score-type signals. NaN where alpha or the loadings are missing, and for a
    row with no more names than regressors."""
    n, m = alpha.shape
    out = np.full((n, m), np.nan)
    bounds = np.append(fitted.refit_rows, n)
    for b in range(len(fitted.refit_rows)):
        beta = fitted.loadings[b]
        has = np.isfinite(beta).all(axis=1)
        design = np.where(has[:, None], np.column_stack([np.ones(m), beta]), 0.0)  # [m, K+1]
        block = slice(bounds[b], bounds[b + 1])
        a = alpha[block]
        ok = has & np.isfinite(a)  # [T, m]
        a0 = np.where(ok, a, 0.0)
        xtx = np.einsum("tn,nk,nl->tkl", ok.astype(float), design, design)
        xty = np.einsum("tn,nk->tk", a0, design)
        coef = (np.linalg.pinv(xtx) @ xty[:, :, None])[:, :, 0]
        fit = coef @ design.T
        enough = ok.sum(axis=1, keepdims=True) > design.shape[1]
        out[block] = np.where(ok & enough, a - fit, np.nan)
    return out
