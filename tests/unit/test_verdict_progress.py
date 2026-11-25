"""The 1d verdict report's progress lines (todo 649a): the cadence and the pace arithmetic."""

from services.bar_reconciliation_audit import verdict_progress, verdict_progress_every


def test_a_full_universe_logs_about_twenty_lines():
    assert verdict_progress_every(12857) == 642
    assert 12857 // verdict_progress_every(12857) == 20


def test_a_small_run_logs_every_name_and_never_divides_by_zero():
    assert verdict_progress_every(7) == 1
    assert verdict_progress_every(0) == 1


def test_eta_is_the_remaining_names_at_the_pace_so_far():
    assert verdict_progress(1000, 4000, 600.0) == {
        "done": 1000,
        "total": 4000,
        "elapsed_s": 600,
        "eta_s": 1800,
    }
    assert verdict_progress(0, 10, 0.0)["eta_s"] == 0
