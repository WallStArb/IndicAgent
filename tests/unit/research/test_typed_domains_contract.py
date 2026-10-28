"""Migration 530's shape (plan 187-11 Task 1): typed domains, retype keys, ordered deletes,
research CVR namespaces and the research stage view."""

import re
from pathlib import Path

MIGRATION = next(
    (Path(__file__).resolve().parents[3] / "production/migrations").glob(
        "*_typed_concept_domains_and_research_stage.sql"
    )
)
SQL = MIGRATION.read_text()
DOMAINS = ("feature", "family", "member", "combiner", "construction_rule", "book", "method")
STAGES = ("idea", "specified", "registered", "tested", "refused", "frozen", "confirmed")


def _code(text: str) -> str:
    return "\n".join(line.split("--")[0] for line in text.splitlines())


CODE = _code(SQL)


def test_migration_530_is_one_transaction():
    assert len(re.findall(r"^BEGIN;", CODE, re.M)) == 1
    assert len(re.findall(r"^COMMIT;", CODE, re.M)) == 1
    assert CODE.index("BEGIN;") < CODE.index("LOCK TABLE") < CODE.rindex("COMMIT;")


def test_both_domain_checks_list_exactly_the_typed_domains():
    for table in ("concept_registry", "concept_evaluation"):
        match = re.search(
            rf"ALTER TABLE {table} ADD CONSTRAINT {table}_domain_check\s+CHECK \(domain = "
            r"ANY \(ARRAY\[(.*?)\]\)\)",
            CODE,
            re.S,
        )
        assert match, table
        assert tuple(re.findall(r"'(\w+)'", match.group(1))) == DOMAINS


def test_retype_is_keyed_by_metadata_kind_and_by_the_five_named_rows():
    assert "WHEN 'member' THEN 'member'" in CODE
    assert "WHEN 'family' THEN 'family'" in CODE
    assert "WHEN 'book_version' THEN 'book'" in CODE
    named = CODE[CODE.index("SET domain = 'family'") :]
    for name in (
        "alpha_score_residual_single_security_15m",
        "bars_since_high_fast_xs_ls_h5",
        "phase148_alpha_score_directional",
        "range_pct_fast_xs_ls_h5",
        "range_pct_fast_xs_ls_h5_single_name_only",
    ):
        assert f"'{name}'" in named


def test_dependents_are_deleted_before_the_registry_rows_and_the_check_is_dropped_first():
    order = [
        CODE.index(f"DELETE FROM {t}")
        for t in (
            "concept_annotation",
            "concept_gate",
            "concept_transition_log",
            "concept_registry WHERE domain = 'ensemble_strategy'",
        )
    ]
    assert order == sorted(order)
    assert CODE.index("DROP CONSTRAINT concept_registry_domain_check") < CODE.index("UPDATE")
    assert CODE.index("UPDATE") < CODE.index("ADD CONSTRAINT concept_registry_domain_check")


def test_counts_are_checked_inside_the_transaction_before_any_delete():
    assert CODE.index("RAISE EXCEPTION") < CODE.index("DELETE FROM")
    assert "(5, 5, 1, 12, 0, 0, 0, 0, 0, 11, 4, 1, 1, 5)" in CODE


def test_research_namespaces_and_fk_indexes():
    for namespace in ("research_construction_rule", "research_combiner", "research_timeframe"):
        assert f"('{namespace}'," in CODE
    assert "ON research_run (recipe_hash)" in CODE
    assert "ON instrument_classification (scheme, code)" in CODE


def test_the_stage_view_names_every_stage_and_stores_nothing():
    view = CODE[CODE.index("CREATE VIEW concept_research_stage") :]
    for stage in STAGES:
        assert f"'{stage}'" in view
    assert "CREATE TABLE" not in CODE
