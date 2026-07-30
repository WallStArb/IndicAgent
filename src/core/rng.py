"""Deterministic, process-stable string-to-int hashing for RNG seed derivation.

Ring 0: no domain vocabulary, portable infrastructure only. Extracted from
services/ic_engine.py's `_derive_worker_rng_seed` (2026-07-29 /simplify pass, todo
203) after the identical "MD5 hex-digest-first-N-chars-as-int" idiom was independently
re-derived in src/intelligence/feature_factory.py's `_canary_sub_seed` -- two
hand-copied implementations of the same primitive, each combining it with its own
caller-specific seed-mixing formula. This module holds only the shared hash step;
callers keep their own combination formula (`base_seed + hash % N`, or whatever theirs
requires) so this extraction changes zero output for either existing caller.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache

# Bounded, small key universe in every known caller (symbol tickers, or composite
# "tf:regime" strings) -- an LRU cache eliminates repeat hashing of the same key
# across a call site's lifetime (e.g. per-bar loops over one symbol) with no
# caller-visible behavior change, since this function is pure.
_CACHE_SIZE = 256


@lru_cache(maxsize=_CACHE_SIZE)
def hash_key_to_int(key: str, n_hex_chars: int = 8) -> int:
    """Deterministic int hash of a string key, via MD5 hex digest truncated to
    `n_hex_chars` and parsed as a base-16 integer.

    Uses hashlib (not Python's built-in hash()) so results are stable across
    processes/interpreter versions -- required wherever a seed must reproduce
    identically across ProcessPoolExecutor workers or separate runs
    (PYTHONHASHSEED randomizes hash() per-process otherwise).

    Only the hash-key-to-int step lives here -- callers combine this with their own
    base seed using whatever formula suits their reproducibility needs.
    """
    return int(hashlib.md5(key.encode()).hexdigest()[:n_hex_chars], 16)
