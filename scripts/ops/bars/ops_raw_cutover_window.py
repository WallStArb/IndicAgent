"""Cutover window for the unified raw bar table (phase 191 plan 04).

TEMPORARY: deleted at phase 191 close with the other cutover scaffolding.

`open` stops the fetcher timer and every timer or service whose ExecStart names a module that
reads or writes the old stores or canonical bars, records the held list in
`logs/raw_cutover_window.json`, and never kills a running batch: timers are stopped first, a
running batch service is left to finish on its own within a bounded wait, and the open aborts
(nothing recorded) if it does not. `clear` marks a unit as cut over (the reader plan's evidence
file must exist); `resume` restarts a cleared unit and drops it from the record; `resume --all`
refuses while any unit is uncleared; `status` prints the record.

The module set is computed from the `_ALLOW_LIST` keys of the canonical writer-boundary test plus
the reader list, so a writer added later is not missed.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SYSTEMD_DIR = _REPO_ROOT / "production" / "systemd"
_RECORD = _REPO_ROOT / "logs" / "raw_cutover_window.json"
_BOUNDARY_TEST = _REPO_ROOT / "tests" / "unit" / "test_market_data_ohlcv_writer_boundary.py"

READER_MODULES = (
    "bar_derivation",
    "bar_reconciliation_audit",
    "bar_auditor",
    "split_detection",
    "listing_venue_writer",
    "dividend_event_writer",
    "bar_hold",
    "ops_bar_nightly",
    "ohlcv_coverage_writer",
    "ohlcv_history_fetcher",
    "bar_aggregator",
    "bar_scrub",
    "bar_load",
)

Systemctl = Callable[..., str]


class WindowError(RuntimeError):
    """A window precondition failed; the message names the unit or file."""


def allow_list_modules(test_path: Path = _BOUNDARY_TEST) -> set[str]:
    """Module stems named by the keys of every `_ALLOW_LIST` dict literal in the boundary test."""
    tree = ast.parse(test_path.read_text())
    stems: set[str] = set()
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.AnnAssign):
            target = node.target
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "_ALLOW_LIST":
            value = node.value
            if isinstance(value, ast.Dict):
                for key in value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        stems.add(Path(key.value).stem)
    return stems


def module_set() -> set[str]:
    return set(READER_MODULES) | allow_list_modules()


def _exec_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for line in text.splitlines():
        if line.startswith("ExecStart="):
            tokens.update(re.findall(r"[A-Za-z0-9_]+", line))
    return tokens


def _unit_target(text: str, name: str) -> str:
    match = re.search(r"^Unit=(\S+)", text, re.MULTILINE)
    if match:
        return match.group(1)
    return name[: -len(".timer")] + ".service"


def _template_match(target: str, services: dict[str, str]) -> str | None:
    """Service text for `x@yahoo.service` is stored under `x@.service`."""
    if target in services:
        return target
    if "@" in target:
        template = target.split("@")[0] + "@.service"
        if template in services:
            return template
    return None


def held_units(systemd_dir: Path, modules: set[str]) -> list[str]:
    """Held unit names: timers first (sorted), then services (sorted)."""
    services = {p.name: p.read_text() for p in systemd_dir.glob("*.service")}
    timers = {p.name: p.read_text() for p in systemd_dir.glob("*.timer")}
    held_services: set[str] = set()
    held_timers: set[str] = set()
    for name, text in services.items():
        if _exec_tokens(text) & modules:
            held_services.add(name)
    for name, text in timers.items():
        target = _unit_target(text, name)
        template = _template_match(target, services)
        if template is not None and template in held_services:
            held_timers.add(name)
            held_services.add(target)
    # A template service is held under its instance name (the timer's target), not as a template.
    held_services = {s for s in held_services if "@." not in s}
    return sorted(held_timers) + sorted(held_services)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(record: Path) -> dict:
    if not record.exists():
        raise WindowError(f"no window record at {record}")
    return json.loads(record.read_text())


def _save(record: Path, data: dict) -> None:
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps(data, indent=2) + "\n")


def open_window(
    names: list[str],
    record: Path,
    ctl: Systemctl,
    *,
    wait_s: float,
    poll_s: float,
    batch_services: set[str],
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Stop timers, stop non-batch services, wait for batch services to exit, then record."""
    active_at_open = {n: ctl("is-active", n).strip() == "active" for n in names}
    for name in names:
        if name.endswith(".timer") and active_at_open[name]:
            ctl("stop", name)
    for name in names:
        if name.endswith(".service") and active_at_open[name] and name not in batch_services:
            ctl("stop", name)
    deadline = time.monotonic() + wait_s
    while True:
        running = [
            n for n in names if n.endswith(".service") and ctl("is-active", n).strip() == "active"
        ]
        if not running:
            break
        if time.monotonic() >= deadline:
            raise WindowError(
                "still running after the bounded wait (not killed; timers are already "
                f"stopped, rerun open once they exit): {', '.join(running)}"
            )
        sleep(poll_s)
    units = []
    for name in names:
        if name.endswith(".timer"):
            action = "start" if active_at_open[name] else "none"
        else:
            action = "start" if active_at_open[name] and name not in batch_services else "none"
        units.append(
            {
                "name": name,
                "cleared_by": None,
                "evidence": None,
                "active_at_open": active_at_open[name],
                "resume_action": action,
            }
        )
    data = {"opened_at": _now(), "units": units}
    _save(record, data)
    return data


