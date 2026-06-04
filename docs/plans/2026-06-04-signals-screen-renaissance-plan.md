# Signals Screen — Renaissance Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the signals screen into an institutional-grade live monitoring terminal — live signal cards, setup×regime heat map, edge sparklines, intraday session heat map, upgraded ledger columns, and a fully redesigned detail panel.

**Architecture:** Six API changes (3 enhanced, 3 new) feed seven new/upgraded frontend components. No new npm dependencies — sparklines and heat maps are pure SVG/CSS. All new endpoints aggregate `signal_ledger_full` with no schema changes.

**Tech Stack:** Python/FastAPI (backend), Next.js 19/React/TypeScript (frontend), @tanstack/react-virtual (existing), Tailwind CSS, pure SVG

**Spec:** `docs/plans/2026-06-04-signals-screen-renaissance-redesign.md`

---

## File Map

**Backend (all in `src/api/routes/signals.py`):**
- Enhance: `get_active_signals` — add 5 fields
- Enhance: `get_recent_signals` — add 6 fields + r_ratio
- Enhance: `get_signals_stats` — add `recent_outcomes`
- Enhance: `get_signal_detail` — add lifecycle fields
- New: `get_signals_heatmap`
- New: `get_signals_edge_series`
- New: `get_signals_intraday_heatmap`

**Tests (new files):**
- `tests/unit/api/test_signals_api_heatmap.py`
- `tests/unit/api/test_signals_api_edge_series.py`
- `tests/unit/api/test_signals_api_intraday_heatmap.py`
- Extend: `tests/unit/api/test_signals_api_stats.py`
- Extend: `tests/unit/api/test_signals_route.py`

**Frontend (new files):**
- `dashboard/src/components/signals/live-signal-cards.tsx` — LiveSignalCards + SignalCard
- `dashboard/src/components/signals/setup-regime-heatmap.tsx` — SetupRegimeHeatMap
- `dashboard/src/components/signals/edge-sparkline.tsx` — EdgeSparkline (SVG)
- `dashboard/src/components/signals/intraday-heatmap.tsx` — IntradayHeatMap
- `dashboard/src/components/signals/edge-intelligence-strip.tsx` — EdgeIntelligenceStrip container
- `dashboard/src/components/signals/signal-detail-panel.tsx` — redesigned detail panel (extracted from signal-ledger.tsx)

**Frontend (modified):**
- `dashboard/src/lib/types.ts` — new interfaces + extended LedgerSignal
- `dashboard/src/components/signals/filter-bar.tsx` — add regime filter + `regime` to FilterState
- `dashboard/src/components/signals/signal-ledger.tsx` — new columns, remove inline detail panel
- `dashboard/src/components/signals/command-strip.tsx` — skew pill + streak bar
- `dashboard/src/components/signals/signals-page.tsx` — add new zones

---

## Task 1: Enhance `/api/signals/active` — add regime/staleness/ttl fields

**Files:**
- Modify: `src/api/routes/signals.py` (get_active_signals, ~line 179)
- Test: `tests/unit/api/test_signals_route.py`

- [ ] **Step 1: Add the 5 new fields to the SELECT in `get_active_signals`**

In `src/api/routes/signals.py`, find the `get_active_signals` query (the SELECT starting around line 179). Add these columns after `sl.timestamp`:

```python
# Replace the SELECT list — add these 5 columns after sl.timestamp:
                sl.staleness_score,
                sl.staleness_trigger_reason,
                sl.ttl_bars,
                sl.hmm_regime_at_fire,
                sl.bucket_scores,
```

- [ ] **Step 2: Add the 5 fields to the returned dict in `get_active_signals`**

In the `signals.append({...})` block, add after `"setup_win_rate"`:

```python
                    "staleness_score": _f(row["staleness_score"]),
                    "staleness_trigger_reason": _s(row["staleness_trigger_reason"]),
                    "ttl_bars": int(row["ttl_bars"]) if row["ttl_bars"] is not None else None,
                    "hmm_regime_at_fire": int(row["hmm_regime_at_fire"]) if row["hmm_regime_at_fire"] is not None else None,
                    "bucket_scores": _parse_jsonb(row["bucket_scores"], default=None),
```

- [ ] **Step 3: Write a test verifying the new fields appear**

Add to `tests/unit/api/test_signals_route.py`. First read the file to find the existing `_active_row` helper or the test class for active signals, then append:

```python
def test_active_signals_includes_regime_fields():
    """Active signals response includes hmm_regime_at_fire, ttl_bars, bucket_scores."""
    from tests.unit.api.test_signals_route import _make_client, _make_mock_db
    import json, uuid
    from datetime import datetime

    mock_db = _make_mock_db()
    row = {
        "signal_id": str(uuid.uuid4()),
        "symbol": "ES", "timeframe": "1m", "setup_plugin": "trad_FailedBreakout",
        "signal_type": "long_entry", "direction": 1,
        "entry_price": "5285.50", "stop_loss": "5278.00", "confidence": "0.72",
        "status": "pending", "was_selected": True,
        "cis_score": "0.45", "targets": json.dumps([5296.0]),
        "regime_context": None, "stop_basis": None,
        "market_price_at_signal": None, "ask_at_signal": None,
        "bid_at_signal": None, "entry_zone_low": None, "entry_zone_high": None,
        "zone_valid_at_signal": None,
        "signal_computed_at": datetime(2026, 6, 4, 14, 32, 7),
        "bar_close_ts": datetime(2026, 6, 4, 14, 32, 0),
        "timestamp": datetime(2026, 6, 4, 14, 32, 7),
        "setup_win_rate": 0.083, "setup_avg_pnl_r": 0.175,
        "staleness_score": None, "staleness_trigger_reason": None,
        "ttl_bars": 10, "hmm_regime_at_fire": 0,
        "bucket_scores": json.dumps({"trend": 0.82, "momentum": 0.61}),
    }
    mock_db.fetch = AsyncMock(return_value=[row])
    client = _make_client(mock_db)
    data = client.get("/api/signals/active").json()
    sig = data["signals"][0]
    assert sig["hmm_regime_at_fire"] == 0
    assert sig["ttl_bars"] == 10
    assert sig["bucket_scores"] == {"trend": 0.82, "momentum": 0.61}
    assert sig["staleness_score"] is None
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/api/test_signals_route.py -v -k "regime"
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/routes/signals.py tests/unit/api/test_signals_route.py
git commit -m "feat(api): add regime/staleness/ttl fields to /api/signals/active"
```

---

## Task 2: Enhance `/api/signals/recent` — add regime, exit_reason, mfe, ttl, targets, r_ratio

**Files:**
- Modify: `src/api/routes/signals.py` (get_recent_signals, ~line 313)
- Test: `tests/unit/api/test_signals_api_stats.py` (append)

- [ ] **Step 1: Add columns to the SELECT in `get_recent_signals`**

In `get_recent_signals`, the main_query SELECT (around line 314). Add after `sl.symbol`:

```python
                sl.hmm_regime_at_fire,
                sl.exit_reason,
                sl.mfe,
                sl.ttl_bars,
                sl.bars_in_trade,
                sl.targets,
```

- [ ] **Step 2: Add r_ratio computation and new fields to the returned signal dicts**

In the list comprehension building `signals` (around line 352), replace it with a loop that computes r_ratio:

```python
        signals = []
        for row in rows:
            targets = _parse_jsonb(row["targets"], default=[])
            t1 = float(targets[0]) if targets else None
            entry = _f(row["entry_price"])
            stop = _f(row["stop_loss"])
            direction = row["direction"]
            r_ratio = None
            if t1 is not None and entry is not None and stop is not None and entry != stop:
                risk = abs(entry - stop)
                reward = abs(t1 - entry)
                r_ratio = round(reward / risk, 2) if risk > 0 else None
            signals.append({
                "signal_id": str(row["signal_id"]),
                "setup_plugin": row["setup_plugin"],
                "signal_type": row["signal_type"],
                "direction": direction,
                "entry_price": entry,
                "stop_loss": stop,
                "confidence": _f(row["confidence"]),
                "was_selected": row["was_selected"],
                "cis_score": _f(row["cis_score"]),
                "status": row["status"],
                "outcome": row["outcome"],
                "exit_price": _f(row["exit_price"]),
                "pnl_r": _f(row["pnl_r"]),
                "computed_at": (
                    row["signal_computed_at"].isoformat()
                    if row["signal_computed_at"] is not None
                    and hasattr(row["signal_computed_at"], "isoformat")
                    else None
                ),
                "timeframe": row["timeframe"],
                "symbol": row["symbol"],
                "setup_win_rate": _f(row["setup_win_rate"]),
                "setup_avg_pnl_r": _f(row["setup_avg_pnl_r"]),
                "signal_tier": _compute_signal_tier(
                    row["was_selected"],
                    _f(row["confidence"]),
                    _f(row["cis_score"]),
                ),
                "hmm_regime_at_fire": int(row["hmm_regime_at_fire"]) if row["hmm_regime_at_fire"] is not None else None,
                "exit_reason": _s(row["exit_reason"]),
                "mfe": _f(row["mfe"]),
                "ttl_bars": int(row["ttl_bars"]) if row["ttl_bars"] is not None else None,
                "bars_in_trade": int(row["bars_in_trade"]) if row["bars_in_trade"] is not None else None,
                "targets": targets,
                "r_ratio": r_ratio,
            })
```

- [ ] **Step 3: Write a failing test**

Append to `tests/unit/api/test_signals_api_stats.py`:

```python
def _recent_row(**kwargs):
    import uuid, json
    from datetime import datetime
    defaults = {
        "signal_id": str(uuid.uuid4()),
        "setup_plugin": "trad_FailedBreakout", "signal_type": "long_entry",
        "direction": 1, "entry_price": 5285.5, "stop_loss": 5278.0,
        "confidence": 0.72, "was_selected": True, "cis_score": 0.45,
        "status": "expired", "outcome": "target_1", "exit_price": 5296.0,
        "pnl_r": 1.5, "signal_computed_at": datetime(2026, 6, 4, 14, 32, 7),
        "timeframe": "1m", "symbol": "ES",
        "setup_win_rate": 0.083, "setup_avg_pnl_r": 0.175,
        "hmm_regime_at_fire": 0, "exit_reason": "target_1",
        "mfe": 2.4, "ttl_bars": 10, "bars_in_trade": 26,
        "targets": json.dumps([5296.0, 5302.0]),
    }
    return {**defaults, **kwargs}


@pytest.mark.unit
class TestRecentSignalsEnhanced:
    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_recent_includes_regime_and_r_ratio(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_recent_row()])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/recent?tier=all&limit=10").json()
        sig = data["signals"][0]
        assert sig["hmm_regime_at_fire"] == 0
        assert sig["exit_reason"] == "target_1"
        assert sig["mfe"] == 2.4
        assert sig["ttl_bars"] == 10
        assert sig["r_ratio"] == pytest.approx(1.37, abs=0.05)

    def test_r_ratio_null_when_no_targets(self):
        import json
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_recent_row(targets=json.dumps([]))])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/recent?tier=all&limit=10").json()
        assert data["signals"][0]["r_ratio"] is None
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/api/test_signals_api_stats.py -v -k "RecentSignalsEnhanced"
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/routes/signals.py tests/unit/api/test_signals_api_stats.py
git commit -m "feat(api): add regime/exit_reason/mfe/r_ratio to /api/signals/recent"
```

