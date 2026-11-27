"""tools/todo_claims.py on planted todos: each claim rule of PLANNING-SYSTEM.md and staleness."""

from datetime import UTC, datetime, timedelta

import pytest

from tools import todo_claims as tc

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
GOOD = "claimed_by: indicagent-03\nclaimed_at: 2026-11-27T07:12:38+00:00\n"


def _todo(
    claim: str = GOOD, head: str = "status: pending\nclaimable: true\n", body: str = ""
) -> str:
    return f"---\n{head}{claim}---\n\n# Title\n{body}"


def _errors(text: str, todo: str = "pending/700-x.md") -> tuple[str, ...]:
    claim = tc.parse_claim(todo, text, NOW)
    assert claim is not None
    return claim.errors


def test_a_well_formed_claim_has_no_error_and_an_unclaimed_todo_is_not_a_claim():
    assert _errors(_todo()) == ()
    assert tc.parse_claim("pending/700-x.md", _todo(claim=""), NOW) is None


def test_two_claimed_by_lines_left_by_a_race_are_rejected():
    raced = (
        "claimed_by: indicagent-03\nclaimed_by: indicagent-07\nclaimed_at: 2026-11-27T07:00:00Z\n"
    )
    assert any("more than one claimed_by" in error for error in _errors(_todo(raced)))


@pytest.mark.parametrize(
    "worker", ["", "null", "~", "none", "Brandon", "Indicagent-03", "indicagent-", "main", "a b"]
)
def test_claimed_by_must_be_a_session_name(worker):
    claim = f"claimed_by: {worker}\nclaimed_at: 2026-11-27T07:00:00+00:00\n"
    assert any("not a session name" in error for error in _errors(_todo(claim)))


@pytest.mark.parametrize(
    "at", ["", "2026-11-27", "2026-11-27T07:00:00", "2026-11-27T07:00:00-05:00", "soon"]
)
def test_claimed_at_must_be_a_utc_iso_time(at):
    claim = f"claimed_by: indicagent-03\nclaimed_at: {at}\n"
    assert any("not a UTC ISO time" in error for error in _errors(_todo(claim)))


def test_a_future_claimed_at_is_rejected_beyond_the_clock_skew():
    def at(offset: timedelta) -> str:
        return _todo(f"claimed_by: indicagent-03\nclaimed_at: {(NOW + offset).isoformat()}\n")

    assert _errors(at(tc.CLOCK_SKEW)) == ()
    assert "claimed_at is in the future" in _errors(at(tc.CLOCK_SKEW + timedelta(seconds=1)))


@pytest.mark.parametrize(
    "text",
    [
        _todo(claim="  claimed_by: indicagent-03\n  claimed_at: 2026-11-27T07:00:00Z\n"),
        _todo(claim="- claimed_by: indicagent-03\n- claimed_at: 2026-11-27T07:00:00Z\n"),
        _todo(claim="* claimed_by: indicagent-03\n* claimed_at: 2026-11-27T07:00:00Z\n"),
        _todo(claim="\"claimed_by\": indicagent-03\n'claimed_at': 2026-11-27T07:00:00Z\n"),
        _todo(claim=GOOD + "notes:\n  claimed_by: indicagent-07\n"),  # a valid one hides no other
        f"{GOOD}\n# no frontmatter\n",
        f"status: pending\n{GOOD}",  # no block and no heading
    ],
    ids=[
        "indented",
        "dash",
        "star",
        "quoted",
        "nested-second",
        "no-frontmatter",
        "no-block-no-heading",
    ],
)
def test_a_claim_field_outside_the_line1_top_level_frontmatter_is_rejected(text):
    assert any("outside the line-1 frontmatter" in error for error in _errors(text))


@pytest.mark.parametrize(
    ("todo", "head"),
    [("pending/700-x.md", "status: pending\n"), ("completed/700-x.md", "claimable: true\n")],
)
def test_only_a_pending_claimable_todo_is_claimed(todo, head):
    assert any("claimable: true" in error for error in _errors(_todo(head=head), todo))


