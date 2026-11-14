"""corpus_rerun --quiesce and --release: the runbook's manual step 2 as two commands.

``quiesce`` disables and stops every unit in ``infra.corpus_rerun.blocking_timers`` and waits until
the services they start are inactive or failed, after recording the prior enabled and active set to
a file under logs/. ``release`` puts back exactly that recorded set and removes the file. Both
refuse while a corpus rerun, ic_measure or rebuild writer is live (the pin gate's own check), and
both are safe to repeat: a second ``quiesce`` keeps the first record (a timer found enabled again
is added to it, never dropped), a second ``release`` finds no record and does nothing.

The pin gate (``CorpusRerun.pin_checks``) keeps only checking; it never changes a unit.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENABLED_STATES = frozenset({"enabled", "enabled-runtime"})
SETTLED_STATES = frozenset({"inactive", "failed"})
QUIET_ENABLED_STATES = frozenset({"disabled", "masked"})  # what the pin gate accepts of a timer


def timer_is_quiet(enabled: str, service_active: str) -> bool:
    """The pin gate's rule for a blocking timer: not enabled, and its service not running."""
    return enabled in QUIET_ENABLED_STATES and service_active in SETTLED_STATES


STATE_FILE_NAME = "corpus_rerun_quiesce.json"


class QuiesceError(RuntimeError):
    """A refusal or a unit that did not reach the wanted state; the record file stays."""


@dataclass(frozen=True)
class QuiesceDeps:
    query: Callable[[str, str], str]  # systemctl is-enabled | is-active <unit> -> first line
    change: Callable[[str, str], None]  # systemctl disable | stop | enable | start <unit>; raises
    no_live_run: Callable[[], Any]  # a CheckResult: .ok, .detail
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic


def real_change(verb: str, unit: str) -> None:
    done = subprocess.run(
        ["sudo", "-n", "systemctl", verb, unit], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise QuiesceError(
            f"systemctl {verb} {unit} failed: {(done.stderr or done.stdout).strip()}"
        )


def state_path(logs_dir: Path) -> Path:
    return logs_dir / STATE_FILE_NAME


def service_of(timer: str) -> str:
    return timer.removesuffix(".timer") + ".service"


def _read_record(path: Path) -> dict[str, dict[str, bool]]:
    return json.loads(path.read_text())["timers"] if path.exists() else {}


def _write_record(path: Path, timers: Mapping[str, Mapping[str, bool]]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"timers": dict(timers)}, indent=2, sort_keys=True))
    os.replace(tmp, path)


def _refuse_if_live(deps: QuiesceDeps) -> None:
    live = deps.no_live_run()
    if not live.ok:
        raise QuiesceError(f"refused: {live.detail}")


def _observe(deps: QuiesceDeps, timer: str) -> dict[str, bool]:
    return {
        "enabled": deps.query("is-enabled", timer) in ENABLED_STATES,
        "active": deps.query("is-active", timer) == "active",
    }


def quiesce(
    timers: Sequence[str],
    deps: QuiesceDeps,
    path: Path,
    *,
    wait_seconds: float,
    poll_seconds: float,
) -> None:
    """Record, disable and stop each timer, then wait for its service to settle."""
    _refuse_if_live(deps)
    recorded = _read_record(path)
    now = {timer: _observe(deps, timer) for timer in timers}
    prior = {
        timer: {
            key: recorded.get(timer, {}).get(key, False) or now[timer][key]
            for key in ("enabled", "active")
        }
        for timer in timers
    }
    _write_record(path, {**recorded, **prior})  # before any change: a crash leaves the way back
    for timer in timers:
        if now[timer]["enabled"]:
            deps.change("disable", timer)
        if now[timer]["active"]:
            deps.change("stop", timer)
    deadline = deps.monotonic() + wait_seconds
    busy = [service_of(t) for t in timers]
    while busy := [s for s in busy if deps.query("is-active", s) not in SETTLED_STATES]:
        if deps.monotonic() >= deadline:
            raise QuiesceError(f"services still running after {wait_seconds:.0f} s: {busy}")
        deps.sleep(poll_seconds)
    not_quiet = {
        t: deps.query("is-enabled", t)
        for t in timers
        if not timer_is_quiet(deps.query("is-enabled", t), deps.query("is-active", service_of(t)))
    }
    if not_quiet:  # e.g. a unit that no longer exists, or enabled-runtime: the pin gate refuses it
        raise QuiesceError(f"not quiet after the disable, the pin gate would refuse: {not_quiet}")


def release(deps: QuiesceDeps, path: Path) -> list[str]:
    """Restore the recorded set exactly and remove the record; the timers put back are returned
    (empty when nothing was recorded)."""
    _refuse_if_live(deps)
    recorded = _read_record(path)
    for timer, was in recorded.items():
        if was["enabled"]:
            deps.change("enable", timer)
        if was["active"]:
            deps.change("start", timer)
    wrong = [
        t
        for t, was in recorded.items()
        if (deps.query("is-enabled", t) in ENABLED_STATES) != was["enabled"]
    ]
    if wrong:
        raise QuiesceError(f"not restored to the recorded enabled state: {wrong}")
    if recorded:
        path.unlink()
    return sorted(t for t, was in recorded.items() if was["enabled"])
