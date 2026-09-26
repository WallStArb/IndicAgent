"""Spec as pre-registration (D-01): strict schema, canonical hash, HEAD-blob loader, member
resolver restricted to the families package."""

import dataclasses
import json
import subprocess
import textwrap

import pytest
from pydantic import ValidationError

from src.intelligence.research import spec as spec_mod
from src.intelligence.research.evaluate import ROW_SCALED_FIELDS, UNSCALED_FIELDS
from src.intelligence.research.spec import (
    MEMBER_PREFIX,
    FamilySpec,
    canonical_json,
    load_spec_from_file,
    load_spec_from_head,
    parse_spec_text,
    resolve_member,
)

FAMILY = textwrap.dedent("""
    kind: family
    family: fam_one
    prior_source: docs/plans/prereg.md
    horizon: 2
    factor_spec: vintage_1
    panel:
      universe: compute_eligible
      tf: 15m
      bars_per_session: 26
      start: "2006-07-01"
      end_exclusive: "2025-12-24"
    members:
      - name: lag_one
        signal: src.intelligence.research.families.fam.same_slot_mean
        params: {window_sessions: 1}
        slot_history_sessions: 1
        declared_memory_rows: 7124
      - name: mean_five
        signal: src.intelligence.research.families.fam.same_slot_mean
        params: {window_sessions: 5}
        slot_history_sessions: 5
        declared_memory_rows: 7228
    construction:
      name: rank_vol_neutral
      direction: 1
      coverage_floor: 20
      vol_window_sessions: 20
      vol_min_finite_fraction: 0.5
    scoring:
      session_scoring: true
      trading_start: "2010-01-04"
      sub_periods: [["2010-01-04", "2014-12-31"], ["2015-01-01", "2025-12-23"]]
      min_shift: 63
      bootstrap_mean_block: 21
      bootstrap_reps: 2000
      seed: 7
      warmup_sessions: 252
      calibration_refit_sessions: 21
      coverage_fraction: 0.5
      ridge_epsilon_fraction: 1.0e-4
      mv_condition_max: 1.0e+6
      ic_shrinkage_k: 100.0
    guards:
      seed: 11
      n_random: 20
      max_rows: 200
      s1_probe_sessions: 330
    costs:
      bps_low: 1.0
      bps_high: 5.0
    """)

BOOK = textwrap.dedent("""
    kind: book
    book: book_one
    prior_source: docs/plans/prereg.md
    families: [research/specs/fam.yaml]
    combiner: {window_sessions: 252, refit_sessions: 21, penalty: 1.0, min_obs: 10000}
    construction:
      name: rank_vol_neutral
      direction: 1
      coverage_floor: 20
      vol_window_sessions: 20
      vol_min_finite_fraction: 0.5
    scoring:
      session_scoring: true
      trading_start: "2010-01-04"
      sub_periods: [["2010-01-04", "2025-12-23"]]
      min_shift: 63
      bootstrap_mean_block: 21
      bootstrap_reps: 2000
      seed: 7
      warmup_sessions: 252
      calibration_refit_sessions: 21
      coverage_fraction: 0.5
      ridge_epsilon_fraction: 1.0e-4
      mv_condition_max: 1.0e+6
      ic_shrinkage_k: 100.0
    guards: {seed: 11, n_random: 20, max_rows: 200, s1_probe_sessions: 330}
    costs: {bps_low: 1.0, bps_high: 5.0}
    power:
      planted_rank_ic: 0.002
      participation_ratio: 60.0
      n_common_factors: 10
      plant_lags_sessions: 40
      replicates: 100
      seed: 3
      calibration_panels: 4
      calibration_seed: 5
      calibration_tolerance: 1.0e-4
    """)


def _hash(text):
    return spec_mod._sha(canonical_json(spec_mod._family_dump(parse_spec_text(text))))


