"""Unit tests for known-corrupt-OHLCV-print cleanup (todo 151) script functions.

Pure-function tests only -- no DB, no live asyncpg connection. Tests the report
rendering and the pair-scan concurrency. The classification logic
(classify_candidate_bar, apply_cross_symbol_downgrade) is tested separately in
tests/unit/intelligence/test_price_sanity.py.

Plan 185-18 task 1b: the script's apply mode is refused outright (the corrupt-bar
scrub belongs to services/bar_scrub.py, driven from bar_derivation), so the
correction SQL and its audit insert are gone; what remains pinned here is the
fence and the dry-run surface.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from scripts.ops.corpus.ops_known_corrupt_print_cleanup import (
    CandidateRow,
    _scan_and_classify_all_pairs,
    render_dry_run_report,
    render_followup_commands,
)
from src.intelligence.statistics.price_sanity import (
    CandidateVerdict,
)


def _make_row(symbol: str, tf: str, verdict: CandidateVerdict) -> CandidateRow:
    return CandidateRow(
        symbol=symbol,
        tf=tf,
        bar_ts="2007-06-20T19:00:00+00:00",
        timestamp="2007-06-20T19:00:00Z",
        open=1000.0,
        high=1000.0,
        low=28.97,
        close=28.97,
        volume=200.0,
        prev_close=25.07,
        next_open=24.08,
        verdict=verdict,
    )


class TestRenderDryRunReport:
    def test_report_includes_counts(self) -> None:
        confirmed = _make_row(
            "UUP",
            "5m",
            CandidateVerdict(
                "CONFIRMED_CORRUPT", ("open", "high"), 40.7, 1.04, "isolated_spike_neighbors_agree"
            ),
        )
        ambiguous = _make_row(
            "XRT",
            "15m",
            CandidateVerdict(
                "AMBIGUOUS", ("open",), 15.0, 5.0, "implausible_but_neighbors_disagree"
            ),
        )
        report = render_dry_run_report([confirmed, ambiguous])
        assert "CONFIRMED_CORRUPT: 1" in report
        assert "AMBIGUOUS: 1" in report

    def test_report_includes_confirmed_row_details(self) -> None:
        confirmed = _make_row(
            "UUP",
            "5m",
            CandidateVerdict(
                "CONFIRMED_CORRUPT", ("open", "high"), 40.7, 1.04, "isolated_spike_neighbors_agree"
            ),
        )
        report = render_dry_run_report([confirmed])
        assert "UUP" in report
        assert "5m" in report
        assert "isolated_spike_neighbors_agree" in report

    def test_empty_report_zero_candidates(self) -> None:
        report = render_dry_run_report([])
        assert "CONFIRMED_CORRUPT: 0" in report
        assert "AMBIGUOUS: 0" in report


class TestRenderFollowupCommands:
    def test_no_confirmed_returns_no_followup_message(self) -> None:
        text = render_followup_commands([])
        assert "No CONFIRMED_CORRUPT rows" in text

    def test_confirmed_rows_point_at_the_scrub_pipeline_not_this_script(self) -> None:
        """Plan 185-18 task 1b: this script never mutates rows anymore; the
        follow-up points at services/bar_scrub.py (driven from bar_derivation)
        and must not suggest its own retired apply mode."""
        confirmed = _make_row(
            "UUP",
            "5m",
            CandidateVerdict(
                "CONFIRMED_CORRUPT", ("open", "high"), 40.7, 1.04, "isolated_spike_neighbors_agree"
            ),
        )
        text = render_followup_commands([confirmed])
        assert "bar_scrub" in text
        assert "--apply" not in text
        assert "UUP" in text
        assert "ic_measure.py" in text
        assert "backfill_feature_factory.py" in text

    def test_delete_gotcha_note_present(self) -> None:
        # ON CONFLICT DO NOTHING on feature_vectors means re-running the writer alone
        # will NOT overwrite pre-existing rows for the corrected neighborhood -- the
        # follow-up text must warn about this. (The old forward_returns purge line
        # went with the table, deleted in phase 186 plan 23.)
        confirmed = _make_row(
            "UUP",
            "5m",
            CandidateVerdict(
                "CONFIRMED_CORRUPT", ("open", "high"), 40.7, 1.04, "isolated_spike_neighbors_agree"
            ),
        )
        text = render_followup_commands([confirmed])
        assert "ON CONFLICT DO NOTHING" in text
        assert "DELETE FROM feature_vectors" in text


class TestApplyFence:
    """Plan 185-18 task 1b: the script's apply mode raises the supersession
    fence instead of mutating rows -- services/bar_scrub.py owns the scrub."""

    def test_apply_is_refused_with_the_supersession_fence(self) -> None:
        from scripts.ops.corpus.ops_known_corrupt_print_cleanup import _refuse_apply

        with pytest.raises(
            RuntimeError, match=r"superseded by services/bar_scrub\.py \(phase 185\)"
        ):
            _refuse_apply()

    def test_the_correction_sql_is_gone(self) -> None:
        from pathlib import Path

        source = Path("scripts/ops/corpus/ops_known_corrupt_print_cleanup.py").read_text()
        assert "_CORRECTION_UPDATE_SQL" not in source
        assert "_AUDIT_INSERT_SQL" not in source
        assert "_apply_correction" not in source


class TestScanAndClassifyAllPairsConcurrency:
    """The (symbol, tf) pair scan must run concurrently (asyncio.gather), not one
    pair after another -- each pair's neighbor-scan query is independent."""

    @pytest.mark.asyncio
    async def test_scans_all_pairs_concurrently(self) -> None:
        concurrent = 0
        max_concurrent = 0

        async def fake_scan(pool, symbol, tf, magnitude_threshold, neighbor_agreement_threshold):
            nonlocal concurrent, max_concurrent
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
            await asyncio.sleep(0.01)
            concurrent -= 1
            return [f"{symbol}:{tf}"]

        with patch(
            "scripts.ops.corpus.ops_known_corrupt_print_cleanup._scan_and_classify",
            new=fake_scan,
        ):
            all_rows = await _scan_and_classify_all_pairs(
                pool=None,
                pairs=[("UUP", "5m"), ("XRT", "15m"), ("DIA", "1h")],
                magnitude_threshold=10.0,
                neighbor_agreement_threshold=2.0,
            )

        assert max_concurrent > 1, "pairs scanned sequentially, not concurrently"
        assert all_rows == ["UUP:5m", "XRT:15m", "DIA:1h"]
