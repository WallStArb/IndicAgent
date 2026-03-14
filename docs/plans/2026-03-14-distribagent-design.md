# DistribAgent — Signal Distribution Service Design

**Date:** 2026-03-14
**Status:** Design approved, pending implementation plan
**Scope:** Standalone Python service — separate repo from IndicAgent

---

## Overview

DistribAgent is a standalone signal distribution service that consumes IndicAgent's Redpanda streams and broadcasts high-conviction signals with AI narration to trading communities via pluggable platform adapters. It is not embedded in IndicAgent — it is a consumer of IndicAgent's public outputs only.

**Philosophy:** Built on Renaissance/Medallion principles. DistribAgent is not a broadcast pipe — it is a **measurement instrument disguised as a distribution service**. Every broadcast is a labeled training sample. Every trader reaction is a data point. The channel earns nothing it hasn't proven.

**v1 scope:**
- IRC adapter (irc.financialchat.com)
- Consumes `signals.aggregated` + `narratives` Redpanda topics
- Pre-broadcast quality gate (performance-gated, shadow mode)
- Outcome follow-up (closed-loop lifecycle reporting)
- Natural language query handling via Ollama
- Configurable per-channel filters
- SQLite broadcast log (measurement instrument)

**Out of scope for v1:** Discord adapter, proactive market commentary, learned community filters, web dashboard

**IndicAgent prerequisite:** A `GET /api/signals/performance` endpoint must be added to IndicAgent before DistribAgent can be built. This endpoint exposes `setup_performance` data (setup_plugin, win_rate, avg_pnl_r, sample_size) and is a hard dependency of the quality gate.

---

## Architecture

```
IndicAgent (Redpanda)
  signals.aggregated ──┐   ← new signals + terminal events (direction=0)
  narratives ──────────┤   ← I8 LLM narration per signal
                        ▼
              ┌──────────────────────┐
              │     DistribAgent     │
              │                     │
              │  Quality Gate       │  ← setup_performance API check, shadow mode
              │  Signal Buffer      │  ← pairs signal + narrative (5s window)
              │  Broadcast Log      │  ← SQLite: every broadcast + outcome + reactions
              │  Outcome Tracker    │  ← filters direction=0 events on signals.aggregated
              │  Agent Core (LLM)   │  ← NL queries + synthesis via Ollama
              │  Adapter Layer      │  ← BaseAdapter interface
              └──────────┬──────────┘
                         │
                   IRCAdapter (v1)
              irc.financialchat.com
                         │
                 DiscordAdapter (v2)
```

**Key design decisions:**
- Signal Buffer pairs each signal with its narrative before broadcasting (waits up to 5s — I8 narration is async and slightly delayed). If no narrative arrives within 5s, signal broadcasts with `narrative=None` — a placeholder line `"(narration unavailable)"` is shown instead of omitting the line.
- Ollama connection points at same instance IndicAgent uses — no new infrastructure
- Config is a single `config.yaml` — channels, filters, adapter credentials
- Each IRC channel can have independent filter settings
- SQLite for broadcast log — lightweight, no external DB dependency, portable
- On startup, Outcome Tracker reads SQLite for broadcasts with null `outcome_at` and reconstructs the pending set — restarts do not lose outcome follow-up responsibility

---

## Data Flow

### Signal Consumption

DistribAgent subscribes to **one** Redpanda topic for all signal events:

**`signals.aggregated`** — all signal events from signal_generator_service. Two event types distinguished by `direction` field:
- `direction != 0` → new signal event. Filtered by quality gate before broadcast.
- `direction == 0` → terminal event (signal resolved). Outcome Tracker processes these.

**CIS filter policy:** Only signals with `resolution_method = "cis"` are distributed. This is intentional policy — CIS-resolved signals represent genuine multi-bucket confluence. Other resolution methods (priority, majority, sole, regime_tiebreak) are not distributed in v1. This policy is explicit in config (`distribution_policy: cis_only`) and can be extended later.

