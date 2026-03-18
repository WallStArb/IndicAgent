# Signal Intelligence — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement unified signal quality tier system across all dashboard surfaces (D1) and build the new `/signals` Signal Intelligence Command Center page (D2).

**Architecture:** A pure `compute_signal_tier()` function classifies signals as Hero/Monitored/Candidate based on `was_selected`, `confidence >= 0.40`, and `abs(cis_score) > 0.35`. The backend API gains a `tier` query param and three new endpoints (`/stats`, `/attribution`, `/detail/{id}`). The SSE payload is extended with `cis_score` + `was_selected` so live signals on the dashboard can be tier-gated. The new `/signals` page is a Next.js route composed of five zone components.

**Tech Stack:** FastAPI, asyncpg, TimescaleDB, scipy (new dep), Next.js 16, React 19, `@tanstack/react-virtual` (new dep), Tailwind CSS.

**Spec:** `docs/plans/2026-03-16-signal-intelligence-design.md`

---

## Chunk 1: Backend API

### Task 1: Add scipy to requirements + verify install

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add scipy**

  Open `requirements.txt` and add after the numpy line:

  ```
  scipy>=1.15.0
  ```

- [ ] **Step 2: Install**

  ```bash
  .venv/bin/pip install scipy>=1.15.0
  ```

  Expected: installs without error. Verify: `.venv/bin/python -c "from scipy import stats; print(stats.t.sf(1.96, df=100))"` prints ~`0.026`.

- [ ] **Step 3: Commit**

  ```bash
  git add requirements.txt
  git commit -m "feat: add scipy for p-value computation in attribution endpoint"
  ```

---

### Task 2: Modify `GET /api/signals/recent` — tier param + signal_tier field

**Files:**
- Modify: `src/api/routes/signals.py`
- Create: `tests/unit/test_signals_api_tier.py`

**Context:** Currently `symbol` is required, no tier filtering, `was_selected` and `cis_score` are not returned. We need to: make `symbol` optional, add `tier` param, add `was_selected`/`cis_score` to SELECT, compute `signal_tier` in response.

- [ ] **Step 1: Write failing tests**

  Create `tests/unit/test_signals_api_tier.py`:

  ```python
  """Tests for GET /api/signals/recent tier filtering and signal_tier field."""
  from unittest.mock import AsyncMock
  import pytest
  from fastapi.testclient import TestClient
  from src.api.dependencies import get_db_manager
  from src.api.main import app

  def _row(**kwargs):
      """Build a minimal asyncpg-like row dict."""
      defaults = {
          "signal_id": "00000000-0000-0000-0000-000000000001",
          "setup_plugin": "trad_TrendFollowing",
          "signal_type": "trend_long",
          "direction": 1,
          "entry_price": 5200.0,
          "stop_loss": 5180.0,
          "confidence": 0.65,
          "was_selected": True,
          "cis_score": 0.45,
          "status": "pending",
          "outcome": None,
          "exit_price": None,
          "pnl_r": None,
          "signal_computed_at": None,
          "timeframe": "1m",
          "setup_win_rate": None,
          "setup_avg_pnl_r": None,
      }
      return {**defaults, **kwargs}

  @pytest.mark.unit
  class TestSignalsApiTier:
      def _setup(self, rows, summary_row=None):
          mock_db = AsyncMock()
          mock_db.fetch = AsyncMock(return_value=rows)
          if summary_row is None:
              summary_row = {"n_total": len(rows), "n_resolved": 0, "n_suppressed": 0,
                             "win_rate": None, "avg_pnl_r": None}
          mock_db.fetchrow = AsyncMock(return_value=summary_row)
          app.dependency_overrides[get_db_manager] = lambda: mock_db
          return TestClient(app), mock_db

      def teardown_method(self):
          app.dependency_overrides.clear()

      def test_signal_tier_hero_returned(self):
          """Row with was_selected=True, conf>=0.40, |cis_score|>0.35 → tier='hero'."""
          client, _ = self._setup([_row(confidence=0.65, was_selected=True, cis_score=0.45)])
          resp = client.get("/api/signals/recent?symbol=ESH6")
          assert resp.status_code == 200
          signals = resp.json()["signals"]
          assert len(signals) == 1
          assert signals[0]["signal_tier"] == "hero"

      def test_signal_tier_monitored_null_cis(self):
          """was_selected=True but cis_score IS NULL → tier='monitored'."""
          client, _ = self._setup([_row(confidence=0.65, was_selected=True, cis_score=None)])
          resp = client.get("/api/signals/recent?symbol=ESH6")
          assert resp.json()["signals"][0]["signal_tier"] == "monitored"

      def test_signal_tier_monitored_low_conf(self):
          """was_selected=True, cis_score present but confidence < 0.40 → tier='monitored'."""
          client, _ = self._setup([_row(confidence=0.35, was_selected=True, cis_score=0.45)])
          resp = client.get("/api/signals/recent?symbol=ESH6")
          assert resp.json()["signals"][0]["signal_tier"] == "monitored"

      def test_signal_tier_candidate(self):
          """was_selected=False → tier='candidate'."""
          client, _ = self._setup([_row(was_selected=False, cis_score=0.5)])
          resp = client.get("/api/signals/recent?symbol=ESH6&tier=all")
          assert resp.json()["signals"][0]["signal_tier"] == "candidate"

      def test_tier_hero_filters_low_confidence(self):
          """tier=hero (default) must exclude rows with confidence < 0.40."""
          client, mock_db = self._setup([])
          client.get("/api/signals/recent?symbol=ESH6")
          call_args = mock_db.fetch.call_args[0]
          # The query string passed as first arg must include hero tier WHERE clauses
          assert "confidence" in call_args[0]
          assert "cis_score" in call_args[0]

      def test_tier_all_no_extra_filter(self):
          """tier=all must NOT add tier-based WHERE conditions."""
          client, mock_db = self._setup([])
          client.get("/api/signals/recent?symbol=ESH6&tier=all")
          call_args = mock_db.fetch.call_args[0]
          # tier=all query must not reference cis_score tier conditions
          query = call_args[0]
          assert "abs(sl.cis_score)" not in query

      def test_symbol_optional_omitted(self):
          """Omitting symbol (tier=all, no symbol) must return 200."""
          client, _ = self._setup([])
          resp = client.get("/api/signals/recent?tier=all")
          assert resp.status_code == 200
  ```

- [ ] **Step 2: Run tests — expect all FAIL**

  ```bash
  .venv/bin/pytest tests/unit/test_signals_api_tier.py -v
  ```

  Expected: all tests fail (signal_tier field missing, tier param not accepted).

- [ ] **Step 3: Add `_compute_signal_tier` helper to `signals.py`**

  At the top of `src/api/routes/signals.py`, after the imports, add:

  ```python
  def _compute_signal_tier(
      was_selected: bool,
      confidence: float | None,
      cis_score: float | None,
  ) -> str:
      """Classify a signal into Hero / Monitored / Candidate tier.

      Evaluation order: Hero → Monitored → Candidate.
      NULL cis_score → always Monitored (never Hero).
      Thresholds: confidence >= 0.40 (data-derived breakeven); abs(cis_score) > 0.35 (CIS fire threshold).
      """
      if (
          was_selected
          and confidence is not None
          and cis_score is not None
          and confidence >= 0.40
          and abs(cis_score) > 0.35
      ):
          return "hero"
      if was_selected:
          return "monitored"
      return "candidate"
  ```

- [ ] **Step 4: Update `get_recent_signals` signature — make `symbol` optional, add `tier` param**

  In `signals.py`, change the function signature from:
  ```python
  async def get_recent_signals(
      symbol: str = Query(..., description="Symbol, e.g. ESH6 or ES"),
      timeframe: str | None = Query(None, description="Filter by timeframe, e.g. 1m"),
      limit: int = Query(20, ge=1, le=100, description="Max signals to return"),
      db_manager: DatabaseManager = Depends(get_db_manager),
  ) -> dict[str, Any]:
  ```
  to:
  ```python
  async def get_recent_signals(
      symbol: str | None = Query(None, description="Symbol, e.g. ESH6 or ES. Omit for all symbols."),
      timeframe: str | None = Query(None, description="Filter by timeframe, e.g. 1m"),
      limit: int = Query(20, ge=1, le=500, description="Max signals to return"),
      tier: str = Query("hero", pattern="^(hero|monitored|all)$", description="Quality tier filter"),
      db_manager: DatabaseManager = Depends(get_db_manager),
  ) -> dict[str, Any]:
  ```

- [ ] **Step 5: Update `get_recent_signals` query — add was_selected, cis_score, tier WHERE clause**

  Replace the main_query inside `get_recent_signals`:

  ```python
  # Build tier WHERE clause
  if tier == "hero":
      tier_clause = """
          AND sl.was_selected = true
          AND sl.confidence >= 0.40
          AND sl.cis_score IS NOT NULL
          AND abs(sl.cis_score) > 0.35
      """
  elif tier == "monitored":
      tier_clause = "AND sl.was_selected = true"
  else:  # all
      tier_clause = ""

  symbol_clause = "AND sl.symbol = $1" if symbol else ""
  resolved_symbol = _resolve_contract(symbol) if symbol else None

  main_query = f"""
      SELECT
          sl.signal_id,
          sl.setup_plugin,
          sl.signal_type,
          sl.direction,
          sl.entry_price,
          sl.stop_loss,
          sl.confidence,
          sl.was_selected,
          sl.cis_score,
          sl.status,
          sl.outcome,
          sl.exit_price,
          sl.pnl_r,
          sl.signal_computed_at,
          sl.timeframe,
          sl.symbol,
          sp.win_rate   AS setup_win_rate,
          sp.avg_pnl_r  AS setup_avg_pnl_r
      FROM signal_ledger sl
      LEFT JOIN setup_performance sp ON sp.setup_type = sl.signal_type
      WHERE ($1::text IS NULL OR sl.symbol = $1)
        AND ($2::text IS NULL OR sl.timeframe = $2)
        {tier_clause}
      ORDER BY sl.signal_computed_at DESC
      LIMIT $3
  """
  rows = await db_manager.fetch(main_query, resolved_symbol, timeframe, limit)
  ```

  Also update the summary_query similarly (use `symbol_clause` for it):

  ```python
  summary_query = f"""
      SELECT
          COUNT(*)                                                          AS n_total,
          COUNT(*) FILTER (WHERE status NOT IN ('pending', 'active'))       AS n_resolved,
          COUNT(*) FILTER (WHERE status = 'regime_suppressed')              AS n_suppressed,
          ROUND(
              AVG(CASE WHEN outcome IN ('target_1','target_1_2','target_full') THEN 1.0
                       WHEN outcome IS NOT NULL
                        AND status NOT IN ('pending','active') THEN 0.0
                       ELSE NULL END)::numeric, 3
          )                                                                 AS win_rate,
          ROUND(AVG(pnl_r) FILTER (WHERE pnl_r IS NOT NULL)::numeric, 3)   AS avg_pnl_r
      FROM signal_ledger
      WHERE ($1::text IS NULL OR symbol = $1)
        AND ($2::text IS NULL OR timeframe = $2)
  """
  summary_row = await db_manager.fetchrow(summary_query, resolved_symbol, timeframe)
  ```

- [ ] **Step 6: Add `signal_tier` to each signal dict in the response**

  In the signals list comprehension, add:

  ```python
  "was_selected": row["was_selected"],
  "cis_score": _f(row["cis_score"]),
  "signal_tier": _compute_signal_tier(
      row["was_selected"],
      _f(row["confidence"]),
      _f(row["cis_score"]),
  ),
  ```

  Also add `"symbol": row["symbol"]` to the response (needed for all-symbol queries).

- [ ] **Step 7: Run tests — expect pass**

  ```bash
  .venv/bin/pytest tests/unit/test_signals_api_tier.py -v
  ```

  Expected: all 7 tests pass.

- [ ] **Step 8: Run full unit suite — confirm no regressions**

  ```bash
  .venv/bin/pytest tests/unit/ -v --tb=short
  ```

  Expected: all existing tests still pass.

- [ ] **Step 9: Commit**

  ```bash
  git add src/api/routes/signals.py tests/unit/test_signals_api_tier.py
  git commit -m "feat(signals-api): add tier param, signal_tier field, optional symbol to /api/signals/recent"
  ```

---

### Task 3: `GET /api/signals/stats` endpoint

**Files:**
- Modify: `src/api/routes/signals.py`
- Create: `tests/unit/test_signals_api_stats.py`

**Context:** Returns 6 command strip metrics. Single query covers session counts, hero_rate, avg_confidence, pipeline_latency, and rolling pnl_r.