---

## Task 3: Enhance `/api/signals/stats` — add `recent_outcomes`

**Files:**
- Modify: `src/api/routes/signals.py` (get_signals_stats, ~line 420)
- Test: `tests/unit/api/test_signals_api_stats.py`

- [ ] **Step 1: Add a second DB fetch for last-10 resolved signals in `get_signals_stats`**

After the existing `row = await db_manager.fetchrow(query)` and before building the return dict, add:

```python
        outcomes_query = """
            SELECT outcome, pnl_r
            FROM signal_ledger_full
            WHERE was_selected = true
              AND status NOT IN ('pending', 'active')
              AND outcome IS NOT NULL
            ORDER BY signal_computed_at DESC
            LIMIT 10
        """
        outcome_rows = await db_manager.fetch(outcomes_query)
        recent_outcomes = [
            {"outcome": r["outcome"], "pnl_r": _f(r["pnl_r"])}
            for r in outcome_rows
        ]
```

- [ ] **Step 2: Add `recent_outcomes` to the return dict**

In the return statement of `get_signals_stats`, add:

```python
            "recent_outcomes": recent_outcomes,
```

- [ ] **Step 3: Update the stats mock to handle two DB calls and write a test**

In `tests/unit/api/test_signals_api_stats.py`, add:

```python
    def test_stats_includes_recent_outcomes(self):
        mock_db = AsyncMock()
        mock_db.fetchrow = AsyncMock(return_value=_stats_row())
        mock_db.fetch = AsyncMock(return_value=[
            {"outcome": "target_1", "pnl_r": 1.5},
            {"outcome": "stop_loss", "pnl_r": -1.0},
        ])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/stats").json()
        assert "recent_outcomes" in data
        assert len(data["recent_outcomes"]) == 2
        assert data["recent_outcomes"][0]["outcome"] == "target_1"
        assert data["recent_outcomes"][0]["pnl_r"] == 1.5

    def test_stats_recent_outcomes_empty_when_no_resolved(self):
        mock_db = AsyncMock()
        mock_db.fetchrow = AsyncMock(return_value=_stats_row())
        mock_db.fetch = AsyncMock(return_value=[])
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get("/api/signals/stats").json()
        assert data["recent_outcomes"] == []
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/api/test_signals_api_stats.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/routes/signals.py tests/unit/api/test_signals_api_stats.py
git commit -m "feat(api): add recent_outcomes to /api/signals/stats"
```

---

## Task 4: Enhance `/api/signals/detail` — add lifecycle fields

**Files:**
- Modify: `src/api/routes/signals.py` (get_signal_detail, ~line 720)
- Test: `tests/unit/api/test_signals_api_detail.py`

- [ ] **Step 1: Add lifecycle columns to the detail SELECT**

In `get_signal_detail`, the query around line 732. After `sl.activation_price, sl.mae, sl.mfe, sl.bars_in_trade,` add:

```python
                sl.hmm_regime_at_fire,
                sl.activated_at,
                sl.bars_to_activation,
                sl.exit_reason,
                sl.ttl_bars,
                sl.exit_at,
```

- [ ] **Step 2: Add the new fields to the return dict**

In the `return {...}` of `get_signal_detail`, after `"bars_in_trade"`:

```python
            "hmm_regime_at_fire": int(row["hmm_regime_at_fire"]) if row["hmm_regime_at_fire"] is not None else None,
            "activated_at": row["activated_at"].isoformat() if row["activated_at"] else None,
            "bars_to_activation": int(row["bars_to_activation"]) if row["bars_to_activation"] is not None else None,
            "exit_reason": _s(row["exit_reason"]),
            "ttl_bars": int(row["ttl_bars"]) if row["ttl_bars"] is not None else None,
            "exit_at": row["exit_at"].isoformat() if row.get("exit_at") else None,
```

- [ ] **Step 3: Write a failing test**

Read `tests/unit/api/test_signals_api_detail.py` to find the mock row factory, then append:

```python
    def test_detail_includes_lifecycle_fields(self):
        from datetime import datetime
        mock_db = AsyncMock()
        # Extend existing _detail_row with new fields
        row = _detail_row(
            hmm_regime_at_fire=0,
            activated_at=datetime(2026, 6, 4, 14, 32, 9),
            bars_to_activation=2,
            exit_reason="target_1",
            ttl_bars=10,
            exit_at=datetime(2026, 6, 4, 14, 58, 41),
        )
        mock_db.fetchrow = AsyncMock(return_value=row)
        app.dependency_overrides[get_db_manager] = lambda: mock_db
        data = TestClient(app).get(f"/api/signals/detail/{row['signal_id']}").json()
        assert data["hmm_regime_at_fire"] == 0
        assert data["bars_to_activation"] == 2
        assert data["exit_reason"] == "target_1"
        assert data["ttl_bars"] == 10
        assert "activated_at" in data
        assert "exit_at" in data
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/api/test_signals_api_detail.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/routes/signals.py tests/unit/api/test_signals_api_detail.py
git commit -m "feat(api): add lifecycle fields to /api/signals/detail"
```

---

## Task 5: New endpoint `GET /api/signals/heatmap`

**Files:**
- Modify: `src/api/routes/signals.py`
- Create: `tests/unit/api/test_signals_api_heatmap.py`

- [ ] **Step 1: Write the failing test first**

Create `tests/unit/api/test_signals_api_heatmap.py`:

```python
"""Tests for GET /api/signals/heatmap."""
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.api import dependencies
from src.api.routes.signals import router as signals_router

test_app = FastAPI()
test_app.include_router(signals_router, prefix="/api")

def _make_client(mock_db):
    test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
    return TestClient(test_app)

def _heatmap_row(**kwargs):
    defaults = {
        "setup_plugin": "trad_FailedBreakout",
        "regime": 0,
        "n": 41715,
        "avg_r": 0.175,
        "win_rate": 0.083,
    }
    return {**defaults, **kwargs}


@pytest.mark.unit
class TestSignalsHeatmap:
    def teardown_method(self):
        test_app.dependency_overrides.clear()

    def test_heatmap_returns_200(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_heatmap_row()])
        data = _make_client(mock_db).get("/api/signals/heatmap").json()
        assert "cells" in data
        assert len(data["cells"]) == 1

    def test_heatmap_cell_schema(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[_heatmap_row()])
        data = _make_client(mock_db).get("/api/signals/heatmap").json()
        cell = data["cells"][0]
        assert cell["setup_plugin"] == "trad_FailedBreakout"
        assert cell["regime"] == 0
        assert cell["n"] == 41715
        assert cell["avg_r"] == pytest.approx(0.175)
        assert cell["win_rate"] == pytest.approx(0.083)

    def test_heatmap_empty_returns_empty_cells(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[])
        data = _make_client(mock_db).get("/api/signals/heatmap").json()
        assert data["cells"] == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/api/test_signals_api_heatmap.py -v
```

Expected: FAIL — 404 (endpoint not found)

- [ ] **Step 3: Implement the endpoint**

In `src/api/routes/signals.py`, add after `get_signals_stats`:

```python
@router.get("/signals/heatmap")
async def get_signals_heatmap(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Setup × regime performance matrix for heat map visualization.

    Returns avg_r and win_rate for each (setup_plugin, hmm_regime_at_fire) cell.
    Ordered by total signal volume per setup descending.
    90-day lookback, resolved signals only.
    """
    try:
        query = """
            WITH base AS (
                SELECT
                    setup_plugin,
                    hmm_regime_at_fire AS regime,
                    COUNT(*) AS n,
                    ROUND(AVG(pnl_r)::numeric, 4) AS avg_r,
                    ROUND(
                        AVG(CASE WHEN outcome IN ('target_1', 'target_1_2', 'target_full')
                            THEN 1.0 ELSE 0.0 END)::numeric, 3
                    ) AS win_rate
                FROM signal_ledger_full
                WHERE outcome IS NOT NULL
                  AND pnl_r IS NOT NULL
                  AND was_selected = true
                  AND timestamp >= NOW() - INTERVAL '90 days'
                GROUP BY setup_plugin, hmm_regime_at_fire
            ),
            totals AS (
                SELECT setup_plugin, SUM(n) AS total_n
                FROM base
                GROUP BY setup_plugin
            )
            SELECT b.setup_plugin, b.regime, b.n, b.avg_r, b.win_rate
            FROM base b
            JOIN totals t ON t.setup_plugin = b.setup_plugin
            ORDER BY t.total_n DESC, b.setup_plugin, b.regime
        """
        rows = await db_manager.fetch(query)
        return {
            "cells": [
                {
                    "setup_plugin": row["setup_plugin"],
                    "regime": int(row["regime"]) if row["regime"] is not None else None,
                    "n": int(row["n"]),
                    "avg_r": _f(row["avg_r"]),
                    "win_rate": _f(row["win_rate"]),
                }
                for row in rows
            ]
        }
    except Exception as error:
        logger.error("Error fetching signals heatmap", error=str(error))
        raise HTTPException(status_code=500, detail=str(error)) from error
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/api/test_signals_api_heatmap.py -v
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/api/routes/signals.py tests/unit/api/test_signals_api_heatmap.py
git commit -m "feat(api): add GET /api/signals/heatmap endpoint"
```

---

## Task 6: New endpoints `GET /api/signals/edge-series` and `GET /api/signals/intraday-heatmap`

**Files:**
- Modify: `src/api/routes/signals.py`
- Create: `tests/unit/api/test_signals_api_edge_series.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/api/test_signals_api_edge_series.py`:

```python
"""Tests for GET /api/signals/edge-series and /api/signals/intraday-heatmap."""
from datetime import date
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.api import dependencies
from src.api.routes.signals import router as signals_router

test_app = FastAPI()
test_app.include_router(signals_router, prefix="/api")

def _make_client(mock_db):
    test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
    return TestClient(test_app)


@pytest.mark.unit
class TestEdgeSeries:
    def teardown_method(self):
        test_app.dependency_overrides.clear()

    def test_edge_series_returns_200(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[
            {"day": date(2026, 6, 3), "n": 100, "avg_r": 0.15, "win_rate": 0.12},
        ])
        data = _make_client(mock_db).get("/api/signals/edge-series").json()
        assert "series" in data
        assert len(data["series"]) == 1

    def test_edge_series_point_schema(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[
            {"day": date(2026, 6, 3), "n": 100, "avg_r": 0.15, "win_rate": 0.12},
        ])
        data = _make_client(mock_db).get("/api/signals/edge-series").json()
        pt = data["series"][0]
        assert "day" in pt
        assert pt["avg_r"] == pytest.approx(0.15)
        assert pt["win_rate"] == pytest.approx(0.12)
        assert pt["n"] == 100


@pytest.mark.unit
class TestIntradayHeatmap:
    def teardown_method(self):
        test_app.dependency_overrides.clear()

    def test_intraday_heatmap_returns_200(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[
            {"hour": 9, "dow": 1, "n": 250, "avg_r": 0.22},
        ])
        data = _make_client(mock_db).get("/api/signals/intraday-heatmap").json()
        assert "cells" in data
        assert len(data["cells"]) == 1

    def test_intraday_cell_schema(self):
        mock_db = AsyncMock()
        mock_db.fetch = AsyncMock(return_value=[
            {"hour": 10, "dow": 3, "n": 180, "avg_r": -0.05},
        ])
        data = _make_client(mock_db).get("/api/signals/intraday-heatmap").json()
        cell = data["cells"][0]
        assert cell["hour"] == 10
        assert cell["dow"] == 3
        assert cell["avg_r"] == pytest.approx(-0.05)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/api/test_signals_api_edge_series.py -v
```

