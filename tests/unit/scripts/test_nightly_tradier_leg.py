"""The nightly's Tradier 1d leg and the Tradier-owned skip (phase 185 plan 26, D-21).

The nightly runs infrastructure_run_tradier_daily.py --nightly before selecting the IBKR legs;
its refusals are audit findings, never a nightly failure. The IBKR legs then fetch no 1d for a
Tradier-owned name. Everything here runs against fakes: no DB, no subprocess, no network.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scripts.infrastructure.backfill import infrastructure_nightly_backfill as nightly
from scripts.infrastructure.backfill.infrastructure_nightly_backfill import (
    _run_tradier_leg as real_run_tradier_leg,
)
from scripts.infrastructure.backfill.infrastructure_nightly_backfill import (
    split_tradier_owned,
)
from scripts.infrastructure.backfill.infrastructure_run_tradier_daily import (
    EXIT_REFUSED,
    TRADIER_OWNED_SQL,
)
from services.bar_derivation import _SELECT_DAILY_CHANGED_SINCE_SQL
from services.bar_reconciliation_audit import check_tradier_refused

_COMPUTE, _COMPUTE_1D = nightly._LEGS


def _timeframes(args: tuple[str, ...]) -> str:
    return args[args.index("--timeframes") + 1]


# -- the skip ----------------------------------------------------------------


def test_owned_compute_names_fetch_the_stack_without_1d():
    dispatches = split_tradier_owned([(_COMPUTE, ["A", "B", "C"])], {"B"})
    assert dispatches[0] == ("compute", ["A", "C"], _COMPUTE.delegate_args)
    name, symbols, args = dispatches[1]
    assert (name, symbols) == ("compute_tradier_owned", ["B"])
    stack = _timeframes(args).split(",")
    assert "1d" not in stack
    assert stack == [tf for tf in nightly._DEFAULT_TIMEFRAMES.split(",") if tf != "1d"]


def test_owned_1d_only_names_drop_out():
    dispatches = split_tradier_owned([(_COMPUTE_1D, ["X", "Y", "Z"])], {"X", "Z"})
    assert dispatches == [("compute_1d_only", ["Y"], _COMPUTE_1D.delegate_args)]


def test_no_owned_names_leaves_the_legs_unchanged():
    batches = [(_COMPUTE, ["A", "B"]), (_COMPUTE_1D, ["X"])]
    assert split_tradier_owned(batches, set()) == [
        ("compute", ["A", "B"], _COMPUTE.delegate_args),
        ("compute_1d_only", ["X"], _COMPUTE_1D.delegate_args),
    ]


def test_staleness_order_is_kept_on_both_sides():
    dispatches = split_tradier_owned([(_COMPUTE, ["D", "A", "C", "B"])], {"C", "D"})
    assert dispatches[0][1] == ["A", "B"]
    assert dispatches[1][1] == ["D", "C"]


def test_the_skip_and_d2_use_the_same_ownership_predicate():
    # One predicate: a name some load was accepted for. A later refused load must not hand the
    # name back to IBKR (D2 would then overwrite its bars) or the skip and D2 would disagree.
    d2 = " ".join(_SELECT_DAILY_CHANGED_SINCE_SQL.split())
    assert TRADIER_OWNED_SQL.format(col="$1") in d2
    assert "max(loaded_at)" not in d2


# -- the leg's exit code -----------------------------------------------------


def _subprocess_returning(returncode: int) -> MagicMock:
    return MagicMock(return_value=SimpleNamespace(returncode=returncode))


def test_tradier_leg_runs_the_loader_in_nightly_mode():
    run = _subprocess_returning(0)
    with patch.object(nightly.subprocess, "run", run):
        assert real_run_tradier_leg() == 0
    command = run.call_args.args[0]
    assert command[1].endswith("infrastructure_run_tradier_daily.py")
    assert command[2:] == ["--nightly"]


def test_tradier_refusals_never_fail_the_nightly():
    with patch.object(nightly.subprocess, "run", _subprocess_returning(EXIT_REFUSED)):
        assert real_run_tradier_leg() == 0


def test_tradier_runtime_error_is_an_error():
    with patch.object(nightly.subprocess, "run", _subprocess_returning(1)):
        assert real_run_tradier_leg() == 1


# -- the nightly's order and switch ------------------------------------------


def _drive(tmp_path, nightly_audit, *, enabled: bool, owned: set[str], tradier_rc: int = 0):
    """Run nightly.main() with both legs non-empty and every stage faked."""
    events: list[str] = []
    delegate_calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    by_leg = {"compute": ["AAA", "OWN1"], "compute_1d_only": ["BBB", "OWN2"]}
    nightly_audit.tradier_leg.side_effect = lambda: events.append("tradier") or tradier_rc

    def _select(_conn, leg):
        events.append(f"select:{leg.name}")
        return by_leg[leg.name]

    def _delegate(symbols, extra_args):
        delegate_calls.append((tuple(symbols), tuple(extra_args)))
        return 0

    job_counter = MagicMock()
    statuses: list[str] = []
    job_counter.add.side_effect = lambda _n, labels: statuses.append(labels["status"])
    owned_query = MagicMock(return_value=owned)
    with (
        patch.object(nightly, "setup_service_logging"),
        patch.object(nightly, "Settings"),
        patch.object(nightly, "connect_db"),
        patch.object(nightly, "_load_tradier_enabled", return_value=enabled),
        patch.object(nightly, "_select_stalest", side_effect=_select),
        patch.object(nightly, "_select_tradier_owned", owned_query),
        patch.object(nightly, "_load_lease_wait_minutes", return_value=60),
        patch.object(nightly, "_load_overlap_sessions", return_value=20),
        patch.object(nightly, "_run_delegate", side_effect=_delegate),
        patch.object(nightly, "_prepare_grid_stage", return_value=tmp_path / "exclude.txt"),
        patch.object(nightly, "_run_split_detect", return_value=0),
        patch.object(nightly, "_run_daily_stage", return_value=0),
        patch.object(nightly, "_run_grid_stage", return_value=0),
        patch.object(nightly, "flush_and_shutdown_metrics"),
        patch.object(nightly, "JOB_COMPLETED_TOTAL", job_counter),
    ):
        rc = nightly.main()
    return SimpleNamespace(
        rc=rc,
        events=events,
        delegate_calls=delegate_calls,
        statuses=statuses,
        owned_queried=owned_query.called,
    )


def test_tradier_leg_runs_before_the_ibkr_selection_and_owned_names_skip_1d(
    tmp_path, nightly_audit
):
    result = _drive(tmp_path, nightly_audit, enabled=True, owned={"OWN1", "OWN2"})
    assert result.rc == 0 and result.statuses == ["success"]
    assert result.events[0] == "tradier"
    assert result.events[1:] == ["select:compute", "select:compute_1d_only"]
    calls = {symbols: args for symbols, args in result.delegate_calls}
    assert set(calls) == {("AAA",), ("OWN1",), ("BBB",)}  # OWN2 was 1d-only: no IBKR fetch
    assert "1d" not in _timeframes(calls[("OWN1",)]).split(",")
    nightly_audit.assert_called_once()  # the D7 audit still runs last


def test_tradier_runtime_error_fails_the_nightly_but_ibkr_legs_still_run(tmp_path, nightly_audit):
    result = _drive(tmp_path, nightly_audit, enabled=True, owned={"OWN1"}, tradier_rc=1)
    assert result.rc == 1 and result.statuses == ["failed"]
    assert result.delegate_calls  # IBKR legs still ran
    nightly_audit.assert_called_once()


def test_switch_off_restores_the_ibkr_only_nightly(tmp_path, nightly_audit):
    result = _drive(tmp_path, nightly_audit, enabled=False, owned={"OWN1", "OWN2"})
    assert result.rc == 0
    assert "tradier" not in result.events
    assert not result.owned_queried
    assert {symbols for symbols, _ in result.delegate_calls} == {
        ("AAA", "OWN1"),
        ("BBB", "OWN2"),
    }


# -- the audit finding -------------------------------------------------------


def test_refused_latest_load_of_an_owned_name_is_an_audit_finding():
    result = check_tradier_refused(
        {
            "AAA": ("loaded", None),
            "BBB": ("gated", "40 of 300 existing bars change"),
            "CCC": ("failed", "timeout"),
        }
    )
    assert result.n_findings == 2
    assert result.samples[0].startswith("BBB|gated|")
    assert result.samples[1].startswith("CCC|failed|")


def test_all_loaded_is_clean():
    assert check_tradier_refused({"AAA": ("loaded", None)}).n_findings == 0
