# Dashboard Gotchas

Developer reference for common pitfalls and non-obvious patterns in the Next.js dashboard.

## Re-render Optimization

**1s re-render tick:** `signal-card.tsx` calls `setInterval(1s)` via `useFormattedTimestamp` — any derived values (formatted strings, timestamps) must use `useMemo` to avoid per-second recomputation.

**`format.ts` timing utils:**
- `fmtTimeHMS(iso)` → `HH:MM:SS` or null (guards invalid dates)
- `fmtLagSeconds(lagS)` → `"+1.2s"` or null (guards NaN)

## SSE (Server-Sent Events)

**Broadcaster `_latest` rebuild:** `KafkaSSEBroadcaster` uses stable `group_id="sse_broadcaster"` + `seek_to_beginning()` on startup so all topic history replays on each API restart, fully populating the snapshot cache. If dashboard shows "-" after an API restart, restart the API again — the broadcaster needs ~5s to replay.

**`intelligence_i7` SSE domain:** `intelligence_i7:SYMBOL:TF` stream is subscribed in `_build_stream_list()` (alongside `intelligence:`); event name is `signal_scorecard`. Check must appear before `intelligence:` startswith check to prevent shadowing.

**`signal_scorecard` event payload:** `{"ts": "...", "symbol": "ES", "tf": "1m", "data": "[{...}]"}` where `data` is a JSON-encoded string of `RankedSignal[]`. Parse with `JSON.parse(String(payload.data || "[]"))`.

**`GET /api/signals/recent`:** `?symbol=&timeframe=&limit=` — returns `signal_ledger` rows with `setup_performance` LEFT JOIN, ordered by `computed_at DESC`. Drill panel fetches on mount and merges with SSE history deduplicated by `signal_id` (SSE version wins on conflict).

**SSE `Cache-Control` / `X-Accel-Buffering`:** `sse_events` StreamingResponse includes `Cache-Control: no-cache` and `X-Accel-Buffering: no` headers — prevents reverse proxies (nginx, CF) from buffering the stream.

## Layout & UI

**Dashboard layout modes:** `trading-dashboard.tsx` has two modes — `"focus"` (left `WatchlistRail` + single `SymbolCard`) and `"grid"` (`GroupedSymbolGrid` grouped by sector). Auto-switches to focus when profile > 12 instruments. Toggle in header.

**Skeleton cards:** `SkeletonCard` renders a shimmer placeholder while `symbolData[sym]` is null on page load/SSE reconnect. Prevents blank card flash.

**Signal alert strip:** `SignalAlertStrip` renders above content when any instrument has a signal ≥ 0.65 confidence. Scans all TFs per symbol; deduplicates to one pill per symbol (highest confidence).

## Configuration

**`symbol-config.ts` `loadConfig()`:** Fetches all asset classes from `/api/instruments` (not just `futures`). ETFs have `asset_class: "equity"` in the DB. `SymbolInfo.sector` is `string` (not a union) to accommodate all ETF sectors.

**`getApiBase()` runtime detection** (`src/lib/api.ts`): Returns the correct API base URL at runtime based on `window.location.hostname`. LAN/localhost → `http://<hostname>:8000`; any other host → `https://api.indicagent.com`. Use this instead of `NEXT_PUBLIC_API_BASE_URL` so both direct LAN access and CloudFlare tunnel work without config changes. `NEXT_PUBLIC_API_BASE_URL` still overrides if set.

**`allowedDevOrigins` (Next.js dev):** Next.js 16+ blocks cross-origin `/_next/*` HMR requests by default — causes full page reload every ~30-80s when accessing dev server from a non-localhost host. Fix: add all access origins (local IP, CF domains) to `allowedDevOrigins` in `next.config.ts`. Current: `["dash.indicagent.com", "www.indicagent.com", "192.168.1.158"]`.
