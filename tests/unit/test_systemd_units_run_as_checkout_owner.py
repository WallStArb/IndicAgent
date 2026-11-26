"""Units that run repo Python must run as the checkout owner (todo 479).

A unit without `User=` runs as root and leaves a root-owned file under `logs/`,
which then breaks any user-run import of the service module or its unit test
with a PermissionError. Root-only units (sysfs writes, ready probes) never
invoke the repo venv, so they stay exempt.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

UNIT_DIR = Path(__file__).resolve().parents[2] / "production" / "systemd"
_VENV_PYTHON = re.compile(r"^ExecStart=\S*/\.venv/bin/python\b", re.MULTILINE)
_USER = re.compile(r"^User=bg$", re.MULTILINE)
_REPO_PYTHON_UNITS = sorted(
    path for path in UNIT_DIR.glob("*.service") if _VENV_PYTHON.search(path.read_text())
)


def test_repo_python_units_exist() -> None:
    assert _REPO_PYTHON_UNITS, "no repo-python units found; the scan is broken"


@pytest.mark.parametrize("unit", _REPO_PYTHON_UNITS, ids=lambda path: path.name)
def test_repo_python_unit_declares_user(unit: Path) -> None:
    assert _USER.search(unit.read_text()), f"{unit.name} runs repo Python without User=bg"
