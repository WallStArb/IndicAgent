"""Massive load-check runner (admission design section 8a and section 8 step 6). Read-only.

Stages (``--stages``, default ``A,B``):

- A, systemic and cheap: record sanity (minute and day files), session offset against the NYSE grid
  (seeded draw), publish lag and manifest completeness, survivorship (disclosed, never a gate).
- B, systemic, internal to Massive: day file against minute file per era (decides the 1d kind) and
  volume bands (IBKR against Massive, per era and listing exchange).

Check math lives in ``src/intelligence/bars/massive_load_checks.py`` (pure, unit tested); this
script is the edge: it reads the archive and the manifest, one serial read-only database
connection, and writes per-check CSV and JSON under ``--out``. It never writes to the database.

Determinism and resume: result files carry no wall-clock content; every run records the sha256 of
its inputs (manifest, serve times) in ``inputs.json``; each (check, era) result lands in
``parts/<check>__<era>.json`` and an existing part is reused unless ``--force`` (the part carries
the seed and sample size it was computed under and is recomputed when they differ). The summary
says ``complete`` only when every requested era of every requested stage has a part; otherwise it
says ``partial`` and names what is missing.

Throttle: the runner sleeps through the nightly timer windows (Alpaca 04:40Z, derivation 05:20 and
05:45Z, audit 06:00Z) and for ``--throttle-s`` seconds between files, so it never competes with them.
Logs go to logs/massive_load_checks.log; nothing is logged per row.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import psycopg  # noqa: E402
import structlog  # noqa: E402

from src.config.settings import get_settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.intelligence.bars import massive_load_checks as lc  # noqa: E402
from src.intelligence.bars import massive_name_checks as nc  # noqa: E402
from src.intelligence.bars.daily_rule import RAW_DAILY_SESSION_ZONE, raw_session_date  # noqa: E402
from src.intelligence.bars.sessions import nyse_sessions  # noqa: E402
from src.intelligence.bars.split_rescale import (  # noqa: E402
    SplitFactor,
    SplitRow,
    splits_known_at,
)

setup_service_logging("logs/massive_load_checks.log")
logger = structlog.get_logger("massive_load_checks")

DEFAULT_OUT = Path("logs/massive_load_checks")
DEFAULT_DATA_DIR = Path("data/massive")
DEFAULT_SEED = 20261112
MINUTE, DAY = "minute_aggs_v1", "day_aggs_v1"
_NS = 1_000_000_000
#: Nightly timer windows to sleep through, UTC (start, end): Alpaca 04:40, derivation 05:20 and
#: 05:45, audit 06:00, each with a run allowance.
NIGHTLY_WINDOWS = ((dtime(4, 35), dtime(4, 55)), (dtime(5, 15), dtime(6, 30)))
_READ_COLS = ("ticker", "volume", "open", "high", "low", "close", "window_start")


# ------------------------------------------------------------------------------------ plumbing
def connect_read_only(url: str | None = None) -> psycopg.Connection:
    """A session whose every transaction is read-only. psycopg ignores ``conn.read_only`` in
    autocommit mode, so the server-side default is set at connect time (round 5 finding 6)."""
    return psycopg.connect(
        url or get_settings().database_url,
        autocommit=True,
        options="-c default_transaction_read_only=on",
    )


def in_nightly_window(now: datetime) -> bool:
    t = now.astimezone(UTC).time()
    return any(start <= t < end for start, end in NIGHTLY_WINDOWS)


def wait_out_nightly_window(sleep: Callable[[float], None] = time.sleep) -> None:
    while in_nightly_window(datetime.now(UTC)):
        sleep(60.0)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def write_csv(path: Path, rows: list[Mapping[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


@dataclass(frozen=True)
class Config:
    out: Path
    data_dir: Path
    seed: int
    days_per_era: int
    eras: tuple[int, ...]
    force: bool
    throttle_s: float


def parse_eras(text: str) -> tuple[int, ...]:
    """``2010`` or ``2003-2026`` or ``2010,2015``."""
    out: list[int] = []
    for part in text.split(","):
        if "-" in part:
            lo, hi = part.split("-")
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return tuple(sorted(set(out)))


def day_path(data_dir: Path, dataset: str, day: date) -> Path:
    return data_dir / "files" / dataset / f"{day:%Y}" / f"{day:%m}" / f"{day.isoformat()}.csv.gz"


@dataclass(frozen=True)
class Archive:
    manifest: dict[str, dict[date, dict[str, Any]]]
    servetimes: dict[str, dict[date, tuple[datetime, str, int]]]
    inputs: dict[str, str]


def load_archive(data_dir: Path) -> Archive:
    """Manifest rows (the last row per key wins: a re-download supersedes) and serve times."""
    mdir = data_dir / "manifest"
    manifest: dict[str, dict[date, dict[str, Any]]] = {MINUTE: {}, DAY: {}}
    for line in (mdir / "manifest.jsonl").read_text().splitlines():
        row = json.loads(line)
        stamp = Path(row["key"]).name.removesuffix(".csv.gz")
        manifest[row["dataset"]][date.fromisoformat(stamp)] = row
    serve: dict[str, dict[date, tuple[datetime, str, int]]] = {MINUTE: {}, DAY: {}}
    inputs = {"manifest.jsonl": sha256_file(mdir / "manifest.jsonl")}
    for dataset in (MINUTE, DAY):
        path = mdir / f"servetimes_{dataset}.jsonl"
        inputs[path.name] = sha256_file(path)
        for line in path.read_text().splitlines():
            key, last_modified, etag, size = line.split("\t")
            stamp = Path(key).name.removesuffix(".csv.gz")
            serve[dataset][date.fromisoformat(stamp)] = (
                datetime.fromisoformat(last_modified.replace("Z", "+00:00")),
                etag,
                int(size),
            )
    return Archive(manifest, serve, inputs)


def archive_sessions(archive: Archive) -> list[date]:
    """Every NYSE session between the first and last archived day (the completeness universe)."""
    days = sorted(set(archive.manifest[MINUTE]) | set(archive.manifest[DAY]))
    return sorted(nyse_sessions(days[0], days[-1]))


def _rows_sha256(rows: Any) -> str:
    """Order-independent content hash of a set of small tuples (part keys carry it)."""
    return hashlib.sha256(json.dumps(sorted(map(repr, rows))).encode()).hexdigest()


# --------------------------------------------------------------------------------------- reads
@dataclass(frozen=True)
class RawFile:
    tickers: np.ndarray
    code: np.ndarray
    window_start: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray


def read_raw_file(path: Path) -> RawFile:
    """A flat file's rows as served (no session cut, nothing dropped)."""
    types: dict[str, pa.DataType] = {
        "ticker": pa.string(),
        "volume": pa.float64(),
        "window_start": pa.int64(),
        **{k: pa.float64() for k in ("open", "high", "low", "close")},
    }
    table = pacsv.read_csv(
        path,
        convert_options=pacsv.ConvertOptions(include_columns=list(_READ_COLS), column_types=types),
    )
    names, inverse = np.unique(table["ticker"].to_numpy(zero_copy_only=False), return_inverse=True)
    return RawFile(
        names,
        inverse.astype(np.int64),
        table["window_start"].to_numpy(),
        table["open"].to_numpy(),
        table["high"].to_numpy(),
        table["low"].to_numpy(),
        table["close"].to_numpy(),
        table["volume"].to_numpy(),
    )


def owned_rows(raw: RawFile) -> np.ndarray:
    """Rows whose ticker is a name; an empty ticker string belongs to no instrument."""
    blank_codes = np.flatnonzero(raw.tickers == "")
    owned: np.ndarray = ~np.isin(raw.code, blank_codes)
    return owned


@dataclass(frozen=True)
class SanityScan:
    """One file's sanity counts with the masks they were counted from (reused to list defects)."""

    counts: lc.SanityCounts
    defective: np.ndarray
    owned: np.ndarray


def sanity_of(raw: RawFile) -> SanityScan:
    owned = owned_rows(raw)
    counts, defective = lc.record_sanity(
        raw.code, raw.window_start, raw.open, raw.high, raw.low, raw.close, raw.volume, owned
    )
    return SanityScan(counts, defective, owned)


# ---------------------------------------------------------------------------------- part store
def part_path(cfg: Config, check: str, era: int) -> Path:
    return cfg.out / "parts" / f"{check}__{era}.json"


def key_path(cfg: Config, check: str, era: int) -> Path:
    return cfg.out / "parts" / f"{check}__{era}.key.json"


def write_part(cfg: Config, check: str, era: int, payload: dict[str, Any]) -> None:
    """Write a part and, beside it, its key: a reuse check reads the small sidecar, never the
    part. The sidecar lands last, so a part without its key is never reused."""
    key_path(cfg, check, era).unlink(missing_ok=True)  # no stale key beside a half-written part
    write_json(part_path(cfg, check, era), payload)
    write_json(key_path(cfg, check, era), payload["key"])


def part_current(cfg: Config, check: str, era: int, key: Mapping[str, object]) -> bool:
    """Whether a saved part was computed under this key (the sidecar only)."""
    sidecar = key_path(cfg, check, era)
    if cfg.force or not sidecar.exists() or not part_path(cfg, check, era).exists():
        return False
    return bool(json.loads(sidecar.read_text()) == json.loads(json.dumps(key)))


def all_parts(
    cfg: Config, check: str, key: Mapping[str, object] | None = None
) -> dict[int, dict[str, Any]]:
    """The saved parts of the requested eras. With ``key`` (one key for every era) the key embedded
    in each part is compared too, besides the sidecar a reuse check reads."""
    out: dict[int, dict[str, Any]] = {}
    for era in cfg.eras:
        path = part_path(cfg, check, era)
        if path.exists():
            part = json.loads(path.read_text())
            if key is not None and part.get("key") != json.loads(json.dumps(key)):
                raise RuntimeError(f"{path} was computed under another key: rerun its stage")
            out[era] = part
    return out


#: Bumped when a check rule changes, so saved parts computed under the old rule are recomputed.
LOGIC_VERSION = "2026-11-13-r5h"


_RAW_FINGERPRINT_SQL = """
SELECT vendor, kind, timeframe, count(*), max(served_at) FROM ohlcv_raw
WHERE "timestamp" >= %s AND "timestamp" < %s
  AND (vendor || '|' || kind || '|' || timeframe) = ANY(%s) GROUP BY 1, 2, 3
"""
_REVISION_FINGERPRINT_SQL = """
SELECT date_part('year', "timestamp" AT TIME ZONE 'UTC')::int, vendor, kind, timeframe, count(*)
FROM ohlcv_revision WHERE "timestamp" >= %s AND "timestamp" < %s
  AND (vendor || '|' || kind || '|' || timeframe) = ANY(%s) GROUP BY 1, 2, 3, 4
"""


def raw_fingerprints(
    conn: psycopg.Connection,
    eras: Iterable[int],
    series: Iterable[tuple[str, str, str]],
) -> dict[int, dict[str, str]]:
    """Per era, per ``vendor|kind|timeframe``: ``rows|latest served_at|revision rows`` (round 5
    rule 7). A reload or extension moves the count; a restatement that keeps the count moves the
    served stamp and the revision-log count. Computed once per invocation (the revision log is read
    in one pass over every requested era), read only for the ``series`` the requested stages read,
    and scoped again by each check to its own."""
    eras = sorted(set(eras))
    wanted = sorted("|".join(s) for s in series)
    if not eras or not wanted:
        return {}
    out: dict[int, dict[str, str]] = {era: {} for era in eras}
    wait_out_nightly_window()
    with conn.cursor() as cur:
        cur.execute(
            _REVISION_FINGERPRINT_SQL,
            (datetime(eras[0], 1, 1, tzinfo=UTC), datetime(eras[-1] + 1, 1, 1, tzinfo=UTC), wanted),
        )
        revisions = {(e, f"{v}|{k}|{t}"): int(n) for e, v, k, t, n in cur.fetchall()}
        for era in eras:
            wait_out_nightly_window()
            cur.execute(
                _RAW_FINGERPRINT_SQL,
                (datetime(era, 1, 1, tzinfo=UTC), datetime(era + 1, 1, 1, tzinfo=UTC), wanted),
            )
            for v, k, t, n, served in cur.fetchall():
                series = f"{v}|{k}|{t}"
                stamp = served.isoformat() if served is not None else ""
                out[era][series] = f"{n}|{stamp}|{revisions.get((era, series), 0)}"
    return out


def scoped_fingerprint(
    fingerprint: Mapping[str, str], series: Iterable[tuple[str, str, str]]
) -> dict[str, str]:
    """The fingerprint entries of the (vendor, kind, timeframe) series a check reads."""
    wanted = {"|".join(s) for s in series}
    return {k: v for k, v in sorted(fingerprint.items()) if k in wanted}


