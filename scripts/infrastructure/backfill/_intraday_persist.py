"""Atomic request-and-bars persist for fetched chunks (todo 462, phase 185 plan 12, phase 191
plan 05; design: docs/plans/2026-10-12-unified-raw-bar-table-design.md, Ingress contract).

A chunk's answer and its bars land together. The helper writes, in ONE transaction:

    BEGIN
      SET LOCAL ROLE bar_derivation_writer     -- raw rows (and selection) via the ingress contract
      apply_raw_contract(...)
      SET LOCAL ROLE ohlcv_observation_writer  -- the chunk's ohlcv_request rows
      write_request_rows(...)
      SET LOCAL ROLE bar_derivation_writer     -- the series' ohlcv_coverage row (optional)
      upsert_coverage(...)
    COMMIT

so a recorded answer can never outrun its stored bars (T-185-12-07) and the coverage ledger can
never describe bars that did not land. No grant is added: both NOLOGIN roles already hold the
grants they need (migrations 380, 383, 472), and sequential SET LOCAL ROLE inside one top-level
transaction is the verified pattern from plans 11 and 12.

The raw write runs before the request rows because each request row that answered with bars carries
the content digest of the answer the chunk stored (design section 3, direct mode provenance;
src/intelligence/bars/digest.py arithmetic over the chunk's rows, one per timestamp, last wins),
and the contract writes every offered row last-wins (D-191-N): nothing is refused or held, so a
request that answered with bars always carries the digest of what the chunk stored.

Coverage follows the raw write: the rows the contract found new move the series' bounds and row
count (every new raw row of the vendor counts, tradeable or not: coverage describes what that
vendor holds). The CoverageDelta carries the serving vendor's
label (phase 190, migration 464), set where the delta is built.

Discipline the caller owes:

- The helper demands an idle connection, and a flush is NEVER called inside the helper's
  transaction (a flush opens its own and would trap the SET LOCAL ROLE). If the sink holds other
  pending rows, the caller flushes them on the idle connection before or after this helper.
- The request rows arrive as data: the caller pulled them off the sink buffer via the sink's
  public take_requests method, so the helper never touches the sink and ohlcv_request keeps one
  INSERT definition (write_request_rows, imported here).
- The bars arrive as RawRow (vendor and kind decided by the caller from what the vendor served).
  The helper owns no INSERT for any bar table.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import psycopg

from services.ohlcv_coverage_writer import (
    CoverageDelta,
    count_new_slots,
    refresh_1d_bounds,
    upsert_coverage,
)
from services.ohlcv_ingress_contract import (
    DEFAULT_CALLER,
    IngressResult,
    RawContractParams,
    apply_raw_contract,
    read_raw_params,
)
from services.ohlcv_raw_writer import RawRow
from services.ohlcv_request_writer import REQUEST_ROW_WIDTH, write_request_rows
from src.intelligence.bars.digest import bar_content_digest

_REQUEST_ROLE = "ohlcv_observation_writer"
# bar_derivation_writer holds the raw, load, revision, selection and coverage grants
# (migrations 383, 443, 472); it is the bar-writer role, not a second raw owner.
_BAR_ROLE = "bar_derivation_writer"


@dataclass(frozen=True)
class PersistResult:
    """What one persisted chunk did. `ingress` is None when nothing was offered."""

    n_requests: int
    n_rows: int
    ingress: IngressResult | None = None


# ohlcv_request row layout (services/ohlcv_request_writer._REQUEST_COLUMNS).
_REQ_ID, _REQ_OUTCOME, _REQ_N_BARS, _REQ_ANSWERED_AT = 0, 11, 14, 18
_REQUEST_COLUMNS_WITHOUT_DIGEST = REQUEST_ROW_WIDTH


def persist_chunk_atomically(
    conn: Any,
    *,
    request_rows: list[tuple],
    raw_rows: list[RawRow],
    coverage: CoverageDelta | None = None,
    caller: str = DEFAULT_CALLER,
    request_id: uuid.UUID | None = None,
    answered_at: datetime | None = None,
    params: RawContractParams | None = None,
    refresh_1d_provider: str | None = None,
) -> PersistResult:
    """Commit one fetched chunk's raw rows, its request rows and (when `coverage` is given) its
    ohlcv_coverage update together.

    `request_id` names the ohlcv_request that served the raw rows (lineage); by default it is the
    chunk's answering request (the last request row that answered with bars, else the last row),
    and a chunk with no request rows (a loader) gets a fresh id. `params` is the contract's
    pre-read settings (a loader reads them once, the fetcher lets each chunk read them).
    `refresh_1d_provider` names the vendor whose 1d bounds are recomputed for the chunk's symbols
    in the same transaction (a daily answer moves no CoverageDelta; a run killed at the service
    time limit never reaches an end-of-run refresh).
    `answered_at` is when the vendor answered the chunk, the served_at of its raw rows and the
    serve time last-wins orders by (fourth review of plan 191-07, finding 1); by default the
    answering request row's answered_at. A chunk with raw rows and neither raises before any
    SQL: the write time is never a serve time. Raises with the transaction rolled back if any
    write fails: no answer is recorded without its bars, no bars land without their answer, and
    the ledger never moves without both.
    """
    if not request_rows and not raw_rows:
        return PersistResult(0, 0)
    if coverage is not None:
        _check_rows_match_series(raw_rows, coverage)
    if raw_rows:
        answered_at = answered_at or _answering_answered_at(request_rows)
        if answered_at is None:
            raise ValueError(
                "persist_chunk_atomically: raw rows need the vendor's answer time (answered_at "
                "or an answering request row carrying it)"
            )
    if conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
        raise RuntimeError(
            "persist_chunk_atomically requires an idle connection: an open caller "
            "transaction would demote this to a savepoint and trap SET LOCAL ROLE"
        )
    ingress: IngressResult | None = None
    with conn.transaction():
        if raw_rows:
            with conn.cursor() as cur:
                # The contract's settings (config_state, the CVR, bar_source_policy) are read as
                # the connection's own user: the bar-writer role holds no grant on them.
                params = params or read_raw_params(cur)
                cur.execute(f"SET LOCAL ROLE {_BAR_ROLE}")
            ingress = apply_raw_contract(
                conn,
                raw_rows,
                caller=caller,
                request_id=request_id or _answering_request_id(request_rows),
                answered_at=answered_at,
                params=params,
            )
        with conn.cursor() as cur:
            if request_rows:
                stamped = [_with_digest(row, raw_rows) for row in request_rows]
                cur.execute(f"SET LOCAL ROLE {_REQUEST_ROLE}")
                write_request_rows(cur, stamped)
            if coverage is not None and ingress is not None:
                cur.execute(f"SET LOCAL ROLE {_BAR_ROLE}")
                _upsert_coverage(cur, raw_rows, ingress, coverage)
            if refresh_1d_provider is not None and ingress is not None:
                cur.execute(f"SET LOCAL ROLE {_BAR_ROLE}")
                refresh_1d_bounds(
                    cur, {row.symbol for row in raw_rows}, provider=refresh_1d_provider
                )
    return PersistResult(len(request_rows), len(raw_rows), ingress)


def _answering_row(request_rows: list[tuple]) -> tuple | None:
    """The request that served a chunk: the provider reports every request at its outcome point
    and hands the chunk to on_chunk right after, so the last request that answered with bars is
    the one (else the last row; None without request rows)."""
    answering = [
        row for row in request_rows if row[_REQ_OUTCOME] == "bars" and row[_REQ_N_BARS] > 0
    ]
    candidates = answering or request_rows
    return candidates[-1] if candidates else None


def _answering_request_id(request_rows: list[tuple]) -> uuid.UUID:
    """The answering request's id; a chunk without request rows (a loader's frame) gets a fresh
    id."""
    row = _answering_row(request_rows)
    return uuid.UUID(str(row[_REQ_ID])) if row is not None else uuid.uuid4()


def _answering_answered_at(request_rows: list[tuple]) -> datetime | None:
    """The answering request's answer time, or None."""
    row = _answering_row(request_rows)
    return row[_REQ_ANSWERED_AT] if row is not None else None


