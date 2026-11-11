from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
import psycopg

from scripts.infrastructure.backfill._intraday_persist import persist_chunk_atomically
from services.ohlcv_coverage_writer import DESTINATION_RAW as COVERAGE_DESTINATION_RAW
from services.ohlcv_coverage_writer import CoverageDelta, refresh_1d_bounds
from services.ohlcv_ingress_contract import (
    IngressResult,
    RawContractParams,
    apply_raw_contract_batch,
)
from services.ohlcv_raw_writer import RawBatch, RawRow, build_raw_batch, datetime_to_us
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
    # series-chunks loaded with selection deferred (vendor unranked; bulk path): n_unselected
    # is then not measured by the load but by ops_selection_gate --compare
    n_selection_deferred: int = 0

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
            self.n_selection_deferred + ingress.n_selection_deferred,
        )


RAW_ONLY = (
    "RAW-ONLY (selection deferred: vendor unranked; unselected is counted by "
    "ops_selection_gate --compare)"
)


def load_status(
    *, apply: bool, unselected: int = 0, basis_flagged: int = 0, selection_deferred: int = 0
) -> str:
    """The run's status word: APPLIED only when no landed slot lacks a canonical winner (an
    unselected slot means the policy ranks no vendor that holds it: the rows are in raw,
    canonical has nothing there), no series carries a basis-change flag and selection ran.
    Restatements are written last-wins and flagged, never held (D-191-N); a share-only flag is
    informational, a basis-change flag (a common price or volume multiple, a time shift) makes the
    run partial until ops_restatement_review.py marks it reviewed (fourth review of 191-07,
    finding 2). A load whose selection was deferred (vendor unranked) is RAW-ONLY, never APPLIED
    or UNSELECTED: its unselected count of 0 is unmeasured, not clean, and the selection gate's
    --compare measures it (bulk raw load path design, section 6)."""
    if not apply:
        return "PLANNED"
    if unselected:
        return "UNSELECTED (landed in raw, no canonical winner, see bar_source_policy)"
    words = []
    if basis_flagged:
        words.append(
            "PARTIAL (basis-change restatement flagged, review with ops_restatement_review.py)"
        )
    if selection_deferred:
        words.append(RAW_ONLY)
    return "; ".join(words) or "APPLIED"


def resolve_kind(vendor: str, kind: str | None) -> str:
    """The kind a vendor's rows are written under: the vendor's label-map kind
    (`label_to_vendor_kind`) unless an explicit kind is passed, which must be one the vendor
    serves (`VENDOR_SERVED_KINDS`). Alpaca rows always need the explicit, feed-derived kind."""
    served_vendor, label_kind = label_to_vendor_kind(vendor)
    if served_vendor != vendor:
        raise ValueError(f"vendor {vendor!r} maps to {served_vendor!r}")
    if kind is None and vendor == VENDOR_ALPACA:
        raise ValueError(
            "alpaca rows need an explicit kind from alpaca_kind_for_feed: the kind names a "
            "split-adjusted basis the label default cannot vouch for (D-191-A)"
        )
    if kind is None:
        return label_kind
    served = VENDOR_SERVED_KINDS.get(vendor)
    if served is None or kind not in served:
        raise ValueError(f"vendor {vendor!r} does not serve kind {kind!r}")
    return kind


