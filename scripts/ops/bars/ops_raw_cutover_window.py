"""Cutover window for the unified raw bar table (phase 191 plan 04).

TEMPORARY: deleted at phase 191 close with the other cutover scaffolding.

`open` stops the fetcher timer and every timer or service whose ExecStart names a module that
reads or writes the old stores or canonical bars, records the held list in
`logs/raw_cutover_window.json`, and never kills a running batch: timers are stopped first, a
running batch service is left to finish on its own within a bounded wait, and the open aborts
if it does not (the record is written first with state "opening", so a re-run keeps the recorded
active state of timers it already stopped). `clear` marks a unit as cut over (the reader plan's evidence
file must exist); `resume` restarts a cleared unit and drops it from the record, refusing a unit whose dependencies
(`UNIT_DEPENDENCIES`: the fetcher timer needs its service, which needs bar derivation) are
uncleared, and the fetcher pair until plans 06, 08 and 10 have summaries unless
`--override-fetcher-plan-gate` (logged); `resume --all`
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

_PHASE_DIR = _REPO_ROOT / ".planning" / "phases" / "191-unified-raw-bar-table"
_OVERRIDE_LOG = _REPO_ROOT / "logs" / "raw_cutover_window_overrides.log"

FETCHER_TIMER = "indicagent-ibkr-history-fetcher.timer"
FETCHER_SERVICE = "indicagent-ibkr-history-fetcher.service"

# Modules the fetcher service runs: bar_derivation as a subprocess, the rest in-process. Only
# bar_derivation has a unit of its own; the others are covered by clearing the fetcher service.
FETCHER_RUNS_MODULES = ("bar_derivation", "split_detection", "bar_hold", "ohlcv_coverage_writer")
MODULE_UNITS = {"bar_derivation": "indicagent-bar-derivation.service"}

# unit -> units that must be cleared (or already resumed) before it may resume. A timer needs
# the service it triggers; the fetcher service needs every unit whose module it runs.
UNIT_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    FETCHER_TIMER: (FETCHER_SERVICE,),
    FETCHER_SERVICE: tuple(MODULE_UNITS.values()),
}

# The fetcher pair also stays held until these plans have a SUMMARY (planner and coverage on raw,
# split detection and the daily rule on raw, the selection gate).
FETCHER_PLANS = ("191-06", "191-08", "191-10")


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
    """Stop timers, stop non-batch services, wait for batch services to exit, then record.

    The pre-stop active state is persisted (state "opening") before anything is stopped, so an
    open that aborts at the bounded wait and is re-run keeps the timers' resume action."""
    prior = _load(record) if record.exists() else None
    if prior is not None and prior.get("state", "open") != "opening":
        raise WindowError(f"window already open: {record}")
    recorded = {u["name"]: u["active_at_open"] for u in (prior or {}).get("units", [])}
    active_at_open = {
        n: recorded[n] if n in recorded else ctl("is-active", n).strip() == "active" for n in names
    }
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
    data = {
        "opened_at": (prior or {}).get("opened_at", _now()),
        "state": "opening",
        "units": units,
    }
    _save(record, data)
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
    data["state"] = "open"
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


def fetcher_plans_done(phase_dir: Path = _PHASE_DIR) -> list[str]:
    """Fetcher gate plans that have a SUMMARY.md in the phase directory."""
    return [p for p in FETCHER_PLANS if (phase_dir / f"{p}-SUMMARY.md").exists()]


def _dependency_closure(name: str) -> list[str]:
    seen: list[str] = []
    stack = list(UNIT_DEPENDENCIES.get(name, ()))
    while stack:
        dep = stack.pop(0)
        if dep not in seen:
            seen.append(dep)
            stack.extend(UNIT_DEPENDENCIES.get(dep, ()))
    return seen