def chunk_digest(rows: list[RawRow]) -> str:
    """Content digest of the answer a chunk offers: one row per timestamp (last wins), the
    bar content digest arithmetic with no quarantine rules (the ingress rows carry none)."""
    keyed = {row.timestamp: row for row in rows}
    ordered = [keyed[ts] for ts in sorted(keyed)]
    return bar_content_digest(
        np.array([ts.timestamp() for ts in sorted(keyed)], dtype=np.int64),
        np.array([row.open for row in ordered], dtype=np.float64),
        np.array([row.high for row in ordered], dtype=np.float64),
        np.array([row.low for row in ordered], dtype=np.float64),
        np.array([row.close for row in ordered], dtype=np.float64),
        np.array([row.volume for row in ordered], dtype=np.float64),
        [() for _ in ordered],
    )


def _with_digest(request_row: tuple, bar_rows: list[RawRow]) -> tuple:
    """The request row with its content digest appended: the chunk's digest when the request
    answered with bars and the chunk was stored, NULL otherwise."""
    if len(request_row) != _REQUEST_COLUMNS_WITHOUT_DIGEST:
        raise ValueError(
            f"request rows reach the persist helper without a digest column "
            f"({_REQUEST_COLUMNS_WITHOUT_DIGEST} values); got {len(request_row)}"
        )
    has_bars = request_row[_REQ_OUTCOME] == "bars" and request_row[_REQ_N_BARS] > 0
    stored = has_bars and bool(bar_rows)
    return request_row + ((chunk_digest(bar_rows) if stored else None),)


def _check_rows_match_series(rows: list[RawRow], coverage: CoverageDelta) -> None:
    """Refuse, before any SQL, a chunk holding rows for a series other than the
    one its coverage update names: the ledger would silently credit the wrong row."""
    series = {(row.symbol, row.timeframe) for row in rows}
    if series - {(coverage.symbol, coverage.timeframe)}:
        raise ValueError(
            f"chunk rows span series {sorted(series)} but the coverage update names "
            f"({coverage.symbol!r}, {coverage.timeframe!r})"
        )


def _upsert_coverage(
    cur: Any, rows: list[RawRow], ingress: IngressResult, coverage: CoverageDelta
) -> None:
    """Widen the series' stored bounds by the rows the raw write found new (under the bar-writer
    role already set). Coverage counts every row the vendor served, tradeable or not: it
    describes what that vendor holds in ohlcv_raw. Bounds follow the new rows; when none are new
    they still reflect the offered rows, which are stored. row_count counts distinct slots, so a
    stamp the vendor already held under another kind adds none."""
    new_timestamps = set(ingress.new_timestamps)
    bounds = new_timestamps or {row.timestamp for row in rows}
    upsert_coverage(
        cur,
        coverage,
        earliest=min(bounds),
        latest=max(bounds),
        n_new_rows=count_new_slots(
            cur, coverage.symbol, coverage.timeframe, coverage.provider, ingress.new_timestamps
        ),
    )
