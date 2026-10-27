"""B3: align, the only research node that sees two clocks (multi-timeframe design D4, D7).

A source value is usable on a destination row when its availability is at or before the
destination row's close. `<=` is causal because a book enters at the next open, after the
close. Both availability arrays come from `clock.closes_at`: the source's on its own bar grid,
never availability read from stored metadata (184-REVIEWS row 1).

Per destination row and symbol, align takes the latest finite source value among the rows
available by then, and only when that value is at most `max_age_rows` source rows older than
the latest available source row; otherwise NaN. Ages count source-grid rows, untraded and NaT
rows included, so a missing source bar ages a value instead of being skipped (184-REVIEWS
row 13); a weekend or holiday adds no source rows and ages nothing. The age bound is what
keeps this from being a carry-forward fill. Source rows with NaT availability are never read.

There is one implementation (184-REVIEWS row 2): `align_index` returns the int32 [nd, m]
source-row index (-1 where there is no value) and `align` is `gather` over it. S2b calls
`align_index` for same-or-coarser sources; for finer sources S0 calls it once, persists the
index, and S2b replays it with `gather`. `check_alignment` is the S3 proof over every scored
row of an index. Pure functions over arrays: no I/O, the source is never written.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from src.intelligence.research.guards import GuardFailure

_NO_ROW = -1

ArrayFn = Callable[[np.ndarray], np.ndarray]


def align(
    src: np.ndarray,
    src_avail: np.ndarray,
    dst_avail: np.ndarray,
    max_age_rows: int,
    *,
    n_symbols: int | None = None,
) -> np.ndarray:
    """[nd, m] source values on the destination clock (module rules). Float sources keep their
    dtype; a [ns, 1] source broadcasts to `n_symbols` columns."""
    src = _as_2d(src)
    idx = align_index(np.isfinite(src), src_avail, dst_avail, max_age_rows, n_symbols=n_symbols)
    return gather(src, idx)


def align_index(
    src_finite: np.ndarray,
    src_avail: np.ndarray,
    dst_avail: np.ndarray,
    max_age_rows: int,
    *,
    n_symbols: int | None = None,
) -> np.ndarray:
    """int32 [nd, m]: the source row each destination cell reads, -1 where it reads nothing.

    `src_finite` is bool [ns, k] (k symbols, or 1 for a series broadcast to `n_symbols`
    columns); `src_avail` datetime64 [ns], non-decreasing where not NaT; `dst_avail`
    datetime64 [nd].
    """
    src_finite = _as_2d(np.asarray(src_finite, dtype=bool))
    ns, k = src_finite.shape
    m = _n_columns(k, n_symbols)
    max_age_rows = _check_age(max_age_rows)
    src_ns, dst_ns = _avail(src_avail, ns, "src_avail"), _avail(dst_avail, None, "dst_avail")
    cand = _candidates(src_ns, dst_ns)
    rows = np.arange(ns, dtype=np.int32)[:, None]
    readable = src_finite & ~np.isnat(src_ns)[:, None]
    # Latest finite readable row at or before each source row: an index, never a value copy.
    last_finite = np.maximum.accumulate(np.where(readable, rows, np.int32(_NO_ROW)), axis=0)
    has_cand = cand >= 0
    picked = (
        last_finite[np.where(has_cand, cand, 0)]
        if ns
        else np.full((len(cand), k), _NO_ROW, dtype=np.int32)
    )
    ok = has_cand[:, None] & (picked >= 0) & (cand[:, None] - picked <= max_age_rows)
    idx = np.where(ok, picked, np.int32(_NO_ROW)).astype(np.int32, copy=False)
    if m != k:
        idx = np.ascontiguousarray(np.broadcast_to(idx, (len(cand), m)))
    return idx


def gather(src: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """src[idx[t, j], j] (column 0 for a [ns, 1] source), NaN where idx is -1."""
    src = _as_2d(src)
    idx = np.asarray(idx)
    if idx.ndim != 2 or src.shape[1] not in (1, idx.shape[1]):
        raise ValueError(f"gather: source shape {src.shape} does not fit index {idx.shape}")
    dtype = src.dtype if np.issubdtype(src.dtype, np.floating) else np.float64
    out = np.full(idx.shape, np.nan, dtype=dtype)
    hit = idx >= 0
    cols = np.broadcast_to(np.arange(idx.shape[1]) if src.shape[1] > 1 else 0, idx.shape)
    out[hit] = src[idx[hit], cols[hit]]
    return out


def check_alignment(
    idx: np.ndarray,
    src_avail: np.ndarray,
    dst_avail: np.ndarray,
    max_age_rows: int,
    rows: np.ndarray,
) -> None:
    """S3 alignment proof: raise GuardFailure naming the first destination row in `rows` whose
    index reads a source row available after the destination close, a row past the latest
    available one, or a row more than `max_age_rows` older than it.

    Pass `src_avail = clock.closes_at(...)` on the source bar grid, never stored availability.
    This proves the alignment only; a stored value's own causality is phase 186's truncation
    probe.
    """
    idx = np.asarray(idx)
    max_age_rows = _check_age(max_age_rows)
    src_ns = _avail(src_avail, None, "src_avail")
    dst_ns = _avail(dst_avail, len(idx), "dst_avail")
    if idx.ndim != 2:
        raise ValueError(f"check_alignment: index has shape {idx.shape}, expected [nd, m]")
    cand = _candidates(src_ns, dst_ns)
    rows = np.asarray(rows, dtype=np.int64)
    sub = idx[rows].astype(np.int64)
    used = sub >= 0
    out_of_range = (sub < _NO_ROW) | (sub >= len(src_ns))
    safe = np.clip(sub, 0, max(len(src_ns) - 1, 0))
    read_avail = src_ns[safe] if len(src_ns) else np.full(sub.shape, np.datetime64("NaT", "ns"))
    t_avail = dst_ns[rows][:, None]
    unknown = used & (np.isnat(read_avail) | np.isnat(t_avail))
    future = used & ~unknown & ((read_avail > t_avail) | (sub > cand[rows][:, None]))
    stale = used & ~unknown & ~future & (cand[rows][:, None] - sub > max_age_rows)
    for kind, bad in (
        ("index", out_of_range),
        ("lookahead", future | unknown),
        ("max age", stale),
    ):
        if bad.any():
            r, j = (int(v) for v in np.argwhere(bad)[0])
            t, i = int(rows[r]), int(sub[r, j])
            raise GuardFailure(
                f"{kind}: destination row {t} (available {dst_ns[t]}), column {j}, reads "
                f"source row {i}; latest available source row {int(cand[t])}, "
                f"max_age_rows {max_age_rows}"
            )


def align_causality_probe(
    src: np.ndarray,
    src_avail: np.ndarray,
    dst_avail: np.ndarray,
    max_age_rows: int,
    rows: np.ndarray,
    *,
    seed: int,
    n_symbols: int | None = None,
    fn: ArrayFn | None = None,
) -> None:
    """Cross-clock causality probe (D7 guard 1, unit level): for each destination row t in
    `rows`, replace every source row not available by t's close (once with NaN, once with
    seeded per-cell random rescaling, as guards.causality_probe_array does) and raise
    GuardFailure("lookahead ...") if any output at destination rows <= t moves.

    `fn` maps a source array to destination rows and defaults to `align` with these
    availabilities; pass the composition under test (a leaky availability, align followed by a
    smoother) to probe it against `src_avail` as the truth. The probe trusts `src_avail`, so it
    proves the alignment only; the runner's S3 uses `check_alignment` over every scored row.
    """
    work_src = _as_2d(src).astype(np.float64, copy=True)
    src_ns = _avail(src_avail, len(work_src), "src_avail")
    dst_ns = _avail(dst_avail, None, "dst_avail")
    if fn is None:

        def fn(x: np.ndarray) -> np.ndarray:
            return align(x, src_ns, dst_ns, max_age_rows, n_symbols=n_symbols)

    base = fn(work_src)
    base_nan = np.isnan(base)
    rng = np.random.default_rng(seed)
    for fill in ("nan", "rescale"):
        for t in np.sort(np.asarray(rows, dtype=np.int64)):
            t = int(t)
            if np.isnat(dst_ns[t]):
                continue
            later = np.isnat(src_ns) | (src_ns > dst_ns[t])
            if not later.any():
                continue
            work = work_src.copy()
            if fill == "nan":
                work[later] = np.nan
            else:
                work[later] *= np.exp(rng.normal(0.0, 0.5, work[later].shape))
            out = fn(work)
            head = slice(0, t + 1)
            out_nan = np.isnan(out[head])
            moved = (out_nan != base_nan[head]) | (~out_nan & (out[head] != base[head]))
            if moved.any():
                r = int(np.argwhere(moved)[0][0])
                raise GuardFailure(
                    f"lookahead: destination row {r} changed when source rows available after "
                    f"destination row {t}'s close ({dst_ns[t]}) were replaced ({fill})"
                )


def _candidates(src_ns: np.ndarray, dst_ns: np.ndarray) -> np.ndarray:
    """int32 [nd]: the latest source-grid row available at each destination close, -1 where
    none or the destination is NaT. Searches the non-NaT source rows and maps back to original
    row numbers, so ages stay in source-grid rows."""
    known = np.flatnonzero(~np.isnat(src_ns))
    keys = src_ns[known].astype(np.int64)
    if np.any(np.diff(keys) < 0):
        raise ValueError("align: source availability is not non-decreasing over its non-NaT rows")
    cand = np.full(len(dst_ns), _NO_ROW, dtype=np.int32)
    live = ~np.isnat(dst_ns)
    pos = np.searchsorted(keys, dst_ns[live].astype(np.int64), side="right") - 1
    cand[live] = np.where(pos >= 0, known[np.maximum(pos, 0)] if len(known) else _NO_ROW, _NO_ROW)
    return cand


def _avail(avail: np.ndarray, n: int | None, name: str) -> np.ndarray:
    avail = np.asarray(avail)
    if not np.issubdtype(avail.dtype, np.datetime64):
        raise ValueError(f"align: {name} must be datetime64, got {avail.dtype}")
    if avail.ndim != 1 or (n is not None and len(avail) != n):
        raise ValueError(f"align: {name} has shape {avail.shape}, expected ({n},)")
    return avail.astype("datetime64[ns]")


def _as_2d(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x)
    if x.ndim != 2:
        raise ValueError(f"align: source must be [ns, m], got shape {x.shape}")
    return x


def _n_columns(k: int, n_symbols: int | None) -> int:
    if n_symbols is None:
        return k
    if k not in (1, n_symbols):
        raise ValueError(f"align: a {k}-column source cannot fill {n_symbols} symbols")
    return n_symbols


def _check_age(max_age_rows: int) -> int:
    if isinstance(max_age_rows, bool) or not isinstance(max_age_rows, (int, np.integer)):
        raise ValueError(f"align: max_age_rows must be an int, got {max_age_rows!r}")
    if max_age_rows < 0:
        raise ValueError(f"align: max_age_rows must be >= 0, got {max_age_rows}")
    return int(max_age_rows)
