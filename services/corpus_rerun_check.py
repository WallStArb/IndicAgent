"""The corpus rerun `--check` mode: every refusal a launch would meet, read-only, printed at once.

`CorpusRerun.pin_checks` already returns every pin check as a list; `--check` shows that list whole
(the gate itself stops a step at the first set of failures) and adds the two causes the gate cannot
name:

- the pinned APR keys whose values moved since the run was created (the run pins a hash, and the
  values behind it are recorded at `--new-run` so a mismatch names its key);
- the stored units that would block the stage's units: an append-only unit loaded under another run
  with a different batch key is not adopted, and its rows make the new unit's COPY fail on the primary
  key after minutes of compute (the 2026-11-26 pilot restart). The runbook's recovery (supersede through
  migration 416, delete by the unit's replace_where) is the fix; this names the units before the launch.

Pure functions over plain values; the one query is `fetch_stored_units`. Nothing here writes.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

BLOCKING_STATUSES = ("completed", "started")


@dataclasses.dataclass(frozen=True)
class UnitSpan:
    """The identity of a bulk-load unit as far as a collision goes: its rows are (tf, symbols, range)."""

    batch_key: str
    tf: str
    range_start: datetime
    range_end: datetime
    symbols: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class StoredUnit:
    """A provenance row of the target table written under another run."""

    unit: UnitSpan
    run_id: str | None
    status: str
    row_count: int | None


@dataclasses.dataclass(frozen=True)
class Blocker:
    stored: StoredUnit
    blocks: tuple[str, ...]  # batch keys of the planned units whose rows it holds


def _overlaps(a: UnitSpan, b: UnitSpan) -> bool:
    return a.tf == b.tf and a.range_start < b.range_end and b.range_start < a.range_end


def find_blockers(planned: Iterable[UnitSpan], stored: Iterable[StoredUnit]) -> list[Blocker]:
    """The stored units whose rows a planned unit would collide with. The same batch key is adopted by
    the runner, not a collision; a different key over shared symbols, tf and range is."""
    by_symbol: dict[str, list[UnitSpan]] = defaultdict(list)
    for unit in planned:
        for symbol in unit.symbols:
            by_symbol[symbol].append(unit)
    found: list[Blocker] = []
    for row in stored:
        if row.status not in BLOCKING_STATUSES:
            continue
        hit = {
            unit.batch_key
            for symbol in row.unit.symbols
            for unit in by_symbol.get(symbol, ())
            if unit.batch_key != row.unit.batch_key and _overlaps(unit, row.unit)
        }
        if hit:
            found.append(Blocker(row, tuple(sorted(hit))))
    return sorted(found, key=lambda b: b.stored.unit.batch_key)


def apr_diff(pinned: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    """The pinned APR keys whose value moved (or vanished), as `key: pinned -> current` lines. A key
    added since the run was created is listed too: it changes the hash like any other."""
    lines = []
    for key in sorted({*pinned, *current}):
        before, after = pinned.get(key), current.get(key)
        if before != after:
            lines.append(f"{key}: {_short(before)} -> {_short(after)}")
    return lines


def _short(value: Any, limit: int = 120) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


_STORED_UNITS_SQL = """
SELECT batch_key, tf, range_start, range_end, symbols, run_id::text, status, row_count
  FROM provenance_batch
 WHERE target_table = %s AND status = ANY(%s)
   AND (%s::uuid IS NULL OR run_id IS DISTINCT FROM %s::uuid)
"""


def fetch_stored_units(conn: Any, target_table: str, run_id: str | None) -> list[StoredUnit]:
    """Every blocking-status provenance row of `target_table` not written under `run_id` (every row
    when it is None: the check of a run that does not exist yet)."""
    params = (target_table, list(BLOCKING_STATUSES), run_id, run_id)
    rows = conn.execute(_STORED_UNITS_SQL, params).fetchall()
    return [
        StoredUnit(UnitSpan(key, tf, start, end, tuple(symbols)), owner, status, count)
        for key, tf, start, end, symbols, owner, status, count in rows
    ]


def render(
    checks: Sequence[Mapping[str, Any]], diff: Sequence[str], blockers: Sequence[Blocker]
) -> tuple[list[str], bool]:
    """The report lines and whether the launch would pass (every check ok, no blocker)."""
    lines = [f"{'ok  ' if c['ok'] else 'FAIL'} {c['name']}: {c['detail']}" for c in checks]
    if diff:
        lines.append(f"FAIL pinned APR keys that moved ({len(diff)}):")
        lines.extend(f"       {line}" for line in diff)
    if blockers:
        lines.append(f"FAIL stored units that would block the stage's units ({len(blockers)}):")
        for blocker in blockers:
            unit = blocker.stored.unit
            lines.append(
                f"       {unit.batch_key[:12]} run {(blocker.stored.run_id or '-')[:8]} "
                f"{blocker.stored.status} {unit.tf} {len(unit.symbols)} names "
                f"{unit.range_start:%Y-%m-%d}..{unit.range_end:%Y-%m-%d} "
                f"rows {blocker.stored.row_count}; blocks {len(blocker.blocks)} planned unit(s)"
            )
    ok = all(c["ok"] for c in checks) and not diff and not blockers
    lines.append("check: would launch" if ok else "check: a launch would be refused")
    return lines, ok
