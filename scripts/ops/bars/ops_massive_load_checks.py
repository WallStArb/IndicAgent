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
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
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
from src.intelligence.bars.daily_rule import raw_session_date  # noqa: E402
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


def sanity_of(raw: RawFile) -> lc.SanityCounts:
    return lc.record_sanity(
        raw.code, raw.window_start, raw.open, raw.high, raw.low, raw.close, raw.volume
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


def sample_key(cfg: Config) -> dict[str, object]:
    return {"seed": cfg.seed, "days_per_era": cfg.days_per_era}


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


NONPOSITIVE_EXAMPLE_CAP = 50  # rows listed per era in the report; the counts are exact


def nonpositive_examples(
    day: date, raw: RawFile, open_ns: int, close_ns: int
) -> list[dict[str, Any]]:
    """Minute rows with a non-positive or missing price, listed with whether they sit inside the
    regular session (a disclosure aid; the verdict rests on the exact counts)."""
    ok = (raw.open > 0) & (raw.high > 0) & (raw.low > 0) & (raw.close > 0)
    out = []
    for i in np.flatnonzero(~ok)[:NONPOSITIVE_EXAMPLE_CAP]:
        out.append(
            {
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
        )
    return out


def blank_ticker_nonpositive(raw: RawFile) -> int:
    """Rows with an empty ticker string and a non-positive price (junk rows no instrument owns)."""
    ok = (raw.open > 0) & (raw.high > 0) & (raw.low > 0) & (raw.close > 0)
    blank = np.isin(raw.code, np.flatnonzero(raw.tickers == ""))
    return int(np.count_nonzero(blank & ~ok))


def run_record_sanity_and_session(
    cfg: Config, archive: Archive, sessions: list[date], drawn: list[date], era: int
) -> None:
    """Stage A scans of one era: day-file sanity over EVERY day file of the era, minute-file
    sanity and the session offset over the era's drawn days."""
    key = sample_key(cfg)
    if all(load_part(cfg, c, era, key) for c in ("record_sanity", "session")):
        logger.info("era_reused", check="stage_a_scans", era=era)
        return
    t0 = time.monotonic()
    day_counts: lc.SanityCounts | None = None
    n_day_files = 0
    for day in (d for d in sessions if lc.era_of(d) == era and d in archive.manifest[DAY]):
        wait_out_nightly_window()
        counts = sanity_of(read_raw_file(day_path(cfg.data_dir, DAY, day)))
        day_counts = counts if day_counts is None else day_counts + counts
        n_day_files += 1
        time.sleep(cfg.throttle_s)
    minute_counts: lc.SanityCounts | None = None
    session_rows: list[lc.SessionDayResult] = []
    examples: list[dict[str, Any]] = []
    blank_nonpositive = 0
    era_days = [d for d in drawn if lc.era_of(d) == era]
    bounds = nyse_sessions(era_days[0], era_days[-1]) if era_days else {}
    for day in era_days:
        wait_out_nightly_window()
        raw = read_raw_file(day_path(cfg.data_dir, MINUTE, day))
        counts = sanity_of(raw)
        minute_counts = counts if minute_counts is None else minute_counts + counts
        open_dt, close_dt = bounds[day]
        blank_nonpositive += blank_ticker_nonpositive(raw)
        examples.extend(
            nonpositive_examples(
                day, raw, int(open_dt.timestamp()) * _NS, int(close_dt.timestamp()) * _NS
            )
        )
        session_rows.append(
            lc.session_day_result(
                day,
                raw.window_start,
                raw.volume,
                int(open_dt.timestamp()) * _NS,
                int(close_dt.timestamp()) * _NS,
            )
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
            "nonpositive_examples": examples[:NONPOSITIVE_EXAMPLE_CAP],
            "blank_ticker_nonpositive_rows": blank_nonpositive,
            "minute_files": {
                **asdict(minute_counts),
                "n_files": len(era_days),
                "verdict": lc.sanity_verdict(minute_counts),
            },
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
            counts = part[kind]
            san_rows.append({"era": era, "file_kind": kind, **counts})
    fields = [
        "era",
        "file_kind",
        "n_files",
        "n_rows",
        "n_ohlc_inconsistent",
        "n_nonpositive_price",
        "n_negative_volume",
        "n_duplicate_keys",
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
    examples = [
        {"era": era, **row}
        for era, part in sorted(sanity.items())
        for row in part.get("nonpositive_examples", [])
    ]
    write_csv(
        cfg.out / "stageA_nonpositive_examples.csv",
        examples,
        [
            "era",
            "day",
            "ticker",
            "window_start_ns",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "in_rth",
        ],
    )
    by_era = lc.session_verdict_by_era(results)
    write_json(cfg.out / "stageA_session_verdict.json", by_era)
    blank = sum(p.get("blank_ticker_nonpositive_rows", 0) for p in sanity.values())
    nonpositive = sum(r["n_nonpositive_price"] for r in san_rows)
    return {
        "record_sanity_nonpositive_rows": nonpositive,
        "record_sanity_nonpositive_blank_ticker_rows": blank,
        "record_sanity_nonpositive_named_rows": nonpositive - blank,
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
SELECT symbol, effective_date, factor, recorded_at, inferred_by, (detail ? 'rows_file')
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
            }
            for s, d, f, r, by, rf in cur.fetchall()
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
    record = {
        "frozen_at": datetime.now(UTC).isoformat(),
        "sha256": {ca_path.name: sha256_file(ca_path), span_path.name: sha256_file(span_path)},
        "n_corporate_actions": len(ca_rows),
        "n_ticker_spans": len(span_rows),
    }
    write_json(record_path, record)
    logger.info("inputs_frozen", **record)
    return record


def load_frozen_splits(cfg: Config) -> dict[str, list[SplitFactor]]:
    """Market splits per symbol from the frozen file (the horizon is the freeze time)."""
    record = json.loads((cfg.out / "frozen" / "frozen.json").read_text())
    horizon = datetime.fromisoformat(record["frozen_at"])
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


# ------------------------------------------------------------- stage B: day against minute
def day_file_by_ticker(raw: RawFile) -> dict[str, tuple[float, float, float, float, float]]:
    return {
        str(t): (float(o), float(h), float(low), float(c), float(v))
        for t, o, h, low, c, v in zip(
            raw.tickers[raw.code], raw.open, raw.high, raw.low, raw.close, raw.volume, strict=True
        )
    }


def run_day_vs_minute(cfg: Config, archive: Archive, drawn: list[date], era: int) -> None:
    key = sample_key(cfg)
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
SELECT replace(request_key, '@active', ''), body->'results'->>'primary_exchange'
FROM reference_raw WHERE vendor = 'massive' AND endpoint = 'overview'
  AND request_key LIKE '%%@active'
"""
UNKNOWN_EXCHANGE = "UNKNOWN"


def run_volume_bands(
    cfg: Config, conn: psycopg.Connection, splits: dict[str, list[SplitFactor]], era: int
) -> None:
    """Per name-era median of IBKR (smart_trades) over Massive (sip_flat) 1d volume, the Massive
    volume carried to IBKR's split-adjusted basis by the FROZEN splits. Only sessions where both
    traded count; a name with none is counted unmatched, never assumed."""
    key = sample_key(cfg)
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
        cur.execute(_EXCHANGE_SQL)
        exchange = {s: (e or UNKNOWN_EXCHANGE) for s, e in cur.fetchall()}
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
    unmatched = {era: len(p["unmatched"]) for era, p in sorted(parts.items())}
    write_json(cfg.out / "stageB_volume_unmatched.json", unmatched)
    return {
        "volume_bands": "stop" if any(r.verdict == "stop" for r in rows) else "ok",
        "n_cells": len(rows),
        "cells_stop": [[r.era, r.exchange] for r in rows if r.verdict == "stop"],
    }


def run_stage_b(cfg: Config, archive: Archive, conn: psycopg.Connection) -> dict[str, Any]:
    sessions = archive_sessions(archive)
    drawn = draw_days(cfg, archive, sessions)
    freeze_inputs(cfg, conn)
    splits = load_frozen_splits(cfg)
    for era in cfg.eras:
        run_day_vs_minute(cfg, archive, drawn, era)
        run_volume_bands(cfg, conn, splits, era)
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
    zone = "UTC" if (timeframe, vendor) == ("1d", "ibkr") else _NY_ZONE
    keys_all = _session_keys(t_all, zone)
    out: dict[str, Bars] = {}
    for symbol, idx in df.groupby("symbol", sort=False).indices.items():
        sub = df.iloc[idx]
        served = sub["served_at"].dropna()
        out[str(symbol)] = Bars(
            t_all[idx],
            keys_all[idx],
            tuple(sub[c].to_numpy(dtype=float) for c in ("open", "high", "low", "close")),
            sub["volume"].fillna(0).to_numpy(dtype=float),
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
    n_agree: int
    n_agree_all: int
    classes: dict[str, int]
    median_log_ratio: float
    correlation: float
    n_incumbent_zero_volume: int
    n_incumbent_traded_missing: int
    missing_listed: list[str]


def compare_arm(
    timeframe: str,
    arm: str,
    massive: Bars,
    inc: Bars,
    splits: list[SplitFactor],
    sessions: dict[date, tuple[datetime, datetime]],
) -> ArmResult | None:
    """Massive against one incumbent arm for one name-era. None when the arm holds no bar."""
    if len(inc.t_ns) == 0:
        return None
    five = timeframe == "5m"
    keep = rth_mask(inc.t_ns, sessions) if five else np.ones(len(inc.t_ns), dtype=bool)
    zero_volume = int(np.count_nonzero(keep & ~(inc.volume > 0)))
    keep &= inc.volume > 0  # traded buckets only
    join_inc = inc.t_ns if five else inc.key.astype("int64")
    join_m = massive.t_ns if five else massive.key.astype("int64")
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
        return ArmResult(0, 0, 0, {}, math.nan, math.nan, zero_volume, len(missing), listed)
    inc_ohlc = tuple(a[hit] for a in inc.ohlc)
    m_ohlc = tuple(a[midx] for a in massive.ohlc)
    day_keys = massive.key[midx]
    scale = lc.split_scale_for_days(day_keys, splits)

    def neighbour(shift: int) -> tuple[np.ndarray, ...]:
        j = midx + shift
        ok = (j >= 0) & (j < len(massive.t_ns))
        j = np.clip(j, 0, len(massive.t_ns) - 1)
        return tuple(np.where(ok, a[j], np.nan) for a in massive.ohlc)

    increment = nc.INCUMBENT_INCREMENT[arm]
    counts = nc.price_agreement(
        m_ohlc,
        scale,
        inc_ohlc,
        increment,
        massive_prev_raw=neighbour(-1),
        massive_next_raw=neighbour(1),  # type: ignore[arg-type]
        last_bucket=last_bucket_mask(inc.t_ns[hit], sessions) if five else None,
    )
    median_log = nc.scale_check(m_ohlc[3], scale, inc_ohlc[3])
    corr = nc.identity_correlation(m_ohlc[3] / scale, inc_ohlc[3]) if not five else math.nan
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
    )


def judge_name_era(
    results: dict[str, ArmResult | None], preclass: str, listed_in_era: bool
) -> tuple[str, str]:
    """(outcome, reason) of one name-era from the IBKR arm; Alpaca never judges."""
    if not listed_in_era:
        return nc.OUTCOME_GAP, "not_listed_in_era"
    if preclass == nc.ERA_NON_SPLIT:
        return nc.OUTCOME_GAP, "non_split_adjustment_convention"
    r1, r5 = results.get("1d"), results.get("5m")
    judged = [r for r in (r1, r5) if r is not None and r.n_matched > 0]
    if not judged:
        return nc.OUTCOME_GAP, "no_incumbent_overlap"
    if r1 is not None and r1.n_matched > 0 and not nc.identity_resolved(r1.correlation):
        return nc.OUTCOME_GAP, "identity_unresolved"
    for label, r in (("1d", r1), ("5m", r5)):
        if r is None or r.n_matched == 0:
            continue
        counts = nc.AgreementCounts(r.n_matched, r.n_agree, r.n_agree_all, r.classes)
        if not nc.name_era_agreement_ok(counts):
            return nc.OUTCOME_GAP, f"price_agreement_{label}"
        if not nc.scale_ok(r.median_log_ratio):
            return nc.OUTCOME_GAP, f"scale_factor_{label}"
    return nc.OUTCOME_PASS, ""


def run_name_era_batch(
    cfg: Config,
    conn: psycopg.Connection,
    names: list[str],
    era: int,
    splits: dict[str, list[SplitFactor]],
    non_split: set[str],
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
        listed = name in data[("1d", "massive")] or name in data[("5m", "massive")]
        sp = splits.get(name, [])
        in_window = [s for s in sp if date(era, 1, 1) <= s.effective_date <= date(era, 12, 31)]
        preclass = nc.preclassify_name_era(len(in_window), name in non_split)
        results: dict[str, dict[str, ArmResult | None]] = {"ibkr": {}, "alpaca": {}}
        if listed:
            for timeframe in ("1d", "5m"):
                massive = data[(timeframe, "massive")].get(name)
                for arm in results:
                    inc = data.get((timeframe, arm), {}).get(name)
                    if massive is None or inc is None:
                        results[arm][timeframe] = None
                        continue
                    results[arm][timeframe] = compare_arm(
                        timeframe, arm, massive, inc, sp, sessions
                    )
        outcome, reason = judge_name_era(results["ibkr"], preclass, listed)
        alp = data.get(("1d", "alpaca"), {}).get(name)
        seam = bool(alp) and nc.alpaca_epoch_seam_possible(
            alp.served_min, alp.served_max, [s.effective_date for s in in_window]
        )
        out[name] = {
            "outcome": outcome,
            "reason": reason,
            "preclass": preclass,
            "alpaca_epoch_seam_possible": seam,
            "splits_in_window": [f"{x.effective_date}:{x.factor}" for x in in_window],
            "arms": {
                a: {tf: (asdict(r) if r else None) for tf, r in rs.items()}
                for a, rs in results.items()
            },
        }
    return out


def run_disputed_windows(
    cfg: Config, conn: psycopg.Connection, disputed_csv: Path, splits: dict[str, list[SplitFactor]]
) -> dict[str, Any]:
    """1d census at the disputed dates: ten sessions either side of each (symbol, date) of the
    supplied file (the todo 592 witness rows), Massive against the IBKR arm."""
    cases: list[tuple[str, date]] = []
    with disputed_csv.open() as handle:
        for row in csv.DictReader(handle):
            try:
                cases.append((row["symbol"], date.fromisoformat(row["date"])))
            except (KeyError, ValueError):
                continue
    rows: list[dict[str, Any]] = []
    for symbol, day in sorted(set(cases)):
        wait_out_nightly_window()
        start = datetime.combine(day - timedelta(days=40), dtime(0), tzinfo=UTC)
        end = datetime.combine(day + timedelta(days=40), dtime(0), tzinfo=UTC)
        massive = fetch_bars(conn, "1d", "massive", [symbol], start, end).get(symbol)
        inc = fetch_bars(conn, "1d", "ibkr", [symbol], start, end).get(symbol)
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
        result = compare_arm("1d", "ibkr", massive, trimmed, splits.get(symbol, []), {})
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


def _arm_counts(detail: dict[str, Any], arm: str, timeframe: str) -> nc.AgreementCounts | None:
    r = detail["arms"][arm].get(timeframe)
    if not r or r["n_matched"] == 0:
        return None
    return nc.AgreementCounts(r["n_matched"], r["n_agree"], r["n_agree_all"], r["classes"])


def run_stage_c(
    cfg: Config,
    conn: psycopg.Connection,
    max_names: int | None,
    non_split_csv: Path | None,
    disputed_csv: Path | None,
) -> dict[str, Any]:
    freeze_inputs(cfg, conn)
    splits = load_frozen_splits(cfg)
    with (cfg.out / "frozen" / "ticker_spans.csv").open() as handle:
        mapped = sorted({row["symbol"] for row in csv.DictReader(handle)})
    names = mapped
    if max_names is not None:
        names = sorted(random.Random(cfg.seed).sample(mapped, min(max_names, len(mapped))))
    non_split: set[str] = set()
    if non_split_csv is not None:
        with non_split_csv.open() as handle:
            non_split = {row["symbol"] for row in csv.DictReader(handle)}
    key = {**sample_key(cfg), "max_names": max_names, "n_names": len(names)}
    for era in cfg.eras:
        if load_part(cfg, "name_checks", era, key):
            continue
        t0 = time.monotonic()
        detail: dict[str, dict[str, Any]] = {}
        for i in range(0, len(names), NAME_BATCH):
            detail.update(
                run_name_era_batch(cfg, conn, names[i : i + NAME_BATCH], era, splits, non_split)
            )
            time.sleep(cfg.throttle_s)
        write_json(part_path(cfg, "name_checks", era), {"key": key, "era": era, "names": detail})
        logger.info(
            "era_scanned",
            check="name_checks",
            era=era,
            names=len(detail),
            seconds=round(time.monotonic() - t0, 1),
        )
    summary = assemble_stage_c(cfg, mapped, names, key)
    summary["non_split_adjustment_list"] = "supplied" if non_split_csv else "not supplied"
    summary["disputed_windows"] = (
        run_disputed_windows(cfg, conn, disputed_csv, splits) if disputed_csv else "not supplied"
    )
    return summary


def assemble_stage_c(
    cfg: Config, mapped: list[str], names: list[str], key: dict[str, Any]
) -> dict[str, Any]:
    parts = {e: p for e, p in all_parts(cfg, "name_checks").items() if p["key"] == key}
    rows: list[dict[str, Any]] = []
    vendor_by_era: dict[int, dict[str, Any]] = {}
    stop_eras: list[int] = []
    classes_total: Counter[str] = Counter()
    ledger: list[dict[str, Any]] = []
    scale_rows: list[dict[str, Any]] = []
    outcomes: dict[tuple[str, int], tuple[str, str]] = {}
    unmatched_rows: list[dict[str, Any]] = []
    for era, part in sorted(parts.items()):
        by_tf: dict[str, list[nc.AgreementCounts]] = {"1d": [], "5m": []}
        by_tf_clean: dict[str, list[nc.AgreementCounts]] = {"1d": [], "5m": []}
        for name, d in sorted(part["names"].items()):
            outcomes[(name, era)] = (d["outcome"], d["reason"])
            row = {
                "name": name,
                "era": era,
                "outcome": d["outcome"],
                "reason": d["reason"],
                "preclass": d["preclass"],
                "alpaca_epoch_seam_possible": d["alpaca_epoch_seam_possible"],
            }
            for arm in ("ibkr", "alpaca"):
                for tf in ("1d", "5m"):
                    r = d["arms"][arm].get(tf)
                    p = f"{arm}_{tf}"
                    row[f"{p}_matched"] = r["n_matched"] if r else 0
                    row[f"{p}_agree"] = r["n_agree"] if r else 0
                    row[f"{p}_agree_all_ohlc"] = r["n_agree_all"] if r else 0
                    row[f"{p}_median_log_ratio"] = r["median_log_ratio"] if r else ""
                    row[f"{p}_zero_volume_incumbent"] = r["n_incumbent_zero_volume"] if r else 0
                    row[f"{p}_incumbent_traded_missing"] = (
                        r["n_incumbent_traded_missing"] if r else 0
                    )
                    if r:
                        for item in r["missing_listed"]:
                            unmatched_rows.append(
                                {"name": name, "era": era, "arm": arm, "timeframe": tf, "bar": item}
                            )
            rows.append(row)
            # vendor-wide counts: IBKR arm only, name-eras whose price check applies
            if d["reason"] not in (
                "identity_unresolved",
                "non_split_adjustment_convention",
                "not_listed_in_era",
            ):
                for tf in ("1d", "5m"):
                    c = _arm_counts(d, "ibkr", tf)
                    if c:
                        by_tf[tf].append(c)
                        classes_total.update(c.n_class)
                        r = d["arms"]["ibkr"][tf]
                        if nc.scale_ok(r["median_log_ratio"]):
                            by_tf_clean[tf].append(c)
                        else:
                            scale_rows.append(
                                {
                                    "name": name,
                                    "era": era,
                                    "timeframe": tf,
                                    "median_log_ratio": r["median_log_ratio"],
                                    "implied_factor": math.exp(r["median_log_ratio"]),
                                    "frozen_splits_in_window": ";".join(d["splits_in_window"]),
                                    "preclass": d["preclass"],
                                }
                            )
            if d["outcome"] == nc.OUTCOME_GAP and d["reason"].startswith(
                ("price_agreement", "scale_factor")
            ):
                ledger.append(
                    {
                        "name": name,
                        "span": str(era),
                        "claimed_defect": d["reason"],
                        "witnesses": "ibkr arm only; no third witness recorded",
                        "verdict": nc.VERDICT_UNRESOLVED,
                        "deciding_session_id": "",
                    }
                )
        vendor_by_era[era] = {}
        for tf, cs in by_tf.items():
            if cs:
                w = nc.vendor_wide(cs)
                vendor_by_era[era][tf] = asdict(w)
                if by_tf_clean[tf]:
                    # sensitivity only: the verdict above counts every judged name-era
                    vendor_by_era[era][f"{tf}_excluding_scale_failures"] = asdict(
                        nc.vendor_wide(by_tf_clean[tf])
                    )
                if w.verdict == "stop":
                    stop_eras.append(era)
            else:
                vendor_by_era[era][tf] = None
    write_csv(cfg.out / "stageC_name_era_checks.csv", rows, list(rows[0]) if rows else ["name"])
    write_csv(
        cfg.out / "stageC_scale_factor.csv",
        scale_rows,
        [
            "name",
            "era",
            "timeframe",
            "median_log_ratio",
            "implied_factor",
            "frozen_splits_in_window",
            "preclass",
        ],
    )
    write_csv(
        cfg.out / "stageC_unmatched_incumbent_bars.csv",
        unmatched_rows,
        ["name", "era", "arm", "timeframe", "bar"],
    )
    write_csv(
        cfg.out / "stageC_disagreement_ledger.csv",
        ledger,
        ["name", "span", "claimed_defect", "witnesses", "verdict", "deciding_session_id"],
    )
    write_json(cfg.out / "stageC_vendor_wide.json", vendor_by_era)
    expected = [(n, e) for n in mapped for e in cfg.eras]
    closed = nc.close_partition(expected, outcomes, stop_eras=sorted(set(stop_eras)))
    gap_additions = sorted(
        {f"{n}|{e}|{r}" for (n, e), (o, r) in outcomes.items() if o == nc.OUTCOME_GAP}
    )
    write_json(cfg.out / "stageC_gap_list_additions.json", gap_additions)
    summary: dict[str, Any] = {
        "names_judged": len(names),
        "mapped_names": len(mapped),
        "eras": sorted(parts),
        "vendor_wide_stop_eras": sorted(set(stop_eras)),
        "vendor_wide_other_share_investigate_eras": sorted(
            e for e, v in vendor_by_era.items() for x in v.values() if x and x["investigate"]
        ),
        "disagreement_classes_total": dict(classes_total),
        "ledger_rows": len(ledger),
        "scale_failure_name_era_timeframes": len(scale_rows),
        "gap_list_cell_count": len(gap_additions),
        "vendor_wide_agreement": "stop" if stop_eras else "ok",
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
    verdicts["manifest_complete"] = all(v["complete"] for v in completeness.values())
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
    parser.add_argument("--max-names", type=int, default=None, help="stage C: seeded name sample")
    parser.add_argument(
        "--non-split-csv",
        type=Path,
        default=None,
        help="stage C: symbol column, the non-split adjustment name list",
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
    with psycopg.connect(get_settings().database_url) as conn:
        conn.read_only = True
        if "A" in stages:
            summary["stage_a"] = run_stage_a(cfg, archive, conn)
        if "B" in stages:
            summary["stage_b"] = run_stage_b(cfg, archive, conn)
        if "C" in stages:
            summary["stage_c"] = run_stage_c(
                cfg, conn, args.max_names, args.non_split_csv, args.disputed_csv
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
        and cfg.eras == tuple(range(2003, 2027))
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
