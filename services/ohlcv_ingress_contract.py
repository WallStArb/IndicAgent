"""The ingress write contract for vendor bar writes (phase 185 plan 39; raw-first since phase 191).

Data layer integrity design (docs/plans/archive/2026-10-06-data-layer-integrity-design.md)
section 4 and the unified raw bar table design (docs/plans/2026-10-12-unified-raw-bar-table-design.md, Ingress
contract, D-191-N). `apply_raw_contract` is the one entry point; it takes one chunk of vendor
answers (`RawRow`, vendor and kind decided by the caller from what the vendor served) and, per
(symbol, timeframe, vendor, kind) series, in the caller's one transaction:

1. classifies the offer against the SAME series' stored raw rows (new, changed or unchanged by
   exact value; a bar missing from an answer is not a deletion; another vendor's row at the slot
   is a different key and never a revision);
2. writes the ohlcv_load row and the raw rows last-wins by serve time: a vendor's own re-serve
   answered at or after the stored row's served_at replaces it and the old value goes to
   ohlcv_revision (origin raw), so every overwrite is recoverable (owner decision 2026-10-14,
   D-191-N: no load-level refusal, nothing held); an offer older than the stored answer (an
   artifact replay) leaves raw unchanged and is logged as origin superseded (fourth review of
   plan 191-07, finding 1). `answered_at` is the vendor's answer time, never the write time;
3. runs the restatement detector (src/intelligence/bars/restatement.py) over the rows the load
   replaces: a load whose changed share exceeds the APR flag share, or whose changes carry a
   basis-change signature (a common price or volume multiple, a one-bar time shift), is logged
   as a warning, counted on the `ohlcv_restatement_flags_total` metric and recorded in
   ohlcv_restatement_flag for review. It never blocks the write; a basis-change flag makes the
   caller's run partial (`IngressResult.n_basis_flagged`) and fails the selection gate until it
   is reviewed (scripts/ops/bars/ops_restatement_review.py);
4. runs canonical selection over the touched span for direct timeframes
   (services/bar_selection.py).

Everything runs on the caller's connection, so the caller's one transaction covers the request
rows, the bars, the load record, the flag and the coverage update. This module owns the INSERTs
into ohlcv_load and ohlcv_restatement_flag and reads the config and vocabulary tables; it owns
no bar-table write (ohlcv_raw is services/ohlcv_raw_writer.py's, canonical is
services/bar_selection.py's).
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog

from services.bar_selection import DIRECT_TIMEFRAMES, lock_selections, select_and_write
from services.ohlcv_raw_writer import (
    CLS_REPLACE,
    CLS_SUPERSEDED,
    CLS_UNCHANGED,
    Classified,
    RawBatch,
    RawDelta,
    RawRow,
    RawWriteParams,
    batch_symbols,
    preview_series,
    stage_and_classify,
    us_to_datetime,
    write_classified,
    write_raw,
)
from src.intelligence.bars.restatement import (
    BASIS_SIGNATURES,
    DetectorParams,
    Restatement,
    detect,
)
from src.intelligence.bars.selection import PolicyRow
from src.observability.metrics import counter

# ohlcv_load.caller of an ingress chunk written outside a fetch context that names its own.
DEFAULT_CALLER = "ibkr-history-fetch"
OUTCOME_APPLIED = "applied"

logger = structlog.get_logger(__name__)

RESTATEMENT_FLAGS = counter(
    "ohlcv_restatement_flags_total",
    "Vendor loads the restatement detector flagged (share or basis-change signature), by vendor "
    "and signature; never blocks a write (D-191-N)",
)

# APR keys of the restatement detector (migration 481).
FLAG_SHARE_KEY = "threshold.bar_integrity.restatement_flag_share"
FLAG_MIN_STORED_KEY = "threshold.bar_integrity.restatement_flag_min_stored"
SIGNATURE_MIN_BARS_KEY = "threshold.bar_integrity.restatement_signature_min_bars"
RATIO_TOLERANCE_KEY = "threshold.bar_integrity.restatement_ratio_tolerance"
SHIFT_MIN_SHARE_KEY = "threshold.bar_integrity.restatement_shift_min_share"
# Detector v2 (migration 485; fourth review of 191-07, finding 3).
RATIO_MIN_SHARE_KEY = "threshold.bar_integrity.restatement_ratio_min_share"
RATIO_MIN_MOVE_KEY = "threshold.bar_integrity.restatement_ratio_min_move"
PRICE_TICK_KEY = "threshold.bar_integrity.restatement_price_tick"
VOLUME_TOLERANCE_KEY = "threshold.bar_integrity.restatement_volume_tolerance"
VOLUME_MIN_MOVE_KEY = "threshold.bar_integrity.restatement_volume_min_move"
_DETECTOR_KEYS = (
    FLAG_SHARE_KEY,
    FLAG_MIN_STORED_KEY,
    SIGNATURE_MIN_BARS_KEY,
    RATIO_TOLERANCE_KEY,
    SHIFT_MIN_SHARE_KEY,
    RATIO_MIN_SHARE_KEY,
    RATIO_MIN_MOVE_KEY,
    PRICE_TICK_KEY,
    VOLUME_TOLERANCE_KEY,
    VOLUME_MIN_MOVE_KEY,
)
# Bar lengths (a unit conversion, not a tunable).
_BAR = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}

_INSERT_LOAD_SQL = (
    "INSERT INTO ohlcv_load (load_id, symbol, timeframe, source, requested_start, requested_end, "
    "outcome, n_bars, n_new, n_changed, first_bar, last_bar, detail, caller, destination, "
    "n_unchanged, n_removed, n_archived, n_superseded) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
_INSERT_FLAG_SQL = (
    "INSERT INTO ohlcv_restatement_flag (load_id, symbol, timeframe, vendor, kind, n_stored, "
    "n_changed, share, signatures, ratio, shift_bars, detail) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
# The review queue (migration 485; fourth review of 191-07, finding 2). A flag carrying a
# basis-change signature stays unreviewed until a reviewer marks it; the selection gate fails
# and the D7 gauge ohlcv_restatement_unreviewed_basis_flags stays nonzero meanwhile.
BASIS_SIGNATURE_LIST = sorted(BASIS_SIGNATURES)
UNREVIEWED_BASIS_SQL = (
    "SELECT load_id, symbol, timeframe, vendor, kind, n_stored, n_changed, share, signatures, "
    "detail, flagged_at FROM ohlcv_restatement_flag "
    "WHERE reviewed_at IS NULL AND signatures && %s::text[] "
    "ORDER BY flagged_at, symbol, timeframe"
)
_MARK_REVIEWED_SQL = (
    "UPDATE ohlcv_restatement_flag SET reviewed_at = now(), reviewed_by = %s, review_note = %s "
    "WHERE load_id = ANY(%s) AND reviewed_at IS NULL"
)


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
    n_superseded: int = 0


def read_detector_params(cur: Any) -> DetectorParams:
    """The restatement detector's thresholds from config_state; a missing key is loud."""
    cur.execute(
        "SELECT config_key, config_value FROM config_state WHERE config_key = ANY(%s)",
        (list(_DETECTOR_KEYS),),
    )
    values = {key: value for key, value in cur.fetchall()}
    missing = set(_DETECTOR_KEYS) - set(values)
    if missing:
        raise RuntimeError(
            f"restatement detector keys missing from config_state: {sorted(missing)}"
        )
    return DetectorParams(
        flag_share=float(values[FLAG_SHARE_KEY]),
        flag_min_stored=int(float(values[FLAG_MIN_STORED_KEY])),
        signature_min_bars=int(float(values[SIGNATURE_MIN_BARS_KEY])),
        ratio_tolerance=float(values[RATIO_TOLERANCE_KEY]),
        shift_min_share=float(values[SHIFT_MIN_SHARE_KEY]),
        ratio_min_share=float(values[RATIO_MIN_SHARE_KEY]),
        ratio_min_move=float(values[RATIO_MIN_MOVE_KEY]),
        price_tick=float(values[PRICE_TICK_KEY]),
        volume_tolerance=float(values[VOLUME_TOLERANCE_KEY]),
        volume_min_move=float(values[VOLUME_MIN_MOVE_KEY]),
    )


