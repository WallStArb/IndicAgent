"""CI guard: no new `feature_vectors` reader outside this checked-in allow-list (184 B1k).

A backtest that reads stored features outside the research runner is an uncounted look
(unified design section 12.2): its result never enters the attempt ledger, so the selection
it informs carries no multiplicity charge. Research reads stored features only through S0
(`src/intelligence/research/feature_inputs.py`), which every runner attempt counts. This grep
makes any other new reader a reviewed diff: a new file that names the table fails CI until it
is added here with a reason.

Two patterns, independent of which physical table name is current: a `FROM`/`JOIN` of the table
and a quoted table-name literal (which catches `sql.Identifier("feature_vectors")`, table
constants and `--feature-table` defaults). Both match `feature_vectors`, `feature_vectors_v2`
and any swap-era name such as `feature_vectors_old` alike. The allow-list is keyed by file, not
by table name, so 186-27's swap (readers move from `_v2` to the bare name) keeps every entry
valid; if 186-27 deletes a file's last reference, its executor prunes that stale entry in the
same commit.

Entries are per file; a directory is never listed, so a new file under `scripts/research/`
fails closed even beside listed legacy scripts. Each legacy research reader's reason names the
removal todo by file name, and `test_legacy_entries_name_removal_todo` holds that todo to exist
(184-REVIEWS row 18).

CI-clean: no DB, no network; a pure filesystem grep.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

from tests.unit._source_grep_helpers import (
    assert_allow_list_has_no_stale_entries,
    assert_no_unlisted_references,
    find_pattern_references,
)

_REPO_ROOT = Path(__file__).parent.parent.parent
_TABLE_PATTERN = re.compile(
    r"""\b(?:FROM|JOIN)\s+"?feature_vectors(?:_[a-z0-9]+)*\b"""
    r"""|["']feature_vectors(?:_[a-z0-9]+)*["']"""
)
_SEARCH_DIRS = ("services", "src", "scripts")
_LEGACY_DIR = "scripts/research/"
_REMOVAL_TODO_PATTERN = re.compile(r"^[0-9]+-remove-legacy-feature-vectors-research-readers\.md$")
_REMOVAL_TODO = "554-remove-legacy-feature-vectors-research-readers.md"
_LEGACY = (
    "LEGACY research reader: pre-184 exploratory reader, existing; new research must use the "
    f"runner (S0). Removal: todo {_REMOVAL_TODO}."
)

# (file, reason): every `feature_vectors` reference in the tree must appear here.
_ALLOW_LIST: dict[str, str] = {
    # Writers and the write path.
    "services/feature_vector_writer.py": (
        "WRITER: the streaming persistence writer; checks the table's columns at startup."
    ),
    "services/backfill_feature_factory.py": (
        "WRITER: the 186-26 rebuild writer; names its target table feature_vectors_v2."
    ),
    "services/regime_writer.py": (
        "WRITER: writes the regime columns by key and reads the rows it updates."
    ),
    "services/_batch_utils.py": (
        "WRITER: bulk-load infrastructure; the table is in the hardened write-session set."
    ),
    "services/rebuild_preconditions.py": (
        "WRITER: 186-26 launch preconditions check that feature_vectors_v2 exists."
    ),
    # Measurement.
    "services/ic_measure.py": (
        "MEASUREMENT: the IC measure job's feature table argument (sql.Identifier)."
    ),
    "services/cross_sectional_regime_model.py": (
        "MEASUREMENT: reads the feature bar grid for the cross-sectional regime model."
    ),
    # Lifecycle, ops and observability.
    "services/feature_lifecycle.py": (
        "LIFECYCLE: the sole feature-domain status writer reads coverage and the schema."
    ),
    "services/regime_coverage_auditor.py": (
        "OPS: regime column coverage audit (counts, no values reach a decision)."
    ),
    "src/api/routes/pipeline.py": "OPS: newest bar per feature store for the status page.",
    "src/config/vocabulary_drift.py": (
        "OPS: scans distinct regime labels for vocabulary drift (no feature values)."
    ),
    "src/observability/corpus_manifest_verifier.py": (
        "OPS: corpus manifest counts per tf (symbols, rows)."
    ),
    "scripts/ops/corpus/ops_corpus_pipeline_run.sh": "OPS: corpus pipeline progress counts.",
    "scripts/ops/corpus/ops_pipeline_monitor.sh": "OPS: corpus pipeline monitor counts.",
    "scripts/ops/corpus/ops_ctf_columns_recompute_15m.py": (
        "OPS: one-shot ctf column recompute at 15m (reads and rewrites stored columns)."
    ),
    "scripts/ops/corpus/ops_regime_null_out_and_verify.py": (
        "OPS: regime column null-out and verification (todo 248 hygiene)."
    ),
    "scripts/ops/corpus/ops_stale_k3_hmm_fields_cleanup.py": ("OPS: stale k=3 HMM field cleanup."),
    "scripts/ops/alpha/ops_broadcast_feature_audit.py": (
        "OPS: broadcast (HTF-constant) feature audit; a data-shape diagnostic, no returns."
    ),
    "scripts/ops/alpha/ops_dependence_length_diagnostic.py": (
        "OPS: feature autocorrelation dependence-length diagnostic, no returns."
    ),
    "scripts/ops/corpus/ops_oos_holdout_eval.py": (
        "LEGACY evaluation reader: reads features against forward opens outside the runner, an "
        f"uncounted look. Removal: todo {_REMOVAL_TODO}."
    ),
    # Research S0.
    "src/intelligence/research/feature_inputs.py": (
        "RESEARCH S0: the research S0 read; every research read goes through the runner and is "
        "counted (184 B1e)."
    ),
    # Legacy research scripts.
    "scripts/research/feature_matrix.py": _LEGACY,
    "scripts/research/todo445_5m_incremental_ic.py": _LEGACY,
}


@functools.lru_cache(maxsize=1)
def _find_table_references() -> dict[str, int]:
    """{relative_path: match_count} for every .py/.sh file under _SEARCH_DIRS naming the table."""
    return find_pattern_references(
        _REPO_ROOT, _SEARCH_DIRS, _TABLE_PATTERN, file_globs=("*.py", "*.sh")
    )


def test_every_feature_vectors_reference_is_on_the_allow_list():
    assert_no_unlisted_references(
        _find_table_references(),
        _ALLOW_LIST,
        what="`feature_vectors` reader(s)",
        remedy=(
            "Research reads stored features only through the runner's S0 "
            "(src/intelligence/research/feature_inputs.py), so the look is counted. A genuine "
            "non-research reader (writer, measurement, ops) goes on _ALLOW_LIST in this file "
            "with a one-line reason."
        ),
    )


def test_feature_vectors_allow_list_has_no_stale_entries():
    assert_allow_list_has_no_stale_entries(_find_table_references(), _ALLOW_LIST)


def test_legacy_entries_name_removal_todo():
    assert not [p for p in _ALLOW_LIST if p.endswith("/")], "the allow-list is per file"
    legacy = {p: r for p, r in _ALLOW_LIST.items() if p.startswith(_LEGACY_DIR)}
    pending = {
        p.name
        for p in (_REPO_ROOT / ".planning" / "todos" / "pending").iterdir()
        if _REMOVAL_TODO_PATTERN.match(p.name)
    }
    for path, reason in legacy.items():
        named = [name for name in pending if name in reason]
        assert named, (
            f"{path}: a legacy reason must name an existing pending removal todo "
            f"(pending matches: {sorted(pending)}), got {reason!r}"
        )
