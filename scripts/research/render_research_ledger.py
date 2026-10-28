"""Render docs/research/research-ledger.md from the database (187-13, design 10.2.6).

The ledger is a report, never edited: ideas by research stage, attempts by vintage with their
headline numbers, the current StepM selection set with its disclosure block, and the legacy
verdicts. The selection set is computed by select_books.build_report, never stored, and is shown
only when its report says result true; otherwise the refusal reasons are shown and no set.

    .venv/bin/python -m scripts.research.render_research_ledger            # render and commit
    .venv/bin/python -m scripts.research.render_research_ledger --stdout   # print, change nothing

The nightly oneshot (indicagent-research-ledger-render) runs this. It writes the file atomically
when the text changed and commits that one path, retrying while .git/index.lock is held; it never
pushes and touches no other path. A file with uncommitted edits is never overwritten.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import structlog  # noqa: E402

from scripts.research.select_books import build_report  # noqa: E402
from src.config.config_service import ConfigService  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.database_manager import connect_with_codecs  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402

JOB = "research_ledger_render"
OUT = "docs/research/research-ledger.md"
COMMIT_MESSAGE = "docs(research-ledger): nightly render"
RENDER_COMMAND = ".venv/bin/python -m scripts.research.render_research_ledger"
RETRIES_KEY = "infra.research_ledger_render.git_lock_retries"
_LOCK_WAIT_SECONDS = 2.0
_STAGE_ORDER = ("frozen", "confirmed", "tested", "registered", "specified", "refused", "idea")

_logger = structlog.get_logger()

_STAGE_SQL = """
SELECT s.domain, s.name, s.stage, s.recipe_versions, s.attempts, s.tested, s.refused
FROM concept_research_stage s WHERE s.domain <> 'feature' ORDER BY s.stage, s.domain, s.name
"""
_ATTEMPT_SQL = """
SELECT r.vintage, c.name AS concept, c.domain, r.kind, r.mode, r.status, r.decision_t,
       r.decision_p, r.gross_sharpe, r.mean_session_pnl, r.n_sessions, r.span_start, r.span_end,
       r.started_at, r.run_id::text AS run_id
FROM research_run r JOIN concept_registry c USING (concept_id)
WHERE r.kind <> 'legacy_verdict'
ORDER BY r.vintage, r.started_at, c.name, r.run_id
"""
_LEGACY_SQL = """
SELECT r.evidence->>'card_id' AS card_id, r.evidence->>'verdict' AS verdict,
       r.evidence->>'verdict_date' AS verdict_date, r.evidence->>'title' AS title,
       r.evidence->>'status_now' AS status_now