def frame_to_raw_rows(
    frame: pd.DataFrame, symbol: str, *, vendor: str, timeframe: str, kind: str | None = None
) -> list[RawRow]:
    """One frame (columns t, o, h, l, c, v) -> RawRow, the kind from the vendor's label map
    (`label_to_vendor_kind`: alpaca -> sip_rth) unless an explicit kind is passed, which must be
    one the vendor serves (`VENDOR_SERVED_KINDS`; the nightly's feed-derived iex_rth). Every row
    is kept; nothing is dropped."""
    kind = resolve_kind(vendor, kind)
    stamps = frame["t"].dt.to_pydatetime()
    # an optional per-row serve time (a batched loader's per-file LastModified), else the call's
    served = (
        frame["answered_at"].dt.to_pydatetime() if "answered_at" in frame else [None] * len(frame)
    )
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
            answered_at=at,
        )
        for ts, o, h, low, c, v, at in zip(
            stamps, frame["o"], frame["h"], frame["l"], frame["c"], frame["v"], served, strict=True
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
    request_rows: list[tuple] | None = None,
    lineage: Mapping[str, Any] | None = None,
) -> LoadResult:
    """Offer one vendor frame to ohlcv_raw in chunks, one transaction per chunk; a dry run
    (`write` False) plans nothing beyond the offered count and writes no ledger row.

    `request_rows` are the ohlcv_request rows of the one vendor page that served the frame
    (todo 596): they commit in the same transaction as the page's bars (an empty page commits
    its row alone), and the raw rows the page writes new or changed carry its request_id. The
    frame must then fit one chunk, so the ledger row and its bars can never commit apart.

    `answered_at` is when the vendor answered the frame (the nightly's request answer time, a
    campaign artifact's recorded fetch time), required for a write: raw is last-wins by serve
    time, so replaying an old artifact after a newer serve logs the older values as superseded
    and leaves raw unchanged. `coverage` adds the same-transaction ohlcv_coverage upsert for the
    series (labeled with the vendor); a raw-only capture passes False. A 1d series is not widened
    chunk by chunk: its bounds are recomputed after the load (refresh_1d_bounds), because only the
    kinds that cover a session count and a vendor may restate a history.
    Rerunning is idempotent: an unchanged row writes nothing. `lineage` is written into the load
    row's detail (a loader's record of the source file, ticker event and definitions).
    """
    if not write:
        return LoadResult(n_offered=len(frame))
    if answered_at is None:
        raise ValueError(f"load_frame {symbol}: a write needs the vendor's answer time")
    rows = frame_to_raw_rows(frame, symbol, vendor=vendor, timeframe=timeframe, kind=kind)
    refresh_in_chunk = bool(request_rows) and coverage and timeframe == "1d"
    if request_rows:
        if len(rows) > chunk_rows:
            raise ValueError(
                f"load_frame {symbol}: a page's {len(rows)} rows exceed one chunk "
                f"({chunk_rows}); its ledger row cannot commit with all of its bars"
            )
        if not rows:
            persist_chunk_atomically(conn, request_rows=list(request_rows), raw_rows=[])
            return LoadResult()
    result = LoadResult()
    for start in range(0, len(rows), chunk_rows):
        chunk = rows[start : start + chunk_rows]
        persisted = persist_chunk_atomically(  # a campaign artifact has no request rows
            conn,
            request_rows=list(request_rows or []),
            raw_rows=chunk,
            caller=caller,
            answered_at=answered_at,
            params=params,
            refresh_1d_provider=vendor if refresh_in_chunk else None,
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
            lineage=lineage,
        )
        result = result.plus(persisted.ingress)
        if on_chunk:
            on_chunk(start + len(chunk), len(rows))
    if coverage and timeframe == "1d" and rows and not refresh_in_chunk:
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
    request_rows: list[tuple] | None = None,
    lineage: Mapping[str, Any] | None = None,
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
        request_rows=request_rows,
        lineage=lineage,
    )


# --------------------------------------------------------------------------------------
# Bulk path (docs/plans/2026-11-11-bulk-raw-load-path-design.md): a loader's whole month as one
# RawBatch, written in transactions of whole series-chunks
# --------------------------------------------------------------------------------------


def _utc_ns(stamps: pd.Series, what: str) -> np.ndarray:
    """A tz-aware stamp column as UTC nanoseconds; a naive column is refused."""
    if stamps.dt.tz is None:
        raise ValueError(f"naive {what} refused (UTC required)")
    out: np.ndarray = (
        stamps.dt.tz_convert(UTC).dt.tz_localize(None).to_numpy("datetime64[ns]").view(np.int64)
    )
    return out


def ns_to_us(t_ns: np.ndarray, what: str = "timestamp") -> np.ndarray:
    """Nanoseconds as microseconds. Raw stores microseconds, so a stamp with a nanosecond part is
    refused (the row path's `to_pydatetime` drops it silently; the bulk path is stricter)."""
    t_ns = np.asarray(t_ns, dtype=np.int64)
    if (t_ns % 1000).any():
        raise ValueError(f"{what} with a nanosecond part refused: raw stores microseconds")
    us: np.ndarray = t_ns // 1000
    return us


def whole_volume(volume: np.ndarray) -> np.ndarray:
    """Served volume as int64 by the row path's `int(v)` (truncation); a non-finite volume raises
    as `int(nan)` does."""
    volume = np.asarray(volume)
    if volume.dtype.kind == "f" and not np.isfinite(volume).all():
        raise ValueError("cannot convert a non-finite volume to an integer")
    out: np.ndarray = volume.astype(np.int64)
    return out


