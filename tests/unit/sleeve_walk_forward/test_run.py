import json
import pickle

import numpy as np
import pytest

from scripts.analysis.sleeve_walk_forward import run
from scripts.analysis.sleeve_walk_forward.config import HarnessConfig
from scripts.analysis.sleeve_walk_forward.results import GroupArrays, Snapshot
from tests.unit.sleeve_walk_forward.test_refit import _snapshot

CFG = HarnessConfig(
    refit_years=range(
        2009, 2010
    ),  # one refit: the fixture's 2008 refit has under a year to train on
    training_start="2007-01-01",
    warmup_sessions=60,
    calibration_refit_sessions=30,
    min_shift=20,
    trading_start="2009-04-15",
    sub_periods=(
        ("2009-04-15", "2009-05-31"),
        ("2009-06-01", "2009-07-15"),
        ("2009-07-16", "2009-12-31"),
    ),
    bootstrap_reps=50,
)


def _e2e_snapshot() -> Snapshot:
    # One equity regime, so every scored day has stratum weights; with two, early refits
    # leave half the days without alpha and calibration's 95% coverage bar zeroes the book.
    base = _snapshot()
    one = np.full(len(base.sessions), "hi")
    eq = GroupArrays(
        **{**base.groups["equity"].__dict__, "labels": one[base.groups["equity"].session_idx]}
    )
    base = Snapshot(
        **{
            **base.__dict__,
            "groups": {**base.groups, "equity": eq},
            "all_1d": eq,
            "equity_labels": one,
        }
    )
    n, f = len(base.sessions), len(base.feature_names)
    feats = np.full((n, 3, f), np.nan, np.float32)
    for j, sym in enumerate(("E0", "E1", "E2")):
        m = eq.symbols == sym
        feats[eq.session_idx[m], j] = eq.X[m]
    rng = np.random.default_rng(3)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n, 3)), axis=0))
    return Snapshot(
        **{
            **base.__dict__,
            "sleeve_features": feats,
            "sleeve_has_row": np.ones((n, 3), bool),
            "sleeve_opens": closes,
            "sleeve_closes": closes,
        }
    )


@pytest.fixture
def harness(tmp_path, monkeypatch):
    snap = _e2e_snapshot()
    monkeypatch.setattr(run, "CONFIG", CFG)
    monkeypatch.setattr(run, "load_snapshot", lambda _path: snap)
    monkeypatch.setattr(run, "verify_snapshot", lambda _path: None)  # fixture is not on disk
    (tmp_path / "snapshot_fixture").mkdir()
    excluded = tmp_path / "excluded.json"
    excluded.write_text("[]")
    return tmp_path, excluded


def test_stages_chain_to_a_verdict(harness):
    out, excluded = harness
    s1 = run.main(
        [
            "--stage",
            "s1",
            "--in",
            str(out / "snapshot_fixture"),
            "--out-dir",
            str(out),
            "--excluded-file",
            str(excluded),
        ]
    )
    s2 = run.main(["--stage", "s2", "--in", str(s1), "--out-dir", str(out)])
    s3 = run.main(["--stage", "s3", "--in", str(s2), "--out-dir", str(out)])
    s4 = run.main(["--stage", "s4", "--in", str(s3), "--out-dir", str(out), "--fidelity", "OK"])
    verdict = json.loads(s4.with_suffix(".json").read_text())
    assert verdict["fidelity"] == "OK"
    assert verdict["sleeve_verdict"] in {"FAIL", "PASS"}
    assert set(verdict["diagnostics"]) == {"ic_proportional", "vol_normalized", "mean_variance"}
    assert [p.name.split("_")[0] for p in (s1, s2, s3, s4)] == ["s1", "s2", "s3", "s4"]


def test_same_inputs_same_artifact_hash(harness):
    out, excluded = harness
    args = [
        "--stage",
        "s1",
        "--in",
        str(out / "snapshot_fixture"),
        "--out-dir",
        str(out),
        "--excluded-file",
        str(excluded),
    ]
    assert run.main(args).name == run.main(args).name


def test_parent_from_other_commit_is_refused(harness):
    out, excluded = harness
    s1 = run.main(
        [
            "--stage",
            "s1",
            "--in",
            str(out / "snapshot_fixture"),
            "--out-dir",
            str(out),
            "--excluded-file",
            str(excluded),
        ]
    )
    obj = pickle.loads(s1.read_bytes())
    obj["code_key"] = "0" * 64
    s1.write_bytes(pickle.dumps(obj))
    with pytest.raises(SystemExit, match="code"):
        run.main(["--stage", "s2", "--in", str(s1), "--out-dir", str(out)])
    assert run.main(
        ["--stage", "s2", "--in", str(s1), "--out-dir", str(out), "--allow-code-drift"]
    ).exists()


def test_s1_requires_an_exclusion_list(harness):
    out, _ = harness
    with pytest.raises(SystemExit):
        run.main(["--stage", "s1", "--in", str(out / "snapshot_fixture"), "--out-dir", str(out)])


def test_code_key_covers_harness_sources(tmp_path, monkeypatch):
    src = tmp_path / "stage.py"
    src.write_text("x = 1\n")
    monkeypatch.setattr(run, "_HARNESS_SOURCES", (src,))
    before = run._code_key()
    src.write_text("x = 2\n")
    assert run._code_key() != before


def test_payload_records_git_commit(harness):
    out, excluded = harness
    s1 = run.main(
        [
            "--stage",
            "s1",
            "--in",
            str(out / "snapshot_fixture"),
            "--out-dir",
            str(out),
            "--excluded-file",
            str(excluded),
        ]
    )
    obj = pickle.loads(s1.read_bytes())
    assert len(obj["git_commit"]) == 40 and isinstance(obj["git_dirty"], bool)
