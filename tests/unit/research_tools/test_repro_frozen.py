"""Tests of the promoted repro_frozen tool: remapping unpickler, same(), import hygiene."""

import pickle
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import scripts.research.determinism.repro_frozen as rf

from src.intelligence.research.evaluate import EvaluationResult

REPO = Path(rf.__file__).resolve().parents[3]
OLD_EVAL_MODULE = "scripts.analysis.sleeve_walk_forward.evaluate"


def _fixture_result() -> EvaluationResult:
    return EvaluationResult(
        arms=("a", "b"),
        sharpe_obs=np.array([0.5, -0.2], dtype="float32"),
        sharpe_null=np.arange(6, dtype="float32").reshape(3, 2),
        shifts=np.array([63, 126, 252], dtype="int64"),
        adjusted_p=np.array([0.4, 0.6], dtype="float32"),
        excess=np.array([0.1, -0.05], dtype="float32"),
        sub_period_excess=np.arange(6, dtype="float32").reshape(2, 3),
        excess_ci=np.arange(4, dtype="float32").reshape(2, 2),
    )


def _fixture_pickle_with_old_module_path(tmp_path: Path) -> Path:
    """Pickle at protocol 0 (GLOBAL opcode stores the module as newline-terminated text), then
    rewrite the module string so the bytes name the pre-move module path."""
    path = tmp_path / "fixture.pkl"
    path.write_bytes(pickle.dumps(_fixture_result(), protocol=0))
    data = path.read_bytes()
    new = data.replace(
        b"src.intelligence.research.evaluate",
        OLD_EVAL_MODULE.encode(),
    )
    assert new != data and OLD_EVAL_MODULE.encode() in new
    path.write_bytes(new)
    return path


class TestRemappingUnpickler:
    def test_renamed_modules_has_exactly_one_entry(self):
        assert rf._RENAMED_MODULES == {OLD_EVAL_MODULE: "src.intelligence.research.evaluate"}

    def test_fixture_loads_through_remap_with_module_blocked(self, tmp_path, monkeypatch):
        path = _fixture_pickle_with_old_module_path(tmp_path)
        monkeypatch.setitem(sys.modules, OLD_EVAL_MODULE, None)
        with pytest.raises(ModuleNotFoundError):
            pickle.loads(path.read_bytes())
        loaded = rf.load_frozen(path)
        assert type(loaded) is EvaluationResult
        np.testing.assert_array_equal(loaded.excess, _fixture_result().excess)
        np.testing.assert_array_equal(loaded.sharpe_null, _fixture_result().sharpe_null)

    def test_other_modules_load_unchanged(self, tmp_path):
        path = tmp_path / "od.pkl"
        od = pickle.dumps({"k": __import__("collections").OrderedDict([("a", 1)])})
        path.write_bytes(od)
        assert isinstance(rf.load_frozen(path)["k"], __import__("collections").OrderedDict)


class TestRealFrozenPickles:
    @pytest.mark.parametrize(
        "relpath",
        [
            "phase179/rerun_e14/s3_4dead18ade3bde16.pkl",
            "phase181/s3_d3c9294661215c6d.pkl",
        ],
    )
    def test_frozen_s3_loads_with_shim_blocked(self, relpath, monkeypatch):
        path = rf.frozen_logs_dir(None) / relpath
        if not path.exists():
            pytest.skip(f"frozen artifact missing: {path}")
        monkeypatch.setitem(sys.modules, OLD_EVAL_MODULE, None)
        payload = rf.load_frozen(path)["payload"]
        assert isinstance(payload["result"], EvaluationResult)


class TestSame:
    def test_equal_nested_structures_pass(self):
        a = _fixture_result()
        b = pickle.loads(pickle.dumps(a))
        assert rf.same(a, b)
        assert rf.same({"x": [np.array([1.0, np.nan])]}, {"x": [np.array([1.0, np.nan])]})

    def test_one_ulp_float32_difference_raises(self):
        a = np.array([1.0], dtype="float32")
        b = np.nextafter(np.array([1.0], dtype="float32"), np.array([2.0], dtype="float32"))
        with pytest.raises(AssertionError):
            rf.same(a, b)

    def test_nan_equals_nan(self):
        assert rf.same(np.array([np.nan], dtype="float32"), np.array([np.nan], dtype="float32"))


class TestImportHygiene:
    def test_import_leaves_no_old_chain_modules_and_no_argv_parse(self):
        probe = (
            "import sys;"
            "sys.argv=['prog','--bogus-flag','another'];"
            "import scripts.research.determinism.repro_frozen as m;"
            "bad=[k for k in sys.modules"
            " if k.startswith('scripts.analysis')"
            " or k in ('services.ic_engine','services.ensemble_trainer',"
            "'services.cross_sectional_regime_model')];"
            "print('BAD', bad)"
        )
        out = subprocess.run(
            [sys.executable, "-c", probe], cwd=REPO, capture_output=True, text=True
        )
        assert out.returncode == 0, out.stderr
        assert "BAD []" in out.stdout


class TestFrozenLogsDir:
    def test_none_from_worktree_resolves_to_main_checkout_logs(self):
        logs = rf.frozen_logs_dir(None)
        assert (logs / "phase181").is_dir()
        assert logs.name == "logs"

    def test_explicit_path_wins(self, tmp_path):
        assert rf.frozen_logs_dir(tmp_path) == tmp_path