def frame_to_raw_batch(
    frames: Mapping[str, pd.DataFrame],
    *,
    vendor: str,
    timeframe: str,
    params: RawContractParams,
    kind: str | None = None,
    answered_at: datetime | None = None,
    chunk_rows: int | None = None,
    now: datetime | None = None,
) -> RawBatch:
    """The columnar twin of `frame_to_raw_rows` over many symbols' frames (columns t, o, h, l,
    c, v and an optional per-row `answered_at`, else the call's `answered_at`): the same kind
    resolution and volume truncation, validated and cut into series-chunks by `build_raw_batch`."""
    kind = resolve_kind(vendor, kind)
    frames = {symbol: frame for symbol, frame in frames.items() if len(frame)}
    if not frames:
        raise ValueError("frame_to_raw_batch: no rows offered")
    symbols = np.concatenate([np.full(len(f), s, dtype=object) for s, f in frames.items()])
    frame = pd.concat(frames.values(), ignore_index=True)
    if "answered_at" in frame:
        if frame["answered_at"].isna().any():
            raise ValueError(
                "frame_to_raw_batch: some rows have no answered_at (every frame carries a per-row "
                "serve time, or none does and the call's answered_at applies)"
            )
        served = ns_to_us(_utc_ns(frame["answered_at"], "answered_at"), "answered_at")
    elif answered_at is None or answered_at.tzinfo is None:
        raise ValueError("frame_to_raw_batch needs the vendor's tz-aware answer time")
    else:
        served = np.full(len(frame), datetime_to_us(answered_at), dtype=np.int64)
    return build_raw_batch(
        timeframe=timeframe,
        vendor=vendor,
        kind=kind,
        symbols=symbols,
        ts_us=ns_to_us(_utc_ns(frame["t"], "timestamp")),
        open=frame["o"].to_numpy(np.float64),
        high=frame["h"].to_numpy(np.float64),
        low=frame["l"].to_numpy(np.float64),
        close=frame["c"].to_numpy(np.float64),
        volume=whole_volume(frame["v"].to_numpy()),
        served_us=served,
        vendor_codes=params.vendor_codes,
        kind_codes=params.kind_codes,
        future_tolerance_s=params.write.future_tolerance_s,
        # a series-chunk must fit one packed transaction (APR copy_batch_rows)
        chunk_rows=chunk_rows or min(CHUNK_ROWS, params.write.batch_rows),
        now=now,
    )


def pack_series_chunks(sizes: np.ndarray, max_rows: int) -> list[tuple[int, int]]:
    """Consecutive key ranges [first, stop) of at most `max_rows` rows each, never splitting a
    series-chunk (one key is one ohlcv_load row and lands whole or not at all)."""
    if len(sizes) and int(np.max(sizes)) > max_rows:
        raise ValueError(f"a series-chunk of {int(np.max(sizes))} rows exceeds {max_rows}")
    groups: list[tuple[int, int]] = []
    first = rows = 0
    for key, size in enumerate(np.asarray(sizes).tolist()):
        if rows + size > max_rows:
            groups.append((first, key))
            first, rows = key, 0
        rows += size
    if len(sizes):
        groups.append((first, len(sizes)))
    return groups


def load_batch(
    conn: Any,
    batch: RawBatch,
    *,
    caller: str,
    params: RawContractParams,
    lineage_by_symbol: Mapping[str, Mapping[str, Any]] | None = None,
    request_ids: list | None = None,
    max_rows: int | None = None,
    on_group: Callable[[int, int], None] | None = None,
) -> LoadResult:
    """Write a `RawBatch` to ohlcv_raw through the bulk contract, one transaction per packed group
    of whole series-chunks of at most `max_rows` rows (default the APR
    infra.ohlcv_observation.copy_batch_rows), under `persist_chunk_atomically`'s rules: an idle
    connection, the bar-writer role set locally, everything of a group committed together. Raw
    only: no request rows, no coverage. Rerunning is the resume: committed groups classify as
    unchanged. `on_group(rows_done, rows_total)` reports progress after each commit."""
    groups = pack_series_chunks(np.diff(batch.key_bounds()), max_rows or params.write.batch_rows)
    result = LoadResult()
    done = 0
    for first, stop in groups:
        group = batch.keys(first, stop)
        if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            raise RuntimeError("load_batch requires an idle connection (SET LOCAL ROLE)")
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET LOCAL ROLE bar_derivation_writer")
            ingress = apply_raw_contract_batch(
                conn,
                group,
                caller=caller,
                params=params,
                lineage_by_symbol=lineage_by_symbol,
                request_ids=None if request_ids is None else list(request_ids[first:stop]),
            )
        result = result.plus(ingress)
        done += len(group)
        if on_group:
            on_group(done, len(batch))
    return result
