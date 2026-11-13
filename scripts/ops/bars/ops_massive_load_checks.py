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
from typing import Any

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
def connect_read_only() -> psycopg.Connection:
    """A session whose every transaction is read-only. psycopg ignores ``conn.read_only`` in
    autocommit mode, so the server-side default is set at connect time (round 5 finding 6)."""
    return psycopg.connect(
        get_settings().database_url, autocommit=True, options="-c default_transaction_read_only=on"
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


def sanity_of(raw: RawFile) -> lc.SanityCounts:
    return lc.record_sanity(
        raw.code,
        raw.window_start,
        raw.open,
        raw.high,
        raw.low,
        raw.close,
        raw.volume,
        owned_rows(raw),
    )


# ---------------------------------------------------------------------------------- part store
def part_path(cfg: Config, check: str, era: int) -> Path:
    return cfg.out / "parts" / f"{check}__{era}.json"


def load_part(cfg: Config, check: str, era: int, key: dict[str, object]) -> dict[str, Any] | None:
    """A saved part computed under the same sampling key, else None (recompute)."""
    path = part_path(cfg, check, era)
    if cfg.force or not path.exists():
        return None
    part: dict[str, Any] = json.loads(path.read_text())
    return part if part.get("key") == key else None


def all_parts(cfg: Config, check: str) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for era in cfg.eras:
        path = part_path(cfg, check, era)
        if path.exists():
            out[era] = json.loads(path.read_text())
    return out


#: Bumped when a check rule changes, so saved parts computed under the old rule are recomputed.
LOGIC_VERSION = "2026-11-13-r5b"


_RAW_FINGERPRINT_SQL = """
SELECT vendor, kind, timeframe, count(*), max(served_at) FROM ohlcv_raw
WHERE "timestamp" >= %s AND "timestamp" < %s GROUP BY 1, 2, 3
"""
_REVISION_FINGERPRINT_SQL = """
SELECT date_part('year', "timestamp" AT TIME ZONE 'UTC')::int, vendor, kind, timeframe, count(*)
FROM ohlcv_revision WHERE "timestamp" >= %s AND "timestamp" < %s GROUP BY 1, 2, 3, 4
"""


def raw_fingerprints(conn: psycopg.Connection, eras: Iterable[int]) -> dict[int, dict[str, str]]:
    """Per era, per ``vendor|kind|timeframe``: ``rows|latest served_at|revision rows`` (round 5
    rule 7). A reload or extension moves the count; a restatement that keeps the count moves the
    served stamp and the revision-log count. Computed once per invocation (the revision log is read
    in one pass over every requested era) and scoped by each check to the series it reads."""
    eras = sorted(set(eras))
    if not eras:
        return {}
    out: dict[int, dict[str, str]] = {era: {} for era in eras}
    with conn.cursor() as cur:
        cur.execute(
            _REVISION_FINGERPRINT_SQL,
            (datetime(eras[0], 1, 1, tzinfo=UTC), datetime(eras[-1] + 1, 1, 1, tzinfo=UTC)),
        )
        revisions = {(e, f"{v}|{k}|{t}"): int(n) for e, v, k, t, n in cur.fetchall()}
        for era in eras:
            cur.execute(
                _RAW_FINGERPRINT_SQL,
                (datetime(era, 1, 1, tzinfo=UTC), datetime(era + 1, 1, 1, tzinfo=UTC)),
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


def gap_keys_of(named: list[dict[str, Any]]) -> list[str]:
    """One gap-list key per (ticker, day) of every named defective bar, never capped."""
    return sorted({f"{r['ticker']}|{r['day']}|defective_bar" for r in named})


def defect_rows(day: date, raw: RawFile, open_ns: int, close_ns: int) -> tuple[list, list]:
    """(owned defective rows, unowned rows with a defect), listed for the report. An owned defect
    is a gap-list item for its bar; an unowned row belongs to no instrument and is listed only."""
    bad = lc.defective_row_mask(raw.open, raw.high, raw.low, raw.close, raw.volume)
    own = owned_rows(raw)
    named: list[dict[str, Any]] = []
    unowned: list[dict[str, Any]] = []
    for i in np.flatnonzero(bad):
        row = {
            "day": day.isoformat(),
            "ticker": str(raw.tickers[raw.code[i]]),
            "window_start_ns": int(raw.window_start[i]),
            "open": float(raw.open[i]),
            "high": float(raw.high[i]),
            "low": float(raw.low[i]),
            "close": float(raw.close[i]),
            "volume": float(raw.volume[i]),
            "in_rth": bool(open_ns <= raw.window_start[i] < close_ns),
        }
        (named if own[i] else unowned).append(row)
    return named, unowned


def run_record_sanity_and_session(
    cfg: Config, archive: Archive, sessions: list[date], drawn: list[date], era: int
) -> None:
    """Stage A scans of one era: day-file sanity over EVERY day file of the era, minute-file
    sanity and the session offset over the era's drawn days."""
    key = sample_key(cfg, archive.inputs)
    if all(load_part(cfg, c, era, key) for c in ("record_sanity", "session")):
        logger.info("era_reused", check="stage_a_scans", era=era)
        return
    t0 = time.monotonic()
    day_counts: lc.SanityCounts | None = None
    n_day_files = 0
    named: list[dict[str, Any]] = []
    unowned: list[dict[str, Any]] = []
    for day in (d for d in sessions if lc.era_of(d) == era and d in archive.manifest[DAY]):
        wait_out_nightly_window()
        raw = read_raw_file(day_path(cfg.data_dir, DAY, day))
        counts = sanity_of(raw)
        day_counts = counts if day_counts is None else day_counts + counts
        if counts.n_defective_rows or counts.n_unowned_defective:
            n, u = defect_rows(day, raw, 0, 0)
            named.extend({**r, "file_kind": "day"} for r in n)
            unowned.extend({**r, "file_kind": "day"} for r in u)
        n_day_files += 1
        time.sleep(cfg.throttle_s)
    minute_counts: lc.SanityCounts | None = None
    session_rows: list[lc.SessionDayResult] = []
    era_days = [d for d in drawn if lc.era_of(d) == era]
    bounds = nyse_sessions(era_days[0], era_days[-1]) if era_days else {}
    for day in era_days:
        wait_out_nightly_window()
        raw = read_raw_file(day_path(cfg.data_dir, MINUTE, day))
        counts = sanity_of(raw)
        minute_counts = counts if minute_counts is None else minute_counts + counts
        open_dt, close_dt = bounds[day]
        open_ns, close_ns = int(open_dt.timestamp()) * _NS, int(close_dt.timestamp()) * _NS
        if counts.n_defective_rows or counts.n_unowned_defective:
            n, u = defect_rows(day, raw, open_ns, close_ns)
            named.extend({**r, "file_kind": "minute"} for r in n)
            unowned.extend({**r, "file_kind": "minute"} for r in u)
        session_rows.append(
            lc.session_day_result(day, raw.window_start, raw.volume, open_ns, close_ns)
        )
        time.sleep(cfg.throttle_s)
    if day_counts is None or minute_counts is None:
        raise lc.VacuousCheckError(f"era {era}: no day file or no drawn minute file scanned")
    write_json(
        part_path(cfg, "record_sanity", era),
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
            "named_defects": named[:DEFECT_LIST_CAP],  # the displayed listing only
            "n_named_defects": len(named),
            # the gap list is built from every named defect, never from the capped listing
            "named_gap_keys": gap_keys_of(named),
            "unowned_rows": unowned[:UNOWNED_LIST_CAP],
        },
    )
    write_json(
        part_path(cfg, "session", era),
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


def run_survivorship(cfg: Config, archive: Archive, conn: psycopg.Connection) -> dict[str, Any]:
    """Presence by era (names with a held 1d Massive bar per era) and each instrument's first and
    last Massive 1d bar against its recorded listing end. Disclosed, never a gate."""
    with conn.cursor() as cur:
        cur.execute("""SELECT symbol, min("timestamp")::date, max("timestamp")::date
               FROM ohlcv_raw WHERE timeframe = '1d' AND vendor = 'massive' AND kind = 'sip_flat'
               GROUP BY symbol""")
        held = {s: (a, b) for s, a, b in cur.fetchall()}
        cur.execute("""SELECT EXTRACT(year FROM "timestamp")::int AS era, count(DISTINCT symbol)
               FROM ohlcv_raw WHERE timeframe = '1d' AND vendor = 'massive' AND kind = 'sip_flat'
               GROUP BY 1 ORDER BY 1""")
        presence = {int(e): int(n) for e, n in cur.fetchall()}
        cur.execute("SELECT symbol FROM instruments WHERE is_active ORDER BY symbol")
        active = [s for (s,) in cur.fetchall()]
        cur.execute("SELECT symbol, last_session FROM listing_end_current")
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
def assemble_stage_a(cfg: Config) -> dict[str, Any]:
    """Fold the saved parts into the stage A result files and verdicts."""
    sanity = all_parts(cfg, "record_sanity")
    session = all_parts(cfg, "session")
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
       (SELECT string_agg(r->>'vendor' || '/' || r->>'kind', ';' ORDER BY r->>'vendor', r->>'kind')
        FROM jsonb_array_elements(COALESCE(detail->'unadjusted_routes', '[]'::jsonb)) AS r)
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


def freeze_inputs(cfg: Config, conn: psycopg.Connection) -> dict[str, Any]:
    """Write (once) and verify the frozen corporate-action list and ticker-as-of map."""
    from src.intelligence.bars.corporate_actions import is_market_split  # noqa: PLC0415

    fdir = cfg.out / "frozen"
    record_path = fdir / "frozen.json"
    ca_path, span_path = fdir / "corporate_actions.csv", fdir / "ticker_spans.csv"
    if record_path.exists():
        record = json.loads(record_path.read_text())
        for path in (ca_path, span_path):
            if sha256_file(path) != record["sha256"][path.name]:
                raise RuntimeError(f"frozen input {path} no longer matches its recorded hash")
        if "horizon" not in record:
            raise RuntimeError(
                f"{record_path} predates round 5 (no horizon): refreeze in a new --out"
            )
        return dict(record)
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
    """The frozen record (file hashes and splits horizon) a part key carries."""
    record: dict[str, Any] = json.loads((cfg.out / "frozen" / "frozen.json").read_text())
    return {"sha256": record["sha256"], "horizon": record["horizon"]}


def load_frozen_splits(cfg: Config) -> dict[str, list[SplitFactor]]:
    """Market splits per symbol from the frozen file (the horizon is the freeze time, read from
    the frozen record: a split not yet executed then never rescales)."""
    record = json.loads((cfg.out / "frozen" / "frozen.json").read_text())
    horizon = datetime.fromisoformat(record["horizon"])
    rows: dict[str, list[SplitRow]] = {}
    with (cfg.out / "frozen" / "corporate_actions.csv").open() as handle:
        for row in csv.DictReader(handle):
            rows.setdefault(row["symbol"], []).append(
                SplitRow(
                    date.fromisoformat(row["effective_date"]),
                    float(row["factor"]),
                    datetime.fromisoformat(row["recorded_at"]),
                    row["market_fact"] == "True",
                )
            )
    return {s: splits_known_at(r, horizon) for s, r in rows.items()}


#: The incumbent 1d series the calendar audit names unadjusted (daily_rule.RESCALABLE_SERIES).
IBKR_RESCALED_SERIES = "ibkr/smart_trades"


@dataclass(frozen=True)
class Frozen:
    """Everything stage C reads from the frozen record: the market splits Massive is divided by,
    the calendar-audit rescales of the IBKR 1d series (rule 7) and the ticker-as-of spans."""

    splits: dict[str, list[SplitFactor]]
    ibkr_rescales: dict[str, list[SplitFactor]]
    spans: dict[str, list[tuple[date, date | None]]]

    def span_listed(self, name: str, era: int) -> bool:
        """The frozen ticker spans overlap the era."""
        start, end = date(era, 1, 1), date(era, 12, 31)
        return any(a <= end and (b is None or b >= start) for a, b in self.spans.get(name, []))


def load_frozen(cfg: Config) -> Frozen:
    record = json.loads((cfg.out / "frozen" / "frozen.json").read_text())
    horizon = datetime.fromisoformat(record["horizon"])
    rescale_rows: dict[str, list[SplitRow]] = {}
    with (cfg.out / "frozen" / "corporate_actions.csv").open() as handle:
        for row in csv.DictReader(handle):
            if IBKR_RESCALED_SERIES in row["unadjusted_routes"].split(";"):
                # a calendar-audit row rescales the incumbent route whether or not it records the
                # market's split (an operator route correction is a fact about the incumbent)
                rescale_rows.setdefault(row["symbol"], []).append(
                    SplitRow(
                        date.fromisoformat(row["effective_date"]),
                        float(row["factor"]),
                        datetime.fromisoformat(row["recorded_at"]),
                        True,
                    )
                )
    spans: dict[str, list[tuple[date, date | None]]] = {}
    with (cfg.out / "frozen" / "ticker_spans.csv").open() as handle:
        for row in csv.DictReader(handle):
            end = date.fromisoformat(row["valid_to"]) if row["valid_to"] else None
            spans.setdefault(row["symbol"], []).append((date.fromisoformat(row["valid_from"]), end))
    return Frozen(
        load_frozen_splits(cfg),
        {sym: splits_known_at(rows, horizon) for sym, rows in rescale_rows.items()},
        spans,
    )


def rescaled_bars(bars: Bars, splits: list[SplitFactor]) -> Bars:
    """A series carried onto the split-adjusted basis: prices of the sessions on or before each
    split's effective date divided by its factor (the daily rule's route rescale)."""
    scale = lc.split_scale_for_days(bars.key, splits)
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
    if load_part(cfg, "day_vs_minute", era, key):
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
    write_json(part_path(cfg, "day_vs_minute", era), {"key": key, "era": era, "rows": rows})
    logger.info("era_scanned", check="day_vs_minute", era=era, days=len(era_days))


def assemble_day_vs_minute(cfg: Config) -> dict[str, Any]:
    parts = all_parts(cfg, "day_vs_minute")
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


def run_volume_bands(
    cfg: Config,
    conn: psycopg.Connection,
    splits: dict[str, list[SplitFactor]],
    era: int,
    fingerprint: Mapping[str, str],
) -> None:
    """Per name-era median of IBKR (smart_trades) over Massive (sip_flat) 1d volume, the Massive
    volume carried to IBKR's split-adjusted basis by the FROZEN splits. Only sessions where both
    traded count; a name with none is counted unmatched, never assumed."""
    with conn.cursor() as cur:
        cur.execute(_EXCHANGE_SQL)
        exchange = {s: (e or UNKNOWN_EXCHANGE) for s, e in cur.fetchall()}
    key = {
        **sample_key(cfg, raw=scoped_fingerprint(fingerprint, VOLUME_SERIES)),
        "frozen": frozen_hashes(cfg),
        "exchange_map_sha256": _rows_sha256(exchange.items()),
    }
    if load_part(cfg, "volume_bands", era, key):
        return
    start, end = datetime(era, 1, 1, tzinfo=UTC), datetime(era + 1, 1, 1, tzinfo=UTC)
    series: dict[str, dict[str, dict[date, float]]] = {"ibkr": {}, "massive": {}}
    with conn.cursor() as cur:
        for vendor, kind in (("ibkr", "smart_trades"), ("massive", "sip_flat")):
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
        scale = lc.split_scale_for_days(days, splits.get(symbol, []))
        ratio = np.array([ibkr[d] for d in common]) / (
            np.array([massive[d] for d in common]) * scale
        )
        ratios.setdefault(exchange.get(symbol, UNKNOWN_EXCHANGE), {})[symbol] = float(
            np.median(ratio)
        )
    if not ratios:
        raise lc.VacuousCheckError(f"volume_bands: era {era} matched no name")
    write_json(
        part_path(cfg, "volume_bands", era),
        {
            "key": key,
            "era": era,
            "ratios": ratios,
            "unmatched": unmatched,
            "n_massive_names": len(series["massive"]),
        },
    )
    logger.info("era_scanned", check="volume_bands", era=era, names=sum(map(len, ratios.values())))


def assemble_volume_bands(cfg: Config) -> dict[str, Any]:
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
    splits = load_frozen_splits(cfg)
    for era in cfg.eras:
        run_day_vs_minute(cfg, archive, drawn, era)
        run_volume_bands(cfg, conn, splits, era, fingerprints[era])
    verdict = assemble_day_vs_minute(cfg)
    vol = assemble_volume_bands(cfg)
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


def fetch_bars(
    conn: psycopg.Connection,
    timeframe: str,
    vendor: str,
    names: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, Bars]:
    """Raw bars of one (timeframe, vendor) for several names over [start, end), per name."""
    kind = ARM_KINDS[(timeframe, vendor)]
    with conn.cursor() as cur:
        cur.execute(_BARS_SQL, (timeframe, vendor, kind, names, start, end))
        rows = cur.fetchall()
    if not rows:
        return {}
    df = pd.DataFrame.from_records(
        rows, columns=["symbol", "ts", "open", "high", "low", "close", "volume", "served_at"]
    )
    t_all = (
        df["ts"].dt.tz_convert("UTC").dt.tz_localize(None).astype("datetime64[ns]").astype("int64")
    ).to_numpy()
    zone = RAW_DAILY_SESSION_ZONE[(vendor, kind)] if timeframe == "1d" else _NY_ZONE
    keys_all = _session_keys(t_all, zone)
    out: dict[str, Bars] = {}
    for symbol, idx in df.groupby("symbol", sort=False).indices.items():
        sub = df.iloc[idx]
        served = sub["served_at"].dropna()
        out[str(symbol)] = Bars(
            t_all[idx],
            keys_all[idx],
            tuple(sub[c].to_numpy(dtype=float) for c in ("open", "high", "low", "close")),
            sub["volume"].to_numpy(dtype=float, na_value=np.nan),  # NaN stays unknown, not zero
            served.min().date() if len(served) else None,
            served.max().date() if len(served) else None,
        )
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

    def neighbour(shift: int) -> tuple[np.ndarray, ...]:
        j = midx + shift
        ok = (j >= 0) & (j < len(massive.t_ns))
        j = np.clip(j, 0, len(massive.t_ns) - 1)
        return tuple(np.where(ok, a[j], np.nan) for a in massive.ohlc)

    rank = np.cumsum(keep) - 1  # each kept incumbent bar's position in the filtered series
    counts = nc.price_agreement(
        m_ohlc,
        scale,
        inc_ohlc,
        nc.INCUMBENT_INCREMENT[arm],
        massive_prev_raw=neighbour(-1),
        massive_next_raw=neighbour(1),  # type: ignore[arg-type]
        last_bucket=last_bucket_mask(inc.t_ns[hit], sessions) if five else None,
        massive_pos=midx,
        incumbent_pos=rank[hit],
    )
    median_log = nc.scale_check(m_ohlc[3], scale, inc_ohlc[3])
    dispersion = nc.level_dispersion(m_ohlc[3], scale, inc_ohlc[3])
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
        median_log,
        corr,
        zero_volume,
        len(missing),
        listed,
        counts.n_ret_pairs,
        counts.n_ret_agree,
        counts.n_intra,
        counts.n_intra_agree,
        dispersion,
        nc.scale_class(median_log, dispersion, counts.share, counts.ret_share),
        unknown_volume,
        {str(b): n for b, n in counts.lp_hist.items()},
    )


@dataclass(frozen=True)
class NameJudgement:
    outcome: str
    reason: str
    judged: tuple[str, ...]  # timeframes with a detector: the names that feed the era counters


def judged_timeframes(
    results: Mapping[str, ArmResult | None],
    preclass: str,
    listed_in_era: bool,
    massive_hole: bool = False,
) -> tuple[str, str, tuple[str, ...]]:
    """(outcome, reason, timeframes) of the gates before any price verdict: a name-era that is not
    listed, on the non-split convention list, without a detector (fewer than
    ``NAME_ERA_MIN_PAIRS`` consecutive pairs) or with an unresolved identity is judged by nothing.
    A Massive hole (the frozen span lists the name, the incumbent traded, Massive holds nothing) is
    flagged first: a data defect, never not_listed and never stop-exempt. An empty outcome means
    the name-era is judged on the returned timeframes."""
    if massive_hole:
        return nc.OUTCOME_FLAGGED, "massive_hole", ()
    if not listed_in_era:
        return nc.OUTCOME_NOT_LISTED, "not_listed_in_era", ()
    if preclass == nc.ERA_NON_SPLIT:
        return nc.OUTCOME_NO_DETECTOR, "non_split_adjustment_convention", ()
    # identity from the daily returns, else from the 5m returns; unresolved when the judging
    # correlation is under 0.9 or both are thin (a missing correlation is never a pass)
    present = [r for r in (results.get("1d"), results.get("5m")) if r is not None]
    judging = next((r.correlation for r in present if math.isfinite(r.correlation)), math.nan)
    if any(r.n_matched > 0 for r in present) and not nc.identity_resolved(judging):
        return nc.OUTCOME_UNRESOLVED, "identity_unresolved", ()
    usable = tuple(
        tf for tf in ("1d", "5m") if results.get(tf) is not None and nc.has_detector(results[tf].counts())  # type: ignore[union-attr]
    )
    if not usable:
        return nc.OUTCOME_NO_DETECTOR, "no_detector", ()
    return "", "", usable


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
    outcome, reason, usable = judged_timeframes(results, preclass, listed_in_era, massive_hole)
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
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        wait_out_nightly_window()
        m5 = data[("5m", "massive")].get(name)
        dayfile = data[("1d", "massive")].get(name)
        massive_rows = m5 is not None or dayfile is not None
        span_listed = frozen.span_listed(name, era)
        listed = span_listed or massive_rows
        # the frozen span lists the name and an incumbent traded, yet Massive holds nothing: a hole
        incumbent_traded = any(
            _has_traded(data.get((tf, arm), {}).get(name))
            for tf in ("1d", "5m")
            for arm in ("ibkr", "alpaca")
        )
        massive_hole = span_listed and not massive_rows and incumbent_traded
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
                        inc = rescaled_bars(
                            inc, ibkr_rescale
                        )  # rule 7: the audit's unadjusted series
                    results[arm][tf] = compare_arm(tf, arm, massive, inc, sp, sessions)
        alp = data.get(("1d", "alpaca"), {}).get(name)
        seam = bool(alp) and nc.alpaca_epoch_seam_possible(
            alp.served_min, alp.served_max, [s.effective_date for s in in_window]
        )
        ibkr_classes = {tf: (r.scale_class if r else "") for tf, r in results["ibkr"].items()}
        out[name] = {
            "listed": listed,
            "massive_hole": massive_hole,
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
                c in (nc.SCALE_ADJUSTMENT_LEVEL, nc.SCALE_LEVEL_DRIFT)
                for c in ibkr_classes.values()
            ),
            "splits_in_window": [f"{x.effective_date}:{x.factor}" for x in in_window],
            "arms": {
                a: {tf: (asdict(r) if r else None) for tf, r in rs.items()}
                for a, rs in results.items()
            },
        }
    return out


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
            inc = rescaled_bars(inc, frozen.ibkr_rescales[symbol])  # rule 7
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
        window = set(nc.dispute_window_sessions([d.astype(object) for d in massive.key], day))
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
                agree=result.n_agree,
                share=result.n_agree / result.n_matched,
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


