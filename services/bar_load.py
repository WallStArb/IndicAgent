from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

from scripts.infrastructure.backfill._intraday_persist import persist_chunk_atomically
from services.ohlcv_coverage_writer import DESTINATION_RAW as COVERAGE_DESTINATION_RAW
from services.ohlcv_coverage_writer import CoverageDelta, refresh_1d_bounds
from services.ohlcv_ingress_contract import IngressResult, RawContractParams
from services.ohlcv_raw_writer import RawRow
from src.intelligence.bars.sources import DERIVATION_OWNED_TIMEFRAMES
from src.intelligence.bars.vendor_kind import (
    VENDOR_ALPACA,
    VENDOR_SERVED_KINDS,
    label_to_vendor_kind,
)

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
    `kind` overrides the vendor's label-map kind when the request context names the basis
    more precisely than the label does (the nightly's feed-derived `iex_rth`); it is checked
    against the vendor's served kinds so an iex answer can never be written as sip_rth.
    """

    vendor: str
    timeframe: str
    caller: str
    kind: str | None = None

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
    n_unselected: int = 0
    n_flagged_series: int = 0  # series the restatement detector flagged (written all the same)
    n_basis_flagged: int = 0  # of those, flagged with a basis-change signature: run is partial
    n_superseded: int = 0  # offers older than the stored answer: logged, raw unchanged
    n_excluded: int = 0  # slots holding only never-selected kinds: reported, not a failure

    def plus(self, ingress: IngressResult | None) -> LoadResult:
        if ingress is None:
            return self
        return LoadResult(
            self.n_offered + ingress.n_offered,
            self.n_new + ingress.n_new,
            self.n_changed + ingress.n_changed,
            self.n_unchanged + ingress.n_unchanged,
            self.n_unselected + ingress.n_unselected,
            self.n_flagged_series + len(ingress.flagged),
            self.n_basis_flagged + ingress.n_basis_flagged,
            self.n_superseded + ingress.n_superseded,
            self.n_excluded + ingress.n_excluded,
        )


def load_status(*, apply: bool, unselected: int = 0, basis_flagged: int = 0) -> str:
    """The run's status word: APPLIED only when no landed slot lacks a canonical winner (an
    unselected slot means the policy ranks no vendor that holds it: the rows are in raw,
    canonical has nothing there) and no series carries a basis-change flag. Restatements are
    written last-wins and flagged, never held (D-191-N); a share-only flag is informational, a
    basis-change flag (a common price or volume multiple, a time shift) makes the run partial
    until ops_restatement_review.py marks it reviewed (fourth review of 191-07, finding 2)."""
    if not apply:
        return "PLANNED"
    if unselected:
        return "UNSELECTED (landed in raw, no canonical winner, see bar_source_policy)"
    if basis_flagged:
        return "PARTIAL (basis-change restatement flagged, review with ops_restatement_review.py)"
    return "APPLIED"


def frame_to_raw_rows(
    frame: pd.DataFrame, symbol: str, *, vendor: str, timeframe: str, kind: str | None = None
) -> list[RawRow]:
    """One frame (columns t, o, h, l, c, v) -> RawRow, the kind from the vendor's label map
    (`label_to_vendor_kind`: alpaca -> sip_rth) unless an explicit kind is passed, which must be
    one the vendor serves (`VENDOR_SERVED_KINDS`; the nightly's feed-derived iex_rth). Every row
    is kept; nothing is dropped."""
    served_vendor, label_kind = label_to_vendor_kind(vendor)
    if served_vendor != vendor:
        raise ValueError(f"vendor {vendor!r} maps to {served_vendor!r}")
    if kind is None and vendor == VENDOR_ALPACA:
        raise ValueError(
            "alpaca rows need an explicit kind from alpaca_kind_for_feed: the kind names a "
            "split-adjusted basis the label default cannot vouch for (D-191-A)"
        )
    if kind is not None:
        served = VENDOR_SERVED_KINDS.get(vendor)
        if served is None or kind not in served:
            raise ValueError(f"vendor {vendor!r} does not serve kind {kind!r}")
    else:
        kind = label_kind
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
    answered_at: datetime | None = None,
    coverage: bool = True,
    params: RawContractParams | None = None,
    chunk_rows: int = CHUNK_ROWS,
    on_chunk=None,
    kind: str | None = None,
) -> LoadResult:
    """Offer one vendor frame to ohlcv_raw in chunks, one transaction per chunk; a dry run
    (`write` False) plans nothing beyond the offered count.

    `answered_at` is when the vendor answered the frame (the nightly's request answer time, a
    campaign artifact's recorded fetch time), required for a write: raw is last-wins by serve
    time, so replaying an old artifact after a newer serve logs the older values as superseded
    and leaves raw unchanged. `coverage` adds the same-transaction ohlcv_coverage upsert for the
    series (labeled with the vendor); a raw-only capture passes False. A 1d series is not widened
    chunk by chunk: its bounds are recomputed after the load (refresh_1d_bounds), because only the
    kinds that cover a session count and a vendor may restate a history.
    Rerunning is idempotent: an unchanged row writes nothing.
    """
    if not write:
        return LoadResult(n_offered=len(frame))
    if answered_at is None:
        raise ValueError(f"load_frame {symbol}: a write needs the vendor's answer time")
    rows = frame_to_raw_rows(frame, symbol, vendor=vendor, timeframe=timeframe, kind=kind)
    result = LoadResult()
    for start in range(0, len(rows), chunk_rows):
        chunk = rows[start : start + chunk_rows]
        persisted = persist_chunk_atomically(  # the campaign writes no ohlcv_request rows
            conn,
            request_rows=[],
            raw_rows=chunk,
            caller=caller,
            answered_at=answered_at,
            params=params,
            coverage=(
                CoverageDelta(
                    symbol,
                    timeframe,
                    COVERAGE_DESTINATION_RAW,
                    fetched_at=datetime.now(UTC),
                    provider=vendor,
                )
                if coverage and timeframe != "1d"
                else None
            ),
        )
        result = result.plus(persisted.ingress)
        if on_chunk:
            on_chunk(start + len(chunk), len(rows))
    if coverage and timeframe == "1d" and rows:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET LOCAL ROLE bar_derivation_writer")
                refresh_1d_bounds(cur, [symbol], provider=vendor)
    return result


def load_series(
    conn,
    policy: LoadPolicy,
    symbol: str,
    frame: pd.DataFrame,
    *,
    write: bool,
    answered_at: datetime | None = None,
    params: RawContractParams | None = None,
    chunk_rows: int = CHUNK_ROWS,
    on_chunk=None,
) -> LoadResult:
    """Load one symbol's frame under a policy; a dry run plans only the offered count. The
    frame must carry a tz-aware UTC `t` column plus the OHLCV columns, and a write the vendor's
    answer time (`load_frame`). Everything vendor-blind is the engine; the policy only names
    the writer."""
    return load_frame(
        conn,
        symbol,
        frame,
        vendor=policy.vendor,
        timeframe=policy.timeframe,
        caller=policy.caller,
        write=write,
        answered_at=answered_at,
        params=params,
        chunk_rows=chunk_rows,
        on_chunk=on_chunk,
        kind=policy.kind,
    )
