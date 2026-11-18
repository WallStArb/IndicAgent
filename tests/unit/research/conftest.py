"""Research unit tests run real-mode runs on synthetic harnesses that are not about the battery
pass records; they get a stand-in for the record check. The tests of the check itself
(test_battery_pass.py) and the runner's refusal opt out and exercise the real one."""

import pytest

from src.intelligence.research import battery_pass

_OWN_TESTS = {"test_battery_pass", "test_runner_battery_pass_gate"}


@pytest.fixture(autouse=True)
def _battery_pass_standin(request, monkeypatch):
    if request.module.__name__.rsplit(".", 1)[-1] in _OWN_TESTS:
        return
    monkeypatch.setattr(battery_pass, "require", lambda *a, **k: "test stand-in")
