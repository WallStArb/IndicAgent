"""Unit tests for src/core/rng.py's shared hash-key-to-int primitive.

Extracted 2026-07-29 (/simplify pass, todo 203) from services/ic_engine.py's
_derive_worker_rng_seed after src/intelligence/feature_factory.py's canary seeding
independently re-derived the same MD5-hash-to-int idiom. Both callers keep their own
combination formula; this module only owns the shared hash step.
"""

from __future__ import annotations

from src.core.rng import hash_key_to_int


class TestHashKeyToInt:
    def test_deterministic_for_same_key(self) -> None:
        assert hash_key_to_int("SPY") == hash_key_to_int("SPY")

    def test_different_keys_give_different_hashes(self) -> None:
        assert hash_key_to_int("SPY") != hash_key_to_int("QQQ")

    def test_stable_across_process_no_python_hash_randomization(self) -> None:
        """Must use hashlib, not Python's built-in hash() -- PYTHONHASHSEED would
        make the latter non-reproducible across interpreter invocations."""
        results = [hash_key_to_int("SPY") for _ in range(5)]
        assert len(set(results)) == 1

    def test_matches_known_md5_derivation(self) -> None:
        """Pins the exact algorithm (MD5 hex digest, first 8 chars, base-16 int) --
        existing production callers (ic_engine.py, feature_factory.py) depend on
        this exact derivation for seed reproducibility."""
        import hashlib

        expected = int(hashlib.md5(b"SPY").hexdigest()[:8], 16)
        assert hash_key_to_int("SPY") == expected

    def test_n_hex_chars_parameter_changes_result(self) -> None:
        assert hash_key_to_int("SPY", n_hex_chars=8) != hash_key_to_int("SPY", n_hex_chars=4)

    def test_composite_string_keys_work(self) -> None:
        """ic_engine.py's cross-sectional path keys by f'{tf}:{regime_label}', not
        a bare symbol -- any string key must work, not just tickers."""
        assert hash_key_to_int("1h:trending_up") != hash_key_to_int("1h:trending_down")
