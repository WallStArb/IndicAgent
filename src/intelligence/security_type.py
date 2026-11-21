"""Security type, resolved once per security (todo 648, amendment 2026-11-21).

The stage 2 membership needs the type of a security (common stock, ADR common, ETF are eligible).
A type is persistent metadata of the security, not a monthly event: Massive rebuilt its point-in-time
ticker lists in 2025 (rows of the 2005 and 2016 lists carry `last_updated_utc` 2025), the labels
changed meaning between lists (1,547 FIGIs change label at 2016-10, 725 at 2019-04 to 2019-09), and
about 40 percent of the 2008 list rows and 60 percent of 2016 carry none. A per-date label therefore
neither times a real event nor is known at its date, and a missing one reset the hysteresis of a name
that was a member the month before. So the type is resolved once from every typed row the security
holds in any list, by the class mapping below, and written to `security_type` with its evidence.

Pure functions over label counts: no I/O, deterministic, the order of the rows never matters. The
mapping values are pre-registered constants of the amendment (like the floors in
`universe_membership`), deliberately not APR keys: a tunable type map invites tuning after seeing
results. A change is a dated amendment and a new `TYPE_RULE_ID`.
"""

from __future__ import annotations

from collections.abc import Mapping

# Identifies the resolution rule below; the table's primary key carries it, so a rule change is a new
# build beside the old one, never an edit.
TYPE_RULE_ID = "security-type-2026-11-21"

# The ETF class: four labels Massive uses for the same instrument family. Of 1,740 symbols ever
# labelled INDEX, 1,357 also carry another ETF-class label and 379 of the other 383 have fund names;
# an instrument that trades has no index label (an index has no executions). ETV is a taxonomy step
# of 2022-10 for commodity ETFs (GLD, SLV, USO).
ETF_CLASS = frozenset({"ETF", "INDEX", "ETS", "ETV"})

# Labels that exclude a security from the eligible types and win over every other label it ever
# carried, in this order (the first one present is the resolved type). ETN first: an ETN is not an
# ETF (VXX, TVIX carry both labels).
EXCLUDING_FIRST = ("ETN", "WARRANT", "RIGHT", "PFD", "ADRP")

# Resolved types and what the rule does with them: `ETF` for the ETF class, `FUND` beneath it (a
# fund label alone, or over CS: 557 securities carry both; a business development company labelled
# FUND is a known error, disclosed), then the common-stock labels, with CS beating UNIT (a master
# limited partnership), then any other label.
COMMON = ("CS", "ADRC")  # tie-break order: more rows first, then this order


def resolve_security_type(labels: Mapping[str, int]) -> tuple[str | None, bool]:
    """The persistent type of a security and whether its labels disagree.

    `labels` maps each type label the security carries in any list to the number of rows. Returns
    (type, conflict): the type is None when the security carries no label (untyped, never filled),
    and `conflict` is true when the labels span more than one class (ETF class, common stock,
    FUND, UNIT, or any other single label counts as its own class), which the table records so the
    disagreement is counted, never hidden.
    """
    present = {label: n for label, n in labels.items() if n > 0}
    if not present:
        return None, False
    classes = {
        "ETF" if label in ETF_CLASS else "COMMON" if label in COMMON else label for label in present
    }
    conflict = len(classes) > 1
    for label in EXCLUDING_FIRST:
        if label in present:
            return label, conflict
    if present.keys() & ETF_CLASS:
        return "ETF", conflict
    if "FUND" in present:
        return "FUND", conflict
    common = [label for label in COMMON if label in present]
    if common:
        return max(common, key=lambda label: (present[label], -COMMON.index(label))), conflict
    if "UNIT" in present:
        return "UNIT", conflict
    return max(sorted(present), key=lambda label: present[label]), conflict
