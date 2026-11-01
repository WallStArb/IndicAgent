"""Unit tests for the daily borrow availability capture (todo 438)."""

from services.borrow_availability_capture import summarize
from src.providers.ibkr import BorrowSnapshot


def test_summarize_counts_asked_answered_unknown() -> None:
    snapshots = [
        BorrowSnapshot(symbol="A", shortable_shares=5.0),
        BorrowSnapshot(symbol="B", shortable_shares=0.0),
        BorrowSnapshot(symbol="C", shortable_shares=None),
    ]
    counts = summarize(snapshots)
    assert counts == {"asked": 3, "answered": 2, "unknown": 1}


def test_summarize_all_unknown_is_all_asked() -> None:
    # Asked-but-unknown rows still exist (one per ask), so asked counts them and
    # the run reports partial; unasked symbols are absent, never zero-filled.
    snapshots = [BorrowSnapshot(symbol="X", shortable_shares=None)]
    assert summarize(snapshots) == {"asked": 1, "answered": 0, "unknown": 1}


def test_borrow_snapshot_unknown_is_none_not_zero() -> None:
    # A silent answer is NULL shares, not 0.0: zero means "asked and IBKR says
    # none are lendable", NULL means "asked and no answer". The generated
    # `shortable` column maps shares > 0 to the flag, so one rule, one place.
    assert BorrowSnapshot(symbol="X", shortable_shares=None).shortable_shares is None
    assert BorrowSnapshot(symbol="Y", shortable_shares=0.0).shortable_shares == 0.0
