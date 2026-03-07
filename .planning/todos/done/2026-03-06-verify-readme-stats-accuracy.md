# Verify README Stats Accuracy

**Created:** 2026-03-06

## Task

Double-check that all stats and counts in `README.md` are accurate against the actual codebase state.

## Items to Verify

- [ ] Plugin count (currently says 90) — cross-check against `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py`
- [ ] I2 plugin count (currently says 8) — confirm against tier list
- [ ] Service count (currently says 10 systemd services) — confirm against `services/` directory and systemd unit files
- [ ] `timeframes_builder_service` — confirm it exists and is wired
- [ ] `llm_writer_service` — confirm it exists and is wired
- [ ] Test count in CLAUDE.md (currently says 1182) — run `.venv/bin/pytest tests/unit/ --co -q | tail -1` to confirm
- [ ] Instrument count (24) — confirm against `get_active_contracts()` in `src/config/settings.py`
- [ ] Metrics ports listed are still correct

## Context

README was updated with bus-first framing on 2026-03-06 (commit `75e2b86`). Some numbers were updated based on recent work but not verified from source.
