"""The corpus rerun's disk budget (186-31, todo 593; lead requirement 2026-11-05).

Pure functions over measured counts and APR figures; no I/O. The runner (services/corpus_rerun.py)
reads the counts and the live figures and calls these; the rebuild writer
(services/backfill_feature_factory.py) calls `UnitDiskGuard.check` before each unit's COPY.

The run's growth from launch never exceeds `infra.corpus_rerun.max_disk_fraction` of the free
bytes at launch. The intraday history is rebuilt span by span (Jan-1 aligned spans, 1h then 15m
then 5m per span) so that each span's rows compress before the next span's are written. The
projected peak of span k is

- the uncompressed bytes of span k's intraday rows,
- plus the straddling chunk carried from span k-1 (span k-1's rows inside the chunk that
  crosses span k's start; it compresses only after span k completes),
- plus the compressed bytes of every earlier span's rows outside that chunk,
- plus the 1d rows: uncompressed in chunks not yet compressed, compressed in the rest,
- plus max_wal_size,
- plus two group spools of the largest group of span k (the next group's workers spool while
  the previous group loads), at the spool bytes per row.

The 1d stage (whole history, before any span) peaks at every 1d row uncompressed plus the WAL and
two spools of its largest group. Each step's gate adds only its own tf's rows to the growth
measured since launch (`step_increment`); `footprint_before` is the modelled growth a step starts
from, so a plan that fits passes every step's gate. `plan_spans` picks the smallest number of spans of about equal intraday
rows whose largest peak is at or below the limit; `project` re-projects fixed spans (the pilot's
check with the measured bytes per row).

Chunk boundaries are the hypertable's: TimescaleDB places a chunk at a multiple of the time
dimension's interval from the Unix epoch, so chunk k covers [epoch + k * interval, + interval).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

DAILY_TF = "1d"
INTRADAY_TFS: tuple[str, ...] = ("1h", "15m", "5m")
STAGE_1D = "stage_1d"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

Span = tuple[datetime, datetime]


@dataclasses.dataclass(frozen=True)
class BudgetInputs:
    """Every figure the projection uses, each an APR value or a live measurement."""

    free_bytes_at_launch: int
    max_disk_fraction: float
    bytes_per_row: float  # stored bytes per uncompressed row, indexes included
    compression_ratio: float  # uncompressed over compressed bytes
    stored_bytes_per_spool_byte: float
    wal_bytes: int  # max_wal_size
    chunk_interval: timedelta  # the hypertable's time dimension interval

    def __post_init__(self) -> None:
        if self.free_bytes_at_launch <= 0:
            raise ValueError("free_bytes_at_launch must be positive")
        if not 0 < self.max_disk_fraction < 1:
            raise ValueError("max_disk_fraction must be in (0, 1)")
        for name in ("bytes_per_row", "compression_ratio", "stored_bytes_per_spool_byte"):
            if not getattr(self, name) > 0:
                raise ValueError(f"{name} must be positive")
        if self.chunk_interval <= timedelta(0):
            raise ValueError("chunk_interval must be positive")

    @property
    def limit_bytes(self) -> float:
        return self.max_disk_fraction * self.free_bytes_at_launch

    @property
    def spool_bytes_per_row(self) -> float:
        return self.bytes_per_row / self.stored_bytes_per_spool_byte


@dataclasses.dataclass(frozen=True)
class RowCounts:
    """Tradeable bar rows of the rebuild's universe from each name's proven start to the horizon,
    keyed (tf, symbol chunk index, first day of the month). A month a bound cuts is pro-rated by
    its days, so a chunk boundary inside a month takes its share."""

    cells: Mapping[tuple[str, int, date], int]

    def rows(
        self, lo: datetime, hi: datetime, tfs: Sequence[str], chunk: int | None = None
    ) -> float:
        total = 0.0
        for (tf, index, month), n in self.cells.items():
            if tf not in tfs or (chunk is not None and index != chunk):
                continue
            start = datetime(month.year, month.month, 1, tzinfo=UTC)
            end = _next_month(start)
            overlap = min(end, hi) - max(start, lo)
            if overlap > timedelta(0):
                total += n * (overlap / (end - start))
        return total

    def chunks(self) -> list[int]:
        return sorted({index for _, index, _ in self.cells})

    def minus(self, stored: RowCounts) -> RowCounts:
        """The rows still to be written: these counts less the rows already stored (never
        below zero per cell). Rows on disk at launch are not growth."""
        return RowCounts(
            {key: max(0, n - stored.cells.get(key, 0)) for key, n in self.cells.items()}
        )

    def intraday_years(self) -> list[int]:
        """Every calendar year from the first to the last month holding an intraday row."""
        years = [m.year for (tf, _, m), n in self.cells.items() if tf in INTRADAY_TFS and n]
        return list(range(min(years), max(years) + 1)) if years else []


def _next_month(start: datetime) -> datetime:
    return datetime(start.year + start.month // 12, start.month % 12 + 1, 1, tzinfo=UTC)


def _jan1(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=UTC)


def chunk_floor(ts: datetime, interval: timedelta) -> datetime:
    """Start of the hypertable chunk holding `ts` (epoch-aligned multiples of the interval)."""
    return _EPOCH + ((ts - _EPOCH) // interval) * interval


_FAR_FUTURE = datetime(9999, 1, 1, tzinfo=UTC)


@dataclasses.dataclass(frozen=True)
class Peak:
    """One step's projected footprint since launch, term by term (bytes)."""

    step: str
    intraday: float
    straddle: float
    compressed_rest: float
    daily_uncompressed: float
    daily_compressed: float
    wal: float
    spool: float

    @property
    def total(self) -> float:
        return (
            self.intraday
            + self.straddle
            + self.compressed_rest
            + self.daily_uncompressed
            + self.daily_compressed
            + self.wal
            + self.spool
        )

    @property
    def working_set(self) -> float:
        """The peak less its compressed part and the WAL: what check_disk_guard calls
        span_peak_bytes."""
        return self.intraday + self.straddle + self.daily_uncompressed + self.spool

    def as_record(self) -> dict[str, Any]:
        record = dataclasses.asdict(self)
        record["total"] = self.total
        return record