**`narratives`** — I8 LLM narrative per signal. Payload schema:
```json
{
  "signal_id": "uuid",
  "symbol": "ES",
  "timeframe": "1m",
  "narrative": "ES broke above VWAP with institutional flow alignment...",
  "generated_at": "2026-03-14T09:15:03Z"
}
```
Matched to signals by `signal_id` in the Signal Buffer.

### Outcome Tracking

The Outcome Tracker maintains an in-memory set of `signal_id → (channel, broadcast_at)` for all signals broadcast in the current session. It also reconstructs this set from SQLite on startup (rows where `outcome_at IS NULL`).

When a `direction=0` event arrives on `signals.aggregated`, if its `signal_id` is in the pending set, the outcome is posted to the originating channel and the SQLite row is updated.

### Quality Gate API

DistribAgent calls `GET /api/signals/performance` on IndicAgent to retrieve per-setup win rates and sample sizes. Response schema:
```json
[
  {
    "setup_plugin": "trad_TrendFollowing",
    "win_rate": 0.67,
    "avg_pnl_r": 0.8,
    "sample_size": 84
  }
]
```
This response is cached with a 15-minute TTL. If the API is unreachable, the cache is used if fresh enough; otherwise shadow mode activates for all setups until connectivity is restored.

---

## Quality Gate

Every signal must pass all three gates before broadcast:

```
1. CIS gate:         abs(cis_score) >= min_cis_score (configurable, default 0.40)
                     AND resolution_method == "cis"
2. Performance gate: setup_performance entry exists AND:
                       - sample_size >= 30
                       - win_rate >= 0.52
                       - avg_pnl_r > 0.0
3. Shadow mode gate: No setup_performance entry (sample_size < 30) → shadow mode
```

**Shadow mode is stateless.** If `setup_performance` has no row for a `setup_plugin` (meaning fewer than 30 samples — IndicAgent only writes rows at 30+), the setup is in shadow mode automatically. No separate shadow state is stored. Once the row appears and passes thresholds, the setup graduates. The 15-min TTL cache means graduation lag is at most 15 minutes.

The shadow queue depth (`!shadow` command) is computed by checking which `setup_plugin` values have appeared in recent `signals.aggregated` events but have no `setup_performance` entry.

---

## Adapter Interface

```python
class BaseAdapter:
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def broadcast(self, packet: BroadcastPacket) -> None: ...
    async def broadcast_outcome(self, outcome: OutcomePacket) -> None: ...
    async def handle_command(self, user: str, channel: str, cmd: str, args: list[str]) -> str: ...
    async def send(self, channel: str, message: str) -> None: ...
```

New adapters drop a file in `adapters/`, register in `config.yaml`. No core changes required.

**IRC Rate Limiting:** IRCAdapter maintains a per-channel outbound queue with a 1.2s inter-message delay (safely below IRC flood limits). Multi-line signal broadcasts are queued as individual messages. If the queue backs up beyond 50 messages, oldest non-critical messages are dropped with a warning log.

**IRC Authentication:** NickServ/SASL credentials are configured in the `auth` block. The adapter attempts SASL PLAIN first (if configured), falls back to NickServ IDENTIFY after connect. Nick collision is handled by appending `_` until a free nick is found, then attempting to regain the configured nick via NickServ GHOST.

---

## BroadcastPacket

```python
@dataclass
class BroadcastPacket:
    signal_id: str
    symbol: str
    timeframe: str
    direction: int          # +1 long / -1 short
    entry_price: float
    stop_loss: float
    targets: list[float]
    confidence: float
    cis_score: float
    bucket_scores: dict     # {"trend": 0.4, "momentum": 0.3, ...}
    setup_plugin: str
    win_rate: float         # from setup_performance
    sample_size: int
    avg_pnl_r: float
    narrative: str | None   # from I8; None if 5s window expired
    timestamp: datetime

@dataclass
class OutcomePacket:
    signal_id: str
    symbol: str
    timeframe: str
    direction: int
    entry_price: float
    outcome: str            # "target_1", "target_full", "stopped_in_trade", etc.
    pnl_r: float
    mae: float
    mfe: float
    bars_in_trade: int
    broadcast_channel: str
    broadcast_at: datetime
```