FROM research_run r WHERE r.kind = 'legacy_verdict' ORDER BY verdict_date, card_id
"""
_POD_SQL = """
SELECT child.name AS pod, parent.name AS member
FROM concept_parent e
JOIN concept_registry child ON child.concept_id = e.child_concept_id
JOIN concept_registry parent ON parent.concept_id = e.parent_concept_id
WHERE child.domain = 'book' AND child.metadata->>'kind' = 'pod'
ORDER BY pod, member
"""
_AS_OF_SQL = """
SELECT greatest(
    (SELECT max(greatest(started_at, finished_at)) FROM research_run),
    (SELECT max(created_at) FROM concept_registry)
)
"""


@dataclass(frozen=True)
class LedgerData:
    stages: list[dict]
    attempts: list[dict]
    legacy: list[dict]
    pod_members: dict[str, list[str]]
    selection: dict
    as_of: str


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _table(header: tuple[str, ...], rows: list[tuple]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return out


def _selection_lines(selection: dict) -> list[str]:
    if not selection.get("result"):
        lines = ["No selection set: the selection is not a result.", ""]
        lines += [f"- {reason}" for reason in selection.get("refusals", ["no report"])]
        return lines
    chosen = selection["selection_set"]
    lines = [
        f"Vintage `{selection['vintage']}`: {len(chosen)} selected of "
        f"{selection['attempts']} counted attempts with a series.",
        "",
    ]
    lines += _table(
        ("Concept", "t", "Adjusted p", "Run"),
        [(s["concept"], s["t"], s["adjusted_p"], s["run_id"][:8]) for s in chosen],
    )
    lines += [
        "",
        "Disclosure: "
        f"sessions {selection['sessions'][0]} to {selection['sessions'][1]} "
        f"({selection['sessions'][2]}), FWER {selection['fwer']}, block mean "
        f"{selection['block_mean']}, {selection['reps']} reps, max horizon "
        f"{selection['max_horizon_sessions']} sessions, {selection['not_selected']} not selected.",
    ]
    missing = selection.get("missing_series", [])
    if missing:
        lines += ["", f"series_unavailable ({len(missing)} counted attempts, never filled):", ""]
        lines += [f"- {m['concept']} ({m['status']}, run {m['run_id'][:8]})" for m in missing]
    return lines


def render(data: LedgerData) -> str:
    """The ledger text: a pure, deterministic function of the rows (no wall clock)."""
    out = [
        "<!-- GENERATED FILE. Do not edit. Render it with the command in the next paragraph. -->",
        "",
        "# Research ledger",
        "",
        f"Rendered from DB state as of {data.as_of}. This file is generated: do not edit it. "
        f"Render with `{RENDER_COMMAND}`. The nightly job `indicagent-research-ledger-render` "
        "commits it when it changes. The hand-edited predecessor "
        "`docs/research/construction-verdict-ledger.md` is frozen.",
        "",
        "## Selection (StepM)",
        "",
        *_selection_lines(data.selection),
        "",
        "## Ideas by research stage",
        "",
    ]
    by_stage: dict[str, list[dict]] = {}
    for row in data.stages:
        by_stage.setdefault(row["stage"], []).append(row)
    for stage in sorted(
        by_stage, key=lambda s: (_STAGE_ORDER.index(s) if s in _STAGE_ORDER else 99, s)
    ):
        out += [f"### {stage} ({len(by_stage[stage])})", ""]
        out += _table(
            ("Domain", "Concept", "Recipe versions", "Attempts", "Tested", "Refused"),
            [
                (
                    r["domain"],
                    r["name"],
                    r["recipe_versions"],
                    r["attempts"],
                    r["tested"],
                    r["refused"],
                )
                for r in by_stage[stage]
            ],
        )
        out.append("")
    out += ["## Attempts by vintage", ""]
    vintages = sorted({r["vintage"] for r in data.attempts})
    if not vintages:
        out += ["No attempts recorded.", ""]
    for vintage in vintages:
        rows = [r for r in data.attempts if r["vintage"] == vintage]
        out += [f"### {vintage} ({len(rows)})", ""]
        out += _table(
            (
                "Concept",
                "Kind",
                "Mode",
                "Status",
                "t",
                "p",
                "Gross Sharpe",
                "Mean pnl",
                "Sessions",
                "Span",
                "Run",
            ),
            [
                (
                    r["concept"],
                    r["kind"],
                    r["mode"],
                    r["status"],
                    r["decision_t"],
                    r["decision_p"],
                    r["gross_sharpe"],
                    r["mean_session_pnl"],
                    r["n_sessions"],
                    f"{r['span_start']} to {r['span_end']}" if r["span_start"] else "",
                    r["run_id"][:8],
                )
                for r in rows
            ],
        )
        for row in rows:
            if row["kind"] == "pod_book" and data.pod_members.get(row["concept"]):
                out += [
                    "",
                    f"`{row['concept']}` members: " + ", ".join(data.pod_members[row["concept"]]),
                ]
        out.append("")
    out += [f"## Legacy verdicts ({len(data.legacy)})", ""]
    out += _table(
        ("Card", "Verdict", "Date", "Title", "Now"),
        [
            (r["card_id"], r["verdict"], r["verdict_date"], r["title"], r["status_now"])
            for r in data.legacy
        ],
    )
    return "\n".join(out) + "\n"


def newest_battery(root: Path) -> str | None:
    """The most recently written record, or None; select_books judges whether it
    attests the current StepM code, so a stale record only produces a refusal line."""
    records = sorted(
        (root / "logs" / "research").glob("stepm_null_battery_s4000_*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    return str(records[-1]) if records else None


async def fetch(dsn: str, root: Path) -> LedgerData:
    selection = await build_report(dsn, None, newest_battery(root), diagnostic=False)
    conn = await connect_with_codecs(dsn)
    try:
        stages = [dict(r) for r in await conn.fetch(_STAGE_SQL)]
        attempts = [dict(r) for r in await conn.fetch(_ATTEMPT_SQL)]
        legacy = [dict(r) for r in await conn.fetch(_LEGACY_SQL)]
        pods: dict[str, list[str]] = {}
        for r in await conn.fetch(_POD_SQL):
            pods.setdefault(r["pod"], []).append(r["member"])
        as_of = await conn.fetchval(_AS_OF_SQL)
    finally:
        await conn.close()
    stamp = as_of.strftime("%Y-%m-%dT%H:%M:%SZ") if as_of else "no records"
    return LedgerData(stages, attempts, legacy, pods, selection, stamp)


GitRunner = Callable[[list[str]], subprocess.CompletedProcess]


def _git_runner(root: Path) -> GitRunner:
    def run(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
        )

    return run


def _blob_hash(text: str) -> str:
    return hashlib.sha1(
        f"blob {len(text.encode())}\0".encode() + text.encode()
    ).hexdigest()  # noqa: S324


def write_and_commit(
    root: Path,
    rendered: str,
    *,
    run: GitRunner,
    retries: int,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Write the file atomically and commit that one path. Returns unchanged, committed or
    skipped:<reason>. Skips when the file holds uncommitted edits (its hash differs from HEAD's
    blob): the job never overwrites work it did not render."""
    target = root / OUT
    head = run(["rev-parse", f"HEAD:{OUT}"])
    tracked = head.returncode == 0
    current = target.read_text() if target.exists() else None
    if tracked and (current is None or _blob_hash(current) != head.stdout.strip()):
        return "skipped:file differs from HEAD (uncommitted edits)"
    if current == rendered:
        return "unchanged"
    temp = target.with_suffix(".md.tmp")
    temp.write_text(rendered)
    os.replace(temp, target)
    for attempt in range(retries + 1):
        added = run(["add", "--", OUT])
        done = added if added.returncode else run(["commit", "-m", COMMIT_MESSAGE, "--", OUT])
        if done.returncode == 0:
            return "committed"
        if "index.lock" not in done.stderr or attempt == retries:
            return f"skipped:git failed: {done.stderr.strip()[:200]}"
        sleep(_LOCK_WAIT_SECONDS)
    return "skipped:unreachable"


async def _main(args: argparse.Namespace) -> int:
    from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics

    root = Path(__file__).resolve().parents[2]
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    status = "failure"
    try:
        rendered = render(await fetch(dsn, root))
        if args.stdout:
            print(rendered, end="")
            status = "success"
            return 0
        cfg = ConfigService(dsn)
        await cfg.initialize()
        try:
            retries = int(await cfg.get(RETRIES_KEY, default=5))
        finally:
            await cfg.close()
        outcome = write_and_commit(root, rendered, run=_git_runner(root), retries=retries)
        _logger.info("research_ledger_render.done", outcome=outcome)
        print(outcome)
        status = "success" if not outcome.startswith("skipped") else "skipped"
        return 0
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": JOB, "status": status})
        flush_and_shutdown_metrics()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stdout", action="store_true", help="print the text, write nothing")
    args = parser.parse_args(argv)
    setup_service_logging("logs/research_ledger_render.log")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    from src.observability.otel import OTelInitError, init_otel_providers

    try:
        init_otel_providers(JOB)
    except OTelInitError as error:
        print(f"[warn] OTel init failed, metrics disabled: {error}")
    sys.exit(main())