# Two group spools coexist: the next group's workers write theirs while the previous group loads.
SPOOLS_IN_FLIGHT = 2


def _largest_group_rows(counts: RowCounts, lo: datetime, hi: datetime, tfs: Sequence[str]) -> float:
    return max(
        (counts.rows(lo, hi, (tf,), chunk) for tf in tfs for chunk in counts.chunks()),
        default=0.0,
    )


def _spool_bytes(rows: float, inputs: BudgetInputs) -> float:
    return SPOOLS_IN_FLIGHT * rows * inputs.spool_bytes_per_row


def daily_peak(counts: RowCounts, inputs: BudgetInputs) -> Peak:
    """The 1d stage: every 1d row uncompressed (nothing compresses until the stage ends)."""
    every = (_EPOCH, _FAR_FUTURE)
    spool = _largest_group_rows(counts, *every, (DAILY_TF,))
    return Peak(
        step=STAGE_1D,
        intraday=0.0,
        straddle=0.0,
        compressed_rest=0.0,
        daily_uncompressed=counts.rows(*every, (DAILY_TF,)) * inputs.bytes_per_row,
        daily_compressed=0.0,
        wal=float(inputs.wal_bytes),
        spool=_spool_bytes(spool, inputs),
    )


def span_peak(spans: Sequence[Span], k: int, counts: RowCounts, inputs: BudgetInputs) -> Peak:
    """The projected peak of span index k (0-based) while its 5m stage writes."""
    start, end = spans[k]
    b, ratio = inputs.bytes_per_row, inputs.compression_ratio
    open_from = chunk_floor(start, inputs.chunk_interval)
    straddle = counts.rows(open_from, start, INTRADAY_TFS) if k else 0.0
    spool = _largest_group_rows(counts, start, end, INTRADAY_TFS)
    return Peak(
        step=f"s{k + 1}",
        intraday=counts.rows(start, end, INTRADAY_TFS) * b,
        straddle=straddle * b,
        compressed_rest=counts.rows(_EPOCH, open_from, INTRADAY_TFS) * b / ratio,
        daily_uncompressed=counts.rows(open_from, _FAR_FUTURE, (DAILY_TF,)) * b,
        daily_compressed=counts.rows(_EPOCH, open_from, (DAILY_TF,)) * b / ratio,
        wal=float(inputs.wal_bytes),
        spool=_spool_bytes(spool, inputs),
    )


