"""The shared H0 generator's bit-identity pins (todo 546).

The three battery modules (null_battery, null_battery_overnight_intraday,
null_battery_daily_residual) compose these primitives, and their recorded battery results and
static gates are valid only if the primitives reproduce, bit for bit, the values the inline
copies produced at fixed seeds. The hashes below were captured from the pre-refactor modules
immediately before the refactor; if one fails, a stress changed and every battery certified on
it is stale. Bit-identity pins by hash, not golden files: the arrays are deterministic given
the seed, so the hash is the array.

Bit-identity rule (memory): seeds bind by cell position; compare only at identical seeds.
"""

import hashlib

import numpy as np
import pytest

from src.intelligence.research import null_battery as nb
from src.intelligence.research import null_battery_daily_residual as nd
from src.intelligence.research import null_battery_overnight_intraday as no
from src.intelligence.research import null_panels

# (module, scenario kwargs, seed, expected [panel hash, target hash]), captured 2026-11-01
# from the pre-refactor inline stresses. sha256 of the float64 bytes, first 16 hex chars.
_PINS = {
    "nb_all_4242": (
        nb,
        dict(
            sessions=80,
            names=12,
            t4_noise=True,
            static_cell_sd=0.3,
            slot_effect_sd=0.2,
            factor_sd=0.5,
            vol_clustering=True,
            late_fraction=0.25,
            late_name=True,
        ),
        4242,
        ["934378cd8af5b638", "32c2951c55766284"],
    ),
    "nb_plain_5": (nb, dict(sessions=60, names=8), 5, ["7275acb10c3a4b87", "8fecae8e91e17890"]),
    "legs_all_99": (
        no,
        dict(
            sessions=70,
            names=10,
            leg_means=(0.1, 0.0, -0.1),
            t4_noise=True,
            static_cell_sd=(0.2, 0.0, 0.3),
            factor_sd=0.4,
            vol_clustering=True,
            late_fraction=0.2,
            late_name=True,
        ),
        99,
        ["73b335ccb59da314", "abb340baa1c7712a"],
    ),
    "daily_all_1234": (
        nd,
        dict(
            sessions=90,
            names=14,
            market_mean=0.05,
            t4_noise=True,
            static_sd=0.25,
            factor_sd=0.6,
            vol_clustering=True,
            late_fraction=0.3,
            late_name=True,
        ),
        1234,
        ["5c086cb8a2142c9a", "fa879648dc101c21"],
    ),
}


def _h(a: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(a, dtype=np.float64)).hexdigest()[:16]


@pytest.mark.parametrize("key", sorted(_PINS))
def test_battery_panels_are_bit_identical_at_the_pinned_seeds(key):
    module, kwargs, seed, expected = _PINS[key]
    scenario = (
        nb.NullScenario(key, **kwargs)
        if module is nb
        else no.LegsScenario(key, **kwargs) if module is no else nd.DailyScenario(key, **kwargs)
    )
    panel, target = module.null_panel(scenario, seed)
    assert [_h(panel), _h(target)] == expected


def test_vol_clustering_matches_the_ar1_definition() -> None:
    call_rng, ref_rng = np.random.default_rng(7), np.random.default_rng(7)
    u = np.ones((40, 3, 2))
    out = null_panels.vol_clustering(u, call_rng)
    log_vol = np.zeros(40)
    shocks = 0.15 * ref_rng.standard_normal(40)
    for s in range(1, 40):
        log_vol[s] = 0.97 * log_vol[s - 1] + shocks[s]
    np.testing.assert_array_equal(out, u * np.exp(log_vol)[:, None, None])


def test_factor_term_draw_orders_differ_at_a_fixed_seed() -> None:
    """The flag exists because the historical copies drew in both orders; the orders must
    stay distinct or one family's pins silently move."""
    a = null_panels.factor_term(np.random.default_rng(1), (10, 1), 5, 0.5, loadings_first=True)
    b = null_panels.factor_term(np.random.default_rng(1), (10, 1), 5, 0.5, loadings_first=False)
    assert not np.array_equal(a, b)
