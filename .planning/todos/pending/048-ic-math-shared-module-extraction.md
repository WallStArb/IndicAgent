# Extract shared IC math out of ic_engine.py's private internals

**Found:** 2026-07-02, during `/simplify` pass on Phase 142A (`services/ensemble_ic_engine.py`).

`ensemble_ic_engine.py` imports `_fisher_z_ci`, `_vectorized_ic`, `_nan_to_none`,
`_p_values_from_ic`, `_compute_ic_rolling_metrics` directly from `services/ic_engine.py` —
all underscore-prefixed (private-by-convention) module functions. The in-code comment frames
this as "composition, not forking," which is the right call methodologically (parity should
be structural, not re-derived), but mechanically it means two Ring 2 daemons now share state
by reaching into each other's internals rather than through a public interface. If
`ic_engine.py`'s internals shift shape (return tuple order, signature), `ensemble_ic_engine.py`
breaks silently at runtime with no import-time signal.

There's also a related smell: `services/ensemble_trainer.py`, `services/alpha_publisher.py`,
and now `services/ensemble_ic_engine.py` each hand-roll their own `_load_apr` /
`_cfg_float`/`_cfg_int`/`_cfg_str`-style APR-loading helpers (asyncpg version) — a third
verbatim copy of the same pattern across `services/`.

**Action:** Extract the shared Fisher-z CI / BH-FDR / rolling-Sharpe math into a Ring 0/Ring 1
module (e.g. `src/intelligence/statistics/ic_math.py`) with a public API; have both
`ic_engine.py` and `ensemble_ic_engine.py` import from there instead of one reaching into the
other's private functions. Separately, consider adding an asyncpg equivalent of
`services/_batch_utils.py`'s `load_config_service_sync` (that module is psycopg2-based today)
so `ensemble_trainer.py`, `alpha_publisher.py`, and `ensemble_ic_engine.py` can all call one
shared APR loader instead of three copies.

**Blocked on:** nothing — safe to fix anytime. Deferred out of the `/simplify` pass because
both fixes require touching files outside the reviewed diff (`ic_engine.py`,
`ensemble_trainer.py`, `alpha_publisher.py`) and are architecture-level moves, not local
cleanup.