def systemic_stop_eras(cfg: Config) -> dict[int, str]:
    """Eras a systemic verdict of stages A and B stops (session offset, record sanity rate, a
    volume step), from the result files of this run; empty when those stages did not run."""
    stops: dict[int, list[str]] = {}
    path = cfg.out / "stageA_session_verdict.json"
    if path.exists():
        for era, v in json.loads(path.read_text()).items():
            if v["verdict"] == "stop":
                stops.setdefault(int(era), []).append("session")
    path = cfg.out / "stageA_record_sanity.csv"
    if path.exists():
        with path.open() as handle:
            for row in csv.DictReader(handle):
                if row["verdict"] == "stop":
                    stops.setdefault(int(row["era"]), []).append("record_sanity")
    path = cfg.out / "stageB_volume_bands.csv"
    if path.exists():
        with path.open() as handle:
            for row in csv.DictReader(handle):
                if row["verdict"] == "stop":
                    stops.setdefault(int(row["era"]), []).append("volume_step")
    return {e: "+".join(sorted(set(r))) for e, r in stops.items()}


_TAPE_SQL = """
SELECT "timestamp", close FROM ohlcv_raw
WHERE symbol = %s AND timeframe = '1d' AND vendor = 'massive' AND kind = 'sip_flat'
  AND "timestamp" >= %s AND "timestamp" < %s ORDER BY "timestamp"
"""