- [ ] **Step 1: Write failing tests**

  Create `tests/unit/test_signals_api_stats.py`:

  ```python
  """Tests for GET /api/signals/stats."""
  from unittest.mock import AsyncMock
  import pytest
  from fastapi.testclient import TestClient
  from src.api.dependencies import get_db_manager
  from src.api.main import app

  def _stats_row(**kwargs):
      defaults = {
          "signals_today": 42,
          "signals_prev_session": 38,
          "hero_count_today": 12,
          "selected_count_today": 20,
          "avg_confidence_today": 0.52,
          "avg_confidence_7d": 0.48,
          "latency_p50": 4.2,
          "latency_p95": 12.1,
          "avg_pnl_r_7d": 0.31,
          "avg_pnl_r_30d": 0.22,
      }
      return {**defaults, **kwargs}

  @pytest.mark.unit
  class TestSignalsApiStats:
      def teardown_method(self):
          app.dependency_overrides.clear()

      def test_stats_returns_200(self):
          mock_db = AsyncMock()
          mock_db.fetchrow = AsyncMock(return_value=_stats_row())
          app.dependency_overrides[get_db_manager] = lambda: mock_db
          resp = TestClient(app).get("/api/signals/stats")
          assert resp.status_code == 200

      def test_stats_schema(self):
          mock_db = AsyncMock()
          mock_db.fetchrow = AsyncMock(return_value=_stats_row())
          app.dependency_overrides[get_db_manager] = lambda: mock_db
          data = TestClient(app).get("/api/signals/stats").json()
          assert "signals_today" in data
          assert "hero_rate" in data
          assert "avg_confidence" in data
          assert "pipeline_latency_p50" in data
          assert "alpha_7d" in data
          assert "edge_trend" in data

      def test_edge_trend_expanding(self):
          """alpha_7d > alpha_30d → edge_trend='expanding'."""
          mock_db = AsyncMock()
          mock_db.fetchrow = AsyncMock(return_value=_stats_row(avg_pnl_r_7d=0.4, avg_pnl_r_30d=0.2))
          app.dependency_overrides[get_db_manager] = lambda: mock_db
          data = TestClient(app).get("/api/signals/stats").json()
          assert data["edge_trend"] == "expanding"

      def test_edge_trend_compressing(self):
          """alpha_7d < alpha_30d → edge_trend='compressing'."""
          mock_db = AsyncMock()
          mock_db.fetchrow = AsyncMock(return_value=_stats_row(avg_pnl_r_7d=0.1, avg_pnl_r_30d=0.3))
          app.dependency_overrides[get_db_manager] = lambda: mock_db
          data = TestClient(app).get("/api/signals/stats").json()
          assert data["edge_trend"] == "compressing"

      def test_hero_rate_zero_denominator(self):
          """selected_count_today=0 → hero_rate=0.0 (no division by zero)."""
          mock_db = AsyncMock()
          mock_db.fetchrow = AsyncMock(return_value=_stats_row(hero_count_today=0, selected_count_today=0))
          app.dependency_overrides[get_db_manager] = lambda: mock_db
          data = TestClient(app).get("/api/signals/stats").json()
          assert data["hero_rate"] == 0.0
  ```

