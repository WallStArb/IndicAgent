# Guides — Task-Oriented How-Tos

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-27

Step-by-step guides for common development and operational tasks.

---

## Guides

**[Running Services](running-services.md)**
Full service DAG (L1–L10), systemd management, observability, direct invocation

**[Database Management](database-management.md)**
TimescaleDB migrations, backfill, gap-fill, compression, vacuum, backups

---

## Related

- **Adding plugins:** See `src/intelligence/ai/AUTHORING.md` (canonical) and `docs/concepts/plugin-architecture.md`
- **Testing:** `pytest tests/unit/ -v` · `pytest tests/integration/ -v` · see `pytest.ini` for config
- **Monitoring/debugging:** [Cheatsheet](../cheatsheet.md) · [Operations Reference](../operations/infrastructure-reference.md) · [Gotchas](../gotchas.md)
- **Dashboard development:** `cd dashboard && npm run dev` · components in `dashboard/src/components/`

---

**Back to:** [Documentation Home](../README.md)
