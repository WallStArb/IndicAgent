"""The persistent-predictor E17 battery module (plan 184-05): cells, certificates, wiring."""

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from src.intelligence.features.research_kernels import rolling
from src.intelligence.research import null_battery_persistent as b
from src.intelligence.research import static_sizes
from src.intelligence.research.book import book_memory
from src.intelligence.research.combiner import EqualWeight
from src.intelligence.research.horizon import HorizonRule
from src.intelligence.research.member_memory import (
    feature_member_memory_rows,
    feature_member_memory_sessions,
)


def _gating():
    return [c for c in b.scenarios() if c.name not in b.DIAGNOSTIC_CELLS]


def _cell(name):
    return next(c for c in b.scenarios() if c.name == name)


def _tiny(name, **kw):
    return dataclasses.replace(_cell(name), sessions=1500, names=30, **kw)


# --- cells and certificates -------------------------------------------------------------


def test_scenario_names_are_unique_and_diagnostics_are_cells():
    names = [c.name for c in b.scenarios()]
    assert len(names) == len(set(names))
    assert b.DIAGNOSTIC_CELLS <= set(names)


def test_every_certificate_is_horizon_one_equal_weight():
    for c in b.scenarios():
        assert c.certificate.horizon == 1
        assert c.certificate.combiner == "equal_weight"


def test_gating_certificates_are_exactly_the_planned_set():
    got = {
        (
            c.certificate.identity,
            c.certificate.window,
            c.certificate.smoothing_half_life,
            c.certificate.source_tf,
            c.certificate.book_tf,
            c.certificate.max_gap_rows,
            c.certificate.source_memory_bars_max,
        )
        for c in _gating()
    }
    kernels = {(rolling.family_of(k.name), rolling.window_of(k.name)): k for k in rolling.KERNELS}
    want = {
        ("feature", None, None, "1d", "1d", None, 252),
        ("feature", None, None, "1h", "1d", None, 140),
        ("feature", None, None, "15m", "1d", None, 520),
        ("feature", None, None, "5m", "1d", None, 1560),
        ("feature", None, 5, "1d", "1d", None, 252),
        ("feature", None, 21, "1d", "1d", None, 252),
        ("feature", None, 63, "1d", "1d", None, 252),
        ("feature", None, 21, "1h", "1d", None, 140),
        ("feature", None, None, "1d", "1h", None, 252),
    }
    for (family, window), _ in sorted(kernels.items()):
        want.add((family, window, None, "1d", "1d", 2, window - 1))
    want.add(("rk_vwap_dev", 20, None, "1h", "1d", 2, 19))
    assert got == want


def test_kernel_certificates_take_their_windows_from_the_registry():
    registry = {(rolling.family_of(k.name), rolling.window_of(k.name)) for k in rolling.KERNELS}
    kernel_cells = [c for c in _gating() if c.certificate.identity != "feature"]
    assert kernel_cells
    for c in kernel_cells:
        assert (c.certificate.identity, c.certificate.window) in registry


def test_cell_memory_is_book_memory_over_the_one_member_memory_function():
    for c in b.scenarios():
        cert = c.certificate
        s, bk = b._SOURCE_BARS[cert.source_tf], b._BOOK_BARS[cert.book_tf]
        kw = dict(
            source_memory_bars=cert.source_memory_bars_max,
            source_bars_per_session=s,
            max_age_rows=cert.max_age_rows,
            smoothing_half_life=cert.smoothing_half_life,
            slot_history_sessions=0,
            book_bars_per_session=bk,
        )
        want = book_memory(
            [feature_member_memory_sessions(**kw)],
            [feature_member_memory_rows(**kw)],
            1,
            EqualWeight((1.0,)),
            HorizonRule(),
            bk,
        ).sessions
        assert b.cell_memory_sessions(c) == want
    # a daily target adds its reach (timing.e17_memory); an hourly target does not
    assert b.cell_memory_sessions(_cell("f1d_tau20")) == 252 + 1 + 1
    assert b.cell_memory_sessions(_cell("book1h_f1d_tau20")) == 252 + 1


def test_the_gate_and_clock_are_wired():
    gate = b.static_gate()
    assert isinstance(gate, static_sizes.StaticGate)
    assert gate.cell_rows == 1


def test_default_gate_is_zero_while_no_passing_certificate_has_a_stress_cell():
    """Todo 588 B1: the only cells with static means failed, so every passing certificate gates
    at 0 until part B adds passing static-stress cells."""
    gate = b.static_gate()
    assert gate.static_sd == (0.0,) and gate.time_of_day == (0.0,)
    for c in b.PASSING_CERTIFICATES:
        gate = b.static_gate([c])
        assert gate.static_sd == (0.0,) and gate.time_of_day == (0.0,), c
    assert max(c.static_cell_sd for c in _gating()) > 0  # the failed cells did carry sizes


