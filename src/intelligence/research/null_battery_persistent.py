"""The E17 H0 battery for persistent predictors routed through the 184 nodes (methodology-
change-ledger E17, condition 2; design D6 and D7 guard 6; driver scripts/research/
e17_null_battery.py --battery src.intelligence.research.null_battery_persistent).

A slow predictor is where a timing test over-rejects, and feature members are the first
persistent ones: 52-week percentiles, smoothed members with 838 sessions of memory. Each cell
draws a predictor that is independent of future returns by construction (an AR(1) per name at
the cell's source clock with time constant tau in sessions, or a research kernel on the null's
own past price path), routes it exactly as a feature member is routed (align.align on the
clock.closes_at availabilities, smoothing.smooth, families.features.centred), builds the
equal-weight book with R1 through book.book_timing, and scores it with the E17 statistic at
the memory book_memory gives for the member (cell_memory_sessions). Two arms per cell: `member`
is the family-level test (timing_test with the daily overlap statistic on a daily book, as
runner.py scores a member) and `book_equal` is the S8 book test.

The null returns follow null_battery_daily_residual's split of each session into an overnight
and an intraday move for a daily book (a panel whose opens equal the previous closes cannot see
the overnight move a daily open-to-open target shares with a close-to-close signal); an hourly
book draws bar returns directly and keeps its target in session.

Supported subset (184-REVIEWS row 4): daily books with 1d, 1h, 15m and 5m sources and hourly
books with 1d sources, horizon 1, equal-weight. Each gating cell carries a BatteryCertificate
and a feature or kernel is admitted only by `admit`, which matches every discrete field of the
request and the member's source memory against a certificate the battery has passed. Compute
only.
"""

from __future__ import annotations

import dataclasses
import functools
import math
from collections.abc import Sequence
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
from scipy.signal import lfilter

from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.features.contract.registry import VOLUME_BASIS_CONSOLIDATED
from src.intelligence.features.research_kernels.rolling import KERNELS, family_of, window_of
from src.intelligence.research import clock, null_panels, static_sizes
from src.intelligence.research.align import align
from src.intelligence.research.book import book_memory, book_timing
from src.intelligence.research.combiner import EqualWeight
from src.intelligence.research.construction import RankVolNeutral
from src.intelligence.research.families.features import centred
from src.intelligence.research.horizon import HorizonRule
from src.intelligence.research.kernel_source import kernel_member_memory_bars, kernel_source
from src.intelligence.research.member_memory import (
    feature_member_memory_rows,
    feature_member_memory_sessions,
)
from src.intelligence.research.null_battery import (
    MEASURED_SLOT_EFFECT_SD,
    MEASURED_STATIC_CELL_SD,
)
from src.intelligence.research.null_battery_daily_residual import DailyScenario
from src.intelligence.research.null_battery_daily_residual import null_panel as daily_null_panel
from src.intelligence.research.panel import Panel
from src.intelligence.research.portfolio import rank_vol_neutral_weights, trailing_vol
from src.intelligence.research.smoothing import smooth
from src.intelligence.research.timing import timing_test

# Battery design constants (APR-exempt, as null_battery's): changing one changes the gate and
# needs a rerun.
_WARMUP_SESSIONS = 252
_COVERAGE_FLOOR = 20
_VOL_WINDOW_SESSIONS = 20
_HORIZON = 1
_MAX_AGE_ROWS = 1
_KERNEL_MAX_GAP_ROWS = 2
_PRICE_SCALE = 0.01  # noise sd 1 -> 1% returns
_INTRADAY_SPLIT_NOISE = 0.5  # bar noise around an even split of a session return
_HIGH_LOW_SCALE = 0.003  # synthetic high/low spread around the close
# Stored-feature memory bounds per source tf, in source bars (the largest declared
# feature_memory_bars the supported subset admits).
_FEATURE_MEMORY_BOUND = {"1d": 252, "1h": 140, "15m": 520, "5m": 1560}
_SOURCE_BARS = {"1d": 1, "1h": 7, "15m": 26, "5m": 78}
_BOOK_BARS = {"1d": 1, "1h": 7}
# The stored windows the D5 duplicate check compares a research kernel's window against: the
# production provenance config's values at 2026-10-27 (percentile 50 and 200, 52-week high 252),
# the same values 184-02's KERNELS comment records. A stand-in object, never FeatureFactoryConfig().
_STORED_WINDOWS = SimpleNamespace(
    percentile_window_fast=50, percentile_window_slow=200, high_52w_window=252
)
_FIRST_SESSION = date(2000, 1, 3)
_LAST_SESSION = date(2019, 12, 31)
_FULL_SESSION = timedelta(hours=6, minutes=30)


