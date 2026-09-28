#!/usr/bin/env python3
"""D-38 Postgres settings baseline capture (phase 186 plan 05, design 14.5).

Takes the "before" measurement that plan 186-17 tunes against: running
pg_settings vs production/docker-compose.yml drift, buffer hit ratio, temp-file
spills, the top pg_stat_statements spillers, container facts, and host RAM.
186-17 re-takes the baseline with this same script and compares.

READ-ONLY, non-negotiable (T-186-05-06): every statement here is a SELECT or a
`docker inspect`. This script never runs ALTER SYSTEM, never writes
postgresql.auto.conf, never recreates or restarts anything -- tuning belongs to
186-17, under the performance-investigation SOP (measure first).

Usage:
    python scripts/ops/db/ops_pg_settings_baseline.py \
        --out .planning/phases/186-.../186-05-pg-baseline.json [--top 20]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import psycopg
import yaml

from src.config.settings import Settings

# Settings captured in the baseline. Memory settings feed the 186-17 tuning
# conversation; the non-memory ones (max_parallel_workers*, temp_file_limit,
# dynamic_shared_memory_type, hash_mem_multiplier) decide its assumptions
# (A2: dynamic_shared_memory_type picks the /dev/shm story).
_TRACKED_SETTINGS = (
    "shared_buffers",
    "work_mem",
    "maintenance_work_mem",
    "effective_cache_size",
    "max_wal_size",
    "max_parallel_workers",
    "max_parallel_workers_per_gather",
    "hash_mem_multiplier",
    "temp_file_limit",
    "dynamic_shared_memory_type",
)

_CONTAINER = "timescaledb"

# Postgres memory units -> byte factors (pg_settings.unit vocabulary).
_UNIT_FACTORS: dict[str, int] = {
    "B": 1,
    "kB": 1024,
    "8kB": 8192,
    "MB": 1024**2,
    "GB": 1024**3,
    "TB": 1024**4,
}

# Suffixed strings like "64MB" / "3GB" (compose command style). Compose also
# allows lowercase ("512m") for shm_size, so accept both cases.
_SUFFIX_FACTORS: dict[str, int] = {
    "B": 1,
    "K": 1024,
    "KB": 1024,
    "KIB": 1024,
    "M": 1024**2,
    "MB": 1024**2,
    "MIB": 1024**2,
    "G": 1024**3,
    "GB": 1024**3,
    "GIB": 1024**3,
    "T": 1024**4,
    "TB": 1024**4,
    "TIB": 1024**4,
}

_KB = 1024
_MB = 1024**2
_GB = 1024**3


def parse_compose_command_settings(
    compose_path: Path | str, service: str = "timescaledb"
) -> dict[str, str]:
    """Parse a compose file's `command` -c pairs (and shm_size) for one service.

    Returns {"<pg setting>": "<value>"} for every `key=value` that follows a
    `-c` in the service's command list, plus the service's `shm_size` under
    "__shm_size" (a compose-only fact, not a pg_settings name). A command
    without -c pairs and no shm_size yields {}.
    """
    doc = yaml.safe_load(Path(compose_path).read_text(encoding="utf-8"))
    svc = (doc.get("services") or {}).get(service) or {}
    out: dict[str, str] = {}
    command = svc.get("command") or []
    expect_value = False
    for item in command:
        if expect_value:
            if "=" in item:
                key, _, value = item.partition("=")
                out[key] = value
            expect_value = False
        elif item == "-c":
            expect_value = True
    if svc.get("shm_size") is not None:
        out["__shm_size"] = str(svc["shm_size"])
    return out


def normalize_setting_bytes(value: str, unit: str) -> int | None:
    """Byte count for a memory setting, or None for non-memory settings.

    `value`/`unit` follow pg_settings' shape: ("393216", "8kB"), ("8192", "kB")
    -- or a suffixed string with an empty unit, the compose command style:
    ("64MB", ""), ("3GB", ""). Anything else (max_connections' ("200", ""),
    dynamic_shared_memory_type's ("posix", ""), time units like "min") is not a
    memory setting: None.
    """
    value = str(value).strip()
    unit = (unit or "").strip()
    if unit:
        if unit not in _UNIT_FACTORS:
            return None
        try:
            return int(float(value) * _UNIT_FACTORS[unit])
        except ValueError:
            return None
    lowered = value.lower()
    for suffix, factor in sorted(_SUFFIX_FACTORS.items(), key=lambda kv: -kv[1]):
        if lowered.endswith(suffix.lower()):
            head = lowered[: -len(suffix)].strip()
            if head and head.replace(".", "", 1).replace(",", "", 1).isdigit():
                return int(float(head) * factor)
            break
    return None


def _format_bytes(n: int) -> str:
    for factor, suffix in ((_GB, "GB"), (_MB, "MB"), (_KB, "kB")):
        if n >= factor and n % factor == 0:
            return f"{n // factor}{suffix}"
    return f"{n}B"


def compare_settings(
    compose: dict[str, str], running: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """One drift entry per compose-tracked setting.

    Entry fields: name, compose, running, source, sourcefile, status in
    {match, drift, unknown}. Memory settings compare on normalized byte counts
    ("3GB" == 393216 x 8kB); non-memory settings compare as raw strings. Keys
    starting with "__" are compose metadata (shm_size), not pg_settings names,
    and are skipped.
    """
    entries: list[dict[str, Any]] = []
    for name, compose_value in compose.items():
        if name.startswith("__"):
            continue
        row = running.get(name)
        if row is None:
            entries.append(
                {
                    "name": name,
                    "compose": compose_value,
                    "running": None,
                    "source": None,
                    "sourcefile": None,
                    "status": "unknown",
                }
            )
            continue
        compose_bytes = normalize_setting_bytes(compose_value, "")
        running_bytes = normalize_setting_bytes(row["setting"], row["unit"])
        if compose_bytes is not None and running_bytes is not None:
            equal = compose_bytes == running_bytes
            running_display = _format_bytes(running_bytes)
        elif compose_bytes is None and running_bytes is None:
            equal = str(compose_value) == str(row["setting"])
            running_display = str(row["setting"])
        else:
            # One side carries a memory unit the other lacks: incomparable.
            equal = False
            running_display = str(row["setting"])
        entries.append(
            {
                "name": name,
                "compose": compose_value,
                "running": running_display,
                "source": row.get("source"),
                "sourcefile": row.get("sourcefile"),
                "status": "match" if equal else "drift",
            }
        )
    return entries


def _fetch_settings(cur) -> dict[str, dict[str, Any]]:
    cur.execute(
        "SELECT name, setting, unit, source, sourcefile, pending_restart "
        "FROM pg_settings WHERE name = ANY(%s) ORDER BY name",
        (list(_TRACKED_SETTINGS),),
    )
    return {
        row[0]: {
            "setting": row[1],
            "unit": row[2],
            "source": row[3],
            "sourcefile": row[4],
            "pending_restart": row[5],
        }
        for row in cur.fetchall()
    }


def _fetch_role_database_settings(cur) -> list[dict[str, Any]]:
    # ALTER ROLE / ALTER DATABASE overrides (e.g. migration 193's
    # statement_timeout) -- the other place a running setting can drift from
    # the command line. Read via pg_db_role_setting, per design D-38.
    cur.execute(
        "SELECT COALESCE(d.datname, '*'), COALESCE(r.rolname, '*'), s.setconfig "
        "FROM pg_db_role_setting s "
        "LEFT JOIN pg_database d ON d.oid = s.setdatabase "
        "LEFT JOIN pg_roles r ON r.oid = s.setrole "
        "ORDER BY 1, 2"
    )
    return [{"database": row[0], "role": row[1], "settings": row[2]} for row in cur.fetchall()]


def _fetch_database_stats(cur) -> dict[str, Any]:
    cur.execute(
        "SELECT blks_hit, blks_read, temp_files, temp_bytes, stats_reset "
        "FROM pg_stat_database WHERE datname = current_database()"
    )
    hit, read, temp_files, temp_bytes, stats_reset = cur.fetchone()
    total = (hit or 0) + (read or 0)
    return {
        "blks_hit": hit,
        "blks_read": read,
        "hit_ratio": round(hit / total, 5) if total else None,
        "temp_files": temp_files,
        "temp_bytes": temp_bytes,
        "stats_reset": stats_reset.isoformat() if stats_reset else None,
    }


def _fetch_top_temp_statements(cur, top: int) -> list[dict[str, Any]]:
    # Spill ranking is temp_blks_written: the work_mem evidence the SOP wants.
    cur.execute(
        "SELECT queryid, left(query, 200) AS query, calls, temp_blks_read, "
        "temp_blks_written, total_exec_time, mean_exec_time "
        "FROM pg_stat_statements "
        "WHERE temp_blks_written > 0 "
        "ORDER BY temp_blks_written DESC LIMIT %s",
        (top,),
    )
    return [
        {
            "queryid": str(row[0]),
            "query": row[1],
            "calls": row[2],
            "temp_blks_read": row[3],
            "temp_blks_written": row[4],
            "total_exec_time_ms": float(row[5]) if row[5] is not None else None,
            "mean_exec_time_ms": float(row[6]) if row[6] is not None else None,
        }
        for row in cur.fetchall()
    ]


def _inspect_container() -> dict[str, Any]:
    # `docker inspect` only -- the read-only container API. No state changes.
    try:
        result = subprocess.run(
            ["docker", "inspect", _CONTAINER],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        info = json.loads(result.stdout)[0]
        labels = (info.get("Config") or {}).get("Labels") or {}
        return {
            "Created": info.get("Created"),
            "Cmd": (info.get("Config") or {}).get("Cmd"),
            "ShmSize": (info.get("HostConfig") or {}).get("ShmSize"),
            "StartedAt": (info.get("State") or {}).get("StartedAt"),
            "compose_config_files": labels.get("com.docker.compose.project.config_files"),
            "error": None,
        }
    except (subprocess.SubprocessError, OSError, ValueError, IndexError) as error:
        return {"error": f"docker inspect failed: {error}"}


def _read_meminfo() -> dict[str, Any]:
    meminfo: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            meminfo[key] = int(rest.strip().split()[0])  # kB
    except OSError as error:
        return {"error": f"/proc/meminfo unreadable: {error}"}
    return {
        "MemTotal_kB": meminfo.get("MemTotal"),
        "MemAvailable_kB": meminfo.get("MemAvailable"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--compose",
        default="production/docker-compose.yml",
        help="Compose file to compare against (default: production/docker-compose.yml)",
    )
    # CLI argument, not an APR key: scripts/ diagnostics are outside the APR
    # mandate (docs/foundation/adaptive-parameter-registry.md).
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of pg_stat_statements spill rows to record (default: 20)",
    )
    parser.add_argument("--out", help="Write the baseline JSON here")
    args = parser.parse_args()

    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    compose = parse_compose_command_settings(args.compose)

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            pg_settings = _fetch_settings(cur)
            role_db = _fetch_role_database_settings(cur)
            database = _fetch_database_stats(cur)
            top_temp = _fetch_top_temp_statements(cur, args.top)

    compare = compare_settings(compose, pg_settings)
    baseline = {
        "captured_at": datetime.now(UTC).isoformat(),
        "settings": pg_settings,
        "role_database_settings": role_db,
        "database": database,
        "top_temp_statements": top_temp,
        "container": _inspect_container(),
        "host": _read_meminfo(),
        "compose_file": str(args.compose),
        "compose_command_settings": compose,
        "compare": compare,
    }

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")

    drifts = [e for e in compare if e["status"] == "drift"]
    unknowns = [e for e in compare if e["status"] == "unknown"]
    print(f"captured_at: {baseline['captured_at']}")
    print(
        f"database: hit_ratio={database['hit_ratio']} "
        f"temp_files={database['temp_files']} temp_bytes={database['temp_bytes']}"
    )
    for entry in drifts:
        print(
            f"DRIFT {entry['name']}: compose={entry['compose']} "
            f"running={entry['running']} (source: {entry['source']})"
        )
    for entry in unknowns:
        print(f"UNKNOWN {entry['name']}: compose={entry['compose']} not in pg_settings")
    if top_temp:
        worst = top_temp[0]
        print(
            f"top spiller: {worst['query'][:60]!r} "
            f"temp_blks_written={worst['temp_blks_written']} calls={worst['calls']}"
        )
    if not drifts and not unknowns:
        print("compose and running settings agree")
    if args.out:
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