def test_gate_comes_from_the_given_certificates_cells_only(monkeypatch):
    base = _cell("f1d_tau20")
    stressed = dataclasses.replace(
        base,
        name="stress",
        certificate=dataclasses.replace(base.certificate, source_tf="1h"),
        static_cell_sd=0.3,
        slot_effect_sd=0.02,
    )
    other = dataclasses.replace(base, name="other", static_cell_sd=0.1, slot_effect_sd=0.01)
    monkeypatch.setattr(b, "scenarios", lambda: (other, stressed))
    assert b.static_gate([other.certificate]).static_sd == (0.1,)
    assert b.static_gate([stressed.certificate]).static_sd == (0.3,)
    assert b.static_gate([stressed.certificate]).time_of_day == (0.02,)
    both = b.static_gate([other.certificate, stressed.certificate])
    assert both.static_sd == (0.3,)
    # a certificate no cell carries gates at 0
    nothing = dataclasses.replace(base.certificate, window=7)
    assert b.static_gate([nothing]).static_sd == (0.0,)
    assert b.static_gate([]).static_sd == (0.0,)


def test_a_diagnostic_cell_never_lifts_a_gate(monkeypatch):
    base = _cell("f1d_tau20")
    diag = dataclasses.replace(base, name="hostile_tau200", static_cell_sd=0.3)
    monkeypatch.setattr(b, "scenarios", lambda: (diag,))
    assert b.static_gate([base.certificate]).static_sd == (0.0,)


# --- admission --------------------------------------------------------------------------


def _request(cert, **kw):
    fields = {
        f.name: getattr(cert, f.name)
        for f in dataclasses.fields(cert)
        if f.name != "source_memory_bars_max"
    }
    return b.CertificateRequest(**{**fields, "source_memory_bars": 200, **kw})


@pytest.fixture
def cert():
    return _cell("f1d_tau20").certificate


def test_certificate_admits_an_exact_match_within_the_memory_bound(cert):
    assert b.admit(_request(cert), [cert]) is cert
    assert b.admit(_request(cert, source_memory_bars=cert.source_memory_bars_max), [cert]) is cert


@pytest.mark.parametrize(
    "change",
    [
        {"identity": "rk_vwap_dev"},
        {"window": 252},
        {"smoothing_half_life": 21},
        {"source_tf": "15m"},
        {"book_tf": "1h"},
        {"horizon": 2},
        {"combiner": "ridge"},
        {"max_age_rows": 2},
        {"max_gap_rows": 2},
        {"source_memory_bars": 253},
    ],
)
def test_certificate_refuses_when_any_one_field_differs(cert, change):
    with pytest.raises(b.NotCertified):
        b.admit(_request(cert, **change), [cert])


def test_certificate_refusal_names_the_nearest_mismatch(cert):
    other = dataclasses.replace(cert, source_tf="1h", source_memory_bars_max=140)
    with pytest.raises(b.NotCertified, match="smoothing_half_life"):
        b.admit(_request(cert, smoothing_half_life=21), [other, cert])


def test_certificate_with_nothing_passing_refuses_every_request(cert):
    with pytest.raises(b.NotCertified):
        b.admit(_request(cert), ())


def test_certificate_default_set_is_passing_certificates(cert, monkeypatch):
    monkeypatch.setattr(b, "PASSING_CERTIFICATES", (cert,))
    assert b.admit(_request(cert)) is cert


# --- simulation -------------------------------------------------------------------------


def test_simulate_is_finite_and_deterministic():
    sc = _tiny("f1d_tau20")
    out = b.simulate(sc, 5)
    assert set(out) == {"member", "book_equal"}
    assert all(np.isfinite(t) and 0 <= p <= 1 for t, p in out.values())
    assert b.simulate(sc, 5) == out
    assert b.simulate(sc, 6) != out


@pytest.mark.parametrize(
    "name",
    [
        "f1h_tau20",
        "f15m_tau20",
        "f5m_tau20",
        "f1d_s21_tau5",
        "f1h_s21_tau5",
        "rk_price_percentile_w126_1d",
        "rk_vwap_dev_w20_1h",
        "book1h_f1d_tau20",
    ],
)
def test_every_route_simulates(name):
    sc = _tiny(name)
    detail = b.simulate_detail(sc, 2)
    assert all(np.isfinite(t) and n > 0 for t, p, n in detail.values()), name


def test_the_daily_null_has_an_overnight_component():
    """A panel whose opens equal the previous closes hides the overnight move a daily open-to-open
    target shares with a close-to-close signal (the blind spot behind the E17 L off-by-one)."""
    resid, target = b.null_returns(_tiny("f1d_tau20"), 1)
    gap = (target[:-1] - resid[1:])[np.isfinite(target[:-1]) & np.isfinite(resid[1:])]
    assert gap.std() > 0.3