# --- admission ----------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class BatteryCertificate:
    """What a battery cell certified: the route and the largest source memory it tested."""

    identity: str  # "feature", or the research kernel family
    window: int | None  # the kernel's window; None for a stored feature
    smoothing_half_life: int | None
    source_tf: str
    book_tf: str
    horizon: int
    combiner: str
    max_age_rows: int
    max_gap_rows: int | None  # None for a stored feature
    source_memory_bars_max: int


@dataclasses.dataclass(frozen=True)
class CertificateRequest:
    """A member's route: every discrete field of a certificate plus its own source memory."""

    identity: str
    window: int | None
    smoothing_half_life: int | None
    source_tf: str
    book_tf: str
    horizon: int
    combiner: str
    max_age_rows: int
    max_gap_rows: int | None
    source_memory_bars: int


class NotCertified(ValueError):
    """No passing certificate covers the request."""


_DISCRETE = tuple(
    f.name for f in dataclasses.fields(BatteryCertificate) if f.name != "source_memory_bars_max"
)

# The certificates whose every gating cell held size at 0.05 and 0.01 in both arms (184-05-
# BATTERY.md, battery module commit 49e21bb41); a failing route stays refused (todo 586).
_REPORT_PASSING: tuple[BatteryCertificate, ...] = (
    BatteryCertificate("feature", None, None, "1h", "1d", 1, "equal_weight", 1, None, 140),
    BatteryCertificate("feature", None, None, "15m", "1d", 1, "equal_weight", 1, None, 520),
    BatteryCertificate("feature", None, 5, "1d", "1d", 1, "equal_weight", 1, None, 252),
    BatteryCertificate("rk_high_dist", 126, None, "1d", "1d", 1, "equal_weight", 1, 2, 125),
    BatteryCertificate("rk_vwap_dev", 20, None, "1d", "1d", 1, "equal_weight", 1, 2, 19),
    BatteryCertificate("rk_vwap_dev", 20, None, "1h", "1d", 1, "equal_weight", 1, 2, 19),
)

# Report-passing certificates the runner does not admit, each with the reason (todo 588; the
# report's table stays the evidence and is never edited). A certificate returns only when a
# battery cell tests what the reason names (todo 588 part B).
WITHHELD_CERTIFICATES: dict[BatteryCertificate, str] = {
    _REPORT_PASSING[2]: (
        "smoothing 5 on a 1d source passes only because the unsmoothed 1d to 1d route fails at "
        "tau 60 and 200 (persistence); it returns only if it passes at tau 200"
    ),
    _REPORT_PASSING[4]: (
        "rk_vwap_dev 1d to 1d: the cells assume one volume basis; withheld until S0 supplies "
        "volume_basis and the battery certifies a mixed volume basis"
    ),
    _REPORT_PASSING[5]: (
        "rk_vwap_dev 1h to 1d: the cells assume one volume basis; withheld until S0 supplies "
        "volume_basis and the battery certifies a mixed volume basis"
    ),
}

PASSING_CERTIFICATES: tuple[BatteryCertificate, ...] = tuple(
    c for c in _REPORT_PASSING if c not in WITHHELD_CERTIFICATES
)


def _mismatches(request: CertificateRequest, cert: BatteryCertificate) -> list[str]:
    out = [f for f in _DISCRETE if getattr(request, f) != getattr(cert, f)]
    if request.source_memory_bars > cert.source_memory_bars_max:
        out.append("source_memory_bars")
    return out