def test_formatting_and_comments_do_not_change_the_hash():
    reformatted = "# a comment\n" + FAMILY.replace("  - name: lag_one", "\n  - name: lag_one")
    reordered = FAMILY.replace("kind: family\nfamily: fam_one", "family: fam_one\nkind: family")
    assert _hash(FAMILY) == _hash(reformatted) == _hash(reordered)


def test_a_member_param_changes_the_hash():
    assert _hash(FAMILY) != _hash(FAMILY.replace("window_sessions: 5", "window_sessions: 6"))


def test_yaml_type_traps_are_rejected():
    with pytest.raises(ValidationError):
        parse_spec_text(
            FAMILY.replace("ridge_epsilon_fraction: 1.0e-4", "ridge_epsilon_fraction: 1e-4")
        )
    with pytest.raises(ValidationError):
        parse_spec_text(FAMILY.replace('start: "2006-07-01"', "start: 2006-07-01"))
    with pytest.raises(ValidationError):
        parse_spec_text(FAMILY.replace("session_scoring: true", "session_scoring: no"))


@pytest.mark.parametrize(
    "old,new",
    [
        ("  bps_high: 5.0", "  bps_high: 5.0\n  extra: 1"),
        ("horizon: 2", "horizon: 2\nsurprise: 1"),
        ("direction: 1", "direction: 0"),
        ("direction: 1", "direction: 2"),
        ("name: mean_five", "name: lag_one"),
        (
            'sub_periods: [["2010-01-04", "2014-12-31"], ["2015-01-01", "2025-12-23"]]',
            'sub_periods: [["2015-01-01", "2025-12-23"], ["2010-01-04", "2014-12-31"]]',
        ),
    ],
)
def test_invalid_specs_are_rejected(old, new):
    assert old in FAMILY
    with pytest.raises(ValidationError):
        parse_spec_text(FAMILY.replace(old, new))


@pytest.mark.parametrize("path", ["os.system", "src.intelligence.research.evaluate.evaluate"])
def test_member_paths_outside_families_are_rejected(path, monkeypatch):
    with pytest.raises(ValidationError):
        parse_spec_text(FAMILY.replace(f"{MEMBER_PREFIX}fam.same_slot_mean", path, 1))
    calls = []
    monkeypatch.setattr(spec_mod.importlib, "import_module", lambda name: calls.append(name))
    with pytest.raises(ValueError, match="families"):
        resolve_member(path)
    assert calls == []


def test_book_hash_moves_with_a_family_spec(tmp_path):
    (tmp_path / "research/specs").mkdir(parents=True)
    fam = tmp_path / "research/specs/fam.yaml"
    book = tmp_path / "research/specs/book.yaml"
    fam.write_text(FAMILY)
    book.write_text(BOOK)
    first = load_spec_from_file(book, root=tmp_path).spec_hash
    fam.write_text(FAMILY.replace("window_sessions: 5", "window_sessions: 6"))
    assert load_spec_from_file(book, root=tmp_path).spec_hash != first


def test_book_families_must_share_panel_and_horizon(tmp_path):
    (tmp_path / "research/specs").mkdir(parents=True)
    (tmp_path / "research/specs/fam.yaml").write_text(FAMILY)
    (tmp_path / "research/specs/fam2.yaml").write_text(
        FAMILY.replace("family: fam_one", "family: fam_two").replace("horizon: 2", "horizon: 3")
    )
    book = tmp_path / "research/specs/book.yaml"
    book.write_text(
        BOOK.replace(
            "[research/specs/fam.yaml]", "[research/specs/fam.yaml, research/specs/fam2.yaml]"
        )
    )
    with pytest.raises(ValueError, match="horizon"):
        load_spec_from_file(book, root=tmp_path)


