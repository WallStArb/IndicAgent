"""The ingress write contract for vendor bar writes (phase 185 plan 39; raw-first since phase 191).

Data layer integrity design (docs/plans/2026-10-06-data-layer-integrity-design.md) section 4 and
the unified raw bar table design (docs/plans/2026-10-12-unified-raw-bar-table-design.md, Ingress
contract). `apply_raw_contract` is the one entry point; it takes one chunk of vendor answers
(`RawRow`, vendor and kind decided by the caller from what the vendor served) and, per
(symbol, timeframe, vendor, kind) series, in the caller's one transaction:

1. classifies the offer against the SAME series' stored raw rows (new, changed or unchanged by
   exact value; a bar missing from an answer is not a deletion; another vendor's row at the slot
   is a different key and never a revision);
2. judges the overlap: when the vendor restated more of its own stored rows than
   threshold.bar_integrity.max_revision_ratio allows, and at least
   threshold.bar_integrity.revision_ratio_min_stored rows are stored (a fetcher tail window holds
   about 78 5m bars and IBKR restates recent bars, so a small window is written and recorded,
   never refused), the series is refused: an ohlcv_load row (outcome refused) is written, the
   offered values that differ from the stored rows are held as pending revisions and ohlcv_raw is
   not touched, so selection cannot promote them, now or on any later call;
3. otherwise writes the ohlcv_load row, the raw rows (old values of changed rows go to
   ohlcv_revision, origin raw) and runs canonical selection over the touched span for direct
   timeframes (services/bar_selection.py).

Everything runs on the caller's connection, so the caller's one transaction covers the request
rows, the bars, the load record and the coverage update. This module owns the INSERTs into
ohlcv_load and reads the config and vocabulary tables; it owns no bar-table write (ohlcv_raw is
services/ohlcv_raw_writer.py's, canonical is services/bar_selection.py's).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from services.bar_selection import DIRECT_TIMEFRAMES, select_and_write
from services.ohlcv_raw_writer import (
    RawDelta,
    RawRow,
    RawWriteParams,
    hold_pending,
    preview_series,
    write_raw,
)
from src.intelligence.bars.selection import PolicyRow
from src.intelligence.bars.write_contract import WriteDelta, revision_ratio, should_refuse

# ohlcv_load.caller of an ingress chunk written outside a fetch context that names its own.
DEFAULT_CALLER = "ibkr-history-fetch"
OUTCOME_APPLIED = "applied"
OUTCOME_REFUSED = "refused"

MAX_RATIO_KEY = "threshold.bar_integrity.max_revision_ratio"
MIN_STORED_KEY = "threshold.bar_integrity.revision_ratio_min_stored"

_INSERT_LOAD_SQL = (
    "INSERT INTO ohlcv_load (load_id, symbol, timeframe, source, requested_start, requested_end, "
    "outcome, n_bars, n_new, n_changed, first_bar, last_bar, detail, caller, destination, "
    "n_unchanged, n_removed, n_archived) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


@dataclass(frozen=True)
class ContractParams:
    """The two APR thresholds the refusal reads."""

    max_ratio: float
    min_stored: int


@dataclass(frozen=True)
class SeriesLoad:
    """One series' write record: what a chunk offered and what the contract found."""

    symbol: str
    timeframe: str
    destination: str
    caller: str
    source: str
    n_bars: int
    n_stored: int
    n_new: int
    n_changed: int
    n_unchanged: int
    first_bar: date
    last_bar: date


def read_params(cur: Any) -> ContractParams:
    """Read the refusal thresholds from config_state; a missing key is a loud error."""
    cur.execute(
        "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)",
        ([MAX_RATIO_KEY, MIN_STORED_KEY],),
    )
    values = {key: value for key, value in cur.fetchall()}
    missing = {MAX_RATIO_KEY, MIN_STORED_KEY} - set(values)
    if missing:
        raise RuntimeError(
            f"write contract thresholds missing from config_state: {sorted(missing)}"
        )
    return ContractParams(
        max_ratio=float(values[MAX_RATIO_KEY]), min_stored=int(float(values[MIN_STORED_KEY]))
    )


