"""Provenance batch helper for every derivation-side writer (phase 185 plan 04).

One bar_derivation_batch row per derivation run (scrub, grid, daily, seam
audit, listing venue, legacy): stage, rule version, the exact code commit and
the APR snapshot the run executed under. Plans 05/10/12/17/20 open a batch
before writing and close it with completed/failed, so every bar_quality_flag
row's batch_id answers "which code and which thresholds produced this
verdict" (D-08).

JSON parameters are passed as json.dumps strings with explicit ::jsonb casts:
bare asyncpg/psycopg connections carry no jsonb codec (CLAUDE.md asyncpg rule).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

_BATCH_STATUSES = ("completed", "failed")
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _git_output(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=True,
        cwd=_REPO_ROOT,
    )
    return result.stdout


def current_code_commit() -> str:
    """HEAD commit, with a -dirty suffix when tracked files have local changes.

    Untracked files do not dirty the commit: they are not part of what the
    running code is, only clutter beside it.
    """
    head = _git_output("rev-parse", "HEAD").strip()
    tracked_changes = any(
        not line.startswith("??") for line in _git_output("status", "--porcelain").splitlines()
    )
    return f"{head}-dirty" if tracked_changes else head


async def open_batch(
    conn: Any,
    *,
    stage: str,
    rule_version: str,
    apr_snapshot: dict[str, Any],
    n_symbols: int | None,
    detail: dict[str, Any] | None = None,
) -> str:
    """Insert one running batch row under the writer role; return its batch_id."""
    async with conn.transaction():
        await conn.execute("SET LOCAL ROLE bar_derivation_writer")
        return await conn.fetchval(
            """
            INSERT INTO bar_derivation_batch
                (batch_id, stage, rule_version, code_commit, apr_snapshot,
                 n_symbols, status, started_at, detail)
            VALUES (gen_random_uuid(), $1, $2, $3, $4::jsonb, $5, 'running', now(), $6::jsonb)
            RETURNING batch_id::text
            """,
            stage,
            rule_version,
            current_code_commit(),
            json.dumps(apr_snapshot),
            n_symbols,
            json.dumps(detail or {}),
        )


async def close_batch(
    conn: Any,
    batch_id: str,
    *,
    status: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """Set the batch's terminal status, finished_at, and merge detail into the row."""
    if status not in _BATCH_STATUSES:
        raise ValueError(f"unknown batch status {status!r}; expected one of {_BATCH_STATUSES}")
    async with conn.transaction():
        await conn.execute("SET LOCAL ROLE bar_derivation_writer")
        await conn.execute(
            """
            UPDATE bar_derivation_batch
            SET status = $2, finished_at = now(), detail = detail || $3::jsonb
            WHERE batch_id = $1::uuid
            """,
            batch_id,
            status,
            json.dumps(detail or {}),
        )


def open_batch_sync(
    conn: Any,
    *,
    stage: str,
    rule_version: str,
    apr_snapshot: dict[str, Any],
    n_symbols: int | None,
    detail: dict[str, Any] | None = None,
) -> str:
    """psycopg twin of open_batch."""
    with conn.transaction():
        conn.execute("SET LOCAL ROLE bar_derivation_writer")
        return conn.execute(
            """
            INSERT INTO bar_derivation_batch
                (batch_id, stage, rule_version, code_commit, apr_snapshot,
                 n_symbols, status, started_at, detail)
            VALUES (gen_random_uuid(), %s, %s, %s, %s::jsonb, %s, 'running', now(), %s::jsonb)
            RETURNING batch_id::text
            """,
            (
                stage,
                rule_version,
                current_code_commit(),
                json.dumps(apr_snapshot),
                n_symbols,
                json.dumps(detail or {}),
            ),
        ).fetchone()[0]


def close_batch_sync(
    conn: Any,
    batch_id: str,
    *,
    status: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """psycopg twin of close_batch."""
    if status not in _BATCH_STATUSES:
        raise ValueError(f"unknown batch status {status!r}; expected one of {_BATCH_STATUSES}")
    with conn.transaction():
        conn.execute("SET LOCAL ROLE bar_derivation_writer")
        conn.execute(
            """
            UPDATE bar_derivation_batch
            SET status = %s, finished_at = now(), detail = detail || %s::jsonb
            WHERE batch_id = %s::uuid
            """,
            (status, json.dumps(detail or {}), batch_id),
        )
