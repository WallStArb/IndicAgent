"""CI guard: service_auditor.py's registry only points at real, non-archived systemd units.

_AGENT_ID_TO_UNIT and _DAG_ORDER (services/service_auditor.py) are hand-maintained string
tables with no structural check that a value actually corresponds to a live, non-archived
systemd unit. This already caused a real ~18-day silent outage (todo 200):
feature_vector_writer's agent_id was mapped to indicagent-feature-writer, the archived
v2.x unit, instead of the real indicagent-feature-vector-writer -- so the auditor
monitored a unit that was supposed to be dead and never alerted that the real v3.0
FeatureVectorWriter had no systemd unit deployed at all.

Note the archived .service FILES are still present on disk (production/systemd/ was never
swept when v2.x was archived) -- a naive "does the file exist" check alone would NOT have
caught the original bug, since indicagent-feature-writer.service does exist. The
_ARCHIVED_UNIT_DENYLIST check below is required in addition to the existence check.

Writing this test's existence check (below) against the live registry surfaced two real,
independently-verified findings, each recorded in _MISSING_UNIT_ALLOWLIST with its own
reason rather than silently fixed here (out of this test-authoring task's scope):

  - 6 Phase 138/142 IC-pipeline entries (regime-writer, forward-return-writer, ic-engine,
    ensemble-ic-engine, alpha-frame-writer, counterfactual-tracker) have no systemd unit at
    all, live or checked-in -- confirmed via `systemctl list-units --all` (zero hits) and
    `scripts/ops/corpus/ops_corpus_pipeline_run.sh`'s header, which documents these as
    orchestrated by that shell script instead. PERMANENT, by design.
  - `indicagent-feature-vector-pipeline` -- a live, always-on daemon, NOT a oneshot -- IS
    deployed on the box (`systemctl status` shows it loaded+enabled) but has been
    `failed`/start-limit-hit for ~2 days as of this writing, AND its unit file was never
    checked into production/systemd/ at all (repo/deploy drift). PENDING -- filed as todo 219
    rather than guessed at here.

CI-clean: no systemctl, no DB, no network -- pure filesystem read of production/systemd/.
"""

from __future__ import annotations

from pathlib import Path

from services.service_auditor import _AGENT_ID_TO_UNIT, _DAG_ORDER

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_SYSTEMD_DIR = _REPO_ROOT / "production" / "systemd"

# Unit names CLAUDE.md's Architecture section explicitly flags as archived/dead v2.x units
# -- confirmed failed/inactive-dead with ExecStart pointing at a deleted file, not a
# legitimate timer-triggered oneshot (those, e.g. ml-training/ml-orchestrator/roll-batch,
# are correctly "inactive (dead) between runs" per CLAUDE.md and must NOT be deny-listed).
# (unit_name, reason) -- a future deliberate exception gets a row here with justification,
# same convention as tests/unit/test_market_data_ohlcv_boundary.py's _ALLOW_LIST.
_ARCHIVED_UNIT_DENYLIST: dict[str, str] = {
    "indicagent-feature-writer": (
        "v2.x Typed Bus writer, ARCHIVED per CLAUDE.md Architecture section -- unit is "
        "inactive (dead), ExecStart points at services/feature_writer.py which no longer "
        "exists on disk. This exact unit is what todo 200 found feature_vector_writer's "
        "agent_id was silently mismapped to for ~18 days."
    ),
    "indicagent-intelligence-pipeline": (
        "v2.x pipeline, ARCHIVED per CLAUDE.md Architecture section -- unit is failed, "
        "ExecStart points at a deleted file. CLAUDE.md: 'Do not restart this unit "
        "expecting it to work.'"
    ),
}

