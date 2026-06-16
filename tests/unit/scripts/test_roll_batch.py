"""Unit tests for roll_batch.detect_rolls() — pure function, no I/O."""

from __future__ import annotations

from datetime import date

from production.scripts.roll_batch import detect_rolls


class TestDetectRolls:
    def test_no_rolls_outside_window(self):
        # Jan 3 is before roll_end for all active contracts (CL roll_end ~Jan 9)
        result = detect_rolls(date(2026, 1, 3))
        assert result == []

    def test_quarterly_equity_roll(self):
        result = detect_rolls(date(2026, 9, 15))
        symbols = {d.base_symbol for d in result}
        assert "ES" in symbols
        assert "NQ" in symbols

    def test_monthly_energy_roll(self):
        result = detect_rolls(date(2026, 4, 18))
        symbols = {d.base_symbol for d in result}
        assert "CL" in symbols

    def test_roll_decision_fields(self):
        result = detect_rolls(date(2026, 9, 15))
        es = next(d for d in result if d.base_symbol == "ES")
        assert es.old_contract == "ESM6"
        assert es.new_contract == "ESU6"
        assert es.roll_end == date(2026, 9, 11)  # Friday before expiry week (3rd Fri Sep 18)

    def test_idempotent_same_day(self):
        r1 = detect_rolls(date(2026, 9, 15))
        r2 = detect_rolls(date(2026, 9, 15))
        assert len(r1) == len(r2)
        assert {(d.base_symbol, d.new_contract) for d in r1} == {
            (d.base_symbol, d.new_contract) for d in r2
        }

    def test_grain_cycle(self):
        result = detect_rolls(date(2026, 9, 15))
        symbols = {d.base_symbol for d in result}
        assert "ZC" in symbols
        assert "ZS" in symbols
        assert "ZW" in symbols

    def test_unknown_symbol_skipped(self):
        result = detect_rolls(date(2026, 9, 15))
        symbols = {d.base_symbol for d in result}
        assert "UNKNOWN" not in symbols