def _utc_date(ts: datetime) -> date:
    return ts.astimezone(UTC).date()


# The lineage note's selection field when selection was deferred (bulk path, vendor unranked).
SELECTION_DEFERRED = "deferred_unranked"


def _lineage_note(lineage: Mapping[str, Any] | None, horizon: datetime | None) -> str | None:
    """The load-detail note a loader's lineage becomes: sorted JSON with the selection horizon
    added (a lineage that already names a horizon is overwritten: the contract's is the one the
    canonical rows were rescaled by). A deferred selection (`horizon` None) records
    `"horizon": null, "selection": "deferred_unranked"`: no selection ran, so no horizon is
    claimed. None without a lineage."""
    if lineage is None:
        return None
    added = (
        {"horizon": None, "selection": SELECTION_DEFERRED}
        if horizon is None
        else {"horizon": horizon.isoformat()}
    )
    return "lineage: " + json.dumps({**lineage, **added}, sort_keys=True)


def _load_params(
    load: SeriesLoad, *, outcome: str, detail: str | None, load_id: uuid.UUID
) -> tuple:
    return (
        load_id,
        load.symbol,
        load.timeframe,
        load.source,
        load.first_bar,
        load.last_bar,
        outcome,
        load.n_bars,
        load.n_new,
        load.n_changed,
        load.first_bar,
        load.last_bar,
        detail,
        load.caller,
        load.destination,
        load.n_unchanged,
        0,
        0,
        load.n_superseded,
    )