@pytest.mark.parametrize(
    "text",
    [
        _todo(claim="", body=f"- claimed_by: <name> is how it reads\n\n```yaml\n{GOOD}```\n"),
        f"---\nstatus: pending\n---\n\nSome text\n- claimed_by: <name>\n~~~\n{GOOD}~~~\n",
        f"# Title\n{GOOD}",
    ],
    ids=["under-title", "no-heading", "title-first"],
)
def test_a_claim_line_in_the_body_is_prose_not_a_claim(text):
    """Only the head of a todo can hold a claim (PLANNING-SYSTEM.md); a body may quote one."""
    assert tc.parse_claim("pending/700-x.md", text, NOW) is None


def test_claimed_at_without_claimed_by_is_a_broken_claim():
    errors = _errors(_todo(claim="claimed_at: 2026-11-27T07:00:00Z\n"))
    assert "claimed_by '' is not a session name" in errors


def test_a_claim_is_stale_after_stale_days_from_claimed_at():
    def claim(age: timedelta) -> tc.Claim:
        return tc.Claim("pending/700-x.md", {}, NOW - age, ())

    days = timedelta(days=tc.STALE_DAYS)
    assert not tc.is_stale(claim(days), NOW)
    assert tc.is_stale(claim(days + timedelta(seconds=1)), NOW)


def test_main_exits_0_on_a_fresh_claim_and_1_on_a_broken_or_stale_one(tmp_path, capsys):
    def run(claim: str) -> tuple[int, str]:
        (tmp_path / "pending").mkdir(exist_ok=True)
        (tmp_path / "pending" / "700-x.md").write_text(_todo(claim=claim))
        return tc.main(tmp_path), capsys.readouterr().out

    def at(age: timedelta) -> str:
        return f"claimed_by: indicagent-03\nclaimed_at: {(datetime.now(UTC) - age).isoformat()}\n"

    code, out = run(at(timedelta(days=1)))
    assert code == 0 and "age 24.0 h" in out and "PROBLEM" not in out
    code, out = run(at(timedelta(days=tc.STALE_DAYS, hours=1)))
    assert code == 1 and "PROBLEM pending/700-x.md: stale, age 73.0 h > 72 h" in out
    code, out = run("claimed_by: null\n")
    assert code == 1 and "PROBLEM pending/700-x.md: claimed_by 'null' is not a session name" in out


IDS = {"O1", "O2"}
LATER = f"{tc.OBJECTIVE_REQUIRED_AFTER + 1}-x.md"


def _objective(line: str) -> str:
    return f"---\nstatus: pending\n{line}---\n\n# Title\n"


def test_objective_ids_are_read_from_the_table_rows_only():
    text = "Use `objective: O9` in prose.\n\n| Id | Outcome |\n|---|---|\n| O1 | a |\n| O2 | b |\n"
    assert tc.objective_ids(text) == ["O1", "O2"]


def test_a_known_objective_passes_and_an_older_todo_may_omit_it():
    assert tc.objective_errors(LATER, _objective("objective: O1\n"), IDS) == ()
    assert tc.objective_errors("600-x.md", _objective(""), IDS) == ()


def test_a_later_todo_without_an_objective_is_rejected():
    assert any("no objective" in e for e in tc.objective_errors(LATER, _objective(""), IDS))
    no_block = "# Title\n\nobjective: O1\n"  # a body line is prose, not the field
    assert any("no objective" in e for e in tc.objective_errors(LATER, no_block, IDS))


@pytest.mark.parametrize("value", ["O3", "o1", "", "O1, O2"])
def test_an_unknown_objective_is_rejected_on_any_todo(value):
    for name in (LATER, "600-x.md"):
        errors = tc.objective_errors(name, _objective(f"objective: {value}\n"), IDS)
        assert any("not an id in OBJECTIVES.md" in e for e in errors)


def test_two_objective_lines_are_rejected():
    errors = tc.objective_errors(LATER, _objective("objective: O1\nobjective: O2\n"), IDS)
    assert any("more than one objective" in e for e in errors)
