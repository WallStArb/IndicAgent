"""Tests for scripts/ops/ops_complexity_census.py (plan 185-44 task 1).

Each census count is a pure function over injected listings; these pin each definition on small
fakes. The last test pins the script's read-only contract: no write statement in its source and a
read-only database session.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.ops.ops_complexity_census import (
    DocHeader,
    UnitState,
    apr_keys_without_reader,
    count_scripts,
    has_apr_reader,
    parse_dag_units,
    parse_status_line,
    parse_systemctl_show,
    phase_complete,
    plan_summary_exists,
    render_markdown,
    services_without_live_consumer,
    stale_docs,
    temporary_entries,
)

_SCRIPT = Path(__file__).parents[3] / "scripts" / "ops" / "ops_complexity_census.py"


def test_count_scripts_counts_py_and_sh_and_skips_init_and_pycache():
    paths = [
        "scripts/a.py",
        "scripts/b.sh",
        "scripts/__init__.py",
        "scripts/__pycache__/a.cpython-312.pyc",
        "scripts/__pycache__/x.py",
        "scripts/readme.md",
        "scripts/ops/bars/c.py",
        "scripts/ops/d.sh",
        "scripts/ops/__init__.py",
    ]
    result = count_scripts(paths)
    assert result["total"] == [
        "scripts/a.py",
        "scripts/b.sh",
        "scripts/ops/bars/c.py",
        "scripts/ops/d.sh",
    ]
    assert result["ops"] == ["scripts/ops/bars/c.py", "scripts/ops/d.sh"]


def test_temporary_entries_reads_flat_and_nested_allow_lists():
    source = """
_ALLOW_LIST: dict[str, str] = {
    "a.py": "PERMANENT: fine.",
    "b.py": (
        "TEMPORARY: until the lock lands "
        "(retire: 189-08)."
    ),
}
_ALLOW_LISTS = {
    "tbl": {"c.py": "TEMPORARY: no clause", "d.py": "PERMANENT"},
}
_NOT_A_DICT = "TEMPORARY"
"""
    entries = temporary_entries({"tests/unit/test_x_boundary.py": source})
    assert [(e.file, e.variable, e.key) for e in entries] == [
        ("tests/unit/test_x_boundary.py", "_ALLOW_LIST", "b.py"),
        ("tests/unit/test_x_boundary.py", "_ALLOW_LISTS", "tbl/c.py"),
    ]
    assert "retire: 189-08" in entries[0].reason


def test_temporary_entries_finds_reasons_inside_calls():
    source = """