def test_intraday_book_target_stays_in_session():
    sc = _tiny("book1h_f1d_tau20")
    resid, target = b.null_returns(sc, 1)
    bk = sc.book_bars_per_session
    pos = np.arange(len(target)) % bk
    assert np.isnan(target[pos == bk - 2]).all()
    ok = np.isfinite(target[:-1]) & np.isfinite(resid[1:])
    assert np.allclose(target[:-1][ok], resid[1:][ok])


def test_the_predictor_does_not_see_the_target():
    """Under H0 the member and the target are independent: the cross-sectional rank correlation
    averages to zero."""
    sc = dataclasses.replace(_cell("f1d_tau5"), sessions=1500, names=60)
    resid, target = b.null_returns(sc, 3)
    alpha = b.member_alpha(sc, 3, resid)
    ics = []
    for t in range(300, 1400):
        ok = np.isfinite(alpha[t]) & np.isfinite(target[t])
        if ok.sum() > 20:
            ics.append(np.corrcoef(alpha[t][ok], target[t][ok])[0, 1])
    assert abs(np.mean(ics)) < 4 * np.std(ics) / np.sqrt(len(ics))


def test_persistence_matches_tau():
    sc = dataclasses.replace(_cell("f1d_tau20"), sessions=2000, names=40, late_fraction=0.0)
    resid, _ = b.null_returns(sc, 4)
    x = b.member_alpha(sc, 4, resid)
    ok = np.isfinite(x[1:]) & np.isfinite(x[:-1])
    lag1 = np.corrcoef(x[1:][ok], x[:-1][ok])[0, 1]
    assert 0.85 < lag1 < 0.99


# --- the passing set follows the committed report ---------------------------------------


def _report_rows():
    """{cell: (role, certificate, verdict)} parsed from the committed battery report."""
    path = (
        Path(__file__).resolve().parents[3]
        / ".planning/phases/184-multi-timeframe-research-inputs/184-05-BATTERY.md"
    )
    rows = {}
    for line in path.read_text().splitlines():
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) != 22 or cols[1] not in ("gate", "diag"):
            continue

        def val(x):
            return None if x == "None" else int(x) if x.lstrip("-").isdigit() else x

        cert = b.BatteryCertificate(
            identity=cols[2],
            window=val(cols[3]),
            smoothing_half_life=val(cols[4]),
            source_tf=cols[5],
            book_tf=cols[6],
            horizon=val(cols[7]),
            combiner=cols[8],
            max_age_rows=val(cols[9]),
            max_gap_rows=val(cols[10]),
            source_memory_bars_max=val(cols[11]),
        )
        rows[cols[0]] = (cols[1], cert, cols[21])
    return rows


def test_report_has_one_row_per_scenario_with_its_certificate():
    rows = _report_rows()
    assert set(rows) == {c.name for c in b.scenarios()}
    for sc in b.scenarios():
        assert rows[sc.name][1] == sc.certificate
        assert (rows[sc.name][0] == "diag") == (sc.name in b.DIAGNOSTIC_CELLS)


def _report_text():
    return (
        Path(__file__).resolve().parents[3]
        / ".planning/phases/184-multi-timeframe-research-inputs/184-05-BATTERY.md"
    ).read_text()


def _report_passing():
    gating = [(cert, verdict) for role, cert, verdict in _report_rows().values() if role == "gate"]
    return {cert for cert, _ in gating if all(v == "PASS" for c, v in gating if c == cert)}


def test_passing_certificates_are_the_reports_passing_set_minus_the_withheld():
    want = _report_passing()
    assert want
    assert set(b.WITHHELD_CERTIFICATES) <= want
    assert set(b.PASSING_CERTIFICATES) == want - set(b.WITHHELD_CERTIFICATES)
    assert len(b.PASSING_CERTIFICATES) == len(want) - len(b.WITHHELD_CERTIFICATES)


def test_every_withheld_certificate_is_listed_in_the_report_with_its_reason():
    text = _report_text()
    assert "## Withheld" in text
    section = text.split("## Withheld", 1)[1]
    assert b.WITHHELD_CERTIFICATES
    for cert, reason in b.WITHHELD_CERTIFICATES.items():
        assert reason.strip()
        assert reason in section, cert


def test_the_withheld_set_is_the_588_set():
    withheld = {
        (c.identity, c.smoothing_half_life, c.source_tf, c.book_tf) for c in b.WITHHELD_CERTIFICATES
    }
    assert withheld == {
        ("feature", 5, "1d", "1d"),
        ("rk_vwap_dev", None, "1d", "1d"),
        ("rk_vwap_dev", None, "1h", "1d"),
    }
    assert {c.identity for c in b.PASSING_CERTIFICATES} == {"feature", "rk_high_dist"}
    assert all(c.smoothing_half_life is None for c in b.PASSING_CERTIFICATES)


@pytest.mark.parametrize("cert", list(b.WITHHELD_CERTIFICATES))
def test_a_withheld_route_is_refused_by_the_default_pool(cert):
    with pytest.raises(b.NotCertified):
        b.admit(_request(cert))