def _step_bounds(spans: Sequence[Span], k: int | None, tf: str) -> tuple[datetime, datetime]:
    if tf == DAILY_TF:
        return _EPOCH, _FAR_FUTURE
    if k is None:
        raise ValueError(f"an intraday step ({tf}) needs its span index")
    return spans[k]


def step_increment(
    spans: Sequence[Span],
    k: int | None,
    tf: str,
    counts: RowCounts,
    inputs: BudgetInputs,
    loaded_rows: float = 0.0,
) -> float:
    """What one step adds over the footprint it starts from: its own tf's rows in its span (the
    whole history for 1d) not yet loaded under the run, the WAL and its two group spools. The
    span's earlier tfs and every compressed row are already on disk, so the runtime growth holds
    them; counting them here again would double count."""
    lo, hi = _step_bounds(spans, k, tf)
    rows = max(0.0, counts.rows(lo, hi, (tf,)) - loaded_rows)
    spool = _largest_group_rows(counts, lo, hi, (tf,))
    return rows * inputs.bytes_per_row + inputs.wal_bytes + _spool_bytes(spool, inputs)


def footprint_before(
    spans: Sequence[Span], k: int | None, tf: str, counts: RowCounts, inputs: BudgetInputs
) -> float:
    """The modelled growth since launch when a step starts: the peak's stored terms with only
    the span's earlier tfs written (no WAL, no spool). footprint_before + step_increment of a
    step never exceeds its span's peak, so a plan that fits passes every step's gate."""
    if tf == DAILY_TF:
        return 0.0
    assert k is not None
    peak = span_peak(spans, k, counts, inputs)
    start, end = spans[k]
    earlier = INTRADAY_TFS[: INTRADAY_TFS.index(tf)]
    written = counts.rows(start, end, earlier) * inputs.bytes_per_row
    return (
        written
        + peak.straddle
        + peak.compressed_rest
        + peak.daily_uncompressed
        + peak.daily_compressed
    )


def project(spans: Sequence[Span], counts: RowCounts, inputs: BudgetInputs) -> list[Peak]:
    """The 1d stage's peak, then each span's, in run order."""
    return [daily_peak(counts, inputs)] + [
        span_peak(spans, k, counts, inputs) for k in range(len(spans))
    ]


def overflowing(peaks: Sequence[Peak], inputs: BudgetInputs) -> list[Peak]:
    return [p for p in peaks if p.total > inputs.limit_bytes]


def split_years(counts: RowCounts, n: int, years: Sequence[int] | None = None) -> list[Span] | None:
    """n Jan-1 aligned spans of about equal intraday rows covering every year in `years`
    (default: every intraday year of the counts), or None when there are fewer years than n."""
    years = list(counts.intraday_years() if years is None else years)
    if not years or n < 1 or n > len(years):
        return None
    per_year = [counts.rows(_jan1(y), _jan1(y + 1), INTRADAY_TFS) for y in years]
    cumulative = [0.0]
    for rows in per_year:
        cumulative.append(cumulative[-1] + rows)
    total = cumulative[-1]
    cuts = [0]
    for i in range(1, n):
        target = total * i / n
        lo, hi = cuts[-1] + 1, len(years) - (n - i)  # leave one year for every later span
        cuts.append(min(range(lo, hi + 1), key=lambda c: (abs(cumulative[c] - target), c)))
    cuts.append(len(years))
    return [(_jan1(years[a]), _jan1(years[b - 1] + 1)) for a, b in zip(cuts, cuts[1:])]


@dataclasses.dataclass(frozen=True)
class SpanPlan:
    spans: list[Span]
    peaks: list[Peak]
    limit_bytes: float

    def as_record(self) -> dict[str, Any]:
        return {
            "spans": [[s.isoformat(), e.isoformat()] for s, e in self.spans],
            "peaks": [p.as_record() for p in self.peaks],
            "limit_bytes": self.limit_bytes,
        }


class SpanPlanRefused(RuntimeError):
    """No span count fits the disk limit; the message carries the table of every candidate."""


