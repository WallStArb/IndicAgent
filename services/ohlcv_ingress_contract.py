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

A refusal holds against small asks (third review of plan 191-07, finding 2). The 500-row minimum
lets a one-session ask restate freely, so a re-serve of a held span would otherwise land the very
values the refusal held. An offer that would change or insert a key still held under a refused
load of the same vendor and kind (a live pending revision there that no later accepted serve
answered) is refused whole, whatever its size: the re-serve lane verifies a refusal, it never
overrides one. Each held key the offer answers is reported as `held_offer` (the vendor served the
held value again), `stored_value` (it served the stored value: unchanged, nothing written) or
`new_value`. Releasing a hold stays an explicit decision.

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

import structlog

from services.bar_selection import DIRECT_TIMEFRAMES, NON_SERVE_CALLERS, select_and_write
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

HELD_OFFER, STORED_VALUE, NEW_VALUE = "held_offer", "stored_value", "new_value"

logger = structlog.get_logger(__name__)

# Pending values a refused load of the same vendor and kind holds at the offered keys, with the
# refusal time (third review of plan 191-07, finding 2).
_OPEN_HOLDS_SQL = (
    'SELECT v."timestamp", v.old_open, v.old_high, v.old_low, v.old_close, v.old_volume, '
    "l.loaded_at FROM ohlcv_revision v JOIN ohlcv_load l ON l.load_id = v.load_id "
    "AND l.symbol = v.symbol AND l.timeframe = v.timeframe "
    "WHERE v.symbol = %s AND v.timeframe = %s AND v.vendor = %s AND v.kind = %s "
    "AND v.origin = 'pending' AND l.outcome = 'refused' AND v.\"timestamp\" = ANY(%s)"
)
# The load that wrote the current raw row at a held key: an applied vendor serve after the
# refusal answered the key again (services/bar_selection.py read_held_keys), so it holds nothing.
_RAW_WRITER_AT_SQL = (
    'SELECT r."timestamp", l.loaded_at, l.outcome, l.destination, l.caller FROM ohlcv_raw r '
    "JOIN ohlcv_load l ON l.load_id = r.load_id WHERE r.symbol = %s AND r.timeframe = %s "
    'AND r.vendor = %s AND r.kind = %s AND r."timestamp" = ANY(%s)'
)

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
    # answers at keys a refused load still holds: (timestamp, held_offer | stored_value | new_value)
    held_answers: tuple[tuple[datetime, str], ...] = ()


def read_open_holds(
    conn: Any, symbol: str, timeframe: str, vendor: str, kind: str, stamps: list[datetime]
) -> dict[datetime, set[tuple]]:
    """timestamp -> the values refused loads of this series still hold there. A key whose
    current raw row an applied vendor serve wrote after the latest refusal holding it was
    answered again and holds nothing."""
    holds: dict[datetime, set[tuple]] = defaultdict(set)
    refused_at: dict[datetime, datetime] = {}
    with conn.cursor() as cur:
        cur.execute(_OPEN_HOLDS_SQL, (symbol, timeframe, vendor, kind, stamps))
        for ts, o, h, lo, c, v, at in cur.fetchall():
            holds[ts].add((o, h, lo, c, v))
            refused_at[ts] = max(at, refused_at.get(ts, at))
        if not holds:
            return {}
        cur.execute(_RAW_WRITER_AT_SQL, (symbol, timeframe, vendor, kind, sorted(holds)))
        for ts, at, outcome, destination, caller in cur.fetchall():
            if (
                ts in refused_at
                and outcome == OUTCOME_APPLIED
                and destination == DESTINATION_RAW
                and caller not in NON_SERVE_CALLERS
                and at > refused_at[ts]
            ):
                holds.pop(ts, None)
    return dict(holds)


def held_answers(
    offered: Mapping[datetime, tuple],
    holds: Mapping[datetime, set[tuple]],
    writes: set[datetime],
) -> dict[datetime, str]:
    """What the offer answers at each held key: the held value again, the stored value (the key
    is not among `writes`, the stamps the offer would change or insert), or a new value."""
    out: dict[datetime, str] = {}
    for ts, held in holds.items():
        if ts not in offered:
            continue
        if offered[ts] in held:
            out[ts] = HELD_OFFER
        elif ts not in writes:
            out[ts] = STORED_VALUE
        else:
            out[ts] = NEW_VALUE
    return out


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
    # every held key an offer answered: (symbol, timeframe, vendor, kind, timestamp, answer)
    held_answers: tuple[tuple[str, str, str, str, datetime, str], ...] = ()


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
    answers_out: list[tuple[str, str, str, str, datetime, str]] = []
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
        holds = read_open_holds(conn, symbol, timeframe, vendor, kind, stamps)
        writes = {*delta.changed_old, *delta.new_timestamps}
        answers = held_answers(
            {r.timestamp: (r.open, r.high, r.low, r.close, r.volume) for r in series_rows},
            holds,
            writes,
        )
        overrides = sorted(ts for ts in answers if ts in writes)
        answers_out.extend(
            (symbol, timeframe, vendor, kind, ts, answer) for ts, answer in sorted(answers.items())
        )
        if answers:
            logger.info(
                "ingress.held_keys_answered",
                symbol=symbol,
                timeframe=timeframe,
                vendor=vendor,
                kind=kind,
                held_offer=sum(1 for a in answers.values() if a == HELD_OFFER),
                stored_value=sum(1 for a in answers.values() if a == STORED_VALUE),
                new_value=sum(1 for a in answers.values() if a == NEW_VALUE),
                would_write=len(overrides),
            )
        # a held key changes only by an explicit decision, never by a small ask (finding 2)
        held_refusal = bool(overrides) and not waived
        refuse = refuse or held_refusal
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
            counts = {
                a: sum(1 for x in answers.values() if x == a) for a in sorted(set(answers.values()))
            }
            reason = (
                f"{len(overrides)} offered rows would change keys a refused load holds "
                f"(answers {counts}); a hold is released only by an explicit decision"
                if held_refusal
                else f"> max {params.thresholds.max_ratio:.4f}"
            )
            detail = (
                f"refused: {vendor} restated {delta.changed} / its stored "
                f"{delta.n_stored} = {ratio:.4f}; {reason}; "
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
                    held_answers=tuple(sorted(answers.items())),
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
            # read under the series' selection lock, never the chunk's cached copy: a policy
            # --reselect commits holding that lock (second review of 191-07, low item)
            policy_rows=None,
            kind_order=params.kind_order,
            batch_rows=params.write.batch_rows,
        )
        selected += result.new + result.changed
        # A NULL-volume winner is skipped by the writer and leaves the slot's previous canonical
        # row in place: the offered row reached raw and no canonical row took it, so it counts
        # with the unselected slots (191-07 review, low finding).
        unselected += result.unselected + result.skipped_null_volume
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
        held_answers=tuple(answers_out),
    )