def _record_load(
    cur: Any,
    load: SeriesLoad,
    *,
    outcome: str,
    detail: str | None,
    load_id: uuid.UUID,
) -> None:
    cur.execute(
        _INSERT_LOAD_SQL, _load_params(load, outcome=outcome, detail=detail, load_id=load_id)
    )


def _load_detail(
    lineage_note: str | None, restatement: Restatement, n_superseded: int
) -> str | None:
    """The ohlcv_load detail: the lineage note, the restatement flag and the superseded count."""
    notes = [] if lineage_note is None else [lineage_note]
    if restatement.flagged:
        notes.append(f"restatement flagged: {restatement.detail()}")
    if n_superseded:
        notes.append(f"{n_superseded} offers older than the stored answer superseded")
    return "; ".join(notes) or None


def _record_flagged(cur: Any, flag: FlaggedSeries) -> None:
    """Record, count and log one series the restatement detector flagged (written all the same)."""
    series = (flag.symbol, flag.timeframe, flag.vendor, flag.kind)
    record_flag(cur, flag.load_id, series, flag.restatement)
    for signature in flag.restatement.signatures:
        RESTATEMENT_FLAGS.add(1, {"vendor": flag.vendor, "signature": signature})
    logger.warning(
        "ingress.restatement_flagged",
        symbol=flag.symbol,
        timeframe=flag.timeframe,
        vendor=flag.vendor,
        kind=flag.kind,
        load_id=str(flag.load_id),
        detail=flag.restatement.detail(),
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

    detector: DetectorParams
    write: RawWriteParams
    vendor_codes: frozenset[str]
    kind_codes: frozenset[str]
    kind_order: Mapping[str, int]
    policy_rows: tuple[PolicyRow, ...]


@dataclass(frozen=True)
class FlaggedSeries:
    """A series the restatement detector flagged (written all the same, D-191-N)."""

    symbol: str
    timeframe: str
    vendor: str
    kind: str
    load_id: uuid.UUID
    restatement: Restatement


@dataclass(frozen=True)
class IngressResult:
    """What one `apply_raw_contract` call did. Every offered row is written last-wins;
    `new_timestamps` are the timestamps of newly inserted raw rows; `flagged` lists the series
    the restatement detector flagged for review."""

    n_offered: int
    n_new: int
    n_changed: int
    n_unchanged: int
    selected_slots: int
    new_timestamps: tuple[datetime, ...] = ()
    # Slots that reached raw but that no ranked vendor holds (the policy gap a loader must not
    # hide: the offered rows are in raw, canonical has no row for them).
    n_unselected: int = 0
    flagged: tuple[FlaggedSeries, ...] = ()
    # changed offers older than the stored answer: logged as superseded, raw untouched
    n_superseded: int = 0
    # slots whose only candidates are never-selected kinds (iex_rth): reported, never a failure
    n_excluded: int = 0
    # series-chunks whose selection was deferred (bulk path, vendor ranked in no policy row of
    # the timeframe): unselected slots are then counted by ops_selection_gate --compare
    n_selection_deferred: int = 0

    @property
    def n_basis_flagged(self) -> int:
        """Series flagged with a basis-change signature: the run is partial (finding 2)."""
        return sum(1 for flag in self.flagged if flag.restatement.basis_change)


def read_raw_params(cur: Any) -> RawContractParams:
    """Detector thresholds and raw-writer settings from config_state, vocabulary codes from the CVR
    (`bar_vendor`, `bar_kind`) and the whole bar_source_policy; a missing APR key is loud."""
    detector = read_detector_params(cur)
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
        "FROM bar_source_policy_current"
    )
    policy = tuple(PolicyRow(*row) for row in cur.fetchall())
    return RawContractParams(
        detector=detector,
        write=RawWriteParams(
            batch_rows=int(float(values[BATCH_ROWS_KEY])),
            future_tolerance_s=int(float(values[FUTURE_TOLERANCE_KEY])),
        ),
        vendor_codes=vendors,
        kind_codes=frozenset(kinds),
        kind_order=kinds,
        policy_rows=policy,
    )