def massive_split_tape(
    conn: psycopg.Connection, symbol: str, effective: date
) -> tuple[float, float] | None:
    """Massive's raw (unadjusted) close on the last session on or before a split's effective date
    and on the first session after it; None when either side is absent."""
    start = datetime.combine(effective - timedelta(days=10), dtime(0), tzinfo=UTC)
    end = datetime.combine(effective + timedelta(days=10), dtime(0), tzinfo=UTC)
    with conn.cursor() as cur:
        cur.execute(_TAPE_SQL, (symbol, start, end))
        rows = [(raw_session_date("massive", "sip_flat", t), float(c)) for t, c in cur.fetchall()]
    before = [c for d, c in rows if d <= effective]
    after = [c for d, c in rows if d > effective]
    return (before[-1], after[0]) if before and after else None


def ledger_row(
    conn: psycopg.Connection,
    name: str,
    era: int,
    tf: str,
    claimed: str,
    median_log: float | None,
    splits: list[str],
    session_id: str,
) -> dict[str, Any]:
    """One disagreement-ledger row with the two witnesses available without new data: the frozen
    corporate-action list, and Massive's own tape step at the recorded split's date. A case with
    neither stays unresolved; no witness is invented."""
    window = [(s.split(":")[0], float(s.split(":")[1])) for s in splits]
    witnesses: list[nc.Witness] = []
    frozen = None if median_log is None else nc.frozen_split_witness(math.exp(median_log), window)
    if frozen is not None:
        witnesses.append(frozen)
        effective, factor = next(
            (e, f)
            for e, f in window
            if frozen.citation.endswith(f"{e} x{f}")  # the split the witness cites
        )
        tape = massive_split_tape(conn, name, date.fromisoformat(effective))
        if tape is not None:
            tw = nc.massive_tape_witness(tape[0], tape[1], factor, effective)
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


