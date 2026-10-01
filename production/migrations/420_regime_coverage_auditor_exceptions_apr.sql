-- Migration 420: regime coverage auditor known exceptions (phase 186 plan 186-18, todos 341 and 289)
--
-- The nightly regime-coverage-auditor failed every night on BIL, EMLC, ETHA, IBIT and VIXY (their
-- stored feature_vectors.regime is all NULL), so the alarm carried no information. The auditor now
-- fails only on an unregistered gap or an expired registration; this seeds the registry with the
-- five symbols, diagnosed by scripts/infrastructure/features_regime_kernel_coverage_sweep.py on the
-- 186-13 kernel (evidence/186-18-regime-coverage.json, key todo_341): every one has kernel labels in
-- at least one trend cell (class d), so the stored NULLs come from the old writer and the 186-26
-- rebuild clears them. Each entry expires 90 days after this migration (a review date): renew it
-- with a fresh diagnosis or remove it; once the rebuild lands the entries go stale and the auditor
-- warns instead of failing.
--
-- Todo 289: alpha.hmm.walk_forward.refit_every_bars.1d stays 252. The pre-registered rule (todo 289,
-- committed before the run) compared the larger of the two families' pooled 1d skip fractions at
-- 126, 252 and 504 over 931 names: 0.9838, 0.9821, 0.9794. 252 is within 0.02 of the smallest, so
-- it is kept; no schedule change, so no config_history row for it.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.regime.coverage_auditor.known_exceptions',
    'json',
    '[]',
    NULL, NULL,
    '[user_preference] JSON list of {symbol, reason, expires, todo}: symbols whose stored '
    'regime is all NULL for a diagnosed reason; regime_coverage_auditor stays green on these '
    'until the expires date (ISO), after which the entry fails the job again. A listed symbol '
    'that is no longer a gap warns and does not fail; a malformed list fails the job. '
    'Operator-visible switch, not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES (
    'alpha.regime.coverage_auditor.known_exceptions',
    '[
 {
  "symbol": "BIL",
  "reason": "Stored feature_vectors.regime is all NULL because of the pre-186-13 writer gate; on the 186-13 kernel (training-slice gate) it labels the trend family at 1d (class d, 4 segments written); 1h and 5m trend are degenerate, 15m trend is gated on every segment (near-flat price, todo 168 precedent). The 186-26 rebuild writes the 1d labels.",
  "expires": "2026-12-29",
  "todo": "341"
 },
 {
  "symbol": "EMLC",
  "reason": "Stored feature_vectors.regime is all NULL because of the pre-186-13 writer gate; on the 186-13 kernel (training-slice gate) it labels the trend family at 5m, 15m, 1h and 1d (class d). The 186-26 rebuild writes them.",
  "expires": "2026-12-29",
  "todo": "341"
 },
 {
  "symbol": "ETHA",
  "reason": "Stored feature_vectors.regime is all NULL because of the pre-186-13 writer gate; on the 186-13 kernel (training-slice gate) it labels the trend family at 5m and 1h (class d); 15m trend is degenerate and 1d is history short (501 observations against a 504 boundary). The 186-26 rebuild writes the 5m and 1h labels.",
  "expires": "2026-12-29",
  "todo": "341"
 },
 {
  "symbol": "IBIT",
  "reason": "Stored feature_vectors.regime is all NULL because of the pre-186-13 writer gate; on the 186-13 kernel (training-slice gate) it labels the trend family at 15m, 1h and 1d (class d); 5m trend is degenerate. The 186-26 rebuild writes them.",
  "expires": "2026-12-29",
  "todo": "341"
 },
 {
  "symbol": "VIXY",
  "reason": "Stored feature_vectors.regime is all NULL because of the pre-186-13 writer gate; on the 186-13 kernel (training-slice gate) it labels the trend family at 5m, 15m, 1h and 1d (class d). The 186-26 rebuild writes them.",
  "expires": "2026-12-29",
  "todo": "341"
 }
]',
    1
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), c.config_key, 1, c.config_value, 'migration_420',
       'Initial exceptions: BIL, EMLC, ETHA, IBIT, VIXY diagnosed by the 186-18 kernel sweep (todo 341), expire 2026-12-29'
FROM config_state c
WHERE c.config_key = 'alpha.regime.coverage_auditor.known_exceptions'
  AND NOT EXISTS (
    SELECT 1 FROM config_history h
    WHERE h.config_key = c.config_key AND h.changed_by = 'migration_420'
);

COMMIT;
