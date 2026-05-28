<!-- generated-by: gsd-doc-writer -->
# Server-Sent Events Protocol

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-27

Real-time streaming API served by the FastAPI backend on `:8000`.

---

## Stream Keys

See [Stream Schemas](../schemas/stream-schemas.md) for data formats.

Topics are built via `src/core/stream_keys.py` with dot-separated names and optional `INDICAGENT_ENV` prefix:

```
{env}.market.bars                    # canonical 1m OHLCV bars
{env}.market.bars.htf                # HTF bars (5m, 15m, 1h, 4h, 1d)
{env}.intelligence.journal           # full IntelligenceEvent per bar (I1-I7 JSONB)
{env}.intelligence.i7.signals        # ranked I7 signals per bar
{env}.lifecycle.transitions          # signal lifecycle state changes
{env}.llm.calls                      # LLM audit log entries
```

---

[TODO: Document SSE connection, message format, examples]

---

**Guide:** [Dashboard Development](../../guides/dashboard-development.md)
