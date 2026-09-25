"""S1: residual returns against a causal factor model (architecture doc section 3.2, step 3).

The vintage-1 specification is pinned in FactorSpec before any candidate data is seen; changing
a field is a methodology change. Every factor is leave-one-out: a factor's value at row t never
contains the name's own return at t. (A name's history in the window does shape the fitted
quantities, its loadings and the PC weights, as estimation from the window should.)

Factors per name i at row s, from the return panel R [n, m] itself:
  1. market: equal-weighted mean of the other names' returns;
  2. group: equal-weighted mean of the other members of i's statistical group. Groups are
     re-formed at every refit from prices only (_causal_groups): average-linkage clustering on
     distance 1 - correlation of the window's market-residual returns, cut to the smallest
     subtrees of at least min_group_size names, with any leftover name joining the group it
     is most correlated with. A name without enough data in the window has this factor fixed
     at 0. No reference data (sector labels) enters S1, so groups are point-in-time by
     construction;
  3. k principal components of the market-and-group residuals: the eigenvectors of the
     window's residual correlation give portfolio weights, and a PC factor return is that
     portfolio of the other names' raw returns. Building the factor from raw returns, not from
     residuals, keeps its value leave-one-out: another name's residual depends on name i's
     return through that name's own market and group factors. The joint regression with the
     market and group factors absorbs the portfolio's market and group content.

Loadings. At each refit row p (every refit_sessions sessions, on a session boundary) the model
is fitted by OLS with an intercept, per name, on the window of rows known at p: rows s with
p - lag - W < s <= p - lag. The caller gives the return's horizon, and lag follows from it:
bar returns (horizon None) are known at their own close, lag 0; a forward return over
`horizon` rows spans s+1 ... s+1+horizon, lag fwd_span(horizon). So no row inside a target's
forward window ever enters a loading. The loadings then apply to rows [p, next refit). The
intercept is estimated but never subtracted: the residual keeps each name's drift. All names'
regressions are solved together from masked normal equations; the pseudo-inverse gives the
minimum-norm solution, so a factor fixed at 0 (an ungrouped name's group) gets beta 0.

residual[t, i] = R[t, i] - sum_k beta[i, k] * F_k[t, i], NaN when R[t, i], any factor value, or
the loadings are missing (a name with fewer than min_finite_sessions finite rows in the window,
in sessions' worth of rows, gets no loadings). Missing is never filled.

Intraday panels count windows in sessions (window_sessions * bars_per_session rows), so a
window's loadings pool every time-of-day slot.

Two uses for a candidate:
  - a return target or a return-built signal input: residual_returns(R, ...);
  - a score-type signal: neutralize(alpha, result), a cross-sectional regression of each row's
    alpha on the loadings in force at that row.

S1 reads prices only. Present-day sector labels were rejected as look-ahead (reclassified
names such as META and GOOGL in 2018) and dirty in places; see FactorSpec.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import numpy as np
from scipy.cluster.hierarchy import linkage, to_tree
from scipy.spatial.distance import squareform

from src.intelligence.research.panel import fwd_span
from src.intelligence.statistics.correlation import pairwise_corr

FACTOR_NAMES_BASE = ("market", "group")


@dataclasses.dataclass(frozen=True)
class FactorSpec:
    """S1 methodology, pinned per data vintage. Lengths in sessions.

    S1 freezes at the first book-version screen test, not before: family evidence records
    produced earlier are diagnostics and are recomputed under the final S1.

    Groups (2026-09-25, pre-data). Chosen from return-correlation structure on 2013-2025 1d
    bar returns with no candidate signal or outcome involved, so not tuned toward a result.
    Label groups first: min_group_size 3 / 5 / 8 left the 13 sectors of 3-7 names with average
    within-group residual correlation -0.097 / -0.017 / +0.148 (raw 0.523). Then causal clusters
    against labels at min 5, from scripts/analysis/s1_grouping_comparison.py (breadth = residual
    participation ratio; small groups = the 15 label groups of 2-4 names, mostly near-duplicates
    such as IYT/XTN, municipal bonds, rates; band +-0.15):

                        breadth  label groups >=5 (mean, max|.|)  small groups (mean, max, outside)
      labels   min 5      97.2      -0.057, 0.140                   +0.294, +0.722, 11/15
      clusters min 5     115.4      +0.042, 0.164                   +0.223, +0.484,  8/15
      clusters min 10    103.6      +0.096, 0.253                   +0.256, +0.598, 11/15 (sensitivity)

    Clusters at 5 win on the two measures not biased toward labels (the label yardstick scores
    the label model on its own groups, including assignments it could not have known in 2013).
    Over-correction check: residual correlation within each cluster over the next 252 sessions,
    groups fixed at the refit, averages +0.027 (p5 -0.055, p95 +0.135, n 2,579). Numbers are on
    the 1d panel captured 2026-09-25, before migration 363 cleaned the labels (which the label
    arm and this yardstick read).

    Known limit: near-duplicate twins stay correlated under both models (a twin is one of 4+
    names in its leave-one-out mean). p-values and standard errors stay valid (the null shifts
    the whole panel, the bootstrap is over time); the cost is overstated breadth, which the
    combiner's covariance absorbs.
    """

    window_sessions: int = 252
    refit_sessions: int = 21
    n_components: int = 5
    min_finite_sessions: int = 126
    min_group_size: int = 5

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
    groups: np.ndarray  # int [B, m] statistical group per block, -1 where ungrouped

    def loadings_at(self, t: int) -> np.ndarray:
        """[m, K] loadings in force at row t (NaN before the first refit)."""
        b = int(np.searchsorted(self.refit_rows, t, side="right")) - 1
        if b < 0:
            return np.full(self.loadings.shape[1:], np.nan)
        return self.loadings[b]


def leave_one_out_mean(x: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """[T, m]: per row, the mean of the other finite members of each name's group; NaN for a
    name without a group or with no other finite member that row."""
    out = np.full(x.shape, np.nan)
    member = groups >= 0
    ids = np.unique(groups[member])
    if len(ids) == 0:
        return out
    finite = np.isfinite(x)
    x0 = np.where(finite, x, 0.0)
    indicator = (groups[:, None] == ids[None, :]).astype(float)  # [m, G]
    col = np.searchsorted(ids, groups[member])  # each member's group column
    total = (x0 @ indicator)[:, col]
    others = (finite @ indicator)[:, col] - finite[:, member]
    with np.errstate(invalid="ignore", divide="ignore"):
        out[:, member] = np.where(others > 0, (total - x0[:, member]) / others, np.nan)
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


def _market(r: np.ndarray) -> np.ndarray:
    """[T, m]: leave-one-out equal-weighted return of the whole universe."""
    return leave_one_out_mean(r, np.zeros(r.shape[1], dtype=int))


def _base_factors(r: np.ndarray, market: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """[T, m, 2]: leave-one-out market and group returns; group fixed at 0 for ungrouped."""
    group = leave_one_out_mean(r, groups)
    group[:, groups < 0] = 0.0
    return np.stack([market, group], axis=2)


def _causal_groups(
    r_w: np.ndarray, market_w: np.ndarray, min_rows: int, min_size: int
) -> np.ndarray:
    """int [m]: statistical groups from one window's prices; -1 for names without min_rows
    finite market residuals. Average linkage on 1 - correlation of market residuals; groups
    are the smallest subtrees with at least min_size names, and a name left in a smaller
    subtree joins the core group (members before any leftover joins) it has the highest average
    correlation with, so the assignment does not depend on column order."""
    m = r_w.shape[1]
    groups = np.full(m, -1)
    a, b = _ols_loadings(r_w, market_w[:, :, None], min_rows)
    e = r_w - a - market_w * b[:, 0]
    use = np.flatnonzero(np.isfinite(e).sum(axis=0) >= min_rows)
    if len(use) < 2 * min_size:
        return groups
    corr = pairwise_corr(e[:, use], min_rows)
    dist = np.clip(1.0 - (corr + corr.T) / 2, 0.0, None)
    np.fill_diagonal(dist, 0.0)
    local = np.full(len(use), -1)
    stack = [to_tree(linkage(squareform(dist, checks=False), "average"))]
    n_groups = 0
    while stack:
        node = stack.pop()
        if node.is_leaf():
            continue
        left, right = node.get_left(), node.get_right()
        if node.count >= min_size and left.count < min_size and right.count < min_size:
            local[node.pre_order()] = n_groups
            n_groups += 1
        else:
            stack += [right, left]
    core = np.flatnonzero(local >= 0)
    leftover = np.flatnonzero(local < 0)
    if len(leftover):
        indicator = (local[core][:, None] == np.arange(n_groups)[None, :]).astype(float)
        means = (corr[np.ix_(leftover, core)] @ indicator) / indicator.sum(axis=0)
        local[leftover] = means.argmax(axis=1)
    groups[use] = local
    return groups


def _pc_weights(e1: np.ndarray, k: int, min_rows: int) -> np.ndarray:
    """[m, k] portfolio weights: the top-k eigenvectors of the standardized residuals'
    pairwise-complete correlation, divided by each name's residual sd. Zero rows for names
    with fewer than min_rows finite residuals."""
    m = e1.shape[1]
    weights = np.zeros((m, k))
    use = np.isfinite(e1).sum(axis=0) >= min_rows
    if use.sum() <= k:
        return weights
    sd = np.nanstd(e1[:, use], axis=0)
    scale = np.where(sd > 0, sd, 1.0)
    eigval, eigvec = np.linalg.eigh(pairwise_corr(e1[:, use], min_rows))
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
    *,
    bars_per_session: int = 1,
    horizon: int | None = None,
    spec: FactorSpec = VINTAGE_1,
    grouping: Callable[[np.ndarray, np.ndarray, int, int], np.ndarray] | None = None,
) -> Residualized:
    """Residualize a return panel r [n, m]: bar returns (horizon None) or forward returns over
    `horizon` rows (panel.forward_returns). Rows before the first full window are NaN.

    `grouping(r_w, market_w, min_rows, min_size) -> int [m]` replaces the causal clusters, for
    method comparisons only (scripts/analysis/s1_grouping_comparison.py); every S1 run uses the
    default."""
    grouping = grouping or _causal_groups
    n, m = r.shape
    lag = 0 if horizon is None else fwd_span(horizon)
    window = spec.window_sessions * bars_per_session
    step = spec.refit_sessions * bars_per_session
    min_rows = spec.min_finite_sessions * bars_per_session
    k = spec.n_components
    market = _market(r)  # pure per row

    residual = np.full((n, m), np.nan)
    first = -(-(window - 1 + lag) // bars_per_session) * bars_per_session
    refit_rows = np.arange(first, n, step)
    loadings = np.full((len(refit_rows), m, 2 + k), np.nan)
    groups_by_block = np.full((len(refit_rows), m), -1)
    for b, p in enumerate(refit_rows):
        rows = slice(p - lag - window + 1, p - lag + 1)
        block = slice(p, min(p + step, n))
        r_w, market_w, r_t = r[rows], market[rows], r[block]
        groups = grouping(r_w, market_w, min_rows, spec.min_group_size)
        groups_by_block[b] = groups
        base_w = _base_factors(r_w, market_w, groups)
        a1, b1 = _ols_loadings(r_w, base_w, min_rows)
        weights = _pc_weights(r_w - a1 - np.einsum("tmk,mk->tm", base_w, b1), k, min_rows)
        _, beta = _ols_loadings(
            r_w, np.concatenate([base_w, _pc_factors(r_w, weights)], 2), min_rows
        )
        loadings[b] = beta

        base_t = _base_factors(r_t, market[block], groups)
        x_t = np.concatenate([base_t, _pc_factors(r_t, weights)], axis=2)
        residual[block] = r_t - np.einsum("tmk,mk->tm", x_t, beta)
    return Residualized(residual, refit_rows, loadings, groups_by_block)


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
