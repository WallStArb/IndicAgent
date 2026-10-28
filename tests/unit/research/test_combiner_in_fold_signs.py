"""In-fold equal-weight signs (design 4.2, plan 187-09 Task 3, R-187-17)."""

import datetime
import json
import warnings
from types import SimpleNamespace

import numpy as np
import pytest

from src.intelligence.research.book import book_memory
from src.intelligence.research.combiner import (
    EqualWeight,
    SignFold,
    exchange_sessions,
    in_fold_signs,
    refit_positions,
)
from src.intelligence.research.horizon import HorizonRule

BPS = 2
FOLD = SignFold(window_rows=40 * BPS, refit_rows=10 * BPS, embargo=3)


def _panel(seed=0, n=400, m=40):
    """Member 0 carries +IC, member 1 -IC, member 2 is noise; the target is their mix."""
    rng = np.random.default_rng(seed)
    stack = rng.normal(size=(n, m, 3))
    target = 0.4 * stack[:, :, 0] - 0.4 * stack[:, :, 1] + rng.normal(size=(n, m))
    return stack, target


def _old_equal_weight(stack, signs):
    """EqualWeight.combine before the fold field (complete-case, fixed signs)."""
    x = stack.astype(np.float64)
    x = np.where(np.isfinite(x).all(axis=2, keepdims=True), x, np.nan)
    with warnings.catch_warnings(), np.errstate(invalid="ignore", divide="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        sd = np.nanstd(x, axis=1, keepdims=True)
        z = (x - np.nanmean(x, axis=1, keepdims=True)) / np.where(sd > 0, sd, np.nan)
        return (z * np.asarray(signs)).mean(axis=2)


def _z(stack):
    sd = stack.std(axis=1, keepdims=True)
    return (stack - stack.mean(axis=1, keepdims=True)) / sd


def test_fixed_signs_are_unchanged():
    stack, target = _panel()
    stack[np.random.default_rng(1).random(stack.shape) < 0.1] = np.nan
    ew = EqualWeight((1.0, -1.0, 1.0))
    assert ew.training_rows == 0
    np.testing.assert_array_equal(ew.combine(stack, target), _old_equal_weight(stack, ew.signs))


def test_planted_members_get_their_signs_and_rows_before_the_first_refit_are_nan():
    stack, target = _panel()
    signs = in_fold_signs(_z(stack), target, (None, None, 1.0), FOLD, None)
    first = refit_positions(len(stack), FOLD)[0]
    assert first == FOLD.window_rows + FOLD.embargo - 1
    assert np.isnan(signs[:first, :2]).all()
    assert (signs[first:, 0] == 1).all() and (signs[first:, 1] == -1).all()
    assert (signs[:, 2] == 1).all()  # a fixed sign holds on every row
    combined = EqualWeight((None, None, 1.0), fold=FOLD).combine(stack, target)
    assert np.isnan(combined[:first]).all() and np.isfinite(combined[first:]).all()


def test_signs_are_causal():
    stack, target = _panel(seed=2, m=6)  # a thin cross-section, so the signs move
    z = _z(stack)
    base = in_fold_signs(z, target, (None, None, None), FOLD, None)
    for p in refit_positions(len(stack), FOLD):
        later = target.copy()
        later[p - FOLD.embargo + 1 :] *= -1  # every target from the embargo boundary on
        moved = in_fold_signs(z, later, (None, None, None), FOLD, None)
        np.testing.assert_array_equal(moved[p], base[p])


def test_a_zero_fold_ic_makes_the_member_absent():
    stack, target = _panel()
    stack[:, :, 2] = np.where(np.arange(stack.shape[1]) % 2, 1.0, -1.0)  # same every row
    target[:] = 0.0  # no spread in the target: every fold IC is undefined
    signs = in_fold_signs(_z(stack), target, (1.0, -1.0, None), FOLD, None)
    assert np.isnan(signs[:, 2]).all()
    complete_case = EqualWeight((1.0, -1.0, None), fold=FOLD).combine(stack, target)
    assert np.isnan(complete_case).all()
    present = EqualWeight((1.0, -1.0, None), min_members=2, fold=FOLD).combine(stack, target)
    z = _z(stack)
    np.testing.assert_allclose(present, (z[:, :, 0] - z[:, :, 1]) / 3)


def test_an_anchored_fold_refits_on_the_calendar_grid():
    sessions = exchange_sessions(np.datetime64("2014-01-02"), np.datetime64("2016-12-31"))[:200]
    rows = np.repeat(sessions, BPS)
    stack, target = _panel(n=len(rows), m=6, seed=3)
    anchored = SignFold(40 * BPS, 10 * BPS, 3, refit_anchor=datetime.date(2014, 1, 9))
    signs = in_fold_signs(_z(stack), target, (None, None, None), anchored, rows)
    changes = np.flatnonzero(np.any(signs[1:] != signs[:-1], axis=1) & ~np.isnan(signs[1:, 0]))
    assert sessions[5] == np.datetime64("2014-01-09")  # the anchor is session 5
    grid_rows = {BPS * i for i in range(200) if i % 10 == 5}  # first row of each grid session
    assert changes.size and {int(r) + 1 for r in changes} <= grid_rows
    with pytest.raises(ValueError, match="row_session_dates"):
        in_fold_signs(_z(stack), target, (None, None, None), anchored, None)


def test_training_rows_enter_the_book_memory():
    ew = EqualWeight((None, 1.0), fold=FOLD)
    assert ew.training_rows == FOLD.window_rows + FOLD.embargo
    mem = book_memory([5], [5 * BPS], 1, ew, HorizonRule(), BPS)
    fixed = book_memory([5], [5 * BPS], 1, EqualWeight((1.0, 1.0)), HorizonRule(), BPS)
    assert mem.combiner_rows == ew.training_rows
    assert mem.rows - fixed.rows == ew.training_rows
    assert mem.sessions > fixed.sessions


def test_a_fold_is_required_exactly_when_a_sign_is_in_fold():
    with pytest.raises(ValueError, match="fold"):
        EqualWeight((None, 1.0))
    with pytest.raises(ValueError, match="fold"):
        EqualWeight((1.0, 1.0), fold=FOLD)
    with pytest.raises(ValueError):
        SignFold(0, 1, 1)


_SIGNS = "fam_one.{}: in_fold"


def _in_fold_line(names, extra=""):
    signs = ", ".join(_SIGNS.format(n) for n in names)
    return f"combiner: {{kind: equal_weight, signs: {{{signs}}}{extra}}}"


def test_spec_in_fold_signs_need_the_fold_fields(tmp_path):
    from tests.unit.research.test_spec import FAMILY, _book, parse_spec_text

    names = [m.name for m in parse_spec_text(FAMILY).members]
    fixed_line = f"combiner: {{kind: equal_weight, signs: {{fam_one.{names[0]}: 1"
    fixed = _book(tmp_path, fixed_line + "".join(f", fam_one.{n}: -1" for n in names[1:]) + "}}")
    assert "sign_window_sessions" not in json.loads(fixed.canonical)["book"]["combiner"]
    fold = ", sign_window_sessions: 60, sign_refit_sessions: 21"
    loaded = _book(tmp_path, _in_fold_line(names, fold))
    assert loaded.model.combiner.sign_window_sessions == 60
    assert loaded.spec_hash != fixed.spec_hash
    _book(tmp_path, _in_fold_line(names, fold + ', refit_anchor: "2014-01-02"'))
    for bad in (
        _in_fold_line(names),  # in_fold without the fold
        _in_fold_line(names, ", sign_window_sessions: 60"),  # half the fold
        "combiner: {window_sessions: 252, refit_sessions: 21, penalty: 1.0, min_obs: 10000"
        ", sign_window_sessions: 60, sign_refit_sessions: 21}",  # a ridge takes none
    ):
        with pytest.raises(ValueError):
            _book(tmp_path, bad)
    fixed_with_fold = f"combiner: {{kind: equal_weight, signs: {{fam_one.{names[0]}: 1"
    fixed_with_fold += "".join(f", fam_one.{n}: 1" for n in names[1:]) + "}" + fold + "}"
    with pytest.raises(ValueError, match="in_fold"):
        _book(tmp_path, fixed_with_fold)


def test_runner_builds_the_fold_and_names_the_feature():
    from src.intelligence.research import runner as runner_mod
    from src.intelligence.research.panel import fwd_span
    from src.intelligence.research.spec import CombinerSpec

    c = CombinerSpec(
        kind="equal_weight",
        signs={"f.a": "in_fold", "f.b": -1},
        sign_window_sessions=60,
        sign_refit_sessions=21,
        refit_anchor="2014-01-02",
    )
    book = SimpleNamespace(combiner=c)
    ew = runner_mod._combiner(book, ["f.a", "f.b"], BPS, 1)
    assert ew.signs == (None, -1.0)
    assert ew.fold == SignFold(60 * BPS, 21 * BPS, fwd_span(1), datetime.date(2014, 1, 2))
    assert runner_mod._combiner_features(book) == ("refit_anchor", "in_fold_signs")
    assert runner_mod._in_fold_settings(book) == {
        "sign_window_sessions": 60,
        "sign_refit_sessions": 21,
    }


def test_the_last_training_row_moves_the_sign():
    """The fold reaches row p - embargo exactly: not short of it (the causality test above
    only proves it stops there)."""
    stack, target = _panel(m=6)
    z = _z(stack)
    one_row = SignFold(window_rows=1, refit_rows=10 * BPS, embargo=3)
    p = refit_positions(len(stack), one_row)[3]
    last = p - one_row.embargo  # the fold's only training row
    base = in_fold_signs(z, target, (None, None, None), one_row, None)
    flipped = target.copy()
    flipped[last] *= -1
    moved = in_fold_signs(z, flipped, (None, None, None), one_row, None)
    finite = np.isfinite(base[p])
    assert finite.any()
    np.testing.assert_array_equal(moved[p][finite], -base[p][finite])


def test_a_fold_longer_than_the_panel_leaves_every_in_fold_member_absent():
    stack, target = _panel(n=40)
    signs = in_fold_signs(_z(stack), target, (None, 1.0, None), SignFold(50, 10, 3), None)
    assert np.isnan(signs[:, [0, 2]]).all() and (signs[:, 1] == 1).all()
    ew = EqualWeight((None, 1.0, None), fold=SignFold(50, 10, 3))
    assert np.isnan(ew.combine(stack, target)).all()


def test_the_certificate_pins_the_in_fold_settings():
    from src.intelligence.research import certificate as cert
    from tests.unit.research.test_certificate import FP, GOOD, _holds

    settings = {"sign_window_sessions": 60, "sign_refit_sessions": 21}
    good = {**GOOD, "in_fold": settings, "cells": _holds("equal_weight_in_fold_signs")}
    features = ("in_fold_signs",)
    args = ("equal_weight", None, "real", good, FP, None, features)
    assert cert.fitted_book_refusal(*args, settings) is None
    other = {**settings, "sign_window_sessions": 120}
    assert "not the certified" in cert.fitted_book_refusal(*args, other)
    no_cell = {**good, "cells": {}}
    assert "equal_weight_in_fold_signs" in cert.fitted_book_refusal(
        "equal_weight", None, "real", no_cell, FP, None, features, settings
    )