def admit(
    request: CertificateRequest, certificates: Sequence[BatteryCertificate] | None = None
) -> BatteryCertificate:
    """The passing certificate matching every discrete field of `request` whose tested source
    memory covers the request's; NotCertified (naming the nearest mismatch) otherwise."""
    pool = PASSING_CERTIFICATES if certificates is None else tuple(certificates)
    nearest: tuple[int, BatteryCertificate, list[str]] | None = None
    for cert in pool:
        wrong = _mismatches(request, cert)
        if not wrong:
            return cert
        if nearest is None or len(wrong) < nearest[0]:
            nearest = (len(wrong), cert, wrong)
    if nearest is None:
        raise NotCertified("no passing battery certificate exists (184-05-BATTERY.md)")
    _, cert, wrong = nearest
    detail = ", ".join(
        f"{f}: {getattr(request, f)!r} vs "
        f"{getattr(cert, 'source_memory_bars_max' if f == 'source_memory_bars' else f)!r}"
        for f in wrong
    )
    raise NotCertified(f"no battery certificate covers the request; nearest differs in {detail}")


def _feature_cert(source_tf: str, book_tf: str, smoothing: int | None) -> BatteryCertificate:
    return BatteryCertificate(
        identity="feature",
        window=None,
        smoothing_half_life=smoothing,
        source_tf=source_tf,
        book_tf=book_tf,
        horizon=_HORIZON,
        combiner="equal_weight",
        max_age_rows=_MAX_AGE_ROWS,
        max_gap_rows=None,
        source_memory_bars_max=_FEATURE_MEMORY_BOUND[source_tf],
    )


def _kernel_cert(kernel_name: str, source_tf: str) -> BatteryCertificate:
    family, window = family_of(kernel_name), window_of(kernel_name)
    return BatteryCertificate(
        identity=family,
        window=window,
        smoothing_half_life=None,
        source_tf=source_tf,
        book_tf="1d",
        horizon=_HORIZON,
        combiner="equal_weight",
        max_age_rows=_MAX_AGE_ROWS,
        max_gap_rows=_KERNEL_MAX_GAP_ROWS,
        source_memory_bars_max=kernel_member_memory_bars(kernel_name, {family: window}, None),
    )


# --- cells --------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PersistentScenario:
    name: str
    certificate: BatteryCertificate
    tau_sessions: float | None = None  # None for a kernel cell (its price path sets persistence)
    sessions: int = 4000  # the real-run standard (certificate.REAL_SESSIONS)
    names: int = 60
    t4_noise: bool = False
    static_cell_sd: float = 0.0
    slot_effect_sd: float = 0.0
    factor_sd: float = 0.0
    vol_clustering: bool = False
    late_fraction: float = 0.4
    late_name: bool = True
    # A two-member book (todo 588 part B): the second member's route. It shares the first's book
    # tf, horizon and combiner; the member arm scores each member and the book arm their mean.
    partner: BatteryCertificate | None = None

    def __post_init__(self) -> None:
        if self.partner is not None:
            wrong = [
                f
                for f in ("book_tf", "horizon", "combiner", "max_age_rows")
                if getattr(self.partner, f) != getattr(self.certificate, f)
            ]
            if wrong:
                raise ValueError(f"a book's members share {wrong}")

    @property
    def members(self) -> tuple[BatteryCertificate, ...]:
        return (self.certificate,) + (() if self.partner is None else (self.partner,))

    @property
    def source_bars_per_session(self) -> int:
        return _SOURCE_BARS[self.certificate.source_tf]

    @property
    def book_bars_per_session(self) -> int:
        return _BOOK_BARS[self.certificate.book_tf]


def cell_memory_sessions(sc: PersistentScenario) -> int:
    """The cell's E17 L: book_memory over the one member-memory function, with each certificate's
    tested source memory as its member's."""
    bk = sc.book_bars_per_session
    sessions, rows = [], []
    for cert in sc.members:
        kw = dict(
            source_memory_bars=cert.source_memory_bars_max,
            source_bars_per_session=_SOURCE_BARS[cert.source_tf],
            max_age_rows=cert.max_age_rows,
            smoothing_half_life=cert.smoothing_half_life,
            slot_history_sessions=0,  # centred adds no history over its aligned input
            book_bars_per_session=bk,
        )
        sessions.append(feature_member_memory_sessions(**kw))
        rows.append(feature_member_memory_rows(**kw))
    return book_memory(
        sessions,
        rows,
        sc.certificate.horizon,
        EqualWeight((1.0,) * len(sc.members)),
        HorizonRule(),
        bk,
    ).sessions