_ACTIVE_SQL = "SELECT symbol FROM instruments WHERE is_active ORDER BY symbol"
#: The raw series stage C reads: every arm of ARM_KINDS.
STAGE_C_SERIES = tuple(sorted((vendor, kind, tf) for (tf, vendor), kind in ARM_KINDS.items()))


def run_stage_c(
    cfg: Config,
    conn: psycopg.Connection,
    max_names: int | None,
    non_split_csv: Path | None,
    disputed_csv: Path | None,
    session_id: str,
    fingerprints: Mapping[int, Mapping[str, str]],
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
        **sample_key(cfg),
        "max_names": max_names,
        "n_names": len(names),
        "non_split_rows": len(non_split),
        "non_split_sha256": _rows_sha256(non_split),
        "frozen": frozen_hashes(cfg),
    }
    keys = {
        era: {
            **base_key,
            "raw_fingerprint": scoped_fingerprint(fingerprints[era], STAGE_C_SERIES),
        }
        for era in cfg.eras
    }
    for era in cfg.eras:
        if load_part(cfg, "name_checks", era, keys[era]):
            continue
        t0 = time.monotonic()
        detail: dict[str, dict[str, Any]] = {}
        for i in range(0, len(names), NAME_BATCH):
            detail.update(
                run_name_era_batch(cfg, conn, names[i : i + NAME_BATCH], era, frozen, non_split)
            )
            time.sleep(cfg.throttle_s)
        write_json(
            part_path(cfg, "name_checks", era), {"key": keys[era], "era": era, "names": detail}
        )
        logger.info(
            "era_scanned",
            check="name_checks",
            era=era,
            names=len(detail),
            seconds=round(time.monotonic() - t0, 1),
        )
    summary = assemble_stage_c(cfg, conn, mapped, unmapped, keys, session_id)
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
        # a stable offset within 10 bp is listed, not systemic; level_drift always counts
        level_class=(
            r.scale_class
            if r.scale_class == nc.SCALE_LEVEL_DRIFT or abs(r.median_log_ratio) > nc.SCALE_LEVEL_TOL
            else ""
        ),
        median_log_ratio=r.median_log_ratio,
    )