def _check_resumable(
    data: dict,
    unit: dict,
    fetcher_plans_done_fn: Callable[[], list[str]],
    override: bool,
) -> None:
    name = unit["name"]
    if unit["cleared_by"] is None:
        raise WindowError(f"refusing to resume uncleared unit {name}")
    held = {u["name"]: u for u in data["units"]}
    uncleared = [
        d for d in _dependency_closure(name) if d in held and held[d]["cleared_by"] is None
    ]
    if uncleared:
        raise WindowError(
            f"refusing to resume {name}: it runs or triggers uncleared {', '.join(uncleared)}"
        )
    if name in (FETCHER_TIMER, FETCHER_SERVICE):
        missing = [p for p in FETCHER_PLANS if p not in fetcher_plans_done_fn()]
        if missing and not override:
            raise WindowError(
                f"refusing to resume {name}: the fetcher stays held until plans "
                f"{', '.join(FETCHER_PLANS)} are done (no SUMMARY for {', '.join(missing)}); "
                "override only with --override-fetcher-plan-gate (logged)"
            )
        if missing:
            entry = {"unit": name, "missing_plans": missing, "at": _now()}
            data.setdefault("fetcher_gate_overrides", []).append(entry)


def _log_override(data: dict, start: int, log: Path) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as fh:
        for entry in data.get("fetcher_gate_overrides", [])[start:]:
            fh.write(json.dumps({"event": "fetcher_plan_gate_override", **entry}) + "\n")


def _resume(data: dict, unit: dict, ctl: Systemctl) -> None:
    if unit.get("resume_action", "start") == "start":
        ctl("start", unit["name"])
    data["units"] = [u for u in data["units"] if u["name"] != unit["name"]]


def resume_unit(
    record: Path,
    name: str,
    ctl: Systemctl,
    *,
    fetcher_plans_done: Callable[[], list[str]] | None = None,
    override_fetcher_plan_gate: bool = False,
    override_log: Path = _OVERRIDE_LOG,
) -> None:
    done_fn = (
        fetcher_plans_done if fetcher_plans_done is not None else globals()["fetcher_plans_done"]
    )
    data = _load(record)
    unit = next((u for u in data["units"] if u["name"] == name), None)
    if unit is None:
        raise WindowError(f"{name} is not in the record")
    start = len(data.get("fetcher_gate_overrides", []))
    _check_resumable(data, unit, done_fn, override_fetcher_plan_gate)
    _log_override(data, start, override_log)
    _resume(data, unit, ctl)
    _save(record, data)


def resume_all(
    record: Path,
    ctl: Systemctl,
    *,
    fetcher_plans_done: Callable[[], list[str]] | None = None,
    override_fetcher_plan_gate: bool = False,
    override_log: Path = _OVERRIDE_LOG,
) -> None:
    done_fn = (
        fetcher_plans_done if fetcher_plans_done is not None else globals()["fetcher_plans_done"]
    )
    data = _load(record)
    uncleared = [u["name"] for u in data["units"] if u["cleared_by"] is None]
    if uncleared:
        raise WindowError(f"refusing resume --all, uncleared: {', '.join(uncleared)}")
    start = len(data.get("fetcher_gate_overrides", []))
    for unit in data["units"]:
        _check_resumable(data, unit, done_fn, override_fetcher_plan_gate)
    _log_override(data, start, override_log)
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
    p_resume.add_argument("--override-fetcher-plan-gate", action="store_true")
    args = parser.parse_args()
    try:
        if args.cmd == "open":
            names = held_units(_SYSTEMD_DIR, module_set())
            if args.dry_run:
                print("\n".join(names))
                return 0
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
                resume_all(
                    _RECORD,
                    _real_systemctl,
                    override_fetcher_plan_gate=args.override_fetcher_plan_gate,
                )
            else:
                resume_unit(
                    _RECORD,
                    args.unit,
                    _real_systemctl,
                    override_fetcher_plan_gate=args.override_fetcher_plan_gate,
                )
    except WindowError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
