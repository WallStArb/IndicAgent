"""CI guard: schema-shape numbers typed into evergreen docs must match code truth
(todo 602).

CI has no live database, so the checkable source of truth is CODE, not the DB.
Two facts are derivable here:

- the `feature_vectors` column list, from `feature_vectors_columns()` in
  `src/intelligence/features/feature_vector_persistence.py` (registry order, the
  same explicit list the rebuild writer COPYs with);
- the `FeatureVector` field count, from `dataclasses.fields(FeatureVector)`.

Each guarded claim below pairs a doc file and a capture regex with the code
derivation. The regex is deliberately narrow so the failure names the doc line
to fix, not a vague mismatch. A DB-live number (row counts, coverage counts,
universe size, free disk) has no code truth and is NOT guarded here; those stay
in dated handoff sections (.planning/STATE.md) and dated measured-state tables,
never as undated claims in docs/foundation or canonical docs/plans. Historical
counts (a "before migration 577 dropped 13" note, a Phase A "50-column"
retelling) are pinned to their era and are not guarded either.

CI-clean: no DB, no network -- imports tests already use, plus a regex scan of
three markdown files.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from src.intelligence.features.feature_vector import FeatureVector
from src.intelligence.features.feature_vector_persistence import (
    feature_vectors_columns,
)

_REPO_ROOT = Path(__file__).parent.parent.parent

# (doc path relative to repo root, capture regex, code-derived truth, what the
# claim is). The regex must match exactly once in the file; if the doc wording
# changes, the "pattern not found" failure is the prompt to re-anchor the check.
_GUARDED_CLAIMS: tuple[tuple[str, str, object, str], ...] = (
    (
        "docs/foundation/glossary.md",
        r"since migration 570; (\d+) columns",
        lambda: len(feature_vectors_columns()),
        "feature_vectors column count (glossary feature_vectors entry)",
    ),
    (
        "docs/foundation/canonical-truth-registry.md",
        r"(\d+) typed columns per bar",
        lambda: len(feature_vectors_columns()),
        "feature_vectors column count (canonical-truth-registry route table row)",
    ),
    (
        "docs/foundation/business-requirements.md",
        r"(\d+) `FeatureVector` fields",
        lambda: len(dataclasses.fields(FeatureVector)),
        "FeatureVector dataclass field count (business-requirements Stage 0 row)",
    ),
)


def _doc_line(path: Path, pattern: str) -> tuple[int, str]:
    """The 1-based line number and the captured number for a guarded claim."""
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = re.search(pattern, line)
        if match:
            return lineno, match.group(1)
    raise AssertionError(
        f"{path}: no line matches {pattern!r}. The doc wording moved or the "
        "guarded number was removed; re-anchor this check's regex to the new "
        "wording (or drop the claim if the number is gone on purpose)."
    )


def test_guarded_doc_numbers_match_code_truth() -> None:
    failures: list[str] = []
    for rel_path, pattern, truth, claim in _GUARDED_CLAIMS:
        path = _REPO_ROOT / rel_path
        lineno, doc_number = _doc_line(path, pattern)
        code_number = truth()
        if int(doc_number) != code_number:
            failures.append(
                f"{path}:{lineno}: {claim} says {doc_number}, code derives "
                f"{code_number} -- fix the doc line (the number, not the check)"
            )
    assert not failures, "\n".join(failures)