---

## Broadcast Format

### Signal Entry
```
[ES 1m ▲ LONG] 5423.50 → SL 5418.00 | T1 5433 T2 5440
CIS 0.61 | trend ▲ momentum ▲ structure ▲ institutional ▲ pattern ○ regime ▲
"ES broke above VWAP with institutional flow alignment — 4th test of overnight high"
Setup: TrendFollowing | Win rate: 67% (n=84) | Avg R: +0.8
```

The `▲▲▲▲○▲` bucket display gives traders an instant visual read of confluence depth. If narrative is absent: `"(narration unavailable)"` on line 3.

### Outcome Follow-up (automatic)
```
[ES 1m LONG CLOSED] +1.2R — target_1 hit (47 bars)
Signal from 09:15 | Entry 5423.50 → Exit 5433.00
TrendFollowing: 68% / 85 trades (live updated)
```

---

## Agentic Layer

### Hard Commands
```
!signals [symbol] [tf]     → recent signals with win rates
!status                    → pipeline health, last signal time, shadow queue depth
!explain <signal_id>       → CIS bucket breakdown in plain English (from SQLite bucket_scores)
!performance [setup]       → win rate, avg R, sample size for a setup type
!shadow                    → setups in shadow mode + samples needed to graduate
```

`!explain` reads `bucket_scores` from the `broadcasts` SQLite table (stored as JSON). No IndicAgent API call required.

### Natural Language (via Ollama)
The Agent Core detects non-command messages that address the bot and synthesizes a response from live intelligence data pulled via IndicAgent API.

```
<trader> what's ES doing right now?
<bot> ES 1m showing bullish CIS 0.61 — trend, momentum, structure, and
      institutional all aligned. Last signal 3m ago, pending activation.
      Regime: trending. No conflicting signals on 5m or 15m.
```

Context passed to LLM: current signals, regime classification, active CIS scores, recent outcomes. Response is capped at 3 IRC lines to avoid flooding.

---

## Broadcast Log (SQLite)

```sql
CREATE TABLE broadcasts (
    signal_id     TEXT PRIMARY KEY,
    symbol        TEXT,
    timeframe     TEXT,
    setup_plugin  TEXT,
    direction     INTEGER,
    cis_score     REAL,
    bucket_scores TEXT,   -- JSON: {"trend": 0.4, "momentum": 0.3, ...}
    win_rate      REAL,
    channel       TEXT,
    broadcast_at  TEXT,
    outcome       TEXT,   -- NULL until resolved
    pnl_r         REAL,
    outcome_at    TEXT,   -- NULL until resolved
    narrative     TEXT
);

CREATE TABLE reactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    channel       TEXT,
    user          TEXT,
    message       TEXT,
    timestamp     TEXT,
    signal_id     TEXT   -- NULL if not linked to a specific signal
);

CREATE TABLE shadow_log (
    signal_id     TEXT PRIMARY KEY,
    symbol        TEXT,
    timeframe     TEXT,
    setup_plugin  TEXT,
    cis_score     REAL,
    bucket_scores TEXT,  -- JSON
    logged_at     TEXT,
    would_have_outcome TEXT,  -- back-filled when terminal event arrives
    would_have_pnl_r   REAL
);
```

The `reactions` table captures all channel messages alongside broadcast timestamps — over time this reveals which signal types generate discussion, skepticism, or follow-on queries.

On startup: `SELECT signal_id, channel, broadcast_at FROM broadcasts WHERE outcome_at IS NULL` reconstructs the Outcome Tracker's pending set.

---

## Configuration

