"""Config-dictionary readers and the lookahead and active-scale fallbacks."""

from __future__ import annotations

import json
from typing import Any

from src.config.config_service import ConfigService


def cfg(cfg_dict: dict[str, Any], key: str, default: Any) -> Any:
    """Cast a raw config_value to default's type, or return default if unset.

    bool is special-cased: config_value is always TEXT (e.g. "false"), and
    `bool("false")` is True in Python since any non-empty string is truthy --
    `type(default)(val)` would silently invert every falsy bool APR flag. Parsed
    via the same `str(val).lower() == "true"` idiom ic_engine.py's ConfigService
    path already uses for `alpha.regime.equity_model_enabled`.

    list/dict defaults are also special-cased (todo 187): `type(default)(val)` against
    a raw JSON-array/object string is a documented-broken cast (e.g.
    `list("[1,3,5,10]")` splits into individual characters, not the parsed list) --
    already fixed for dict defaults via `get_dict_config` below, generalized here so
    `cfg()` itself is safe for any json-typed default instead of every list-typed
    caller needing its own local `json.loads` workaround.
    """
    val = cfg_dict.get(key)
    if val is None:
        return default
    if isinstance(default, bool):
        return str(val).strip().lower() == "true"
    if isinstance(default, (list, dict)):
        return json.loads(val) if isinstance(val, str) else val
    return type(default)(val)


LOOKAHEAD_FALLBACKS_BY_TF: dict[str, dict[str, int]] = {
    "5m": {"fast": 1, "mid": 6, "slow": 12, "extended": 39},
    "15m": {"fast": 1, "mid": 2, "slow": 5, "extended": 10},
    "1h": {"fast": 1, "mid": 2, "slow": 20, "extended": 60},
    "1d": {"fast": 1, "mid": 2, "slow": 5, "extended": 10},
}
"""Todo 146's confirmed per-tf IC lookahead grid, as bar-count VALUES .
1h's slow(20)/extended(60) are unchanged from the old global default -- these bar
counts were never the problem; the now-removed same-ET-session completeness gate
(todo 208) was. Whether 20/60 bars is still the *right* grid for 1h once measured
under the corrected, session-agnostic completeness definition is a separate, open
tier-count/spacing question (todo 208's Step 3, deliberately deferred, not settled
by this table). The alpha.ic.lookahead.* APR keys retired with the old ic_engine
stack (phase 186 plan 23). Its one remaining consumer is ops_oos_holdout_eval.py, which
refuses since migration 575 and goes with todo 554; the IC writer's grid is
alpha.ic_measure.horizons."""


def _get_json_typed_config(cfg_service: ConfigService, key: str, default: dict | list) -> Any:
    """Shared implementation behind `get_dict_config`/`get_list_config`: read a
    JSON-typed APR key via `ConfigService.get_sync()`, tolerating either a pre-parsed
    dict/list (the normal case -- `load_config_service_sync`'s `_parse_value` already
    `json.loads()`s `value_type='json'` keys at cache-load time) or a raw JSON string
    (test/fallback default path). `cfg()` above can't be reused here: its
    `type(default)(val)` cast breaks for a dict/list default against a raw JSON-string
    value.
    """
    v = cfg_service.get_sync(key, default)
    if isinstance(v, type(default)):
        return v
    if isinstance(v, str):
        return json.loads(v)
    return default


def get_dict_config(cfg_service: ConfigService, key: str, default: dict) -> dict:
    """Read a JSON-object APR key -- see `_get_json_typed_config`."""
    return _get_json_typed_config(cfg_service, key, default)


def get_list_config(cfg_service: ConfigService, key: str, default: list) -> list:
    """Read a JSON-array APR key -- see `_get_json_typed_config`. Sibling of
    `get_dict_config` above."""
    return _get_json_typed_config(cfg_service, key, default)
