"""Date-indexed panel for within-symbol IC tests: synchronous date-block bootstrap and the
panel-synchronous whole-date circular-shift null.

Extracted from scripts/analysis/alpha_score_residual_single_security_15m.py (its todo 372 fix
and review record live there) so later constructions reuse it instead of copying: first
consumer after the residual diagnostic is the H-A extreme-volume divergence Track 1
(docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md). Scores may be
NaN where a statistic is undefined; `spearman` drops non-finite pairs and the family counts
finite (score, return) rows. On all-finite data both match the pre-extraction behavior.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
from scipy.stats import rankdata


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman correlation over the finite (x, y) pairs; NaN below 4 pairs or with no
    variance. Non-finite pairs are dropped, so a score defined only on event rows (NaN
    elsewhere) can sit on the full dense panel the shift null requires."""
    keep = np.isfinite(x) & np.isfinite(y)
    if not keep.all():
        x, y = x[keep], y[keep]
    if len(x) < 4 or np.std(x) < 1e-12 or np.std(y) < 1e-12:
        return float("nan")
    return float(np.corrcoef(rankdata(x), rankdata(y))[0, 1])


def _concat_ranges(src_starts: np.ndarray, counts: np.ndarray) -> np.ndarray:
    """Row indices for the concatenation of ranges [s_j, s_j + c_j). Vectorized."""
    tot = int(counts.sum())
    if tot == 0:
        return np.empty(0, dtype=np.int64)
    offsets = np.cumsum(counts) - counts
    return np.repeat(src_starts, counts) + np.arange(tot) - np.repeat(offsets, counts)


def _panel_synchronous_shift_indices(
    cal_start_s: np.ndarray, cal_len_s: np.ndarray, n_cal: int, k: int
) -> tuple[np.ndarray, np.ndarray]:
    """For ONE symbol's per-calendar-position (cal_start, cal_len) rows (each
    shape (n_cal,), indexed by position in the PANEL-SHARED calendar -- the
    same arrays `bootstrap_ci` already reads correctly), return (ret_idx,
    score_idx): absolute row indices such that ret_idx pairs this symbol's
    rows at each TRUE calendar position with score_idx at that SAME
    position shifted `k` calendar positions earlier (circular). k is the
    SAME value for every symbol in a null replicate -- this is what makes
    the shift panel-synchronous (todo 372: the replaced code computed
    `k % (that symbol's own active-date count)`, which maps the same
    nominal k to a DIFFERENT real calendar offset per symbol whenever
    active-date counts vary, silently degrading the shared shift into
    independent per-symbol shifts).

    A calendar position is used only when the symbol has data at BOTH the
    true and shifted position with the SAME row count there, giving an
    unambiguous, count-preserving row-for-row pairing (rows within a
    date-block are stored in bar_ts order on both sides, see
    Panel.__init__). A position without a same-count match on the shifted
    side contributes nothing -- never truncated or reordered to force a
    fit. This generalizes cleanly to intraday timeframes where a symbol can
    have multiple rows on one calendar date (cal_len > 1); at tf=1d, where
    cal_len is always 0 or 1, the condition collapses to plain "both dates
    present," no special-casing needed.
    """
    pos = np.arange(n_cal)
    shifted = (pos - k) % n_cal
    src_len = cal_len_s[shifted]
    usable = (cal_len_s > 0) & (src_len > 0) & (cal_len_s == src_len)
    if not usable.any():
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=np.int64)
    true_starts = cal_start_s[usable]
    true_counts = cal_len_s[usable]
    src_starts = cal_start_s[shifted[usable]]
    ret_idx = _concat_ranges(true_starts, true_counts)
    score_idx = _concat_ranges(src_starts, true_counts)  # true_counts == src_counts here
    return ret_idx, score_idx


