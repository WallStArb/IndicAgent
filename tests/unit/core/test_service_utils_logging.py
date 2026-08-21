"""Unit tests for src.core.service_utils.setup_service_logging (todo 315).

No prior test coverage existed for this function at all before this file -- adding it
alongside the sys.excepthook fix, not just testing the new behavior in isolation.
"""

from __future__ import annotations

import logging
import sys

import pytest

from src.core import service_utils


@pytest.fixture(autouse=True)
def _reset_logging_state(monkeypatch):
    """setup_service_logging is idempotent via a module-level global (first call wins,
    by design -- prevents BaseDaemon.__init__ from overwriting a pre-configured log
    path in production). Tests need each call to actually run the setup path, so reset
    the global and the real sys.excepthook around every test."""
    monkeypatch.setattr(service_utils, "_configured_log_file", None)
    original_excepthook = sys.excepthook
    yield
    sys.excepthook = original_excepthook


@pytest.mark.unit
def test_installs_excepthook(tmp_path):
    """setup_service_logging replaces sys.excepthook with the rotation-safe logger."""
    log_file = str(tmp_path / "test_service.log")
    service_utils.setup_service_logging(log_file)
    assert sys.excepthook is service_utils._log_uncaught_exception


@pytest.mark.unit
def test_second_call_is_noop_and_does_not_reinstall(tmp_path, monkeypatch):
    """Idempotency (first call wins) still holds -- a second call must not re-run setup,
    including not touching sys.excepthook again (a sentinel from the first call must
    survive a second setup_service_logging() call untouched)."""
    log_file = str(tmp_path / "test_service.log")
    service_utils.setup_service_logging(log_file)

    sentinel = object()
    monkeypatch.setattr(sys, "excepthook", sentinel)

    service_utils.setup_service_logging(str(tmp_path / "different.log"))
    assert sys.excepthook is sentinel


@pytest.mark.unit
def test_uncaught_exception_reaches_the_log_file(tmp_path):
    """The actual bug this fixes: an uncaught exception must land in the file
    RotatingFileHandler is writing to -- not just print to stderr, which a stale
    shell-redirect fd could be the only thing capturing (todo 315)."""
    log_file = tmp_path / "test_service.log"
    service_utils.setup_service_logging(str(log_file))

    try:
        raise ValueError("boom -- deliberate test exception")
    except ValueError:
        exc_type, exc_value, exc_tb = sys.exc_info()

    sys.excepthook(exc_type, exc_value, exc_tb)

    contents = log_file.read_text()
    assert "Uncaught exception" in contents
    assert "boom -- deliberate test exception" in contents


@pytest.mark.unit
def test_uncaught_exception_still_calls_original_excepthook(tmp_path, monkeypatch):
    """Preserves the stderr print for a live terminal -- this is a durable second copy,
    not a replacement of existing crash-visibility behavior."""
    log_file = str(tmp_path / "test_service.log")
    service_utils.setup_service_logging(log_file)

    calls = []
    monkeypatch.setattr(service_utils, "_ORIGINAL_EXCEPTHOOK", lambda *a: calls.append(a))

    try:
        raise ValueError("boom")
    except ValueError:
        exc_type, exc_value, exc_tb = sys.exc_info()
    sys.excepthook(exc_type, exc_value, exc_tb)

    assert len(calls) == 1
    assert calls[0][0] is exc_type


@pytest.mark.unit
def test_keyboard_interrupt_not_logged_as_crash(tmp_path, monkeypatch):
    """Ctrl-C is operator-initiated, not a real crash -- must not pollute the log at
    CRITICAL level, but the original excepthook must still fire (normal exit path)."""
    log_file = tmp_path / "test_service.log"
    service_utils.setup_service_logging(str(log_file))

    calls = []
    monkeypatch.setattr(service_utils, "_ORIGINAL_EXCEPTHOOK", lambda *a: calls.append(a))

    try:
        raise KeyboardInterrupt()
    except KeyboardInterrupt:
        exc_type, exc_value, exc_tb = sys.exc_info()
    sys.excepthook(exc_type, exc_value, exc_tb)

    assert len(calls) == 1  # original hook still called
    if log_file.exists():
        assert "Uncaught exception" not in log_file.read_text()


@pytest.mark.unit
def test_normal_log_statements_still_reach_the_file(tmp_path):
    """Sanity check the pre-existing behavior (RotatingFileHandler wiring) is unchanged
    by this fix -- a normal log call still lands in log_file."""
    log_file = tmp_path / "test_service.log"
    service_utils.setup_service_logging(str(log_file))

    logging.getLogger("test_logger").info("hello from a normal log call")

    assert "hello from a normal log call" in log_file.read_text()