def record_flag(cur: Any, load_id: uuid.UUID, series: SeriesKey, restatement: Restatement) -> None:
    """Insert one ohlcv_restatement_flag row for a load the detector flagged (the table's one
    INSERT; the retroactive run over a one-time write uses it too)."""
    symbol, timeframe, vendor, kind = series
    cur.execute(
        _INSERT_FLAG_SQL,
        (
            load_id,
            symbol,
            timeframe,
            vendor,
            kind,
            restatement.n_stored,
            restatement.n_changed,
            restatement.share,
            list(restatement.signatures),
            restatement.ratio,
            restatement.shift_bars,
            restatement.detail(),
        ),
    )


def mark_reviewed(cur: Any, load_ids: list[uuid.UUID], *, reviewed_by: str, note: str) -> int:
    """Mark flags reviewed (reviewed_at, reviewed_by and review_note together, migration 485);
    a flag already reviewed keeps its first review. Returns the rows marked."""
    if not reviewed_by.strip() or not note.strip():
        raise ValueError("a review names its reviewer and carries a note")
    cur.execute(_MARK_REVIEWED_SQL, (reviewed_by, note, list(load_ids)))
    return cur.rowcount


def read_unreviewed_basis(cur: Any) -> list[tuple]:
    """Every flag with a basis-change signature that no reviewer has marked."""
    cur.execute(UNREVIEWED_BASIS_SQL, (BASIS_SIGNATURE_LIST,))
    return cur.fetchall()


def _stored_at_offer(rows: list[RawRow], delta: RawDelta) -> dict[datetime, tuple]:
    """The vendor's stored values at the offered keys the load writes or confirms: the old value
    of a replaced row, the offered value of an unchanged one; a new key has none, and a
    superseded offer is left out (it changes nothing in raw)."""
    skip = set(delta.new_timestamps) | set(delta.superseded_timestamps)
    stored: dict[datetime, tuple] = {}
    for row in rows:
        if row.timestamp in delta.changed_old:
            stored[row.timestamp] = tuple(delta.changed_old[row.timestamp])
        elif row.timestamp not in skip:
            stored[row.timestamp] = (row.open, row.high, row.low, row.close, row.volume)
    return stored