def scenarios() -> tuple[PersistentScenario, ...]:
    """Gating cells for exactly the certificates the supported subset admits, plus one
    diagnostic. Every gating cell lists 40% of its names late and one at 60% of the span, which
    puts the no-fill rules (alignment age, smoothing windows, kernel warmup) in the loop."""
    daily = _feature_cert("1d", "1d", None)
    static = 2 * MEASURED_STATIC_CELL_SD
    cells = [PersistentScenario(f"f1d_tau{t}", daily, t) for t in (1, 5, 20, 60, 200)]
    cells.append(PersistentScenario("f1d_static_tau200", daily, 200, static_cell_sd=static))
    for tf in ("1h", "15m", "5m"):
        cert = _feature_cert(tf, "1d", None)
        cells += [PersistentScenario(f"f{tf}_tau{t}", cert, t) for t in (20, 200)]
    for h in (5, 21, 63):
        cert = _feature_cert("1d", "1d", h)
        cells += [PersistentScenario(f"f1d_s{h}_tau{t}", cert, t) for t in (5, 60)]
    cells.append(PersistentScenario("f1h_s21_tau5", _feature_cert("1h", "1d", 21), 5))
    for kernel in KERNELS:
        cells.append(PersistentScenario(f"{kernel.name}_1d", _kernel_cert(kernel.name, "1d")))
    vwap = next(k.name for k in KERNELS if family_of(k.name) == "rk_vwap_dev")
    cells.append(PersistentScenario(f"{vwap}_1h", _kernel_cert(vwap, "1h")))
    hourly = _feature_cert("1d", "1h", None)
    slot = 2 * MEASURED_SLOT_EFFECT_SD
    cells += [
        PersistentScenario(f"book1h_f1d_tau{t}", hourly, t, slot_effect_sd=slot) for t in (20, 200)
    ]
    # Diagnostic (appended: the drivers seed by position): the known E17 limit, a long-memory
    # predictor against large static means times volatility clustering (null_battery docstring).
    cells.append(
        PersistentScenario("hostile_tau200", daily, 200, static_cell_sd=0.3, vol_clustering=True)
    )
    return tuple(cells) + _part_b_cells()


def _part_b_cells() -> tuple[PersistentScenario, ...]:
    """The todo 588 part B cells, appended after the 184-05 cells (the drivers seed by position,
    so the original cells keep their seeds). Every one gates.

    Static stress: each passing route at tau 200 with static means at 1x and 2x the measured
    size. Time-of-day stress: the same at the daily book's one slot, where a time-of-day effect
    is the mean return common to every name (static_sizes.measure on a daily panel reads exactly
    that), at 1x and 2x the measured slot effect; a kernel cell has no source-tf effect to
    stress separately and a 1d source has no intraday slot, so the stored 1d route and the kernel
    carry static cells only. Books: the two-member 1h plus 15m book at tau 20 and 200. The
    smoothing-5 re-earn test at tau 200."""
    cells: list[PersistentScenario] = []
    members = {tf: _feature_cert(tf, "1d", None) for tf in ("1h", "15m")}
    high = next(k.name for k in KERNELS if family_of(k.name) == "rk_high_dist")
    routes = [(f"f{tf}", cert, 200.0) for tf, cert in members.items()]
    routes.append((f"{high}_1d", _kernel_cert(high, "1d"), None))
    for label, cert, tau in routes:
        suffix = "" if tau is None else "_tau200"
        for k in (1, 2):
            cells.append(
                PersistentScenario(
                    f"{label}_static{k}x{suffix}",
                    cert,
                    tau,
                    static_cell_sd=k * MEASURED_STATIC_CELL_SD,
                )
            )
    for label, cert, tau in routes[:2]:
        for k in (1, 2):
            cells.append(
                PersistentScenario(
                    f"{label}_slot{k}x_tau200",
                    cert,
                    tau,
                    slot_effect_sd=k * MEASURED_SLOT_EFFECT_SD,
                )
            )
    cells += [
        PersistentScenario(f"book_f1h_f15m_tau{t}", members["1h"], t, partner=members["15m"])
        for t in (20, 200)
    ]
    cells.append(PersistentScenario("f1d_s5_tau200", _feature_cert("1d", "1d", 5), 200))
    return tuple(cells)


