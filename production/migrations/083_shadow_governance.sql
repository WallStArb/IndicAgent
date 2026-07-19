-- Shadow governance tables: shadow_registry + shadow_transition_log (Phase 75)
-- shadow_registry: single source of truth for shadow state and per-component gate params.
-- shadow_transition_log: immutable audit trail of promotions and demotions.

CREATE TABLE IF NOT EXISTS shadow_registry (
    component_name                TEXT PRIMARY KEY,
    component_type                TEXT NOT NULL
        CHECK (component_type IN ('i7_plugin', 'swarm_agent')),
    is_shadow                     BOOLEAN NOT NULL DEFAULT TRUE,
    enrolled_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    promoted_at                   TIMESTAMPTZ,
    demoted_at                    TIMESTAMPTZ,
    min_n                         INTEGER NOT NULL DEFAULT 100,
    min_ev_r                      FLOAT NOT NULL DEFAULT 0.0,
    ci_alpha                      FLOAT NOT NULL DEFAULT 0.05,
    demotion_lookback_days        INTEGER NOT NULL DEFAULT 30,
    demotion_threshold_ev_r       FLOAT NOT NULL DEFAULT -0.05,
    demotion_min_evaluations      INTEGER NOT NULL DEFAULT 3,
    demotion_consecutive_count    INTEGER NOT NULL DEFAULT 0,
    last_eval_n                   INTEGER,
    last_eval_ev_r                FLOAT,
    last_eval_ci_lower            FLOAT,
    last_eval_win_rate            FLOAT,
    last_eval_at                  TIMESTAMPTZ
);

COMMENT ON TABLE shadow_registry IS
    'Per-component shadow state and gate parameters. Single source of truth.';
COMMENT ON COLUMN shadow_registry.is_shadow IS
    'TRUE = shadow mode (not live); FALSE = live (promoted). Default TRUE.';
COMMENT ON COLUMN shadow_registry.demotion_consecutive_count IS
    'Rolling count of consecutive eval periods where EV[R] < demotion_threshold_ev_r.';

CREATE TABLE IF NOT EXISTS shadow_transition_log (
    id             BIGSERIAL PRIMARY KEY,
    component_name TEXT NOT NULL,
    component_type TEXT NOT NULL,
    from_state     TEXT NOT NULL
        CHECK (from_state IN ('shadow', 'live')),
    to_state       TEXT NOT NULL
        CHECK (to_state IN ('shadow', 'live')),
    triggered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trigger_reason TEXT NOT NULL,
    n              INTEGER,
    ev_r           FLOAT,
    ci_lower       FLOAT,
    win_rate       FLOAT
);

COMMENT ON TABLE shadow_transition_log IS
    'Immutable audit trail of all shadow↔live transitions. Append-only.';

CREATE INDEX IF NOT EXISTS shadow_transition_log_component_ts_idx
    ON shadow_transition_log (component_name, triggered_at DESC);