def plan_spans(
    counts: RowCounts, inputs: BudgetInputs, stored: RowCounts | None = None
) -> SpanPlan:
    """The smallest n whose largest projected peak (1d stage included) is at or below
    max_disk_fraction times the free bytes at launch. `stored` holds the rows already in the
    table (a re-plan or a resume): the spans still cover every intraday year of `counts`, but
    only the rows still to be written count as growth."""
    years = counts.intraday_years()
    if stored is not None:
        counts = counts.minus(stored)
    tried: list[str] = []
    for n in range(1, len(years) + 1):
        spans = split_years(counts, n, years)
        if spans is None:
            continue
        peaks = project(spans, counts, inputs)
        if not overflowing(peaks, inputs):
            return SpanPlan(spans, peaks, inputs.limit_bytes)
        worst = max(peaks, key=lambda p: p.total)
        tried.append(f"n={n}: worst {worst.step} {worst.total / 1e9:,.0f} GB")
    raise SpanPlanRefused(
        f"no span count fits {inputs.max_disk_fraction:.2f} x "
        f"{inputs.free_bytes_at_launch / 1e9:,.0f} GB free = {inputs.limit_bytes / 1e9:,.0f} GB "
        f"(or there is no intraday row to plan): " + "; ".join(tried or ["no candidate"])
    )


def format_peaks(peaks: Sequence[Peak], limit_bytes: float) -> str:
    """One line per step, in GB, for the runner's output and the runbook."""
    gb = 1e9
    lines = [
        f"{'step':>9} {'intraday':>9} {'straddle':>9} {'compr.':>8} {'1d unc':>7} "
        f"{'1d cmp':>7} {'wal':>5} {'spool':>6} {'peak':>8}  limit {limit_bytes / gb:,.0f} GB"
    ]
    for p in peaks:
        lines.append(
            f"{p.step:>9} {p.intraday / gb:9.1f} {p.straddle / gb:9.1f} "
            f"{p.compressed_rest / gb:8.1f} {p.daily_uncompressed / gb:7.1f} "
            f"{p.daily_compressed / gb:7.1f} {p.wal / gb:5.1f} {p.spool / gb:6.1f} "
            f"{p.total / gb:8.1f}{'  OVER' if p.total > limit_bytes else ''}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The unit guard (hard, before each COPY)
# ---------------------------------------------------------------------------


class DiskGuardRefused(RuntimeError):
    """A unit's projected bytes would push the run past its disk limit; nothing was written."""

    def __init__(self, detail: Mapping[str, Any]):
        self.detail = dict(detail)
        super().__init__(
            "disk_guard: "
            + ", ".join(
                f"{k}={v:,.0f}" if isinstance(v, int | float) else f"{k}={v}"
                for k, v in self.detail.items()
            )
        )


@dataclasses.dataclass
class UnitDiskGuard:
    """Refuses a unit before its COPY when its spool bytes times the stored-per-spool ratio would
    push the growth since launch past max_disk_fraction of the free bytes at launch, or the free
    space below the reserve. The ratio is the larger of the seed and every ratio measured so far
    (`observe`). `free_bytes` reads the database volume's free space now."""

    free_bytes_at_launch: int
    max_disk_fraction: float
    reserve_bytes: int
    wal_bytes: int
    stored_bytes_per_spool_byte: float
    free_bytes: Callable[[], int]

    def observe(self, stored_per_spool: float) -> None:
        self.stored_bytes_per_spool_byte = max(self.stored_bytes_per_spool_byte, stored_per_spool)

    def check(self, spool_bytes: int) -> None:
        free_now = int(self.free_bytes())
        projected = spool_bytes * self.stored_bytes_per_spool_byte
        growth = self.free_bytes_at_launch - free_now
        limit = self.max_disk_fraction * self.free_bytes_at_launch
        over_fraction = growth + projected + self.wal_bytes > limit
        under_reserve = free_now - projected - self.wal_bytes < self.reserve_bytes
        if over_fraction or under_reserve:
            raise DiskGuardRefused(
                {
                    "breached": "fraction_limit" if over_fraction else "reserve",
                    "spool_bytes": spool_bytes,
                    "projected_unit_bytes": projected,
                    "stored_bytes_per_spool_byte": self.stored_bytes_per_spool_byte,
                    "growth_since_launch_bytes": growth,
                    "wal_bytes": self.wal_bytes,
                    "limit_bytes": limit,
                    "free_bytes": free_now,
                    "reserve_bytes": self.reserve_bytes,
                }
            )