def apply_raw_contract(
    conn: Any,
    rows: list[RawRow],
    *,
    caller: str,
    request_id: uuid.UUID,
    answered_at: datetime,
    params: RawContractParams | None = None,
    lineage: Mapping[str, Any] | None = None,
) -> IngressResult:
    """Record one chunk of vendor answers in ohlcv_raw last-wins by serve time, then select
    canonical rows. `answered_at` is when the vendor answered the chunk (module docstring).

    Per (symbol, timeframe, vendor, kind) series, in one transaction on the caller's connection:
    `preview_series` classifies the offer against the vendor's OWN stored raw rows (the counts
    the ohlcv_load row carries before `write_raw` logs revisions under it), the load row is
    written (source = vendor, destination raw, outcome applied), `write_raw` replaces changed
    rows (old values to ohlcv_revision) and inserts new ones, and the restatement detector
    reports the overlap (flagged series are recorded in ohlcv_restatement_flag and logged; the
    write stands). Direct timeframes (1m, 5m, 4h) are then selected over the span touched.

    A cross-vendor difference is never a revision: the vendors are different keys in ohlcv_raw.

    `lineage` (a loader's flat record of what the rows came from: file key, ETag, sha256, ...)
    is written into every load row's detail as one `lineage: {json}` note with the selection
    `horizon` added: the horizon is resolved here once, before the load rows, and handed to the
    selection, so the recorded value is the one the canonical rows were rescaled by.
    """
    if not rows:
        return IngressResult(0, 0, 0, 0, 0)
    horizon = datetime.now(UTC)
    lineage_note = _lineage_note(lineage, horizon)
    with conn.cursor() as cur:
        params = params or read_raw_params(cur)

    by_series: dict[SeriesKey, list[RawRow]] = defaultdict(list)
    for row in rows:
        by_series[(row.symbol, row.timeframe, row.vendor, row.kind)].append(row)

    n_new = n_changed = n_unchanged = n_superseded = 0
    new_timestamps: list[datetime] = []
    flagged: list[FlaggedSeries] = []
    spans: dict[tuple[str, str], list[datetime]] = defaultdict(list)
    for (symbol, timeframe, vendor, kind), series_rows in sorted(by_series.items()):
        stamps = sorted({r.timestamp for r in series_rows})
        # The role may INSERT an ohlcv_load row but not UPDATE it, so the counts are known
        # before the row is written; write_raw (below) then records the same findings.
        delta = preview_series(conn, series_rows, answered_at=answered_at)
        latest = {r.timestamp: r for r in series_rows}
        older = set(delta.superseded_timestamps)
        offered = {
            ts: (r.open, r.high, r.low, r.close, r.volume)
            for ts, r in latest.items()
            if ts not in older
        }
        restatement = detect(
            offered,
            _stored_at_offer(list(latest.values()), delta),
            _BAR.get(timeframe, timedelta(minutes=5)),
            params.detector,
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
            n_superseded=delta.superseded,
        )
        load_id = uuid.uuid4()
        detail = _load_detail(lineage_note, restatement, delta.superseded)
        with conn.cursor() as cur:
            _record_load(cur, load, outcome=OUTCOME_APPLIED, detail=detail, load_id=load_id)
        (written,) = write_raw(
            conn,
            series_rows,
            load_id=load_id,
            request_id=request_id,
            answered_at=answered_at,
            vendor_codes=params.vendor_codes,
            kind_codes=params.kind_codes,
            batch_rows=params.write.batch_rows,
            future_tolerance_s=params.write.future_tolerance_s,
        )
        found = (written.new, written.changed, written.unchanged, written.superseded)
        previewed = (delta.new, delta.changed, delta.unchanged, delta.superseded)
        if found != previewed:
            raise RuntimeError(
                f"raw write disagrees with its preview for {symbol} {timeframe} {vendor} {kind}: "
                f"{found} vs {previewed}"
            )
        if restatement.flagged:
            flag = FlaggedSeries(symbol, timeframe, vendor, kind, load_id, restatement)
            with conn.cursor() as cur:
                _record_flagged(cur, flag)
            flagged.append(flag)
        n_new += delta.new
        n_changed += delta.changed
        n_unchanged += delta.unchanged
        n_superseded += delta.superseded
        new_timestamps.extend(delta.new_timestamps)
        spans[(symbol, timeframe)].extend(stamps)

    selected, unselected, excluded = _select(
        conn,
        {
            key: (min(stamps), max(stamps))
            for key, stamps in spans.items()
            if key[1] in DIRECT_TIMEFRAMES
        },
        params,
        horizon,
    )
    return IngressResult(
        n_offered=len(rows),
        n_new=n_new,
        n_changed=n_changed,
        n_unchanged=n_unchanged,
        selected_slots=selected,
        new_timestamps=tuple(sorted(new_timestamps)),
        n_unselected=unselected,
        flagged=tuple(flagged),
        n_superseded=n_superseded,
        n_excluded=excluded,
    )