_REGISTRY = {
    "t": (Writer("x.py", reason="TEMPORARY: second writer (retire: 185-42)"),),
}
"""
    entries = temporary_entries({"f.py": source})
    assert [(e.variable, e.key) for e in entries] == [("_REGISTRY", "t")]
    assert "retire: 185-42" in entries[0].reason


def test_apr_reader_literal_and_boundaries():
    corpus = 'cfg.get_sync("alpha.ic.lookahead.fast", 1)\nx = "infra.a.b_long"\n'
    assert has_apr_reader("alpha.ic.lookahead.fast", corpus)
    # a longer key is not a read of its prefix
    assert not has_apr_reader("infra.a.b", corpus)
    assert not has_apr_reader("infra.a", corpus)


def test_apr_reader_dynamic_suffix_by_naming_rule():
    corpus = (
        'cfg.get_sync(f"infra.backfill.depth_days.{tf}")\n'
        'cfg.get_sync(f"feature.trade_framer.target_max_atr_{tf}")\n'
        '_PREFIX = "alert.lag."\n'
    )
    assert has_apr_reader("infra.backfill.depth_days.1d", corpus)
    assert has_apr_reader("feature.trade_framer.target_max_atr_15m", corpus)
    assert has_apr_reader("alert.lag.indicagent-api", corpus)
    assert not has_apr_reader("infra.other.depth_days.1d", corpus)


def test_apr_keys_without_reader_lists_unread_keys_sorted():
    corpus = 'get("a.b.c")'
    assert apr_keys_without_reader(["z.y.x", "a.b.c", "m.n.o"], corpus) == ["m.n.o", "z.y.x"]


def test_parse_dag_units_reads_dict_keys():
    source = '_DAG_ORDER: dict[str, int] = {\n    "indicagent-a": 0,\n    "indicagent-b": 1,\n}\n'
    assert parse_dag_units(source) == ["indicagent-a", "indicagent-b"]


def test_parse_systemctl_show_blocks():
    output = (
        "Id=indicagent-a.service\nType=simple\nActiveState=active\nLoadState=loaded\n\n"
        "Id=indicagent-a.timer\nLoadState=not-found\nActiveState=inactive\n\n"
        "Id=indicagent-b.service\nType=oneshot\nActiveState=inactive\nLoadState=loaded\n"
    )
    states = parse_systemctl_show(output)
    assert states["indicagent-a.service"] == UnitState("simple", "active", "loaded")
    assert states["indicagent-a.timer"].load_state == "not-found"
    assert states["indicagent-b.service"].unit_type == "oneshot"


def test_services_without_live_consumer_definition():
    states = {
        "u-active.service": UnitState("simple", "active", "loaded"),
        "u-failed.service": UnitState("simple", "failed", "loaded"),
        "u-missing.service": UnitState("", "inactive", "not-found"),
        "u-idle.service": UnitState("simple", "inactive", "loaded"),
        "u-oneshot.service": UnitState("oneshot", "inactive", "loaded"),
        "u-timer.service": UnitState("exec", "inactive", "loaded"),
        "u-timer.timer": UnitState("", "inactive", "loaded"),
        "u-dormant.service": UnitState("simple", "active", "loaded"),
    }
    units = [
        "u-active",
        "u-failed",
        "u-missing",
        "u-idle",
        "u-oneshot",
        "u-timer",
        "u-dormant",
    ]
    result = dict(services_without_live_consumer(units, states, {"u-dormant": "archived"}))
    assert set(result) == {"u-failed", "u-missing", "u-idle", "u-dormant"}
    assert result["u-failed"] == "failed"
    assert result["u-missing"] == "missing (not-found)"
    assert "inactive" in result["u-idle"]
    assert "archived" in result["u-dormant"]


def test_parse_status_line_variants():
    assert parse_status_line("# T\n\n**Status:** draft - x\n") == "draft - x"
    assert parse_status_line("---\nstatus: proposed\n---\n") == "proposed"
    assert parse_status_line("> Status: in progress\n") == "in progress"
    assert parse_status_line("# no status here\n") is None


def test_stale_docs_age_and_completed_plan_rules():
    now = 100 * 86400
    headers = [
        DocHeader("docs/a.md", "draft", now - 31 * 86400),
        DocHeader("docs/b.md", "draft", now - 5 * 86400),
        DocHeader("docs/c.md", "proposed, lands in plan 185-27", now - 1 * 86400),
        DocHeader("docs/d.md", "current", now - 400 * 86400),
        DocHeader("docs/research/e.md", "draft", now - 400 * 86400),
        DocHeader("docs/f.md", "in progress (phase 183)", now - 1 * 86400),
        DocHeader("docs/g.md", "PROPOSED, dated 2026-10-06", now - 1 * 86400),
    ]
    result = stale_docs(
        headers,
        now_epoch=now,
        is_plan_complete=lambda plan: plan == "185-27",
        is_phase_complete=lambda phase: phase == "183",
    )
    assert [(r[0], r[2]) for r in result] == [
        ("docs/a.md", "unchanged 31 days"),
        ("docs/c.md", "names completed plan 185-27"),
        ("docs/f.md", "names completed phase 183"),
    ]


def test_plan_summary_and_phase_completion(tmp_path):
    phase = tmp_path / "phases" / "185-x"
    phase.mkdir(parents=True)
    (phase / "185-01-PLAN.md").write_text("")
    (phase / "185-01-SUMMARY.md").write_text("")
    (phase / "185-02-PLAN.md").write_text("")
    assert plan_summary_exists("185-01", tmp_path)
    assert not plan_summary_exists("185-02", tmp_path)
    assert not phase_complete("185", tmp_path)
    (phase / "185-02-SUMMARY.md").write_text("")
    assert phase_complete("185", tmp_path)
    archived = tmp_path / "milestones" / "v1-phases" / "067-y"
    archived.mkdir(parents=True)
    (archived / "67-01-PLAN.md").write_text("")
    (archived / "67-01-SUMMARY.md").write_text("")
    assert phase_complete("67", tmp_path)
    assert plan_summary_exists("67-01", tmp_path)
    assert not phase_complete("999", tmp_path)


def test_render_markdown_has_counts_and_listings():
    census = {
        "counts": {"scripts_total": 2, "temporary_entries": 1},
        "listings": {"scripts_total": ["a", "b"], "temporary_entries": ["x | TEMPORARY"]},
    }
    text = render_markdown(census)
    assert "| scripts_total | 2 |" in text
    assert "- x | TEMPORARY" in text


def test_census_script_is_read_only():
    source = _SCRIPT.read_text()
    write = re.compile(
        r"\b(?:INSERT\s+INTO|DELETE\s+FROM|UPDATE\s+\w+\s+SET|TRUNCATE\s|ALTER\s+TABLE|"
        r"CREATE\s+(?:TABLE|INDEX|VIEW)|DROP\s+(?:TABLE|VIEW|INDEX)|COPY\s+\w+\s+FROM)",
        re.IGNORECASE,
    )
    assert not write.search(source), write.search(source)
    assert "read_only = True" in source
    assert ".commit(" not in source
