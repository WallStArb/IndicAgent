-- 585: register the two spread-estimator feature concepts as candidates (todo 601,
-- registry-schema reconciliation).
--
-- Migration 526 (todo 553) added the high_low_spread and roll_spread kernels
-- (src/intelligence/features/kernels/liquidity.py), their APR window seeds
-- (feature.high_low_spread.window, feature.roll_spread.window) and the two nullable
-- real columns on the feature table. The concept_registry rows were never inserted,
-- so the two stored columns sit outside the UCR until the 186-26 rerun populates
-- them and the ic_measure proposer first sweeps them. This closes that gap before
-- the first sweep: a measured column is a registered concept.
--
-- Data only: two INSERTs, no DDL, no compressed hypertable is touched, no VACUUM
-- clause is owed. Idempotent on the (domain, name) unique key. Candidate shape
-- mirrors migration 584 item 8 (dividend_yield): status candidate, enabled false,
-- no gate row (register_idea convention: a candidate earns its gate later).

INSERT INTO concept_registry
    (domain, name, description, status, enabled, group_name, is_control, added_phase, metadata)
VALUES
    (
        'feature',
        'high_low_spread',
        'Corwin-Schultz (2012) two-bar high-low spread estimate, negatives set to 0, averaged over feature.high_low_spread.window pairs (21: the paper''s monthly average of daily estimates); declared memory = window',
        'candidate',
        false,
        'volume',
        false,
        '601-recon',
        jsonb_build_object(
            'composition', 'base',
            'module', 'kernels/liquidity.py',
            'apr_namespace', 'feature.',
            'todo', '601 registry reconciliation',
            'provenance', 'kernels and APR seeds added by migration 526 (todo 553)'
        )
    ),
    (
        'feature',
        'roll_spread',
        'Roll (1984) implied spread: serial covariance of log close changes over feature.roll_spread.window return pairs (252: one trading year), NaN when the covariance is non-negative; declared memory = window + 1',
        'candidate',
        false,
        'volume',
        false,
        '601-recon',
        jsonb_build_object(
            'composition', 'base',
            'module', 'kernels/liquidity.py',
            'apr_namespace', 'feature.',
            'todo', '601 registry reconciliation',
            'provenance', 'kernels and APR seeds added by migration 526 (todo 553)'
        )
    )
ON CONFLICT (domain, name) DO NOTHING;