def _select(
    conn: Any,
    spans: Mapping[tuple[str, str], tuple[datetime, datetime]],
    params: RawContractParams,
    horizon: datetime,
) -> tuple[int, int, int]:
    """Select canonical rows over each (symbol, timeframe)'s touched span [first, last]; returns
    (selected slots, unselected slots, excluded slots)."""
    selected = unselected = excluded = 0
    for (symbol, timeframe), (first, last) in sorted(spans.items()):
        result = select_and_write(
            conn,
            symbols=[symbol],
            timeframe=timeframe,
            start=first,
            end=last + timedelta(microseconds=1),
            # read under the series' selection lock, never the chunk's cached copy: a policy
            # --reselect commits holding that lock (second review of 191-07, low item)
            policy_rows=None,
            kind_order=params.kind_order,
            batch_rows=params.write.batch_rows,
            horizon=horizon,
        )
        selected += result.new + result.changed
        # A NULL-volume winner is skipped by the writer and leaves the slot's previous canonical
        # row in place: the offered row reached raw and no canonical row took it, so it counts
        # with the unselected slots (191-07 review, low finding).
        unselected += result.unselected + result.skipped_null_volume
        excluded += result.excluded
    return selected, unselected, excluded


# --------------------------------------------------------------------------------------
# Bulk path (docs/plans/2026-11-11-bulk-raw-load-path-design.md, sections 5 and 6)
# --------------------------------------------------------------------------------------

# Whether any open policy row of the timeframe ranks the vendor (the bar-writer role holds
# SELECT on the view). Only a ranked vendor's rows can win, retract or move a session choice.
_VENDOR_RANKED_SQL = (
    "SELECT EXISTS (SELECT 1 FROM bar_source_policy_current WHERE timeframe = %s "
    "AND %s IN (primary_source, fallback_source))"
)


def vendor_is_ranked(cur: Any, timeframe: str, vendor: str) -> bool:
    cur.execute(_VENDOR_RANKED_SQL, (timeframe, vendor))
    return bool(cur.fetchone()[0])


def _batch_restatement(
    classified: Classified, start: int, stop: int, params: DetectorParams
) -> Restatement:
    """The detector over one series-chunk with exactly the row path's inputs (`_stored_at_offer`):
    offered is every non-superseded row, stored the offered values of the unchanged rows plus the
    old values of the replaced ones. A chunk with no replaced row cannot flag (share 0, no
    changed bar; `apply_raw_contract_batch` requires signature_min_bars >= 1), so it gets the
    detector's answer without building the dictionaries."""
    batch = classified.batch
    classes = classified.cls[start:stop]
    n_unchanged = int((classes == CLS_UNCHANGED).sum())
    if not (classes == CLS_REPLACE).any():
        return Restatement(n_unchanged, 0, 0.0, (), None, None, None)
    volumes = batch.rows_volumes(start, stop)
    offered: dict[datetime, tuple] = {}
    stored: dict[datetime, tuple] = {}
    for i, cls in enumerate(classes.tolist(), start):
        if cls == CLS_SUPERSEDED:
            continue
        ts = us_to_datetime(batch.ts_us[i])
        values = (
            float(batch.open[i]),
            float(batch.high[i]),
            float(batch.low[i]),
            float(batch.close[i]),
            volumes[i - start],
        )
        offered[ts] = values
        if cls == CLS_UNCHANGED:
            stored[ts] = values
        elif cls == CLS_REPLACE:
            stored[ts] = classified.replaced_old[i]
    return detect(offered, stored, _BAR.get(batch.timeframe, timedelta(minutes=5)), params)