Expected: FAIL — 404

- [ ] **Step 3: Implement both endpoints**

In `src/api/routes/signals.py`, add after the heatmap endpoint:

```python
@router.get("/signals/edge-series")
async def get_signals_edge_series(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Daily avg R and win rate for the last 30 days — feeds the edge sparkline."""
    try:
        query = """
            SELECT
                DATE_TRUNC('day', signal_computed_at)::date AS day,
                COUNT(*) FILTER (WHERE pnl_r IS NOT NULL) AS n,
                ROUND(AVG(pnl_r) FILTER (WHERE pnl_r IS NOT NULL)::numeric, 4) AS avg_r,
                ROUND(
                    AVG(CASE WHEN outcome IN ('target_1', 'target_1_2', 'target_full')
                        THEN 1.0 ELSE 0.0 END) FILTER (WHERE outcome IS NOT NULL)::numeric, 3
                ) AS win_rate
            FROM signal_ledger_full
            WHERE was_selected = true
              AND signal_computed_at >= NOW() - INTERVAL '30 days'
            GROUP BY 1
            ORDER BY 1
        """
        rows = await db_manager.fetch(query)
        return {
            "series": [
                {
                    "day": str(row["day"]),
                    "n": int(row["n"]),
                    "avg_r": _f(row["avg_r"]),
                    "win_rate": _f(row["win_rate"]),
                }
                for row in rows
            ]
        }
    except Exception as error:
        logger.error("Error fetching edge series", error=str(error))
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.get("/signals/intraday-heatmap")
async def get_signals_intraday_heatmap(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Avg R by (hour, day-of-week) — feeds the intraday session heat map.

    Times are in US/Eastern. Only market hours (8-17) and weekdays returned.
    90-day lookback.
    """
    try:
        query = """
            SELECT
                EXTRACT(HOUR FROM signal_computed_at AT TIME ZONE 'America/New_York')::int AS hour,
                EXTRACT(DOW FROM signal_computed_at AT TIME ZONE 'America/New_York')::int AS dow,
                COUNT(*) FILTER (WHERE pnl_r IS NOT NULL) AS n,
                ROUND(AVG(pnl_r) FILTER (WHERE pnl_r IS NOT NULL)::numeric, 4) AS avg_r
            FROM signal_ledger_full
            WHERE was_selected = true
              AND signal_computed_at >= NOW() - INTERVAL '90 days'
              AND EXTRACT(DOW FROM signal_computed_at AT TIME ZONE 'America/New_York') BETWEEN 1 AND 5
              AND EXTRACT(HOUR FROM signal_computed_at AT TIME ZONE 'America/New_York') BETWEEN 8 AND 17
            GROUP BY 1, 2
            ORDER BY 1, 2
        """
        rows = await db_manager.fetch(query)
        return {
            "cells": [
                {
                    "hour": row["hour"],
                    "dow": row["dow"],
                    "n": int(row["n"]),
                    "avg_r": _f(row["avg_r"]),
                }
                for row in rows
            ]
        }
    except Exception as error:
        logger.error("Error fetching intraday heatmap", error=str(error))
        raise HTTPException(status_code=500, detail=str(error)) from error
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/api/test_signals_api_edge_series.py -v
```

Expected: all PASS

- [ ] **Step 5: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/api/routes/signals.py tests/unit/api/test_signals_api_edge_series.py
git commit -m "feat(api): add edge-series and intraday-heatmap endpoints"
```

---

## Task 7: TypeScript types — extend LedgerSignal, FilterState, add new interfaces

**Files:**
- Modify: `dashboard/src/lib/types.ts`
- Modify: `dashboard/src/components/signals/filter-bar.tsx`

- [ ] **Step 1: Read the current types file**

Read `dashboard/src/lib/types.ts` to find `LedgerSignal` and the end of the file.

- [ ] **Step 2: Extend `LedgerSignal` with new fields**

After the existing `setup_avg_pnl_r` field in `LedgerSignal`:

```typescript
  hmm_regime_at_fire: number | null;
  exit_reason: string | null;
  mfe: number | null;
  ttl_bars: number | null;
  bars_in_trade: number | null;
  targets: number[];
  r_ratio: number | null;
```

- [ ] **Step 3: Add new interfaces for the new API responses**

At the end of `dashboard/src/lib/types.ts`, add:

```typescript
export interface HeatMapCell {
  setup_plugin: string;
  regime: number | null;
  n: number;
  avg_r: number | null;
  win_rate: number | null;
}

export interface EdgeSeriesPoint {
  day: string;
  n: number;
  avg_r: number | null;
  win_rate: number | null;
}

export interface IntradayCell {
  hour: number;
  dow: number;
  n: number;
  avg_r: number | null;
}

export interface ActiveSignal {
  signal_id: string;
  symbol: string;
  timeframe: string;
  setup_plugin: string;
  signal_type: string;
  direction: number;
  entry_price: number | null;
  stop_loss: number | null;
  confidence: number | null;
  status: string;
  was_selected: boolean;
  cis_score: number | null;
  profit_target: number | null;
  profit_target_2: number | null;
  profit_target_3: number | null;
  risk_reward_ratio: number | null;
  stop_type: string | null;
  regime_context: string | null;
  market_price_at_signal: number | null;
  signal_computed_at: string | null;
  bar_close_ts: string | null;
  timestamp: string | null;
  setup_win_rate: number | null;
  setup_avg_pnl_r: number | null;
  staleness_score: number | null;
  staleness_trigger_reason: string | null;
  ttl_bars: number | null;
  hmm_regime_at_fire: number | null;
  bucket_scores: Record<string, number> | null;
  signal_tier: string;
}

export interface RecentOutcome {
  outcome: string;
  pnl_r: number | null;
}
```

- [ ] **Step 4: Add `regime` to `FilterState` in filter-bar.tsx**

In `dashboard/src/components/signals/filter-bar.tsx`, in the `FilterState` interface, add:

```typescript
  regime: number[];  // [] = all, [0] = trend, [1] = range, [2] = vol
```

In `getDefaultFilters()`, add:

```typescript
    regime: [],
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd dashboard && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/lib/types.ts dashboard/src/components/signals/filter-bar.tsx
git commit -m "feat(dashboard): extend TypeScript types for Renaissance redesign"
```

---

## Task 8: Command Strip — skew pill and streak bar

**Files:**
- Modify: `dashboard/src/components/signals/command-strip.tsx`

- [ ] **Step 1: Read the current CommandStrip component fully**

Read `dashboard/src/components/signals/command-strip.tsx`.

- [ ] **Step 2: Add skew and streak computation to CommandStrip**

The CommandStrip already polls `/api/signals/stats`. Add a second poll of `/api/signals/active` for the skew. Replace the component with this extended version (keep all existing StatPill entries, add new ones):

```typescript
// Add to imports:
import type { ActiveSignal, RecentOutcome } from "@/lib/types";

// Add inside CommandStrip component, after existing stats state:
const [activeSignals, setActiveSignals] = useState<ActiveSignal[]>([]);

// Add to the useEffect (after existing load()):
const loadActive = async () => {
  try {
    const res = await fetch(`${getApiBase()}/api/signals/active`);
    if (res.ok) {
      const d = await res.json();
      setActiveSignals(d.signals ?? []);
    }
  } catch { /* fail silently */ }
};
loadActive();
const activeInterval = setInterval(loadActive, 30_000);
// add activeInterval to cleanup: return () => { clearInterval(interval); clearInterval(activeInterval); };
```

- [ ] **Step 3: Add the SkewPill and StreakBar sub-components**

Add before the CommandStrip function:

```typescript
function SkewPill({ signals }: { signals: ActiveSignal[] }) {
  const longs = signals.filter(s => s.direction === 1).length;
  const shorts = signals.filter(s => s.direction === -1).length;
  const total = longs + shorts;
  if (total === 0) return null;
  const longPct = longs / total;
  const skewed = longPct >= 0.9 || longPct <= 0.1;
  return (
    <div className="flex flex-col gap-0.5 px-4 py-2 border-r border-[var(--border-subtle)] min-w-[100px]">
      <span className="text-[0.5rem] font-semibold uppercase tracking-widest text-[var(--text-muted)]">
        Live Skew
      </span>
      <span className="text-sm font-bold font-data leading-none"
        style={{ color: skewed ? "var(--amber)" : "var(--text-secondary)" }}>
        ▲{longs} / ▼{shorts}
      </span>
      <div className="h-1 rounded overflow-hidden bg-[var(--bg-elevated)] mt-0.5" style={{ width: "60px" }}>
        <div className="h-full rounded"
          style={{ width: `${longPct * 100}%`, backgroundColor: "var(--green)" }} />
      </div>
    </div>
  );
}