DIAGNOSTIC_CELLS = frozenset({"hostile_tau200"})


# Stress cells (static or time-of-day) that held size at 0.05 and 0.01 in every arm, from the
# committed reports (184-05-BATTERY.md, its Part B extension). A stress cell not listed here
# lifts no gate, whether it failed or has not run: the gate fails closed (todo 588).
PASSED_STRESS_CELLS: frozenset[str] = frozenset()


def _stressed(cell: PersistentScenario) -> bool:
    return cell.static_cell_sd > 0 or cell.slot_effect_sd > 0


def static_gate(
    certificates: Sequence[BatteryCertificate] | None = None,
) -> static_sizes.StaticGate:
    """The sizes the given certificates (default: every passing one) were shown to hold at. Per
    certificate: the max over its own gating cells that passed (an unstressed cell holds 0, a
    stress cell counts only from PASSED_STRESS_CELLS), so a failed or unrun stress cell never
    lifts a gate and a certificate with no passed stress cell gates at 0 (todo 588 B1). A book
    of several routes holds only the size every one of them held: the minimum over the
    certificates."""
    pool = PASSING_CERTIFICATES if certificates is None else tuple(certificates)
    if not pool:
        return static_sizes.StaticGate(__name__, 1, (0.0,), (0.0,))
    cells = scenarios()
    gates = []
    for cert in dict.fromkeys(pool):
        own = tuple(
            c
            for c in cells
            if cert in c.members
            and c.name not in DIAGNOSTIC_CELLS
            and (not _stressed(c) or c.name in PASSED_STRESS_CELLS)
        )
        gates.append(
            static_sizes.gate_from_cells(
                __name__,
                1,
                own or (PersistentScenario("none", cert, 1.0),),
                DIAGNOSTIC_CELLS,
                static=lambda c: (c.static_cell_sd,),
                time_of_day=lambda c: (c.slot_effect_sd,),
            )
        )
    return static_sizes.StaticGate(
        __name__,
        1,
        (min(g.static_sd[0] for g in gates),),
        (min(g.time_of_day[0] for g in gates),),
    )


# --- grids --------------------------------------------------------------------------------


@functools.lru_cache(maxsize=4)
def _session_bounds(sessions: int) -> tuple[np.ndarray, np.ndarray]:
    """(dates datetime64[D], opens datetime64[ns] naive UTC) of the first `sessions` full NYSE
    sessions from 2000; early-close days are left out so every slot of a regular grid is a
    traded slot (closes_at refuses a slot past the close)."""
    bounds = nyse_sessions(_FIRST_SESSION, _LAST_SESSION)
    days = [d for d in sorted(bounds) if bounds[d][1] - bounds[d][0] == _FULL_SESSION]
    if len(days) < sessions:
        raise ValueError(f"the calendar holds {len(days)} full sessions, {sessions} requested")
    days = days[:sessions]
    opens = [np.datetime64(bounds[d][0].replace(tzinfo=None), "ns") for d in days]
    return np.array(days, dtype="datetime64[D]"), np.array(opens, dtype="datetime64[ns]")


@functools.lru_cache(maxsize=8)
def _grid(sessions: int, tf: str) -> tuple[np.ndarray, np.ndarray]:
    """(row timestamps, availability) of a regular `tf` grid over the calendar's sessions."""
    days, opens = _session_bounds(sessions)
    bps = _SOURCE_BARS[tf]
    if tf == "1d":
        stamps = days
    else:
        slots = np.arange(bps) * np.timedelta64(clock.TF_MINUTES[tf], "m")
        stamps = (opens[:, None] + slots[None, :]).reshape(-1)
    return stamps, clock.closes_at(stamps, np.ones(len(stamps), dtype=bool), tf, bps)


# --- the null -----------------------------------------------------------------------------


