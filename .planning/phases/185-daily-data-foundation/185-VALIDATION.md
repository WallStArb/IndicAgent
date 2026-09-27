---
phase: 185
slug: daily-data-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-27
---

# Phase 185: validation strategy

Per-phase validation contract for feedback sampling during execution. Source: 185-RESEARCH.md "Validation architecture".

## Test infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest (asyncio-mode auto) |
| Config file | `pytest.ini` |
| Quick run command | `.venv/bin/pytest tests/unit/bars/ tests/unit/providers/test_ibkr_provider.py -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` (CI also runs ruff, black, vulture, mypy-baseline) |
| Estimated runtime | quick under 30 s; full suite a few minutes |

## Sampling rate

- After every task commit: the quick run command.
- After every plan wave: the full suite, plus the read-only integration checks for any migration applied.
- Before `/gsd-verify-work`: full suite green; `data_bar_check` passes for D-28; the D2b live check passes before phase 186 is told its precondition holds.
- Max feedback latency: 60 s for the quick command.

## Per-requirement verification map
| Req | Behavior | Test type | Automated command | File exists? |
|-----|----------|-----------|-------------------|-------------|
| D-10/D-13 | 45 dry-run CONFIRMED_CORRUPT rows flagged; 1,864 edge bars not flagged; the 15 existing 1d rows flagged | unit, fixture | `pytest tests/unit/bars/test_scrub_known_answers.py -x` | Wave 0 |
| D-11 | All 27 MARKET_EVENT rows (26 on 2010-05-06, EWW 2006-11-07) stay CONFIRMED_CORRUPT | unit | `pytest tests/unit/bars/test_corroboration_ceiling.py -x` | Wave 0 |
| D-08 | Each rule on synthetic cases (OHLC violation, zero price, stale run, volume spike, jump with and without a corporate action) | unit | `pytest tests/unit/bars/test_scrub_rules.py -x` | Wave 0 |
| D-14 | Ported flags agree with `forward_return_writer` semantics on fixtures (ceiling, window corroboration, gap-before never fires at 1d) | unit | `pytest tests/unit/bars/test_flag_parity.py -x` | Wave 0 |
| D-15 | Derived = direct 5m computation; no bucket spans a session; half day and both DST days; 1h volume sum = 1d volume; first open = 1d open | unit + one DB integration sample | `pytest tests/unit/bars/test_session_grid.py -x` | Wave 0 |
| D-15 | No symbol carries 1h rows at both :00 and :30 in one session after the switch | integration (DB, read-only query) | `pytest tests/integration/test_derived_grid_live.py -x` | Wave 0 |
| D-05 | Append-only triggers refuse UPDATE/DELETE/TRUNCATE; roles refuse cross-writes | migration contract + integration | `pytest tests/unit/test_ohlcv_observation_migration_contract.py -x` | Wave 0 |
| D-16/D-20 | Provider emits a request record per request (SMART, each venue, no-data, failure); venue bars reach `on_observation` with `store_bars` false | unit (fake IB) | `pytest tests/unit/providers/test_ibkr_provider.py -k request_record -x` | extend existing |
| D-24/D-21 | Seam detector finds synthetic 2:1, 1:8, 20:1 seams at the right date; no seam on MRNA/ALMS-shaped event series | unit | `pytest tests/unit/bars/test_seams.py -x` | Wave 0 |
| D-22 | D5 reading D1 reproduces the interim writer's events on stored fixtures (JPM, KO, XLU, NVR 2004 derives nothing) | unit | `pytest tests/unit/services/test_dividend_event_writer.py -x` | extend existing |
| D-23 | Disputed-date record marks spanning returns unknown | unit | `pytest tests/unit/bars/test_corporate_actions.py -x` | Wave 0 |
| D-06 | Single writer: no `INSERT INTO market_data_ohlcv` site outside the allow-list may write 1d/15m/1h | CI grep | `pytest tests/unit/test_market_data_ohlcv_writer_boundary.py -x` | Wave 0 |
| D-07 | Digest is stable under row order and changes when any value or flag changes | unit | `pytest tests/unit/bars/test_digest.py -x` | Wave 0 |
| D-04 | Labels on a synthetic panel (known truncation share, dividend-coverage share, scrub share, survivorship numbers) | unit | `pytest tests/unit/bars/test_labels.py -x` | Wave 0 |
| D-26 | Each audit check on fixtures, including the close tolerance and the nightly-skipped fact | unit | `pytest tests/unit/services/test_bar_reconciliation_audit.py -x` | Wave 0 |
| D-17 | Study statistics on synthetic venue data (volume share, close match) | unit | `pytest tests/unit/bars/test_venue_study.py -x` | Wave 0 |

Existing CI guards that constrain new code: `test_market_data_ohlcv_boundary.py` (new raw-table reads need an allow-list entry with a reason; the derivation and D7 need raw access and should be listed), `test_compressed_hypertable_write_boundary.py` (currently scoped to `feature_vectors`/`feature_ic_scores`; extend to `market_data_ohlcv` UPDATEs), `test_compressed_hypertable_migration_vacuum_check.py` (any migration doing decompress + recompress needs a bare `VACUUM`), `test_todo_priorities_link_integrity.py` (every new todo needs a PRIORITIES.md row), `test_service_auditor_registry_integrity.py` (new units registered in `_DAG_ORDER`/`_AGENT_ID_TO_UNIT` must exist as non-archived unit files), `test_ledger_sole_writer.py` (only S6 writes `research_run`).


Existing CI guards that constrain new code: `test_market_data_ohlcv_boundary.py`, `test_compressed_hypertable_write_boundary.py` (extend to `market_data_ohlcv` UPDATEs), `test_compressed_hypertable_migration_vacuum_check.py`, `test_todo_priorities_link_integrity.py`, `test_service_auditor_registry_integrity.py`, `test_ledger_sole_writer.py`.

## Wave 0 requirements
- [ ] `tests/fixtures/bars/` with the dry-run report, the 67 flagged rows, MRNA/ALMS windows, SPY 2025-11-28 and DST-day 5m samples
- [ ] `tests/unit/bars/` package and shared builders (synthetic bar series, fake calendar sessions)
- [ ] Scratch-hypertable measurement of insert/upsert/segment-delete rates (185-01)
- [ ] Framework install: none needed


## Manual-only verifications

| Behavior | Requirement | Why manual | Test instructions |
|----------|-------------|------------|-------------------|
| D3 study verdict (listing venue has most volume; only its closes match SMART) | D-17 | Needs live IBKR fetches and a judgment against pre-registered thresholds | Run the study script, compare the report to the thresholds committed before the fetch |
| IBKR fetch campaigns complete (381-name re-run, D1 bootstrap, seam audit) | D-27 | Live IBKR, multi-hour | Check `ohlcv_request` outcome counts against the expected request list |

## Validation sign-off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency under 60 s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
