---
status: pending
priority: P1
filed: 2026-11-14
source: lead audit 2026-11-14 (read-only worker, claims 1 and 2 re-verified at source by the lead), executed under the owner's standing licence to rewrite
---

# Refactor audit 2026-11-14: ranked candidates

## What

Seventeen candidates, ranked by how much each shortens the path to a counted test or protects one. Guards: the rebuild code key (`unit_code_key`), `repro_frozen`, timers, the step 7 window. Execute in the order below; each landing gets /simplify, /review and the SOP gates.

| # | Candidate | Action | Earliest time |
|---|---|---|---|
| 1 | The rebuild code key never hashes `src/intelligence/feature_factory.py`, though `services/backfill_feature_factory.py` imports four input builders from it (a logic edit there changes features without changing the key) | LANDED 2026-11-14: builders in `features/external_inputs.py`, `FeatureFactoryConfig` in `features/feature_factory_config.py`; the writer line of the key is now the import closure of the writer itself (a new import is hashed by default), with a reviewed `WRITER_UNHASHED_IMPORTS` map of seven imports that cannot change a value registering by name; guarded by `test_every_runtime_import_of_the_writer_is_hashed_or_reviewed`. Open: `ic_measure` keys its own module the same unfollowed `own` way (its `_batch_utils`, `canonical_json`, `corpus_manifest`, `settings`, `otel` imports are unhashed); same fix | done for the rebuild key |
| 2 | `services/corpus_rerun_data_gate.py` `_survivorship_caveat` takes its era from `primary_pair(VENDOR_IBKR, ...)`; after step 7 every count is 0 and the text blames IBKR | derive the pre-era from the policy in force; restate the cause (today's universe) | landed 2026-11-14: caveat code `survivorship_pre_alpaca_era_5m`, pre-era read from the segments the 5m policy yields |
| 3 | 1d scrub failure is never retried: digests are written after a failed `scrub_symbols`, and the `--changed-only` baseline ignores batch status (`bar_derivation.py` 1594-1613, 541-549) | skip digests on scrub failure; require `status = 'success'` in the baseline | after step 7 |
| 4 | Local `vulture` exits 3 (255 findings) while CI runs bare `vulture` | confirm CI state, delete the truly dead code, whitelist dispatch-by-name methods | now outside step 7 modules |
| 5 | Futures-only chain is dead and `macro_analyzer` persists its own output (DAG invariant 3); `flight_to_quality` turns missing into 0.0 | delete the chain (macro, cross-asset, roll units, `_DAG_ORDER` entries); keep the `roll_events` table | now (restart `service_auditor` after) |
| 6 | Dead v2.x classes in `schemas.py` (inside the rebuild key) | LANDED 2026-11-14 with 1: dead classes deleted (`FEATURE_SCHEMA_VERSION` kept, `IntelligenceEvent` reads it); `FeatureVector` and `FeatureVectorRecord` in `features/feature_vector.py`, so `schemas.py` left the rebuild key | done |
| 7 | `services/bar_writer.py` writes 1m to canonical bypassing raw (breaks law 528) | route through the raw ingress or delete with the streaming path | now; landed 2026-11-14: deleted with its unit, tests, auditor entries and the bar.writer.dlq topic (installed copy at /etc/systemd/system left for the lead) |
| 8 | Streaming `FeatureFactory` maps non-finite to 0.0 (66 `_guard(` calls; breaks `no_fill`) | LANDED 2026-11-14 with 1: `_guard` deleted, every call is `_missing_if_nan`, `_guard_counted` returns None; kernel parity goldens regenerated (only fallback values became NaN, reason in the manifest). Open in the same dormant path: `_cold_start_vector` literals, `_series_last(arr, fallback)` and inline `else 0.0`/`else 1.0` reads in `compute_batch`; streaming maps inf to None where the rebuild keeps inf | partly done |
| 9 | `ops_seam_witness.py` re-derives the 1d session zone inline | use `daily_rule.raw_session_date` | after step 7 |
| 10 | `_batch_utils.py` sync and async twins (write session, job restore, headroom, table probe) | one pure plan, two thin drivers; then split the file | after step 7 |
| 11 | 53 direct DB connects; no single factory; `::date` calls rely on the server timezone | one Ring 0 connect that sets `timezone=UTC` | after step 7 |
| 12 | Real APR migrations: `service_auditor` escalation window, count, stall threshold, Prometheus URL; `backfill_feature_factory` fetch calendar slack days; dormant `bar_auditor` constants | APR keys, or delete with the dormant path; the slack key part closed 2026-11-14 by deletion, not APR: `unit_fetch_start` and `bars_to_fetch_window` had no runtime caller (the writer always computes from the series start) | now (service_auditor and bar_auditor parts open) |
| 13 | `_BP = 1e4` duplicates `vendor_basis.BP`; two basis-point formulas (`log(a/b)` vs `abs(a/b-1)`) | one `bp_deviation` in `vendor_basis` | after step 7 |
| 14 | `combiner.py:451,497` `except LinAlgError: continue` drops a fold silently | validate penalty > 0 in the spec and raise, or count skipped folds | landed 2026-11-14: every recorded ridge penalty is 1.0 (book_v1.yaml, e17 certificate); `RidgeSpec` requires penalty > 0 and the two `LinAlgError` fold skips are removed (a singular solve now raises); `repro_frozen` bit-identical. Open: the `isfinite(b)` skip below the solve is unreachable short of float overflow |
| 15 | Manual timer quiesce in the rerun and step 7 (A10/D5) | `corpus_rerun --quiesce` and `--release` | landed 2026-11-14 (`services/corpus_rerun_quiesce.py`); acts on the APR `blocking_timers` list only, so the step 7 A10 list (daily, grid, audit, dividend, regime, nightly timers and the compression auditor service) needs those units in that key before the step 7 window |
| 16 | Oversized modules (`feature_factory`, `backfill_feature_factory`, `kernels/price`, `_batch_utils`, `bar_derivation`, `bar_reconciliation_audit`, `runner`) | split by responsibility, per the order and guards in the audit | per file: after step 7, or after 584 |
| 17 | The archive last-file-day rule exists twice: `ops_massive_policy_plan.archive_end_of` and `massive_reference_capture.last_file_day` | one helper beside `MASSIVE_MANIFEST` in `vendor_ingress.py` (both are step 7 or nightly imports); keep `ArchiveManifestError(ValueError)` with the same message | after step 7 |

Dead helpers with no callers (delete with their tests): `ic_math.scale_max_abs_return`, `daily_rule.basis_closes`, `daily_rule.current_closes`, `bar_scrub.load_scrub_params`, `ops_selection_gate.utc_date`, and the tests-only set (`ic_math` walk-forward and magnitude helpers, `term_structure_lag.lag_*`, `contribution.shapley_sampled`, `leave_one_out`, `AsyncRequestSink`, `align_causality_probe`). Swallowed errors, broad excepts and APR constants not listed above were checked and are correct or exempt.

## Done when

Each row is landed, or struck with a reason; the table is updated on each landing.
