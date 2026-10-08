"""Migration 460 contract: bar_source_policy.closed_at, stamped by the closing update (185-50).

A close changes valid_to only, so recorded_at never moved and the daily stage's revision waiver
and --changed-only probe could not see it (todo 508: FTV, IP, STE refused at ratio 0.999). The
append-only trigger now stamps closed_at on the one allowed UPDATE; an INSERT cannot carry it;
a closed row stays immutable. The three 185-49 closures are backfilled once from the apply log.
Reads the .sql text only (no DB), SQL line comments stripped.
"""

from __future__ import annotations

import re

from tests.unit._source_grep_helpers import read_source

_FILE = "460_bar_source_policy_closed_at.sql"
_RAW = read_source("production", "migrations", _FILE)
_CODE = re.sub(r"--[^\n]*", "", _RAW)
_FLAT = re.sub(r"\s+", " ", _CODE)
_TRIGGER = _FLAT.split("CREATE OR REPLACE FUNCTION bar_source_policy_append_only()")[1].split(
    "END $$;"
)[0]

_BACKFILLED = (
    "e8207a5d-f6cf-4fec-909f-716771394f7c",  # FTV
    "a4a06df8-44be-4886-9a80-8396f1c890fe",  # IP
    "de2b15f0-9238-4422-80a6-fff9ed0b3f9d",  # STE
)


def test_closed_at_migration_runs_in_one_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")


def test_adds_a_nullable_closed_at_idempotently():
    assert (
        "ALTER TABLE bar_source_policy ADD COLUMN IF NOT EXISTS closed_at timestamptz NULL" in _FLAT
    )


def test_closed_at_only_on_a_closed_row_and_not_before_its_record():
    assert "DROP CONSTRAINT IF EXISTS ck_bar_source_policy_closed_at" in _FLAT
    assert (
        "CHECK (closed_at IS NULL OR (valid_to IS NOT NULL AND closed_at >= recorded_at))" in _FLAT
    )


def test_the_trigger_stamps_the_close_and_refuses_a_stamped_insert():
    assert "NEW.closed_at IS NOT NULL" in _TRIGGER  # INSERT branch
    assert "NEW.closed_at := now();" in _TRIGGER  # UPDATE branch
    assert "OLD.valid_to IS NOT NULL" in _TRIGGER  # a closed row is immutable
    assert "NEW.valid_to IS NULL" in _TRIGGER


def test_every_other_column_still_compared_on_update():
    compared = _TRIGGER.split("IS DISTINCT FROM")[0]
    for column in (
        "policy_id",
        "timeframe",
        "symbol",
        "valid_from",
        "ingress_mode",
        "primary_source",
        "fallback_source",
        "reason",
        "evidence",
        "recorded_at",
    ):
        assert f"NEW.{column}" in compared, column
    assert "NEW.valid_to" not in compared and "NEW.closed_at" not in compared


def test_the_185_49_closures_are_backfilled_once_with_the_trigger_off_only_inside():
    disable = "ALTER TABLE bar_source_policy DISABLE TRIGGER trg_bar_source_policy_append_only"
    enable = "ALTER TABLE bar_source_policy ENABLE TRIGGER trg_bar_source_policy_append_only"
    assert _FLAT.count(disable) == 1 and _FLAT.count(enable) == 1
    window = _FLAT.split(disable)[1].split(enable)[0]
    assert window.strip().startswith("UPDATE bar_source_policy SET closed_at =")
    assert "closed_at IS NULL" in window and "valid_to IS NOT NULL" in window
    for policy_id in _BACKFILLED:
        assert policy_id in window
    assert "TIMESTAMPTZ '2026-10-08 20:15:26.826+00'" in window


def test_no_other_write():
    assert "DELETE" not in _FLAT.split("CREATE OR REPLACE FUNCTION")[0]
    assert "INSERT INTO" not in _FLAT
