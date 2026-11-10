"""Reference raw writer: the one writer of ``reference_raw`` (admission design section 6, step 3).

Ingests every vendor reference capture manifest under ``data/massive/reference`` once: one row
per manifest line, lineage = manifest path + line + file path + the file's sha256 (verified
against the file's bytes, a mismatch fails the run). Bodies are loaded as the exact text served
and parsed by jsonb in the database; HTTP 404 NOT_FOUND answers are rows like any other.

One transaction per manifest, all or nothing. Idempotent: a line already present (by manifest
path and line) is skipped before its file is read, and its stored sha256 must equal the
manifest's; any unique conflict on a line that was not present is an anomaly and fails the run.
A run without --apply does everything inside the transaction and rolls it back.

    .venv/bin/python -m services.reference_raw_writer                    # rolled-back rehearsal
    .venv/bin/python -m services.reference_raw_writer --apply            # load
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import asyncpg

from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.intelligence.bars.massive_reference import (
    VENDOR,
    ReferenceCapture,
    discover_manifests,
    manifest_layout,
    parse_manifest_line,
    read_body,
)
from src.observability.metrics import counter
from src.observability.otel import OTelInitError, init_otel_providers

_JOB = "reference-raw-writer"
_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_ROOT = _REPO_ROOT / "data" / "massive" / "reference"
# Rows per INSERT. A body can reach a few hundred KB; this bounds one statement's memory.
_CHUNK = 200
_ROWS_TOTAL = counter(
    "reference_raw_rows_total",
    "reference_raw_writer rows per run by layout and outcome (inserted, present). Never per row.",
)

_PRESENT_SQL = """
SELECT manifest_line, file_sha256 FROM reference_raw WHERE manifest_path = $1
"""
_INSERT_SQL = """
INSERT INTO reference_raw (vendor, endpoint, request_key, page, as_of, url, http_status, body,
                           served_at, manifest_path, manifest_line, file_path, file_sha256)
SELECT $1, e, k, p, a, u, h, b::jsonb, s, mp, ml, fp, fs
  FROM unnest($2::text[], $3::text[], $4::int[], $5::date[], $6::text[], $7::int[], $8::text[],
              $9::timestamptz[], $10::text[], $11::int[], $12::text[], $13::text[])
       AS t(e, k, p, a, u, h, b, s, mp, ml, fp, fs)
ON CONFLICT DO NOTHING
RETURNING 1
"""
_BODY_STATUS_SQL = """
SELECT endpoint, http_status, body->>'status' AS body_status, count(*) AS n
  FROM reference_raw WHERE manifest_path = $1 GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