def _daily_scenario(sc: PersistentScenario) -> DailyScenario:
    return DailyScenario(
        sc.name,
        sessions=sc.sessions,
        names=sc.names,
        t4_noise=sc.t4_noise,
        market_mean=sc.slot_effect_sd,  # a daily book's one slot (_part_b_cells)
        static_sd=sc.static_cell_sd,
        factor_sd=sc.factor_sd,
        vol_clustering=sc.vol_clustering,
        late_fraction=sc.late_fraction,
        late_name=sc.late_name,
        horizon=_HORIZON,
    )


def _hourly_null(sc: PersistentScenario, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """(bar returns [n, m], target [n, m]) of an hourly book under H0: bars within a session
    are continuous (open = previous close), the target of row T is bar T+1's return
    (ln open[T+2] / open[T+1]), NaN where T+2 opens in the next session."""
    rng = np.random.default_rng(seed)
    bk, s_n, m = sc.book_bars_per_session, sc.sessions, sc.names
    u = null_panels.noise(rng, (s_n, bk, m), sc.t4_noise)
    if sc.vol_clustering:
        u = null_panels.vol_clustering(u, rng)
    if sc.static_cell_sd:
        u = u + null_panels.cell_means(rng, (bk, m), sc.static_cell_sd)
    if sc.slot_effect_sd:
        u = u + null_panels.cell_means(rng, (bk, 1), sc.slot_effect_sd)
    if sc.factor_sd:
        u = u + null_panels.factor_term(rng, (s_n, bk, 1), m, sc.factor_sd, loadings_first=True)
    starts = null_panels.listing_starts(rng, s_n, m, sc.late_fraction, sc.late_name)
    listed = null_panels.listing_mask(starts, s_n, m, bk)
    resid = np.where(listed, u.reshape(-1, m), np.nan)
    target = np.full(resid.shape, np.nan)
    target[:-1] = resid[1:]
    target[np.arange(len(target)) % bk == bk - 2] = np.nan
    return resid, target


def null_returns(sc: PersistentScenario, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """(residual bar returns, residual target) of one H0 panel on the book clock, NaN where a
    name has not listed."""
    if sc.book_bars_per_session == 1:
        return daily_null_panel(_daily_scenario(sc), seed)
    return _hourly_null(sc, seed)


# --- the predictor ------------------------------------------------------------------------


def _ar1(rng: np.random.Generator, rows: int, names: int, rows_per_tau: float) -> np.ndarray:
    """Stationary unit-variance AR(1) per name with time constant `rows_per_tau` rows."""
    phi = math.exp(-1.0 / rows_per_tau)
    scale = math.sqrt(1.0 - phi * phi)
    z = rng.standard_normal((rows, names))
    z[0] /= scale
    return lfilter([scale], [1.0, -phi], z, axis=0)


def _session_listed(resid: np.ndarray, book_bars: int) -> np.ndarray:
    """bool [sessions, m]: a name is listed from the session whose first row has a return."""
    return np.isfinite(resid[::book_bars])


def _source_path(
    daily_resid: np.ndarray, bars: int, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(open, high, low, close) [sessions * bars, m] of the null's own price path at the source
    tf: each session's return is split into `bars` bar returns that sum to it (the last bar
    takes the remainder), so the path's session closes are the daily null's."""
    s_n, m = daily_resid.shape
    if bars == 1:
        steps = daily_resid
    else:
        first = daily_resid[:, None, :] / bars + _INTRADAY_SPLIT_NOISE * rng.standard_normal(
            (s_n, bars - 1, m)
        )
        steps = np.concatenate(
            [first, daily_resid[:, None, :] - first.sum(axis=1, keepdims=True)], axis=1
        )
        steps = steps.reshape(-1, m)
    close = 100.0 * np.exp(_PRICE_SCALE * np.nancumsum(steps, axis=0))
    close[np.isnan(steps)] = np.nan
    opens = np.vstack([np.full((1, m), 100.0), close[:-1]])
    spread = _HIGH_LOW_SCALE * np.abs(rng.standard_normal((2, *close.shape)))
    return opens, close * np.exp(spread[0]), close * np.exp(-spread[1]), close


def _kernel_values(
    sc: PersistentScenario, cert: BatteryCertificate, resid: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    bars = _SOURCE_BARS[cert.source_tf]
    opens, high, low, close = _source_path(resid, bars, rng)
    stamps, _ = _grid(sc.sessions, cert.source_tf)
    n = len(stamps)
    panel = Panel(
        tf=cert.source_tf,
        symbols=tuple(f"s{j}" for j in range(sc.names)),
        timestamps=stamps,
        bars_per_session=bars,
        valid=np.ones(n, dtype=bool),
        open=opens,
        close=close,
        volume=np.ones(close.shape),
    )
    output = f"{cert.identity}_w{cert.window}"
    result = kernel_source(
        panel,
        (output,),
        {cert.identity: cert.window},
        _STORED_WINDOWS,  # type: ignore[arg-type]
        max_gap_rows=cert.max_gap_rows,
        high=high,
        low=low,
        volume_basis=np.full(close.shape, VOLUME_BASIS_CONSOLIDATED),  # one vendor,
    )
    return result.values[output]


def member_alpha(
    sc: PersistentScenario, seed: int, resid: np.ndarray, index: int = 0
) -> np.ndarray:
    """Member `index`'s alpha [n, m] on the book clock: the persistent source, aligned to the book
    clock, smoothed when the certificate says so, then the centred rank. Each member draws its
    own stream (the first keeps the stream of every earlier cell)."""
    cert = sc.members[index]
    rng = np.random.default_rng((seed, 17 + 100 * index))
    bars, bk = _SOURCE_BARS[cert.source_tf], sc.book_bars_per_session
    if cert.identity == "feature":
        x = _ar1(rng, sc.sessions * bars, sc.names, sc.tau_sessions * bars)
        listed = np.repeat(_session_listed(resid, bk), bars, axis=0)
        x[~listed] = np.nan
    else:
        x = _kernel_values(sc, cert, resid, rng)
    if cert.source_tf != cert.book_tf:
        x = align(
            x,
            _grid(sc.sessions, cert.source_tf)[1],
            _grid(sc.sessions, cert.book_tf)[1],
            cert.max_age_rows,
        )
    if cert.smoothing_half_life is not None:
        x = smooth(x, cert.smoothing_half_life)
    return centred(x, bars_per_session=bk, coverage_floor=_COVERAGE_FLOOR)


# --- scoring ------------------------------------------------------------------------------


def simulate_detail(sc: PersistentScenario, seed: int) -> dict[str, tuple[float, float, int]]:
    """One H0 panel: {arm: (t, p, tested sessions)} for the member and the equal-weight book. A
    two-member book also scores its second member as `member_b`."""
    bk, memory = sc.book_bars_per_session, cell_memory_sessions(sc)
    resid, target = null_returns(sc, seed)
    alphas = [member_alpha(sc, seed, resid, i) for i in range(len(sc.members))]
    window = _VOL_WINDOW_SESSIONS * bk
    vol = trailing_vol(resid, window_rows=window, min_finite=window // 2)
    trade = np.zeros(len(resid), dtype=bool)
    trade[_WARMUP_SESSIONS * bk :] = True

    def member(alpha: np.ndarray):
        weights, has = rank_vol_neutral_weights(
            alpha, vol=vol, direction=1.0, coverage_floor=_COVERAGE_FLOOR
        )
        return timing_test(
            weights,
            target,
            has,
            trade,
            bars_per_session=bk,
            warmup_sessions=_WARMUP_SESSIONS,
            memory_sessions=memory,
            overlap_sessions=sc.certificate.horizon - 1 if bk == 1 else None,
        ).hac

    book = book_timing(
        np.stack(alphas, axis=2),
        target,
        vol,
        trade,
        combiner=EqualWeight((1.0,) * len(alphas)),
        rule=RankVolNeutral(1.0, _COVERAGE_FLOOR),
        bars_per_session=bk,
        warmup_sessions=_WARMUP_SESSIONS,
        memory_sessions=memory,
    ).timing.hac
    arms = {"member": member(alphas[0])}
    if len(alphas) > 1:
        arms["member_b"] = member(alphas[1])
    arms["book_equal"] = book
    return {arm: (h.t, h.p, h.n) for arm, h in arms.items()}


def simulate(sc: PersistentScenario, seed: int) -> dict[str, tuple[float, float]]:
    """One H0 panel: {arm: (t, p)}, the driver's interface."""
    return {arm: (t, p) for arm, (t, p, _) in simulate_detail(sc, seed).items()}
