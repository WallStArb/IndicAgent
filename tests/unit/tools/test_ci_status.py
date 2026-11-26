"""Unit tests for tools/ci_status.py: the verdict over check runs, the wait loop and the API
errors. The GitHub API is never called."""

import io
import json
import urllib.error

import pytest

from tools import ci_status


def run(name="Unit Tests", status="completed", conclusion="success"):
    return {"name": name, "status": status, "conclusion": conclusion}


def test_all_completed_and_successful_passes():
    assert ci_status.verdict([run(), run("Lint & Format")]) == ci_status.PASS


@pytest.mark.parametrize("bad", ["failure", "cancelled", "skipped", "timed_out"])
def test_a_finished_check_without_success_fails_even_while_others_run(bad):
    runs = [run(conclusion=bad), run("Lint & Format", "in_progress", None)]
    assert ci_status.verdict(runs) == ci_status.FAIL


def test_a_running_or_queued_check_is_pending():
    assert ci_status.verdict([run(), run("x", "queued", None)]) == ci_status.PENDING


def test_no_checks_is_its_own_state_and_not_a_pass():
    assert ci_status.verdict([]) == ci_status.NONE
    assert ci_status.EXIT[ci_status.NONE] == 1 and ci_status.EXIT[ci_status.PASS] == 0


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:Owner/Name.git",
        "https://github.com/Owner/Name.git",
        "https://github.com/Owner/Name",
    ],
)
def test_repo_of_reads_ssh_and_https_remotes(url):
    assert ci_status.repo_of(url) == "Owner/Name"


def test_repo_of_refuses_a_foreign_remote():
    with pytest.raises(ci_status.ApiError):
        ci_status.repo_of("git@gitlab.com:a/b.git")


def reads(*states):
    it = iter(states)
    return lambda: next(it)


def test_wait_polls_until_the_verdict_is_final():
    clock = iter(range(0, 1000, 1))
    slept = []
    state, runs = ci_status.wait_for(
        reads([], [run(status="queued", conclusion=None)], [run()]),
        timeout=600,
        poll=20,
        sleep=slept.append,
        clock=lambda: next(clock),
    )
    assert state == ci_status.PASS and slept == [20, 20]


def test_wait_stops_at_the_first_failure():
    state, _ = ci_status.wait_for(
        reads([run(conclusion="failure"), run("b", "in_progress", None)]),
        timeout=600,
        sleep=lambda s: pytest.fail("must not sleep after a failure"),
    )
    assert state == ci_status.FAIL


def test_wait_returns_the_last_read_pending_when_the_timeout_ends():
    ticks = iter([0, 0, 30, 60])
    state, runs = ci_status.wait_for(
        lambda: [run(status="in_progress", conclusion=None)],
        timeout=50,
        poll=20,
        sleep=lambda s: None,
        clock=lambda: next(ticks),
    )
    assert state == ci_status.PENDING and runs


class _Ctx(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener(runs, total=None):
    payload = json.dumps({"total_count": len(runs) if total is None else total, "check_runs": runs})
    return lambda request, timeout: _Ctx(payload.encode())


def test_fetch_reads_the_check_runs():
    assert ci_status.fetch_runs("o/n", "abc", opener([run()])) == [run()]


def test_fetch_refuses_a_truncated_page():
    with pytest.raises(ci_status.ApiError, match="one page"):
        ci_status.fetch_runs("o/n", "abc", opener([run()], total=150))


def test_fetch_names_an_http_error():
    def deny(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "nf", {}, None)

    with pytest.raises(ci_status.ApiError, match="404"):
        ci_status.fetch_runs("o/n", "abc", deny)


def test_render_lists_each_check_with_its_conclusion():
    text = ci_status.render([run("B", "in_progress", None), run("A")])
    assert text.splitlines()[0].startswith("A") and text.splitlines()[1].endswith("-")