def _utc_date(ts: datetime) -> date:
    return ts.astimezone(UTC).date()


def _record_load(
    cur: Any,
    load: SeriesLoad,
    *,
    outcome: str,
    detail: str | None,
    load_id: uuid.UUID,
    n_archived: int = 0,
) -> None:
    cur.execute(
        _INSERT_LOAD_SQL,
        (
            load_id,
            load.symbol,
            load.timeframe,
            load.source,
            load.first_bar,
            load.last_bar,
            outcome,
            load.n_bars,
            0 if outcome == OUTCOME_REFUSED else load.n_new,
            0 if outcome == OUTCOME_REFUSED else load.n_changed,
            load.first_bar,
            load.last_bar,
            detail,
            load.caller,
            load.destination,
            0 if outcome == OUTCOME_REFUSED else load.n_unchanged,
            0,
            n_archived,
        ),
    )


# --------------------------------------------------------------------------------------
# Raw-first ingress contract (phase 191 plan 04; design doc, Ingress contract)
# --------------------------------------------------------------------------------------

DESTINATION_RAW = "raw"
BATCH_ROWS_KEY = "infra.ohlcv_observation.copy_batch_rows"
FUTURE_TOLERANCE_KEY = "threshold.bar_integrity.future_bar_tolerance_s"
_VENDOR_NAMESPACE = "bar_vendor"
_KIND_NAMESPACE = "bar_kind"

SeriesKey = tuple[str, str, str, str]  # symbol, timeframe, vendor, kind


@dataclass(frozen=True)
class RawContractParams:
    """Everything `apply_raw_contract` reads from the database, read once by the caller."""

    thresholds: ContractParams
    write: RawWriteParams
    vendor_codes: frozenset[str]
    kind_codes: frozenset[str]
    kind_order: Mapping[str, int]
    policy_rows: tuple[PolicyRow, ...]


@dataclass(frozen=True)
class RefusedSeries:
    """A series whose vendor restated more of its own stored raw than the threshold allows."""

    symbol: str
    timeframe: str
    vendor: str
    kind: str
    ratio: float
    max_ratio: float
    n_changed: int
    n_stored: int
    detail: str
    n_held: int = 0


@dataclass(frozen=True)
class IngressResult:
    """What one `apply_raw_contract` call did. Counts cover the series that were written;
    a refused series writes no raw row (its offered values are held as pending revisions) and
    is counted in `n_held` only. `new_timestamps` are the timestamps of newly inserted raw rows."""

    n_offered: int
    n_new: int
    n_changed: int
    n_unchanged: int
    refused: bool
    selected_slots: int
    refused_series: tuple[RefusedSeries, ...] = ()
    n_held: int = 0
    new_timestamps: tuple[datetime, ...] = ()
    # Slots that reached raw but that no ranked vendor holds (the policy gap a loader must not
    # hide: the offered rows are in raw, canonical has no row for them).
    n_unselected: int = 0


def read_raw_params(cur: Any) -> RawContractParams:
    """Thresholds and raw-writer settings from config_state, vocabulary codes from the CVR
    (`bar_vendor`, `bar_kind`) and the whole bar_source_policy; a missing APR key is loud."""
    thresholds = read_params(cur)
    cur.execute(
        "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)",
        ([BATCH_ROWS_KEY, FUTURE_TOLERANCE_KEY],),
    )
    values = {key: value for key, value in cur.fetchall()}
    missing = {BATCH_ROWS_KEY, FUTURE_TOLERANCE_KEY} - set(values)
    if missing:
        raise RuntimeError(f"raw contract settings missing from config_state: {sorted(missing)}")
    cur.execute(
        "SELECT namespace, code, sort_order FROM controlled_vocabulary "
        "WHERE namespace = ANY(%s) AND NOT is_deprecated",
        ([_VENDOR_NAMESPACE, _KIND_NAMESPACE],),
    )
    vocabulary = cur.fetchall()
    vendors = frozenset(code for ns, code, _ in vocabulary if ns == _VENDOR_NAMESPACE)
    kinds = {code: order for ns, code, order in vocabulary if ns == _KIND_NAMESPACE}
    if not vendors or not kinds:
        raise RuntimeError("controlled_vocabulary has no bar_vendor or bar_kind codes")
    cur.execute(
        "SELECT timeframe, symbol, valid_from, valid_to, primary_source, fallback_source "
        "FROM bar_source_policy"
    )
    policy = tuple(PolicyRow(*row) for row in cur.fetchall())
    return RawContractParams(
        thresholds=thresholds,
        write=RawWriteParams(
            batch_rows=int(float(values[BATCH_ROWS_KEY])),
            future_tolerance_s=int(float(values[FUTURE_TOLERANCE_KEY])),
        ),
        vendor_codes=vendors,
        kind_codes=frozenset(kinds),
        kind_order=kinds,
        policy_rows=policy,
    )


