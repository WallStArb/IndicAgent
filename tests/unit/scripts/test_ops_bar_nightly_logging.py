"""The Alpaca nightly logs to its own file at info, not to journald (todo 598).

Without `setup_service_logging` structlog printed every per-session selection debug line to stdout, which
systemd sends to journald (about 47 MB/h on the 596 re-ask). The check runs in a subprocess so the
process-wide logging configuration of the test session is never touched."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "ops" / "bars" / "ops_bar_nightly.py"


def test_debug_lines_stay_out_of_stdout_and_warnings_reach_the_log_file(tmp_path: Path) -> None:
    log_file = tmp_path / "ops_bar_nightly.log"
    code = (
        "import structlog\n"
        "from scripts.ops.bars import ops_bar_nightly as nightly\n"
        "from src.core.service_utils import setup_service_logging\n"
        f"setup_service_logging({str(log_file)!r})\n"
        "structlog.get_logger('services.bar_selection').debug('bar_selection.session_choice', s=1)\n"
        "nightly._logger.warning('ops_bar_nightly.window_failed', symbol='AAA')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "session_choice" not in result.stdout + result.stderr
    assert "window_failed" not in result.stdout
    text = log_file.read_text()
    assert "ops_bar_nightly.window_failed" in text and "session_choice" not in text


def test_main_configures_logging_before_any_work() -> None:
    main = next(
        node
        for node in ast.parse(SCRIPT.read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    calls = [
        node.func.id
        for node in ast.walk(main)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "setup_service_logging" in calls
    assert calls.index("setup_service_logging") < calls.index("get_settings")
