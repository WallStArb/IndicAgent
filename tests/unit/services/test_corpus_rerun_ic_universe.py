"""todo 609 blocker I1: the corpus rerun refuses while the IC universe differs."""

from __future__ import annotations

from services import corpus_rerun as cr


def _tree(tmp_path, *, ic_measure: str, snapshot: str):
    (tmp_path / "services").mkdir()
    (tmp_path / "src/intelligence/research").mkdir(parents=True)
    (tmp_path / "services/ic_measure.py").write_text(ic_measure)
    (tmp_path / "src/intelligence/research/snapshot.py").write_text(snapshot)
    return tmp_path


def test_blocks_while_either_reader_uses_the_eligibility_flags(tmp_path):
    root = _tree(tmp_path, ic_measure="universe_symbols(dsn, 'compute_eligible_1d')", snapshot="x")
    result = cr.check_ic_universe_aligned(root)
    assert not result.ok and "blocker I1" in result.detail
    assert "services/ic_measure.py" in result.detail


def test_passes_once_both_readers_read_membership(tmp_path):
    root = _tree(tmp_path, ic_measure="corpus_universe(conn)", snapshot="FROM universe_membership")
    assert cr.check_ic_universe_aligned(root).ok


def test_the_live_tree_is_blocked_until_the_readers_change():
    assert not cr.check_ic_universe_aligned().ok
