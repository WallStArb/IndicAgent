"""Unit tests for roll chain derivation and system events topic builder.

Tests:
- derive_roll_chain: quarterly, monthly, grain cycle futures
- derive_roll_chain: roll_from/roll_to linkage correctness
- derive_roll_chain: chronological ordering
- derive_roll_chain: ValueError for unknown symbol
- topic_system_events: naming convention
"""

from __future__ import annotations

import pytest

from src.config.contracts import FUTURES_ROLL_CYCLES, MONTH_CODE_TO_NUM, derive_roll_chain
from src.core.stream_keys import topic_system_events

# ---------------------------------------------------------------------------
# derive_roll_chain — basic contract structure
# ---------------------------------------------------------------------------


class TestDeriveRollChainStructure:
    def test_es_returns_three_contracts(self):
        """ES quarterly — must return exactly 3 contracts."""
        chain = derive_roll_chain("ES")
        assert len(chain) == 3

    def test_es_contracts_have_required_keys(self):
        """Each contract dict must have all required fields."""
        chain = derive_roll_chain("ES")
        required = {"symbol", "base_symbol", "month_code", "expiry_month", "expiry_year", "roll_from", "roll_to"}
        for contract in chain:
            assert required.issubset(set(contract.keys())), f"Missing keys in {contract}"

    def test_es_base_symbol_correct(self):
        """All contracts in ES chain must have base_symbol='ES'."""
        chain = derive_roll_chain("ES")
        for contract in chain:
            assert contract["base_symbol"] == "ES"

    def test_es_symbol_format(self):
        """ES contracts must have symbols like ESM6 (base + month_code + 1-digit year)."""
        chain = derive_roll_chain("ES")
        for contract in chain:
            sym = contract["symbol"]
            # ES + 1 letter + 1 digit = 4 chars
            assert len(sym) == 4, f"Expected 4-char symbol for ES, got {sym!r}"
            assert sym.startswith("ES"), f"Symbol must start with 'ES', got {sym!r}"

    def test_rty_symbol_format(self):
        """RTY (multi-char base) contracts must have symbols like RTYM6."""
        chain = derive_roll_chain("RTY")
        for contract in chain:
            sym = contract["symbol"]
            # RTY (3) + 1 month code + 1 year digit = 5 chars, e.g. "RTYH6"
            assert len(sym) == 5, f"Expected 5-char symbol for RTY, got {sym!r}"
            assert sym.startswith("RTY"), f"Symbol must start with 'RTY', got {sym!r}"

    def test_es_month_codes_are_quarterly(self):
        """ES uses quarterly roll cycle H/M/U/Z — all month codes must be from this set."""
        quarterly = {"H", "M", "U", "Z"}
        chain = derive_roll_chain("ES")
        for contract in chain:
            assert contract["month_code"] in quarterly, (
                f"ES month code {contract['month_code']!r} not in quarterly cycle"
            )

    def test_es_contracts_sorted_chronologically(self):
        """Contracts must be sorted by (expiry_year, expiry_month) ascending."""
        chain = derive_roll_chain("ES")
        dates = [(c["expiry_year"], c["expiry_month"]) for c in chain]
        assert dates == sorted(dates), f"Chain not sorted: {dates}"


# ---------------------------------------------------------------------------
# derive_roll_chain — roll_from/roll_to linkage
# ---------------------------------------------------------------------------


class TestDeriveRollChainLinkage:
    def test_first_contract_roll_from_is_none(self):
        """First contract's roll_from must be None (no predecessor in the 3-chain)."""
        chain = derive_roll_chain("ES")
        assert chain[0]["roll_from"] is None

    def test_last_contract_roll_to_is_none(self):
        """Last contract's roll_to must be None (no successor in the 3-chain)."""
        chain = derive_roll_chain("ES")
        assert chain[-1]["roll_to"] is None

    def test_middle_contract_links_to_neighbors(self):
        """Middle contract must link to first and last."""
        chain = derive_roll_chain("ES")
        assert chain[1]["roll_from"] == chain[0]["symbol"]
        assert chain[1]["roll_to"] == chain[2]["symbol"]

    def test_first_contract_roll_to_is_second(self):
        """First contract's roll_to must be the second contract's symbol."""
        chain = derive_roll_chain("ES")
        assert chain[0]["roll_to"] == chain[1]["symbol"]

    def test_last_contract_roll_from_is_second(self):
        """Last contract's roll_from must be the second contract's symbol."""
        chain = derive_roll_chain("ES")
        assert chain[-1]["roll_from"] == chain[1]["symbol"]


# ---------------------------------------------------------------------------
# derive_roll_chain — monthly futures (CL, GC, SI, HG)
# ---------------------------------------------------------------------------


class TestDeriveRollChainMonthly:
    def test_cl_returns_three_contracts(self):
        """CL monthly — must return exactly 3 contracts."""
        chain = derive_roll_chain("CL")
        assert len(chain) == 3

    def test_cl_base_symbol_correct(self):
        chain = derive_roll_chain("CL")
        for contract in chain:
            assert contract["base_symbol"] == "CL"

    def test_cl_uses_monthly_cycle(self):
        """CL uses all 12 months — any month code is valid."""
        all_months = set(MONTH_CODE_TO_NUM.keys())
        chain = derive_roll_chain("CL")
        for contract in chain:
            assert contract["month_code"] in all_months

    def test_cl_sorted_chronologically(self):
        chain = derive_roll_chain("CL")
        dates = [(c["expiry_year"], c["expiry_month"]) for c in chain]
        assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# derive_roll_chain — grain cycle (ZC, ZS, ZW)
