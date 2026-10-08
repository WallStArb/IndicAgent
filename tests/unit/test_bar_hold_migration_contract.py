"""Migration 461 contract: held names, void rows and the split recognition rule (plan 185-51).

Todo 515: the overlap judge recorded CTVA's spin-off rescale (39/7) as a split and ETHA's one
reverse split twice at wrong dates, and no sanctioned path could retract or correct a row. The
migration adds one definition of a held name (bar_hold, append-only, a release is a new row),
lets corporate_action carry a void row and operator corrections (still append-only; the current
view hides superseded and void rows), and seeds the three APR keys of the recognition rule.
Reads the .sql text only (no DB), SQL line comments stripped.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_FILE = "461_bar_hold_and_corporate_action_void.sql"
_RAW = read_source("production", "migrations", _FILE)
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)

_KEYS = {
    "infra.backfill.split_ratio_max_numerator": "50",
    "infra.backfill.split_ratio_max_denominator": "4",
    "infra.backfill.split_ratio_rel_tol": "0.002",
}


def test_bar_hold_migration_runs_in_one_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")


def test_corporate_action_admits_void_rows_that_must_supersede():
    assert "DROP CONSTRAINT IF EXISTS corporate_action_action_type_check" in _FLAT
    assert "CHECK (action_type IN ('split', 'reverse_split', 'void'))" in _FLAT
    assert "CHECK (action_type <> 'void' OR supersedes IS NOT NULL)" in _FLAT
    assert (
        "CHECK (inferred_by IN ('seam_audit', 'nightly_overlap', 'tradier_refetch', 'operator'))"
        in _FLAT
    )


def test_a_row_is_superseded_at_most_once():
    assert (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_corporate_action_supersedes "
        "ON corporate_action (supersedes) WHERE supersedes IS NOT NULL" in _FLAT
    )


def test_the_current_view_hides_void_and_superseded_rows():
    view = _FLAT.split("CREATE OR REPLACE VIEW corporate_action_current AS")[1].split(";")[0]
    assert "ca.action_type <> 'void'" in view
    assert "newer.supersedes = ca.action_id" in view


def test_bar_hold_is_append_only_with_one_reason_and_release_rows():
    table = _FLAT.split("CREATE TABLE IF NOT EXISTS bar_hold (")[1].split(");")[0]
    assert "symbol text NOT NULL REFERENCES instruments(symbol)" in table
    assert "timeframe text NOT NULL CHECK (timeframe = '1d')" in table
    assert "reason text NOT NULL CHECK (reason IN ('unclassified_rescale', 'release'))" in table
    assert "action_id uuid NULL REFERENCES corporate_action(action_id)" in table
    assert "releases uuid NULL REFERENCES bar_hold(hold_id)" in table
    assert "CHECK ((reason = 'release') = (releases IS NOT NULL))" in table
    assert "CHECK (jsonb_typeof(detail) = 'object')" in table
    assert (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_bar_hold_releases ON bar_hold (releases) "
        "WHERE releases IS NOT NULL" in _FLAT
    )
    assert (
        "CREATE TRIGGER trg_bar_hold_append_only BEFORE UPDATE OR DELETE ON bar_hold "
        "FOR EACH ROW EXECUTE FUNCTION corporate_action_append_only()" in _FLAT
    )
    assert "BEFORE TRUNCATE ON bar_hold" in _FLAT


def test_bar_hold_current_is_the_one_definition_of_held():
    view = _FLAT.split("CREATE OR REPLACE VIEW bar_hold_current AS")[1].split(";")[0]
    assert "h.reason <> 'release'" in view and "r.releases = h.hold_id" in view


def test_the_writer_role_inserts_and_reads_only():
    assert "GRANT INSERT, SELECT ON bar_hold TO bar_derivation_writer" in _FLAT
    assert "GRANT SELECT ON bar_hold_current TO bar_derivation_writer" in _FLAT
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON bar_hold FROM PUBLIC" in _FLAT


def test_the_recognition_keys_are_seeded_as_initial_estimates_and_not_ml_targets():
    for key, value in _KEYS.items():
        schema = re.search(
            rf"\('{re.escape(key)}', '(\w+)', '([\d.]+)', [\d.]+, [\d.]+, '([^']+)'\)", _FLAT
        )
        assert schema, key
        assert schema.group(2) == value
        assert schema.group(3).startswith("[initial_estimate]")
        assert "Not an ML learning target." in schema.group(3)
        assert f"('{key}', '{value}', 1)" in _FLAT
    assert "ON CONFLICT (config_key) DO NOTHING" in _FLAT
    assert "'migration_461'" in _FLAT
