"""The tests/unit live-database boundary (todo 494).

Three 185-18 leaks reached the live database from unit tests: a real grid derivation run, a
permanent D1 fixture append, and a self-cleaning live write. Two conftest guards in
tests/unit/conftest.py now hold the class closed, and this file holds their honesty:

- subprocess.run/Popen/call/check_* naming a live writer (bar_derivation,
  feature_vector_pipeline, scripts/ops) raise unless the test carries
  `pytest.mark.live_writer_subprocess`;
- a connection a unit test opens to the live database (the `indicagent` database, not
  `indicagent_test`) is forced read-only unless the test carries `pytest.mark.live_db`.

This file is the static half: every tests/unit file holding a live-DSN literal is allow-listed
here with its reason, read-only or marker-carrying, and a stale entry fails the same way the
market_data_ohlcv boundary test's does. CI-clean: filesystem only, no database.

Not caught by construction, named so a reviewer looks: a write through a connection this guard
does not patch (a driver added later) reaches the live database; and `from subprocess import run`
at module import time binds the real function past the conftest's monkeypatch, so a spawn that
imports that way is invisible to the spawn guard. A new driver in tests/unit is a conftest
change, not a test-local connect; an import-bound spawn is caught only by this file's review.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

_REPO_UNIT = Path(__file__).resolve().parent
_LIVE_DSN = re.compile(
    r"postgres(?:ql)?[\w+]*://[^\"'\n]*(?:localhost|127\.0\.0\.1)(?::\d+)?/indicagent(?!\w)"
)

# tests/unit files that hold a live-DSN literal, with the reason their connection is acceptable.
# A read-only reason means the conftest forces the session read-only and the test only reads
# (or takes advisory locks, which are not writes). A marker reason means the file carries
# `pytest.mark.live_db` on the tests that write, and the writes must be self-rolling-back
# (pg_temp inside a transaction the test aborts), never persistent rows.
_LIVE_DSN_FILES: Mapping[str, str] = {
    "test_spread_leg_pair_validity.py": (
        "read-only: fetches live policy/coverage rows to check a spread-leg predicate against "
        "real names; skips silently when the database is unreachable"
    ),
    "services/test_bar_derivation_stage_lock.py": (
        "read-only: proves the stage advisory lock is exclusive (advisory locks and a session "
        "SET are not writes; the read-only default does not block them)"
    ),
    "test_bar_source_policy_retirement.py": (
        "marker (pytest.mark.live_db): apply_plan runs against the real append-only trigger on "
        "a TEMP copy of bar_source_policy inside a transaction the fixture always aborts; "
        "nothing persists and no permanent relation is touched"
    ),
    "services/test_bar_derivation_policy_change_sql.py": (
        "marker (pytest.mark.live_db): the change-detection SQL runs against a TEMP shadow of "
        "bar_source_policy and fixture rows in ohlcv_request/ohlcv_raw/ohlcv_load inside a "
        "transaction the fixture always aborts; nothing persists"
    ),
    "test_canonical_bar_lineage_massive_migration_contract.py": (
        "marker (pytest.mark.live_db): migration 588's view SELECT runs against TEMP shadows of "
        "market_data_ohlcv, corporate_action_current, ohlcv_raw, ohlcv_load and "
        "bar_content_digest inside a transaction the fixture always aborts; nothing persists"
    ),
    "core/test_resource_lease.py": (
        "read-only: takes advisory-lease locks and reads pg_stat_activity (locks and session "
        "state are not writes)"
    ),
    "scripts/test_fetcher_lock.py": (
        "read-only: takes FetcherLock advisory locks and reads pg_stat_activity"
    ),
    "scripts/test_ohlcv_history_fetcher.py": (
        "read-only: probes reachability and reads live state; the fetcher itself runs on fake "
        "pools"
    ),
    "intelligence/test_swing_fib_trend_structure_primitives.py": (
        "read-only: fetches live OHLCV to fit structure primitives; skips when unreachable"
    ),
    "config/test_settings_active_contracts_dimension.py": (
        "mock-only: the literal is a Settings stub's database_url, never connected"
    ),
    "services/test_service_contract_resolution.py": (
        "mock-only: the literal is a settings stub, never connected"
    ),
    "services/test_cross_asset_service.py": (
        "mock-only: the literal is a service stub's database_url; the persist tests run on a "
        "mock pool and assert the SQL text, never connected"
    ),
    "services/test_macro_analyzer.py": (
        "mock-only: the literal is an agent stub's database_url, never connected"
    ),
}


def _unit_files() -> dict[str, str]:
    return {
        str(path.relative_to(_REPO_UNIT)): path.read_text()
        for path in sorted(_REPO_UNIT.rglob("*.py"))
        if path.name != "test_live_db_write_boundary.py"
    }


def test_every_file_with_a_live_dsn_literal_is_allow_listed():
    sources = _unit_files()
    with_literal = {name for name, text in sources.items() if _LIVE_DSN.search(text)}
    listed = set(_LIVE_DSN_FILES)
    assert with_literal <= listed, (
        f"tests/unit files connect to the live database without an entry here: "
        f"{sorted(with_literal - listed)}. Reads are allow-listed with a reason; writes need "
        "the live_db marker and a self-rolling-back design (todo 494)."
    )
    stale = listed - with_literal
    assert not stale, (
        f"allow-list entries whose file no longer holds a live-DSN literal: {sorted(stale)}. "
        "Remove the entry (or the literal was fixed: delete it here)."
    )


def test_marker_files_actually_carry_the_marker():
    for name, reason in _LIVE_DSN_FILES.items():
        if reason.startswith("marker"):
            text = (_REPO_UNIT / name).read_text()
            assert (
                "pytest.mark.live_db" in text
            ), f"{name} is allow-listed as a live_db marker file but does not use the marker"


def test_the_guards_are_in_the_unit_conftest():
    conftest = (_REPO_UNIT / "conftest.py").read_text()
    assert "_refuse_live_writer_spawns" in conftest
    assert "_live_dsn_connections_are_read_only" in conftest
    for token in ("bar_derivation", "feature_vector_pipeline", "scripts/ops", "scripts.ops"):
        assert token in conftest, f"guarded writer token {token!r} missing from the conftest"