def _own_delta(delta: RawDelta) -> WriteDelta:
    """The same-vendor delta as the pure contract's WriteDelta (counts only matter)."""
    return WriteDelta(changed={ts: (old, old) for ts, old in delta.changed_old.items()})  # type: ignore[misc]


def apply_raw_contract(
    conn: Any,
    rows: list[RawRow],
    *,
    caller: str,
    request_id: uuid.UUID,
    params: RawContractParams | None = None,
    waived: bool = False,
) -> IngressResult:
    """Record one chunk of vendor answers in ohlcv_raw, then select canonical rows.

    Per (symbol, timeframe, vendor, kind) series, in one transaction on the caller's connection:
    `preview_series` classifies the offer against the vendor's OWN stored raw rows, then
    `should_refuse` judges the overlap. An accepted series gets an ohlcv_load row (source =
    vendor, destination raw) and `write_raw`; it is then selected through
    `bar_selection.select_and_write` over the span it touched, for direct timeframes (1m, 5m,
    4h). Raw-only timeframes (15m, 1h, 1d) get no selection here.

    A refused series (the vendor restated more of its own history than the threshold allows)
    is durable: it gets an ohlcv_load row (outcome refused), its offered rows that differ from
    the stored rows are held as pending revisions (`hold_pending`), and ohlcv_raw is not
    touched, so the stored rows stay current and selection, which reads only current raw, can
    never promote a refused value, now or on any later call, however often the same values are
    offered again. Only an explicit decision releases it: a waived write. A (symbol, timeframe)
    with any refused series is not selected in this call.

    A cross-vendor difference never refuses and never writes a revision row: the vendors are
    different keys in ohlcv_raw. `waived` is the caller's statement that a recorded corporate
    action explains the restatement: nothing is refused and the load detail names the waiver.
    """
    if not rows:
        return IngressResult(0, 0, 0, 0, False, 0)
    with conn.cursor() as cur:
        params = params or read_raw_params(cur)

    by_series: dict[SeriesKey, list[RawRow]] = defaultdict(list)
    for row in rows:
        by_series[(row.symbol, row.timeframe, row.vendor, row.kind)].append(row)

    n_new = n_changed = n_unchanged = n_held_total = 0
    new_timestamps: list[datetime] = []
    refused: list[RefusedSeries] = []
    refused_slots: set[tuple[str, str]] = set()
    spans: dict[tuple[str, str], list[datetime]] = defaultdict(list)
    for (symbol, timeframe, vendor, kind), series_rows in sorted(by_series.items()):
        stamps = sorted({r.timestamp for r in series_rows})
        # The role may INSERT an ohlcv_load row but not UPDATE it, so the counts are known
        # before the row is written; write_raw (below) then records the same findings.
        delta = preview_series(conn, series_rows)
        own = _own_delta(delta)
        refuse = should_refuse(
            own,
            delta.n_stored,
            params.thresholds.max_ratio,
            min_stored=params.thresholds.min_stored,
            waived=waived,
        )
        load = SeriesLoad(
            symbol=symbol,
            timeframe=timeframe,
            destination=DESTINATION_RAW,
            caller=caller,
            source=vendor,
            n_bars=len(stamps),
            n_stored=delta.n_stored,
            n_new=delta.new,
            n_changed=delta.changed,
            n_unchanged=delta.unchanged,
            first_bar=_utc_date(stamps[0]),
            last_bar=_utc_date(stamps[-1]),
        )
        load_id = uuid.uuid4()
        detail: str | None
        held_stamps = sorted({*delta.changed_old, *delta.new_timestamps}) if refuse else []
        if refuse:
            ratio = revision_ratio(own, delta.n_stored)
            detail = (
                f"refused: {vendor} restated {delta.changed} / its stored "
                f"{delta.n_stored} = {ratio:.4f} > max {params.thresholds.max_ratio:.4f}; "
                f"new {delta.new}, unchanged {delta.unchanged}; {len(held_stamps)} offered rows "
                "held as pending revisions, the stored raw rows are unchanged"
            )
            refused.append(
                RefusedSeries(
                    symbol,
                    timeframe,
                    vendor,
                    kind,
                    ratio,
                    params.thresholds.max_ratio,
                    delta.changed,
                    delta.n_stored,
                    detail,
                    n_held=len(held_stamps),
                )
            )
            refused_slots.add((symbol, timeframe))
            # n_archived: offered rows recorded outside new/changed (unchanged ones equal the
            # stored raw rows, the rest are the pending revisions), so the load still balances.
            outcome, n_archived = OUTCOME_REFUSED, len(stamps)
        else:
            detail = (
                f"waived: recorded corporate action; changed {delta.changed} / stored "
                f"{delta.n_stored}"
                if waived and delta.changed
                else None
            )
            outcome, n_archived = OUTCOME_APPLIED, 0
            spans[(symbol, timeframe)].extend(stamps)
        with conn.cursor() as cur:
            _record_load(
                cur, load, outcome=outcome, detail=detail, load_id=load_id, n_archived=n_archived
            )
        if refuse:
            latest = {r.timestamp: r for r in series_rows}
            n_held_total += hold_pending(
                conn,
                [latest[ts] for ts in held_stamps],
                load_id=load_id,
                request_id=request_id,
                vendor_codes=params.vendor_codes,
                kind_codes=params.kind_codes,
                future_tolerance_s=params.write.future_tolerance_s,
            )
            continue
        (written,) = write_raw(
            conn,
            series_rows,
            load_id=load_id,
            request_id=request_id,
            vendor_codes=params.vendor_codes,
            kind_codes=params.kind_codes,
            batch_rows=params.write.batch_rows,
            future_tolerance_s=params.write.future_tolerance_s,
        )
        if (written.new, written.changed, written.unchanged) != (
            delta.new,
            delta.changed,
            delta.unchanged,
        ):
            raise RuntimeError(
                f"raw write disagrees with its preview for {symbol} {timeframe} {vendor} {kind}: "
                f"{(written.new, written.changed, written.unchanged)} vs "
                f"{(delta.new, delta.changed, delta.unchanged)}"
            )
        n_new += delta.new
        n_changed += delta.changed
        n_unchanged += delta.unchanged
        new_timestamps.extend(delta.new_timestamps)

    selected = unselected = 0
    for (symbol, timeframe), stamps in sorted(spans.items()):
        if (symbol, timeframe) in refused_slots or timeframe not in DIRECT_TIMEFRAMES:
            continue
        result = select_and_write(
            conn,
            symbols=[symbol],
            timeframe=timeframe,
            start=min(stamps),
            end=max(stamps) + timedelta(microseconds=1),
            policy_rows=params.policy_rows,
            kind_order=params.kind_order,
            batch_rows=params.write.batch_rows,
        )
        selected += result.new + result.changed
        unselected += result.unselected
    return IngressResult(
        n_offered=len(rows),
        n_new=n_new,
        n_changed=n_changed,
        n_unchanged=n_unchanged,
        refused=bool(refused),
        selected_slots=selected,
        refused_series=tuple(refused),
        n_held=n_held_total,
        new_timestamps=tuple(sorted(new_timestamps)),
        n_unselected=unselected,
    )
