"""CI guard: every table the migrations create and every APR key they seed has a reader (185-44).

The table set is CREATE TABLE minus DROP TABLE (renames followed) and the APR key set is
config_schema inserts minus deletes, both parsed from production/migrations/ in order
(tests/unit/_migration_catalog.py). A reader is a reference in services/, src/ or scripts/
(*.py, *.sh, *.sql); migrations and tests do not count.

- APR key reader: the census rule (scripts/ops/ops_complexity_census.py `has_apr_reader`): the
  literal key, or a dotted prefix of it followed by a `{` placeholder, a `%` format or a closing
  quote (keys built in code by the registry's naming rule, e.g. `f"<prefix>.{tf}"`).
- table reader: any whole-word reference that is not the target of a write or DDL statement
  (INSERT INTO, UPDATE, DELETE FROM, COPY, TRUNCATE, ALTER/CREATE/DROP TABLE), so a table
  that is only ever written counts as reader-less.

A reader-less name fails unless it is
- in the frozen 2026-10-06 lists below (they may only shrink: an entry that gains a reader or
  leaves the migrations fails as stale, and a frozen name must come from a migration numbered
  at or below _FROZEN_MIGRATION_CEILING, so no new name can be frozen),
- in _KEEP_TABLES with a reason (raw market data kept by rule, written but read elsewhere), or
- in _PENDING_RETIREMENT with a reason carrying `retire: <plan id>`: the plan that orphans a
  name adds the entry in its own commit, and test_temporary_allow_list_expiry.py fails the
  entry once that plan's SUMMARY exists while the name is still created or seeded, or as stale
  once the name is gone.

Keys seeded by SQL string concatenation inside a migration (`'alpha.frame.' || ...`) are invisible
to the parse and therefore to this guard; the census (which reads the live config_state) counts
them. CI-clean: filesystem only, no database.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path

from scripts.ops.ops_complexity_census import has_apr_reader, load_reader_corpus
from tests.unit._migration_catalog import (
    MIGRATIONS_DIR,
    REPO_ROOT,
    catalog,
    migration_catalog,
    migration_files,
)

# The highest migration number on 2026-10-06, when the frozen lists were generated.
_FROZEN_MIGRATION_CEILING = 441

_RETIRE_CLAUSE = re.compile(r"retire:\s*\d{2,3}[A-Z]?(?:\.\d+)?-\d{2}\b")

_WRITE_TARGET = re.compile(
    r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|COPY|TRUNCATE(?:\s+TABLE)?|"
    r"ALTER\s+TABLE(?:\s+IF\s+EXISTS)?|CREATE\s+(?:UNLOGGED\s+)?TABLE(?:\s+IF\s+NOT\s+EXISTS)?|"
    r"DROP\s+TABLE(?:\s+IF\s+EXISTS)?)\s+(?:ONLY\s+)?(?:public\.)?$",
    re.IGNORECASE,
)

# Frozen 2026-10-06 (plan 185-44 baseline). MAY ONLY SHRINK: remove an entry when its table gains
# a reader or is dropped; never add one (a new reader-less table goes to _KEEP_TABLES with a
# reason or to _PENDING_RETIREMENT with a retire clause).
_FROZEN_UNREAD_TABLES: dict[str, str] = {
    "batch_job_checkpoints": "no reference outside its migration (155) on 2026-10-06",
    "concept_annotation": "no reference outside its migration (225) on 2026-10-06",
    "factor_series_correlation": "written by services/tag_calibrator.py, never read (2026-10-06)",
    "gate_evaluations": "no reference outside its migration (248) on 2026-10-06",
    "ic_cell_fingerprints": "no reference outside its migration (251) on 2026-10-06",
}

# Frozen 2026-10-06 (plan 185-44 baseline): APR keys seeded by the migrations with no reader in
# services/, src/ or scripts/. MAY ONLY SHRINK: remove a key when it gains a reader or a
# migration retires it; never add one.
_FROZEN_UNREAD_KEYS: frozenset[str] = frozenset(
    {
        "alpha.commodity_regime.momentum_window",
        "alpha.commodity_regime.primary_threshold",
        "alpha.commodity_regime.ts_proxy_threshold",
        "alpha.concept_registry.ensemble_strategy_min_new_observations",
        "alpha.concept_registry.ensemble_strategy_min_observations",
        "alpha.concept_registry.ensemble_strategy_min_promotion_consecutive",
        "alpha.construction.attribution_max_static_r2",
        "alpha.construction.cost_hurdle_bps_round_trip",
        "alpha.construction.decile_fraction",
        "alpha.construction.null_p_threshold",
        "alpha.construction.null_shuffles",
        "alpha.equity_regime.breadth_bull",
        "alpha.equity_regime.ma_window",
        "alpha.equity_regime.realized_vol_window",
        "alpha.equity_regime.vix_high_pct",
        "alpha.equity_regime.vix_low_pct",
        "alpha.equity_regime.vix_z_window",
        "alpha.frame.atr_period",
        "alpha.frame.geometry_source",
        "alpha.frame.min_stop_price_fraction",
        "alpha.frame.stop_atr_mult",
        "alpha.frame.structure_snap_proximity_atr",
        "alpha.frame.target_r_multiple",
        "alpha.fx_regime.carry_risk_on_threshold",
        "alpha.fx_regime.dollar_strong_threshold",
        "alpha.fx_regime.momentum_window",
        "alpha.ic.bootstrap_early_stop.check_interval",
        "alpha.ic.bootstrap_early_stop.enabled",
        "alpha.ic.bootstrap_early_stop.min_resamples",
        "alpha.ic.bootstrap_early_stop.stable_checks",
        "alpha.ic.bootstrap_early_stop.tol",
        "alpha.ic.bootstrap_numba_kernel",
        "alpha.ic.earnings_season_conditioned",
        "alpha.ic.max_cell_rows",
        "alpha.ic.min_obs_daily_features",
        "alpha.ic.min_obs_per_regime",
        "alpha.ic.min_observations",
        "alpha.ic.partial_fdr_alpha",
        "alpha.ic.refresh_min_new_fraction",
        "alpha.ic.sharpe_min_windows",
        "alpha.ic.walk_forward_folds",
        "alpha.publisher.is_shadow",
        "alpha.rates_regime.credit_tight_threshold",
        "alpha.rates_regime.credit_window",
        "alpha.rates_regime.curve_window",
        "alpha.rates_regime.inverted_threshold",
        "alpha.rates_regime.steep_threshold",
        "alpha.regime.breadth_bear",
        "alpha.regime.breadth_bull",
        "alpha.regime.groups.signal_tag_filter",
        "alpha.regime.ma_window",
        "alpha.regime.vix_high_pct",
        "alpha.regime.vix_low_pct",
        "alpha.vector.v1_quant.members",
        "feature.zone_engine.min_stop_distance_atr.equity",
        "feature.zone_engine.min_stop_distance_atr.futures",
        "feature.zone_engine.min_stop_distance_atr.fx",
        "infra.alpha_publisher.chunk_size",
        "infra.bar_auditor.price_sanity_batch_size",
        "infra.cross_sectional_spread_tracker.chunk_size",
        "infra.cross_sectional_spread_tracker.itersize",
        "infra.dividend_event.lookback_years",
        "infra.ensemble_trainer.workers",
        "infra.ic.max_unrouted_symbols",
        "infra.interaction_primitives_pilot.fetch_flush_rows",
        "threshold.signal_audit.hit_rate_anti_signal_ceiling",
        "threshold.signal_audit.hit_rate_validated_floor",
        "threshold.signal_audit.ic_anti_signal_ceiling",
        "threshold.signal_audit.ic_validated_floor",
        "threshold.signal_audit.partial_population_floor",
        "threshold.signal_audit.verifiable_population_floor",
    }
)

# Tables kept by rule although nothing in services/, src/ or scripts/ reads them (raw market
# data is permanent; a table written here and read by another surface). Each needs a reason.
# Empty on 2026-10-06: every raw market data table has a reader today.
_KEEP_TABLES: dict[str, str] = {}

# name -> reason carrying `retire: <plan id>`. The plan that orphans a table or APR key adds its
# entry in the same commit; the retiring plan (185-43 for the data layer work) removes the name
# and the entry together. Checked by test_temporary_allow_list_expiry.py.
_PENDING_RETIREMENT: dict[str, str] = {}


def table_has_reader(table: str, corpus: str) -> bool:
    """A whole-word reference to `table` that is not the target of a write or DDL statement."""
    start = corpus.find(table)
    while start != -1:
        end = start + len(table)
        before = corpus[start - 1] if start else " "
        after = corpus[end] if end < len(corpus) else " "
        whole_word = not (before.isalnum() or before == "_") and not (
            after.isalnum() or after == "_"
        )
        if whole_word and not _WRITE_TARGET.search(corpus[max(0, start - 60) : start]):
            return True
        start = corpus.find(table, start + 1)
    return False


def reader_violations(
    tables: Iterable[str],
    keys: Iterable[str],
    corpus: str,
    *,
    frozen_tables: Iterable[str],
    frozen_keys: Iterable[str],
    keep_tables: Mapping[str, str],
    pending: Mapping[str, str],
) -> list[str]:
    """Reader-less names that no list excuses, as messages."""
    excused = set(frozen_tables) | set(frozen_keys) | set(keep_tables) | set(pending)
    problems = [
        f"table {table} has no reader in services/, src/ or scripts/"
        for table in sorted(tables)
        if table not in excused and not table_has_reader(table, corpus)
    ]
    problems += [
        f"APR key {key} has no reader in services/, src/ or scripts/"
        for key in sorted(keys)
        if key not in excused and not has_apr_reader(key, corpus)
    ]
    return problems


def list_violations(
    tables: Iterable[str],
    keys: Iterable[str],
    frozen_era_names: Iterable[str],
    corpus: str,
    *,
    frozen_tables: Iterable[str],
    frozen_keys: Iterable[str],
    keep_tables: Mapping[str, str],
    pending: Mapping[str, str],
) -> list[str]:
    """Stale or malformed list entries, as messages."""
    tables, keys, frozen_era = set(tables), set(keys), set(frozen_era_names)
    problems: list[str] = []
    for table in sorted(frozen_tables):
        if table not in tables:
            problems.append(f"frozen table {table} is no longer created: remove its entry")
        elif table_has_reader(table, corpus):
            problems.append(f"frozen table {table} now has a reader: remove its entry")
    for key in sorted(frozen_keys):
        if key not in keys:
            problems.append(f"frozen APR key {key} is no longer seeded: remove its entry")
        elif has_apr_reader(key, corpus):
            problems.append(f"frozen APR key {key} now has a reader: remove its entry")
    for name in sorted(set(frozen_tables) | set(frozen_keys)):
        if name not in frozen_era:
            problems.append(
                f"frozen entry {name} does not come from a migration at or below "
                f"{_FROZEN_MIGRATION_CEILING}: the frozen lists may only shrink"
            )
    for table, reason in sorted(keep_tables.items()):
        if not reason.strip():
            problems.append(f"keep entry {table} has no reason")
        if table not in tables:
            problems.append(f"keep entry {table} is no longer created: remove it")
        elif table_has_reader(table, corpus):
            problems.append(f"keep entry {table} now has a reader: remove it")
    for name, reason in sorted(pending.items()):
        if not _RETIRE_CLAUSE.search(reason):
            problems.append(f"pending-retirement entry {name} has no `retire: <plan id>` clause")
    return problems


def _frozen_era_names() -> set[str]:
    files = [
        path
        for path in migration_files(MIGRATIONS_DIR)
        if (match := re.match(r"(\d+)", path.name))
        and int(match.group(1)) <= _FROZEN_MIGRATION_CEILING
    ]
    tables, keys = catalog(files)
    return tables | keys


def test_every_migration_table_and_apr_key_has_a_reader():
    tables, keys = migration_catalog()
    problems = reader_violations(
        tables,
        keys,
        load_reader_corpus(REPO_ROOT),
        frozen_tables=_FROZEN_UNREAD_TABLES,
        frozen_keys=_FROZEN_UNREAD_KEYS,
        keep_tables=_KEEP_TABLES,
        pending=_PENDING_RETIREMENT,
    )
    assert not problems, (
        "Reader-less names (a table or APR key nothing reads is debt). Delete it in a migration, "
        "or add a _PENDING_RETIREMENT entry with `retire: <plan id>` in this commit, or a "
        "_KEEP_TABLES entry with a reason:\n" + "\n".join(problems)
    )


def test_reader_lists_have_no_stale_or_malformed_entries():
    tables, keys = migration_catalog()
    problems = list_violations(
        tables,
        keys,
        _frozen_era_names(),
        load_reader_corpus(REPO_ROOT),
        frozen_tables=_FROZEN_UNREAD_TABLES,
        frozen_keys=_FROZEN_UNREAD_KEYS,
        keep_tables=_KEEP_TABLES,
        pending=_PENDING_RETIREMENT,
    )
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------------------------------------
# the guard's own behavior, on fakes


def _fake_tree(tmp_path: Path, migrations: dict[str, str], sources: dict[str, str]) -> Path:
    (tmp_path / "migrations").mkdir()
    for name, sql in migrations.items():
        (tmp_path / "migrations" / name).write_text(sql)
    for relative, text in sources.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


_FAKE_MIGRATIONS = {
    "001_a.sql": (
        "CREATE TABLE IF NOT EXISTS read_tbl (x int);\n"
        "CREATE TABLE unread_tbl (x int);\n"
        "CREATE TABLE written_tbl (x int);\n"
        "CREATE TABLE dropped_tbl (x int);\n"
        "-- CREATE TABLE commented_tbl (x int);\n"
        "INSERT INTO config_schema (config_key, value_type, default_value, description) VALUES\n"
        "  ('infra.fake.read_key', 'int', '1', 'read; it''s fine'),\n"
        "  ('infra.fake.test_only_key', 'int', '1', 'x'),\n"
        "  ('infra.fake.deleted_key', 'int', '1', 'x');\n"
    ),
    "002_b.sql": (
        "DROP TABLE IF EXISTS dropped_tbl CASCADE;\n"
        "DELETE FROM config_schema WHERE config_key = 'infra.fake.deleted_key';\n"
    ),
}

_FAKE_SOURCES = {
    "services/svc.py": (
        'SQL = "SELECT x FROM read_tbl"\n'
        'W = "INSERT INTO written_tbl (x) VALUES (1)"\n'
        'cfg.get_sync("infra.fake.read_key")\n'
    ),
    "tests/unit/test_svc.py": 'cfg.get_sync("infra.fake.test_only_key")\nSELECT FROM unread_tbl\n',
}


def _fake_violations(tmp_path: Path, **lists: object) -> list[str]:
    root = _fake_tree(tmp_path, _FAKE_MIGRATIONS, _FAKE_SOURCES)
    tables, keys = catalog(migration_files(root / "migrations"))
    kwargs = {"frozen_tables": (), "frozen_keys": (), "keep_tables": {}, "pending": {}}
    kwargs.update(lists)
    return reader_violations(tables, keys, load_reader_corpus(root), **kwargs)  # type: ignore[arg-type]


def test_fake_reader_less_table_and_test_only_key_fail(tmp_path):
    problems = _fake_violations(tmp_path)
    assert problems == [
        "table unread_tbl has no reader in services/, src/ or scripts/",
        "table written_tbl has no reader in services/, src/ or scripts/",
        "APR key infra.fake.test_only_key has no reader in services/, src/ or scripts/",
    ]


def test_fake_dropped_table_and_deleted_key_are_ignored(tmp_path):
    root = _fake_tree(tmp_path, _FAKE_MIGRATIONS, {})
    tables, keys = catalog(migration_files(root / "migrations"))
    assert "dropped_tbl" not in tables
    assert "commented_tbl" not in tables
    assert "infra.fake.deleted_key" not in keys
    assert {"read_tbl", "unread_tbl", "written_tbl"} <= tables


def test_fake_frozen_kept_and_pending_names_pass(tmp_path):
    problems = _fake_violations(
        tmp_path,
        frozen_tables={"unread_tbl"},
        keep_tables={"written_tbl": "raw data, read by an audit outside the repo"},
        pending={"infra.fake.test_only_key": "orphaned by 185-98 (retire: 185-99)"},
    )
    assert problems == []


def test_fake_stale_and_malformed_list_entries_fail(tmp_path):
    root = _fake_tree(tmp_path, _FAKE_MIGRATIONS, _FAKE_SOURCES)
    tables, keys = catalog(migration_files(root / "migrations"))
    problems = list_violations(
        tables,
        keys,
        {"read_tbl", "unread_tbl", "dropped_tbl", "infra.fake.read_key"},
        load_reader_corpus(root),
        frozen_tables={"read_tbl", "dropped_tbl", "unread_tbl"},
        frozen_keys={"infra.fake.read_key", "infra.fake.test_only_key"},
        keep_tables={"read_tbl": " "},
        pending={"infra.fake.test_only_key": "no clause here"},
    )
    assert problems == [
        "frozen table dropped_tbl is no longer created: remove its entry",
        "frozen table read_tbl now has a reader: remove its entry",
        "frozen APR key infra.fake.read_key now has a reader: remove its entry",
        "frozen entry infra.fake.test_only_key does not come from a migration at or below "
        f"{_FROZEN_MIGRATION_CEILING}: the frozen lists may only shrink",
        "keep entry read_tbl has no reason",
        "keep entry read_tbl now has a reader: remove it",
        "pending-retirement entry infra.fake.test_only_key has no `retire: <plan id>` clause",
    ]