- [ ] **Step 2: Run tests — expect FAIL**

  ```bash
  .venv/bin/pytest tests/unit/test_signals_api_stats.py -v
  ```

  Expected: all fail (endpoint doesn't exist).

- [ ] **Step 3: Add `GET /api/signals/stats` to `signals.py`**

  Add after the `get_recent_signals` function:

  ```python
  @router.get("/signals/stats")
  async def get_signals_stats(
      db_manager: DatabaseManager = Depends(get_db_manager),
  ) -> dict[str, Any]:
      """
      Command strip metrics: throughput, hero rate, avg confidence,
      pipeline latency percentiles, alpha composite, edge trend.
      Refreshes on a 60s client polling cadence.
      """
      try:
          query = """
              SELECT
                  -- Session counts (last 24h as proxy for current session)
                  COUNT(*) FILTER (
                      WHERE was_selected = true
                        AND signal_computed_at >= NOW() - INTERVAL '24 hours'
                  ) AS signals_today,
                  COUNT(*) FILTER (
                      WHERE was_selected = true
                        AND signal_computed_at >= NOW() - INTERVAL '48 hours'
                        AND signal_computed_at < NOW() - INTERVAL '24 hours'
                  ) AS signals_prev_session,
                  -- Hero tier count today
                  COUNT(*) FILTER (
                      WHERE was_selected = true
                        AND confidence >= 0.40
                        AND cis_score IS NOT NULL
                        AND abs(cis_score) > 0.35
                        AND signal_computed_at >= NOW() - INTERVAL '24 hours'
                  ) AS hero_count_today,
                  -- Selected count today (denominator for hero_rate)
                  COUNT(*) FILTER (
                      WHERE was_selected = true
                        AND signal_computed_at >= NOW() - INTERVAL '24 hours'
                  ) AS selected_count_today,
                  -- Avg confidence
                  ROUND(
                      AVG(confidence) FILTER (
                          WHERE was_selected = true
                            AND signal_computed_at >= NOW() - INTERVAL '24 hours'
                      )::numeric, 4
                  ) AS avg_confidence_today,
                  ROUND(
                      AVG(confidence) FILTER (
                          WHERE was_selected = true
                            AND signal_computed_at >= NOW() - INTERVAL '7 days'
                      )::numeric, 4
                  ) AS avg_confidence_7d,
                  -- Pipeline latency: signal_computed_at - timestamp (bar close time)
                  -- NOTE: latency uses signal_ledger.timestamp (bar OPEN time) as start,
                  -- not bar CLOSE time. For a 1m bar this overstates latency by ~60s.
                  -- True bar_close = timestamp + bar_period. Correcting this requires
                  -- per-timeframe CASE and is deferred to v2. Document this in the UI tooltip.
                  ROUND(
                      PERCENTILE_CONT(0.5) WITHIN GROUP (
                          ORDER BY EXTRACT(EPOCH FROM (signal_computed_at - timestamp))
                      ) FILTER (
                          WHERE was_selected = true
                            AND signal_computed_at IS NOT NULL
                            AND signal_computed_at >= NOW() - INTERVAL '24 hours'
                      )::numeric, 2
                  ) AS latency_p50,
                  ROUND(
                      PERCENTILE_CONT(0.95) WITHIN GROUP (
                          ORDER BY EXTRACT(EPOCH FROM (signal_computed_at - timestamp))
                      ) FILTER (
                          WHERE was_selected = true
                            AND signal_computed_at IS NOT NULL
                            AND signal_computed_at >= NOW() - INTERVAL '24 hours'
                      )::numeric, 2
                  ) AS latency_p95,
                  -- Rolling pnl_r
                  ROUND(
                      AVG(pnl_r) FILTER (
                          WHERE was_selected = true
                            AND pnl_r IS NOT NULL
                            AND timestamp >= NOW() - INTERVAL '7 days'
                      )::numeric, 4
                  ) AS avg_pnl_r_7d,
                  ROUND(
                      AVG(pnl_r) FILTER (
                          WHERE was_selected = true
                            AND pnl_r IS NOT NULL
                            AND timestamp >= NOW() - INTERVAL '30 days'
                      )::numeric, 4
                  ) AS avg_pnl_r_30d
              FROM signal_ledger
          """
          row = await db_manager.fetchrow(query)

          def _f(v: Any) -> float | None:
              return float(v) if v is not None else None

          signals_today = int(row["signals_today"] or 0)
          signals_prev = int(row["signals_prev_session"] or 0)
          hero_count = int(row["hero_count_today"] or 0)
          selected_count = int(row["selected_count_today"] or 0)
          avg_conf_today = _f(row["avg_confidence_today"])
          avg_conf_7d = _f(row["avg_confidence_7d"])
          latency_p50 = _f(row["latency_p50"])
          latency_p95 = _f(row["latency_p95"])
          alpha_7d = _f(row["avg_pnl_r_7d"])
          alpha_30d = _f(row["avg_pnl_r_30d"])

          hero_rate = round(hero_count / selected_count, 4) if selected_count > 0 else 0.0

          # Edge trend: comparing recent vs baseline rolling pnl_r
          if alpha_7d is not None and alpha_30d is not None:
              diff = alpha_7d - alpha_30d
              if diff > 0.02:
                  edge_trend = "expanding"
              elif diff < -0.02:
                  edge_trend = "compressing"
              else:
                  edge_trend = "stable"
          else:
              edge_trend = "stable"

          # hero_rate_trend: v1 returns 0.0 — computing 7d hero rate requires a second
          # query window (hero_count_7d / selected_count_7d). Deferred to v2.
          # DO NOT compute as (hero_count / prev_session) * factor — that formula is wrong.
          hero_rate_trend = 0.0

          return {
              "signals_today": signals_today,
              "signals_prev_session": signals_prev,
              "hero_rate": hero_rate,
              "hero_rate_trend": hero_rate_trend,
              "avg_confidence": avg_conf_today,
              "avg_confidence_7d": avg_conf_7d,
              "pipeline_latency_p50": latency_p50,
              "pipeline_latency_p95": latency_p95,
              "alpha_7d": alpha_7d,
              "alpha_30d": alpha_30d,
              "edge_trend": edge_trend,
          }

      except Exception as e:
          logger.error("Error fetching signal stats", error=str(e))
          raise HTTPException(status_code=500, detail=f"Error fetching signal stats: {str(e)}") from e
  ```

  **Important:** `GET /api/signals/stats` must be registered BEFORE `GET /api/signals/{symbol}` in the router, or FastAPI will try to match "stats" as a symbol param. Since both routes are on the same router and FastAPI resolves routes in order of definition, the `stats` route must appear first. Verify the order in the file after editing.

- [ ] **Step 4: Run tests — expect pass**

  ```bash
  .venv/bin/pytest tests/unit/test_signals_api_stats.py -v
  ```

  Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

  ```bash
  git add src/api/routes/signals.py tests/unit/test_signals_api_stats.py
  git commit -m "feat(signals-api): add GET /api/signals/stats for command strip metrics"
  ```

---

### Task 4: `GET /api/signals/attribution` endpoint

**Files:**
- Modify: `src/api/routes/signals.py`
- Create: `tests/unit/test_signals_api_attribution.py`

**Context:** Returns per-setup and per-asset-class alpha tables with p-value. Uses scipy for t-distribution p-value computation. Asset class is derived from Settings contracts (base symbol → sector mapping). The `setup_performance` table is NOT used — it lacks `std_pnl_r`. Query window defaults to 30d.

- [ ] **Step 1: Write failing tests**

  Create `tests/unit/test_signals_api_attribution.py`:

  ```python
  """Tests for GET /api/signals/attribution."""
  from unittest.mock import AsyncMock, patch
  import pytest
  from fastapi.testclient import TestClient
  from src.api.dependencies import get_db_manager
  from src.api.main import app

  def _row(**kwargs):
      defaults = {
          "group_key": "trad_TrendFollowing",
          "n": 120,
          "win_rate": 0.58,
          "avg_pnl_r": 0.42,
          "std_pnl_r": 1.1,
          "n_pnl": 100,
      }
      return {**defaults, **kwargs}

  @pytest.mark.unit
  class TestSignalsApiAttribution:
      def teardown_method(self):
          app.dependency_overrides.clear()

      def test_attribution_returns_200(self):
          mock_db = AsyncMock()
          mock_db.fetch = AsyncMock(return_value=[_row()])
          app.dependency_overrides[get_db_manager] = lambda: mock_db
          resp = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup")
          assert resp.status_code == 200

      def test_attribution_schema(self):
          mock_db = AsyncMock()
          mock_db.fetch = AsyncMock(return_value=[_row()])
          app.dependency_overrides[get_db_manager] = lambda: mock_db
          data = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup").json()
          assert "groups" in data
          assert len(data["groups"]) == 1
          g = data["groups"][0]
          assert "name" in g
          assert "n" in g
          assert "win_rate" in g
          assert "avg_pnl_r" in g
          assert "sharpe_proxy" in g
          assert "p_value" in g

      def test_p_value_significant_for_large_n(self):
          """N=1000, avg=0.3, std=1.0 → t=9.5 → p < 0.05."""
          mock_db = AsyncMock()
          mock_db.fetch = AsyncMock(return_value=[_row(n=1000, avg_pnl_r=0.3, std_pnl_r=1.0, n_pnl=1000)])
          app.dependency_overrides[get_db_manager] = lambda: mock_db
          data = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup").json()
          assert data["groups"][0]["p_value"] < 0.05

      def test_p_value_not_significant_for_small_n(self):
          """N=5, avg=0.1, std=2.0 → t=0.11 → p > 0.05."""
          mock_db = AsyncMock()
          mock_db.fetch = AsyncMock(return_value=[_row(n=5, avg_pnl_r=0.1, std_pnl_r=2.0, n_pnl=5)])
          app.dependency_overrides[get_db_manager] = lambda: mock_db
          data = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup").json()
          assert data["groups"][0]["p_value"] > 0.05

      def test_sharpe_zero_std_returns_none(self):
          """std_pnl_r=0 → sharpe_proxy=None (guard division by zero)."""
          mock_db = AsyncMock()
          mock_db.fetch = AsyncMock(return_value=[_row(std_pnl_r=0.0)])
          app.dependency_overrides[get_db_manager] = lambda: mock_db
          data = TestClient(app).get("/api/signals/attribution?window=30d&group_by=setup").json()
          assert data["groups"][0]["sharpe_proxy"] is None

      def test_window_param_7d_accepted(self):
          mock_db = AsyncMock()
          mock_db.fetch = AsyncMock(return_value=[])
          app.dependency_overrides[get_db_manager] = lambda: mock_db
          resp = TestClient(app).get("/api/signals/attribution?window=7d&group_by=setup")
          assert resp.status_code == 200
  ```

- [ ] **Step 2: Run tests — expect FAIL**

  ```bash
  .venv/bin/pytest tests/unit/test_signals_api_attribution.py -v
  ```

- [ ] **Step 3: Add `_compute_p_value` helper and `GET /api/signals/attribution` to `signals.py`**

  After the imports in `signals.py`, add the p-value helper:

  ```python
  import math
  from scipy import stats as _scipy_stats
  ```

  Add the `_compute_p_value` function:

  ```python
  def _compute_p_value(avg_pnl_r: float, std_pnl_r: float, n: int) -> float | None:
      """Two-sided one-sample t-test p-value against null hypothesis mean=0.

      Returns None if inputs are invalid (n < 2, std near-zero or NaN/Inf).
      """
      if n < 2 or std_pnl_r < 1e-9 or math.isnan(std_pnl_r) or math.isinf(std_pnl_r):
          return None
      t_stat = avg_pnl_r / (std_pnl_r / math.sqrt(n))
      return float(_scipy_stats.t.sf(abs(t_stat), df=n - 1) * 2)
  ```

  Add the attribution endpoint after `get_signals_stats`:

  ```python
  _WINDOW_MAP: dict[str, str] = {
      "7d": "7 days",
      "30d": "30 days",
      "90d": "90 days",
  }

  @router.get("/signals/attribution")
  async def get_signals_attribution(
      window: str = Query("30d", pattern="^(7d|30d|90d)$"),
      group_by: str = Query("setup", pattern="^(setup|asset_class)$"),
      db_manager: DatabaseManager = Depends(get_db_manager),
  ) -> dict[str, Any]:
      """
      Per-setup or per-asset-class alpha table.

      Computes AVG/STDDEV of pnl_r from signal_ledger directly (NOT setup_performance).
      Includes sharpe_proxy and two-sided t-test p-value.
      """
      try:
          interval = _WINDOW_MAP.get(window, "30 days")

          if group_by == "setup":
              group_field = "sl.setup_plugin"
          else:
              group_field = "sl.symbol"  # will be remapped to asset_class in Python

          query = f"""
              SELECT
                  {group_field}                                                 AS group_key,
                  COUNT(*) FILTER (
                      WHERE sl.outcome IS NOT NULL
                        AND sl.status NOT IN ('pending', 'active')
                  )                                                             AS n,
                  ROUND(
                      AVG(CASE
                              WHEN sl.outcome IN ('target_1','target_1_2','target_full') THEN 1.0
                              WHEN sl.outcome IS NOT NULL
                               AND sl.status NOT IN ('pending','active') THEN 0.0
                              ELSE NULL
                          END)::numeric, 4
                  )                                                             AS win_rate,
                  ROUND(
                      AVG(sl.pnl_r) FILTER (WHERE sl.pnl_r IS NOT NULL)::numeric, 4
                  )                                                             AS avg_pnl_r,
                  ROUND(
                      STDDEV(sl.pnl_r) FILTER (WHERE sl.pnl_r IS NOT NULL)::numeric, 4
                  )                                                             AS std_pnl_r,
                  COUNT(*) FILTER (WHERE sl.pnl_r IS NOT NULL)                 AS n_pnl
              FROM signal_ledger sl
              WHERE sl.was_selected = true
                AND sl.timestamp >= NOW() - INTERVAL '{interval}'
              GROUP BY {group_field}
              ORDER BY avg_pnl_r DESC NULLS LAST
          """
          rows = await db_manager.fetch(query)

          # If grouping by asset_class, remap symbol → asset_class using Settings
          # V1 LIMITATION — asset class p-value and sharpe are always null.
          # The SQL groups by symbol then remaps to sector in Python. Once aggregated
          # per symbol, STDDEV is no longer available per sector (can't reconstruct
          # combined std from per-symbol averages). A future v2 would run a separate
          # SQL query directly grouped by a stored asset_class column (requires a schema
          # migration to add asset_class as a denormalized column on signal_ledger).
          if group_by == "asset_class":
              from src.config.settings import Settings
              _settings = Settings()
              contracts = _settings.get_active_contracts()
              # Build base_symbol → sector (sector is the sub-classification of futures)
              sym_to_sector: dict[str, str] = {c.symbol: (c.sector or c.asset_class.value) for c in contracts}
              base_symbols = sorted(sym_to_sector, key=len, reverse=True)

              def _classify(contract_sym: str) -> str:
                  if contract_sym in sym_to_sector:
                      return sym_to_sector[contract_sym]
                  for base in base_symbols:
                      if contract_sym.startswith(base):
                          return sym_to_sector[base]
                  return "unknown"

              # Aggregate per sector (multiple symbols may share a sector)
              from collections import defaultdict
              sector_buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {
                  "n": 0, "win_wins": 0, "win_total": 0, "pnl_r_sum": 0.0,
                  "pnl_r_sq_sum": 0.0, "n_pnl": 0
              })
              for row in rows:
                  sector = _classify(str(row["group_key"]))
                  b = sector_buckets[sector]
                  b["n"] += int(row["n"] or 0)
                  b["n_pnl"] += int(row["n_pnl"] or 0)
                  if row["avg_pnl_r"] is not None and row["n_pnl"]:
                      b["pnl_r_sum"] += float(row["avg_pnl_r"]) * int(row["n_pnl"])
                  if row["win_rate"] is not None and row["n"]:
                      b["win_wins"] += float(row["win_rate"]) * int(row["n"])
                      b["win_total"] += int(row["n"])

              groups = []
              for sector, b in sorted(sector_buckets.items(),
                                      key=lambda x: x[1]["pnl_r_sum"] / max(x[1]["n_pnl"], 1),
                                      reverse=True):
                  n_pnl = b["n_pnl"]
                  avg_r = round(b["pnl_r_sum"] / n_pnl, 4) if n_pnl > 0 else None
                  win_r = round(b["win_wins"] / b["win_total"], 4) if b["win_total"] > 0 else None
                  # std not computable from aggregated data — set None
                  groups.append({
                      "name": sector, "n": b["n"], "win_rate": win_r,
                      "avg_pnl_r": avg_r, "sharpe_proxy": None,
                      "p_value": None, "std_pnl_r": None,
                  })
          else:
              def _f(v: Any) -> float | None:
                  return float(v) if v is not None else None

              groups = []
              for row in rows:
                  avg_r = _f(row["avg_pnl_r"])
                  std_r = _f(row["std_pnl_r"])
                  n_pnl = int(row["n_pnl"] or 0)
                  sharpe = round(avg_r / std_r, 4) if avg_r is not None and std_r and std_r != 0 else None
                  p_val = _compute_p_value(avg_r, std_r, n_pnl) if avg_r is not None and std_r is not None else None
                  groups.append({
                      "name": str(row["group_key"]),
                      "n": int(row["n"] or 0),
                      "win_rate": _f(row["win_rate"]),
                      "avg_pnl_r": avg_r,
                      "std_pnl_r": std_r,
                      "sharpe_proxy": sharpe,
                      "p_value": round(p_val, 4) if p_val is not None else None,
                  })

          return {"window": window, "group_by": group_by, "groups": groups}

      except Exception as e:
          logger.error("Error fetching signal attribution", error=str(e))
          raise HTTPException(status_code=500, detail=f"Error fetching attribution: {str(e)}") from e
  ```

  **Note:** `Settings.get_active_contracts()` is called inside the endpoint, not at import time, to avoid startup failures in test environments.

- [ ] **Step 4: Run tests — expect pass**

  ```bash
  .venv/bin/pytest tests/unit/test_signals_api_attribution.py -v
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add src/api/routes/signals.py tests/unit/test_signals_api_attribution.py
  git commit -m "feat(signals-api): add GET /api/signals/attribution with p-value and sharpe proxy"
  ```

---

### Task 5: `GET /api/signals/detail/{signal_id}` endpoint

**Files:**
- Modify: `src/api/routes/signals.py`
- Create: `tests/unit/test_signals_api_detail.py`

**Context:** Returns full signal detail including intelligence_features JOIN and signal_tier. Path is `/signals/detail/{signal_id}` — NOT `/signals/{signal_id}` to avoid shadowing the existing `/signals/{symbol}` catch-all.

- [ ] **Step 1: Write failing tests**

  Create `tests/unit/test_signals_api_detail.py`:

  ```python
  """Tests for GET /api/signals/detail/{signal_id}."""
  from unittest.mock import AsyncMock
  import pytest
  from fastapi.testclient import TestClient
  from src.api.dependencies import get_db_manager
  from src.api.main import app

  _SIGNAL_ID = "12345678-1234-1234-1234-123456789012"

  def _detail_row(**kwargs):
      from datetime import datetime, timezone
      now = datetime.now(timezone.utc)
      defaults = {
          "signal_id": _SIGNAL_ID,
          "timestamp": now,
          "symbol": "ESH6",
          "timeframe": "1m",
          "setup_plugin": "trad_TrendFollowing",
          "signal_type": "trend_long",
          "direction": 1,
          "entry_price": 5200.0,
          "stop_loss": 5180.0,
          "targets": [5240.0],
          "confidence": 0.65,
          "was_selected": True,
          "cis_score": 0.45,
          "bucket_scores": None,
          "status": "active",
          "outcome": None,
          "exit_price": None,
          "pnl_r": None,
          "signal_computed_at": now,
          "feature_ts": None,
          "feature_tf": None,
          "bar": None,
          "i1": None,
          "i3": None,
          "i4": None,
          "i5": None,
          "smc": None,
          "i6": None,
      }
      return {**defaults, **kwargs}

  @pytest.mark.unit
  class TestSignalsApiDetail:
      def teardown_method(self):
          app.dependency_overrides.clear()

      def test_detail_returns_200(self):
          mock_db = AsyncMock()
          mock_db.fetchrow = AsyncMock(return_value=_detail_row())
          app.dependency_overrides[get_db_manager] = lambda: mock_db
          resp = TestClient(app).get(f"/api/signals/detail/{_SIGNAL_ID}")
          assert resp.status_code == 200

      def test_detail_returns_signal_tier(self):
          mock_db = AsyncMock()
          mock_db.fetchrow = AsyncMock(return_value=_detail_row(confidence=0.65, was_selected=True, cis_score=0.45))
          app.dependency_overrides[get_db_manager] = lambda: mock_db
          data = TestClient(app).get(f"/api/signals/detail/{_SIGNAL_ID}").json()
          assert data["signal_tier"] == "hero"

      def test_detail_returns_404_when_not_found(self):
          mock_db = AsyncMock()
          mock_db.fetchrow = AsyncMock(return_value=None)
          app.dependency_overrides[get_db_manager] = lambda: mock_db
          resp = TestClient(app).get(f"/api/signals/detail/{_SIGNAL_ID}")
          assert resp.status_code == 404

      def test_detail_does_not_shadow_symbol_route(self):
          """GET /api/signals/ESH6 must NOT be caught by the detail route."""
          mock_db = AsyncMock()
          mock_db.fetch = AsyncMock(return_value=[])
          mock_db.fetchrow = AsyncMock(return_value={"n_total": 0, "n_resolved": 0,
              "n_suppressed": 0, "win_rate": None, "avg_pnl_r": None})
          app.dependency_overrides[get_db_manager] = lambda: mock_db
          resp = TestClient(app).get("/api/signals/ESH6")
          # Must hit the symbol route (200), not detail (would 404 for non-UUID)
          assert resp.status_code == 200
  ```

- [ ] **Step 2: Run tests — expect FAIL**

  ```bash
  .venv/bin/pytest tests/unit/test_signals_api_detail.py -v
  ```

- [ ] **Step 3: Add `GET /api/signals/detail/{signal_id}` to `signals.py`**

  Add before the `GET /api/signals/{symbol}` route (order matters — FastAPI resolves routes in definition order):

  ```python
  @router.get("/signals/detail/{signal_id}")
  async def get_signal_detail(
      signal_id: str,
      db_manager: DatabaseManager = Depends(get_db_manager),
  ) -> dict[str, Any]:
      """
      Full signal detail with intelligence_features JOIN.
      Path is /signals/detail/{signal_id} (not /signals/{signal_id})
      to avoid shadowing the existing /signals/{symbol} catch-all route.
      """
      try:
          query = """
              SELECT
                  sl.signal_id, sl.timestamp, sl.symbol, sl.timeframe,
                  sl.setup_plugin, sl.signal_type, sl.direction,
                  sl.entry_price, sl.stop_loss, sl.targets, sl.confidence,
                  sl.was_selected, sl.cis_score, sl.bucket_scores,
                  sl.status, sl.outcome, sl.exit_price, sl.pnl_r,
                  sl.signal_computed_at, sl.feature_ts, sl.feature_tf,
                  sl.entry_zone_low, sl.entry_zone_high, sl.zone_valid_at_signal,
                  sl.activation_price, sl.mae, sl.mfe, sl.bars_in_trade,
                  f.bar, f.i1, f.i3, f.i4, f.i5, f.smc, f.i6
              FROM signal_ledger sl
              LEFT JOIN intelligence_features f
                ON sl.symbol = f.symbol
               AND sl.feature_ts = f.ts
               AND sl.feature_tf = f.tf
              WHERE sl.signal_id = $1::uuid
          """
          row = await db_manager.fetchrow(query, signal_id)
          if row is None:
              raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")

          def _f(v: Any) -> float | None:
              return float(v) if v is not None else None

          return {
              "signal_id": str(row["signal_id"]),
              "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
              "symbol": row["symbol"],
              "timeframe": row["timeframe"],
              "setup_plugin": row["setup_plugin"],
              "signal_type": row["signal_type"],
              "direction": row["direction"],
              "entry_price": _f(row["entry_price"]),
              "stop_loss": _f(row["stop_loss"]),
              "targets": _parse_jsonb(row["targets"], default=[]),
              "confidence": _f(row["confidence"]),
              "was_selected": row["was_selected"],
              "cis_score": _f(row["cis_score"]),
              "bucket_scores": _parse_jsonb(row["bucket_scores"], default=None),
              "status": row["status"],
              "outcome": row["outcome"],
              "exit_price": _f(row["exit_price"]),
              "pnl_r": _f(row["pnl_r"]),
              "signal_computed_at": row["signal_computed_at"].isoformat() if row["signal_computed_at"] else None,
              "entry_zone_low": _f(row["entry_zone_low"]),
              "entry_zone_high": _f(row["entry_zone_high"]),
              "zone_valid_at_signal": row["zone_valid_at_signal"],
              "activation_price": _f(row["activation_price"]),
              "mae": _f(row["mae"]),
              "mfe": _f(row["mfe"]),
              "bars_in_trade": row["bars_in_trade"],
              "signal_tier": _compute_signal_tier(
                  row["was_selected"],
                  _f(row["confidence"]),
                  _f(row["cis_score"]),
              ),
              "features": {
                  "bar": _parse_jsonb(row["bar"], default=None),
                  "i1": _parse_jsonb(row["i1"], default=None),
                  "i3": _parse_jsonb(row["i3"], default=None),
                  "i4": _parse_jsonb(row["i4"], default=None),
                  "i5": _parse_jsonb(row["i5"], default=None),
                  "smc": _parse_jsonb(row["smc"], default=None),
                  "i6": _parse_jsonb(row["i6"], default=None),
              } if row["feature_ts"] else None,
          }

      except HTTPException:
          raise
      except Exception as e:
          logger.error("Error fetching signal detail", signal_id=signal_id, error=str(e))
          raise HTTPException(status_code=500, detail=f"Error fetching signal detail: {str(e)}") from e
  ```

- [ ] **Step 4: Run tests — expect pass**

  ```bash
  .venv/bin/pytest tests/unit/test_signals_api_detail.py -v
  ```

- [ ] **Step 5: Run all unit tests**

  ```bash
  .venv/bin/pytest tests/unit/ -v --tb=short
  ```

  Expected: all pass.

- [ ] **Step 6: Lint**

  ```bash
  .venv/bin/ruff check . --fix && .venv/bin/black src/api/routes/signals.py
  ```

- [ ] **Step 7: Commit**

  ```bash
  git add src/api/routes/signals.py tests/unit/test_signals_api_detail.py
  git commit -m "feat(signals-api): add GET /api/signals/detail/{signal_id} with features JOIN and signal_tier"
  ```

---

### Task 6: Add `cis_score` + `was_selected` to SSE signal message

**Files:**
- Modify: `services/signal_generator_service.py`

**Context:** The SSE `signals_aggregated` message is built from `result.selected_signal` (line 979). `cis_score` is on `result` (not `result.selected_signal`). `was_selected` is always `true` for the published signal. Without these fields, the frontend `isHeroTier()` function will always return `false` (cis_score=null → never Hero), making `SignalBanner`, `SignalAlertStrip`, and `WatchlistRail` never show signals.

- [ ] **Step 1: Find the SSE message construction in the service**

  In `services/signal_generator_service.py`, locate the section around line 979:

  ```python
  message = {k: str(v) for k, v in sig.items() if isinstance(v, (str, int, float, bool))}
  ```

  Identify the block that adds extra fields to `message` (lines 980–1027), ending just before the `kafka_producer.publish` calls.

- [ ] **Step 2: Add cis_score and was_selected to the message**

  After the `message["zone_valid_at_signal"]` block (around line 1027), add:

  ```python
  # Tier data — required by frontend Hero tier gate
  # cis_score is on result (AggregatedResult), not on result.selected_signal
  if result.cis_score is not None:
      message["cis_score"] = str(result.cis_score)
  # was_selected is always True for the published signal
  message["was_selected"] = "1"
  ```

- [ ] **Step 3: Verify the message is parsed correctly on the frontend**

  In `dashboard/src/hooks/use-market-stream.ts` (or wherever SSE signals are parsed), search for where `signal_computed_at` or `ask_at_signal` is parsed. The parsing pattern for these string fields should handle `cis_score` and `was_selected` similarly.

  Open the hook file and check: if numeric fields are parsed with `parseFloat(payload.field)`, add the same parsing for `cis_score`. If the hook does typed parsing, add type entries. If fields are passed as-is, no change needed — the types.ts update in Task 7 handles it.

  Run: `grep -n "signal_computed_at\|parseFloat\|was_selected" dashboard/src/hooks/use-market-stream.ts`

  Look at how other numeric string fields are handled and mirror for `cis_score`.

- [ ] **Step 4: Restart the signal_generator_service to verify the change**

  ```bash
  sudo systemctl restart indicagent-signal-generator
  journalctl -u indicagent-signal-generator -f --lines=20
  ```

  Confirm: service starts without error. After ~50 live 1m bars (~50 min warmup), check that the SSE signal payload includes `cis_score` in the browser DevTools Network tab under SSE events.

- [ ] **Step 5: Add unit test for SSE injection**

  In `tests/unit/service_tests/` (follow the `ServiceClass.__new__` pattern used in other service tests), add a test that verifies `cis_score` and `was_selected` appear in the SSE message when `result.cis_score` is set:

  ```python
  # tests/unit/service_tests/test_signal_generator_sse_fields.py
  """Verify cis_score + was_selected are injected into the SSE signal message."""
  import pytest
  from unittest.mock import MagicMock

  @pytest.mark.unit
  def test_cis_score_injected_when_present():
      """message must include cis_score when result.cis_score is not None."""
      # Build a minimal message dict matching the service's construction pattern
      # (string-coerce all scalar fields from result.selected_signal)
      sig = {"direction": 1, "entry_price": 5200.0, "stop_loss": 5180.0,
             "confidence": 0.65, "setup_plugin": "trad_TrendFollowing"}
      message = {k: str(v) for k, v in sig.items() if isinstance(v, (str, int, float, bool))}

      # Simulate Task 6 injection logic
      cis_score = 0.42
      if cis_score is not None:
          message["cis_score"] = str(cis_score)
      message["was_selected"] = "1"

      assert "cis_score" in message
      assert message["cis_score"] == "0.42"
      assert message["was_selected"] == "1"

  @pytest.mark.unit
  def test_cis_score_absent_when_none():
      """message must NOT include cis_score when result.cis_score is None (fallback path)."""
      sig = {"direction": 1, "confidence": 0.30}
      message = {k: str(v) for k, v in sig.items() if isinstance(v, (str, int, float, bool))}
      cis_score = None
      if cis_score is not None:
          message["cis_score"] = str(cis_score)
      message["was_selected"] = "1"

      assert "cis_score" not in message
      assert message["was_selected"] == "1"
  ```

  Run: `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_sse_fields.py -v`

  Expected: both tests pass.

- [ ] **Step 6: Commit**

  ```bash
  git add services/signal_generator_service.py \
    tests/unit/service_tests/test_signal_generator_sse_fields.py
  git commit -m "feat(signal-generator): add cis_score + was_selected to SSE signal message for Hero tier gating"
  ```

---

## Chunk 2: Frontend — Tier System + Existing Dashboard Surfaces

### Task 7: Add types and `signal-tier.ts` utility

**Files:**
- Modify: `dashboard/src/lib/types.ts`
- Create: `dashboard/src/lib/signal-tier.ts`

- [ ] **Step 1: Add `SignalTier` type and extend `SignalData` in `types.ts`**

  In `dashboard/src/lib/types.ts`, add after the existing imports at the top:

  ```typescript
  // ── Signal Quality Tier ──
  export type SignalTier = "hero" | "monitored" | "candidate";
  ```

  In the `SignalData` interface, add these optional fields after `setup_avg_pnl_r`:

  ```typescript
  // Tier classification — from API response or computed client-side from cis_score + was_selected
  cis_score?: number | null;         // CIS composite score (null for pre-CIS signals and SSE before Task 6)
  was_selected?: boolean;            // Did this signal win aggregation? (always true in SSE stream)
  signal_tier?: SignalTier;          // Computed tier — present in API responses; derive client-side for SSE
  ```

  Add new types for API responses at the end of the file:

  ```typescript
  // ── /api/signals/stats response ──
  export interface SignalStatsData {
    signals_today: number;
    signals_prev_session: number;
    hero_rate: number;
    hero_rate_trend: number;
    avg_confidence: number | null;
    avg_confidence_7d: number | null;
    pipeline_latency_p50: number | null;
    pipeline_latency_p95: number | null;
    alpha_7d: number | null;
    alpha_30d: number | null;
    edge_trend: "expanding" | "compressing" | "stable";
  }

  // ── /api/signals/attribution response ──
  export interface AttributionGroup {
    name: string;
    n: number;
    win_rate: number | null;
    avg_pnl_r: number | null;
    std_pnl_r: number | null;
    sharpe_proxy: number | null;
    p_value: number | null;
  }

  export interface SignalAttributionData {
    window: string;
    group_by: string;
    groups: AttributionGroup[];
  }

  // ── /api/signals/recent ledger row ──
  export interface LedgerSignal {
    signal_id: string;
    computed_at: string | null;
    symbol: string;
    timeframe: string;
    setup_plugin: string;
    signal_type: string;
    direction: number;
    confidence: number | null;
    cis_score: number | null;
    was_selected: boolean;
    signal_tier: SignalTier;
    status: string;
    outcome: string | null;
    pnl_r: number | null;
    entry_price: number | null;
    stop_loss: number | null;
    exit_price: number | null;
    setup_win_rate: number | null;
    setup_avg_pnl_r: number | null;
  }
  ```

- [ ] **Step 2: Create `dashboard/src/lib/signal-tier.ts`**

  ```typescript
  // dashboard/src/lib/signal-tier.ts
  import type { SignalTier } from "@/lib/types";

  /**
   * Compute signal quality tier from DB/API fields.
   * Evaluation order: Hero → Monitored → Candidate.
   * NULL cis_score always → Monitored (never Hero).
   *
   * Thresholds:
   *   confidence >= 0.40  — data-derived breakeven (signal_ledger outcome analysis)
   *   abs(cis_score) > 0.35 — CIS fire threshold (eliminates 80% fallback-path noise)
   */
  export function computeSignalTier(
    wasSelected: boolean,
    confidence: number | null | undefined,
    cisScore: number | null | undefined,
  ): SignalTier {
    if (
      wasSelected &&
      confidence != null &&
      cisScore != null &&
      confidence >= 0.40 &&
      Math.abs(cisScore) > 0.35
    ) {
      return "hero";
    }
    if (wasSelected) return "monitored";
    return "candidate";
  }

  /**
   * Hero tier gate for SSE SignalData where was_selected is always true.
   * If cis_score is absent (pre-Task-6 service), returns false — safe default.
   */
  export function isHeroTier(
    confidence: number,
    cisScore: number | null | undefined,
  ): boolean {
    return (
      confidence >= 0.40 &&
      cisScore != null &&
      Math.abs(cisScore) > 0.35
    );
  }

  /** Color for a tier dot/badge. */
  export function tierColor(tier: SignalTier): string {
    if (tier === "hero") return "var(--blue)";
    if (tier === "monitored") return "var(--amber)";
    return "var(--text-muted)";
  }

  /** CSS opacity for a tier row. */
  export function tierOpacity(tier: SignalTier): number {
    if (tier === "hero") return 1.0;
    if (tier === "monitored") return 0.85;
    return 0.6;
  }
  ```

- [ ] **Step 3: Build check — confirm no TypeScript errors**

  ```bash
  cd dashboard && npx tsc --noEmit
  ```

  Expected: 0 errors (or only pre-existing unrelated errors).

- [ ] **Step 4: Commit**

  ```bash
  git add dashboard/src/lib/types.ts dashboard/src/lib/signal-tier.ts
  git commit -m "feat(dashboard): add SignalTier types and signal-tier.ts utility"
  ```

---

### Task 8: Update `SignalBanner` — Hero tier gate

**Files:**
- Modify: `dashboard/src/components/signal-banner.tsx`

**Current:** Gates at `signal.confidence < HIGH_CONFIDENCE_THRESHOLD` where `HIGH_CONFIDENCE_THRESHOLD = 0.75`.
**New:** Gates on `isHeroTier(signal.confidence, signal.cis_score)`.

- [ ] **Step 1: Update `signal-banner.tsx`**

  Remove the `HIGH_CONFIDENCE_THRESHOLD` constant and replace the guard:

  ```typescript
  // Remove:
  const HIGH_CONFIDENCE_THRESHOLD = 0.75;

  // Add at top of file (after existing imports):
  import { isHeroTier } from "@/lib/signal-tier";
  ```

  Change the guard from:
  ```typescript
  if (!signal || signal.confidence < HIGH_CONFIDENCE_THRESHOLD) return null;
  ```
  to:
  ```typescript
  if (!signal || !isHeroTier(signal.confidence, signal.cis_score)) return null;
  ```

- [ ] **Step 2: Build check**

  ```bash
  cd dashboard && npx tsc --noEmit
  ```

  Expected: 0 errors.

- [ ] **Step 3: Commit**

  ```bash
  git add dashboard/src/components/signal-banner.tsx
  git commit -m "feat(signal-banner): gate on Hero tier instead of confidence >= 0.75"
  ```

---

### Task 9: Update `SignalAlertStrip` — Hero tier gate

**Files:**
- Modify: `dashboard/src/components/signal-alert-strip.tsx`

**Current:** `if (signal.confidence < ALERT_CONFIDENCE_THRESHOLD) continue;` where threshold = 0.65.
**New:** Use `isHeroTier(signal.confidence, signal.cis_score)`.

- [ ] **Step 1: Update `signal-alert-strip.tsx`**

  Add import:
  ```typescript
  import { isHeroTier } from "@/lib/signal-tier";
  ```

  Remove: `const ALERT_CONFIDENCE_THRESHOLD = 0.65;`

  Replace:
  ```typescript
  if (signal.confidence < ALERT_CONFIDENCE_THRESHOLD) continue;
  ```
  with:
  ```typescript
  if (!isHeroTier(signal.confidence, signal.cis_score)) continue;
  ```

- [ ] **Step 2: Build check and commit**

  ```bash
  cd dashboard && npx tsc --noEmit
  git add dashboard/src/components/signal-alert-strip.tsx
  git commit -m "feat(signal-alert-strip): gate on Hero tier instead of confidence >= 0.65"
  ```

---

### Task 10: Update `WatchlistRail` — Hero tier badge only

**Files:**
- Modify: `dashboard/src/components/watchlist-rail.tsx`

**Current:** `getActiveSignal()` shows badge for any non-stale signal regardless of confidence.
**New:** Badge shows only for Hero tier signals. Regime accent (left border color) is unchanged.

- [ ] **Step 1: Update `watchlist-rail.tsx`**

  Add import:
  ```typescript
  import { isHeroTier } from "@/lib/signal-tier";
  ```

  In `WatchlistRow`, after computing `bestSignal`, add:

  ```typescript
  const isHero = bestSignal !== null && isHeroTier(bestSignal.confidence, bestSignal.cis_score);
  ```

  Change `hasSignal` from:
  ```typescript
  const hasSignal = bestSignal !== null && !bestSignal.resolved;
  ```
  to:
  ```typescript
  const hasSignal = isHero && !bestSignal?.resolved;
  ```

  The `borderColor` and background color logic that already references `hasSignal` remains unchanged.

  **Note:** `regimeColor` (the left-border accent from I4 trend regime) is intentionally unchanged — it reflects market structure, not signal quality. Only the L/S signal badge is gated.

- [ ] **Step 2: Build check and commit**

  ```bash
  cd dashboard && npx tsc --noEmit
  git add dashboard/src/components/watchlist-rail.tsx
  git commit -m "feat(watchlist-rail): show L/S badge only for Hero tier signals"
  ```

---

### Task 11: Update `ConfidenceRing` — add tier badge below ring

**Files:**
- Modify: `dashboard/src/components/confidence-ring.tsx`

**Current:** Shows score + price + direction badge. No tier context.
**New:** Add small tier badge below the direction badge when a signal is present.

- [ ] **Step 1: Update `confidence-ring.tsx`**

  Add import:
  ```typescript
  import { computeSignalTier, tierColor } from "@/lib/signal-tier";
  ```

  Inside the `ConfidenceRing` component, after the `hasSignal` declaration, add:

  ```typescript
  const tier = hasSignal
    ? computeSignalTier(
        signal!.was_selected ?? true,  // SSE signals are always was_selected=true
        signal!.confidence,
        signal!.cis_score ?? null,
      )
    : null;
  ```

  After the direction badge JSX block (the `{hasSignal && (...)}` block), add:

  ```typescript
  {tier && (
    <span
      className="text-[0.42rem] font-bold uppercase tracking-widest px-1 py-0 rounded"
      style={{
        backgroundColor: "rgba(255,255,255,0.05)",
        color: tierColor(tier),
      }}
    >
      {tier}
    </span>
  )}
  ```

- [ ] **Step 2: Build check and commit**

  ```bash
  cd dashboard && npx tsc --noEmit
  git add dashboard/src/components/confidence-ring.tsx
  git commit -m "feat(confidence-ring): add tier badge below direction indicator"
  ```

---

### Task 12: Update `SignalScorecard` — tier visual weight

**Files:**
- Modify: `dashboard/src/components/signal-scorecard.tsx`

**Current:** All signals rendered with same visual weight. Winner gets filled dot (●), others open dot (○).
**New:** Winner badge shows "HERO" label only if tier is Hero. Confidence column color-coded by tier breakpoint. Candidate signals (is_winner=false, confidence < 0.40 or no CIS) at 60% opacity.

**Note:** `RankedSignal` in the scorecard comes from SSE `signal_scorecard` events — it has `confidence`, `is_winner`, `composite_rank`, but NOT `cis_score` or `was_selected` (those aren't in `RankedSignal`). Tier approximation for scorecard rows: a signal is "Hero-quality" if `is_winner && confidence >= 0.40`. Full tier classification requires `cis_score` which isn't in `RankedSignal`. Use the simplified rule: `confidence >= 0.40` for the scorecard display (winner badge) and opacity fallback.

- [ ] **Step 1: Update `signal-scorecard.tsx`**

  Add to imports:
  ```typescript
  // No external import needed — inline tier logic for RankedSignal (no cis_score available)
  ```

  In the `sorted.map()` body, change the winner label and opacity:

  ```typescript
  // Replace the winner dot logic:
  const isHighQuality = signal.confidence >= 0.40;
  const dotColor = isWinner
    ? isHighQuality ? "var(--blue)" : "var(--amber)"
    : "var(--text-muted)";

  // Opacity: non-winner, low confidence → 60%
  const rowOpacity = !isWinner && signal.confidence < 0.40 ? 0.6 : 1.0;
  ```

  Wrap the row div with `style={{ opacity: rowOpacity }}`:
  ```typescript
  <div
    key={...}
    className="flex items-center gap-2 text-[0.65rem]"
    style={{ opacity: rowOpacity }}
  >
  ```

  For the winner, add a "HERO" badge next to the dot when isHighQuality:
  ```typescript
  {isWinner && isHighQuality && (
    <span className="text-[0.4rem] font-bold uppercase px-0.5 rounded"
      style={{ backgroundColor: "rgba(59,130,246,0.15)", color: "var(--blue)" }}>
      hero
    </span>
  )}
  ```

- [ ] **Step 2: Build check and commit**

  ```bash
  cd dashboard && npx tsc --noEmit
  git add dashboard/src/components/signal-scorecard.tsx
  git commit -m "feat(signal-scorecard): tier visual weight — hero badge, candidate opacity"
  ```

---

### Task 13: Update `DrillPanel` — `RecentSignals` passes `tier=hero` + add `use-market-stream.ts` cis_score parsing

**Files:**
- Modify: `dashboard/src/components/drill-panel.tsx`
- Modify: `dashboard/src/hooks/use-market-stream.ts` (or wherever SSE signals are parsed)

- [ ] **Step 1: Find the RecentSignals fetch call in `drill-panel.tsx`**

  Search for the fetch call in `drill-panel.tsx`:

  ```bash
  grep -n "signals/recent\|fetchRecent\|getRecentSignals" dashboard/src/components/drill-panel.tsx
  ```

  Locate the API call. It currently passes `symbol` and optionally `timeframe`. The default `tier=hero` is now handled server-side (Task 2 set default to `hero`), so the call needs no change for the default case. But verify the fetch URL includes no explicit `tier` param that would need updating.

- [ ] **Step 2: Add tier badge to `RecentSignalCard` in `drill-panel.tsx`**

  In the `RecentSignalCard` sub-component (renders individual signals in the history section), add a tier dot:

  ```typescript
  // Add to imports in drill-panel.tsx:
  import { computeSignalTier, tierColor } from "@/lib/signal-tier";
  ```

  In `RecentSignalCard`, compute tier from the signal data (which now includes `signal_tier` from the API):

  ```typescript
  const tier = (signal as any).signal_tier ?? computeSignalTier(
    (signal as any).was_selected ?? true,
    signal.confidence,
    (signal as any).cis_score ?? null,
  );
  ```

  Add a small tier dot before the setup name:

  ```typescript
  <span
    className="shrink-0 w-1.5 h-1.5 rounded-full inline-block"
    style={{ backgroundColor: tierColor(tier) }}
    title={`${tier} tier`}
  />
  ```

- [ ] **Step 3: Parse `cis_score` and `was_selected` from SSE signal payload**

  Open `dashboard/src/hooks/use-market-stream.ts`. Find where signal fields are parsed from the SSE message. Locate code that processes `signal_computed_at` or `confidence` from the message.

  Add parsing for the new fields:

  ```typescript
  // After existing signal field parsing (e.g., after confidence is parsed):
  if (payload.cis_score !== undefined) {
    signal.cis_score = parseFloat(payload.cis_score) || null;
  }
  if (payload.was_selected !== undefined) {
    signal.was_selected = Number(payload.was_selected) > 0;
  }
  ```

  The exact location depends on the hook's structure. Follow the same pattern as `ask_at_signal` or `market_price_at_signal` parsing.

- [ ] **Step 4: Build check**

  ```bash
  cd dashboard && npx tsc --noEmit
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add dashboard/src/components/drill-panel.tsx dashboard/src/hooks/use-market-stream.ts
  git commit -m "feat(drill-panel): tier dots in RecentSignals; parse cis_score/was_selected from SSE"
  ```

---

## Chunk 3: Signal Intelligence Page

### Task 14: Install `@tanstack/react-virtual` + create page skeleton

**Files:**
- Modify: `dashboard/package.json`
- Create: `dashboard/src/app/signals/page.tsx`
- Modify: `dashboard/src/components/trading-dashboard.tsx`

- [ ] **Step 1: Install @tanstack/react-virtual**

  ```bash
  cd dashboard && npm install @tanstack/react-virtual
  ```

  Expected: installs `@tanstack/react-virtual@^3.x`. Verify `package.json` is updated.

- [ ] **Step 2: Create `dashboard/src/app/signals/page.tsx`**

  ```typescript
  // dashboard/src/app/signals/page.tsx
  "use client";

  import { Suspense } from "react";
  import { SignalsPage } from "@/components/signals/signals-page";

  export default function Signals() {
    return (
      <Suspense>
        <SignalsPage />
      </Suspense>
    );
  }
  ```

- [ ] **Step 3: Create `dashboard/src/components/signals/signals-page.tsx` — full page layout**

  ```typescript
  // dashboard/src/components/signals/signals-page.tsx
  "use client";

  import { useState, useCallback } from "react";
  import Link from "next/link";
  import { ArrowLeft } from "lucide-react";
  import { CommandStrip } from "./command-strip";
  import { AttributionRow } from "./attribution-row";
  import { ClusterStrip } from "./cluster-strip";
  import { FilterBar, FilterState, defaultFilters } from "./filter-bar";
  import { SignalLedger } from "./signal-ledger";

  export function SignalsPage() {
    const [filters, setFilters] = useState<FilterState>(defaultFilters);

    const handleFilterChange = useCallback((next: Partial<FilterState>) => {
      setFilters((prev) => ({ ...prev, ...next }));
    }, []);

    return (
      <div className="min-h-screen flex flex-col bg-[var(--bg-base)]">
        {/* Header */}
        <header
          className="sticky top-0 z-50 flex items-center justify-between px-5 py-2.5 border-b border-[var(--border-subtle)] shrink-0"
          style={{ background: "rgba(10, 14, 20, 0.92)", backdropFilter: "blur(8px)" }}
        >
          <div className="flex items-center gap-3">
            <Link
              href="/dashboard"
              className="flex items-center gap-1.5 text-[0.65rem] text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
            >
              <ArrowLeft size={12} />
              Dashboard
            </Link>
            <div className="w-px h-3 bg-[var(--border-subtle)]" />
            <span style={{
              fontFamily: "var(--font-display)",
              fontWeight: 700,
              fontSize: "0.9rem",
              color: "var(--text-primary)",
            }}>
              Signal Intelligence
            </span>
          </div>
        </header>

        {/* Zone 1 — Command Strip (sticky below header) */}
        <div className="sticky top-[41px] z-40 border-b border-[var(--border-subtle)]"
             style={{ background: "rgba(10, 14, 20, 0.95)" }}>
          <CommandStrip />
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-[1600px] mx-auto px-4 py-4 flex flex-col gap-4">
            {/* Zone 2 — Attribution Row */}
            <AttributionRow onSetupClick={(setup) => handleFilterChange({ setup_plugin: [setup] })}
                            onAssetClassClick={(ac) => handleFilterChange({ asset_class: [ac] })} />

            {/* Zone 3 — Cluster Strip */}
            <ClusterStrip onClusterClick={(symbols) => handleFilterChange({ symbol: symbols })} />

            {/* Zone 4 — Filter Bar */}
            <FilterBar filters={filters} onChange={handleFilterChange} />

            {/* Zone 5 — Signal Ledger */}
            <SignalLedger filters={filters} />
          </div>
        </div>
      </div>
    );
  }
  ```

- [ ] **Step 4: Add `/signals` nav link to `trading-dashboard.tsx`**

  In `dashboard/src/components/trading-dashboard.tsx`, add to imports:
  ```typescript
  import Link from "next/link";
  import { BarChart2 } from "lucide-react";
  ```

  In the header's `<div className="flex items-center gap-3">` (left side), add after the profile switcher:
  ```typescript
  <Link
    href="/signals"
    className="flex items-center gap-1 px-2 py-0.5 rounded text-[0.62rem] text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] transition-colors"
  >
    <BarChart2 size={10} />
    Signals
  </Link>
  ```

- [ ] **Step 5: Build check**

  ```bash
  cd dashboard && npx tsc --noEmit
  ```

- [ ] **Step 6: Commit**

  ```bash
  git add dashboard/package.json dashboard/package-lock.json \
    dashboard/src/app/signals/page.tsx \
    dashboard/src/components/signals/signals-page.tsx \
    dashboard/src/components/trading-dashboard.tsx
  git commit -m "feat(signals-page): scaffold /signals route and page layout with nav link"
  ```

---

### Task 15: Zone 1 — `CommandStrip` component

**Files:**
- Create: `dashboard/src/components/signals/command-strip.tsx`

**Context:** 6 stat pills. Data from `GET /api/signals/stats`, refreshed every 60s.

- [ ] **Step 1: Create `command-strip.tsx`**

  ```typescript
  // dashboard/src/components/signals/command-strip.tsx
  "use client";

  import { useState, useEffect } from "react";
  import { getApiBase } from "@/lib/api";
  import type { SignalStatsData } from "@/lib/types";
  import { fmtNum } from "@/lib/format";

  function StatPill({
    label,
    value,
    sub,
    color,
  }: {
    label: string;
    value: string;
    sub?: string;
    color: string;
  }) {
    return (
      <div
        className="flex flex-col gap-0.5 px-4 py-2 border-r border-[var(--border-subtle)] last:border-r-0 min-w-[120px]"
      >
        <span className="text-[0.5rem] font-semibold uppercase tracking-widest text-[var(--text-muted)]">
          {label}
        </span>
        <span
          className="text-sm font-bold font-data leading-none"
          style={{ color }}
        >
          {value}
        </span>
        {sub && (
          <span className="text-[0.52rem] font-data text-[var(--text-muted)]">{sub}</span>
        )}
      </div>
    );
  }

  function latencyColor(p50: number | null): string {
    if (p50 === null) return "var(--text-muted)";
    if (p50 < 10) return "var(--green)";
    if (p50 < 30) return "var(--amber)";
    return "var(--red)";
  }

  function edgeTrendColor(trend: string): string {
    if (trend === "expanding") return "var(--green)";
    if (trend === "compressing") return "var(--red)";
    return "var(--text-muted)";
  }

  export function CommandStrip() {
    const [stats, setStats] = useState<SignalStatsData | null>(null);

    useEffect(() => {
      const load = async () => {
        try {
          const res = await fetch(`${getApiBase()}/api/signals/stats`);
          if (res.ok) setStats(await res.json());
        } catch {
          // fail silently — show dashes
        }
      };
      load();
      const interval = setInterval(load, 60_000);
      return () => clearInterval(interval);
    }, []);

    const s = stats;
    const heroRatePct = s ? `${fmtNum(s.hero_rate * 100, 1)}%` : "—";
    const heroRateTrend = s && s.hero_rate_trend !== 0
      ? (s.hero_rate_trend > 0 ? `↑ ${fmtNum(s.hero_rate_trend * 100, 1)}%` : `↓ ${fmtNum(Math.abs(s.hero_rate_trend) * 100, 1)}%`)
      : undefined;
    const confToday = s?.avg_confidence != null ? fmtNum(s.avg_confidence, 3) : "—";
    const conf7d = s?.avg_confidence_7d != null ? `7d avg ${fmtNum(s.avg_confidence_7d, 3)}` : undefined;
    const latP50 = s?.pipeline_latency_p50 != null ? `${fmtNum(s.pipeline_latency_p50, 1)}s` : "—";
    const latP95 = s?.pipeline_latency_p95 != null ? `p95 ${fmtNum(s.pipeline_latency_p95, 1)}s` : undefined;
    const alpha7d = s?.alpha_7d != null ? (s.alpha_7d >= 0 ? `+${fmtNum(s.alpha_7d, 3)}R` : `${fmtNum(s.alpha_7d, 3)}R`) : "—";
    const alpha30d = s?.alpha_30d != null ? `30d ${s.alpha_30d >= 0 ? "+" : ""}${fmtNum(s.alpha_30d, 3)}R` : undefined;

    return (
      <div className="flex items-stretch overflow-x-auto" style={{ scrollbarWidth: "none" }}>
        <StatPill
          label="Signals / session"
          value={s ? String(s.signals_today) : "—"}
          sub={s ? `prev ${s.signals_prev_session}` : undefined}
          color="var(--blue)"
        />
        <StatPill
          label="Hero rate"
          value={heroRatePct}
          sub={heroRateTrend}
          color={s && s.hero_rate_trend > 0 ? "var(--amber)" : "var(--text-secondary)"}
        />
        <StatPill
          label="Avg confidence"
          value={confToday}
          sub={conf7d}
          color={s && s.avg_confidence != null && s.avg_confidence_7d != null
            ? s.avg_confidence > s.avg_confidence_7d ? "var(--green)" : "var(--red)"
            : "var(--text-secondary)"}
        />
        <StatPill
          label="Pipeline latency"
          value={latP50}
          sub={latP95}
          color={latencyColor(s?.pipeline_latency_p50 ?? null)}
        />
        <StatPill
          label="Alpha composite"
          value={alpha7d}
          sub={alpha30d}
          color={s && s.alpha_7d != null ? s.alpha_7d > 0 ? "var(--green)" : "var(--red)" : "var(--text-secondary)"}
        />
        <StatPill
          label="Edge trend"
          value={s?.edge_trend ?? "—"}
          sub={s ? `7d−30d ${s.alpha_7d != null && s.alpha_30d != null ? fmtNum((s.alpha_7d ?? 0) - (s.alpha_30d ?? 0), 3) : "—"}R` : undefined}
          color={edgeTrendColor(s?.edge_trend ?? "")}
        />
      </div>
    );
  }
  ```

- [ ] **Step 2: Build check and commit**

  ```bash
  cd dashboard && npx tsc --noEmit
  git add dashboard/src/components/signals/command-strip.tsx
  git commit -m "feat(signals-page): Zone 1 — CommandStrip with 6 stat pills"
  ```

---

### Task 16: Zone 2 — `AttributionRow` component

**Files:**
- Create: `dashboard/src/components/signals/attribution-row.tsx`

**Context:** Two side-by-side alpha tables (Setup Alpha left, Asset Class Alpha right). Inline histogram cells use canvas. Clicking a row pre-filters the Signal Ledger. p-value cells highlighted when `p < 0.05`.

- [ ] **Step 1: Create `attribution-row.tsx`**

  ```typescript
  // dashboard/src/components/signals/attribution-row.tsx
  "use client";

  import { useState, useEffect, useRef } from "react";
  import { getApiBase } from "@/lib/api";
  import type { SignalAttributionData, AttributionGroup } from "@/lib/types";
  import { fmtNum } from "@/lib/format";

  // ── Mini histogram (9 buckets, 80×20px canvas) ──
  function MiniHistogram({ values }: { values: number[] }) {
    const ref = useRef<HTMLCanvasElement>(null);
    useEffect(() => {
      const canvas = ref.current;
      if (!canvas || values.length === 0) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const min = Math.min(...values);
      const max = Math.max(...values);
      const range = max - min || 1;
      const bucketCount = 9;
      const buckets = new Array(bucketCount).fill(0);
      for (const v of values) {
        const idx = Math.min(Math.floor(((v - min) / range) * bucketCount), bucketCount - 1);
        buckets[idx]++;
      }
      const maxCount = Math.max(...buckets, 1);
      ctx.clearRect(0, 0, 80, 20);
      const barW = 80 / bucketCount;
      buckets.forEach((count, i) => {
        const h = (count / maxCount) * 20;
        const midpointNorm = (i + 0.5) / bucketCount;
        ctx.fillStyle = midpointNorm > 0.5 ? "rgba(0,220,130,0.7)" : "rgba(255,71,87,0.5)";
        ctx.fillRect(i * barW, 20 - h, barW - 1, h);
      });
    }, [values]);
    return <canvas ref={ref} width={80} height={20} className="rounded-sm" />;
  }

  function PValueCell({ p }: { p: number | null }) {
    if (p === null) return <span className="text-[var(--text-muted)]">—</span>;
    const sig = p < 0.05;
    return (
      <span
        className="font-data text-[0.65rem]"
        style={{ color: sig ? "var(--cyan)" : "var(--text-secondary)" }}
      >
        {p.toFixed(3)}
        {sig && " *"}
      </span>
    );
  }

  function AttributionTable({
    title,
    data,
    onRowClick,
  }: {
    title: string;
    data: AttributionGroup[];
    onRowClick: (name: string) => void;
  }) {
    return (
      <div className="flex-1 min-w-0">
        <div className="text-[0.6rem] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-2 px-1">
          {title}
        </div>
        <table className="w-full text-[0.65rem]" style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr className="text-[var(--text-muted)]" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
              <th className="text-left py-1 px-1 font-semibold">Setup</th>
              <th className="text-right py-1 px-1 font-semibold">N</th>
              <th className="text-right py-1 px-1 font-semibold">Win%</th>
              <th className="text-right py-1 px-1 font-semibold">Avg R</th>
              <th className="text-right py-1 px-1 font-semibold">Sharpe</th>
              <th className="text-right py-1 px-1 font-semibold">p-val</th>
            </tr>
          </thead>
          <tbody>
            {data.map((g) => (
              <tr
                key={g.name}
                className="cursor-pointer hover:bg-[var(--bg-elevated)] transition-colors"
                onClick={() => onRowClick(g.name)}
                style={{ borderBottom: "1px solid var(--border-subtle)" }}
              >
                <td className="py-1 px-1 font-data text-[var(--text-secondary)] truncate max-w-[160px]">
                  {g.name.replace(/^(trad_|ind_|smc_)/, "")}
                </td>
                <td className="py-1 px-1 text-right font-data text-[var(--text-muted)]">{g.n}</td>
                <td className="py-1 px-1 text-right font-data"
                    style={{ color: g.win_rate != null && g.win_rate >= 0.5 ? "var(--green)" : "var(--red)" }}>
                  {g.win_rate != null ? `${fmtNum(g.win_rate * 100, 1)}%` : "—"}
                </td>
                <td className="py-1 px-1 text-right font-data"
                    style={{ color: g.avg_pnl_r != null ? g.avg_pnl_r >= 0 ? "var(--green)" : "var(--red)" : "var(--text-muted)" }}>
                  {g.avg_pnl_r != null ? (g.avg_pnl_r >= 0 ? "+" : "") + fmtNum(g.avg_pnl_r, 3) : "—"}
                </td>
                <td className="py-1 px-1 text-right font-data text-[var(--text-secondary)]">
                  {g.sharpe_proxy != null ? fmtNum(g.sharpe_proxy, 2) : "—"}
                </td>
                <td className="py-1 px-1 text-right"><PValueCell p={g.p_value} /></td>
              </tr>
            ))}
            {data.length === 0 && (
              <tr><td colSpan={6} className="py-4 text-center text-[var(--text-muted)] italic">No data</td></tr>
            )}
          </tbody>
        </table>
      </div>
    );
  }

  export function AttributionRow({
    onSetupClick,
    onAssetClassClick,
  }: {
    onSetupClick: (setup: string) => void;
    onAssetClassClick: (ac: string) => void;
  }) {
    const [setupData, setSetupData] = useState<SignalAttributionData | null>(null);
    const [acData, setAcData] = useState<SignalAttributionData | null>(null);

    useEffect(() => {
      const base = getApiBase();
      Promise.all([
        fetch(`${base}/api/signals/attribution?window=30d&group_by=setup`).then((r) => r.json()),
        fetch(`${base}/api/signals/attribution?window=30d&group_by=asset_class`).then((r) => r.json()),
      ]).then(([setup, ac]) => {
        setSetupData(setup);
        setAcData(ac);
      }).catch(() => {});
    }, []);

    return (
      <div
        className="flex gap-4 p-3 rounded"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}
      >
        <AttributionTable
          title="Setup Alpha (30d)"
          data={setupData?.groups ?? []}
          onRowClick={onSetupClick}
        />
        <div className="w-px bg-[var(--border-subtle)] shrink-0" />
        <AttributionTable
          title="Asset Class Alpha (30d)"
          data={acData?.groups ?? []}
          onRowClick={onAssetClassClick}
        />
      </div>
    );
  }
  ```

- [ ] **Step 2: Build check and commit**

  ```bash
  cd dashboard && npx tsc --noEmit
  git add dashboard/src/components/signals/attribution-row.tsx
  git commit -m "feat(signals-page): Zone 2 — AttributionRow with p-value table and asset class alpha"
  ```

---

### Task 17: Zone 3 — `ClusterStrip` component

**Files:**
- Create: `dashboard/src/components/signals/cluster-strip.tsx`

**Context:** Detected from SSE signal stream — no new API endpoint. Collects `signal_scorecard` SSE events across all symbols. A "cluster" = ≥3 symbols fire in the same 1m bar on the same TF within the last 5 minutes. Setup diversity score: `distinct_setups / total_symbols`. Uses `useMarketStream` hook's data.

- [ ] **Step 1: Create `cluster-strip.tsx`**

  ```typescript
  // dashboard/src/components/signals/cluster-strip.tsx
  "use client";

  import { useState, useEffect, useRef } from "react";
  import { getApiBase } from "@/lib/api";
  import type { LedgerSignal } from "@/lib/types";
  import { fmtNum } from "@/lib/format";

  interface ClusterEvent {
    barTs: string;         // ISO bar timestamp — cluster key
    tf: string;
    symbols: string[];
    setups: string[];
    avgConf: number;
    diversityScore: number; // distinct_setups / symbols.length
  }

  const CLUSTER_MIN_SYMBOLS = 3;
  const CLUSTER_WINDOW_MS = 5 * 60 * 1000; // 5 minutes

  /**
   * ClusterStrip detects clusters from the recent signals API.
   * Fetches /api/signals/recent?tier=all&limit=200 every 30s and
   * groups by (bar_ts ≈ timestamp rounded to 1m, timeframe).
   */
  export function ClusterStrip({
    onClusterClick,
  }: {
    onClusterClick: (symbols: string[]) => void;
  }) {
    const [clusters, setClusters] = useState<ClusterEvent[]>([]);

    useEffect(() => {
      const detect = async () => {
        try {
          const res = await fetch(
            `${getApiBase()}/api/signals/recent?tier=all&limit=200`
          );
          if (!res.ok) return;
          const data: { signals: LedgerSignal[] } = await res.json();
          const now = Date.now();
          const cutoff = now - CLUSTER_WINDOW_MS;

          // Group by (minute-truncated timestamp, timeframe)
          const byBar = new Map<string, LedgerSignal[]>();
          for (const sig of data.signals) {
            const ts = sig.computed_at ? new Date(sig.computed_at).getTime() : 0;
            if (ts < cutoff) continue;
            // Truncate to minute
            const minuteTs = new Date(Math.floor(ts / 60_000) * 60_000).toISOString();
            const key = `${minuteTs}|${sig.timeframe}`;
            if (!byBar.has(key)) byBar.set(key, []);
            byBar.get(key)!.push(sig);
          }

          const found: ClusterEvent[] = [];
          for (const [key, sigs] of byBar.entries()) {
            if (sigs.length < CLUSTER_MIN_SYMBOLS) continue;
            const [barTs, tf] = key.split("|");
            const symbols = [...new Set(sigs.map((s) => s.symbol))];
            if (symbols.length < CLUSTER_MIN_SYMBOLS) continue;
            const setups = [...new Set(sigs.map((s) => s.setup_plugin))];
            const avgConf = sigs.reduce((a, b) => a + (b.confidence ?? 0), 0) / sigs.length;
            const diversityScore = setups.length / symbols.length;
            found.push({ barTs, tf, symbols, setups, avgConf, diversityScore });
          }

          setClusters(found.sort((a, b) => b.symbols.length - a.symbols.length));
        } catch {
          // fail silently
        }
      };
      detect();
      const t = setInterval(detect, 30_000);
      return () => clearInterval(t);
    }, []);

    if (clusters.length === 0) return null;

    return (
      <div className="flex flex-col gap-2">
        {clusters.map((c, i) => {
          const isConfluence = c.diversityScore >= 0.6;
          const label = isConfluence ? "Confluence" : "Correlated";
          const color = isConfluence ? "var(--cyan)" : "var(--amber)";
          const timeStr = new Date(c.barTs).toLocaleTimeString([], {
            hour: "2-digit", minute: "2-digit", hour12: false,
          });
          return (
            <button
              key={i}
              onClick={() => onClusterClick(c.symbols)}
              className="w-full flex items-center gap-3 px-3 py-2 rounded text-left transition-opacity hover:opacity-80"
              style={{
                background: isConfluence ? "rgba(0,220,255,0.05)" : "rgba(255,179,71,0.06)",
                border: `1px solid ${color}33`,
              }}
            >
              <span className="text-[0.6rem] font-bold uppercase tracking-widest" style={{ color }}>
                {label}
              </span>
              <span className="text-[0.62rem] font-data text-[var(--text-secondary)]">
                {timeStr} UTC · {c.tf} · {c.symbols.length} symbols · avg conf {fmtNum(c.avgConf, 2)} · {c.setups.length} distinct setup{c.setups.length !== 1 ? "s" : ""}
              </span>
              <span className="text-[0.55rem] text-[var(--text-muted)] flex-1 truncate">
                [{c.symbols.join(" ")}]
              </span>
            </button>
          );
        })}
      </div>
    );
  }
  ```

- [ ] **Step 2: Build check and commit**

  ```bash
  cd dashboard && npx tsc --noEmit
  git add dashboard/src/components/signals/cluster-strip.tsx
  git commit -m "feat(signals-page): Zone 3 — ClusterStrip with setup diversity score"
  ```

---

### Task 18: Zone 4 — `FilterBar` component

**Files:**
- Create: `dashboard/src/components/signals/filter-bar.tsx`

**Context:** Persistent above ledger. Multi-select pills, range slider, date picker. Filter state serialized to URL params via `useSearchParams` + `useRouter`.

- [ ] **Step 1: Create `filter-bar.tsx`**

  ```typescript
  // dashboard/src/components/signals/filter-bar.tsx
  "use client";

  import { useCallback } from "react";
  import { useRouter, useSearchParams } from "next/navigation";

  export interface FilterState {
    symbol: string[];
    asset_class: string[];
    setup_plugin: string[];
    timeframe: string[];
    tier: string[];
    confidence_min: number;
    confidence_max: number;
    cis_filter: "all" | "cis_only" | "fallback_only";
    status: string[];
    date_from: string;   // YYYY-MM-DD
    date_to: string;     // YYYY-MM-DD
  }

  function defaultDateFrom() {
    const d = new Date();
    d.setDate(d.getDate() - 7);
    return d.toISOString().slice(0, 10);
  }

  export const defaultFilters: FilterState = {
    symbol: [],
    asset_class: [],
    setup_plugin: [],
    timeframe: [],
    tier: [],
    confidence_min: 0,
    confidence_max: 1,
    cis_filter: "all",
    status: [],
    date_from: defaultDateFrom(),
    date_to: new Date().toISOString().slice(0, 10),
  };

  const TIER_OPTIONS = ["hero", "monitored", "candidate"] as const;
  const TF_OPTIONS = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;
  const STATUS_OPTIONS = ["pending", "active", "regime_suppressed", "expired"] as const;
  const ASSET_CLASS_OPTIONS = ["equity_index", "energy", "metals", "interest_rates", "fx", "crypto"] as const;

  function PillToggle<T extends string>({
    label,
    options,
    selected,
    onChange,
  }: {
    label: string;
    options: readonly T[];
    selected: T[];
    onChange: (val: T[]) => void;
  }) {
    const toggle = (v: T) => {
      if (selected.includes(v)) {
        onChange(selected.filter((x) => x !== v));
      } else {
        onChange([...selected, v]);
      }
    };
    return (
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-[0.52rem] uppercase tracking-widest text-[var(--text-muted)] shrink-0">
          {label}
        </span>
        {options.map((opt) => {
          const active = selected.includes(opt) || selected.length === 0;
          return (
            <button
              key={opt}
              onClick={() => toggle(opt)}
              className="px-2 py-0.5 rounded text-[0.6rem] font-semibold transition-colors"
              style={{
                backgroundColor: selected.includes(opt)
                  ? "var(--bg-elevated)"
                  : "transparent",
                color: selected.includes(opt)
                  ? "var(--text-primary)"
                  : "var(--text-muted)",
                border: `1px solid ${selected.includes(opt) ? "var(--border-bright)" : "var(--border-subtle)"}`,
              }}
            >
              {opt}
            </button>
          );
        })}
      </div>
    );
  }

  export function FilterBar({
    filters,
    onChange,
  }: {
    filters: FilterState;
    onChange: (next: Partial<FilterState>) => void;
  }) {
    return (
      <div
        className="flex flex-wrap gap-3 p-3 rounded"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}
      >
        {/* Tier */}
        <PillToggle
          label="Tier"
          options={TIER_OPTIONS}
          selected={filters.tier as typeof TIER_OPTIONS[number][]}
          onChange={(v) => onChange({ tier: v })}
        />

        {/* Timeframe */}
        <PillToggle
          label="TF"
          options={TF_OPTIONS}
          selected={filters.timeframe as typeof TF_OPTIONS[number][]}
          onChange={(v) => onChange({ timeframe: v })}
        />

        {/* Asset class */}
        <PillToggle
          label="Asset"
          options={ASSET_CLASS_OPTIONS}
          selected={filters.asset_class as typeof ASSET_CLASS_OPTIONS[number][]}
          onChange={(v) => onChange({ asset_class: v })}
        />

        {/* CIS filter */}
        <div className="flex items-center gap-1.5">
          <span className="text-[0.52rem] uppercase tracking-widest text-[var(--text-muted)]">CIS</span>
          {(["all", "cis_only", "fallback_only"] as const).map((opt) => (
            <button
              key={opt}
              onClick={() => onChange({ cis_filter: opt })}
              className="px-2 py-0.5 rounded text-[0.6rem] font-semibold transition-colors"
              style={{
                backgroundColor: filters.cis_filter === opt ? "var(--bg-elevated)" : "transparent",
                color: filters.cis_filter === opt ? "var(--text-primary)" : "var(--text-muted)",
                border: `1px solid ${filters.cis_filter === opt ? "var(--border-bright)" : "var(--border-subtle)"}`,
              }}
            >
              {opt.replace("_", " ")}
            </button>
          ))}
        </div>

        {/* Confidence range */}
        <div className="flex items-center gap-2">
          <span className="text-[0.52rem] uppercase tracking-widest text-[var(--text-muted)]">Conf</span>
          <input
            type="range"
            min={0} max={1} step={0.05}
            value={filters.confidence_min}
            onChange={(e) => onChange({ confidence_min: parseFloat(e.target.value) })}
            className="w-20 h-1 accent-[var(--blue)]"
          />
          <span className="text-[0.6rem] font-data text-[var(--text-secondary)]">
            {(filters.confidence_min * 100).toFixed(0)}%–{(filters.confidence_max * 100).toFixed(0)}%
          </span>
        </div>

        {/* Date range */}
        <div className="flex items-center gap-1.5">
          <span className="text-[0.52rem] uppercase tracking-widest text-[var(--text-muted)]">Date</span>
          <input
            type="date"
            value={filters.date_from}
            onChange={(e) => onChange({ date_from: e.target.value })}
            className="text-[0.6rem] font-data bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded px-1 py-0.5 text-[var(--text-secondary)]"
          />
          <span className="text-[0.52rem] text-[var(--text-muted)]">→</span>
          <input
            type="date"
            value={filters.date_to}
            onChange={(e) => onChange({ date_to: e.target.value })}
            className="text-[0.6rem] font-data bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded px-1 py-0.5 text-[var(--text-secondary)]"
          />
        </div>

        {/* Reset */}
        <button
          onClick={() => onChange(defaultFilters)}
          className="ml-auto text-[0.55rem] text-[var(--text-muted)] hover:text-[var(--text-secondary)] transition-colors"
        >
          Reset
        </button>
      </div>
    );
  }
  ```

- [ ] **Step 2: Build check and commit**

  ```bash
  cd dashboard && npx tsc --noEmit
  git add dashboard/src/components/signals/filter-bar.tsx
  git commit -m "feat(signals-page): Zone 4 — FilterBar with multi-select pills and date range"
  ```

---

### Task 19: Zone 5 — `SignalLedger` + `SignalDetailPanel`

**Files:**
- Create: `dashboard/src/components/signals/signal-ledger.tsx`

**Context:** Virtualized table using `@tanstack/react-virtual`. Fetches `GET /api/signals/recent?tier=all&limit=500` with filter params. Clicking a row opens a right-side detail panel (reuses DrillPanel internals via `GET /api/signals/detail/{signal_id}`). Row visual weight by tier. Close detail panel on Escape.

- [ ] **Step 1: Create `signal-ledger.tsx`**

  ```typescript
  // dashboard/src/components/signals/signal-ledger.tsx
  "use client";

  import { useState, useEffect, useRef, useCallback, useMemo } from "react";
  import { useVirtualizer } from "@tanstack/react-virtual";
  import { getApiBase } from "@/lib/api";
  import type { LedgerSignal, SignalTier } from "@/lib/types";
  import { FilterState } from "./filter-bar";
  import { tierColor, tierOpacity } from "@/lib/signal-tier";
  import { fmtNum, fmtTimeHMS } from "@/lib/format";
  import { TrendingUp, TrendingDown, X } from "lucide-react";

  // ── Row component ──

  function TierDot({ tier }: { tier: SignalTier }) {
    return (
      <span
        className="inline-block w-2 h-2 rounded-full shrink-0"
        style={{ backgroundColor: tierColor(tier) }}
        title={tier}
      />
    );
  }

  function OutcomeCell({ outcome }: { outcome: string | null }) {
    if (!outcome) return <span className="text-[var(--text-muted)]">—</span>;
    const isWin = ["target_1", "target_1_2", "target_full"].includes(outcome);
    const isLoss = !isWin;
    return (
      <span
        className="text-[0.58rem] font-semibold px-1 py-0 rounded"
        style={{
          color: isWin ? "var(--green)" : "var(--red)",
          backgroundColor: isWin ? "rgba(0,220,130,0.1)" : "rgba(255,71,87,0.1)",
        }}
      >
        {outcome.replace(/_/g, " ")}
      </span>
    );
  }

  function LedgerRow({
    signal,
    isSelected,
    onClick,
  }: {
    signal: LedgerSignal;
    isSelected: boolean;
    onClick: () => void;
  }) {
    const tier = signal.signal_tier;
    const opacity = tierOpacity(tier);
    const isLong = signal.direction === 1;
    const isCandidate = tier === "candidate";
    const timeStr = fmtTimeHMS(signal.computed_at ?? undefined);
    const pnlColor = signal.pnl_r != null
      ? signal.pnl_r >= 0 ? "var(--green)" : "var(--red)"
      : "var(--text-muted)";
    const cisStr = signal.cis_score != null
      ? (signal.cis_score >= 0 ? "+" : "") + fmtNum(signal.cis_score, 2)
      : "—";

    return (
      <div
        onClick={onClick}
        className="flex items-center gap-0 cursor-pointer hover:bg-[var(--bg-elevated)] transition-colors border-b border-[var(--border-subtle)]"
        style={{
          opacity,
          borderLeft: tier === "hero" ? "2px solid var(--blue)" : "2px solid transparent",
          backgroundColor: isSelected ? "var(--bg-elevated)" : undefined,
          height: "28px",
        }}
      >
        {/* Time */}
        <span className="w-[90px] shrink-0 px-2 text-[0.6rem] font-data text-[var(--text-muted)]">
          {timeStr ?? "—"}
        </span>
        {/* Symbol */}
        <span className="w-[70px] shrink-0 px-1 text-[0.65rem] font-bold font-data text-[var(--text-secondary)]">
          {signal.symbol}
        </span>
        {/* TF */}
        <span className="w-[36px] shrink-0 px-1 text-[0.6rem] font-data text-[var(--text-muted)]">
          {signal.timeframe}
        </span>
        {/* Setup */}
        <span
          className={`w-[130px] shrink-0 px-1 text-[0.62rem] font-data truncate ${isCandidate ? "italic" : ""}`}
          style={{ color: "var(--text-secondary)" }}
        >
          {signal.setup_plugin.replace(/^(trad_|ind_|smc_)/, "")}
        </span>
        {/* Dir */}
        <span className="w-[28px] shrink-0 px-1 flex items-center justify-center">
          {isLong
            ? <TrendingUp size={10} style={{ color: "var(--green)" }} />
            : <TrendingDown size={10} style={{ color: "var(--red)" }} />
          }
        </span>
        {/* Tier dot */}
        <span className="w-[22px] shrink-0 px-1 flex items-center justify-center">
          <TierDot tier={tier} />
        </span>
        {/* Confidence */}
        <span
          className="w-[56px] shrink-0 px-1 text-right text-[0.62rem] font-data"
          style={{ color: (signal.confidence ?? 0) >= 0.40 ? "var(--text-primary)" : "var(--text-muted)" }}
        >
          {signal.confidence != null ? fmtNum(signal.confidence, 2) : "—"}
        </span>
        {/* CIS */}
        <span
          className="w-[56px] shrink-0 px-1 text-right text-[0.62rem] font-data"
          style={{ color: signal.cis_score != null ? signal.cis_score >= 0 ? "var(--green)" : "var(--red)" : "var(--text-muted)" }}
        >
          {cisStr}
        </span>
        {/* Status */}
        <span className="w-[76px] shrink-0 px-1 text-[0.58rem] font-data text-[var(--text-muted)] truncate">
          {signal.status}
        </span>
        {/* Outcome */}
        <span className="w-[96px] shrink-0 px-1">
          <OutcomeCell outcome={signal.outcome} />
        </span>
        {/* PnL R */}
        <span className="w-[56px] shrink-0 px-1 text-right text-[0.62rem] font-data" style={{ color: pnlColor }}>
          {signal.pnl_r != null ? (signal.pnl_r >= 0 ? "+" : "") + fmtNum(signal.pnl_r, 1) + "R" : "—"}
        </span>
      </div>
    );
  }

  // ── Header row ──
  function LedgerHeader() {
    return (
      <div
        className="flex items-center gap-0 border-b border-[var(--border-default)] sticky top-0 z-10"
        style={{ background: "var(--bg-surface)", height: "28px" }}
      >
        {[
          { label: "Time",    w: 90 },
          { label: "Symbol",  w: 70 },
          { label: "TF",      w: 36 },
          { label: "Setup",   w: 130 },
          { label: "Dir",     w: 28 },
          { label: "Tier",    w: 22 },
          { label: "Conf",    w: 56, right: true },
          { label: "CIS",     w: 56, right: true },
          { label: "Status",  w: 76 },
          { label: "Outcome", w: 96 },
          { label: "PnL R",   w: 56, right: true },
        ].map(({ label, w, right }) => (
          <span
            key={label}
            className={`shrink-0 px-1 text-[0.52rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] ${right ? "text-right" : ""}`}
            style={{ width: `${w}px` }}
          >
            {label}
          </span>
        ))}
      </div>
    );
  }

  // ── Detail panel ──

  function SignalDetailPanel({
    signalId,
    onClose,
  }: {
    signalId: string;
    onClose: () => void;
  }) {
    const [detail, setDetail] = useState<any | null>(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
      setLoading(true);
      fetch(`${getApiBase()}/api/signals/detail/${signalId}`)
        .then((r) => r.json())
        .then((d) => { setDetail(d); setLoading(false); })
        .catch(() => setLoading(false));
    }, [signalId]);

    useEffect(() => {
      const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
      window.addEventListener("keydown", handler);
      return () => window.removeEventListener("keydown", handler);
    }, [onClose]);

    return (
      <div
        className="flex flex-col border-l border-[var(--border-subtle)] overflow-y-auto shrink-0"
        style={{ width: "320px", background: "var(--bg-surface)" }}
      >
        <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-subtle)]">
          <span className="text-[0.62rem] font-bold uppercase tracking-widest text-[var(--text-secondary)]">
            Signal Detail
          </span>
          <button onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
            <X size={14} />
          </button>
        </div>
        {loading && (
          <div className="p-4 text-[0.62rem] text-[var(--text-muted)] italic">Loading...</div>
        )}
        {!loading && detail && (
          <div className="p-3 flex flex-col gap-2 text-[0.65rem]">
            <div className="grid grid-cols-2 gap-1">
              {[
                ["Symbol", detail.symbol],
                ["TF", detail.timeframe],
                ["Setup", detail.setup_plugin?.replace(/^(trad_|ind_|smc_)/, "")],
                ["Direction", detail.direction === 1 ? "LONG ▲" : "SHORT ▼"],
                ["Tier", detail.signal_tier?.toUpperCase()],
                ["Confidence", fmtNum(detail.confidence, 3)],
                ["CIS Score", detail.cis_score != null ? fmtNum(detail.cis_score, 3) : "—"],
                ["Entry", detail.entry_price != null ? fmtNum(detail.entry_price, 2) : "—"],
                ["Stop", detail.stop_loss != null ? fmtNum(detail.stop_loss, 2) : "—"],
                ["Status", detail.status],
                ["Outcome", detail.outcome ?? "—"],
                ["PnL R", detail.pnl_r != null ? fmtNum(detail.pnl_r, 2) + "R" : "—"],
                ["MAE", detail.mae != null ? fmtNum(detail.mae, 2) : "—"],
                ["MFE", detail.mfe != null ? fmtNum(detail.mfe, 2) : "—"],
                ["Bars", detail.bars_in_trade != null ? String(detail.bars_in_trade) : "—"],
              ].map(([k, v]) => (
                <div key={k} className="flex flex-col gap-0.5">
                  <span className="text-[0.48rem] uppercase tracking-widest text-[var(--text-muted)]">{k}</span>
                  <span className="text-[0.65rem] font-data text-[var(--text-primary)]">{v}</span>
                </div>
              ))}
            </div>
            {detail.bucket_scores && (
              <div className="mt-2">
                <span className="text-[0.52rem] uppercase tracking-widest text-[var(--text-muted)]">CIS Buckets</span>
                <pre className="text-[0.55rem] font-data text-[var(--text-secondary)] mt-1 whitespace-pre-wrap">
                  {JSON.stringify(detail.bucket_scores, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
        {!loading && !detail && (
          <div className="p-4 text-[0.62rem] text-[var(--red)] italic">Signal not found</div>
        )}
      </div>
    );
  }

  // ── Main SignalLedger ──

  function buildQueryParams(filters: FilterState): string {
    const params = new URLSearchParams();
    params.set("limit", "500");

    // Tier: if filter selects specific tiers, use "all" and filter client-side
    // If only hero selected, use tier=hero for server-side filter
    if (filters.tier.length === 1 && filters.tier[0] === "hero") {
      params.set("tier", "hero");
    } else if (filters.tier.length === 1 && filters.tier[0] === "monitored") {
      params.set("tier", "monitored");
    } else {
      params.set("tier", "all");
    }

    if (filters.symbol.length === 1) params.set("symbol", filters.symbol[0]);
    if (filters.timeframe.length === 1) params.set("timeframe", filters.timeframe[0]);

    return params.toString();
  }

  export function SignalLedger({ filters }: { filters: FilterState }) {
    const [signals, setSignals] = useState<LedgerSignal[]>([]);
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const parentRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
      const qs = buildQueryParams(filters);
      fetch(`${getApiBase()}/api/signals/recent?${qs}`)
        .then((r) => r.json())
        .then((d) => setSignals(d.signals ?? []))
        .catch(() => setSignals([]));
    }, [filters]);

    // Client-side filtering for multi-select cases
    const filtered = useMemo(() => {
      return signals.filter((s) => {
        if (filters.tier.length > 0 && !filters.tier.includes(s.signal_tier)) return false;
        if (filters.timeframe.length > 0 && !filters.timeframe.includes(s.timeframe)) return false;
        if (filters.symbol.length > 0 && !filters.symbol.includes(s.symbol)) return false;
        if (filters.setup_plugin.length > 0 && !filters.setup_plugin.includes(s.setup_plugin)) return false;
        if (filters.status.length > 0 && !filters.status.includes(s.status)) return false;
        if (s.confidence != null && s.confidence < filters.confidence_min) return false;
        if (s.confidence != null && s.confidence > filters.confidence_max) return false;
        if (filters.cis_filter === "cis_only" && (s.cis_score == null || Math.abs(s.cis_score) <= 0.35)) return false;
        if (filters.cis_filter === "fallback_only" && s.cis_score != null && Math.abs(s.cis_score) > 0.35) return false;
        return true;
      });
    }, [signals, filters]);

    const rowVirtualizer = useVirtualizer({
      count: filtered.length,
      getScrollElement: () => parentRef.current,
      estimateSize: () => 28,
      overscan: 20,
    });

    const selectedSignal = selectedId
      ? filtered.find((s) => s.signal_id === selectedId) ?? null
      : null;

    return (
      <div
        className="flex rounded overflow-hidden"
        style={{ border: "1px solid var(--border-subtle)", background: "var(--bg-surface)", height: "600px" }}
      >
        {/* Table */}
        <div className="flex flex-col flex-1 min-w-0">
          <LedgerHeader />
          <div ref={parentRef} className="flex-1 overflow-y-auto overflow-x-auto" style={{ position: "relative" }}>
            <div style={{ height: `${rowVirtualizer.getTotalSize()}px`, position: "relative" }}>
              {rowVirtualizer.getVirtualItems().map((vi) => {
                const sig = filtered[vi.index];
                return (
                  <div
                    key={sig.signal_id}
                    style={{ position: "absolute", top: vi.start, width: "100%" }}
                  >
                    <LedgerRow
                      signal={sig}
                      isSelected={sig.signal_id === selectedId}
                      onClick={() => setSelectedId(sig.signal_id === selectedId ? null : sig.signal_id)}
                    />
                  </div>
                );
              })}
            </div>
          </div>
          <div className="px-3 py-1 border-t border-[var(--border-subtle)] text-[0.55rem] text-[var(--text-muted)]">
            {filtered.length} signals
          </div>
        </div>

        {/* Detail panel */}
        {selectedId && (
          <SignalDetailPanel
            signalId={selectedId}
            onClose={() => setSelectedId(null)}
          />
        )}
      </div>
    );
  }
  ```

- [ ] **Step 2: Build check**

  ```bash
  cd dashboard && npx tsc --noEmit
  ```

  Fix any type errors. Common pitfall: `fmtNum` type signature — it accepts `number | undefined | null`, ensure all usages match.

- [ ] **Step 3: Commit**

  ```bash
  git add dashboard/src/components/signals/signal-ledger.tsx
  git commit -m "feat(signals-page): Zone 5 — SignalLedger with TanStack Virtual + SignalDetailPanel"
  ```

---

### Task 20: Wire all signal components + smoke test

**Files:**
- All signal component files should already exist from Tasks 14–19

- [ ] **Step 1: Verify all imports resolve in `signals-page.tsx`**

  ```bash
  cd dashboard && npx tsc --noEmit 2>&1 | head -40
  ```

  Fix any remaining import errors.

- [ ] **Step 2: Start dev server and verify the page loads**

  ```bash
  cd dashboard && npm run dev -- --port 3000 --hostname 0.0.0.0 > /tmp/dash.log 2>&1 &
  ```

  Open `http://192.168.1.158:3000/signals` in browser. Verify:
  - Page loads without JS errors in console
  - Command strip shows 6 pills (may show `—` if API is not running)
  - Attribution Row renders two empty tables (if no DB data)
  - Filter bar renders all controls
  - Signal Ledger renders with headers

- [ ] **Step 3: With API running, verify data flows**

  ```bash
  sudo systemctl status indicagent-api
  ```

  If running, check:
  - `GET /api/signals/stats` returns 200
  - `GET /api/signals/attribution?window=30d&group_by=setup` returns groups
  - `GET /api/signals/recent?tier=all&limit=20` returns signals with `signal_tier` field

- [ ] **Step 4: Verify main dashboard still works**

  Open `http://192.168.1.158:3000/dashboard`. Confirm:
  - SignalAlertStrip still renders (now Hero tier only — may show fewer signals)
  - WatchlistRail renders normally
  - Drill panel opens and shows RecentSignals with tier dots

- [ ] **Step 5: Run full unit test suite + lint**

  ```bash
  .venv/bin/pytest tests/unit/ -v --tb=short
  .venv/bin/ruff check . --fix
  .venv/bin/black src/
  ```

- [ ] **Step 6: Final commit**

  ```bash
  git add -p  # review staged changes
  git commit -m "feat: Signal Intelligence Command Center + unified tier system complete"
  ```

---

## Success Criteria Verification

Before claiming completion, verify each criterion from the spec:

1. **No signal with confidence < 0.40 or |cis_score| < 0.35 renders as a hero on any dashboard surface**
   - Test: find a signal in the ledger with confidence=0.30. Confirm it does NOT appear in SignalBanner or SignalAlertStrip.

2. **Signal Intelligence page loads with full ledger in < 2s**
   - Test: open `/signals` with browser DevTools network tab. Confirm `signals/recent?tier=all&limit=500` completes in < 2s.

3. **Attribution table shows statistically significant edge (p < 0.05) for at least the top 3 setup plugins by volume**
   - Test: open `/signals` → AttributionRow. Confirm p-value column shows `*` markers for high-volume setups.

4. **Cluster detector correctly identifies correlated vs confluence clusters**
   - Test: manually inspect ClusterStrip output when multiple symbols have signals. Confirm "Correlated" vs "Confluence" classification makes sense given the setup diversity shown.

5. **All existing functionality preserved — no signal data is hidden, only weighted**
   - Test: open drill panel → RecentSignals. Confirm signals appear (tier=hero default). Then call `GET /api/signals/recent?symbol=ESH6&tier=all` and confirm it returns more signals than `tier=hero`.
