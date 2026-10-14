from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from scripts.infrastructure.backfill._intraday_persist import persist_chunk_atomically
from services.ohlcv_coverage_writer import DESTINATION_GRID as COVERAGE_DESTINATION_GRID
from services.ohlcv_coverage_writer import CoverageDelta
from services.ohlcv_ingress_contract import IngressResult, RawContractParams
from services.ohlcv_raw_writer import RawRow
from src.intelligence.bars.sources import DERIVATION_OWNED_TIMEFRAMES
from src.intelligence.bars.vendor_kind import label_to_vendor_kind

# Chunk size bounds the rows one transaction offers the contract (its stored-row read renders an
# array of the chunk's stamps client-side; a 100k-stamp array blew psycopg's 1 GiB query buffer,
# ProgramLimitExceeded, observed 2026-10-10; 10k keeps it at sub-MB scale).
CHUNK_ROWS = 10_000


@dataclass(frozen=True)
class LoadPolicy:
    """Which vendor and timeframe this loader writes, and under what caller name.

    Policy is named, never passed ad hoc: the vendor travels in the RawRow (the contract
    validates it against the CVR), and the timeframe selects the slot rule. A timeframe in
    DERIVATION_OWNED_TIMEFRAMES is refused outright (writer fence); `load_frame` is the
    fence-free raw capture for the timeframes the vendor serves that no loader authors.
    """

    vendor: str
    timeframe: str
    caller: str

    def __post_init__(self) -> None:
        if self.timeframe in DERIVATION_OWNED_TIMEFRAMES:
            raise ValueError(
                f"{self.timeframe!r} is a derivation-owned timeframe; the load engine "
                "writes raw provider bars only (writer fence)"
            )


@dataclass(frozen=True)
class LoadResult:
    """What a frame load did, summed over its chunks. A dry run reports `n_offered` only."""

    n_offered: int = 0
    n_new: int = 0
    n_changed: int = 0
    n_unchanged: int = 0
    n_held: int = 0
    refused: bool = False
    n_refused_series: int = 0

    @property
    def n_landed(self) -> int:
        """Offered rows that reached ohlcv_raw (everything not held as a pending revision)."""
        return self.n_offered - self.n_held

    def plus(self, ingress: IngressResult | None) -> LoadResult:
        if ingress is None:
            return self
        return LoadResult(
            self.n_offered + ingress.n_offered,
            self.n_new + ingress.n_new,
            self.n_changed + ingress.n_changed,
            self.n_unchanged + ingress.n_unchanged,
            self.n_held + ingress.n_held,
            self.refused or ingress.refused,
            self.n_refused_series + len(ingress.refused_series),
        )


def load_status(*, apply: bool, held: int) -> str:
    """The run's status word: APPLIED only when nothing was held as a refused series' pending
    revisions; a held row means a vendor restated its own history and needs a decision."""
    if not apply:
        return "PLANNED"
    return "APPLIED" if held == 0 else "HELD (applied, refused series held, see ohlcv_load)"


def frame_to_raw_rows(
    frame: pd.DataFrame, symbol: str, *, vendor: str, timeframe: str
) -> list[RawRow]:
    """One frame (columns t, o, h, l, c, v) -> RawRow, the kind from the vendor's label map
    (`label_to_vendor_kind`: alpaca -> sip_rth). Every row is kept; nothing is dropped."""
    served_vendor, kind = label_to_vendor_kind(vendor)
    if served_vendor != vendor:
        raise ValueError(f"vendor {vendor!r} maps to {served_vendor!r}")
    stamps = frame["t"].dt.to_pydatetime()
    return [
        RawRow(
            timestamp=ts,
            symbol=symbol,
            timeframe=timeframe,
            vendor=vendor,
            kind=kind,
            open=float(o),
            high=float(h),
            low=float(low),
            close=float(c),
            volume=int(v),
        )
        for ts, o, h, low, c, v in zip(
            stamps, frame["o"], frame["h"], frame["l"], frame["c"], frame["v"], strict=True
        )
    ]


def load_frame(
    conn,
    symbol: str,
    frame: pd.DataFrame,
    *,
    vendor: str,
    timeframe: str,
    caller: str,
    write: bool,
    coverage: bool = True,
    params: RawContractParams | None = None,
    chunk_rows: int = CHUNK_ROWS,
    on_chunk=None,
) -> LoadResult:
    """Offer one vendor frame to ohlcv_raw in chunks, one transaction per chunk; a dry run
    (`write` False) plans nothing beyond the offered count.

    `coverage` adds the same-transaction ohlcv_coverage upsert for the series (labeled with the
    vendor); a raw-only capture such as the nightly 1d passes False. Rerunning is idempotent: an
    unchanged row writes nothing.
    """
    if not write:
        return LoadResult(n_offered=len(frame))
    rows = frame_to_raw_rows(frame, symbol, vendor=vendor, timeframe=timeframe)
    result = LoadResult()
    for start in range(0, len(rows), chunk_rows):
        chunk = rows[start : start + chunk_rows]
        persisted = persist_chunk_atomically(  # the campaign writes no ohlcv_request rows
            conn,
            request_rows=[],
            raw_rows=chunk,
            caller=caller,
            params=params,
            coverage=(
                CoverageDelta(
                    symbol,
                    timeframe,
                    COVERAGE_DESTINATION_GRID,
                    fetched_at=datetime.now(UTC),
                    provider=vendor,
                )
                if coverage
                else None
            ),
        )
        result = result.plus(persisted.ingress)
        if on_chunk:
            on_chunk(start + len(chunk), len(rows))
    return result


def load_series(
    conn,
    policy: LoadPolicy,
    symbol: str,
    frame: pd.DataFrame,
    *,
    write: bool,
    params: RawContractParams | None = None,
    chunk_rows: int = CHUNK_ROWS,
    on_chunk=None,
) -> LoadResult:
    """Load one symbol's frame under a policy; a dry run plans only the offered count. The
    frame must carry a tz-aware UTC `t` column plus the OHLCV columns. Everything vendor-blind
    is the engine; the policy only names the writer."""
    return load_frame(
        conn,
        symbol,
        frame,
        vendor=policy.vendor,
        timeframe=policy.timeframe,
        caller=policy.caller,
        write=write,
        params=params,
        chunk_rows=chunk_rows,
        on_chunk=on_chunk,
    )