def sample_key(
    cfg: Config,
    inputs: Mapping[str, str] | None = None,
    raw: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """The identity of a saved part: sampling, rule version and the inputs it was computed over
    (the archive file hashes for file checks, the era's raw fingerprint for database checks)."""
    key: dict[str, object] = {
        "seed": cfg.seed,
        "days_per_era": cfg.days_per_era,
        "logic": LOGIC_VERSION,
    }
    if inputs is not None:
        key["archive_inputs"] = dict(sorted(inputs.items()))
    if raw is not None:
        key["raw_fingerprint"] = dict(sorted(raw.items()))
    return key


# ------------------------------------------------------------------------------ stage A: scans
def provenance(cfg: Config, inputs: Mapping[str, str], *, frozen: bool) -> dict[str, Any]:
    """What a stage result file was computed under; stage C refuses a file that does not carry
    the current one (round 5 second review, finding 7)."""
    out: dict[str, Any] = {
        "logic": LOGIC_VERSION,
        "seed": cfg.seed,
        "days_per_era": cfg.days_per_era,
        "archive_inputs": dict(sorted(inputs.items())),
        "eras": list(cfg.eras),
    }
    if frozen:
        out["frozen"] = frozen_hashes(cfg)
    return out


def draw_days(cfg: Config, archive: Archive, sessions: list[date]) -> list[date]:
    """The seeded draw over sessions that have both files, for the requested eras."""
    held = [d for d in sessions if d in archive.manifest[MINUTE] and d in archive.manifest[DAY]]
    held = [d for d in held if lc.era_of(d) in cfg.eras]
    if not held:
        raise lc.VacuousCheckError("draw_days: no session with both files in the requested eras")
    bounds = nyse_sessions(held[0], held[-1])
    return lc.seeded_session_draw(
        held,
        per_era=cfg.days_per_era,
        seed=cfg.seed,
        early_closes=lc.early_close_sessions({d: bounds[d] for d in held}),
        post_dst=lc.post_dst_sessions(held),
    )


DEFECT_LIST_CAP = 500  # defective rows listed per era and file kind; the counts are exact
UNOWNED_LIST_CAP = 50


@dataclass
class DefectLog:
    """Defects of one era: the gap-list keys of EVERY named defective bar (a set), the first
    ``DEFECT_LIST_CAP`` named rows and ``UNOWNED_LIST_CAP`` unowned rows as dicts for the report.
    Rows beyond the caps are counted and keyed, never materialized."""

    gap: set[str] = field(default_factory=set)
    named: list[dict[str, Any]] = field(default_factory=list)
    unowned: list[dict[str, Any]] = field(default_factory=list)
    n_named: int = 0
    _listed: Counter[tuple[str, str]] = field(default_factory=Counter)  # (list, file kind) rows

    def add(
        self, day: date, raw: RawFile, scan: SanityScan, open_ns: int, close_ns: int, file_kind: str
    ) -> None:
        """An owned defect is a gap-list item for its bar; an unowned row belongs to no
        instrument and is listed only."""
        bad = np.flatnonzero(scan.defective)
        owned_idx, unowned_idx = bad[scan.owned[bad]], bad[~scan.owned[bad]]
        self.n_named += len(owned_idx)
        self.gap.update(
            f"{raw.tickers[code]}|{day.isoformat()}|defective_bar"
            for code in np.unique(raw.code[owned_idx])
        )
        for idx, rows, cap, which in (
            (owned_idx, self.named, DEFECT_LIST_CAP, "named"),
            (unowned_idx, self.unowned, UNOWNED_LIST_CAP, "unowned"),
        ):
            room = max(0, cap - self._listed[(which, file_kind)])  # the cap is per file kind
            self._listed[(which, file_kind)] += min(room, len(idx))
            for i in idx[:room]:
                rows.append(
                    {
                        "day": day.isoformat(),
                        "ticker": str(raw.tickers[raw.code[i]]),
                        "window_start_ns": int(raw.window_start[i]),
                        "open": float(raw.open[i]),
                        "high": float(raw.high[i]),
                        "low": float(raw.low[i]),
                        "close": float(raw.close[i]),
                        "volume": float(raw.volume[i]),
                        # a day file has no session: null, not False
                        "in_rth": (
                            bool(open_ns <= raw.window_start[i] < close_ns)
                            if file_kind == "minute"
                            else None
                        ),
                        "file_kind": file_kind,
                    }
                )


def run_record_sanity_and_session(
    cfg: Config, archive: Archive, sessions: list[date], drawn: list[date], era: int
) -> None:
    """Stage A scans of one era: day-file sanity over EVERY day file of the era, minute-file
    sanity and the session offset over the era's drawn days."""
    key = sample_key(cfg, archive.inputs)
    if all(part_current(cfg, c, era, key) for c in ("record_sanity", "session")):
        logger.info("era_reused", check="stage_a_scans", era=era)
        return
    t0 = time.monotonic()
    day_counts: lc.SanityCounts | None = None
    n_day_files = 0
    log = DefectLog()
    for day in (d for d in sessions if lc.era_of(d) == era and d in archive.manifest[DAY]):
        wait_out_nightly_window()
        raw = read_raw_file(day_path(cfg.data_dir, DAY, day))
        scan = sanity_of(raw)
        day_counts = scan.counts if day_counts is None else day_counts + scan.counts
        log.add(day, raw, scan, 0, 0, "day")
        n_day_files += 1
        time.sleep(cfg.throttle_s)
    minute_counts: lc.SanityCounts | None = None
    session_rows: list[lc.SessionDayResult] = []
    era_days = [d for d in drawn if lc.era_of(d) == era]
    bounds = nyse_sessions(era_days[0], era_days[-1]) if era_days else {}
    for day in era_days:
        wait_out_nightly_window()
        raw = read_raw_file(day_path(cfg.data_dir, MINUTE, day))
        scan = sanity_of(raw)
        minute_counts = scan.counts if minute_counts is None else minute_counts + scan.counts
        open_dt, close_dt = bounds[day]
        open_ns, close_ns = int(open_dt.timestamp()) * _NS, int(close_dt.timestamp()) * _NS
        log.add(day, raw, scan, open_ns, close_ns, "minute")
        session_rows.append(
            lc.session_day_result(day, raw.window_start, raw.volume, open_ns, close_ns)
        )
        time.sleep(cfg.throttle_s)
    if day_counts is None or minute_counts is None:
        raise lc.VacuousCheckError(f"era {era}: no day file or no drawn minute file scanned")
    write_part(
        cfg,
        "record_sanity",
        era,
        {
            "key": key,
            "era": era,
            "day_files": {
                **asdict(day_counts),
                "n_files": n_day_files,
                "verdict": lc.sanity_verdict(day_counts),
            },
            "minute_files": {
                **asdict(minute_counts),
                "n_files": len(era_days),
                "verdict": lc.sanity_verdict(minute_counts),
            },
            "named_defects": log.named,  # the displayed listing only (capped)
            "n_named_defects": log.n_named,
            # the gap list is built from every named defect, never from the capped listing
            "named_gap_keys": sorted(log.gap),
            "unowned_rows": log.unowned,
        },
    )
    write_part(
        cfg,
        "session",
        era,
        {
            "key": key,
            "era": era,
            "days": [
                {
                    "day": r.day,
                    "open_offset_min": r.open_offset_min,
                    "close_offset_min": r.close_offset_min,
                    "passed": r.passed,
                }
                for r in session_rows
            ],
        },
    )
    logger.info(
        "era_scanned", check="stage_a_scans", era=era, seconds=round(time.monotonic() - t0, 1)
    )


def run_publish_and_manifest(cfg: Config, archive: Archive, sessions: list[date]) -> None:
    """Publish lag of the last 20 sessions and manifest completeness (no file reads)."""
    last = [d for d in sessions if d in archive.servetimes[MINUTE]][-lc.PUBLISH_LAG_SESSIONS :]
    bounds = nyse_sessions(last[0], last[-1])
    rows = []
    for dataset in (MINUTE, DAY):
        for day in last:
            if day not in archive.servetimes[dataset]:
                continue
            lag = lc.publish_lag_hours(archive.servetimes[dataset][day][0], bounds[day][1])
            rows.append({"dataset": dataset, "day": day.isoformat(), "lag_hours": round(lag, 3)})
    if not rows:
        raise lc.VacuousCheckError("publish lag: no serve time for the last sessions")
    write_csv(cfg.out / "stageA_publish_lag.csv", rows, ["dataset", "day", "lag_hours"])
    completeness = lc.manifest_completeness(sessions, archive.manifest)
    write_json(cfg.out / "stageA_manifest_completeness.json", completeness)


_HELD_SQL = """SELECT symbol, min("timestamp")::date, max("timestamp")::date
FROM ohlcv_raw WHERE timeframe = '1d' AND vendor = 'massive' AND kind = 'sip_flat'
GROUP BY symbol"""
_PRESENCE_SQL = """SELECT EXTRACT(year FROM "timestamp")::int AS era, count(DISTINCT symbol)
FROM ohlcv_raw WHERE timeframe = '1d' AND vendor = 'massive' AND kind = 'sip_flat'
GROUP BY 1 ORDER BY 1"""
_ACTIVE_SQL = "SELECT symbol FROM instruments WHERE is_active ORDER BY symbol"
_LISTING_END_SQL = "SELECT symbol, last_session FROM listing_end_current"


def run_survivorship(cfg: Config, archive: Archive, conn: psycopg.Connection) -> dict[str, Any]:
    """Presence by era (names with a held 1d Massive bar per era) and each instrument's first and
    last Massive 1d bar against its recorded listing end. Disclosed, never a gate."""
    wait_out_nightly_window()
    with conn.cursor() as cur:
        cur.execute(_HELD_SQL)
        held = {s: (a, b) for s, a, b in cur.fetchall()}
        cur.execute(_PRESENCE_SQL)
        presence = {int(e): int(n) for e, n in cur.fetchall()}
        cur.execute(_ACTIVE_SQL)
        active = [s for (s,) in cur.fetchall()]
        cur.execute(_LISTING_END_SQL)
        listing_end = {s: d for s, d in cur.fetchall()}
    archive_end = max(archive.manifest[DAY])
    rows = []
    for symbol in sorted(set(active) | set(listing_end)):
        first, last = held.get(symbol, (None, None))
        rows.append(
            {
                "symbol": symbol,
                "first_bar": first,
                "last_bar": last,
                "listing_end": listing_end.get(symbol),
                "reading": lc.survivorship_reading(
                    first, last, listing_end.get(symbol), archive_end
                ),
            }
        )
    write_csv(
        cfg.out / "stageA_survivorship.csv",
        rows,
        ["symbol", "first_bar", "last_bar", "listing_end", "reading"],
    )
    summary = {
        "presence_by_era": presence,
        "readings": lc.count_by(str(r["reading"]) for r in rows),
        "n_names": len(rows),
        "missing_names": [r["symbol"] for r in rows if r["reading"] == "absent"],
    }
    write_json(cfg.out / "stageA_survivorship_summary.json", summary)
    return summary


# ---------------------------------------------------------------------------- stage A: verdicts
def assemble_stage_a(cfg: Config, inputs: Mapping[str, str]) -> dict[str, Any]:
    """Fold the saved parts into the stage A result files and verdicts."""
    key = sample_key(cfg, inputs)
    sanity = all_parts(cfg, "record_sanity", key)
    session = all_parts(cfg, "session", key)
    if not sanity or not session:
        raise lc.VacuousCheckError("assemble_stage_a: no era part saved")
    san_rows = []
    for era, part in sorted(sanity.items()):
        for kind in ("day_files", "minute_files"):
            san_rows.append({"era": era, "file_kind": kind, **part[kind]})
    fields = [
        "era",
        "file_kind",
        "n_files",
        "n_rows",
        "n_ohlc_inconsistent",
        "n_nonpositive_price",
        "n_negative_volume",
        "n_duplicate_keys",
        "n_defective_rows",
        "n_unowned_rows",
        "n_unowned_defective",
        "verdict",
    ]
    write_csv(cfg.out / "stageA_record_sanity.csv", san_rows, fields)
    results = [
        lc.SessionDayResult(
            date.fromisoformat(d["day"]), era, d["open_offset_min"], d["close_offset_min"]
        )
        for era, part in sorted(session.items())
        for d in part["days"]
    ]
    write_csv(
        cfg.out / "stageA_session.csv",
        [
            {
                "day": r.day.isoformat(),
                "era": r.era,
                "open_offset_min": r.open_offset_min,
                "close_offset_min": r.close_offset_min,
                "passed": r.passed,
            }
            for r in results
        ],
        ["day", "era", "open_offset_min", "close_offset_min", "passed"],
    )
    row_fields = [
        "era",
        "file_kind",
        "day",
        "ticker",
        "window_start_ns",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "in_rth",
    ]
    named = [
        {"era": era, **row} for era, part in sorted(sanity.items()) for row in part["named_defects"]
    ]
    write_csv(cfg.out / "stageA_named_defects.csv", named, row_fields)
    write_csv(
        cfg.out / "stageA_unowned_rows.csv",
        [{"era": e, **r} for e, part in sorted(sanity.items()) for r in part["unowned_rows"]],
        row_fields,
    )
    # a named-instrument defect is a gap-list item for its bar's day, never a stop by itself
    gap = sorted({key for part in sanity.values() for key in part["named_gap_keys"]})
    write_json(cfg.out / "stageA_gap_list_additions.json", gap)
    by_era = lc.session_verdict_by_era(results)
    write_json(cfg.out / "stageA_session_verdict.json", by_era)
    stops: dict[str, list[str]] = {}
    for era, v in by_era.items():
        if v["verdict"] == "stop":
            stops.setdefault(str(era), []).append("session")
    for r in san_rows:
        if r["verdict"] == "stop":
            stops.setdefault(str(r["era"]), []).append("record_sanity")
    write_json(
        cfg.out / "stageA_systemic.json",
        {"provenance": provenance(cfg, inputs, frozen=False), "stop_eras": stops},
    )
    total = lambda f: sum(r[f] for r in san_rows)  # noqa: E731
    return {
        "record_sanity_owned_rows": total("n_rows"),
        "record_sanity_owned_defective_rows": total("n_defective_rows"),
        "record_sanity_unowned_rows": total("n_unowned_rows"),
        "record_sanity_unowned_defective_rows": total("n_unowned_defective"),
        "record_sanity_gap_list_bars": len(gap),
        "record_sanity": "stop" if any(r["verdict"] == "stop" for r in san_rows) else "ok",
        "session": "stop" if any(v["verdict"] == "stop" for v in by_era.values()) else "ok",
        "eras_with_parts": sorted(sanity),
    }


# --------------------------------------------------------------------------- frozen inputs
#: The corporate-action list and the ticker-as-of map are frozen and hashed BEFORE any comparison
#: that uses them (design 8a, identity and adjustment factor): the files below are written once,
#: their sha256 recorded in frozen/frozen.json, and every later run reads the files, never the
#: database tables again. A frozen file whose hash no longer matches its record stops the run.
_CA_SQL = """
SELECT symbol, effective_date, factor, recorded_at, inferred_by, (detail ? 'rows_file'),
       (SELECT string_agg((route->>'vendor') || '/' || (route->>'kind'), ';'
                          ORDER BY route->>'vendor', route->>'kind')
        FROM jsonb_array_elements(COALESCE(detail->'unadjusted_routes', '[]'::jsonb)) AS route)
FROM corporate_action_current WHERE action_type IN ('split', 'reverse_split')
ORDER BY symbol, effective_date, recorded_at, action_id
"""
_SPAN_SQL = """
SELECT symbol, ticker, valid_from, valid_to FROM ticker_event_current
ORDER BY symbol, valid_from, ticker
"""
_CA_FIELDS = [
    "symbol",
    "effective_date",
    "factor",
    "recorded_at",
    "inferred_by",
    "rows_file",
    "market_fact",
    "unadjusted_routes",
]
_SPAN_FIELDS = ["symbol", "ticker", "valid_from", "valid_to"]


#: The layout of the frozen record and its CSV columns; a record of another version is refused.
FREEZE_VERSION = 2


def read_frozen_record(cfg: Config) -> dict[str, Any]:
    """The frozen record, refused when it is of another freeze version."""
    path = cfg.out / "frozen" / "frozen.json"
    record: dict[str, Any] = json.loads(path.read_text())
    if record.get("freeze_version") != FREEZE_VERSION:
        raise RuntimeError(
            f"{path} is freeze version {record.get('freeze_version')!r}, need {FREEZE_VERSION}: "
            "refreeze in a new --out"
        )
    return record


def freeze_inputs(cfg: Config, conn: psycopg.Connection) -> dict[str, Any]:
    """Write (once) and verify the frozen corporate-action list and ticker-as-of map."""
    from src.intelligence.bars.corporate_actions import is_market_split  # noqa: PLC0415

    fdir = cfg.out / "frozen"
    record_path = fdir / "frozen.json"
    ca_path, span_path = fdir / "corporate_actions.csv", fdir / "ticker_spans.csv"
    if record_path.exists():
        record = read_frozen_record(cfg)
        for path in (ca_path, span_path):
            if sha256_file(path) != record["sha256"][path.name]:
                raise RuntimeError(f"frozen input {path} no longer matches its recorded hash")
        return record
    with conn.cursor() as cur:
        cur.execute(_CA_SQL)
        ca_rows = [
            {
                "symbol": s,
                "effective_date": d,
                "factor": repr(f),
                "recorded_at": r.isoformat(),
                "inferred_by": by,
                "rows_file": rf,
                "market_fact": is_market_split(by, operator_rows_file=rf),
                "unadjusted_routes": routes or "",
            }
            for s, d, f, r, by, rf, routes in cur.fetchall()
        ]
        cur.execute(_SPAN_SQL)
        span_rows = [
            {"symbol": s, "ticker": t, "valid_from": a, "valid_to": b}
            for s, t, a, b in cur.fetchall()
        ]
    if not ca_rows or not span_rows:
        raise lc.VacuousCheckError("freeze_inputs: no corporate action or no ticker span row")
    write_csv(ca_path, ca_rows, _CA_FIELDS)
    write_csv(span_path, span_rows, _SPAN_FIELDS)
    horizon = datetime.now(UTC).isoformat()
    record = {
        "freeze_version": FREEZE_VERSION,
        "sha256": {ca_path.name: sha256_file(ca_path), span_path.name: sha256_file(span_path)},
        "n_corporate_actions": len(ca_rows),
        "n_ticker_spans": len(span_rows),
        # the splits horizon decides which frozen splits rescale, so it is part of the frozen
        # record that part keys carry (round 5 finding 7); frozen_at.txt is an unhashed note only
        "horizon": horizon,
    }
    (fdir / "frozen_at.txt").write_text(horizon + "\n")
    write_json(record_path, record)
    logger.info("inputs_frozen", **record)
    return record


def frozen_hashes(cfg: Config) -> dict[str, Any]:
    """The frozen record (version, file hashes and splits horizon) a part key carries."""
    record = read_frozen_record(cfg)
    return {k: record[k] for k in ("freeze_version", "sha256", "horizon")}


#: The incumbent 1d series the calendar audit names unadjusted (daily_rule.RESCALABLE_SERIES).
IBKR_RESCALED_SERIES = "ibkr/smart_trades"


@dataclass(frozen=True)
class Frozen:
    """Everything the checks read from the frozen record: the market splits Massive is divided by,
    the calendar-audit rescales of the IBKR 1d series (rule 7) and the ticker-as-of spans."""

    splits: dict[str, list[SplitFactor]]
    ibkr_rescales: dict[str, list[SplitFactor]]
    spans: dict[str, list[tuple[date, date | None]]]

    def span_listed(self, name: str, era: int) -> bool:
        """The frozen ticker spans overlap the era (``valid_to`` is exclusive)."""
        start, end = date(era, 1, 1), date(era, 12, 31)
        return any(a <= end and (b is None or b > start) for a, b in self.spans.get(name, []))

    def ibkr_scale(self, name: str, days: np.ndarray) -> np.ndarray:
        """The cumulative factor the IBKR 1d series is divided by on each session (prices) and
        multiplied by (volume): the one rule 7 helper stage C prices and volume bands share."""
        return lc.split_scale_for_days(days, self.ibkr_rescales.get(name, []))


def load_frozen(cfg: Config) -> Frozen:
    """One parse of the frozen record and both CSVs. The horizon is the freeze time: a split not
    yet executed then never rescales."""
    horizon = datetime.fromisoformat(read_frozen_record(cfg)["horizon"])
    market: dict[str, list[SplitRow]] = {}
    audit: dict[str, list[SplitRow]] = {}
    with (cfg.out / "frozen" / "corporate_actions.csv").open() as handle:
        for row in csv.DictReader(handle):
            base = (
                date.fromisoformat(row["effective_date"]),
                float(row["factor"]),
                datetime.fromisoformat(row["recorded_at"]),
            )
            market.setdefault(row["symbol"], []).append(
                SplitRow(*base, row["market_fact"] == "True")
            )
            if IBKR_RESCALED_SERIES in row["unadjusted_routes"].split(";"):
                # a calendar-audit row rescales the incumbent route whether or not it records the
                # market's split (an operator route correction is a fact about the incumbent)
                audit.setdefault(row["symbol"], []).append(SplitRow(*base, True))
    spans: dict[str, list[tuple[date, date | None]]] = {}
    with (cfg.out / "frozen" / "ticker_spans.csv").open() as handle:
        for row in csv.DictReader(handle):
            end = date.fromisoformat(row["valid_to"]) if row["valid_to"] else None
            spans.setdefault(row["symbol"], []).append((date.fromisoformat(row["valid_from"]), end))
    return Frozen(
        {s: splits_known_at(r, horizon) for s, r in market.items()},
        {s: splits_known_at(r, horizon) for s, r in audit.items()},
        spans,
    )


def rescaled_bars(bars: Bars, scale: np.ndarray) -> Bars:
    """A series carried onto the split-adjusted basis: prices divided by the per-session
    ``scale`` (``Frozen.ibkr_scale``, the one rule 7 factor)."""
    ohlc = tuple(a / scale for a in bars.ohlc)
    return Bars(bars.t_ns, bars.key, ohlc, bars.volume, bars.served_min, bars.served_max)


# ------------------------------------------------------------- stage B: day against minute
def day_file_by_ticker(raw: RawFile) -> dict[str, tuple[float, float, float, float, float]]:
    return {
        str(t): (float(o), float(h), float(low), float(c), float(v))
        for t, o, h, low, c, v in zip(
            raw.tickers[raw.code], raw.open, raw.high, raw.low, raw.close, raw.volume, strict=True
        )
    }


def run_day_vs_minute(cfg: Config, archive: Archive, drawn: list[date], era: int) -> None:
    key = sample_key(cfg, archive.inputs)
    if part_current(cfg, "day_vs_minute", era, key):
        return
    era_days = [d for d in drawn if lc.era_of(d) == era]
    if not era_days:
        raise lc.VacuousCheckError(f"day_vs_minute: era {era} has no drawn day")
    bounds = nyse_sessions(era_days[0], era_days[-1])
    rows: list[dict[str, Any]] = []
    for day in era_days:
        wait_out_nightly_window()
        minute = read_raw_file(day_path(cfg.data_dir, MINUTE, day))
        day_raw = read_raw_file(day_path(cfg.data_dir, DAY, day))
        open_dt, close_dt = bounds[day]
        rth = (minute.window_start >= int(open_dt.timestamp()) * _NS) & (
            minute.window_start < int(close_dt.timestamp()) * _NS
        )
        day_rows = day_file_by_ticker(day_raw)
        for basis, mask in (("rth", rth), ("all_hours", np.ones(len(rth), dtype=bool))):
            agg = lc.aggregate_by_ticker(
                minute.tickers,
                minute.code,
                minute.window_start,
                minute.open,
                minute.high,
                minute.low,
                minute.close,
                minute.volume,
                mask,
            )
            counts = lc.compare_day_to_minutes(day_rows, agg)
            rows.append({"day": day.isoformat(), "basis": basis, **asdict(counts)})
        time.sleep(cfg.throttle_s)
    write_part(cfg, "day_vs_minute", era, {"key": key, "era": era, "rows": rows})
    logger.info("era_scanned", check="day_vs_minute", era=era, days=len(era_days))


def assemble_day_vs_minute(cfg: Config, inputs: Mapping[str, str]) -> dict[str, Any]:
    parts = all_parts(cfg, "day_vs_minute", sample_key(cfg, inputs))
    if not parts:
        raise lc.VacuousCheckError("assemble_day_vs_minute: no era part saved")
    count_fields = [f for f in lc.DayVsMinuteCounts.__dataclass_fields__]
    csv_rows: list[dict[str, Any]] = []
    totals: dict[tuple[int, str], lc.DayVsMinuteCounts] = {}
    for era, part in sorted(parts.items()):
        for row in part["rows"]:
            counts = lc.DayVsMinuteCounts(**{f: row[f] for f in count_fields})
            k = (era, row["basis"])
            totals[k] = totals[k] + counts if k in totals else counts
    for (era, basis), counts in sorted(totals.items()):
        csv_rows.append(
            {
                "era": era,
                "basis": basis,
                **asdict(counts),
                "close_mismatch_share": counts.mismatch_close / counts.n_names,
            }
        )
    write_csv(
        cfg.out / "stageB_day_vs_minute.csv",
        csv_rows,
        ["era", "basis", *count_fields, "close_mismatch_share"],
    )
    verdict = lc.day_vs_minute_verdict({e: c for (e, b), c in totals.items() if b == "rth"})
    write_json(cfg.out / "stageB_day_vs_minute_verdict.json", verdict)
    return verdict


# -------------------------------------------------------------------- stage B: volume bands
_VOL_SQL = """
SELECT symbol, "timestamp", volume FROM ohlcv_raw
WHERE timeframe = '1d' AND vendor = %s AND kind = %s AND volume > 0
  AND "timestamp" >= %s AND "timestamp" < %s
ORDER BY symbol, "timestamp"
"""
_EXCHANGE_SQL = """
SELECT DISTINCT ON (request_key) replace(request_key, '@active', ''),
       body->'results'->>'primary_exchange'
FROM reference_raw WHERE vendor = 'massive' AND endpoint = 'overview'
  AND request_key LIKE '%%@active'
ORDER BY request_key, served_at DESC, reference_raw_id DESC
"""
UNKNOWN_EXCHANGE = "UNKNOWN"


VOLUME_SERIES = (("ibkr", "smart_trades", "1d"), ("massive", "sip_flat", "1d"))


@dataclass(frozen=True)
class ExchangeMap:
    """The latest Massive overview capture per ticker, read and hashed once per invocation."""

    by_symbol: dict[str, str]
    sha256: str


def load_exchange_map(conn: psycopg.Connection) -> ExchangeMap:
    wait_out_nightly_window()
    with conn.cursor() as cur:
        cur.execute(_EXCHANGE_SQL)
        by_symbol = {s: (e or UNKNOWN_EXCHANGE) for s, e in cur.fetchall()}
    return ExchangeMap(by_symbol, _rows_sha256(by_symbol.items()))


def run_volume_bands(
    cfg: Config,
    conn: psycopg.Connection,
    frozen: Frozen,
    era: int,
    fingerprint: Mapping[str, str],
    exchange: ExchangeMap,
) -> None:
    """Per name-era median of IBKR (smart_trades) over Massive (sip_flat) 1d volume, the Massive
    volume carried to IBKR's split-adjusted basis by the FROZEN splits and the IBKR volume carried
    by the calendar-audit rescale of the same series (rule 7, the factor stage C divides IBKR
    prices by). Only sessions where both traded count; a name with none is counted unmatched."""
    key = {
        **sample_key(cfg, raw=scoped_fingerprint(fingerprint, VOLUME_SERIES)),
        "frozen": frozen_hashes(cfg),
        "exchange_map_sha256": exchange.sha256,
    }
    if part_current(cfg, "volume_bands", era, key):
        return
    start, end = datetime(era, 1, 1, tzinfo=UTC), datetime(era + 1, 1, 1, tzinfo=UTC)
    series: dict[str, dict[str, dict[date, float]]] = {"ibkr": {}, "massive": {}}
    with conn.cursor() as cur:
        for vendor, kind in (("ibkr", "smart_trades"), ("massive", "sip_flat")):
            wait_out_nightly_window()
            cur.execute(_VOL_SQL, (vendor, kind, start, end))
            for symbol, stamp, volume in cur.fetchall():
                day = raw_session_date(vendor, kind, stamp)
                series[vendor].setdefault(symbol, {})[day] = float(volume)
    ratios: dict[str, dict[str, float]] = {}
    unmatched: list[str] = []
    for symbol, massive in sorted(series["massive"].items()):
        ibkr = series["ibkr"].get(symbol, {})
        common = sorted(set(massive) & set(ibkr))
        if not common:
            unmatched.append(symbol)
            continue
        days = np.array(common, dtype="datetime64[D]")
        scale = lc.split_scale_for_days(days, frozen.splits.get(symbol, []))
        ibkr_volume = np.array([ibkr[d] for d in common]) * frozen.ibkr_scale(symbol, days)
        ratio = ibkr_volume / (np.array([massive[d] for d in common]) * scale)
        ratios.setdefault(exchange.by_symbol.get(symbol, UNKNOWN_EXCHANGE), {})[symbol] = float(
            np.median(ratio)
        )
    if not ratios:
        raise lc.VacuousCheckError(f"volume_bands: era {era} matched no name")
    write_part(
        cfg,
        "volume_bands",
        era,
        {
            "key": key,
            "era": era,
            "ratios": ratios,
            "unmatched": unmatched,
            "n_massive_names": len(series["massive"]),
        },
    )
    logger.info("era_scanned", check="volume_bands", era=era, names=sum(map(len, ratios.values())))


def assemble_volume_bands(cfg: Config, inputs: Mapping[str, str]) -> dict[str, Any]:
    parts = all_parts(cfg, "volume_bands")
    if not parts:
        raise lc.VacuousCheckError("assemble_volume_bands: no era part saved")
    cells = {(era, ex): r for era, part in parts.items() for ex, r in part["ratios"].items()}
    rows = lc.volume_bands(cells)
    write_csv(
        cfg.out / "stageB_volume_bands.csv",
        [asdict(r) for r in rows],
        list(lc.VolumeBandRow.__dataclass_fields__),
    )
    exchanges = sorted({r.exchange for r in rows})
    by_era = {r.era: {} for r in rows}
    for r in rows:
        by_era[r.era][r.exchange] = round(r.median_ratio, 4)
    write_csv(
        cfg.out / "stageB_volume_ratio_by_era.csv",
        [
            {"era": era, **{ex: by_era[era].get(ex, "") for ex in exchanges}}
            for era in sorted(by_era)
        ],
        ["era", *exchanges],
    )
    unmatched = {era: len(p["unmatched"]) for era, p in sorted(parts.items())}
    write_json(cfg.out / "stageB_volume_unmatched.json", unmatched)
    write_json(
        cfg.out / "stageB_systemic.json",
        {
            "provenance": provenance(cfg, inputs, frozen=True),
            "stop_eras": {str(r.era): ["volume_step"] for r in rows if r.verdict == "stop"},
        },
    )
    return {
        "volume_bands": "stop" if any(r.verdict == "stop" for r in rows) else "ok",
        "n_cells": len(rows),
        "cells_stop": [[r.era, r.exchange] for r in rows if r.verdict == "stop"],
        "cells_drift_note": len([r for r in rows if r.note]),
    }


def run_stage_b(
    cfg: Config,
    archive: Archive,
    conn: psycopg.Connection,
    fingerprints: Mapping[int, Mapping[str, str]],
) -> dict[str, Any]:
    sessions = archive_sessions(archive)
    drawn = draw_days(cfg, archive, sessions)
    freeze_inputs(cfg, conn)
    frozen = load_frozen(cfg)
    exchange = load_exchange_map(conn)  # once per invocation, hashed into every volume part key
    for era in cfg.eras:
        run_day_vs_minute(cfg, archive, drawn, era)
        run_volume_bands(cfg, conn, frozen, era, fingerprints[era], exchange)
    verdict = assemble_day_vs_minute(cfg, archive.inputs)
    vol = assemble_volume_bands(cfg, archive.inputs)
    return {
        "day_vs_minute_1d_kind": verdict["decision"],
        "day_vs_minute_eras_over_limit": verdict["eras_over_limit"],
        "volume_bands": vol["volume_bands"],
        "volume_cells": vol["n_cells"],
        "volume_cells_stop": vol["cells_stop"],
    }


# -------------------------------------------------------------------------- stage C: name level
#: Arms. IBKR is the independent arm and judges; Alpaca (from 2016-01-04) is reported as
#: corroboration only: same upstream as Massive, so it never passes, fails or stops anything.
ARM_KINDS = {
    ("1d", "massive"): "sip_flat",
    ("1d", "ibkr"): "smart_trades",
    ("1d", "alpaca"): "sip_rth",
    ("5m", "massive"): "sip_flat_agg",
    ("5m", "ibkr"): "named",
    ("5m", "alpaca"): "sip_rth",
}
ALPACA_FIRST_DAY = date(2016, 1, 4)
UNMATCHED_LIST_CAP = 20  # listed incumbent bars per (name, era, kind); the counts are exact
NAME_BATCH = 50
_BARS_SQL = """
SELECT symbol, "timestamp", open, high, low, close, volume, served_at FROM ohlcv_raw
WHERE timeframe = %s AND vendor = %s AND kind = %s AND symbol = ANY(%s)
  AND "timestamp" >= %s AND "timestamp" < %s
ORDER BY symbol, "timestamp"
"""
_NY_ZONE = "America/New_York"


@dataclass(frozen=True)
class Bars:
    t_ns: np.ndarray
    key: np.ndarray  # session date (datetime64[D]) in the series' own stamp zone
    ohlc: tuple[np.ndarray, ...]
    volume: np.ndarray
    served_min: date | None
    served_max: date | None


def _session_keys(t_ns: np.ndarray, zone: str) -> np.ndarray:
    index = pd.DatetimeIndex(t_ns.astype("datetime64[ns]"), tz="UTC").tz_convert(zone)
    return index.tz_localize(None).normalize().values.astype("datetime64[D]")


STREAM_ROWS = 10_000  # rows per network round trip of the bar stream


def _bars_of(rows: list[tuple], timeframe: str, vendor: str, kind: str) -> Bars:
    """One name's rows (time-ordered) as arrays."""
    df = pd.DataFrame.from_records(
        rows, columns=["symbol", "ts", "open", "high", "low", "close", "volume", "served_at"]
    )
    t_ns = (
        df["ts"].dt.tz_convert("UTC").dt.tz_localize(None).astype("datetime64[ns]").astype("int64")
    ).to_numpy()
    zone = RAW_DAILY_SESSION_ZONE[(vendor, kind)] if timeframe == "1d" else _NY_ZONE
    served = df["served_at"].dropna()
    return Bars(
        t_ns,
        _session_keys(t_ns, zone),
        tuple(df[c].to_numpy(dtype=float) for c in ("open", "high", "low", "close")),
        df["volume"].to_numpy(dtype=float, na_value=np.nan),  # NaN stays unknown, not zero
        served.min().date() if len(served) else None,
        served.max().date() if len(served) else None,
    )


def fetch_bars(
    conn: psycopg.Connection,
    timeframe: str,
    vendor: str,
    names: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, Bars]:
    """Raw bars of one (timeframe, vendor) for several names over [start, end), per name. The
    rows are streamed (ordered by symbol) and converted to arrays one name at a time, so the
    Python-object footprint is one name's rows, never the batch's."""
    kind = ARM_KINDS[(timeframe, vendor)]
    wait_out_nightly_window()
    out: dict[str, Bars] = {}
    pending: list[tuple] = []
    with conn.cursor() as cur:
        for row in cur.stream(
            _BARS_SQL, (timeframe, vendor, kind, names, start, end), size=STREAM_ROWS
        ):
            if pending and row[0] != pending[0][0]:
                out[str(pending[0][0])] = _bars_of(pending, timeframe, vendor, kind)
                pending = []
            pending.append(row)
    if pending:
        out[str(pending[0][0])] = _bars_of(pending, timeframe, vendor, kind)
    return out


def rth_mask(t_ns: np.ndarray, sessions: dict[date, tuple[datetime, datetime]]) -> np.ndarray:
    """True for stamps inside the NYSE regular session [open, close) of their New York date."""
    days = sorted(sessions)
    sk = np.array(days, dtype="datetime64[D]")
    open_ns = np.array([int(sessions[d][0].timestamp()) * _NS for d in days], dtype=np.int64)
    close_ns = np.array([int(sessions[d][1].timestamp()) * _NS for d in days], dtype=np.int64)
    keys = _session_keys(t_ns, _NY_ZONE)
    pos = np.minimum(np.searchsorted(sk, keys), len(sk) - 1)
    valid = sk[pos] == keys
    mask: np.ndarray = valid & (t_ns >= open_ns[pos]) & (t_ns < close_ns[pos])
    return mask


def last_bucket_mask(
    t_ns: np.ndarray, sessions: dict[date, tuple[datetime, datetime]]
) -> np.ndarray:
    """True for the final 5m bucket of each stamp's session (its start is the close minus 5 min)."""
    days = sorted(sessions)
    sk = np.array(days, dtype="datetime64[D]")
    close_ns = np.array([int(sessions[d][1].timestamp()) * _NS for d in days], dtype=np.int64)
    keys = _session_keys(t_ns, _NY_ZONE)
    pos = np.minimum(np.searchsorted(sk, keys), len(sk) - 1)
    mask: np.ndarray = (sk[pos] == keys) & (t_ns >= close_ns[pos] - 300 * _NS)
    return mask


@dataclass(frozen=True)
class ArmResult:
    n_matched: int
    n_agree: int  # level agreement on the close
    n_agree_all: int  # level agreement on all of O, H, L, C
    classes: dict[str, int]
    median_log_ratio: float
    correlation: float
    n_incumbent_zero_volume: int
    n_incumbent_traded_missing: int
    missing_listed: list[str]
    n_ret_pairs: int = 0
    n_ret_agree: int = 0
    n_intra: int = 0
    n_intra_agree: int = 0
    dispersion: float = math.nan
    scale_class: str = ""
    n_incumbent_unknown_volume: int = 0  # incumbent bars with a NULL volume: unknown, not zero
    break_step: float = math.nan  # step of an in-era level break that reads as a split
    break_pre_median: float = math.nan  # Massive / incumbent log level before that break
    stable_offset: bool = False  # the stable constant offset predicate, evaluated once
    lp_hist: dict[str, int] = field(default_factory=dict)  # last_print candidates by size bin

    def counts(self) -> nc.AgreementCounts:
        return nc.AgreementCounts(
            self.n_matched,
            self.n_agree,
            self.n_agree_all,
            self.classes,
            self.n_ret_pairs,
            self.n_ret_agree,
            self.n_intra,
            self.n_intra_agree,
            {int(b): n for b, n in self.lp_hist.items()},
        )


def compare_arm(
    timeframe: str,
    arm: str,
    massive: Bars,
    inc: Bars,
    splits: list[SplitFactor],
    sessions: dict[date, tuple[datetime, datetime]],
) -> ArmResult | None:
    """Massive against one incumbent arm for one name-era. None when the arm holds no bar.

    ``massive`` is the 5m series for ``5m`` and the served day file for ``1d`` (design 8a
    amendment 2026-11-12: Massive 1d is the served day file, never built from minutes)."""
    if len(inc.t_ns) == 0:
        return None
    five = timeframe == "5m"
    keep = rth_mask(inc.t_ns, sessions) if five else np.ones(len(inc.t_ns), dtype=bool)
    unknown_volume = int(np.count_nonzero(keep & np.isnan(inc.volume)))
    zero_volume = int(np.count_nonzero(keep & (inc.volume <= 0)))
    keep &= inc.volume > 0  # traded buckets only; a NULL volume is unknown, not a traded bucket
    join_inc = inc.t_ns if five else inc.key.astype("int64")
    join_m = massive.t_ns if five else massive.key.astype("int64")
    if len(join_m) == 0:
        return None
    order = np.argsort(join_m, kind="stable")
    pos = np.searchsorted(join_m[order], join_inc)
    pos = np.minimum(pos, len(join_m) - 1)
    hit = (join_m[order][pos] == join_inc) & keep
    midx = order[pos][hit]
    missing = np.flatnonzero(keep & ~hit)
    listed = [
        str(np.datetime64(int(inc.t_ns[i]), "ns")) if five else str(inc.key[i])
        for i in missing[:UNMATCHED_LIST_CAP]
    ]
    if not hit.any():
        return ArmResult(
            0, 0, 0, {}, math.nan, math.nan, zero_volume, len(missing), listed,
            n_incumbent_unknown_volume=unknown_volume,
        )  # fmt: skip
    inc_ohlc = tuple(a[hit] for a in inc.ohlc)
    m_ohlc = tuple(a[midx] for a in massive.ohlc)
    scale = lc.split_scale_for_days(massive.key[midx], splits)

    def neighbour(shift: int) -> tuple[tuple[np.ndarray, ...], np.ndarray]:
        """The neighbour bar (NaN where absent) and the split scale of its OWN session."""
        j = midx + shift
        ok = (j >= 0) & (j < len(massive.t_ns))
        j = np.clip(j, 0, len(massive.t_ns) - 1)
        own_scale = lc.split_scale_for_days(massive.key[j], splits)
        return tuple(np.where(ok, a[j], np.nan) for a in massive.ohlc), own_scale

    prev_bar, prev_scale = neighbour(-1)
    next_bar, next_scale = neighbour(1)

    rank = np.cumsum(keep) - 1  # each kept incumbent bar's position in the filtered series
    counts = nc.price_agreement(
        m_ohlc,
        scale,
        inc_ohlc,
        nc.INCUMBENT_INCREMENT[arm],
        massive_prev_raw=prev_bar,
        massive_next_raw=next_bar,  # type: ignore[arg-type]
        massive_prev_scale=prev_scale,
        massive_next_scale=next_scale,
        last_bucket=last_bucket_mask(inc.t_ns[hit], sessions) if five else None,
        massive_pos=midx,
        incumbent_pos=rank[hit],
    )
    adj_close = m_ohlc[3] / scale
    if five:  # bar-to-bar returns of consecutive matched bars (same rule as the daily one)
        consec = (midx[1:] - midx[:-1] == 1) & (rank[hit][1:] - rank[hit][:-1] == 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = nc.return_correlation(
                np.log(adj_close[1:] / adj_close[:-1])[consec],
                np.log(inc_ohlc[3][1:] / inc_ohlc[3][:-1])[consec],
            )
    else:
        corr = nc.identity_correlation(adj_close, inc_ohlc[3])
    return ArmResult(
        counts.n_matched,
        counts.n_agree,
        counts.n_agree_all,
        counts.n_class,
        counts.median_log,
        corr,
        zero_volume,
        len(missing),
        listed,
        counts.n_ret_pairs,
        counts.n_ret_agree,
        counts.n_intra,
        counts.n_intra_agree,
        counts.iqr,
        nc.scale_class(
            counts.median_log,
            counts.stable_offset,
            counts.share,
            counts.ret_share,
            counts.break_step,
        ),
        n_incumbent_unknown_volume=unknown_volume,
        break_step=counts.break_step,
        break_pre_median=counts.break_pre_median,
        stable_offset=counts.stable_offset,
        lp_hist={str(b): n for b, n in counts.lp_hist.items()},
    )


@dataclass(frozen=True)
class NameJudgement:
    outcome: str
    reason: str
    judged: tuple[str, ...]  # timeframes with a detector: the names that feed the era counters


class NameGate(NamedTuple):
    outcome: str  # empty when the name-era is judged on ``usable``
    reason: str
    usable: tuple[str, ...]  # timeframes with a detector and a resolved identity of their own
    decorrelated: tuple[str, ...]  # detector timeframes whose own identity correlation failed


def identity_state(r: ArmResult | None) -> str:
    """The identity of one timeframe's pair: none (no matched bar), thin (no finite correlation:
    a coverage gap), decorrelated (a finite correlation under 0.9: a disagreement), nodet
    (resolved but no detector) or usable (resolved with a detector)."""
    if r is None or r.n_matched == 0:
        return "none"
    if not math.isfinite(r.correlation):
        return "thin"
    if not nc.identity_resolved(r.correlation):
        return "decorrelated"
    return "usable" if nc.has_detector(r.counts()) else "nodet"


def judged_timeframes(
    results: Mapping[str, ArmResult | None],
    preclass: str,
    listed_in_era: bool,
    massive_hole: bool = False,
) -> NameGate:
    """The gates before any price verdict. A Massive hole (the frozen span lists the name, the
    incumbent traded, Massive holds nothing) is flagged first: a data defect, never not_listed and
    never stop-exempt. A name-era that is not listed or on the non-split convention list is judged
    by nothing. Identity is judged per timeframe (``identity_state``): the name-era is judged on
    its usable timeframes; with none it is ``identity_decorrelated`` (a detector timeframe
    disagrees), ``identity_thin`` (matched bars, no usable evidence) or has no detector."""
    if massive_hole:
        return NameGate(nc.OUTCOME_FLAGGED, "massive_hole", (), ())
    if not listed_in_era:
        return NameGate(nc.OUTCOME_NOT_LISTED, "not_listed_in_era", (), ())
    if preclass == nc.ERA_NON_SPLIT:
        return NameGate(nc.OUTCOME_NO_DETECTOR, "non_split_adjustment_convention", (), ())
    states = {tf: identity_state(results.get(tf)) for tf in ("1d", "5m")}
    usable = tuple(tf for tf, st in states.items() if st == "usable")
    # only a decorrelation on a timeframe that has a detector counts toward an era stop
    decorrelated = tuple(
        tf
        for tf, st in states.items()
        if st == "decorrelated" and nc.has_detector(results[tf].counts())  # type: ignore[union-attr]
    )
    if usable:
        return NameGate("", "", usable, decorrelated)
    if decorrelated:  # a DETECTOR timeframe disagrees; otherwise thin or no detector below
        return NameGate(nc.OUTCOME_UNRESOLVED, "identity_decorrelated", (), decorrelated)
    if "thin" in states.values():
        return NameGate(nc.OUTCOME_UNRESOLVED, "identity_thin", (), ())
    return NameGate(nc.OUTCOME_NO_DETECTOR, "no_detector", (), ())


def judge_name_era(
    results: Mapping[str, ArmResult | None],
    preclass: str,
    listed_in_era: bool,
    *,
    one_d_unresolved: bool,
    massive_hole: bool = False,
) -> NameJudgement:
    """The cell outcome of one name-era from the IBKR arm; Alpaca never judges.

    The verdict basis is the return-based agreement (99 percent of consecutive pairs per name-era),
    which a constant level factor cannot move. A stable level offset that reads as a split ratio is
    a candidate missing split (flagged); one that does not is an incumbent non-split adjustment and
    a level drift with agreeing returns is the same family: both pass, listed in the scale listing
    (the era counters, not the name, catch them when they are many). In an era whose 1d verdict is
    unresolved (rule 5) the 1d evidence cannot flag a name: the cell is judged on 5m alone, and a
    name with 1d evidence only is unresolved."""
    gate = judged_timeframes(results, preclass, listed_in_era, massive_hole)
    outcome, reason, usable = gate.outcome, gate.reason, gate.usable
    if outcome:
        return NameJudgement(outcome, reason, ())
    listed = ""
    used = 0
    for tf in usable:
        r = results[tf]
        assert r is not None
        if tf == "1d" and one_d_unresolved:
            continue
        used += 1
        if not nc.name_era_agreement_ok(r.counts()):
            return NameJudgement(nc.OUTCOME_FLAGGED, f"price_agreement_{tf}", usable)
        if r.scale_class == nc.SCALE_SPLIT_LIKE:
            return NameJudgement(nc.OUTCOME_FLAGGED, f"scale_factor_split_like_{tf}", usable)
        if r.scale_class:
            listed = f"{r.scale_class}_listed"
    if not used:
        return NameJudgement(nc.OUTCOME_UNRESOLVED, "close_convention_1d", usable)
    return NameJudgement(nc.OUTCOME_PASS, listed, usable)


def _has_traded(bars: Bars | None) -> bool:
    return bars is not None and bool(np.any(bars.volume > 0))


def trade_witness(data: Mapping[tuple[str, str], Mapping[str, Bars]], name: str) -> str:
    """Who witnesses that a name traded, for hole detection only: IBKR first, then Alpaca (the
    same upstream as Massive, so never a counter input or a price judgement), else empty."""
    for arm in ("ibkr", "alpaca"):
        if any(_has_traded(data.get((tf, arm), {}).get(name)) for tf in ("1d", "5m")):
            return arm
    return ""


def run_name_era_batch(
    cfg: Config,
    conn: psycopg.Connection,
    names: list[str],
    era: int,
    frozen: Frozen,
    non_split: set[tuple[str, int | None]],
) -> dict[str, dict[str, Any]]:
    """All checks of one batch of names for one era; returns per-name detail rows."""
    sessions = nyse_sessions(date(era, 1, 1), date(era, 12, 31))
    data: dict[tuple[str, str], dict[str, Bars]] = {}
    start, end = datetime(era, 1, 1, tzinfo=UTC), datetime(era + 1, 1, 1, tzinfo=UTC)
    for timeframe in ("1d", "5m"):
        arms = ["massive", "ibkr"] + (["alpaca"] if era >= ALPACA_FIRST_DAY.year else [])
        for arm in arms:
            data[(timeframe, arm)] = fetch_bars(conn, timeframe, arm, names, start, end)
    # every frozen split on or after the era's first session explains the era's cumulative scale
    first_session = date(era, 1, 1)
    after = {
        n: [s for s in frozen.splits.get(n, []) if s.effective_date >= first_session] for n in names
    }
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        wait_out_nightly_window()
        m5 = data[("5m", "massive")].get(name)
        dayfile = data[("1d", "massive")].get(name)
        massive_rows = m5 is not None or dayfile is not None
        span_listed = frozen.span_listed(name, era)
        listed = span_listed or massive_rows
        # the frozen span lists the name and an incumbent traded, yet Massive holds nothing: a hole
        witness = trade_witness(data, name)
        massive_hole = span_listed and not massive_rows and bool(witness)
        sp = frozen.splits.get(name, [])
        ibkr_rescale = frozen.ibkr_rescales.get(name, [])
        in_window = [s for s in sp if date(era, 1, 1) <= s.effective_date <= date(era, 12, 31)]
        listed_non_split = (name, era) in non_split or (name, None) in non_split
        preclass = nc.preclassify_name_era(len(in_window), listed_non_split)
        # Massive 1d is the served day file (design 8a amendment 2026-11-12), never RTH-built
        results: dict[str, dict[str, ArmResult | None]] = {"ibkr": {}, "alpaca": {}}
        if listed:
            for arm in results:
                for tf, massive in (("1d", dayfile), ("5m", m5)):
                    inc = data.get((tf, arm), {}).get(name)
                    if massive is None or inc is None:
                        results[arm][tf] = None
                        continue
                    if arm == "ibkr" and tf == "1d" and ibkr_rescale:
                        inc = rescaled_bars(inc, frozen.ibkr_scale(name, inc.key))  # rule 7
                    results[arm][tf] = compare_arm(tf, arm, massive, inc, sp, sessions)
        alp = data.get(("1d", "alpaca"), {}).get(name)
        seam = bool(alp) and nc.alpaca_epoch_seam_possible(
            alp.served_min, alp.served_max, [s.effective_date for s in in_window]
        )
        out[name] = {
            "listed": listed,
            "massive_hole": massive_hole,
            "hole_witness": witness if massive_hole else "",
            "ibkr_rescales": [
                f"{x.effective_date}:{x.factor}"
                for x in ibkr_rescale
                if x.effective_date >= date(era, 1, 1)
            ],
            "preclass": preclass,
            "alpaca_epoch_seam_possible": seam,
            # a stable constant level factor (or a drifting one with agreeing returns) that no
            # frozen split reproduces: the input of the non-split list (--non-split-csv)
            "probable_ibkr_non_split_adjustment": any(
                r is not None
                and r.scale_class in (nc.SCALE_ADJUSTMENT_LEVEL, nc.SCALE_LEVEL_DRIFT)
                and (
                    r.stable_offset
                    or nc.counts_as_systemic(r.scale_class, r.median_log_ratio, r.break_step)
                )
                for r in results["ibkr"].values()
            ),
            "splits_in_window": [f"{x.effective_date}:{x.factor}" for x in in_window],
            "splits_after_era": [f"{x.effective_date}:{x.factor}" for x in after[name]],
            "arms": {
                a: {tf: (asdict(r) if r else None) for tf, r in rs.items()}
                for a, rs in results.items()
            },
        }
    return out


def dispute_window(day: date) -> list[date]:
    """The ten NYSE sessions either side of a disputed date and its own session."""
    calendar = sorted(nyse_sessions(day - timedelta(days=40), day + timedelta(days=40)))
    return nc.dispute_window_sessions(calendar, day)


def run_disputed_windows(
    cfg: Config, conn: psycopg.Connection, disputed_csv: Path, frozen: Frozen
) -> dict[str, Any]:
    """1d census at the disputed dates: ten sessions either side of each (symbol, date) of the
    supplied file (the todo 592 witness rows), Massive against the IBKR arm."""
    cases: list[tuple[str, date]] = []
    malformed = 0
    with disputed_csv.open() as handle:
        for row in csv.DictReader(handle):
            try:
                cases.append((row["symbol"], date.fromisoformat(row["date"])))
            except (KeyError, ValueError, TypeError):
                malformed += 1
    if malformed:  # a dropped dispute would shrink the census silently
        raise ValueError(f"{disputed_csv}: {malformed} malformed row(s) (need symbol and ISO date)")
    rows: list[dict[str, Any]] = []
    for symbol, day in sorted(set(cases)):
        wait_out_nightly_window()
        start = datetime.combine(day - timedelta(days=40), dtime(0), tzinfo=UTC)
        end = datetime.combine(day + timedelta(days=40), dtime(0), tzinfo=UTC)
        massive = fetch_bars(conn, "1d", "massive", [symbol], start, end).get(symbol)
        inc = fetch_bars(conn, "1d", "ibkr", [symbol], start, end).get(symbol)
        if inc is not None and frozen.ibkr_rescales.get(symbol):
            inc = rescaled_bars(inc, frozen.ibkr_scale(symbol, inc.key))  # rule 7
        row: dict[str, Any] = {
            "symbol": symbol,
            "date": day.isoformat(),
            "matched": 0,
            "agree": 0,
            "share": "",
            "median_log_ratio": "",
            "note": "",
        }
        if massive is None or inc is None:
            row["note"] = "no_massive_bars" if massive is None else "no_incumbent_bars"
            rows.append(row)
            continue
        # the window is the NYSE session calendar centred on the disputed date, never Massive's
        # own dates (a hole in Massive must not shift or shrink it)
        window = set(dispute_window(day))
        keep = np.array([d.astype(object) in window for d in inc.key])
        trimmed = Bars(
            inc.t_ns[keep],
            inc.key[keep],
            tuple(a[keep] for a in inc.ohlc),
            inc.volume[keep],
            None,
            None,
        )
        result = compare_arm("1d", "ibkr", massive, trimmed, frozen.splits.get(symbol, []), {})
        if result is None or result.n_matched == 0:
            row["note"] = "no_overlap_in_window"
        else:
            row.update(
                matched=result.n_matched,
                agree=result.n_agree_all,  # the census reads open, high, low and close
                share=result.n_agree_all / result.n_matched,
                median_log_ratio=result.median_log_ratio,
            )
        rows.append(row)
    write_csv(
        cfg.out / "stageC_disputed_windows.csv",
        rows,
        ["symbol", "date", "matched", "agree", "share", "median_log_ratio", "note"],
    )
    judged = [r for r in rows if r["matched"]]
    return {
        "disputed_cases": len(rows),
        "disputed_cases_with_overlap": len(judged),
        "disputed_cases_disagreeing": sum(1 for r in judged if r["share"] < nc.NAME_ERA_AGREE_MIN),
    }


def _arm_result(detail: dict[str, Any], arm: str, timeframe: str) -> ArmResult | None:
    r = detail["arms"][arm].get(timeframe)
    return ArmResult(**r) if r else None


def read_non_split_csv(path: Path | None) -> set[tuple[str, int | None]]:
    """(symbol, era) pairs of the non-split adjustment list; a row without an era covers all."""
    if path is None:
        return set()
    out: set[tuple[str, int | None]] = set()
    with path.open() as handle:
        for row in csv.DictReader(handle):
            era = row.get("era")
            out.add((row["symbol"], int(era) if era else None))
    return out


def systemic_stop_eras(cfg: Config, inputs: Mapping[str, str]) -> dict[int, str]:
    """Eras a systemic verdict of stages A and B stops (session offset, record sanity rate, a
    volume step), from the result files of this run; empty when those stages did not run. A file
    that does not carry the current provenance (rule version, archive inputs, the frozen record
    for stage B, every requested era) is refused, never read."""
    stops: dict[int, list[str]] = {}
    for name, with_frozen in (("stageA_systemic.json", False), ("stageB_systemic.json", True)):
        path = cfg.out / name
        if not path.exists():
            continue
        record = json.loads(path.read_text())
        want = provenance(cfg, inputs, frozen=with_frozen)
        have = record.get("provenance", {})
        stale = [k for k in want if k != "eras" and have.get(k) != want[k]]
        if not set(want["eras"]) <= set(have.get("eras", [])):
            stale.append("eras")
        if stale:
            raise RuntimeError(f"{path} was computed under other {stale}: rerun its stage")
        for era, reasons in record["stop_eras"].items():
            stops.setdefault(int(era), []).extend(reasons)
    return {e: "+".join(sorted(set(r))) for e, r in stops.items()}


_TAPES_SQL = """
SELECT t.symbol, t.eff, o."timestamp", o.close
FROM unnest(%s::text[], %s::date[]) AS t(symbol, eff)
JOIN ohlcv_raw o ON o.symbol = t.symbol AND o.timeframe = '1d' AND o.vendor = 'massive'
 AND o.kind = 'sip_flat'
 AND o."timestamp" >= ((t.eff - 10)::timestamp AT TIME ZONE 'UTC')
 AND o."timestamp" < ((t.eff + 10)::timestamp AT TIME ZONE 'UTC')
ORDER BY t.symbol, t.eff, o."timestamp"
"""


def fetch_split_tapes(
    conn: psycopg.Connection, pairs: list[tuple[str, date]]
) -> dict[tuple[str, date], list[float]]:
    """Massive's raw (unadjusted) close on the last session on or before each split's effective
    date and on the first session after it, for every (symbol, effective date), in ONE query.
    A pair with either side absent is missing from the result."""
    if not pairs:
        return {}
    wait_out_nightly_window()
    with conn.cursor() as cur:
        cur.execute(_TAPES_SQL, ([p[0] for p in pairs], [p[1] for p in pairs]))
        rows = cur.fetchall()
    closes: dict[tuple[str, date], list[tuple[date, float]]] = {}
    for symbol, effective, stamp, close in rows:
        closes.setdefault((symbol, effective), []).append(
            (raw_session_date("massive", "sip_flat", stamp), float(close))
        )
    out: dict[tuple[str, date], list[float]] = {}
    for (symbol, effective), series in closes.items():
        before = [c for d, c in series if d <= effective]
        after = [c for d, c in series if d > effective]
        if before and after:
            out[(symbol, effective)] = [before[-1], after[0]]
    return out


def ledger_row(
    name: str,
    era: int,
    tf: str,
    claimed: str,
    level_log: float | None,
    splits_after: list[str],
    tapes: Mapping[str, list[float]],
    session_id: str,
) -> dict[str, Any]:
    """One disagreement-ledger row with the two witnesses available without new data: the frozen
    corporate-action list (every split that explains the era's cumulative scale), and Massive's
    own tape step at the cited split's date (``tapes`` comes from the name part). A case with
    neither stays unresolved; no witness is invented."""
    window = [(s.split(":")[0], float(s.split(":")[1])) for s in splits_after]
    witnesses: list[nc.Witness] = []
    frozen = None if level_log is None else nc.frozen_split_witness(math.exp(level_log), window)
    if frozen is not None:
        witnesses.append(frozen)
        cited = next(
            ((e, f) for e, f in window if frozen.citation.endswith(f"split {e} x{f}")), None
        )
        if cited is not None and cited[0] in tapes:  # a single split's tape; a product has none
            tw = nc.massive_tape_witness(*tapes[cited[0]], cited[1], cited[0])
            if tw is not None:
                witnesses.append(tw)
    row = nc.ledger_verdict(
        name, f"{era}/{tf}", claimed, witnesses, nc.DISPUTE_MASSIVE_VS_IBKR, session_id
    )
    return {
        "name": name,
        "span": f"{era}/{tf}",
        "claimed_defect": claimed,
        "witnesses": "; ".join(f"{w.kind}={w.citation}" for w in witnesses) or "none available",
        "verdict": row.verdict,
        "deciding_session_id": session_id if row.verdict != nc.VERDICT_UNRESOLVED else "",
        "decided_by": row.decided_by,
    }


TAPE_SERIES = (("massive", "sip_flat", "1d"),)  # the split tapes' source
#: The raw series stage C reads: every arm of ARM_KINDS.
STAGE_C_SERIES = tuple(sorted((vendor, kind, tf) for (tf, vendor), kind in ARM_KINDS.items()))


def stage_c_keys(
    eras: Iterable[int],
    base_key: Mapping[str, Any],
    fingerprints: Mapping[int, Mapping[str, str]],
) -> dict[int, dict[str, Any]]:
    """The identity of each era's name part: the base key and the era's own raw series. Split
    tapes live in their own parts (``run_split_tapes``), so no tape year enters a name key."""
    return {
        era: {**base_key, "raw_fingerprint": scoped_fingerprint(fingerprints[era], STAGE_C_SERIES)}
        for era in eras
    }


def tape_window_years(effective: date) -> tuple[int, ...]:
    """The years a split's tape reads: the effective date's and the plus and minus 10 day window's."""
    return tuple(
        sorted(
            {
                (effective - timedelta(days=10)).year,
                effective.year,
                (effective + timedelta(days=10)).year,
            }
        )
    )


TAPE_CHUNK = 500  # (name, split) pairs per tape query


def run_split_tapes(
    cfg: Config,
    conn: psycopg.Connection,
    frozen: Frozen,
    names: list[str],
    fingerprints: Mapping[int, Mapping[str, str]],
) -> dict[str, dict[str, list[float]]]:
    """Massive's tape step at every frozen split of the sampled names (the ledger's second
    witness), in one part per effective-date year keyed by the frozen record, the pairs and the
    fingerprints of the years the tape windows read. A current-year split invalidates only its
    own part; name parts neither store nor key on tapes. Returns name -> effective date -> tape."""
    by_year: dict[int, list[tuple[str, date]]] = {}
    for n in names:
        for sp in frozen.splits.get(n, []):
            if sp.effective_date.year >= min(cfg.eras):
                by_year.setdefault(sp.effective_date.year, []).append((n, sp.effective_date))
    windows = {
        y: sorted({w for _, e in pairs for w in tape_window_years(e)})
        for y, pairs in by_year.items()
    }
    missing = sorted({w for ws in windows.values() for w in ws} - set(fingerprints))
    fingerprints = {**fingerprints, **raw_fingerprints(conn, missing, TAPE_SERIES)}
    out: dict[str, dict[str, list[float]]] = {}
    for year, pairs in sorted(by_year.items()):
        key = {
            "logic": LOGIC_VERSION,
            "frozen": frozen_hashes(cfg),
            "pairs_sha256": _rows_sha256(sorted(pairs)),
            "tape_fingerprints": {
                str(w): scoped_fingerprint(fingerprints[w], TAPE_SERIES) for w in windows[year]
            },
        }
        if part_current(cfg, "split_tapes", year, key):
            part = json.loads(part_path(cfg, "split_tapes", year).read_text())
            if part["key"] != key:  # the second check: the key embedded in the part
                raise RuntimeError(f"split_tapes part {year} disagrees with its sidecar key")
            tapes = part["tapes"]
        else:
            fetched: dict[tuple[str, date], list[float]] = {}
            for i in range(0, len(pairs), TAPE_CHUNK):
                fetched.update(fetch_split_tapes(conn, pairs[i : i + TAPE_CHUNK]))
            tapes = {}
            for (n, eff), tape in fetched.items():
                tapes.setdefault(n, {})[eff.isoformat()] = tape
            write_part(cfg, "split_tapes", year, {"key": key, "year": year, "tapes": tapes})
        for n, by_date in tapes.items():
            out.setdefault(n, {}).update(by_date)
    return out


def run_stage_c(
    cfg: Config,
    conn: psycopg.Connection,
    max_names: int | None,
    non_split_csv: Path | None,
    disputed_csv: Path | None,
    session_id: str,
    fingerprints: Mapping[int, Mapping[str, str]],
    archive_inputs: Mapping[str, str],
) -> dict[str, Any]:
    freeze_inputs(cfg, conn)
    frozen = load_frozen(cfg)
    mapped = sorted(frozen.spans)
    with conn.cursor() as cur:
        cur.execute(_ACTIVE_SQL)
        active = [s for (s,) in cur.fetchall()]
    # active instruments with no ticker span are unmapped cells (a sampled run judges no unmapped)
    unmapped = [] if max_names is not None else sorted(set(active) - set(mapped))
    names = mapped
    if max_names is not None:
        names = sorted(random.Random(cfg.seed).sample(mapped, min(max_names, len(mapped))))
    non_split = read_non_split_csv(non_split_csv)
    base_key = {
        "seed": cfg.seed,  # the name sample (--max-names) draws from it
        "logic": LOGIC_VERSION,
        "max_names": max_names,
        "n_names": len(names),
        "non_split_rows": len(non_split),
        "non_split_sha256": _rows_sha256(non_split),
        "frozen": frozen_hashes(cfg),
    }
    keys = stage_c_keys(cfg.eras, base_key, fingerprints)
    for era in cfg.eras:
        if part_current(cfg, "name_checks", era, keys[era]):
            continue
        t0 = time.monotonic()
        detail: dict[str, dict[str, Any]] = {}
        for i in range(0, len(names), NAME_BATCH):
            detail.update(
                run_name_era_batch(cfg, conn, names[i : i + NAME_BATCH], era, frozen, non_split)
            )
            time.sleep(cfg.throttle_s)
        write_part(cfg, "name_checks", era, {"key": keys[era], "era": era, "names": detail})
        logger.info(
            "era_scanned",
            check="name_checks",
            era=era,
            names=len(detail),
            seconds=round(time.monotonic() - t0, 1),
        )
    tapes = run_split_tapes(cfg, conn, frozen, names, fingerprints)
    summary = assemble_stage_c(cfg, mapped, unmapped, keys, session_id, archive_inputs, tapes)
    summary["non_split_adjustment_list"] = (
        f"supplied ({len(non_split)} rows)" if non_split_csv else "not supplied"
    )
    summary["disputed_windows"] = (
        run_disputed_windows(cfg, conn, disputed_csv, frozen) if disputed_csv else "not supplied"
    )
    return summary


def _name_facts(
    name: str, d: dict[str, Any], tf: str, usable: tuple[str, ...]
) -> nc.NameFacts | None:
    """The judged facts of one name-era and timeframe, or None when no detector speaks for it."""
    r = _arm_result(d, "ibkr", tf)
    if r is None or tf not in usable:
        return None
    return nc.NameFacts(
        name,
        r.counts(),
        flagged=not nc.name_era_agreement_ok(r.counts()),
        level_class=(
            r.scale_class
            if nc.counts_as_systemic(r.scale_class, r.median_log_ratio, r.break_step)
            else ""
        ),
        median_log_ratio=r.median_log_ratio,
    )


def era_verdicts(
    judged: dict[tuple[int, str], list[nc.NameFacts]],
    eras: list[int],
    unresolved: Mapping[tuple[int, str], int] | None = None,
) -> dict[tuple[int, str], nc.EraVerdict]:
    """Verdicts of every (era, timeframe), calibrated on the reference eras present in the run
    (rules 1 to 3). A reference era is calibrated on the OTHER reference eras: against its own
    counters the 3x rule could never fire (a defect in 2014 to 2026 would raise its own bar). A
    run with no other reference era uses the floor and the pooled cap of its own eras. Only rows
    with enough judged names calibrate. The reference counters are measured with the cap of the
    era under test (their flagged share counts unexplained disagreement only)."""
    out: dict[tuple[int, str], nc.EraVerdict] = {}
    unres = unresolved or {}
    ref_eras = [e for e in eras if e in nc.REFERENCE_ERAS]
    for tf in ("1d", "5m"):
        hist = {e: _pooled_hist(judged.get((e, tf), [])) for e in eras}
        for era in eras:
            ref = [
                e
                for e in ref_eras
                if e != era and len(judged.get((e, tf), [])) >= nc.MIN_JUDGED_NAMES
            ]
            cap = nc.last_print_cap_bin(hist[e] for e in (ref or eras))
            thresholds = nc.counter_thresholds(
                nc.era_counters(judged.get((e, tf), []), unres.get((e, tf), 0), cap) for e in ref
            )
            verdict = nc.judge_era(
                tf, judged.get((era, tf), []), thresholds, cap, unres.get((era, tf), 0)
            )
            out[(era, tf)] = replace(verdict, calibration=",".join(map(str, ref)) or "self")
    return out


def _pooled_hist(names: list[nc.NameFacts]) -> Counter[int]:
    """The last_print candidate histogram of an era's judged names, summed once."""
    total: Counter[int] = Counter()
    for f in names:
        total.update(f.counts.lp_hist)
    return total


def _close_convention_unresolved(verdict: nc.EraVerdict) -> bool:
    return verdict.verdict == nc.ERA_UNRESOLVED and "close_convention" in verdict.reasons


def assemble_stage_c(
    cfg: Config,
    mapped: list[str],
    unmapped: list[str],
    keys: dict[int, dict[str, Any]],
    session_id: str,
    archive_inputs: Mapping[str, str],
    tapes: Mapping[str, Mapping[str, list[float]]],
) -> dict[str, Any]:
    parts = {e: p for e, p in all_parts(cfg, "name_checks").items() if p["key"] == keys.get(e)}
    eras = sorted(parts)
    judged: dict[tuple[int, str], list[nc.NameFacts]] = {}
    arm_results: dict[tuple[str, int], dict[str, ArmResult | None]] = {}
    unresolved: dict[tuple[int, str], int] = {}  # decorrelated names per (era, timeframe)
    for era in eras:
        for name, d in sorted(parts[era]["names"].items()):
            results = {tf: _arm_result(d, "ibkr", tf) for tf in ("1d", "5m")}
            gate = judged_timeframes(results, d["preclass"], d["listed"], d["massive_hole"])
            arm_results[(name, era)] = results
            for tf in gate.decorrelated:
                unresolved[(era, tf)] = unresolved.get((era, tf), 0) + 1
            for tf in gate.usable:
                facts = _name_facts(name, d, tf, gate.usable)
                if facts is not None:
                    judged.setdefault((era, tf), []).append(facts)
    verdicts = era_verdicts(judged, eras, unresolved)
    rows: list[dict[str, Any]] = []
    scale_rows: list[dict[str, Any]] = []
    non_split_rows: list[dict[str, Any]] = []
    unmatched_rows: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    outcomes: dict[tuple[str, int], tuple[str, str]] = {}
    classes_total: Counter[str] = Counter()
    carriers: dict[int, set[str]] = {}
    for (era, tf), v in verdicts.items():
        # a timeframe flags only where its own verdict lets it: never through an unresolved 1d
        if not (tf == "1d" and _close_convention_unresolved(v)):
            carriers.setdefault(era, set()).update(v.other_concentration)
    for era in eras:
        # the close convention only: a thin era is a coverage gap, treated alike on 1d and 5m
        one_d_unresolved = _close_convention_unresolved(verdicts[(era, "1d")])
        for name, d in sorted(parts[era]["names"].items()):
            j = judge_name_era(
                arm_results[(name, era)],
                d["preclass"],
                d["listed"],
                one_d_unresolved=one_d_unresolved,
                massive_hole=d["massive_hole"],
            )
            if j.outcome == nc.OUTCOME_PASS and name in carriers.get(era, ()):
                # rule 4, second half: a carrier of concentrated unexplained pairs is flagged
                j = NameJudgement(nc.OUTCOME_FLAGGED, "other_concentration", j.judged)
            outcomes[(name, era)] = (j.outcome, j.reason)
            row: dict[str, Any] = {
                "name": name,
                "era": era,
                "outcome": j.outcome,
                "reason": j.reason,
                "preclass": d["preclass"],
                "hole_witness": d["hole_witness"],
                "alpaca_epoch_seam_possible": d["alpaca_epoch_seam_possible"],
                "probable_ibkr_non_split_adjustment": d["probable_ibkr_non_split_adjustment"],
            }
            for arm in ("ibkr", "alpaca"):
                for tf in ("1d", "5m"):
                    r = d["arms"][arm].get(tf)
                    p = f"{arm}_{tf}"
                    row[f"{p}_matched"] = r["n_matched"] if r else 0
                    row[f"{p}_level_agree"] = r["n_agree"] if r else 0
                    row[f"{p}_agree_all_ohlc"] = r["n_agree_all"] if r else 0
                    row[f"{p}_return_pairs"] = r["n_ret_pairs"] if r else 0
                    row[f"{p}_return_agree"] = r["n_ret_agree"] if r else 0
                    row[f"{p}_intrabar_agree"] = r["n_intra_agree"] if r else 0
                    row[f"{p}_median_log_ratio"] = r["median_log_ratio"] if r else ""
                    row[f"{p}_level_class"] = r["scale_class"] if r else ""
                    row[f"{p}_zero_volume_incumbent"] = r["n_incumbent_zero_volume"] if r else 0
                    row[f"{p}_unknown_volume_incumbent"] = (
                        r["n_incumbent_unknown_volume"] if r else 0
                    )
                    row[f"{p}_incumbent_traded_missing"] = (
                        r["n_incumbent_traded_missing"] if r else 0
                    )
                    if r:
                        unmatched_rows.extend(
                            {"name": name, "era": era, "arm": arm, "timeframe": tf, "bar": b}
                            for b in r["missing_listed"]
                        )
            rows.append(row)
            for tf in j.judged:
                r = d["arms"]["ibkr"][tf]
                classes_total.update(r["classes"])
                cls = r["scale_class"]
                if not cls:
                    continue
                scale_rows.append(
                    {
                        "name": name,
                        "era": era,
                        "timeframe": tf,
                        "level_class": cls,
                        "median_log_ratio": r["median_log_ratio"],
                        "implied_factor": math.exp(r["median_log_ratio"]),
                        "dispersion_iqr": r["dispersion"],
                        "return_agreement": (
                            r["n_ret_agree"] / r["n_ret_pairs"] if r["n_ret_pairs"] else ""
                        ),
                        "frozen_splits_in_window": ";".join(d["splits_in_window"]),
                    }
                )
                # an in-era break is judged by the residual BEFORE it (Massive / incumbent), the
                # frozen_split_witness convention; otherwise by the era's median
                pre = r["break_pre_median"]
                ledger.append(
                    ledger_row(
                        name, era, tf, f"level_class:{cls}",
                        pre if math.isfinite(pre) else r["median_log_ratio"],
                        d["splits_after_era"], tapes.get(name, {}), session_id,
                    )
                )  # fmt: skip
            if j.outcome == nc.OUTCOME_FLAGGED and j.reason.startswith("price_agreement"):
                tf = j.reason.rsplit("_", 1)[1]
                r = d["arms"]["ibkr"].get(tf)
                ledger.append(
                    ledger_row(
                        name, era, tf, j.reason, r["median_log_ratio"] if r else None,
                        d["splits_after_era"], tapes.get(name, {}), session_id,
                    )
                )  # fmt: skip
            if d["probable_ibkr_non_split_adjustment"]:
                one, five = d["arms"]["ibkr"].get("1d"), d["arms"]["ibkr"].get("5m")
                non_split_rows.append(
                    {
                        "symbol": name,
                        "era": era,
                        "class_1d": one["scale_class"] if one else "",
                        "class_5m": five["scale_class"] if five else "",
                        "median_log_1d": one["median_log_ratio"] if one else "",
                        "median_log_5m": five["median_log_ratio"] if five else "",
                        "implied_factor_1d": math.exp(one["median_log_ratio"]) if one else "",
                        "implied_factor_5m": math.exp(five["median_log_ratio"]) if five else "",
                    }
                )
    for era in eras:
        for name in unmapped:
            outcomes[(name, era)] = (nc.OUTCOME_UNMAPPED, "active_instrument_without_span")
    era_rows = [
        {
            "era": era,
            "timeframe": tf,
            "verdict": v.verdict,
            "reasons": ";".join(v.reasons),
            "calibrated_on": v.calibration,
            "n_judged_names": v.n_judged,
            "n_matched": v.n_matched,
            "n_return_pairs": v.n_ret_pairs,
            "return_residual": v.return_residual,
            "other_share": v.other_share,
            "n_other_carriers": v.n_other_carriers,
            "other_concentration": ";".join(v.other_concentration),
            "flagged_share": v.counters.flagged_share,
            "identity_unresolved_share": v.counters.identity_unresolved_share,
            "level_class_share": v.counters.level_class_share,
            "shared_factor_share": v.counters.shared_factor_share,
            "threshold_flagged_share": v.thresholds["flagged_share"],
            "threshold_identity_unresolved_share": v.thresholds["identity_unresolved_share"],
            "threshold_level_class_share": v.thresholds["level_class_share"],
            "threshold_shared_factor_share": v.thresholds["shared_factor_share"],
            "class_mix": json.dumps(v.class_mix, sort_keys=True),
        }
        for (era, tf), v in sorted(verdicts.items())
    ]
    write_csv(cfg.out / "stageC_name_era_checks.csv", rows, list(rows[0]) if rows else ["name"])
    write_csv(
        cfg.out / "stageC_era_tables.csv", era_rows, list(era_rows[0]) if era_rows else ["era"]
    )
    write_csv(
        cfg.out / "stageC_unmatched_incumbent_bars.csv",
        unmatched_rows,
        ["name", "era", "arm", "timeframe", "bar"],
    )
    write_csv(
        cfg.out / "stageC_scale_factor.csv",
        scale_rows,
        [
            "name",
            "era",
            "timeframe",
            "level_class",
            "median_log_ratio",
            "implied_factor",
            "dispersion_iqr",
            "return_agreement",
            "frozen_splits_in_window",
        ],
    )
    write_csv(
        cfg.out / "stageC_non_split_candidates.csv",
        non_split_rows,
        [
            "symbol",
            "era",
            "class_1d",
            "class_5m",
            "median_log_1d",
            "median_log_5m",
            "implied_factor_1d",
            "implied_factor_5m",
        ],
    )
    ledger_fields = [
        "name",
        "span",
        "claimed_defect",
        "witnesses",
        "verdict",
        "deciding_session_id",
        "decided_by",
    ]
    write_csv(cfg.out / "stageC_disagreement_ledger.csv", ledger, ledger_fields)
    # an era stop is a stop of either timeframe or of stage A or B (a real stop outranks unresolved)
    stops = {**systemic_stop_eras(cfg, archive_inputs)}
    for (era, tf), v in sorted(verdicts.items()):
        if v.verdict == nc.ERA_STOP:
            reason = f"{tf}:" + "+".join(v.reasons)
            stops[era] = f"{stops[era]}+{reason}" if era in stops else reason
    unresolved_1d = sorted(e for e in eras if _close_convention_unresolved(verdicts[(e, "1d")]))
    expected = [(n, e) for n in [*mapped, *unmapped] for e in cfg.eras]
    closed = nc.close_partition(expected, outcomes, stop_eras=stops)
    gap_additions = sorted(
        {f"{n}|{e}|{r}" for (n, e), (o, r) in outcomes.items() if o == nc.OUTCOME_FLAGGED}
    )
    write_json(cfg.out / "stageC_gap_list_additions.json", gap_additions)
    write_json(cfg.out / "stageC_stop_eras.json", {str(e): r for e, r in sorted(stops.items())})
    reasons = Counter(f"{o}:{r}" if r else o for (o, r) in outcomes.values())
    summary: dict[str, Any] = {
        "names_judged": len({n for n, _ in outcomes}),
        "mapped_names": len(mapped),
        "unmapped_names": len(unmapped),
        "eras": eras,
        "era_verdicts": {f"{e}/{tf}": v.verdict for (e, tf), v in sorted(verdicts.items())},
        "unresolved_1d_eras": unresolved_1d,
        "stop_eras_all_sources": {str(e): r for e, r in sorted(stops.items())},
        "disagreement_classes_total": dict(classes_total),
        "ledger_rows": len(ledger),
        "ledger_verdicts": dict(Counter(r["verdict"] for r in ledger)),
        "level_class_name_era_timeframes": len(scale_rows),
        "probable_non_split_name_eras": len(non_split_rows),
        "flagged_cell_count": len(gap_additions),
        "cell_outcome_reasons_before_era_stop": dict(reasons),
        "vendor_wide_return_agreement": "stop" if stops else "ok",
    }
    if isinstance(closed, nc.PartialRun):
        summary["partition"] = {
            "status": "partial",
            "n_expected": closed.n_expected,
            "n_judged": closed.n_judged,
        }
    else:
        summary["partition"] = {
            "status": "complete",
            "n_mapped_cells": closed.n_mapped_cells,
            "counts": closed.counts,
            "reasons": dict(Counter(f"{o}:{r}" for (o, r) in closed.cells.values())),
        }
        write_json(
            cfg.out / "stageC_partition.json",
            {
                "counts": closed.counts,
                "n_mapped_cells": closed.n_mapped_cells,
                "cells": [[n, e, o, r] for (n, e), (o, r) in sorted(closed.cells.items())],
            },
        )
    return summary


# ------------------------------------------------------------------------------------- driver
def run_stage_a(cfg: Config, archive: Archive, conn: psycopg.Connection) -> dict[str, Any]:
    sessions = archive_sessions(archive)
    run_publish_and_manifest(cfg, archive, sessions)
    drawn = draw_days(cfg, archive, sessions)
    for era in cfg.eras:
        run_record_sanity_and_session(cfg, archive, sessions, drawn, era)
    verdicts = assemble_stage_a(cfg, archive.inputs)
    verdicts["survivorship"] = run_survivorship(cfg, archive, conn)
    completeness = json.loads((cfg.out / "stageA_manifest_completeness.json").read_text())
    verdicts["manifest_complete"] = (
        "ok" if all(v["complete"] for v in completeness.values()) else "stop"
    )
    return verdicts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--stages", default="A,B", help="comma list of A, B, C")
    parser.add_argument("--eras", default="2003-2026", help="e.g. 2010 or 2003-2026")
    parser.add_argument("--days-per-era", type=int, default=6, help="seeded minute-file draw")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--throttle-s", type=float, default=0.0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--session-id",
        required=True,
        help="stage C: the deciding session recorded on decided ledger rows",
    )
    parser.add_argument("--max-names", type=int, default=None, help="stage C: seeded name sample")
    parser.add_argument(
        "--non-split-csv",
        type=Path,
        default=None,
        help="stage C: symbol (and optional era) rows, the non-split adjustment list",
    )
    parser.add_argument(
        "--disputed-csv",
        type=Path,
        default=None,
        help="stage C: symbol,date rows (the todo 592 witness cases)",
    )
    args = parser.parse_args(argv)
    cfg = Config(
        args.out,
        args.data_dir,
        args.seed,
        args.days_per_era,
        parse_eras(args.eras),
        args.force,
        args.throttle_s,
    )
    stages = {s.strip().upper() for s in args.stages.split(",")}
    archive = load_archive(cfg.data_dir)
    cfg.out.mkdir(parents=True, exist_ok=True)
    write_json(cfg.out / "inputs.json", archive.inputs)
    summary: dict[str, Any] = {
        "stages_requested": sorted(stages),
        "seed": cfg.seed,
        "eras": list(cfg.eras),
        "inputs": archive.inputs,
    }
    archive_last_era = max(archive.manifest[MINUTE] | archive.manifest[DAY]).year
    with connect_read_only() as conn:
        # one fingerprint per era per invocation, shared by every check that keys on raw rows
        read: set[tuple[str, str, str]] = set()
        if "B" in stages:
            read |= set(VOLUME_SERIES)
        if "C" in stages:
            read |= set(STAGE_C_SERIES)
        fingerprints = raw_fingerprints(conn, cfg.eras, read) if read else {}
        if "A" in stages:
            summary["stage_a"] = run_stage_a(cfg, archive, conn)
        if "B" in stages:
            summary["stage_b"] = run_stage_b(cfg, archive, conn, fingerprints)
        if "C" in stages:
            summary["stage_c"] = run_stage_c(
                cfg,
                conn,
                args.max_names,
                args.non_split_csv,
                args.disputed_csv,
                args.session_id,
                fingerprints,
                archive.inputs,
            )
    systemic = {
        f"{stage}.{k}": v
        for stage in ("stage_a", "stage_b", "stage_c")
        for k, v in summary.get(stage, {}).items()
        if v in ("stop", "ok")
    }
    summary["systemic_verdicts"] = systemic
    # complete only when every stage ran over every era and the partition closed over the whole
    # mapped universe; anything less is partial and carries no partition table
    partition = summary.get("stage_c", {}).get("partition")
    full = (
        stages >= {"A", "B", "C"}
        and cfg.eras == tuple(range(2003, archive_last_era + 1))
        and isinstance(partition, dict)
        and partition.get("status") == "complete"
    )
    summary["status"] = "complete" if full else "partial"
    summary["partition"] = partition if full else None
    write_json(cfg.out / "summary.json", summary)
    logger.info("summary_written", status=summary["status"], systemic=systemic)
    print(json.dumps({"status": summary["status"], "systemic_verdicts": systemic}, indent=2))
    return 1 if "stop" in systemic.values() else 0


_PROBE_START, _PROBE_END = datetime(2010, 1, 1, tzinfo=UTC), datetime(2011, 1, 1, tzinfo=UTC)
#: Every SQL statement the runner issues, with probe parameters: a test EXPLAINs each one against
#: the live database (no SQL ships unexecuted), and checks that every ``execute`` call names one.
SQL_STATEMENTS: dict[str, tuple[str, tuple[Any, ...]]] = {
    "_HELD_SQL": (_HELD_SQL, ()),
    "_PRESENCE_SQL": (_PRESENCE_SQL, ()),
    "_ACTIVE_SQL": (_ACTIVE_SQL, ()),
    "_LISTING_END_SQL": (_LISTING_END_SQL, ()),
    "_CA_SQL": (_CA_SQL, ()),
    "_SPAN_SQL": (_SPAN_SQL, ()),
    "_EXCHANGE_SQL": (_EXCHANGE_SQL, ()),
    "_VOL_SQL": (_VOL_SQL, ("ibkr", "smart_trades", _PROBE_START, _PROBE_END)),
    "_BARS_SQL": (_BARS_SQL, ("1d", "massive", "sip_flat", ["A"], _PROBE_START, _PROBE_END)),
    "_TAPES_SQL": (_TAPES_SQL, (["A"], [date(2010, 3, 1)])),
    "_RAW_FINGERPRINT_SQL": (_RAW_FINGERPRINT_SQL, (_PROBE_START, _PROBE_END, ["a|b|1d"])),
    "_REVISION_FINGERPRINT_SQL": (
        _REVISION_FINGERPRINT_SQL,
        (_PROBE_START, _PROBE_END, ["a|b|1d"]),
    ),
}


if __name__ == "__main__":
    sys.exit(main())
