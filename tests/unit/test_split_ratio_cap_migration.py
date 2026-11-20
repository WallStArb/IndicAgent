import re
from pathlib import Path

from src.intelligence.bars.corporate_actions import SplitRatioRule, recognised_split_ratio

_SQL = (
    Path(__file__).resolve().parents[2]
    / "production/migrations/604_split_ratio_max_numerator_1000.sql"
).read_text()
_CODE = "\n".join(line for line in _SQL.splitlines() if not line.lstrip().startswith("--"))
_FLAT = re.sub(r"\s+", " ", _CODE)
_SEED_MAX = 1000  # config_schema.max_value of the key (migration 461)


def test_the_cap_migration_is_one_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.rstrip().endswith("COMMIT;")


def test_the_cap_moves_to_1000_and_is_recorded_in_config_history():
    assert "SET config_value = '1000', version = version + 1" in _FLAT
    assert "WHERE config_key = 'infra.backfill.split_ratio_max_numerator'" in _FLAT
    assert "INSERT INTO config_history" in _FLAT and "'migration_604'" in _FLAT
    assert "[measured]" in _SQL  # provenance tag of the calibration note


def test_the_new_value_is_inside_the_schema_bounds_and_only_the_numerator_moves():
    assert int(re.search(r"config_value = '(\d+)'", _FLAT).group(1)) <= _SEED_MAX
    keys = set(re.findall(r"config_key = '([^']+)'", _CODE))
    assert keys == {"infra.backfill.split_ratio_max_numerator"}  # denominator and tolerance stay


def test_the_schema_description_is_rewritten_with_the_measured_provenance_and_the_limit():
    assert "description = '[measured 2026-11-20, was initial_estimate 50]" in _FLAT
    assert "UPDATE config_schema" in _FLAT and "default_value <> '1000'" in _FLAT
    assert "no longer discriminates" in _SQL and "Equal to the snap bound" not in _SQL


def test_the_rule_at_the_new_cap_reads_the_measured_reverse_splits_and_still_filters_below_250():
    rule = SplitRatioRule(1000, 4, 0.002)
    assert recognised_split_ratio(1 / 100, rule) == 1 / 100
    assert recognised_split_ratio(1 / 1000, rule) == 1 / 1000
    assert recognised_split_ratio(1 / 1001, rule) is None  # above the cap
    assert recognised_split_ratio(1.05, rule) is None  # a 5 % stock dividend is no split row
    # The documented limit: from p = 250 on rounding alone stays inside the tolerance.
    assert recognised_split_ratio(1 / 612.7, rule) is not None