def test_evaluation_config_satisfies_evaluate():
    model = parse_spec_text(FAMILY)
    assert isinstance(model, FamilySpec)
    cfg = model.scoring.evaluation_config()
    for name in (*ROW_SCALED_FIELDS, *UNSCALED_FIELDS):
        assert hasattr(cfg, name), name
    assert dataclasses.replace(cfg, warmup_sessions=1).warmup_sessions == 1
    assert cfg.sub_periods == (("2010-01-04", "2014-12-31"), ("2015-01-01", "2025-12-23"))


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def test_load_from_head_reads_the_committed_blob(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "research/specs").mkdir(parents=True)
    path = tmp_path / "research/specs/fam.yaml"
    path.write_text(FAMILY)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "spec")
    path.write_text(FAMILY.replace("window_sessions: 5", "window_sessions: 9"))
    loaded = load_spec_from_head(tmp_path, "research/specs/fam.yaml")
    assert loaded.spec_hash == _hash(FAMILY)
    assert loaded.blob_sha == _git(tmp_path, "rev-parse", "HEAD:research/specs/fam.yaml")


def test_canonical_json_refuses_nan():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


def test_timing_statistic_is_hashed_only_when_set():
    """Specs run under E16 keep their recorded hashes; setting the E17 statistic is a new one."""
    assert "timing_statistic" not in FAMILY
    e17 = FAMILY.replace(
        "ic_shrinkage_k: 100.0\n", "ic_shrinkage_k: 100.0\n  timing_statistic: e17\n"
    )
    assert parse_spec_text(e17).scoring.timing_statistic == "e17"
    assert '"timing_statistic"' not in canonical_json(
        spec_mod._family_dump(parse_spec_text(FAMILY))
    )
    assert _hash(e17) != _hash(FAMILY)
    with pytest.raises(ValidationError):
        parse_spec_text(e17.replace("timing_statistic: e17", "timing_statistic: e16"))


_RIDGE = "combiner: {window_sessions: 252, refit_sessions: 21, penalty: 1.0, min_obs: 10000}"


def _book(tmp_path, combiner_line):
    (tmp_path / "research/specs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "research/specs/fam.yaml").write_text(FAMILY)
    book = tmp_path / "research/specs/book.yaml"
    book.write_text(BOOK.replace(_RIDGE, combiner_line))
    return load_spec_from_file(book, root=tmp_path)


def test_legacy_ridge_combiner_keeps_its_canonical_form(tmp_path):
    loaded = _book(tmp_path, _RIDGE)
    combiner = json.loads(loaded.canonical)["book"]["combiner"]
    assert combiner == {
        "window_sessions": 252,
        "refit_sessions": 21,
        "penalty": 1.0,
        "min_obs": 10000,
    }
    assert loaded.model.combiner.kind is None


def test_equal_weight_combiner_needs_one_sign_per_member(tmp_path):
    names = [m.name for m in parse_spec_text(FAMILY).members]
    signs = ", ".join(f"fam_one.{n}: 1" for n in names)
    loaded = _book(tmp_path, f"combiner: {{kind: equal_weight, signs: {{{signs}}}}}")
    assert loaded.model.combiner.signs == {f"fam_one.{n}": 1 for n in names}
    assert loaded.spec_hash != _book(tmp_path, _RIDGE).spec_hash
    partial = ", ".join(f"fam_one.{n}: 1" for n in names[1:])
    with pytest.raises(ValueError, match="missing"):
        _book(tmp_path, f"combiner: {{kind: equal_weight, signs: {{{partial}}}}}")


@pytest.mark.parametrize(
    "line",
    [
        "combiner: {kind: equal_weight, signs: {fam_one.x: 1}, penalty: 1.0}",
        "combiner: {kind: equal_weight}",
        "combiner: {kind: equal_weight, signs: {fam_one.x: 2}}",
        "combiner: {window_sessions: 252, refit_sessions: 21, penalty: 1.0}",
    ],
)
def test_combiner_fields_must_match_kind(tmp_path, line):
    with pytest.raises(ValueError):
        _book(tmp_path, line)