# ---------------------------------------------------------------------------


class TestDeriveRollChainGrain:
    def test_zc_returns_three_contracts(self):
        """ZC grain cycle — must return exactly 3 contracts."""
        chain = derive_roll_chain("ZC")
        assert len(chain) == 3

    def test_zc_uses_grain_cycle(self):
        """ZC uses H/K/N/U/Z grain cycle — month codes must be from this set."""
        grain = {"H", "K", "N", "U", "Z"}
        chain = derive_roll_chain("ZC")
        for contract in chain:
            assert contract["month_code"] in grain, (
                f"ZC month code {contract['month_code']!r} not in grain cycle {grain}"
            )

    def test_zs_uses_grain_cycle(self):
        """ZS (soybeans) also uses H/K/N/U/Z grain cycle."""
        grain = {"H", "K", "N", "U", "Z"}
        chain = derive_roll_chain("ZS")
        for contract in chain:
            assert contract["month_code"] in grain

    def test_zc_sorted_chronologically(self):
        chain = derive_roll_chain("ZC")
        dates = [(c["expiry_year"], c["expiry_month"]) for c in chain]
        assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# derive_roll_chain — error handling
# ---------------------------------------------------------------------------


class TestDeriveRollChainErrors:
    def test_unknown_symbol_raises_value_error(self):
        """Unknown base symbol must raise ValueError."""
        with pytest.raises(ValueError, match="UNKNOWN"):
            derive_roll_chain("UNKNOWN")

    def test_unknown_symbol_empty_string_raises_value_error(self):
        with pytest.raises(ValueError):
            derive_roll_chain("")

    def test_lowercase_symbol_raises_value_error(self):
        """Case-sensitive lookup — 'es' (lowercase) is not 'ES'."""
        with pytest.raises(ValueError):
            derive_roll_chain("es")


# ---------------------------------------------------------------------------
# derive_roll_chain — custom ref_year / ref_month
# ---------------------------------------------------------------------------


class TestDeriveRollChainCustomRef:
    def test_custom_ref_year_month_returns_correct_chain(self):
        """With ref_year=2026, ref_month=3, ES chain starts at H (March) or later."""
        chain = derive_roll_chain("ES", ref_year=2026, ref_month=3)
        assert len(chain) == 3
        # All contracts must be >= (2026, 3)
        for c in chain:
            assert (c["expiry_year"], c["expiry_month"]) >= (2026, 3)

    def test_custom_ref_produces_sorted_chain(self):
        chain = derive_roll_chain("NQ", ref_year=2026, ref_month=6)
        dates = [(c["expiry_year"], c["expiry_month"]) for c in chain]
        assert dates == sorted(dates)


# ---------------------------------------------------------------------------
# FUTURES_ROLL_CYCLES constant — smoke checks
# ---------------------------------------------------------------------------


class TestFuturesRollCycles:
    def test_es_in_roll_cycles(self):
        assert "ES" in FUTURES_ROLL_CYCLES

    def test_cl_in_roll_cycles(self):
        assert "CL" in FUTURES_ROLL_CYCLES

    def test_zc_in_roll_cycles(self):
        assert "ZC" in FUTURES_ROLL_CYCLES

    def test_es_has_four_codes(self):
        """ES quarterly = H, M, U, Z — exactly 4 codes."""
        assert set(FUTURES_ROLL_CYCLES["ES"]) == {"H", "M", "U", "Z"}

    def test_cl_has_twelve_codes(self):
        """CL monthly = all 12 month codes."""
        assert len(FUTURES_ROLL_CYCLES["CL"]) == 12

    def test_zc_has_five_codes(self):
        """ZC grain = H, K, N, U, Z — exactly 5 codes."""
        assert set(FUTURES_ROLL_CYCLES["ZC"]) == {"H", "K", "N", "U", "Z"}


# ---------------------------------------------------------------------------
# MONTH_CODE_TO_NUM constant
# ---------------------------------------------------------------------------


class TestMonthCodeToNum:
    def test_has_twelve_entries(self):
        assert len(MONTH_CODE_TO_NUM) == 12

    def test_h_is_march(self):
        assert MONTH_CODE_TO_NUM["H"] == 3

    def test_m_is_june(self):
        assert MONTH_CODE_TO_NUM["M"] == 6

    def test_u_is_september(self):
        assert MONTH_CODE_TO_NUM["U"] == 9

    def test_z_is_december(self):
        assert MONTH_CODE_TO_NUM["Z"] == 12

    def test_f_is_january(self):
        assert MONTH_CODE_TO_NUM["F"] == 1


# ---------------------------------------------------------------------------
# topic_system_events — stream key builder
# ---------------------------------------------------------------------------


class TestTopicSystemEvents:
    def test_development_prefix(self):
        """topic_system_events('development') → 'development.system.events'"""
        result = topic_system_events("development")
        assert result == "development.system.events"

    def test_empty_prefix(self):
        """topic_system_events('') → 'system.events'"""
        result = topic_system_events("")
        assert result == "system.events"

    def test_prod_prefix(self):
        """topic_system_events('prod') → 'prod.system.events'"""
        result = topic_system_events("prod")
        assert result == "prod.system.events"

    def test_uses_dots_not_colons(self):
        """Kafka topic names use dots, not colons."""
        result = topic_system_events("dev")
        assert ":" not in result
        assert "." in result