def apply_raw_contract_batch(
    conn: Any,
    batch: RawBatch,
    *,
    caller: str,
    params: RawContractParams,
    lineage_by_symbol: Mapping[str, Mapping[str, Any]] | None = None,
    request_ids: list[uuid.UUID] | None = None,
) -> IngressResult:
    """`apply_raw_contract` for one `RawBatch`, set-based, in the caller's transaction under the
    bar-writer role: one ohlcv_load row per series-chunk with the same counts, outcome and detail,
    the same revisions, raw rows, restatement flags and, for a ranked vendor, the same selection.

    Selection is deferred when the batch's vendor is ranked in no policy row of a direct
    timeframe: an unranked vendor's rows can neither win a slot nor retract or move a canonical
    row when canonical equals the selection of raw, so the only output selection could have is
    the unselected count, which ops_selection_gate --compare measures instead (design section
    6). `n_selection_deferred` then counts the series-chunks and the lineage note records
    `"horizon": null, "selection": "deferred_unranked"`.

    `lineage_by_symbol` names each symbol's lineage (every symbol of the batch when given);
    `request_ids` one request id per series-chunk (fresh ids by default). `new_timestamps` is
    left empty: the bulk path has no coverage ledger to feed."""
    if len(batch) == 0:
        return IngressResult(0, 0, 0, 0, 0)
    if params.detector.signature_min_bars < 1:
        raise ValueError("the bulk contract needs restatement_signature_min_bars >= 1")
    request_ids = request_ids or [uuid.uuid4() for _ in range(batch.n_keys)]
    load_ids = [uuid.uuid4() for _ in range(batch.n_keys)]
    bounds = batch.key_bounds().tolist()
    direct = batch.timeframe in DIRECT_TIMEFRAMES
    flagged: list[FlaggedSeries] = []
    with conn.cursor() as cur:
        classified = stage_and_classify(cur, batch)  # takes the series locks
        if direct:
            # the policy is read under the selection locks, as select_and_write reads it: a
            # --reselect that ranks this vendor either committed first (seen here, so the batch
            # is selected) or waits for this commit and then selects these rows itself
            lock_selections(cur, batch_symbols(batch), batch.timeframe)
        deferred = direct and not vendor_is_ranked(cur, batch.timeframe, batch.vendor)
        horizon = None if deferred else datetime.now(UTC)
        notes: dict[str, str | None] = {}
        load_rows: list[tuple] = []
        for key, (start, stop) in enumerate(zip(bounds[:-1], bounds[1:], strict=True)):
            symbol = str(batch.symbols[start])
            if symbol not in notes:
                lineage = None if lineage_by_symbol is None else lineage_by_symbol[symbol]
                notes[symbol] = _lineage_note(lineage, horizon)
            n_new, n_unchanged, n_changed, n_superseded = classified.counts[key].tolist()
            restatement = _batch_restatement(classified, start, stop, params.detector)
            load = SeriesLoad(
                symbol=symbol,
                timeframe=batch.timeframe,
                destination=DESTINATION_RAW,
                caller=caller,
                source=batch.vendor,
                n_bars=stop - start,
                n_stored=n_unchanged + n_changed + n_superseded,
                n_new=n_new,
                n_changed=n_changed,
                n_unchanged=n_unchanged,
                first_bar=us_to_datetime(batch.ts_us[start]).date(),
                last_bar=us_to_datetime(batch.ts_us[stop - 1]).date(),
                n_superseded=n_superseded,
            )
            detail = _load_detail(notes[symbol], restatement, n_superseded)
            load_rows.append(
                _load_params(load, outcome=OUTCOME_APPLIED, detail=detail, load_id=load_ids[key])
            )
            if restatement.flagged:
                flagged.append(
                    FlaggedSeries(
                        symbol,
                        batch.timeframe,
                        batch.vendor,
                        batch.kind,
                        load_ids[key],
                        restatement,
                    )
                )
        # the load rows carry the counts before the revisions reference them (foreign key)
        cur.executemany(_INSERT_LOAD_SQL, load_rows)
        write_classified(cur, classified, load_ids=load_ids, request_ids=request_ids)
        for flag in flagged:
            _record_flagged(cur, flag)
    selected = unselected = excluded = 0
    if direct and not deferred:
        # rows are ordered by (symbol, stamp): a symbol's span runs from its first key's first
        # row to its last key's last row
        spans: dict[tuple[str, str], tuple[datetime, datetime]] = {}
        for start, stop in zip(bounds[:-1], bounds[1:], strict=True):
            series = (str(batch.symbols[start]), batch.timeframe)
            first = spans[series][0] if series in spans else us_to_datetime(batch.ts_us[start])
            spans[series] = (first, us_to_datetime(batch.ts_us[stop - 1]))
        assert horizon is not None  # None exactly when deferred
        selected, unselected, excluded = _select(conn, spans, params, horizon)
    n_new, n_unchanged, n_changed, n_superseded = classified.counts.sum(axis=0).tolist()
    return IngressResult(
        n_offered=int(batch.n_offered.sum()),
        n_new=n_new,
        n_changed=n_changed,
        n_unchanged=n_unchanged,
        selected_slots=selected,
        n_unselected=unselected,
        flagged=tuple(flagged),
        n_superseded=n_superseded,
        n_excluded=excluded,
        n_selection_deferred=batch.n_keys if deferred else 0,
    )