def era_verdicts(
    judged: dict[tuple[int, str], list[nc.NameFacts]],
    eras: list[int],
    unresolved: Mapping[int, int] | None = None,
) -> dict[tuple[int, str], nc.EraVerdict]:
    """Verdicts of every (era, timeframe), calibrated on the reference eras present in the run
    (rules 1 to 3). A reference era is calibrated on the OTHER reference eras: against its own
    counters the 3x rule could never fire (a defect in 2014 to 2026 would raise its own bar). A
    run with no other reference era uses the floor and the pooled cap of its own eras."""
    out: dict[tuple[int, str], nc.EraVerdict] = {}
    ref_eras = [e for e in eras if e in nc.REFERENCE_ERAS]
    for tf in ("1d", "5m"):
        counters = {
            e: nc.era_counters(judged.get((e, tf), []), (unresolved or {}).get(e, 0)) for e in eras
        }
        hists = {e: [f.counts.lp_hist for f in judged.get((e, tf), [])] for e in eras}
        for era in eras:
            ref = [e for e in ref_eras if e != era]
            thresholds = nc.counter_thresholds(counters[e] for e in ref)
            cap = nc.last_print_cap_bin(h for e in (ref or eras) for h in hists[e])
            verdict = nc.judge_era(
                tf, judged.get((era, tf), []), thresholds, cap, (unresolved or {}).get(era, 0)
            )
            calibration = ",".join(map(str, ref)) if ref else "self"
            out[(era, tf)] = replace(verdict, calibration=calibration)
    return out