def clear_unit(record: Path, name: str, plan: str, evidence: Path) -> None:
    data = _load(record)
    unit = next((u for u in data["units"] if u["name"] == name), None)
    if unit is None:
        raise WindowError(f"{name} is not in the record")
    if not Path(evidence).exists():
        raise WindowError(f"evidence file does not exist: {evidence}")
    unit["cleared_by"] = plan
    unit["evidence"] = str(evidence)
    _save(record, data)


def _resume(data: dict, unit: dict, ctl: Systemctl) -> None:
    if unit.get("resume_action", "start") == "start":
        ctl("start", unit["name"])
    data["units"] = [u for u in data["units"] if u["name"] != unit["name"]]


def resume_unit(record: Path, name: str, ctl: Systemctl) -> None:
    data = _load(record)
    unit = next((u for u in data["units"] if u["name"] == name), None)
    if unit is None:
        raise WindowError(f"{name} is not in the record")
    if unit["cleared_by"] is None:
        raise WindowError(f"refusing to resume uncleared unit {name}")
    _resume(data, unit, ctl)
    _save(record, data)


def resume_all(record: Path, ctl: Systemctl) -> None:
    data = _load(record)
    uncleared = [u["name"] for u in data["units"] if u["cleared_by"] is None]
    if uncleared:
        raise WindowError(f"refusing resume --all, uncleared: {', '.join(uncleared)}")
    for unit in list(data["units"]):
        _resume(data, unit, ctl)
    _save(record, data)


def _real_systemctl(*args: str) -> str:
    password = os.environ.get("SUDO_PASS")
    if password:
        cmd = ["/usr/bin/sudo.ws", "-S", "systemctl", *args]
    else:
        cmd = ["systemctl", *args]
    out = subprocess.run(
        cmd,
        input=(password + "\n") if password else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if args[0] != "is-active" and out.returncode != 0:
        raise WindowError(f"systemctl {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def _batch_services(names: list[str], systemd_dir: Path) -> set[str]:
    """Services that a held timer triggers: they finish on their own once the timer is stopped."""
    services = {p.name: p.read_text() for p in systemd_dir.glob("*.service")}
    batch: set[str] = set()
    for timer in (n for n in names if n.endswith(".timer")):
        text = (systemd_dir / timer).read_text()
        batch.add(_unit_target(text, timer))
    return {b for b in batch if _template_match(b, services) is not None}


def _print_status(record: Path, ctl: Systemctl) -> None:
    data = _load(record)
    print(f"window opened {data['opened_at']}")
    for unit in data["units"]:
        state = ctl("is-active", unit["name"]).strip()
        print(f"{unit['name']:60s} {state:10s} cleared_by={unit['cleared_by']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_open = sub.add_parser("open")
    p_open.add_argument("--wait-s", type=float, default=3600.0)
    p_open.add_argument("--poll-s", type=float, default=15.0)
    p_open.add_argument("--dry-run", action="store_true")
    sub.add_parser("status")
    p_clear = sub.add_parser("clear")
    p_clear.add_argument("--unit", required=True)
    p_clear.add_argument("--plan", required=True)
    p_clear.add_argument("--evidence", required=True)
    p_resume = sub.add_parser("resume")
    group = p_resume.add_mutually_exclusive_group(required=True)
    group.add_argument("--unit")
    group.add_argument("--all", action="store_true")
    args = parser.parse_args()
    try:
        if args.cmd == "open":
            names = held_units(_SYSTEMD_DIR, module_set())
            if args.dry_run:
                print("\n".join(names))
                return 0
            if _RECORD.exists():
                raise WindowError(f"window already open: {_RECORD}")
            open_window(
                names,
                _RECORD,
                _real_systemctl,
                wait_s=args.wait_s,
                poll_s=args.poll_s,
                batch_services=_batch_services(names, _SYSTEMD_DIR),
            )
            _print_status(_RECORD, _real_systemctl)
        elif args.cmd == "status":
            _print_status(_RECORD, _real_systemctl)
        elif args.cmd == "clear":
            clear_unit(_RECORD, args.unit, args.plan, Path(args.evidence))
        elif args.cmd == "resume":
            if args.all:
                resume_all(_RECORD, _real_systemctl)
            else:
                resume_unit(_RECORD, args.unit, _real_systemctl)
    except WindowError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