```yaml
indicagent:
  kafka_bootstrap: "localhost:19092"
  api_base_url: "http://localhost:8000"
  env_prefix: "production"

ollama:
  base_url: "http://localhost:11434"
  model: "qwen3.5:9b"

filters:
  min_cis_score: 0.40
  min_win_rate: 0.52
  min_sample_size: 30
  distribution_policy: "cis_only"   # only resolution_method="cis" signals distributed

adapters:
  irc:
    enabled: true
    host: "irc.financialchat.com"
    port: 6697
    ssl: true
    nick: "SignalBot"
    auth:
      sasl_plain:
        username: "SignalBot"
        password: ""         # set via env: DISTRIBAGENT_IRC_SASL_PASSWORD
      nickserv_identify:
        password: ""         # fallback: set via env: DISTRIBAGENT_IRC_NS_PASSWORD
    rate_limit:
      messages_per_second: 0.83   # 1 message per 1.2s
      queue_max: 50
    channels:
      "#es-signals":
        symbols: ["ES", "NQ"]
        timeframes: ["1m", "5m"]
        min_cis_score: 0.45
      "#all-signals":
        symbols: null    # all instruments
        timeframes: null # all timeframes
        min_cis_score: 0.40
```

Secrets are never stored in `config.yaml` — all passwords read from environment variables at startup.

---

## Repo Structure

```
distribagent/
  adapters/
    base.py           # BaseAdapter interface + BroadcastPacket / OutcomePacket
    irc.py            # IRCAdapter (v1) with rate limiter + auth
    discord.py        # DiscordAdapter (v2, stub)
  core/
    stream_reader.py  # Redpanda consumer (signals.aggregated + narratives)
    signal_buffer.py  # signal + narrative pairing (5s window)
    quality_gate.py   # CIS + performance + shadow mode checks + 15min cache
    outcome_tracker.py # pending signal set + SQLite recovery on startup
    agent.py          # LLM synthesis + command dispatch
  db/
    broadcast_log.py  # SQLite operations
    schema.sql
  config.py           # pydantic-settings config loader
  main.py             # asyncio entrypoint
  config.yaml.example
  pyproject.toml
  README.md
```

---

## Renaissance Quality Principles

1. **Earn distribution rights through proof** — no setup type broadcasts without 30+ samples and positive expectancy. Shadow mode is mandatory for new setups.
2. **Close the loop** — every broadcast is followed by an outcome. Traders see P&L, not just entries. Outcome Tracker survives restarts.
3. **The channel is a measurement instrument** — all reactions logged, query patterns analyzed.
4. **Never distribute noise** — 2 high-conviction signals beat 30 mediocre ones. Quality gate is non-negotiable.
5. **Degrade gracefully** — if IndicAgent API is unreachable, shadow mode activates automatically. No stale performance data reaches the channel.
6. **Transparent shadow queue** — `!shadow` shows what's being validated. Traders understand the system's standards.
7. **Secrets out of config** — all credentials in environment variables, never committed.

---

## Testing Strategy

- Unit tests for quality gate logic (all threshold combinations, API-unreachable path)
- Unit tests for signal buffer (pairing, 5s timeout with/without narrative, narrative-absent broadcast)
- Unit tests for broadcast formatting (all outcome types, direction symbols, bucket display)
- Unit tests for command parsing and response generation
- Unit tests for outcome tracker (startup recovery from SQLite, terminal event processing)
- Integration tests against a test Redpanda topic with fixture signals
- IRC adapter tested against mock socket (rate limiter, auth sequence, nick collision)
- SQLite log tested with fixture broadcasts + outcome updates

---

## IndicAgent Prerequisites

Before DistribAgent can be built, IndicAgent needs one addition:

**`GET /api/signals/performance`** — returns current `setup_performance` rows:
```json
[
  {
    "setup_plugin": "trad_TrendFollowing",
    "win_rate": 0.67,
    "avg_pnl_r": 0.8,
    "sample_size": 84
  }
]
```
This is a simple SELECT on the existing `setup_performance` table. Add to `src/api/routes/signals.py`.

---

## v2 Roadmap

- Discord adapter
- Proactive market commentary (regime shift announcements, unusual CIS spikes across instruments)
- Community feedback analysis (which signals generate most discussion, query patterns by time of day)
- Performance leaderboard (`!leaderboard` — top performing setup types by R)
- Multi-network IRC support
- Shadow mode leaderboard (what's closest to graduating)
