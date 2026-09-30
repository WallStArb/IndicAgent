"""Integration test: services/ic_measure.py on a real TimescaleDB (phase 186 plan 14).

Seeds 8 symbols x 120 NYSE sessions of 1d bars, feature_vectors rows (one feature built to
predict the next-open return, one noise, regime_volatility labels), the month digests phase 185
would write, and one legacy-scope row in the legacy feature_ic_scores table. Then proves:
(1) rows land in feature_ic_scores_v2 with both fresh scopes, every training_window_end before
oos_start, provenance completed, no NaN stored, the predictive feature's IC positive;
(2) a rerun skips every unit; (3) one revised bar (and its new month digest) replaces the units
atomically and supersedes the previous keys; (4) the legacy table is untouched; (5) monitoring
with members writes one row per window; (6) every chunk of v2 is compressed after the runs.

Runs against indicagent_test (migrations replayed by conftest, so 413, 414 and 415 are exercised).

Run: pytest tests/integration/test_ic_measure.py -m integration
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import numpy as np
import psycopg
import pytest

from services.ic_measure import IcMeasure, UnitOutcome
from src.core.market_calendar import get_market_calendar

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_DSN = "postgresql://postgres:postgres@localhost:5432/indicagent_test"
_OOS = "2025-12-24T05:15:00Z"
_N_SESSIONS = 120
_N_SYMBOLS = 8
_PREDICTIVE = "momentum_z_fast"
_NOISE = "hurst"

# APR values the writer needs that the replayed migrations do not seed into the test database
# (key, type, value); seeded with ON CONFLICT DO NOTHING and removed again when this test inserted them.
_APR = [
    ("alpha.ic.subsample_min_stride", "int", "5"),
    ("alpha.ic.bootstrap_block_size.1d", "int", "10"),
    ("alpha.ic.bootstrap_resamples", "int", "200"),
    ("alpha.ic.bootstrap_seed", "int", "42"),
    ("alpha.ic.fdr_alpha", "float", "0.05"),
    ("alpha.ic.min_reliable_n", "int", "100"),
    ("alpha.ic.hac_max_lag", "int", "3"),
    ("alpha.ic.feature_block_columns", "int", "32"),
    ("alpha.validation.oos_start", "string", _OOS),
    ("infra.ic_measure.fetch_chunk_rows", "int", "200000"),
]


def _sessions() -> list[date]:
    calendar = get_market_calendar()
    day, out = date(2024, 1, 2), []
    while len(out) < _N_SESSIONS:
        if calendar.is_trading_day("NYSE", day):
            out.append(day)
        day += timedelta(days=1)
    return out


def _utc(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _args(**overrides: object) -> argparse.Namespace:
    fields: dict[str, object] = dict(
        tf=["1d"],
        jobs=["proposer", "regime_volatility"],
        members=[],
        symbols=None,
        start=None,
        feature_table="feature_vectors",
        dry_run=False,
        allow_absent_digests=False,
    )
    fields.update(overrides)
    return argparse.Namespace(**fields)


class TestIcMeasureIntegration:
    @pytest.fixture(scope="class")
    def world(self):
        tag = uuid4().hex[:6].upper()
        symbols = [f"ICM{tag}{i}" for i in range(_N_SYMBOLS)]
        sessions = _sessions()
        rng = np.random.default_rng(11)
        opens = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (_N_SESSIONS, _N_SYMBOLS)), axis=0))
        target = np.full_like(opens, np.nan)
        target[:-2] = np.log(opens[2:] / opens[1:-1])  # horizon 1: entry T+1 open, exit T+2 open
        predictive = np.nan_to_num(target, nan=0.0) * 50 + rng.normal(0, 0.3, opens.shape)
        noise = rng.normal(size=opens.shape)
        inserted_apr: list[str] = []
        with psycopg.connect(_DSN, autocommit=True) as conn:
            for key, value_type, value in _APR:
                got = conn.execute(
                    "INSERT INTO config_schema (config_key, value_type, default_value, description) "
                    "VALUES (%s, %s, %s, 'ic_measure integration test seed') "
                    "ON CONFLICT (config_key) DO NOTHING RETURNING config_key",
                    (key, value_type, value),
                ).fetchone()
                conn.execute(
                    "INSERT INTO config_state (config_key, config_value, version) VALUES (%s, %s, 1) "
                    "ON CONFLICT (config_key) DO NOTHING",
                    (key, value),
                )
                if got:
                    inserted_apr.append(key)
            for symbol in symbols:
                conn.execute(
                    "INSERT INTO instruments (symbol, base, compute_eligible_1d) VALUES (%s, %s, true)",
                    (symbol, symbol),
                )
            for j, symbol in enumerate(symbols):
                for i, day in enumerate(sessions):
                    o = float(opens[i, j])
                    conn.execute(
                        "INSERT INTO market_data_ohlcv (timestamp, symbol, timeframe, open, high, "
                        "low, close, volume) VALUES (%s, %s, '1d', %s, %s, %s, %s, 1000)",
                        (_utc(day), symbol, o, o * 1.01, o * 0.99, o * 1.001),
                    )
                    conn.execute(
                        "INSERT INTO feature_vectors (symbol, tf, bar_ts, pipeline_version, "
                        f"{_PREDICTIVE}, {_NOISE}, regime_volatility) "
                        "VALUES (%s, '1d', %s, 'test', %s, %s, %s)",
                        (
                            symbol,
                            _utc(day),
                            float(predictive[i, j]),
                            float(noise[i, j]),
                            "low" if i % 2 == 0 else "high",
                        ),
                    )
            legacy_before = self._legacy(conn)
            conn.execute(
                "INSERT INTO feature_ic_scores (feature_name, vector_domain, symbol, tf, regime, "
                "lookahead_bars, training_window_end, is_pooled, n_independent, reliable, ic_value, "
                "regime_label_source, regime_scope) VALUES (%s, 'quant', 'POOLED', '1d', '_pooled', 1, "
                "'2025-12-24 05:15:00+00', true, 10, true, 0.123, 'none', 'pooled')",
                (f"legacy_{tag}",),
            )
        self._seed_digests(symbols, sessions, revision=0)
        yield {
            "tag": tag,
            "symbols": symbols,
            "sessions": sessions,
            "legacy_before": legacy_before,
            "legacy_row": f"legacy_{tag}",
        }
        with psycopg.connect(_DSN, autocommit=True) as conn:
            conn.execute(
                "DELETE FROM feature_ic_scores WHERE feature_name = %s", (f"legacy_{tag}",)
            )
            conn.execute("DELETE FROM feature_ic_scores_v2")
            conn.execute("DELETE FROM feature_vectors WHERE symbol = ANY(%s)", (symbols,))
            conn.execute("DELETE FROM market_data_ohlcv WHERE symbol = ANY(%s)", (symbols,))
            conn.execute("DELETE FROM instruments WHERE symbol = ANY(%s)", (symbols,))
            for key in inserted_apr:
                conn.execute("DELETE FROM config_state WHERE config_key = %s", (key,))
                conn.execute("DELETE FROM config_schema WHERE config_key = %s", (key,))

    @staticmethod
    def _legacy(conn: psycopg.Connection) -> tuple:
        return conn.execute(
            "SELECT count(*), coalesce(sum(hashtext(feature_name || symbol || tf || regime || "
            "lookahead_bars || coalesce(ic_value::text, ''))::numeric), 0) FROM feature_ic_scores"
        ).fetchone()

    @staticmethod
    def _seed_digests(
        symbols: list[str], sessions: list[date], revision: int, only: str | None = None
    ) -> None:
        months = sorted({(d.year, d.month) for d in sessions})
        with psycopg.connect(_DSN, autocommit=True) as conn:
            for symbol in symbols:
                if only and symbol != only:
                    continue
                for year, month in months:
                    start = datetime(year, month, 1, tzinfo=UTC)
                    end = (start + timedelta(days=32)).replace(day=1)
                    conn.execute(
                        "INSERT INTO bar_content_digest (symbol, timeframe, range_start, range_end, "
                        "digest, algorithm, rule_version, n_rows) "
                        "VALUES (%s, '1d', %s, %s, %s, 'sha256-bars-v1', 'test', 1)",
                        (symbol, start, end, f"{symbol}-{year}-{month}-r{revision}"),
                    )

    @staticmethod
    def _run(world: dict, **overrides: object) -> list[UnitOutcome]:
        runner = IcMeasure(_args(symbols=world["symbols"], **overrides), _DSN)
        runner.run()
        assert runner.failures == [], runner.failures
        return runner.outcomes

    @staticmethod
    def _scalar(query: str, params: tuple = ()) -> object:
        with psycopg.connect(_DSN) as conn:
            return conn.execute(query, params).fetchone()[0]

    def test_case_1_rows_scopes_bound_and_provenance(self, world: dict) -> None:
        outcomes = self._run(world)
        assert outcomes and {o.status for o in outcomes} == {"loaded"}
        scopes = {
            r[0]
            for r in psycopg.connect(_DSN)
            .execute("SELECT DISTINCT regime_scope FROM feature_ic_scores_v2")
            .fetchall()
        }
        assert scopes == {"unstratified", "regime_volatility"}
        assert (
            self._scalar(
                "SELECT count(*) FROM feature_ic_scores_v2 WHERE training_window_end >= %s", (_OOS,)
            )
            == 0
        )
        assert (
            self._scalar(
                "SELECT count(*) FROM feature_ic_scores_v2 WHERE ic_value = 'NaN'::float8 "
                "OR p_value = 'NaN'::float8"
            )
            == 0
        )
        assert self._scalar(
            "SELECT count(*) FROM provenance_batch WHERE writer LIKE 'ic_measure.%%' "
            "AND status = 'completed' AND symbols @> %s::text[]",
            (world["symbols"],),
        ) == len(outcomes)
        ic = self._scalar(
            "SELECT ic_value FROM feature_ic_scores_v2 WHERE feature_name = %s AND "
            "regime_scope = 'unstratified' AND lookahead_bars = 1",
            (_PREDICTIVE,),
        )
        assert ic is not None and ic > 0.3, ic
        noise = self._scalar(
            "SELECT ic_value FROM feature_ic_scores_v2 WHERE feature_name = %s AND "
            "regime_scope = 'unstratified' AND lookahead_bars = 1",
            (_NOISE,),
        )
        assert abs(noise) < 0.2

    def test_case_2_rerun_skips_every_unit(self, world: dict) -> None:
        rows = self._scalar("SELECT count(*) FROM feature_ic_scores_v2")
        batches = self._scalar(
            "SELECT count(*) FROM provenance_batch WHERE writer LIKE 'ic_measure.%%'"
        )
        outcomes = self._run(world)
        assert {o.status for o in outcomes} == {"skipped"}
        assert self._scalar("SELECT count(*) FROM feature_ic_scores_v2") == rows
        assert (
            self._scalar("SELECT count(*) FROM provenance_batch WHERE writer LIKE 'ic_measure.%%'")
            == batches
        )

    def test_case_3_a_revised_bar_replaces_the_units(self, world: dict) -> None:
        rows = self._scalar("SELECT count(*) FROM feature_ic_scores_v2")
        before = self._scalar(
            "SELECT ic_value FROM feature_ic_scores_v2 WHERE feature_name = %s AND "
            "regime_scope = 'unstratified' AND lookahead_bars = 1",
            (_PREDICTIVE,),
        )
        revised = world["symbols"][3]
        mid = _utc(world["sessions"][60])
        with psycopg.connect(_DSN, autocommit=True) as conn:
            conn.execute(
                "UPDATE market_data_ohlcv SET open = open * 1.08 WHERE symbol = %s "
                "AND timeframe = '1d' AND timestamp = %s",
                (revised, mid),
            )
        self._seed_digests(world["symbols"], world["sessions"], revision=1, only=revised)
        outcomes = self._run(world)
        assert {o.status for o in outcomes} == {"replaced"}
        assert self._scalar("SELECT count(*) FROM feature_ic_scores_v2") == rows
        after = self._scalar(
            "SELECT ic_value FROM feature_ic_scores_v2 WHERE feature_name = %s AND "
            "regime_scope = 'unstratified' AND lookahead_bars = 1",
            (_PREDICTIVE,),
        )
        assert after != before
        statuses = dict(
            psycopg.connect(_DSN)
            .execute(
                "SELECT status, count(*) FROM provenance_batch WHERE writer LIKE 'ic_measure.%%' "
                "AND symbols @> %s::text[] GROUP BY status",
                (world["symbols"],),
            )
            .fetchall()
        )
        assert statuses["superseded"] == statuses["completed"] == len(outcomes)

    def test_case_4_legacy_table_untouched(self, world: dict) -> None:
        with psycopg.connect(_DSN) as conn:
            count, checksum = self._legacy(conn)
            assert conn.execute(
                "SELECT ic_value FROM feature_ic_scores WHERE feature_name = %s",
                (world["legacy_row"],),
            ).fetchone() == (0.123,)
        before_count, before_checksum = world["legacy_before"]
        assert (
            count == before_count + 1
        )  # exactly the one seeded row, nothing written by the writer
        assert checksum != before_checksum  # the seeded row's own contribution only

    def test_case_5_monitoring_one_row_per_window(self, world: dict) -> None:
        outcomes = self._run(world, jobs=["monitoring"], members=[_PREDICTIVE, _NOISE])
        assert [o.status for o in outcomes] == ["loaded"]
        assert (
            self._scalar(
                "SELECT count(*) FROM feature_ic_scores_v2 WHERE regime_scope = 'member_window'"
            )
            == 4
        )  # 120 sessions in windows of 63: 2 windows x 2 members
        assert (
            self._scalar(
                "SELECT count(DISTINCT training_window_end) FROM feature_ic_scores_v2 "
                "WHERE regime_scope = 'member_window' AND feature_name = %s",
                (_PREDICTIVE,),
            )
            == 2
        )

    def test_case_6_every_chunk_is_compressed(self, world: dict) -> None:
        assert (
            self._scalar(
                "SELECT count(*) FROM timescaledb_information.chunks "
                "WHERE hypertable_name = 'feature_ic_scores_v2' AND NOT is_compressed"
            )
            == 0
        )
        assert (
            self._scalar(
                "SELECT count(*) FROM timescaledb_information.chunks "
                "WHERE hypertable_name = 'feature_ic_scores_v2'"
            )
            >= 1
        )
