"""The committed family 1 spec conforms to its pre-registration
(docs/plans/2026-09-25-family1-intraday-periodicity-prereg.md)."""

from pathlib import Path

from src.intelligence.research.families.common import declared_memory_rows
from src.intelligence.research.spec import FamilySpec, load_spec_from_file, resolve_member

ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "research/specs/family1_intraday_periodicity.yaml"


def _spec() -> FamilySpec:
    model = load_spec_from_file(SPEC, root=ROOT).model
    assert isinstance(model, FamilySpec)
    return model


def test_members_resolve_and_memory_matches():
    spec = _spec()
    for m in spec.members:
        assert callable(resolve_member(m.signal))
        assert m.declared_memory_rows == declared_memory_rows(m.slot_history_sessions, 26)
        assert m.params == {"window_sessions": m.slot_history_sessions}


def test_prereg_pinned_values():
    spec = _spec()
    # Section 2: 15m bars, compute_eligible universe, 26 slots per session, vintage-1 S1.
    assert spec.panel.universe == "compute_eligible"
    assert spec.panel.tf == "15m"
    assert spec.panel.bars_per_session == 26  # 13 half-hour slots
    assert spec.factor_spec == "vintage_1"
    # Section 2: end-exclusive at oos_start's date.
    assert spec.panel.end_exclusive == "2025-12-24"
    # Section 3: windows 1, 5, 20, 40; coverage floor 20.
    assert [m.slot_history_sessions for m in spec.members] == [1, 5, 20, 40]
    assert [m.declared_memory_rows for m in spec.members] == [7124, 7228, 7618, 8138]
    assert spec.construction.coverage_floor == 20
    # Sections 1 and 4: direction +1, horizon 2 bars, R1, R2 session scoring.
    assert spec.construction.direction == 1
    assert spec.construction.name == "rank_vol_neutral"
    assert spec.horizon == 2
    assert spec.scoring.session_scoring is True
    # Section 2: scored span and the three reported sub-periods.
    assert spec.scoring.trading_start == "2010-01-04"
    assert [tuple(p) for p in spec.scoring.sub_periods] == [
        ("2010-01-04", "2014-12-31"),
        ("2015-01-01", "2019-12-31"),
        ("2020-01-01", "2025-12-23"),
    ]
