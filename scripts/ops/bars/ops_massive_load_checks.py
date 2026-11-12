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
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from datetime import time as dtime
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.csv as pacsv

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import psycopg  # noqa: E402
import structlog  # noqa: E402

from src.config.settings import get_settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.intelligence.bars import massive_load_checks as lc  # noqa: E402
from src.intelligence.bars.sessions import nyse_sessions  # noqa: E402

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
    era_days = [d for d in drawn if lc.era_of(d) == era]
    bounds = nyse_sessions(era_days[0], era_days[-1]) if era_days else {}
    for day in era_days:
        wait_out_nightly_window()
        raw = read_raw_file(day_path(cfg.data_dir, MINUTE, day))
        counts = sanity_of(raw)
        minute_counts = counts if minute_counts is None else minute_counts + counts
        open_dt, close_dt = bounds[day]
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
    by_era = lc.session_verdict_by_era(results)
    write_json(cfg.out / "stageA_session_verdict.json", by_era)
    return {
        "record_sanity": "stop" if any(r["verdict"] == "stop" for r in san_rows) else "ok",
        "session": "stop" if any(v["verdict"] == "stop" for v in by_era.values()) else "ok",
        "eras_with_parts": sorted(sanity),
    }


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
    parser.add_argument("--stages", default="A", help="comma list of stages")
    parser.add_argument("--eras", default="2003-2026", help="e.g. 2010 or 2003-2026")
    parser.add_argument("--days-per-era", type=int, default=6, help="seeded minute-file draw")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--throttle-s", type=float, default=0.0)
    parser.add_argument("--force", action="store_true")
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
    systemic = {
        f"{stage}.{k}": v
        for stage in ("stage_a", "stage_b")
        for k, v in summary.get(stage, {}).items()
        if v in ("stop", "ok")
    }
    summary["systemic_verdicts"] = systemic
    summary["status"] = "partial"  # stage C (name-level partition) not run: never a result table
    summary["partition"] = None
    write_json(cfg.out / "summary.json", summary)
    logger.info("summary_written", status=summary["status"], systemic=systemic)
    print(json.dumps({"status": summary["status"], "systemic_verdicts": systemic}, indent=2))
    return 1 if "stop" in systemic.values() else 0


if __name__ == "__main__":
    sys.exit(main())