# Registry entries with no matching production/systemd/ file, confirmed real (not a typo/
# rename) and documented with a reason rather than silently dropped from the check.
# (unit_name, reason) -- same allow-list-with-reason convention as _ARCHIVED_UNIT_DENYLIST
# and tests/unit/test_market_data_ohlcv_boundary.py's _ALLOW_LIST.
_MISSING_UNIT_ALLOWLIST: dict[str, str] = {
    "indicagent-regime-writer": (
        "PERMANENT: Phase 138 IC-pipeline oneshot, orchestrated by "
        "scripts/ops/corpus/ops_corpus_pipeline_run.sh, never deployed as a systemd unit by "
        "design -- confirmed zero hits in `systemctl list-units --all` (2026-07-31)."
    ),
    "indicagent-forward-return-writer": (
        "PERMANENT: same as indicagent-regime-writer above -- corpus-pipeline-script-only, "
        "confirmed no live or checked-in systemd unit."
    ),
    "indicagent-ic-engine": (
        "PERMANENT: same as indicagent-regime-writer above -- corpus-pipeline-script-only, "
        "confirmed no live or checked-in systemd unit."
    ),
    "indicagent-ensemble-ic-engine": (
        "PERMANENT: Phase 142A oneshot, same corpus-pipeline-script-only pattern as "
        "indicagent-regime-writer above."
    ),
    "indicagent-alpha-frame-writer": (
        "PERMANENT: Phase 142B oneshot, same corpus-pipeline-script-only pattern as "
        "indicagent-regime-writer above."
    ),
    "indicagent-counterfactual-tracker": (
        "PERMANENT: Phase 142B oneshot, same corpus-pipeline-script-only pattern as "
        "indicagent-regime-writer above."
    ),
    "indicagent-feature-vector-pipeline": (
        "PENDING (todo 219, filed 2026-07-31): unlike the entries above, this IS a live "
        "always-on daemon (DAG priority 6, not in _ONESHOT_UNITS) and IS deployed on the "
        "box (systemctl shows it loaded+enabled) -- it has simply never been checked into "
        "production/systemd/ (repo/deploy drift). Also independently found to be "
        "failed/start-limit-hit for ~2 days as of filing (unrelated crash: missing "
        "_THRESHOLD_KEYS entry in feature_vector_pipeline.py). Not fixed here -- out of "
        "this test-authoring task's scope; remove this entry once todo 219 lands the "
        "checked-in unit file."
    ),
}


def _unit_file_exists(unit: str) -> bool:
    return (_SYSTEMD_DIR / f"{unit}.service").exists() or (_SYSTEMD_DIR / f"{unit}.target").exists()


# -- Existence: every registry entry must point at a real unit file, or be on the
#    documented missing-unit allow-list -------------------------------------------------


def test_dag_order_keys_map_to_real_systemd_units():
    missing = sorted(
        unit
        for unit in _DAG_ORDER
        if not _unit_file_exists(unit) and unit not in _MISSING_UNIT_ALLOWLIST
    )
    assert not missing, (
        f"_DAG_ORDER key(s) with no matching .service/.target file under production/systemd/ "
        f"and not on _MISSING_UNIT_ALLOWLIST: {missing}"
    )


def test_agent_id_to_unit_values_map_to_real_systemd_units():
    missing = sorted(
        {
            unit
            for unit in _AGENT_ID_TO_UNIT.values()
            if not _unit_file_exists(unit) and unit not in _MISSING_UNIT_ALLOWLIST
        }
    )
    assert not missing, (
        f"_AGENT_ID_TO_UNIT value(s) with no matching .service/.target file under "
        f"production/systemd/ and not on _MISSING_UNIT_ALLOWLIST: {missing}"
    )


def test_missing_unit_allowlist_has_no_stale_entries():
    referenced = set(_DAG_ORDER) | set(_AGENT_ID_TO_UNIT.values())
    stale = sorted(
        unit
        for unit in _MISSING_UNIT_ALLOWLIST
        if unit not in referenced or _unit_file_exists(unit)
    )
    assert not stale, (
        f"_MISSING_UNIT_ALLOWLIST entries no longer needed (unit file now exists, or unit no "
        f"longer referenced by _DAG_ORDER/_AGENT_ID_TO_UNIT): {stale}. Remove the stale row."
    )


# -- Deny-list: no registry entry may point at a confirmed-archived unit -------------


def test_dag_order_keys_not_on_archived_denylist():
    hits = sorted(set(_DAG_ORDER) & set(_ARCHIVED_UNIT_DENYLIST))
    assert not hits, (
        f"_DAG_ORDER key(s) pointing at a confirmed-archived unit: "
        f"{[(unit, _ARCHIVED_UNIT_DENYLIST[unit]) for unit in hits]}"
    )


def test_agent_id_to_unit_values_not_on_archived_denylist():
    hits = sorted(set(_AGENT_ID_TO_UNIT.values()) & set(_ARCHIVED_UNIT_DENYLIST))
    assert not hits, (
        f"_AGENT_ID_TO_UNIT value(s) pointing at a confirmed-archived unit: "
        f"{[(unit, _ARCHIVED_UNIT_DENYLIST[unit]) for unit in hits]}"
    )
