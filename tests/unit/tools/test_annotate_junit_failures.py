"""tools/annotate_junit_failures.py: failed tests become GitHub error annotations."""

from tools import annotate_junit_failures as ann

XML = """<testsuites><testsuite>
<testcase classname="tests.unit.a" name="test_ok"/>
<testcase classname="tests.unit.b" name="test_bad"><failure message="assert 1 == 2&#10;more">trace</failure></testcase>
<testcase classname="tests.unit.c" name="test_err"><error message="boom: 100% sure"/></testcase>
</testsuite></testsuites>"""


def test_failures_and_errors_are_annotated_and_counted(tmp_path):
    path = tmp_path / "r.xml"
    path.write_text(XML)
    lines = ann.annotations(path)
    assert lines[0] == "::error title=tests.unit.b::test_bad::assert 1 == 2"
    assert lines[1] == "::error title=tests.unit.c::test_err::boom: 100%25 sure"
    assert lines[-1] == "::error title=unit test failures::2 failed or errored in total"


def test_the_annotation_count_is_capped_but_the_total_is_kept(tmp_path):
    cases = "".join(
        f'<testcase classname="c" name="t{i}"><failure message="m"/></testcase>' for i in range(30)
    )
    path = tmp_path / "r.xml"
    path.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>")
    lines = ann.annotations(path)
    assert len(lines) == ann.MAX_ANNOTATIONS + 1
    assert lines[-1].endswith("30 failed or errored in total")


def test_a_clean_run_prints_nothing_and_a_missing_file_warns(tmp_path, capsys):
    path = tmp_path / "r.xml"
    path.write_text(
        '<testsuites><testsuite><testcase classname="c" name="t"/></testsuite></testsuites>'
    )
    assert ann.annotations(path) == []
    assert ann.main([str(tmp_path / "absent.xml")]) == 0
    assert "was not written" in capsys.readouterr().out


SKIPS = """<testsuites><testsuite>
<testcase classname="a" name="t1"><skipped message="local PostgreSQL not reachable"/></testcase>
<testcase classname="a" name="t2"><skipped message="local PostgreSQL not reachable"/></testcase>
<testcase classname="b" name="t3"><skipped message="shallow clone&#10;second line"/></testcase>
<testcase classname="c" name="t4"/>
</testsuite></testsuites>"""


def test_skips_are_counted_by_reason(tmp_path):
    path = tmp_path / "r.xml"
    path.write_text(SKIPS)
    assert ann.skip_counts(path) == {"local PostgreSQL not reachable": 2, "shallow clone": 1}
    assert ann.skip_summary(path) == (
        "::notice title=unit test skips::3 skipped. 2 x local PostgreSQL not reachable; 1 x shallow clone"
    )


def test_a_run_without_skips_still_reports_zero(tmp_path):
    path = tmp_path / "r.xml"
    path.write_text(XML)
    assert ann.skip_summary(path) == "::notice title=unit test skips::0 skipped."
