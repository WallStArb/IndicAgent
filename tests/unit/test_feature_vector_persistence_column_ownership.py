"""Regression guard: REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES exclusion (Phase 172-02).

Root cause this prevents (documented at length in feature_vector_persistence.py's
comment block above REGIME_WRITER_OWNED_COLUMN_NAMES): a --refresh recompute's
FEATURE_VECTOR_UPSERT_SQL DO UPDATE SET clause would silently NULL out a column
family if that family isn't excluded from the derivation -- confirmed as the exact
root cause of the 2026-07-30 incident that nulled feature_vectors.regime across all
36.8M rows. This test pins the same invariant for the new regime_volatility family
(migration 307) before any compute path (Task 3+) writes to it, so the exclusion is
proven in place before there is any real data to lose.

No DB, no Kafka. Pure source introspection, same style as
test_feature_vector_persistence_completeness.py.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.intelligence.features.feature_vector_persistence import (
    _EXTERNALLY_OWNED_COLUMN_NAMES,
    FEATURE_VECTOR_UPSERT_SQL,
    REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES,
    REGIME_WRITER_OWNED_COLUMN_NAMES,
)


def _upsert_set_columns() -> list[str]:
    """Column names on the left of `= EXCLUDED.<same>` in DO UPDATE SET, in order."""
    match = re.search(r"DO UPDATE SET\s*(.*?)\s*\Z", FEATURE_VECTOR_UPSERT_SQL, re.DOTALL)
    assert match, "Could not parse DO UPDATE SET clause"
    return re.findall(r"(\w+)\s*=\s*EXCLUDED\.\1", match.group(1))


def test_regime_volatility_tuple_shape():
    """8-element tuple, regime_volatility first, in migration 307's declared order."""
    expected = (
        "regime_volatility",
        "hmm_vol_prob_calm",
        "hmm_vol_prob_elevated",
        "hmm_vol_prob_turbulent",
        "hmm_vol_regime_prob",
        "hmm_vol_entropy",
        "hmm_vol_duration",
        "hmm_vol_churn",
    )
    assert REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES == expected
    assert len(REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES) == 8


def test_regime_volatility_columns_absent_from_upsert_do_update_set():
    """None of the 8 new columns may appear in FEATURE_VECTOR_UPSERT_SQL's DO UPDATE
    SET -- a --refresh recompute must never be able to NULL this family out.

    Note: this assertion is currently true "by construction" (the 8 new columns
    aren't in _ALL_COLUMN_NAMES at all, same as 4 of the legacy 8 per this
    module's own comment), so it alone would not go red if the union below were
    dropped. test_regime_volatility_columns_in_externally_owned_set is the
    assertion that actually exercises the union and goes red if it's removed;
    this one is kept as a second, SQL-text-level structural check of the same
    invariant for when/if these columns are ever added to _ALL_COLUMN_NAMES.
    """
    set_columns = set(_upsert_set_columns())
    overlap = set_columns & set(REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES)
    assert not overlap, (
        f"DO UPDATE SET includes regime_volatility-owned column(s) {overlap} -- a "
        f"--refresh run will silently NULL this family corpus-wide"
    )


def test_regime_volatility_columns_in_externally_owned_set():
    """REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES must be unioned into
    _EXTERNALLY_OWNED_COLUMN_NAMES -- the actual exclusion mechanism
    _UPDATE_SET_SQL is derived from. This is the assertion that goes red if the
    union in feature_vector_persistence.py is ever dropped (verified manually
    during authoring: removing the union from _EXTERNALLY_OWNED_COLUMN_NAMES's
    derivation makes this specific test fail; the DO-UPDATE-SET-text test above
    does not, because these columns are absent from _ALL_COLUMN_NAMES entirely,
    the same "safe by construction" situation as 4 of the legacy 8 columns)."""
    missing = set(REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES) - _EXTERNALLY_OWNED_COLUMN_NAMES
    assert not missing, (
        f"REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES member(s) {missing} are not in "
        f"_EXTERNALLY_OWNED_COLUMN_NAMES -- if these columns are ever added to "
        f"_ALL_COLUMN_NAMES, a --refresh recompute would NULL them out corpus-wide"
    )


def test_legacy_regime_columns_still_absent_from_upsert_do_update_set():
    """The existing 8 REGIME_WRITER_OWNED_COLUMN_NAMES members must remain excluded
    too -- this new tuple must be UNIONED into the exclusion set, never substituted
    for the old one."""
    set_columns = set(_upsert_set_columns())
    overlap = set_columns & set(REGIME_WRITER_OWNED_COLUMN_NAMES)
    assert not overlap, (
        f"DO UPDATE SET includes legacy regime-owned column(s) {overlap} -- the "
        f"regime_volatility exclusion must not have replaced the existing one"
    )


def test_regime_volatility_and_legacy_tuples_are_disjoint():
    """The two families must not share any column name -- they are separate writers
    with separate ownership, not aliases of each other."""
    overlap = set(REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES) & set(
        REGIME_WRITER_OWNED_COLUMN_NAMES
    )
    assert not overlap, f"Unexpected shared column name(s) between the two families: {overlap}"