class Panel:
    """Per-symbol date-block index structures over a row subset of the big arrays."""

    # Class-level defaults so an instance built without __init__ (as a regression test does)
    # still has them.
    date_block = 5
    max_workers = 8

    def __init__(
        self,
        symbol_ids: np.ndarray,
        dates: np.ndarray,  # int32 YYYYMMDD per row
        scores: np.ndarray,  # signal under test; NaN where undefined
        returns: np.ndarray,
        *,
        min_rows: int = 100,
        date_block: int = 5,
        max_workers: int = 8,
    ) -> None:
        self.scores = scores
        self.returns = returns
        self.dates = dates
        self.date_block = date_block
        self.max_workers = max_workers
        finite = np.isfinite(scores) & np.isfinite(returns)
        self.calendar = np.unique(dates)
        n_cal = len(self.calendar)
        n_sym = int(symbol_ids.max()) + 1
        self.cal_start = np.zeros((n_sym, n_cal), dtype=np.int64)
        self.cal_len = np.zeros((n_sym, n_cal), dtype=np.int64)
        # per-symbol block (own-date) structures for the synchronous shift null
        self.sym_blocks: dict[int, tuple[np.ndarray, np.ndarray, slice]] = {}
        for s in np.unique(symbol_ids):
            rows = np.flatnonzero(symbol_ids == s)
            d_sym = dates[rows]
            uniq = np.unique(d_sym)
            first = np.searchsorted(d_sym, uniq)
            counts = np.diff(np.append(first, len(d_sym)))
            pos = np.searchsorted(self.calendar, uniq)
            self.cal_start[s, pos] = rows[first]
            self.cal_len[s, pos] = counts
            self.sym_blocks[int(s)] = (rows[first], counts, slice(rows[0], rows[-1] + 1))
        # family: symbols with at least min_rows measurement rows (finite score and return)
        self.family = sorted(
            s for s, (_st, _c, sl) in self.sym_blocks.items() if int(finite[sl].sum()) >= min_rows
        )

    def _symbol_rows_for_dates(self, s: int, cal_idx: np.ndarray) -> np.ndarray:
        starts = self.cal_start[s, cal_idx]
        counts = self.cal_len[s, cal_idx]
        return _concat_ranges(starts, counts)

    def family_stat(self, score_override: np.ndarray | None = None) -> float:
        sc = self.scores if score_override is None else score_override
        vals = []
        for s in self.family:
            sl = self.sym_blocks[s][2]
            vals.append(spearman(sc[sl], self.returns[sl]))
        vals = [v for v in vals if not np.isnan(v)]
        return float(np.mean(vals)) if vals else float("nan")

    def bootstrap_ci(
        self, rng: np.random.Generator, n_boot: int, score_override: np.ndarray | None = None
    ) -> tuple[float, float]:
        sc = self.scores if score_override is None else score_override
        n_cal = len(self.calendar)
        offsets = np.arange(self.date_block)
        n_blocks = int(np.ceil(n_cal / self.date_block))
        family_arr = np.array(self.family)
        # serial index generation, then threaded compute (production ic_math
        # convention): numpy Generators are not thread-safe
        block_starts = rng.integers(0, n_cal, size=(n_boot, n_blocks))

        def _one_rep(b: int) -> float:
            cal_idx = (block_starts[b][:, None] + offsets).ravel()[:n_cal] % n_cal
            vals = []
            for s in family_arr:
                rows = self._symbol_rows_for_dates(int(s), cal_idx)  # absolute indices
                if len(rows) < 4:
                    continue
                vals.append(spearman(sc[rows], self.returns[rows]))
            vals = [v for v in vals if not np.isnan(v)]
            return float(np.mean(vals)) if vals else float("nan")

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            reps = list(pool.map(_one_rep, range(n_boot)))
        reps_arr = np.array([r for r in reps if not np.isnan(r)])
        return float(np.percentile(reps_arr, 2.5)), float(np.percentile(reps_arr, 97.5))

    def sync_shift_null_p(
        self,
        observed: float,
        rng: np.random.Generator,
        n_null: int,
        score_override: np.ndarray | None = None,
    ) -> float:
        if np.isnan(observed):
            return 1.0
        sc = self.scores if score_override is None else score_override
        n_cal = len(self.calendar)
        ks = rng.integers(1, n_cal, size=n_null)  # serial, then threaded compute

        def _one_rep(i: int) -> float:
            k = int(ks[i])
            vals = []
            for s in self.family:
                ret_idx, score_idx = _panel_synchronous_shift_indices(
                    self.cal_start[s], self.cal_len[s], n_cal, k
                )
                if len(ret_idx) == 0:
                    continue
                vals.append(spearman(sc[score_idx], self.returns[ret_idx]))
            vals = [v for v in vals if not np.isnan(v)]
            return float(np.mean(vals)) if vals else float("nan")

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            reps = list(pool.map(_one_rep, range(n_null)))
        # Denominator must track REALIZED (non-NaN) replicates, not n_null: a NaN
        # replicate (no symbol had a usable shifted pairing at that k -- e.g.
        # delistings/holiday gaps thinning the calendar) is a replicate that produced
        # no evidence either way, not one that failed to beat `observed`. Counting NaNs
        # in beat's numerator-implicit denominator silently deflates p toward 0 as
        # degeneracy rises (todo 372 finding, AGY independent review 2026-09-11) -- a
        # spurious pass, not a conservative one.
        n_valid = beat = 0
        for r in reps:
            if np.isnan(r):
                continue
            n_valid += 1
            if r >= observed:
                beat += 1
        if n_valid < 0.5 * n_null:
            raise ValueError(
                f"sync_shift_null_p: only {n_valid}/{n_null} null replicates produced "
                "a usable statistic -- panel is too sparse/degenerate for this null to be "
                "trustworthy. Fix the panel construction (e.g. build on the full dense "
                "calendar, not pre-filtered event rows) rather than trusting this p-value."
            )
        return (1 + beat) / (n_valid + 1)