"""


def _lines(manifest: Path) -> Iterator[tuple[int, str]]:
    """Physical lines with their 1-based numbers. A blank line is a manifest defect, not noise."""
    with manifest.open(encoding="utf-8") as handle:
        for number, text in enumerate(handle, 1):
            if not text.strip():
                raise ValueError(f"{manifest}:{number}: blank manifest line")
            yield number, text


def _build_chunk(captures: list[ReferenceCapture]) -> list[list]:
    """Column arrays for one INSERT; reads and verifies every file (blocking, runs in a thread)."""
    bodies = [read_body(c, repo_root=_REPO_ROOT) for c in captures]
    return [
        [c.endpoint for c in captures],
        [c.request_key for c in captures],
        [c.page for c in captures],
        [c.as_of for c in captures],
        [c.url for c in captures],
        [c.http_status for c in captures],
        bodies,
        [c.served_at for c in captures],
        [c.manifest_path for c in captures],
        [c.manifest_line for c in captures],
        [c.file_path for c in captures],
        [c.file_sha256 for c in captures],
    ]


class ReferenceRawWriter(BaseBatch):
    """Batch service: reference capture manifests -> reference_raw."""

    job_name = _JOB
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str, reference_root: Path, apply: bool, max_rows: int | None):
        super().__init__(db_dsn)
        self._root = reference_root
        self._apply = apply
        self._max_rows = max_rows

    async def _load_manifest(self, conn: asyncpg.Connection, manifest: Path) -> Counter:
        layout = manifest_layout(manifest)
        manifest_path = manifest.relative_to(_REPO_ROOT).as_posix()
        present = {
            row["manifest_line"]: row["file_sha256"]
            for row in await conn.fetch(_PRESENT_SQL, manifest_path)
        }
        outcome: Counter = Counter()
        pending: list[ReferenceCapture] = []
        by_endpoint: Counter = Counter()

        async def flush() -> None:
            if not pending:
                return
            columns = await asyncio.to_thread(_build_chunk, pending)
            inserted = await conn.fetch(_INSERT_SQL, VENDOR, *columns)
            if len(inserted) != len(pending):
                raise RuntimeError(
                    f"{manifest_path}: {len(pending) - len(inserted)} lines of a chunk starting "
                    f"at line {pending[0].manifest_line} hit a unique conflict; a manifest holds "
                    "one capture of a request page"
                )
            outcome["inserted"] += len(pending)
            pending.clear()

        seen = 0
        for number, text in _lines(manifest):
            if self._max_rows is not None and seen >= self._max_rows:
                break
            seen += 1
            capture = parse_manifest_line(text, manifest, number, repo_root=_REPO_ROOT)
            if number in present:
                if present[number] != capture.file_sha256:
                    raise RuntimeError(
                        f"{manifest_path}:{number}: stored sha256 differs from the manifest's"
                    )
                outcome["present"] += 1
                continue
            by_endpoint[(capture.endpoint, capture.http_status)] += 1
            pending.append(capture)
            if len(pending) >= _CHUNK:
                await flush()
        await flush()

        for key, value in outcome.items():
            _ROWS_TOTAL.add(value, {"layout": layout, "outcome": key})
        status_rows = await conn.fetch(_BODY_STATUS_SQL, manifest_path)
        self.logger.info(
            "reference_raw_writer.manifest_done",
            manifest=manifest_path,
            layout=layout,
            lines=seen,
            inserted=outcome["inserted"],
            present=outcome["present"],
            endpoint_http_status={f"{e}:{s}": n for (e, s), n in sorted(by_endpoint.items())},
            stored_endpoint_http_body_status={
                f"{r['endpoint']}:{r['http_status']}:{r['body_status']}": r["n"]
                for r in status_rows
            },
        )
        return outcome

    async def execute(self, pool: asyncpg.Pool) -> None:
        manifests = discover_manifests(self._root)
        if not manifests:
            raise FileNotFoundError(f"no reference manifests under {self._root}")
        started = time.monotonic()
        async with pool.acquire() as conn:
            for manifest in manifests:
                try:
                    async with conn.transaction():
                        await self._load_manifest(conn, manifest)
                        if not self._apply:
                            raise _Rehearsal
                except _Rehearsal:
                    self.logger.info(
                        "reference_raw_writer.rolled_back", manifest=manifest.name, apply=False
                    )
            size = await conn.fetchval("SELECT pg_total_relation_size('reference_raw'::regclass)")
        self.logger.info(
            "reference_raw_writer.run_done",
            apply=self._apply,
            manifests=len(manifests),
            table_bytes=size,
            elapsed_s=round(time.monotonic() - started, 1),
        )


class _Rehearsal(Exception):
    """Raised inside a manifest's transaction to roll it back on a run without --apply."""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load Massive reference captures into reference_raw"
    )
    parser.add_argument("--reference-root", type=Path, default=_DEFAULT_ROOT)
    parser.add_argument("--apply", action="store_true", help="commit; default rolls back")
    parser.add_argument(
        "--max-rows", type=int, default=None, help="rehearsal only: first N lines per manifest"
    )
    args = parser.parse_args()
    if args.apply and args.max_rows is not None:
        parser.error("--max-rows is a rehearsal limit and cannot be combined with --apply")
    try:
        init_otel_providers(f"indicagent-{_JOB}")
    except OTelInitError:
        pass
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    writer = ReferenceRawWriter(db_dsn, args.reference_root.resolve(), args.apply, args.max_rows)
    asyncio.run(writer.run())


if __name__ == "__main__":
    main()