def assemble_stage_c(
    cfg: Config,
    conn: psycopg.Connection,
    mapped: list[str],
    unmapped: list[str],
    keys: dict[int, dict[str, Any]],
    session_id: str,
) -> dict[str, Any]:
    parts = {e: p for e, p in all_parts(cfg, "name_checks").items() if p["key"] == keys.get(e)}
    eras = sorted(parts)
    judged: dict[tuple[int, str], list[nc.NameFacts]] = {}
    arm_results: dict[tuple[str, int], dict[str, ArmResult | None]] = {}
    unresolved: dict[int, int] = {}  # names per era whose identity correlation failed
    for era in eras:
        for name, d in sorted(parts[era]["names"].items()):
            results = {tf: _arm_result(d, "ibkr", tf) for tf in ("1d", "5m")}
            gate = judged_timeframes(results, d["preclass"], d["listed"], d["massive_hole"])
            arm_results[(name, era)] = results
            if gate[1] == "identity_unresolved":
                unresolved[era] = unresolved.get(era, 0) + 1
            for tf in gate[2]:
                facts = _name_facts(name, d, tf, gate[2])
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
    for era in eras:
        one_d_unresolved = verdicts[(era, "1d")].verdict == nc.ERA_UNRESOLVED
        for name, d in sorted(parts[era]["names"].items()):
            j = judge_name_era(
                arm_results[(name, era)],
                d["preclass"],
                d["listed"],
                one_d_unresolved=one_d_unresolved,
                massive_hole=d["massive_hole"],
            )
            outcomes[(name, era)] = (j.outcome, j.reason)
            row: dict[str, Any] = {
                "name": name,
                "era": era,
                "outcome": j.outcome,
                "reason": j.reason,
                "preclass": d["preclass"],
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
                ledger.append(
                    ledger_row(
                        conn, name, era, tf, f"level_class:{cls}", r["median_log_ratio"],
                        d["splits_in_window"], session_id,
                    )
                )  # fmt: skip
            if j.outcome == nc.OUTCOME_FLAGGED and j.reason.startswith("price_agreement"):
                tf = j.reason.rsplit("_", 1)[1]
                r = d["arms"]["ibkr"].get(tf)
                ledger.append(
                    ledger_row(
                        conn, name, era, tf, j.reason, r["median_log_ratio"] if r else None,
                        d["splits_in_window"], session_id,
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
    stops = {**systemic_stop_eras(cfg)}
    for (era, tf), v in sorted(verdicts.items()):
        if v.verdict == nc.ERA_STOP:
            reason = f"{tf}:" + "+".join(v.reasons)
            stops[era] = f"{stops[era]}+{reason}" if era in stops else reason
    unresolved_1d = sorted(e for e in eras if verdicts[(e, "1d")].verdict == nc.ERA_UNRESOLVED)
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
    verdicts = assemble_stage_a(cfg)
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
        default="agent-a982cb955333e9a38",
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
        fingerprints = raw_fingerprints(conn, cfg.eras) if stages & {"B", "C"} else {}
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


if __name__ == "__main__":
    sys.exit(main())