function StreakBar({ outcomes }: { outcomes: RecentOutcome[] }) {
  if (!outcomes || outcomes.length === 0) return null;
  const WIN_OUTCOMES = new Set(["target_1", "target_1_2", "target_full"]);
  return (
    <div className="flex flex-col gap-0.5 px-4 py-2 border-r border-[var(--border-subtle)] min-w-[140px]">
      <span className="text-[0.5rem] font-semibold uppercase tracking-widest text-[var(--text-muted)]">
        Last 10
      </span>
      <div className="flex gap-0.5 items-center mt-0.5">
        {outcomes.map((o, i) => {
          const isWin = WIN_OUTCOMES.has(o.outcome);
          const isExpired = o.outcome === "never_activated" || o.outcome === "ttl_expired";
          const bg = isWin ? "var(--green)" : isExpired ? "var(--text-muted)" : "var(--red)";
          return (
            <div key={i} className="w-3 h-3 rounded-sm"
              style={{ backgroundColor: bg, opacity: 0.85 }}
              title={`${o.outcome}${o.pnl_r != null ? ` (${o.pnl_r >= 0 ? "+" : ""}${o.pnl_r.toFixed(1)}R)` : ""}`}
            />
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Add the two new pills to the JSX**

In the CommandStrip return, before the closing `</div>`, add:

```tsx
      <SkewPill signals={activeSignals} />
      {s?.recent_outcomes && <StreakBar outcomes={s.recent_outcomes} />}
```

Also update `SignalStatsData` in `dashboard/src/lib/types.ts` to add:

```typescript
  recent_outcomes?: RecentOutcome[];
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd dashboard && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/components/signals/command-strip.tsx dashboard/src/lib/types.ts
git commit -m "feat(dashboard): add live skew pill and last-10 streak bar to command strip"
```

---

## Task 9: Live Signal Cards zone

**Files:**
- Create: `dashboard/src/components/signals/live-signal-cards.tsx`

- [ ] **Step 1: Create the SignalCard sub-component**

Create `dashboard/src/components/signals/live-signal-cards.tsx`:

```typescript
"use client";

import { useState, useEffect, useMemo } from "react";
import { getApiBase } from "@/lib/api";
import type { ActiveSignal } from "@/lib/types";
import { fmtNum, fmtTimeHMS } from "@/lib/format";
import { TrendingUp, TrendingDown, AlertTriangle, Zap } from "lucide-react";

const REGIME_LABELS: Record<number, string> = { 0: "TREND", 1: "RANGE", 2: "VOL" };
const REGIME_COLORS: Record<number, string> = {
  0: "var(--green)",
  1: "var(--amber)",
  2: "var(--red)",
};

const BUCKET_ORDER = ["trend", "momentum", "structure", "institutional", "regime", "pattern"];

function RegimeBadge({ regime }: { regime: number | null }) {
  if (regime == null) return null;
  return (
    <span className="text-[0.48rem] font-bold px-1 py-0.5 rounded"
      style={{
        color: REGIME_COLORS[regime] ?? "var(--text-muted)",
        border: `1px solid ${REGIME_COLORS[regime] ?? "var(--border-subtle)"}`,
        backgroundColor: "rgba(0,0,0,0.3)",
      }}>
      {REGIME_LABELS[regime] ?? `R${regime}`}
    </span>
  );
}

function CISBucketBars({ buckets }: { buckets: Record<string, number> | null }) {
  if (!buckets) return null;
  const sorted = BUCKET_ORDER
    .filter(k => k in buckets)
    .map(k => ({ key: k, val: buckets[k] }))
    .sort((a, b) => Math.abs(b.val) - Math.abs(a.val))
    .slice(0, 2);

  return (
    <div className="flex flex-col gap-0.5">
      {sorted.map(({ key, val }) => (
        <div key={key} className="flex items-center gap-1">
          <span className="text-[0.45rem] text-[var(--text-muted)] w-[52px] shrink-0 truncate">{key}</span>
          <div className="flex-1 h-1 rounded overflow-hidden bg-[var(--bg-elevated)]">
            <div className="h-full rounded"
              style={{
                width: `${Math.min(100, Math.abs(val) * 100)}%`,
                backgroundColor: val >= 0 ? "var(--green)" : "var(--red)",
              }} />
          </div>
          <span className="text-[0.45rem] font-data w-[28px] text-right shrink-0"
            style={{ color: val >= 0 ? "var(--green)" : "var(--red)" }}>
            {val >= 0 ? "+" : ""}{fmtNum(val, 2)}
          </span>
        </div>
      ))}
    </div>
  );
}

function AgeDots({ barsElapsed, ttlBars }: { barsElapsed: number; ttlBars: number }) {
  const DOTS = 10;
  const filled = Math.min(DOTS, Math.round((barsElapsed / Math.max(ttlBars, 1)) * DOTS));
  const ratio = barsElapsed / Math.max(ttlBars, 1);
  const color = ratio < 0.5 ? "var(--text-secondary)" : ratio < 0.8 ? "var(--amber)" : "var(--red)";
  return (
    <span className="flex gap-0.5 items-center">
      {Array.from({ length: DOTS }, (_, i) => (
        <span key={i} className="inline-block w-1.5 h-1.5 rounded-full"
          style={{ backgroundColor: i < filled ? color : "var(--bg-elevated)" }} />
      ))}
    </span>
  );
}

function SignalCard({
  signal,
  isConflict,
  allActive,
}: {
  signal: ActiveSignal;
  isConflict: boolean;
  allActive: ActiveSignal[];
}) {
  const isHero = signal.signal_tier === "hero";
  const isLong = signal.direction === 1;
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!signal.signal_computed_at) return;
    const firedAt = new Date(signal.signal_computed_at).getTime();
    const tick = () => setElapsed(Math.floor((Date.now() - firedAt) / 60000));
    tick();
    const id = setInterval(tick, 30_000);
    return () => clearInterval(id);
  }, [signal.signal_computed_at]);

  const isRecent = elapsed < 5;
  const rr = signal.risk_reward_ratio;
  const ttlBars = signal.ttl_bars ?? 10;
  const barsElapsed = elapsed; // bars ≈ minutes for 1m TF; close enough for display

  // Regime shift: another signal on same (symbol, tf) with different regime
  const hasRegimeShift = allActive.some(
    s => s.signal_id !== signal.signal_id
      && s.symbol === signal.symbol
      && s.timeframe === signal.timeframe
      && s.hmm_regime_at_fire !== signal.hmm_regime_at_fire
  );

  const isStale = signal.staleness_score != null && signal.staleness_score > 0;

  return (
    <div
      className="shrink-0 flex flex-col gap-1.5 p-2 rounded"
      style={{
        width: "188px",
        background: "var(--bg-surface)",
        border: `1px solid ${isHero ? "var(--blue)" : "var(--border-subtle)"}`,
        borderLeft: `3px solid ${isHero ? "var(--blue)" : "transparent"}`,
        boxShadow: isHero ? "0 0 12px rgba(59,130,246,0.12)" : undefined,
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-1">
        <div className="flex items-center gap-1">
          {isRecent && (
            <span className="w-1.5 h-1.5 rounded-full animate-pulse shrink-0"
              style={{ backgroundColor: "var(--blue)" }} />
          )}
          <span className="text-[0.75rem] font-bold font-data"
            style={{ color: isLong ? "var(--green)" : "var(--red)" }}>
            {signal.symbol}
          </span>
          {isLong
            ? <TrendingUp size={10} style={{ color: "var(--green)" }} />
            : <TrendingDown size={10} style={{ color: "var(--red)" }} />}
        </div>
        <div className="flex items-center gap-1">
          <RegimeBadge regime={signal.hmm_regime_at_fire} />
          <span className="text-[0.45rem] text-[var(--text-muted)]">{signal.timeframe}</span>
        </div>
      </div>

      {/* Setup */}
      <div className="text-[0.52rem] text-[var(--text-secondary)] truncate">
        {signal.setup_plugin.replace(/^(trad_|ind_|smc_)/, "")}
      </div>

      {/* CIS + buckets */}
      <div className="flex flex-col gap-0.5">
        <span className="text-[0.55rem] font-data font-bold"
          style={{ color: (signal.cis_score ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
          CIS {signal.cis_score != null ? ((signal.cis_score >= 0 ? "+" : "") + fmtNum(signal.cis_score, 2)) : "—"}
        </span>
        <CISBucketBars buckets={signal.bucket_scores} />
      </div>

      {/* Prices */}
      <div className="flex gap-1 text-[0.52rem] font-data">
        <span className="text-[var(--text-muted)]">E</span>
        <span className="text-[var(--text-primary)]">{signal.entry_price != null ? fmtNum(signal.entry_price, 2) : "—"}</span>
        <span className="text-[var(--text-muted)]">SL</span>
        <span style={{ color: "var(--red)" }}>{signal.stop_loss != null ? fmtNum(signal.stop_loss, 2) : "—"}</span>
        <span className="text-[var(--text-muted)]">T1</span>
        <span style={{ color: "var(--green)" }}>{signal.profit_target != null ? fmtNum(signal.profit_target, 2) : "—"}</span>
      </div>

      {/* R:R + age dots */}
      <div className="flex items-center justify-between">
        <span className="text-[0.5rem] font-data text-[var(--text-secondary)]">
          {rr != null ? `R:R ${fmtNum(rr, 1)}x` : ""}
        </span>
        <AgeDots barsElapsed={barsElapsed} ttlBars={ttlBars} />
        <span className="text-[0.48rem] text-[var(--text-muted)]">{barsElapsed}b</span>
      </div>

      {/* Badges */}
      {(isConflict || hasRegimeShift || isStale) && (
        <div className="flex gap-1 flex-wrap">
          {isConflict && (
            <span className="flex items-center gap-0.5 text-[0.45rem] px-1 py-0.5 rounded"
              style={{ color: "var(--red)", border: "1px solid var(--red)", backgroundColor: "rgba(255,71,87,0.08)" }}>
              <Zap size={8} /> CONFLICT
            </span>
          )}
          {hasRegimeShift && (
            <span className="flex items-center gap-0.5 text-[0.45rem] px-1 py-0.5 rounded"
              style={{ color: "var(--amber)", border: "1px solid var(--amber)", backgroundColor: "rgba(245,158,11,0.08)" }}>
              <AlertTriangle size={8} /> REGIME SHIFT
            </span>
          )}
          {isStale && (
            <span className="flex items-center gap-0.5 text-[0.45rem] px-1 py-0.5 rounded"
              style={{ color: "var(--amber)", border: "1px solid var(--amber)", backgroundColor: "rgba(245,158,11,0.08)" }}>
              <AlertTriangle size={8} /> STALE
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export function LiveSignalCards() {
  const [signals, setSignals] = useState<ActiveSignal[]>([]);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch(`${getApiBase()}/api/signals/active`);
        if (res.ok) {
          const d = await res.json();
          setSignals(d.signals ?? []);
        }
      } catch { /* fail silently */ }
    };
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, []);

  const sorted = useMemo(() => {
    return [...signals].sort((a, b) => {
      const tierOrder: Record<string, number> = { hero: 0, monitored: 1, candidate: 2 };
      const ta = tierOrder[a.signal_tier] ?? 3;
      const tb = tierOrder[b.signal_tier] ?? 3;
      if (ta !== tb) return ta - tb;
      return Math.abs(b.cis_score ?? 0) - Math.abs(a.cis_score ?? 0);
    });
  }, [signals]);

  // Conflict detection: (symbol, timeframe) pairs with opposing directions
  const conflictIds = useMemo(() => {
    const ids = new Set<string>();
    const byKey = new Map<string, ActiveSignal[]>();
    for (const s of signals) {
      const key = `${s.symbol}|${s.timeframe}`;
      if (!byKey.has(key)) byKey.set(key, []);
      byKey.get(key)!.push(s);
    }
    for (const group of byKey.values()) {
      if (group.some(s => s.direction === 1) && group.some(s => s.direction === -1)) {
        group.forEach(s => ids.add(s.signal_id));
      }
    }
    return ids;
  }, [signals]);

  if (sorted.length === 0) {
    return (
      <div className="flex items-center justify-center h-[120px] rounded"
        style={{ border: "1px solid var(--border-subtle)", background: "var(--bg-surface)" }}>
        <span className="text-[0.62rem] text-[var(--text-muted)] italic">
          No active signals — market quiet
        </span>
      </div>
    );
  }

  return (
    <div className="flex gap-2 overflow-x-auto pb-1" style={{ scrollbarWidth: "none" }}>
      {sorted.map(sig => (
        <SignalCard
          key={sig.signal_id}
          signal={sig}
          isConflict={conflictIds.has(sig.signal_id)}
          allActive={signals}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd dashboard && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/signals/live-signal-cards.tsx
git commit -m "feat(dashboard): add LiveSignalCards zone with regime/conflict/staleness badges"
```

---

## Task 10: SetupRegimeHeatMap component

**Files:**
- Create: `dashboard/src/components/signals/setup-regime-heatmap.tsx`

- [ ] **Step 1: Create the component**

Create `dashboard/src/components/signals/setup-regime-heatmap.tsx`:

```typescript
"use client";

import { useState, useEffect, useMemo } from "react";
import { getApiBase } from "@/lib/api";
import type { HeatMapCell } from "@/lib/types";
import { fmtNum } from "@/lib/format";

const REGIME_LABELS = ["Trend", "Range", "Vol"];

type Metric = "avg_r" | "win_rate";

function cellBg(value: number | null, n: number): string {
  if (value == null || n === 0) return "var(--bg-elevated)";
  const nOpacity = Math.min(1, n / 30) * 0.75 + 0.15;
  const intensity = Math.min(1, Math.abs(value) / 0.3);
  const alpha = nOpacity * intensity;
  if (value > 0) return `rgba(0, 220, 130, ${alpha.toFixed(2)})`;
  return `rgba(255, 71, 87, ${alpha.toFixed(2)})`;
}

function cellText(value: number | null, metric: Metric): string {
  if (value == null) return "—";
  if (metric === "avg_r") return (value >= 0 ? "+" : "") + fmtNum(value, 2) + "R";
  return fmtNum(value * 100, 1) + "%";
}

export function SetupRegimeHeatMap({
  onCellClick,
}: {
  onCellClick?: (setup: string, regime: number) => void;
}) {
  const [cells, setCells] = useState<HeatMapCell[]>([]);
  const [metric, setMetric] = useState<Metric>("avg_r");

  useEffect(() => {
    fetch(`${getApiBase()}/api/signals/heatmap`)
      .then(r => r.ok ? r.json() : { cells: [] })
      .then(d => setCells(d.cells ?? []))
      .catch(() => {});
  }, []);

  // Build grid: top 15 setups (by first-seen order = highest volume) × 3 regimes
  const { setups, grid } = useMemo(() => {
    const seenSetups: string[] = [];
    const lookup = new Map<string, HeatMapCell>();
    for (const c of cells) {
      const key = `${c.setup_plugin}|${c.regime}`;
      lookup.set(key, c);
      if (!seenSetups.includes(c.setup_plugin)) seenSetups.push(c.setup_plugin);
    }
    return {
      setups: seenSetups.slice(0, 15),
      grid: (setup: string, regime: number) => lookup.get(`${setup}|${regime}`) ?? null,
    };
  }, [cells]);

  if (setups.length === 0) {
    return (
      <div className="flex items-center justify-center h-[160px]"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "4px" }}>
        <span className="text-[0.6rem] text-[var(--text-muted)] italic">Loading heat map…</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 p-3 rounded"
      style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="text-[0.52rem] font-bold uppercase tracking-widest text-[var(--text-muted)]">
          Setup × Regime
        </span>
        <div className="flex gap-1">
          {(["avg_r", "win_rate"] as Metric[]).map(m => (
            <button key={m} onClick={() => setMetric(m)}
              className="text-[0.5rem] px-1.5 py-0.5 rounded font-semibold"
              style={{
                background: metric === m ? "var(--bg-elevated)" : "transparent",
                color: metric === m ? "var(--text-primary)" : "var(--text-muted)",
                border: `1px solid ${metric === m ? "var(--border-default)" : "var(--border-subtle)"}`,
              }}>
              {m === "avg_r" ? "Avg R" : "Win%"}
            </button>
          ))}
        </div>
      </div>

      {/* Column headers */}
      <div className="flex items-center gap-0.5" style={{ paddingLeft: "120px" }}>
        {REGIME_LABELS.map(l => (
          <div key={l} className="text-[0.48rem] font-semibold uppercase text-[var(--text-muted)] text-center"
            style={{ width: "64px" }}>
            {l}
          </div>
        ))}
      </div>

      {/* Rows */}
      <div className="flex flex-col gap-0.5">
        {setups.map(setup => (
          <div key={setup} className="flex items-center gap-0.5">
            <div className="text-[0.52rem] font-data text-[var(--text-secondary)] truncate shrink-0"
              style={{ width: "116px" }} title={setup}>
              {setup.replace(/^(trad_|ind_|smc_)/, "")}
            </div>
            {[0, 1, 2].map(regime => {
              const cell = grid(setup, regime);
              const value = cell ? (metric === "avg_r" ? cell.avg_r : cell.win_rate) : null;
              const n = cell?.n ?? 0;
              return (
                <div key={regime}
                  onClick={() => cell && onCellClick?.(setup, regime)}
                  className="flex items-center justify-center rounded text-[0.5rem] font-data font-bold shrink-0"
                  style={{
                    width: "64px", height: "20px",
                    backgroundColor: cellBg(value, n),
                    color: value != null && value !== 0 ? "var(--text-primary)" : "var(--text-muted)",
                    cursor: cell ? "pointer" : "default",
                    opacity: n === 0 ? 0.2 : 1,
                  }}
                  title={cell ? `N=${cell.n}  Win ${fmtNum((cell.win_rate ?? 0) * 100, 1)}%  Avg R ${fmtNum(cell.avg_r ?? 0, 3)}` : "No data"}>
                  {cellText(value, metric)}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd dashboard && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/components/signals/setup-regime-heatmap.tsx
git commit -m "feat(dashboard): add SetupRegimeHeatMap component"
```

---

## Task 11: EdgeSparkline and IntradayHeatMap components

**Files:**
- Create: `dashboard/src/components/signals/edge-sparkline.tsx`
- Create: `dashboard/src/components/signals/intraday-heatmap.tsx`

- [ ] **Step 1: Create EdgeSparkline**

Create `dashboard/src/components/signals/edge-sparkline.tsx`:

```typescript
"use client";

import { useState, useEffect, useMemo } from "react";
import { getApiBase } from "@/lib/api";
import type { EdgeSeriesPoint } from "@/lib/types";
import { fmtNum } from "@/lib/format";

const W = 280, H = 72, PAD = { top: 8, bottom: 8, left: 4, right: 4 };

export function EdgeSparkline() {
  const [series, setSeries] = useState<EdgeSeriesPoint[]>([]);

  useEffect(() => {
    fetch(`${getApiBase()}/api/signals/edge-series`)
      .then(r => r.ok ? r.json() : { series: [] })
      .then(d => setSeries(d.series ?? []))
      .catch(() => {});
  }, []);

  const { points, zeroY, areaAbove, areaBelow, rollingPoints } = useMemo(() => {
    if (series.length < 2) return { points: "", zeroY: H / 2, areaAbove: "", areaBelow: "", rollingPoints: "" };

    const values = series.map(d => d.avg_r ?? 0);
    const minV = Math.min(0, ...values);
    const maxV = Math.max(0, ...values);
    const range = maxV - minV || 0.01;
    const innerW = W - PAD.left - PAD.right;
    const innerH = H - PAD.top - PAD.bottom;

    const sx = (i: number) => PAD.left + (i / (series.length - 1)) * innerW;
    const sy = (v: number) => PAD.top + innerH - ((v - minV) / range) * innerH;
    const zY = sy(0);

    const pts = series.map((d, i) => `${sx(i)},${sy(d.avg_r ?? 0)}`).join(" ");

    // Rolling 7-day average
    const rolling = series.map((_, i) => {
      const slice = series.slice(Math.max(0, i - 6), i + 1);
      const avg = slice.reduce((s, p) => s + (p.avg_r ?? 0), 0) / slice.length;
      return avg;
    });
    const rPts = rolling.map((v, i) => `${sx(i)},${sy(v)}`).join(" ");

    // Area above zero (green fill)
    const abovePts = series
      .map((d, i) => ({ x: sx(i), y: sy(Math.max(0, d.avg_r ?? 0)) }));
    const above = [
      `${abovePts[0].x},${zY}`,
      ...abovePts.map(p => `${p.x},${p.y}`),
      `${abovePts[abovePts.length - 1].x},${zY}`,
    ].join(" ");

    const belowPts = series
      .map((d, i) => ({ x: sx(i), y: sy(Math.min(0, d.avg_r ?? 0)) }));
    const below = [
      `${belowPts[0].x},${zY}`,
      ...belowPts.map(p => `${p.x},${p.y}`),
      `${belowPts[belowPts.length - 1].x},${zY}`,
    ].join(" ");

    return { points: pts, zeroY: zY, areaAbove: above, areaBelow: below, rollingPoints: rPts };
  }, [series]);

  const last = series[series.length - 1];

  if (series.length === 0) {
    return (
      <div className="flex items-center justify-center h-[88px]"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "4px" }}>
        <span className="text-[0.6rem] text-[var(--text-muted)] italic">Loading…</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1 p-3 rounded"
      style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}>
      <div className="flex items-center justify-between">
        <span className="text-[0.52rem] font-bold uppercase tracking-widest text-[var(--text-muted)]">
          30d Edge
        </span>
        {last && (
          <span className="text-[0.55rem] font-data"
            style={{ color: (last.avg_r ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
            today {(last.avg_r ?? 0) >= 0 ? "+" : ""}{fmtNum(last.avg_r ?? 0, 3)}R
          </span>
        )}
      </div>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        {/* Zero line */}
        <line x1={PAD.left} y1={zeroY} x2={W - PAD.right} y2={zeroY}
          stroke="var(--border-default)" strokeWidth="0.5" strokeDasharray="3 3" />
        {/* Green area above zero */}
        <polygon points={areaAbove} fill="rgba(0,220,130,0.08)" />
        {/* Red area below zero */}
        <polygon points={areaBelow} fill="rgba(255,71,87,0.08)" />
        {/* Rolling 7d line */}
        <polyline points={rollingPoints} fill="none"
          stroke="rgba(255,255,255,0.2)" strokeWidth="1" />
        {/* Daily avg R line */}
        <polyline points={points} fill="none"
          stroke="var(--cyan, #06b6d4)" strokeWidth="1.5" />
        {/* Today dot */}
        {last && series.length > 1 && (() => {
          const lx = W - PAD.right;
          const innerH2 = H - PAD.top - PAD.bottom;
          const values = series.map(d => d.avg_r ?? 0);
          const minV = Math.min(0, ...values);
          const maxV = Math.max(0, ...values);
          const range = maxV - minV || 0.01;
          const ly = PAD.top + innerH2 - (((last.avg_r ?? 0) - minV) / range) * innerH2;
          return (
            <circle cx={lx} cy={ly} r={3}
              fill={(last.avg_r ?? 0) >= 0 ? "var(--green)" : "var(--red)"}
              stroke="var(--bg-surface)" strokeWidth="1" />
          );
        })()}
      </svg>
    </div>
  );
}
```

- [ ] **Step 2: Create IntradayHeatMap**

Create `dashboard/src/components/signals/intraday-heatmap.tsx`:

```typescript
"use client";

import { useState, useEffect } from "react";
import { getApiBase } from "@/lib/api";
import type { IntradayCell } from "@/lib/types";
import { fmtNum } from "@/lib/format";

const DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri"];
const HOURS = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17];

function cellBg(avgR: number | null, n: number): string {
  if (avgR == null || n === 0) return "var(--bg-elevated)";
  const opacity = Math.min(1, n / 50) * 0.7 + 0.15;
  const intensity = Math.min(1, Math.abs(avgR) / 0.25);
  const a = (opacity * intensity).toFixed(2);
  return avgR > 0 ? `rgba(0,220,130,${a})` : `rgba(255,71,87,${a})`;
}

export function IntradayHeatMap() {
  const [cells, setCells] = useState<IntradayCell[]>([]);

  useEffect(() => {
    fetch(`${getApiBase()}/api/signals/intraday-heatmap`)
      .then(r => r.ok ? r.json() : { cells: [] })
      .then(d => setCells(d.cells ?? []))
      .catch(() => {});
  }, []);

  const lookup = new Map<string, IntradayCell>();
  for (const c of cells) lookup.set(`${c.hour}|${c.dow}`, c);

  if (cells.length === 0) {
    return (
      <div className="flex items-center justify-center h-[100px]"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "4px" }}>
        <span className="text-[0.6rem] text-[var(--text-muted)] italic">Loading…</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5 p-3 rounded"
      style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}>
      <span className="text-[0.52rem] font-bold uppercase tracking-widest text-[var(--text-muted)]">
        Intraday Edge
      </span>

      {/* Column headers (DOW) */}
      <div className="flex items-center gap-0.5" style={{ paddingLeft: "28px" }}>
        {DOW_LABELS.map(d => (
          <div key={d} className="text-[0.45rem] font-semibold text-[var(--text-muted)] text-center"
            style={{ width: "36px" }}>
            {d}
          </div>
        ))}
      </div>

      {/* Rows (hour) */}
      {HOURS.map(hour => (
        <div key={hour} className="flex items-center gap-0.5">
          <div className="text-[0.45rem] text-[var(--text-muted)] text-right shrink-0"
            style={{ width: "24px" }}>
            {hour}:00
          </div>
          {[1, 2, 3, 4, 5].map(dow => {
            const cell = lookup.get(`${hour}|${dow}`) ?? null;
            return (
              <div key={dow}
                className="flex items-center justify-center rounded text-[0.42rem] font-data shrink-0"
                style={{
                  width: "36px", height: "16px",
                  backgroundColor: cellBg(cell?.avg_r ?? null, cell?.n ?? 0),
                  color: "var(--text-primary)",
                  opacity: (cell?.n ?? 0) === 0 ? 0.2 : 1,
                }}
                title={cell ? `N=${cell.n}  Avg R ${fmtNum(cell.avg_r ?? 0, 3)}` : "No data"}>
                {cell?.avg_r != null ? ((cell.avg_r >= 0 ? "+" : "") + fmtNum(cell.avg_r, 2)) : ""}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd dashboard && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/signals/edge-sparkline.tsx dashboard/src/components/signals/intraday-heatmap.tsx
git commit -m "feat(dashboard): add EdgeSparkline (SVG) and IntradayHeatMap components"
```

---

## Task 12: EdgeIntelligenceStrip container + wire everything into SignalsPage

**Files:**
- Create: `dashboard/src/components/signals/edge-intelligence-strip.tsx`
- Modify: `dashboard/src/components/signals/signals-page.tsx`

- [ ] **Step 1: Create the EdgeIntelligenceStrip container**

Create `dashboard/src/components/signals/edge-intelligence-strip.tsx`:

```typescript
"use client";

import { SetupRegimeHeatMap } from "./setup-regime-heatmap";
import { EdgeSparkline } from "./edge-sparkline";
import { IntradayHeatMap } from "./intraday-heatmap";

export function EdgeIntelligenceStrip({
  onHeatMapCellClick,
}: {
  onHeatMapCellClick?: (setup: string, regime: number) => void;
}) {
  return (
    <div className="grid gap-3" style={{ gridTemplateColumns: "1fr 1fr" }}>
      {/* Left: Setup × Regime heat map */}
      <SetupRegimeHeatMap onCellClick={onHeatMapCellClick} />

      {/* Right: sparkline + intraday stacked */}
      <div className="flex flex-col gap-3">
        <EdgeSparkline />
        <IntradayHeatMap />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Update SignalsPage to add Zone 2 and Zone 3**

Read `dashboard/src/components/signals/signals-page.tsx` then update:

```typescript
"use client";

import { useState, useCallback } from "react";
import { CommandStrip } from "./command-strip";
import { AttributionRow } from "./attribution-row";
import { ClusterStrip } from "./cluster-strip";
import { FilterBar, FilterState, defaultFilters } from "./filter-bar";
import { SignalLedger } from "./signal-ledger";
import { LiveSignalCards } from "./live-signal-cards";
import { EdgeIntelligenceStrip } from "./edge-intelligence-strip";

export function SignalsPage() {
  const [filters, setFilters] = useState<FilterState>(defaultFilters);

  const handleFilterChange = useCallback((next: Partial<FilterState>) => {
    setFilters((prev) => ({ ...prev, ...next }));
  }, []);

  const handleHeatMapClick = useCallback((setup: string, regime: number) => {
    setFilters((prev) => ({
      ...prev,
      setup_plugin: [setup],
      regime: [regime],
    }));
  }, []);

  return (
    <div className="min-h-screen flex flex-col bg-[var(--bg-base)]">
      <div className="sticky top-0 z-40 border-b border-[var(--border-subtle)]"
           style={{ background: "rgba(10, 14, 20, 0.95)" }}>
        <CommandStrip />
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-[1600px] mx-auto px-4 py-4 flex flex-col gap-4">
          {/* Zone 2 — Live Signal Cards */}
          <LiveSignalCards />

          {/* Zone 3 — Edge Intelligence Strip */}
          <EdgeIntelligenceStrip onHeatMapCellClick={handleHeatMapClick} />

          {/* Zone 4 — Attribution Row */}
          <AttributionRow onSetupClick={(setup) => handleFilterChange({ setup_plugin: [setup] })}
                          onAssetClassClick={(ac) => handleFilterChange({ asset_class: [ac] })} />

          {/* Zone 5 — Cluster Strip */}
          <ClusterStrip onClusterClick={(symbols) => handleFilterChange({ symbol: symbols })} />

          {/* Zone 6 — Filter Bar */}
          <FilterBar filters={filters} onChange={handleFilterChange} />

          {/* Zone 7 — Signal Ledger */}
          <SignalLedger filters={filters} />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd dashboard && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/signals/edge-intelligence-strip.tsx dashboard/src/components/signals/signals-page.tsx
git commit -m "feat(dashboard): wire LiveSignalCards and EdgeIntelligenceStrip into SignalsPage"
```

---

## Task 13: FilterBar — add regime pill toggle + client-side regime filtering

**Files:**
- Modify: `dashboard/src/components/signals/filter-bar.tsx`

- [ ] **Step 1: Read the current filter-bar.tsx fully**

Read `dashboard/src/components/signals/filter-bar.tsx`.

- [ ] **Step 2: Add `REGIME_OPTIONS` and the regime pill toggle**

Add the constant near the top with other option arrays:

```typescript
const REGIME_OPTIONS = [
  { value: 0, label: "Trend" },
  { value: 1, label: "Range" },
  { value: 2, label: "Vol" },
] as const;
```

Add a `RegimePillToggle` component (or reuse PillToggle with number type). Since `PillToggle` is generic over strings, add a numeric variant:

```typescript
function RegimePillToggle({
  selected,
  onChange,
}: {
  selected: number[];
  onChange: (val: number[]) => void;
}) {
  const toggle = (v: number) => {
    if (selected.includes(v)) onChange(selected.filter(x => x !== v));
    else onChange([...selected, v]);
  };
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <span className="text-[0.52rem] uppercase tracking-widest text-[var(--text-muted)] shrink-0">
        Regime
      </span>
      {REGIME_OPTIONS.map(({ value, label }) => (
        <button key={value} onClick={() => toggle(value)}
          className="px-2 py-0.5 rounded text-[0.6rem] font-semibold transition-colors"
          style={{
            backgroundColor: selected.includes(value) ? "var(--bg-elevated)" : "transparent",
            color: selected.includes(value) ? "var(--text-primary)" : "var(--text-muted)",
            border: `1px solid ${selected.includes(value) ? "var(--border-right)" : "var(--border-subtle)"}`,
          }}>
          {label}
        </button>
      ))}
    </div>
  );
}
```

In the `FilterBar` JSX, add after the Tier PillToggle:

```tsx
      <RegimePillToggle
        selected={filters.regime}
        onChange={(v) => onChange({ regime: v })}
      />
```

- [ ] **Step 3: Add regime to the client-side filter in signal-ledger.tsx**

Read `dashboard/src/components/signals/signal-ledger.tsx`. In the `filtered` useMemo, add after the existing `filters.status` check:

```typescript
      if (
        filters.regime.length > 0 &&
        (s.hmm_regime_at_fire == null || !filters.regime.includes(s.hmm_regime_at_fire))
      )
        return false;
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd dashboard && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/components/signals/filter-bar.tsx dashboard/src/components/signals/signal-ledger.tsx
git commit -m "feat(dashboard): add regime filter to FilterBar with client-side filtering"
```

---

## Task 14: Signal Ledger — new columns (Regime dot, R:R, Exit, Age/Cap)

**Files:**
- Modify: `dashboard/src/components/signals/signal-ledger.tsx`

- [ ] **Step 1: Read the full signal-ledger.tsx**

Read `dashboard/src/components/signals/signal-ledger.tsx`.

- [ ] **Step 2: Add helper functions for new columns**

Add near the top of the file, after existing imports:

```typescript
const REGIME_DOT_COLORS: Record<number, string> = {
  0: "var(--green)",
  1: "var(--amber)",
  2: "var(--red)",
};

const EXIT_COLORS: Record<string, string> = {
  stop_loss: "var(--red)",
  ttl_expired: "var(--text-muted)",
  target_1: "rgba(0,220,130,0.7)",
  target_2: "var(--green)",
  target_3: "var(--cyan, #06b6d4)",
  condition_expired: "var(--text-muted)",
};

const STATUS_COLORS: Record<string, string> = {
  pending: "var(--text-muted)",
  active: "var(--cyan, #06b6d4)",
  regime_suppressed: "var(--red)",
  expired: "var(--text-muted)",
};

function ExitCell({ signal }: { signal: LedgerSignal }) {
  const live = signal.status === "pending" || signal.status === "active";
  if (live) {
    return (
      <span className="text-[0.5rem] font-semibold px-1 py-0 rounded"
        style={{
          color: STATUS_COLORS[signal.status] ?? "var(--text-muted)",
          border: `1px solid ${STATUS_COLORS[signal.status] ?? "var(--border-subtle)"}`,
          backgroundColor: "rgba(0,0,0,0.2)",
        }}>
        {signal.status}
      </span>
    );
  }
  const reason = signal.exit_reason ?? signal.status;
  const label = reason === "stop_loss" ? "SL"
    : reason === "ttl_expired" ? "TTL"
    : reason === "target_1" ? "T1"
    : reason === "target_2" ? "T2"
    : reason === "target_3" ? "T3"
    : reason?.toUpperCase().slice(0, 4) ?? "—";
  return (
    <span className="text-[0.5rem] font-semibold px-1 py-0 rounded"
      style={{
        color: EXIT_COLORS[reason] ?? "var(--text-muted)",
        border: `1px solid ${EXIT_COLORS[reason] ?? "var(--border-subtle)"}`,
        backgroundColor: "rgba(0,0,0,0.2)",
      }}>
      {label}
    </span>
  );
}

function AgeCapCell({ signal }: { signal: LedgerSignal }) {
  const live = signal.status === "pending" || signal.status === "active";
  if (live) {
    if (signal.bars_in_trade == null || signal.ttl_bars == null)
      return <span className="text-[var(--text-muted)]">-</span>;
    const ratio = signal.bars_in_trade / signal.ttl_bars;
    const color = ratio < 0.5 ? "var(--text-secondary)"
      : ratio < 0.8 ? "var(--amber)"
      : "var(--red)";
    return (
      <span className="text-[0.6rem] font-data" style={{ color }}>
        {signal.bars_in_trade}b
      </span>
    );
  }
  if (signal.mfe != null && signal.mfe > 0 && signal.pnl_r != null) {
    const cap = signal.pnl_r / signal.mfe;
    const color = cap >= 0.7 ? "var(--green)" : cap >= 0.4 ? "var(--amber)" : "var(--red)";
    return (
      <span className="text-[0.6rem] font-data" style={{ color }}>
        {fmtNum(cap, 2)}
      </span>
    );
  }
  return <span className="text-[var(--text-muted)]">-</span>;
}
```

- [ ] **Step 3: Update LedgerRow to use new columns**

Replace the existing LedgerRow JSX with the new column layout. The full column order is:
`Time | Symbol | TF | Regime● | Setup | Dir | R:R | Tier | CIS | Exit | Outcome | PnL R | Age/Cap`

Replace the LedgerRow return JSX:

```tsx
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
        {timeStr ?? "-"}
      </span>
      {/* Symbol */}
      <span className="w-[70px] shrink-0 px-1 text-[0.65rem] font-bold font-data text-[var(--text-secondary)]">
        {signal.symbol}
      </span>
      {/* TF */}
      <span className="w-[36px] shrink-0 px-1 text-[0.6rem] font-data text-[var(--text-muted)]">
        {signal.timeframe}
      </span>
      {/* Regime dot */}
      <span className="w-[22px] shrink-0 px-1 flex items-center justify-center">
        <span className="inline-block w-2 h-2 rounded-full"
          style={{ backgroundColor: signal.hmm_regime_at_fire != null
            ? (REGIME_DOT_COLORS[signal.hmm_regime_at_fire] ?? "var(--text-muted)")
            : "var(--bg-elevated)" }}
          title={signal.hmm_regime_at_fire != null
            ? ["Trend","Range","Vol"][signal.hmm_regime_at_fire] ?? ""
            : "unknown"} />
      </span>
      {/* Setup */}
      <span className={`w-[130px] shrink-0 px-1 text-[0.62rem] font-data truncate ${tier === "candidate" ? "italic" : ""}`}
        style={{ color: "var(--text-secondary)" }}>
        {signal.setup_plugin.replace(/^(trad_|ind_|smc_)/, "")}
      </span>
      {/* Dir */}
      <span className="w-[28px] shrink-0 px-1 flex items-center justify-center">
        {isLong
          ? <TrendingUp size={10} style={{ color: "var(--green)" }} />
          : <TrendingDown size={10} style={{ color: "var(--red)" }} />}
      </span>
      {/* R:R */}
      <span className="w-[48px] shrink-0 px-1 text-right text-[0.62rem] font-data text-[var(--text-secondary)]">
        {signal.r_ratio != null ? `${fmtNum(signal.r_ratio, 1)}x` : "-"}
      </span>
      {/* Tier dot */}
      <span className="w-[22px] shrink-0 px-1 flex items-center justify-center">
        <TierDot tier={tier} />
      </span>
      {/* CIS */}
      <span className="w-[56px] shrink-0 px-1 text-right text-[0.62rem] font-data"
        style={{
          color: signal.cis_score != null
            ? signal.cis_score >= 0 ? "var(--green)" : "var(--red)"
            : "var(--text-muted)",
        }}>
        {cisStr}
      </span>
      {/* Exit */}
      <span className="w-[64px] shrink-0 px-1 flex items-center">
        <ExitCell signal={signal} />
      </span>
      {/* Outcome */}
      <span className="w-[96px] shrink-0 px-1">
        <OutcomeCell outcome={signal.outcome} />
      </span>
      {/* PnL R */}
      <span className="w-[56px] shrink-0 px-1 text-right text-[0.62rem] font-data"
        style={{ color: pnlColor }}>
        {signal.pnl_r != null
          ? (signal.outcome === "never_activated" ? "~" : "")
            + (signal.pnl_r >= 0 ? "+" : "")
            + fmtNum(signal.pnl_r, 1) + "R"
          : "-"}
      </span>
      {/* Age/Cap */}
      <span className="w-[52px] shrink-0 px-1 text-right">
        <AgeCapCell signal={signal} />
      </span>
    </div>
  );
```

- [ ] **Step 4: Update LedgerHeader to match new columns**

Replace the columns array in `LedgerHeader`:

```typescript
      [
        { label: "Time", w: 90 },
        { label: "Symbol", w: 70 },
        { label: "TF", w: 36 },
        { label: "●", w: 22 },
        { label: "Setup", w: 130 },
        { label: "Dir", w: 28 },
        { label: "R:R", w: 48, right: true },
        { label: "Tier", w: 22 },
        { label: "CIS", w: 56, right: true },
        { label: "Exit", w: 64 },
        { label: "Outcome", w: 96 },
        { label: "PnL R", w: 56, right: true },
        { label: "Age/Cap", w: 52, right: true },
      ]
```

- [ ] **Step 5: Verify TypeScript compiles**

```bash
cd dashboard && npx tsc --noEmit
```

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/components/signals/signal-ledger.tsx
git commit -m "feat(dashboard): upgrade ledger columns — regime dot, R:R, Exit, Age/Cap"
```

---

## Task 15: Redesign Signal Detail Panel

**Files:**
- Create: `dashboard/src/components/signals/signal-detail-panel.tsx`
- Modify: `dashboard/src/components/signals/signal-ledger.tsx` (remove inline panel, import new one)

- [ ] **Step 1: Create signal-detail-panel.tsx with all six sections**

Create `dashboard/src/components/signals/signal-detail-panel.tsx`:

```typescript
"use client";

import { useState, useEffect } from "react";
import { getApiBase, fetchJson } from "@/lib/api";
import { fmtNum, fmtTimeHMS } from "@/lib/format";
import { X, ChevronDown, ChevronUp, TrendingUp, TrendingDown } from "lucide-react";

const REGIME_LABELS: Record<number, string> = { 0: "TREND", 1: "RANGE", 2: "VOL" };
const REGIME_COLORS: Record<number, string> = {
  0: "var(--green)", 1: "var(--amber)", 2: "var(--red)",
};
const TIER_COLORS: Record<string, string> = {
  hero: "var(--blue)", monitored: "var(--text-secondary)", candidate: "var(--text-muted)",
};
const BUCKET_ORDER = ["trend", "momentum", "structure", "institutional", "regime", "pattern"];
const WIN_OUTCOMES = new Set(["target_1", "target_1_2", "target_full"]);

function SectionLabel({ label }: { label: string }) {
  return (
    <div className="text-[0.48rem] font-bold uppercase tracking-widest text-[var(--text-muted)] mt-3 mb-1">
      {label}
    </div>
  );
}

function PriceLadder({ detail }: { detail: Record<string, unknown> }) {
  const entry = detail.entry_price as number | null;
  const stop = detail.stop_loss as number | null;
  const targets = (detail.targets as number[]) ?? [];
  const direction = detail.direction as number;

  if (!entry || !stop) return null;

  const risk = Math.abs(entry - stop);
  const rAtLevel = (price: number) => risk > 0 ? ((price - entry) / risk) * direction : 0;

  const levels = [
    ...targets.map((t, i) => ({ label: `T${i + 1}`, price: t, r: rAtLevel(t) })).reverse(),
    { label: "ENTRY", price: entry, r: 0, isEntry: true },
    { label: "SL", price: stop, r: rAtLevel(stop) },
  ];

  return (
    <div className="flex flex-col gap-0.5">
      {levels.map(({ label, price, r, isEntry }) => (
        <div key={label} className="flex items-center gap-2 text-[0.6rem] font-data">
          <span className="w-[12px] text-[var(--text-muted)]"
            style={{ color: isEntry ? "var(--blue)" : undefined }}>
            {isEntry ? "●" : ""}
          </span>
          <span className="w-[32px] font-bold"
            style={{
              color: label === "SL" ? "var(--red)"
                : label === "ENTRY" ? "var(--text-primary)"
                : "var(--green)",
            }}>
            {label}
          </span>
          <span className="flex-1 text-[var(--text-secondary)]">{fmtNum(price, 2)}</span>
          {r !== 0 && (
            <span style={{ color: r > 0 ? "var(--green)" : "var(--red)" }}>
              {r >= 0 ? "+" : ""}{fmtNum(r, 1)}R
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function CISBuckets({ buckets }: { buckets: Record<string, number> | null }) {
  if (!buckets) return <span className="text-[0.55rem] text-[var(--text-muted)] italic">No CIS data</span>;

  const sorted = BUCKET_ORDER
    .filter(k => k in buckets)
    .map(k => ({ key: k, val: buckets[k] }))
    .sort((a, b) => Math.abs(b.val) - Math.abs(a.val));

  return (
    <div className="flex flex-col gap-1">
      {sorted.map(({ key, val }) => (
        <div key={key} className="flex items-center gap-1.5">
          <span className="text-[0.5rem] text-[var(--text-muted)] w-[68px] shrink-0 capitalize">{key}</span>
          <div className="flex-1 h-1.5 rounded overflow-hidden bg-[var(--bg-elevated)]">
            <div className="h-full rounded transition-all"
              style={{
                width: `${Math.min(100, Math.abs(val) * 100)}%`,
                backgroundColor: val >= 0 ? "var(--green)" : "var(--red)",
              }} />
          </div>
          <span className="text-[0.52rem] font-data w-[32px] text-right shrink-0"
            style={{ color: val >= 0 ? "var(--green)" : "var(--red)" }}>
            {val >= 0 ? "+" : ""}{fmtNum(val, 2)}
          </span>
        </div>
      ))}
    </div>
  );
}

function SetupEdge({ detail }: { detail: Record<string, unknown> }) {
  const setup = detail.setup_plugin as string;
  const symbol = detail.symbol as string;
  const wr = detail.setup_win_rate as number | null;
  const avgR = detail.setup_avg_pnl_r as number | null;
  const regime = detail.hmm_regime_at_fire as number | null;

  return (
    <div className="flex flex-col gap-1 text-[0.58rem] font-data">
      <div className="flex items-center justify-between">
        <span className="text-[var(--text-secondary)] truncate">{setup?.replace(/^(trad_|ind_|smc_)/, "")} on {symbol}</span>
      </div>
      <div className="flex gap-3">
        <span>Win <span style={{ color: wr != null && wr >= 0.1 ? "var(--green)" : "var(--amber)" }}>
          {wr != null ? fmtNum(wr * 100, 1) + "%" : "—"}
        </span></span>
        <span>Avg R <span style={{ color: avgR != null && avgR > 0 ? "var(--green)" : "var(--red)" }}>
          {avgR != null ? (avgR >= 0 ? "+" : "") + fmtNum(avgR, 3) : "—"}
        </span></span>
      </div>
      {regime != null && (
        <span style={{ color: "var(--text-muted)" }}>
          In {REGIME_LABELS[regime] ?? `regime ${regime}`} regime
        </span>
      )}
    </div>
  );
}

function CaptureBar({ detail }: { detail: Record<string, unknown> }) {
  const mae = detail.mae as number | null;
  const mfe = detail.mfe as number | null;
  const pnlR = detail.pnl_r as number | null;

  if (mae == null || mfe == null || pnlR == null) return null;

  const totalRange = Math.abs(mae) + Math.abs(mfe);
  if (totalRange === 0) return null;

  const maeW = Math.round((Math.abs(mae) / totalRange) * 100);
  const mfeW = 100 - maeW;
  const exitPct = mfe > 0 ? Math.min(100, Math.round((pnlR / mfe) * mfeW)) : 0;
  const capEff = mfe > 0 ? pnlR / mfe : null;

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1 text-[0.5rem] font-data">
        <span style={{ color: "var(--red)" }}>MAE {fmtNum(mae, 1)}R</span>
        <div className="flex-1 flex h-2 rounded overflow-hidden">
          <div style={{ width: `${maeW}%`, backgroundColor: "rgba(255,71,87,0.25)" }} />
          <div className="relative" style={{ width: `${mfeW}%`, backgroundColor: "rgba(0,220,130,0.15)" }}>
            {exitPct > 0 && (
              <div className="absolute left-0 top-0 h-full"
                style={{ width: `${exitPct}%`, backgroundColor: "rgba(0,220,130,0.5)" }} />
            )}
          </div>
        </div>
        <span style={{ color: "var(--green)" }}>MFE +{fmtNum(mfe, 1)}R</span>
      </div>
      {capEff != null && (
        <span className="text-[0.5rem] font-data text-[var(--text-muted)]">
          Captured {fmtNum(capEff * 100, 0)}% of available move
          (+{fmtNum(pnlR, 2)}R of {fmtNum(mfe, 2)}R)
        </span>
      )}
    </div>
  );
}

function Timeline({ detail }: { detail: Record<string, unknown> }) {
  const firedAt = detail.signal_computed_at as string | null;
  const activatedAt = detail.activated_at as string | null;
  const exitAt = detail.exit_at as string | null;
  const activationPrice = detail.activation_price as number | null;
  const barsToActivation = detail.bars_to_activation as number | null;
  const barsInTrade = detail.bars_in_trade as number | null;
  const exitReason = detail.exit_reason as string | null;
  const pnlR = detail.pnl_r as number | null;
  const status = detail.status as string;

  const events = [
    {
      ts: firedAt,
      label: "Signal fired",
      detail: null,
      active: true,
    },
    activatedAt
      ? {
          ts: activatedAt,
          label: `Activated at ${activationPrice != null ? fmtNum(activationPrice, 2) : "—"}`,
          detail: barsToActivation != null ? `${barsToActivation} bars to activation` : null,
          active: true,
        }
      : {
          ts: null,
          label: status === "pending" ? "Waiting for activation…" : "Never activated",
          detail: null,
          active: false,
        },
    exitAt
      ? {
          ts: exitAt,
          label: `Exited — ${exitReason ?? "unknown"}`,
          detail: pnlR != null
            ? `${pnlR >= 0 ? "+" : ""}${fmtNum(pnlR, 2)}R${barsInTrade != null ? ` · ${barsInTrade} bars` : ""}`
            : null,
          active: true,
        }
      : activatedAt
      ? {
          ts: null,
          label: "In trade…",
          detail: barsInTrade != null ? `${barsInTrade} bars held` : null,
          active: false,
        }
      : null,
  ].filter(Boolean) as { ts: string | null; label: string; detail: string | null; active: boolean }[];

  return (
    <div className="flex flex-col gap-1.5">
      {events.map((ev, i) => (
        <div key={i} className="flex items-start gap-2 text-[0.55rem]">
          <span style={{ color: ev.active ? "var(--text-secondary)" : "var(--text-muted)" }}>
            {ev.active ? "◉" : "○"}
          </span>
          <div className="flex flex-col gap-0.5">
            <span className="font-data"
              style={{ color: ev.active ? "var(--text-primary)" : "var(--text-muted)" }}>
              {ev.ts ? fmtTimeHMS(ev.ts) + "  " : ""}{ev.label}
            </span>
            {ev.detail && (
              <span className="text-[0.48rem] text-[var(--text-muted)]">{ev.detail}</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

export function SignalDetailPanel({
  signalId,
  onClose,
}: {
  signalId: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [rawOpen, setRawOpen] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetchJson<Record<string, unknown>>(`${getApiBase()}/api/signals/detail/${signalId}`)
      .then(d => setDetail(d))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [signalId]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const tier = detail?.signal_tier as string | undefined;
  const regime = detail?.hmm_regime_at_fire as number | null | undefined;
  const isLong = detail?.direction === 1;
  const barsAgo = detail?.bars_in_trade as number | null;

  return (
    <div className="flex flex-col border-l border-[var(--border-subtle)] overflow-y-auto shrink-0"
      style={{ width: "300px", background: "var(--bg-surface)" }}>
      {/* Close bar */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-subtle)]">
        <span className="text-[0.58rem] font-bold uppercase tracking-widest text-[var(--text-secondary)]">
          Signal Detail
        </span>
        <button onClick={onClose} aria-label="Close"
          className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
          <X size={14} />
        </button>
      </div>

      {loading && (
        <div className="p-4 text-[0.6rem] text-[var(--text-muted)] italic">Loading…</div>
      )}
      {!loading && !detail && (
        <div className="p-4 text-[0.6rem] text-[var(--red)] italic">Signal not found</div>
      )}
      {!loading && detail && (
        <div className="p-3 flex flex-col gap-0.5 text-[0.6rem]">

          {/* A. Header */}
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-base font-bold font-data"
                style={{ color: isLong ? "var(--green)" : "var(--red)" }}>
                {detail.symbol as string}
              </span>
              {isLong
                ? <TrendingUp size={14} style={{ color: "var(--green)" }} />
                : <TrendingDown size={14} style={{ color: "var(--red)" }} />}
              {tier && (
                <span className="text-[0.5rem] font-bold px-1.5 py-0.5 rounded"
                  style={{
                    color: TIER_COLORS[tier] ?? "var(--text-muted)",
                    border: `1px solid ${TIER_COLORS[tier] ?? "var(--border-subtle)"}`,
                  }}>
                  {tier.toUpperCase()}
                </span>
              )}
              {regime != null && (
                <span className="text-[0.5rem] font-bold px-1.5 py-0.5 rounded"
                  style={{
                    color: REGIME_COLORS[regime] ?? "var(--text-muted)",
                    border: `1px solid ${REGIME_COLORS[regime] ?? "var(--border-subtle)"}`,
                  }}>
                  {REGIME_LABELS[regime] ?? `R${regime}`}
                </span>
              )}
              <span className="text-[0.5rem] text-[var(--text-muted)]">{detail.timeframe as string}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[0.55rem] text-[var(--text-secondary)]">
                {(detail.setup_plugin as string)?.replace(/^(trad_|ind_|smc_)/, "")}
              </span>
              <span className="text-[0.52rem] font-data font-bold"
                style={{ color: (detail.cis_score as number ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                CIS {detail.cis_score != null
                  ? ((detail.cis_score as number) >= 0 ? "+" : "") + fmtNum(detail.cis_score as number, 2)
                  : "—"}
              </span>
            </div>
            {detail.signal_computed_at && (
              <span className="text-[0.48rem] text-[var(--text-muted)]">
                Fired {fmtTimeHMS(detail.signal_computed_at as string)}
                {barsAgo != null ? ` · ${barsAgo} bars ago` : ""}
              </span>
            )}
          </div>

          {/* B. Price Ladder */}
          <SectionLabel label="Trade Anatomy" />
          <PriceLadder detail={detail} />

          {/* C. CIS Buckets */}
          <SectionLabel label="CIS Breakdown" />
          <CISBuckets buckets={detail.bucket_scores as Record<string, number> | null} />

          {/* D. Setup Edge */}
          <SectionLabel label="Setup Edge" />
          <SetupEdge detail={detail} />

          {/* E. Capture Bar (resolved only) */}
          {detail.outcome && (
            <>
              <SectionLabel label="Capture Efficiency" />
              <CaptureBar detail={detail} />
            </>
          )}

          {/* F. Lifecycle Timeline */}
          <SectionLabel label="Lifecycle" />
          <Timeline detail={detail} />

          {/* G. Raw data (collapsible) */}
          <button
            onClick={() => setRawOpen(v => !v)}
            className="flex items-center gap-1 mt-3 text-[0.48rem] text-[var(--text-muted)] hover:text-[var(--text-secondary)]">
            {rawOpen ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
            Raw data
          </button>
          {rawOpen && (
            <pre className="text-[0.48rem] font-data text-[var(--text-muted)] whitespace-pre-wrap mt-1 overflow-x-auto">
              {JSON.stringify(detail, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Remove inline SignalDetailPanel from signal-ledger.tsx and import the new one**

In `dashboard/src/components/signals/signal-ledger.tsx`:
- Delete the entire `SignalDetailPanel` function (from its comment down to the closing `}`)
- Add import at the top: `import { SignalDetailPanel } from "./signal-detail-panel";`

- [ ] **Step 3: Verify TypeScript compiles**

```bash
cd dashboard && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/components/signals/signal-detail-panel.tsx dashboard/src/components/signals/signal-ledger.tsx
git commit -m "feat(dashboard): redesign detail panel — price ladder, CIS bars, capture efficiency, timeline"
```

---

## Task 16: Run the app, verify visually, fix any runtime issues

- [ ] **Step 1: Start the API**

```bash
uvicorn src.api.main:app --reload --port 8000
```

Verify new endpoints return data:
```bash
curl -s http://localhost:8000/api/signals/heatmap | python3 -m json.tool | head -30
curl -s http://localhost:8000/api/signals/edge-series | python3 -m json.tool | head -20
curl -s http://localhost:8000/api/signals/intraday-heatmap | python3 -m json.tool | head -20
curl -s "http://localhost:8000/api/signals/stats" | python3 -m json.tool | grep -A5 "recent_outcomes"
```

Expected: valid JSON with data, `recent_outcomes` array in stats

- [ ] **Step 2: Start the dashboard**

```bash
cd dashboard && npm run dev
```

Open `http://localhost:3000/signals` — verify:
- [ ] Live signal cards appear (or empty state if no active signals)
- [ ] Edge intelligence strip shows heat map and sparkline
- [ ] Intraday heat map shows colored grid
- [ ] Ledger rows show regime dot, R:R column, Exit badge, Age/Cap column
- [ ] Command strip shows skew pill and streak bar
- [ ] Regime filter pills appear in filter bar
- [ ] Clicking a ledger row opens the redesigned detail panel (6 sections)
- [ ] Price ladder renders correctly
- [ ] CIS bucket bars render for signals with bucket_scores
- [ ] Capture bar renders for resolved signals

- [ ] **Step 3: Run full unit test suite**

```bash
.venv/bin/pytest tests/unit/ -q
```

Expected: all PASS

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "fix: address any runtime issues found during visual verification"
```

---

## Task 17: Done-Coding SOP

- [ ] Run code-simplifier on changed files
- [ ] Run `/review` (peer code review)
- [ ] Run `pytest tests/unit/ -q` — green
- [ ] Commit on feature branch (if on one)
- [ ] `git checkout main && git merge --ff-only <branch>`
- [ ] `git branch -d <branch>` and `git worktree prune`
- [ ] `git push origin main`
